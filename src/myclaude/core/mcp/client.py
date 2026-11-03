from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

import os

log = logging.getLogger(__name__)



class McpServerUnavailableError(Exception):
    pass


class McpToolError(Exception):
    """MCP server 返回的应用层错误（连接正常，但工具调用失败）"""

@dataclass
class McpToolDef:
    name: str
    description: str
    input_schema: dict[str, Any]=field(default_factory=dict)

#mcp server可用通过JSON-RPC2.0进行stdio or TCP通信

class McpClient:
    def __init__(self) -> None:
        self._id = 0
        self._proc: asyncio.subprocess.Process | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._tcp_writer: asyncio.StreamWriter | None = None
        self._transport = ""
        self._lock = asyncio.Lock()
        self._stderr_task: asyncio.Task[None] | None = None#error

    _STREAM_LIMIT = 64 * 1024 * 1024

    #stdio进行握手
    async def connect_stdio(self,
                            command:str,
                            args:list[str],
                            env:dict[str, str]|None=None,
                            )->None:
        merged_env = {**os.environ, **(env or {})}
        self._proc = await asyncio.create_subprocess_exec(
            command,
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=merged_env,
            limit=self._STREAM_LIMIT,
        )
        self._reader = self._proc.stdout
        self._transport = "stdio"
        # 后台持续读取 stderr，防止管道缓冲区满导致子进程阻塞
        self._stderr_task = asyncio.create_task(self._drain_stderr())
        await self._initialize()

    #通过TCP
    async def connect_tcp(self, host: str, port: int) -> None:
        self._reader, self._tcp_writer = await asyncio.open_connection(
            host, port, limit=self._STREAM_LIMIT
        )
        self._transport = "tcp"
        await self._initialize()

        # 发送 initialize 请求完成 MCP 握手
    async def _initialize(self) -> None:
        await self._call(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "myclaude", "version": "0.1"},
            },
        )
        await self._notify("notifications/initialized", {})

    # 列出 MCP server 提供的工具定义
    async def list_tools(self) -> list[McpToolDef]:
        response = await self._call("tools/list", {})
        tools: list[McpToolDef] = []
        for t in response.get("tools", []):
            tools.append(
                McpToolDef(
                    name=t.get("name", ""),
                    description=t.get("description", ""),
                    input_schema=t.get("inputSchema", {}),
                )
            )
        return tools

    # 调用 MCP server 上的工具，返回所有 text 内容拼接
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        response = await self._call(
            "tools/call",
            {"name": name, "arguments": arguments},
        )
        parts: list[str] = []
        for item in response.get("content", []):
            if item.get("type") == "text":
                parts.append(str(item["text"]))
        return "\n".join(parts)

    #读取后台进程 持续输出stderr记录日志
    async def _drain_stderr(self) -> None:
        if self._proc is None or self._proc.stderr is None:
            return
        try:
            while True:
                line=await self._proc.stderr.readline()
                if not line:
                    break
                stderr_line=line.decode(errors="replace").rsplit()
                if stderr_line:
                    log.debug("mcp stderr line: %s", stderr_line)

        except asyncio.CancelledError:
            pass
        except Exception:
            log.debug("mcp stderr drain stopped",exc_info=True)

    # 关闭连接并终止 stdio 子进程
    async def close(self) -> None:
        if self._stderr_task is not None:
            self._stderr_task.cancel()
            try:
                await self._stderr_task
            except asyncio.CancelledError:
                pass
            self._stderr_task = None
        if self._transport == "stdio" and self._proc is not None:
            try:
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), timeout=5.0)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
        elif self._transport == "tcp":
            writer = self._tcp_writer
            if writer is not None:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass

    #给RPC请求并且接受等待
    async def _call(self,method:str,params:dict[str, Any]) -> dict[str, Any]:
        self._id+=1
        req_id=self._id
        req_id_str=str(req_id)
        request = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
        async with self._lock:
            await self._write_line(json.dumps(request))
            while True:
                line = await self._read_line()
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    log.debug("mcp: ignoring non-JSON line: %r", line[:200])
                    continue
                msg_id = msg.get("id")
                if msg_id is None:
                    # server-initiated notification，忽略
                    log.debug("mcp: received server notification: %s", msg.get("method"))
                    continue
                if str(msg_id) == req_id_str:
                    if "error" in msg:
                        err = msg["error"]
                        raise McpToolError(
                            f"{err.get('message', str(err))} (code={err.get('code')})"
                        )
                    result: dict[str, Any] = msg.get("result", {})
                    return result

    #发送相应的json并且写入
    async def _write_line(self,line:str) -> None:
        data=(line+"\n").encode()
        if self._transport == "stdio":
            w=self._proc.stdin if self._proc else None
            if w is None:
                raise McpServerUnavailableError("stdio writer unavailable")
            w.write(data)
            await w.drain()
        elif self._transport == "tcp":
            w = self._tcp_writer
            if w is None:
                raise McpServerUnavailableError("tcp writer unavailable")
            w.write(data)
            await w.drain()

    # 从 MCP server 读取一行 JSON；跳过空行，仅 EOF（b""）才视为连接断开
    async def _read_line(self) -> str:
        if self._reader is None:
            raise McpServerUnavailableError("reader unavailable")
        while True:
            try:
                data = await asyncio.wait_for(
                    self._reader.readline(),
                    timeout=30.0,
                )
            except TimeoutError:
                raise McpServerUnavailableError("MCP server read timeout")
            except (asyncio.LimitOverrunError, ValueError) as exc:
                raise McpServerUnavailableError(
                    f"MCP response too large (>{self._STREAM_LIMIT // 1024 // 1024}MB): {exc}"
                ) from exc
            if data == b"":
                raise McpServerUnavailableError("MCP server closed connection")
            line = data.decode(errors="replace").strip()
            if line:
                return line







