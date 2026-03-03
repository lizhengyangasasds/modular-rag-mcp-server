"""MCP Tool: qa_tester

This tool provides automated testing capabilities through the MCP protocol.
It generates test cases, runs tests, and generates test reports.

Usage via MCP:
    Tool name: qa_tester
    Input schema:
        - task (string, required): Description of what needs to be tested
        - test_framework (string, optional): Testing framework (default: pytest)
        - code (string, optional): Code to be tested
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


TOOL_NAME = "qa_tester"
TOOL_DESCRIPTION = """Professional automated testing assistant.

This tool helps you write comprehensive test cases, run tests, and generate
test reports. It supports multiple testing frameworks and follows testing best practices.

Parameters:
- task: Description of what needs to be tested
- test_framework: Testing framework (pytest, unittest, jest, etc.)
- code: Optional code to be tested
"""

TOOL_INPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "task": {
            "type": "string",
            "description": "Description of what needs to be tested.",
        },
        "test_framework": {
            "type": "string",
            "description": "Testing framework to use.",
            "default": "pytest",
        },
        "code": {
            "type": "string",
            "description": "Optional code to be tested.",
        },
    },
    "required": ["task"],
}


class QATesterTool:
    """MCP Tool for automated testing."""

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

    def generate_tests(
        self,
        task: str,
        test_framework: str = "pytest",
        code: Optional[str] = None,
    ) -> str:
        """Generate test cases based on task description.

        Args:
            task: Testing task description.
            test_framework: Target testing framework.
            code: Optional code to test.

        Returns:
            Generated test code with explanation.
        """
        llm = self._get_llm()

        code_section = ""
        if code:
            code_section = f"\n## 待测试代码\n```{test_framework.split('-')[0]}\n{code}\n```\n"

        prompt = f"""你是 qa-tester，一个专业的自动化测试工程师。

## 测试任务
{task}
{code_section}

## 测试框架
{test_framework}

## 要求
1. 编写全面的测试用例，覆盖正常情况、边界情况和异常情况
2. 使用测试框架的最佳实践
3. 确保测试的可维护性和可读性
4. 提供测试运行方法和预期结果
5. 生成测试报告模板

## 输出格式
请按以下格式输出：

### 测试代码
```{test_framework.split('-')[0]}
# 测试代码
```

### 运行方法
测试运行命令和步骤

### 预期结果
测试应该验证的内容
"""
        return llm.generate(prompt)

    async def execute(
        self,
        task: str,
        test_framework: str = "pytest",
        code: Optional[str] = None,
    ) -> types.CallToolResult:
        """Execute the qa_tester tool."""
        import asyncio

        logger.info(f"Executing qa_tester (framework={test_framework})")

        try:
            result = await asyncio.to_thread(
                self.generate_tests, task, test_framework, code,
            )

            response_text = f"## 测试用例生成完成\n\n{result}"

            return types.CallToolResult(
                content=[types.TextContent(type="text", text=response_text)],
                isError=False,
            )

        except Exception as e:
            logger.exception("Error executing qa_tester")
            return types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text",
                        text=f"测试生成失败: {str(e)}",
                    )
                ],
                isError=True,
            )


def register_tool(protocol_handler: ProtocolHandler) -> None:
    """Register the qa_tester tool."""
    tool = QATesterTool()

    async def handler(
        task: str,
        test_framework: str = "pytest",
        code: Optional[str] = None,
    ) -> types.CallToolResult:
        return await tool.execute(task=task, test_framework=test_framework, code=code)

    protocol_handler.register_tool(
        name=TOOL_NAME,
        description=TOOL_DESCRIPTION,
        input_schema=TOOL_INPUT_SCHEMA,
        handler=handler,
    )
    logger.info(f"Registered MCP tool: {TOOL_NAME}")
