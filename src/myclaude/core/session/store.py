from __future__ import annotations
import json
import logging
from datetime import UTC,datetime
from pathlib import Path
from typing import Any

from myclaude.core.compact.budget import (
    TOOL_RESULT_KEEP,
    TOOL_RESULT_LIMIT,
    truncate_tool_results,
)
from myclaude.core.session.model import Session

logger = logging.getLogger(__name__)
MessageContent=str|list[dict[str, Any]]

def _now()->str:
    return datetime.now(UTC).isoformat()

class SessionStore:
    #初始化文件来存储根目录；截断阈值可由 [compaction] 配置覆盖
    def __init__(
        self,
        root:Path,
        *,
        tool_result_limit:int=TOOL_RESULT_LIMIT,
        tool_result_keep:int=TOOL_RESULT_KEEP,
    )->None:
        self.root=root.expanduser()
        self.root.mkdir(exist_ok=True,parents=True)
        self.tool_result_limit=tool_result_limit
        self.tool_result_keep=tool_result_keep

    #指定返回的路径
    def session_dir(self,sid:str)->Path:
        return self.root /sid

    def runs_dir(self,sid:str)->Path:
        return self.session_dir(sid)/"runs"

    def read_meta(self, sid: str) -> Session:
        data = json.loads(
            (self.session_dir(sid) / "meta.json").read_text(encoding="utf-8")
        )
        return Session.from_dict(data)

    #追加api消息
    def append_message(
            self,
            sid:str,
            role:str,
            content:MessageContent,
            run_id:str|None=None,
    )->None:
        row:dict[str,Any]={"ts":_now(),"role":role,"content":content}
        if run_id is not None:
            row["run_id"]=run_id
        path=self.session_dir(sid)
        path.parent.mkdir(parents=True, exist_ok=True)
        with (path / "thread.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
#增加
    def append_messages(
            self,
            sid: str,
            messages: list[dict[str, Any]],
            run_id: str,
    ) -> None:
        for msg in messages:
            self.append_message(
                sid,
                role=str(msg["role"]),
                content=msg["content"],
                run_id=run_id,
            )

    def read_messages(self, sid: str) -> list[dict[str, Any]]:
        path = self.session_dir(sid) / "thread.jsonl"
        if not path.exists():
            return []

        messages: list[dict[str, Any]] = []
        for line_no, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                logger.warning(
                    "skip broken thread row sid=%s line=%s", sid, line_no
                )
                continue
            role = row.get("role")
            if role not in ("user", "assistant"):
                logger.warning(
                    "skip unknown thread role sid=%s line=%s role=%s",
                    sid,
                    line_no,
                    role,
                )
                continue
            messages.append(
                {"role": role, "content": row.get("content", "")}
            )

        # 先保证 tool_use / tool_result 配对合法，再做长度截断
        messages = self._trim_orphan_tool_use(messages)
        return truncate_tool_results(
            messages,
            limit=self.tool_result_limit,
            keep=self.tool_result_keep,
        )
    #写入操作
    def write_meta(self,session:Session)->None:
        path=self.session_dir(session.id)
        path.mkdir(parents=True, exist_ok=True)
        (path/"meta.json").write_text(
            json.dumps(session.to_dict(), ensure_ascii=False,indent=2),
            encoding="utf-8",
        )

    # 裁掉尾部未配对 tool_use 以及其后的消息，避免 Anthropic messages.invalid
    def _trim_orphan_tool_use(
            self, messages: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        pending: set[str] = set()
        last_balanced = 0
        for idx, msg in enumerate(messages, start=1):
            content = msg.get("content")
            if isinstance(content, list):
                if msg.get("role") == "assistant":
                    for block in content:
                        if block.get("type") == "tool_use":
                            pending.add(str(block.get("id", "")))
                elif msg.get("role") == "user":
                    for block in content:
                        if block.get("type") == "tool_result":
                            pending.discard(
                                str(block.get("tool_use_id", ""))
                            )
            if not pending:
                last_balanced = idx
        if pending:
            logger.warning("trim orphan tool_use blocks from thread")
            return messages[:last_balanced]
        return messages

    # 将压缩后的消息覆盖写入 thread.jsonl，原文件备份为 thread_<ts>.jsonl.bak
    def write_compacted(
        self,
        sid: str,
        messages: list[dict[str, Any]],
    ) -> None:
        session_dir = self.session_dir(sid)
        session_dir.mkdir(parents=True, exist_ok=True)
        path = session_dir / "thread.jsonl"
        ts_str = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
        bak = session_dir / f"thread_{ts_str}.jsonl.bak"
        if path.exists():
            path.rename(bak)
        with path.open("w", encoding="utf-8") as f:
            for msg in messages:
                row: dict[str, Any] = {
                    "ts": _now(),
                    "role": msg["role"],
                    "content": msg["content"],
                }
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    # 读取 notes.md 全文，文件不存在时返回空字符串
    def read_notes(self, sid: str) -> str:
        path = self.session_dir(sid) / "notes.md"
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    # 将一条主动笔记追加到 notes.md
    def append_note(self, sid: str, content: str, run_id: str) -> None:
        path = self.session_dir(sid)
        path.mkdir(parents=True, exist_ok=True)
        with (path / "notes.md").open("a", encoding="utf-8") as f:
            f.write(f"## Note ({_now()}, {run_id})\n{content}\n\n")
