from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

TaskStatus = Literal["pending", "in_progress", "completed"]


@dataclass
class Task:
    id: int
    subject: str
    description: str
    status: TaskStatus
    blocked_by: list[int]
    created_at: str
    updated_at: str
#序列号为dict
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "subject": self.subject,
            "description": self.description,
            "status": self.status,
            "blocked_by": list(self.blocked_by),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    # 从 dict 构造 Task；对脏数据做最小防御
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Task:
        status = str(data.get("status", "pending"))
        if status not in ("pending", "in_progress", "completed"):
            status = "pending"
        return cls(
            id=int(data["id"]),
            subject=str(data["subject"]),
            description=str(data.get("description", "")),
            status=status,  # type: ignore[arg-type]
            blocked_by=[int(x) for x in data.get("blocked_by", [])],
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
        )