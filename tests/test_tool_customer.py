"""Tests for qbo_customer tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.exceptions import ToolError

from quickbooks_mcp.tools.customer import (
    _create,
    _deactivate,
    _get,
    _list,
    _search,
    _update,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_customer_obj(
    id_: str = "42",
    display_name: str = "Smith Freight LLC",
    active: bool = True,
    sync_token: str = "3",
) -> MagicMock:
    """Return a mock python-quickbooks Customer object with a to_dict() method."""
    obj = MagicMock()
    obj.Id = id_
    obj.DisplayName = display_name
    obj.Active = active
    obj.SyncToken = sync_token
    obj.to_dict.return_value = {
        "Id": id_,
        "DisplayName": display_name,
        "Active": active,
        "SyncToken": sync_token,
    }
    return obj


def _make_client(return_value=None) -> MagicMock:
    """Build a mock QBOClient whose execute() returns *return_value*."""
    client = MagicMock()
    client.qb_client = MagicMock()
    client.execute = AsyncMock(return_value=return_value)
    return client


def _make_ctx(client: MagicMock) -> MagicMock:
    """Build a mock FastMCP Context backed by *client*."""
    ctx = MagicMock()
    ctx.request_context.lifespan_context.client = client
    return ctx


# ---------------------------------------------------------------------------
# Helper to capture the registered tool function
# ---------------------------------------------------------------------------


def _capture_tool_fn():
    """Register qbo_customer on a mock MCP and return the inner async function."""
    from quickbooks_mcp.tools.customer import register

    mcp = MagicMock()
    tool_fn = None

    def capture_tool(*args, **kwargs):
        def decorator(fn):
            nonlocal tool_fn
            tool_fn = fn
            return fn

        return decorator

    mcp.tool = capture_tool
    register(mcp)
    return tool_fn


# ---------------------------------------------------------------------------
# 1. list customers returns paginated results
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_customers_returns_paginated_results():
    customers = [_make_customer_obj(id_=str(i), display_name=f"Customer {i}") for i in range(3)]
    client = _make_client(return_value=customers)

    with patch("quickbooks_mcp.tools.customer._get_class") as mock_cls_factory:
        mock_cls = MagicMock()
        mock_cls.filter.return_value = customers
        mock_cls_factory.return_value = mock_cls

        response = await _list(client, True, 20, 0, "json")

    assert response["status"] == "ok"
    assert response["operation"] == "list"
    assert response["entity_type"] == "Customer"
    assert response["count"] == 3
    assert len(response["data"]) == 3
    assert response["metadata"]["start_position"] == 1


# ---------------------------------------------------------------------------
# 2. get customer by ID
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_customer_by_id():
    customer = _make_customer_obj(id_="99", display_name="Acme Corp")
    client = _make_client(return_value=customer)

    with patch("quickbooks_mcp.tools.customer._get_class") as mock_cls_factory:
        mock_cls = MagicMock()
        mock_cls.get.return_value = customer
        mock_cls_factory.return_value = mock_cls

        response = await _get(client, "99", "json")

    assert response["status"] == "ok"
    assert response["operation"] == "get"
    assert response["entity_type"] == "Customer"
    assert response["data"][0]["id"] == "99"
    assert response["data"][0]["display_name"] == "Acme Corp"


# ---------------------------------------------------------------------------
# 3. create customer with display_name
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_customer_with_display_name():
    new_customer = _make_customer_obj(id_="101", display_name="Apex Logistics")
    client = _make_client(return_value=new_customer)

    with patch("quickbooks_mcp.tools.customer._get_class") as mock_cls_factory:
        mock_cls = MagicMock()
        created = _make_customer_obj(id_="101", display_name="Apex Logistics")
        mock_cls.return_value = created
        mock_cls_factory.return_value = mock_cls

        response = await _create(
            client,
            display_name="Apex Logistics",
            email="apex@logistics.com",
            phone="555-1234",
            company_name="Apex Logistics Inc",
            extra_dict={},
            response_format="json",
        )

    assert response["status"] == "ok"
    assert response["operation"] == "create"
    assert response["entity_type"] == "Customer"


# ---------------------------------------------------------------------------
# 4. update customer merges fields and auto-fetches SyncToken
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_customer_fetches_sync_token_and_merges():
    existing = _make_customer_obj(id_="42", display_name="Old Name", sync_token="2")
    updated = _make_customer_obj(id_="42", display_name="New Name", sync_token="3")
    client = _make_client(return_value=updated)

    with patch("quickbooks_mcp.tools.customer._get_class") as mock_cls_factory:
        mock_cls = MagicMock()
        mock_cls.get.return_value = existing
        existing.save.return_value = None
        existing.to_dict.return_value = {
            "Id": "42",
            "DisplayName": "New Name",
            "Active": True,
            "SyncToken": "3",
        }
        mock_cls_factory.return_value = mock_cls

        response = await _update(
            client,
            "42",
            display_name="New Name",
            email=None,
            phone=None,
            company_name=None,
            extra_dict={},
            response_format="json",
        )

    assert response["status"] == "ok"
    assert response["operation"] == "update"
    client.execute.assert_called_once()


# ---------------------------------------------------------------------------
# 5. deactivate customer sets Active=False
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deactivate_customer_sets_active_false():
    customer = _make_customer_obj(id_="77", active=True)
    deactivated = _make_customer_obj(id_="77", active=False)
    client = _make_client(return_value=deactivated)

    with patch("quickbooks_mcp.tools.customer._get_class") as mock_cls_factory:
        mock_cls = MagicMock()
        mock_cls.get.return_value = customer
        customer.to_dict.return_value = {
            "Id": "77",
            "DisplayName": "Acme",
            "Active": False,
            "SyncToken": "1",
        }
        mock_cls_factory.return_value = mock_cls

        response = await _deactivate(client, "77", "json")

    assert response["status"] == "ok"
    assert response["operation"] == "deactivate"
    assert response["data"][0]["active"] is False
    client.execute.assert_called_once()


# ---------------------------------------------------------------------------
# 6. search customers with query
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_customers_with_query():
    c1 = {"Id": "5", "DisplayName": "John Smith", "Active": True}
    c2 = {"Id": "6", "DisplayName": "Jane Smith", "Active": True}
    client = _make_client(return_value=[c1, c2])
    client.qb_client.query = MagicMock(return_value=[c1, c2])

    response = await _search(client, "DisplayName LIKE '%Smith%'", "json")

    assert response["status"] == "ok"
    assert response["operation"] == "search"
    assert response["entity_type"] == "Customer"
    assert response["count"] == 2
    assert (
        response["metadata"]["query"] == "SELECT * FROM Customer WHERE DisplayName LIKE '%Smith%'"
    )


# ---------------------------------------------------------------------------
# 7. get without id raises ToolError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_without_id_raises_tool_error():
    tool_fn = _capture_tool_fn()
    assert tool_fn is not None

    ctx = MagicMock()
    with patch("quickbooks_mcp.server.get_client") as mock_get_client:
        mock_get_client.return_value = _make_client()
        with pytest.raises(ToolError, match="'id' is required"):
            await tool_fn(
                ctx=ctx,
                operation="get",
                id=None,
            )


# ---------------------------------------------------------------------------
# 8. extra with protected key raises ToolError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extra_with_protected_key_raises_tool_error():
    tool_fn = _capture_tool_fn()
    assert tool_fn is not None

    ctx = MagicMock()
    with patch("quickbooks_mcp.server.get_client") as mock_get_client:
        mock_get_client.return_value = _make_client()
        with pytest.raises(ToolError, match="protected keys"):
            await tool_fn(
                ctx=ctx,
                operation="create",
                display_name="Test Co",
                extra={"SyncToken": "99"},
            )


# ---------------------------------------------------------------------------
# 9. extra accepts dict directly (Phase 1 type safety)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extra_accepts_dict_directly():
    """extra is now dict|None — verify dict with valid keys passes through to _create."""
    new_customer = _make_customer_obj(id_="200", display_name="Dict Co")
    client = _make_client(return_value=new_customer)

    with patch("quickbooks_mcp.tools.customer._get_class") as mock_cls_factory:
        mock_cls = MagicMock()
        mock_cls.return_value = new_customer
        mock_cls_factory.return_value = mock_cls

        response = await _create(
            client,
            display_name="Dict Co",
            email=None,
            phone=None,
            company_name=None,
            extra_dict={"Notes": "VIP client"},
            response_format="json",
        )

    assert response["status"] == "ok"
    assert response["operation"] == "create"


# ---------------------------------------------------------------------------
# 10. markdown format returns string
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_markdown_format_returns_string():
    customers = [_make_customer_obj(id_="1", display_name="Alpha Freight")]
    client = _make_client(return_value=customers)

    with patch("quickbooks_mcp.tools.customer._get_class") as mock_cls_factory:
        mock_cls = MagicMock()
        mock_cls.filter.return_value = customers
        mock_cls_factory.return_value = mock_cls

        response = await _list(client, True, 20, 0, "markdown")

    assert isinstance(response, str)
    assert "Alpha Freight" in response or "Customer" in response


# ---------------------------------------------------------------------------
# 11. no party_type parameter — tool works without one
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_party_type_parameter():
    """qbo_customer has no party_type parameter — verify _list works directly."""
    customers = [_make_customer_obj(id_="1", display_name="Test Co")]
    client = _make_client(return_value=customers)

    with patch("quickbooks_mcp.tools.customer._get_class") as mock_cls_factory:
        mock_cls = MagicMock()
        mock_cls.filter.return_value = customers
        mock_cls_factory.return_value = mock_cls

        response = await _list(client, True, 20, 0, "json")

    assert response["status"] == "ok"
    assert response["entity_type"] == "Customer"


@pytest.mark.asyncio
async def test_tool_signature_has_no_party_type():
    """Verify the registered tool function does not accept party_type."""
    import inspect

    tool_fn = _capture_tool_fn()
    assert tool_fn is not None
    sig = inspect.signature(tool_fn)
    assert "party_type" not in sig.parameters
