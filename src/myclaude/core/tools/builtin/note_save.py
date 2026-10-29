from __future__ import annotations

from myclaude.core.session.store import SessionStore
from myclaude.core.tools.base import BaseTool, ToolResult

class NoteSaveTool(BaseTool):
    name = "note_save"
    description = (
        "Save a concise fact or decision to this session's notes. "
        "These notes are visible in future turns of the same session."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The durable fact or decision to remember.",
            },
        },
        "required": ["content"],
    }
#绑定session和run使得工具写入对应的notes.md
    def __init__(
            self,
            store: SessionStore,
            session_id: str,
            run_id: str,
    ) -> None:
        self._store = store
        self._session_id = session_id
        self._run_id = run_id

    async def invoke(self,params:dict[str,object]) ->ToolResult:
        content=str(params.get("content")).strip()
        if not content:
            return ToolResult(
                content="empty content",
                is_error=True,
                error_type="runtime_error",
            )
        self._store.append_note(
            self._session_id, content, self._run_id
        )
        return ToolResult(content="saved")