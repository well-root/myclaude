from typing import Literal, Annotated

from pydantic import BaseModel, Discriminator


class PingCommand(BaseModel):
    type:Literal["core.ping"]="core.ping"
    client:str

class PongCommand(BaseModel):
    server_version:str
    uptime_ms:str
    received_bytes:str

Command=Annotated[
    PingCommand,
    Discriminator("type"),
]

