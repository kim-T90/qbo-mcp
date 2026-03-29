"""Tests for qbo_vendor_credit tool."""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.exceptions import ToolError

from quickbooks_mcp.tools._base import tx_list

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

TX_TYPE = "vendor_credit"
ENTITY_TYPE = "VendorCredit"


def _make_tx_obj(
    id_: str = "200",
    total: float = 150.00,
    sync_token: str = "1",
) -> MagicMock:
    obj = MagicMock()
    obj.Id = id_
    obj.SyncToken = sync_token
    obj.to_dict.return_value = {
        "Id": id_,
        "SyncToken": sync_token,
        "TotalAmt": total,
        "TxnDate": "2026-02-01",
        "VendorRef": {"value": "30", "name": "Parts Inc"},
    }
    return obj


def _make_client(return_value=None) -> MagicMock:
    client = MagicMock()
    client.qb_client = MagicMock()
    client.execute = AsyncMock(return_value=return_value)
    return client


def _make_ctx(client: MagicMock) -> MagicMock:
    ctx = MagicMock()
    ctx.request_context.lifespan_context.client = client
    return ctx


def _capture_tool_fn():
    from quickbooks_mcp.tools.vendor_credit import register

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
# 1. list vendor credits
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_vendor_credits_returns_paginated_results():
    items = [_make_tx_obj(id_=str(i)) for i in range(2)]
    client = _make_client(return_value=items)

    with patch("quickbooks_mcp.tools._base.get_tx_class") as mock_cls_factory:
        mock_cls = MagicMock()
        mock_cls.filter.return_value = items
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
    assert response["entity_type"] == ENTITY_TYPE
    assert response["count"] == 2


# ---------------------------------------------------------------------------
# 2. get requires id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_without_id_raises_tool_error():
    tool_fn = _capture_tool_fn()
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
    vc = _make_tx_obj(id_="77")
    client = _make_client(return_value=vc)
    ctx = _make_ctx(client)

    response = await tool_fn(
        ctx=ctx,
        operation="delete",
        id="77",
    )

    assert response["status"] == "preview"
    assert response["operation"] == "delete"
    assert response["entity_type"] == ENTITY_TYPE


# ---------------------------------------------------------------------------
# 5. search requires query
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_without_query_raises_tool_error():
    tool_fn = _capture_tool_fn()
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
    client = _make_client()
    ctx = _make_ctx(client)
    with pytest.raises(ToolError, match="protected keys"):
        await tool_fn(
            ctx=ctx,
            operation="create",
            vendor_ref="10",
            extra={"Id": "999"},
        )


# ---------------------------------------------------------------------------
# 7. no tx_type parameter
# ---------------------------------------------------------------------------


def test_tool_signature_has_no_tx_type():
    tool_fn = _capture_tool_fn()
    sig = inspect.signature(tool_fn)
    assert "tx_type" not in sig.parameters
