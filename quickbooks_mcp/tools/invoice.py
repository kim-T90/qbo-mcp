"""qbo_invoice tool — manage QuickBooks Online invoices."""

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
    tx_pdf,
    tx_search,
    tx_send,
    tx_update,
    tx_void,
    validate_extra,
)

if TYPE_CHECKING:
    from fastmcp import FastMCP

TX_TYPE = "invoice"
ENTITY_TYPE = "Invoice"

_TOOL_DESCRIPTION = (
    f"{PREVIEW_HINT} "
    "Manage QuickBooks Online invoices. "
    "Create, list, update, delete, void, email, or download as PDF. "
    "create requires customer_ref (customer ID from qbo_customer). "
    'line_items: [{"amount": 100.0, "description": "...", "item_ref": "1"}]'
    " — see qbo_help(topic='line_items', entity='invoice') for full schema. "
    f"Search uses IDS query syntax — {IDS_QUERY_RULES} "
    f"{SEARCH_EXAMPLES['invoice']} "
    "Typical flow: qbo_customer(list) -> get customer ID -> "
    f"qbo_invoice(create). {ERROR_SHAPE_HINT}"
)


def register(mcp: FastMCP) -> None:
    """Register the qbo_invoice tool on *mcp*."""
    from quickbooks_mcp.server import get_client  # noqa: PLC0415

    @mcp.tool(
        name="qbo_invoice",
        description=_TOOL_DESCRIPTION,
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    async def qbo_invoice(
        ctx: Context,
        operation: Literal[
            "list", "get", "create", "update", "delete", "void", "send", "pdf", "search"
        ],
        id: str | None = None,
        customer_ref: str | None = None,
        line_items: list[dict] | None = None,
        memo: str | None = None,
        due_date: str | None = None,
        email: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        query: str | None = None,
        max_results: int = 20,
        offset: int = 0,
        extra: dict | None = None,
        preview: bool = True,
        response_format: Literal["json", "markdown"] = "json",
    ) -> dict | str:
        """Create, read, update, delete, void, send, or search QuickBooks Online invoices.

        Args:
            operation: Action to perform.
            id: QBO entity ID (numeric string, e.g. '42') — required
                for get, update, delete, void, send, pdf.
            customer_ref: Customer ID (numeric string from
                qbo_customer list) — required for create.
            line_items: List of line item dicts. Each item supports:
                amount (float), description (str), item_ref (str — Item ID),
                detail_type (str — defaults to 'SalesItemLineDetail').
            memo: Private note on the invoice.
            due_date: Due date in YYYY-MM-DD format.
            email: Recipient email for the send operation.
            start_date: Filter list by TxnDate >= start_date (YYYY-MM-DD).
            end_date: Filter list by TxnDate <= end_date (YYYY-MM-DD).
            query: IDS WHERE clause for search (e.g. "TotalAmt > '100.00'").
            max_results: Maximum records to return for list (default 20).
            offset: Zero-based start offset for list pagination (default 0).
            extra: Optional dict of additional QBO fields.
            preview: Safety gate — True (default) returns a preview without
                executing. Set False to actually write.
            response_format: 'json' (default) or 'markdown'.
        """
        client = get_client(ctx)
        extra_dict = validate_extra(extra)

        if operation in ("get", "update", "delete", "void", "send", "pdf") and not id:
            raise ToolError(f"'id' is required for operation='{operation}'.")
        if operation == "send" and not email:
            raise ToolError("'email' is required for operation='send'.")
        if operation == "create" and not customer_ref:
            raise ToolError(
                "'customer_ref' is required when creating an invoice. "
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
                    due_date,
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
                    due_date,
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
            elif operation == "void":
                if preview:
                    return await destructive_preview(
                        client,
                        TX_TYPE,
                        ENTITY_TYPE,
                        "void",
                        id,
                    )
                return await tx_void(client, TX_TYPE, ENTITY_TYPE, id, response_format)
            elif operation == "send":
                return await tx_send(
                    client,
                    TX_TYPE,
                    ENTITY_TYPE,
                    id,
                    email,
                    response_format,
                )
            elif operation == "pdf":
                return await tx_pdf(client, TX_TYPE, ENTITY_TYPE, id, response_format)
            elif operation == "search":
                return await tx_search(client, ENTITY_TYPE, query, response_format)
        except ToolError:
            raise
        except Exception as exc:
            return format_qbo_error(exc, operation, ENTITY_TYPE)

        raise ToolError(f"Unhandled operation: {operation}")  # pragma: no cover
