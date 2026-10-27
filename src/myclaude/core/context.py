from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
#给Agent的工作记忆 直接使用anthropic的格式
@dataclass
class ExecutionContext:
    run_id:str
    goal:str
    max_steps:int
    messages:list[dict[str, Any]] = field(default_factory=list)
    status:str = "running" # or suceess falid
    step:int = 0
    reason:str | None = None
    result:str=""

#将结果作为第一条加入
    def __post_init__(self)->None:
        if not self.messages:
            self.messages.append({"role": "user", "content": self.goal})

            #llm响应的content block追加消息
    def add_assistant_messages(self,content:list[Any]) -> None:
        self.messages.append({"role": "assistant", "content": content})
    
    
    #调用工具的调用
    def add_tool_result(self,tool_use_id:str,content:str,is_error:bool=False) -> None:
        block:dict[str, Any]={
            "type":"tool_result",
            "tool_use_id":tool_use_id,
            "content":content,
        }
        
        if is_error:
            block["is_error"] = True
        
        last=self.messages[-1] if self.messages else None
        
        if(
            last is not None
            and last["role"] == "user"
            and isinstance(last["content"], list)
            and last["content"]
            and all(b.get("type") == "tool_result" for b in last["content"])
            
        ):
            last["content"].append(block)
        
        else:
            self.messages.append({"role":"user","content":[block]})

    #返回true表示loop应该停止
    def is_done(self)->bool:
        return self.status != "running"

    #RUN
    def mark_success(self) -> None:
        self.status = "success"

    def mark_failure(self,reason:str) -> None:
        self.status = "failed"
        self.reason=reason


