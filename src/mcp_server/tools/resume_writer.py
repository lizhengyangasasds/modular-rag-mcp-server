"""MCP Tool: resume_writer

This tool provides resume writing assistance through the MCP protocol.
It generates project experience descriptions for resumes based on project details.

Usage via MCP:
    Tool name: resume_writer
    Input schema:
        - target_position (string, required): Target job position
        - background (string, optional): Personal background and experience
        - project_description (string, optional): Description of the project to highlight
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, TYPE_CHECKING

from mcp import types
from src.libs.llm import LLMFactory, BaseLLM

if TYPE_CHECKING:
    from src.mcp_server.protocol_handler import ProtocolHandler
    from src.core.settings import Settings

logger = logging.getLogger(__name__)


TOOL_NAME = "resume_writer"
TOOL_DESCRIPTION = """Professional resume project experience writer.

This tool generates compelling project experience descriptions for resumes
based on your project details. It follows the STAR method and highlights
technical achievements with quantifiable results.

Parameters:
- target_position: Job position you're applying for
- background: Your personal background and experience
- project_description: Description of the project to highlight
"""

TOOL_INPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "target_position": {
            "type": "string",
            "description": "Target job position for the resume.",
        },
        "background": {
            "type": "string",
            "description": "Personal background and experience summary.",
        },
        "project_description": {
            "type": "string",
            "description": "Description of the project to write about.",
        },
    },
    "required": ["target_position"],
}


class ResumeWriterTool:
    """MCP Tool for resume writing."""

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

    def generate_resume(
        self,
        target_position: str,
        background: Optional[str] = None,
        project_description: Optional[str] = None,
    ) -> str:
        """Generate resume content.

        Args:
            target_position: Target job position.
            background: Personal background.
            project_description: Project description.

        Returns:
            Generated resume content.
        """
        llm = self._get_llm()

        prompt = f"""你是 resume_writer，一个专业的简历写作专家。

## 目标岗位
{target_position}

## 个人背景
{background or "未提供"}

## 项目描述
{project_description or "未提供，请基于 Modular RAG MCP Server 项目生成项目经历"}

## 要求
请严格遵循以下原则：

1. **采用四段式结构**: 背景 → 目标 → 过程 → 结果
2. **每条 bullet 用动词开头**
3. **包含技术细节**
4. **量化效果**（使用具体数字）
5. **突出与岗位相关的技能和经验**
6. **语言专业、简洁、有说服力**

## 输出格式

### 项目名称（英文）
项目描述，使用 STAR 方法组织：

- **背景**: 项目背景和团队环境
- **技术栈**: 使用的核心技术
- **贡献**: 具体工作内容
- **成果**: 量化的成果和影响

---
"""

        # 如果没有提供项目描述，使用默认的 Modular RAG MCP Server 项目
        if not project_description:
            prompt += """

### 参考项目信息（Modular RAG MCP Server）

这是一个模块化的 RAG（检索增强生成）MCP 服务器，包含以下特点：

**技术亮点**：
- 模块化架构，支持多种 LLM 提供商（DeepSeek、OpenAI、Azure、Ollama）
- 混合检索：稠密向量 + 稀疏向量 + RRF 融合
- 本地向量化：使用 Sentence-BERT 模型，不上传文档
- 向量数据库：ChromaDB 本地存储
- 可观测性：完整的追踪和日志系统
- 文档处理：支持 PDF、Markdown、TXT，支持图片提取和描述
- LLM 增强：文档摘要、元数据丰富、块优化

**技术栈**：Python, LangChain, ChromaDB, Sentence-Transformers, DeepSeek API

请基于上述项目信息，为目标岗位生成专业的项目经历描述。
"""

        return llm.generate(prompt)

    async def execute(
        self,
        target_position: str,
        background: Optional[str] = None,
        project_description: Optional[str] = None,
    ) -> types.CallToolResult:
        """Execute the resume_writer tool."""
        import asyncio

        logger.info(f"Executing resume_writer (position={target_position})")

        try:
            result = await asyncio.to_thread(
                self.generate_resume, target_position, background, project_description,
            )

            response_text = f"## 简历项目经历生成完成\n\n{result}"

            return types.CallToolResult(
                content=[types.TextContent(type="text", text=response_text)],
                isError=False,
            )

        except Exception as e:
            logger.exception("Error executing resume_writer")
            return types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text",
                        text=f"简历生成失败: {str(e)}",
                    )
                ],
                isError=True,
            )


def register_tool(protocol_handler: ProtocolHandler) -> None:
    """Register the resume_writer tool."""
    tool = ResumeWriterTool()

    async def handler(
        target_position: str,
        background: Optional[str] = None,
        project_description: Optional[str] = None,
    ) -> types.CallToolResult:
        return await tool.execute(
            target_position=target_position,
            background=background,
            project_description=project_description,
        )

    protocol_handler.register_tool(
        name=TOOL_NAME,
        description=TOOL_DESCRIPTION,
        input_schema=TOOL_INPUT_SCHEMA,
        handler=handler,
    )
    logger.info(f"Registered MCP tool: {TOOL_NAME}")
