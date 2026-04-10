"""qbo_item tool — products and services in QuickBooks Online."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

from fastmcp import Context
from fastmcp.exceptions import ToolError
from quickbooks.objects.item import Item

from quickbooks_mcp.converters import qbo_to_snake
from quickbooks_mcp.errors import format_qbo_error
from quickbooks_mcp.formatting import format_response, paginate_list, truncate_response
from quickbooks_mcp.models import (
    ERROR_SHAPE_HINT,
    IDS_QUERY_RULES,
    ITEM_TYPE_MAP,
    PROTECTED_KEYS,
    SEARCH_EXAMPLES,
    VALID_ITEM_TYPES,
)

if TYPE_CHECKING:
    from fastmcp import FastMCP

logger = logging.getLogger(__name__)

_ENTITY_TYPE = "Item"

_TOOL_DESCRIPTION = (
    "Manage QuickBooks Online products and services (Items). "
    "Supports list, get, create, update, deactivate, and search operations. "
    "Item types: service (labour/fees), non_inventory (goods not tracked), "
    "inventory (tracked stock). "
    "Use income_account_ref and expense_account_ref to link chart-of-accounts entries. "
    f"{IDS_QUERY_RULES} "
    f"{SEARCH_EXAMPLES['item']} "
    f"{ERROR_SHAPE_HINT}"
)


def register(mcp: FastMCP) -> None:
    """Register the qbo_item tool on *mcp*."""
    from quickbooks_mcp.server import get_client

    @mcp.tool(
        name="qbo_item",
        description=_TOOL_DESCRIPTION,
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    async def qbo_item(
        ctx: Context,
        operation: Literal["list", "get", "create", "update", "deactivate", "search"],
        id: str | None = None,
        name: str | None = None,
        item_type: VALID_ITEM_TYPES | None = None,
        description: str | None = None,
        unit_price: float | None = None,
        income_account_ref: str | None = None,
        expense_account_ref: str | None = None,
        active_only: bool = True,
        query: str | None = None,
        max_results: int = 20,
        offset: int = 0,
        extra: dict | None = None,
        response_format: Literal["json", "markdown"] = "json",
    ) -> dict | str:
        """Manage QuickBooks Online products and services.

        Args:
            operation: What to do. One of:
                - list: Return active (or all) items with pagination.
                - get: Fetch a single item by ID.
                - create: Create a new item. Requires name and item_type.
                - update: Update fields on an existing item. Requires id.
                - deactivate: Mark an item inactive (soft-delete). Requires id.
                - search: Run an IDS query. Requires query.
            id: QBO entity ID (numeric string, e.g. '42') — required
                for get, update, deactivate.
            name: Item name — required for create, optional for update.
            item_type: One of 'service', 'non_inventory', 'inventory' — required for create.
            description: Item description shown on transactions.
            unit_price: Default unit price / rate.
            income_account_ref: Account ID (numeric string from
                qbo_account list) for income (sales) side.
            expense_account_ref: Account ID (numeric string from
                qbo_account list) for expense (COGS) side.
            active_only: If True (default) list only active items.
            query: IDS WHERE clause for search, e.g. "Name LIKE '%freight%'".
            max_results: Page size (default 20).
            offset: Zero-based offset for pagination (default 0).
            extra: Optional dict of additional QBO fields to merge
                (protected keys Id, SyncToken, MetaData, etc. are rejected).
            response_format: 'json' for structured dict (default), 'markdown' for
                human-readable text.
        """
        client = get_client(ctx)

        # Validate extra against protected keys.
        extra_dict: dict = extra or {}
        if extra_dict:
            bad_keys = PROTECTED_KEYS & set(extra_dict)
            if bad_keys:
                raise ToolError(
                    f"extra contains protected key(s): {sorted(bad_keys)}. Remove them and retry."
                )

        try:
            if operation == "list":
                return await _list_items(client, active_only, max_results, offset, response_format)
            elif operation == "get":
                if not id:
                    raise ToolError("id is required for get.")
                return await _get_item(client, id, response_format)
            elif operation == "create":
                if not name:
                    raise ToolError("name is required for create.")
                if not item_type:
                    raise ToolError("item_type is required for create.")
                return await _create_item(
                    client,
                    name,
                    item_type,
                    description,
                    unit_price,
                    income_account_ref,
                    expense_account_ref,
                    extra_dict,
                    response_format,
                )
            elif operation == "update":
                if not id:
                    raise ToolError("id is required for update.")
                return await _update_item(
                    client,
                    id,
                    name,
                    description,
                    unit_price,
                    income_account_ref,
                    expense_account_ref,
                    extra_dict,
                    response_format,
                )
            elif operation == "deactivate":
                if not id:
                    raise ToolError("id is required for deactivate.")
                return await _deactivate_item(client, id, response_format)
            elif operation == "search":
                if not query:
                    raise ToolError("query is required for search.")
                return await _search_items(client, query, max_results, offset, response_format)
        except ToolError:
            raise
        except Exception as exc:
            error = format_qbo_error(exc, operation, _ENTITY_TYPE)
            return error

        raise ToolError(f"Unhandled operation: {operation}")  # pragma: no cover


# ---------------------------------------------------------------------------
# Operation handlers
# ---------------------------------------------------------------------------


async def _list_items(
    client: object,
    active_only: bool,
    max_results: int,
    offset: int,
    response_format: str,
) -> dict | str:
    def _fetch() -> list:
        kwargs: dict = {
            "max_results": max_results,
            "start_position": offset + 1,
            "qb": client.qb_client,
        }  # type: ignore[attr-defined]
        if active_only:
            kwargs["Active"] = True
        return Item.filter(**kwargs)

    results = await client.execute(_fetch)  # type: ignore[attr-defined]
    items = [qbo_to_snake(r.to_dict()) for r in (results or [])]
    total = len(items)
    page, meta = paginate_list(items, total, offset=0, limit=max_results)
    response = format_response(
        page, "list", _ENTITY_TYPE, metadata=meta, response_format=response_format
    )
    if isinstance(response, dict):
        response = truncate_response(response)
    return response


async def _get_item(client: object, id: str, response_format: str) -> dict | str:
    result = await client.execute(Item.get, id, qb=client.qb_client)  # type: ignore[attr-defined]
    data = qbo_to_snake(result.to_dict())
    return format_response(data, "get", _ENTITY_TYPE, response_format=response_format)


async def _create_item(
    client: object,
    name: str,
    item_type: str,
    description: str | None,
    unit_price: float | None,
    income_account_ref: str | None,
    expense_account_ref: str | None,
    extra_dict: dict,
    response_format: str,
) -> dict | str:
    def _build_and_save() -> object:
        item = Item()
        item.Name = name
        item.Type = ITEM_TYPE_MAP[item_type]
        if description is not None:
            item.Description = description
        if unit_price is not None:
            item.UnitPrice = unit_price
        if income_account_ref:
            item.IncomeAccountRef = {"value": income_account_ref}
        if expense_account_ref:
            item.ExpenseAccountRef = {"value": expense_account_ref}
        for k, v in extra_dict.items():
            setattr(item, k, v)
        return item.save(qb=client.qb_client)  # type: ignore[attr-defined]

    result = await client.execute(_build_and_save)  # type: ignore[attr-defined]
    data = qbo_to_snake(result.to_dict())
    return format_response(data, "create", _ENTITY_TYPE, response_format=response_format)


async def _update_item(
    client: object,
    id: str,
    name: str | None,
    description: str | None,
    unit_price: float | None,
    income_account_ref: str | None,
    expense_account_ref: str | None,
    extra_dict: dict,
    response_format: str,
) -> dict | str:
    # Fetch first to get current SyncToken (required for optimistic-concurrency).
    existing = await client.execute(Item.get, id, qb=client.qb_client)  # type: ignore[attr-defined]

    def _apply_and_save() -> object:
        if name is not None:
            existing.Name = name
        if description is not None:
            existing.Description = description
        if unit_price is not None:
            existing.UnitPrice = unit_price
        if income_account_ref is not None:
            existing.IncomeAccountRef = {"value": income_account_ref}
        if expense_account_ref is not None:
            existing.ExpenseAccountRef = {"value": expense_account_ref}
        for k, v in extra_dict.items():
            setattr(existing, k, v)
        return existing.save(qb=client.qb_client)  # type: ignore[attr-defined]

    result = await client.execute(_apply_and_save)  # type: ignore[attr-defined]
    data = qbo_to_snake(result.to_dict())
    return format_response(data, "update", _ENTITY_TYPE, response_format=response_format)


async def _deactivate_item(client: object, id: str, response_format: str) -> dict | str:
    existing = await client.execute(Item.get, id, qb=client.qb_client)  # type: ignore[attr-defined]

    def _deactivate_and_save() -> object:
        existing.Active = False
        return existing.save(qb=client.qb_client)  # type: ignore[attr-defined]

    result = await client.execute(_deactivate_and_save)  # type: ignore[attr-defined]
    data = qbo_to_snake(result.to_dict())
    return format_response(data, "deactivate", _ENTITY_TYPE, response_format=response_format)


async def _search_items(
    client: object,
    query: str,
    max_results: int,
    offset: int,
    response_format: str,
) -> dict | str:
    iql = f"SELECT * FROM Item WHERE {query}"
    rows = await client.query_rows(iql, _ENTITY_TYPE)  # type: ignore[attr-defined]
    items = [qbo_to_snake(row) for row in rows]
    total = len(items)
    page, meta = paginate_list(items, total, offset=offset, limit=max_results)
    meta["query"] = iql
    response = format_response(
        page, "search", _ENTITY_TYPE, metadata=meta, response_format=response_format
    )
    if isinstance(response, dict):
        response = truncate_response(response)
    return response
