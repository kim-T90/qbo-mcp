"""QuickBooks MCP tool modules.

Each module exports a ``register(mcp)`` function that registers its
tool(s) on the given FastMCP instance.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_all(mcp: FastMCP) -> None:
    """Register all QBO tools on *mcp*."""
    from quickbooks_mcp.tools import (
        account,
        attachment,
        bill,
        bill_payment,
        credit_memo,
        customer,
        deposit,
        employee,
        estimate,
        help,
        invoice,
        item,
        journal_entry,
        payment,
        purchase,
        reference,
        refund_receipt,
        report,
        sales_receipt,
        sync,
        transfer,
        vendor,
        vendor_credit,
    )

    reference.register(mcp)
    help.register(mcp)
    account.register(mcp)
    customer.register(mcp)
    vendor.register(mcp)
    employee.register(mcp)

    # Per-type transaction tools (Phase 4A: customer-ref)
    invoice.register(mcp)
    estimate.register(mcp)
    sales_receipt.register(mcp)
    credit_memo.register(mcp)
    refund_receipt.register(mcp)
    payment.register(mcp)

    # Per-type transaction tools (Phase 4B: vendor-ref + no-ref)
    bill.register(mcp)
    vendor_credit.register(mcp)
    bill_payment.register(mcp)
    deposit.register(mcp)
    transfer.register(mcp)
    journal_entry.register(mcp)
    purchase.register(mcp)

    item.register(mcp)
    report.register(mcp)
    attachment.register(mcp)
    sync.register(mcp)
