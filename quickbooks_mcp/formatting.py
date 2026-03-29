"""QuickBooks Online MCP — response formatting utilities.

All MCP tools return a consistent envelope so callers can handle success and
error paths uniformly without inspecting payload shapes.

Success envelope::

    {
        "status": "ok",
        "operation": "create",
        "entity_type": "Invoice",
        "count": 1,
        "data": [...],
        "metadata": {...}
    }

Error envelope::

    {
        "status": "error",
        "operation": "list",
        "entity_type": "Customer",
        "code": 404,
        "message": "...",
        "detail": "...",
        "suggestion": "..."
    }
"""

from __future__ import annotations

import json
import logging
from typing import Any

from quickbooks_mcp.errors import CHARACTER_LIMIT

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pagination helper
# ---------------------------------------------------------------------------


def paginate_list(
    items: list[dict],
    total: int,
    offset: int = 0,
    limit: int = 20,
) -> tuple[list[dict], dict]:
    """Slice a list and produce pagination metadata.

    Returns:
        (sliced_items, pagination_meta_dict)
    """
    page = items[offset : offset + limit]
    has_more = (offset + limit) < total
    meta = {
        "start_position": offset + 1,
        "max_results": limit,
        "total": total,
        "has_more": has_more,
    }
    if has_more:
        meta["next_offset"] = offset + limit
    return page, meta


# ---------------------------------------------------------------------------
# Markdown formatter
# ---------------------------------------------------------------------------


def _to_markdown_table(items: list[dict], entity_type: str) -> str:
    """Convert a list of flat dicts to a Markdown table."""
    if not items:
        return f"*No {entity_type} records found.*"

    # Use keys from first item as columns
    columns = list(items[0].keys())
    # Limit to 8 columns for readability
    if len(columns) > 8:
        columns = columns[:8]

    header = "| " + " | ".join(str(c) for c in columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    rows = []
    for item in items:
        vals = []
        for c in columns:
            v = item.get(c, "")
            # Flatten nested dicts to their 'value' or 'name' key
            if isinstance(v, dict):
                v = v.get("name") or v.get("value") or str(v)
            vals.append(str(v).replace("|", "\\|"))
        rows.append("| " + " | ".join(vals) + " |")

    return "\n".join([header, sep, *rows])


def _to_markdown_detail(item: dict, entity_type: str) -> str:
    """Convert a single dict to a Markdown key-value block."""
    lines = [f"## {entity_type}"]
    for k, v in item.items():
        if isinstance(v, dict):
            v = v.get("name") or v.get("value") or str(v)
        elif isinstance(v, list):
            v = f"({len(v)} items)"
        lines.append(f"- **{k}**: {v}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public formatters
# ---------------------------------------------------------------------------


def format_response(
    data: Any,
    operation: str,
    entity_type: str,
    metadata: dict | None = None,
    response_format: str = "json",
) -> dict | str:
    """Wrap data in the standard MCP success response envelope.

    Args:
        data: The payload — typically a list of entity dicts or a single dict.
              Scalars and None are wrapped in a list automatically.
        operation: The tool operation that produced this response (e.g. 'list').
        entity_type: The QBO entity type (e.g. 'Invoice', 'Customer').
        metadata: Optional extra context (e.g. pagination cursors, query info).
        response_format: 'json' for structured dict, 'markdown' for readable text.

    Returns:
        A dict (json) or str (markdown) conforming to the response schema.
    """
    if data is None:
        items: list = []
    elif isinstance(data, list):
        items = data
    else:
        items = [data]

    if response_format == "markdown":
        if len(items) == 0:
            return f"*No {entity_type} records found.*"
        if len(items) == 1 and operation in ("get", "create", "update"):
            return _to_markdown_detail(items[0], entity_type)
        return _to_markdown_table(items, entity_type)

    return {
        "status": "ok",
        "operation": operation,
        "entity_type": entity_type,
        "count": len(items),
        "data": items,
        "metadata": metadata or {},
    }


def format_error(error_dict: dict, operation: str, entity_type: str) -> dict:
    """Wrap an error dict in the standard MCP error response envelope.

    Args:
        error_dict: A structured error dict produced by
                    :func:`~quickbooks_mcp.errors.format_qbo_error`.
        operation: The tool operation that failed (e.g. 'create').
        entity_type: The QBO entity type being operated on (e.g. 'Invoice').

    Returns:
        A dict conforming to the error envelope schema.
    """
    return {
        "status": "error",
        "operation": operation,
        "entity_type": entity_type,
        **{k: v for k, v in error_dict.items() if k != "status"},
    }


def truncate_response(response: dict, limit: int = CHARACTER_LIMIT) -> dict:
    """Truncate the data array if the serialised response exceeds *limit* chars.

    When a response is too large for an LLM context window, the data array is
    trimmed incrementally until the payload fits (or until only one item
    remains).  A ``_truncated`` key is added to the metadata with guidance
    on how to retrieve the remaining records.

    Args:
        response: A success envelope produced by :func:`format_response`.
        limit: Maximum number of JSON-serialised characters (default:
               ``CHARACTER_LIMIT`` from ``errors.py``).

    Returns:
        The original response dict (possibly mutated) fitting within *limit*
        characters.  If the response is already within the limit it is returned
        unchanged.

    Note:
        This function only truncates responses that have a ``"data"`` list.
        Error envelopes and responses without a data list are returned as-is.
    """
    if "data" not in response or not isinstance(response["data"], list):
        return response

    serialised = json.dumps(response, default=str)
    if len(serialised) <= limit:
        return response

    original_count = len(response["data"])
    items = list(response["data"])

    # Binary-search style trim: halve until it fits, then fine-trim.
    while len(items) > 1:
        items = items[: max(1, len(items) // 2)]
        candidate = {**response, "data": items, "count": len(items)}
        if len(json.dumps(candidate, default=str)) <= limit:
            break

    # Fine-trim one-by-one to maximise data returned within the limit.
    while len(items) > 1:
        next_candidate = {**response, "data": items[:-1], "count": len(items) - 1}
        if len(json.dumps(next_candidate, default=str)) <= limit:
            items = items[:-1]
            break
        # If even removing one more still doesn't help, keep current length.
        break

    returned_count = len(items)
    omitted = original_count - returned_count

    logger.debug(
        "Truncated response for %s/%s: %d -> %d items (%d omitted)",
        response.get("operation"),
        response.get("entity_type"),
        original_count,
        returned_count,
        omitted,
    )

    metadata = dict(response.get("metadata") or {})
    metadata["_truncated"] = {
        "original_count": original_count,
        "returned_count": returned_count,
        "omitted_count": omitted,
        "guidance": (
            f"Response was truncated to {returned_count} of {original_count} items "
            f"to stay within the {limit:,}-character context limit. "
            "Use pagination parameters (e.g. 'max_results', 'start_position') "
            "or narrow your query with filters to retrieve the remaining records."
        ),
    }

    response = {**response, "data": items, "count": returned_count, "metadata": metadata}
    return response
