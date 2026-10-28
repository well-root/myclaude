from __future__ import annotations
import json
import sys
import time
from pathlib import Path
from myclaude.core.config import myclaudeconfig
from myclaude.core.trace.record import TraceRecord

_COLORS = {
    "CLIENT→CORE": "\033[36m",
    "CORE→CLIENT": "\033[33m",
    "CORE": "\033[32m",
    "CORE→LLM": "\033[35m",
    "LLM→CORE": "\033[34m",
}
_RESET = "\033[0m"
_BOLD = "\033[1m"


#从jsonl读取并且展示
def cmd_trace(
        config:myclaudeconfig,
        run_id:str|None=None,
        *,
        layer:str |None=None,
        direction:str |None=None,
        raw:bool=False,
        follow:bool=False,
)->None:
    try:
        sys.stdout.reconfigure(encoding="utf-8",errors="replace")
    except (AttributeError,ValueError):
        pass

    trace_path=Path(config.trace.trace_file).expanduser()
    if not trace_path.exists():
        print(
            f"trace file not found: {trace_path}",
            file=sys.stderr,
        )
        print(
            "Start the daemon first, or set [trace].file / "
            "MYCLAUDE_TRACE_FILE.",
            file=sys.stderr,
        )
        sys.exit(1)

    with open(trace_path, encoding="utf-8") as f:
        for line in f:
            _process_line(
                line.strip(),
                run_id=run_id,
                layer=layer,
                direction=direction,
                raw=raw,
            )

    if not follow:
        return

    with open(trace_path, encoding="utf-8") as f:
        f.seek(0, 2)
        try:
            while True:
                line = f.readline()
                if line:
                    _process_line(
                        line.strip(),
                        run_id=run_id,
                        layer=layer,
                        direction=direction,
                        raw=raw,
                    )
                else:
                    time.sleep(0.05)
        except KeyboardInterrupt:
            return

def _process_line(
        line:str,
        *,
        run_id:str |None=None,
        layer:str |None=None,
        direction:str |None=None,
        raw:bool,
)->None:
    if not line:
        return
    try:
        record = TraceRecord.model_validate(json.loads(line))
    except Exception:
        return

    if run_id is not None and record.run_id != run_id:
        return
    if layer is not None and record.layer != layer:
        return
    if direction is not None and record.direction != direction:
        return

    if raw:
        print(line)
    else:
        _print_record(record)

def _print_record(record:TraceRecord)->None:
    color = _COLORS.get(record.direction, "")
    ts = record.ts[11:23] if len(record.ts) >= 23 else record.ts

    direction_str = (
        f"{color}{_BOLD}{record.direction:<14}{_RESET}"
    )
    kind_str = f"{record.kind:<13}"

    parts: list[str] = []
    if record.run_id:
        parts.append(f"run={record.run_id[:8]}")
    if record.step is not None:
        parts.append(f"step={record.step}")
    parts.append(_summarize(record))

    print(
        f"{ts}  {direction_str}  {kind_str}  "
        f"{'  '.join(parts)}"
    )


# 从 data 字段提取关键摘要（不输出大型 payload）
def _summarize(record: TraceRecord) -> str:
    data = record.data
    kind = record.kind

    if kind == "command":
        params = data.get("params") or {}
        goal = (
            str(params.get("goal", ""))
            if isinstance(params, dict)
            else ""
        )
        suffix = f'  goal="{goal[:50]}"' if goal else ""
        return f"method={data.get('method')}{suffix}"

    if kind == "response":
        result = data.get("result")
        if isinstance(result, dict) and "run_id" in result:
            return f"run_id={str(result['run_id'])[:8]}"
        return str(result)[:60]

    if kind == "error":
        err = data.get("error") or {}
        return (
            f"code={err.get('code')}  "
            f"{err.get('message', '')}"
        )

    if kind == "push":
        return (
            f"event={data.get('event_type')}  "
            f"sub={data.get('sub_id')}"
        )

    if kind == "event":
        return f"type={data.get('type')}"

    if kind == "api_call":
        msgs = data.get("messages")
        count = (
            len(msgs)
            if isinstance(msgs, list)
            else data.get("message_count", "?")
        )
        tools = data.get("tool_schemas")
        tool_count = (
            len(tools)
            if isinstance(tools, list)
            else data.get("tool_count", "?")
        )
        return f"msgs={count}  tools={tool_count}"

    if kind == "api_response":
        usage = data.get("usage") or {}
        return (
            f"stop={data.get('stop_reason')}  "
            f"latency={data.get('latency_ms')}ms  "
            f"out_tokens={usage.get('output_tokens', '?')}"
        )

    return str(data)[:60]


