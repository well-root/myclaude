from __future__ import annotations
from typing import Literal, Annotated

from pydantic import BaseModel, Discriminator


class PingCommand(BaseModel):
    type:Literal["core.ping"]="core.ping"
    client:str

class PongResult(BaseModel):
    server_version:str
    uptime_ms:str
    received_at:str
#根据type()来决定类型的判别联合
Command=Annotated[
    PingCommand,
    Discriminator("type"),
]


