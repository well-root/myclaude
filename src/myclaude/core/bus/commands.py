from __future__ import annotations
from typing import Literal, Annotated,Any

from pydantic import BaseModel, Discriminator
from myclaude.core.session.model import SessionMode,SessionStatus

class PingCommand(BaseModel):
    type:Literal["core.ping"]="core.ping"
    client:str

class PongResult(BaseModel):
    server_version:str
    uptime_ms:int
    received_at:str

class AgentRunCommand(BaseModel):
    type:Literal["agent.run"]="agent.run"
    goal:str


class AgentRunResult(BaseModel):
    run_id:str

class EventSubscriberCommand(BaseModel):
    type:Literal["event.subscribe"]="event.subscribe"
    topic:list[str] #定义得如["step.*"]模式
    scope:str="global"
    replay_from_run:str | None=None

class EventSubscriberResult(BaseModel):
    subscriber_id:str
    replayed_count:int=0

class SessionCreateCommand(BaseModel):
    type: Literal["session.create"] = "session.create"
    mode: SessionMode = "chat"
    title: str = ""


class SessionCreateResult(BaseModel):
    session_id: str
    status: SessionStatus


class SessionSendMessageCommand(BaseModel):
    type: Literal["session.send_message"] = "session.send_message"
    session_id: str
    content: str


class SessionSendMessageResult(BaseModel):
    run_id: str


class SessionGetHistoryCommand(BaseModel):
    type: Literal["session.get_history"] = "session.get_history"
    session_id: str


class SessionGetHistoryResult(BaseModel):
    messages: list[dict[str, Any]]


class SessionCloseCommand(BaseModel):
    type: Literal["session.close"] = "session.close"
    session_id: str


class SessionCloseResult(BaseModel):
    status: SessionStatus


class PermissionRespondCommand(BaseModel):
    type: Literal["permission.respond"] = "permission.respond"
    tool_use_id: str
    # "allow_once" | "always_allow" | "deny_once" | "always_deny"
    decision: str


class PermissionRespondResult(BaseModel):
    ok: bool = True


#根据type()来决定类型的判别联合
Command=Annotated[
    PingCommand
    |AgentRunCommand
    |EventSubscriberResult
    |SessionCreateCommand
    |SessionSendMessageCommand
    |SessionGetHistoryCommand
    |SessionCloseCommand
    |PermissionRespondCommand,
    Discriminator("type"),
]


