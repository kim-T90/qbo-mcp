"""QuickBooks Online MCP — configuration loader."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from urllib.parse import urlparse

from dotenv import find_dotenv, load_dotenv
from fastmcp.exceptions import ToolError

logger = logging.getLogger(__name__)

_REQUIRED_VARS: tuple[str, ...] = (
    "QBO_CLIENT_ID",
    "QBO_CLIENT_SECRET",
    "QBO_REFRESH_TOKEN",
    "QBO_REALM_ID",
)

_VALID_ENVIRONMENTS: frozenset[str] = frozenset({"sandbox", "production"})
DEFAULT_OAUTH_PLAYGROUND_REDIRECT_URI = (
    "https://developer.intuit.com/v2/OAuth2Playground/RedirectUrl"
)


def _parse_bool(value: str) -> bool:
    """Parse a truthy environment variable string to bool."""
    return value.strip().lower() in {"true", "1", "yes"}


def _validate_redirect_uri(redirect_uri: str) -> str:
    """Validate that a redirect URI is a well-formed absolute URL."""
    parsed = urlparse(redirect_uri)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ToolError(
            f"Invalid QBO_REDIRECT_URI value: {redirect_uri!r}. "
            "Expected an absolute URL like 'https://example.com/callback'."
        )
    return redirect_uri


def resolve_redirect_uri(environment: str, raw_redirect_uri: str | None) -> str:
    """Resolve the redirect URI for the configured QBO environment.

    Sandbox mode falls back to the Intuit OAuth Playground to preserve the
    existing quickstart. Production mode requires an explicitly configured
    redirect URI that matches the value registered in Intuit Developer.
    """
    redirect_uri = (raw_redirect_uri or "").strip()
    if redirect_uri:
        return _validate_redirect_uri(redirect_uri)

    if environment == "sandbox":
        return DEFAULT_OAUTH_PLAYGROUND_REDIRECT_URI

    raise ToolError(
        "QBO_REDIRECT_URI is required when QBO_ENVIRONMENT='production'. "
        "Register a production redirect URI in Intuit Developer and add it to your .env file."
    )


@dataclass(frozen=True)
class QBOConfig:
    client_id: str
    client_secret: str
    refresh_token: str
    realm_id: str
    environment: str
    redirect_uri: str
    minor_version: int
    debug: bool

    @classmethod
    def from_env(cls) -> QBOConfig:
        """Load and validate QBO configuration from environment variables.

        Searches for a .env file using find_dotenv() (walks up from the
        current working directory) and loads it before reading env vars.

        Raises:
            ToolError: If any required variable is missing or
                QBO_ENVIRONMENT is not "sandbox" or "production".
        """
        dotenv_path = find_dotenv(usecwd=True)
        if dotenv_path:
            load_dotenv(dotenv_path, override=False)
            logger.debug("Loaded .env from %s", dotenv_path)
        else:
            logger.debug("No .env file found; relying on process environment")

        missing = [var for var in _REQUIRED_VARS if not os.environ.get(var)]
        if missing:
            raise ToolError(
                f"Missing required QuickBooks configuration: {', '.join(missing)}. "
                "Add these variables to your .env file — see .env.example for the "
                "full list of required and optional settings."
            )

        environment = os.environ.get("QBO_ENVIRONMENT", "sandbox").strip().lower()
        if environment not in _VALID_ENVIRONMENTS:
            raise ToolError(
                f"Invalid QBO_ENVIRONMENT value: {environment!r}. "
                "Must be 'sandbox' or 'production'."
            )
        redirect_uri = resolve_redirect_uri(environment, os.environ.get("QBO_REDIRECT_URI"))

        raw_minor = os.environ.get("QBO_MINOR_VERSION", "75")
        try:
            minor_version = int(raw_minor)
        except ValueError:
            raise ToolError(f"Invalid QBO_MINOR_VERSION value: {raw_minor!r}. Must be an integer.")

        debug = _parse_bool(os.environ.get("DEBUG_QBO", "false"))

        return cls(
            client_id=os.environ["QBO_CLIENT_ID"],
            client_secret=os.environ["QBO_CLIENT_SECRET"],
            refresh_token=os.environ["QBO_REFRESH_TOKEN"],
            realm_id=os.environ["QBO_REALM_ID"],
            environment=environment,
            redirect_uri=redirect_uri,
            minor_version=minor_version,
            debug=debug,
        )
