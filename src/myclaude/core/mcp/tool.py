from __future__ import annotations
from typing import Any
from myclaude.core.mcp.client import (
McpClient,
McpServerUnavailableError,
McpToolDef,
McpToolError,
)

from myclaude.core.tools.base import BaseTool,ToolResult

class McpTool(BaseTool):
    params_model = None

    #初始化 MCP 工具包装器，工具名以 server_name__ 为前缀防止命名冲突
    def __init__(self, client: McpClient, server_name: str, tool_def: McpToolDef) -> None:
        self._client = client
        self._server_name = server_name
        self._tool_def = tool_def
        self.name = f"{server_name}__{tool_def.name}"
        self.description = tool_def.description or f"MCP tool from {server_name}"
        self.input_schema: dict[str, Any] = (
                tool_def.input_schema or {"type": "object", "properties": {}}
        )

    #调用 MCP server 上的工具，失败时返回 is_error=True
    async def invoke(self, params: dict[str, object]) -> ToolResult:
        try:
            content = await self._client.call_tool(self._tool_def.name, dict(params))
            return ToolResult(content=content)
        except McpServerUnavailableError as exc:
            return ToolResult(
                content=f"mcp server '{self._server_name}' unavailable: {exc}",
                is_error=True,
                error_type="runtime_error",
            )
        except McpToolError as exc:
            return ToolResult(
                content=f"mcp tool '{self.name}' error: {exc}",
                is_error=True,
                error_type="runtime_error",
            )
        except Exception as exc:
            return ToolResult(
                content=f"mcp tool '{self.name}' unexpected error: {exc}",
                is_error=True,
                error_type="runtime_error",
            )

