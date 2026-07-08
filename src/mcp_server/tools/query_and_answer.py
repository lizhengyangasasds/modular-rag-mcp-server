"""MCP Tool: query_and_answer

This tool provides RAG-style question answering through the MCP protocol.
It combines HybridSearch (Dense + Sparse + RRF Fusion) with a LLM-powered
response generator to produce natural-language answers with inline citations.

Unlike query_knowledge_hub (which returns raw retrieval results),
this tool sends the retrieved chunks to DeepSeek to generate a complete,
well-structured answer with [n] citation markers.

Usage via MCP:
    Tool name: query_and_answer
    Input schema:
        - query (string, required): The question to answer
        - top_k (integer, optional): Number of retrieval results to use (default: 5)
        - collection (string, optional): Limit search to specific collection
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from mcp import types

from src.core.response.rag_response_builder import (
    MCPToolResponse,
    RAGResponseBuilder,
    create_rag_response_builder,
)
from src.core.settings import Settings
from src.core.trace import TraceCollector, TraceContext
from src.core.types import RetrievalResult

if TYPE_CHECKING:
    from src.core.query_engine.hybrid_search import HybridSearch

logger = logging.getLogger(__name__)


# Tool metadata
TOOL_NAME = "query_and_answer"
TOOL_DESCRIPTION = """Answer questions using RAG (Retrieval Augmented Generation).

This tool combines hybrid search with an LLM to generate comprehensive,
well-structured answers with inline citations [1], [2], etc. Unlike
query_knowledge_hub which returns raw retrieval results, this tool
generates a natural-language answer based on the retrieved documents.

Parameters:
- query: Your question (required)
- top_k: Number of retrieval results to use as context (default: 5)
- collection: Optional collection name to limit search scope
"""
TOOL_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "The question to answer using retrieval-augmented generation.",
        },
        "top_k": {
            "type": "integer",
            "description": "Number of retrieval results to use as context for generation.",
            "default": 5,
            "minimum": 1,
            "maximum": 20,
        },
        "collection": {
            "type": "string",
            "description": "Optional collection name to limit the search scope.",
        },
    },
    "required": ["query"],
}


class QueryAndAnswerTool:
    """MCP Tool for RAG-style question answering.

    This class orchestrates the complete RAG pipeline:
    1. Retrieve relevant chunks via HybridSearch (reused from QueryKnowledgeHubTool)
    2. Optionally rerank results
    3. Generate answer via LLM using RAGResponseBuilder

    Design Principles:
    - Reuse HybridSearch from QueryKnowledgeHubTool to avoid duplication
    - Lazy initialization: LLM and search components created on first use
    - Error resilience: Falls back to retrieval-only results if generation fails

    Example:
        >>> tool = QueryAndAnswerTool()
        >>> result = await tool.execute(query="梯度消失怎么办", top_k=5)
        >>> print(result.content)   # LLM-generated answer with citations
    """

    def __init__(
        self,
        settings: Settings | None = None,
        hybrid_search: HybridSearch | None = None,
        rag_builder: RAGResponseBuilder | None = None,
        enable_rerank: bool = True,
        default_collection: str = "knowledge_hub",
    ) -> None:
        """Initialize QueryAndAnswerTool.

        Args:
            settings: Application settings. If None, loaded from default path.
            hybrid_search: Pre-configured HybridSearch instance. If None,
                reuses the one from QueryKnowledgeHubTool.
            rag_builder: Pre-configured RAGResponseBuilder. If None, creates one.
            enable_rerank: Whether to apply reranking before generation.
            default_collection: Default collection name.
        """
        self._settings = settings
        self._hybrid_search = hybrid_search
        self._rag_builder = rag_builder
        self._enable_rerank = enable_rerank
        self._default_collection = default_collection
        self._initialized = False
        self._current_collection: str | None = None

    @property
    def settings(self) -> Settings:
        """Get settings, loading if necessary."""
        if self._settings is None:
            from src.core.settings import load_settings

            self._settings = load_settings()
        return self._settings

    def _ensure_initialized(self, collection: str) -> None:
        """Ensure HybridSearch and RAG builder are initialized for the collection.

        Args:
            collection: Target collection name.
        """
        if self._current_collection == collection and self._initialized:
            return

        # Reuse HybridSearch from QueryKnowledgeHubTool to avoid duplication
        if self._hybrid_search is None:
            from src.mcp_server.tools.query_knowledge_hub import get_tool_instance

            query_tool = get_tool_instance(self.settings)
            # Trigger initialization by calling ensure_initialized
            query_tool._ensure_initialized(collection)
            self._hybrid_search = query_tool.hybrid_search

        # Create RAG builder if not provided
        if self._rag_builder is None:
            self._rag_builder = create_rag_response_builder(self.settings)

        self._current_collection = collection
        self._initialized = True
        logger.info(
            f"QueryAndAnswerTool initialized for collection: {collection}"
        )

    async def execute(
        self,
        query: str,
        top_k: int = 5,
        collection: str | None = None,
    ) -> MCPToolResponse:
        """Execute RAG question answering.

        Args:
            query: Question to answer.
            top_k: Number of retrieval results to use.
            collection: Optional collection name.

        Returns:
            MCPToolResponse with LLM-generated answer and citations.

        Raises:
            ValueError: If query is empty or invalid.
        """
        # Validate query
        if not query or not query.strip():
            raise ValueError("Query cannot be empty")

        effective_top_k = min(max(top_k, 1), 20)
        effective_collection = collection or self._default_collection

        logger.info(
            f"Executing query_and_answer: query='{query[:50]}...', "
            f"top_k={effective_top_k}, collection={effective_collection}"
        )

        trace = TraceContext(trace_type="rag_query")
        trace.metadata["query"] = query[:200]
        trace.metadata["top_k"] = effective_top_k
        trace.metadata["collection"] = effective_collection
        trace.metadata["source"] = "mcp"

        try:
            # Ensure components are initialized (reuses QueryKnowledgeHubTool's HybridSearch)
            import asyncio

            await asyncio.to_thread(self._ensure_initialized, effective_collection)

            # Perform hybrid search
            results = await asyncio.to_thread(
                self._perform_search, query, effective_top_k, trace,
            )

            # Apply reranking if enabled
            if self._enable_rerank and results:
                from src.core.query_engine.reranker import create_core_reranker

                reranker = create_core_reranker(settings=self.settings)
                if reranker.is_enabled:
                    try:
                        rerank_result = reranker.rerank(
                            query=query,
                            results=results,
                            top_k=effective_top_k,
                            trace=trace,
                        )
                        results = rerank_result.results
                    except Exception as e:
                        logger.warning(f"Reranking failed, using original order: {e}")

            # Build generated response
            if not results:
                response = self._rag_builder._build_empty_response(query)
            else:
                response = self._rag_builder.build(query=query, results=results)

            # Store results in trace
            trace.metadata["final_results"] = [
                {
                    "chunk_id": r.chunk_id,
                    "score": round(r.score, 4),
                    "text": r.text or "",
                    "source": r.metadata.get("source_path", r.metadata.get("source", "")),
                }
                for r in results
            ]
            trace.metadata["generated"] = response.metadata.get("generated", False)

            logger.info(
                f"query_and_answer completed: {len(results)} results, "
                f"generated={not response.is_empty or response.metadata.get('generated')}"
            )

            TraceCollector().collect(trace)
            return response

        except Exception as e:
            logger.exception(f"query_and_answer failed: {e}")
            TraceCollector().collect(trace)
            return self._build_error_response(query, effective_collection, str(e))

    def _perform_search(
        self,
        query: str,
        top_k: int,
        trace: Any | None = None,
    ) -> list[RetrievalResult]:
        """Perform hybrid search using the reused HybridSearch instance.

        Args:
            query: Search query.
            top_k: Maximum results.
            trace: Optional TraceContext.

        Returns:
            List of RetrievalResult.
        """
        if self._hybrid_search is None:
            raise RuntimeError("HybridSearch not initialized")

        try:
            results = self._hybrid_search.search(
                query=query,
                top_k=top_k * 2 if self._enable_rerank else top_k,
                filters=None,
                trace=trace,
                return_details=False,
            )
            return results if isinstance(results, list) else results.results
        except Exception as e:
            logger.warning(f"Hybrid search failed: {e}")
            return []

    def _build_error_response(
        self,
        query: str,
        collection: str,
        error_message: str,
    ) -> MCPToolResponse:
        """Build error response.

        Args:
            query: Original query.
            collection: Target collection.
            error_message: Error description.

        Returns:
            MCPToolResponse indicating error.
        """
        content = "## 问答失败\n\n"
        content += f"查询: **{query}**\n"
        content += f"集合: `{collection}`\n\n"
        content += f"**错误信息:** {error_message}\n\n"
        content += "请检查:\n"
        content += "- LLM API 配置是否正确\n"
        content += "- 知识库是否已包含相关文档\n"
        content += "- 网络连接是否正常\n"

        return MCPToolResponse(
            content=content,
            citations=[],
            metadata={
                "query": query,
                "collection": collection,
                "error": error_message,
                "generated": True,
            },
            is_empty=True,
        )


# Module-level tool instance (lazy-initialized)
_tool_instance: QueryAndAnswerTool | None = None


def get_tool_instance(settings: Settings | None = None) -> QueryAndAnswerTool:
    """Get or create the tool instance.

    Args:
        settings: Optional settings to use for initialization.

    Returns:
        QueryAndAnswerTool instance.
    """
    global _tool_instance
    if _tool_instance is None:
        _tool_instance = QueryAndAnswerTool(settings=settings)
    return _tool_instance


async def query_and_answer_handler(
    query: str,
    top_k: int = 5,
    collection: str | None = None,
) -> types.CallToolResult:
    """Handler function for MCP tool registration.

    This function is registered with the ProtocolHandler and called
    when the MCP client invokes the query_and_answer tool.

    Args:
        query: Question to answer.
        top_k: Number of retrieval results to use.
        collection: Optional collection name.

    Returns:
        MCP CallToolResult with LLM-generated answer and citations.
    """
    tool = get_tool_instance()

    try:
        response = await tool.execute(
            query=query,
            top_k=top_k,
            collection=collection,
        )

        content_blocks = response.to_mcp_content()
        return types.CallToolResult(
            content=content_blocks,
            isError=response.is_empty and "error" in response.metadata,
        )

    except ValueError as e:
        return types.CallToolResult(
            content=[
                types.TextContent(
                    type="text",
                    text=f"参数错误: {e}",
                )
            ],
            isError=True,
        )
    except Exception as e:
        logger.exception(f"query_and_answer handler error: {e}")
        return types.CallToolResult(
            content=[
                types.TextContent(
                    type="text",
                    text="内部错误: 问答生成失败",
                )
            ],
            isError=True,
        )


def register_tool(protocol_handler) -> None:
    """Register query_and_answer tool with the protocol handler.

    Args:
        protocol_handler: ProtocolHandler instance to register with.
    """
    protocol_handler.register_tool(
        name=TOOL_NAME,
        description=TOOL_DESCRIPTION,
        input_schema=TOOL_INPUT_SCHEMA,
        handler=query_and_answer_handler,
    )
    logger.info(f"Registered MCP tool: {TOOL_NAME}")
