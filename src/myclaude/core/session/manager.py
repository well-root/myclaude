from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from myclaude.core.bus.envelope import HandlerError
from myclaude.core.bus.events import (
    SessionClosedEvent,
    SessionCreatedEvent,
    SessionMessageReceivedEvent,
    SessionResumedEvent,
    SessionWaitingForInputEvent,
    SkillInvokedEvent,
)
from myclaude.core.events.bus import EventBus
from myclaude.core.runs import new_run_id
from myclaude.core.session.model import Session, SessionMode
from myclaude.core.session.store import SessionStore
from myclaude.core.skills.loader import SkillLoader

if TYPE_CHECKING:
    from myclaude.core.llm.base import LLMProvider
    from myclaude.core.runner import AgentRunner

SESSION_NOT_FOUND = -32010
SESSION_CLOSED = -32011
SESSION_BUSY = -32012
COMPACT_PROVIDER_MISSING = -32020
COMPACT_FAILED = -32021

def _now()->str:
    return datetime.now(UTC).isoformat()

class SessionManager:
    # 初始化会话管理器，接入文件存储、runner 工厂、事件总线和可选的 LLM provider
    def __init__(
        self,
        store: SessionStore,
        runner_factory: Callable[[], AgentRunner],
        bus: EventBus,
        *,
        provider: LLMProvider | None = None,
        provider_factory: Callable[[], LLMProvider] | None = None,
    ) -> None:
        self._store = store
        self._runner_factory = runner_factory
        self._bus = bus
        self._provider = provider
        self._provider_factory = provider_factory
        self._sessions: dict[str, Session] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._skill_loader = SkillLoader()

#创建session 然后写入josn
    async def create(self,mode:SessionMode,title:str="")->Session:
        sid = f"sess-{uuid.uuid4().hex[:12]}"
        ts = _now()
        session = Session(
            id=sid,
            mode=mode,
            status="active",
            title=title,
            created_at=ts,
            updated_at=ts,
            run_ids=[],
        )

        self._locks[sid] = asyncio.Lock()
        self._store.write_meta(session)
        self._sessions[sid] = session
        await self._bus.publish(
            SessionCreatedEvent(session_id=sid, mode=mode, ts=ts)
        )
        return session
    #启动agent run 然后呢追加thread
    async def seed_message(self,sid:str,content:str,*,run_id:str|None=None)->str:
        session=self._get_session(sid)
        lock = self._locks[sid]
        if lock.locked():
            raise HandlerError(SESSION_BUSY, "session busy")

        async with lock:
            if session.status == "closed":
                raise HandlerError(SESSION_CLOSED, "session already closed")

            if session.status == "waiting_for_input":
                await self._bus.publish(
                    SessionResumedEvent(session_id=sid, ts=_now())
                )

            run_id = run_id or new_run_id()

            # Skill 解析：/review 这类输入仍然是 thread 里的原始用户消息，
            # 但把渲染后的 skill prompt 作为 system_prompt_override 传给 runner。
            goal = content
            system_prompt_override: str | None = None
            tool_whitelist: list[str] | None = None
            if content.startswith("/") and len(content) > 1:
                parts = content[1:].split(None, 1)
                skill_name = parts[0] if parts else ""
                arguments = parts[1] if len(parts) > 1 else ""
                skill = self._skill_loader.resolve(skill_name)
                if skill is not None:
                    system_prompt_override = self._skill_loader.render_prompt(
                        skill, arguments
                    )
                    tool_whitelist = skill.allowed_tools or None
                    await self._bus.publish(
                        SkillInvokedEvent(
                            skill_name=skill_name,
                            arguments=arguments,
                            run_id=run_id,
                            ts=_now(),
                        )
                    )

            #先写进thread 再启动runner
            self._store.append_message(sid, "user", content)
            await self._bus.publish(
                SessionMessageReceivedEvent(
                    session_id=sid, content=content, ts=_now()
                )
            )

            if not session.title:
                session.title = content[:40]

            session.run_ids.append(run_id)
            session.updated_at = _now()
            self._store.write_meta(session)

            runner = self._runner_factory()
            await runner.run_and_capture(
                goal,
                run_id=run_id,
                session=session,
                store=self._store,
                system_prompt_override=system_prompt_override,
                tool_whitelist=tool_whitelist,
            )

            session.updated_at = _now()
            if session.mode == "one_shot":
                session.status = "closed"
                await self._bus.publish(
                    SessionClosedEvent(
                        session_id=sid, ts=session.updated_at
                    )
                )
            else:
                session.status = "waiting_for_input"
                await self._bus.publish(
                    SessionWaitingForInputEvent(
                        session_id=sid,
                        last_run_id=run_id,
                        ts=session.updated_at,
                    )
                )
            self._store.write_meta(session)
            return run_id

    async def close(self, sid: str) -> None:
        session = self._get_session(sid)
        lock = self._locks[sid]
        if lock.locked():
            raise HandlerError(SESSION_BUSY, "session busy")
        async with lock:
            session.status = "closed"
            session.updated_at = _now()
            self._store.write_meta(session)
            await self._bus.publish(
                SessionClosedEvent(session_id=sid, ts=session.updated_at)
            )

    # 手动压缩指定 session 的 thread，将摘要持久化写入 thread.jsonl
    async def compact(self, sid: str, focus: str = "") -> Any:
        self._get_session(sid)
        lock = self._locks[sid]
        if lock.locked():
            raise HandlerError(SESSION_BUSY, "session busy")

        provider = self._provider
        if provider is None and self._provider_factory is not None:
            try:
                provider = self._provider_factory()
            except (Exception, SystemExit) as exc:
                raise HandlerError(
                    COMPACT_PROVIDER_MISSING,
                    f"provider not available for compaction: {exc}",
                ) from exc
        if provider is None:
            raise HandlerError(
                COMPACT_PROVIDER_MISSING,
                "provider not available for compaction",
            )

        async with lock:
            from myclaude.core.bus.commands import SessionCompactResult
            from myclaude.core.compact.compactor import Compactor

            messages = self._store.read_messages(sid)
            compactor = Compactor(
                self._bus,
                self._store.session_dir(sid),
                sid,
            )
            result = await compactor.compact_messages(
                messages,
                provider,
                focus=focus,
            )
            if result is None:
                raise HandlerError(
                    COMPACT_FAILED,
                    "compaction failed or not beneficial",
                )
            # 手动压缩同样留一份摘要，方便事后审计
            compactor.write_summary(result.summary_text)
            self._store.write_compacted(sid, [
                {"role": "user", "content": result.summary_text},
                {
                    "role": "assistant",
                    "content": "Understood, I'll continue from this summary.",
                },
            ])
            return SessionCompactResult(
                summary_tokens=result.summary_tokens,
                saved_tokens=max(
                    0,
                    result.original_token_estimate - result.summary_tokens,
                ),
            )

    #读取历史
    async def get_history(self, sid: str) -> list[dict[str, Any]]:
        self._get_session(sid)
        return self._store.read_messages(sid)

    #去session 不存在的话抛出结构化异常
    def _get_session(self, sid: str) -> Session:
        session = self._sessions.get(sid)
        if session is None:
            raise HandlerError(SESSION_NOT_FOUND, "session not found")
        return session

