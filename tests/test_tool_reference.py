"""Tests for the qbo_reference tool."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.exceptions import ToolError

from quickbooks_mcp.tools.reference import (
    _get_company_info,
    _get_preferences,
    _list_classes,
    _list_departments,
    _list_payment_methods,
    _list_tax_codes,
    _list_terms,
    _operation_to_entity,
    register,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_qbo_obj(data: dict[str, Any]) -> MagicMock:
    """Return a mock python-quickbooks entity whose .to_dict() returns *data*."""
    obj = MagicMock()
    obj.to_dict.return_value = data
    return obj


def _make_mock_client(execute_return: Any) -> MagicMock:
    """Build a mock QBOClient with a pre-configured execute AsyncMock."""
    client = MagicMock()
    client.execute = AsyncMock(return_value=execute_return)
    client.qb_client = MagicMock()
    return client


# ---------------------------------------------------------------------------
# _operation_to_entity
# ---------------------------------------------------------------------------


class TestOperationToEntity:
    def test_known_operations_map_correctly(self) -> None:
        assert _operation_to_entity("list_tax_codes") == "TaxCode"
        assert _operation_to_entity("list_classes") == "Class"
        assert _operation_to_entity("list_departments") == "Department"
        assert _operation_to_entity("list_terms") == "Term"
        assert _operation_to_entity("list_payment_methods") == "PaymentMethod"
        assert _operation_to_entity("get_company_info") == "CompanyInfo"
        assert _operation_to_entity("get_preferences") == "Preferences"

    def test_unknown_operation_returns_itself(self) -> None:
        assert _operation_to_entity("unknown_op") == "unknown_op"


# ---------------------------------------------------------------------------
# list_tax_codes
# ---------------------------------------------------------------------------


class TestListTaxCodes:
    @pytest.mark.asyncio
    async def test_returns_json_envelope(self, env_vars: dict[str, str]) -> None:
        tax_code = _make_qbo_obj({"Id": "1", "Name": "CA Sales Tax", "Active": True})
        client = _make_mock_client([tax_code])

        with patch("quickbooks_mcp.tools.reference.TaxCode", create=True):
            result = await _list_tax_codes(client, "json")

        assert isinstance(result, dict)
        assert result["status"] == "ok"
        assert result["operation"] == "list_tax_codes"
        assert result["entity_type"] == "TaxCode"
        assert result["count"] == 1
        data = result["data"]
        assert len(data) == 1
        # Keys converted to snake_case
        assert "id" in data[0]
        assert "name" in data[0]

    @pytest.mark.asyncio
    async def test_empty_results_returns_zero_count(self, env_vars: dict[str, str]) -> None:
        client = _make_mock_client([])

        with patch("quickbooks_mcp.tools.reference.TaxCode", create=True):
            result = await _list_tax_codes(client, "json")

        assert isinstance(result, dict)
        assert result["count"] == 0
        assert result["data"] == []

    @pytest.mark.asyncio
    async def test_markdown_format_returns_string(self, env_vars: dict[str, str]) -> None:
        tax_code = _make_qbo_obj({"Id": "1", "Name": "CA Sales Tax"})
        client = _make_mock_client([tax_code])

        with patch("quickbooks_mcp.tools.reference.TaxCode", create=True):
            result = await _list_tax_codes(client, "markdown")

        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# list_terms
# ---------------------------------------------------------------------------


class TestListTerms:
    @pytest.mark.asyncio
    async def test_returns_list_of_terms(self, env_vars: dict[str, str]) -> None:
        term1 = _make_qbo_obj({"Id": "1", "Name": "Net 30", "DueDays": 30})
        term2 = _make_qbo_obj({"Id": "2", "Name": "Due on receipt", "DueDays": 0})
        client = _make_mock_client([term1, term2])

        with patch("quickbooks_mcp.tools.reference.Term", create=True):
            result = await _list_terms(client, "json")

        assert isinstance(result, dict)
        assert result["status"] == "ok"
        assert result["count"] == 2
        names = [item["name"] for item in result["data"]]
        assert "Net 30" in names
        assert "Due on receipt" in names

    @pytest.mark.asyncio
    async def test_keys_are_snake_case(self, env_vars: dict[str, str]) -> None:
        term = _make_qbo_obj({"Id": "1", "Name": "Net 30", "DueDays": 30})
        client = _make_mock_client([term])

        with patch("quickbooks_mcp.tools.reference.Term", create=True):
            result = await _list_terms(client, "json")

        item = result["data"][0]
        assert "due_days" in item
        assert "DueDays" not in item


# ---------------------------------------------------------------------------
# get_company_info
# ---------------------------------------------------------------------------


class TestGetCompanyInfo:
    @pytest.mark.asyncio
    async def test_returns_company_info_dict(self, env_vars: dict[str, str]) -> None:
        mock_info = _make_qbo_obj(
            {
                "Id": "1",
                "CompanyName": "Origin Transport LLC",
                "LegalName": "Origin Transport LLC",
                "Country": "US",
                "FiscalYearStartMonth": "January",
            }
        )
        client = _make_mock_client(mock_info)

        with patch("quickbooks_mcp.tools.reference.CompanyInfo", create=True):
            result = await _get_company_info(client, "json")

        assert isinstance(result, dict)
        assert result["status"] == "ok"
        assert result["operation"] == "get_company_info"
        assert result["entity_type"] == "CompanyInfo"
        assert result["count"] == 1
        data = result["data"][0]
        assert data["company_name"] == "Origin Transport LLC"
        assert data["country"] == "US"

    @pytest.mark.asyncio
    async def test_calls_execute_with_get_1(self, env_vars: dict[str, str]) -> None:
        mock_info = _make_qbo_obj({"Id": "1", "CompanyName": "Test Co"})
        client = _make_mock_client(mock_info)

        with patch("quickbooks.objects.company_info.CompanyInfo") as mock_company_info:
            await _get_company_info(client, "json")

        client.execute.assert_awaited_once_with(mock_company_info.get, 1, qb=client.qb_client)

    @pytest.mark.asyncio
    async def test_markdown_format_returns_string(self, env_vars: dict[str, str]) -> None:
        mock_info = _make_qbo_obj({"Id": "1", "CompanyName": "Origin Transport LLC"})
        client = _make_mock_client(mock_info)

        with patch("quickbooks_mcp.tools.reference.CompanyInfo", create=True):
            result = await _get_company_info(client, "markdown")

        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# get_preferences
# ---------------------------------------------------------------------------


class TestGetPreferences:
    @pytest.mark.asyncio
    async def test_returns_preferences_data(self, env_vars: dict[str, str]) -> None:
        mock_prefs = _make_qbo_obj(
            {
                "Id": "1",
                "AccountingInfoPrefs": {"FirstMonthOfFiscalYear": "January"},
                "CurrencyPrefs": {"HomeCurrency": {"value": "USD"}},
            }
        )
        client = _make_mock_client(mock_prefs)

        with patch("quickbooks_mcp.tools.reference.Preferences", create=True):
            result = await _get_preferences(client, "json")

        assert isinstance(result, dict)
        assert result["status"] == "ok"
        assert result["operation"] == "get_preferences"
        assert result["entity_type"] == "Preferences"
        data = result["data"][0]
        assert "accounting_info_prefs" in data

    @pytest.mark.asyncio
    async def test_calls_execute_with_get_1(self, env_vars: dict[str, str]) -> None:
        mock_prefs = _make_qbo_obj({"Id": "1"})
        client = _make_mock_client(mock_prefs)

        with patch("quickbooks.objects.preferences.Preferences") as mock_preferences:
            await _get_preferences(client, "json")

        client.execute.assert_awaited_once_with(mock_preferences.get, 1, qb=client.qb_client)


# ---------------------------------------------------------------------------
# list_classes (raw query path)
# ---------------------------------------------------------------------------


class TestListClasses:
    @pytest.mark.asyncio
    async def test_returns_classes_from_raw_query(self, env_vars: dict[str, str]) -> None:
        # qb_client.query returns dicts directly (not objects with .to_dict())
        raw_classes = [
            {"Id": "1", "Name": "Operations", "Active": True},
            {"Id": "2", "Name": "Admin", "Active": True},
        ]
        client = _make_mock_client(raw_classes)

        result = await _list_classes(client, "json")

        assert isinstance(result, dict)
        assert result["status"] == "ok"
        assert result["count"] == 2
        names = [item["name"] for item in result["data"]]
        assert "Operations" in names
        assert "Admin" in names

    @pytest.mark.asyncio
    async def test_uses_select_from_class_query(self, env_vars: dict[str, str]) -> None:
        client = _make_mock_client([])

        await _list_classes(client, "json")

        client.execute.assert_awaited_once_with(client.qb_client.query, "SELECT * FROM Class")


# ---------------------------------------------------------------------------
# list_departments
# ---------------------------------------------------------------------------


class TestListDepartments:
    @pytest.mark.asyncio
    async def test_returns_list_of_departments(self, env_vars: dict[str, str]) -> None:
        dept = _make_qbo_obj({"Id": "1", "Name": "West Coast", "Active": True})
        client = _make_mock_client([dept])

        with patch("quickbooks_mcp.tools.reference.Department", create=True):
            result = await _list_departments(client, "json")

        assert isinstance(result, dict)
        assert result["count"] == 1
        assert result["data"][0]["name"] == "West Coast"


# ---------------------------------------------------------------------------
# list_payment_methods
# ---------------------------------------------------------------------------


class TestListPaymentMethods:
    @pytest.mark.asyncio
    async def test_returns_list_of_payment_methods(self, env_vars: dict[str, str]) -> None:
        pm1 = _make_qbo_obj({"Id": "1", "Name": "Check", "Active": True})
        pm2 = _make_qbo_obj({"Id": "2", "Name": "Credit Card", "Active": True})
        client = _make_mock_client([pm1, pm2])

        with patch("quickbooks_mcp.tools.reference.PaymentMethod", create=True):
            result = await _list_payment_methods(client, "json")

        assert isinstance(result, dict)
        assert result["count"] == 2


# ---------------------------------------------------------------------------
# register / full tool — invalid operation raises ToolError
# ---------------------------------------------------------------------------


class TestQboReferenceTool:
    def _make_ctx(self, client: MagicMock) -> MagicMock:
        """Build a minimal FastMCP Context mock pointing at *client*."""
        ctx = MagicMock()
        ctx.request_context.lifespan_context.client = client
        return ctx

    @pytest.mark.asyncio
    async def test_invalid_operation_raises_tool_error(self, env_vars: dict[str, str]) -> None:
        from fastmcp import FastMCP

        fresh_mcp = FastMCP("fresh")
        register(fresh_mcp)
        inner = await fresh_mcp.get_tool("qbo_reference")

        client = _make_mock_client(None)
        ctx = self._make_ctx(client)

        with patch("quickbooks_mcp.server.get_client", return_value=client):
            with pytest.raises(ToolError, match="Invalid operation"):
                await inner.fn(ctx=ctx, operation="not_valid")

    @pytest.mark.asyncio
    async def test_get_company_info_via_registered_tool(self, env_vars: dict[str, str]) -> None:
        mock_info = _make_qbo_obj(
            {"Id": "1", "CompanyName": "Origin Transport LLC", "Country": "US"}
        )
        client = _make_mock_client(mock_info)
        ctx = self._make_ctx(client)

        from fastmcp import FastMCP

        fresh_mcp = FastMCP("fresh2")
        register(fresh_mcp)
        inner = await fresh_mcp.get_tool("qbo_reference")

        with (
            patch("quickbooks_mcp.server.get_client", return_value=client),
            patch("quickbooks.objects.company_info.CompanyInfo"),
        ):
            result = await inner.fn(ctx=ctx, operation="get_company_info", response_format="json")

        assert isinstance(result, dict)
        assert result["status"] == "ok"
        assert result["data"][0]["company_name"] == "Origin Transport LLC"

    @pytest.mark.asyncio
    async def test_markdown_format_returns_string_via_tool(self, env_vars: dict[str, str]) -> None:
        mock_info = _make_qbo_obj({"Id": "1", "CompanyName": "Origin Transport LLC"})
        client = _make_mock_client(mock_info)
        ctx = self._make_ctx(client)

        from fastmcp import FastMCP

        fresh_mcp = FastMCP("fresh3")
        register(fresh_mcp)
        inner = await fresh_mcp.get_tool("qbo_reference")

        with (
            patch("quickbooks_mcp.server.get_client", return_value=client),
            patch("quickbooks.objects.company_info.CompanyInfo"),
        ):
            result = await inner.fn(
                ctx=ctx, operation="get_company_info", response_format="markdown"
            )

        assert isinstance(result, str)
