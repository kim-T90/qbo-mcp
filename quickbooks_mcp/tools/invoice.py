"""qbo_invoice tool â€” manage QuickBooks Online invoices."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Literal

from fastmcp import Context
from fastmcp.exceptions import ToolError

from quickbooks_mcp.converters import qbo_to_snake
from quickbooks_mcp.errors import format_qbo_error
from quickbooks_mcp.formatting import format_response, truncate_response
from quickbooks_mcp.models import ERROR_SHAPE_HINT, IDS_QUERY_RULES, PREVIEW_HINT, SEARCH_EXAMPLES
from quickbooks_mcp.tools._base import (
    destructive_preview,
    tx_create,
    tx_delete,
    tx_get,
    tx_list,
    tx_pdf,
    tx_search,
    tx_send,
    tx_update,
    tx_void,
    validate_extra,
)

if TYPE_CHECKING:
    from fastmcp import FastMCP

TX_TYPE = "invoice"
ENTITY_TYPE = "Invoice"
INVOICE_LINE_SEARCH_PAGE_SIZE = 100
INVOICE_LINE_SEARCH_SCAN_LIMIT = 500

_TOOL_DESCRIPTION = (
    f"{PREVIEW_HINT} "
    "Manage QuickBooks Online invoices. "
    "Create, list, update, delete, void, email, download as PDF, "
    "or scan invoice line descriptions for keywords. "
    "create requires customer_ref (customer ID from qbo_customer). "
    'line_items: [{"amount": 100.0, "description": "...", "item_ref": "1"}] '
    "â€” see qbo_help(topic='line_items', entity='invoice') for full schema. "
    f"IDS search uses top-level invoice fields only â€” {IDS_QUERY_RULES} "
    "Use operation='search_line_items' for description-based line item scans. "
    f"{SEARCH_EXAMPLES['invoice']} "
    "Typical flow: qbo_customer(list) -> get customer ID -> "
    f"qbo_invoice(create). {ERROR_SHAPE_HINT}"
)


def _normalize_keywords(keywords: list[str] | None) -> list[str]:
    if not keywords:
        raise ToolError("'keywords' is required for operation='search_line_items'.")

    normalized = [keyword.strip().lower() for keyword in keywords if keyword.strip()]
    if not normalized:
        raise ToolError(
            "'keywords' must contain at least one non-empty value for operation='search_line_items'."
        )

    return list(dict.fromkeys(normalized))


def _validate_date_range(start_date: str | None, end_date: str | None) -> None:
    if not start_date:
        raise ToolError("'start_date' is required for operation='search_line_items'.")
    if not end_date:
        raise ToolError("'end_date' is required for operation='search_line_items'.")

    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    if start > end:
        raise ToolError("'start_date' must be less than or equal to 'end_date'.")


def _line_description_candidates(line: dict) -> list[str]:
    descriptions: list[str] = []

    top_level = line.get("description")
    if isinstance(top_level, str) and top_level.strip():
        descriptions.append(top_level.strip())

    for value in line.values():
        if isinstance(value, dict):
            nested = value.get("description")
            if isinstance(nested, str) and nested.strip():
                descriptions.append(nested.strip())

    return descriptions


def _line_item_ref(line: dict) -> tuple[str | None, str | None]:
    for value in line.values():
        if not isinstance(value, dict):
            continue
        item_ref = value.get("item_ref")
        if isinstance(item_ref, dict):
            return item_ref.get("value"), item_ref.get("name")

    return None, None


async def _search_line_items(
    client,
    keywords: list[str] | None,
    start_date: str | None,
    end_date: str | None,
    max_results: int,
    offset: int,
    response_format: str,
) -> dict | str:
    normalized_keywords = _normalize_keywords(keywords)
    _validate_date_range(start_date, end_date)

    window_start = max(offset, 0)
    window_end = window_start + max(max_results, 1)
    page_rows: list[dict] = []
    total_match_count = 0
    matched_invoice_count = 0
    scanned_invoice_count = 0
    scan_limit_reached = False
    start_position = 1

    while scanned_invoice_count < INVOICE_LINE_SEARCH_SCAN_LIMIT:
        remaining = INVOICE_LINE_SEARCH_SCAN_LIMIT - scanned_invoice_count
        page_size = min(INVOICE_LINE_SEARCH_PAGE_SIZE, remaining)
        sql = (
            "SELECT * FROM Invoice "
            f"WHERE TxnDate >= '{start_date}' AND TxnDate <= '{end_date}' "
            "ORDERBY MetaData.LastUpdatedTime "
            f"STARTPOSITION {start_position} MAXRESULTS {page_size}"
        )
        rows = await client.query_rows(sql, ENTITY_TYPE)
        if not rows:
            break

        scanned_invoice_count += len(rows)
        if scanned_invoice_count >= INVOICE_LINE_SEARCH_SCAN_LIMIT:
            scan_limit_reached = True

        for row in rows:
            invoice = qbo_to_snake(row)
            lines = invoice.get("line") or []
            if not isinstance(lines, list):
                continue

            customer_ref = invoice.get("customer_ref")
            customer_id = customer_ref.get("value") if isinstance(customer_ref, dict) else None
            customer_name = customer_ref.get("name") if isinstance(customer_ref, dict) else None
            invoice_had_match = False

            for line_index, line in enumerate(lines, start=1):
                if not isinstance(line, dict):
                    continue

                descriptions = _line_description_candidates(line)
                if not descriptions:
                    continue

                match_description = next(
                    (
                        description
                        for description in descriptions
                        if any(keyword in description.lower() for keyword in normalized_keywords)
                    ),
                    None,
                )
                if match_description is None:
                    continue

                total_match_count += 1
                if not invoice_had_match:
                    matched_invoice_count += 1
                    invoice_had_match = True

                if window_start < total_match_count <= window_end:
                    item_ref, item_name = _line_item_ref(line)
                    page_rows.append(
                        {
                            "invoice_id": invoice.get("id"),
                            "doc_number": invoice.get("doc_number"),
                            "txn_date": invoice.get("txn_date"),
                            "customer_ref": customer_id,
                            "customer_name": customer_name,
                            "line_index": line_index,
                            "amount": line.get("amount"),
                            "description": match_description,
                            "item_ref": item_ref,
                            "item_name": item_name,
                        }
                    )

        start_position += len(rows)
        if len(rows) < page_size:
            break

    page_size = max(max_results, 1)
    has_more = total_match_count > (window_start + page_size)
    metadata = {
        "keywords": normalized_keywords,
        "start_date": start_date,
        "end_date": end_date,
        "scanned_invoice_count": scanned_invoice_count,
        "matched_invoice_count": matched_invoice_count,
        "total_match_count": total_match_count,
        "has_more": has_more,
        "scan_limit_reached": scan_limit_reached,
        "scan_limit": INVOICE_LINE_SEARCH_SCAN_LIMIT,
        "query_mode": "invoice_line_description_scan",
        "partial": scan_limit_reached,
    }
    if has_more:
        metadata["next_offset"] = window_start + page_size

    response = format_response(
        page_rows,
        "search_line_items",
        ENTITY_TYPE,
        metadata=metadata,
        response_format=response_format,
    )
    if isinstance(response, dict):
        response = truncate_response(response)
    return response


def register(mcp: FastMCP) -> None:
    """Register the qbo_invoice tool on *mcp*."""
    from quickbooks_mcp.server import get_client  # noqa: PLC0415

    @mcp.tool(
        name="qbo_invoice",
        description=_TOOL_DESCRIPTION,
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    async def qbo_invoice(
        ctx: Context,
        operation: Literal[
            "list",
            "get",
            "create",
            "update",
            "delete",
            "void",
            "send",
            "pdf",
            "search",
            "search_line_items",
        ],
        id: str | None = None,
        customer_ref: str | None = None,
        line_items: list[dict] | None = None,
        keywords: list[str] | None = None,
        memo: str | None = None,
        due_date: str | None = None,
        email: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        query: str | None = None,
        max_results: int = 20,
        offset: int = 0,
        extra: dict | None = None,
        preview: bool = True,
        response_format: Literal["json", "markdown"] = "json",
    ) -> dict | str:
        """Create, read, update, delete, void, send, or search QuickBooks Online invoices.

        Args:
            operation: Action to perform.
            id: QBO entity ID (numeric string, e.g. '42') â€” required
                for get, update, delete, void, send, pdf.
            customer_ref: Customer ID (numeric string from
                qbo_customer list) â€” required for create.
            line_items: List of line item dicts. Each item supports:
                amount (float), description (str), item_ref (str â€” Item ID),
                detail_type (str â€” defaults to 'SalesItemLineDetail').
            keywords: Keyword list for search_line_items.
            memo: Private note on the invoice.
            due_date: Due date in YYYY-MM-DD format.
            email: Recipient email for the send operation.
            start_date: Filter list by TxnDate >= start_date (YYYY-MM-DD).
            end_date: Filter list by TxnDate <= end_date (YYYY-MM-DD).
            query: IDS WHERE clause for search (e.g. "TotalAmt > '100.00'").
            max_results: Maximum records to return for list or search_line_items.
            offset: Zero-based start offset for list or search_line_items.
            extra: Optional dict of additional QBO fields.
            preview: Safety gate â€” True (default) returns a preview without
                executing. Set False to actually write.
            response_format: 'json' (default) or 'markdown'.
        """
        client = get_client(ctx)
        extra_dict = validate_extra(extra)

        if operation in ("get", "update", "delete", "void", "send", "pdf") and not id:
            raise ToolError(f"'id' is required for operation='{operation}'.")
        if operation == "send" and not email:
            raise ToolError("'email' is required for operation='send'.")
        if operation == "create" and not customer_ref:
            raise ToolError(
                "'customer_ref' is required when creating an invoice. "
                "Use qbo_customer(operation='list') to find customer IDs."
            )
        if operation == "search" and not query:
            raise ToolError("'query' is required for operation='search'.")
        if operation == "search_line_items":
            _validate_date_range(start_date, end_date)
            _normalize_keywords(keywords)

        try:
            if operation == "list":
                return await tx_list(
                    client,
                    TX_TYPE,
                    ENTITY_TYPE,
                    start_date,
                    end_date,
                    max_results,
                    offset,
                    response_format,
                )
            elif operation == "get":
                return await tx_get(client, TX_TYPE, ENTITY_TYPE, id, response_format)
            elif operation == "create":
                return await tx_create(
                    client,
                    TX_TYPE,
                    ENTITY_TYPE,
                    customer_ref,
                    None,
                    line_items,
                    memo,
                    due_date,
                    extra_dict,
                    response_format,
                )
            elif operation == "update":
                return await tx_update(
                    client,
                    TX_TYPE,
                    ENTITY_TYPE,
                    id,
                    customer_ref,
                    None,
                    line_items,
                    memo,
                    due_date,
                    extra_dict,
                    response_format,
                )
            elif operation == "delete":
                if preview:
                    return await destructive_preview(
                        client,
                        TX_TYPE,
                        ENTITY_TYPE,
                        "delete",
                        id,
                    )
                return await tx_delete(client, TX_TYPE, ENTITY_TYPE, id, response_format)
            elif operation == "void":
                if preview:
                    return await destructive_preview(
                        client,
                        TX_TYPE,
                        ENTITY_TYPE,
                        "void",
                        id,
                    )
                return await tx_void(client, TX_TYPE, ENTITY_TYPE, id, response_format)
            elif operation == "send":
                return await tx_send(
                    client,
                    TX_TYPE,
                    ENTITY_TYPE,
                    id,
                    email,
                    response_format,
                )
            elif operation == "pdf":
                return await tx_pdf(client, TX_TYPE, ENTITY_TYPE, id, response_format)
            elif operation == "search":
                return await tx_search(client, ENTITY_TYPE, query, response_format)
            elif operation == "search_line_items":
                return await _search_line_items(
                    client,
                    keywords,
                    start_date,
                    end_date,
                    max_results,
                    offset,
                    response_format,
                )
        except ToolError:
            raise
        except Exception as exc:
            return format_qbo_error(exc, operation, ENTITY_TYPE)

        raise ToolError(f"Unhandled operation: {operation}")  # pragma: no cover
