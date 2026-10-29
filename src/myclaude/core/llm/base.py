#llm协议的
from __future__ import annotations

from typing import Protocol
from myclaude.core.events.bus import EventBus
from myclaude.core.llm.types import LLMResponse

class LLMProvider(Protocol):
    #流失调用
    async def chat(
            self,
            messages: list[dict[str, object]],
            tool_schemas: list[dict[str, object]],
            bus: EventBus,
            run_id: str,
            *,
            step:int=0,
            system:str|None=None,
                )->LLMResponse:...
