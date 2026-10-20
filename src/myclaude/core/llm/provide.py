#这个是llm的格式化
from __future__ import     annotations

import os
from datetime import UTC,datetime

from typing import Any
import anthropic

from myclaude.core.bus.events import LLMModelSelectedEvent,LLMTokenEvent,LLMUserEvent
from myclaude.core.events.bus import EventBus
from myclaude.core.llm.types import LLMResponse,ToolCallBlock,UsageStats

_SYSTEM_PROMPT = (
    "You are a helpful AI assistant. "
    "Use the available tools to complete the user's goal. "
    "When the goal is fully achieved, respond with a final answer and do not call any more tools."
)

def _now()->str:
    return datetime.now(UTC).isoformat()

class AnthropicProvider:
    #初始化客户端 跳过apikey去检验
    def __init__(self,model:str,client:Any=None)->None:
        if client is None:
            api_key=os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                raise SystemExit("Please set an environment variable ANTHROPIC_API_KEY")
            self._client:Any=anthropic.AsyncAnthropic(api_key=api_key)

        else:
            self._client=client
        self._model=model

    #流式调用
    async def chat(
            self,
            messages:list[dict[str, object]],
            tool_schemas:list[dict[str, object]],
            bus:EventBus,
            run_id:str,
    )->LLMResponse:
        await bus.publish(
            LLMModelSelectedEvent(run_id=run_id,model=self._model,strategy="static",ts=_now()),

        )

        system: list[dict[str, object]] = [
            {"type": "text", "text": _SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}},
        ]

        tools: list[dict[str, object]] = list(tool_schemas)
        if tools:
            last = dict(tools[-1])
            last["cache_control"] = {"type": "ephemeral"}
            tools = tools[:-1] + [last]


        kwargs:dict[str,object]={
            "model":self._model,
            "max_tokens":4096,
            "system":system,
            "messages":messages,

        }

        if tools:
            kwargs["tools"]=tools

        text_parts:list[str]=[]

        async with self._client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                await bus.publish(LLMTokenEvent(run_id=run_id,token=text,ts=_now()))

                text_parts.append(text)
            final_message=await stream.get_final_message()

        usage=final_message.usage
        cache_read:int=getattr(usage,"cache_read_input_tokens",0) or 0
        cache_write:int=getattr(usage,"cache_creation_input_tokens",0) or 0

        await bus.publish(
            LLMUserEvent(
                run_id=run_id,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_read_input_tokens=cache_read,
                cache_read_output_tokens=cache_write,
                ts=_now(),

            )
        )
        tool_calls:list[ToolCallBlock]=[]
        for block in final_message.content:
            if block.type=="tool_use":
                tool_calls.append(
                    ToolCallBlock(id=block.id,name=block.name,input=dict(block.input))
                )

        #把end_turn和其他七七八八的作为中止的有效信息 maxtoken作为终止轮处理

        stop_reason=final_message.stop_reason or "end_turn"
        if stop_reason not in ("end_turn","tool_use"):
            stop_reason="end_turn"

        return LLMResponse(
            stop_reason=stop_reason,
            tool_calls=tool_calls,
            text="".join(text_parts),
            usage=UsageStats(
                input_tokens=usage.input_token,
                output_tokens=usage.output_token,
                cache_read_input_tokens=cache_read,
                cache_creation_input_tokens=cache_write,
            ),


        )

