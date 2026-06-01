"""Smoke test: the server imports and registers its tools."""

import asyncio

from zapi_mcp import server


def test_tools_registered():
    tools = asyncio.run(server.mcp.list_tools())
    names = {t.name for t in tools}
    assert {
        "daily_brief",
        "get_problems",
        "get_hosts",
        "get_host_items",
        "acknowledge_problem",
    } <= names


def test_every_tool_has_description():
    tools = asyncio.run(server.mcp.list_tools())
    for t in tools:
        assert t.description, f"tool {t.name} has no description"
