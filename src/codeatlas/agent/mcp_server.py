"""Serve the graph tools over MCP (stdio), with the same names and schemas as the agent."""

from __future__ import annotations

import json
from typing import Any

import mcp_types as types
from mcp.server import Server

from codeatlas.agent.tools import ToolSet


def build_server(tools: ToolSet) -> Server[Any]:
    """An MCP server whose tool list is exactly `tools.specs`."""

    async def on_list_tools(ctx: Any, params: Any) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[
            types.Tool(name=s.name, description=s.description, input_schema=s.parameters)
            for s in tools.specs
        ])

    async def on_call_tool(ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
        result = tools.call(params.name, dict(params.arguments or {}))
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False))],
            is_error="error" in result,
        )

    return Server("codeatlas", on_list_tools=on_list_tools, on_call_tool=on_call_tool)


async def serve_stdio(tools: ToolSet) -> None:
    """Run until the client disconnects. Nothing but protocol may be written to stdout."""
    from mcp.server.stdio import stdio_server

    server = build_server(tools)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())
