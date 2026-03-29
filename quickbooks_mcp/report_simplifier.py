"""QuickBooks Online MCP — report simplifier.

Converts the deeply nested QBO report JSON structure into a flat list of dicts
that is trivial for LLMs and downstream code to consume.

QBO report structure::

    {
        "Header": {
            "ReportName": "ProfitAndLoss",
            "Column": [
                {"ColTitle": "",      "ColType": "Account"},
                {"ColTitle": "Total", "ColType": "Money"},
            ]
        },
        "Rows": {"Row": [
            {
                "type": "Section",
                "Header": {"ColData": [{"value": "Income"}]},
                "Rows": {"Row": [
                    {"type": "Data", "ColData": [
                        {"value": "Sales", "id": "1"},
                        {"value": "5000.00"},
                    ]},
                ]},
                "Summary": {"ColData": [
                    {"value": "Total Income"},
                    {"value": "5000.00"},
                ]},
            },
            {"type": "Data", "ColData": [
                {"value": "Net Income"},
                {"value": "3000.00"},
            ]},
        ]}
    }

Output is a flat list of dicts, each keyed by column name (with the first
empty column title normalised to ``"name"``).  Section header and total rows
carry additional ``_type`` and ``_depth`` keys.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def extract_columns(header: dict) -> list[str]:
    """Return column names from ``Header.Column[].ColTitle``.

    The first column is often an empty string representing the account/name
    column.  We replace it with ``"name"`` for clarity.

    Args:
        header: The top-level ``Header`` dict from a QBO report response.

    Returns:
        A list of column name strings.
    """
    columns: list[str] = []
    for col in header.get("Column", []):
        title = col.get("ColTitle", "")
        columns.append(title if title else "name")
    return columns


def flatten_rows(rows: list, columns: list[str], depth: int = 0) -> list[dict]:
    """Walk a QBO ``Rows.Row`` list recursively and produce flat dicts.

    Each output dict has the column names as keys.  Section headers and
    totals carry two extra keys:

    - ``_type``: ``"section"`` for a section header row, ``"total"`` for a
      summary row, absent for plain data rows.
    - ``_depth``: nesting depth (0 = top-level).

    Args:
        rows: The ``Row`` list from a ``Rows`` container.
        columns: Column names from :func:`extract_columns`.
        depth: Current recursion depth (used to set ``_depth``).

    Returns:
        Flat list of row dicts.
    """
    result: list[dict] = []

    for row in rows:
        row_type = row.get("type", "")

        if row_type == "Section":
            # --- Section header ---
            section_header = row.get("Header", {})
            col_data = section_header.get("ColData", [])
            if col_data:
                header_row = _zip_col_data(col_data, columns)
                header_row["_type"] = "section"
                header_row["_depth"] = depth
                result.append(header_row)

            # --- Nested data rows ---
            nested = row.get("Rows", {}).get("Row", [])
            if nested:
                result.extend(flatten_rows(nested, columns, depth=depth + 1))

            # --- Summary / total row ---
            summary = row.get("Summary", {})
            sum_col_data = summary.get("ColData", [])
            if sum_col_data:
                total_row = _zip_col_data(sum_col_data, columns)
                total_row["_type"] = "total"
                total_row["_depth"] = depth
                result.append(total_row)

        else:
            # Data row (type == "Data" or no type)
            col_data = row.get("ColData", [])
            if col_data:
                data_row = _zip_col_data(col_data, columns)
                data_row["_depth"] = depth
                result.append(data_row)

    return result


def simplify_report(raw_report: dict) -> list[dict]:
    """Convert a raw QBO report dict into a flat list of row dicts.

    Works for all 11 report types (ProfitAndLoss, BalanceSheet, TrialBalance,
    CashFlow, GeneralLedger, AgedReceivables, AgedReceivableDetail,
    AgedPayables, AgedPayableDetail, CustomerBalanceSummary,
    VendorBalanceSummary).

    Args:
        raw_report: The full QBO report response dict (the value at key
            ``"<ReportName>"`` inside the QBO API response, or the dict
            returned directly by ``qb_client.get_report()``).

    Returns:
        Flat list of row dicts.  Returns an empty list for reports with no
        rows.
    """
    header = raw_report.get("Header", {})
    columns = extract_columns(header)

    if not columns:
        logger.debug("simplify_report: no columns found in Header")
        return []

    rows_container = raw_report.get("Rows", {})
    rows = rows_container.get("Row", [])

    if not rows:
        return []

    return flatten_rows(rows, columns, depth=0)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _zip_col_data(col_data: list[dict], columns: list[str]) -> dict:
    """Zip ColData values with column names into a flat dict.

    If there are more columns than ColData entries (or vice-versa) we zip up
    to the shorter length — QBO occasionally returns ragged rows.

    Args:
        col_data: List of ``{"value": ..., "id": ...}`` dicts from QBO.
        columns: Column names from :func:`extract_columns`.

    Returns:
        Flat dict mapping column name → string value.
    """
    row: dict = {}
    for col_name, cell in zip(columns, col_data):
        row[col_name] = cell.get("value", "")
    return row
