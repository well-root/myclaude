from __future__ import annotations

import asyncio
import json
from typing import Any

from textual.app import App, ComposeResult
from textual.widgets import Label, RichLog

from myclaude.core.transport.socket_client import IpcError, SocketClient

class MyClaudeTuiApp(App[None]):
    #展示界面
    TITLE = "myclaude"
    BINDINGS = [("ctrl+q", "quit", "quit")]

    CSS = """
        Screen { layout: vertical; }
        #status {
            height: 1;
            background: $primary;
            color: $text;
            padding: 0 1;
        }
        #log { height: 1fr; }
        """
    def __init__(
            self,
            host: str,
            port: int,
            replay_run_id:str | None = None,
    )->None:
        super().__init__()
        self.host = host
        self.port = port
        self.replay_run_id = replay_run_id
        self.token_buf=""

    def compose(self) -> ComposeResult:
        yield Label("● connecting...", id="status")
        yield RichLog(
            id="log", highlight=True, markup=True
        )

    def on_mount(self) -> None:
        #交给textual的work
        self.run_worker(self.socket_loop(),exclusive=True,name="socket")

        """把每行token都写到一行"""
    def flush_token(self,log:RichLog)->None:
        if self.token_buf.split():
            log.write(self.token_buf)
        self.token_buf=""
#日志的处理
    def handle_event(self,event:dict[str, Any],log:RichLog)->None:
        t=event.get("type","")

        if t == "llm.token":
            self.token_buf+=event.get("text","")
            return
        #换
        self.flush_token(log)

        if t=="run.started":
            log.write(
                f"[bold blue]▶ run[/bold blue]  "
                f"{event.get('run_id', '')}  "
                f"{event.get('goal', '')}"
            )

        elif t == "step.started":
            log.write(
                f"[bold]  step {event.get('step')}[/bold]  "
                f"planning..."
            )

        elif t == "llm.user":
            log.write(
                f"[dim]  tokens in="
                f"{event.get('input_tokens', 0)} "
                f"out={event.get('output_tokens', 0)}[/dim]"
            )

        elif t == "tool.call_started":
            params = json.dumps(
                event.get("params", {}), ensure_ascii=False
            )
            log.write(
                f"[dim]  tool[/dim] "
                f"[bold]{event.get('tool_name', '')}[/bold] "
                f"{params}"
            )

        elif t == "tool.call_finished":
            log.write(
                f"[green]  ✓[/green] "
                f"{event.get('tool_name', '')}  "
                f"{event.get('elapsed_ms', 0)}ms"
            )

        elif t == "tool.call_failed":
            log.write(
                f"[red]  ✗[/red] "
                f"{event.get('tool_name', '')}  "
                f"{event.get('error_msg', '')}"
            )

        elif t == "step.finished":
            log.write(
                f"[dim]  step {event.get('step')} done[/dim]"
            )

        elif t == "run.finished":
            status = event.get("status", "")
            color = "green" if status == "success" else "red"
            reason = (
                f"  {event.get('reason')}"
                if event.get("reason")
                else ""
            )
            log.write(
                f"[bold {color}]■ run {status}"
                f"[/bold {color}]  "
                f"{event.get('steps', 0)} steps{reason}"
            )

        elif t == "log.line":
            log.write(
                f"[dim]{event.get('level', 'INFO')}[/dim] "
                f"{event.get('message', '')}"
            )

    async def socket_loop(self)->None:
        status=self.query_one("#status",Label)
        log=self.query_one("#log",RichLog)

        while True:
            client=SocketClient(self.host,self.port)
            try:
                await client.connect()
            except(ConnectionRefusedError,OSError):
                status.update("● not connected — retrying in 2s")

                await  asyncio.sleep(2)
                continue
            status.update(
                f"● connected  {self.host}:{self.port}"
            )
            loop_task = asyncio.create_task(
                client.run_event_loop()
            )

            async def on_event(event:dict[str, Any])->None:
                try:
                    self.handle_event(event,log)

                except Exception:
                    # 单个事件渲染失败不应该终止整条 socket 循环
                    log.write(
                        "[red]event handler error: "
                        f"{event.get('type')}[/red]"
                    )

                client.on_event(on_event)


                try:
                    params: dict[str, Any] = {
                        "topics": [
                            "run.*",
                            "step.*",
                            "tool.*",
                            "llm.token",
                            "llm.user",
                            "log.*",
                        ],
                        "scope": "global",
                    }

                    if self.replay_run_id is not None:
                        params["replay_run_id"] = (self.replay_run_id)

                    await  client.send_command(
                        "event.subscribe",params
                    )
                    await loop_task

                except(IpcError,OSError)as e:
                    status.update(f"● disconnected — {e}")

                finally:
                    if not loop_task.done():
                        loop_task.cancel()
                    self.flush_token(log)
                    await client.close()

                status.update(
                    "● disconnected — retrying in 2s"
                )
                await asyncio.sleep(2)

