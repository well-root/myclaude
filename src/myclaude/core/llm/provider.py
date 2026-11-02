#这个是llm的格式化
from __future__ import     annotations

import os
from datetime import UTC,datetime

from typing import Any
import anthropic

from myclaude.core.bus.events import LLMModelSelectedEvent,LLMTokenEvent,LLMUserEvent
from myclaude.core.events.bus import EventBus
from myclaude.core.context import BASE_SYSTEM_PROMPT
from myclaude.core.llm.types import LLMResponse,ToolCallBlock,UsageStats


def _now()->str:
    return datetime.now(UTC).isoformat()

# 各模型的 context window；未知模型保守按 200k 计算
_MODEL_CONTEXT_WINDOWS:dict[str,int]={
    "deepseek-flash":1_048_576,
    "deepseek-chat":131_072,
    "claude-sonnet-4-6":200_000,
    "claude-haiku-4-5-20251001":200_000,
    "claude-opus-4-7":200_000,
}

def _context_window(model:str)->int:
    return _MODEL_CONTEXT_WINDOWS.get(model,200_000)

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
            *,
            step:int=0,#仅为了满足规范 这里根本不会使用
            system:str|None=None,
    )->LLMResponse:
        await bus.publish(
            LLMModelSelectedEvent(run_id=run_id,model=self._model,strategy="static",ts=_now()),

        )

        system_blocks:list[dict[str, object]]=[{
            "type":"text",
            "text":system or BASE_SYSTEM_PROMPT,
            "cache_control":{"type": "ephemeral"},
        },]

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

        # 本次 prompt 的实际规模 = 未缓存输入 + 缓存命中 + 本次写入缓存
        prompt_tokens = usage.input_tokens + cache_read + cache_write
        context_pct = prompt_tokens / _context_window(self._model)


        await bus.publish(
            LLMUserEvent(
                run_id=run_id,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_read_input_tokens=cache_read,
                cache_read_output_tokens=cache_write,
                context_pct=context_pct,
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
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_read_input_tokens=cache_read,
                cache_creation_input_tokens=cache_write,
                context_pct=context_pct,
            ),


        )

