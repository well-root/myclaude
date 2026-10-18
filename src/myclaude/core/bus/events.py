from __future__ import annotations
from typing import Any, Annotated,Literal
from pydantic import BaseModel, Discriminator

class CoreStartedEvent(BaseModel):
    type: Literal["core.started"]="core.started"
    listen_address: str #记录请求的地址
    version:str


class RunStartedEvent(BaseModel):
    type:Literal["core.started"]="core.started"
    version:str


