#生成run_id 见目录 接入广播中心
from __future__ import annotations
import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from pathlib import Path


from myclaude.core.bus.events import (
    RunFinishedEvent,
    RunStartedEvent,
)
from myclaude.core.config import myclaudeconfig
from myclaude.core.context import ExecutionContext
from myclaude.core.events.bus import EventBus, EventHandler
from myclaude.core.events.writer import EventWriter
from myclaude.core.llm.base import LLMProvider
from myclaude.core.llm.provider import AnthropicProvider
from myclaude.core.loop import AgentLoop
from myclaude.core.runs import RUN_DIR, new_run_id
from myclaude.core.session.model import Session
from myclaude.core.session.store import SessionStore
from myclaude.core.task.manager import TaskManager
from myclaude.core.tools.builtin import (
    BashTool,
    ListDirTool,
    NoteSaveTool,
    ReadFileTool,
    TaskCreateTool,
    TaskGetTool,
    TaskListTool,
    TaskUpdateTool,
    WriteFileTool,
)
from myclaude.core.tools.registry import ToolRegistry
from myclaude.core.trace.provider import TracingProvider
from myclaude.core.trace.writer import TraceWriter

logger=logging.getLogger(__name__)

def _now()->str:
    return datetime.now(UTC).isoformat()

@dataclass
class RunOutcome:
    status:str
    result : str
    reason:str |None=None




class AgentRunner:
    #组装运行时的依赖
    def __init__(
            self,
            config:myclaudeconfig,
            # 是「分界线」：**它后面的参数只能按关键字传，不能按位置传。**
            *,
            bus:EventBus|None=None,
            provider:LLMProvider |None = None,
            extra_handlers:list[EventHandler] |None = None,
            run_dir:Path |None = None,
            trace:TraceWriter |None = None,
    )->None:
        self.config = config
        self.bus = bus
        self.provider = provider
        self.extra_handlers = extra_handlers or []
        self.run_dir = run_dir or RUN_DIR
        self.trace=trace

    #执行一次完整的调用
    async def run(self,goal:str,*,run_id:str|None=None)->None:
        await self.run_and_capture(goal,run_id=run_id)



    async def run_and_capture(self,
                            goal,
                            *,
                            run_id:str|None=None,
                            session:Session|None=None,
                            store:SessionStore|None=None
                            )->RunOutcome:
        run_id =  run_id or new_run_id()
        if session is not None and store is not None:

            run_path=self.run_dir(session.id) / run_id
            history=store.read_messages(session.id)
            notes=store.read_notes(session.id)
        else:
            run_path=self.run_dir /run_id
            history=[{"role":"user","content":goal}]
            notes=""
        run_path.mkdir(parents=True, exist_ok=True)

        # 有外部 bus 就用外部 bus（daemon 的全局 bus）；
        # 没有就新建一个本地 bus，保持 s1 的直接调用方式不变。
        bus = self.bus if self.bus is not None else EventBus()
        for handler in self.extra_handlers:
            bus.subscribe(handler)

        context = ExecutionContext(
            run_id=run_id,
            goal=goal,
            max_steps=self.config.agent.max_steps,
            prefill_messages=history,
            session_notes=notes,
        )

        # 历史消息已经全部在 thread 里，run 结束后只追加新增部分
        prefill_len = len(history)

        #每次run就保存一个独立的.tasks目录
        task_manager = TaskManager(run_path / ".tasks")

        async with EventWriter(run_path/"events.jsonl") as writer:
            writer.subscribe(bus)
            await bus.publish(RunStartedEvent(run_id=run_id,goal=goal,ts=_now(),))
            cancelled=False

            try:
                base_provider:LLMProvider= (self.provider or AnthropicProvider(
                    self.config.llm.default_model
                ))
                #开始埋trace
                provider:LLMProvider=base_provider
                if self.trace is not None:
                    provider=TracingProvider(base_provider,self.trace,include_payload=(self.config.trace.include_llm_payload),)

#工具调用

                registry=self._build_registry(task_manager,
                                            session=session,
                                            store=store,
                                            run_id=run_id,

                                            )
                loop = AgentLoop(provider, registry, bus)
                await loop.run(context)

            except asyncio.CancelledError:
                cancelled=True
                if not context.is_done():
                    context.mark_failure("canceled")


            except Exception:
                logger.exception(
                    "agent run failed run_id=%s step=%d",
                    run_id,
                    context.step,
                )
                if not context.is_done():
                    context.mark_failure("llm_error")

            await bus.publish(
                RunFinishedEvent(
                    run_id=run_id,
                    status=context.status,
                    reason=context.reason,
                    steps=context.step,
                    ts=_now(),
                )
            )

            # 只写回本轮新增的 assistant / tool_result 消息
            if session is not None and store is not None:
                store.append_messages(
                    session.id,
                    context.messages[prefill_len:],
                    run_id=run_id,
                )


        if cancelled:
            raise asyncio.CancelledError()

        return RunOutcome(
            status=context.status,
            result=context.result,
            reason=context.reason,
        )
    #工具和任务共享一个Taskmanager
    def _build_registry(self, task_manager: TaskManager,*,session:Session|None=None,store:SessionStore|None=None,run_id:str|None=None
    ) -> ToolRegistry:
        registry = ToolRegistry()
        for tool in (
            ReadFileTool(),
            BashTool(),
            WriteFileTool(),
            ListDirTool(),
        ):
            registry.register(tool)

        for tool in (
            TaskCreateTool(task_manager),
            TaskUpdateTool(task_manager),
            TaskListTool(task_manager),
            TaskGetTool(task_manager),
        ):
            registry.register(tool)

        #同时具有session和store和run_id的才配暴露note-save
        if(
            session is not None and
            store is not None and
            run_id is not None
        ):
            registry.register(NoteSaveTool(store,session.id,run_id))

        return registry

