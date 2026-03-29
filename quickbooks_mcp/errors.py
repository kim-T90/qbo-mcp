"""QuickBooks Online MCP — error handling utilities."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

CHARACTER_LIMIT = 25_000

# Maps QBO HTTP-style error codes to actionable suggestions for the LLM.
_SUGGESTIONS: dict[int | str, str] = {
    401: (
        "Authentication failed. Re-run the QBO OAuth flow to obtain a fresh "
        "refresh token, then update QBO_REFRESH_TOKEN in your .env file."
    ),
    403: (
        "Permission denied. Confirm the QBO app has the required scopes "
        "(com.intuit.quickbooks.accounting) and that the connected company "
        "matches QBO_REALM_ID."
    ),
    # 404 is handled dynamically in _build_suggestion to produce entity-aware hints.
    429: (
        "Rate limited by QBO. Wait at least 60 seconds before retrying. "
        "Batch operations where possible to reduce request volume."
    ),
    400: None,  # Handled dynamically — includes QBO detail in suggestion.
    500: (
        "QBO internal error. Retry once after a short delay. If the error "
        "persists, check the Intuit Developer status page."
    ),
    503: (
        "QBO service unavailable. Retry with exponential back-off. "
        "Check the Intuit Developer status page for outage information."
    ),
}

# Maps entity types to the dedicated tool name for error suggestions.
_ENTITY_TOOL_MAP: dict[str, str] = {
    "Customer": "qbo_customer",
    "Vendor": "qbo_vendor",
    "Employee": "qbo_employee",
    "Invoice": "qbo_invoice",
    "Bill": "qbo_bill",
    "Payment": "qbo_payment",
    "BillPayment": "qbo_bill_payment",
    "Estimate": "qbo_estimate",
    "CreditMemo": "qbo_credit_memo",
    "SalesReceipt": "qbo_sales_receipt",
    "RefundReceipt": "qbo_refund_receipt",
    "VendorCredit": "qbo_vendor_credit",
    "Deposit": "qbo_deposit",
    "Transfer": "qbo_transfer",
    "JournalEntry": "qbo_journal_entry",
    "Purchase": "qbo_purchase",
    "Item": "qbo_item",
    "Account": "qbo_account",
}


def _extract_status_code(exc: Exception) -> int | None:
    """Best-effort extraction of an HTTP status code from a QBO exception."""
    # python-quickbooks QuickbooksException stores status_code attribute.
    code = getattr(exc, "status_code", None)
    if isinstance(code, int):
        return code

    # Fall back to parsing the string representation for a leading integer.
    msg = str(exc)
    first_token = msg.split()[0].rstrip(":") if msg else ""
    try:
        return int(first_token)
    except ValueError:
        return None


def _entity_list_hint(entity_type: str) -> str:
    """Return a tool invocation hint for listing entities of the given type."""
    tool_name = _ENTITY_TOOL_MAP.get(entity_type)
    if tool_name:
        return f"Use {tool_name}(operation='list') to find the correct ID before retrying."
    # Fallback for entity types without a dedicated tool (e.g. Invoice, Bill).
    return f"Use the relevant list tool for {entity_type} to find the correct ID before retrying."


def _build_suggestion(status_code: int | None, exc: Exception, entity_type: str) -> str:
    """Return a human-readable next-action suggestion for the LLM."""
    if status_code == 400:
        detail = getattr(exc, "detail", None) or str(exc)
        return (
            f"Bad request sent to QBO. QBO detail: {detail}. "
            "Check the field values and types, then retry. "
            f"{_entity_list_hint(entity_type)} "
            "Use qbo_help(topic='fields', entity=...) to check valid field names."
        )

    if status_code == 404:
        return f"Entity not found. {_entity_list_hint(entity_type)}"

    suggestion = _SUGGESTIONS.get(status_code or -1)
    if suggestion:
        return suggestion

    # Generic fallback
    return (
        f"Unexpected QBO error (status={status_code}). "
        "Inspect the 'detail' field, correct the request, and retry. "
        "Use qbo_help(topic='error_codes') for recovery guidance."
    )


def format_qbo_error(exc: Exception, operation: str, entity_type: str) -> dict:
    """Convert a QBO exception to a structured error response.

    Args:
        exc: The exception raised by the python-quickbooks library.
        operation: The MCP tool operation that failed (e.g. 'create', 'list').
        entity_type: The QBO entity type being operated on (e.g. 'Invoice').

    Returns:
        A dict with keys: status, code, message, detail, suggestion.
    """
    status_code = _extract_status_code(exc)

    # python-quickbooks may expose a .detail attribute with the raw QBO body.
    raw_detail = getattr(exc, "detail", None)
    message = getattr(exc, "message", None) or str(exc)

    logger.debug(
        "QBO error during %s on %s: status=%s message=%r",
        operation,
        entity_type,
        status_code,
        message,
    )

    return {
        "status": "error",
        "code": status_code,
        "message": message,
        "detail": raw_detail or message,
        "suggestion": _build_suggestion(status_code, exc, entity_type),
    }
