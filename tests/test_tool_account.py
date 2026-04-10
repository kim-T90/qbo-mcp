"""Tests for the qbo_account tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.exceptions import ToolError

from quickbooks_mcp.tools.account import register

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_account_mock(
    id_: str = "1",
    name: str = "Checking",
    account_type: str = "Bank",
    current_balance: float = 25000.00,
    active: bool = True,
) -> MagicMock:
    """Return a mock Account object with to_dict()."""
    account = MagicMock()
    account.to_dict.return_value = {
        "Id": id_,
        "Name": name,
        "AccountType": account_type,
        "CurrentBalance": current_balance,
        "Active": active,
        "SyncToken": "0",
    }
    return account


def _make_client_mock(execute_return=None) -> MagicMock:
    """Return a mock QBOClient with async execute and a MagicMock qb_client."""
    client = MagicMock()
    client.qb_client = MagicMock()
    client.execute = AsyncMock(return_value=execute_return)
    client.query_rows = AsyncMock(return_value=execute_return)
    client.query_count = AsyncMock()
    return client


def _make_ctx(client: MagicMock) -> MagicMock:
    """Return a mock FastMCP Context backed by *client*."""
    ctx = MagicMock()
    ctx.request_context.lifespan_context.client = client
    return ctx


# ---------------------------------------------------------------------------
# Fixture: registered tool function
# ---------------------------------------------------------------------------


@pytest.fixture
def tool_fn():
    """Return the raw qbo_account coroutine extracted from a one-shot FastMCP."""
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
# 1. list returns paginated accounts
# ---------------------------------------------------------------------------


class TestList:
    @pytest.mark.asyncio
    async def test_list_returns_paginated_accounts(self, tool_fn) -> None:
        accounts = [_make_account_mock(id_=str(i)) for i in range(5)]
        client = _make_client_mock(execute_return=accounts)
        ctx = _make_ctx(client)

        with patch("quickbooks_mcp.server.get_client", return_value=client):
            result = await tool_fn(ctx=ctx, operation="list", max_results=3, offset=0)

        assert result["status"] == "ok"
        assert result["operation"] == "list"
        assert result["entity_type"] == "Account"
        assert len(result["data"]) == 3
        assert result["metadata"]["max_results"] == 3
        assert result["metadata"]["has_more"] is True

    @pytest.mark.asyncio
    async def test_list_inactive_included_when_active_only_false(self, tool_fn) -> None:
        accounts = [_make_account_mock(active=False)]
        client = _make_client_mock(execute_return=accounts)
        ctx = _make_ctx(client)

        with patch("quickbooks_mcp.server.get_client", return_value=client):
            result = await tool_fn(ctx=ctx, operation="list", active_only=False)

        assert result["status"] == "ok"
        assert result["data"][0]["active"] is False


# ---------------------------------------------------------------------------
# 2. get returns single account by ID
# ---------------------------------------------------------------------------


class TestGet:
    @pytest.mark.asyncio
    async def test_get_returns_single_account(self, tool_fn) -> None:
        account = _make_account_mock(id_="42", name="Savings")
        client = _make_client_mock(execute_return=account)
        ctx = _make_ctx(client)

        with patch("quickbooks_mcp.server.get_client", return_value=client):
            result = await tool_fn(ctx=ctx, operation="get", id="42")

        assert result["status"] == "ok"
        assert result["operation"] == "get"
        assert result["data"][0]["id"] == "42"
        assert result["data"][0]["name"] == "Savings"


# ---------------------------------------------------------------------------
# 3. create with name and type succeeds
# ---------------------------------------------------------------------------


class TestCreate:
    @pytest.mark.asyncio
    async def test_create_returns_new_account(self, tool_fn) -> None:
        account = _make_account_mock(id_="99", name="Payroll", account_type="Expense")
        client = _make_client_mock(execute_return=account)
        ctx = _make_ctx(client)

        with patch("quickbooks_mcp.server.get_client", return_value=client):
            result = await tool_fn(
                ctx=ctx,
                operation="create",
                name="Payroll",
                account_type="Expense",
            )

        assert result["status"] == "ok"
        assert result["operation"] == "create"
        assert result["data"][0]["id"] == "99"

    @pytest.mark.asyncio
    async def test_create_with_sub_type(self, tool_fn) -> None:
        account = _make_account_mock(id_="5", name="Chase Checking", account_type="Bank")
        client = _make_client_mock(execute_return=account)
        ctx = _make_ctx(client)

        with patch("quickbooks_mcp.server.get_client", return_value=client):
            result = await tool_fn(
                ctx=ctx,
                operation="create",
                name="Chase Checking",
                account_type="Bank",
                account_sub_type="Checking",
            )

        assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# 4. update fetches SyncToken then saves
# ---------------------------------------------------------------------------


class TestUpdate:
    @pytest.mark.asyncio
    async def test_update_calls_execute_once(self, tool_fn) -> None:
        """execute() is called once — the inner fn does get + save atomically."""
        account = _make_account_mock(id_="7", name="Updated Name")
        client = _make_client_mock(execute_return=account)
        ctx = _make_ctx(client)

        with patch("quickbooks_mcp.server.get_client", return_value=client):
            result = await tool_fn(
                ctx=ctx,
                operation="update",
                id="7",
                name="Updated Name",
            )

        assert result["status"] == "ok"
        assert result["operation"] == "update"
        # execute() called exactly once (get+save bundled in the closure)
        assert client.execute.call_count == 1


# ---------------------------------------------------------------------------
# 5. deactivate sets Active=False
# ---------------------------------------------------------------------------


class TestDeactivate:
    @pytest.mark.asyncio
    async def test_deactivate_returns_inactive_account(self, tool_fn) -> None:
        account = _make_account_mock(id_="3", active=False)
        client = _make_client_mock(execute_return=account)
        ctx = _make_ctx(client)

        with patch("quickbooks_mcp.server.get_client", return_value=client):
            result = await tool_fn(ctx=ctx, operation="deactivate", id="3")

        assert result["status"] == "ok"
        assert result["operation"] == "deactivate"
        assert result["data"][0]["active"] is False

    @pytest.mark.asyncio
    async def test_deactivate_passes_active_false_to_sdk(self, tool_fn) -> None:
        """Verify the closure sets Active=False on the fetched account object."""
        fetched = MagicMock()
        fetched.Active = True
        fetched.to_dict.return_value = {"Id": "3", "Active": False, "SyncToken": "1"}
        client = MagicMock()
        client.qb_client = MagicMock()

        async def execute_side_effect(fn, *args, **kwargs):
            # Run the closure synchronously to inspect side-effects
            from quickbooks.objects.account import Account  # noqa: F401

            with patch("quickbooks.objects.account.Account.get", return_value=fetched):
                fn()
            return fetched

        client.execute = execute_side_effect
        ctx = _make_ctx(client)

        with patch("quickbooks_mcp.server.get_client", return_value=client):
            await tool_fn(ctx=ctx, operation="deactivate", id="3")

        assert fetched.Active is False
        fetched.save.assert_called_once()


# ---------------------------------------------------------------------------
# 6. search passes query to QBO
# ---------------------------------------------------------------------------


class TestSearch:
    @pytest.mark.asyncio
    async def test_search_returns_matching_accounts(self, tool_fn) -> None:
        # qb.query returns dicts (raw JSON), not model objects
        raw = [{"Id": "10", "Name": "Checking", "AccountType": "Bank"}]
        client = _make_client_mock(execute_return=raw)
        ctx = _make_ctx(client)

        with patch("quickbooks_mcp.server.get_client", return_value=client):
            result = await tool_fn(
                ctx=ctx,
                operation="search",
                query="AccountType = 'Bank'",
            )

        assert result["status"] == "ok"
        assert result["operation"] == "search"
        assert result["data"][0]["name"] == "Checking"

    @pytest.mark.asyncio
    async def test_search_builds_correct_sql(self, tool_fn) -> None:
        """Verify the IDS SELECT is constructed from the WHERE clause."""
        client = MagicMock()
        client.qb_client = MagicMock()
        client.query_rows = AsyncMock(return_value=[])
        ctx = _make_ctx(client)

        with patch("quickbooks_mcp.server.get_client", return_value=client):
            await tool_fn(
                ctx=ctx,
                operation="search",
                query="Name LIKE '%Truck%'",
            )

        client.query_rows.assert_awaited_once_with(
            "SELECT * FROM Account WHERE Name LIKE '%Truck%'", "Account"
        )


# ---------------------------------------------------------------------------
# 7. get without id raises ToolError
# ---------------------------------------------------------------------------


class TestGetValidation:
    @pytest.mark.asyncio
    async def test_get_without_id_raises(self, tool_fn) -> None:
        client = _make_client_mock()
        ctx = _make_ctx(client)

        with (
            patch("quickbooks_mcp.server.get_client", return_value=client),
            pytest.raises(ToolError, match="id is required"),
        ):
            await tool_fn(ctx=ctx, operation="get")


# ---------------------------------------------------------------------------
# 8. create without name raises ToolError
# ---------------------------------------------------------------------------


class TestCreateValidation:
    @pytest.mark.asyncio
    async def test_create_without_name_raises(self, tool_fn) -> None:
        client = _make_client_mock()
        ctx = _make_ctx(client)

        with (
            patch("quickbooks_mcp.server.get_client", return_value=client),
            pytest.raises(ToolError, match="name is required"),
        ):
            await tool_fn(ctx=ctx, operation="create", account_type="Bank")

    @pytest.mark.asyncio
    async def test_create_without_account_type_raises(self, tool_fn) -> None:
        client = _make_client_mock()
        ctx = _make_ctx(client)

        with (
            patch("quickbooks_mcp.server.get_client", return_value=client),
            pytest.raises(ToolError, match="account_type is required"),
        ):
            await tool_fn(ctx=ctx, operation="create", name="My Account")


# ---------------------------------------------------------------------------
# 9. extra with protected key raises ToolError
# ---------------------------------------------------------------------------


class TestExtraValidation:
    @pytest.mark.asyncio
    async def test_extra_with_protected_key_raises(self, tool_fn) -> None:
        client = _make_client_mock()
        ctx = _make_ctx(client)

        with (
            patch("quickbooks_mcp.server.get_client", return_value=client),
            pytest.raises(ToolError, match="protected keys"),
        ):
            await tool_fn(
                ctx=ctx,
                operation="create",
                name="Test",
                account_type="Bank",
                extra={"SyncToken": "99", "Description": "ok"},
            )

    @pytest.mark.asyncio
    async def test_extra_with_all_protected_keys_raises(self, tool_fn) -> None:
        client = _make_client_mock()
        ctx = _make_ctx(client)

        with (
            patch("quickbooks_mcp.server.get_client", return_value=client),
            pytest.raises(ToolError, match="protected keys"),
        ):
            await tool_fn(
                ctx=ctx,
                operation="update",
                id="1",
                extra={"Id": "1", "MetaData": {}},
            )


# ---------------------------------------------------------------------------
# 10. invalid operation raises ToolError
# ---------------------------------------------------------------------------


class TestInvalidOperation:
    @pytest.mark.asyncio
    async def test_invalid_operation_raises(self, tool_fn) -> None:
        """Passing an unknown operation string should raise ToolError."""
        client = _make_client_mock()
        ctx = _make_ctx(client)

        with (
            patch("quickbooks_mcp.server.get_client", return_value=client),
            pytest.raises((ToolError, Exception)),
        ):
            # Bypasses Literal type check at runtime — hits the fallback raise
            await tool_fn(ctx=ctx, operation="delete")  # type: ignore[arg-type]
