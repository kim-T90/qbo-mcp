"""QuickBooks Online MCP server."""

from __future__ import annotations

import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastmcp import Context, FastMCP

from quickbooks_mcp.client import QBOClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("quickbooks-mcp")


@dataclass
class AppContext:
    client: QBOClient


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    logger.info("Starting QuickBooks MCP server...")
    client = QBOClient.from_config()
    await client.connect()
    logger.info(
        "QBO client connected (realm=%s, env=%s)",
        client.realm_id,
        client.environment,
    )
    try:
        yield AppContext(client=client)
    finally:
        await client.close()
        logger.info("QuickBooks MCP server shut down.")


def get_client(ctx: Context) -> QBOClient:
    """Extract QBOClient from request context. Used by all tool modules."""
    app: AppContext = ctx.request_context.lifespan_context
    return app.client


mcp = FastMCP(
    "QuickBooks",
    instructions=(
        "QuickBooks Online accounting tools. "
        "Use qbo_reference(operation='get_company_info') to verify connection. "
        "Use qbo_help to look up field names, operation matrices, and IDS query syntax "
        "BEFORE constructing search queries or creating transactions. "
        "Use qbo_account for chart of accounts, qbo_customer for customers, "
        "qbo_vendor for vendors, qbo_employee for employees, "
        "qbo_invoice for invoices, qbo_bill for bills, qbo_payment for payments, "
        "qbo_estimate for estimates, qbo_sales_receipt for sales receipts, "
        "qbo_credit_memo for credit memos, qbo_refund_receipt for refund receipts, "
        "qbo_vendor_credit for vendor credits, qbo_bill_payment for bill payments, "
        "qbo_deposit for deposits, qbo_transfer for transfers, "
        "qbo_journal_entry for journal entries, qbo_purchase for purchases, "
        "qbo_item for products/services, "
        "qbo_report for financial reports, qbo_attachment for file attachments, "
        "qbo_bulk for bulk/CDC operations. "
        "If authentication fails (401/403), use "
        "qbo_help(topic='error_codes') for recovery steps."
    ),
    lifespan=app_lifespan,
    mask_error_details=True,
)

# Register all tool modules
from quickbooks_mcp.tools import register_all  # noqa: E402

register_all(mcp)
