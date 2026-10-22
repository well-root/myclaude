from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path

from myclaude.core.config import myclaudeconfig
from myclaude.core.context import ExecutionContext
from myclaude.core.events.bus import EventBus
from myclaude.core.llm.types import LLMResponse, ToolCallBlock
from myclaude.core.runner import AgentRunner
from myclaude.core.tools.invocation import invoke_tool
from myclaude.core.tools.registry import ToolRegistry


class FakeProvider:
    """不调用真实 API：第一次要求读文件，第二次直接结束。"""

    def __init__(self) -> None:
        self.calls = 0

    async def chat(
        self,
        messages: list[dict[str, object]],
        tool_schemas: list[dict[str, object]],
        bus: EventBus,
        run_id: str,
    ) -> LLMResponse:
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(
                stop_reason="tool_use",
                tool_calls=[
                    ToolCallBlock(id="t1", name="read_file", input={"path": "sample.txt"}),
                    ToolCallBlock(id="t2", name="read_file", input={"path": "sample.txt"}),
                ],
            )
        return LLMResponse(stop_reason="end_turn", text="done")


def check_context_merging() -> None:
    ctx = ExecutionContext(run_id="r1", goal="g", max_steps=5)
    ctx.add_assistant_messages([
        {"type": "tool_use", "id": "a", "name": "read_file", "input": {}},
        {"type": "tool_use", "id": "b", "name": "read_file", "input": {}},
    ])
    ctx.add_tool_result("a", "A")
    ctx.add_tool_result("b", "B")
    assert len(ctx.messages) == 3
    assert [b["tool_use_id"] for b in ctx.messages[-1]["content"]] == ["a", "b"]


async def check_unknown_tool() -> None:
    result = await invoke_tool(
        ToolRegistry(), ToolCallBlock(id="x", name="nope", input={}), EventBus(), "r1"
    )
    assert result.is_error and result.error_type == "runtime_error"


async def main() -> None:
    #单元检查
    check_context_merging()
    await check_unknown_tool()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)#见目录
        (root / "sample.txt").write_text("magic=7391\n", encoding="utf-8")
        old = os.getcwd()
        os.chdir(root)
        try:
            cfg = myclaudeconfig()
            cfg.agent.max_steps = 5
            provider = FakeProvider()
            runner = AgentRunner(cfg, provider=provider, run_dir=root / "runs")
            await runner.run("read sample.txt and report the magic number")
        finally:
            os.chdir(old)
#读取jsonl得到event
        files = list((root / "runs").rglob("events.jsonl"))
        assert len(files) == 1, files
        events = [
            json.loads(line)
            for line in files[0].read_text(encoding="utf-8").splitlines()
            if line
        ]
        types = [e["type"] for e in events]
        print("events:", types)
        assert types[0] == "run.started", types[0]
        assert types[-1] == "run.finished", types[-1]
        assert events[-1]["status"] == "success", events[-1]
        assert any(
            e["type"] == "tool.call_finished" and e["tool_name"] == "read_file"
            for e in events
        )
        assert sum(1 for e in events if e["type"] == "tool.call_finished") == 2
        print("SELFTEST OK  status=%s steps=%s" % (events[-1]["status"], events[-1]["steps"]))


if __name__ == "__main__":
    asyncio.run(main())