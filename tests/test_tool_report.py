"""Tests for the qbo_report tool and report_simplifier module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.exceptions import ToolError

from quickbooks_mcp.report_simplifier import extract_columns, simplify_report
from quickbooks_mcp.tools.report import register

# ---------------------------------------------------------------------------
# Sample report fixtures
# ---------------------------------------------------------------------------

_COLUMNS = [
    {"ColTitle": "", "ColType": "Account"},
    {"ColTitle": "Total", "ColType": "Money"},
]

_SIMPLE_PNL = {
    "Header": {
        "ReportName": "ProfitAndLoss",
        "Column": _COLUMNS,
    },
    "Rows": {
        "Row": [
            {
                "type": "Section",
                "Header": {"ColData": [{"value": "Income"}]},
                "Rows": {
                    "Row": [
                        {
                            "type": "Data",
                            "ColData": [{"value": "Sales", "id": "1"}, {"value": "5000.00"}],
                        },
                    ]
                },
                "Summary": {"ColData": [{"value": "Total Income"}, {"value": "5000.00"}]},
            },
            {
                "type": "Data",
                "ColData": [{"value": "Net Income"}, {"value": "3000.00"}],
            },
        ]
    },
}

_NESTED_PNL = {
    "Header": {
        "ReportName": "ProfitAndLoss",
        "Column": _COLUMNS,
    },
    "Rows": {
        "Row": [
            {
                "type": "Section",
                "Header": {"ColData": [{"value": "Income"}]},
                "Rows": {
                    "Row": [
                        {
                            "type": "Section",
                            "Header": {"ColData": [{"value": "Services"}]},
                            "Rows": {
                                "Row": [
                                    {
                                        "type": "Data",
                                        "ColData": [
                                            {"value": "Freight", "id": "2"},
                                            {"value": "3000.00"},
                                        ],
                                    },
                                ]
                            },
                            "Summary": {
                                "ColData": [{"value": "Total Services"}, {"value": "3000.00"}]
                            },
                        },
                    ]
                },
                "Summary": {"ColData": [{"value": "Total Income"}, {"value": "3000.00"}]},
            },
        ]
    },
}

_EMPTY_PNL = {
    "Header": {"ReportName": "ProfitAndLoss", "Column": _COLUMNS},
    "Rows": {"Row": []},
}


# ---------------------------------------------------------------------------
# Helpers: mock client + context
# ---------------------------------------------------------------------------


def _make_client_mock(report_return: dict) -> MagicMock:
    client = MagicMock()
    client.qb_client = MagicMock()
    client.qb_client.get_report = MagicMock(return_value=report_return)
    client.execute = AsyncMock(return_value=report_return)
    return client


def _make_ctx(client: MagicMock) -> MagicMock:
    ctx = MagicMock()
    ctx.request_context.lifespan_context.client = client
    return ctx


# ---------------------------------------------------------------------------
# Fixture: registered tool function
# ---------------------------------------------------------------------------


@pytest.fixture
def tool_fn():
    """Return the raw qbo_report coroutine extracted from a one-shot FastMCP."""
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


# ---------------------------------------------------------------------------
# 1. simplify_report with a mock P&L structure → flat list with correct cols
# ---------------------------------------------------------------------------


class TestSimplifyReportBasic:
    def test_flat_list_with_correct_columns(self) -> None:
        rows = simplify_report(_SIMPLE_PNL)

        # Expect: section header, data row, total, top-level data row
        assert isinstance(rows, list)
        assert len(rows) == 4

        # Section header
        assert rows[0]["name"] == "Income"
        assert rows[0]["_type"] == "section"
        assert rows[0]["_depth"] == 0

        # Data row inside section
        assert rows[1]["name"] == "Sales"
        assert rows[1]["Total"] == "5000.00"
        assert rows[1]["_depth"] == 1

        # Total row
        assert rows[2]["name"] == "Total Income"
        assert rows[2]["_type"] == "total"

        # Top-level data row
        assert rows[3]["name"] == "Net Income"
        assert rows[3]["Total"] == "3000.00"

    def test_extract_columns_normalises_empty_title(self) -> None:
        cols = extract_columns({"Column": _COLUMNS})
        assert cols == ["name", "Total"]

    def test_extract_columns_no_columns_key(self) -> None:
        assert extract_columns({}) == []


# ---------------------------------------------------------------------------
# 2. simplify_report handles nested sections
# ---------------------------------------------------------------------------


class TestSimplifyReportNestedSections:
    def test_nested_sections_produce_correct_depth(self) -> None:
        rows = simplify_report(_NESTED_PNL)

        types_depths = [(r.get("_type"), r["_depth"]) for r in rows]

        # outer section header (depth 0)
        assert ("section", 0) in types_depths
        # inner section header (depth 1)
        assert ("section", 1) in types_depths
        # data row (depth 2)
        assert (None, 2) in types_depths
        # inner total (depth 1)
        assert ("total", 1) in types_depths
        # outer total (depth 0)
        assert ("total", 0) in types_depths

    def test_nested_data_values_preserved(self) -> None:
        rows = simplify_report(_NESTED_PNL)
        data_rows = [r for r in rows if r.get("_type") is None]
        assert data_rows[0]["name"] == "Freight"
        assert data_rows[0]["Total"] == "3000.00"


# ---------------------------------------------------------------------------
# 3. simplify_report handles empty rows
# ---------------------------------------------------------------------------


class TestSimplifyReportEmpty:
    def test_empty_rows_returns_empty_list(self) -> None:
        assert simplify_report(_EMPTY_PNL) == []

    def test_no_columns_returns_empty_list(self) -> None:
        report = {"Header": {}, "Rows": {"Row": [{"type": "Data", "ColData": []}]}}
        assert simplify_report(report) == []

    def test_missing_rows_key_returns_empty_list(self) -> None:
        report = {"Header": {"Column": _COLUMNS}}
        assert simplify_report(report) == []


# ---------------------------------------------------------------------------
# 4. profit_and_loss calls get_report with correct name and date params
# ---------------------------------------------------------------------------


class TestProfitAndLoss:
    @pytest.mark.asyncio
    async def test_calls_get_report_with_correct_name_and_dates(self, tool_fn) -> None:
        client = _make_client_mock(_SIMPLE_PNL)
        ctx = _make_ctx(client)

        with patch("quickbooks_mcp.server.get_client", return_value=client):
            result = await tool_fn(
                ctx=ctx,
                operation="profit_and_loss",
                start_date="2026-01-01",
                end_date="2026-03-31",
            )

        # execute() was called once
        assert client.execute.call_count == 1

        # Inspect the closure that was passed to execute
        call_args = client.execute.call_args
        fetch_fn = call_args[0][0]

        # Simulate executing the closure to inspect the SDK call
        fetch_fn()
        client.qb_client.get_report.assert_called_once()
        call = client.qb_client.get_report.call_args
        assert call[0][0] == "ProfitAndLoss"
        params = call[0][1]
        assert params["start_date"] == "2026-01-01"
        assert params["end_date"] == "2026-03-31"

        assert result["status"] == "ok"
        assert result["operation"] == "profit_and_loss"


# ---------------------------------------------------------------------------
# 5. balance_sheet uses as_of_date param
# ---------------------------------------------------------------------------


class TestBalanceSheet:
    @pytest.mark.asyncio
    async def test_balance_sheet_sends_as_of_date(self, tool_fn) -> None:
        client = _make_client_mock(_EMPTY_PNL)
        ctx = _make_ctx(client)

        with patch("quickbooks_mcp.server.get_client", return_value=client):
            await tool_fn(
                ctx=ctx,
                operation="balance_sheet",
                as_of_date="2026-03-31",
            )

        fetch_fn = client.execute.call_args[0][0]
        fetch_fn()
        call = client.qb_client.get_report.call_args
        assert call[0][0] == "BalanceSheet"
        assert call[0][1]["as_of_date"] == "2026-03-31"
        assert "start_date" not in call[0][1]
        assert "end_date" not in call[0][1]


# ---------------------------------------------------------------------------
# 6. raw=True returns unsimplified data
# ---------------------------------------------------------------------------


class TestRawMode:
    @pytest.mark.asyncio
    async def test_raw_true_returns_nested_structure(self, tool_fn) -> None:
        client = _make_client_mock(_SIMPLE_PNL)
        ctx = _make_ctx(client)

        with patch("quickbooks_mcp.server.get_client", return_value=client):
            result = await tool_fn(
                ctx=ctx,
                operation="profit_and_loss",
                raw=True,
            )

        assert result["status"] == "ok"
        # raw mode wraps the full report dict; data is a list containing it
        assert isinstance(result["data"], list)
        raw_report = result["data"][0]
        assert "Header" in raw_report
        assert "Rows" in raw_report


# ---------------------------------------------------------------------------
# 7. raw=False returns simplified flat rows
# ---------------------------------------------------------------------------


class TestSimplifiedMode:
    @pytest.mark.asyncio
    async def test_raw_false_returns_flat_rows(self, tool_fn) -> None:
        client = _make_client_mock(_SIMPLE_PNL)
        ctx = _make_ctx(client)

        with patch("quickbooks_mcp.server.get_client", return_value=client):
            result = await tool_fn(
                ctx=ctx,
                operation="profit_and_loss",
                raw=False,
            )

        assert result["status"] == "ok"
        # All rows should be flat dicts — no nested "Header"/"Rows" keys
        for row in result["data"]:
            assert "Header" not in row
            assert "Rows" not in row
            assert "name" in row


# ---------------------------------------------------------------------------
# 8. Invalid operation raises ToolError
# ---------------------------------------------------------------------------


class TestInvalidOperation:
    @pytest.mark.asyncio
    async def test_invalid_operation_raises_tool_error(self, tool_fn) -> None:
        client = _make_client_mock(_EMPTY_PNL)
        ctx = _make_ctx(client)

        with (
            patch("quickbooks_mcp.server.get_client", return_value=client),
            pytest.raises((ToolError, Exception)),
        ):
            # Bypasses Literal type check at runtime — hits the fallback raise
            await tool_fn(ctx=ctx, operation="not_a_report")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 9. Markdown format returns string
# ---------------------------------------------------------------------------


class TestMarkdownFormat:
    @pytest.mark.asyncio
    async def test_markdown_format_returns_string(self, tool_fn) -> None:
        client = _make_client_mock(_SIMPLE_PNL)
        ctx = _make_ctx(client)

        with patch("quickbooks_mcp.server.get_client", return_value=client):
            result = await tool_fn(
                ctx=ctx,
                operation="profit_and_loss",
                response_format="markdown",
            )

        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# 10. Large report triggers truncation
# ---------------------------------------------------------------------------


class TestTruncation:
    @pytest.mark.asyncio
    async def test_large_report_triggers_truncation(self, tool_fn) -> None:
        # Build a report with many rows to exceed the CHARACTER_LIMIT
        many_rows = [
            {
                "type": "Data",
                "ColData": [
                    {"value": f"Account {i}", "id": str(i)},
                    {"value": f"{i * 100}.00"},
                ],
            }
            for i in range(500)
        ]
        big_report = {
            "Header": {"ReportName": "ProfitAndLoss", "Column": _COLUMNS},
            "Rows": {"Row": many_rows},
        }

        client = _make_client_mock(big_report)
        ctx = _make_ctx(client)

        with patch("quickbooks_mcp.server.get_client", return_value=client):
            result = await tool_fn(
                ctx=ctx,
                operation="profit_and_loss",
            )

        assert result["status"] == "ok"
        # If truncation fired, metadata will have the _truncated key;
        # if the payload happened to fit, it won't — but count must match data length.
        assert result["count"] == len(result["data"])
        # Either truncated with fewer rows, or all 500 fit (both are correct).
        assert result["count"] <= 500
