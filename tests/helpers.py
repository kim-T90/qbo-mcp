"""Mock response factories for QuickBooks MCP tests."""

from __future__ import annotations

from typing import Any


def make_invoice_response(
    id_: str = "147",
    doc_number: str = "1001",
    total: float = 1500.00,
    customer_name: str = "Smith Freight LLC",
    balance: float = 1500.00,
) -> dict[str, Any]:
    """Create a mock QBO Invoice response dict."""
    return {
        "Id": id_,
        "DocNumber": doc_number,
        "TotalAmt": total,
        "Balance": balance,
        "CustomerRef": {"value": "42", "name": customer_name},
        "TxnDate": "2026-03-15",
        "DueDate": "2026-04-14",
        "SyncToken": "0",
        "MetaData": {
            "CreateTime": "2026-03-15T10:00:00-07:00",
            "LastUpdatedTime": "2026-03-15T10:00:00-07:00",
        },
        "Line": [
            {
                "Amount": total,
                "Description": "Freight haul - LA to Phoenix",
                "DetailType": "SalesItemLineDetail",
                "SalesItemLineDetail": {
                    "ItemRef": {"value": "1", "name": "Freight"},
                    "Qty": 1,
                    "UnitPrice": total,
                },
            }
        ],
    }


def make_customer_response(
    id_: str = "42",
    display_name: str = "Smith Freight LLC",
    email: str = "smith@freight.com",
    active: bool = True,
) -> dict[str, Any]:
    """Create a mock QBO Customer response dict."""
    return {
        "Id": id_,
        "DisplayName": display_name,
        "PrimaryEmailAddr": {"Address": email},
        "Active": active,
        "SyncToken": "0",
        "MetaData": {
            "CreateTime": "2026-01-15T10:00:00-07:00",
            "LastUpdatedTime": "2026-03-10T14:30:00-07:00",
        },
    }


def make_account_response(
    id_: str = "1",
    name: str = "Checking",
    account_type: str = "Bank",
    current_balance: float = 25000.00,
    active: bool = True,
) -> dict[str, Any]:
    """Create a mock QBO Account response dict."""
    return {
        "Id": id_,
        "Name": name,
        "AccountType": account_type,
        "CurrentBalance": current_balance,
        "Active": active,
        "SyncToken": "0",
    }


def make_company_info_response(
    company_name: str = "Origin Transport LLC",
    legal_name: str = "Origin Transport LLC",
    country: str = "US",
) -> dict[str, Any]:
    """Create a mock QBO CompanyInfo response dict."""
    return {
        "Id": "1",
        "CompanyName": company_name,
        "LegalName": legal_name,
        "Country": country,
        "CompanyAddr": {
            "Line1": "123 Main St",
            "City": "Los Angeles",
            "CountrySubDivisionCode": "CA",
            "PostalCode": "90001",
        },
        "FiscalYearStartMonth": "January",
    }


def make_error_response(
    code: str = "6000",
    message: str = "Business Validation Error",
    detail: str = "CustomerRef is required for Invoice",
) -> dict[str, Any]:
    """Create a mock QBO error Fault response."""
    return {
        "Fault": {
            "Error": [
                {
                    "Message": message,
                    "Detail": detail,
                    "code": code,
                }
            ],
            "type": "ValidationFault",
        }
    }
