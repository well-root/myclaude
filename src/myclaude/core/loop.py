from __future__ import annotations
from datetime import  UTC,datetime
import logging
from typing import TYPE_CHECKING

from myclaude.core.context import BASE_SYSTEM_PROMPT,ExecutionContext
logger = logging.getLogger(__name__)
import asyncio
from myclaude.core.bus.events import StepFinishedEvent, StepStartedEvent
from myclaude.core.context import ExecutionContext
from myclaude.core.events.bus import EventBus
from myclaude.core.llm.base import LLMProvider
from myclaude.core.tools.invocation import invoke_tool
from myclaude.core.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from myclaude.core.permissions.manager import PermissionManager
def _now()->str:
    return datetime.now(UTC).isoformat()

#⭐⭐⭐ 项目最有意思的部分
#llm provide 和 工具表 事务总线
class AgentLoop:
    def __init__(self,
                provider: LLMProvider,
                registry: ToolRegistry,
                bus: EventBus,
                *,
                permission_manager: PermissionManager|None=None,
                session_id:str="",
                )->None:
        self.provider = provider
        self.registry = registry
        self.bus = bus
        self.permission_manager = permission_manager
        self.session_id = session_id


    #驱动计划和行动 感觉想react
    async def run(self,context: ExecutionContext) -> None:
        while not context.is_done():
            context.step +=1
            await self.bus.publish(
                StepStartedEvent(run_id=context.run_id,step=context.step,ts=_now())
            )

            #【plan】 llm
            try:
                response = await self.provider.chat(
                    messages=context.messages,
                    tool_schemas=self.registry.tool_schemas(),
                    bus=self.bus,
                    run_id=context.run_id,
                    step=context.step,
                    system=context.system_prompt(BASE_SYSTEM_PROMPT)
                )

            except asyncio.CancelledError:
                context.mark_failure("cancelled")
                raise
            except Exception:
                logger.exception(
                    "LLM chat failed (run_id=%s, step=%d)",
                    context.run_id, context.step,
                )
                context.mark_failure("llm_error")
                break

            #把记忆篮子加入 记忆内容#这也是观察阶段
            blocks:list[dict[str,object]]=[]
            if response.text:
                blocks.append({"type": "text", "text": response.text})
            for tc in response.tool_calls:
                result = await invoke_tool(
                    self.registry, tc, self.bus, context.run_id,
                    permission_manager=self.permission_manager,
                    session_id=self.session_id,
                )
                context.add_tool_result(tc.id, result.content, is_error=result.is_error)

            #act
            if response.stop_reason=="tool_use":
                for tc in response.tool_calls:
                    result = await invoke_tool(
                        self.registry,tc,self.bus,context.run_id,
                    )
                    context.add_tool_result(tc.id, result.content,is_error=result.is_error)

            #最终的检查部分
            if response.stop_reason=="end_turn":
                context.result=response.text or ""
                context.mark_success()
            elif context.step>=context.max_steps:
                context.mark_failure("more than max_steps")

            await self.bus.publish(
                StepFinishedEvent(
                    run_id=context.run_id,step=context.step,ts=_now()
                )
            )

