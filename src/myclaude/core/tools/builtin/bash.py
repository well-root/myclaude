#bash 执行工具
from __future__ import  annotations
import asyncio

from pydantic import ConfigDict,Field,BaseModel

from myclaude.core.tools.base import BaseTool,ToolResult

MAX_OUTPUT_BYTES = 64 * 1024  # 64 KB
DEFAULT_TIMEOUT = 60

class BashParams(BaseModel):
    model_config=ConfigDict(extra="ignore")
    command: str
    timeout: int=Field(default=DEFAULT_TIMEOUT,ge=1,le=120)


#执行一个 shell 命令并返回其输出（标准输出和标准错误合并）。非交互式——需要用户输入的命令会挂起并超时。优先使用简短、专注的命令。输出截断为 64 KB。在 Windows 上，命令通过 cmd.exe 运行。
class BashTool(BaseTool):
    params_model = BashParams
    name = "bash"
    description = (
        "Execute a shell command and return its output (stdout + stderr combined). "
        "Non-interactive only — commands requiring user input will hang and time out. "
        "Prefer short, focused commands. Output is truncated at 64 KB. "
        "On Windows the command runs through cmd.exe."
    )
    input_schema: dict[str, object] = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Shell command to execute.",
            },
            "timeout": {
                "type": "integer",
                "description": (
                    f"Maximum seconds to wait "
                    f"(default {DEFAULT_TIMEOUT}, max 120)."
                ),
            },
        },
        "required": ["command"],
    }


    #执行shell 合并标准命令和标准错误命令，超时返回错误
    async def invoke(self,params:dict[str,object]) ->ToolResult:
        p=BashParams.model_validate(params)
        command=p.command
        timeout=p.timeout


        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            try:
                stdout_bytes, _ = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except TimeoutError:
                proc.kill()
                await proc.communicate()
                return ToolResult(
                    content=f"[timeout after {timeout}s]",
                    is_error=True,
                    error_type="timeout",
                )
        except Exception as exc:
            return ToolResult(
                content=str(exc),
                is_error=True,
                error_type="runtime_error",
            )

        output=stdout_bytes.decode("utf-8",errors="replace")
        if len(stdout_bytes)>MAX_OUTPUT_BYTES:
            output = output[:MAX_OUTPUT_BYTES] + "\n[truncated]"

        returncode=proc.returncode or 0
        if returncode != 0:
            return ToolResult(
                content=f"[exit {returncode}]\n{output}",
                is_error=True,
                error_type="runtime_error",
            )
        return ToolResult(content=output or "[no output]")
