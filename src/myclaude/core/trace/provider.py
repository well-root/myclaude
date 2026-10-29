from __future__ import annotations

import copy
import dataclasses
import time
from datetime import UTC, datetime
from typing import Any

from myclaude.core.events.bus import EventBus
from myclaude.core.llm.base import LLMProvider
from myclaude.core.llm.types import LLMResponse
from myclaude.core.trace.record import TraceRecord
from myclaude.core.trace.writer import TraceWriter

def _now()->str:
    return datetime.now(UTC).isoformat()

class TracingProvider:
    #写入完整的IO
    def __init__(self, inner:LLMProvider,trace:TraceWriter,*,include_payload:bool=True)->None:
        self.inner=inner
        self.trace=trace
        self.include_payload=include_payload

    async def chat(
            self,
            messages: list[dict[str, object]],
            tool_schemas: list[dict[str, object]],
            bus: EventBus,
            run_id: str,
            *,
            step: int = 0,
            system:str|None=None,
    )->LLMResponse:
        if self.include_payload:
            call_data:dict[str, Any]={
                "messages":copy.deepcopy(messages),
                "tool_schemas":copy.deepcopy(tool_schemas),
                "system":system,
            }
        else:
            call_data={
                "message_count":len(messages),
                "tool_count":len(tool_schemas),
            }

        self.trace.emit(
            TraceRecord(
                ts=_now(),
                direction="CORE→LLM",
                layer="llm",
                kind="api_call",
                run_id=run_id,
                step=step,
                data=call_data,
            )
        )

        t0=time.monotonic()
        result = await self.inner.chat(
            messages=messages,
            tool_schemas=tool_schemas,
            bus=bus,
            run_id=run_id,
            step=step,
            system=system,
        )

        latency_ms = int((time.monotonic() - t0) * 1000)

        if self.include_payload:
            resp_data: dict[str, Any] = {
                "stop_reason": result.stop_reason,
                "text": result.text,
                "tool_calls": [
                    dataclasses.asdict(tc) for tc in result.tool_calls
                ],
                "usage": (
                    dataclasses.asdict(result.usage)
                    if result.usage
                    else {}
                ),
                "latency_ms": latency_ms,
            }
        else:
            resp_data = {
                "stop_reason": result.stop_reason,
                "usage": (
                    dataclasses.asdict(result.usage)
                    if result.usage
                    else {}
                ),
                "latency_ms": latency_ms,
            }

        self.trace.emit(
            TraceRecord(
                ts=_now(),
                direction="LLM→CORE",
                layer="llm",
                kind="api_response",
                run_id=run_id,
                step=step,
                data=resp_data,
            )
        )

        return result



