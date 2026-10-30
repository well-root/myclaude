#让session协议脱离TUI工具
from __future__ import annotations
import asyncio
import sys
from typing import Any
from myclaude.core.config import myclaudeconfig
from myclaude.core.transport.socket_client import (
    IpcError,
    SocketClient,
)

class ChatPrinter:
    def __init__(self)->None:
        self._inline=False

    #若未换行自己补全一个换行的操作
    def _ensure_newline(self)->None:
        if self._inline:
            print()
            self._inline=False

    #按照事件类来打印事务消息
    async def handle(self,event:dict[str, Any]) -> None:
        t=event.get("type","")
        if t == "llm.token":
            print(event.get("token", ""), end="", flush=True)
            self._inline = True
        elif t == "tool.call_started":
            self._ensure_newline()
            print(f"[tool] {event.get('tool_name', '')}")
        elif t == "session.waiting_for_input":
            self._ensure_newline()
            print("[waiting for input]")
        elif t == "session.closed":
            self._ensure_newline()
            print("session closed.")

    #避免通信堵塞
async def _readline(prompt:str) -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, input,prompt)

#异步创建 chat session，循环读取输入并发送

async def _chat_async(config:myclaudeconfig)->int:
    client=SocketClient(config.host,config.port)

    try:
        await client.connect()
    except(ConnectionRefusedError,OSError):
        print(
            f"error: core not running "
            f"({config.host}:{config.port})",
            file=sys.stderr,
        )
        return 1

    printer=ChatPrinter()
    client.on_event(printer.handle)
    loop_task=asyncio.create_task(client.run_event_loop())

    try:
        await client.send_command(
            "event.subscribe",
            {
                "topic": [
                    "session.*",
                    "run.*",
                    "tool.*",
                    "llm.token",
                ],
                "scope": "global",
            },
        )
        created = await client.send_command(
            "session.create", {"mode": "chat"}
        )
        session_id = str(created["session_id"])
        print(f"[session: {session_id}]")
        while True:
            try:
                line=await _readline(">")
            except(EOFError,KeyboardInterrupt):
                break

            content=line.strip()
            if not content:
                continue
            await client.send_command(
                "session.send_message",
                {
                    "session_id": session_id,
                    "content": content,
                },
            )

            await client.send_command(
                "session.close", {"session_id": session_id}
            )

    except IpcError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    finally:
        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
                pass
        await client.close()
    return 0

#zhi执行chat命令
def cmd_chat(config:myclaudeconfig)->None:
    try:
        exit_code=asyncio.run(_chat_async(config))
    except KeyboardInterrupt:
        sys.exit(130)
    sys.exit(exit_code)