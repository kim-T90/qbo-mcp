"""qbo_refund_receipt tool — manage QuickBooks Online refund receipts."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from fastmcp import Context
from fastmcp.exceptions import ToolError

from quickbooks_mcp.errors import format_qbo_error
from quickbooks_mcp.models import ERROR_SHAPE_HINT, IDS_QUERY_RULES, PREVIEW_HINT, SEARCH_EXAMPLES
from quickbooks_mcp.tools._base import (
    destructive_preview,
    tx_create,
    tx_delete,
    tx_get,
    tx_list,
    tx_search,
    tx_update,
    validate_extra,
)

if TYPE_CHECKING:
    from fastmcp import FastMCP

TX_TYPE = "refund_receipt"
ENTITY_TYPE = "RefundReceipt"

_TOOL_DESCRIPTION = (
    f"{PREVIEW_HINT} "
    "Manage QuickBooks Online refund receipts. "
    "Create, list, update, delete, or search. "
    "create requires customer_ref. "
    'line_items: [{"amount": 100.0, "description": "..."}] — '
    "see qbo_help(topic='line_items', entity='refund_receipt') for full schema. "
    f"Search uses IDS query syntax — {IDS_QUERY_RULES} "
    f"{SEARCH_EXAMPLES['refund_receipt']} "
    f"{ERROR_SHAPE_HINT}"
)


def register(mcp: FastMCP) -> None:
    """Register the qbo_refund_receipt tool on *mcp*."""
    from quickbooks_mcp.server import get_client  # noqa: PLC0415

    @mcp.tool(
        name="qbo_refund_receipt",
        description=_TOOL_DESCRIPTION,
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    async def qbo_refund_receipt(
        ctx: Context,
        operation: Literal["list", "get", "create", "update", "delete", "search"],
        id: str | None = None,
        customer_ref: str | None = None,
        line_items: list[dict] | None = None,
        memo: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        query: str | None = None,
        max_results: int = 20,
        offset: int = 0,
        extra: dict | None = None,
        preview: bool = True,
        response_format: Literal["json", "markdown"] = "json",
    ) -> dict | str:
        """Create, read, update, delete, or search QuickBooks Online refund receipts.

        Args:
            operation: Action to perform.
            id: QBO entity ID (numeric string, e.g. '42') — required
                for get, update, delete.
            customer_ref: Customer ID (numeric string from
                qbo_customer list) — required for create.
            line_items: List of line item dicts. Each item supports:
                amount (float), description (str), item_ref (str — Item ID),
                detail_type (str — defaults to 'SalesItemLineDetail').
            memo: Private note on the refund receipt.
            start_date: Filter list by TxnDate >= start_date (YYYY-MM-DD).
            end_date: Filter list by TxnDate <= end_date (YYYY-MM-DD).
            query: IDS WHERE clause for search.
            max_results: Maximum records to return for list (default 20).
            offset: Zero-based start offset for list pagination (default 0).
            extra: Optional dict of additional QBO fields.
            preview: Safety gate for delete. True (default) returns a
                preview; set preview=False to proceed.
            response_format: 'json' (default) or 'markdown'.
        """
        client = get_client(ctx)
        extra_dict = validate_extra(extra)

        if operation in ("get", "update", "delete") and not id:
            raise ToolError(f"'id' is required for operation='{operation}'.")
        if operation == "create" and not customer_ref:
            raise ToolError(
                "'customer_ref' is required when creating a refund_receipt. "
                "Use qbo_customer(operation='list') to find customer IDs."
            )
        if operation == "search" and not query:
            raise ToolError("'query' is required for operation='search'.")

        try:
            if operation == "list":
                return await tx_list(
                    client,
                    TX_TYPE,
                    ENTITY_TYPE,
                    start_date,
                    end_date,
                    max_results,
                    offset,
                    response_format,
                )
            elif operation == "get":
                return await tx_get(client, TX_TYPE, ENTITY_TYPE, id, response_format)
            elif operation == "create":
                return await tx_create(
                    client,
                    TX_TYPE,
                    ENTITY_TYPE,
                    customer_ref,
                    None,
                    line_items,
                    memo,
                    None,  # RefundReceipt has no DueDate
                    extra_dict,
                    response_format,
                )
            elif operation == "update":
                return await tx_update(
                    client,
                    TX_TYPE,
                    ENTITY_TYPE,
                    id,
                    customer_ref,
                    None,
                    line_items,
                    memo,
                    None,  # RefundReceipt has no DueDate
                    extra_dict,
                    response_format,
                )
            elif operation == "delete":
                if preview:
                    return await destructive_preview(
                        client,
                        TX_TYPE,
                        ENTITY_TYPE,
                        "delete",
                        id,
                    )
                return await tx_delete(client, TX_TYPE, ENTITY_TYPE, id, response_format)
            elif operation == "search":
                return await tx_search(client, ENTITY_TYPE, query, response_format)
        except ToolError:
            raise
        except Exception as exc:
            return format_qbo_error(exc, operation, ENTITY_TYPE)

        raise ToolError(f"Unhandled operation: {operation}")  # pragma: no cover
