from __future__ import annotations
from datetime import  UTC,datetime
import logging
logger = logging.getLogger(__name__)
import asyncio
from myclaude.core.bus.events import StepFinishedEvent, StepStartedEvent
from myclaude.core.context import ExecutionContext
from myclaude.core.events.bus import EventBus
from myclaude.core.llm.base import LLMProvider
from myclaude.core.tools.invocation import invoke_tool
from myclaude.core.tools.registry import ToolRegistry

def _now()->str:
    return datetime.now(UTC).isoformat()

#⭐⭐⭐ 项目最有意思的部分
#llm provide 和 工具表 事务总线
class AgentLoop:
    def __init__(self,
                provider: LLMProvider,
                registry: ToolRegistry,
                bus: EventBus,
                )->None:
        self.provider = provider
        self.registry = registry
        self.bus = bus


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
                blocks.append(
                    {"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.input}
                )
            context.add_assistant_messages(blocks)

            #act
            if response.stop_reason=="tool_use":
                for tc in response.tool_calls:
                    result = await invoke_tool(
                        self.registry,tc,self.bus,context.run_id,
                    )
                    context.add_tool_result(tc.id, result.content,is_error=result.is_error)

            #最终的检查部分
            if response.stop_reason=="end_turn":
                context.mark_success()
            elif context.step>=context.max_steps:
                context.mark_failure("more than max_steps")

            await self.bus.publish(
                StepFinishedEvent(
                    run_id=context.run_id,step=context.step,ts=_now()
                )
            )

