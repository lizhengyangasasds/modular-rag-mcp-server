"""Tests for the resync_document MCP tool.

Verifies the delete-then-ingest verification logic on a single document.
Heavy storage backends (ChromaDB / BM25 / ImageStorage / FileIntegrity)
are mocked to keep tests fast and offline.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.mcp_server.tools.resync_document import (
    TOOL_INPUT_SCHEMA,
    TOOL_NAME,
    ResyncDocumentTool,
)

# ── Helpers ───────────────────────────────────────────────────────────────


def _make_tool() -> ResyncDocumentTool:
    """Build a tool without triggering settings load."""
    tool = ResyncDocumentTool.__new__(ResyncDocumentTool)
    tool._settings = MagicMock()
    return tool


def _make_pipeline_result(success: bool = True, error: str | None = None) -> Any:
    pr = MagicMock()
    pr.success = success
    pr.error = error
    return pr


# ── Constants ─────────────────────────────────────────────────────────────


def test_tool_constants_present() -> None:
    assert TOOL_NAME == "resync_document"
    assert "source_path" in TOOL_INPUT_SCHEMA["required"]


# ── Failure modes ─────────────────────────────────────────────────────────


def test_missing_file_returns_error(tmp_path: Path) -> None:
    tool = _make_tool()
    missing = tmp_path / "no_such.pdf"

    result = tool.resync_document(source_path=str(missing))

    assert result.error is not None
    assert "not found" in result.error.lower()
    assert result.fully_refreshed is False
    assert result.chunks_after == 0


# ── Unchanged file: short-circuit ─────────────────────────────────────────


def test_unchanged_file_skips_reingest(tmp_path: Path) -> None:
    pdf = tmp_path / "handbook.pdf"
    pdf.write_text("same content")
    tool = _make_tool()

    fake_integrity = MagicMock()
    fake_integrity.compute_sha256.return_value = "samehash"
    fake_integrity.db_path = ":memory:"  # unused because we patch lookup

    pipeline_mock = MagicMock()
    pipeline_mock.run.return_value = _make_pipeline_result(success=True)

    with (
        patch(
            "src.libs.loader.file_integrity.SQLiteIntegrityChecker",
            return_value=fake_integrity,
            create=True,
        ),
        patch(
            "src.ingestion.document_manager.DocumentManager",
            create=True,
        ) as doc_mgr_cls,
        patch(
            "src.ingestion.pipeline.IngestionPipeline",
            return_value=pipeline_mock,
            create=True,
        ),
        patch.object(
            ResyncDocumentTool, "_lookup_old_hash", return_value="samehash"
        ),
    ):
        result = tool.resync_document(source_path=str(pdf))

    assert result.file_changed is False
    assert result.fully_refreshed is True
    # No deletion or re-ingest should have been attempted.
    doc_mgr_cls.assert_not_called()
    pipeline_mock.run.assert_not_called()


# ── Changed file: delete + ingest + verify ────────────────────────────────


def test_changed_file_deletes_old_then_reingests(tmp_path: Path) -> None:
    pdf = tmp_path / "handbook.pdf"
    pdf.write_text("v2 content")
    tool = _make_tool()

    fake_integrity = MagicMock()
    fake_integrity.compute_sha256.return_value = "newhash"
    fake_integrity.db_path = ":memory:"

    del_result = MagicMock()
    del_result.chunks_deleted = 42
    del_result.bm25_removed = 42
    del_result.images_deleted = 3
    del_result.success = True
    del_result.errors = []

    fake_doc_mgr = MagicMock()
    fake_doc_mgr.delete_document.return_value = del_result
    # First count (before) → 42; second count (after) → 38
    fake_doc_mgr._count_chunks.side_effect = [42, 38]
    fake_doc_mgr._count_images.return_value = 3
    fake_doc_mgr.close.return_value = None

    pipeline_mock = MagicMock()
    pipeline_mock.run.return_value = _make_pipeline_result(success=True)

    with (
        patch(
            "src.libs.loader.file_integrity.SQLiteIntegrityChecker",
            return_value=fake_integrity,
            create=True,
        ),
        patch(
            "src.ingestion.document_manager.DocumentManager",
            return_value=fake_doc_mgr,
            create=True,
        ),
        patch(
            "src.ingestion.pipeline.IngestionPipeline",
            return_value=pipeline_mock,
            create=True,
        ),
        patch.object(
            ResyncDocumentTool, "_lookup_old_hash", return_value="oldhash"
        ),
        patch.object(
            ResyncDocumentTool, "_count_bm25", return_value=42
        ),
    ):
        result = tool.resync_document(source_path=str(pdf))

    assert result.file_changed is True
    assert result.old_hash == "oldhash"
    assert result.new_hash == "newhash"
    assert result.chunks_before == 42
    assert result.chunks_deleted == 42
    assert result.chunks_after == 38
    assert result.fully_refreshed is True
    fake_doc_mgr.delete_document.assert_called_once()
    pipeline_mock.run.assert_called_once_with(str(pdf))


# ── Partial delete: warning emitted ───────────────────────────────────────


def test_partial_delete_emits_warning(tmp_path: Path) -> None:
    pdf = tmp_path / "handbook.pdf"
    pdf.write_text("v3 content")
    tool = _make_tool()

    fake_integrity = MagicMock()
    fake_integrity.compute_sha256.return_value = "newhash"
    fake_integrity.db_path = ":memory:"

    del_result = MagicMock()
    del_result.chunks_deleted = 10  # expected 42 → only 10 removed
    del_result.bm25_removed = 0
    del_result.images_deleted = 0
    del_result.success = True
    del_result.errors = []

    fake_doc_mgr = MagicMock()
    fake_doc_mgr.delete_document.return_value = del_result
    fake_doc_mgr._count_chunks.side_effect = [42, 12]
    fake_doc_mgr._count_images.return_value = 0
    fake_doc_mgr.close.return_value = None

    pipeline_mock = MagicMock()
    pipeline_mock.run.return_value = _make_pipeline_result(success=True)

    with (
        patch(
            "src.libs.loader.file_integrity.SQLiteIntegrityChecker",
            return_value=fake_integrity,
            create=True,
        ),
        patch(
            "src.ingestion.document_manager.DocumentManager",
            return_value=fake_doc_mgr,
            create=True,
        ),
        patch(
            "src.ingestion.pipeline.IngestionPipeline",
            return_value=pipeline_mock,
            create=True,
        ),
        patch.object(
            ResyncDocumentTool, "_lookup_old_hash", return_value="oldhash"
        ),
        patch.object(ResyncDocumentTool, "_count_bm25", return_value=0),
    ):
        result = tool.resync_document(source_path=str(pdf))

    assert result.fully_refreshed is False
    assert any("orphan" in w.lower() or "only" in w.lower() for w in result.warnings)


# ── first-time ingest path ────────────────────────────────────────────────


def test_first_time_ingest_no_old_hash(tmp_path: Path) -> None:
    pdf = tmp_path / "new.pdf"
    pdf.write_text("first content")
    tool = _make_tool()

    fake_integrity = MagicMock()
    fake_integrity.compute_sha256.return_value = "newhash"
    fake_integrity.db_path = ":memory:"

    fake_doc_mgr = MagicMock()
    fake_doc_mgr._count_chunks.return_value = 5
    fake_doc_mgr.close.return_value = None

    pipeline_mock = MagicMock()
    pipeline_mock.run.return_value = _make_pipeline_result(success=True)

    with (
        patch(
            "src.libs.loader.file_integrity.SQLiteIntegrityChecker",
            return_value=fake_integrity,
            create=True,
        ),
        patch(
            "src.ingestion.document_manager.DocumentManager",
            return_value=fake_doc_mgr,
            create=True,
        ),
        patch(
            "src.ingestion.pipeline.IngestionPipeline",
            return_value=pipeline_mock,
            create=True,
        ),
        patch.object(ResyncDocumentTool, "_lookup_old_hash", return_value=None),
    ):
        result = tool.resync_document(source_path=str(pdf))

    assert result.file_changed is True  # We don't know if it changed
    assert result.old_hash is None
    assert result.chunks_before == 0
    assert result.chunks_after == 5
    assert result.fully_refreshed is True
    fake_doc_mgr.delete_document.assert_not_called()


# ── ingest pipeline failure surfaces error ────────────────────────────────


def test_pipeline_failure_returns_error(tmp_path: Path) -> None:
    pdf = tmp_path / "bad.pdf"
    pdf.write_text("content")
    tool = _make_tool()

    fake_integrity = MagicMock()
    fake_integrity.compute_sha256.return_value = "newhash"
    fake_integrity.db_path = ":memory:"

    fake_doc_mgr = MagicMock()
    fake_doc_mgr.delete_document.return_value = MagicMock(
        chunks_deleted=0, bm25_removed=0, images_deleted=0,
        success=True, errors=[],
    )
    fake_doc_mgr._count_chunks.return_value = 0
    fake_doc_mgr.close.return_value = None

    pipeline_mock = MagicMock()
    pipeline_mock.run.return_value = _make_pipeline_result(success=False, error="boom")

    with (
        patch(
            "src.libs.loader.file_integrity.SQLiteIntegrityChecker",
            return_value=fake_integrity,
            create=True,
        ),
        patch(
            "src.ingestion.document_manager.DocumentManager",
            return_value=fake_doc_mgr,
            create=True,
        ),
        patch(
            "src.ingestion.pipeline.IngestionPipeline",
            return_value=pipeline_mock,
            create=True,
        ),
        patch.object(
            ResyncDocumentTool, "_lookup_old_hash", return_value="oldhash"
        ),
        patch.object(ResyncDocumentTool, "_count_bm25", return_value=0),
    ):
        result = tool.resync_document(source_path=str(pdf))

    assert result.error == "boom"
    assert result.fully_refreshed is False


# ── _lookup_old_hash directly ─────────────────────────────────────────────


def test_lookup_old_hash_returns_none_on_missing_db(tmp_path: Path) -> None:
    """Smoke test the private helper: missing DB connection → None."""
    tool = _make_tool()
    fake_integrity = MagicMock()
    fake_integrity.db_path = "/nonexistent/path/db.sqlite"

    fake_holder: dict[str, str] = {}  # ensure no path attribute leaks

    value = tool._lookup_old_hash(fake_integrity, tmp_path / "x.pdf")

    assert value is None
    # safety net so pytest doesn't collect as unused
    assert fake_holder == {}  # noqa: S101 — explicit assertion


# ── format_response strings ───────────────────────────────────────────────


def test_format_response_unchanged(tmp_path: Path) -> None:
    tool = _make_tool()
    res = tool.resync_document(source_path=str(tmp_path / "x.pdf"))  # missing
    assert "失败" in tool.format_response(res) or "错误" in tool.format_response(res)


def test_format_response_success_contains_diff(tmp_path: Path) -> None:
    pdf = tmp_path / "x.pdf"
    pdf.write_text("content")
    tool = _make_tool()

    fake_integrity = MagicMock()
    fake_integrity.compute_sha256.return_value = "newhash"
    fake_integrity.db_path = ":memory:"

    del_result = MagicMock(
        chunks_deleted=10, bm25_removed=10, images_deleted=0,
        success=True, errors=[],
    )
    fake_doc_mgr = MagicMock()
    fake_doc_mgr.delete_document.return_value = del_result
    fake_doc_mgr._count_chunks.side_effect = [10, 12]
    fake_doc_mgr._count_images.return_value = 0
    fake_doc_mgr.close.return_value = None

    pipeline_mock = MagicMock()
    pipeline_mock.run.return_value = _make_pipeline_result(success=True)

    with (
        patch(
            "src.libs.loader.file_integrity.SQLiteIntegrityChecker",
            return_value=fake_integrity,
            create=True,
        ),
        patch(
            "src.ingestion.document_manager.DocumentManager",
            return_value=fake_doc_mgr,
            create=True,
        ),
        patch(
            "src.ingestion.pipeline.IngestionPipeline",
            return_value=pipeline_mock,
            create=True,
        ),
        patch.object(ResyncDocumentTool, "_lookup_old_hash", return_value="oldhash"),
        patch.object(ResyncDocumentTool, "_count_bm25", return_value=10),
    ):
        result = tool.resync_document(source_path=str(pdf))

    text = tool.format_response(result)
    assert "Chunks 变化" in text
    assert "删除前旧 chunks" in text
    assert "新增 chunks" in text


@pytest.mark.parametrize(
    "flag,expected_in_response",
    [
        (True, "全部 chunks 已刷新完成"),
        (False, "存在遗留 chunks"),
    ],
)
def test_format_response_refresh_flag(
    tmp_path: Path, flag: bool, expected_in_response: str
) -> None:
    tool = _make_tool()
    res = MagicMock()
    res.error = None
    res.source_path = "x.pdf"
    res.collection = "knowledge_hub"
    res.old_hash = "oldhash" if flag else "oldhash"
    res.new_hash = "newhash"
    res.chunks_before = 10
    res.chunks_deleted = 10 if flag else 5
    res.chunks_after = 12
    res.bm25_before = 0
    res.bm25_deleted = 0
    res.images_before = 0
    res.images_deleted = 0
    res.fully_refreshed = flag
    res.file_changed = True
    res.warnings = []

    text = tool.format_response(res)
    assert expected_in_response in text
