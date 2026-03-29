r"""Live validation — WRITE operations for QuickBooks MCP.

Creates test entities, validates CRUD, then cleans up (deactivate/void/delete).
All test entities are prefixed with [MCP-TEST] for identification.

Run from the quickbooks project directory:
    cd ~/Projects/MCP\ Combo\ Building/src/quickbooks
    uv run python validate_live_write.py
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import traceback
from datetime import date, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Results tracking
# ---------------------------------------------------------------------------

results: list[dict] = []

# IDs of entities created — used for cleanup
_created: dict[str, str | None] = {
    "customer_id": None,
    "item_id": None,
    "invoice_id": None,
    "attachment_id": None,
}


def record(tool: str, operation: str, status: str, detail: str = "") -> None:
    results.append({"tool": tool, "op": operation, "status": status, "detail": detail})
    icon = "PASS" if status == "pass" else "FAIL"
    print(f"  [{icon}] {tool}.{operation}: {detail[:140]}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def find_income_account(client) -> str | None:
    """Find an Income account ID to use for creating a test item."""
    from quickbooks.objects.account import Account

    result = await client.execute(
        Account.filter, AccountType="Income", max_results=1, qb=client.qb_client
    )
    if result:
        return result[0].Id
    return None


# ---------------------------------------------------------------------------
# 1. qbo_party — create, update, get, deactivate
# ---------------------------------------------------------------------------


async def validate_party_write(client) -> None:
    """Create a test customer, update, verify, then deactivate."""
    from quickbooks.objects.customer import Customer

    print("\n--- qbo_party (write) ---")

    # CREATE
    try:

        def _create():
            obj = Customer()
            obj.DisplayName = f"[MCP-TEST] Validation Customer {date.today().isoformat()}"
            obj.CompanyName = "MCP Test Corp"
            obj.PrimaryEmailAddr = {"Address": "test@mcp-validation.dev"}
            obj.PrimaryPhone = {"FreeFormNumber": "555-0199"}
            obj.save(qb=client.qb_client)
            return obj

        created = await client.execute(_create)
        cust_id = created.Id
        _created["customer_id"] = cust_id
        record("qbo_party", "create_customer", "pass", f"ID={cust_id}, Name={created.DisplayName}")
    except Exception as e:
        record("qbo_party", "create_customer", "fail", str(e))
        return  # Can't continue without customer

    # UPDATE
    try:

        def _update():
            obj = Customer.get(cust_id, qb=client.qb_client)
            obj.CompanyName = "MCP Test Corp (Updated)"
            obj.save(qb=client.qb_client)
            return obj

        updated = await client.execute(_update)
        record("qbo_party", "update_customer", "pass", f"CompanyName={updated.CompanyName}")
    except Exception as e:
        record("qbo_party", "update_customer", "fail", str(e))

    # GET (verify update stuck)
    try:
        fetched = await client.execute(Customer.get, cust_id, qb=client.qb_client)
        company = fetched.CompanyName
        ok = "Updated" in (company or "")
        record(
            "qbo_party",
            "get_customer",
            "pass" if ok else "fail",
            f"CompanyName={company} (update verified={ok})",
        )
    except Exception as e:
        record("qbo_party", "get_customer", "fail", str(e))


# ---------------------------------------------------------------------------
# 2. qbo_item — create, deactivate
# ---------------------------------------------------------------------------


async def validate_item_write(client) -> None:
    """Create a test service item, then deactivate it."""
    from quickbooks.objects.item import Item

    print("\n--- qbo_item (write) ---")

    # Find an income account for the item
    income_acct_id = await find_income_account(client)
    if not income_acct_id:
        record("qbo_item", "create_item", "fail", "No income account found for IncomeAccountRef")
        return

    # CREATE
    try:

        def _create():
            item = Item()
            item.Name = f"[MCP-TEST] Validation Service {date.today().isoformat()}"
            item.Type = "Service"
            item.Description = "MCP validation test service — will be deactivated"
            item.UnitPrice = 150.00
            item.IncomeAccountRef = {"value": income_acct_id}
            return item.save(qb=client.qb_client)

        created = await client.execute(_create)
        item_id = created.Id
        _created["item_id"] = item_id
        record("qbo_item", "create_item", "pass", f"ID={item_id}, Name={created.Name}")
    except Exception as e:
        record("qbo_item", "create_item", "fail", str(e))
        return


# ---------------------------------------------------------------------------
# 3. qbo_transaction — create invoice, update, pdf, void
# ---------------------------------------------------------------------------


async def validate_transaction_write(client) -> None:
    """Create a test invoice, update memo, get PDF, then void."""
    from quickbooks.objects.invoice import Invoice

    print("\n--- qbo_transaction (write) ---")

    cust_id = _created["customer_id"]
    item_id = _created["item_id"]
    if not cust_id:
        record("qbo_transaction", "create_invoice", "fail", "No test customer — skipping")
        return

    # CREATE invoice
    try:
        line_items = [
            {
                "Amount": 150.00,
                "DetailType": "SalesItemLineDetail",
                "SalesItemLineDetail": {
                    "ItemRef": {"value": item_id} if item_id else {},
                    "UnitPrice": 150.00,
                    "Qty": 1,
                },
                "Description": "MCP validation test line item",
            }
        ]

        def _create():
            inv = Invoice()
            inv.CustomerRef = {"value": cust_id}
            inv.Line = line_items
            inv.PrivateNote = "[MCP-TEST] Validation invoice — will be voided"
            inv.DueDate = (date.today() + timedelta(days=30)).isoformat()
            inv.save(qb=client.qb_client)
            return inv

        created = await client.execute(_create)
        inv_id = created.Id
        _created["invoice_id"] = inv_id
        total = getattr(created, "TotalAmt", "?")
        record("qbo_transaction", "create_invoice", "pass", f"ID={inv_id}, Total={total}")
    except Exception as e:
        record("qbo_transaction", "create_invoice", "fail", str(e))
        return

    # UPDATE memo
    try:

        def _update():
            obj = Invoice.get(inv_id, qb=client.qb_client)
            obj.PrivateNote = "[MCP-TEST] Updated memo — validation complete"
            obj.save(qb=client.qb_client)
            return obj

        updated = await client.execute(_update)
        record("qbo_transaction", "update_invoice", "pass", f"Memo={updated.PrivateNote}")
    except Exception as e:
        record("qbo_transaction", "update_invoice", "fail", str(e))

    # PDF download
    try:

        def _pdf():
            inv = Invoice.get(inv_id, qb=client.qb_client)
            return inv.download_pdf(qb=client.qb_client)

        pdf_bytes = await client.execute(_pdf)
        size = len(pdf_bytes) if pdf_bytes else 0
        is_pdf = pdf_bytes[:4] == b"%PDF" if pdf_bytes else False
        record(
            "qbo_transaction",
            "pdf_invoice",
            "pass" if is_pdf else "fail",
            f"{size} bytes, valid_pdf={is_pdf}",
        )
    except Exception as e:
        record("qbo_transaction", "pdf_invoice", "fail", str(e))


# ---------------------------------------------------------------------------
# 4. qbo_attachment — upload, get, delete
# ---------------------------------------------------------------------------


async def validate_attachment_write(client) -> None:
    """Upload a test file to the invoice, get metadata, then delete."""
    import json

    import requests

    print("\n--- qbo_attachment (write) ---")

    inv_id = _created["invoice_id"]
    if not inv_id:
        record("qbo_attachment", "upload", "fail", "No test invoice — skipping")
        return

    # Create a minimal test PDF
    test_pdf = Path(tempfile.mktemp(suffix=".pdf"))
    # Minimal valid PDF
    test_pdf.write_bytes(
        b"%PDF-1.0\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj "
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj "
        b"3 0 obj<</Type/Page/MediaBox[0 0 3 3]>>endobj\n"
        b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n"
        b"0000000058 00000 n \n0000000115 00000 n \n"
        b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n174\n%%EOF"
    )

    # UPLOAD
    try:
        qb = client.qb_client
        base_url = (
            "https://quickbooks.api.intuit.com"
            if client.environment == "production"
            else "https://sandbox-quickbooks.api.intuit.com"
        )
        url = f"{base_url}/v3/company/{client.realm_id}/upload"

        upload_metadata = {
            "AttachableRef": [{"EntityRef": {"type": "Invoice", "value": inv_id}}],
            "FileName": "mcp-test-validation.pdf",
            "ContentType": "application/pdf",
            "Note": "[MCP-TEST] Validation attachment — will be deleted",
        }

        def _upload():
            access_token = qb.auth_client.access_token
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            }
            files = {
                "file_metadata_01": (None, json.dumps(upload_metadata), "application/json"),
                "file_content_01": (
                    "mcp-test-validation.pdf",
                    test_pdf.read_bytes(),
                    "application/pdf",
                ),
            }
            resp = requests.post(url, headers=headers, files=files)
            resp.raise_for_status()
            return resp.json()

        raw = await client.execute(_upload)
        att_response = raw.get("AttachableResponse", [{}])
        attachable = att_response[0].get("Attachable", {})
        att_id = attachable.get("Id")
        _created["attachment_id"] = att_id
        record("qbo_attachment", "upload", "pass", f"ID={att_id}, File=mcp-test-validation.pdf")
    except Exception as e:
        record("qbo_attachment", "upload", "fail", str(e))
    finally:
        test_pdf.unlink(missing_ok=True)

    # GET metadata
    if _created["attachment_id"]:
        try:
            from quickbooks.objects.attachable import Attachable

            att = await client.execute(
                Attachable.get, _created["attachment_id"], qb=client.qb_client
            )
            fname = getattr(att, "FileName", "?")
            record("qbo_attachment", "get", "pass", f"FileName={fname}")
        except Exception as e:
            record("qbo_attachment", "get", "fail", str(e))


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


async def cleanup(client) -> None:
    """Delete/void/deactivate all test entities in reverse order."""
    from quickbooks.objects.attachable import Attachable
    from quickbooks.objects.customer import Customer
    from quickbooks.objects.invoice import Invoice
    from quickbooks.objects.item import Item

    print("\n--- CLEANUP ---")

    # Delete attachment
    if _created["attachment_id"]:
        try:

            def _del_att():
                obj = Attachable.get(_created["attachment_id"], qb=client.qb_client)
                obj.delete(qb=client.qb_client)
                return True

            await client.execute(_del_att)
            record("cleanup", "delete_attachment", "pass", f"ID={_created['attachment_id']}")
        except Exception as e:
            record("cleanup", "delete_attachment", "fail", str(e))

    # Void invoice
    if _created["invoice_id"]:
        try:

            def _void_inv():
                obj = Invoice.get(_created["invoice_id"], qb=client.qb_client)
                obj.void(qb=client.qb_client)
                return True

            await client.execute(_void_inv)
            record("cleanup", "void_invoice", "pass", f"ID={_created['invoice_id']}")
        except Exception as e:
            record("cleanup", "void_invoice", "fail", str(e))

    # Deactivate item
    if _created["item_id"]:
        try:

            def _deact_item():
                obj = Item.get(_created["item_id"], qb=client.qb_client)
                obj.Active = False
                obj.save(qb=client.qb_client)
                return True

            await client.execute(_deact_item)
            record("cleanup", "deactivate_item", "pass", f"ID={_created['item_id']}")
        except Exception as e:
            record("cleanup", "deactivate_item", "fail", str(e))

    # Deactivate customer
    if _created["customer_id"]:
        try:

            def _deact_cust():
                obj = Customer.get(_created["customer_id"], qb=client.qb_client)
                obj.Active = False
                obj.save(qb=client.qb_client)
                return True

            await client.execute(_deact_cust)
            record("cleanup", "deactivate_customer", "pass", f"ID={_created['customer_id']}")
        except Exception as e:
            record("cleanup", "deactivate_customer", "fail", str(e))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> int:
    from quickbooks_mcp.client import QBOClient

    print("=" * 60)
    print("QuickBooks MCP — Live Validation (WRITE OPERATIONS)")
    print("=" * 60)
    print(
        "\nThis script creates test entities prefixed [MCP-TEST],\n"
        "validates write operations, then cleans up everything.\n"
    )

    # Connect
    print("Connecting to QBO...")
    client = QBOClient.from_config()
    try:
        await client.connect()
    except Exception as e:
        print(f"\nFATAL: Could not connect to QBO: {e}")
        traceback.print_exc()
        return 1

    print(f"Connected! realm={client.realm_id}, env={client.environment}\n")

    # Run write validations
    validators = [
        validate_party_write,
        validate_item_write,
        validate_transaction_write,
        validate_attachment_write,
    ]

    for validator in validators:
        try:
            await validator(client)
        except Exception as e:
            print(f"\nUnexpected error in {validator.__name__}: {e}")
            traceback.print_exc()

    # Always attempt cleanup
    try:
        await cleanup(client)
    except Exception as e:
        print(f"\nCleanup error: {e}")
        traceback.print_exc()

    await client.close()

    # Summary
    # Separate validation results from cleanup results
    validation = [r for r in results if r["tool"] != "cleanup"]
    cleanup_results = [r for r in results if r["tool"] == "cleanup"]

    v_passed = sum(1 for r in validation if r["status"] == "pass")
    v_failed = sum(1 for r in validation if r["status"] == "fail")
    c_passed = sum(1 for r in cleanup_results if r["status"] == "pass")
    c_failed = sum(1 for r in cleanup_results if r["status"] == "fail")

    print("\n" + "=" * 60)
    print(f"WRITE TESTS: {v_passed}/{len(validation)} passed, {v_failed} failed")
    print(f"CLEANUP:     {c_passed}/{len(cleanup_results)} passed, {c_failed} failed")
    print("=" * 60)

    if v_failed:
        print("\nFailed write tests:")
        for r in validation:
            if r["status"] == "fail":
                print(f"  - {r['tool']}.{r['op']}: {r['detail'][:200]}")

    if c_failed:
        print("\nFailed cleanup (manual review needed):")
        for r in cleanup_results:
            if r["status"] == "fail":
                print(f"  - {r['op']}: {r['detail'][:200]}")

    # Created entity IDs for reference
    print("\nEntities created (for manual verification):")
    for key, val in _created.items():
        print(f"  {key}: {val or 'N/A'}")

    return 0 if v_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
