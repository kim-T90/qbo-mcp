"""qbo_purchase tool — manage QuickBooks Online purchases."""

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

_TX_TYPE = "purchase"
_ENTITY_TYPE = "Purchase"

_TOOL_DESCRIPTION = (
    f"{PREVIEW_HINT} "
    "Manage QuickBooks Online purchases (direct expenses paid by "
    "check, credit card, or cash). "
    "For vendor invoices, use qbo_bill instead. "
    "Create, list, update, delete, or search purchases. "
    'line_items: [{"amount": 100.0, "description": "...", "item_ref": "1"}]'
    " — see qbo_help(topic='line_items', entity='purchase') for full schema. "
    f"Search uses IDS query syntax — {IDS_QUERY_RULES} "
    f"{SEARCH_EXAMPLES['purchase']} "
    f"{ERROR_SHAPE_HINT}"
)


def register(mcp: FastMCP) -> None:
    """Register the qbo_purchase tool on *mcp*."""
    from quickbooks_mcp.server import get_client  # noqa: PLC0415

    @mcp.tool(
        name="qbo_purchase",
        description=_TOOL_DESCRIPTION,
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    async def qbo_purchase(
        ctx: Context,
        operation: Literal["list", "get", "create", "update", "delete", "search"],
        id: str | None = None,
        vendor_ref: str | None = None,
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
        """Create, read, update, delete, or search QBO purchases.

        Args:
            operation: Action to perform.
            id: QBO entity ID (numeric string, e.g. '42') — required
                for get, update, delete.
            vendor_ref: Vendor ID (numeric string from qbo_vendor
                list) — optional for linking.
            line_items: List of line item dicts.
            memo: Private memo field.
            start_date: Filter list by TxnDate >= (YYYY-MM-DD).
            end_date: Filter list by TxnDate <= (YYYY-MM-DD).
            query: IDS WHERE clause for search.
            max_results: Max records for list (default 20).
            offset: Zero-based start offset for pagination.
            extra: Optional dict of additional QBO fields.
            preview: Safety gate for delete. When True (default)
                returns a preview; set preview=False to execute.
            response_format: 'json' or 'markdown'.
        """
        client = get_client(ctx)
        extra_dict = validate_extra(extra)

        if operation in ("get", "update", "delete") and not id:
            raise ToolError(f"'id' is required for operation='{operation}'.")
        if operation == "search" and not query:
            raise ToolError("'query' is required for operation='search'.")

        try:
            if operation == "list":
                return await tx_list(
                    client,
                    _TX_TYPE,
                    _ENTITY_TYPE,
                    start_date,
                    end_date,
                    max_results,
                    offset,
                    response_format,
                )
            elif operation == "get":
                return await tx_get(
                    client,
                    _TX_TYPE,
                    _ENTITY_TYPE,
                    id,
                    response_format,  # type: ignore[arg-type]
                )
            elif operation == "create":
                return await tx_create(
                    client,
                    _TX_TYPE,
                    _ENTITY_TYPE,
                    None,
                    vendor_ref,
                    line_items,
                    memo,
                    None,
                    extra_dict,
                    response_format,
                )
            elif operation == "update":
                return await tx_update(
                    client,
                    _TX_TYPE,
                    _ENTITY_TYPE,
                    id,  # type: ignore[arg-type]
                    None,
                    vendor_ref,
                    line_items,
                    memo,
                    None,
                    extra_dict,
                    response_format,
                )
            elif operation == "delete":
                if preview:
                    return await destructive_preview(
                        client,
                        _TX_TYPE,
                        _ENTITY_TYPE,
                        "delete",
                        id,  # type: ignore[arg-type]
                    )
                return await tx_delete(
                    client,
                    _TX_TYPE,
                    _ENTITY_TYPE,
                    id,
                    response_format,  # type: ignore[arg-type]
                )
            elif operation == "search":
                return await tx_search(
                    client,
                    _ENTITY_TYPE,
                    query,
                    response_format,  # type: ignore[arg-type]
                )
        except ToolError:
            raise
        except Exception as exc:
            return format_qbo_error(exc, operation, _ENTITY_TYPE)

        raise ToolError(  # pragma: no cover
            f"Unhandled operation: {operation}"
        )
