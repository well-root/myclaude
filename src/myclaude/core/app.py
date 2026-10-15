#daemon 的监听TCP
import asyncio
import socketserver
import signal
import time
from logging import shutdown
from venv import logger

from anthropic._utils._logs import setup_logging

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

    #定义一个异步的启动装置(监听器)
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

