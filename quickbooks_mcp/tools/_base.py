"""Shared helpers for per-transaction-type tools.

This module extracts the common transaction logic from transaction.py so that
each per-type tool (invoice.py, estimate.py, etc.) can import thin, reusable
building blocks instead of duplicating code.
"""

from __future__ import annotations

import base64
import importlib
import logging
from typing import Any

from fastmcp.exceptions import ToolError

from quickbooks_mcp.converters import qbo_to_snake
from quickbooks_mcp.formatting import format_response, paginate_list, truncate_response
from quickbooks_mcp.models import PROTECTED_KEYS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# TX class import map  (module_path, class_name)
# ---------------------------------------------------------------------------

TX_IMPORTS: dict[str, tuple[str, str]] = {
    "invoice": ("quickbooks.objects.invoice", "Invoice"),
    "bill": ("quickbooks.objects.bill", "Bill"),
    "bill_payment": ("quickbooks.objects.billpayment", "BillPayment"),
    "payment": ("quickbooks.objects.payment", "Payment"),
    "deposit": ("quickbooks.objects.deposit", "Deposit"),
    "transfer": ("quickbooks.objects.transfer", "Transfer"),
    "journal_entry": ("quickbooks.objects.journalentry", "JournalEntry"),
    "purchase": ("quickbooks.objects.purchase", "Purchase"),
    "estimate": ("quickbooks.objects.estimate", "Estimate"),
    "credit_memo": ("quickbooks.objects.creditmemo", "CreditMemo"),
    "sales_receipt": ("quickbooks.objects.salesreceipt", "SalesReceipt"),
    "refund_receipt": ("quickbooks.objects.refundreceipt", "RefundReceipt"),
    "vendor_credit": ("quickbooks.objects.vendorcredit", "VendorCredit"),
}

# Default line-item detail type per tx_type category
DEFAULT_DETAIL_TYPE: dict[str, str] = {
    "invoice": "SalesItemLineDetail",
    "estimate": "SalesItemLineDetail",
    "sales_receipt": "SalesItemLineDetail",
    "credit_memo": "SalesItemLineDetail",
    "refund_receipt": "SalesItemLineDetail",
    "bill": "ItemBasedExpenseLineDetail",
    "purchase": "ItemBasedExpenseLineDetail",
    "vendor_credit": "ItemBasedExpenseLineDetail",
    "journal_entry": "JournalEntryLineDetail",
    "deposit": "DepositLineDetail",
}


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


def get_tx_class(tx_type: str) -> Any:
    """Lazily import and return the python-quickbooks class for *tx_type*."""
    module_path, class_name = TX_IMPORTS[tx_type]
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def validate_extra(extra: dict | None) -> dict:
    """Validate *extra* dict against protected keys and return a clean dict.

    Returns an empty dict when *extra* is None or empty.  Raises ToolError
    when protected keys are detected.
    """
    extra_dict: dict = extra or {}
    if extra_dict:
        bad_keys = PROTECTED_KEYS & set(extra_dict)
        if bad_keys:
            raise ToolError(
                f"'extra' contains protected keys that cannot be set directly: "
                f"{sorted(bad_keys)}. Remove them and retry."
            )
    return extra_dict


def build_line_items(tx_type: str, line_item_dicts: list[dict]) -> list[dict]:
    """Convert snake_case line item dicts to QBO PascalCase line objects."""
    default_detail = DEFAULT_DETAIL_TYPE.get(tx_type, "SalesItemLineDetail")
    qbo_lines = []
    for raw in line_item_dicts:
        detail_type = raw.get("detail_type") or raw.get("DetailType") or default_detail
        amount = raw.get("amount") or raw.get("Amount") or 0.0
        description = raw.get("description") or raw.get("Description")
        item_ref = raw.get("item_ref") or raw.get("ItemRef")

        line: dict = {
            "Amount": amount,
            "DetailType": detail_type,
        }

        # Build the detail sub-object
        detail_body: dict = {}
        if description:
            detail_body["Description"] = description
        if item_ref:
            detail_body["ItemRef"] = {"value": item_ref}

        # Copy any extra detail fields from raw that aren't top-level keys
        _known = {
            "amount",
            "description",
            "item_ref",
            "detail_type",
            "Amount",
            "Description",
            "ItemRef",
            "DetailType",
        }
        for k, v in raw.items():
            if k not in _known:
                detail_body[k] = v

        if detail_body:
            line[detail_type] = detail_body

        qbo_lines.append(line)
    return qbo_lines


# ---------------------------------------------------------------------------
# Operation handlers
# ---------------------------------------------------------------------------


async def tx_list(
    client: Any,
    tx_type: str,
    entity_type: str,
    start_date: str | None,
    end_date: str | None,
    max_results: int,
    offset: int,
    response_format: str,
) -> dict | str:
    """List transactions with optional date filtering and pagination."""
    cls = get_tx_class(tx_type)
    start_position = offset + 1

    def _fetch() -> list:
        kwargs: dict = {
            "max_results": max_results,
            "start_position": start_position,
            "qb": client.qb_client,
        }
        if start_date:
            kwargs["TxnDate"] = f">= '{start_date}'"
        if end_date:
            kwargs["TxnDate <="] = f"'{end_date}'"
        return cls.filter(**kwargs)

    results = await client.execute(_fetch)
    items = [qbo_to_snake(r.to_dict()) for r in (results or [])]
    _, meta = paginate_list(items, total=len(items), offset=0, limit=max_results)
    meta["start_position"] = start_position
    response = format_response(
        items, "list", entity_type, metadata=meta, response_format=response_format
    )
    if isinstance(response, dict):
        response = truncate_response(response)
    return response


async def tx_get(
    client: Any,
    tx_type: str,
    entity_type: str,
    id: str,
    response_format: str,
) -> dict | str:
    """Fetch a single transaction by ID."""
    cls = get_tx_class(tx_type)
    result = await client.execute(cls.get, id, qb=client.qb_client)
    data = qbo_to_snake(result.to_dict())
    return format_response(data, "get", entity_type, response_format=response_format)


async def tx_create(
    client: Any,
    tx_type: str,
    entity_type: str,
    customer_ref: str | None,
    vendor_ref: str | None,
    line_item_dicts: list[dict] | None,
    memo: str | None,
    due_date: str | None,
    extra_dict: dict,
    response_format: str,
) -> dict | str:
    """Create a new transaction."""
    cls = get_tx_class(tx_type)

    def _do_create():
        obj = cls()
        if customer_ref is not None:
            obj.CustomerRef = {"value": customer_ref}
        if vendor_ref is not None:
            obj.VendorRef = {"value": vendor_ref}
        if memo is not None:
            obj.PrivateNote = memo
        if due_date is not None:
            obj.DueDate = due_date
        if line_item_dicts:
            obj.Line = build_line_items(tx_type, line_item_dicts)
        for key, value in extra_dict.items():
            setattr(obj, key, value)
        obj.save(qb=client.qb_client)
        return obj

    result = await client.execute(_do_create)
    data = qbo_to_snake(result.to_dict())
    return format_response(data, "create", entity_type, response_format=response_format)


async def tx_update(
    client: Any,
    tx_type: str,
    entity_type: str,
    id: str,
    customer_ref: str | None,
    vendor_ref: str | None,
    line_item_dicts: list[dict] | None,
    memo: str | None,
    due_date: str | None,
    extra_dict: dict,
    response_format: str,
) -> dict | str:
    """Update an existing transaction (auto-fetches SyncToken)."""
    cls = get_tx_class(tx_type)

    def _do_update():
        obj = cls.get(id, qb=client.qb_client)
        if customer_ref is not None:
            obj.CustomerRef = {"value": customer_ref}
        if vendor_ref is not None:
            obj.VendorRef = {"value": vendor_ref}
        if memo is not None:
            obj.PrivateNote = memo
        if due_date is not None:
            obj.DueDate = due_date
        if line_item_dicts:
            obj.Line = build_line_items(tx_type, line_item_dicts)
        for key, value in extra_dict.items():
            setattr(obj, key, value)
        obj.save(qb=client.qb_client)
        return obj

    result = await client.execute(_do_update)
    data = qbo_to_snake(result.to_dict())
    return format_response(data, "update", entity_type, response_format=response_format)


async def tx_delete(
    client: Any,
    tx_type: str,
    entity_type: str,
    id: str,
    response_format: str,
) -> dict | str:
    """Permanently delete a transaction."""
    cls = get_tx_class(tx_type)

    def _do_delete():
        obj = cls.get(id, qb=client.qb_client)
        obj.delete(qb=client.qb_client)
        return obj

    result = await client.execute(_do_delete)
    data = qbo_to_snake(result.to_dict())
    return format_response(data, "delete", entity_type, response_format=response_format)


async def tx_void(
    client: Any,
    tx_type: str,
    entity_type: str,
    id: str,
    response_format: str,
) -> dict | str:
    """Void a transaction without deleting."""
    cls = get_tx_class(tx_type)

    def _do_void():
        obj = cls.get(id, qb=client.qb_client)
        obj.void(qb=client.qb_client)
        return obj

    result = await client.execute(_do_void)
    data = qbo_to_snake(result.to_dict())
    return format_response(data, "void", entity_type, response_format=response_format)


async def tx_send(
    client: Any,
    tx_type: str,
    entity_type: str,
    id: str,
    email: str | None,
    response_format: str,
) -> dict | str:
    """Email a transaction PDF to a recipient."""
    cls = get_tx_class(tx_type)

    def _do_send():
        obj = cls.get(id, qb=client.qb_client)
        return obj.send(qb=client.qb_client, send_to=email)

    result = await client.execute(_do_send)
    if result is None:
        data = {"id": id, "status": "sent", "sent_to": email}
    elif hasattr(result, "to_dict"):
        data = qbo_to_snake(result.to_dict())
    else:
        data = {"id": id, "status": "sent", "sent_to": email}
    return format_response(data, "send", entity_type, response_format=response_format)


async def tx_pdf(
    client: Any,
    tx_type: str,
    entity_type: str,
    id: str,
    response_format: str,
) -> dict | str:
    """Download a transaction as base64-encoded PDF."""
    cls = get_tx_class(tx_type)

    def _do_pdf() -> bytes:
        obj = cls.get(id, qb=client.qb_client)
        return obj.download_pdf(qb=client.qb_client)

    pdf_bytes = await client.execute(_do_pdf)
    encoded = base64.b64encode(pdf_bytes).decode("utf-8") if pdf_bytes else ""
    data = {
        "id": id,
        "entity_type": entity_type,
        "content_type": "application/pdf",
        "encoding": "base64",
        "data": encoded,
    }
    return format_response(data, "pdf", entity_type, response_format=response_format)


async def tx_search(
    client: Any,
    entity_type: str,
    query: str,
    response_format: str,
) -> dict | str:
    """Run a raw IDS query against a transaction table."""
    full_query = f"SELECT * FROM {entity_type} WHERE {query}"

    results = await client.execute(client.qb_client.query, full_query)
    items = [
        qbo_to_snake(r) if isinstance(r, dict) else qbo_to_snake(r.to_dict())
        for r in (results or [])
    ]
    response = format_response(
        items,
        "search",
        entity_type,
        metadata={"query": full_query},
        response_format=response_format,
    )
    if isinstance(response, dict):
        response = truncate_response(response)
    return response


async def destructive_preview(
    client: Any,
    tx_type: str,
    entity_type: str,
    operation: str,
    id: str,
) -> dict:
    """Fetch the entity and return a preview instead of executing the destructive op."""
    cls = get_tx_class(tx_type)
    result = await client.execute(cls.get, id, qb=client.qb_client)
    data = qbo_to_snake(result.to_dict())
    return {
        "status": "preview",
        "operation": operation,
        "entity_type": entity_type,
        "tx_type": tx_type,
        "id": id,
        "data": data,
        "warning": (
            f"This will {operation} {entity_type} {id}. Call again with preview=False to proceed."
        ),
    }
