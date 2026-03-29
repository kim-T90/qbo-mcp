"""Shared test fixtures for QuickBooks MCP tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from quickbooks_mcp.config import QBOConfig


@pytest.fixture(autouse=True)
def _block_dotenv_discovery():
    """Prevent real .env files from leaking into tests."""
    with patch("quickbooks_mcp.config.find_dotenv", return_value=""):
        yield


@pytest.fixture
def env_vars(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Set required QBO environment variables for testing."""
    vars_ = {
        "QBO_CLIENT_ID": "test_client_id",
        "QBO_CLIENT_SECRET": "test_client_secret",
        "QBO_REFRESH_TOKEN": "test_refresh_token",
        "QBO_REALM_ID": "1234567890",
        "QBO_ENVIRONMENT": "sandbox",
        "QBO_MINOR_VERSION": "75",
        "DEBUG_QBO": "false",
    }
    for k, v in vars_.items():
        monkeypatch.setenv(k, v)
    return vars_


@pytest.fixture
def qbo_config(env_vars: dict[str, str]) -> QBOConfig:
    """Create a QBOConfig from test env vars."""
    return QBOConfig.from_env()


@pytest.fixture
def mock_qb_client() -> MagicMock:
    """Create a mock python-quickbooks QuickBooks client."""
    client = MagicMock()
    client.company_id = "1234567890"
    client.minorversion = 75
    return client


@pytest.fixture
def mock_auth_client() -> MagicMock:
    """Create a mock intuitlib AuthClient."""
    auth = MagicMock()
    auth.access_token = "test_access_token"
    auth.refresh_token = "test_refresh_token"
    auth.realm_id = "1234567890"
    return auth


@pytest.fixture
def mock_company_info() -> MagicMock:
    """Create a mock CompanyInfo response."""
    info = MagicMock()
    info.CompanyName = "Test Trucking Co"
    info.LegalName = "Test Trucking Co LLC"
    info.Id = "1"
    info.Country = "US"
    return info


@pytest.fixture
def tmp_env_file(tmp_path: Path) -> Path:
    """Create a temporary .env file for token persistence tests."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "QBO_CLIENT_ID=test_client_id\n"
        "QBO_CLIENT_SECRET=test_client_secret\n"
        "QBO_REFRESH_TOKEN=old_refresh_token\n"
        "QBO_REALM_ID=1234567890\n"
        "QBO_ENVIRONMENT=sandbox\n"
    )
    return env_file
