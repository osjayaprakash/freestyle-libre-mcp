"""Run the real entry point as a subprocess: proves nothing but MCP frames reach stdout."""

import sys

from mcp import Client, StdioServerParameters

ENV = {
    "LIBRELINKUP_EMAIL": "nobody@example.com",
    "LIBRELINKUP_PASSWORD": "unused",
    "PATH": "",
}


async def test_stdio_server_starts_and_lists_tools():
    params = StdioServerParameters(command=sys.executable, args=["-m", "librelinkup_mcp"], env=ENV)
    async with Client(params) as client:
        tools = await client.list_tools()
    assert {t.name for t in tools.tools} == {
        "list_patients",
        "get_current_glucose",
        "get_glucose_graph",
        "get_glucose_logbook",
    }
