from __future__ import annotations

import json

import pytest

from myclaude.core.bus.events import (
    RunStartedEvent,
    StepStartedEvent,
    ToolCallStartedEvent,
)
from myclaude.core.transport.ipc_broadcaster import (
    IpcEventBroadcaster,
)


class FakeWriter:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.chunks: list[bytes] = []
        self.closed = False

    def write(self, data: bytes) -> None:
        if self.fail:
            raise ConnectionResetError("boom")
        self.chunks.append(data)

    async def drain(self) -> None:
        if self.fail:
            raise ConnectionResetError("boom")

    def get_extra_info(self, *args, **kwargs):
        return ("127.0.0.1", 12345)

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        pass


def _events(writer: FakeWriter) -> list[dict]:
    raw = b"".join(writer.chunks)
    return [
        json.loads(line)["event"]
        for line in raw.splitlines()
        if line
    ]


@pytest.mark.asyncio
async def test_topic_filter() -> None:
    broadcaster = IpcEventBroadcaster()
    writer = FakeWriter()
    broadcaster.subscribe(writer, ["run.*"])

    await broadcaster.handle(
        RunStartedEvent(run_id="r1", goal="g", ts="t")
    )
    await broadcaster.handle(
        StepStartedEvent(run_id="r1", step=1, ts="t")
    )

    events = _events(writer)
    assert len(events) == 1
    assert events[0]["type"] == "run.started"


@pytest.mark.asyncio
async def test_scope_filter() -> None:
    broadcaster = IpcEventBroadcaster()
    writer = FakeWriter()
    broadcaster.subscribe(writer, ["run.*"], scope="run:r2")

    await broadcaster.handle(
        RunStartedEvent(run_id="r1", goal="g", ts="t")
    )
    await broadcaster.handle(
        RunStartedEvent(run_id="r2", goal="g", ts="t")
    )

    events = _events(writer)
    assert len(events) == 1
    assert events[0]["run_id"] == "r2"


@pytest.mark.asyncio
async def test_two_subscribers_both_receive() -> None:
    broadcaster = IpcEventBroadcaster()
    w1 = FakeWriter()
    w2 = FakeWriter()
    broadcaster.subscribe(w1, ["run.*"])
    broadcaster.subscribe(w2, ["run.*"])

    await broadcaster.handle(
        RunStartedEvent(run_id="r1", goal="g", ts="t")
    )

    assert len(_events(w1)) == 1
    assert len(_events(w2)) == 1


@pytest.mark.asyncio
async def test_unsubscribe() -> None:
    broadcaster = IpcEventBroadcaster()
    writer = FakeWriter()
    broadcaster.subscribe(writer, ["run.*"])
    broadcaster.unsubscribe(writer)

    await broadcaster.handle(
        RunStartedEvent(run_id="r1", goal="g", ts="t")
    )

    assert _events(writer) == []


@pytest.mark.asyncio
async def test_dead_connection_is_removed() -> None:
    broadcaster = IpcEventBroadcaster()
    writer = FakeWriter(fail=True)
    broadcaster.subscribe(writer, ["run.*"])

    await broadcaster.handle(
        RunStartedEvent(run_id="r1", goal="g", ts="t")
    )

    assert broadcaster.subscriptions == []


@pytest.mark.asyncio
async def test_tool_topic_matches_tool_events() -> None:
    broadcaster = IpcEventBroadcaster()
    writer = FakeWriter()
    broadcaster.subscribe(writer, ["tool.*"])

    await broadcaster.handle(
        ToolCallStartedEvent(
            run_id="r1",
            tool_use_id="t1",
            tool_name="read_file",
            params={"path": "README.md"},
            ts="t",
        )
    )

    events = _events(writer)
    assert len(events) == 1
    assert events[0]["type"] == "tool.call_started"