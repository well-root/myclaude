from __future__ import annotations

import asyncio

from myclaude.cli.commands.run import StdoutPrinter
from myclaude.core.bus.events import (
    LLMTokenEvent,
    RunFinishedEvent,
    RunStartedEvent,
    StepFinishedEvent,
    StepStartedEvent,
    ToolCallFailedEvent,
    ToolCallFinishedEvent,
    ToolCallStartedEvent,
)

TS = "2026-10-25T00:00:00+00:00"


def test_run_lifecycle(capsys) -> None:
    printer = StdoutPrinter()

    async def run() -> None:
        await printer.handle(RunStartedEvent(run_id="r1", goal="g", ts=TS))
        await printer.handle(StepStartedEvent(run_id="r1", step=1, ts=TS))
        await printer.handle(LLMTokenEvent(run_id="r1", token="hello", ts=TS))
        await printer.handle(LLMTokenEvent(run_id="r1", token=" world", ts=TS))
        await printer.handle(StepFinishedEvent(run_id="r1", step=1, ts=TS))
        await printer.handle(
            ToolCallStartedEvent(
                run_id="r1",
                tool_use_id="t1",
                tool_name="read_file",
                params={"path": "README.md"},
                ts=TS,
            )
        )
        await printer.handle(
            ToolCallFinishedEvent(
                run_id="r1",
                tool_use_id="t1",
                tool_name="read_file",
                elapsed_ms=3,
                ts=TS,
            )
        )
        await printer.handle(
            RunFinishedEvent(run_id="r1", status="success", steps=1, ts=TS)
        )

    asyncio.run(run())
    out = capsys.readouterr().out

    assert "[run] r1" in out
    assert "hello world" in out
    assert "[step 1] done" in out
    assert "[tool] read_file" in out
    assert "[run] success  1 steps" in out


def test_tool_failure_uses_error_msg(capsys) -> None:
    printer = StdoutPrinter()

    asyncio.run(
        printer.handle(
            ToolCallFailedEvent(
                run_id="r1",
                tool_use_id="t1",
                tool_name="read_file",
                error_type="permission",
                error_msg="permission denied",
                elapsed_ms=1,
                ts=TS,
            )
        )
    )

    err = capsys.readouterr().err
    assert "permission denied" in err
    assert "✗" in err