"""Tests for qbo_transaction tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.exceptions import ToolError

from quickbooks_mcp.tools._base import (  # noqa: F401
    destructive_preview,
    tx_create,
    tx_delete,
    tx_get,
    tx_list,
    tx_pdf,
    tx_search,
    tx_send,
    tx_update,
    tx_void,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_tx_obj(
    id_: str = "100",
    tx_type: str = "Invoice",
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
    """Return (mcp_mock, captured_fn_getter) for registering and calling the tool."""
    from quickbooks_mcp.tools.transaction import register

    mcp = MagicMock()
    tool_fn_container: list = []

    def capture_tool(*args, **kwargs):
        def decorator(fn):
            tool_fn_container.append(fn)
            return fn

        return decorator

    mcp.tool = capture_tool
    register(mcp)
    return mcp, tool_fn_container[0]


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

        response = await tx_list(client, "invoice", "Invoice", None, None, 20, 0, "json")

    assert response["status"] == "ok"
    assert response["operation"] == "list"
    assert response["entity_type"] == "Invoice"
    assert response["count"] == 3
    assert len(response["data"]) == 3
    assert response["metadata"]["start_position"] == 1


# ---------------------------------------------------------------------------
# 2. get invoice by ID
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_invoice_by_id():
    inv = _make_tx_obj(id_="42", total=500.00)
    client = _make_client(return_value=inv)

    with patch("quickbooks_mcp.tools._base.get_tx_class") as mock_cls_factory:
        mock_cls = MagicMock()
        mock_cls.get.return_value = inv
        mock_cls_factory.return_value = mock_cls

        response = await tx_get(client, "invoice", "Invoice", "42", "json")

    assert response["status"] == "ok"
    assert response["operation"] == "get"
    assert response["entity_type"] == "Invoice"
    assert response["data"][0]["id"] == "42"
    assert response["data"][0]["total_amt"] == 500.00


# ---------------------------------------------------------------------------
# 3. create invoice with customer_ref and line_items
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_invoice_with_customer_ref_and_line_items():
    created = _make_tx_obj(id_="200", total=150.00)
    client = _make_client(return_value=created)

    line_items = [{"amount": 150.00, "description": "Freight charge", "item_ref": "5"}]

    pass  # tx_create imported at module level from _base

    with patch("quickbooks_mcp.tools._base.get_tx_class") as mock_cls_factory:
        mock_cls = MagicMock()
        obj_instance = _make_tx_obj(id_="200", total=150.00)
        mock_cls.return_value = obj_instance
        obj_instance.save.return_value = None
        mock_cls_factory.return_value = mock_cls

        response = await tx_create(
            client,
            "invoice",
            "Invoice",
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
    assert response["entity_type"] == "Invoice"
    client.execute.assert_called_once()


# ---------------------------------------------------------------------------
# 4. update invoice auto-fetches SyncToken
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
            "invoice",
            "Invoice",
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
    # execute called once wrapping the _do_update closure
    client.execute.assert_called_once()


# ---------------------------------------------------------------------------
# 5. void invoice works
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

        response = await tx_void(client, "invoice", "Invoice", "77", "json")

    assert response["status"] == "ok"
    assert response["operation"] == "void"
    assert response["entity_type"] == "Invoice"
    client.execute.assert_called_once()


# ---------------------------------------------------------------------------
# 6. delete invoice works
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_invoice_works():
    inv = _make_tx_obj(id_="88")
    inv.delete.return_value = None
    client = _make_client(return_value=inv)

    with patch("quickbooks_mcp.tools._base.get_tx_class") as mock_cls_factory:
        mock_cls = MagicMock()
        mock_cls.get.return_value = inv
        mock_cls_factory.return_value = mock_cls

        response = await tx_delete(client, "invoice", "Invoice", "88", "json")

    assert response["status"] == "ok"
    assert response["operation"] == "delete"
    assert response["entity_type"] == "Invoice"
    client.execute.assert_called_once()


# ---------------------------------------------------------------------------
# 7. send invoice with email
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_invoice_with_email():
    # send returns the sent object (or None — both handled)
    sent = _make_tx_obj(id_="33")
    client = _make_client(return_value=sent)

    with patch("quickbooks_mcp.tools._base.get_tx_class") as mock_cls_factory:
        mock_cls = MagicMock()
        mock_cls.send.return_value = sent
        mock_cls_factory.return_value = mock_cls

        response = await tx_send(client, "invoice", "Invoice", "33", "dispatch@example.com", "json")

    assert response["status"] == "ok"
    assert response["operation"] == "send"
    assert response["entity_type"] == "Invoice"
    client.execute.assert_called_once()


# ---------------------------------------------------------------------------
# 7b. pdf download
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pdf_download_invoice():
    """download_pdf is an instance method — _pdf must fetch the object first."""
    pass  # tx_pdf imported at module level from _base

    pdf_bytes = b"%PDF-1.0 fake-pdf-content"
    client = _make_client(return_value=pdf_bytes)

    with patch("quickbooks_mcp.tools._base.get_tx_class") as mock_cls_factory:
        mock_cls = MagicMock()
        mock_obj = MagicMock()
        mock_obj.download_pdf.return_value = pdf_bytes
        mock_cls.get.return_value = mock_obj
        mock_cls_factory.return_value = mock_cls

        response = await tx_pdf(client, "invoice", "Invoice", "42", "json")

    assert response["status"] == "ok"
    assert response["operation"] == "pdf"
    assert response["entity_type"] == "Invoice"
    # format_response wraps single dicts in a list
    pdf_data = response["data"][0]
    assert pdf_data["id"] == "42"
    assert pdf_data["encoding"] == "base64"
    assert pdf_data["content_type"] == "application/pdf"
    # Verify base64 data is non-empty (the mock returns bytes)
    assert len(pdf_data["data"]) > 0
    client.execute.assert_called_once()


# ---------------------------------------------------------------------------
# 8. unsupported operation for tx_type raises ToolError (void on bill)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unsupported_operation_for_tx_type_raises_tool_error():
    _, tool_fn = _capture_tool_fn()

    ctx = _make_ctx(_make_client())
    with patch("quickbooks_mcp.server.get_client") as mock_get_client:
        mock_get_client.return_value = _make_client()
        with pytest.raises(ToolError, match="not supported for 'bill'"):
            await tool_fn(
                ctx=ctx,
                operation="void",
                tx_type="bill",
            )


# ---------------------------------------------------------------------------
# 9. search with query
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_invoices_with_query():
    inv1 = {"Id": "1", "TotalAmt": 200.00, "TxnDate": "2026-01-05"}
    inv2 = {"Id": "2", "TotalAmt": 450.00, "TxnDate": "2026-01-10"}
    client = _make_client(return_value=[inv1, inv2])
    client.qb_client.query = MagicMock(return_value=[inv1, inv2])

    response = await tx_search(client, "Invoice", "TotalAmt > '100.00'", "json")

    assert response["status"] == "ok"
    assert response["operation"] == "search"
    assert response["entity_type"] == "Invoice"
    assert response["count"] == 2
    assert response["metadata"]["query"] == "SELECT * FROM Invoice WHERE TotalAmt > '100.00'"


# ---------------------------------------------------------------------------
# 10. invalid line_items JSON raises ToolError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_with_native_line_items_list():
    """line_items now accepts a native list[dict], not a JSON string."""
    _, tool_fn = _capture_tool_fn()

    created = _make_tx_obj(id_="201", total=250.00)
    client = _make_client(return_value=created)
    ctx = _make_ctx(client)

    with patch("quickbooks_mcp.server.get_client", return_value=client):
        result = await tool_fn(
            ctx=ctx,
            operation="create",
            tx_type="invoice",
            customer_ref="10",
            line_items=[{"amount": 250.00, "description": "Haul", "item_ref": "5"}],
        )

    assert result["status"] == "ok"
    assert result["operation"] == "create"


# ---------------------------------------------------------------------------
# 11. missing id for get/update/delete/void raises ToolError
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("op", ["get", "update", "delete", "void"])
@pytest.mark.asyncio
async def test_missing_id_raises_tool_error(op: str):
    _, tool_fn = _capture_tool_fn()

    ctx = _make_ctx(_make_client())
    with patch("quickbooks_mcp.server.get_client") as mock_get_client:
        mock_get_client.return_value = _make_client()
        with pytest.raises(ToolError, match="'id' is required"):
            await tool_fn(
                ctx=ctx,
                operation=op,
                tx_type="invoice",
                id=None,
            )


# ---------------------------------------------------------------------------
# 12. extra with protected key raises ToolError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extra_with_protected_key_raises_tool_error():
    _, tool_fn = _capture_tool_fn()

    ctx = _make_ctx(_make_client())
    with patch("quickbooks_mcp.server.get_client") as mock_get_client:
        mock_get_client.return_value = _make_client()
        with pytest.raises(ToolError, match="protected keys"):
            await tool_fn(
                ctx=ctx,
                operation="create",
                tx_type="invoice",
                extra={"SyncToken": "99"},
            )


# ---------------------------------------------------------------------------
# Bonus: markdown format returns string
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_markdown_format_returns_string():
    invoices = [_make_tx_obj(id_="1", total=100.00)]
    client = _make_client(return_value=invoices)

    with patch("quickbooks_mcp.tools._base.get_tx_class") as mock_cls_factory:
        mock_cls = MagicMock()
        mock_cls.filter.return_value = invoices
        mock_cls_factory.return_value = mock_cls

        response = await tx_list(client, "invoice", "Invoice", None, None, 20, 0, "markdown")

    assert isinstance(response, str)


# ---------------------------------------------------------------------------
# 13. preview=True on delete returns preview (does not delete)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_preview_true_returns_preview():
    """delete with preview=True (default) fetches entity and returns preview."""
    pass  # destructive_preview imported at module level from _base

    inv = _make_tx_obj(id_="90", total=400.00)
    client = _make_client(return_value=inv)

    with patch("quickbooks_mcp.tools._base.get_tx_class") as mock_cls_factory:
        mock_cls = MagicMock()
        mock_cls.get.return_value = inv
        mock_cls_factory.return_value = mock_cls

        response = await destructive_preview(client, "invoice", "Invoice", "delete", "90")

    assert response["status"] == "preview"
    assert response["operation"] == "delete"
    assert response["entity_type"] == "Invoice"
    assert response["tx_type"] == "invoice"
    assert response["id"] == "90"
    assert response["data"]["id"] == "90"
    assert "preview=False" in response["warning"]
    assert "delete" in response["warning"]


# ---------------------------------------------------------------------------
# 14. preview=False on delete actually deletes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_preview_false_actually_deletes():
    """delete with preview=False proceeds with actual deletion."""
    _, tool_fn = _capture_tool_fn()

    inv = _make_tx_obj(id_="91")
    inv.delete.return_value = None
    client = _make_client(return_value=inv)
    ctx = _make_ctx(client)

    with patch("quickbooks_mcp.server.get_client", return_value=client):
        response = await tool_fn(
            ctx=ctx,
            operation="delete",
            tx_type="invoice",
            id="91",
            preview=False,
        )

    assert response["status"] == "ok"
    assert response["operation"] == "delete"
    client.execute.assert_called_once()


# ---------------------------------------------------------------------------
# 15. preview=True on void returns preview (does not void)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_void_preview_true_returns_preview():
    """void with preview=True (default) fetches entity and returns preview."""
    pass  # destructive_preview imported at module level from _base

    inv = _make_tx_obj(id_="92", total=350.00)
    client = _make_client(return_value=inv)

    with patch("quickbooks_mcp.tools._base.get_tx_class") as mock_cls_factory:
        mock_cls = MagicMock()
        mock_cls.get.return_value = inv
        mock_cls_factory.return_value = mock_cls

        response = await destructive_preview(client, "invoice", "Invoice", "void", "92")

    assert response["status"] == "preview"
    assert response["operation"] == "void"
    assert response["entity_type"] == "Invoice"
    assert response["id"] == "92"
    assert "preview=False" in response["warning"]
    assert "void" in response["warning"]


# ---------------------------------------------------------------------------
# 16. preview=False on void actually voids
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_void_preview_false_actually_voids():
    """void with preview=False proceeds with actual void."""
    _, tool_fn = _capture_tool_fn()

    inv = _make_tx_obj(id_="93")
    inv.void.return_value = None
    client = _make_client(return_value=inv)
    ctx = _make_ctx(client)

    with patch("quickbooks_mcp.server.get_client", return_value=client):
        response = await tool_fn(
            ctx=ctx,
            operation="void",
            tx_type="invoice",
            id="93",
            preview=False,
        )

    assert response["status"] == "ok"
    assert response["operation"] == "void"
    client.execute.assert_called_once()


# ---------------------------------------------------------------------------
# 17. preview=True via tool_fn (integration-level) returns preview for delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_via_tool_fn_default_preview_returns_preview():
    """Calling tool_fn with delete + default preview=True returns preview."""
    _, tool_fn = _capture_tool_fn()

    inv = _make_tx_obj(id_="94", total=600.00)
    client = _make_client(return_value=inv)
    ctx = _make_ctx(client)

    with patch("quickbooks_mcp.server.get_client", return_value=client):
        response = await tool_fn(
            ctx=ctx,
            operation="delete",
            tx_type="invoice",
            id="94",
            # preview defaults to True
        )

    assert response["status"] == "preview"
    assert response["operation"] == "delete"
    assert response["id"] == "94"
