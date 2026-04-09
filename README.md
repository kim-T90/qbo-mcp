# QuickBooks Online MCP Server

A Python MCP server exposing QuickBooks Online accounting operations through 8 parameterized tools (~140 operations). Built on FastMCP 3.x + python-quickbooks.

**Stack:** Python 3.13, FastMCP 3.x, python-quickbooks, intuit-oauth, uv

## Quick Start

### 1. Install dependencies

```bash
uv sync
```

### 2. Choose your setup track

This repo supports two OAuth setup paths:

- **Sandbox quickstart**: use development keys and a sandbox company. If `QBO_REDIRECT_URI` is unset, the auth CLI falls back to the Intuit OAuth Playground for a fast local setup.
- **Production / private internal setup**: use production keys and your live QuickBooks Online company. You must register your own HTTPS redirect URI in Intuit Developer and set `QBO_REDIRECT_URI` locally.

### 3A. Sandbox quickstart

Create or open an app at [developer.intuit.com](https://developer.intuit.com), then copy the app's **development** Client ID and Client Secret.

```bash
cp .env.example .env
```

Edit `.env` and set:

```dotenv
QBO_CLIENT_ID=your_development_client_id
QBO_CLIENT_SECRET=your_development_client_secret
QBO_ENVIRONMENT=sandbox
QBO_REDIRECT_URI=
```

Leave `QBO_REFRESH_TOKEN` and `QBO_REALM_ID` blank. Then run:

```bash
uv run python -m quickbooks_mcp.auth
```

The CLI opens the authorization URL, then asks you to paste the full callback URL from your browser. In sandbox mode, leaving `QBO_REDIRECT_URI` blank uses the Intuit OAuth Playground redirect automatically.

### 3B. Production / private internal setup

Production access to live QuickBooks data still requires a real Intuit app, even for internal use.

In Intuit Developer:

1. Create or open the app you will dedicate to this MCP.
2. Complete the production metadata and compliance flow.
3. Register your production redirect URI, for example:
   `https://your-org.example.com/integrations/quickbooks/callback`
4. Wait for production keys to become available, then copy the **production** Client ID and Client Secret.

Your public pages can stay minimal. Most teams add:

- `https://your-org.example.com/integrations/quickbooks/privacy`
- `https://your-org.example.com/integrations/quickbooks/terms`
- `https://your-org.example.com/integrations/quickbooks/launch`
- `https://your-org.example.com/integrations/quickbooks/disconnect`
- `https://your-org.example.com/integrations/quickbooks/callback`

The callback page can be a static page that shows `window.location.href` and offers a copy button so you can paste the full callback URL back into the terminal. A starter bundle for all required pages lives at `examples/quickbooks_pages/`.

Set `.env` like this:

```dotenv
QBO_CLIENT_ID=your_production_client_id
QBO_CLIENT_SECRET=your_production_client_secret
QBO_ENVIRONMENT=production
QBO_REDIRECT_URI=https://your-org.example.com/integrations/quickbooks/callback
QBO_REFRESH_TOKEN=
QBO_REALM_ID=
```

Then run:

```bash
uv run python -m quickbooks_mcp.auth
```

After you approve the app in QuickBooks, land on your hosted callback page, copy the full callback URL, and paste it back into the terminal. The script saves `QBO_REFRESH_TOKEN` and `QBO_REALM_ID` to `.env`.

### 4. Verify the connection

```bash
uv run python -c "
import asyncio
from quickbooks_mcp.client import QBOClient
async def check():
    c = QBOClient.from_config()
    await c.connect()
    print(f'Connected to {c.environment} (realm {c.realm_id})')
    await c.close()
asyncio.run(check())
"
```

If this prints your realm ID, you're good. If it fails, check your `.env` values and re-run the auth flow.

### 5. Register in Claude Code

First, find your quickbooks directory path:

```bash
# From the quickbooks project directory:
pwd
# Example output: /Users/you/Projects/MCP Combo Building/src/quickbooks
```

Then register (replace the path with YOUR output from `pwd`):

```bash
claude mcp add quickbooks \
  --scope user \
  -e QBO_CLIENT_ID=YOUR_CLIENT_ID \
  -e QBO_CLIENT_SECRET=YOUR_CLIENT_SECRET \
  -e QBO_REFRESH_TOKEN=YOUR_REFRESH_TOKEN \
  -e QBO_REALM_ID=YOUR_REALM_ID \
  -e QBO_ENVIRONMENT=production \
  -e QBO_REDIRECT_URI=YOUR_REDIRECT_URI \
  -e QBO_MINOR_VERSION=75 \
  -- uv run --directory "YOUR_PATH_FROM_PWD" python -m quickbooks_mcp
```

**Verify:** Start a new Claude Code session and ask it to call `qbo_reference(operation="get_company_info")`. It should return your company name.

### 6. Register in Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (merge into existing `mcpServers` if the file already has entries):

```json
{
  "mcpServers": {
    "quickbooks": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "YOUR_PATH_FROM_PWD",
        "python",
        "-m",
        "quickbooks_mcp"
      ],
      "env": {
        "QBO_CLIENT_ID": "YOUR_CLIENT_ID",
        "QBO_CLIENT_SECRET": "YOUR_CLIENT_SECRET",
        "QBO_REFRESH_TOKEN": "YOUR_REFRESH_TOKEN",
        "QBO_REALM_ID": "YOUR_REALM_ID",
        "QBO_ENVIRONMENT": "production",
        "QBO_REDIRECT_URI": "YOUR_REDIRECT_URI",
        "QBO_MINOR_VERSION": "75"
      }
    }
  }
}
```

**Important:** Replace `YOUR_PATH_FROM_PWD` and all `YOUR_*` values with your actual credentials from `.env`. Then restart Claude Desktop.

**Verify:** In a new Claude Desktop conversation, ask "What is my company name?" — it should call `qbo_reference` and return it.

## Configuration

Copy `.env.example` to `.env` and fill in your values. See `.env.example` for descriptions of each variable.

| Variable            | Required | Default                                                   | Description                                                   |
| ------------------- | -------- | --------------------------------------------------------- | ------------------------------------------------------------- |
| `QBO_CLIENT_ID`     | Yes      | --                                                        | OAuth app Client ID                                           |
| `QBO_CLIENT_SECRET` | Yes      | --                                                        | OAuth app Client Secret                                       |
| `QBO_REFRESH_TOKEN` | Yes      | --                                                        | OAuth refresh token (auto-rotated)                            |
| `QBO_REALM_ID`      | Yes      | --                                                        | QBO Company ID                                                |
| `QBO_ENVIRONMENT`   | No       | `sandbox`                                                 | `sandbox` or `production`                                     |
| `QBO_REDIRECT_URI`  | Prod yes | `https://developer.intuit.com/v2/OAuth2Playground/RedirectUrl` in sandbox | Registered redirect URI. Required in production.              |
| `QBO_MINOR_VERSION` | No       | `75`                                                      | QBO API minor version                                         |
| `DEBUG_QBO`         | No       | `false`                                                   | Log raw API payloads to stderr                                |

## Tool Reference

All tools accept `response_format: "json" | "markdown"` (default: `"json"`).

### qbo_help

Offline reference for field names, operation matrices, and IDS query syntax. **No API calls.** Use this before constructing search queries or creating transactions.

| Topic          | Description                            | Params                                    |
| -------------- | -------------------------------------- | ----------------------------------------- |
| `fields`       | Queryable field names per entity       | `entity` (e.g. `"Customer"`, `"Invoice"`) |
| `operations`   | Which operations each tx_type supports | --                                        |
| `query_syntax` | IDS query syntax guide with examples   | --                                        |

**Example:** What fields can I search on for invoices?

```
qbo_help(topic="fields", entity="Invoice")
# Returns: Id, DocNumber, TxnDate, DueDate, TotalAmt, Balance, CustomerRef, ...
```

### qbo_reference

Read-only lookup of reference data and company settings.

| Operation              | Description                                  |
| ---------------------- | -------------------------------------------- |
| `get_company_info`     | Company name, address, fiscal year           |
| `get_preferences`      | Account-wide preference settings             |
| `list_tax_codes`       | All tax codes                                |
| `list_classes`         | All classes (tracking/categorization)        |
| `list_departments`     | All departments (locations/business units)   |
| `list_terms`           | Payment terms (Net 30, Due on receipt, etc.) |
| `list_payment_methods` | Payment methods (Check, Credit Card, etc.)   |

**Example:** Verify connection

```
qbo_reference(operation="get_company_info")
```

### qbo_account

Chart of accounts CRUD.

| Operation    | Description    | Key Params                                 |
| ------------ | -------------- | ------------------------------------------ |
| `list`       | Paginated list | `active_only`, `max_results`, `offset`     |
| `get`        | Get by ID      | `id`                                       |
| `create`     | Create account | `name`, `account_type`, `account_sub_type` |
| `update`     | Update account | `id`, fields to update                     |
| `deactivate` | Soft-delete    | `id`                                       |
| `search`     | IDS query      | `query` (WHERE clause)                     |

**Example:** Find bank accounts

```
qbo_account(operation="search", query="AccountType = 'Bank'")
```

### qbo_party

Customers, vendors, and employees via `party_type` parameter.

| Operation    | Description    | Key Params                                     |
| ------------ | -------------- | ---------------------------------------------- |
| `list`       | Paginated list | `party_type`, `active_only`, `max_results`     |
| `get`        | Get by ID      | `party_type`, `id`                             |
| `create`     | Create party   | `party_type`, `display_name`, `email`, `phone` |
| `update`     | Update party   | `party_type`, `id`, fields to update           |
| `deactivate` | Soft-delete    | `party_type`, `id`                             |
| `search`     | IDS query      | `party_type`, `query`                          |

`party_type`: `customer`, `vendor`, `employee`

**Example:** Create a customer

```
qbo_party(
    operation="create",
    party_type="customer",
    display_name="Apex Logistics",
    email="dispatch@apex.com"
)
```

### qbo_transaction

All 13 transaction types via `tx_type` parameter. 9 operations (not all available for every type).

| Operation | Description            | Key Params                                           |
| --------- | ---------------------- | ---------------------------------------------------- |
| `list`    | Paginated list         | `tx_type`, `start_date`, `end_date`, `max_results`   |
| `get`     | Get by ID              | `tx_type`, `id`                                      |
| `create`  | Create transaction     | `tx_type`, `customer_ref`/`vendor_ref`, `line_items` |
| `update`  | Update transaction     | `tx_type`, `id`, fields to update                    |
| `delete`  | Permanently delete     | `tx_type`, `id`                                      |
| `void`    | Void without deleting  | `tx_type`, `id`                                      |
| `send`    | Email PDF to customer  | `tx_type`, `id`, `email`                             |
| `pdf`     | Download as base64 PDF | `tx_type`, `id`                                      |
| `search`  | IDS query              | `tx_type`, `query`                                   |

`tx_type`: `invoice`, `bill`, `bill_payment`, `payment`, `deposit`, `transfer`, `journal_entry`, `purchase`, `estimate`, `credit_memo`, `sales_receipt`, `refund_receipt`, `vendor_credit`

**Example:** Create an invoice

```
qbo_transaction(
    operation="create",
    tx_type="invoice",
    customer_ref="42",
    line_items='[{"amount": 1500.00, "description": "Freight — CHI to LAX", "item_ref": "1"}]',
    due_date="2026-04-30"
)
```

### qbo_item

Products and services catalog.

| Operation    | Description    | Key Params                                              |
| ------------ | -------------- | ------------------------------------------------------- |
| `list`       | Paginated list | `active_only`, `max_results`                            |
| `get`        | Get by ID      | `id`                                                    |
| `create`     | Create item    | `name`, `item_type`, `unit_price`, `income_account_ref` |
| `update`     | Update item    | `id`, fields to update                                  |
| `deactivate` | Soft-delete    | `id`                                                    |
| `search`     | IDS query      | `query`                                                 |

`item_type`: `service`, `non_inventory`, `inventory`

**Example:** Create a service

```
qbo_item(
    operation="create",
    name="Line Haul",
    item_type="service",
    unit_price=2500.00,
    income_account_ref="79"
)
```

### qbo_report

11 financial reports. Read-only.

| Operation          | Description               | Key Params               |
| ------------------ | ------------------------- | ------------------------ |
| `profit_and_loss`  | Income vs expenses        | `start_date`, `end_date` |
| `balance_sheet`    | Assets/liabilities/equity | `as_of_date`             |
| `trial_balance`    | Debit/credit balances     | `as_of_date`             |
| `cash_flow`        | Cash inflows/outflows     | `start_date`, `end_date` |
| `general_ledger`   | Transaction-level detail  | `start_date`, `end_date` |
| `ar_aging_summary` | AR aging buckets          | `as_of_date`             |
| `ar_aging_detail`  | AR aging detail           | `as_of_date`             |
| `ap_aging_summary` | AP aging buckets          | `as_of_date`             |
| `ap_aging_detail`  | AP aging detail           | `as_of_date`             |
| `customer_balance` | Balance per customer      | --                       |
| `vendor_balance`   | Balance per vendor        | --                       |

Options: `summarize_by` (`Total`, `Month`, `Week`, `Days`), `raw` (returns full QBO nesting).

**Example:** Current quarter P&L

```
qbo_report(operation="profit_and_loss", start_date="2026-01-01", end_date="2026-03-31")
```

### qbo_attachment

File attachments on QBO entities. Supports PDF, PNG, JPG, GIF, DOC, DOCX, XLS, XLSX.

| Operation  | Description                | Key Params                              |
| ---------- | -------------------------- | --------------------------------------- |
| `upload`   | Attach file to entity      | `file_path`, `entity_type`, `entity_id` |
| `list`     | List attachments on entity | `entity_type`, `entity_id`              |
| `get`      | Get attachment metadata    | `id`                                    |
| `download` | Download to disk           | `id`, `output_dir`                      |
| `delete`   | Delete attachment          | `id`                                    |

`entity_type`: `invoice`, `bill`, `journal_entry`, `item`, `purchase`, `vendor`, `customer`

**Example:** Attach a rate confirmation to an invoice

```
qbo_attachment(
    operation="upload",
    file_path="/path/to/ratecon.pdf",
    entity_type="invoice",
    entity_id="147"
)
```

### qbo_sync

Bulk and sync operations.

| Operation | Description         | Key Params                                               |
| --------- | ------------------- | -------------------------------------------------------- |
| `cdc`     | Change Data Capture | `entities` (comma-separated), `changed_since` (ISO date) |
| `batch`   | Batch up to 30 ops  | `operations` (JSON array)                                |
| `count`   | Count entities      | `entity_type`, `query` (optional WHERE)                  |

**Example:** What changed in the last 7 days?

```
qbo_sync(operation="cdc", entities="Invoice,Bill,Payment", changed_since="2026-03-21")
```

## IDS Query Syntax

The `search` operation on all tools uses QBO's IDS query language (not SQL):

- Table names are **singular**: `Invoice`, not `Invoices`
- No JOINs, subqueries, or GROUP BY
- Operators: `=`, `<`, `>`, `<=`, `>=`, `LIKE`, `IN`
- `LIKE` uses `%` wildcard: `WHERE DisplayName LIKE '%Smith%'`
- String values use **single quotes**
- Max 1000 results per query
- Order by `MetaData.LastUpdatedTime` (not `Id`)

**Common field names** (QBO uses PascalCase, not snake_case):

| Entity          | Key Fields                                                              |
| --------------- | ----------------------------------------------------------------------- |
| Customer/Vendor | `DisplayName`, `CompanyName`, `PrimaryEmailAddr`, `Balance`, `Active`   |
| Invoice         | `DocNumber`, `TotalAmt`, `Balance`, `DueDate`, `TxnDate`, `CustomerRef` |
| Bill            | `DocNumber`, `TotalAmt`, `Balance`, `DueDate`, `TxnDate`, `VendorRef`   |
| Account         | `Name`, `AccountType`, `AccountSubType`, `CurrentBalance`, `Active`     |
| Item            | `Name`, `Type`, `UnitPrice`, `Active`                                   |

**Examples:**

```
# Find customers by name (use DisplayName, not name)
qbo_party(operation="search", party_type="customer", query="DisplayName LIKE '%freight%'")

# Find high-value invoices
qbo_transaction(operation="search", tx_type="invoice", query="TotalAmt > '1000.00'")

# Find inactive accounts
qbo_account(operation="search", query="Active = false")
```

## Troubleshooting

| Problem                                     | Solution                                                                                                                |
| ------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `Missing required QuickBooks configuration` | Copy `.env.example` to `.env` and fill in credentials. Run auth flow if tokens are missing.                             |
| `QBO_REDIRECT_URI is required`              | Set `QBO_REDIRECT_URI` to the production callback URL you registered in Intuit Developer.                               |
| `Failed to connect to QuickBooks Online`    | Refresh token may be expired. Re-run: `uv run python -m quickbooks_mcp.auth`                                            |
| `QBO connection expired`                    | Same fix — re-run the auth flow to get fresh tokens.                                                                    |
| `Business Validation Error`                 | Check the `detail` field in the error response. Common cause: missing `customer_ref` on invoices or wrong field values. |
| `Rate limit exceeded (429)`                 | Wait 60 seconds. Use `max_results` to reduce page sizes. Batch operations where possible.                               |
| Search returns empty but data exists        | Field names are PascalCase (`DisplayName`, not `name`). Check the field name table above.                               |
| MCP not showing in Claude Code              | Restart your Claude Code session. Check `~/.claude/.mcp.json` for the entry.                                            |
| MCP not showing in Claude Desktop           | Restart Claude Desktop. Check JSON syntax in `claude_desktop_config.json`.                                              |

## Development

```bash
# Run tests
uv run pytest

# Lint
uv run ruff check .

# Dev server with Inspector UI
uv run fastmcp dev inspector quickbooks_mcp/server.py

# Live validation (read-only)
uv run python validate_live.py

# Live validation (write ops + cleanup)
uv run python validate_live_write.py
```

## Architecture

- **8 parameterized tools** covering ~140 operations (vs 55+ flat tools)
- **Async-safe**: All python-quickbooks calls via `asyncio.to_thread()`
- **Rate limiting**: Token bucket (500 req/min) + semaphore (10 concurrent)
- **Token refresh**: Auto-refresh on 401, atomic `.env` persistence, lock to prevent thundering herd
- **Error handling**: `ToolError` with actionable suggestions, `mask_error_details=True`
- **Response format**: JSON (structured) or Markdown (human-readable), CHARACTER_LIMIT truncation

See `docs/project/architecture.md` for the full design.
