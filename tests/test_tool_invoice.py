"""Tests for qbo_invoice tool."""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.exceptions import ToolError

from quickbooks_mcp.tools._base import (
    tx_create,
    tx_get,
    tx_list,
    tx_search,
    tx_send,
    tx_update,
    tx_void,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

TX_TYPE = "invoice"
ENTITY_TYPE = "Invoice"


def _make_tx_obj(
    id_: str = "100",
    total: float = 250.00,
    sync_token: str = "1",
) -> MagicMock:
    """Return a mock python-quickbooks transaction object with to_dict()."""
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
    """Register qbo_invoice on a mock MCP and return the inner async function."""
    from quickbooks_mcp.tools.invoice import register

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
# 1. list invoices returns paginated results
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_invoices_returns_paginated_results():
    invoices = [_make_tx_obj(id_=str(i), total=float(100 * i)) for i in range(3)]
    client = _make_client(return_value=invoices)

    with patch("quickbooks_mcp.tools._base.get_tx_class") as mock_cls_factory:
        mock_cls = MagicMock()
        mock_cls.filter.return_value = invoices
        mock_cls_factory.return_value = mock_cls

        response = await tx_list(client, TX_TYPE, ENTITY_TYPE, None, None, 20, 0, "json")

    assert response["status"] == "ok"
    assert response["operation"] == "list"
    assert response["entity_type"] == ENTITY_TYPE
    assert response["count"] == 3
    assert len(response["data"]) == 3
    assert response["metadata"]["start_position"] == 1


# ---------------------------------------------------------------------------
# 2. get invoice requires id
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
            ToolError, match="customer_ref.*required.*creating an invoice"
        ) as exc_info:
            await tool_fn(ctx=ctx, operation="create", customer_ref=None)
        assert "qbo_customer" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 4. create invoice with customer_ref and line_items
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_invoice_with_customer_ref_and_line_items():
    created = _make_tx_obj(id_="200", total=150.00)
    client = _make_client(return_value=created)

    line_items = [{"amount": 150.00, "description": "Freight charge", "item_ref": "5"}]

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
            line_item_dicts=line_items,
            memo="Test invoice",
            due_date="2026-02-28",
            extra_dict={},
            response_format="json",
        )

    assert response["status"] == "ok"
    assert response["operation"] == "create"
    assert response["entity_type"] == ENTITY_TYPE
    client.execute.assert_called_once()


# ---------------------------------------------------------------------------
# 5. delete with preview=True returns preview
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_preview_true_returns_preview():
    tool_fn = _capture_tool_fn()
    assert tool_fn is not None

    inv = _make_tx_obj(id_="90", total=400.00)
    client = _make_client(return_value=inv)
    ctx = _make_ctx(client)

    with patch("quickbooks_mcp.server.get_client", return_value=client):
        response = await tool_fn(ctx=ctx, operation="delete", id="90")

    assert response["status"] == "preview"
    assert response["operation"] == "delete"
    assert response["entity_type"] == ENTITY_TYPE
    assert response["id"] == "90"
    assert "preview=False" in response["warning"]


# ---------------------------------------------------------------------------
# 6. delete with preview=False executes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_preview_false_actually_deletes():
    tool_fn = _capture_tool_fn()
    assert tool_fn is not None

    inv = _make_tx_obj(id_="91")
    inv.delete.return_value = None
    client = _make_client(return_value=inv)
    ctx = _make_ctx(client)

    with patch("quickbooks_mcp.server.get_client", return_value=client):
        response = await tool_fn(ctx=ctx, operation="delete", id="91", preview=False)

    assert response["status"] == "ok"
    assert response["operation"] == "delete"
    client.execute.assert_called_once()


# ---------------------------------------------------------------------------
# 7. search requires query
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
# 8. extra dict with protected keys raises error
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
# 9. tool has no tx_type parameter
# ---------------------------------------------------------------------------


def test_tool_signature_has_no_tx_type():
    tool_fn = _capture_tool_fn()
    assert tool_fn is not None
    sig = inspect.signature(tool_fn)
    assert "tx_type" not in sig.parameters


# ---------------------------------------------------------------------------
# 10. tool has no vendor_ref parameter
# ---------------------------------------------------------------------------


def test_tool_signature_has_no_vendor_ref():
    tool_fn = _capture_tool_fn()
    assert tool_fn is not None
    sig = inspect.signature(tool_fn)
    assert "vendor_ref" not in sig.parameters


# ---------------------------------------------------------------------------
# 11. void with preview=True returns preview
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_void_preview_true_returns_preview():
    tool_fn = _capture_tool_fn()
    assert tool_fn is not None

    inv = _make_tx_obj(id_="92", total=350.00)
    client = _make_client(return_value=inv)
    ctx = _make_ctx(client)

    with patch("quickbooks_mcp.server.get_client", return_value=client):
        response = await tool_fn(ctx=ctx, operation="void", id="92")

    assert response["status"] == "preview"
    assert response["operation"] == "void"
    assert response["id"] == "92"
    assert "preview=False" in response["warning"]


# ---------------------------------------------------------------------------
# 12. void with preview=False executes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_void_preview_false_actually_voids():
    tool_fn = _capture_tool_fn()
    assert tool_fn is not None

    inv = _make_tx_obj(id_="93")
    inv.void.return_value = None
    client = _make_client(return_value=inv)
    ctx = _make_ctx(client)

    with patch("quickbooks_mcp.server.get_client", return_value=client):
        response = await tool_fn(ctx=ctx, operation="void", id="93", preview=False)

    assert response["status"] == "ok"
    assert response["operation"] == "void"
    client.execute.assert_called_once()


# ---------------------------------------------------------------------------
# 13. send requires email
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
# 14. search with query works
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_invoices_with_query():
    inv1 = {"Id": "1", "TotalAmt": 200.00, "TxnDate": "2026-01-05"}
    inv2 = {"Id": "2", "TotalAmt": 450.00, "TxnDate": "2026-01-10"}
    client = _make_client(return_value=[inv1, inv2])
    client.qb_client.query = MagicMock(return_value=[inv1, inv2])

    response = await tx_search(client, ENTITY_TYPE, "TotalAmt > '100.00'", "json")

    assert response["status"] == "ok"
    assert response["operation"] == "search"
    assert response["entity_type"] == ENTITY_TYPE
    assert response["count"] == 2
    assert response["metadata"]["query"] == "SELECT * FROM Invoice WHERE TotalAmt > '100.00'"


# ---------------------------------------------------------------------------
# 15. get invoice by id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_invoice_by_id():
    inv = _make_tx_obj(id_="42", total=500.00)
    client = _make_client(return_value=inv)

    with patch("quickbooks_mcp.tools._base.get_tx_class") as mock_cls_factory:
        mock_cls = MagicMock()
        mock_cls.get.return_value = inv
        mock_cls_factory.return_value = mock_cls

        response = await tx_get(client, TX_TYPE, ENTITY_TYPE, "42", "json")

    assert response["status"] == "ok"
    assert response["operation"] == "get"
    assert response["entity_type"] == ENTITY_TYPE
    assert response["data"][0]["id"] == "42"


# ---------------------------------------------------------------------------
# 16. update invoice auto-fetches SyncToken
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_invoice_auto_fetches_sync_token():
    existing = _make_tx_obj(id_="55", sync_token="2")
    existing.save.return_value = None
    existing.to_dict.return_value = {
        "Id": "55",
        "SyncToken": "3",
        "TotalAmt": 300.00,
        "TxnDate": "2026-01-20",
    }
    client = _make_client(return_value=existing)

    with patch("quickbooks_mcp.tools._base.get_tx_class") as mock_cls_factory:
        mock_cls = MagicMock()
        mock_cls.get.return_value = existing
        mock_cls_factory.return_value = mock_cls

        response = await tx_update(
            client,
            TX_TYPE,
            ENTITY_TYPE,
            "55",
            customer_ref="10",
            vendor_ref=None,
            line_item_dicts=None,
            memo="Updated memo",
            due_date=None,
            extra_dict={},
            response_format="json",
        )

    assert response["status"] == "ok"
    assert response["operation"] == "update"
    client.execute.assert_called_once()


# ---------------------------------------------------------------------------
# 17. void invoice works via _base
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_void_invoice_works():
    inv = _make_tx_obj(id_="77", sync_token="1")
    inv.void.return_value = None
    client = _make_client(return_value=inv)

    with patch("quickbooks_mcp.tools._base.get_tx_class") as mock_cls_factory:
        mock_cls = MagicMock()
        mock_cls.get.return_value = inv
        mock_cls_factory.return_value = mock_cls

        response = await tx_void(client, TX_TYPE, ENTITY_TYPE, "77", "json")

    assert response["status"] == "ok"
    assert response["operation"] == "void"
    assert response["entity_type"] == ENTITY_TYPE
    client.execute.assert_called_once()


# ---------------------------------------------------------------------------
# 18. send invoice with email
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_invoice_with_email():
    sent = _make_tx_obj(id_="33")
    client = _make_client(return_value=sent)

    with patch("quickbooks_mcp.tools._base.get_tx_class") as mock_cls_factory:
        mock_cls = MagicMock()
        mock_cls.send.return_value = sent
        mock_cls_factory.return_value = mock_cls

        response = await tx_send(client, TX_TYPE, ENTITY_TYPE, "33", "dispatch@example.com", "json")

    assert response["status"] == "ok"
    assert response["operation"] == "send"
    assert response["entity_type"] == ENTITY_TYPE
    client.execute.assert_called_once()


# ---------------------------------------------------------------------------
# 19. markdown format returns string
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_markdown_format_returns_string():
    invoices = [_make_tx_obj(id_="1", total=100.00)]
    client = _make_client(return_value=invoices)

    with patch("quickbooks_mcp.tools._base.get_tx_class") as mock_cls_factory:
        mock_cls = MagicMock()
        mock_cls.filter.return_value = invoices
        mock_cls_factory.return_value = mock_cls

        response = await tx_list(client, TX_TYPE, ENTITY_TYPE, None, None, 20, 0, "markdown")

    assert isinstance(response, str)
