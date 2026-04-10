"""qbo_help tool — offline reference for field names, operation matrices, and query syntax."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from fastmcp import Context
from fastmcp.exceptions import ToolError

from quickbooks_mcp.models import TX_OPERATION_MATRIX

if TYPE_CHECKING:
    from fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Field name reference (common IDS query fields per entity)
# ---------------------------------------------------------------------------

_FIELD_NAMES: dict[str, list[str]] = {
    "Customer": [
        "Id",
        "DisplayName",
        "CompanyName",
        "PrimaryEmailAddr",
        "PrimaryPhone",
        "Balance",
        "Active",
        "MetaData.LastUpdatedTime",
    ],
    "Vendor": [
        "Id",
        "DisplayName",
        "CompanyName",
        "PrimaryEmailAddr",
        "PrimaryPhone",
        "Balance",
        "Active",
        "Vendor1099",
        "MetaData.LastUpdatedTime",
    ],
    "Employee": [
        "Id",
        "DisplayName",
        "PrimaryEmailAddr",
        "PrimaryPhone",
        "Active",
        "MetaData.LastUpdatedTime",
    ],
    "Invoice": [
        "Id",
        "DocNumber",
        "TxnDate",
        "DueDate",
        "TotalAmt",
        "Balance",
        "CustomerRef",
        "PrivateNote",
        "MetaData.LastUpdatedTime",
    ],
    "Bill": [
        "Id",
        "DocNumber",
        "TxnDate",
        "DueDate",
        "TotalAmt",
        "Balance",
        "VendorRef",
        "PrivateNote",
        "MetaData.LastUpdatedTime",
    ],
    "Payment": [
        "Id",
        "TxnDate",
        "TotalAmt",
        "CustomerRef",
        "PrivateNote",
        "MetaData.LastUpdatedTime",
    ],
    "Estimate": [
        "Id",
        "DocNumber",
        "TxnDate",
        "TotalAmt",
        "CustomerRef",
        "ExpirationDate",
        "MetaData.LastUpdatedTime",
    ],
    "Account": [
        "Id",
        "Name",
        "FullyQualifiedName",
        "AccountType",
        "AccountSubType",
        "CurrentBalance",
        "Active",
        "MetaData.LastUpdatedTime",
    ],
    "Item": [
        "Id",
        "Name",
        "Type",
        "UnitPrice",
        "Active",
        "IncomeAccountRef",
        "ExpenseAccountRef",
        "MetaData.LastUpdatedTime",
    ],
    "Deposit": [
        "Id",
        "TxnDate",
        "TotalAmt",
        "PrivateNote",
        "MetaData.LastUpdatedTime",
    ],
    "Transfer": [
        "Id",
        "TxnDate",
        "Amount",
        "FromAccountRef",
        "ToAccountRef",
        "MetaData.LastUpdatedTime",
    ],
    "JournalEntry": [
        "Id",
        "TxnDate",
        "TotalAmt",
        "DocNumber",
        "PrivateNote",
        "MetaData.LastUpdatedTime",
    ],
    "Purchase": [
        "Id",
        "TxnDate",
        "TotalAmt",
        "AccountRef",
        "PaymentType",
        "MetaData.LastUpdatedTime",
    ],
}

_IDS_SYNTAX_GUIDE = (
    "IDS query syntax (used in all search operations):\n"
    "- Operators: =, <, >, <=, >=, LIKE, IN\n"
    "- LIKE uses % wildcard: DisplayName LIKE '%Smith%'\n"
    "- String values need single quotes: TotalAmt > '1000.00'\n"
    "- Date values use YYYY-MM-DD in single quotes: "
    "TxnDate >= '2026-01-01'\n"
    "- Boolean values are unquoted: Active = true (not 'true')\n"
    "- IN uses parentheses: Id IN ('1', '2', '3')\n"
    "- ORDER BY is supported but only on "
    "MetaData.LastUpdatedTime. Syntax: "
    "ORDERBY MetaData.LastUpdatedTime DESC\n"
    "- Pagination is handled by tool parameters "
    "(max_results, offset), NOT in the query string. "
    "Do not add STARTPOSITION or MAXRESULTS to your query.\n"
    "- No JOINs, subqueries, or GROUP BY\n"
    "- Max 1000 results per query\n\n"
    "Examples:\n"
    "  DisplayName LIKE '%freight%'\n"
    "  TotalAmt > '500.00' AND Balance > '0'\n"
    "  TxnDate >= '2026-01-01' AND TxnDate <= '2026-03-31'\n"
    "  Active = true\n"
    "  Id IN ('1', '2', '3')"
)

_INVOICE_LINE_SEARCH_NOTE = (
    "Invoice IDS search only supports top-level invoice fields such as DocNumber, "
    "TxnDate, TotalAmt, Balance, CustomerRef, and PrivateNote. It does not search "
    "nested line descriptions. Use qbo_invoice(operation='search_line_items', "
    "keywords=[...], start_date='YYYY-MM-DD', end_date='YYYY-MM-DD') for "
    "description-based line-item scans."
)


# ---------------------------------------------------------------------------
# Line item schema reference per detail type
# ---------------------------------------------------------------------------

_LINE_ITEM_SCHEMAS: dict[str, dict] = {
    "SalesItemLineDetail": {
        "used_by": ["invoice", "estimate", "sales_receipt", "credit_memo", "refund_receipt"],
        "default_for": "Sales transactions (customer-facing)",
        "fields": {
            "amount": {"type": "float", "required": True, "description": "Line total"},
            "description": {"type": "str", "required": False, "description": "Line description"},
            "item_ref": {"type": "str", "required": False, "description": "Item ID from qbo_item"},
            "detail_type": {
                "type": "str",
                "required": False,
                "description": "Override detail type (defaults to SalesItemLineDetail)",
            },
        },
        "example": {"amount": 1500.00, "description": "Freight haul", "item_ref": "5"},
    },
    "ItemBasedExpenseLineDetail": {
        "used_by": ["bill", "purchase", "vendor_credit"],
        "default_for": "Expense transactions (vendor-facing)",
        "fields": {
            "amount": {"type": "float", "required": True, "description": "Line total"},
            "description": {"type": "str", "required": False, "description": "Line description"},
            "item_ref": {"type": "str", "required": False, "description": "Item ID from qbo_item"},
            "detail_type": {
                "type": "str",
                "required": False,
                "description": "Override detail type (defaults to ItemBasedExpenseLineDetail)",
            },
            "CustomerRef": {
                "type": "dict",
                "required": False,
                "description": 'Billable-to customer ref: {"value": "42"}',
            },
        },
        "example": {"amount": 200.00, "description": "Fuel surcharge", "item_ref": "3"},
    },
    "JournalEntryLineDetail": {
        "used_by": ["journal_entry"],
        "default_for": "Journal entries (double-entry)",
        "fields": {
            "amount": {"type": "float", "required": True, "description": "Line amount"},
            "description": {"type": "str", "required": False, "description": "Line memo"},
            "detail_type": {
                "type": "str",
                "required": False,
                "description": "Override (defaults to JournalEntryLineDetail)",
            },
            "PostingType": {
                "type": "str",
                "required": True,
                "description": "'Debit' or 'Credit'",
            },
            "AccountRef": {
                "type": "dict",
                "required": True,
                "description": 'Account ref: {"value": "1"}',
            },
        },
        "example": {
            "amount": 500.00,
            "description": "Debit fuel expense",
            "PostingType": "Debit",
            "AccountRef": {"value": "64"},
        },
    },
    "DepositLineDetail": {
        "used_by": ["deposit"],
        "default_for": "Deposit transactions",
        "fields": {
            "amount": {"type": "float", "required": True, "description": "Deposit line amount"},
            "description": {"type": "str", "required": False, "description": "Line description"},
            "AccountRef": {
                "type": "dict",
                "required": True,
                "description": 'Income/source account ref: {"value": "1"}',
            },
        },
        "example": {
            "amount": 3000.00,
            "description": "Customer deposit",
            "AccountRef": {"value": "35"},
        },
    },
}

# Default detail type per tx_type (mirrors transaction._DEFAULT_DETAIL_TYPE)
_ERROR_CODES: dict[int, dict] = {
    400: {
        "meaning": "Bad request",
        "common_causes": [
            "Invalid field values",
            "Missing required fields",
            "Malformed query syntax",
        ],
        "recovery": (
            "Check field values and types. Use qbo_help(topic='fields') to verify field names."
        ),
    },
    401: {
        "meaning": "Authentication failed",
        "common_causes": [
            "Expired access token",
            "Invalid refresh token",
        ],
        "recovery": ("Re-run OAuth flow and update QBO_REFRESH_TOKEN in .env file."),
    },
    403: {
        "meaning": "Permission denied",
        "common_causes": [
            "Missing API scopes",
            "Wrong company/realm",
        ],
        "recovery": (
            "Verify QBO app has com.intuit.quickbooks.accounting scope and QBO_REALM_ID is correct."
        ),
    },
    404: {
        "meaning": "Entity not found",
        "common_causes": [
            "Wrong ID",
            "Entity was deleted",
        ],
        "recovery": ("Use the relevant list tool to find the correct ID."),
    },
    429: {
        "meaning": "Rate limited",
        "common_causes": ["Too many requests"],
        "recovery": ("Wait 60 seconds. Use qbo_bulk(operation='batch') to combine ops."),
    },
    500: {
        "meaning": "QBO internal error",
        "common_causes": ["Temporary QBO issue"],
        "recovery": ("Retry after a short delay. Check Intuit Developer status page."),
    },
    503: {
        "meaning": "QBO unavailable",
        "common_causes": ["QBO maintenance window"],
        "recovery": ("Retry with exponential backoff. Check Intuit status page."),
    },
}

_TX_DEFAULT_DETAIL: dict[str, str] = {
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
# Required params per tool/entity per operation
# ---------------------------------------------------------------------------

_REQUIRED_PARAMS: dict[str, dict[str, list[str]]] = {
    # --- Transaction types ---
    "invoice": {
        "list": [],
        "get": ["id"],
        "create": ["customer_ref", "line_items"],
        "update": ["id"],
        "delete": ["id"],
        "void": ["id"],
        "send": ["id", "email"],
        "pdf": ["id"],
        "search": ["query"],
        "search_line_items": ["keywords", "start_date", "end_date"],
    },
    "bill": {
        "list": [],
        "get": ["id"],
        "create": ["vendor_ref"],
        "update": ["id"],
        "delete": ["id"],
        "search": ["query"],
    },
    "bill_payment": {
        "list": [],
        "get": ["id"],
        "create": [],
        "update": ["id"],
        "delete": ["id"],
        "void": ["id"],
        "search": ["query"],
    },
    "payment": {
        "list": [],
        "get": ["id"],
        "create": ["customer_ref"],
        "update": ["id"],
        "void": ["id"],
        "search": ["query"],
    },
    "deposit": {
        "list": [],
        "get": ["id"],
        "create": [],
        "update": ["id"],
        "delete": ["id"],
        "search": ["query"],
    },
    "transfer": {
        "list": [],
        "get": ["id"],
        "create": [],
        "update": ["id"],
        "delete": ["id"],
        "search": ["query"],
    },
    "journal_entry": {
        "list": [],
        "get": ["id"],
        "create": ["line_items"],
        "update": ["id"],
        "delete": ["id"],
        "search": ["query"],
    },
    "purchase": {
        "list": [],
        "get": ["id"],
        "create": [],
        "update": ["id"],
        "delete": ["id"],
        "search": ["query"],
    },
    "estimate": {
        "list": [],
        "get": ["id"],
        "create": ["customer_ref"],
        "update": ["id"],
        "delete": ["id"],
        "send": ["id", "email"],
        "pdf": ["id"],
        "search": ["query"],
    },
    "credit_memo": {
        "list": [],
        "get": ["id"],
        "create": ["customer_ref"],
        "update": ["id"],
        "delete": ["id"],
        "search": ["query"],
    },
    "sales_receipt": {
        "list": [],
        "get": ["id"],
        "create": ["customer_ref"],
        "update": ["id"],
        "delete": ["id"],
        "void": ["id"],
        "send": ["id", "email"],
        "pdf": ["id"],
        "search": ["query"],
    },
    "refund_receipt": {
        "list": [],
        "get": ["id"],
        "create": ["customer_ref"],
        "update": ["id"],
        "delete": ["id"],
        "search": ["query"],
    },
    "vendor_credit": {
        "list": [],
        "get": ["id"],
        "create": ["vendor_ref"],
        "update": ["id"],
        "delete": ["id"],
        "search": ["query"],
    },
    # --- Party tools (qbo_customer, qbo_vendor, qbo_employee) ---
    "customer": {
        "list": [],
        "get": ["id"],
        "create": ["display_name"],
        "update": ["id"],
        "deactivate": ["id"],
        "search": ["query"],
    },
    "vendor": {
        "list": [],
        "get": ["id"],
        "create": ["display_name"],
        "update": ["id"],
        "deactivate": ["id"],
        "search": ["query"],
    },
    "employee": {
        "list": [],
        "get": ["id"],
        "create": ["given_name", "family_name"],
        "update": ["id"],
        "deactivate": ["id"],
        "search": ["query"],
    },
    # --- Entity tools (qbo_account, qbo_item) ---
    "account": {
        "list": [],
        "get": ["id"],
        "create": ["name", "account_type"],
        "update": ["id"],
        "deactivate": ["id"],
        "search": ["query"],
    },
    "item": {
        "list": [],
        "get": ["id"],
        "create": ["name", "item_type"],
        "update": ["id"],
        "deactivate": ["id"],
        "search": ["query"],
    },
}

# Map entity keys to their tool name for display
_ENTITY_TOOL_MAP: dict[str, str] = {
    "invoice": "qbo_invoice",
    "bill": "qbo_bill",
    "bill_payment": "qbo_bill_payment",
    "payment": "qbo_payment",
    "deposit": "qbo_deposit",
    "transfer": "qbo_transfer",
    "journal_entry": "qbo_journal_entry",
    "purchase": "qbo_purchase",
    "estimate": "qbo_estimate",
    "credit_memo": "qbo_credit_memo",
    "sales_receipt": "qbo_sales_receipt",
    "refund_receipt": "qbo_refund_receipt",
    "vendor_credit": "qbo_vendor_credit",
    "customer": "qbo_customer",
    "vendor": "qbo_vendor",
    "employee": "qbo_employee",
    "account": "qbo_account",
    "item": "qbo_item",
}


def register(mcp: FastMCP) -> None:
    """Register the qbo_help tool on *mcp*."""

    @mcp.tool(
        name="qbo_help",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def qbo_help(
        ctx: Context,
        topic: Literal[
            "fields",
            "operations",
            "query_syntax",
            "line_items",
            "required_params",
            "error_codes",
        ]
        | None = None,
        entity: str | None = None,
    ) -> dict | str:
        """Offline reference for QuickBooks field names, operation matrices, and IDS query syntax.

        No API calls are made. Use this before constructing search queries or
        creating transactions to discover the correct field names and available operations.

        Call with no arguments to see available topics and a quick-start guide.

        Args:
            topic: What to look up (omit to see all topics):
                - fields: List queryable field names for an entity.
                  Provide entity (e.g. 'Customer', 'Invoice', 'Account').
                  Omit entity to see all available entities.
                - operations: Show which operations each transaction type supports
                  (list, get, create, update, delete, void, send, pdf, search).
                - query_syntax: IDS query syntax guide with examples.
                - line_items: Line item schema per tx_type. Shows required vs
                  optional fields and the default detail type for each category.
                  Provide entity (tx_type, e.g. 'invoice', 'bill') to see the
                  schema for that specific type, or omit for all schemas.
                - required_params: Show required parameters per operation for
                  each tool. Provide entity (e.g. 'invoice', 'customer') to see
                  params for that specific entity, or omit for all tools.
                - error_codes: Common QBO HTTP error codes with meanings,
                  causes, and recovery steps.
            entity: Entity name for field lookup (e.g. 'Customer', 'Invoice').
                PascalCase or lowercase both work.
        """
        if topic is None:
            return {
                "topics": [
                    "fields",
                    "operations",
                    "query_syntax",
                    "line_items",
                    "required_params",
                    "error_codes",
                ],
                "quick_start": {
                    "search": (
                    "Use qbo_{entity}(operation='search', "
                    "query=\"Balance > '0'\"). "
                    "Example: qbo_invoice(operation='search', "
                    "query=\"Balance > '0'\") finds unpaid invoices. "
                    "Use qbo_invoice(operation='search_line_items', keywords=['emb'], "
                    "start_date='2026-01-01', end_date='2026-01-31') to search "
                    "invoice line descriptions."
                ),
                    "create": (
                        "Use qbo_{entity}(operation='create', ..., "
                        "preview=False). preview defaults to True "
                        "(dry-run) — set False to execute."
                    ),
                    "reference": (
                        "qbo_reference(operation='get_company_info') "
                        "for company details, 'list_terms' for "
                        "payment terms, 'list_payment_methods' for "
                        "payment methods."
                    ),
                },
                "note": ("Call qbo_help(topic='...') for detailed reference on any topic above."),
            }

        if topic == "fields":
            if entity:
                # Normalize: try PascalCase first, then title-case the input
                key = entity if entity in _FIELD_NAMES else entity.title().replace("_", "")
                if key not in _FIELD_NAMES:
                    available = sorted(_FIELD_NAMES.keys())
                    raise ToolError(
                        f"No field reference for '{entity}'. "
                        f"Available entities: {', '.join(available)}"
                    )
                return {
                    "entity": key,
                    "fields": _FIELD_NAMES[key],
                    "note": (
                        "Use these PascalCase field names in IDS search queries. "
                        + (_INVOICE_LINE_SEARCH_NOTE if key == "Invoice" else "")
                    ),
                }
            # No entity specified — list all
            return {
                "available_entities": sorted(_FIELD_NAMES.keys()),
                "usage": (
                    "Call qbo_help(topic='fields', entity='Customer') "
                    "to see fields for a specific entity."
                ),
            }

        if topic == "operations":
            matrix = {}
            for tx_type, ops in sorted(TX_OPERATION_MATRIX.items()):
                matrix[tx_type] = sorted(ops)
            return {
                "transaction_operation_matrix": matrix,
                "invoice_tool_only_operations": {
                    "qbo_invoice": ["search_line_items"],
                },
                "note": (
                    "All tx_types support list, get, create, update, delete, search. "
                    "void, send, pdf are only available for specific types as shown. "
                    "qbo_invoice also supports search_line_items for line description scans."
                ),
            }

        if topic == "query_syntax":
            return {
                "guide": _IDS_SYNTAX_GUIDE,
                "common_fields": {
                    "customers_vendors": "DisplayName, CompanyName, Balance, Active",
                    "transactions": "DocNumber, TxnDate, DueDate, TotalAmt, Balance",
                    "accounts": "Name, AccountType, CurrentBalance, Active",
                    "items": "Name, Type, UnitPrice, Active",
                },
                "note": (
                    "Use qbo_help(topic='fields', entity='...') for the full field list per entity. "
                    + _INVOICE_LINE_SEARCH_NOTE
                ),
            }

        if topic == "line_items":
            if entity:
                tx_type = entity.lower().replace(" ", "_")
                detail_type = _TX_DEFAULT_DETAIL.get(tx_type)
                if detail_type is None:
                    available = sorted(_TX_DEFAULT_DETAIL.keys())
                    raise ToolError(
                        f"No line_items schema for '{entity}'. "
                        f"Available tx_types: {', '.join(available)}"
                    )
                schema = _LINE_ITEM_SCHEMAS[detail_type]
                return {
                    "tx_type": tx_type,
                    "default_detail_type": detail_type,
                    "fields": schema["fields"],
                    "example": schema["example"],
                    "note": (
                        "Pass line_items as a list of dicts. "
                        "detail_type defaults automatically based on tx_type."
                    ),
                }
            # No entity — return all schemas with tx_type mapping
            return {
                "tx_type_defaults": _TX_DEFAULT_DETAIL,
                "schemas": _LINE_ITEM_SCHEMAS,
                "note": (
                    "Each tx_type auto-selects a default detail type. "
                    "Use entity param to see the schema for a specific tx_type. "
                    "Pass line_items as a list of dicts to the relevant transaction tool "
                    "(e.g. qbo_invoice, qbo_bill)."
                ),
            }

        if topic == "required_params":
            if entity:
                key = entity.lower().replace(" ", "_")
                if key not in _REQUIRED_PARAMS:
                    available = sorted(_REQUIRED_PARAMS.keys())
                    raise ToolError(
                        f"No required_params reference for '{entity}'. "
                        f"Available entities: {', '.join(available)}"
                    )
                tool_name = _ENTITY_TOOL_MAP[key]
                _no_delete = {
                    "customer",
                    "vendor",
                    "employee",
                    "account",
                    "item",
                }
                note = (
                    f"Shows required params for each operation on "
                    f"{key} via {tool_name}. An empty list means no "
                    f"required params beyond the operation itself."
                )
                if key in _no_delete:
                    note += (
                        f" Note: 'delete' is not available for {key} — use 'deactivate' instead."
                    )
                return {
                    "entity": key,
                    "tool": tool_name,
                    "required_params": _REQUIRED_PARAMS[key],
                    "note": (
                        note
                        + (
                            " search_line_items requires keywords, start_date, and end_date."
                            if key == "invoice"
                            else ""
                        )
                    ),
                }
            # No entity — return all
            grouped: dict[str, dict] = {}
            for ent_key, ops in sorted(_REQUIRED_PARAMS.items()):
                tool_name = _ENTITY_TOOL_MAP[ent_key]
                if tool_name not in grouped:
                    grouped[tool_name] = {}
                grouped[tool_name][ent_key] = ops
            return {
                "tools": grouped,
                "note": (
                    "Required parameters per operation for all QBO tools. "
                    "Use entity param to narrow to a specific entity. "
                    "An empty list means no required params beyond the operation itself."
                ),
            }

        if topic == "error_codes":
            return {
                "error_codes": {str(code): info for code, info in _ERROR_CODES.items()},
                "note": (
                    "Common QBO API HTTP status codes. Check the recovery field for next steps."
                ),
            }

        raise ToolError(
            f"Unknown topic '{topic}'. "
            "Valid: fields, operations, query_syntax, "
            "line_items, required_params, error_codes"
        )
