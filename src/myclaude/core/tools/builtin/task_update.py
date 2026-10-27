from __future__ import annotations
import json
from typing import Any,cast
from myclaude.core.task.manager import TaskManager
from myclaude.core.task.model import TaskStatus
from myclaude.core.tools.base import BaseTool,ToolResult

class TaskUpdateTool(BaseTool):
    name = "task_update"
    description = (
        "Update a task's status or dependency list. "
        "Set status to 'in_progress' when starting work on a task, "
        "'completed' when finished "
        "(automatically clears it from other tasks' blocked_by). "
        "Returns the updated task as JSON."
    )
    input_schema: dict[str, object] = {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "integer",
                "description": "ID of the task to update.",
            },
            "status": {
                "type": "string",
                "enum": ["pending", "in_progress", "completed"],
                "description": "New status for the task.",
            },
            "add_blocked_by": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Task IDs to add to blocked_by.",
            },
            "remove_blocked_by": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Task IDs to remove from blocked_by.",
            },
        },
        "required": ["task_id"],
    }


    #用taskmannager实列 提供invoke
    def __init__(self,task_manager: TaskManager)->None:
        self.manager=task_manager

    #进行更新的定义
    async def invoke(self, params: dict[str, object]) -> ToolResult:
        raw_add: Any = params.get("add_blocked_by") or []
        raw_rem: Any = params.get("remove_blocked_by") or []

        try:
            task_id = int(str(params["task_id"]))
            status_raw = params.get("status")
            status: TaskStatus | None = None
            if status_raw is not None:
                status = cast(TaskStatus, str(status_raw))

            if not isinstance(raw_add, list):
                raise ValueError("add_blocked_by must be an array")
            if not isinstance(raw_rem, list):
                raise ValueError("remove_blocked_by must be an array")

            add_blocked = [int(str(x)) for x in raw_add]
            remove_blocked = [int(str(x)) for x in raw_rem]

            task = self.manager.update(
                task_id,
                status=status,
                add_blocked_by=add_blocked or None,
                remove_blocked_by=remove_blocked or None,
            )
            return ToolResult(
                content=json.dumps(
                    task.to_dict(), ensure_ascii=False
                )
            )
        except (ValueError, TypeError) as exc:
            return ToolResult(
                content=str(exc),
                is_error=True,
                error_type="runtime_error",
            )