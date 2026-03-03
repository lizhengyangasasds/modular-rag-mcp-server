"""MCP Tool: doc_generator

This tool provides documentation generation through the MCP protocol.
It generates API docs, README, and technical documentation.

Usage via MCP:
    Tool name: doc_generator
    Input schema:
        - doc_type (string, optional): Document type (readme, api, guide) (default: readme)
        - output_path (string, optional): Output file path (default: generated to stdout)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional, TYPE_CHECKING

from mcp import types
from src.libs.llm import LLMFactory, BaseLLM

if TYPE_CHECKING:
    from src.mcp_server.protocol_handler import ProtocolHandler
    from src.core.settings import Settings

logger = logging.getLogger(__name__)


TOOL_NAME = "doc_generator"
TOOL_DESCRIPTION = """Automatic documentation generator.

This tool generates various types of documentation:
- README: Project overview and quick start guide
- API: API documentation with endpoints and usage
- Guide: Technical guide with detailed explanations

Parameters:
- doc_type: Type of documentation to generate
- output_path: Optional file path to save the documentation
"""

TOOL_INPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "doc_type": {
            "type": "string",
            "description": "Type of documentation (readme, api, guide).",
            "default": "readme",
            "enum": ["readme", "api", "guide"],
        },
        "output_path": {
            "type": "string",
            "description": "Optional file path to save the documentation.",
        },
    },
}


class DocGeneratorTool:
    """MCP Tool for documentation generation."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self._settings = settings

    @property
    def settings(self) -> Settings:
        if self._settings is None:
            from src.core.settings import load_settings
            self._settings = load_settings()
        return self._settings

    def _get_llm(self) -> BaseLLM:
        """Get LLM instance from factory."""
        return LLMFactory.create(self.settings)

    def generate_doc(
        self,
        doc_type: str = "readme",
        output_path: Optional[str] = None,
    ) -> str:
        """Generate documentation.

        Args:
            doc_type: Type of documentation.
            output_path: Optional path to save the doc.

        Returns:
            Generated documentation content.
        """
        llm = self._get_llm()

        doc_templates = {
            "readme": """为 Modular RAG MCP Server 项目生成 README.md 文档。

要求：
1. 项目徽章（Python版本、许可证等）
2. 项目简介
3. 核心特性
4. 快速开始（安装、配置、使用）
5. 架构说明
6. 配置说明
7. 工具列表
8. 贡献指南
9. 许可证

语言：中文""",

            "api": """为 Modular RAG MCP Server 生成 API 文档。

要求：
1. MCP 协议说明
2. 所有工具的详细说明（参数、返回值、示例）
3. 请求/响应格式
4. 错误处理
5. 使用示例

语言：中文""",

            "guide": """为 Modular RAG MCP Server 生成技术指南。

要求：
1. 整体架构说明
2. 各模块详细介绍
3. 配置指南
4. 部署指南
5. 故障排除
6. 性能优化建议

语言：中文""",
        }

        prompt = doc_templates.get(doc_type, doc_templates["readme"])

        # 添加项目信息
        prompt = f"""{prompt}

## 项目信息

**Modular RAG MCP Server** - 模块化 RAG MCP 服务器

**核心模块**：
- LLM: DeepSeek、OpenAI、Azure、Ollama 支持
- Embedding: 本地 Sentence-BERT + Azure OpenAI
- Vector Store: ChromaDB
- Retrieval: 混合检索（稠密 + 稀疏 + RRF）
- Ingestion: PDF/MD/TXT 处理，图片提取

**MCP 工具**：
1. query_knowledge_hub - 知识库问答
2. list_collections - 列出文档集合
3. get_document_summary - 获取文档摘要
4. ingest_documents - 导入文档
5. auto_coder - 自动编码
6. qa_tester - 自动化测试
7. code_reviewer - 代码审查
8. setup - 项目初始化
9. package - 项目打包
10. deploy - 项目部署
11. resume_writer - 简历写作
12. doc_generator - 文档生成
"""

        result = llm.generate(prompt)

        # Save to file if output_path provided
        if output_path:
            try:
                Path(output_path).write_text(result, encoding="utf-8")
                return f"文档已保存到: {output_path}\n\n{result}"
            except Exception as e:
                return f"保存文件失败: {e}\n\n{result}"

        return result

    async def execute(
        self,
        doc_type: str = "readme",
        output_path: Optional[str] = None,
    ) -> types.CallToolResult:
        """Execute the doc_generator tool."""
        import asyncio

        logger.info(f"Executing doc_generator (type={doc_type})")

        try:
            result = await asyncio.to_thread(
                self.generate_doc, doc_type, output_path,
            )

            response_text = f"## 文档生成完成\n\n{result}"

            return types.CallToolResult(
                content=[types.TextContent(type="text", text=response_text)],
                isError=False,
            )

        except Exception as e:
            logger.exception("Error executing doc_generator")
            return types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text",
                        text=f"文档生成失败: {str(e)}",
                    )
                ],
                isError=True,
            )


def register_tool(protocol_handler: ProtocolHandler) -> None:
    """Register the doc_generator tool."""
    tool = DocGeneratorTool()

    async def handler(
        doc_type: str = "readme",
        output_path: Optional[str] = None,
    ) -> types.CallToolResult:
        return await tool.execute(doc_type=doc_type, output_path=output_path)

    protocol_handler.register_tool(
        name=TOOL_NAME,
        description=TOOL_DESCRIPTION,
        input_schema=TOOL_INPUT_SCHEMA,
        handler=handler,
    )
    logger.info(f"Registered MCP tool: {TOOL_NAME}")
