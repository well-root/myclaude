from __future__ import annotations

from myclaude.core.task.model import Task


def test_task_roundtrip() -> None:
    task = Task(
        id=1,
        subject="分析目录结构",
        description="了解整体布局",
        status="in_progress",
        blocked_by=[2, 3],
        created_at="2026-05-19T10:00:01+00:00",
        updated_at="2026-05-19T10:00:45+00:00",
    )

    data = task.to_dict()
    restored = Task.from_dict(data)

    assert restored == task
    assert data["blocked_by"] == [2, 3]
    # to_dict 返回的是副本，改它不影响原 Task
    data["blocked_by"].append(4)
    assert task.blocked_by == [2, 3]


def test_from_dict_defaults_and_bad_status() -> None:
    task = Task.from_dict(
        {
            "id": "7",
            "subject": "写报告",
            "status": "wat",
        }
    )

    assert task.id == 7
    assert task.description == ""
    assert task.blocked_by == []
    assert task.status == "pending"