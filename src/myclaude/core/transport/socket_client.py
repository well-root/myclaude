from __future__ import annotations
import asyncio
import json
import uuid
from collections.abc import Awaitable,Callable
from typing import Any
from myclaude.core.bus.envelope import JsonRpcRequest

type EventHandler = Callable[dict[str, Any],Awaitable[None]]

#留给单行得最大工作
_MAX_LINE_BYTES = 64*1024*1024

class IpcError(RuntimeError):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code


class SocketClient:
    def __init__(self,host:str,port:int) -> None:
        self.host = host
        self.port = port
        self.reader:asyncio.StreamReader | None=None
        self.write:asyncio.StreamWriter | None=None
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._event_handlers: list[EventHandler] = []

        #从core守护到TCP的链接
    async def connect(self) -> None:
        self.reader,self.writer=await asyncio.open_connection(self.host,self.port,limit=_MAX_LINE_BYTES)


        #关闭TCP进 并且等待socket
    async def close(self) -> None:
        if self.writer is None:
            return
        write=self.writer
        self.writer=None
        write.close()

        try:
            await asyncio.wait_for(write.wait_closed(), timeout=1.0)
        except TimeoutError:
            pass

    def on_event(self,handler: EventHandler ) -> None:
    #事务回调 这样可以加入多个handler
        self._event_handlers.append(handler)

    async def send_command(
            self,
            method: str,
            params: dict[str, Any],
    )->dict[str, Any]:
        if self.writer is None:
            raise RuntimeError("not connected - call connect() first")

        req_id=str(uuid.uuid4())
        request=JsonRpcRequest(id=req_id,method=method,params=params)
        fut:asyncio.Future[dict[str, Any]] = (
            asyncio.get_running_loop().create_future()
        )
        #发送JSON-RPC成功返回result dict,失败就IcpError
        self._pending[req_id] = fut
        self.writer.write(request.model_dump_json().encode()+ b"\n")
        await self.writer.drain()
        return await fut
    #持续读取服务器的消息 ， 分发到RPC响应事务
    async def run_event_loop(self) -> None:
        if self.reader is None:
            raise RuntimeError("not connected - call connect() first")

        try:
            while True:
                try:
                    line = await self.reader.readline()

                except (ConnectionResetError,OSError):
                    break

                except(ValueError,asyncio.LimitOverrunError):
                    continue

                if not line:
                    break
                await self._dispatch(line)

        finally:
            #wu无论如何最后断开
            for fut in self._pending.values():
                if not fut.done():
                    fut.cancel()
                self._pending.clear()

    #解析单行
    async def _dispatch(self, line: bytes) -> None:
        try:
            msg: dict[str, Any] = json.loads(line)
        except json.JSONDecodeError:
            return

        if "jsonrpc" in msg:
            req_id: str | None = msg.get("id")
            if req_id and req_id in self._pending:
                fut = self._pending.pop(req_id)
                if not fut.done():
                    if "error" in msg:
                        err = msg["error"]
                        fut.set_exception(
                            IpcError(
                                err.get("code", -1),
                                err.get("message", "unknown"),
                            )
                        )
                    else:
                        fut.set_result(msg.get("result") or {})

        elif msg.get("kind") == "event":
            event_data: dict[str, Any] = msg.get("event", {})
            for handler in self._event_handlers:
                await handler(event_data)





