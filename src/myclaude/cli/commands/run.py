#把订阅的事件格式化 然后打印
from __future__ import annotations
import asyncio
import json
import sys
import time
from pydantic import BaseModel
from typing import Any
from myclaude.core.config import myclaudeconfig
from myclaude.core.transport.socket_client import IpcError, SocketClient

_TOPICS = ["run.*", "step.*", "tool.*", "llm.*", "log.*"]
class StdoutPrinter:
    #把事务进程打印到终端
    def __init__(self)->None:
        #当前输出是否处在行内模式
        self.inline=False
        #本次 run 的起始时间戳
        self.run_start:float=0.0



    def ensure_newline(self)->None:
        if self.inline:
            print()
            self.inline=False

#推过来的可能是dict也可能是pydantiic
    async def handle(self,event:BaseModel|dict[str,Any])->None:
        if isinstance(event,BaseModel):
            event=event.model_dump()
        t = event.get("type", "")
        if t == "llm.token":
            print(event.get("token", ""), end="", flush=True)
            self.inline = True
            return

        self.ensure_newline()

        if t == "run.started":
            self.run_start = time.monotonic()
            print(f"[run] {event.get('run_id', '')}")

        elif t == "step.started":
            print(f"[step {event.get('step')}] planning...")

        elif t == "tool.call_started":
            params_str = json.dumps(event.get("params", {}), ensure_ascii=False)
            print(f"[tool] {event.get('tool_name', '')} {params_str}")

        elif t == "tool.call_finished":
            print(f"[tool] {event.get('tool_name', '')} ✓  {event.get('elapsed_ms', 0)}ms")

        elif t == "tool.call_failed":
            print(
                f"[tool] {event.get('tool_name', '')} ✗  {event.get('error_msg', '')}",
                file=sys.stderr,
            )

        elif t == "step.finished":
            print(f"[step {event.get('step')}] done")

        elif t == "run.finished":
            elapsed = time.monotonic() - self.run_start
            print(
                f"[run] {event.get('status')}  "
                f"{event.get('steps', 0)} steps  {elapsed:.1f}s"
            )

#执行命令
def cmd_run(goal:str,config:myclaudeconfig)->None:
    try:
        exit_code = asyncio.run(_run_via_daemon(goal, config))
    except KeyboardInterrupt:
        sys.exit(130)
    except IpcError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
    except (ConnectionRefusedError, OSError) as e:
        print(
            f"error: core not running ({config.host}:{config.port}): {e}\n"
            f"hint: myclaude core start",
            file=sys.stderr,
        )
        sys.exit(1)
    sys.exit(exit_code)

async def _run_via_daemon(goal: str, config: myclaudeconfig) -> int:
    printer = StdoutPrinter()
    client = SocketClient(config.host, config.port)
    await client.connect()

    finished = asyncio.Event()
    exit_code = 0
    run_id: str | None = None
    buffered: list[dict[str, Any]] = []

    async def process(event: dict[str, Any]) -> None:
        nonlocal exit_code
        await printer.handle(event)
        if event.get("type") == "run.finished" and event.get("run_id") == run_id:
            if event.get("status") != "success":
                exit_code = 1
            finished.set()

    async def on_event(event: dict[str, Any]) -> None:
        if run_id is None:
            # agent.run 的响应还没回来，先缓存推来的事件
            buffered.append(event)
            return
        await process(event)

    client.on_event(on_event)
    loop_task = asyncio.create_task(client.run_event_loop())

    try:
        # 必须先订阅再触发 run，否则漏掉 run.started
        await client.send_command(
            "event.subscribe",
            {"topic": _TOPICS, "scope": "global"},
        )
        result = await client.send_command("agent.run", {"goal": goal})
        run_id = result["run_id"]

        # 补放 run.started 等早到的事件
        pending, buffered = buffered, []
        for event in pending:
            await process(event)

        # 事件流正常结束 或 连接断开，谁先到就退出
        fin = asyncio.create_task(finished.wait())
        done, _ = await asyncio.wait(
            {fin, loop_task}, return_when=asyncio.FIRST_COMPLETED
        )
        fin.cancel()
        if loop_task in done and not finished.is_set():
            print("error: connection to core lost", file=sys.stderr)
            return 1
        return exit_code

    finally:
        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass
        await client.close()




