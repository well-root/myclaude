# tui/app.py 展示画面（Ai）
from __future__ import annotations

import asyncio
import json
from typing import Any

from rich.markdown import Markdown as RichMarkdown
from rich.markup import escape
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import Label, Static

from myclaude.core.transport.socket_client import (
    IpcError,
    SocketClient,
)


def _preview(s: str, n: int) -> str:
    return s[:n] + "…" if len(s) > n else s


def _params_str(params: dict[str, Any]) -> str:
    return json.dumps(params, ensure_ascii=False)


class LLMStreamBlock(Static):
    """在同一个 Static widget 中累积 LLM 流式 token。"""

    DEFAULT_CSS = """
    LLMStreamBlock {
        height: auto;
        padding: 0 2;
        color: $text;
    }
    """

    def __init__(self) -> None:
        super().__init__("")
        self._text = ""
        self._finalized = False

    # 追加一个 token 并刷新显示
    def append_token(self, token: str) -> None:
        self._text += token
        self.update(self._text)

    # 流结束时把纯文本换成 Rich Markdown 渲染
    def finalize_markdown(self) -> None:
        if self._finalized:
            return
        self._finalized = True
        if self._text.strip():
            self.update(
                RichMarkdown(
                    self._text, code_theme="monokai"
                )
            )


class ToolCallBlock(Widget):
    """可折叠的工具调用块：折叠时显示摘要，点击展开细节。"""

    DEFAULT_CSS = """
    ToolCallBlock {
        height: auto;
        padding: 0 0;
    }
    ToolCallBlock > .detail {
        display: none;
        padding: 0 4;
        color: $text-muted;
    }
    ToolCallBlock.expanded > .detail {
        display: block;
    }
    """

    def __init__(
        self, tool_name: str, params: dict[str, Any]
    ) -> None:
        super().__init__()
        self._tool_name = tool_name
        self._params = params
        self._params_full = _params_str(params)
        self._output = ""
        self._elapsed_ms = 0
        self._is_error = False
        self._finished = False

    def compose(self) -> ComposeResult:
        yield Static(
            self._summary(), classes="summary"
        )
        yield Static("", classes="detail")

    # 生成摘要行文本
    def _summary(self) -> str:
        params_pre = escape(
            _preview(self._params_full, 60)
        )
        name = escape(self._tool_name)
        icon = "[bold yellow]✎[/bold yellow]"
        line = (
            f"  {icon} [bold]{name}[/bold]  "
            f"[dim]{params_pre}[/dim]"
        )
        if self._finished:
            out_pre = escape(_preview(self._output, 50))
            color = "red" if self._is_error else "dim"
            hint = (
                "  [dim]▸ click to expand[/dim]"
                if len(self._output) > 50
                else ""
            )
            line += (
                f"\n  [dim]↳[/dim] "
                f"[{color}]{out_pre}[/{color}]"
                f"  [dim]{self._elapsed_ms}ms[/dim]{hint}"
            )
        return line

    # 工具调用完成时更新结果并刷新摘要
    def set_result(
        self,
        output: str,
        elapsed_ms: int,
        *,
        is_error: bool = False,
    ) -> None:
        self._output = output
        self._elapsed_ms = elapsed_ms
        self._is_error = is_error
        self._finished = True
        if self.children:
            self.query_one(
                ".summary", Static
            ).update(self._summary())

    # 点击时切换展开/折叠
    def on_click(self) -> None:
        if not self._finished:
            return
        if "expanded" in self.classes:
            self.remove_class("expanded")
        else:
            detail = self.query_one(".detail", Static)
            detail.update(
                f"[dim]params:[/dim]\n"
                f"    {escape(self._params_full)}\n"
                f"[dim]output:[/dim]\n"
                f"    {escape(self._output)}\n"
                f"[dim]elapsed:[/dim] "
                f"{self._elapsed_ms}ms"
            )
            self.add_class("expanded")


class MyClaudeTuiApp(App[None]):
    """myclaude TUI：终端滚屏风格，实时展示 agent 执行过程。"""

    TITLE = "myclaude"
    BINDINGS = [
        Binding("ctrl+q", "quit", "quit"),
    ]
    CSS = """
    Screen { background: $background; }
    #header {
        height: 1;
        background: $primary;
        color: $text;
        padding: 0 1;
    }
    #log-view { height: 1fr; }
    Static.run-header { color: cyan; padding: 1 2 0 2; }
    Static.step-divider { color: $text-muted; padding: 0 2; }
    Static.run-ok { color: green; padding: 0 2 1 2; }
    Static.run-err { color: red; padding: 0 2 1 2; }
    Static.usage { padding: 0 2; }
    Static.log-line { padding: 0 2; }
    """

    def __init__(
        self,
        host: str,
        port: int,
        replay_run_id: str | None = None,
    ) -> None:
        super().__init__()
        self._host = host
        self._port = port
        self._replay_run_id = replay_run_id
        self._client: SocketClient | None = None
        self._current_llm: LLMStreamBlock | None = None
        self._pending_tool_blocks: dict[
            str, ToolCallBlock
        ] = {}

    def compose(self) -> ComposeResult:
        yield Label(
            "[bold]myclaude[/bold]  "
            "[dim]connecting...[/dim]",
            id="header",
        )
        yield VerticalScroll(id="log-view")

    def on_mount(self) -> None:
        self.run_worker(
            self._socket_loop(),
            exclusive=True,
            name="socket",
        )

    # 向日志视图追加一个 widget 并滚动到底部
    def _append(self, widget: Widget) -> None:
        log_view = self.query_one(
            "#log-view", VerticalScroll
        )
        log_view.mount(widget)
        log_view.scroll_end(animate=False)

    # 结束当前 LLM 流式块（下一个 token 会开启新块）
    def _break_llm(self) -> None:
        if self._current_llm is not None:
            self._current_llm.finalize_markdown()
        self._current_llm = None

    # 管理 SocketClient 生命周期：连接、订阅、断线重连
    async def _socket_loop(self) -> None:
        header = self.query_one("#header", Label)

        while True:
            client = SocketClient(self._host, self._port)
            self._client = None
            try:
                await client.connect()
            except (ConnectionRefusedError, OSError):
                header.update(
                    "[bold]myclaude[/bold]  "
                    "[red]not connected — retrying...[/red]"
                )
                await asyncio.sleep(2)
                continue

            self._client = client
            header.update(
                f"[bold]myclaude[/bold]  "
                f"[dim]{self._host}:{self._port}[/dim]"
            )
            loop_task = asyncio.create_task(
                client.run_event_loop()
            )

            async def on_event(
                event: dict[str, Any],
            ) -> None:
                try:
                    self._handle_event(event)
                except Exception as exc:
                    # 单个事件渲染失败不终止 socket 循环
                    self._append(
                        Static(
                            "[red]event handler error: "
                            f"{escape(str(exc))}[/red]",
                            classes="log-line",
                        )
                    )

            client.on_event(on_event)

            try:
                params: dict[str, Any] = {
                    "topic": [
                        "run.*",
                        "step.*",
                        "tool.*",
                        "llm.token",
                        "llm.user",
                        "log.*",
                    ],
                    "scope": "global",
                }
                if self._replay_run_id is not None:
                    params["replay_from_run"] = (
                        self._replay_run_id
                    )
                await client.send_command(
                    "event.subscribe", params
                )
                await loop_task
            except IpcError as e:
                header.update(
                    "[bold]myclaude[/bold]  "
                    f"[red]subscribe error: "
                    f"{escape(str(e))}[/red]"
                )
            finally:
                if not loop_task.done():
                    loop_task.cancel()
                self._client = None
                self._break_llm()
                await client.close()

            header.update(
                "[bold]myclaude[/bold]  "
                "[dim]disconnected — retrying...[/dim]"
            )
            await asyncio.sleep(2)

    # 根据事件 type 路由到对应渲染逻辑
    def _handle_event(self, event: dict[str, Any]) -> None:
        t = event.get("type", "")

        if t == "llm.token":
            token = str(event.get("token", ""))
            if self._current_llm is None:
                llm_block = LLMStreamBlock()
                self._append(llm_block)
                self._current_llm = llm_block
            self._current_llm.append_token(token)
            return

        self._break_llm()

        if t == "run.started":
            run_id = escape(str(event.get("run_id", "")))
            goal = escape(str(event.get("goal", "")))
            self._append(
                Static(
                    f"[bold cyan]▶ run[/bold cyan]  "
                    f"[dim]{run_id}[/dim]\n"
                    f"  [dim]goal:[/dim] {goal}",
                    classes="run-header",
                )
            )

        elif t == "step.started":
            step = event.get("step", "")
            self._append(
                Static(
                    f"[dim]── step {step} "
                    f"{'─' * 48}[/dim]",
                    classes="step-divider",
                )
            )

        elif t == "step.finished":
            step = event.get("step", "")
            self._append(
                Static(
                    f"[dim]  step {step} done[/dim]",
                    classes="step-divider",
                )
            )

        elif t == "tool.call_started":
            tool_use_id = str(
                event.get("tool_use_id", "")
            )
            tool_name = str(event.get("tool_name", ""))
            params = event.get("params") or {}
            if not isinstance(params, dict):
                params = {"value": params}
            block = ToolCallBlock(tool_name, params)
            self._pending_tool_blocks[tool_use_id] = block
            self._append(block)

        elif t == "tool.call_finished":
            tool_use_id = str(
                event.get("tool_use_id", "")
            )
            elapsed_ms = int(
                event.get("elapsed_ms") or 0
            )
            output = str(event.get("output") or "")
            block = self._pending_tool_blocks.pop(
                tool_use_id, None
            )
            if block is not None:
                block.set_result(output, elapsed_ms)

        elif t == "tool.call_failed":
            tool_use_id = str(
                event.get("tool_use_id", "")
            )
            elapsed_ms = int(
                event.get("elapsed_ms") or 0
            )
            error_msg = str(
                event.get("error_msg") or ""
            )
            block = self._pending_tool_blocks.pop(
                tool_use_id, None
            )
            if block is not None:
                block.set_result(
                    error_msg,
                    elapsed_ms,
                    is_error=True,
                )

        elif t == "run.finished":
            status = event.get("status", "")
            steps = event.get("steps", 0)
            reason = str(event.get("reason") or "")
            if status == "success":
                self._append(
                    Static(
                        "[bold green]✓ completed"
                        "[/bold green]  "
                        f"[dim]{steps} steps[/dim]",
                        classes="run-ok",
                    )
                )
            else:
                detail = (
                    f"  [dim]{escape(reason)}[/dim]"
                    if reason
                    else ""
                )
                self._append(
                    Static(
                        "[bold red]✗ failed[/bold red]"
                        f"{detail}  "
                        f"[dim]{steps} steps[/dim]",
                        classes="run-err",
                    )
                )

        elif t == "llm.user":
            cache_read = event.get(
                "cache_read_input_tokens", 0
            )
            cache_write = event.get(
                "cache_read_output_tokens", 0
            )
            self._append(
                Static(
                    f"[dim]  tokens  "
                    f"in={event.get('input_tokens')} "
                    f"out={event.get('output_tokens')} "
                    f"cache_read={cache_read} "
                    f"cache_write={cache_write}[/dim]",
                    classes="usage",
                )
            )

        elif t == "log.line":
            level = str(event.get("level", "INFO"))
            color = (
                "bold red"
                if level == "ERROR"
                else (
                    "yellow"
                    if level == "WARNING"
                    else "dim"
                )
            )
            source = escape(
                str(event.get("source", ""))
            )
            message = escape(
                str(event.get("message", ""))
            )
            self._append(
                Static(
                    f"[{color}]{level}[/{color}]  "
                    f"[dim]{source}[/dim]  {message}",
                    classes="log-line",
                )
            )


# TUI 入口：供 tui/__main__.py 调用
def run(
    host: str,
    port: int,
    replay_run_id: str | None = None,
) -> None:
    app = MyClaudeTuiApp(
        host, port, replay_run_id=replay_run_id
    )
    app.run()