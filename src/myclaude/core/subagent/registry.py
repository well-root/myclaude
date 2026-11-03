from __future__ import annotations
import asyncio
from myclaude.core.context import ExecutionContext

#管理subagent的周期
class BackgroundTaskRegistry:
    def __init__(self)->None:
        self._tasks:dict[str,tuple[asyncio.Task,ExecutionContext]] = {}



    def register(
            self,
            run_id:str,
            task:asyncio.Task[None],
            context:ExecutionContext,
    )->None:
        self._tasks[run_id] = (task, context)


    #查询任务和上下文
    def get(self,run_id:str)->tuple[asyncio.Task,ExecutionContext]|None:
        return self._tasks.get(run_id)


    def all(self)->list[tuple[asyncio.Task[None],ExecutionContext]]:
        return list(self._tasks.values())

    #取消列出的所有日内瓦
    async def cancel_all(self)->None:
        for task,_context in list(self._tasks.values()):
            if not task.done():
                task.cancel()

        for task,_context in list(self._tasks.values()):
            if task.cancelled():
                continue
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass

