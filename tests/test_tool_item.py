"""Tests for the qbo_item tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.exceptions import ToolError

from quickbooks_mcp.tools.item import (
    _create_item,
    _deactivate_item,
    _get_item,
    _list_items,
    _search_items,
    _update_item,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_item_obj(
    id_: str = "10",
    name: str = "Freight Service",
    item_type: str = "Service",
    unit_price: float = 150.0,
    active: bool = True,
    sync_token: str = "3",
) -> MagicMock:
    """Return a mock python-quickbooks Item object."""
    obj = MagicMock()
    obj.to_dict.return_value = {
        "Id": id_,
        "Name": name,
        "Type": item_type,
        "UnitPrice": unit_price,
        "Active": active,
        "SyncToken": sync_token,
    }
    return obj


def _make_client() -> MagicMock:
    """Return a mock QBOClient with execute wired up synchronously."""
    client = MagicMock()
    client.qb_client = MagicMock()

    async def _execute(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    client.execute = _execute
    client.query_rows = AsyncMock(return_value=[])
    client.query_count = AsyncMock()
    return client


def _get_tool_fn():
    """Register qbo_item on a mock mcp and return the raw coroutine."""
    from quickbooks_mcp.tools.item import register

    fake_mcp = MagicMock()
    captured = {}

    def fake_tool(**kwargs):
        def decorator(fn):
            captured["fn"] = fn
            return fn

        return decorator

    fake_mcp.tool = fake_tool
    register(fake_mcp)
    return captured["fn"]


# ---------------------------------------------------------------------------
# 1. list returns paginated items
# ---------------------------------------------------------------------------


class TestListItems:
    @pytest.mark.asyncio
    async def test_list_returns_paginated_items(self) -> None:
        item_obj = _make_item_obj()
        client = _make_client()

        with patch("quickbooks_mcp.tools.item.Item") as mock_item:
            mock_item.filter.return_value = [item_obj]
            result = await _list_items(
                client, active_only=True, max_results=20, offset=0, response_format="json"
            )

        assert result["status"] == "ok"
        assert result["operation"] == "list"
        assert result["entity_type"] == "Item"
        assert result["count"] == 1
        assert result["data"][0]["name"] == "Freight Service"

    @pytest.mark.asyncio
    async def test_list_passes_active_filter(self) -> None:
        client = _make_client()

        with patch("quickbooks_mcp.tools.item.Item") as mock_item:
            mock_item.filter.return_value = []
            await _list_items(
                client, active_only=True, max_results=20, offset=0, response_format="json"
            )

        call_kwargs = mock_item.filter.call_args[1]
        assert call_kwargs["Active"] is True

    @pytest.mark.asyncio
    async def test_list_omits_active_filter_when_false(self) -> None:
        client = _make_client()

        with patch("quickbooks_mcp.tools.item.Item") as mock_item:
            mock_item.filter.return_value = []
            await _list_items(
                client, active_only=False, max_results=20, offset=0, response_format="json"
            )

        call_kwargs = mock_item.filter.call_args[1]
        assert "Active" not in call_kwargs


# ---------------------------------------------------------------------------
# 2. get item by ID
# ---------------------------------------------------------------------------


class TestGetItem:
    @pytest.mark.asyncio
    async def test_get_returns_item(self) -> None:
        item_obj = _make_item_obj(id_="10")
        client = _make_client()

        with patch("quickbooks_mcp.tools.item.Item") as mock_item:
            mock_item.get.return_value = item_obj
            result = await _get_item(client, "10", "json")

        assert result["status"] == "ok"
        assert result["operation"] == "get"
        assert result["data"][0]["id"] == "10"
        mock_item.get.assert_called_once_with("10", qb=client.qb_client)


# ---------------------------------------------------------------------------
# 3. create service item with name and unit_price
# ---------------------------------------------------------------------------


class TestCreateItem:
    @pytest.mark.asyncio
    async def test_create_service_item(self) -> None:
        saved = _make_item_obj(name="Hauling", item_type="Service", unit_price=200.0)
        client = _make_client()

        with patch("quickbooks_mcp.tools.item.Item") as mock_item:
            instance = MagicMock()
            instance.save.return_value = saved
            mock_item.return_value = instance

            result = await _create_item(
                client,
                name="Hauling",
                item_type="service",
                description=None,
                unit_price=200.0,
                income_account_ref=None,
                expense_account_ref=None,
                extra_dict={},
                response_format="json",
            )

        assert result["status"] == "ok"
        assert result["operation"] == "create"
        assert result["data"][0]["name"] == "Hauling"
        assert instance.Name == "Hauling"
        assert instance.UnitPrice == 200.0


# ---------------------------------------------------------------------------
# 4. create sets Type from item_type mapping
# ---------------------------------------------------------------------------


class TestCreateItemTypeMapping:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("item_type", "expected_qbo_type"),
        [
            ("service", "Service"),
            ("non_inventory", "NonInventory"),
            ("inventory", "Inventory"),
        ],
    )
    async def test_type_mapped_correctly(self, item_type: str, expected_qbo_type: str) -> None:
        saved = _make_item_obj(item_type=expected_qbo_type)
        client = _make_client()

        with patch("quickbooks_mcp.tools.item.Item") as mock_item:
            instance = MagicMock()
            instance.save.return_value = saved
            mock_item.return_value = instance

            await _create_item(
                client,
                name="Test",
                item_type=item_type,
                description=None,
                unit_price=None,
                income_account_ref=None,
                expense_account_ref=None,
                extra_dict={},
                response_format="json",
            )

        assert instance.Type == expected_qbo_type


# ---------------------------------------------------------------------------
# 5. update auto-fetches SyncToken
# ---------------------------------------------------------------------------


class TestUpdateItem:
    @pytest.mark.asyncio
    async def test_update_fetches_existing_first(self) -> None:
        existing = _make_item_obj(id_="10", sync_token="5")
        updated = _make_item_obj(id_="10", name="New Name", sync_token="6")
        client = _make_client()

        fetch_count = 0

        with patch("quickbooks_mcp.tools.item.Item") as mock_item:

            def _get(id_, *, qb):
                nonlocal fetch_count
                fetch_count += 1
                return existing

            mock_item.get.side_effect = _get
            existing.save.return_value = updated

            result = await _update_item(
                client,
                id="10",
                name="New Name",
                description=None,
                unit_price=None,
                income_account_ref=None,
                expense_account_ref=None,
                extra_dict={},
                response_format="json",
            )

        assert fetch_count == 1
        assert existing.Name == "New Name"
        assert result["status"] == "ok"
        assert result["operation"] == "update"


# ---------------------------------------------------------------------------
# 6. deactivate sets Active=False
# ---------------------------------------------------------------------------


class TestDeactivateItem:
    @pytest.mark.asyncio
    async def test_deactivate_sets_active_false(self) -> None:
        existing = _make_item_obj(id_="10", active=True)
        deactivated = _make_item_obj(id_="10", active=False)
        client = _make_client()

        with patch("quickbooks_mcp.tools.item.Item") as mock_item:
            mock_item.get.return_value = existing
            existing.save.return_value = deactivated

            result = await _deactivate_item(client, "10", "json")

        assert existing.Active is False
        assert result["status"] == "ok"
        assert result["operation"] == "deactivate"


# ---------------------------------------------------------------------------
# 7. search passes query
# ---------------------------------------------------------------------------


class TestSearchItems:
    @pytest.mark.asyncio
    async def test_search_passes_query_to_qb(self) -> None:
        item_obj = _make_item_obj(name="Fuel Surcharge")
        client = _make_client()
        client.query_rows = AsyncMock(return_value=[item_obj.to_dict.return_value])

        result = await _search_items(
            client,
            query="Name LIKE '%Surcharge%'",
            max_results=20,
            offset=0,
            response_format="json",
        )

        client.query_rows.assert_awaited_once_with(
            "SELECT * FROM Item WHERE Name LIKE '%Surcharge%'", "Item"
        )
        assert result["status"] == "ok"
        assert result["operation"] == "search"
        assert result["data"][0]["name"] == "Fuel Surcharge"

    @pytest.mark.asyncio
    async def test_search_metadata_includes_query(self) -> None:
        client = _make_client()
        client.query_rows = AsyncMock(return_value=[])

        result = await _search_items(
            client,
            query="Type = 'Service'",
            max_results=20,
            offset=0,
            response_format="json",
        )

        assert "query" in result["metadata"]
        assert "SELECT * FROM Item WHERE" in result["metadata"]["query"]


def _make_ctx() -> MagicMock:
    """Build a Context mock that get_client can extract a QBOClient from."""
    mock_client = _make_client()
    ctx = MagicMock()
    ctx.request_context.lifespan_context.client = mock_client
    return ctx


# ---------------------------------------------------------------------------
# 8. create without name raises ToolError
# ---------------------------------------------------------------------------


class TestCreateWithoutName:
    @pytest.mark.asyncio
    async def test_create_raises_when_name_missing(self) -> None:
        tool_fn = _get_tool_fn()
        ctx = _make_ctx()

        with pytest.raises(ToolError, match="name is required"):
            await tool_fn(
                ctx=ctx,
                operation="create",
                item_type="service",
            )


# ---------------------------------------------------------------------------
# 9. create without item_type raises ToolError
# ---------------------------------------------------------------------------


class TestCreateWithoutItemType:
    @pytest.mark.asyncio
    async def test_create_raises_when_item_type_missing(self) -> None:
        tool_fn = _get_tool_fn()
        ctx = _make_ctx()

        with pytest.raises(ToolError, match="item_type is required"):
            await tool_fn(
                ctx=ctx,
                operation="create",
                name="New Item",
            )


# ---------------------------------------------------------------------------
# 10. extra with protected key raises ToolError
# ---------------------------------------------------------------------------


class TestExtraProtectedKey:
    @pytest.mark.asyncio
    async def test_extra_with_protected_key_raises(self) -> None:
        tool_fn = _get_tool_fn()
        ctx = _make_ctx()

        with pytest.raises(ToolError, match="protected key"):
            await tool_fn(
                ctx=ctx,
                operation="create",
                name="Test",
                item_type="service",
                extra={"SyncToken": "99", "Name": "override"},
            )
