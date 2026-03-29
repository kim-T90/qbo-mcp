"""qbo_report tool — 11 QBO financial reports, read-only."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

from fastmcp import Context
from fastmcp.exceptions import ToolError

from quickbooks_mcp.formatting import format_response, truncate_response

if TYPE_CHECKING:
    from fastmcp import FastMCP

logger = logging.getLogger(__name__)

_ENTITY_TYPE = "Report"

# Maps tool operation names to QBO report name strings accepted by the SDK.
REPORT_NAME_MAP: dict[str, str] = {
    "profit_and_loss": "ProfitAndLoss",
    "balance_sheet": "BalanceSheet",
    "trial_balance": "TrialBalance",
    "cash_flow": "CashFlow",
    "general_ledger": "GeneralLedger",
    "ar_aging_summary": "AgedReceivables",
    "ar_aging_detail": "AgedReceivableDetail",
    "ap_aging_summary": "AgedPayables",
    "ap_aging_detail": "AgedPayableDetail",
    "customer_balance": "CustomerBalanceSummary",
    "vendor_balance": "VendorBalanceSummary",
}

ReportOperation = Literal[
    "profit_and_loss",
    "balance_sheet",
    "trial_balance",
    "cash_flow",
    "general_ledger",
    "ar_aging_summary",
    "ar_aging_detail",
    "ap_aging_summary",
    "ap_aging_detail",
    "customer_balance",
    "vendor_balance",
]


def register(mcp: FastMCP) -> None:
    """Register the qbo_report tool on *mcp*."""

    @mcp.tool(
        name="qbo_report",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def qbo_report(
        ctx: Context,
        operation: ReportOperation,
        start_date: str | None = None,
        end_date: str | None = None,
        as_of_date: str | None = None,
        summarize_by: Literal["Total", "Month", "Week", "Days"] = "Total",
        raw: bool = False,
        response_format: Literal["json", "markdown"] = "json",
    ) -> dict | str:
        """Fetch one of 11 standard QuickBooks Online financial reports.

        Operations:
        - profit_and_loss: Income vs expenses for a date range.
        - balance_sheet: Assets, liabilities, and equity as-of a date.
        - trial_balance: Debit/credit balances for all accounts.
        - cash_flow: Cash inflows and outflows for a date range.
        - general_ledger: Detailed transaction-level ledger.
        - ar_aging_summary: Accounts receivable aging buckets (summary).
        - ar_aging_detail: Accounts receivable aging buckets (detail).
        - ap_aging_summary: Accounts payable aging buckets (summary).
        - ap_aging_detail: Accounts payable aging buckets (detail).
        - customer_balance: Outstanding balance per customer.
        - vendor_balance: Outstanding balance per vendor.

        Date parameters:
        - start_date / end_date: YYYY-MM-DD range for flow reports
          (profit_and_loss, cash_flow, general_ledger, aging reports).
        - as_of_date: YYYY-MM-DD snapshot date for balance_sheet and balance
          summary reports.

        summarize_by controls column granularity: Total (default), Month,
        Week, or Days.

        raw=True returns the full nested QBO structure unchanged.
        raw=False (default) returns a flat list of row dicts via
        simplify_report().
        """
        from quickbooks_mcp.report_simplifier import simplify_report
        from quickbooks_mcp.server import get_client

        client = get_client(ctx)
        qb = client.qb_client

        if operation not in REPORT_NAME_MAP:
            raise ToolError(
                f"Unknown operation: {operation!r}. Valid operations: {sorted(REPORT_NAME_MAP)}"
            )

        report_name = REPORT_NAME_MAP[operation]

        # Build query-string params for the QBO reports API.
        qs_params: dict[str, str] = {"summarize_column_by": summarize_by}
        if start_date:
            qs_params["start_date"] = start_date
        if end_date:
            qs_params["end_date"] = end_date
        if as_of_date:
            qs_params["as_of_date"] = as_of_date

        def _fetch() -> dict:
            return qb.get_report(report_name, qs_params)

        result = await client.execute(_fetch)

        if raw:
            # Return the raw nested QBO report structure.
            response = format_response(
                result, operation, _ENTITY_TYPE, response_format=response_format
            )
            if response_format == "json":
                response = truncate_response(response)
            return response

        # Simplify the nested QBO report into a flat list of row dicts.
        rows = simplify_report(result)
        response = format_response(rows, operation, _ENTITY_TYPE, response_format=response_format)
        if response_format == "json":
            response = truncate_response(response)
        return response
