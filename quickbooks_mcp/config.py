"""QuickBooks Online MCP — configuration loader."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

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


def _parse_bool(value: str) -> bool:
    """Parse a truthy environment variable string to bool."""
    return value.strip().lower() in {"true", "1", "yes"}


@dataclass(frozen=True)
class QBOConfig:
    client_id: str
    client_secret: str
    refresh_token: str
    realm_id: str
    environment: str
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
            minor_version=minor_version,
            debug=debug,
        )
