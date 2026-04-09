"""QuickBooks Online MCP — QBOClient: async-safe wrapper around python-quickbooks."""

from __future__ import annotations

import asyncio
import logging
import os
import random
import re
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from dotenv import find_dotenv
from fastmcp.exceptions import ToolError
from intuitlib.client import AuthClient
from quickbooks import QuickBooks
from quickbooks.exceptions import AuthorizationException, QuickbooksException
from quickbooks.objects.company_info import CompanyInfo

from quickbooks_mcp.config import QBOConfig
from quickbooks_mcp.rate_limiter import TokenBucketRateLimiter

logger = logging.getLogger("quickbooks-mcp.client")

# Regex that matches the QBO_REFRESH_TOKEN line in a .env file.
# Captures everything up to the newline (or end-of-file) so we can replace
# only the value while leaving surrounding content untouched.
_REFRESH_TOKEN_RE = re.compile(
    r"^(QBO_REFRESH_TOKEN\s*=\s*)(.+?)(\s*)$",
    re.MULTILINE,
)


class QBOClient:
    """Async-safe wrapper around python-quickbooks with token refresh locking,
    rate limiting, and atomic token persistence.

    Do not instantiate directly — use ``QBOClient.from_config()``.
    """

    def __init__(self, config: QBOConfig) -> None:
        self._config = config
        self._qb_client: QuickBooks | None = None
        self._refresh_lock: asyncio.Lock = asyncio.Lock()
        self._semaphore: asyncio.Semaphore = asyncio.Semaphore(10)
        self._rate_limiter: TokenBucketRateLimiter = TokenBucketRateLimiter()
        self._backoff_base: float = 1.0

        # Resolve the .env path once so token persistence is consistent.
        dotenv_path = find_dotenv(usecwd=True)
        self._env_path: Path | None = Path(dotenv_path) if dotenv_path else None

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_config(cls) -> QBOClient:
        """Create a QBOClient from ``QBOConfig.from_env()``."""
        return cls(QBOConfig.from_env())

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Create the python-quickbooks client, exchange the refresh token for
        an access token, and verify the connection via CompanyInfo.

        Raises:
            ToolError: On authentication failure or inability to reach QBO.
        """
        cfg = self._config

        def _build_client() -> QuickBooks:
            auth_client = AuthClient(
                client_id=cfg.client_id,
                client_secret=cfg.client_secret,
                redirect_uri=cfg.redirect_uri,
                environment=cfg.environment,
                refresh_token=cfg.refresh_token,
            )
            # Exchange refresh token for access token.
            auth_client.refresh()

            qb = QuickBooks(
                auth_client=auth_client,
                refresh_token=auth_client.refresh_token,
                company_id=cfg.realm_id,
                minorversion=cfg.minor_version,
            )
            return qb

        try:
            self._qb_client = await asyncio.to_thread(_build_client)
        except Exception as exc:
            raise ToolError(
                f"Failed to connect to QuickBooks Online: {exc}. "
                "Check your credentials and re-run auth if needed: "
                "uv run python -m quickbooks_mcp.auth"
            ) from exc

        # Verify connection by fetching CompanyInfo.
        def _verify() -> CompanyInfo:
            assert self._qb_client is not None
            return CompanyInfo.get(1, qb=self._qb_client)

        try:
            await asyncio.to_thread(_verify)
        except Exception as exc:
            self._qb_client = None
            raise ToolError(f"QuickBooks connection verification failed: {exc}") from exc

        logger.info(
            "Connected to QBO — realm_id=%s environment=%s",
            cfg.realm_id,
            cfg.environment,
        )

    async def close(self) -> None:
        """Release the underlying client reference."""
        self._qb_client = None
        logger.debug("QBOClient closed")

    # ------------------------------------------------------------------
    # Public API call entry point
    # ------------------------------------------------------------------

    async def execute(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Execute a python-quickbooks callable with rate limiting, concurrency
        control, automatic token refresh on 401, and exponential back-off on 429.

        Args:
            fn: A synchronous python-quickbooks callable (e.g. ``Invoice.get``).
            *args: Positional arguments forwarded to *fn*.
            **kwargs: Keyword arguments forwarded to *fn*.

        Returns:
            Whatever *fn* returns.

        Raises:
            ToolError: On unrecoverable API errors or after max retries.
        """
        async with self._semaphore:
            await self._rate_limiter.acquire()

            for attempt in range(3):
                try:
                    result = await self._call(fn, *args, **kwargs)

                    if self._config.debug:
                        # Log callable name and kwargs but NEVER log token values.
                        safe_kwargs = {k: v for k, v in kwargs.items() if "token" not in k.lower()}
                        logger.debug(
                            "QBO call succeeded: fn=%s args=%r kwargs=%r result=%r",
                            getattr(fn, "__name__", repr(fn)),
                            args,
                            safe_kwargs,
                            result,
                        )

                    return result

                except AuthorizationException as exc:
                    if attempt == 0:
                        logger.warning(
                            "QBO 401 on attempt %d — refreshing token and retrying",
                            attempt,
                        )
                        await self._refresh_token()
                        # Loop immediately after refresh (no back-off needed).
                        continue
                    raise ToolError(
                        f"QuickBooks authorization failed after token refresh: {exc}. "
                        "Re-run auth: uv run python -m quickbooks_mcp.auth"
                    ) from exc

                except QuickbooksException as exc:
                    status_code = getattr(exc, "status_code", None)

                    if status_code == 429:
                        if attempt < 2:
                            wait = self._backoff(attempt)
                            logger.warning(
                                "QBO 429 rate limit on attempt %d — backing off %.2fs",
                                attempt,
                                wait,
                            )
                            await asyncio.sleep(wait)
                            continue
                        raise ToolError(
                            "QuickBooks rate limit exceeded after 3 attempts (429). "
                            "Wait at least 60 seconds before retrying. "
                            "Batch operations where possible to reduce request volume."
                        ) from exc

                    # All other QuickbooksException variants.
                    message = getattr(exc, "message", None) or str(exc)
                    detail = getattr(exc, "detail", None)
                    raise ToolError(
                        f"QuickBooks API error (status={status_code}): {message}"
                        + (f" — detail: {detail}" if detail else "")
                    ) from exc

        # Should be unreachable, but satisfies type checkers.
        raise ToolError("QBO execute loop exited without result")  # pragma: no cover

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Offload a synchronous python-quickbooks call to a thread pool."""
        return await asyncio.to_thread(fn, *args, **kwargs)

    async def _refresh_token(self) -> None:
        """Refresh the QBO access token under a lock to prevent thundering herd.

        Updates ``_qb_client`` with the new access token and atomically
        persists the new refresh token to the ``.env`` file.

        Raises:
            ToolError: If the refresh grant is invalid (re-auth required).
        """
        async with self._refresh_lock:
            qb = self._qb_client
            if qb is None:
                raise ToolError("QBO client is not connected. Call connect() before execute().")

            def _do_refresh() -> tuple[str, str]:
                """Return (new_access_token, new_refresh_token)."""
                auth_client: AuthClient = qb.auth_client  # type: ignore[attr-defined]
                auth_client.refresh()
                return auth_client.access_token, auth_client.refresh_token

            try:
                new_access_token, new_refresh_token = await asyncio.to_thread(_do_refresh)
            except Exception as exc:
                msg = str(exc)
                if "invalid_grant" in msg.lower():
                    raise ToolError(
                        "QBO connection expired. Re-run auth: uv run python -m quickbooks_mcp.auth"
                    ) from exc
                raise ToolError(f"QBO token refresh failed: {exc}") from exc

            # Propagate new access token to the existing QuickBooks client.
            qb.auth_client.access_token = new_access_token  # type: ignore[attr-defined]

            logger.info("QBO access token refreshed successfully")

            # Persist the new refresh token atomically.
            await self._persist_token(new_refresh_token)

    async def _persist_token(self, new_refresh_token: str) -> None:
        """Atomically update QBO_REFRESH_TOKEN in the ``.env`` file.

        Reads the current ``.env`` content, replaces the ``QBO_REFRESH_TOKEN``
        line via regex, writes to a sibling tempfile, fsyncs, then uses
        ``os.replace`` for an atomic rename.

        If no ``.env`` file was found at startup, this method logs a warning
        and returns without raising — the in-memory client state is still valid.

        Args:
            new_refresh_token: The new refresh token string to write.
        """
        if self._env_path is None or not self._env_path.exists():
            logger.warning(
                "No .env file found — new refresh token not persisted to disk. "
                "Update QBO_REFRESH_TOKEN manually to avoid re-auth on restart."
            )
            return

        try:
            original_text = self._env_path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.error("Failed to read .env for token persistence: %s", exc)
            return

        if _REFRESH_TOKEN_RE.search(original_text):
            updated_text = _REFRESH_TOKEN_RE.sub(
                lambda m: f"{m.group(1)}{new_refresh_token}{m.group(3)}",
                original_text,
            )
        else:
            # Line not present — append it.
            separator = "" if original_text.endswith("\n") else "\n"
            updated_text = f"{original_text}{separator}QBO_REFRESH_TOKEN={new_refresh_token}\n"
            logger.debug("QBO_REFRESH_TOKEN not found in .env — appending new line")

        env_dir = self._env_path.parent
        try:
            fd, tmp_path = tempfile.mkstemp(dir=env_dir, prefix=".env.tmp.")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(updated_text)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp_path, self._env_path)
                logger.debug("QBO refresh token persisted atomically to %s", self._env_path)
            except Exception:
                # Clean up the tempfile if the rename fails.
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except OSError as exc:
            logger.error("Failed to persist refresh token to .env: %s", exc)

    def _backoff(self, attempt: int) -> float:
        """Return an exponential back-off duration with full jitter.

        Args:
            attempt: Zero-based attempt index (0 → ~1 s, 1 → ~2 s, 2 → ~4 s).

        Returns:
            Sleep duration in seconds.
        """
        cap = self._backoff_base * (2**attempt)
        return random.uniform(0, cap)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def realm_id(self) -> str:
        """The QBO company (realm) ID from config."""
        return self._config.realm_id

    @property
    def environment(self) -> str:
        """The QBO environment: 'sandbox' or 'production'."""
        return self._config.environment

    @property
    def qb_client(self) -> QuickBooks:
        """The underlying python-quickbooks ``QuickBooks`` client instance.

        Raises:
            ToolError: If ``connect()`` has not been called yet.
        """
        if self._qb_client is None:
            raise ToolError(
                "QBO client is not connected. Call connect() before accessing qb_client."
            )
        return self._qb_client
