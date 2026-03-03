"""MCP Tool: auto_coder

This tool provides automatic code generation capabilities through the MCP protocol.
It uses LLM to generate, refactor, or optimize code based on user requirements.

Usage via MCP:
    Tool name: auto_coder
    Input schema:
        - task (string, required): Detailed description of the coding task
        - language (string, optional): Programming language (default: python)
        - context (string, optional): Additional context or existing code
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


TOOL_NAME = "auto_coder"
TOOL_DESCRIPTION = """Professional code generation and refactoring assistant.

This tool helps you write, modify, refactor, or optimize code in any language.
It follows best practices, handles edge cases, and produces well-documented code.

Parameters:
- task: Detailed description of what you want the code to do
- language: Programming language (python, javascript, typescript, go, rust, etc.)
- context: Optional existing code or additional context
"""

TOOL_INPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "task": {
            "type": "string",
            "description": "Detailed description of the coding task.",
        },
        "language": {
            "type": "string",
            "description": "Programming language for the code.",
            "default": "python",
        },
        "context": {
            "type": "string",
            "description": "Optional existing code or additional context to consider.",
        },
    },
    "required": ["task"],
}


class AutoCoderTool:
    """MCP Tool for automatic code generation."""

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

    def generate_code(
        self,
        task: str,
        language: str = "python",
        context: Optional[str] = None,
    ) -> str:
        """Generate code based on task description.

        Args:
            task: Coding task description.
            language: Target programming language.
            context: Optional existing code context.

        Returns:
            Generated code with explanation.
        """
        llm = self._get_llm()

        context_section = ""
        if context:
            context_section = f"\n## 现有代码上下文\n```\n{context}\n```\n"

        prompt = f"""你是 auto-coder，一个专业的 {language} 工程师。

## 任务
{task}
{context_section}

## 要求
1. 代码要规范、易读、符合语言惯例
2. 处理边界情况和异常
3. 遵循最佳实践和设计模式
4. 添加必要的注释说明关键逻辑
5. 给出代码的使用方法和示例

## 输出格式
请按以下格式输出：

### 代码实现
```python
# 你的代码
```

### 使用说明
简要说明如何使用这段代码

### 注意事项
任何需要注意的边界情况或依赖项
"""
        return llm.generate(prompt)

    async def execute(
        self,
        task: str,
        language: str = "python",
        context: Optional[str] = None,
    ) -> types.CallToolResult:
        """Execute the auto_coder tool."""
        import asyncio

        logger.info(f"Executing auto_coder (language={language})")

        try:
            result = await asyncio.to_thread(
                self.generate_code, task, language, context,
            )

            response_text = f"## 自动编码完成\n\n{result}"

            return types.CallToolResult(
                content=[types.TextContent(type="text", text=response_text)],
                isError=False,
            )

        except Exception as e:
            logger.exception("Error executing auto_coder")
            return types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text",
                        text=f"代码生成失败: {str(e)}",
                    )
                ],
                isError=True,
            )


def register_tool(protocol_handler: ProtocolHandler) -> None:
    """Register the auto_coder tool."""
    tool = AutoCoderTool()

    async def handler(
        task: str,
        language: str = "python",
        context: Optional[str] = None,
    ) -> types.CallToolResult:
        return await tool.execute(task=task, language=language, context=context)

    protocol_handler.register_tool(
        name=TOOL_NAME,
        description=TOOL_DESCRIPTION,
        input_schema=TOOL_INPUT_SCHEMA,
        handler=handler,
    )
    logger.info(f"Registered MCP tool: {TOOL_NAME}")
