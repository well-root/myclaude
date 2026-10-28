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
import fnmatch
from pathlib import Path
from pydantic import BaseModel


import myclaude
from myclaude.core.bus.commands import (
    AgentRunCommand,
    AgentRunResult,
    EventSubscriberResult,
    EventSubscriberCommand,
    PongResult,
)
from myclaude.core.bus.envelope import EventPushEnvelope
from myclaude.core.config import get_config, myclaudeconfig
from myclaude.core.events.bus import EventBus
from myclaude.core.logging_setup import setup_logging
from myclaude.core.runner import AgentRunner

from myclaude.core.runs import events_file, new_run_id
from myclaude.core.trace.record import TraceRecord
from myclaude.core.trace.writer import TraceWriter
from myclaude.core.transport.ipc_broadcaster import IpcEventBroadcaster
from myclaude.core.transport.socket_server import (
    SocketServer,
    get_connection_writer,
)

logger=logging.getLogger(__name__)

def _now()->str:
    return datetime.datetime.now(datetime.UTC).isoformat()

class coreAPP:
    def __init__(self) -> None:
        self.start_time=time.monotonic()
        self.bus = EventBus()
        self.broadcaster:IpcEventBroadcaster|None=None
        self.trace:TraceWriter |None=None
        #成为订阅者
        self.running_runs:set[asyncio.Task[None]]=set()


    #处理core.ping返回版本
    async def ping_handler(self,params:dict[str, Any]) -> PongResult:
        client=params.get("client","unknown")
        logger.debug("ping from %s", client)
        return PongResult(
            server_version=myclaude.__version__,
            uptime_ms=int(
                (time.monotonic() - self.start_time) * 1000
            ),
            received_at=datetime.datetime.now(
                datetime.UTC
            ).isoformat(),
        )

    #处理core.ping请求 然后返回服务的版本 运行市场和接收时间
    async def _handle_line(self,params:dict[str,Any])->PongResult:
        return await self.ping_handler(params)

    async def _trace_event_handler(self, event: BaseModel) -> None:
        if self.trace is None:
            return
        data = event.model_dump()
        self.trace.emit(
            TraceRecord(
                ts=_now(),
                direction="CORE",
                layer="event",
                kind="event",
                run_id=data.get("run_id"),
                data=data,
            )
        )



    async def agent_run_handler(self,params:dict[str,Any])->AgentRunResult:
        assert self.config is not None

        cmd=AgentRunCommand.model_validate(params)

        run_id=new_run_id()
        runner=AgentRunner(self.config,bus=self.bus,trace=self.trace)
        task=asyncio.create_task(runner.run(cmd.goal,run_id=run_id))

        self.running_runs.add(task)
        task.add_done_callback(self.on_run_done)
        return AgentRunResult(run_id=run_id)


    #记录异常
    def on_run_done(self,task:asyncio.Task[None])->None:
        self.running_runs.discard(task)
        if task.cancelled():
            logger.info("run task cancelled")
            return
        exc=task.exception()
        if exc is not None:
            logger.error("run task failed: %s", exc,exc_info=exc)

    #注册客户端 回访接受
    async def subscribe_handler(self,params:dict[str,Any])->EventSubscriberResult:
        cmd=EventSubscriberCommand.model_validate(params)
        writer=get_connection_writer()

        replayed_count=0
        if cmd.replay_from_run is not None:
            replayed_count = await self.replay_events(
                cmd.replay_from_run, writer, cmd.topic
            )

        assert self.broadcaster is not None

        sub_id = self.broadcaster.subscribe(
            writer, cmd.topic, cmd.scope
            )
        return EventSubscriberResult(
            subscriber_id=sub_id,
            replayed_count=replayed_count,
        )

    #从event放回topic匹配
    async def replay_events(self,
                            run_id:str,
                            writer:asyncio.StreamWriter,
                            topics:list[str],
                            )->int:
        path=events_file(run_id)
        if not path.exists():
            return 0
        count = 0
        for line in path.read_text(
                encoding="utf-8"
        ).splitlines():
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            event_type: str = event.get("type", "")
            if not any(
                    fnmatch.fnmatch(event_type, p) for p in topics
            ):
                continue

            envelope = EventPushEnvelope(event=event)
            writer.write(envelope.model_dump_json().encode() + b"\n")
            count += 1

        if count:
            await writer.drain()
        return count

    async def run(self)->None:
        self.start_time=time.monotonic()
        self.config = get_config()
        setup_logging(self.config)

        if self.config.trace.enabled:
            trace_path = Path(self.config.trace.trace_file).expanduser()
            self.trace = TraceWriter(trace_path)
            await self.trace.start()
            self.bus.subscribe(self._trace_event_handler)
        self.broadcaster=IpcEventBroadcaster(trace=self.trace)
        self.bus.subscribe(self.broadcaster.handle)

        server = SocketServer(self.config.host, self.config.port,self.broadcaster)
        server.register("core.ping", self._handle_line)
        server.register("agent.run", self.agent_run_handler)
        server.register("event.subscribe", self.subscribe_handler)
        addr=await server.start()
        logger.info("myclaude-core %s listening addr=%s", myclaude.__version__, addr)
        logger.info("config: %s", self.config)

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
        for run_task in list(self.running_runs):
            run_task.cancel()

        if self.running_runs:
            await  asyncio.gather(
                *self.running_runs,
                return_exceptions=True,
            )

        await server.stop()
        if self.trace is not None:
            await self.trace.stop()


    #启动coreapp
def run()->None:
    asyncio.run(coreAPP().run())








