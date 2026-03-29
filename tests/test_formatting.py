"""Tests for QuickBooks MCP formatting module."""

from __future__ import annotations

import json

from quickbooks_mcp.errors import CHARACTER_LIMIT
from quickbooks_mcp.formatting import format_error, format_response, truncate_response

# ---------------------------------------------------------------------------
# format_response — envelope structure
# ---------------------------------------------------------------------------


def test_format_response_wraps_list_with_ok_status() -> None:
    data = [{"id": "1", "display_name": "Acme"}]
    result = format_response(data, operation="list", entity_type="Customer")

    assert result["status"] == "ok"
    assert result["operation"] == "list"
    assert result["entity_type"] == "Customer"
    assert result["count"] == 1
    assert result["data"] == data
    assert result["metadata"] == {}


def test_format_response_none_data_empty_list() -> None:
    result = format_response(None, operation="list", entity_type="Invoice")

    assert result["status"] == "ok"
    assert result["data"] == []
    assert result["count"] == 0


def test_format_response_single_dict_wrapped_in_list() -> None:
    data = {"id": "42", "display_name": "Acme"}
    result = format_response(data, operation="create", entity_type="Customer")

    assert result["data"] == [data]
    assert result["count"] == 1


def test_format_response_metadata_passed_through() -> None:
    meta = {"start_position": 1, "max_results": 10, "total_count": 50}
    result = format_response([], operation="list", entity_type="Invoice", metadata=meta)

    assert result["metadata"] == meta


def test_format_response_metadata_defaults_to_empty_dict() -> None:
    result = format_response([], operation="list", entity_type="Customer")
    assert result["metadata"] == {}


def test_format_response_list_count_matches_length() -> None:
    data = [{"id": str(i)} for i in range(5)]
    result = format_response(data, operation="list", entity_type="Item")
    assert result["count"] == 5


def test_format_response_empty_list_count_zero() -> None:
    result = format_response([], operation="list", entity_type="Customer")
    assert result["count"] == 0
    assert result["data"] == []


# ---------------------------------------------------------------------------
# format_error — envelope structure
# ---------------------------------------------------------------------------


def test_format_error_wraps_error_dict() -> None:
    error_dict = {
        "status": "error",
        "code": 404,
        "message": "Not found",
        "detail": "No entity with that ID",
        "suggestion": "Check the ID and retry",
    }
    result = format_error(error_dict, operation="get", entity_type="Invoice")

    assert result["status"] == "error"
    assert result["operation"] == "get"
    assert result["entity_type"] == "Invoice"
    assert result["code"] == 404
    assert result["message"] == "Not found"
    assert result["detail"] == "No entity with that ID"
    assert result["suggestion"] == "Check the ID and retry"


def test_format_error_does_not_duplicate_status() -> None:
    """The error_dict's 'status' key must not appear twice in the output."""
    error_dict = {"status": "error", "code": 401, "message": "Unauthorized"}
    result = format_error(error_dict, operation="list", entity_type="Customer")

    # Only one 'status' key is present and it is 'error'
    assert result["status"] == "error"
    # The merged dict should have exactly the keys we expect
    expected_keys = {"status", "operation", "entity_type", "code", "message"}
    assert set(result.keys()) == expected_keys


def test_format_error_operation_and_entity_type_set() -> None:
    error_dict = {"status": "error", "code": 500, "message": "Server error"}
    result = format_error(error_dict, operation="create", entity_type="Bill")

    assert result["operation"] == "create"
    assert result["entity_type"] == "Bill"


# ---------------------------------------------------------------------------
# truncate_response — small response passes through unchanged
# ---------------------------------------------------------------------------


def test_truncate_response_small_response_unchanged() -> None:
    response = format_response(
        [{"id": "1", "name": "A"}],
        operation="list",
        entity_type="Customer",
    )
    result = truncate_response(response)
    assert result is response or result == response
    assert "_truncated" not in result.get("metadata", {})


def test_truncate_response_exact_limit_not_truncated() -> None:
    """A response serialising to exactly CHARACTER_LIMIT chars is not truncated."""
    response = format_response([], operation="list", entity_type="Customer")
    # Serialised size is well below the limit — should pass through as-is.
    result = truncate_response(response, limit=CHARACTER_LIMIT)
    assert "_truncated" not in result.get("metadata", {})


# ---------------------------------------------------------------------------
# truncate_response — large data array gets truncated
# ---------------------------------------------------------------------------


def _big_response(n: int) -> dict:
    """Build a response with n large-ish items that will exceed CHARACTER_LIMIT."""
    items = [{"id": str(i), "payload": "x" * 500} for i in range(n)]
    return format_response(items, operation="list", entity_type="Invoice")


def test_truncate_response_large_array_truncated() -> None:
    response = _big_response(200)
    # Confirm the raw response is actually over the limit before we call truncate.
    assert len(json.dumps(response, default=str)) > CHARACTER_LIMIT

    result = truncate_response(response)

    assert len(json.dumps(result, default=str)) <= CHARACTER_LIMIT
    assert result["count"] < 200
    assert len(result["data"]) == result["count"]


def test_truncate_response_adds_truncated_metadata() -> None:
    response = _big_response(200)
    result = truncate_response(response)

    assert "_truncated" in result["metadata"]
    meta = result["metadata"]["_truncated"]
    assert meta["original_count"] == 200
    assert meta["returned_count"] < 200
    assert meta["omitted_count"] == meta["original_count"] - meta["returned_count"]
    assert "guidance" in meta


def test_truncate_response_custom_limit() -> None:
    """A custom limit smaller than the full payload triggers truncation."""
    # 200 items serialise to ~7,700 chars; use a limit below that but above the
    # minimum viable envelope (envelope overhead + _truncated guidance ~600 chars).
    items = [{"id": str(i), "name": f"Customer {i}"} for i in range(200)]
    response = format_response(items, operation="list", entity_type="Customer")
    custom_limit = 3_000

    result = truncate_response(response, limit=custom_limit)

    assert len(json.dumps(result, default=str)) <= custom_limit
    assert result["count"] < 200
    assert "_truncated" in result["metadata"]


# ---------------------------------------------------------------------------
# truncate_response — non-list data returned as-is
# ---------------------------------------------------------------------------


def test_truncate_response_no_data_key_returned_unchanged() -> None:
    error_env = {"status": "error", "operation": "get", "entity_type": "Customer"}
    result = truncate_response(error_env)
    assert result == error_env


def test_truncate_response_non_list_data_returned_unchanged() -> None:
    response = {"status": "ok", "operation": "get", "entity_type": "Customer", "data": "raw"}
    result = truncate_response(response)
    assert result == response


def test_truncate_response_preserves_existing_metadata() -> None:
    """Pre-existing metadata keys survive after truncation."""
    items = [{"id": str(i), "payload": "x" * 500} for i in range(200)]
    response = format_response(
        items,
        operation="list",
        entity_type="Invoice",
        metadata={"query": "SELECT * FROM Invoice"},
    )
    result = truncate_response(response)

    assert result["metadata"]["query"] == "SELECT * FROM Invoice"
    assert "_truncated" in result["metadata"]
