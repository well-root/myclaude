from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from myclaude.core.task.model import Task, TaskStatus


def _now() -> str:
    return datetime.now(UTC).isoformat()

class TaskManager:
    # 初始化：确保目录存在，扫描现有文件确定下一个 ID
    def __init__(self, tasks_dir: Path) -> None:
        self._dir = tasks_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._next_id = self.max_id() + 1

    #只认数值
    def task_files(self) -> list[Path]:
        return [
            p
            for p in self._dir.glob("task_*.json")
            if p.stem[5:].isdigit()
        ]
#返回最大id
    def max_id(self) -> int:
        ids = [int(p.stem[5:]) for p in self.task_files()]
        return max(ids) if ids else 0

    # 读取指定 ID 的任务文件
    def load(self, task_id: int) -> Task:
        path = self._dir / f"task_{task_id}.json"
        if not path.exists():
            raise ValueError(f"task {task_id} not found")
        return Task.from_dict(
            json.loads(path.read_text(encoding="utf-8"))
        )

    # 将任务写入对应 JSON 文件
    def save(self, task: Task) -> None:
        path = self._dir / f"task_{task.id}.json"
        path.write_text(
            json.dumps(task.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # 创建新任务，写入 JSON 文件，返回 Task
    def create(
            self,
            subject: str,
            description: str = "",
            blocked_by: list[int] | None = None,
    ) -> Task:
        for dep_id in blocked_by or []:
            if not (self._dir / f"task_{dep_id}.json").exists():
                raise ValueError(f"blocked_by task {dep_id} not found")

        now = _now()
        task = Task(
            id=self._next_id,
            subject=subject,
            description=description,
            status="pending",
            blocked_by=sorted(set(blocked_by or [])),
            created_at=now,
            updated_at=now,
        )
        self.save(task)
        self._next_id += 1
        return task

    # 读取指定 ID 的任务
    def get(self, task_id: int) -> Task:
        return self.load(task_id)

    # 更新任务状态或依赖列表；status="completed" 时自动清理其他任务的 blocked_by
    def update(
            self,
            task_id: int,
            *,
            status: TaskStatus | None = None,
            add_blocked_by: list[int] | None = None,
            remove_blocked_by: list[int] | None = None,
    ) -> Task:
        task = self.load(task_id)

        if status is not None:
            if status not in ("pending", "in_progress", "completed"):
                raise ValueError(f"invalid status: {status!r}")
            task.status = status
            if status == "completed":
                self.clear_dependency(task_id)

        if add_blocked_by:
            for dep_id in add_blocked_by:
                if dep_id == task_id:
                    raise ValueError("a task cannot block itself")
                if not (self._dir / f"task_{dep_id}.json").exists():
                    raise ValueError(f"blocked_by task {dep_id} not found")
            task.blocked_by = sorted(
                set(task.blocked_by + add_blocked_by)
            )

        if remove_blocked_by:
            task.blocked_by = [
                x for x in task.blocked_by
                if x not in remove_blocked_by
            ]

        task.updated_at = _now()
        self.save(task)
        return task

    # 返回所有任务，按 ID 升序排列
    def list_all(self) -> list[Task]:
        tasks: list[Task] = []
        for f in sorted(
                self.task_files(), key=lambda p: int(p.stem[5:])
        ):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                tasks.append(Task.from_dict(data))
            except (ValueError, KeyError, TypeError):
                # 单个损坏文件不应该让整个 task_list 失败
                continue
        return tasks

    # 将 completed_id 从所有其他任务的 blocked_by 列表中移除
    def clear_dependency(self, completed_id: int) -> None:
        for f in self.task_files():
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (ValueError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            try:
                blocked = [
                    int(x)
                    for x in data.get("blocked_by", [])
                ]
            except (ValueError, TypeError):
                continue
            if completed_id in blocked:
                data["blocked_by"] = [
                    x for x in blocked if x != completed_id
                ]
                data["updated_at"] = _now()
                f.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )

    # 格式化任务列表摘要，供 task_list 工具返回给 Agent
    def format_list(self) -> str:
        tasks = self.list_all()
        if not tasks:
            return "No tasks."
        marker = {
            "pending": "[ ]",
            "in_progress": "[>]",
            "completed": "[x]",
        }
        lines: list[str] = []
        for t in tasks:
            blocked = (
                f" (blocked by: {t.blocked_by})"
                if t.blocked_by
                else ""
            )
            lines.append(
                f"{marker.get(t.status, '[?]')} "
                f"#{t.id}: {t.subject}{blocked}"
            )
        return "\n".join(lines)

