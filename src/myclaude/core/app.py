#daemon 的监听TCP
from __future__ import annotations
import time
import asyncio
import datetime
import json
import logging
import signal
from typing import Any
import sys

import myclaude
from myclaude.core.bus.commands import PongResult
from myclaude.core.config import get_config
from myclaude.core.logging_setup import setup_logging
from myclaude.core.transport.socket_server import SocketServer


logger=logging.getLogger(__name__)

class coreAPP:
    def run(self)->None:

        self._start_time=time.monotonic()

    #处理core.ping请求 然后返回服务的版本 运行市场和接收时间
    async def _handle_line(self,params:dict[str,Any])->PongResult:

        client = params.get("client", "unknown")
        logger.debug("ping from %s", client)
        return PongResult(
            server_version=myclaude.__version__,
            uptime_ms=int((time.monotonic() - self._start_time) * 1000),
            received_at=datetime.datetime.now(datetime.UTC).isoformat(),
        )


    async def run(self)->None:
        self._start_time=time.monotonic()
        config = get_config()
        setup_logging(config)

        server = SocketServer(config.host, config.port)
        server.register("core.ping", self._handle_line)

        addr=await server.start()
        logger.info("myclaude-core %s listening addr=%s", myclaude.__version__, addr)
        logger.info("config: %s", config)

        loop = asyncio.get_running_loop()
        shutdown = asyncio.Event()

        if sys.platform == "win32":
            # Windows 的 asyncio 不支持 add_signal_handler，
            # 改用标准 signal 模块，再跨线程回投到事件循环
            def _on_signal(_signum: int, _frame: Any) -> None:
                loop.call_soon_threadsafe(shutdown.set)

            signal.signal(signal.SIGINT, _on_signal)
            signal.signal(signal.SIGBREAK, _on_signal)

        else:
            loop.add_signal_handler(signal.SIGINT, shutdown.set)
            loop.add_signal_handler(signal.SIGTERM, shutdown.set)

        await shutdown.wait()

        logger.info("shutting down")
        await server.stop()

    #启动coreapp
def run()->None:
    asyncio.run(coreAPP.run())








