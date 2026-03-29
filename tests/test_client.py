"""Tests for QBOClient — async-safe wrapper around python-quickbooks."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from fastmcp.exceptions import ToolError
from quickbooks.exceptions import AuthorizationException, QuickbooksException

from quickbooks_mcp.client import QBOClient
from quickbooks_mcp.config import QBOConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(qbo_config: QBOConfig) -> QBOClient:
    """Create a QBOClient directly from config (bypasses find_dotenv)."""
    with patch("quickbooks_mcp.client.find_dotenv", return_value=""):
        return QBOClient(qbo_config)


def _attach_mock_qb(client: QBOClient, mock_qb: MagicMock) -> None:
    """Inject a mock QuickBooks client so execute() doesn't need connect()."""
    client._qb_client = mock_qb


# ---------------------------------------------------------------------------
# from_config
# ---------------------------------------------------------------------------


class TestFromConfig:
    def test_creates_instance(self, env_vars: dict[str, str]) -> None:
        with (
            patch("quickbooks_mcp.client.find_dotenv", return_value=""),
            patch("quickbooks_mcp.config.find_dotenv", return_value=""),
        ):
            client = QBOClient.from_config()
        assert isinstance(client, QBOClient)
        assert client.realm_id == env_vars["QBO_REALM_ID"]
        assert client.environment == env_vars["QBO_ENVIRONMENT"]


# ---------------------------------------------------------------------------
# execute — success path
# ---------------------------------------------------------------------------


class TestExecuteSuccess:
    @pytest.mark.asyncio
    async def test_calls_fn_via_to_thread(
        self, qbo_config: QBOConfig, mock_qb_client: MagicMock
    ) -> None:
        client = _make_client(qbo_config)
        _attach_mock_qb(client, mock_qb_client)

        def sync_fn(x: int) -> int:
            return x * 2

        result = await client.execute(sync_fn, 21)
        assert result == 42

    @pytest.mark.asyncio
    async def test_passes_kwargs_to_fn(
        self, qbo_config: QBOConfig, mock_qb_client: MagicMock
    ) -> None:
        client = _make_client(qbo_config)
        _attach_mock_qb(client, mock_qb_client)

        def sync_fn(*, value: str) -> str:
            return value.upper()

        result = await client.execute(sync_fn, value="hello")
        assert result == "HELLO"


# ---------------------------------------------------------------------------
# execute — 401 / AuthorizationException retry
# ---------------------------------------------------------------------------


class TestExecute401Retry:
    @pytest.mark.asyncio
    async def test_refreshes_and_retries_on_first_401(
        self, qbo_config: QBOConfig, mock_qb_client: MagicMock, mock_auth_client: MagicMock
    ) -> None:
        mock_qb_client.auth_client = mock_auth_client
        mock_auth_client.refresh = MagicMock()
        mock_auth_client.access_token = "new_access_token"
        mock_auth_client.refresh_token = "new_refresh_token"

        client = _make_client(qbo_config)
        _attach_mock_qb(client, mock_qb_client)
        client._env_path = None  # skip disk persistence

        call_count = 0

        def sync_fn() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise AuthorizationException("Unauthorized")
            return "ok"

        result = await client.execute(sync_fn)
        assert result == "ok"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_raises_tool_error_after_second_401(
        self, qbo_config: QBOConfig, mock_qb_client: MagicMock, mock_auth_client: MagicMock
    ) -> None:
        mock_qb_client.auth_client = mock_auth_client
        mock_auth_client.refresh = MagicMock()
        mock_auth_client.access_token = "new_token"
        mock_auth_client.refresh_token = "new_refresh"

        client = _make_client(qbo_config)
        _attach_mock_qb(client, mock_qb_client)
        client._env_path = None

        def always_401() -> None:
            raise AuthorizationException("Unauthorized")

        with pytest.raises(ToolError, match="authorization failed after token refresh"):
            await client.execute(always_401)


# ---------------------------------------------------------------------------
# execute — 429 / rate-limit backoff
# ---------------------------------------------------------------------------


class TestExecute429Backoff:
    def _make_429(self) -> QuickbooksException:
        exc = QuickbooksException("Rate limited")
        exc.status_code = 429  # type: ignore[attr-defined]
        return exc

    @pytest.mark.asyncio
    async def test_retries_with_backoff_on_429(
        self, qbo_config: QBOConfig, mock_qb_client: MagicMock
    ) -> None:
        client = _make_client(qbo_config)
        _attach_mock_qb(client, mock_qb_client)
        client._backoff_base = 0.0  # zero jitter for determinism

        call_count = 0

        def flaky_fn() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise self._make_429()
            return "ok"

        with patch("quickbooks_mcp.client.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await client.execute(flaky_fn)

        assert result == "ok"
        assert call_count == 3
        assert mock_sleep.call_count == 2

    @pytest.mark.asyncio
    async def test_sleep_called_with_increasing_backoff(
        self, qbo_config: QBOConfig, mock_qb_client: MagicMock
    ) -> None:
        client = _make_client(qbo_config)
        _attach_mock_qb(client, mock_qb_client)
        # Force deterministic non-zero values by patching random.uniform
        with (
            patch("quickbooks_mcp.client.random.uniform", side_effect=[1.0, 2.0]),
            patch("quickbooks_mcp.client.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):
            call_count = 0

            def flaky_fn() -> str:
                nonlocal call_count
                call_count += 1
                if call_count < 3:
                    raise self._make_429()
                return "done"

            await client.execute(flaky_fn)

        assert mock_sleep.call_args_list == [call(1.0), call(2.0)]

    @pytest.mark.asyncio
    async def test_raises_tool_error_after_3_failed_429s(
        self, qbo_config: QBOConfig, mock_qb_client: MagicMock
    ) -> None:
        client = _make_client(qbo_config)
        _attach_mock_qb(client, mock_qb_client)
        client._backoff_base = 0.0

        def always_429() -> None:
            raise self._make_429()

        with (
            patch("quickbooks_mcp.client.asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(ToolError, match="rate limit exceeded after 3 attempts"),
        ):
            await client.execute(always_429)


# ---------------------------------------------------------------------------
# execute — other QuickbooksException
# ---------------------------------------------------------------------------


class TestExecuteOtherException:
    @pytest.mark.asyncio
    async def test_raises_tool_error_on_other_qbo_exception(
        self, qbo_config: QBOConfig, mock_qb_client: MagicMock
    ) -> None:
        client = _make_client(qbo_config)
        _attach_mock_qb(client, mock_qb_client)

        exc = QuickbooksException("Something went wrong")
        exc.status_code = 500  # type: ignore[attr-defined]
        exc.message = "Internal Server Error"  # type: ignore[attr-defined]
        exc.detail = "Unexpected condition"  # type: ignore[attr-defined]

        def failing_fn() -> None:
            raise exc

        with pytest.raises(ToolError, match="QuickBooks API error"):
            await client.execute(failing_fn)

    @pytest.mark.asyncio
    async def test_tool_error_includes_detail_when_present(
        self, qbo_config: QBOConfig, mock_qb_client: MagicMock
    ) -> None:
        client = _make_client(qbo_config)
        _attach_mock_qb(client, mock_qb_client)

        exc = QuickbooksException("Boom")
        exc.status_code = 400  # type: ignore[attr-defined]
        exc.message = "Bad request"  # type: ignore[attr-defined]
        exc.detail = "Invalid field: TxnDate"  # type: ignore[attr-defined]

        def failing_fn() -> None:
            raise exc

        with pytest.raises(ToolError, match="Invalid field: TxnDate"):
            await client.execute(failing_fn)


# ---------------------------------------------------------------------------
# _refresh_token — lock behaviour
# ---------------------------------------------------------------------------


class TestRefreshTokenLock:
    @pytest.mark.asyncio
    async def test_lock_prevents_concurrent_refreshes(
        self, qbo_config: QBOConfig, mock_qb_client: MagicMock, mock_auth_client: MagicMock
    ) -> None:
        mock_qb_client.auth_client = mock_auth_client
        refresh_call_count = 0

        def counting_refresh() -> None:
            nonlocal refresh_call_count
            refresh_call_count += 1

        mock_auth_client.refresh = counting_refresh
        mock_auth_client.access_token = "tok"
        mock_auth_client.refresh_token = "rtok"

        client = _make_client(qbo_config)
        _attach_mock_qb(client, mock_qb_client)
        client._env_path = None

        # Fire two concurrent refreshes — lock ensures sequential execution.
        await asyncio.gather(client._refresh_token(), client._refresh_token())

        # Both should complete (lock serialises, not skips).
        assert refresh_call_count == 2

    @pytest.mark.asyncio
    async def test_raises_tool_error_on_invalid_grant(
        self, qbo_config: QBOConfig, mock_qb_client: MagicMock, mock_auth_client: MagicMock
    ) -> None:
        mock_qb_client.auth_client = mock_auth_client
        mock_auth_client.refresh.side_effect = Exception("invalid_grant: token expired")

        client = _make_client(qbo_config)
        _attach_mock_qb(client, mock_qb_client)

        with pytest.raises(ToolError, match="Re-run auth"):
            await client._refresh_token()

    @pytest.mark.asyncio
    async def test_raises_tool_error_on_other_refresh_error(
        self, qbo_config: QBOConfig, mock_qb_client: MagicMock, mock_auth_client: MagicMock
    ) -> None:
        mock_qb_client.auth_client = mock_auth_client
        mock_auth_client.refresh.side_effect = Exception("network timeout")

        client = _make_client(qbo_config)
        _attach_mock_qb(client, mock_qb_client)

        with pytest.raises(ToolError, match="token refresh failed"):
            await client._refresh_token()


# ---------------------------------------------------------------------------
# _persist_token — atomic .env update
# ---------------------------------------------------------------------------


class TestPersistToken:
    @pytest.mark.asyncio
    async def test_replaces_existing_token_line(
        self, qbo_config: QBOConfig, tmp_env_file: Path
    ) -> None:
        client = _make_client(qbo_config)
        client._env_path = tmp_env_file

        await client._persist_token("brand_new_token")

        content = tmp_env_file.read_text()
        assert "QBO_REFRESH_TOKEN=brand_new_token" in content
        assert "old_refresh_token" not in content

    @pytest.mark.asyncio
    async def test_preserves_other_lines(self, qbo_config: QBOConfig, tmp_env_file: Path) -> None:
        client = _make_client(qbo_config)
        client._env_path = tmp_env_file

        await client._persist_token("brand_new_token")

        content = tmp_env_file.read_text()
        assert "QBO_CLIENT_ID=test_client_id" in content
        assert "QBO_ENVIRONMENT=sandbox" in content

    @pytest.mark.asyncio
    async def test_appends_token_line_when_not_present(
        self, qbo_config: QBOConfig, tmp_path: Path
    ) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("QBO_CLIENT_ID=abc\nQBO_CLIENT_SECRET=xyz\n")

        client = _make_client(qbo_config)
        client._env_path = env_file

        await client._persist_token("appended_token")

        content = env_file.read_text()
        assert "QBO_REFRESH_TOKEN=appended_token" in content
        assert "QBO_CLIENT_ID=abc" in content

    @pytest.mark.asyncio
    async def test_no_op_when_env_path_is_none(self, qbo_config: QBOConfig) -> None:
        client = _make_client(qbo_config)
        client._env_path = None

        # Should not raise; just log a warning.
        await client._persist_token("some_token")

    @pytest.mark.asyncio
    async def test_no_op_when_env_file_missing(self, qbo_config: QBOConfig, tmp_path: Path) -> None:
        nonexistent = tmp_path / ".env"
        client = _make_client(qbo_config)
        client._env_path = nonexistent

        # Should not raise.
        await client._persist_token("some_token")

    @pytest.mark.asyncio
    async def test_write_is_atomic_via_os_replace(
        self, qbo_config: QBOConfig, tmp_env_file: Path
    ) -> None:
        """os.replace should be called (atomic rename) not direct open/write."""
        import os

        client = _make_client(qbo_config)
        client._env_path = tmp_env_file

        with patch("quickbooks_mcp.client.os.replace", wraps=os.replace) as mock_replace:
            await client._persist_token("atomic_token")

        assert mock_replace.call_count == 1
        # Destination of replace() must be the original .env path.
        _, dest = mock_replace.call_args[0]
        assert Path(dest) == tmp_env_file


# ---------------------------------------------------------------------------
# qb_client property
# ---------------------------------------------------------------------------


class TestQbClientProperty:
    def test_raises_when_not_connected(self, qbo_config: QBOConfig) -> None:
        client = _make_client(qbo_config)
        # _qb_client is None until connect() is called.
        with pytest.raises(ToolError, match="not connected"):
            _ = client.qb_client

    def test_returns_client_when_connected(
        self, qbo_config: QBOConfig, mock_qb_client: MagicMock
    ) -> None:
        client = _make_client(qbo_config)
        _attach_mock_qb(client, mock_qb_client)
        assert client.qb_client is mock_qb_client


# ---------------------------------------------------------------------------
# realm_id and environment properties
# ---------------------------------------------------------------------------


class TestProperties:
    def test_realm_id_returns_config_value(self, qbo_config: QBOConfig) -> None:
        client = _make_client(qbo_config)
        assert client.realm_id == qbo_config.realm_id

    def test_environment_returns_config_value(self, qbo_config: QBOConfig) -> None:
        client = _make_client(qbo_config)
        assert client.environment == qbo_config.environment

    def test_realm_id_value(self, qbo_config: QBOConfig) -> None:
        client = _make_client(qbo_config)
        assert client.realm_id == "1234567890"

    def test_environment_value(self, qbo_config: QBOConfig) -> None:
        client = _make_client(qbo_config)
        assert client.environment == "sandbox"
