"""Tests for the qbo_attachment tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.exceptions import ToolError

from quickbooks_mcp.tools.attachment import register

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_attachable_mock(
    id_: str = "100",
    file_name: str = "invoice.pdf",
    download_uri: str = "https://example.com/dl/invoice.pdf",
) -> MagicMock:
    """Return a mock Attachable object with to_dict() and key attributes."""
    obj = MagicMock()
    obj.Id = id_
    obj.FileName = file_name
    obj.TempDownloadUri = download_uri
    obj.to_dict.return_value = {
        "Id": id_,
        "FileName": file_name,
        "ContentType": "application/pdf",
        "TempDownloadUri": download_uri,
        "SyncToken": "0",
    }
    return obj


def _make_client_mock(
    execute_return=None,
    environment: str = "sandbox",
    realm_id: str = "123456",
) -> MagicMock:
    """Return a mock QBOClient."""
    client = MagicMock()
    client.environment = environment
    client.realm_id = realm_id
    client.qb_client = MagicMock()
    client.qb_client.auth_client.access_token = "test_access_token"
    client.execute = AsyncMock(return_value=execute_return)
    client.query_rows = AsyncMock(return_value=execute_return)
    client.query_count = AsyncMock()
    return client


def _make_ctx(client: MagicMock) -> MagicMock:
    """Return a mock FastMCP Context backed by *client*."""
    ctx = MagicMock()
    ctx.request_context.lifespan_context.client = client
    return ctx


# ---------------------------------------------------------------------------
# Fixture: registered tool function (decorator-capture pattern)
# ---------------------------------------------------------------------------


@pytest.fixture
def tool_fn():
    """Return the raw qbo_attachment coroutine extracted from a one-shot FastMCP."""
    mcp = MagicMock()
    captured = {}

    def fake_tool(**kwargs):
        def decorator(fn):
            captured["fn"] = fn
            return fn

        return decorator

    mcp.tool = fake_tool
    register(mcp)
    return captured["fn"]


# ---------------------------------------------------------------------------
# 1. upload — validates file exists
# ---------------------------------------------------------------------------


class TestUploadFileValidation:
    @pytest.mark.asyncio
    async def test_upload_missing_file_raises(self, tool_fn, tmp_path) -> None:
        client = _make_client_mock()
        ctx = _make_ctx(client)
        missing = str(tmp_path / "nope.pdf")

        with (
            patch("quickbooks_mcp.server.get_client", return_value=client),
            pytest.raises(ToolError, match="File not found"),
        ):
            await tool_fn(
                ctx=ctx,
                operation="upload",
                file_path=missing,
                entity_type="invoice",
                entity_id="147",
            )

    @pytest.mark.asyncio
    async def test_upload_unsupported_extension_raises(self, tool_fn, tmp_path) -> None:
        bad_file = tmp_path / "scan.bmp"
        bad_file.write_bytes(b"fake")
        client = _make_client_mock()
        ctx = _make_ctx(client)

        with (
            patch("quickbooks_mcp.server.get_client", return_value=client),
            pytest.raises(ToolError, match="Unsupported file type"),
        ):
            await tool_fn(
                ctx=ctx,
                operation="upload",
                file_path=str(bad_file),
                entity_type="invoice",
                entity_id="147",
            )

    @pytest.mark.asyncio
    async def test_upload_unsupported_entity_type_raises(self, tool_fn, tmp_path) -> None:
        pdf = tmp_path / "doc.pdf"
        pdf.write_bytes(b"%PDF fake")
        client = _make_client_mock()
        ctx = _make_ctx(client)

        with (
            patch("quickbooks_mcp.server.get_client", return_value=client),
            pytest.raises(ToolError, match="Unsupported entity_type"),
        ):
            await tool_fn(
                ctx=ctx,
                operation="upload",
                file_path=str(pdf),
                entity_type="estimate",
                entity_id="1",
            )


# ---------------------------------------------------------------------------
# 2. upload — sends correct multipart request
# ---------------------------------------------------------------------------


class TestUploadHTTP:
    @pytest.mark.asyncio
    async def test_upload_sends_multipart_request(self, tool_fn, tmp_path) -> None:
        pdf = tmp_path / "rate_con.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake content")

        upload_response = {
            "AttachableResponse": [
                {
                    "Attachable": {
                        "Id": "200",
                        "FileName": "rate_con.pdf",
                        "ContentType": "application/pdf",
                        "SyncToken": "0",
                    }
                }
            ]
        }

        mock_resp = MagicMock()
        mock_resp.json.return_value = upload_response
        mock_resp.raise_for_status = MagicMock()

        client = _make_client_mock()
        ctx = _make_ctx(client)

        # execute() must actually run the closure so requests.post is called.
        async def execute_side_effect(fn, *args, **kwargs):
            return fn()

        client.execute = execute_side_effect

        with (
            patch("quickbooks_mcp.server.get_client", return_value=client),
            patch(
                "quickbooks_mcp.tools.attachment.requests.post", return_value=mock_resp
            ) as mock_post,
        ):
            result = await tool_fn(
                ctx=ctx,
                operation="upload",
                file_path=str(pdf),
                entity_type="invoice",
                entity_id="147",
            )

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        url = call_kwargs[0][0] if call_kwargs[0] else call_kwargs[1]["url"]
        assert "/upload" in url
        assert "sandbox" in url
        assert result["status"] == "ok"
        assert result["operation"] == "upload"
        assert result["data"][0]["id"] == "200"

    @pytest.mark.asyncio
    async def test_upload_uses_production_url_when_production_env(self, tool_fn, tmp_path) -> None:
        pdf = tmp_path / "doc.pdf"
        pdf.write_bytes(b"%PDF fake")

        upload_response = {
            "AttachableResponse": [{"Attachable": {"Id": "1", "FileName": "doc.pdf"}}]
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = upload_response
        mock_resp.raise_for_status = MagicMock()

        client = _make_client_mock(environment="production")
        ctx = _make_ctx(client)

        async def execute_side_effect(fn, *args, **kwargs):
            return fn()

        client.execute = execute_side_effect

        with (
            patch("quickbooks_mcp.server.get_client", return_value=client),
            patch(
                "quickbooks_mcp.tools.attachment.requests.post", return_value=mock_resp
            ) as mock_post,
        ):
            await tool_fn(
                ctx=ctx,
                operation="upload",
                file_path=str(pdf),
                entity_type="invoice",
                entity_id="1",
            )

        url = mock_post.call_args[0][0]
        assert "sandbox" not in url
        assert "quickbooks.api.intuit.com" in url

    @pytest.mark.asyncio
    async def test_upload_includes_note_in_metadata(self, tool_fn, tmp_path) -> None:
        import json as _json

        pdf = tmp_path / "bol.pdf"
        pdf.write_bytes(b"%PDF fake")

        upload_response = {
            "AttachableResponse": [{"Attachable": {"Id": "5", "FileName": "bol.pdf"}}]
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = upload_response
        mock_resp.raise_for_status = MagicMock()

        client = _make_client_mock()
        ctx = _make_ctx(client)

        async def execute_side_effect(fn, *args, **kwargs):
            return fn()

        client.execute = execute_side_effect

        with (
            patch("quickbooks_mcp.server.get_client", return_value=client),
            patch(
                "quickbooks_mcp.tools.attachment.requests.post", return_value=mock_resp
            ) as mock_post,
        ):
            await tool_fn(
                ctx=ctx,
                operation="upload",
                file_path=str(pdf),
                entity_type="bill",
                entity_id="99",
                note="BOL from Origin Transport",
            )

        files = mock_post.call_args[1]["files"]
        metadata_json = files["file_metadata_01"][1]
        metadata = _json.loads(metadata_json)
        assert metadata["Note"] == "BOL from Origin Transport"


# ---------------------------------------------------------------------------
# 3. list — returns attachments for an entity
# ---------------------------------------------------------------------------


class TestList:
    @pytest.mark.asyncio
    async def test_list_returns_attachments(self, tool_fn) -> None:
        raw = [
            {"Id": "10", "FileName": "inv_147.pdf", "ContentType": "application/pdf"},
            {"Id": "11", "FileName": "bol.pdf", "ContentType": "application/pdf"},
        ]
        client = _make_client_mock(execute_return=raw)
        ctx = _make_ctx(client)

        with patch("quickbooks_mcp.server.get_client", return_value=client):
            result = await tool_fn(
                ctx=ctx, operation="list", entity_type="invoice", entity_id="147"
            )

        assert result["status"] == "ok"
        assert result["operation"] == "list"
        assert result["entity_type"] == "Attachable"
        assert len(result["data"]) == 2
        assert result["data"][0]["id"] == "10"

    @pytest.mark.asyncio
    async def test_list_builds_correct_query(self, tool_fn) -> None:
        client = MagicMock()
        client.qb_client = MagicMock()
        client.query_rows = AsyncMock(return_value=[])
        ctx = _make_ctx(client)

        with patch("quickbooks_mcp.server.get_client", return_value=client):
            await tool_fn(ctx=ctx, operation="list", entity_type="invoice", entity_id="147")

        client.query_rows.assert_awaited_once()
        sql = client.query_rows.call_args[0][0]
        assert "Invoice" in sql
        assert "147" in sql

    @pytest.mark.asyncio
    async def test_list_missing_entity_type_raises(self, tool_fn) -> None:
        client = _make_client_mock()
        ctx = _make_ctx(client)

        with (
            patch("quickbooks_mcp.server.get_client", return_value=client),
            pytest.raises(ToolError, match="entity_type is required"),
        ):
            await tool_fn(ctx=ctx, operation="list", entity_id="147")

    @pytest.mark.asyncio
    async def test_list_missing_entity_id_raises(self, tool_fn) -> None:
        client = _make_client_mock()
        ctx = _make_ctx(client)

        with (
            patch("quickbooks_mcp.server.get_client", return_value=client),
            pytest.raises(ToolError, match="entity_id is required"),
        ):
            await tool_fn(ctx=ctx, operation="list", entity_type="invoice")


# ---------------------------------------------------------------------------
# 4. get — returns attachment metadata by ID
# ---------------------------------------------------------------------------


class TestGet:
    @pytest.mark.asyncio
    async def test_get_returns_metadata(self, tool_fn) -> None:
        attachable = _make_attachable_mock(id_="100", file_name="rate_con.pdf")
        client = _make_client_mock(execute_return=attachable)
        ctx = _make_ctx(client)

        with patch("quickbooks_mcp.server.get_client", return_value=client):
            result = await tool_fn(ctx=ctx, operation="get", id="100")

        assert result["status"] == "ok"
        assert result["operation"] == "get"
        assert result["data"][0]["id"] == "100"
        assert result["data"][0]["file_name"] == "rate_con.pdf"

    @pytest.mark.asyncio
    async def test_get_missing_id_raises(self, tool_fn) -> None:
        client = _make_client_mock()
        ctx = _make_ctx(client)

        with (
            patch("quickbooks_mcp.server.get_client", return_value=client),
            pytest.raises(ToolError, match="id is required"),
        ):
            await tool_fn(ctx=ctx, operation="get")


# ---------------------------------------------------------------------------
# 5. download — fetches file and writes to disk
# ---------------------------------------------------------------------------


class TestDownload:
    @pytest.mark.asyncio
    async def test_download_writes_file_to_disk(self, tool_fn, tmp_path) -> None:
        file_content = b"%PDF-1.4 fake file content"
        attachable = _make_attachable_mock(
            id_="100",
            file_name="invoice_147.pdf",
            download_uri="https://example.com/dl/invoice_147.pdf",
        )

        mock_dl_resp = MagicMock()
        mock_dl_resp.content = file_content
        mock_dl_resp.raise_for_status = MagicMock()

        execute_calls: list = []

        async def execute_side_effect(fn, *args, **kwargs):
            call_idx = len(execute_calls)
            execute_calls.append(fn)
            if call_idx == 0:
                # First call: Attachable.get
                return attachable
            # Second call: _fetch (HTTP download)
            return fn()

        client = _make_client_mock()
        client.execute = execute_side_effect
        ctx = _make_ctx(client)

        with (
            patch("quickbooks_mcp.server.get_client", return_value=client),
            patch("quickbooks_mcp.tools.attachment.requests.get", return_value=mock_dl_resp),
        ):
            result = await tool_fn(
                ctx=ctx,
                operation="download",
                id="100",
                output_dir=str(tmp_path),
            )

        saved_file = tmp_path / "invoice_147.pdf"
        assert saved_file.exists()
        assert saved_file.read_bytes() == file_content
        assert result["status"] == "ok"
        assert result["data"][0]["file_name"] == "invoice_147.pdf"
        assert result["data"][0]["size_bytes"] == len(file_content)

    @pytest.mark.asyncio
    async def test_download_no_uri_raises(self, tool_fn) -> None:
        attachable = _make_attachable_mock(id_="100", download_uri=None)
        attachable.TempDownloadUri = None
        client = _make_client_mock(execute_return=attachable)
        ctx = _make_ctx(client)

        with (
            patch("quickbooks_mcp.server.get_client", return_value=client),
            pytest.raises(ToolError, match="No download URL"),
        ):
            await tool_fn(ctx=ctx, operation="download", id="100")

    @pytest.mark.asyncio
    async def test_download_missing_id_raises(self, tool_fn) -> None:
        client = _make_client_mock()
        ctx = _make_ctx(client)

        with (
            patch("quickbooks_mcp.server.get_client", return_value=client),
            pytest.raises(ToolError, match="id is required"),
        ):
            await tool_fn(ctx=ctx, operation="download")


# ---------------------------------------------------------------------------
# 6. delete — fetches then deletes attachment
# ---------------------------------------------------------------------------


class TestDelete:
    @pytest.mark.asyncio
    async def test_delete_calls_sdk_delete(self, tool_fn) -> None:
        attachable = _make_attachable_mock(id_="100")

        async def execute_side_effect(fn, *args, **kwargs):
            with patch("quickbooks.objects.attachable.Attachable.get", return_value=attachable):
                return fn()

        client = _make_client_mock()
        client.execute = execute_side_effect
        ctx = _make_ctx(client)

        with patch("quickbooks_mcp.server.get_client", return_value=client):
            result = await tool_fn(ctx=ctx, operation="delete", id="100")

        attachable.delete.assert_called_once()
        assert result["status"] == "ok"
        assert result["operation"] == "delete"
        assert result["data"][0]["id"] == "100"
        assert result["data"][0]["deleted"] is True

    @pytest.mark.asyncio
    async def test_delete_missing_id_raises(self, tool_fn) -> None:
        client = _make_client_mock()
        ctx = _make_ctx(client)

        with (
            patch("quickbooks_mcp.server.get_client", return_value=client),
            pytest.raises(ToolError, match="id is required"),
        ):
            await tool_fn(ctx=ctx, operation="delete")


# ---------------------------------------------------------------------------
# 7. missing required params — upload edge cases
# ---------------------------------------------------------------------------


class TestUploadValidation:
    @pytest.mark.asyncio
    async def test_upload_missing_file_path_raises(self, tool_fn) -> None:
        client = _make_client_mock()
        ctx = _make_ctx(client)

        with (
            patch("quickbooks_mcp.server.get_client", return_value=client),
            pytest.raises(ToolError, match="file_path is required"),
        ):
            await tool_fn(ctx=ctx, operation="upload", entity_type="invoice", entity_id="1")

    @pytest.mark.asyncio
    async def test_upload_missing_entity_type_raises(self, tool_fn, tmp_path) -> None:
        pdf = tmp_path / "doc.pdf"
        pdf.write_bytes(b"fake")
        client = _make_client_mock()
        ctx = _make_ctx(client)

        with (
            patch("quickbooks_mcp.server.get_client", return_value=client),
            pytest.raises(ToolError, match="entity_type is required"),
        ):
            await tool_fn(ctx=ctx, operation="upload", file_path=str(pdf), entity_id="1")

    @pytest.mark.asyncio
    async def test_upload_missing_entity_id_raises(self, tool_fn, tmp_path) -> None:
        pdf = tmp_path / "doc.pdf"
        pdf.write_bytes(b"fake")
        client = _make_client_mock()
        ctx = _make_ctx(client)

        with (
            patch("quickbooks_mcp.server.get_client", return_value=client),
            pytest.raises(ToolError, match="entity_id is required"),
        ):
            await tool_fn(
                ctx=ctx,
                operation="upload",
                file_path=str(pdf),
                entity_type="invoice",
            )


# ---------------------------------------------------------------------------
# 8. markdown format returns string
# ---------------------------------------------------------------------------


class TestMarkdownFormat:
    @pytest.mark.asyncio
    async def test_get_markdown_returns_string(self, tool_fn) -> None:
        attachable = _make_attachable_mock(id_="100", file_name="report.pdf")
        client = _make_client_mock(execute_return=attachable)
        ctx = _make_ctx(client)

        with patch("quickbooks_mcp.server.get_client", return_value=client):
            result = await tool_fn(ctx=ctx, operation="get", id="100", response_format="markdown")

        assert isinstance(result, str)
        assert "Attachable" in result

    @pytest.mark.asyncio
    async def test_list_markdown_returns_string(self, tool_fn) -> None:
        raw = [{"Id": "10", "FileName": "a.pdf"}]
        client = _make_client_mock(execute_return=raw)
        ctx = _make_ctx(client)

        with patch("quickbooks_mcp.server.get_client", return_value=client):
            result = await tool_fn(
                ctx=ctx,
                operation="list",
                entity_type="invoice",
                entity_id="147",
                response_format="markdown",
            )

        assert isinstance(result, str)
