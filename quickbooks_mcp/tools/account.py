"""qbo_account tool — Chart of Accounts CRUD."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

from fastmcp import Context
from fastmcp.exceptions import ToolError

from quickbooks_mcp.converters import qbo_to_snake
from quickbooks_mcp.formatting import format_response, paginate_list, truncate_response
from quickbooks_mcp.models import (
    ERROR_SHAPE_HINT,
    IDS_QUERY_RULES,
    PROTECTED_KEYS,
    SEARCH_EXAMPLES,
    VALID_ACCOUNT_TYPES,
)

if TYPE_CHECKING:
    from fastmcp import FastMCP

logger = logging.getLogger(__name__)

_ENTITY_TYPE = "Account"
_TOOL_DESCRIPTION = (
    "Manage the QuickBooks Online Chart of Accounts. "
    "Create, list, update, deactivate, or search accounts. "
    "account_type is required for create (e.g. 'Bank', 'Expense', 'Income'). "
    "Use qbo_help(topic='fields', entity='Account') for queryable field names. "
    f"Search uses IDS query syntax — {IDS_QUERY_RULES} "
    f"{SEARCH_EXAMPLES['account']} "
    f"{ERROR_SHAPE_HINT}"
)


def register(mcp: FastMCP) -> None:
    """Register the qbo_account tool on *mcp*."""

    @mcp.tool(
        name="qbo_account",
        description=_TOOL_DESCRIPTION,
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    async def qbo_account(
        ctx: Context,
        operation: Literal["list", "get", "create", "update", "deactivate", "search"],
        id: str | None = None,
        name: str | None = None,
        account_type: VALID_ACCOUNT_TYPES | None = None,
        account_sub_type: str | None = None,
        active_only: bool = True,
        query: str | None = None,
        max_results: int = 20,
        offset: int = 0,
        extra: dict | None = None,
        response_format: Literal["json", "markdown"] = "json",
    ) -> dict | str:
        f"""Chart of Accounts CRUD for QuickBooks Online.

        Operations:
        - list: Fetch all accounts. Supports active_only, max_results, offset.
        - get: Fetch a single account by ID.
        - create: Create a new account. Requires name and account_type.
        - update: Update account fields. Auto-fetches SyncToken. Requires id.
        - deactivate: Set Active=False on an account. Requires id.
        - search: Query accounts using an IDS WHERE clause. {IDS_QUERY_RULES}

        account_type: QBO account classification. Valid values: Bank,
        Accounts Receivable, Other Current Asset, Fixed Asset, Other Asset,
        Accounts Payable, Credit Card, Other Current Liability,
        Long Term Liability, Equity, Income, Cost of Goods Sold,
        Expense, Other Income, Other Expense.

        account_sub_type examples: Checking, Savings, CreditCard,
        Accumulated Depreciation, Depreciation, Goodwill, Licenses.

        extra: optional dict of additional QBO fields to merge before save.
        Protected keys (Id, SyncToken, domain, sparse, MetaData, TxnDate) are
        rejected to prevent accidental overwrites.
        """

        from quickbooks_mcp.server import get_client

        client = get_client(ctx)
        qb = client.qb_client

        # Validate extra against protected keys.
        extra_fields: dict = extra or {}
        if extra_fields:
            bad_keys = PROTECTED_KEYS & set(extra_fields.keys())
            if bad_keys:
                raise ToolError(
                    f"extra contains protected keys that cannot be set: {sorted(bad_keys)}. "
                    "Remove these keys and retry."
                )

        # ------------------------------------------------------------------
        # list
        # ------------------------------------------------------------------
        if operation == "list":
            max_results = max(1, min(100, max_results))

            def _list() -> list:
                from quickbooks.objects.account import Account

                filters = {"max_results": 1000, "start_position": 1}
                if active_only:
                    filters["Active"] = True
                return Account.filter(**filters, qb=qb)

            accounts = await client.execute(_list)
            converted = [qbo_to_snake(a.to_dict()) for a in accounts]
            page, meta = paginate_list(
                converted, total=len(converted), offset=offset, limit=max_results
            )
            response = format_response(
                page, operation, _ENTITY_TYPE, metadata=meta, response_format=response_format
            )
            if response_format == "json":
                response = truncate_response(response)
            return response

        # ------------------------------------------------------------------
        # get
        # ------------------------------------------------------------------
        if operation == "get":
            if not id:
                raise ToolError("id is required for operation='get'.")

            def _get() -> object:
                from quickbooks.objects.account import Account

                return Account.get(id, qb=qb)

            account = await client.execute(_get)
            converted = qbo_to_snake(account.to_dict())
            return format_response(
                converted, operation, _ENTITY_TYPE, response_format=response_format
            )

        # ------------------------------------------------------------------
        # create
        # ------------------------------------------------------------------
        if operation == "create":
            if not name:
                raise ToolError("name is required for operation='create'.")
            if not account_type:
                raise ToolError("account_type is required for operation='create'.")

            def _create() -> object:
                from quickbooks.objects.account import Account

                account = Account()
                account.Name = name
                account.AccountType = account_type
                if account_sub_type:
                    account.AccountSubType = account_sub_type
                for k, v in extra_fields.items():
                    setattr(account, k, v)
                account.save(qb=qb)
                return account

            account = await client.execute(_create)
            converted = qbo_to_snake(account.to_dict())
            return format_response(
                converted, operation, _ENTITY_TYPE, response_format=response_format
            )

        # ------------------------------------------------------------------
        # update
        # ------------------------------------------------------------------
        if operation == "update":
            if not id:
                raise ToolError("id is required for operation='update'.")

            def _update() -> object:
                from quickbooks.objects.account import Account

                account = Account.get(id, qb=qb)
                if name:
                    account.Name = name
                if account_type:
                    account.AccountType = account_type
                if account_sub_type:
                    account.AccountSubType = account_sub_type
                for k, v in extra_fields.items():
                    setattr(account, k, v)
                account.save(qb=qb)
                return account

            account = await client.execute(_update)
            converted = qbo_to_snake(account.to_dict())
            return format_response(
                converted, operation, _ENTITY_TYPE, response_format=response_format
            )

        # ------------------------------------------------------------------
        # deactivate
        # ------------------------------------------------------------------
        if operation == "deactivate":
            if not id:
                raise ToolError("id is required for operation='deactivate'.")

            def _deactivate() -> object:
                from quickbooks.objects.account import Account

                account = Account.get(id, qb=qb)
                account.Active = False
                account.save(qb=qb)
                return account

            account = await client.execute(_deactivate)
            converted = qbo_to_snake(account.to_dict())
            return format_response(
                converted, operation, _ENTITY_TYPE, response_format=response_format
            )

        # ------------------------------------------------------------------
        # search
        # ------------------------------------------------------------------
        if operation == "search":
            if not query:
                raise ToolError(
                    "query is required for operation='search'. "
                    "Provide an IDS WHERE clause, e.g. \"Name LIKE '%Checking%'\"."
                )
            sql = f"SELECT * FROM Account WHERE {query}"
            rows = await client.query_rows(sql, _ENTITY_TYPE)
            converted = [qbo_to_snake(row) for row in rows]

            response = format_response(
                converted,
                operation,
                _ENTITY_TYPE,
                metadata={"query": sql},
                response_format=response_format,
            )
            if response_format == "json":
                response = truncate_response(response)
            return response

        # Should be unreachable due to Literal type constraint
        raise ToolError(f"Unknown operation: {operation!r}.")  # pragma: no cover
