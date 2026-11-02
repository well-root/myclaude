from __future__ import annotations
from datetime import  UTC,datetime
import logging
from typing import TYPE_CHECKING

from myclaude.core.context import BASE_SYSTEM_PROMPT,ExecutionContext
logger = logging.getLogger(__name__)
import asyncio
from myclaude.core.bus.events import StepFinishedEvent, StepStartedEvent
from myclaude.core.events.bus import EventBus
from myclaude.core.llm.base import LLMProvider
from myclaude.core.tools.invocation import invoke_tool
from myclaude.core.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from myclaude.core.permissions.manager import PermissionManager
    from myclaude.core.compact.compactor import Compactor
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
                compactor: Compactor|None=None,
                compact_threshold: float=0.80,
                session_id:str="",
                )->None:
        self.provider = provider
        self.registry = registry
        self.bus = bus
        self.permission_manager = permission_manager
        self.session_id = session_id
        self.compactor = compactor
        self.compact_threshold =compact_threshold


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
            blocks: list[dict[str, object]] = []
            if response.text:
                blocks.append({"type": "text", "text": response.text})
            for tc in response.tool_calls:
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc.id,
                        "name": tc.name,
                        "input": tc.input,
                    }
                )
            if blocks:
                context.add_assistant_messages(blocks)

            # 执行工具，只执行一次；结果作为紧随其后的 user 消息
            if response.stop_reason == "tool_use":
                for tc in response.tool_calls:
                    result = await invoke_tool(
                        self.registry,
                        tc,
                        self.bus,
                        context.run_id,
                        permission_manager=self.permission_manager,
                        session_id=self.session_id,
                    )
                    context.add_tool_result(
                        tc.id, result.content, is_error=result.is_error
                    )

            #最终的检查部分
            if response.stop_reason=="end_turn":
                context.result=response.text or ""
                context.mark_success()
            elif context.step>=context.max_steps:
                context.mark_failure("more than max_steps")

            # 仅在 run 还要继续、且 provider 报告的水位超过阈值时触发
            if (
                    not context.is_done()
                    and response.stop_reason == "tool_use"
                    and self.compactor is not None
                    and self.compact_threshold > 0
                    and response.usage is not None
                    and response.usage.context_pct >= self.compact_threshold
            ):
                await self.compactor.compact(context, self.provider)

            await self.bus.publish(
                StepFinishedEvent(
                    run_id=context.run_id,step=context.step,ts=_now()
                )
            )

