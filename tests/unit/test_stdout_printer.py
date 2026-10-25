from __future__ import annotations

import asyncio

from myclaude.cli.commands.run import StdoutPrinter


def test_run_lifecycle(capsys) -> None:
    printer = StdoutPrinter()

    async def run() -> None:
        await printer.handle(
            {"type": "run.started", "run_id": "r1"}
        )
        await printer.handle(
            {"type": "step.started", "step": 1}
        )
        await printer.handle(
            {"type": "llm.token", "token": "hello"}
        )
        await printer.handle(
            {"type": "llm.token", "token": " world"}
        )
        await printer.handle(
            {"type": "step.finished", "step": 1}
        )
        await printer.handle(
            {
                "type": "tool.call_started",
                "tool_name": "read_file",
                "params": {"path": "README.md"},
            }
        )
        await printer.handle(
            {
                "type": "tool.call_finished",
                "tool_name": "read_file",
                "elapsed_ms": 3,
            }
        )
        await printer.handle(
            {
                "type": "run.finished",
                "status": "success",
                "steps": 1,
            }
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
            {
                "type": "tool.call_failed",
                "tool_name": "read_file",
                "error_msg": "permission denied",
            }
        )
    )

    err = capsys.readouterr().err
    assert "permission denied" in err
    assert "✗" in err