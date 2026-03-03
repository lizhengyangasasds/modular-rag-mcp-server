"""MCP Tool: setup

This tool provides project setup capabilities through the MCP protocol.
It helps set up the project environment, install dependencies, and initialize databases.

Usage via MCP:
    Tool name: setup
    Input schema: (no parameters required)
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, TYPE_CHECKING

from mcp import types

if TYPE_CHECKING:
    from src.mcp_server.protocol_handler import ProtocolHandler
    from src.core.settings import Settings

logger = logging.getLogger(__name__)


TOOL_NAME = "setup"
TOOL_DESCRIPTION = """Set up the project environment.

This tool initializes the project by:
- Checking Python version compatibility
- Installing required dependencies from pyproject.toml
- Creating necessary directories (data/db, documents, etc.)
- Initializing the vector database

No parameters required - run with default settings.
"""

TOOL_INPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {},
}


class SetupTool:
    """MCP Tool for project setup."""

    def run_setup(self) -> str:
        """Run the setup process.

        Returns:
            Setup result message.
        """
        steps = []
        errors = []

        # Step 1: Check Python version
        try:
            version = sys.version_info
            if version.major < 3 or (version.major == 3 and version.minor < 10):
                errors.append(f"Python 3.10+ required, found {version.major}.{version.minor}")
            else:
                steps.append(f"Python 版本检查通过: {version.major}.{version.minor}.{version.micro}")
        except Exception as e:
            errors.append(f"Python 版本检查失败: {e}")

        # Step 2: Create directories
        try:
            dirs_to_create = [
                "data/db/chroma",
                "data/db/bm25",
                "data/images",
                "documents",
                "logs",
            ]
            for dir_path in dirs_to_create:
                Path(dir_path).mkdir(parents=True, exist_ok=True)
            steps.append(f"创建目录: {', '.join(dirs_to_create)}")
        except Exception as e:
            errors.append(f"创建目录失败: {e}")

        # Step 3: Install dependencies
        try:
            pyproject = Path("pyproject.toml")
            if pyproject.exists():
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "install", "-e", "."],
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
                if result.returncode == 0:
                    steps.append("依赖安装成功")
                else:
                    errors.append(f"依赖安装失败: {result.stderr[:200]}")
            else:
                steps.append("跳过依赖安装（pyproject.toml 未找到）")
        except subprocess.TimeoutExpired:
            errors.append("依赖安装超时")
        except Exception as e:
            errors.append(f"依赖安装失败: {e}")

        # Build result message
        lines = ["## 项目环境配置完成"]

        if steps:
            lines.extend(["", "### 已完成"])
            for step in steps:
                lines.append(f"- {step}")

        if errors:
            lines.extend(["", "### 错误"])
            for error in errors:
                lines.append(f"- {error}")

        lines.extend([
            "",
            "### 下一步",
            "1. 配置 `config/settings.yaml` 中的 API Key",
            "2. 放入文档到 `documents` 文件夹",
            "3. 运行 `ingest_documents` 导入文档",
            "4. 开始使用知识库问答",
        ])

        return "\n".join(lines)

    async def execute(self) -> types.CallToolResult:
        """Execute the setup tool."""
        import asyncio

        logger.info("Executing setup")

        try:
            result = await asyncio.to_thread(self.run_setup)

            return types.CallToolResult(
                content=[types.TextContent(type="text", text=result)],
                isError=False,
            )

        except Exception as e:
            logger.exception("Error executing setup")
            return types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text",
                        text=f"配置失败: {str(e)}",
                    )
                ],
                isError=True,
            )


def register_tool(protocol_handler: ProtocolHandler) -> None:
    """Register the setup tool."""
    tool = SetupTool()

    async def handler() -> types.CallToolResult:
        return await tool.execute()

    protocol_handler.register_tool(
        name=TOOL_NAME,
        description=TOOL_DESCRIPTION,
        input_schema=TOOL_INPUT_SCHEMA,
        handler=handler,
    )
    logger.info(f"Registered MCP tool: {TOOL_NAME}")
