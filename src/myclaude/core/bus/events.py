from __future__ import annotations
from typing import Any, Annotated,Literal
from pydantic import BaseModel, Discriminator

#定义第一个type的作用：Pydantic 会先看 type 的值，再选对应类做完整校验。没有这个字段，一堆结构相似的 BaseModel 从JSON 反序列化时无法知道该造哪个对象
#这里定义的所有类型都是服务于agent的
#ts表示这个时间的时间戳
class CoreStartedEvent(BaseModel):
    type: Literal["core.started"]="core.started"
    listen_address: str #记录请求的地址
    version:str


class RunStartedEvent(BaseModel):
    type:Literal["run.started"]="run.started"
    run_id:str
    goal:str
    ts:str

class RunFinishedEvent(BaseModel):
    type:Literal["run.finished"]="run.finished"
    run_id:str
    status:Literal["success","failed"] #只有success and faiure
    reason:str | None=None #结束原因
    steps:int
    ts:str

class StepStartedEvent(BaseModel):
    type: Literal["step.started"] = "step.started"
    run_id: str
    step: int
    ts: str

class StepFinishedEvent(BaseModel):
    type:Literal["step.finished"]="step.finished"
    run_id:str
    step:int
    ts:str

class ToolCallStartedEvent(BaseModel):
    type:Literal["tool.call_started"]="tool.call_started"
    run_id:str
    tool_use_id:str
    tool_name:str
    params:dict[str, Any]
    ts:str


class ToolCallFinishedEvent(BaseModel):
    type:Literal["tool.call_finished"]="tool.call_finished"
    run_id:str
    tool_use_id:str
    tool_name:str
    reason:str | None=None
    elapsed_ms:int
    output:str=""
    #elapase:时间的花费长度
    ts:str

class ToolCallFailedEvent(BaseModel):
    type:Literal["tool.call_failed"]="tool.call_failed"
    run_id:str
    tool_use_id:str
    tool_name:str
    error_type:str #zhe这里包括超时 调用错误 工具不存在
    error_msg:str
    elapsed_ms:int
    ts:str

class LLMTokenEvent(BaseModel):
    type:Literal["llm.token"]="llm.token"
    run_id:str
    token:str
    ts:str


class LLMUserEvent(BaseModel):
    type:Literal["llm.user"]="llm.user"
    run_id:str
    input_tokens:int
    output_tokens:int
    cache_read_input_tokens:int
    cache_read_output_tokens:int
    ts:str

class LLMModelSelectedEvent(BaseModel):
    type:Literal["llm.model_selected"]="llm.model_selected"
    run_id:str
    model:str
    strategy:str#计划
    ts:str

class LogLineEvent(BaseModel):
    type:Literal["log.line"]="log.line"
    run_id:str
    level:str #信息日志：debug info warning error
    source:str
    message:str
    ts:str

class SessionCreatedEvent(BaseModel):
    type: Literal["session.created"] = "session.created"
    session_id: str
    mode: str
    ts: str

class SessionMessageReceivedEvent(BaseModel):
    type: Literal["session.message_received"] = "session.message_received"
    session_id: str
    content: str
    ts: str

class SessionWaitingForInputEvent(BaseModel):
    type: Literal["session.waiting_for_input"] = "session.waiting_for_input"
    session_id: str
    last_run_id: str
    ts: str

class SessionResumedEvent(BaseModel):
    type: Literal["session.resumed"] = "session.resumed"
    session_id: str
    ts: str

class SessionClosedEvent(BaseModel):
    type: Literal["session.closed"] = "session.closed"
    session_id: str
    ts: str



# 根据 type 字段决定事件类型的判别联合 这里表示每个时间都可以写成现在的事情
Event = Annotated[
    CoreStartedEvent
    | RunStartedEvent
    | RunFinishedEvent
    | StepStartedEvent
    | StepFinishedEvent
    | ToolCallStartedEvent
    | ToolCallFinishedEvent
    | ToolCallFailedEvent
    | LLMTokenEvent
    | LLMUserEvent
    | LLMModelSelectedEvent
    | LogLineEvent
    | SessionCreatedEvent
    | SessionMessageReceivedEvent
    | SessionWaitingForInputEvent
    | SessionResumedEvent
    | SessionClosedEvent,
    #优先读取type
    Discriminator("type"),
]








