"""Tests for the one-time OAuth setup CLI."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from quickbooks_mcp import auth
from quickbooks_mcp.config import DEFAULT_OAUTH_PLAYGROUND_REDIRECT_URI


def test_extract_callback_params_success() -> None:
    """Callback URLs should yield both auth code and realm ID."""
    auth_code, realm_id = auth._extract_callback_params(
        "https://example.com/callback?code=abc123&realmId=987654321&state=test"
    )

    assert auth_code == "abc123"
    assert realm_id == "987654321"


@pytest.mark.parametrize(
    ("callback_url", "expected_message"),
    [
        ("https://example.com/callback?realmId=987654321", "code"),
        ("https://example.com/callback?code=abc123", "realmId"),
    ],
)
def test_extract_callback_params_missing_fields_raise(
    callback_url: str, expected_message: str
) -> None:
    """Missing required callback params should fail clearly."""
    with pytest.raises(ValueError, match=expected_message):
        auth._extract_callback_params(callback_url)


def test_load_auth_settings_uses_sandbox_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sandbox auth should still default to the OAuth Playground redirect URI."""
    monkeypatch.setenv("QBO_CLIENT_ID", "client-id")
    monkeypatch.setenv("QBO_CLIENT_SECRET", "client-secret")
    monkeypatch.delenv("QBO_REDIRECT_URI", raising=False)
    monkeypatch.delenv("QBO_ENVIRONMENT", raising=False)

    with patch("quickbooks_mcp.auth.find_dotenv", return_value=""):
        client_id, client_secret, environment, redirect_uri = auth._load_auth_settings()

    assert client_id == "client-id"
    assert client_secret == "client-secret"
    assert environment == "sandbox"
    assert redirect_uri == DEFAULT_OAUTH_PLAYGROUND_REDIRECT_URI


def test_main_uses_configured_redirect_uri_and_persists_tokens(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mock_company_info: MagicMock
) -> None:
    """Production auth should use QBO_REDIRECT_URI and persist returned tokens."""
    env_file = tmp_path / ".env"
    env_file.write_text("QBO_CLIENT_ID=client-id\nQBO_CLIENT_SECRET=client-secret\n")

    monkeypatch.setenv("QBO_CLIENT_ID", "client-id")
    monkeypatch.setenv("QBO_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("QBO_ENVIRONMENT", "production")
    monkeypatch.setenv(
        "QBO_REDIRECT_URI",
        "https://example.com/integrations/quickbooks/callback",
    )

    callback_url = (
        "https://example.com/integrations/quickbooks/callback"
        "?code=auth-code-123&realmId=1234567890"
    )
    mock_auth_client = MagicMock()
    mock_auth_client.get_authorization_url.return_value = "https://intuit.example/auth"
    mock_auth_client.refresh_token = "new-refresh-token"
    mock_qb = MagicMock()

    with (
        patch("quickbooks_mcp.auth.find_dotenv", return_value=""),
        patch("quickbooks_mcp.auth.AuthClient", return_value=mock_auth_client) as mock_auth_ctor,
        patch("quickbooks_mcp.auth.QuickBooks", return_value=mock_qb),
        patch("quickbooks_mcp.auth.CompanyInfo.get", return_value=mock_company_info),
        patch("quickbooks_mcp.auth.webbrowser.open"),
        patch("builtins.input", return_value=callback_url),
        patch("quickbooks_mcp.auth._find_or_create_env_path", return_value=env_file),
    ):
        auth.main()

    mock_auth_ctor.assert_called_once_with(
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri="https://example.com/integrations/quickbooks/callback",
        environment="production",
    )
    mock_auth_client.get_bearer_token.assert_called_once_with(
        "auth-code-123", realm_id="1234567890"
    )

    content = env_file.read_text()
    assert "QBO_REFRESH_TOKEN=new-refresh-token" in content
    assert "QBO_REALM_ID=1234567890" in content
