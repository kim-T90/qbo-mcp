"""qbo_reference tool — read-only lookup/reference data from QuickBooks Online."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from fastmcp import Context
from fastmcp.exceptions import ToolError

from quickbooks_mcp.converters import qbo_to_snake
from quickbooks_mcp.errors import format_qbo_error
from quickbooks_mcp.formatting import format_response

if TYPE_CHECKING:
    from fastmcp import FastMCP

# Valid operations exposed by this tool.
_OPERATIONS = (
    "list_tax_codes",
    "list_classes",
    "list_departments",
    "list_terms",
    "list_payment_methods",
    "get_company_info",
    "get_preferences",
)

_TOOL_DESCRIPTION = (
    "Lookup reference / configuration data from QuickBooks Online. "
    "Use this tool to retrieve static lists (tax codes, classes, departments, terms, "
    "payment methods) and company-level settings (company info, preferences). "
    "All data is read-only — no records are created or modified. "
    f"Valid operations: {', '.join(_OPERATIONS)}. "
    "Use get_company_info to verify the QBO connection and identify the active company."
)


def register(mcp: FastMCP) -> None:
    """Register the qbo_reference tool on *mcp*."""

    @mcp.tool(
        name="qbo_reference",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def qbo_reference(
        ctx: Context,
        operation: Literal[
            "list_tax_codes",
            "list_classes",
            "list_departments",
            "list_terms",
            "list_payment_methods",
            "get_company_info",
            "get_preferences",
        ],
        response_format: Literal["json", "markdown"] = "json",
    ) -> dict | str:
        """Lookup reference data from QuickBooks Online.

        Read-only access to QBO configuration lists and company settings.
        No records are created or modified.

        Args:
            operation: What to fetch. One of:
                - list_tax_codes: All tax codes defined in QBO.
                - list_classes: All classes (used for tracking/categorisation).
                - list_departments: All departments (locations/business units).
                - list_terms: All payment terms (e.g. Net 30, Due on receipt).
                - list_payment_methods: All payment methods (e.g. Check, Credit Card).
                - get_company_info: Company profile: name, address, fiscal year start.
                - get_preferences: QBO account-wide preference settings.
            response_format: 'json' for structured dict (default), 'markdown' for
                human-readable text.
        """
        if operation not in _OPERATIONS:
            raise ToolError(
                f"Invalid operation '{operation}'. Valid operations: {', '.join(_OPERATIONS)}"
            )

        from quickbooks_mcp.server import get_client  # deferred to avoid circular import

        client = get_client(ctx)

        try:
            if operation == "list_tax_codes":
                return await _list_tax_codes(client, response_format)
            elif operation == "list_classes":
                return await _list_classes(client, response_format)
            elif operation == "list_departments":
                return await _list_departments(client, response_format)
            elif operation == "list_terms":
                return await _list_terms(client, response_format)
            elif operation == "list_payment_methods":
                return await _list_payment_methods(client, response_format)
            elif operation == "get_company_info":
                return await _get_company_info(client, response_format)
            elif operation == "get_preferences":
                return await _get_preferences(client, response_format)
        except ToolError:
            raise
        except Exception as exc:
            entity_type = _operation_to_entity(operation)
            error = format_qbo_error(exc, operation, entity_type)
            return error

        # Unreachable — satisfies type checkers.
        raise ToolError(f"Unhandled operation: {operation}")  # pragma: no cover


# ---------------------------------------------------------------------------
# Operation handlers
# ---------------------------------------------------------------------------


def _operation_to_entity(operation: str) -> str:
    """Map an operation name to a QBO entity type string."""
    _map = {
        "list_tax_codes": "TaxCode",
        "list_classes": "Class",
        "list_departments": "Department",
        "list_terms": "Term",
        "list_payment_methods": "PaymentMethod",
        "get_company_info": "CompanyInfo",
        "get_preferences": "Preferences",
    }
    return _map.get(operation, operation)


async def _list_tax_codes(client: object, response_format: str) -> dict | str:
    from quickbooks.objects.taxcode import TaxCode

    results = await client.execute(TaxCode.all, qb=client.qb_client)  # type: ignore[attr-defined]
    items = [qbo_to_snake(r.to_dict()) for r in (results or [])]
    return format_response(items, "list_tax_codes", "TaxCode", response_format=response_format)


async def _list_classes(client: object, response_format: str) -> dict | str:
    # python-quickbooks does not ship a Class object; use raw IDS query.
    rows = await client.query_rows("SELECT * FROM Class", "Class")  # type: ignore[attr-defined]
    items = [qbo_to_snake(row) for row in rows]
    return format_response(items, "list_classes", "Class", response_format=response_format)


async def _list_departments(client: object, response_format: str) -> dict | str:
    from quickbooks.objects.department import Department

    results = await client.execute(Department.all, qb=client.qb_client)  # type: ignore[attr-defined]
    items = [qbo_to_snake(r.to_dict()) for r in (results or [])]
    return format_response(items, "list_departments", "Department", response_format=response_format)


async def _list_terms(client: object, response_format: str) -> dict | str:
    from quickbooks.objects.term import Term

    results = await client.execute(Term.all, qb=client.qb_client)  # type: ignore[attr-defined]
    items = [qbo_to_snake(r.to_dict()) for r in (results or [])]
    return format_response(items, "list_terms", "Term", response_format=response_format)


async def _list_payment_methods(client: object, response_format: str) -> dict | str:
    from quickbooks.objects.paymentmethod import PaymentMethod

    results = await client.execute(PaymentMethod.all, qb=client.qb_client)  # type: ignore[attr-defined]
    items = [qbo_to_snake(r.to_dict()) for r in (results or [])]
    return format_response(
        items, "list_payment_methods", "PaymentMethod", response_format=response_format
    )


async def _get_company_info(client: object, response_format: str) -> dict | str:
    from quickbooks.objects.company_info import CompanyInfo

    result = await client.execute(CompanyInfo.get, 1, qb=client.qb_client)  # type: ignore[attr-defined]
    data = qbo_to_snake(result.to_dict())
    return format_response(data, "get_company_info", "CompanyInfo", response_format=response_format)


async def _get_preferences(client: object, response_format: str) -> dict | str:
    from quickbooks.objects.preferences import Preferences

    result = await client.execute(Preferences.get, 1, qb=client.qb_client)  # type: ignore[attr-defined]
    data = qbo_to_snake(result.to_dict())
    return format_response(data, "get_preferences", "Preferences", response_format=response_format)
