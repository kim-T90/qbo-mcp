"""Tests for QuickBooks MCP converters module."""

from __future__ import annotations

import pytest

from quickbooks_mcp.converters import qbo_to_snake, snake_to_qbo, to_pascal_case, to_snake_case

# ---------------------------------------------------------------------------
# to_snake_case
# ---------------------------------------------------------------------------


def test_to_snake_case_display_name() -> None:
    assert to_snake_case("DisplayName") == "display_name"


def test_to_snake_case_bill_addr() -> None:
    assert to_snake_case("BillAddr") == "bill_addr"


def test_to_snake_case_id() -> None:
    assert to_snake_case("Id") == "id"


def test_to_snake_case_txn_date() -> None:
    assert to_snake_case("TxnDate") == "txn_date"


def test_to_snake_case_qbo_class() -> None:
    """Acronym prefix like 'QBO' folds correctly."""
    assert to_snake_case("QBOClass") == "qbo_class"


def test_to_snake_case_already_lower() -> None:
    assert to_snake_case("id") == "id"


def test_to_snake_case_empty_string() -> None:
    assert to_snake_case("") == ""


# ---------------------------------------------------------------------------
# to_pascal_case
# ---------------------------------------------------------------------------


def test_to_pascal_case_display_name() -> None:
    assert to_pascal_case("display_name") == "DisplayName"


def test_to_pascal_case_bill_addr() -> None:
    assert to_pascal_case("bill_addr") == "BillAddr"


def test_to_pascal_case_id() -> None:
    assert to_pascal_case("id") == "Id"


def test_to_pascal_case_txn_date() -> None:
    assert to_pascal_case("txn_date") == "TxnDate"


def test_to_pascal_case_line_items() -> None:
    assert to_pascal_case("line_items") == "LineItems"


def test_to_pascal_case_empty_string() -> None:
    assert to_pascal_case("") == ""


# ---------------------------------------------------------------------------
# qbo_to_snake — dict
# ---------------------------------------------------------------------------


def test_qbo_to_snake_flat_dict() -> None:
    result = qbo_to_snake({"DisplayName": "Acme", "Id": "42"})
    assert result == {"display_name": "Acme", "id": "42"}


def test_qbo_to_snake_nested_dict() -> None:
    payload = {
        "BillAddr": {
            "Line1": "123 Main St",
            "City": "Los Angeles",
        },
        "TxnDate": "2024-01-15",
    }
    result = qbo_to_snake(payload)
    assert result == {
        "bill_addr": {
            "line1": "123 Main St",
            "city": "Los Angeles",
        },
        "txn_date": "2024-01-15",
    }


def test_qbo_to_snake_deeply_nested() -> None:
    payload = {"CustomerRef": {"Value": "1", "Name": "Acme"}}
    result = qbo_to_snake(payload)
    assert result == {"customer_ref": {"value": "1", "name": "Acme"}}


def test_qbo_to_snake_empty_dict() -> None:
    assert qbo_to_snake({}) == {}


# ---------------------------------------------------------------------------
# qbo_to_snake — list
# ---------------------------------------------------------------------------


def test_qbo_to_snake_list_of_dicts() -> None:
    payload = [
        {"DisplayName": "Alice", "Id": "1"},
        {"DisplayName": "Bob", "Id": "2"},
    ]
    result = qbo_to_snake(payload)
    assert result == [
        {"display_name": "Alice", "id": "1"},
        {"display_name": "Bob", "id": "2"},
    ]


def test_qbo_to_snake_nested_list_inside_dict() -> None:
    payload = {"LineItems": [{"DetailType": "SalesItemLineDetail", "Amount": 100}]}
    result = qbo_to_snake(payload)
    assert result == {"line_items": [{"detail_type": "SalesItemLineDetail", "amount": 100}]}


def test_qbo_to_snake_empty_list() -> None:
    assert qbo_to_snake([]) == []


# ---------------------------------------------------------------------------
# qbo_to_snake — scalar pass-through
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("scalar", [42, 3.14, True, None, "plain string"])
def test_qbo_to_snake_scalar_unchanged(scalar: object) -> None:
    assert qbo_to_snake(scalar) is scalar or qbo_to_snake(scalar) == scalar


# ---------------------------------------------------------------------------
# snake_to_qbo — dict
# ---------------------------------------------------------------------------


def test_snake_to_qbo_flat_dict() -> None:
    result = snake_to_qbo({"display_name": "Acme", "id": "42"})
    assert result == {"DisplayName": "Acme", "Id": "42"}


def test_snake_to_qbo_nested_dict() -> None:
    payload = {
        "bill_addr": {
            "line1": "123 Main St",
            "city": "Los Angeles",
        },
        "txn_date": "2024-01-15",
    }
    result = snake_to_qbo(payload)
    assert result == {
        "BillAddr": {
            "Line1": "123 Main St",
            "City": "Los Angeles",
        },
        "TxnDate": "2024-01-15",
    }


def test_snake_to_qbo_deeply_nested() -> None:
    payload = {"customer_ref": {"value": "1", "name": "Acme"}}
    result = snake_to_qbo(payload)
    assert result == {"CustomerRef": {"Value": "1", "Name": "Acme"}}


def test_snake_to_qbo_empty_dict() -> None:
    assert snake_to_qbo({}) == {}


# ---------------------------------------------------------------------------
# snake_to_qbo — list
# ---------------------------------------------------------------------------


def test_snake_to_qbo_list_of_dicts() -> None:
    payload = [
        {"display_name": "Alice", "id": "1"},
        {"display_name": "Bob", "id": "2"},
    ]
    result = snake_to_qbo(payload)
    assert result == [
        {"DisplayName": "Alice", "Id": "1"},
        {"DisplayName": "Bob", "Id": "2"},
    ]


def test_snake_to_qbo_empty_list() -> None:
    assert snake_to_qbo([]) == []


# ---------------------------------------------------------------------------
# snake_to_qbo — scalar pass-through
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("scalar", [42, 3.14, True, None, "plain string"])
def test_snake_to_qbo_scalar_unchanged(scalar: object) -> None:
    assert snake_to_qbo(scalar) is scalar or snake_to_qbo(scalar) == scalar


# ---------------------------------------------------------------------------
# Round-trip symmetry
# ---------------------------------------------------------------------------


def test_round_trip_qbo_snake_qbo() -> None:
    """PascalCase → snake → PascalCase should recover original keys."""
    original = {
        "DisplayName": "Acme",
        "BillAddr": {"Line1": "123 Main St", "City": "LA"},
        "TxnDate": "2024-01-15",
    }
    assert snake_to_qbo(qbo_to_snake(original)) == original


def test_round_trip_snake_qbo_snake() -> None:
    """snake_case → PascalCase → snake_case should recover original keys."""
    original = {
        "display_name": "Acme",
        "bill_addr": {"line1": "123 Main St", "city": "LA"},
        "txn_date": "2024-01-15",
    }
    assert qbo_to_snake(snake_to_qbo(original)) == original
