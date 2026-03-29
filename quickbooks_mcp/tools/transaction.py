"""qbo_transaction tool — all transaction types via tx_type parameter."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from fastmcp import Context
from fastmcp.exceptions import ToolError

from quickbooks_mcp.errors import format_qbo_error
from quickbooks_mcp.models import IDS_QUERY_RULES, TX_CLASS_MAP, TX_OPERATION_MATRIX
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

import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool description
# ---------------------------------------------------------------------------

_TOOL_DESCRIPTION = (
    "[DEPRECATED — will be removed 2026-05-01. "
    "Use qbo_invoice, qbo_bill, qbo_payment, qbo_estimate, "
    "qbo_sales_receipt, qbo_credit_memo, qbo_refund_receipt, "
    "qbo_vendor_credit, qbo_bill_payment, qbo_deposit, qbo_transfer, "
    "qbo_journal_entry, qbo_purchase instead] "
    "Manage all QuickBooks Online transaction types from a single tool. "
    "Specify tx_type and operation. "
    "All tx_types support: list, get, create, update, delete, search. "
    "Additionally: invoice supports void, send, pdf. "
    "estimate supports send, pdf. sales_receipt supports void, send, pdf. "
    "bill_payment and payment support void. "
    "create requires customer_ref for "
    "invoice/estimate/sales_receipt/credit_memo/refund_receipt/payment, "
    "or vendor_ref for bill/vendor_credit. "
    "line_items accepts a list of dicts: "
    '[{"amount": 100.0, "description": "...", "item_ref": "1"}]. '
    "extra accepts a dict of additional QBO fields. "
    f"Search uses IDS query syntax — {IDS_QUERY_RULES}"
)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(mcp: FastMCP) -> None:
    """Register the qbo_transaction tool on *mcp*."""
    from quickbooks_mcp.server import get_client  # noqa: PLC0415

    @mcp.tool(
        name="qbo_transaction",
        description=_TOOL_DESCRIPTION,
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    async def qbo_transaction(
        ctx: Context,
        operation: Literal[
            "list", "get", "create", "update", "delete", "void", "send", "pdf", "search"
        ],
        tx_type: Literal[
            "invoice",
            "bill",
            "bill_payment",
            "payment",
            "deposit",
            "transfer",
            "journal_entry",
            "purchase",
            "estimate",
            "credit_memo",
            "sales_receipt",
            "refund_receipt",
            "vendor_credit",
        ],
        id: str | None = None,
        customer_ref: str | None = None,
        vendor_ref: str | None = None,
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
        """Create, read, update, delete, void, send, or search QuickBooks Online transactions.

        Args:
            operation: Action to perform. One of:
                - list: Paginated list of transactions.
                - get: Fetch a single transaction by id.
                - create: Create a new transaction.
                - update: Merge supplied fields onto an existing transaction (id required).
                - delete: Permanently delete a transaction (id required).
                - void: Void a transaction without deleting (id required).
                - send: Email a transaction PDF to a customer (id + email required).
                - pdf: Download transaction as base64-encoded PDF (id required).
                - search: Run a raw IDS query against the transaction table.
            tx_type: Transaction entity type.
            id: Transaction ID — required for get, update, delete, void, send, pdf.
            customer_ref: Customer ID for invoice, estimate, sales_receipt, credit_memo, etc.
            vendor_ref: Vendor ID for bill, purchase, vendor_credit, etc.
            line_items: List of line item dicts. Each item supports:
                amount (float), description (str), item_ref (str — Item ID),
                detail_type (str — defaults per tx_type, e.g. 'SalesItemLineDetail').
            memo: Private or customer-visible memo field.
            due_date: Due date in YYYY-MM-DD format.
            email: Recipient email for the send operation.
            start_date: Filter list by TxnDate >= start_date (YYYY-MM-DD).
            end_date: Filter list by TxnDate <= end_date (YYYY-MM-DD).
            query: IDS WHERE clause for search (e.g. "TotalAmt > '100.00'").
            max_results: Maximum records to return for list (default 20).
            offset: Zero-based start offset for list pagination (default 0).
            extra: Optional dict of additional QBO fields to merge before save.
                Protected keys (Id, SyncToken, domain, sparse, MetaData, TxnDate)
                are rejected to prevent accidental corruption.
            preview: Safety gate for destructive operations (delete, void).
                When True (the default), returns a preview of the entity
                instead of executing. Set preview=False to proceed with
                the actual operation. Has no effect on non-destructive ops.
            response_format: 'json' for structured dict (default), 'markdown' for
                human-readable text.
        """
        # Validate operation against the matrix before anything else.
        allowed = TX_OPERATION_MATRIX.get(tx_type)
        if allowed is None:
            valid = ", ".join(sorted(TX_OPERATION_MATRIX))
            raise ToolError(f"Invalid tx_type '{tx_type}'. Valid values: {valid}")
        if operation not in allowed:
            raise ToolError(
                f"'{operation}' is not supported for '{tx_type}'. Supported: {sorted(allowed)}"
            )

        # Validate id for operations that require it.
        if operation in ("get", "update", "delete", "void", "send", "pdf") and not id:
            raise ToolError(f"'id' is required for operation='{operation}'.")

        # Validate email for send.
        if operation == "send" and not email:
            raise ToolError("'email' is required for operation='send'.")

        # Validate extra against protected keys.
        extra_dict = validate_extra(extra)

        # Validate party refs for create — catch before hitting QBO API.
        needs_customer = frozenset(
            {
                "invoice",
                "estimate",
                "sales_receipt",
                "credit_memo",
                "refund_receipt",
                "payment",
            }
        )
        needs_vendor = frozenset(
            {
                "bill",
                "vendor_credit",
            }
        )
        if operation == "create":
            if tx_type in needs_customer and not customer_ref:
                raise ToolError(
                    f"'customer_ref' is required when creating a {tx_type}. "
                    "Use qbo_customer(operation='list') to find customer IDs."
                )
            if tx_type in needs_vendor and not vendor_ref:
                raise ToolError(
                    f"'vendor_ref' is required when creating a {tx_type}. "
                    "Use qbo_vendor(operation='list') to find vendor IDs."
                )

        entity_type = TX_CLASS_MAP[tx_type]
        client = get_client(ctx)

        try:
            if operation == "list":
                return await tx_list(
                    client,
                    tx_type,
                    entity_type,
                    start_date,
                    end_date,
                    max_results,
                    offset,
                    response_format,
                )
            elif operation == "get":
                return await tx_get(client, tx_type, entity_type, id, response_format)  # type: ignore[arg-type]
            elif operation == "create":
                return await tx_create(
                    client,
                    tx_type,
                    entity_type,
                    customer_ref,
                    vendor_ref,
                    line_items,
                    memo,
                    due_date,
                    extra_dict,
                    response_format,
                )
            elif operation == "update":
                return await tx_update(
                    client,
                    tx_type,
                    entity_type,
                    id,  # type: ignore[arg-type]
                    customer_ref,
                    vendor_ref,
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
                        tx_type,
                        entity_type,
                        "delete",
                        id,  # type: ignore[arg-type]
                    )
                return await tx_delete(client, tx_type, entity_type, id, response_format)  # type: ignore[arg-type]
            elif operation == "void":
                if preview:
                    return await destructive_preview(
                        client,
                        tx_type,
                        entity_type,
                        "void",
                        id,  # type: ignore[arg-type]
                    )
                return await tx_void(client, tx_type, entity_type, id, response_format)  # type: ignore[arg-type]
            elif operation == "send":
                return await tx_send(client, tx_type, entity_type, id, email, response_format)  # type: ignore[arg-type]
            elif operation == "pdf":
                return await tx_pdf(client, tx_type, entity_type, id, response_format)  # type: ignore[arg-type]
            elif operation == "search":
                if not query:
                    raise ToolError("'query' is required for operation='search'.")
                return await tx_search(client, entity_type, query, response_format)
        except ToolError:
            raise
        except Exception as exc:
            error = format_qbo_error(exc, operation, entity_type)
            return error

        raise ToolError(f"Unhandled operation: {operation}")  # pragma: no cover
