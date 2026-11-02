from __future__ import annotations
from typing import Any

# 单条 tool_result 超过 8000 字符就开始截断，截断后保留前 4000 字符
TOOL_RESULT_LIMIT = 8_000
TOOL_RESULT_KEEP = 4_000


#对长度过大的tool_result内容截断 然后返回新的列表
def truncate_tool_results(
    messages: list[dict[str, Any]],
    limit: int = TOOL_RESULT_LIMIT,
    keep: int = TOOL_RESULT_KEEP,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for msg in messages:
        if msg.get("role") != "user":
            result.append(msg)
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            result.append(msg)
            continue

        new_blocks: list[dict[str, Any]] = []
        for block in content:
            if (
                    isinstance(block, dict)
                    and block.get("type") == "tool_result"
                    and isinstance(block.get("content"), str)
            ):
                text = block["content"]
                if len(text) > limit:
                    omitted = len(text) - keep
                    block = dict(block)
                    block["content"] = (
                            text[:keep]
                            + f"\n[... {omitted} chars omitted. Full output in run events.]"
                    )
            new_blocks.append(block)
        result.append({**msg, "content": new_blocks})
    return result
