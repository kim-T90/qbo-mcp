"""QuickBooks Online MCP — PascalCase ↔ snake_case converters.

QBO API uses PascalCase keys (e.g. "DisplayName", "BillAddr").
MCP tool parameters use snake_case (e.g. "display_name", "bill_addr").

This module converts between both representations recursively so that tools
can accept and return idiomatic snake_case while the QBO client sees the
PascalCase the API expects.
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# String-level converters
# ---------------------------------------------------------------------------

# Matches a run of uppercase letters followed by a lowercase letter, or a
# transition from a lowercase/digit to an uppercase letter.
# Examples:
#   "DisplayName"  → splits at "D|isplay", "N|ame" → "Display_Name"
#   "BillAddr"     → "Bill_Addr"
#   "Id"           → "Id" (single segment)
#   "QBOClass"     → "QBO_Class"
_PASCAL_RE = re.compile(r"(?<=[a-z0-9])([A-Z])|(?<=[A-Z])([A-Z])(?=[a-z])")


def to_snake_case(s: str) -> str:
    """Convert a PascalCase or camelCase string to snake_case.

    Examples::

        to_snake_case("DisplayName")  -> "display_name"
        to_snake_case("BillAddr")     -> "bill_addr"
        to_snake_case("Id")           -> "id"
        to_snake_case("QBOClass")     -> "qbo_class"
        to_snake_case("TxnDate")      -> "txn_date"
    """
    if not s:
        return s
    # Insert underscore before the matched uppercase letter(s).
    result = _PASCAL_RE.sub(lambda m: f"_{m.group(0)}", s)
    return result.lower()


# Matches word segments separated by underscores.
_SNAKE_RE = re.compile(r"(?:^|_)([a-zA-Z0-9])")


def to_pascal_case(s: str) -> str:
    """Convert a snake_case string to PascalCase.

    Examples::

        to_pascal_case("display_name")  -> "DisplayName"
        to_pascal_case("bill_addr")     -> "BillAddr"
        to_pascal_case("id")            -> "Id"
        to_pascal_case("txn_date")      -> "TxnDate"
        to_pascal_case("line_items")    -> "LineItems"
    """
    if not s:
        return s
    return _SNAKE_RE.sub(lambda m: m.group(1).upper(), s)


# ---------------------------------------------------------------------------
# Recursive dict/list converters
# ---------------------------------------------------------------------------


def qbo_to_snake(obj: dict | list | Any) -> dict | list | Any:
    """Recursively convert all dict keys from PascalCase to snake_case.

    Non-dict, non-list values are returned unchanged.

    Args:
        obj: A QBO API response dict, list thereof, or scalar value.

    Returns:
        The same structure with all dict keys converted to snake_case.
    """
    if isinstance(obj, dict):
        return {to_snake_case(k): qbo_to_snake(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [qbo_to_snake(item) for item in obj]
    return obj


def snake_to_qbo(obj: dict | list | Any) -> dict | list | Any:
    """Recursively convert all dict keys from snake_case to PascalCase.

    Non-dict, non-list values are returned unchanged.

    Args:
        obj: A snake_case parameter dict, list thereof, or scalar value.

    Returns:
        The same structure with all dict keys converted to PascalCase.
    """
    if isinstance(obj, dict):
        return {to_pascal_case(k): snake_to_qbo(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [snake_to_qbo(item) for item in obj]
    return obj
