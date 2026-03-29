"""qbo_vendor tool — manage QuickBooks Online vendors."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

from fastmcp import Context
from fastmcp.exceptions import ToolError

from quickbooks_mcp.converters import qbo_to_snake
from quickbooks_mcp.errors import format_qbo_error
from quickbooks_mcp.formatting import format_response, paginate_list, truncate_response
from quickbooks_mcp.models import ERROR_SHAPE_HINT, IDS_QUERY_RULES, PROTECTED_KEYS, SEARCH_EXAMPLES

if TYPE_CHECKING:
    from fastmcp import FastMCP

logger = logging.getLogger(__name__)

ENTITY_TYPE = "Vendor"


def _get_class():
    """Lazily import and return the python-quickbooks Vendor class."""
    from quickbooks.objects.vendor import Vendor

    return Vendor


# ---------------------------------------------------------------------------
# Tool description
# ---------------------------------------------------------------------------

_TOOL_DESCRIPTION = (
    "Manage QuickBooks Online vendors. "
    "Operations: list (paginated), get (by id), create, "
    "update (auto-fetches SyncToken), "
    "deactivate (sets Active=False), search (IDS query). "
    "Operations include 'deactivate' (not 'delete') — QBO does "
    "not allow permanent deletion of vendors. "
    f"Search uses IDS query syntax — {IDS_QUERY_RULES} "
    f"{SEARCH_EXAMPLES['vendor']} "
    f"{ERROR_SHAPE_HINT}"
)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(mcp: FastMCP) -> None:
    """Register the qbo_vendor tool on *mcp*."""
    from quickbooks_mcp.server import get_client  # noqa: PLC0415

    @mcp.tool(
        name="qbo_vendor",
        description=_TOOL_DESCRIPTION,
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    async def qbo_vendor(
        ctx: Context,
        operation: Literal["list", "get", "create", "update", "deactivate", "search"],
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
        """Create, read, update, deactivate, or search QuickBooks Online vendors.

        Args:
            operation: Action to perform. One of:
                - list: Paginated list of vendors.
                - get: Fetch a single vendor by id.
                - create: Create a new vendor with supplied fields.
                - update: Merge supplied fields onto an existing vendor (id required).
                - deactivate: Set Active=False on a vendor (id required).
                - search: Run a raw IDS query against the Vendor table.
            id: QBO entity ID (numeric string, e.g. '42') — required
                for get, update, deactivate.
            display_name: Full display name for create/update.
            email: Primary email address for create/update.
            phone: Primary phone number for create/update.
            company_name: Company/business name for create/update.
            active_only: When listing, include only active records (default True).
            query: IDS WHERE clause for search (e.g. "DisplayName LIKE '%Smith%'").
            max_results: Maximum records to return for list (default 20).
            offset: Zero-based start offset for list pagination (default 0).
            extra: Optional dict with additional QBO fields.
                Protected keys (Id, SyncToken, domain, sparse, MetaData, TxnDate)
                are rejected to prevent accidental corruption.
            response_format: 'json' for structured dict (default), 'markdown' for
                human-readable text.
        """
        # Validate extra dict if provided.
        extra_dict: dict = {}
        if extra:
            if not isinstance(extra, dict):
                raise ToolError("'extra' must be a dict, not a list or scalar.")
            bad_keys = PROTECTED_KEYS & extra.keys()
            if bad_keys:
                raise ToolError(
                    f"'extra' contains protected keys that cannot be set directly: "
                    f"{sorted(bad_keys)}. Remove them and retry."
                )
            extra_dict = extra

        client = get_client(ctx)

        try:
            if operation == "list":
                return await _list(client, active_only, max_results, offset, response_format)
            elif operation == "get":
                if not id:
                    raise ToolError("'id' is required for operation='get'.")
                return await _get(client, id, response_format)
            elif operation == "create":
                return await _create(
                    client,
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
                return await _deactivate(client, id, response_format)
            elif operation == "search":
                if not query:
                    raise ToolError("'query' is required for operation='search'.")
                return await _search(client, query, response_format)
        except ToolError:
            raise
        except Exception as exc:
            error = format_qbo_error(exc, operation, ENTITY_TYPE)
            return error

        raise ToolError(f"Unhandled operation: {operation}")  # pragma: no cover


# ---------------------------------------------------------------------------
# Operation handlers
# ---------------------------------------------------------------------------


async def _list(
    client,
    active_only: bool,
    max_results: int,
    offset: int,
    response_format: str,
) -> dict | str:
    cls = _get_class()
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
    meta["start_position"] = start_position
    response = format_response(
        items, "list", ENTITY_TYPE, metadata=meta, response_format=response_format
    )
    if isinstance(response, dict):
        response = truncate_response(response)
    return response


async def _get(
    client,
    id: str,
    response_format: str,
) -> dict | str:
    cls = _get_class()
    result = await client.execute(cls.get, id, qb=client.qb_client)
    data = qbo_to_snake(result.to_dict())
    return format_response(data, "get", ENTITY_TYPE, response_format=response_format)


async def _create(
    client,
    display_name: str | None,
    email: str | None,
    phone: str | None,
    company_name: str | None,
    extra_dict: dict,
    response_format: str,
) -> dict | str:
    cls = _get_class()

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
    return format_response(data, "create", ENTITY_TYPE, response_format=response_format)


async def _update(
    client,
    id: str,
    display_name: str | None,
    email: str | None,
    phone: str | None,
    company_name: str | None,
    extra_dict: dict,
    response_format: str,
) -> dict | str:
    cls = _get_class()

    def _do_update():
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
    return format_response(data, "update", ENTITY_TYPE, response_format=response_format)


async def _deactivate(
    client,
    id: str,
    response_format: str,
) -> dict | str:
    cls = _get_class()

    def _do_deactivate():
        obj = cls.get(id, qb=client.qb_client)
        obj.Active = False
        obj.save(qb=client.qb_client)
        return obj

    result = await client.execute(_do_deactivate)
    data = qbo_to_snake(result.to_dict())
    return format_response(data, "deactivate", ENTITY_TYPE, response_format=response_format)


async def _search(
    client,
    query: str,
    response_format: str,
) -> dict | str:
    full_query = f"SELECT * FROM {ENTITY_TYPE} WHERE {query}"

    results = await client.execute(client.qb_client.query, full_query)
    items = [
        qbo_to_snake(r) if isinstance(r, dict) else qbo_to_snake(r.to_dict())
        for r in (results or [])
    ]
    response = format_response(
        items,
        "search",
        ENTITY_TYPE,
        metadata={"query": full_query},
        response_format=response_format,
    )
    if isinstance(response, dict):
        response = truncate_response(response)
    return response
