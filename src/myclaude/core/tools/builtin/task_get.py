from __future__ import annotations

import json

from myclaude.core.task.manager import TaskManager
from myclaude.core.tools.base import BaseTool, ToolResult


class TaskGetTool(BaseTool):
    name = "task_get"
    description = (
        "Get full details of a task by its integer ID. "
        "Returns the task as JSON."
    )
    input_schema: dict[str, object] = {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "integer",
                "description": "ID of the task to retrieve.",
            },
        },
        "required": ["task_id"],
    }

    # 持有 TaskManager 实例，供 invoke 调用
    def __init__(self, task_manager: TaskManager) -> None:
        self._manager = task_manager

        #依旧返回json
    async def invoke(self,params:dict[str,object]) ->ToolResult:
        try:
            task_id = int(str(params["task_id"]))
            task=self._manager.get(task_id)
            return ToolResult(content=json.dumps(task.to_dict(),ensure_ascii=False))

        except (ValueError,TypeError) as exc:
            return ToolResult(
                content=str(exc),
                is_error=True,
                error_type="runtime_error",
            )