"""qbo_attachment tool — File attachments for QBO entities."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Literal

import requests
from fastmcp import Context
from fastmcp.exceptions import ToolError

from quickbooks_mcp.converters import qbo_to_snake
from quickbooks_mcp.formatting import format_response

if TYPE_CHECKING:
    from fastmcp import FastMCP

logger = logging.getLogger(__name__)

_ENTITY_TYPE = "Attachable"

SUPPORTED_ENTITY_TYPES = frozenset(
    {"invoice", "bill", "journal_entry", "item", "purchase", "vendor", "customer"}
)

ALLOWED_EXTENSIONS = frozenset(
    {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".doc", ".docx", ".xls", ".xlsx"}
)

MIME_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

# Map snake_case entity_type values to the QBO PascalCase names used in the API.
_ENTITY_TYPE_MAP = {
    "invoice": "Invoice",
    "bill": "Bill",
    "journal_entry": "JournalEntry",
    "item": "Item",
    "purchase": "Purchase",
    "vendor": "Vendor",
    "customer": "Customer",
}


def register(mcp: FastMCP) -> None:
    """Register the qbo_attachment tool on *mcp*."""

    @mcp.tool(
        name="qbo_attachment",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    async def qbo_attachment(
        ctx: Context,
        operation: Literal["upload", "list", "get", "download", "delete"],
        file_path: str | None = None,
        entity_type: Literal[
            "invoice", "bill", "journal_entry", "item", "purchase", "vendor", "customer"
        ]
        | None = None,
        entity_id: str | None = None,
        id: str | None = None,
        note: str | None = None,
        output_dir: str | None = None,
        response_format: Literal["json", "markdown"] = "json",
    ) -> dict | str:
        """File attachments for QuickBooks Online entities.

        Operations:
        - upload: Attach a local file to a QBO entity. Requires file_path,
          entity_type, and entity_id. Uses direct HTTP multipart upload (the
          SDK does not support file upload).
        - list: List attachments linked to a QBO entity. Requires entity_type
          and entity_id.
        - get: Fetch attachment metadata by ID. Requires id.
        - download: Download attachment content to disk. Requires id. Writes
          the file to output_dir (defaults to current working directory).
        - delete: Permanently delete an attachment. Requires id.

        Supported entity_type values: invoice, bill, journal_entry, item,
        purchase, vendor, customer.

        Supported file extensions: .pdf .png .jpg .jpeg .gif .doc .docx
        .xls .xlsx
        """

        from quickbooks_mcp.server import get_client

        client = get_client(ctx)
        qb = client.qb_client

        # ------------------------------------------------------------------
        # upload
        # ------------------------------------------------------------------
        if operation == "upload":
            if not file_path:
                raise ToolError("file_path is required for operation='upload'.")
            if not entity_type:
                raise ToolError("entity_type is required for operation='upload'.")
            if not entity_id:
                raise ToolError("entity_id is required for operation='upload'.")

            entity_type_lower = entity_type.lower()
            if entity_type_lower not in SUPPORTED_ENTITY_TYPES:
                raise ToolError(
                    f"Unsupported entity_type: {entity_type!r}. "
                    f"Allowed: {sorted(SUPPORTED_ENTITY_TYPES)}"
                )

            from pathlib import Path

            path = Path(file_path)
            if not path.exists():
                raise ToolError(f"File not found: {file_path}")

            ext = path.suffix.lower()
            if ext not in ALLOWED_EXTENSIONS:
                raise ToolError(
                    f"Unsupported file type: {ext}. Allowed: {sorted(ALLOWED_EXTENSIONS)}"
                )

            mime = MIME_TYPES[ext]
            file_bytes = path.read_bytes()
            qbo_entity_type = _ENTITY_TYPE_MAP[entity_type_lower]

            base_url = (
                "https://quickbooks.api.intuit.com"
                if client.environment == "production"
                else "https://sandbox-quickbooks.api.intuit.com"
            )
            url = f"{base_url}/v3/company/{client.realm_id}/upload"

            upload_metadata: dict = {
                "AttachableRef": [{"EntityRef": {"type": qbo_entity_type, "value": entity_id}}],
                "FileName": path.name,
                "ContentType": mime,
            }
            if note:
                upload_metadata["Note"] = note

            def _do_upload() -> dict:
                access_token = qb.auth_client.access_token
                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                }
                files = {
                    "file_metadata_01": (None, json.dumps(upload_metadata), "application/json"),
                    "file_content_01": (path.name, file_bytes, mime),
                }
                resp = requests.post(url, headers=headers, files=files)
                resp.raise_for_status()
                return resp.json()

            raw = await client.execute(_do_upload)

            # QBO upload response wraps the result in AttachableResponse[].
            attachable_response = raw.get("AttachableResponse", [{}])
            attachable_data = attachable_response[0].get("Attachable", raw)
            converted = qbo_to_snake(attachable_data)
            return format_response(
                converted, operation, _ENTITY_TYPE, response_format=response_format
            )

        # ------------------------------------------------------------------
        # list
        # ------------------------------------------------------------------
        if operation == "list":
            if not entity_type:
                raise ToolError("entity_type is required for operation='list'.")
            if not entity_id:
                raise ToolError("entity_id is required for operation='list'.")

            entity_type_lower = entity_type.lower()
            if entity_type_lower not in SUPPORTED_ENTITY_TYPES:
                raise ToolError(
                    f"Unsupported entity_type: {entity_type!r}. "
                    f"Allowed: {sorted(SUPPORTED_ENTITY_TYPES)}"
                )

            qbo_entity_type = _ENTITY_TYPE_MAP[entity_type_lower]

            def _list() -> list:
                sql = (
                    f"SELECT * FROM Attachable WHERE "
                    f"AttachableRef.EntityRef.Type = '{qbo_entity_type}' AND "
                    f"AttachableRef.EntityRef.value = '{entity_id}'"
                )
                return qb.query(sql)

            results = await client.execute(_list)

            if results and isinstance(results[0], dict):
                converted_list = [qbo_to_snake(r) for r in results]
            else:
                converted_list = [qbo_to_snake(r.to_dict()) for r in results]

            return format_response(
                converted_list, operation, _ENTITY_TYPE, response_format=response_format
            )

        # ------------------------------------------------------------------
        # get
        # ------------------------------------------------------------------
        if operation == "get":
            if not id:
                raise ToolError("id is required for operation='get'.")

            def _get() -> object:
                from quickbooks.objects.attachable import Attachable

                return Attachable.get(id, qb=qb)

            attachable = await client.execute(_get)
            converted = qbo_to_snake(attachable.to_dict())
            return format_response(
                converted, operation, _ENTITY_TYPE, response_format=response_format
            )

        # ------------------------------------------------------------------
        # download
        # ------------------------------------------------------------------
        if operation == "download":
            if not id:
                raise ToolError("id is required for operation='download'.")

            def _get_meta() -> object:
                from quickbooks.objects.attachable import Attachable

                return Attachable.get(id, qb=qb)

            attachable = await client.execute(_get_meta)
            download_url = getattr(attachable, "TempDownloadUri", None)
            if not download_url:
                raise ToolError("No download URL available for this attachment.")

            file_name = getattr(attachable, "FileName", None) or f"attachment_{id}"

            def _fetch() -> bytes:
                access_token = qb.auth_client.access_token
                resp = requests.get(
                    download_url,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                resp.raise_for_status()
                return resp.content

            content = await client.execute(_fetch)

            from pathlib import Path

            out_path = Path(output_dir or ".") / file_name
            out_path.write_bytes(content)

            result_data = {
                "id": id,
                "file_name": file_name,
                "saved_to": str(out_path.resolve()),
                "size_bytes": len(content),
            }
            return format_response(
                result_data, operation, _ENTITY_TYPE, response_format=response_format
            )

        # ------------------------------------------------------------------
        # delete
        # ------------------------------------------------------------------
        if operation == "delete":
            if not id:
                raise ToolError("id is required for operation='delete'.")

            def _delete() -> dict:
                from quickbooks.objects.attachable import Attachable

                obj = Attachable.get(id, qb=qb)
                obj.delete(qb=qb)
                return {"id": id, "deleted": True}

            result = await client.execute(_delete)
            return format_response(result, operation, _ENTITY_TYPE, response_format=response_format)

        # Should be unreachable due to Literal type constraint
        raise ToolError(f"Unknown operation: {operation!r}.")  # pragma: no cover
