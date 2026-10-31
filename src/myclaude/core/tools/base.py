from __future__ import  annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar
from pydantic import BaseModel
@dataclass
class ToolResult:
    content:str
    is_error:bool=False
    error_type:str | None=None#错误leix

#工具失败也返回 ToolResult(is_error=True)，不向调用方抛异常。

class BaseTool(ABC):
    name:str
    description:str
    input_schema:dict[str, str]
    #可选的参数模型 设置后调用
    params_model:ClassVar[type[BaseModel] |None]=None

    #执行工具调用
    @abstractmethod
    async def invoke(self,params:dict[str,object])->ToolResult:...

