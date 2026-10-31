from __future__ import annotations

import json

import pytest

from myclaude.core.events.bus import EventBus
from myclaude.core.llm.types import (
    LLMResponse,
    ToolCallBlock,
    UsageStats,
)
from myclaude.core.trace.provider import TracingProvider
from myclaude.core.trace.writer import TraceWriter


class FakeProvider:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def chat(
        self,
        messages,
        tool_schemas,
        bus,
        run_id,
        *,
        step: int = 0,
        system:str|None = None,
    ) -> LLMResponse:
        self.calls.append(
            {
                "messages": messages,
                "step": step,
            }
        )
        return LLMResponse(
            stop_reason="tool_use",
            tool_calls=[
                ToolCallBlock(
                    id="tool-1",
                    name="bash",
                    input={"command": "ls"},
                )
            ],
            text="thinking",
            usage=UsageStats(
                input_tokens=10,
                output_tokens=5,
            ),
        )


def _read(path):
    return [
        json.loads(line)
        for line in path.read_text(
            encoding="utf-8"
        ).splitlines()
    ]


@pytest.mark.asyncio
async def test_records_both_directions(tmp_path) -> None:
    path = tmp_path / "daemon.jsonl"
    writer = TraceWriter(path)
    await writer.start()

    inner = FakeProvider()
    provider = TracingProvider(inner, writer)
    response = await provider.chat(
        messages=[{"role": "user", "content": "hi"}],
        tool_schemas=[{"name": "bash"}],
        bus=EventBus(),
        run_id="run-1",
        step=3,
    )
    await writer.stop()

    assert response.stop_reason == "tool_use"
    assert inner.calls[0]["step"] == 3

    rows = _read(path)
    assert [r["direction"] for r in rows] == [
        "CORE→LLM",
        "LLM→CORE",
    ]
    assert rows[0]["kind"] == "api_call"
    assert rows[1]["kind"] == "api_response"
    assert rows[0]["step"] == 3
    assert rows[1]["step"] == 3
    assert rows[1]["data"]["latency_ms"] >= 0
    assert rows[1]["data"]["tool_calls"][0]["name"] == "bash"


@pytest.mark.asyncio
async def test_payload_snapshot_survives_mutation(tmp_path) -> None:
    path = tmp_path / "daemon.jsonl"
    writer = TraceWriter(path)
    await writer.start()

    provider = TracingProvider(FakeProvider(), writer)
    messages = [{"role": "user", "content": "original"}]
    await provider.chat(
        messages=messages,
        tool_schemas=[],
        bus=EventBus(),
        run_id="run-1",
    )

    # emit() 之后改原列表，trace 里仍应是 original
    messages[0]["content"] = "mutated"
    await writer.stop()

    rows = _read(path)
    assert rows[0]["data"]["messages"][0]["content"] == "original"


@pytest.mark.asyncio
async def test_include_payload_false_only_summary(tmp_path) -> None:
    path = tmp_path / "daemon.jsonl"
    writer = TraceWriter(path)
    await writer.start()

    provider = TracingProvider(
        FakeProvider(), writer, include_payload=False
    )
    await provider.chat(
        messages=[{"role": "user", "content": "hi"}],
        tool_schemas=[{"name": "bash"}],
        bus=EventBus(),
        run_id="run-1",
    )
    await writer.stop()

    call = _read(path)[0]
    assert call["data"]["message_count"] == 1
    assert call["data"]["tool_count"] == 1
    assert "messages" not in call["data"]