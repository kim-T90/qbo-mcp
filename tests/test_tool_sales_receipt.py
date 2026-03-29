"""Tests for qbo_sales_receipt tool."""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.exceptions import ToolError

from quickbooks_mcp.tools._base import (
    tx_create,
    tx_list,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

TX_TYPE = "sales_receipt"
ENTITY_TYPE = "SalesReceipt"


def _make_tx_obj(
    id_: str = "100",
    total: float = 250.00,
    sync_token: str = "1",
) -> MagicMock:
    obj = MagicMock()
    obj.Id = id_
    obj.SyncToken = sync_token
    obj.to_dict.return_value = {
        "Id": id_,
        "SyncToken": sync_token,
        "TotalAmt": total,
        "TxnDate": "2026-01-15",
        "CustomerRef": {"value": "10", "name": "Apex Logistics"},
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
    from quickbooks_mcp.tools.sales_receipt import register

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
# 1. list sales receipts returns paginated results
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_sales_receipts_returns_paginated_results():
    receipts = [_make_tx_obj(id_=str(i), total=float(100 * i)) for i in range(3)]
    client = _make_client(return_value=receipts)

    with patch("quickbooks_mcp.tools._base.get_tx_class") as mock_cls_factory:
        mock_cls = MagicMock()
        mock_cls.filter.return_value = receipts
        mock_cls_factory.return_value = mock_cls

        response = await tx_list(client, TX_TYPE, ENTITY_TYPE, None, None, 20, 0, "json")

    assert response["status"] == "ok"
    assert response["operation"] == "list"
    assert response["entity_type"] == ENTITY_TYPE
    assert response["count"] == 3


# ---------------------------------------------------------------------------
# 2. get requires id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_requires_id():
    tool_fn = _capture_tool_fn()
    assert tool_fn is not None

    ctx = MagicMock()
    with patch("quickbooks_mcp.server.get_client") as mock_get_client:
        mock_get_client.return_value = _make_client()
        with pytest.raises(ToolError, match="'id' is required"):
            await tool_fn(ctx=ctx, operation="get", id=None)


# ---------------------------------------------------------------------------
# 3. create requires customer_ref with helpful error message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_requires_customer_ref():
    tool_fn = _capture_tool_fn()
    assert tool_fn is not None

    ctx = MagicMock()
    with patch("quickbooks_mcp.server.get_client") as mock_get_client:
        mock_get_client.return_value = _make_client()
        with pytest.raises(
            ToolError, match="customer_ref.*required.*creating a sales_receipt"
        ) as exc_info:
            await tool_fn(ctx=ctx, operation="create", customer_ref=None)
        assert "qbo_customer" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 4. delete with preview=True returns preview
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_preview_true_returns_preview():
    tool_fn = _capture_tool_fn()
    assert tool_fn is not None

    sr = _make_tx_obj(id_="90", total=400.00)
    client = _make_client(return_value=sr)
    ctx = _make_ctx(client)

    with patch("quickbooks_mcp.server.get_client", return_value=client):
        response = await tool_fn(ctx=ctx, operation="delete", id="90")

    assert response["status"] == "preview"
    assert response["operation"] == "delete"
    assert response["entity_type"] == ENTITY_TYPE
    assert "preview=False" in response["warning"]


# ---------------------------------------------------------------------------
# 5. delete with preview=False executes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_preview_false_actually_deletes():
    tool_fn = _capture_tool_fn()
    assert tool_fn is not None

    sr = _make_tx_obj(id_="91")
    sr.delete.return_value = None
    client = _make_client(return_value=sr)
    ctx = _make_ctx(client)

    with patch("quickbooks_mcp.server.get_client", return_value=client):
        response = await tool_fn(ctx=ctx, operation="delete", id="91", preview=False)

    assert response["status"] == "ok"
    assert response["operation"] == "delete"
    client.execute.assert_called_once()


# ---------------------------------------------------------------------------
# 6. search requires query
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_requires_query():
    tool_fn = _capture_tool_fn()
    assert tool_fn is not None

    ctx = MagicMock()
    with patch("quickbooks_mcp.server.get_client") as mock_get_client:
        mock_get_client.return_value = _make_client()
        with pytest.raises(ToolError, match="'query' is required"):
            await tool_fn(ctx=ctx, operation="search", query=None)


# ---------------------------------------------------------------------------
# 7. extra dict with protected keys raises error
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
                customer_ref="10",
                extra={"SyncToken": "99"},
            )


# ---------------------------------------------------------------------------
# 8. tool has no tx_type parameter
# ---------------------------------------------------------------------------


def test_tool_signature_has_no_tx_type():
    tool_fn = _capture_tool_fn()
    assert tool_fn is not None
    sig = inspect.signature(tool_fn)
    assert "tx_type" not in sig.parameters


# ---------------------------------------------------------------------------
# 9. tool has no vendor_ref parameter
# ---------------------------------------------------------------------------


def test_tool_signature_has_no_vendor_ref():
    tool_fn = _capture_tool_fn()
    assert tool_fn is not None
    sig = inspect.signature(tool_fn)
    assert "vendor_ref" not in sig.parameters


# ---------------------------------------------------------------------------
# 10. void with preview=True returns preview
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_void_preview_true_returns_preview():
    tool_fn = _capture_tool_fn()
    assert tool_fn is not None

    sr = _make_tx_obj(id_="92", total=350.00)
    client = _make_client(return_value=sr)
    ctx = _make_ctx(client)

    with patch("quickbooks_mcp.server.get_client", return_value=client):
        response = await tool_fn(ctx=ctx, operation="void", id="92")

    assert response["status"] == "preview"
    assert response["operation"] == "void"
    assert "preview=False" in response["warning"]


# ---------------------------------------------------------------------------
# 11. void with preview=False executes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_void_preview_false_actually_voids():
    tool_fn = _capture_tool_fn()
    assert tool_fn is not None

    sr = _make_tx_obj(id_="93")
    sr.void.return_value = None
    client = _make_client(return_value=sr)
    ctx = _make_ctx(client)

    with patch("quickbooks_mcp.server.get_client", return_value=client):
        response = await tool_fn(ctx=ctx, operation="void", id="93", preview=False)

    assert response["status"] == "ok"
    assert response["operation"] == "void"
    client.execute.assert_called_once()


# ---------------------------------------------------------------------------
# 12. send requires email
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_requires_email():
    tool_fn = _capture_tool_fn()
    assert tool_fn is not None

    ctx = MagicMock()
    with patch("quickbooks_mcp.server.get_client") as mock_get_client:
        mock_get_client.return_value = _make_client()
        with pytest.raises(ToolError, match="'email' is required"):
            await tool_fn(ctx=ctx, operation="send", id="42", email=None)


# ---------------------------------------------------------------------------
# 13. create with customer_ref works
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_sales_receipt_with_customer_ref():
    created = _make_tx_obj(id_="200", total=150.00)
    client = _make_client(return_value=created)

    with patch("quickbooks_mcp.tools._base.get_tx_class") as mock_cls_factory:
        mock_cls = MagicMock()
        obj_instance = _make_tx_obj(id_="200", total=150.00)
        mock_cls.return_value = obj_instance
        obj_instance.save.return_value = None
        mock_cls_factory.return_value = mock_cls

        response = await tx_create(
            client,
            TX_TYPE,
            ENTITY_TYPE,
            customer_ref="10",
            vendor_ref=None,
            line_item_dicts=[{"amount": 150.00, "description": "Sales receipt line"}],
            memo=None,
            due_date=None,
            extra_dict={},
            response_format="json",
        )

    assert response["status"] == "ok"
    assert response["operation"] == "create"
    assert response["entity_type"] == ENTITY_TYPE
