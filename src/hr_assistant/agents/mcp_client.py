"""MCP client used by the agents.

The agents never import the server's tool functions directly — they discover
and call tools over the MCP protocol, exactly like any third-party MCP host
would. The connection target is either a streamable-HTTP URL (production) or
an in-process MCPServer instance (tests), which the official SDK's Client
accepts interchangeably.
"""

from contextlib import asynccontextmanager

from mcp import Client
from mcp.server import MCPServer


class ToolboxSession:
    """One open MCP session: tool discovery + calls."""

    def __init__(self, client: Client):
        self._client = client
        self._tools_cache: list | None = None

    async def openai_tools(self, allowed: set[str] | None = None) -> list[dict]:
        """MCP tool definitions converted to OpenAI function-calling schema.

        `allowed` restricts which tools a given agent may see (least privilege:
        each specialist only gets the tools of its own domain).
        """
        if self._tools_cache is None:
            result = await self._client.list_tools()
            self._tools_cache = result.tools
        tools = []
        for tool in self._tools_cache:
            if allowed is not None and tool.name not in allowed:
                continue
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description or "",
                        "parameters": tool.input_schema,
                    },
                }
            )
        return tools

    async def call(self, name: str, arguments: dict) -> str:
        """Call a tool; always returns text (JSON for structured results)."""
        result = await self._client.call_tool(name, arguments)
        parts = [block.text for block in result.content if getattr(block, "text", None)]
        text = "\n".join(parts) if parts else "{}"
        if result.is_error:
            return f'{{"error": "tool call failed", "detail": {text!r}}}'
        return text


class MCPToolbox:
    """Factory for MCP sessions against a fixed target (URL or server object)."""

    def __init__(self, target: str | MCPServer):
        self._target = target

    @asynccontextmanager
    async def session(self):
        async with Client(self._target) as client:
            yield ToolboxSession(client)
