from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from myclaude.core.bus.events import ContextCompactedEvent
from myclaude.core.events.bus import EventBus

if TYPE_CHECKING:
    from myclaude.core.context import ExecutionContext
    from myclaude.core.llm.base import LLMProvider

logger = logging.getLogger(__name__)

# 摘要 prompt 固定六段结构，对应接续任务时最容易丢的信息
_COMPACT_PROMPT = """\
You are compressing an agent conversation into a handoff summary.
Another LLM instance will continue this task from your summary alone — make it complete.

Structure your response with exactly these six sections:

## 1. Original Goal
One sentence describing what the user asked the agent to accomplish.

## 2. Completed Steps
Bullet list of what has been done. Be specific (file paths, commands run, decisions made).

## 3. Key Constraints & Discoveries
Facts learned during the run that affect future decisions \
(e.g., API limitations, file formats, user preferences stated mid-conversation).

## 4. Current File State
For each file that was created or modified: path, a one-line description of its current state.

## 5. Remaining TODOs
Ordered list of what still needs to be done to complete the original goal.

## 6. Critical Data
Any values the next LLM needs verbatim: IDs, tokens, exact error messages, config values \
discovered during the run.

Be concise. Omit reasoning steps and intermediate attempts. Keep conclusions.\
"""


#_COMPACT_PROMPT = “”“ 你正在将代理对话压缩成切换摘要。另一个大型语言模型实例会从你的摘要中继续完成此任务——使其完整。用以下六个部分结构化你的回复：## 1。原始目标 第一句描述用户要求代理完成的任务。## 2.已完成步骤的项目符号列表。具体说明（文件路径、执行命令、决策）。## 3.运行过程中学到的关键约束与发现 影响未来决策的关键事实  （例如，API限制、文件格式、用户偏好在对话中提及）。## 4.当前文件状态 对于每个创建或修改的文件：路径，其当前状态的一行描述。## 5.剩余待办事项 完成原始目标的顺序清单。## 6.关键数据 下一个大型语言模型需要的任意值：ID、令牌、精确错误消息、配置值 在运行过程中发现的。
#简明扼要。省略推理步骤和中间尝试。保留结论。

#返回当前事件简单的时间戳字符
def _ts_compact() -> str:
    return datetime.now(UTC).strftime("%Y%m%d_%H%M%S")

#返回事件的ISO 8601字符
def _now()->str:
    return datetime.now(UTC).isoformat()


@dataclass
class CompactionResult:
    summary_text: str
    original_token_estimate:int
    summary_tokens:int

class Compactor:
    # 初始化压缩器，绑定事件总线、session 目录和 session ID
    def __init__(self, bus: EventBus, session_dir: Path, session_id: str) -> None:
        self._bus = bus
        self._session_dir = session_dir
        self._session_id = session_id

    # 压缩 ExecutionContext.messages，就地替换消息列表并写 summary 文件
    async def compact(
            self,
            context: ExecutionContext,
            provider: LLMProvider,
            focus: str = "",
    ) -> CompactionResult | None:
        result = await self.compact_messages(context.messages, provider, focus=focus)
        if result is None:
            return None

        # 自动压缩只改当前 run 的内存 messages，不碰 thread.jsonl
        context.messages = [
            {"role": "user", "content": result.summary_text},
            {"role": "assistant", "content": "Understood, I'll continue from this summary."},
        ]
        self.write_summary(result.summary_text)
        await self._bus.publish(
            ContextCompactedEvent(
                session_id=self._session_id,
                run_id=context.run_id,
                original_tokens=result.original_token_estimate,
                summary_tokens=result.summary_tokens,
                ts=_now(),
            )
        )
        logger.info(
            "context compacted session=%s run=%s original≈%d summary=%d tokens",
            self._session_id,
            context.run_id,
            result.original_token_estimate,
            result.summary_tokens,
        )
        return result

    # 纯函数式压缩：接收消息列表，返回 CompactionResult；失败时返回 None
    async def compact_messages(
            self,
            messages: list[dict[str, Any]],
            provider: LLMProvider,
            focus: str = "",
    ) -> CompactionResult | None:
        if not messages:
            logger.warning("compactor: empty message list, skipping compaction")
            return None

        # 粗略 token 估算：字符数 / 4，只用于向用户展示节省量
        original_estimate = sum(
            len(str(m.get("content", ""))) for m in messages
        ) // 4

        history_text = _messages_to_text(messages)
        prompt = _COMPACT_PROMPT
        if focus.strip():
            prompt += f"\n\nIMPORTANT: Pay special attention to: {focus.strip()}"

        compress_request: list[dict[str, object]] = [
            {"role": "user", "content": f"{prompt}\n\n---\n\n{history_text}"}
        ]

        try:
            # 摘要请求用一条全新的、无人订阅的 bus：token 和 usage 不污染 TUI
            silent_bus = EventBus()
            response = await provider.chat(
                messages=compress_request,
                tool_schemas=[],
                bus=silent_bus,
                run_id="compact",
                step=0,
                system="You are a helpful assistant that summarizes conversations.",
            )
        except Exception:
            logger.exception("compactor: LLM call failed, skipping compaction")
            return None

        summary_text = response.text.strip()
        if not summary_text:
            logger.warning("compactor: LLM returned empty summary, skipping compaction")
            return None

        summary_tokens = (
            response.usage.output_tokens
            if response.usage
            else len(summary_text) // 4
        )
        return CompactionResult(
            summary_text=summary_text,
            original_token_estimate=original_estimate,
            summary_tokens=summary_tokens,
        )

    # 将摘要文本写入 session 目录的 summary_<ts>.md
    def write_summary(self, text: str) -> None:
        try:
            self._session_dir.mkdir(parents=True, exist_ok=True)
            path = self._session_dir / f"summary_{_ts_compact()}.md"
            path.write_text(text, encoding="utf-8")
        except Exception:
            # 写摘要失败不影响主任务，compact 已经完成
            logger.exception("compactor: failed to write summary file")

# 将消息列表序列化为可供 LLM 阅读的纯文本
def _messages_to_text(messages: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for msg in messages:
        role = str(msg.get("role", "unknown")).upper()
        content = msg.get("content", "")
        if isinstance(content, str):
            parts.append(f"[{role}]\n{content}")
        elif isinstance(content, list):
            blocks: list[str] = []
            for block in content:
                if not isinstance(block, dict):
                    blocks.append(str(block))
                    continue
                btype = block.get("type", "")
                if btype == "text":
                    blocks.append(str(block.get("text", "")))
                elif btype == "tool_use":
                    blocks.append(
                        f"<tool_call name={block.get('name')} id={block.get('id')}>\n"
                        f"{block.get('input', {})}\n</tool_call>"
                    )
                elif btype == "tool_result":
                    blocks.append(
                        f"<tool_result id={block.get('tool_use_id')}>\n"
                        f"{block.get('content', '')}\n</tool_result>"
                    )
            parts.append(f"[{role}]\n" + "\n".join(blocks))
    return "\n\n".join(parts)





