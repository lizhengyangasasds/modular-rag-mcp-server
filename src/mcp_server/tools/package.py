"""MCP Tool: package

This tool provides project packaging capabilities through the MCP protocol.
It packages the project for distribution.

Usage via MCP:
    Tool name: package
    Input schema:
        - format (string, optional): Package format (wheel, tarball, docker) (default: wheel)
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional, TYPE_CHECKING

from mcp import types

if TYPE_CHECKING:
    from src.mcp_server.protocol_handler import ProtocolHandler
    from src.core.settings import Settings

logger = logging.getLogger(__name__)


TOOL_NAME = "package"
TOOL_DESCRIPTION = """Package the project for distribution.

This tool:
- Cleans temporary files and caches
- Builds distribution packages
- Creates wheel/sdist artifacts
- Generates requirements.txt

Parameters:
- format: Package format (wheel, tarball, docker)
"""

TOOL_INPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "format": {
            "type": "string",
            "description": "Package format (wheel, tarball, docker).",
            "default": "wheel",
        },
    },
}


class PackageTool:
    """MCP Tool for project packaging."""

    def run_package(self, format: str = "wheel") -> str:
        """Run the packaging process.

        Args:
            format: Package format.

        Returns:
            Package result message.
        """
        steps = []
        errors = []

        # Step 1: Clean
        try:
            dirs_to_clean = ["build", "dist", "__pycache__"]
            for pattern in ["**/*.pyc", "**/__pycache__", "**/*.egg-info", "**/.pytest_cache"]:
                for p in Path(".").rglob(pattern):
                    try:
                        if p.is_file():
                            p.unlink()
                        elif p.is_dir():
                            shutil.rmtree(p, ignore_errors=True)
                    except Exception:
                        pass
            steps.append("清理临时文件完成")
        except Exception as e:
            errors.append(f"清理失败: {e}")

        # Step 2: Build
        if format in ("wheel", "tarball"):
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "build", "--outdir", "dist"],
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
                if result.returncode == 0:
                    steps.append(f"{format} 包构建成功")
                    # List created files
                    dist_dir = Path("dist")
                    if dist_dir.exists():
                        files = list(dist_dir.glob("*"))
                        steps.append(f"生成文件: {', '.join([f.name for f in files])}")
                else:
                    errors.append(f"构建失败: {result.stderr[:200]}")
            except FileNotFoundError:
                errors.append("build 包未安装，运行: pip install build")
            except subprocess.TimeoutExpired:
                errors.append("构建超时")
            except Exception as e:
                errors.append(f"构建失败: {e}")

        elif format == "docker":
            try:
                result = subprocess.run(
                    ["docker", "build", "-t", "modular-rag-mcp-server", "."],
                    capture_output=True,
                    text=True,
                    timeout=600,
                )
                if result.returncode == 0:
                    steps.append("Docker 镜像构建成功: modular-rag-mcp-server")
                else:
                    errors.append(f"Docker 构建失败: {result.stderr[:200]}")
            except FileNotFoundError:
                errors.append("Docker 未安装或不可用")
            except Exception as e:
                errors.append(f"Docker 构建失败: {e}")

        # Step 3: Generate requirements.txt
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "freeze"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode == 0:
                with open("requirements.txt", "w") as f:
                    f.write(result.stdout)
                steps.append("requirements.txt 已生成")
        except Exception as e:
            errors.append(f"生成 requirements.txt 失败: {e}")

        # Build result message
        lines = ["## 项目打包完成"]

        if steps:
            lines.extend(["", "### 已完成"])
            for step in steps:
                lines.append(f"- {step}")

        if errors:
            lines.extend(["", "### 错误"])
            for error in errors:
                lines.append(f"- {error}")

        return "\n".join(lines)

    async def execute(self, format: str = "wheel") -> types.CallToolResult:
        """Execute the package tool."""
        import asyncio

        logger.info(f"Executing package (format={format})")

        try:
            result = await asyncio.to_thread(self.run_package, format)

            return types.CallToolResult(
                content=[types.TextContent(type="text", text=result)],
                isError=False,
            )

        except Exception as e:
            logger.exception("Error executing package")
            return types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text",
                        text=f"打包失败: {str(e)}",
                    )
                ],
                isError=True,
            )


def register_tool(protocol_handler: ProtocolHandler) -> None:
    """Register the package tool."""
    tool = PackageTool()

    async def handler(format: str = "wheel") -> types.CallToolResult:
        return await tool.execute(format=format)

    protocol_handler.register_tool(
        name=TOOL_NAME,
        description=TOOL_DESCRIPTION,
        input_schema=TOOL_INPUT_SCHEMA,
        handler=handler,
    )
    logger.info(f"Registered MCP tool: {TOOL_NAME}")
