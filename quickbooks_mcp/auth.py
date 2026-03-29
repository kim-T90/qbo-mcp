"""QuickBooks Online MCP — one-time OAuth setup CLI.

Usage:
    uv run python -m quickbooks_mcp.auth

Uses the Intuit OAuth Playground redirect URI (already registered on your app)
so no localhost redirect URI registration is needed. After authorizing in the
browser, paste the full callback URL from your browser's address bar.
"""

from __future__ import annotations

import os
import sys
import tempfile
import webbrowser
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from dotenv import find_dotenv, load_dotenv
from intuitlib.client import AuthClient
from intuitlib.enums import Scopes
from quickbooks import QuickBooks
from quickbooks.objects.company_info import CompanyInfo

# The OAuth Playground redirect URI — pre-registered on all Intuit apps.
_REDIRECT_URI = "https://developer.intuit.com/v2/OAuth2Playground/RedirectUrl"


# ---------------------------------------------------------------------------
# .env helpers
# ---------------------------------------------------------------------------


def _find_or_create_env_path() -> Path:
    """Return the .env path to write to."""
    existing = find_dotenv(usecwd=True)
    if existing:
        return Path(existing)
    return Path.cwd() / ".env"


def _read_env_lines(env_path: Path) -> list[str]:
    """Read existing .env lines, or return empty list if file doesn't exist."""
    if not env_path.exists():
        return []
    return env_path.read_text(encoding="utf-8").splitlines(keepends=True)


def _upsert_env_vars(env_path: Path, updates: dict[str, str]) -> None:
    """Atomically update or add key=value pairs in a .env file."""
    lines = _read_env_lines(env_path)
    remaining = dict(updates)

    new_lines: list[str] = []
    for line in lines:
        stripped = line.rstrip("\n\r")
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue
        if "=" in stripped:
            key, _, _ = stripped.partition("=")
            key = key.strip()
            if key in remaining:
                new_lines.append(f"{key}={remaining.pop(key)}\n")
                continue
        new_lines.append(line)

    if remaining:
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines[-1] += "\n"
        for key, value in remaining.items():
            new_lines.append(f"{key}={value}\n")

    dir_ = env_path.parent
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=dir_,
        delete=False,
        prefix=".env.tmp.",
    ) as tmp:
        tmp_path = Path(tmp.name)
        tmp.writelines(new_lines)

    os.replace(tmp_path, env_path)


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the OAuth authorization flow."""
    # 1. Load existing .env to pick up CLIENT_ID / CLIENT_SECRET.
    existing_env = find_dotenv(usecwd=True)
    if existing_env:
        load_dotenv(existing_env, override=False)

    client_id = os.environ.get("QBO_CLIENT_ID", "").strip()
    client_secret = os.environ.get("QBO_CLIENT_SECRET", "").strip()
    environment = os.environ.get("QBO_ENVIRONMENT", "sandbox").strip().lower()

    if not client_id or not client_secret:
        print(
            "Error: QBO_CLIENT_ID and QBO_CLIENT_SECRET must be set in your .env file "
            "or environment before running this command.",
            file=sys.stderr,
        )
        sys.exit(1)

    # 2. Build the AuthClient with the OAuth Playground redirect URI.
    auth_client = AuthClient(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=_REDIRECT_URI,
        environment=environment,
    )
    auth_url = auth_client.get_authorization_url([Scopes.ACCOUNTING])

    # 3. Open browser and ask user to paste the callback URL.
    print(f"Opening browser for QuickBooks authorization ({environment})...")
    print(f"If your browser doesn't open, visit:\n  {auth_url}\n")
    webbrowser.open(auth_url)

    print("After authorizing, you'll be redirected to the Intuit OAuth Playground.")
    print("Copy the FULL URL from your browser's address bar and paste it here.\n")

    callback_url = input("Paste callback URL: ").strip()

    if not callback_url:
        print("\n✗ No URL provided. Aborting.", file=sys.stderr)
        sys.exit(1)

    # 4. Parse auth code and realm ID from the callback URL.
    parsed = urlparse(callback_url)
    params = parse_qs(parsed.query)
    auth_code = params.get("code", [None])[0]
    realm_id = params.get("realmId", [None])[0]

    if not auth_code:
        print("\n✗ No 'code' parameter found in the URL. Aborting.", file=sys.stderr)
        print("  Expected URL like: https://...?code=ABC123&realmId=12345", file=sys.stderr)
        sys.exit(1)

    if not realm_id:
        print("\n✗ No 'realmId' parameter found in the URL. Aborting.", file=sys.stderr)
        print("  Expected URL like: https://...?code=ABC123&realmId=12345", file=sys.stderr)
        sys.exit(1)

    # 5. Exchange auth code for tokens.
    try:
        auth_client.get_bearer_token(auth_code, realm_id=realm_id)
    except Exception as exc:
        print(f"\n✗ Token exchange failed: {exc}", file=sys.stderr)
        print(
            "\nTroubleshooting:\n"
            "  1. Verify your Client ID and Secret are correct\n"
            "  2. Make sure you approved access for the right company\n"
            "  3. Auth codes expire quickly — try running this command again",
            file=sys.stderr,
        )
        sys.exit(1)

    # 6. Write tokens to .env (atomic).
    env_path = _find_or_create_env_path()
    _upsert_env_vars(
        env_path,
        {
            "QBO_REFRESH_TOKEN": auth_client.refresh_token,
            "QBO_REALM_ID": realm_id,
        },
    )

    # 7. Validate the connection by fetching CompanyInfo.
    try:
        qb = QuickBooks(
            auth_client=auth_client,
            refresh_token=auth_client.refresh_token,
            company_id=realm_id,
        )
        company = CompanyInfo.get(1, qb=qb)
        company_name = company.CompanyName
    except Exception as exc:
        print(f"\n✗ Connection validation failed: {exc}")
        print(
            "\nTroubleshooting:\n"
            "  1. Verify your Client ID and Secret are correct\n"
            "  2. Make sure you approved access for the right company\n"
            "  3. Try running this command again"
        )
        sys.exit(1)

    # 8. Success!
    print(
        f"\n✓ Connected to QuickBooks Online!\n"
        f"  Company: {company_name}\n"
        f"  Realm ID: {realm_id}\n"
        f"  Environment: {environment}\n"
        f"\nCredentials saved to {env_path}\n"
        f"Next: Start the server with `uv run python -m quickbooks_mcp`"
    )


if __name__ == "__main__":
    main()
