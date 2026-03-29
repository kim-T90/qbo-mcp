"""Tests for qbo_bill tool."""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.exceptions import ToolError

from quickbooks_mcp.tools._base import tx_list

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

TX_TYPE = "bill"
ENTITY_TYPE = "Bill"


def _make_tx_obj(
    id_: str = "100",
    total: float = 500.00,
    sync_token: str = "1",
) -> MagicMock:
    """Return a mock python-quickbooks Bill object."""
    obj = MagicMock()
    obj.Id = id_
    obj.SyncToken = sync_token
    obj.to_dict.return_value = {
        "Id": id_,
        "SyncToken": sync_token,
        "TotalAmt": total,
        "TxnDate": "2026-01-15",
        "VendorRef": {"value": "20", "name": "Fuel Depot"},
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


def _capture_tool_fn():
    """Register qbo_bill on a mock MCP and return the inner function."""
    from quickbooks_mcp.tools.bill import register

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
# 1. list bills returns paginated results
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_bills_returns_paginated_results():
    bills = [_make_tx_obj(id_=str(i)) for i in range(3)]
    client = _make_client(return_value=bills)

    with patch("quickbooks_mcp.tools._base.get_tx_class") as mock_cls_factory:
        mock_cls = MagicMock()
        mock_cls.filter.return_value = bills
        mock_cls_factory.return_value = mock_cls

        response = await tx_list(
            client,
            TX_TYPE,
            ENTITY_TYPE,
            None,
            None,
            20,
            0,
            "json",
        )

    assert response["status"] == "ok"
    assert response["operation"] == "list"
    assert response["entity_type"] == ENTITY_TYPE
    assert response["count"] == 3


# ---------------------------------------------------------------------------
# 2. get requires id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_without_id_raises_tool_error():
    tool_fn = _capture_tool_fn()
    assert tool_fn is not None

    client = _make_client()
    ctx = _make_ctx(client)
    with pytest.raises(ToolError, match="'id' is required"):
        await tool_fn(ctx=ctx, operation="get", id=None)


# ---------------------------------------------------------------------------
# 3. create requires vendor_ref
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_without_vendor_ref_raises_tool_error():
    tool_fn = _capture_tool_fn()
    assert tool_fn is not None

    client = _make_client()
    ctx = _make_ctx(client)
    with pytest.raises(ToolError, match="vendor_ref"):
        await tool_fn(ctx=ctx, operation="create", vendor_ref=None)


# ---------------------------------------------------------------------------
# 4. delete with preview=True returns preview
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_preview_true_returns_preview():
    tool_fn = _capture_tool_fn()
    assert tool_fn is not None

    bill = _make_tx_obj(id_="55", total=500.00)
    client = _make_client(return_value=bill)
    ctx = _make_ctx(client)

    response = await tool_fn(ctx=ctx, operation="delete", id="55")

    assert response["status"] == "preview"
    assert response["operation"] == "delete"
    assert response["entity_type"] == ENTITY_TYPE


# ---------------------------------------------------------------------------
# 5. search requires query
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_without_query_raises_tool_error():
    tool_fn = _capture_tool_fn()
    assert tool_fn is not None

    client = _make_client()
    ctx = _make_ctx(client)
    with pytest.raises(ToolError, match="'query' is required"):
        await tool_fn(ctx=ctx, operation="search", query=None)


# ---------------------------------------------------------------------------
# 6. protected keys in extra raises error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extra_with_protected_key_raises_tool_error():
    tool_fn = _capture_tool_fn()
    assert tool_fn is not None

    client = _make_client()
    ctx = _make_ctx(client)
    with pytest.raises(ToolError, match="protected keys"):
        await tool_fn(
            ctx=ctx,
            operation="create",
            vendor_ref="10",
            extra={"SyncToken": "99"},
        )


# ---------------------------------------------------------------------------
# 7. no tx_type parameter exists
# ---------------------------------------------------------------------------


def test_tool_signature_has_no_tx_type():
    """qbo_bill has no tx_type parameter."""
    tool_fn = _capture_tool_fn()
    assert tool_fn is not None
    sig = inspect.signature(tool_fn)
    assert "tx_type" not in sig.parameters
