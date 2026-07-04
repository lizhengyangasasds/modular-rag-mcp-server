"""MCP Tool: resync_document

Re-ingest a single document after its content has changed, with full
verification that every old chunk is replaced by fresh ones.

Unlike ``ingest_documents --force``, which only bypasses the integrity
check and appends new chunks alongside stale ones, this tool performs an
explicit delete-then-ingest cycle against all storage backends (ChromaDB,
BM25, ImageStorage, FileIntegrity) and returns a structured diff so the
caller can confirm the document is fully refreshed.

Typical flow when employee_handbook.pdf is updated::

    resync_document(
        source_path="data/employee_handbook.pdf",
        collection="knowledge_hub",
    )

    -> {
        "file_changed": True,
        "old_hash": "abc123...",
        "new_hash": "def456...",
        "chunks_before": 42,
        "chunks_deleted": 42,
        "chunks_after": 38,
        "fully_refreshed": True,
        "warnings": []
    }

Usage via MCP::

    Tool name: resync_document
    Input schema:
        - source_path (string, required): Path to the document file
        - collection (string, optional): Target collection (default: knowledge_hub)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mcp import types

if TYPE_CHECKING:
    from src.core.settings import Settings
    from src.mcp_server.protocol_handler import ProtocolHandler

logger = logging.getLogger(__name__)


TOOL_NAME = "resync_document"
TOOL_DESCRIPTION = """Re-ingest a single document after its content has changed, with full verification.

Workflow:
1. Compute the new SHA-256 of the file on disk.
2. Look up the old hash from the ingestion history (FileIntegrity).
3. If the file is unchanged, return immediately with ``file_changed=False``.
4. Delete every old chunk from ChromaDB + BM25 + ImageStorage keyed by the old hash.
5. Re-ingest the file to produce fresh chunks under the new hash.
6. Verify: old hash should now have 0 chunks; new hash should have > 0 chunks.

Returns a structured diff (chunks_before / chunks_deleted / chunks_after /
fully_refreshed) so the caller can confirm the document is fully refreshed.

Use this whenever a document has been modified on disk and you want to make
sure every old chunk has been replaced — not just appended to.

Parameters:
- source_path: Absolute or workspace-relative path to the document.
- collection: Target collection name (default: knowledge_hub)
"""

TOOL_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "source_path": {
            "type": "string",
            "description": "Path to the document file on disk.",
        },
        "collection": {
            "type": "string",
            "description": "Target collection name.",
            "default": "knowledge_hub",
        },
    },
    "required": ["source_path"],
}


@dataclass
class ResyncResult:
    """Outcome of a resync_document operation."""

    source_path: str = ""
    file_changed: bool = False
    old_hash: str | None = None
    new_hash: str | None = None
    collection: str = "knowledge_hub"
    chunks_before: int = 0
    chunks_deleted: int = 0
    chunks_after: int = 0
    bm25_before: int = 0
    bm25_deleted: int = 0
    images_before: int = 0
    images_deleted: int = 0
    fully_refreshed: bool = False
    error: str | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "file_changed": self.file_changed,
            "old_hash": self.old_hash,
            "new_hash": self.new_hash,
            "collection": self.collection,
            "chunks_before": self.chunks_before,
            "chunks_deleted": self.chunks_deleted,
            "chunks_after": self.chunks_after,
            "bm25_before": self.bm25_before,
            "bm25_deleted": self.bm25_deleted,
            "images_before": self.images_before,
            "images_deleted": self.images_deleted,
            "fully_refreshed": self.fully_refreshed,
            "error": self.error,
            "warnings": self.warnings,
        }


class ResyncDocumentTool:
    """MCP Tool for re-ingesting a single document with verification."""

    def __init__(
        self,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings

    @property
    def settings(self) -> Settings:
        if self._settings is None:
            from src.core.settings import load_settings
            self._settings = load_settings()
        return self._settings

    def resync_document(
        self,
        source_path: str,
        collection: str = "knowledge_hub",
    ) -> ResyncResult:
        """Delete old chunks then re-ingest ``source_path`` and verify counts.

        Args:
            source_path: Path to the document on disk.
            collection: Target collection name.

        Returns:
            ResyncResult with before/after counts and ``fully_refreshed`` flag.
        """
        from src.ingestion.pipeline import IngestionPipeline
        from src.libs.loader.file_integrity import SQLiteIntegrityChecker

        result = ResyncResult(source_path=source_path, collection=collection)
        path = Path(source_path).resolve()

        if not path.exists():
            result.error = f"File not found: {source_path}"
            return result

        try:
            integrity = SQLiteIntegrityChecker()
        except Exception as e:  # pragma: no cover - depends on env
            result.error = f"Cannot open FileIntegrity DB: {e}"
            return result

        new_hash = integrity.compute_sha256(str(path))
        result.new_hash = new_hash

        # Look up old hash from ingestion history (by path).
        old_hash = self._lookup_old_hash(integrity, path)

        # If we know the old hash, snapshot counts before mutation.
        if old_hash is not None:
            result.old_hash = old_hash
            result.file_changed = old_hash != new_hash

            if not result.file_changed:
                # Nothing to do — file is unchanged.
                result.fully_refreshed = True
                return result

            try:
                doc_mgr = self._build_document_manager()
            except Exception as e:
                result.error = f"Cannot build DocumentManager: {e}"
                return result

            result.chunks_before = doc_mgr._count_chunks(old_hash)
            result.bm25_before = self._count_bm25(old_hash)
            result.images_before = doc_mgr._count_images(old_hash)

            try:
                del_res = doc_mgr.delete_document(
                    source_path=str(path),
                    collection=collection,
                    source_hash=old_hash,
                )
            except Exception as e:
                result.error = f"Delete failed: {e}"
                return result

            result.chunks_deleted = del_res.chunks_deleted
            result.bm25_deleted = del_res.bm25_removed
            result.images_deleted = del_res.images_deleted
            result.warnings.extend(del_res.errors)

            if not del_res.success:
                result.warnings.append("Delete reported partial failure; proceeding with re-ingest")

            doc_mgr.close()
        else:
            # No prior history — treat as "changed" (first-time indexing).
            # No deletion needed; the pipeline ingest below handles it.
            result.file_changed = True

        # Re-ingest the (possibly unchanged-but-no-record) file with force=True.
        try:
            pipeline = IngestionPipeline(
                settings=self.settings,
                collection=collection,
                force=True,
            )
        except Exception as e:
            result.error = f"Cannot build IngestionPipeline: {e}"
            return result

        try:
            pipe_result = pipeline.run(str(path))
        finally:
            pipeline.close()

        if not pipe_result.success:
            result.error = pipe_result.error or "Re-ingest pipeline failed"
            return result

        # Verify the new chunks landed under the new hash.
        try:
            doc_mgr = self._build_document_manager()
            result.chunks_after = doc_mgr._count_chunks(new_hash)
            doc_mgr.close()
        except Exception as e:
            result.warnings.append(f"Post-ingest verification failed: {e}")

        # Fully refreshed iff:
        # - old hash exists AND new hash has chunks AND
        #   (no prior record → no deletion needed) OR (prior chunks all deleted)
        if old_hash is None:
            # First-time ingest, nothing to delete.
            result.fully_refreshed = result.chunks_after > 0
        else:
            result.fully_refreshed = (
                result.chunks_after > 0 and result.chunks_deleted >= result.chunks_before
            )
            if result.chunks_deleted < result.chunks_before:
                result.warnings.append(
                    f"Only {result.chunks_deleted}/{result.chunks_before} "
                    f"old chunks were deleted — possible orphan chunks remain"
                )

        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _lookup_old_hash(self, integrity: Any, path: Path) -> str | None:
        """Find the hash of a previously ingested document by its filesystem path."""
        try:
            db_path = integrity.db_path if hasattr(integrity, "db_path") else None
            if db_path is None:
                return None
            import sqlite3

            with sqlite3.connect(str(db_path)) as conn:
                row = conn.execute(
                    "SELECT file_hash FROM ingestion_history WHERE file_path = ? "
                    "ORDER BY last_processed DESC LIMIT 1",
                    (str(path),),
                ).fetchone()
                return row[0] if row else None
        except Exception as e:
            logger.debug("Could not look up old hash for %s: %s", path, e)
            return None

    def _build_document_manager(self) -> Any:
        from src.ingestion.document_manager import DocumentManager

        return DocumentManager(settings=self.settings)

    def _count_bm25(self, source_hash: str) -> int:
        """Count BM25 postings for ``source_hash``. Returns 0 if BM25 unavailable."""
        try:
            from src.libs.storage.bm25_indexer import BM25Indexer

            idx = BM25Indexer()
            return sum(
                1 for doc_id in idx._doc_metadata.keys()  # noqa: SLF001
                if source_hash in str(doc_id)
            )
        except Exception as e:
            logger.debug("BM25 count failed for %s: %s", source_hash, e)
            return 0

    def format_response(self, result: ResyncResult) -> str:
        """Format resync result as human-readable text."""
        if result.error:
            return f"## 文档重同步失败\n\n**错误:** {result.error}"

        lines = ["## 文档重同步完成", ""]

        if not result.file_changed:
            lines.extend([
                f"**文档路径:** {result.source_path}",
                f"**集合:** {result.collection}",
                f"**文件 hash:** `{result.new_hash[:16]}...`",
                "",
                "**结论:** 文件未变化，无需重同步。",
            ])
            return "\n".join(lines)

        lines.extend([
            f"**文档路径:** {result.source_path}",
            f"**集合:** {result.collection}",
            f"**旧 hash:** `{result.old_hash[:16]}...`" if result.old_hash else "**旧 hash:** (无历史记录)",
            f"**新 hash:** `{result.new_hash[:16]}...`",
            "",
            "### Chunks 变化",
            f"- 删除前旧 chunks: **{result.chunks_before}**",
            f"- 实际删除 chunks: **{result.chunks_deleted}**",
            f"- 新增 chunks: **{result.chunks_after}**",
            "",
            "### 其他存储",
            f"- BM25 删除: **{result.bm25_deleted}** (之前 {result.bm25_before})",
            f"- Images 删除: **{result.images_deleted}** (之前 {result.images_before})",
            "",
        ])

        if result.fully_refreshed:
            lines.append("**✅ 全部 chunks 已刷新完成**")
        else:
            lines.append("**⚠️ 存在遗留 chunks 或新 chunks 异常，请检查 warnings**")

        if result.warnings:
            lines.extend(["", "### 警告"])
            for w in result.warnings:
                lines.append(f"- {w}")

        return "\n".join(lines)

    async def execute(
        self,
        source_path: str,
        collection: str = "knowledge_hub",
    ) -> types.CallToolResult:
        """Execute the resync_document tool via MCP."""
        logger.info(
            "Executing resync_document (path=%s, collection=%s)",
            source_path,
            collection,
        )
        try:
            result = await asyncio.to_thread(
                self.resync_document, source_path, collection,
            )
            response_text = self.format_response(result)
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=response_text)],
                isError=result.error is not None,
            )
        except Exception as e:
            logger.exception("Error executing resync_document")
            return types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text",
                        text=f"重同步失败: {str(e)}",
                    )
                ],
                isError=True,
            )


def register_tool(protocol_handler: ProtocolHandler) -> None:
    """Register the resync_document tool."""
    tool = ResyncDocumentTool()

    async def handler(
        source_path: str,
        collection: str = "knowledge_hub",
    ) -> types.CallToolResult:
        return await tool.execute(source_path=source_path, collection=collection)

    protocol_handler.register_tool(
        name=TOOL_NAME,
        description=TOOL_DESCRIPTION,
        input_schema=TOOL_INPUT_SCHEMA,
        handler=handler,
    )
    logger.info(f"Registered MCP tool: {TOOL_NAME}")
