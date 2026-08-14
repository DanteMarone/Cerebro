"""MCP (Model Context Protocol) client and tool registry layer (§10.1 & §10.3).

Cerebro is an MCP client. Tools authored by agents or provided by external systems run as
stdio MCP servers in isolated subprocesses. Process isolation is free, and crashes in an agent's
tool do not crash Cerebro.

Wire naming convention:
Tools are presented to models as `f"{server_name}__{tool_name}"` (using double underscores)
because model providers require tool names to match `^[a-zA-Z0-9_-]{1,64}$`.
"""

import asyncio
import fnmatch
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cerebro.models import Agent
from cerebro.providers.base import ToolSpec
from cerebro.tools import CoreTools

logger = logging.getLogger(__name__)

DEFAULT_MCP_TIMEOUT_S = 30.0


@dataclass
class MCPServerConfig:
    name: str
    transport: str = "stdio"  # "stdio" | "inprocess"
    command: str | None = None
    args: list[str] = field(default_factory=list)
    trust: str = "sandboxed"  # "sandboxed" | "standard" | "trusted"
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None


class MCPClientError(Exception):
    """Refusal or error communicating with an MCP server."""


class StdioMCPClient:
    """Manages communication with a single stdio MCP server process."""

    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        self._process: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()
        self._req_id = 0
        self._tools: list[ToolSpec] = []
        self._raw_tool_names: set[str] = set()

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    async def start(self) -> None:
        if not self.config.command:
            raise MCPClientError(f"Server '{self.config.name}' has no command specified.")

        # Disallow unsafe remote download invocations (§Slice 4 directive)
        cmd_str = f"{self.config.command} {' '.join(self.config.args)}".lower()
        if "npx -y" in cmd_str or "uvx" in cmd_str:
            raise MCPClientError(
                f"Dynamic tool download commands ('npx -y' / 'uvx') are forbidden for server '{self.config.name}'."
            )

        try:
            self._process = await asyncio.create_subprocess_exec(
                self.config.command,
                *self.config.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.config.cwd,
            )
        except Exception as exc:
            raise MCPClientError(f"Failed to spawn MCP server '{self.config.name}': {exc}") from exc

        # Initialize protocol handshake
        await self._initialize()
        await self._fetch_tools()

    async def stop(self) -> None:
        if self._process and self._process.returncode is None:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=2.0)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
        self._process = None

    async def _send_request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        if not self.is_running:
            await self.start()

        async with self._lock:
            self._req_id += 1
            req_id = self._req_id
            payload = {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": method,
                "params": params or {},
            }
            raw = json.dumps(payload) + "\n"
            assert self._process and self._process.stdin and self._process.stdout
            try:
                self._process.stdin.write(raw.encode("utf-8"))
                await self._process.stdin.drain()

                line = await asyncio.wait_for(
                    self._process.stdout.readline(),
                    timeout=DEFAULT_MCP_TIMEOUT_S,
                )
                if not line:
                    raise MCPClientError(f"Server '{self.config.name}' closed connection unexpectedly.")

                resp = json.loads(line.decode("utf-8").strip())
                if "error" in resp:
                    err_msg = resp["error"].get("message", str(resp["error"]))
                    raise MCPClientError(f"MCP server '{self.config.name}' error: {err_msg}")
                return resp.get("result")
            except asyncio.TimeoutError:
                raise MCPClientError(f"MCP request '{method}' to '{self.config.name}' timed out.") from None
            except Exception as exc:
                raise MCPClientError(f"MCP transport error on '{self.config.name}': {exc}") from exc

    async def _initialize(self) -> None:
        await self._send_request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "cerebro", "version": "0.1.0"},
            },
        )
        # Send initialized notification
        assert self._process and self._process.stdin
        notif = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
        self._process.stdin.write(notif.encode("utf-8"))
        await self._process.stdin.drain()

    async def _fetch_tools(self) -> None:
        result = await self._send_request("tools/list", {})
        raw_tools = (result or {}).get("tools", [])
        self._tools = []
        self._raw_tool_names = set()
        for t in raw_tools:
            raw_name = t.get("name", "")
            self._raw_tool_names.add(raw_name)
            wire_name = f"{self.config.name}__{raw_name}"
            self._tools.append(
                ToolSpec(
                    name=wire_name,
                    description=t.get("description", ""),
                    parameters=t.get("inputSchema", {"type": "object", "properties": {}}),
                )
            )

    def get_specs(self) -> list[ToolSpec]:
        return list(self._tools)

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        # Strip server prefix if present
        prefix = f"{self.config.name}__"
        raw_name = tool_name[len(prefix):] if tool_name.startswith(prefix) else tool_name
        try:
            result = await self._send_request("tools/call", {"name": raw_name, "arguments": arguments})
            content = (result or {}).get("content", [])
            text_parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
                elif isinstance(item, str):
                    text_parts.append(item)
            return "\n".join(text_parts) if text_parts else json.dumps(result)
        except Exception as exc:
            return f"error: {exc}"


class MCPRegistry:
    """Registry managing external stdio MCP servers and community tools."""

    def __init__(self, config_path: Path | str | None = None, repo_root: Path | None = None) -> None:
        self.repo_root = Path(repo_root) if repo_root else Path.cwd()
        self.config_path = Path(config_path) if config_path else self.repo_root / "mcp_servers.json"
        self._servers: dict[str, MCPServerConfig] = {}
        self._clients: dict[str, StdioMCPClient] = {}
        self.load_configs()

    def load_configs(self) -> None:
        self._servers = {}
        if self.config_path.exists():
            try:
                data = json.loads(self.config_path.read_text(encoding="utf-8"))
                for name, cfg in data.get("servers", {}).items():
                    if cfg.get("transport") == "inprocess":
                        continue
                    self._servers[name] = MCPServerConfig(
                        name=name,
                        transport=cfg.get("transport", "stdio"),
                        command=cfg.get("command"),
                        args=cfg.get("args", []),
                        trust=cfg.get("trust", "sandboxed"),
                        env=cfg.get("env", {}),
                        cwd=cfg.get("cwd"),
                    )
            except Exception as exc:
                logger.warning("Failed to load mcp_servers.json: %s", exc)

        # Discover community tools in tools/community/{name}/server.py (§10.3)
        community_dir = self.repo_root / "tools" / "community"
        if community_dir.is_dir():
            for server_file in community_dir.glob("*/server.py"):
                comm_name = f"community_{server_file.parent.name}"
                if comm_name not in self._servers:
                    self._servers[comm_name] = MCPServerConfig(
                        name=comm_name,
                        transport="stdio",
                        command="python",
                        args=[str(server_file)],
                        trust="sandboxed",
                        cwd=str(server_file.parent),
                    )

    def register_server(self, config: MCPServerConfig) -> None:
        self._servers[config.name] = config

    def get_client(self, server_name: str) -> StdioMCPClient | None:
        if server_name not in self._servers:
            return None
        if server_name not in self._clients:
            self._clients[server_name] = StdioMCPClient(self._servers[server_name])
        return self._clients[server_name]

    def all_specs(self) -> list[ToolSpec]:
        specs = []
        for name in self._servers:
            client = self.get_client(name)
            if client:
                specs.extend(client.get_specs())
        return specs

    def filter_specs_for_agent(self, agent: Agent, profile: dict | None = None) -> list[ToolSpec]:
        enabled_globs = (profile or {}).get("tools_enabled", ["cerebro-core:*"])
        allowed_specs = []
        for spec in self.all_specs():
            # Check against enabled globs (supporting server__tool or server:tool)
            tool_name = spec.name
            normalized = tool_name.replace("__", ":")
            matched = any(
                fnmatch.fnmatch(tool_name, g) or fnmatch.fnmatch(normalized, g)
                for g in enabled_globs
            )
            if matched:
                allowed_specs.append(spec)
        return allowed_specs

    async def execute(self, tool_name: str, arguments: dict[str, Any]) -> str:
        if "__" not in tool_name:
            return f"error: unknown tool '{tool_name}'"
        server_name, _ = tool_name.split("__", 1)
        client = self.get_client(server_name)
        if not client:
            return f"error: server '{server_name}' not found"
        return await client.call_tool(tool_name, arguments)

    async def close_all(self) -> None:
        for client in self._clients.values():
            await client.stop()
        self._clients.clear()


class CompositeToolExecutor:
    """Unified ToolExecutor combining in-process CoreTools and external MCP servers."""

    def __init__(self, core_tools: CoreTools, mcp_registry: MCPRegistry | None = None) -> None:
        self.core_tools = core_tools
        self.mcp_registry = mcp_registry or MCPRegistry()

    def specs_for(self, agent: Agent, profile: dict | None = None) -> list[ToolSpec]:
        specs = list(self.core_tools.specs_for(agent, profile))
        if self.mcp_registry:
            specs.extend(self.mcp_registry.filter_specs_for_agent(agent, profile))
        return specs

    async def execute(
        self, agent: Agent, name: str, args: dict[str, Any], profile: dict | None = None
    ) -> str:
        if "__" in name:
            if not self.mcp_registry:
                return "error: MCP registry not configured"
            # Verify tool is offered to agent
            offered = {s.name for s in self.specs_for(agent, profile)}
            if name not in offered:
                return f"error: '{name}' is not available to {agent.id}."
            return await self.mcp_registry.execute(name, args)
        return await self.core_tools.execute(agent, name, args, profile)
