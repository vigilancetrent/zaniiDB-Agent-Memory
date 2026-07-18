import pytest

from zanii_memory.mcp_server import create_mcp_server, format_conversation_hits, format_memory_hits

EXPECTED_TOOLS = {"memory_search", "conversation_search", "save_memory", "get_persona"}


async def test_tools_registered(cfg):
    server = create_mcp_server(cfg)
    tools = await server.list_tools()
    assert {t.name for t in tools} == EXPECTED_TOOLS
    for tool in tools:
        assert tool.description  # every tool documents itself


async def test_save_then_search_roundtrip(cfg):
    server = create_mcp_server(cfg)
    result = await server.call_tool(
        "save_memory",
        {"content": "The user requires the AI to write commit messages in English", "type": "instruction"},
    )
    assert "saved" in str(result).lower()

    result = await server.call_tool("save_memory", {"content": "   "})
    assert "skipped" in str(result).lower()

    result = await server.call_tool("memory_search", {"query": "commit messages english"})
    assert "commit messages" in str(result)

    result = await server.call_tool("get_persona", {})
    assert "No persona" in str(result)

    result = await server.call_tool("conversation_search", {"query": "anything"})
    assert "No conversations" in str(result)


def test_formatters_empty():
    assert format_memory_hits([]) == "No memories found."
    assert format_conversation_hits([]) == "No conversations found."
