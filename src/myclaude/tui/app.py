# tui/app.py 展示画面（Ai）
from __future__ import annotations
import logging
import asyncio
import json
from typing import Any

from rich.markdown import Markdown as RichMarkdown
from rich.markup import escape
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.css.query import NoMatches
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Label, Static, TextArea

from myclaude.core.transport.socket_client import (
    IpcError,
    SocketClient,
)

log=logging.getLogger(__name__)
def _preview(s: str, n: int) -> str:
    return s[:n] + "…" if len(s) > n else s


def _params_str(params: dict[str, Any]) -> str:
    return json.dumps(params, ensure_ascii=False)

# 从工具参数中提取最适合摘要展示的关键字段
def _param_summary(
    tool_name: str,
    params: dict[str, Any],
    max_len: int = 72,
) -> str:
    keys_by_tool = {
        "read_file": ("path",),
        "write_file": ("path",),
        "list_dir": ("path", "max_depth"),
        "bash": ("command",),
        "note_save": ("content",),
    }
    keys = keys_by_tool.get(tool_name, ())
    parts = [
        f"{key}={params[key]!r}"
        for key in keys
        if key in params
    ]
    if not parts:
        parts = [
            f"{key}={value!r}"
            for key, value in list(params.items())[:2]
        ]
    return _preview(", ".join(parts), max_len)

class PermissionSelect(Static):
    """内联权限选择控件：挂载在日志流外，键盘焦点无需 ModalScreen。"""

    can_focus = True

    DEFAULT_CSS = """
    PermissionSelect {
        height: auto;
        padding: 0 2;
        margin-bottom: 1;
    }
    """

    _CHOICES: tuple[tuple[str, str, str], ...] = (
        ("allow_once",   "Allow once",   "y / 1"),
        ("always_allow", "Always allow", "a / 2"),
        ("deny_once",    "Deny",         "n / 3"),
        ("always_deny",  "Always deny",  "d / 4"),
    )
    _KEY_MAP: dict[str, str] = {
        "y": "allow_once",  "1": "allow_once",
        "a": "always_allow", "2": "always_allow",
        "n": "deny_once",   "3": "deny_once",
        "d": "always_deny", "4": "always_deny",
    }

    # 用户作出权限决策时发布，携带工具 ID 和决策字符串
    class Decided(Message):
        def __init__(
                self,
                widget: "PermissionSelect",
                tool_use_id: str,
                decision: str,
        ) -> None:
            self.widget = widget
            self.tool_use_id = tool_use_id
            self.decision = decision
            super().__init__()

    # 初始化控件，存储工具 ID（用于 IPC 回复）
    def __init__(self, tool_use_id: str) -> None:
        super().__init__("")
        self._tool_use_id = tool_use_id
        self._cursor = 0

    def on_mount(self) -> None:
        self.update(self._render_ui())
        self.focus()
        log.debug(
            "PermissionSelect.on_mount  can_focus=%s  focused_after=%r",
            self.can_focus,
            self.app.focused,
        )

    # 生成带光标高亮的选项列表文本
    def _render_ui(self) -> str:
        lines: list[str] = []
        for i, (_, label, key_hint) in enumerate(self._CHOICES):
            if i == self._cursor:
                lines.append(
                    f"  [bold cyan]❯ {label}[/bold cyan]  "
                    f"[dim]{key_hint}[/dim]"
                )
            else:
                lines.append(
                    f"    {label}  [dim]{key_hint}[/dim]"
                )
        lines.append("[dim]  ↑↓ navigate   enter confirm[/dim]")
        return "\n".join(lines)

    # 方向键导航；快捷键直接选择；enter 确认光标位置
    def on_key(self, event: events.Key) -> None:
        log.debug(
            "PermissionSelect.on_key  key=%r  char=%r",
            event.key, event.character,
        )
        key = event.key
        if key in ("up", "k"):
            event.stop()
            self._cursor = (
                self._cursor - 1
            ) % len(self._CHOICES)
            self.update(self._render_ui())
        elif key in ("down", "j"):
            event.stop()
            self._cursor = (
                self._cursor + 1
            ) % len(self._CHOICES)
            self.update(self._render_ui())
        elif key == "enter":
            event.stop()
            self._pick(self._CHOICES[self._cursor][0])
        else:
            decision = self._KEY_MAP.get(key)
            if decision is not None:
                event.stop()
                self._pick(decision)

    # 发布决策消息，由宿主 App 负责 IPC 回复和控件清理
    def _pick(self, decision: str) -> None:
        log.debug("PermissionSelect._pick  decision=%s", decision)
        self.post_message(
            self.Decided(self, self._tool_use_id, decision)
        )


class PermissionBlock(Static):
    """日志里的权限审批摘要。"""

    _LABEL_MAP: dict[str, str] = {
        "allow_once":   "allowed (once)",
        "always_allow": "always allowed",
        "deny_once":    "denied",
        "always_deny":  "always denied",
        "timeout":      "⏱ timed out",
    }
    LABEL_MAP = _LABEL_MAP

    # 子类提交消息：用户作出权限决策时发布
    class Resolved(Message):
        def __init__(
                self,
                block: "PermissionBlock",
                decision: str,
        ) -> None:
            self.block = block
            self.decision = decision
            super().__init__()

    # 初始化审批块，记录工具 ID、名称和参数预览
    def __init__(
            self,
            tool_use_id: str,
            tool_name: str,
            param_preview: str,
    ) -> None:
        self._tool_use_id = tool_use_id
        self._tool_name = tool_name
        self._param_preview = param_preview
        self._resolved = False
        super().__init__(
            self._pending_text(), classes="log-line"
        )

    def _pending_text(self) -> str:
        preview = (
            f"  [dim]{escape(self._param_preview)}[/dim]"
            if self._param_preview else ""
        )
        return (
            f"[bold red]? permission[/bold red]  "
            f"[bold]{self._tool_name}[/bold]{preview}"
        )

    # 将块收缩为单行摘要并发布 Resolved 消息
    def _resolve(self, decision: str) -> None:
        if self._resolved:
            return
        self._resolved = True
        allowed = decision in ("allow_once", "always_allow")
        icon = (
            "[bold green]✓[/bold green]"
            if allowed
            else "[bold red]✗[/bold red]"
        )
        label = self._LABEL_MAP.get(decision, decision)
        preview = (
            f"  [dim]{escape(self._param_preview)}[/dim]"
            if self._param_preview else ""
        )
        self.update(
            f"{icon} permission  "
            f"[bold]{self._tool_name}[/bold]{preview}  "
            f"[dim]{label}[/dim]"
        )
        self.post_message(self.Resolved(self, decision))




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
        # note_save 成功时不展示具体内容，避免聊天区噪声
        if (
                self._tool_name == "note_save"
                and self._finished
                and not self._is_error
        ):
            return (
                f"  [green]remembered[/green]  "
                f"[dim]{self._elapsed_ms}ms[/dim]"
            )

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

class ChatTextArea(TextArea):
    """Enter 提交；Shift/Alt/Ctrl+J/Cmd+Enter 换行。"""

    DEFAULT_CSS = """
    ChatTextArea {
        height: auto;
        min-height: 3;
        max-height: 12;
        border: round $surface-lighten-2;
        background: $background;
        padding: 0 1;
        margin: 1 2;
        scrollbar-size-vertical: 1;
    }
    ChatTextArea:focus {
        border: round $accent;
        background: $background;
    }
    """

    # 子类自定义提交消息，供宿主 App 监听
    class Submitted(Message):
        def __init__(self, area: ChatTextArea) -> None:
            self.text_area = area
            self.value = area.text
            super().__init__()

    # Enter 提交；组合键插入换行；其余键交回 TextArea
    async def _on_key(self, event: events.Key) -> None:
        key = event.key
        if key == "enter":
            event.stop()
            event.prevent_default()
            if self.text.strip():
                self.post_message(self.Submitted(self))
            return
        if key in (
            "alt+enter",
            "shift+enter",
            "ctrl+j",
            "super+enter",
        ):
            event.stop()
            event.prevent_default()
            if not self.read_only:
                self.insert("\n")
            return
        await super()._on_key(event)


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
    Static.user-turn { color: cyan; padding: 1 2 0 2; }
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
        self._pending_permission_blocks: dict[str,PermissionBlock]={}
        self._session_id: str | None = None
        self._busy = False

    def compose(self) -> ComposeResult:
        yield Label(
            "[bold]myclaude[/bold]  "
            "[dim]connecting...[/dim]",
            id="header",
        )
        yield VerticalScroll(id="log-view")
        yield ChatTextArea(
            id="prompt", show_line_numbers=False
        )

    def on_mount(self) -> None:
        self.run_worker(
            self._socket_loop(),
            exclusive=True,
            name="socket",
        )
        prompt = self._prompt()
        if prompt is not None:
            prompt.disabled = True
            prompt.border_title = "connecting..."

    def on_key(self, event: events.Key) -> None:
        log.debug(
            "App.on_key  key=%r  focused=%r",
            event.key, self.focused,
        )
        if not self._pending_permission_blocks:
            return
        try:
            select = self.query_one(PermissionSelect)
            if select.has_focus:
                return  # PermissionSelect 有焦点时自行处理
            key = event.key
            decision = PermissionSelect._KEY_MAP.get(key)
            if decision:
                event.stop()
                select._pick(decision)
            elif key in ("up", "k"):
                event.stop()
                select._cursor = (select._cursor - 1) % len(PermissionSelect._CHOICES)
                select.update(select._render_ui())
            elif key in ("down", "j"):
                event.stop()
                select._cursor = (select._cursor + 1) % len(PermissionSelect._CHOICES)
                select.update(select._render_ui())
            elif key == "enter":
                event.stop()
                select._pick(
                    PermissionSelect._CHOICES[
                        select._cursor
                    ][0]
                )
        except Exception:
            pass

    # 退出前尽力关闭当前 session，失败也不阻塞退出
    async def action_quit(self) -> None:
        if (
                self._client is not None
                and self._session_id is not None
        ):
            try:
                await self._client.send_command(
                    "session.close",
                    {"session_id": self._session_id},
                )
            except (IpcError, RuntimeError, OSError):
                self._append(
                    Static(
                        "[yellow]warning: failed to close "
                        "session[/yellow]"
                    )
                )
        self.exit()

    # 输入框提交：发送 session.send_message
    async def on_chat_text_area_submitted(
            self, event: ChatTextArea.Submitted
    ) -> None:
        content = event.value.strip()
        if not content:
            return
        if (
                self._client is None
                or self._session_id is None
                or self._busy
        ):
            self._append(
                Static(
                    "[yellow]agent busy or disconnected"
                    "[/yellow]",
                    classes="log-line",
                )
            )
            return

        self._busy = True
        prompt = event.text_area
        prompt.text = ""
        prompt.disabled = True
        prompt.border_title = "agent is working..."
        self._append(
            Static(
                f"[bold]>[/bold] {escape(content)}",
                classes="user-turn",
            )
        )
        self._update_header("running")
        self.run_worker(
            self._do_send_message(content),
            exclusive=False,
            name="send_message",
        )

        # 在 worker 中执行 IPC 发送，使 App 消息泵在 agent 运行期间仍能处理键盘/焦点等消息

    async def _do_send_message(self, content: str) -> None:
        if self._client is None:
            return
        try:
            await self._client.send_command(
                "session.send_message",
                {
                    "session_id": self._session_id,
                    "content": content,
                },
            )
        except (IpcError, RuntimeError, OSError) as e:
            self._busy = False
            prompt = self._prompt()
            if prompt is not None:
                prompt.disabled = False
                prompt.border_title = (
                    "type a message — enter to send"
                )
            self._update_header("ready")
            self._append(
                Static(
                    f"[red]send error: {escape(str(e))}"
                    "[/red]",
                    classes="log-line",
                )
            )

        # 处理内联审批控件的用户决策：发送 IPC 响应并恢复输入框

    async def on_permission_select_decided(
            self, msg: PermissionSelect.Decided
    ) -> None:
        tool_use_id = msg.tool_use_id
        decision = msg.decision
        log.info(
            "permission decided tool_use_id=%s decision=%s",
            tool_use_id, decision,
        )
        try:
            await msg.widget.remove()
            perm_block = self._pending_permission_blocks.pop(
                tool_use_id, None
            )
            if perm_block is not None:
                perm_block._resolve(decision)
            if self._client is not None:
                try:
                    await self._client.send_command(
                        "permission.respond",
                        {
                            "tool_use_id": tool_use_id,
                            "decision": decision,
                        },
                    )
                except (IpcError, RuntimeError, OSError):
                    pass
            if not self._pending_permission_blocks:
                p = self._prompt()
                if p is not None:
                    p.disabled = False
                    p.border_title = (
                        "type a message — enter to send"
                    )
                    p.focus()
        except Exception:
            log.exception(
                "on_permission_select_decided failed "
                "tool_use_id=%s",
                tool_use_id,
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

    # 在输入框正上方内联挂载权限选择控件
    def _mount_permission_select(self, select: PermissionSelect) -> None:
        prompt = self._prompt()
        if prompt is not None:
            self.mount(select, before=prompt)
        else:
            self.mount(select)

    # 安全获取输入框，组件测试未挂载时返回 None
    def _prompt(self) -> ChatTextArea | None:
        try:
            return self.query_one(
                "#prompt", ChatTextArea
            )
        except NoMatches:
            return None

    # 根据连接和运行状态刷新顶部标题
    def _update_header(self, state: str) -> None:
        try:
            header = self.query_one("#header", Label)
        except NoMatches:
            return
        session = (
            f"  [dim]{self._session_id}[/dim]"
            if self._session_id
            else ""
        )
        color = {
            "ready": "green",
            "running": "yellow",
            "disconnected": "red",
            "connecting": "dim",
        }.get(state, "dim")
        header.update(
            f"[bold]myclaude[/bold]  "
            f"[dim]{self._host}:{self._port}[/dim]"
            f"{session}  [{color}]{state}[/{color}]"
        )

    # 管理 SocketClient 生命周期：连接、订阅、建会话、断线重连
    async def _socket_loop(self) -> None:
        while True:
            client = SocketClient(self._host, self._port)
            self._client = None
            try:
                await client.connect()
            except (ConnectionRefusedError, OSError):
                self._update_header("disconnected")
                await asyncio.sleep(2)
                continue

            self._client = client
            self._update_header("connecting")
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
                        "session.*",
                        "run.*",
                        "step.*",
                        "tool.*",
                        "llm.token",
                        "llm.user",
                        "log.*",
                        "permission.*",
                    ],
                    "scope": "global",
                }
                if self._replay_run_id is not None:
                    params["replay_from_run"] = (
                        self._replay_run_id
                    )
                # 先订阅，再创建 session
                await client.send_command(
                    "event.subscribe", params
                )
                created = await client.send_command(
                    "session.create", {"mode": "chat"}
                )
                self._session_id = str(
                    created["session_id"]
                )
                prompt = self._prompt()
                if prompt is not None:
                    prompt.disabled = False
                    prompt.border_title = (
                        "type a message — enter to send, "
                        "shift+enter for newline"
                    )
                    prompt.focus()
                self._update_header("ready")
                await loop_task
            except IpcError as e:
                self._update_header("disconnected")
                self._append(
                    Static(
                        "[red]subscribe error: "
                        f"{escape(str(e))}[/red]",
                        classes="log-line",
                    )
                )
            finally:
                if not loop_task.done():
                    loop_task.cancel()
                    try:
                        await loop_task
                    except asyncio.CancelledError:
                        pass
                self._client = None
                self._session_id = None
                self._busy = False
                prompt = self._prompt()
                if prompt is not None:
                    prompt.disabled = True
                    prompt.border_title = (
                        "disconnected, retrying..."
                    )
                self._break_llm()
                await client.close()

            self._update_header("disconnected")
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

        if t == "session.waiting_for_input":
            self._busy = False
            prompt = self._prompt()
            if prompt is not None:
                prompt.disabled = False
                prompt.border_title = (
                    "type a message — enter to send, "
                    "shift+enter for newline"
                )
                prompt.focus()
            self._update_header("ready")

        elif t == "session.closed":
            self._busy = False
            prompt = self._prompt()
            if prompt is not None:
                prompt.disabled = True
                prompt.border_title = "session closed"
            self._update_header("disconnected")

        elif t == "run.started":
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

        elif t == "permission.requested":
            tool_use_id = str(event.get("tool_use_id", ""))
            tool_name = str(event.get("tool_name", ""))
            param_preview = str(event.get("param_preview", ""))
            try:
                focused_repr = repr(self.focused)
            except Exception:
                focused_repr = "?"
            log.info(
                "permission.requested tool=%s id=%s  app.focused=%s",
                tool_name, tool_use_id, focused_repr,
            )
            perm_block = PermissionBlock(
                tool_use_id, tool_name, param_preview
            )
            self._pending_permission_blocks[tool_use_id] = perm_block
            prompt = self._prompt()
            if prompt is not None:
                prompt.disabled = True
                prompt.border_title = "permission required"
            self._append(perm_block)
            select = PermissionSelect(tool_use_id)
            self._mount_permission_select(select)
            log.debug(
                "PermissionSelect mounted before #prompt  pending=%d",
                len(self._pending_permission_blocks),
            )

        elif t == "permission.denied":
            # 处理超时或断连等非用户交互触发的 deny；
            # 用户主动 deny 已由 on_permission_select_decided 处理
            tool_use_id = str(event.get("tool_use_id", ""))
            decision = str(event.get("decision", "denied"))
            if tool_use_id in self._pending_permission_blocks:
                perm_block = self._pending_permission_blocks.pop(
                    tool_use_id, None
                )
                if perm_block is not None:
                    perm_block._resolve(decision)
                try:
                    select = self.query_one(PermissionSelect)
                    select.remove()
                except Exception:
                    pass
                if not self._pending_permission_blocks:
                    p = self._prompt()
                    if p is not None:
                        p.disabled = False
                        p.border_title = (
                            "type a message — enter to send"
                        )
                        p.focus()

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