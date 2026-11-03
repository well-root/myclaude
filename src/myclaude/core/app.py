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
    SessionCloseCommand,
    SessionCloseResult,
    SessionCreateCommand,
    SessionCreateResult,
    SessionGetHistoryCommand,
    SessionGetHistoryResult,
    SessionSendMessageCommand,
    SessionSendMessageResult,
    SessionCompactCommand,
    SessionCompactResult,
    PermissionRespondResult, PermissionRespondCommand,
)
from myclaude.core.bus.envelope import EventPushEnvelope
from myclaude.core.config import get_config, myclaudeconfig
from myclaude.core.events.bus import EventBus
from myclaude.core.logging_setup import setup_logging
from myclaude.core.llm.provider import AnthropicProvider
from myclaude.core.mcp.server import McpServerManager
from myclaude.core.runner import AgentRunner
from myclaude.core.subagent.registry import BackgroundTaskRegistry

from myclaude.core.runs import events_file, new_run_id
from myclaude.core.session import SessionManager, SessionStore
from myclaude.core.trace.record import TraceRecord
from myclaude.core.trace.writer import TraceWriter
from myclaude.core.transport.ipc_broadcaster import IpcEventBroadcaster
from myclaude.core.transport.socket_server import (
    SocketServer,
    get_connection_writer,
)

from myclaude.core.permissions.manager import PermissionManager
from myclaude.core.permissions.storage import load_policy_file

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
        self.config:myclaudeconfig|None=None
        self.sessions:SessionManager|None=None
        self.permission_manager:PermissionManager|None=None
        self.mcp_manager:McpServerManager|None=None
        self.task_registry:BackgroundTaskRegistry=BackgroundTaskRegistry()


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
        assert self.sessions is not None

        cmd=AgentRunCommand.model_validate(params)
        session=await self.sessions.create(mode="one_shot",title=cmd.goal[:40])
        run_id=new_run_id()
        task=asyncio.create_task(self.sessions.seed_message(session.id,cmd.goal,run_id=run_id))

        self.running_runs.add(task)
        task.add_done_callback(self.on_run_done)
        return AgentRunResult(run_id=run_id)

        # 创建 chat / one_shot session

    async def session_create_handler(
            self, params: dict[str, Any]
    ) -> SessionCreateResult:
        assert self.sessions is not None
        cmd = SessionCreateCommand.model_validate(params)
        session = await self.sessions.create(
            mode=cmd.mode, title=cmd.title
        )
        return SessionCreateResult(
            session_id=session.id, status=session.status
        )

    # 向 session 发送消息，等这一轮 run 完成才返回
    async def session_send_handler(
            self, params: dict[str, Any]
    ) -> SessionSendMessageResult:
        assert self.sessions is not None
        cmd = SessionSendMessageCommand.model_validate(params)
        run_id = await self.sessions.seed_message(cmd.session_id, cmd.content)
        return SessionSendMessageResult(run_id=run_id)

    # 返回 session 的完整 Anthropic messages 历史
    async def session_history_handler(
            self, params: dict[str, Any]
    ) -> SessionGetHistoryResult:
        assert self.sessions is not None
        cmd = SessionGetHistoryCommand.model_validate(params)
        messages = await self.sessions.get_history(cmd.session_id)
        return SessionGetHistoryResult(messages=messages)

    # 关闭 session
    async def session_close_handler(
            self, params: dict[str, Any]
    ) -> SessionCloseResult:
        assert self.sessions is not None
        cmd = SessionCloseCommand.model_validate(params)
        await self.sessions.close(cmd.session_id)
        return SessionCloseResult(status="closed")

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
            replayed_count = await self.replay_events(cmd.replay_from_run, writer, cmd.topic)

        assert self.broadcaster is not None

        sub_id = self.broadcaster.subscribe(writer, cmd.topic, cmd.scope)
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
            pattern = f"*/runs/{run_id}/events.jsonl"
            for candidate in Path(
                    "~/.myclaude/sessions"
            ).expanduser().glob(pattern):
                path = candidate
                break
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

    # 接收客户端权限审批响应，resolve 对应挂起的 Future
    async def permission_respond_handler(
            self, params: dict[str, Any]
    ) -> PermissionRespondResult:
        cmd = PermissionRespondCommand.model_validate(params)
        logger.info(
            "permission.respond received tool_use_id=%s decision=%s",
            cmd.tool_use_id, cmd.decision,
        )
        if self.permission_manager is None:
            logger.error("permission.respond: PermissionManager not initialized")
            return PermissionRespondResult()
        self.permission_manager.respond(cmd.tool_use_id, cmd.decision)
        return PermissionRespondResult()

    # 手动压缩 session thread，将摘要持久化写入 thread.jsonl
    async def session_compact_handler(
            self, params: dict[str, Any]
    ) -> SessionCompactResult:
        assert self.sessions is not None
        cmd = SessionCompactCommand.model_validate(params)
        result = await self.sessions.compact(cmd.session_id, cmd.focus)
        return result  # type: ignore[no-any-return]

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

        # 权限管理器：进程内共享一份 pending / always 缓存
        policy_file = Path("~/.myclaude/policy.toml").expanduser()
        self.permission_manager = PermissionManager(
            policy_file=policy_file,
            timeout_s=self.config.permission.timeout_s,
        )
        logger.info(
            "permission manager: timeout_s=%.1f  persistent=%d entries",
            self.config.permission.timeout_s,
            len(load_policy_file(policy_file)),
        )


        # MCP：daemon 启动时连接所有配置的 server，失败只记录日志不阻塞启动
        self.mcp_manager = McpServerManager()
        if self.config.mcp.servers:
            logger.info("mcp: starting %d server(s)", len(self.config.mcp.servers))
            await self.mcp_manager.start_all(self.config.mcp.servers)

        #集中会话数据 放到用户目录；tool_result 截断阈值来自 [compaction]
        store = SessionStore(
            Path("~/.myclaude/sessions").expanduser(),
            tool_result_limit=self.config.compaction.tool_result_limit,
            tool_result_keep=self.config.compaction.tool_result_keep,
        )
        self.sessions = SessionManager(
            store,
            runner_factory=lambda: AgentRunner(
                self.config,
                bus=self.bus,
                trace=self.trace,
                permission_manager=self.permission_manager,
                mcp_manager=self.mcp_manager,
                task_registry=self.task_registry,
            ),
            bus=self.bus,
            # 只有真正执行 /compact 时才创建 provider，避免无 API key 时 daemon 启动失败
            provider_factory=lambda: AnthropicProvider(
                self.config.llm.default_model
            ),
        )

        server = SocketServer(self.config.host, self.config.port,self.broadcaster,trace=self.trace)
        server.register("core.ping", self._handle_line)
        server.register("agent.run", self.agent_run_handler)

        server.register("event.subscribe", self.subscribe_handler)
        server.register("session.create", self.session_create_handler)
        server.register("session.send_message", self.session_send_handler)
        server.register(
            "session.get_history",
            self.session_history_handler,
        )
        server.register(
            "session.close",
            self.session_close_handler
        )

        server.register(
            "permission.respond",
            self.permission_respond_handler,
        )
        server.register(
            "session.compact",
            self.session_compact_handler,
        )
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

        await self.task_registry.cancel_all()
        if self.mcp_manager is not None:
            await self.mcp_manager.stop_all()

        await server.stop()
        if self.trace is not None:
            await self.trace.stop()


    #启动coreapp
def run()->None:
    asyncio.run(coreAPP().run())