"""Tests for qbo_journal_entry tool."""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.exceptions import ToolError

from quickbooks_mcp.tools._base import tx_create, tx_list

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

TX_TYPE = "journal_entry"
ENTITY_TYPE = "JournalEntry"


def _make_tx_obj(
    id_: str = "600",
    total: float = 750.00,
    sync_token: str = "1",
) -> MagicMock:
    obj = MagicMock()
    obj.Id = id_
    obj.SyncToken = sync_token
    obj.to_dict.return_value = {
        "Id": id_,
        "SyncToken": sync_token,
        "TotalAmt": total,
        "TxnDate": "2026-03-15",
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
    from quickbooks_mcp.tools.journal_entry import register

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
# 1. list journal entries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_journal_entries_returns_paginated_results():
    items = [_make_tx_obj(id_=str(i)) for i in range(3)]
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
    assert response["count"] == 3


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
# 3. create does NOT require any ref
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_without_refs_does_not_raise():
    je = _make_tx_obj(id_="601")
    client = _make_client(return_value=je)

    with patch("quickbooks_mcp.tools._base.get_tx_class") as mock_cls_factory:
        mock_cls = MagicMock()
        mock_cls.return_value = je
        mock_cls_factory.return_value = mock_cls

        response = await tx_create(
            client,
            TX_TYPE,
            ENTITY_TYPE,
            None,
            None,
            [
                {
                    "amount": 100.0,
                    "PostingType": "Debit",
                    "AccountRef": {"value": "1"},
                },
            ],
            None,
            None,
            {},
            "json",
        )

    assert response["status"] == "ok"
    assert response["operation"] == "create"


# ---------------------------------------------------------------------------
# 4. delete with preview=True returns preview
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_preview_true_returns_preview():
    tool_fn = _capture_tool_fn()
    je = _make_tx_obj(id_="33")
    client = _make_client(return_value=je)
    ctx = _make_ctx(client)

    response = await tool_fn(
        ctx=ctx,
        operation="delete",
        id="33",
    )

    assert response["status"] == "preview"
    assert response["operation"] == "delete"


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
            extra={"sparse": True},
        )


# ---------------------------------------------------------------------------
# 7. no tx_type parameter
# ---------------------------------------------------------------------------


def test_tool_signature_has_no_tx_type():
    tool_fn = _capture_tool_fn()
    sig = inspect.signature(tool_fn)
    assert "tx_type" not in sig.parameters
