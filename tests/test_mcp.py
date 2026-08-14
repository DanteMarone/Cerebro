"""Tests for MCP layer, Stdio transport, wire naming, and CompositeToolExecutor (§10.1 & §10.3)."""

import sys
import pytest

from cerebro.models import Agent
from cerebro.mcp import (
    MCPServerConfig,
    StdioMCPClient,
    MCPRegistry,
    CompositeToolExecutor,
    MCPClientError,
)
from cerebro.tools import CoreTools


@pytest.fixture
def jarvis(tmp_path):
    return Agent(id="jarvis", name="jarvis", provider="lmstudio",
                 home_path=str(tmp_path / "jarvis"))


def test_npx_and_uvx_downloads_are_rejected(tmp_path):
    """Slice 4 requirement: dynamic remote tool download commands are forbidden."""
    client = StdioMCPClient(
        MCPServerConfig(
            name="test_server",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem", str(tmp_path)],
        )
    )
    with pytest.raises(MCPClientError, match="forbidden"):
        import asyncio
        asyncio.run(client.start())


def test_uvx_downloads_are_rejected():
    client = StdioMCPClient(
        MCPServerConfig(
            name="test_server",
            command="uvx",
            args=["mcp-server-git"],
        )
    )
    with pytest.raises(MCPClientError, match="forbidden"):
        import asyncio
        asyncio.run(client.start())


@pytest.mark.asyncio
async def test_stdio_mcp_mock_server_roundtrip(tmp_path):
    """Verify stdio JSON-RPC handshake, wire naming (server__tool), and tool execution."""
    mock_server_script = tmp_path / "mock_server.py"
    mock_server_script.write_text(r"""
import sys, json

while True:
    line = sys.stdin.readline()
    if not line:
        break
    req = json.loads(line.strip())
    method = req.get("method")
    req_id = req.get("id")

    if method == "initialize":
        res = {"protocolVersion": "2024-11-05", "capabilities": {}, "serverInfo": {"name": "mock"}}
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": req_id, "result": res}) + "\n")
        sys.stdout.flush()
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        res = {
            "tools": [
                {
                    "name": "echo",
                    "description": "Echo input text",
                    "inputSchema": {"type": "object", "properties": {"msg": {"type": "string"}}}
                }
            ]
        }
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": req_id, "result": res}) + "\n")
        sys.stdout.flush()
    elif method == "tools/call":
        args = req.get("params", {}).get("arguments", {})
        res = {"content": [{"type": "text", "text": f"echoed: {args.get('msg')}"}]}
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": req_id, "result": res}) + "\n")
        sys.stdout.flush()
""", encoding="utf-8")

    client = StdioMCPClient(
        MCPServerConfig(
            name="mock_svc",
            command=sys.executable,
            args=[str(mock_server_script)],
        )
    )

    try:
        await client.start()
        specs = client.get_specs()
        assert len(specs) == 1
        # Check wire naming: server__tool
        assert specs[0].name == "mock_svc__echo"
        assert specs[0].description == "Echo input text"

        result = await client.call_tool("mock_svc__echo", {"msg": "hello from test"})
        assert "echoed: hello from test" in result
    finally:
        await client.stop()


@pytest.mark.asyncio
async def test_mcp_crash_is_fail_closed_and_does_not_crash_cerebro(tmp_path):
    """Process crash in an MCP tool returns an error string, protecting Cerebro."""
    crashing_script = tmp_path / "crashing_server.py"
    crashing_script.write_text(r"""
import sys, json
line = sys.stdin.readline()
sys.exit(1)
""", encoding="utf-8")

    client = StdioMCPClient(
        MCPServerConfig(
            name="crashing",
            command=sys.executable,
            args=[str(crashing_script)],
        )
    )

    with pytest.raises(MCPClientError):
        await client.start()


@pytest.mark.asyncio
async def test_composite_tool_executor(tmp_path, jarvis):
    """CompositeToolExecutor seamlessly filters and routes between CoreTools and MCP."""
    core = CoreTools(agents_root=tmp_path)
    registry = MCPRegistry(config_path=tmp_path / "mcp_servers.json", repo_root=tmp_path)
    executor = CompositeToolExecutor(core_tools=core, mcp_registry=registry)

    # In-process tool check
    specs = executor.specs_for(jarvis, {"trust": "sandboxed"})
    names = {s.name for s in specs}
    assert "scratchpad_read" in names

    # Execute in-process tool
    res = await executor.execute(jarvis, "scratchpad_read", {}, {"trust": "sandboxed"})
    assert "empty" in res
