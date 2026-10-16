#daemon 的监听TCP
from __future__ import annotations

import asyncio
import datetime
import fnmatch
import json
import logging
import signal
import sys
import time
from datetime import UTC
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from myclaude.core.bus.commands import PingCommand
from myclaude.core.bus.envelope import INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, JsonRpcSuccess
from myclaude.core.config import get_config


class coreAPP:
    async def run(self)->None:

        self._start_time=time.monotonic()
        config=get_config()
        setup_logging(config)

        server=socketserver(config.host, config.port)
        server.register("core.ping",self._ping_handler)

        addr=await server.start()
        logger.info("myclaude %s listening addr=%s",myclaude._version_,addr)

        shutdown=asyncio.Event()
        loop=asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGINT,shutdown.set)
        loop.add_signal_handler(signal.SIGTERM,shutdown.set)



        await shutdown.wait()
        await server.stop()

    #定义一个异步的启动装置(监听器) 如果已经有daemon在跑那就直接推出，否则开始跑start
    async def start(self)->str:
        try:
            _r,w=await asyncio.open_connection(self._host,self._port)
            w.close()
            await w.wait_closed()
            raise SystemExit(f"core already running at {self._host}:{self._post}")
        except(ConnectionResetError,OSError):
            pass

        self._server=await asyncio.start_server(
            self._handle_connection,
            host=self._host,
            port=self._port,
            limit=_MAX_LINE_BYTES,
        )

        return f"{self._host}:{self._port}"
#读取任务
    
    async def _read_loop(self,
        reader:asyncio.StreamReader,
        writer:asyncio.StreamWriter,
    )->None:
        while True:
            line=await reader.readline()
            if not line:
                return
            await self._handle_line(line,writer)

    async def _handle_line(self,line:bytes,writer:asyncio.StreamWriter)->None:
        try:
            raw=json.load(line)
        except json.JSONDecodeError as e:
            await self._send(writer,make_error(None,INVALID_REQUEST,"Invalid Request",str(e)))
            return

        Handle=self._handlers.get(req.method,)
        if Handle is None:
            await self._send(
                writer,
                make_error(req.id,METHOD_NOT_FOUND,f"Method not found:{req.method}"),
            )
            return

        from pydantic import ValidationError
        try:
            result=await handler(res.params)
        except ValidationError as e:
            await self._send(writer, make_error(req.id, INVALID_PARAMS, "Invalid params", str(e)))
            return
        except Exception:
            await self._send(writer, make_error(req.id, INVALID_ERROR, "Invalid error"))
            return

        await self._send(writer,JsonRpcSuccess(id=req.id),result=result.model_dump())

    async def _ping_handler(self,params:dict[str,Any]):
        cmd=PingCommand.model_validate(params)
        logger.debug("ping from %s",cmd.client)
        import myclaude
        return PongResult(
            server_version=myclaude.__version__,
            uptime_ms=int((time.monotonic()-self._start_time)*1000),
            received_at=datetime.datetime.now(datetime.UTC).isoformat(),

        )


