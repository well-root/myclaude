from __future__ import annotations

from myclaude.tui.app import MyClaudeTuiApp


class FakeLog:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def write(self, text: str) -> None:
        self.lines.append(text)


def test_tokens_are_buffered_until_non_token_event() -> None:
    app = MyClaudeTuiApp("127.0.0.1", 1)
    log = FakeLog()

    app.handle_event(
        {"type": "llm.token", "token": "Hel"}, log
    )
    app.handle_event(
        {"type": "llm.token", "token": "lo"}, log
    )
    assert log.lines == []

    app.handle_event(
        {"type": "step.started", "step": 1}, log
    )

    assert log.lines[0] == "Hello"
    assert "step 1" in log.lines[1]


def test_run_finished_failure_is_red() -> None:
    app = MyClaudeTuiApp("127.0.0.1", 1)
    log = FakeLog()

    app.handle_event(
        {
            "type": "run.finished",
            "status": "failed",
            "steps": 2,
            "reason": "llm_error",
        },
        log,
    )

    assert len(log.lines) == 1
    line = log.lines[0]
    assert "run failed" in line
    assert "red" in line
    assert "llm_error" in line


def test_flush_discards_whitespace_only() -> None:
    app = MyClaudeTuiApp("127.0.0.1", 1)
    log = FakeLog()

    app.handle_event(
        {"type": "llm.token", "token": "   "}, log
    )
    app.handle_event(
        {"type": "step.started", "step": 1}, log
    )

    assert all("   " != line for line in log.lines)