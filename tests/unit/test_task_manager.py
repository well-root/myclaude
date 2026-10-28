from __future__ import annotations

import json

import pytest

from myclaude.core.task.manager import TaskManager


def test_create_get_and_list(tmp_path) -> None:
    manager = TaskManager(tmp_path / ".tasks")

    first = manager.create("分析目录结构", "找出核心模块")
    second = manager.create("读取代码", blocked_by=[first.id])

    assert first.id == 1
    assert second.id == 2
    assert manager.get(1).subject == "分析目录结构"

    tasks = manager.list_all()
    assert [t.id for t in tasks] == [1, 2]
    assert "[ ] #1" in manager.format_list()
    assert "blocked by: [1]" in manager.format_list()


def test_completed_clears_dependency(tmp_path) -> None:
    manager = TaskManager(tmp_path / ".tasks")
    first = manager.create("第一步")
    second = manager.create("第二步", blocked_by=[first.id])

    manager.update(first.id, status="completed")

    assert manager.get(second.id).blocked_by == []


def test_add_and_remove_blocked_by(tmp_path) -> None:
    manager = TaskManager(tmp_path / ".tasks")
    a = manager.create("A")
    b = manager.create("B")
    c = manager.create("C")

    manager.update(c.id, add_blocked_by=[a.id, b.id])
    assert manager.get(c.id).blocked_by == [a.id, b.id]

    manager.update(c.id, remove_blocked_by=[a.id])
    assert manager.get(c.id).blocked_by == [b.id]


def test_missing_task_and_dependency(tmp_path) -> None:
    manager = TaskManager(tmp_path / ".tasks")

    with pytest.raises(ValueError, match="not found"):
        manager.get(99)

    with pytest.raises(ValueError, match="blocked_by task 99"):
        manager.create("bad", blocked_by=[99])

    with pytest.raises(ValueError, match="cannot block itself"):
        task = manager.create("self")
        manager.update(task.id, add_blocked_by=[task.id])


def test_invalid_status(tmp_path) -> None:
    manager = TaskManager(tmp_path / ".tasks")
    task = manager.create("A")

    with pytest.raises(ValueError, match="invalid status"):
        manager.update(task.id, status="done")  # type: ignore[arg-type]


def test_ignores_malformed_files_and_reads_utf8(tmp_path) -> None:
    tasks_dir = tmp_path / ".tasks"
    tasks_dir.mkdir()

    # 文件名不匹配 task_<数字>.json，必须被忽略
    (tasks_dir / "task_backup.json").write_text(
        "not json", encoding="utf-8"
    )
    # 数字文件名但内容损坏，list_all 跳过，_max_id 仍然认它
    (tasks_dir / "task_2.json").write_text(
        "{broken", encoding="utf-8"
    )

    manager = TaskManager(tasks_dir)
    task = manager.create("中文任务")

    assert task.id == 3
    assert manager.get(3).subject == "中文任务"
    assert [t.id for t in manager.list_all()] == [3]


def test_task_file_is_utf8_json(tmp_path) -> None:
    manager = TaskManager(tmp_path / ".tasks")
    task = manager.create("中文主题", "中文描述")

    path = tmp_path / ".tasks" / f"task_{task.id}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["subject"] == "中文主题"
    assert data["description"] == "中文描述"