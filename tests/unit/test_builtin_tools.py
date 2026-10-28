from __future__ import annotations

import json
import sys

import pytest

from myclaude.core.task.manager import TaskManager
from myclaude.core.tools.builtin.bash import BashTool
from myclaude.core.tools.builtin.list_dir import ListDirTool
from myclaude.core.tools.builtin.task_create import TaskCreateTool
from myclaude.core.tools.builtin.task_get import TaskGetTool
from myclaude.core.tools.builtin.task_list import TaskListTool
from myclaude.core.tools.builtin.task_update import TaskUpdateTool
from myclaude.core.tools.builtin.write_file import WriteFileTool


@pytest.mark.asyncio
async def test_bash_echo_and_nonzero_exit() -> None:
    ok = await BashTool().invoke({"command": "echo hello"})
    assert ok.is_error is False
    assert "hello" in ok.content

    bad = await BashTool().invoke({"command": "exit 3"})
    assert bad.is_error is True
    assert "[exit 3]" in bad.content


@pytest.mark.asyncio
async def test_bash_timeout() -> None:
    if sys.platform == "win32":
        command = (
            f'"{sys.executable}" -c '
            '"import time; time.sleep(2)"'
        )
    else:
        command = (
            f"{sys.executable} -c "
            "'import time; time.sleep(2)'"
        )

    result = await BashTool().invoke(
        {"command": command, "timeout": 1}
    )
    assert result.is_error is True
    assert result.error_type == "timeout"


@pytest.mark.asyncio
async def test_write_file_and_traversal(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    tool = WriteFileTool()

    result = await tool.invoke(
        {"path": "sub/a.txt", "content": "你好"}
    )
    assert result.is_error is False
    assert (tmp_path / "sub" / "a.txt").read_text(
        encoding="utf-8"
    ) == "你好"

    with pytest.raises(PermissionError):
        await tool.invoke(
            {"path": "../escape.txt", "content": "x"}
        )


@pytest.mark.asyncio
async def test_list_dir_tree(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text(
        "print(1)", encoding="utf-8"
    )
    (tmp_path / "README.md").write_text(
        "hi", encoding="utf-8"
    )

    result = await ListDirTool().invoke({"path": "."})
    assert result.is_error is False
    assert "pkg/" in result.content
    assert "a.py" in result.content
    assert "README.md" in result.content

    with pytest.raises(PermissionError):
        await ListDirTool().invoke({"path": "../"})


@pytest.mark.asyncio
async def test_task_tools_share_same_manager(tmp_path) -> None:
    manager = TaskManager(tmp_path / ".tasks")
    create = TaskCreateTool(manager)
    update = TaskUpdateTool(manager)
    list_tool = TaskListTool(manager)
    get = TaskGetTool(manager)

    created = await create.invoke(
        {"subject": "分析目录", "description": "看结构"}
    )
    assert created.is_error is False
    task = json.loads(created.content)
    assert task["id"] == 1
    assert task["status"] == "pending"

    second = await create.invoke(
        {"subject": "写报告", "blocked_by": [task["id"]]}
    )
    assert second.is_error is False

    updated = await update.invoke(
        {"task_id": task["id"], "status": "completed"}
    )
    assert updated.is_error is False
    assert json.loads(updated.content)["status"] == "completed"

    listing = await list_tool.invoke({})
    assert "[x] #1: 分析目录" in listing.content
    assert "[ ] #2: 写报告" in listing.content
    assert "blocked by: []" not in listing.content

    detail = await get.invoke({"task_id": 2})
    assert json.loads(detail.content)["subject"] == "写报告"

    missing = await get.invoke({"task_id": 99})
    assert missing.is_error is True
    assert "not found" in missing.content