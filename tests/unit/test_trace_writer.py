from __future__ import annotations

import json

import pytest

from myclaude.core.trace.record import TraceRecord
from myclaude.core.trace.writer import TraceWriter


def _record(kind: str = "event") -> TraceRecord:
    return TraceRecord(
        ts="2026-05-19T10:00:00+00:00",
        direction="CORE",
        layer="event",
        kind=kind,
        run_id="run-1",
        data={"type": "run.started", "text": "你好→"},
    )


@pytest.mark.asyncio
async def test_emit_writes_ndjson_in_order(tmp_path) -> None:
    path = tmp_path / "traces" / "daemon.jsonl"
    writer = TraceWriter(path)
    await writer.start()

    writer.emit(_record("a"))
    writer.emit(_record("b"))
    writer.emit(_record("c"))
    await writer.stop()

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    kinds = [TraceRecord.model_validate_json(x).kind for x in lines]
    assert kinds == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_stop_drains_queue_before_cancel(tmp_path) -> None:
    path = tmp_path / "daemon.jsonl"
    writer = TraceWriter(path)
    await writer.start()

    for _ in range(50):
        writer.emit(_record())
    await writer.stop()

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 50
    assert json.loads(lines[0])["data"]["text"] == "你好→"


@pytest.mark.asyncio
async def test_start_is_idempotent(tmp_path) -> None:
    path = tmp_path / "daemon.jsonl"
    writer = TraceWriter(path)

    await writer.start()
    await writer.start()
    writer.emit(_record())
    await writer.stop()

    assert len(path.read_text(encoding="utf-8").splitlines()) == 1