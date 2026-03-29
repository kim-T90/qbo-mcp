"""QuickBooks Online MCP — shared base models and type constants."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Literal types
# ---------------------------------------------------------------------------

VALID_TX_TYPES = Literal[
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
]

VALID_PARTY_TYPES = Literal["customer", "vendor", "employee"]

VALID_ITEM_TYPES = Literal["service", "non_inventory", "inventory"]

VALID_ACCOUNT_TYPES = Literal[
    "Bank",
    "Accounts Receivable",
    "Other Current Asset",
    "Fixed Asset",
    "Other Asset",
    "Accounts Payable",
    "Credit Card",
    "Other Current Liability",
    "Long Term Liability",
    "Equity",
    "Income",
    "Cost of Goods Sold",
    "Expense",
    "Other Income",
    "Other Expense",
]

# ---------------------------------------------------------------------------
# Operation matrix
# ---------------------------------------------------------------------------

TX_OPERATION_MATRIX: dict[str, frozenset[str]] = {
    "invoice": frozenset(
        {"list", "get", "create", "update", "delete", "void", "send", "pdf", "search"}
    ),
    "bill": frozenset({"list", "get", "create", "update", "delete", "search"}),
    "bill_payment": frozenset({"list", "get", "create", "update", "delete", "void", "search"}),
    "payment": frozenset({"list", "get", "create", "update", "void", "search"}),
    "deposit": frozenset({"list", "get", "create", "update", "delete", "search"}),
    "transfer": frozenset({"list", "get", "create", "update", "delete", "search"}),
    "journal_entry": frozenset({"list", "get", "create", "update", "delete", "search"}),
    "purchase": frozenset({"list", "get", "create", "update", "delete", "search"}),
    "estimate": frozenset({"list", "get", "create", "update", "delete", "send", "pdf", "search"}),
    "credit_memo": frozenset({"list", "get", "create", "update", "delete", "search"}),
    "sales_receipt": frozenset(
        {"list", "get", "create", "update", "delete", "void", "send", "pdf", "search"}
    ),
    "refund_receipt": frozenset({"list", "get", "create", "update", "delete", "search"}),
    "vendor_credit": frozenset({"list", "get", "create", "update", "delete", "search"}),
}

# ---------------------------------------------------------------------------
# Protected keys
# ---------------------------------------------------------------------------

PROTECTED_KEYS: frozenset[str] = frozenset(
    {"Id", "SyncToken", "domain", "sparse", "MetaData", "TxnDate"}
)

# Maps party_type to python-quickbooks class name
PARTY_CLASS_MAP: dict[str, str] = {
    "customer": "Customer",
    "vendor": "Vendor",
    "employee": "Employee",
}

# Maps item_type to QBO Type field value
ITEM_TYPE_MAP: dict[str, str] = {
    "service": "Service",
    "non_inventory": "NonInventory",
    "inventory": "Inventory",
}

# Maps tx_type to python-quickbooks class name
TX_CLASS_MAP: dict[str, str] = {
    "invoice": "Invoice",
    "bill": "Bill",
    "bill_payment": "BillPayment",
    "payment": "Payment",
    "deposit": "Deposit",
    "transfer": "Transfer",
    "journal_entry": "JournalEntry",
    "purchase": "Purchase",
    "estimate": "Estimate",
    "credit_memo": "CreditMemo",
    "sales_receipt": "SalesReceipt",
    "refund_receipt": "RefundReceipt",
    "vendor_credit": "VendorCredit",
}

# Full IDS query syntax rules — used by qbo_help(topic='query_syntax')
IDS_QUERY_RULES_FULL = (
    "QBO uses IDS query syntax (NOT SQL). Rules: "
    "Table names are SINGULAR (Invoice, not Invoices). "
    "No JOINs, subqueries, or GROUP BY. "
    "Operators: =, <, >, <=, >=, LIKE, IN. "
    "LIKE uses % wildcard: WHERE DisplayName LIKE '%Smith%'. "
    "String values use single quotes. Max 1000 results. "
    "Order by MetaData.LastUpdatedTime (Id is not sortable). "
    "Example: SELECT * FROM Invoice WHERE TotalAmt > '100.00' ORDERBY MetaData.LastUpdatedTime"
)

# 7d: Single-sentence pointer — no inline example, saves ~900 tokens total
IDS_QUERY_RULES = "call qbo_help(topic='query_syntax') for IDS query syntax rules and examples."

# 8b: Per-entity common search examples — inlined to avoid qbo_help pre-call
_SE = "Common searches: "
SEARCH_EXAMPLES: dict[str, str] = {
    "invoice": (
        f"{_SE}Balance > '0' (unpaid), DueDate < '2026-01-01' (overdue), CustomerRef = '123'."
    ),
    "bill": (f"{_SE}Balance > '0' (unpaid), DueDate < '2026-01-01' (overdue), VendorRef = '123'."),
    "payment": (f"{_SE}TotalAmt > '500', CustomerRef = '123', TxnDate >= '2026-01-01'."),
    "bill_payment": (f"{_SE}TotalAmt > '500', VendorRef = '123', TxnDate >= '2026-01-01'."),
    "estimate": (f"{_SE}TotalAmt > '500', CustomerRef = '123', TxnDate >= '2026-01-01'."),
    "sales_receipt": (f"{_SE}TotalAmt > '500', CustomerRef = '123', TxnDate >= '2026-01-01'."),
    "credit_memo": (f"{_SE}TotalAmt > '500', CustomerRef = '123', TxnDate >= '2026-01-01'."),
    "refund_receipt": (f"{_SE}TotalAmt > '500', CustomerRef = '123', TxnDate >= '2026-01-01'."),
    "deposit": f"{_SE}TotalAmt > '500', TxnDate >= '2026-01-01'.",
    "transfer": f"{_SE}Amount > '1000', TxnDate >= '2026-01-01'.",
    "journal_entry": (f"{_SE}TotalAmt > '500', DocNumber = '123', TxnDate >= '2026-01-01'."),
    "purchase": (f"{_SE}TotalAmt > '500', PaymentType = 'CreditCard', TxnDate >= '2026-01-01'."),
    "vendor_credit": (f"{_SE}TotalAmt > '500', VendorRef = '123', TxnDate >= '2026-01-01'."),
    "customer": (f"{_SE}DisplayName LIKE '%Smith%', Balance > '0', Active = true."),
    "vendor": (f"{_SE}DisplayName LIKE '%freight%', Balance > '0', Active = true."),
    "employee": f"{_SE}DisplayName LIKE '%Smith%', Active = true.",
    "account": (f"{_SE}AccountType = 'Bank', Name LIKE '%checking%', Active = true."),
    "item": (f"{_SE}Name LIKE '%freight%', Type = 'Service', Active = true."),
}

# 7b: Shared error shape hint — appended to mutating tool descriptions
ERROR_SHAPE_HINT = (
    "On QBO API error, returns {status: 'error', code: <http_code>, "
    "message: '...', suggestion: '...'}. "
    "Call qbo_help(topic='error_codes') for recovery steps."
)

# 8a: Preview hint — leads description on write tools so LLMs see it first
PREVIEW_HINT = (
    "IMPORTANT: preview defaults to True (dry-run). Set preview=False to actually execute writes."
)

# ---------------------------------------------------------------------------
# Base models
# ---------------------------------------------------------------------------


class PaginationMeta(BaseModel):
    """Pagination metadata returned alongside list results."""

    model_config = ConfigDict(str_strip_whitespace=True)

    start_position: int = Field(default=1, ge=1)
    max_results: int = Field(default=20, ge=1)
    has_more: bool = False
    total: int | None = None


class QBOResponse(BaseModel):
    """Standard success/error response envelope for all QBO MCP tools."""

    model_config = ConfigDict(str_strip_whitespace=True)

    status: Literal["ok", "error"]
    operation: str
    entity_type: str
    count: int | None = None
    data: list[dict] | dict | None = None
    metadata: dict | None = None
    error: dict | None = None
