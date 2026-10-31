#这个是用来 调用工具的 如果工具错误 统一都会报错为toolresult 但是永远不会抛异常

from __future__ import annotations
import asyncio
import time
from datetime import datetime,UTC
from typing import TYPE_CHECKING,Any
from pydantic import ValidationError
from myclaude.core.bus.events import (
    PermissionDeniedEvent,
    PermissionGrantedEvent,
    PermissionRequestedEvent,
    ToolCallFailedEvent,
    ToolCallFinishedEvent,
    ToolCallStartedEvent,

)
from myclaude.core.events.bus import EventBus
from myclaude.core.llm.types import ToolCallBlock
from myclaude.core.tools.base import ToolResult
from myclaude.core.tools.registry import ToolRegistry
from myclaude.core.tools.errors import RateLimitedError

if TYPE_CHECKING:
    from myclaude.core.permissions.manager import PermissionManager
_DEFAULT_TIMEOUT: float = 120.0
_MAX_RETRIES: int = 2
_RETRY_BASE_S: float = 2.0  # 退避基数；测试里 monkeypatch 为 0
_RETRYABLE: frozenset[str] = frozenset({"runtime_error", "rate_limited"})


def _now()->str:
    return datetime.now(UTC).isoformat()

#若有toolcallfailedenvent 就返回对应的toolresult
async def _fail(
        bus: EventBus,
        run_id:str,
        tool_call:ToolCallBlock,
        error_type:str,
        error_message:str,
        elapsed_ms:int,
        *,
        attempt=1,
)->ToolResult:
    await bus.publish(
        ToolCallFailedEvent(
            run_id=run_id,
            tool_use_id=tool_call.id,
            tool_name=tool_call.name,
            error_type=error_type,
            error_msg=error_message,
            elapsed_ms=elapsed_ms,
            ts=_now(),
        )
    )
    return ToolResult(content=error_message,is_error=True,error_type=error_type)

#校验参数返回toolresult
async def invoke_tool(
        registry: ToolRegistry,
        tool_call:ToolCallBlock,
        bus:EventBus,
        run_id:str,
        timeout:float=_DEFAULT_TIMEOUT,
        *,
        permission_manager:PermissionManager|None=None,
        session_id:str="",
)->ToolResult:
    t0=time.monotonic()

    await bus.publish(
        ToolCallStartedEvent(
            run_id=run_id,
            tool_use_id=tool_call.id,
            tool_name=tool_call.name,
            params=dict(tool_call.input),
            ts=_now(),
        )
    )

    def elapsed()->int:
        return int((time.monotonic() - t0) * 1000)


    tool=registry.get(tool_call.name)
    if tool is None:
        return await _fail(
            bus,run_id,tool_call,
            "runtime_error", f"unknown tool: {tool_call.name}", elapsed(),
        )

    # 第一道关：pydantic 参数校验。参数格式错不是权限问题，直接回给 LLM 修正。
    if tool.params_model is not None:
        try:
            tool.params_model.model_validate(dict(tool_call.input))
        except ValidationError as exc:
            return await _fail(
                bus, run_id, tool_call,
                "schema_error", str(exc), elapsed(),
            )

    # 第二道关：权限审批
    if permission_manager is not None:
        async def _emit_permission(raw: dict[str, Any]) -> None:
            await bus.publish(PermissionRequestedEvent(**raw, run_id=run_id))

        allowed, decision = await permission_manager.check_and_wait(
            tool_use_id=tool_call.id,
            tool_name=tool_call.name,
            params=dict(tool_call.input),
            session_id=session_id,
            event_emitter=_emit_permission,
        )
        if allowed:
            if decision not in ("auto_allow",):
                await bus.publish(
                    PermissionGrantedEvent(
                        run_id=run_id,
                        tool_use_id=tool_call.id,
                        decision=decision,
                        ts=_now(),
                    )
                )
        else:
            if decision != "auto_deny":
                await bus.publish(
                    PermissionDeniedEvent(
                        run_id=run_id,
                        tool_use_id=tool_call.id,
                        decision=decision,
                        ts=_now(),
                    )
                )
            return await _fail(
                bus, run_id, tool_call,
                "permission_denied",
                "Permission denied by user. You may not execute this command. "
                "Try an alternative approach or ask the user what to do.",
                elapsed(),
            )

    # 第三道关：真正执行工具，失败分类 + 指数退避重试
    for attempt in range(1, _MAX_RETRIES + 2):
        error_type: str | None = None
        error_message: str | None = None

        try:
            result = await asyncio.wait_for(
                tool.invoke(dict(tool_call.input)), timeout=timeout
            )
            ms = elapsed()

            if result.is_error:
                error_type = result.error_type or "runtime_error"
                error_message = result.content
            else:
                await bus.publish(
                    ToolCallFinishedEvent(
                        run_id=run_id,
                        tool_use_id=tool_call.id,
                        tool_name=tool_call.name,
                        elapsed_ms=ms,
                        output=result.content,
                        ts=_now(),
                    )
                )
                return result

        except RateLimitedError as exc:
            error_type = "rate_limited"
            error_message = str(exc)
        except TimeoutError:
            return await _fail(
                bus, run_id, tool_call,
                "timeout", f"tool timed out after {timeout}s", elapsed(),
                attempt=attempt,
            )
        except Exception as exc:
            error_type = "runtime_error"
            error_message = str(exc)

        assert error_type is not None and error_message is not None
        ms = elapsed()

        if error_type in _RETRYABLE and attempt <= _MAX_RETRIES:
            await bus.publish(
                ToolCallFailedEvent(
                    run_id=run_id,
                    tool_use_id=tool_call.id,
                    tool_name=tool_call.name,
                    error_type=error_type,
                    error_msg=error_message,
                    elapsed_ms=ms,
                    attempt=attempt,
                    ts=_now(),
                )
            )
            await asyncio.sleep(_RETRY_BASE_S * (2 ** (attempt - 1)))
            continue

        return await _fail(
            bus, run_id, tool_call,
            error_type, error_message, ms,
            attempt=attempt,
        )

    # 理论上不可达，保持返回值完整
    return ToolResult(content="internal error", is_error=True, error_type="runtime_error")
