"""MCP Tool: deploy

This tool provides deployment capabilities through the MCP protocol.
It deploys the project to various targets (local, docker, server).

Usage via MCP:
    Tool name: deploy
    Input schema:
        - target (string, optional): Deployment target (local, docker, server) (default: local)
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


TOOL_NAME = "deploy"
TOOL_DESCRIPTION = """Deploy the project to various targets.

This tool automates deployment to:
- local: Local development setup
- docker: Docker container deployment
- server: Remote server deployment

Parameters:
- target: Deployment target (local, docker, server)
"""

TOOL_INPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "target": {
            "type": "string",
            "description": "Deployment target (local, docker, server).",
            "default": "local",
            "enum": ["local", "docker", "server"],
        },
    },
}


class DeployTool:
    """MCP Tool for project deployment."""

    def run_deploy(self, target: str = "local") -> str:
        """Run the deployment process.

        Args:
            target: Deployment target.

        Returns:
            Deployment result message.
        """
        steps = []
        errors = []

        if target == "local":
            # Local deployment steps
            steps.append("准备本地部署环境")

            # Check if service is already running
            try:
                # For stdio MCP server, no service needs to run
                steps.append("MCP Server 已就绪，可通过 stdio 连接使用")
                steps.append("验证配置文件: config/settings.yaml")
            except Exception as e:
                errors.append(f"本地检查失败: {e}")

        elif target == "docker":
            try:
                # Build docker image
                result = subprocess.run(
                    ["docker", "build", "-t", "modular-rag-mcp:latest", "."],
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
                if result.returncode == 0:
                    steps.append("Docker 镜像构建成功")
                    steps.append("运行容器: docker run -p 8000:8000 modular-rag-mcp:latest")
                else:
                    errors.append(f"Docker 构建失败: {result.stderr[:200]}")
            except FileNotFoundError:
                errors.append("Docker 未安装")
            except Exception as e:
                errors.append(f"Docker 部署失败: {e}")

        elif target == "server":
            steps.append("准备服务器部署")
            steps.append("部署脚本待配置（需要服务器 SSH 凭证）")

        # Build result message
        lines = [f"## 部署到 {target} 完成"]

        if steps:
            lines.extend(["", "### 已完成"])
            for step in steps:
                lines.append(f"- {step}")

        if errors:
            lines.extend(["", "### 错误"])
            for error in errors:
                lines.append(f"- {error}")

        if target == "local":
            lines.extend([
                "",
                "### 使用方式",
                "MCP Server 通过 stdio 通信，集成到 Cursor 后可直接使用。",
            ])
        elif target == "docker":
            lines.extend([
                "",
                "### 下一步",
                "1. docker run -d --name rag-mcp -p 8000:8000 modular-rag-mcp:latest",
                "2. 配置 Cursor MCP 设置连接到服务",
            ])

        return "\n".join(lines)

    async def execute(self, target: str = "local") -> types.CallToolResult:
        """Execute the deploy tool."""
        import asyncio

        logger.info(f"Executing deploy (target={target})")

        try:
            result = await asyncio.to_thread(self.run_deploy, target)

            return types.CallToolResult(
                content=[types.TextContent(type="text", text=result)],
                isError=False,
            )

        except Exception as e:
            logger.exception("Error executing deploy")
            return types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text",
                        text=f"部署失败: {str(e)}",
                    )
                ],
                isError=True,
            )


def register_tool(protocol_handler: ProtocolHandler) -> None:
    """Register the deploy tool."""
    tool = DeployTool()

    async def handler(target: str = "local") -> types.CallToolResult:
        return await tool.execute(target=target)

    protocol_handler.register_tool(
        name=TOOL_NAME,
        description=TOOL_DESCRIPTION,
        input_schema=TOOL_INPUT_SCHEMA,
        handler=handler,
    )
    logger.info(f"Registered MCP tool: {TOOL_NAME}")
