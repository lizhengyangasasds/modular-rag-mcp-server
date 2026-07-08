"""RAG Response Builder — generates LLM answers from retrieval results.

This module builds generated responses by combining:
- Retrieved document chunks (context)
- A prompt template with {query} and {context} placeholders
- An LLM (via LLMFactory) for generation
- Citation metadata for traceability

The generated answer is wrapped in an MCPToolResponse so it can be
returned through the MCP protocol alongside structured citations.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from src.core.response.citation_generator import Citation, CitationGenerator
from src.core.response.response_builder import MCPToolResponse

if TYPE_CHECKING:
    from src.libs.llm.base_llm import BaseLLM, Message


logger = logging.getLogger(__name__)

DEFAULT_PROMPT_TEMPLATE = """你是一个知识库问答助手。基于以下检索到的相关文档片段，回答用户的问题。

**要求：**
1. 直接回答问题，语言简洁有条理，使用中文
2. 在回答中引用来源时，使用 [n] 格式（如 [1]、[2]）标记
3. 如果检索结果不足以完整回答，明确说明哪些信息缺失
4. 不要编造信息，所有答案必须来自提供的检索片段
5. 如果多个片段都支持同一观点，可以同时引用（如 [1][2]）

---
用户问题：{query}

---
相关文档片段：
{context}

---
你的回答：
"""


class RAGResponseBuilder:
    """Builds generated answers from retrieval results using an LLM.

    This class takes the raw retrieval results from HybridSearch, formats
    them into a context prompt, and sends it to an LLM to produce a
    natural-language answer with inline citation markers.

    The output is an MCPToolResponse so it follows the same protocol as
    the regular (non-generated) response path.

    Example:
        >>> from src.libs.llm import LLMFactory
        >>> from src.core.settings import load_settings
        >>> llm = LLMFactory.create(load_settings())
        >>> builder = RAGResponseBuilder(llm=llm)
        >>> results = hybrid_search.search("梯度消失怎么办", top_k=5)
        >>> response = builder.build("梯度消失怎么办", results)
        >>> print(response.content)   # LLM-generated answer with [1][2] markers
    """

    def __init__(
        self,
        llm: BaseLLM,
        prompt_template: str | None = None,
        citation_generator: CitationGenerator | None = None,
        max_context_chunks: int = 10,
        chunk_max_chars: int = 1500,
    ) -> None:
        """Initialize RAGResponseBuilder.

        Args:
            llm: LLM client instance (e.g. from LLMFactory.create()).
            prompt_template: Prompt template string with {query} and {context}
                placeholders. If None, uses the built-in default.
            citation_generator: Optional CitationGenerator. If None, creates one.
            max_context_chunks: Maximum chunks to include in context (default: 10).
            chunk_max_chars: Maximum characters per chunk in context (default: 1500).
        """
        self.llm = llm
        self.prompt_template = prompt_template or DEFAULT_PROMPT_TEMPLATE
        self.citation_generator = citation_generator or CitationGenerator()
        self.max_context_chunks = max_context_chunks
        self.chunk_max_chars = chunk_max_chars

    def build(
        self,
        query: str,
        results: list[Any],
    ) -> MCPToolResponse:
        """Build a generated response from retrieval results.

        Args:
            query: The original user query string.
            results: List of RetrievalResult from HybridSearch.

        Returns:
            MCPToolResponse containing the LLM-generated answer,
            structured citations, and metadata.
        """
        # Handle empty results
        if not results:
            return self._build_empty_response(query)

        # Generate citations for all results
        citations = self.citation_generator.generate(results)

        # Build context from retrieval chunks
        context = self._build_context(results, citations)

        # Format prompt with query and context
        prompt = self.prompt_template.format(query=query, context=context)

        # Call LLM
        try:
            generated_text = self._call_llm(prompt)
        except Exception as e:
            logger.exception(f"RAG LLM call failed: {e}")
            return self._build_llm_error_response(query, str(e), citations)

        # Build metadata
        metadata = {
            "query": query,
            "result_count": len(results),
            "generation_model": getattr(self.llm, "_model", "unknown"),
            "generated": True,
        }

        return MCPToolResponse(
            content=generated_text,
            citations=citations,
            metadata=metadata,
            is_empty=False,
        )

    def _build_context(
        self,
        results: list[Any],
        citations: list[Citation],
    ) -> str:
        """Build context string from retrieval results with inline markers.

        Each chunk is formatted as:
            [n] "chunk text excerpt..." (来源: source_path, p.页码)

        Args:
            results: List of RetrievalResult.
            citations: Corresponding Citation objects.

        Returns:
            Formatted context string for the prompt.
        """
        lines: list[str] = []
        display_chunks = min(len(results), self.max_context_chunks)

        for i in range(display_chunks):
            result = results[i]
            citation = citations[i] if i < len(citations) else None
            marker = f"[{i + 1}]" if citation else f"[{i + 1}]"

            # Truncate chunk text
            text = getattr(result, "text", "") or ""
            if len(text) > self.chunk_max_chars:
                text = text[: self.chunk_max_chars].rsplit(" ", 1)[0] + "..."

            # Build source info
            source_parts = []
            if citation and citation.source:
                source_parts.append(f"来源: {citation.source}")
            if citation and citation.page is not None:
                source_parts.append(f"p.{citation.page}")

            source_info = f" ({', '.join(source_parts)})" if source_parts else ""

            lines.append(f"{marker} \"{text}\"{source_info}")

        return "\n\n".join(lines)

    def _call_llm(self, prompt: str) -> str:
        """Call the LLM with the formatted prompt.

        Args:
            prompt: Full prompt string with query and context.

        Returns:
            LLM-generated text content.
        """
        from src.libs.llm.base_llm import Message

        messages: list[Message] = [Message(role="user", content=prompt)]
        response = self.llm.chat(messages)
        return response.content

    def _build_empty_response(self, query: str) -> MCPToolResponse:
        """Build response when no retrieval results are available.

        Args:
            query: Original user query.

        Returns:
            MCPToolResponse indicating no results.
        """
        content = "## 无法回答\n\n"
        content += f"查询: **{query}**\n\n"
        content += "检索结果为空，无法基于知识库生成回答。\n\n"
        content += "**建议:**\n"
        content += "- 检查知识库中是否已摄取相关文档\n"
        content += "- 尝试使用不同的关键词进行检索\n"
        content += "- 扩大搜索范围（不指定 collection）\n"

        return MCPToolResponse(
            content=content,
            citations=[],
            metadata={"query": query, "generated": True, "result_count": 0},
            is_empty=True,
        )

    def _build_llm_error_response(
        self,
        query: str,
        error_message: str,
        citations: list[Citation],
    ) -> MCPToolResponse:
        """Build response when LLM generation fails.

        Args:
            query: Original user query.
            error_message: Error description.
            citations: Citations from retrieval results.

        Returns:
            MCPToolResponse indicating generation failure.
        """
        content = "## 生成失败\n\n"
        content += f"查询: **{query}**\n\n"
        content += "检索成功，但 LLM 生成回答时出现错误。\n\n"
        content += f"**错误信息:** {error_message}\n\n"
        content += "**建议:**\n"
        content += "- 检查 LLM API 配置是否正确（API Key、endpoint）\n"
        content += "- 确认网络连接正常\n"
        content += "- 可以使用 query_knowledge_hub 工具获取原始检索结果\n"

        return MCPToolResponse(
            content=content,
            citations=citations,
            metadata={
                "query": query,
                "generated": True,
                "error": error_message,
            },
            is_empty=True,
        )


def create_rag_response_builder(
    settings: Any | None = None,
) -> RAGResponseBuilder:
    """Factory function to create a RAGResponseBuilder with default LLM.

    Args:
        settings: Application settings. If None, loaded from default path.

    Returns:
        Configured RAGResponseBuilder instance.
    """
    from src.libs.llm import LLMFactory

    if settings is None:
        from src.core.settings import load_settings

        settings = load_settings()

    llm = LLMFactory.create(settings)

    return RAGResponseBuilder(llm=llm)
