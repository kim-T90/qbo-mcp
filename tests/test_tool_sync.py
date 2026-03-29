"""Tests for the qbo_sync tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.exceptions import ToolError

from quickbooks_mcp.tools.sync import register

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_obj_mock(id_: str = "1", data: dict | None = None) -> MagicMock:
    """Return a mock QBO object with to_dict()."""
    obj = MagicMock()
    obj.Id = id_
    obj.to_dict.return_value = data or {"Id": id_, "SyncToken": "0"}
    return obj


def _make_client_mock(execute_return=None) -> MagicMock:
    client = MagicMock()
    client.qb_client = MagicMock()
    client.execute = AsyncMock(return_value=execute_return)
    return client


def _make_ctx(client: MagicMock) -> MagicMock:
    ctx = MagicMock()
    ctx.request_context.lifespan_context.client = client
    return ctx


# ---------------------------------------------------------------------------
# Fixture: registered tool function (decorator-capture pattern)
# ---------------------------------------------------------------------------


@pytest.fixture
def tool_fn():
    """Return the raw qbo_sync coroutine extracted from a one-shot FastMCP."""
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
# 1. CDC calls change_data_capture with correct entity list and date
# ---------------------------------------------------------------------------


class TestCDC:
    @pytest.mark.asyncio
    async def test_cdc_calls_with_correct_args(self, tool_fn) -> None:
        cdc_result = {"Invoice": [_make_obj_mock("1")], "Customer": [_make_obj_mock("42")]}
        client = _make_client_mock()
        ctx = _make_ctx(client)

        # We need to intercept the inner _fetch closure that calls change_data_capture.
        # Use a side_effect to capture what change_data_capture sees.
        captured_args: dict = {}

        async def execute_side_effect(fn, *args, **kwargs):
            import quickbooks.cdc as cdc_mod

            with patch.object(
                cdc_mod,
                "change_data_capture",
                side_effect=lambda entities, since, qb=None: (
                    captured_args.update({"entities": entities, "since": since}) or cdc_result
                ),
            ):
                return fn()

        client.execute = execute_side_effect

        with patch("quickbooks_mcp.server.get_client", return_value=client):
            result = await tool_fn(
                ctx=ctx,
                operation="cdc",
                entities=["Invoice", "Customer"],
                changed_since="2024-01-01T00:00:00",
            )

        assert captured_args["entities"] == ["Invoice", "Customer"]
        assert captured_args["since"] == "2024-01-01T00:00:00"
        assert result["status"] == "ok"
        assert result["operation"] == "cdc"

    # ---------------------------------------------------------------------------
    # 2. CDC converts results to snake_case
    # ---------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_cdc_converts_to_snake_case(self, tool_fn) -> None:
        invoice_obj = MagicMock()
        invoice_obj.to_dict.return_value = {
            "Id": "1",
            "TotalAmt": 1500.00,
            "CustomerRef": {"value": "42", "name": "Smith Freight"},
        }
        cdc_result = {"Invoice": [invoice_obj]}
        client = _make_client_mock(execute_return=cdc_result)
        ctx = _make_ctx(client)

        with patch("quickbooks_mcp.server.get_client", return_value=client):
            result = await tool_fn(
                ctx=ctx,
                operation="cdc",
                entities=["Invoice"],
                changed_since="2024-01-01T00:00:00",
            )

        assert result["status"] == "ok"
        invoices = result["data"][0]["Invoice"]
        assert invoices[0]["id"] == "1"
        assert invoices[0]["total_amt"] == 1500.00
        assert "customer_ref" in invoices[0]

    # ---------------------------------------------------------------------------
    # 9a. CDC missing entities raises ToolError
    # ---------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_cdc_missing_entities_raises(self, tool_fn) -> None:
        client = _make_client_mock()
        ctx = _make_ctx(client)

        with (
            patch("quickbooks_mcp.server.get_client", return_value=client),
            pytest.raises(ToolError, match="entities is required"),
        ):
            await tool_fn(
                ctx=ctx,
                operation="cdc",
                changed_since="2024-01-01T00:00:00",
            )

    @pytest.mark.asyncio
    async def test_cdc_missing_changed_since_raises(self, tool_fn) -> None:
        client = _make_client_mock()
        ctx = _make_ctx(client)

        with (
            patch("quickbooks_mcp.server.get_client", return_value=client),
            pytest.raises(ToolError, match="changed_since is required"),
        ):
            await tool_fn(
                ctx=ctx,
                operation="cdc",
                entities=["Invoice"],
            )


# ---------------------------------------------------------------------------
# 3. Batch with valid operations succeeds
# ---------------------------------------------------------------------------


class TestBatch:
    @pytest.mark.asyncio
    async def test_batch_create_succeeds(self, tool_fn) -> None:
        ops = [
            {
                "operation": "create",
                "entity_type": "Customer",
                "data": {"DisplayName": "New Corp"},
            }
        ]
        # execute returns a result_id for create
        client = _make_client_mock(execute_return="99")
        ctx = _make_ctx(client)

        with patch("quickbooks_mcp.server.get_client", return_value=client):
            result = await tool_fn(ctx=ctx, operation="batch", operations=ops, preview=False)

        assert result["status"] == "ok"
        assert len(result["succeeded"]) == 1
        assert result["succeeded"][0]["operation"] == "create"
        assert result["succeeded"][0]["entity_type"] == "Customer"
        assert len(result["failed"]) == 0
        assert "1 of 1" in result["summary"]

    # ---------------------------------------------------------------------------
    # 4. Batch partial success
    # ---------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_batch_partial_success(self, tool_fn) -> None:
        ops = [
            {
                "operation": "create",
                "entity_type": "Customer",
                "data": {"DisplayName": "OK Corp"},
            },
            {
                "operation": "create",
                "entity_type": "Customer",
                "data": {"DisplayName": "Bad Corp"},
            },
        ]

        call_count = 0

        async def execute_side_effect(fn, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "10"
            raise Exception("API error: duplicate name")

        client = _make_client_mock()
        client.execute = execute_side_effect
        ctx = _make_ctx(client)

        with patch("quickbooks_mcp.server.get_client", return_value=client):
            result = await tool_fn(ctx=ctx, operation="batch", operations=ops, preview=False)

        assert result["status"] == "partial"
        assert len(result["succeeded"]) == 1
        assert len(result["failed"]) == 1
        assert result["failed"][0]["index"] == 1
        assert "API error" in result["failed"][0]["error"]

    # ---------------------------------------------------------------------------
    # 5. Batch rejects > 30 operations
    # ---------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_batch_rejects_over_30_ops(self, tool_fn) -> None:
        ops = [{"operation": "create", "entity_type": "Customer", "data": {}} for _ in range(31)]
        client = _make_client_mock()
        ctx = _make_ctx(client)

        with (
            patch("quickbooks_mcp.server.get_client", return_value=client),
            pytest.raises(ToolError, match="Maximum 30 operations"),
        ):
            await tool_fn(ctx=ctx, operation="batch", operations=ops, preview=False)

    # ---------------------------------------------------------------------------
    # 6. Batch accepts native list of dicts (type safety)
    # ---------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_batch_accepts_native_list(self, tool_fn) -> None:
        """operations now accepts a native list[dict], not a JSON string."""
        ops = [
            {
                "operation": "create",
                "entity_type": "Invoice",
                "data": {"CustomerRef": {"value": "42"}},
            }
        ]
        client = _make_client_mock(execute_return="50")
        ctx = _make_ctx(client)

        with patch("quickbooks_mcp.server.get_client", return_value=client):
            result = await tool_fn(ctx=ctx, operation="batch", operations=ops, preview=False)

        assert result["status"] == "ok"
        assert len(result["succeeded"]) == 1

    # ---------------------------------------------------------------------------
    # 9b. Batch missing operations raises ToolError
    # ---------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_batch_missing_operations_raises(self, tool_fn) -> None:
        client = _make_client_mock()
        ctx = _make_ctx(client)

        with (
            patch("quickbooks_mcp.server.get_client", return_value=client),
            pytest.raises(ToolError, match="operations is required"),
        ):
            await tool_fn(ctx=ctx, operation="batch")

    # ---------------------------------------------------------------------------
    # 10. Batch markdown format returns string
    # ---------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_batch_markdown_returns_string(self, tool_fn) -> None:
        ops = [{"operation": "create", "entity_type": "Customer", "data": {"DisplayName": "Test"}}]
        client = _make_client_mock(execute_return="55")
        ctx = _make_ctx(client)

        with patch("quickbooks_mcp.server.get_client", return_value=client):
            result = await tool_fn(
                ctx=ctx,
                operation="batch",
                operations=ops,
                preview=False,
                response_format="markdown",
            )

        assert isinstance(result, str)
        assert "Batch Result" in result
        assert "1 of 1" in result


# ---------------------------------------------------------------------------
# 7. Count builds correct SELECT COUNT query
# ---------------------------------------------------------------------------


class TestCount:
    @pytest.mark.asyncio
    async def test_count_builds_correct_query(self, tool_fn) -> None:
        client = _make_client_mock()
        ctx = _make_ctx(client)
        client.qb_client.query = MagicMock(return_value={"totalCount": 42})

        async def execute_side_effect(fn, *args, **kwargs):
            return fn()

        client.execute = execute_side_effect

        with patch("quickbooks_mcp.server.get_client", return_value=client):
            result = await tool_fn(ctx=ctx, operation="count", entity_type="Invoice")

        client.qb_client.query.assert_called_once_with("SELECT COUNT(*) FROM Invoice")
        assert result["status"] == "ok"
        assert result["data"][0]["count"] == 42
        assert result["data"][0]["entity_type"] == "Invoice"

    # ---------------------------------------------------------------------------
    # 8. Count with WHERE clause
    # ---------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_count_with_where_clause(self, tool_fn) -> None:
        client = _make_client_mock()
        ctx = _make_ctx(client)
        client.qb_client.query = MagicMock(return_value={"totalCount": 7})

        async def execute_side_effect(fn, *args, **kwargs):
            return fn()

        client.execute = execute_side_effect

        with patch("quickbooks_mcp.server.get_client", return_value=client):
            result = await tool_fn(
                ctx=ctx,
                operation="count",
                entity_type="Invoice",
                query="TotalAmt > '100.00'",
            )

        expected_sql = "SELECT COUNT(*) FROM Invoice WHERE TotalAmt > '100.00'"
        client.qb_client.query.assert_called_once_with(expected_sql)
        assert result["data"][0]["count"] == 7
        assert result["data"][0]["query"] == expected_sql

    @pytest.mark.asyncio
    async def test_count_handles_list_result(self, tool_fn) -> None:
        """count falls back to len(result) when SDK returns a list."""
        client = _make_client_mock()
        ctx = _make_ctx(client)
        # Some SDK versions return a list of matching objects instead of totalCount dict
        client.qb_client.query = MagicMock(return_value=[{"Id": "1"}, {"Id": "2"}, {"Id": "3"}])

        async def execute_side_effect(fn, *args, **kwargs):
            return fn()

        client.execute = execute_side_effect

        with patch("quickbooks_mcp.server.get_client", return_value=client):
            result = await tool_fn(ctx=ctx, operation="count", entity_type="Customer")

        assert result["data"][0]["count"] == 3

    # ---------------------------------------------------------------------------
    # 9c. Count missing entity_type raises ToolError
    # ---------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_count_missing_entity_type_raises(self, tool_fn) -> None:
        client = _make_client_mock()
        ctx = _make_ctx(client)

        with (
            patch("quickbooks_mcp.server.get_client", return_value=client),
            pytest.raises(ToolError, match="entity_type is required"),
        ):
            await tool_fn(ctx=ctx, operation="count")

    # ---------------------------------------------------------------------------
    # 10. Count markdown format returns string
    # ---------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_count_markdown_returns_string(self, tool_fn) -> None:
        client = _make_client_mock(execute_return={"totalCount": 5})
        ctx = _make_ctx(client)

        with patch("quickbooks_mcp.server.get_client", return_value=client):
            result = await tool_fn(
                ctx=ctx,
                operation="count",
                entity_type="Invoice",
                response_format="markdown",
            )

        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# 11. Batch preview=True returns summary without executing
# ---------------------------------------------------------------------------


class TestBatchPreview:
    @pytest.mark.asyncio
    async def test_batch_preview_returns_summary(self, tool_fn) -> None:
        """preview=True (default) returns a summary of what would happen."""
        ops = [
            {
                "operation": "create",
                "entity_type": "Customer",
                "data": {"DisplayName": "Preview Corp"},
            },
            {
                "operation": "delete",
                "entity_type": "Invoice",
                "id": "42",
            },
        ]
        client = _make_client_mock()
        ctx = _make_ctx(client)

        with patch("quickbooks_mcp.server.get_client", return_value=client):
            result = await tool_fn(ctx=ctx, operation="batch", operations=ops)

        assert result["status"] == "preview"
        assert result["operation"] == "batch"
        assert result["operations_count"] == 2
        assert len(result["summary"]) == 2
        assert result["summary"][0]["operation"] == "create"
        assert result["summary"][0]["entity_type"] == "Customer"
        assert result["summary"][1]["operation"] == "delete"
        assert result["summary"][1]["id"] == "42"
        assert "preview=False" in result["warning"]
        # Ensure no actual execution happened
        client.execute.assert_not_called()

    # ---------------------------------------------------------------------------
    # 12. Batch preview=False actually executes
    # ---------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_batch_preview_false_executes(self, tool_fn) -> None:
        """preview=False bypasses preview and actually executes batch."""
        ops = [
            {
                "operation": "create",
                "entity_type": "Customer",
                "data": {"DisplayName": "Execute Corp"},
            }
        ]
        client = _make_client_mock(execute_return="77")
        ctx = _make_ctx(client)

        with patch("quickbooks_mcp.server.get_client", return_value=client):
            result = await tool_fn(
                ctx=ctx,
                operation="batch",
                operations=ops,
                preview=False,
            )

        assert result["status"] == "ok"
        assert len(result["succeeded"]) == 1
        assert result["succeeded"][0]["id"] == "77"

    # ---------------------------------------------------------------------------
    # 13. Batch preview validates operations
    # ---------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_batch_preview_catches_validation_errors(self, tool_fn) -> None:
        """preview catches invalid operations without executing."""
        ops = [
            {
                "operation": "create",
                "entity_type": "Customer",
                "data": {"DisplayName": "Good"},
            },
            {
                "operation": "read",  # invalid operation
                "entity_type": "Invoice",
            },
            {
                "operation": "delete",
                "entity_type": "Invoice",
                # missing id
            },
        ]
        client = _make_client_mock()
        ctx = _make_ctx(client)

        with patch("quickbooks_mcp.server.get_client", return_value=client):
            result = await tool_fn(ctx=ctx, operation="batch", operations=ops)

        assert result["status"] == "preview"
        assert result["operations_count"] == 3
        assert len(result["summary"]) == 1  # only the valid create
        assert len(result["validation_errors"]) == 2
        client.execute.assert_not_called()

    # ---------------------------------------------------------------------------
    # 14. Batch preview rejects > 30 ops
    # ---------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_batch_preview_rejects_over_30(self, tool_fn) -> None:
        ops = [{"operation": "create", "entity_type": "Customer", "data": {}} for _ in range(31)]
        client = _make_client_mock()
        ctx = _make_ctx(client)

        with (
            patch("quickbooks_mcp.server.get_client", return_value=client),
            pytest.raises(ToolError, match="Maximum 30 operations"),
        ):
            await tool_fn(ctx=ctx, operation="batch", operations=ops)

    # ---------------------------------------------------------------------------
    # 15. CDC and count ignore preview param
    # ---------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_cdc_ignores_preview_param(self, tool_fn) -> None:
        """CDC should work normally regardless of preview value."""
        cdc_result = {"Invoice": [_make_obj_mock("1")]}
        client = _make_client_mock(execute_return=cdc_result)
        ctx = _make_ctx(client)

        with patch("quickbooks_mcp.server.get_client", return_value=client):
            result = await tool_fn(
                ctx=ctx,
                operation="cdc",
                entities=["Invoice"],
                changed_since="2024-01-01T00:00:00",
                preview=True,  # should be ignored
            )

        assert result["status"] == "ok"
        assert result["operation"] == "cdc"
