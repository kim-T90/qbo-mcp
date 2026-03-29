r"""Live validation script for QuickBooks MCP — read-only operations only.

Run from the quickbooks project directory:
    cd ~/Projects/MCP\ Combo\ Building/src/quickbooks
    uv run python validate_live.py
"""

from __future__ import annotations

import asyncio
import sys
import traceback
from datetime import date, timedelta

# ---------------------------------------------------------------------------
# Results tracking
# ---------------------------------------------------------------------------

results: list[dict] = []


def record(tool: str, operation: str, status: str, detail: str = "") -> None:
    results.append({"tool": tool, "op": operation, "status": status, "detail": detail})
    icon = "PASS" if status == "pass" else "FAIL"
    print(f"  [{icon}] {tool}.{operation}: {detail[:120]}")


# ---------------------------------------------------------------------------
# Validation tests (all read-only)
# ---------------------------------------------------------------------------


async def validate_reference(client) -> None:
    """qbo_reference — 3 operations."""
    from quickbooks.objects.company_info import CompanyInfo
    from quickbooks.objects.paymentmethod import PaymentMethod
    from quickbooks.objects.term import Term

    print("\n--- qbo_reference ---")

    # get_company_info
    try:
        info = await client.execute(CompanyInfo.get, 1, qb=client.qb_client)
        name = info.CompanyName
        record("qbo_reference", "get_company_info", "pass", f"Company: {name}")
    except Exception as e:
        record("qbo_reference", "get_company_info", "fail", str(e))

    # list_terms
    try:
        terms = await client.execute(Term.all, qb=client.qb_client)
        record("qbo_reference", "list_terms", "pass", f"{len(terms or [])} terms")
    except Exception as e:
        record("qbo_reference", "list_terms", "fail", str(e))

    # list_payment_methods
    try:
        methods = await client.execute(PaymentMethod.all, qb=client.qb_client)
        record("qbo_reference", "list_payment_methods", "pass", f"{len(methods or [])} methods")
    except Exception as e:
        record("qbo_reference", "list_payment_methods", "fail", str(e))


async def validate_account(client) -> None:
    """qbo_account — list + search."""
    from quickbooks.objects.account import Account

    print("\n--- qbo_account ---")

    # list
    try:
        accounts = await client.execute(Account.all, qb=client.qb_client)
        count = len(accounts or [])
        sample = accounts[0].Name if accounts else "N/A"
        record("qbo_account", "list", "pass", f"{count} accounts (first: {sample})")
    except Exception as e:
        record("qbo_account", "list", "fail", str(e))

    # search (IDS query)
    try:
        results_q = await client.execute(
            client.qb_client.query,
            "SELECT * FROM Account WHERE AccountType = 'Bank' MAXRESULTS 5",
        )
        count = len(results_q or [])
        record("qbo_account", "search", "pass", f"{count} bank accounts")
    except Exception as e:
        record("qbo_account", "search", "fail", str(e))


async def validate_party(client) -> None:
    """qbo_party — list customers, list vendors."""
    from quickbooks.objects.customer import Customer
    from quickbooks.objects.vendor import Vendor

    print("\n--- qbo_party ---")

    # list customers
    try:
        customers = await client.execute(Customer.all, qb=client.qb_client)
        count = len(customers or [])
        record("qbo_party", "list_customers", "pass", f"{count} customers")
    except Exception as e:
        record("qbo_party", "list_customers", "fail", str(e))

    # list vendors
    try:
        vendors = await client.execute(Vendor.all, qb=client.qb_client)
        count = len(vendors or [])
        record("qbo_party", "list_vendors", "pass", f"{count} vendors")
    except Exception as e:
        record("qbo_party", "list_vendors", "fail", str(e))


async def validate_transaction(client) -> None:
    """qbo_transaction — list invoices, list bills, search."""
    print("\n--- qbo_transaction ---")

    # list invoices
    try:
        invoices = await client.execute(
            client.qb_client.query,
            "SELECT * FROM Invoice MAXRESULTS 5",
        )
        count = len(invoices or [])
        record("qbo_transaction", "list_invoices", "pass", f"{count} invoices (max 5)")
    except Exception as e:
        record("qbo_transaction", "list_invoices", "fail", str(e))

    # list bills
    try:
        bills = await client.execute(
            client.qb_client.query,
            "SELECT * FROM Bill MAXRESULTS 5",
        )
        count = len(bills or [])
        record("qbo_transaction", "list_bills", "pass", f"{count} bills (max 5)")
    except Exception as e:
        record("qbo_transaction", "list_bills", "fail", str(e))

    # search payments (last 90 days)
    try:
        since = (date.today() - timedelta(days=90)).isoformat()
        payments = await client.execute(
            client.qb_client.query,
            f"SELECT * FROM Payment WHERE MetaData.LastUpdatedTime >= '{since}' MAXRESULTS 5",
        )
        count = len(payments or [])
        record("qbo_transaction", "search_payments", "pass", f"{count} payments last 90d (max 5)")
    except Exception as e:
        record("qbo_transaction", "search_payments", "fail", str(e))


async def validate_item(client) -> None:
    """qbo_item — list items."""
    from quickbooks.objects.item import Item

    print("\n--- qbo_item ---")

    try:
        items = await client.execute(Item.all, qb=client.qb_client)
        count = len(items or [])
        types = set()
        for item in items or []:
            t = getattr(item, "Type", "unknown")
            types.add(t)
        record("qbo_item", "list", "pass", f"{count} items, types: {', '.join(types)}")
    except Exception as e:
        record("qbo_item", "list", "fail", str(e))


async def validate_report(client) -> None:
    """qbo_report — P&L and balance sheet."""
    print("\n--- qbo_report ---")

    # Profit & Loss (current quarter)
    try:
        today = date.today()
        q_start = date(today.year, ((today.month - 1) // 3) * 3 + 1, 1)
        qb = client.qb_client

        def _fetch_pnl():
            return qb.get_report(
                "ProfitAndLoss",
                {"start_date": q_start.isoformat(), "end_date": today.isoformat()},
            )

        report = await client.execute(_fetch_pnl)
        header = (
            report.get("Header", {}).get("ReportName", "unknown")
            if isinstance(report, dict)
            else "got response"
        )
        record("qbo_report", "profit_and_loss", "pass", f"Report: {header}")
    except Exception as e:
        record("qbo_report", "profit_and_loss", "fail", str(e))

    # Balance Sheet (as of today)
    try:
        qb = client.qb_client

        def _fetch_bs():
            return qb.get_report(
                "BalanceSheet",
                {"as_of_date": date.today().isoformat()},
            )

        report = await client.execute(_fetch_bs)
        header = (
            report.get("Header", {}).get("ReportName", "unknown")
            if isinstance(report, dict)
            else "got response"
        )
        record("qbo_report", "balance_sheet", "pass", f"Report: {header}")
    except Exception as e:
        record("qbo_report", "balance_sheet", "fail", str(e))


async def validate_sync(client) -> None:
    """qbo_bulk — entity count + CDC."""
    print("\n--- qbo_bulk ---")

    # Entity count
    try:
        count_result = await client.execute(
            client.qb_client.query,
            "SELECT COUNT(*) FROM Invoice",
        )
        record("qbo_bulk", "count_invoices", "pass", f"Result: {count_result}")
    except Exception as e:
        record("qbo_bulk", "count_invoices", "fail", str(e))

    # CDC — changes in last 7 days
    try:
        since = (date.today() - timedelta(days=7)).isoformat()
        cdc = await client.execute(
            client.qb_client.change_data_capture,
            ["Invoice", "Bill", "Payment"],
            since,
        )
        entities_found = list(cdc.keys()) if isinstance(cdc, dict) else "response received"
        record("qbo_bulk", "cdc", "pass", f"Entities: {entities_found}")
    except Exception as e:
        record("qbo_bulk", "cdc", "fail", str(e))


async def validate_attachment(client) -> None:
    """qbo_attachment — list attachments (read-only, no uploads against prod)."""
    print("\n--- qbo_attachment ---")

    try:
        attachables = await client.execute(
            client.qb_client.query,
            "SELECT * FROM Attachable MAXRESULTS 5",
        )
        count = len(attachables or [])
        record("qbo_attachment", "list", "pass", f"{count} attachments (max 5)")
    except Exception as e:
        record("qbo_attachment", "list", "fail", str(e))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> int:
    from quickbooks_mcp.client import QBOClient

    print("=" * 60)
    print("QuickBooks MCP — Live Validation (READ-ONLY)")
    print("=" * 60)

    # Connect
    print("\nConnecting to QBO...")
    client = QBOClient.from_config()
    try:
        await client.connect()
    except Exception as e:
        print(f"\nFATAL: Could not connect to QBO: {e}")
        traceback.print_exc()
        return 1

    print(f"Connected! realm={client.realm_id}, env={client.environment}")

    # Run all validations
    validators = [
        validate_reference,
        validate_account,
        validate_party,
        validate_transaction,
        validate_item,
        validate_report,
        validate_sync,
        validate_attachment,
    ]

    for validator in validators:
        try:
            await validator(client)
        except Exception as e:
            print(f"\nUnexpected error in {validator.__name__}: {e}")
            traceback.print_exc()

    await client.close()

    # Summary
    passed = sum(1 for r in results if r["status"] == "pass")
    failed = sum(1 for r in results if r["status"] == "fail")
    total = len(results)

    print("\n" + "=" * 60)
    print(f"RESULTS: {passed}/{total} passed, {failed} failed")
    print("=" * 60)

    if failed:
        print("\nFailed tests:")
        for r in results:
            if r["status"] == "fail":
                print(f"  - {r['tool']}.{r['op']}: {r['detail'][:200]}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
