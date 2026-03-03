"""MCP Tool: ingest_documents

This tool provides document ingestion capabilities through the MCP protocol.
It scans the documents folder and ingests new documents into the knowledge base.

Usage via MCP:
    Tool name: ingest_documents
    Input schema:
        - collection (string, optional): Target collection name (default: knowledge_hub)
        - force (boolean, optional): Force re-ingestion of existing files (default: false)
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from mcp import types

if TYPE_CHECKING:
    from src.mcp_server.protocol_handler import ProtocolHandler
    from src.core.settings import Settings

logger = logging.getLogger(__name__)


TOOL_NAME = "ingest_documents"
TOOL_DESCRIPTION = """Ingest documents from the documents folder into the knowledge base.

This tool processes all documents in the configured documents folder and adds them
to the vector store for future retrieval. It supports incremental ingestion - only
new or modified files are processed.

Parameters:
- collection: Target collection name (default: knowledge_hub)
- force: Re-ingest existing files even if not modified (default: false)

Supported formats: PDF, Markdown, Text files
"""

TOOL_INPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "collection": {
            "type": "string",
            "description": "Target collection name for ingestion.",
            "default": "knowledge_hub",
        },
        "force": {
            "type": "boolean",
            "description": "Force re-ingestion of all files, even if not modified.",
            "default": False,
        },
    },
    "required": [],
}


@dataclass
class IngestDocumentsConfig:
    """Configuration for ingest_documents tool."""
    documents_folder: str = "./documents"
    supported_extensions: tuple = (".pdf", ".md", ".txt", ".markdown")


class IngestResult:
    """Result of document ingestion."""
    def __init__(
        self,
        total_files: int = 0,
        ingested: int = 0,
        skipped: int = 0,
        failed: int = 0,
        errors: Optional[List[str]] = None
    ):
        self.total_files = total_files
        self.ingested = ingested
        self.skipped = skipped
        self.failed = failed
        self.errors = errors or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_files": self.total_files,
            "ingested": self.ingested,
            "skipped": self.skipped,
            "failed": self.failed,
            "errors": self.errors
        }


class IngestDocumentsTool:
    """MCP Tool for document ingestion."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        config: Optional[IngestDocumentsConfig] = None,
    ) -> None:
        self._settings = settings
        self._config = config

    @property
    def settings(self) -> Settings:
        if self._settings is None:
            from src.core.settings import load_settings
            self._settings = load_settings()
        return self._settings

    @property
    def config(self) -> IngestDocumentsConfig:
        if self._config is None:
            self._config = IngestDocumentsConfig()
        return self._config

    def _scan_documents(self, folder: Path) -> List[Path]:
        """Scan folder for supported documents."""
        if not folder.exists():
            return []

        documents = []
        for ext in self.config.supported_extensions:
            documents.extend(folder.glob(f"**/*{ext}"))
        return sorted(set(documents))

    def ingest_documents(
        self,
        collection: str = "knowledge_hub",
        force: bool = False,
    ) -> IngestResult:
        """Ingest documents from the documents folder.

        Args:
            collection: Target collection name.
            force: Force re-ingestion of all files.

        Returns:
            IngestResult with ingestion statistics.
        """
        from src.ingestion.pipeline import IngestionPipeline

        result = IngestResult()
        docs_folder = Path(self.config.documents_folder)

        # Scan for documents
        files = self._scan_documents(docs_folder)
        result.total_files = len(files)

        if not files:
            return result

        # Process each file
        pipeline = IngestionPipeline(
            settings=self.settings,
            collection=collection,
            force=force,
        )

        try:
            for file_path in files:
                try:
                    logger.info(f"Processing: {file_path}")
                    pipeline_result = pipeline.run(str(file_path))

                    if pipeline_result.success:
                        if pipeline_result.stages.get("integrity", {}).get("skipped"):
                            result.skipped += 1
                        else:
                            result.ingested += 1
                    else:
                        result.failed += 1
                        result.errors.append(f"{file_path.name}: {pipeline_result.error}")

                except Exception as e:
                    logger.error(f"Failed to process {file_path}: {e}")
                    result.failed += 1
                    result.errors.append(f"{file_path.name}: {str(e)}")

        finally:
            pipeline.close()

        return result

    def format_response(self, result: IngestResult) -> str:
        """Format ingestion result as readable string."""
        lines = [
            "## 文档导入完成",
            "",
            f"**总计文件:** {result.total_files}",
            f"**成功导入:** {result.ingested}",
            f"**跳过(未修改):** {result.skipped}",
            f"**失败:** {result.failed}",
        ]

        if result.errors:
            lines.extend(["", "### 错误详情"])
            for error in result.errors:
                lines.append(f"- {error}")

        lines.extend([
            "",
            "### 提示",
            "- 已导入的文档可以直接使用 `query_knowledge_hub` 检索",
            "- 如需重新导入，请设置 `force: true`",
        ])

        return "\n".join(lines)

    async def execute(
        self,
        collection: str = "knowledge_hub",
        force: bool = False,
    ) -> types.CallToolResult:
        """Execute the ingest_documents tool."""
        logger.info(f"Executing ingest_documents (collection={collection}, force={force})")

        try:
            result = await asyncio.to_thread(
                self.ingest_documents, collection, force,
            )
            response_text = self.format_response(result)

            return types.CallToolResult(
                content=[types.TextContent(type="text", text=response_text)],
                isError=False,
            )

        except Exception as e:
            logger.exception("Error executing ingest_documents")
            return types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text",
                        text=f"导入失败: {str(e)}",
                    )
                ],
                isError=True,
            )


def register_tool(protocol_handler: ProtocolHandler) -> None:
    """Register the ingest_documents tool."""
    tool = IngestDocumentsTool()

    async def handler(
        collection: str = "knowledge_hub",
        force: bool = False,
    ) -> types.CallToolResult:
        return await tool.execute(collection=collection, force=force)

    protocol_handler.register_tool(
        name=TOOL_NAME,
        description=TOOL_DESCRIPTION,
        input_schema=TOOL_INPUT_SCHEMA,
        handler=handler,
    )
    logger.info(f"Registered MCP tool: {TOOL_NAME}")
