#把订阅的事件格式化 然后打印
from __future__ import annotations
import asyncio
import json
import sys
import time
from pydantic import BaseModel

from myclaude.core.bus.events import (
    LLMTokenEvent,
    RunFinishedEvent,
    RunStartedEvent,
    StepFinishedEvent,
    StepStartedEvent,
    ToolCallFailedEvent,
    ToolCallFinishedEvent,
    ToolCallStartedEvent,
)
from myclaude.core.config import myclaudeconfig
from myclaude.core.runner import AgentRunner


class StdoutPrinter:
    #把事务进程打印到终端
    def __init__(self)->None:
        #当前输出是否处在行内模式
        self.inline=False
        #本次 run 的起始时间戳
        self.run_start:float=0.0



    def ensure_newline(self)->None:
        if self.inline:
            print()
            self.inline=False


    async def handle(self,event:BaseModel)->None:
        if isinstance(event,RunStartedEvent):
            self.run_start=time.monotonic()
            print(f"[run] {event.run_id}")

        elif isinstance(event,StepStartedEvent):
            self.ensure_newline()
            print(f"[step {event.step}] planning...")

        elif isinstance(event,LLMTokenEvent):
            print(event.token,end="",flush=True)
            self.inline=True

        elif isinstance(event,ToolCallStartedEvent):
            self.ensure_newline()
            params_str = json.dumps(event.params,ensure_ascii=False)
            print(f"[tool] {event.tool_name} {params_str}")

        elif isinstance(event, ToolCallFinishedEvent):
            print(f"[tool] {event.tool_name} ✓  {event.elapsed_ms}ms")

        elif isinstance(event, ToolCallFailedEvent):
            print(
                f"[tool] {event.tool_name} ✗  {event.error_message}",
                file=sys.stderr,
            )

        elif isinstance(event, StepFinishedEvent):
            self.ensure_newline()
            print(f"[step {event.step}] done")

        elif isinstance(event, RunFinishedEvent):
            self.ensure_newline()
            elapsed = time.monotonic() - self.run_start
            print(f"[run] {event.status}  {event.steps} steps  {elapsed:.1f}s")

#执行命令
def cmd_run(goal:str,config:myclaudeconfig)->None:
    printer = StdoutPrinter()
    runner = AgentRunner(config,extra_handlers=[printer.handle])
    try:
        asyncio.run(runner.run(goal))

    except KeyboardInterrupt:
        sys.exit(130)







