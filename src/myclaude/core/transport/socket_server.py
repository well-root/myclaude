from __future__ import annotations
from typing import Any
import json
import asyncio
import logging
#ValidationError 是 pydantic-core 在验证失败时引发的异常，它包含一个错误列表，详细说明了验证失败的原
from pydantic import BaseModel,ValidationError
from  collections.abc import Awaitable,Callable

from myclaude.core.bus.envelope import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    JsonRpcRequest,
    JsonRpcSuccess,
    make_error,
)

logger = logging.getLogger(__name__)

#type 在这里不是数据类型结构，是给类型起外号
type CommandHandler=Callable[[dict[str, Any]], Awaitable [Any]]

_MAX_LINE_BYTES = 1 * 1024 * 1024  # 1 MB per frame

#定义网络层的内容
class SocketServer:
    def __init__(self,host:str,port:int)->None:
        self.host = host
        self.port = port
        self._handlers:dict[str,CommandHandler]={}
        self._server: asyncio.AbstractServer | None = None

    #注册一个方法名的命令来处理函数
    def register(self,method:str,handler:CommandHandler)->None:
        self._handlers[method]=handler

    #启动一个TCP服务器
        # 定义一个异步的启动装置(监听器) 如果已经有daemon在跑那就直接推出，否则开始跑start
    async def start(self) -> str:
        try:
            _r, w = await asyncio.open_connection(self._host, self._port)
            w.close()
            await w.wait_closed()
            raise SystemExit(f"core already running at {self._host}:{self._post}")
        except(ConnectionResetError, OSError):
            pass

        self._server = await asyncio.start_server(
            self._handle_connection,
            host=self._host,
            port=self._port,
            limit=_MAX_LINE_BYTES,
        )

        return f"{self._host}:{self._port}"
        #关闭服务器
    async def stop(self) -> None:
        if self._server is None:
            return
        self._server.close()
        try:
            await asyncio.wait_for(self._server.wait_closed(), timeout=2.0)
        except(TimeoutError,asyncio.CancelledError):
            pass

        #处理完单个客户端链接 完成后关闭写流式
    async def _handle_connection(self,reader: asyncio.StreamReader, writer: asyncio.StreamWriter)->None:
        peer=writer.get_extra_info("peername","<unknown>")
        logger.debug(f"client connected {peer}")

        try:
            await self._read_loop(reader,writer)

            #最后都要关闭
        finally:
            writer.close()

            try:
                await asyncio.wait_for(writer.wait_closed(), timeout=2.0)

            except TimeoutError:
                pass
            logger.debug(f"client disconnected {peer}")


    #持续读取换行分割的json并进行分发处理
    async def _read_loop(self,reader: asyncio.StreamReader, writer: asyncio.StreamWriter)->None:
        while True:
            try:
                line=await reader.readline()
            except asyncio.LimitOverrunError:
                await self._send(writer, make_error(None, INVALID_REQUEST, "Request too large"))
                return

            if not line:
                return
            await self._read_loop(reader, writer)

#解析单行的json-rpc并返回对于的handler将结果返回客户端
    async def _handle_line(self,reader: asyncio.StreamReader, writer: asyncio.StreamWriter)->None:
        try:
            raw:Any=json.loads(line)
        except json.JSONDecodeError as e:
            #解析错误
            await self._send(writer, make_error(None, PARSE_ERROR, f"Parse error: {e}"))
            return

        try:
            req=JsonRpcRequest.model_validate(raw)
        except ValidationError as e:
            #格式错误
            await self._send(writer, make_error(None, INVALID_REQUEST, "Invalid Request", str(e)))
            return

        handler = self._handlers.get(req.method)
        if handler is None:
            await self._send(
                writer,
                make_error(req.id, METHOD_NOT_FOUND, f"Method not found: {req.method}"),
            )
            return

        try:
            result = await handler(req.params)
        except ValidationError as e:
            await self._send(
                writer,
                make_error(req.id, INVALID_PARAMS, "Invalid params", str(e)),
            )
            return
        except Exception as e:
            logger.exception("handler %s raised: %s", req.method, e)
            #服务器内部错误
            await self._send(writer, make_error(req.id, INTERNAL_ERROR, "Internal error"))
            return

        result_data: Any = result.model_dump() if isinstance(result, BaseModel) else result
        await self._send(writer, JsonRpcSuccess(id=req.id, result=result_data))

        # 将 pydantic 消息序列化为 JSON 行并写入流，随后刷新缓冲区

    async def _send(self, writer: asyncio.StreamWriter, msg: BaseModel) -> None:
        writer.write(msg.model_dump_json().encode() + b"\n")
        await writer.drain()






