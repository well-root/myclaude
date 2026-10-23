from __future__ import annotations
from typing import Literal, Annotated

from pydantic import BaseModel, Discriminator


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
    type:Literal["event.subscriber"]="event.subscriber"
    topic:list[str] #定义得如["step.*"]模式
    scope:str="global"
    replay_from_run:str | None=None

class EventSubscriberResult(BaseModel):
    subscriber_id:str
    replayed_count:int=0




#根据type()来决定类型的判别联合
Command=Annotated[
    PingCommand,
    Discriminator("type"),
]


