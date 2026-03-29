"""qbo_bill_payment tool — manage QuickBooks Online bill payments."""

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
    tx_void,
    validate_extra,
)

if TYPE_CHECKING:
    from fastmcp import FastMCP

_TX_TYPE = "bill_payment"
_ENTITY_TYPE = "BillPayment"

_TOOL_DESCRIPTION = (
    f"{PREVIEW_HINT} "
    "Manage QuickBooks Online bill payments (paying vendor bills). "
    "For receiving customer payments against invoices, use qbo_payment instead. "
    "Create, list, update, delete, void, or search. "
    "create requires vendor_ref and amount. "
    "line_items use LinkedTxn to reference bills: "
    '[{"TxnId": "123", "TxnType": "Bill", "Amount": 500.0}]. '
    "See qbo_help(topic='line_items', entity='bill_payment') for full schema. "
    "Use extra for PaymentType ('Check' or 'CreditCard') and "
    "CheckPayment/CreditCardPayment details. "
    "Search uses IDS query syntax (not SQL) — "
    f"{IDS_QUERY_RULES} "
    f"{SEARCH_EXAMPLES['bill_payment']} "
    "Typical flow: qbo_vendor(list) -> qbo_bill(list) -> "
    f"qbo_bill_payment(create). {ERROR_SHAPE_HINT}"
)


def register(mcp: FastMCP) -> None:
    """Register the qbo_bill_payment tool on *mcp*."""
    from quickbooks_mcp.server import get_client  # noqa: PLC0415

    @mcp.tool(
        name="qbo_bill_payment",
        description=_TOOL_DESCRIPTION,
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    async def qbo_bill_payment(
        ctx: Context,
        operation: Literal[
            "list",
            "get",
            "create",
            "update",
            "delete",
            "void",
            "search",
        ],
        id: str | None = None,
        vendor_ref: str | None = None,
        amount: float | None = None,
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
        """Create, read, update, delete, void, or search QBO bill payments.

        Args:
            operation: Action to perform.
            id: QBO entity ID (numeric string, e.g. '42') —
                required for get, update, delete, void.
            vendor_ref: Vendor ID (numeric string from
                qbo_vendor list) — required for create.
            amount: Total payment amount (required for create).
            line_items: LinkedTxn dicts referencing bills. Each item:
                TxnId (str — Bill ID), TxnType (str, e.g. "Bill"),
                Amount (float — amount applied to this bill).
            memo: Private memo field.
            start_date: Filter list by TxnDate >= (YYYY-MM-DD).
            end_date: Filter list by TxnDate <= (YYYY-MM-DD).
            query: IDS WHERE clause for search.
            max_results: Max records for list (default 20).
            offset: Zero-based start offset for pagination.
            extra: Optional dict of additional QBO fields.
                Use for PaymentType ('Check' or 'CreditCard').
            preview: Safety gate for delete/void. When True
                (default) returns a preview; set
                preview=False to execute.
            response_format: 'json' or 'markdown'.
        """
        client = get_client(ctx)
        extra_dict = validate_extra(extra)

        # Promote first-class amount into extra
        if amount is not None:
            extra_dict["TotalAmt"] = amount

        if operation in ("get", "update", "delete", "void") and not id:
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
            elif operation == "void":
                if preview:
                    return await destructive_preview(
                        client,
                        _TX_TYPE,
                        _ENTITY_TYPE,
                        "void",
                        id,  # type: ignore[arg-type]
                    )
                return await tx_void(
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
