"""The MCP server lists all eleven tools with their schemas and runs them, in memory."""

import asyncio
import json
import subprocess
import sys

from codeatlas.agent.mcp_server import build_server
from codeatlas.agent.tools import TOOL_NAMES, ToolSet

from .support import SNAP


async def _with_client(tools, action):
    from mcp.client import Client

    async with Client(build_server(tools)) as client:
        return await action(client)


def run(tools, action):
    return asyncio.run(_with_client(tools, action))


def test_lists_all_eleven_tools_with_the_agents_schemas(store):
    tools = ToolSet(store, SNAP)

    async def action(client):
        return (await client.list_tools()).tools

    listed = run(tools, action)
    assert [t.name for t in listed] == list(TOOL_NAMES) and len(listed) == 11
    by_name = {s.name: s for s in tools.specs}
    for tool in listed:
        assert tool.description == by_name[tool.name].description
        assert tool.input_schema == by_name[tool.name].parameters


def test_call_tool_returns_the_same_json_as_the_agent_sees(store):
    tools = ToolSet(store, SNAP)

    async def action(client):
        ok = await client.call_tool("find_callers", {"key": "app/repo.py::Repo.save"})
        bad = await client.call_tool("find_callers", {"key": "nope"})
        return ok, bad

    ok, bad = run(tools, action)
    assert json.loads(ok.content[0].text) == tools.call("find_callers",
                                                        {"key": "app/repo.py::Repo.save"})
    assert not ok.is_error and bad.is_error


def test_cli_reports_a_missing_store_clearly(tmp_path):
    done = subprocess.run([sys.executable, "-m", "codeatlas.agent", "mcp", "--db",
                           str(tmp_path / "missing.sqlite")], capture_output=True, text=True)
    assert done.returncode != 0 and "no store at" in done.stderr
