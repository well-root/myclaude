from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any,Literal
SessionStatus = Literal["active", "waiting_for_input", "closed"]
SessionMode = Literal["one_shot", "chat"]

@dataclass
class Session:
    id:str
    mode:SessionMode
    status:SessionStatus
    title:str
    created_at:str
    updated_at:str
    run_ids:list[str]=field(default_factory=list)

    #把sessio写成简单的dict
    def to_dict(self) -> dict[str, Any]:
        return {
            "id":self.id,
            "mode":self.mode,
            "status":self.status,
            "title":self.title,
            "created_at":self.created_at,
            "updated_at":self.updated_at,
            "run_ids":list(self.run_ids),
        }

    #还原成session对象给llm读取
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Session:
        return cls(
            id=str(data["id"]),
            mode=data["mode"],
            status=data["status"],
            title=data["title"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            run_ids=[str(x) for x in data.get("run_ids", [])],
        )

