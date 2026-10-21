#给工具类的注册表
from __future__ import annotations
from myclaude.core.tools.base import BaseTool

class ToolRegistry:
    def __init__(self)->None:
        self._tools:dict[str,BaseTool]={}
        #工具的注册表,覆盖同一个名字
    def register(self,tool:BaseTool)->None:
        self._tools[tool.name]=tool

        #工具的查找没有就是none

    def get(self,name:str)->BaseTool | None:
        return self._tools.get(name)



    #返回所有的工具表 并且把所有的工具作用返回
    def tool_schemas(self)->list[dict[str,object]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            }
            for tool in self._tools.values()
        ]
