"""qbo_party tool — DEPRECATED. Use qbo_customer, qbo_vendor, or qbo_employee instead."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

from fastmcp import Context
from fastmcp.exceptions import ToolError

from quickbooks_mcp.converters import qbo_to_snake
from quickbooks_mcp.errors import format_qbo_error
from quickbooks_mcp.formatting import format_response, paginate_list, truncate_response
from quickbooks_mcp.models import IDS_QUERY_RULES, PARTY_CLASS_MAP
from quickbooks_mcp.tools._base import validate_extra

if TYPE_CHECKING:
    from fastmcp import FastMCP

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Party class imports
# ---------------------------------------------------------------------------

_PARTY_IMPORTS: dict[str, tuple[str, str]] = {
    "customer": ("quickbooks.objects.customer", "Customer"),
    "vendor": ("quickbooks.objects.vendor", "Vendor"),
    "employee": ("quickbooks.objects.employee", "Employee"),
}


def _get_party_class(party_type: str):  # type: ignore[return]
    """Lazily import and return the python-quickbooks class for *party_type*."""
    module_path, class_name = _PARTY_IMPORTS[party_type]
    import importlib

    module = importlib.import_module(module_path)
    return getattr(module, class_name)


# ---------------------------------------------------------------------------
# Tool description
# ---------------------------------------------------------------------------

_TOOL_DESCRIPTION = (
    "[DEPRECATED — will be removed 2026-05-01. "
    "Use qbo_customer, qbo_vendor, or qbo_employee instead] "
    "Manage QuickBooks Online customers, vendors, and employees. "
    "All party types share a single tool — specify party_type to select the entity. "
    "Operations: list (paginated), get (by id), create, update (auto-fetches SyncToken), "
    "deactivate (sets Active=False), search (IDS query). "
    f"Search uses IDS query syntax — {IDS_QUERY_RULES}"
)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(mcp: FastMCP) -> None:
    """Register the qbo_party tool on *mcp*."""
    # Deferred import to avoid circular dependency: server imports tools/__init__.py
    # which calls register_all() before this module has finished loading.
    from quickbooks_mcp.server import get_client  # noqa: PLC0415

    @mcp.tool(
        name="qbo_party",
        description=_TOOL_DESCRIPTION,
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    async def qbo_party(
        ctx: Context,
        operation: Literal["list", "get", "create", "update", "deactivate", "search"],
        party_type: Literal["customer", "vendor", "employee"],
        id: str | None = None,
        display_name: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        company_name: str | None = None,
        active_only: bool = True,
        query: str | None = None,
        max_results: int = 20,
        offset: int = 0,
        extra: dict | None = None,
        response_format: Literal["json", "markdown"] = "json",
    ) -> dict | str:
        """Create, read, update, deactivate, or search QuickBooks Online parties.

        Args:
            operation: Action to perform. One of:
                - list: Paginated list of parties.
                - get: Fetch a single party by id.
                - create: Create a new party with supplied fields.
                - update: Merge supplied fields onto an existing party (id required).
                - deactivate: Set Active=False on a party (id required).
                - search: Run a raw IDS query against the party table.
            party_type: Entity type — 'customer', 'vendor', or 'employee'.
            id: Entity ID for get, update, and deactivate operations.
            display_name: Full display name for create/update.
            email: Primary email address for create/update.
            phone: Primary phone number for create/update.
            company_name: Company/business name for create/update.
            active_only: When listing, include only active records (default True).
            query: IDS WHERE clause for search (e.g. "DisplayName LIKE '%Smith%'").
            max_results: Maximum records to return for list (default 20).
            offset: Zero-based start offset for list pagination (default 0).
            extra: Optional dict of additional QBO fields.
                Protected keys (Id, SyncToken, domain, sparse, MetaData, TxnDate)
                are rejected to prevent accidental corruption.
            response_format: 'json' for structured dict (default), 'markdown' for
                human-readable text.
        """
        if party_type not in PARTY_CLASS_MAP:
            raise ToolError(
                f"Invalid party_type '{party_type}'. Valid values: {', '.join(PARTY_CLASS_MAP)}"
            )

        extra_dict = validate_extra(extra)

        entity_type = PARTY_CLASS_MAP[party_type]
        client = get_client(ctx)

        try:
            if operation == "list":
                return await _list(
                    client,
                    party_type,
                    entity_type,
                    active_only,
                    max_results,
                    offset,
                    response_format,
                )
            elif operation == "get":
                if not id:
                    raise ToolError("'id' is required for operation='get'.")
                return await _get(client, party_type, entity_type, id, response_format)
            elif operation == "create":
                return await _create(
                    client,
                    party_type,
                    entity_type,
                    display_name,
                    email,
                    phone,
                    company_name,
                    extra_dict,
                    response_format,
                )
            elif operation == "update":
                if not id:
                    raise ToolError("'id' is required for operation='update'.")
                return await _update(
                    client,
                    party_type,
                    entity_type,
                    id,
                    display_name,
                    email,
                    phone,
                    company_name,
                    extra_dict,
                    response_format,
                )
            elif operation == "deactivate":
                if not id:
                    raise ToolError("'id' is required for operation='deactivate'.")
                return await _deactivate(client, party_type, entity_type, id, response_format)
            elif operation == "search":
                if not query:
                    raise ToolError("'query' is required for operation='search'.")
                return await _search(client, entity_type, query, response_format)
        except ToolError:
            raise
        except Exception as exc:
            error = format_qbo_error(exc, operation, entity_type)
            return error

        raise ToolError(f"Unhandled operation: {operation}")  # pragma: no cover


# ---------------------------------------------------------------------------
# Operation handlers
# ---------------------------------------------------------------------------


async def _list(
    client,
    party_type: str,
    entity_type: str,
    active_only: bool,
    max_results: int,
    offset: int,
    response_format: str,
) -> dict | str:
    cls = _get_party_class(party_type)
    start_position = offset + 1

    def _fetch():
        kwargs = {
            "max_results": max_results,
            "start_position": start_position,
            "qb": client.qb_client,
        }
        if active_only:
            kwargs["Active"] = True
        return cls.filter(**kwargs)

    results = await client.execute(_fetch)
    items = [qbo_to_snake(r.to_dict()) for r in (results or [])]
    _page, meta = paginate_list(items, total=len(items), offset=0, limit=max_results)
    # Adjust metadata for the server-side pagination we asked for.
    meta["start_position"] = start_position
    response = format_response(
        items, "list", entity_type, metadata=meta, response_format=response_format
    )
    if isinstance(response, dict):
        response = truncate_response(response)
    return response


async def _get(
    client,
    party_type: str,
    entity_type: str,
    id: str,
    response_format: str,
) -> dict | str:
    cls = _get_party_class(party_type)
    result = await client.execute(cls.get, id, qb=client.qb_client)
    data = qbo_to_snake(result.to_dict())
    return format_response(data, "get", entity_type, response_format=response_format)


async def _create(
    client,
    party_type: str,
    entity_type: str,
    display_name: str | None,
    email: str | None,
    phone: str | None,
    company_name: str | None,
    extra_dict: dict,
    response_format: str,
) -> dict | str:
    cls = _get_party_class(party_type)

    def _do_create():
        obj = cls()
        if display_name is not None:
            obj.DisplayName = display_name
        if email is not None:
            obj.PrimaryEmailAddr = {"Address": email}
        if phone is not None:
            obj.PrimaryPhone = {"FreeFormNumber": phone}
        if company_name is not None:
            obj.CompanyName = company_name
        for key, value in extra_dict.items():
            setattr(obj, key, value)
        obj.save(qb=client.qb_client)
        return obj

    result = await client.execute(_do_create)
    data = qbo_to_snake(result.to_dict())
    return format_response(data, "create", entity_type, response_format=response_format)


async def _update(
    client,
    party_type: str,
    entity_type: str,
    id: str,
    display_name: str | None,
    email: str | None,
    phone: str | None,
    company_name: str | None,
    extra_dict: dict,
    response_format: str,
) -> dict | str:
    cls = _get_party_class(party_type)

    def _do_update():
        # Auto-fetch to get current SyncToken.
        obj = cls.get(id, qb=client.qb_client)
        if display_name is not None:
            obj.DisplayName = display_name
        if email is not None:
            obj.PrimaryEmailAddr = {"Address": email}
        if phone is not None:
            obj.PrimaryPhone = {"FreeFormNumber": phone}
        if company_name is not None:
            obj.CompanyName = company_name
        for key, value in extra_dict.items():
            setattr(obj, key, value)
        obj.save(qb=client.qb_client)
        return obj

    result = await client.execute(_do_update)
    data = qbo_to_snake(result.to_dict())
    return format_response(data, "update", entity_type, response_format=response_format)


async def _deactivate(
    client,
    party_type: str,
    entity_type: str,
    id: str,
    response_format: str,
) -> dict | str:
    cls = _get_party_class(party_type)

    def _do_deactivate():
        obj = cls.get(id, qb=client.qb_client)
        obj.Active = False
        obj.save(qb=client.qb_client)
        return obj

    result = await client.execute(_do_deactivate)
    data = qbo_to_snake(result.to_dict())
    return format_response(data, "deactivate", entity_type, response_format=response_format)


async def _search(
    client,
    entity_type: str,
    query: str,
    response_format: str,
) -> dict | str:
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
