"""qbo_bulk tool — bulk operations: CDC, batch, count."""

from __future__ import annotations

import importlib
import logging
from typing import TYPE_CHECKING, Literal

from fastmcp import Context
from fastmcp.exceptions import ToolError

from quickbooks_mcp.converters import qbo_to_snake
from quickbooks_mcp.formatting import format_response
from quickbooks_mcp.models import (  # noqa: F401 (PREVIEW_HINT used in description)
    ERROR_SHAPE_HINT,
    PREVIEW_HINT,
)

if TYPE_CHECKING:
    from fastmcp import FastMCP

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool description
# ---------------------------------------------------------------------------

_TOOL_DESCRIPTION = (
    f"{PREVIEW_HINT} "
    "Bulk operations for QuickBooks Online. "
    "Operations: cdc (Change Data Capture — fetch entities modified since a datetime), "
    "batch (execute up to 30 create/update/delete operations in sequence), "
    "count (count entities matching an optional WHERE clause). "
    f"{ERROR_SHAPE_HINT}"
)

# ---------------------------------------------------------------------------
# Entity import registry
# ---------------------------------------------------------------------------

_ENTITY_IMPORTS: dict[str, tuple[str, str]] = {
    "Invoice": ("quickbooks.objects.invoice", "Invoice"),
    "Bill": ("quickbooks.objects.bill", "Bill"),
    "BillPayment": ("quickbooks.objects.billpayment", "BillPayment"),
    "Payment": ("quickbooks.objects.payment", "Payment"),
    "Deposit": ("quickbooks.objects.deposit", "Deposit"),
    "Transfer": ("quickbooks.objects.transfer", "Transfer"),
    "JournalEntry": ("quickbooks.objects.journalentry", "JournalEntry"),
    "Purchase": ("quickbooks.objects.purchase", "Purchase"),
    "Estimate": ("quickbooks.objects.estimate", "Estimate"),
    "CreditMemo": ("quickbooks.objects.creditmemo", "CreditMemo"),
    "SalesReceipt": ("quickbooks.objects.salesreceipt", "SalesReceipt"),
    "RefundReceipt": ("quickbooks.objects.refundreceipt", "RefundReceipt"),
    "VendorCredit": ("quickbooks.objects.vendorcredit", "VendorCredit"),
    "Customer": ("quickbooks.objects.customer", "Customer"),
    "Vendor": ("quickbooks.objects.vendor", "Vendor"),
    "Employee": ("quickbooks.objects.employee", "Employee"),
    "Account": ("quickbooks.objects.account", "Account"),
    "Item": ("quickbooks.objects.item", "Item"),
}

_BATCH_MAX = 30


def _get_entity_class(entity_type: str):  # type: ignore[return]
    """Lazily import and return the python-quickbooks class for *entity_type*."""
    entry = _ENTITY_IMPORTS.get(entity_type)
    if entry is None:
        raise ToolError(
            f"Unknown entity_type {entity_type!r}. Supported: {sorted(_ENTITY_IMPORTS.keys())}"
        )
    module_path, class_name = entry
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


# ---------------------------------------------------------------------------
# CDC helper
# ---------------------------------------------------------------------------


async def _cdc(
    client, entity_list: list[str], changed_since: str, response_format: str
) -> dict | str:
    if not entity_list:
        raise ToolError("entities must contain at least one entity name.")

    def _fetch():
        from quickbooks.cdc import change_data_capture

        return change_data_capture(entity_list, changed_since, qb=client.qb_client)

    result = await client.execute(_fetch)

    converted: dict = {}
    for entity_name, objects in (result or {}).items():
        converted[entity_name] = [
            qbo_to_snake(obj.to_dict()) if hasattr(obj, "to_dict") else qbo_to_snake(obj)
            for obj in objects
        ]

    return format_response(converted, "cdc", "Mixed", response_format=response_format)


# ---------------------------------------------------------------------------
# Batch helper
# ---------------------------------------------------------------------------


async def _batch(client, ops: list[dict], response_format: str) -> dict | str:
    if len(ops) > _BATCH_MAX:
        raise ToolError(f"Maximum {_BATCH_MAX} operations per batch, got {len(ops)}.")

    succeeded: list[dict] = []
    failed: list[dict] = []

    for idx, op in enumerate(ops):
        op_type = op.get("operation")
        entity_type = op.get("entity_type")
        data = op.get("data", {})
        obj_id = op.get("id")

        try:
            if op_type not in ("create", "update", "delete"):
                raise ToolError(
                    f"operation must be 'create', 'update', or 'delete', got {op_type!r}."
                )
            if not entity_type:
                raise ToolError("entity_type is required for each batch operation.")

            qb = client.qb_client
            entity_cls = _get_entity_class(entity_type)

            def _execute_op(
                op_type=op_type,
                entity_cls=entity_cls,
                data=data,
                obj_id=obj_id,
                idx=idx,
                qb=qb,
            ):
                if op_type == "create":
                    obj = entity_cls()
                    for k, v in data.items():
                        setattr(obj, k, v)
                    obj.save(qb=qb)
                    return getattr(obj, "Id", None)

                elif op_type == "update":
                    if not obj_id:
                        raise ToolError(f"id is required for update at index {idx}.")
                    obj = entity_cls.get(obj_id, qb=qb)
                    for k, v in data.items():
                        setattr(obj, k, v)
                    obj.save(qb=qb)
                    return getattr(obj, "Id", obj_id)

                else:  # delete
                    if not obj_id:
                        raise ToolError(f"id is required for delete at index {idx}.")
                    obj = entity_cls.get(obj_id, qb=qb)
                    obj.delete(qb=qb)
                    return obj_id

            result_id = await client.execute(_execute_op)
            succeeded.append(
                {
                    "index": idx,
                    "operation": op_type,
                    "entity_type": entity_type,
                    "id": result_id,
                }
            )

        except Exception as exc:
            failed.append(
                {
                    "index": idx,
                    "operation": op_type,
                    "entity_type": entity_type,
                    "error": str(exc),
                }
            )

    total = len(ops)
    if not failed:
        status = "ok"
    elif succeeded:
        status = "partial"
    else:
        status = "error"

    summary_payload = {
        "status": status,
        "succeeded": succeeded,
        "failed": failed,
        "summary": f"{len(succeeded)} of {total} operations succeeded",
    }

    if response_format == "markdown":
        lines = [
            f"## Batch Result: {status.upper()}",
            f"**{len(succeeded)} of {total} operations succeeded**",
        ]
        if succeeded:
            lines.append("\n### Succeeded")
            for s in succeeded:
                lines.append(f"- [{s['index']}] {s['operation']} {s['entity_type']} id={s['id']}")
        if failed:
            lines.append("\n### Failed")
            for f_ in failed:
                lines.append(
                    f"- [{f_['index']}] {f_['operation']} {f_['entity_type']}: {f_['error']}"
                )
        return "\n".join(lines)

    return summary_payload


# ---------------------------------------------------------------------------
# Batch preview helper
# ---------------------------------------------------------------------------


def _batch_preview(ops: list[dict]) -> dict:
    """Validate and summarise a batch without executing any operations."""
    if len(ops) > _BATCH_MAX:
        raise ToolError(f"Maximum {_BATCH_MAX} operations per batch, got {len(ops)}.")

    errors: list[dict] = []
    summary: list[dict] = []

    for idx, op in enumerate(ops):
        op_type = op.get("operation")
        entity_type = op.get("entity_type")
        obj_id = op.get("id")

        # Validate operation value
        if op_type not in ("create", "update", "delete"):
            errors.append(
                {
                    "index": idx,
                    "error": f"operation must be 'create', 'update', or 'delete', got {op_type!r}.",
                }
            )
            continue

        # Validate entity_type is present and known
        if not entity_type:
            errors.append({"index": idx, "error": "entity_type is required."})
            continue

        if entity_type not in _ENTITY_IMPORTS:
            errors.append(
                {
                    "index": idx,
                    "error": (
                        f"Unknown entity_type {entity_type!r}. "
                        f"Supported: {sorted(_ENTITY_IMPORTS.keys())}"
                    ),
                }
            )
            continue

        # Validate id for update/delete
        if op_type in ("update", "delete") and not obj_id:
            errors.append({"index": idx, "error": f"id is required for {op_type} at index {idx}."})
            continue

        summary.append(
            {
                "index": idx,
                "operation": op_type,
                "entity_type": entity_type,
                "id": obj_id,
            }
        )

    result: dict = {
        "status": "preview",
        "operation": "batch",
        "operations_count": len(ops),
        "summary": summary,
        "warning": (
            f"This will execute {len(ops)} operations. Call again with preview=False to proceed."
        ),
    }
    if errors:
        result["validation_errors"] = errors
    return result


# ---------------------------------------------------------------------------
# Count helper
# ---------------------------------------------------------------------------


async def _count(
    client, entity_type: str, query_str: str | None, response_format: str
) -> dict | str:
    count_query = f"SELECT COUNT(*) FROM {entity_type}"
    if query_str:
        count_query += f" WHERE {query_str}"

    def _fetch():
        return client.qb_client.query(count_query)

    result = await client.execute(_fetch)

    if isinstance(result, dict):
        count = result.get("totalCount", 0)
    elif isinstance(result, list):
        count = len(result)
    else:
        count = 0

    return format_response(
        {"entity_type": entity_type, "count": count, "query": count_query},
        "count",
        entity_type,
        response_format=response_format,
    )


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register(mcp: FastMCP) -> None:
    """Register the qbo_bulk tool on *mcp*."""

    @mcp.tool(
        name="qbo_bulk",
        description=_TOOL_DESCRIPTION,
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    async def qbo_bulk(
        ctx: Context,
        operation: Literal["cdc", "batch", "count"],
        entities: list[str] | None = None,
        changed_since: str | None = None,
        operations: list[dict] | None = None,
        entity_type: str | None = None,
        query: str | None = None,
        preview: bool = True,
        response_format: Literal["json", "markdown"] = "json",
    ) -> dict | str:
        """Bulk operations for QuickBooks Online.

        Operations:
        - cdc: Change Data Capture — fetch all entities modified since a given
          datetime. Requires entities (list of entity names, e.g.
          ["Invoice", "Customer", "Payment"]) and changed_since (ISO 8601 datetime
          string, e.g. "2024-01-01T00:00:00"). Returns a dict keyed by entity type.
        - batch: Execute up to 30 create/update/delete operations in sequence.
          Requires operations — a list of dicts, each with keys:
            operation ("create"|"update"|"delete"),
            entity_type (e.g. "Invoice", "Customer"),
            data (dict of fields to set; for create/update),
            id (required for update/delete).
          Returns per-operation success/failure with partial-success support.
          When preview=True (default), returns a summary of what would happen
          without executing. Call again with preview=False to proceed.
        - count: Count entities matching an optional WHERE clause. Requires
          entity_type (singular QBO entity name, e.g. "Invoice"). Optional query
          is an IDS WHERE clause (e.g. "TotalAmt > '100.00'").

        Args:
            preview: Safety gate for the batch operation. When True (default),
                validates and returns a summary instead of executing. Call again
                with preview=False to proceed. Has no effect on cdc or count.
        """

        from quickbooks_mcp.server import get_client

        client = get_client(ctx)

        # ------------------------------------------------------------------
        # cdc
        # ------------------------------------------------------------------
        if operation == "cdc":
            if not entities:
                raise ToolError("entities is required for operation='cdc'.")
            if not changed_since:
                raise ToolError("changed_since is required for operation='cdc'.")
            return await _cdc(client, entities, changed_since, response_format)

        # ------------------------------------------------------------------
        # batch
        # ------------------------------------------------------------------
        if operation == "batch":
            if not operations:
                raise ToolError("operations is required for operation='batch'.")
            if preview:
                return _batch_preview(operations)
            return await _batch(client, operations, response_format)

        # ------------------------------------------------------------------
        # count
        # ------------------------------------------------------------------
        if operation == "count":
            if not entity_type:
                raise ToolError("entity_type is required for operation='count'.")
            return await _count(client, entity_type, query, response_format)

        # Should be unreachable due to Literal type constraint
        raise ToolError(f"Unknown operation: {operation!r}.")  # pragma: no cover
