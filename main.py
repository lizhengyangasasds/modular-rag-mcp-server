"""
Modular RAG MCP Server - Main Entry Point

This module provides the main entry point for the MCP server.
It uses the official MCP SDK with stdio transport.

Usage:
    python main.py

Or run directly via the module:
    python -m src.mcp_server.server
"""

from src.mcp_server.server import main

if __name__ == "__main__":
    exit(main())
