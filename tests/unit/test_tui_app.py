from __future__ import annotations

import pytest

from myclaude.tui.app import (
    LLMStreamBlock,
    MyClaudeTuiApp,
    ToolCallBlock,
)


class _TuiTestApp(MyClaudeTuiApp):
    # 不启动 socket worker，只测渲染逻辑
    def on_mount(self) -> None:
        pass


@pytest.mark.asyncio
async def test_llm_tokens_accumulate_in_one_block() -> None:
    app = _TuiTestApp("127.0.0.1", 1)
    async with app.run_test() as pilot:
        app._handle_event({"type": "run.started", "run_id": "r1", "goal": "g"})
        app._handle_event({"type": "llm.token", "token": "Hello"})
        app._handle_event({"type": "llm.token", "token": " world"})
        await pilot.pause()

        blocks = list(app.query(LLMStreamBlock))
        assert len(blocks) == 1
        assert blocks[0]._text == "Hello world"

        app._handle_event(
            {
                "type": "step.finished",
                "run_id": "r1",
                "step": 1,
            }
        )
        await pilot.pause()
        assert app._current_llm is None
        assert blocks[0]._finalized is True


@pytest.mark.asyncio
async def test_tool_block_finishes_and_expands() -> None:
    app = _TuiTestApp("127.0.0.1", 1)
    async with app.run_test() as pilot:
        app._handle_event(
            {
                "type": "tool.call_started",
                "tool_use_id": "t1",
                "tool_name": "bash",
                "params": {"command": "echo [hi]"},
            }
        )
        app._handle_event(
            {
                "type": "tool.call_finished",
                "tool_use_id": "t1",
                "elapsed_ms": 12,
                "output": "hi",
            }
        )
        await pilot.pause()

        block = app.query_one(ToolCallBlock)
        assert block._finished is True
        assert block._elapsed_ms == 12
        assert "hi" in block._summary()

        block.on_click()
        assert "expanded" in block.classes
        block.on_click()
        assert "expanded" not in block.classes


@pytest.mark.asyncio
async def test_tool_failure_uses_error_msg() -> None:
    app = _TuiTestApp("127.0.0.1", 1)
    async with app.run_test() as pilot:
        app._handle_event(
            {
                "type": "tool.call_started",
                "tool_use_id": "t2",
                "tool_name": "bash",
                "params": {"command": "false"},
            }
        )
        app._handle_event(
            {
                "type": "tool.call_failed",
                "tool_use_id": "t2",
                "elapsed_ms": 3,
                "error_msg": "boom",
            }
        )
        await pilot.pause()

        block = app.query_one(ToolCallBlock)
        assert block._is_error is True
        assert "boom" in block._summary()


@pytest.mark.asyncio
async def test_markup_in_params_does_not_crash() -> None:
    app = _TuiTestApp("127.0.0.1", 1)
    async with app.run_test() as pilot:
        app._handle_event(
            {
                "type": "tool.call_started",
                "tool_use_id": "t3",
                "tool_name": "write_file",
                "params": {
                    "path": "a.py",
                    "content": "x = [1, 2, 3]",
                },
            }
        )
        app._handle_event(
            {
                "type": "tool.call_finished",
                "tool_use_id": "t3",
                "elapsed_ms": 1,
                "output": "[ok]",
            }
        )
        await pilot.pause()

        block = app.query_one(ToolCallBlock)
        assert block._finished is True