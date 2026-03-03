"""MCP Tool: code_reviewer

This tool provides code review capabilities through the MCP protocol.
It analyzes code for issues, suggests improvements, and provides best practices.

Usage via MCP:
    Tool name: code_reviewer
    Input schema:
        - code (string, required): Code to be reviewed
        - language (string, optional): Programming language (default: python)
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


TOOL_NAME = "code_reviewer"
TOOL_DESCRIPTION = """Professional code review assistant.

This tool reviews your code for correctness, performance, security, and best practices.
It provides actionable suggestions and explains the reasoning behind each recommendation.

Parameters:
- code: Code to be reviewed
- language: Programming language (python, javascript, go, rust, etc.)
"""

TOOL_INPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "code": {
            "type": "string",
            "description": "Code to be reviewed.",
        },
        "language": {
            "type": "string",
            "description": "Programming language of the code.",
            "default": "python",
        },
    },
    "required": ["code"],
}


class CodeReviewerTool:
    """MCP Tool for code review."""

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

    def review_code(
        self,
        code: str,
        language: str = "python",
    ) -> str:
        """Review code and provide suggestions.

        Args:
            code: Code to review.
            language: Programming language.

        Returns:
            Review report with suggestions.
        """
        llm = self._get_llm()

        prompt = f"""你是 code_reviewer，一个资深的 {language} 代码审查专家。

## 待审查代码
```{language}
{code}
```

## 审查维度
请从以下几个方面审查代码：

1. **代码正确性**: 逻辑是否正确，是否有潜在的bug
2. **性能优化**: 是否有性能瓶颈或可优化的地方
3. **安全风险**: 是否有安全隐患（注入、XSS等）
4. **代码规范**: 命名、格式、注释是否符合最佳实践
5. **可维护性**: 代码结构、模块化、依赖管理
6. **最佳实践**: 是否符合语言/框架的推荐做法

## 输出格式
请按以下格式输出：

### 总体评分
简要说明代码的整体质量（优秀/良好/需要改进）

### 问题列表
按严重程度列出发现的问题：
- **[严重]** 问题描述及修复建议
- **[中等]** 问题描述及修复建议
- **[建议]** 问题描述及修复建议

### 优化建议
可以进一步改进的地方（可选）

### 亮点
代码中做得好的地方（可选）
"""
        return llm.generate(prompt)

    async def execute(
        self,
        code: str,
        language: str = "python",
    ) -> types.CallToolResult:
        """Execute the code_reviewer tool."""
        import asyncio

        logger.info(f"Executing code_reviewer (language={language})")

        try:
            result = await asyncio.to_thread(
                self.review_code, code, language,
            )

            response_text = f"## 代码审查完成\n\n{result}"

            return types.CallToolResult(
                content=[types.TextContent(type="text", text=response_text)],
                isError=False,
            )

        except Exception as e:
            logger.exception("Error executing code_reviewer")
            return types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text",
                        text=f"代码审查失败: {str(e)}",
                    )
                ],
                isError=True,
            )


def register_tool(protocol_handler: ProtocolHandler) -> None:
    """Register the code_reviewer tool."""
    tool = CodeReviewerTool()

    async def handler(
        code: str,
        language: str = "python",
    ) -> types.CallToolResult:
        return await tool.execute(code=code, language=language)

    protocol_handler.register_tool(
        name=TOOL_NAME,
        description=TOOL_DESCRIPTION,
        input_schema=TOOL_INPUT_SCHEMA,
        handler=handler,
    )
    logger.info(f"Registered MCP tool: {TOOL_NAME}")
