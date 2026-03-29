"""Tests for qbo_help tool."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastmcp.exceptions import ToolError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _capture_tool_fn():
    """Register qbo_help on a mock MCP and return the tool function."""
    from quickbooks_mcp.tools.help import register

    mcp = MagicMock()
    captured = {}

    def fake_tool(**kwargs):
        def decorator(fn):
            captured["fn"] = fn
            return fn

        return decorator

    mcp.tool = fake_tool
    register(mcp)
    return captured["fn"]


def _make_ctx():
    return MagicMock()


# ---------------------------------------------------------------------------
# topic=fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fields_lists_all_entities():
    fn = _capture_tool_fn()
    result = await fn(ctx=_make_ctx(), topic="fields")
    assert "available_entities" in result
    assert "Customer" in result["available_entities"]
    assert "Invoice" in result["available_entities"]
    assert "Account" in result["available_entities"]


@pytest.mark.asyncio
async def test_fields_returns_fields_for_entity():
    fn = _capture_tool_fn()
    result = await fn(ctx=_make_ctx(), topic="fields", entity="Customer")
    assert result["entity"] == "Customer"
    assert "DisplayName" in result["fields"]
    assert "Balance" in result["fields"]


@pytest.mark.asyncio
async def test_fields_accepts_lowercase_entity():
    fn = _capture_tool_fn()
    result = await fn(ctx=_make_ctx(), topic="fields", entity="invoice")
    assert result["entity"] == "Invoice"
    assert "TotalAmt" in result["fields"]


@pytest.mark.asyncio
async def test_fields_unknown_entity_raises():
    fn = _capture_tool_fn()
    with pytest.raises(ToolError, match="No field reference"):
        await fn(ctx=_make_ctx(), topic="fields", entity="Widget")


# ---------------------------------------------------------------------------
# topic=operations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_operations_returns_matrix():
    fn = _capture_tool_fn()
    result = await fn(ctx=_make_ctx(), topic="operations")
    matrix = result["transaction_operation_matrix"]
    assert "invoice" in matrix
    assert "void" in matrix["invoice"]
    assert "send" in matrix["invoice"]
    assert "bill" in matrix
    assert "void" not in matrix["bill"]


# ---------------------------------------------------------------------------
# topic=query_syntax
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_syntax_returns_guide():
    fn = _capture_tool_fn()
    result = await fn(ctx=_make_ctx(), topic="query_syntax")
    assert "guide" in result
    assert "LIKE" in result["guide"]
    assert "common_fields" in result


# ---------------------------------------------------------------------------
# topic=line_items
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_line_items_returns_all_schemas():
    fn = _capture_tool_fn()
    result = await fn(ctx=_make_ctx(), topic="line_items")
    assert "tx_type_defaults" in result
    assert "schemas" in result
    assert "invoice" in result["tx_type_defaults"]
    assert result["tx_type_defaults"]["invoice"] == "SalesItemLineDetail"
    assert "SalesItemLineDetail" in result["schemas"]
    assert "JournalEntryLineDetail" in result["schemas"]


@pytest.mark.asyncio
async def test_line_items_returns_schema_for_invoice():
    fn = _capture_tool_fn()
    result = await fn(ctx=_make_ctx(), topic="line_items", entity="invoice")
    assert result["tx_type"] == "invoice"
    assert result["default_detail_type"] == "SalesItemLineDetail"
    assert "amount" in result["fields"]
    assert result["fields"]["amount"]["required"] is True
    assert "example" in result


@pytest.mark.asyncio
async def test_line_items_returns_schema_for_bill():
    fn = _capture_tool_fn()
    result = await fn(ctx=_make_ctx(), topic="line_items", entity="bill")
    assert result["default_detail_type"] == "ItemBasedExpenseLineDetail"


@pytest.mark.asyncio
async def test_line_items_returns_schema_for_journal_entry():
    fn = _capture_tool_fn()
    result = await fn(ctx=_make_ctx(), topic="line_items", entity="journal_entry")
    assert result["default_detail_type"] == "JournalEntryLineDetail"
    assert "PostingType" in result["fields"]
    assert "AccountRef" in result["fields"]


@pytest.mark.asyncio
async def test_line_items_unknown_tx_type_raises():
    fn = _capture_tool_fn()
    with pytest.raises(ToolError, match="No line_items schema"):
        await fn(ctx=_make_ctx(), topic="line_items", entity="Widget")


# ---------------------------------------------------------------------------
# topic=required_params
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_required_params_returns_all_tools():
    fn = _capture_tool_fn()
    result = await fn(ctx=_make_ctx(), topic="required_params")
    assert "tools" in result
    # Should have tool groupings
    assert "qbo_invoice" in result["tools"]
    assert "qbo_customer" in result["tools"]
    assert "qbo_vendor" in result["tools"]
    assert "qbo_employee" in result["tools"]
    assert "qbo_account" in result["tools"]
    assert "qbo_item" in result["tools"]
    # Transaction types should be under their per-type tools
    assert "invoice" in result["tools"]["qbo_invoice"]
    assert "bill" in result["tools"]["qbo_bill"]
    assert "note" in result


@pytest.mark.asyncio
async def test_required_params_for_invoice():
    fn = _capture_tool_fn()
    result = await fn(ctx=_make_ctx(), topic="required_params", entity="invoice")
    assert result["entity"] == "invoice"
    assert result["tool"] == "qbo_invoice"
    params = result["required_params"]
    assert params["list"] == []
    assert params["get"] == ["id"]
    assert "customer_ref" in params["create"]
    assert "line_items" in params["create"]
    assert params["delete"] == ["id"]
    assert params["void"] == ["id"]
    assert "id" in params["send"]
    assert "email" in params["send"]
    assert params["pdf"] == ["id"]
    assert params["search"] == ["query"]


@pytest.mark.asyncio
async def test_required_params_for_customer():
    fn = _capture_tool_fn()
    result = await fn(ctx=_make_ctx(), topic="required_params", entity="customer")
    assert result["entity"] == "customer"
    assert result["tool"] == "qbo_customer"
    params = result["required_params"]
    assert params["create"] == ["display_name"]
    assert params["deactivate"] == ["id"]
    assert params["search"] == ["query"]


@pytest.mark.asyncio
async def test_required_params_for_account():
    fn = _capture_tool_fn()
    result = await fn(ctx=_make_ctx(), topic="required_params", entity="account")
    assert result["entity"] == "account"
    assert result["tool"] == "qbo_account"
    params = result["required_params"]
    assert "name" in params["create"]
    assert "account_type" in params["create"]


@pytest.mark.asyncio
async def test_required_params_for_item():
    fn = _capture_tool_fn()
    result = await fn(ctx=_make_ctx(), topic="required_params", entity="item")
    assert result["entity"] == "item"
    assert result["tool"] == "qbo_item"
    params = result["required_params"]
    assert "name" in params["create"]
    assert "item_type" in params["create"]


@pytest.mark.asyncio
async def test_required_params_unknown_entity_raises():
    fn = _capture_tool_fn()
    with pytest.raises(ToolError, match="No required_params reference"):
        await fn(ctx=_make_ctx(), topic="required_params", entity="Widget")


@pytest.mark.asyncio
async def test_required_params_covers_all_tx_types():
    """Ensure every tx_type from TX_OPERATION_MATRIX has a required_params entry."""
    from quickbooks_mcp.models import TX_OPERATION_MATRIX
    from quickbooks_mcp.tools.help import _REQUIRED_PARAMS

    for tx_type in TX_OPERATION_MATRIX:
        assert tx_type in _REQUIRED_PARAMS, f"Missing required_params entry for {tx_type}"
        # Every operation in the matrix should have params defined
        for op in TX_OPERATION_MATRIX[tx_type]:
            assert op in _REQUIRED_PARAMS[tx_type], f"Missing required_params for {tx_type}.{op}"


@pytest.mark.asyncio
async def test_required_params_entity_no_delete_note():
    """Entity types should include a note about delete not being available."""
    fn = _capture_tool_fn()
    result = await fn(ctx=_make_ctx(), topic="required_params", entity="customer")
    assert "deactivate" in result["note"]


# ---------------------------------------------------------------------------
# topic=error_codes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_error_codes_returns_all_codes():
    fn = _capture_tool_fn()
    result = await fn(ctx=_make_ctx(), topic="error_codes")
    assert "error_codes" in result
    codes = result["error_codes"]
    assert "400" in codes
    assert "401" in codes
    assert "403" in codes
    assert "404" in codes
    assert "429" in codes
    assert "500" in codes
    assert "503" in codes


@pytest.mark.asyncio
async def test_error_codes_have_required_fields():
    fn = _capture_tool_fn()
    result = await fn(ctx=_make_ctx(), topic="error_codes")
    for code, info in result["error_codes"].items():
        assert "meaning" in info, f"Missing meaning for {code}"
        assert "common_causes" in info, f"Missing causes for {code}"
        assert "recovery" in info, f"Missing recovery for {code}"
