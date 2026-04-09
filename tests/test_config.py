"""Tests for QuickBooks MCP config module."""

from __future__ import annotations

import dataclasses

import pytest
from fastmcp.exceptions import ToolError

from quickbooks_mcp.config import DEFAULT_OAUTH_PLAYGROUND_REDIRECT_URI, QBOConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REQUIRED_VARS = (
    "QBO_CLIENT_ID",
    "QBO_CLIENT_SECRET",
    "QBO_REFRESH_TOKEN",
    "QBO_REALM_ID",
)


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


def test_from_env_success(env_vars: dict[str, str]) -> None:
    """All required vars set → QBOConfig populated with correct values."""
    config = QBOConfig.from_env()

    assert config.client_id == "test_client_id"
    assert config.client_secret == "test_client_secret"
    assert config.refresh_token == "test_refresh_token"
    assert config.realm_id == "1234567890"
    assert config.environment == "sandbox"
    assert config.redirect_uri == DEFAULT_OAUTH_PLAYGROUND_REDIRECT_URI
    assert config.minor_version == 75
    assert config.debug is False


# ---------------------------------------------------------------------------
# Missing required vars
# ---------------------------------------------------------------------------


def test_missing_required_var_raises(
    env_vars: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Single missing required var → ToolError containing the var name."""
    monkeypatch.delenv("QBO_CLIENT_ID")

    with pytest.raises(ToolError, match="QBO_CLIENT_ID"):
        QBOConfig.from_env()


def test_missing_multiple_required_vars_raises(
    env_vars: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Multiple missing required vars → ToolError listing ALL missing names."""
    monkeypatch.delenv("QBO_CLIENT_ID")
    monkeypatch.delenv("QBO_REFRESH_TOKEN")

    with pytest.raises(ToolError) as exc_info:
        QBOConfig.from_env()

    message = str(exc_info.value)
    assert "QBO_CLIENT_ID" in message
    assert "QBO_REFRESH_TOKEN" in message


# ---------------------------------------------------------------------------
# QBO_ENVIRONMENT validation
# ---------------------------------------------------------------------------


def test_invalid_environment_raises(
    env_vars: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unsupported QBO_ENVIRONMENT value → ToolError."""
    monkeypatch.setenv("QBO_ENVIRONMENT", "staging")

    with pytest.raises(ToolError, match="staging"):
        QBOConfig.from_env()


def test_environment_defaults_to_sandbox(
    env_vars: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """QBO_ENVIRONMENT unset → defaults to 'sandbox'."""
    monkeypatch.delenv("QBO_ENVIRONMENT")

    config = QBOConfig.from_env()

    assert config.environment == "sandbox"


def test_production_environment_accepted(
    env_vars: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """'production' is a valid QBO_ENVIRONMENT value."""
    monkeypatch.setenv("QBO_ENVIRONMENT", "production")
    monkeypatch.setenv("QBO_REDIRECT_URI", "https://example.com/qbo/callback")

    config = QBOConfig.from_env()

    assert config.environment == "production"
    assert config.redirect_uri == "https://example.com/qbo/callback"


def test_production_requires_redirect_uri(
    env_vars: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Production mode requires an explicit redirect URI."""
    monkeypatch.setenv("QBO_ENVIRONMENT", "production")
    monkeypatch.delenv("QBO_REDIRECT_URI", raising=False)

    with pytest.raises(ToolError, match="QBO_REDIRECT_URI"):
        QBOConfig.from_env()


def test_sandbox_defaults_redirect_uri(
    env_vars: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sandbox mode falls back to the Intuit OAuth Playground redirect URI."""
    monkeypatch.delenv("QBO_REDIRECT_URI", raising=False)

    config = QBOConfig.from_env()

    assert config.redirect_uri == DEFAULT_OAUTH_PLAYGROUND_REDIRECT_URI


def test_explicit_redirect_uri_is_honored(
    env_vars: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """QBO_REDIRECT_URI overrides the sandbox default when provided."""
    monkeypatch.setenv("QBO_REDIRECT_URI", "https://example.com/custom/callback")

    config = QBOConfig.from_env()

    assert config.redirect_uri == "https://example.com/custom/callback"


def test_invalid_redirect_uri_raises(
    env_vars: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Malformed QBO_REDIRECT_URI values should fail validation."""
    monkeypatch.setenv("QBO_REDIRECT_URI", "not-a-url")

    with pytest.raises(ToolError, match="QBO_REDIRECT_URI"):
        QBOConfig.from_env()


# ---------------------------------------------------------------------------
# QBO_MINOR_VERSION
# ---------------------------------------------------------------------------


def test_minor_version_defaults_to_75(
    env_vars: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """QBO_MINOR_VERSION unset → defaults to 75."""
    monkeypatch.delenv("QBO_MINOR_VERSION")

    config = QBOConfig.from_env()

    assert config.minor_version == 75


def test_invalid_minor_version_raises(
    env_vars: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Non-numeric QBO_MINOR_VERSION → ToolError."""
    monkeypatch.setenv("QBO_MINOR_VERSION", "abc")

    with pytest.raises(ToolError, match="abc"):
        QBOConfig.from_env()


# ---------------------------------------------------------------------------
# DEBUG_QBO parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("truthy", ["true", "1", "yes", "TRUE"])
def test_debug_truthy_values(
    env_vars: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    truthy: str,
) -> None:
    """DEBUG_QBO truthy strings → debug=True."""
    monkeypatch.setenv("DEBUG_QBO", truthy)

    config = QBOConfig.from_env()

    assert config.debug is True


@pytest.mark.parametrize("falsy", ["false", "0", "no", ""])
def test_debug_falsy_values(
    env_vars: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    falsy: str,
) -> None:
    """DEBUG_QBO falsy strings → debug=False."""
    monkeypatch.setenv("DEBUG_QBO", falsy)

    config = QBOConfig.from_env()

    assert config.debug is False


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


def test_config_is_frozen(qbo_config: QBOConfig) -> None:
    """QBOConfig is a frozen dataclass — field assignment raises FrozenInstanceError."""
    with pytest.raises(dataclasses.FrozenInstanceError):
        qbo_config.client_id = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# .env override behaviour
# ---------------------------------------------------------------------------


def test_env_vars_override_dotenv_file(
    env_vars: dict[str, str], monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
) -> None:
    """Process env vars take precedence over values from a .env file (override=False).

    Simulate by setting QBO_CLIENT_ID in the process environment *before*
    load_dotenv runs — the fixture already does this, so the env value
    ('test_client_id') must survive regardless of any .env on disk.
    """
    # Ensure the env var is present with the expected value.
    monkeypatch.setenv("QBO_CLIENT_ID", "from_process_env")

    config = QBOConfig.from_env()

    # The process-level value must win over any discovered .env file.
    assert config.client_id == "from_process_env"
