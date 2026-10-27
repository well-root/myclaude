from __future__ import annotations
import asyncio
from pathlib import Path

from myclaude.core.trace.record import TraceRecord

#初始化 目录和文件
class TraceWriter:
    def __init__(self, path:Path) -> None:
        self.path = path
        self.queue:asyncio.Queue[TraceRecord] = asyncio.Queue()
        self.task:asyncio.Task[None]|None = None

    #创建目录来启动drain task
    async def start(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.task is None or self.task.done():
            self.task=asyncio.create_task(self.drain())

    # 等待队列清空后取消 drain task
    async def stop(self) -> None:
        await self.queue.join()
        if self.task is not None:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None

    # 非阻塞地将 record 放入写入队列
    def emit(self, record: TraceRecord) -> None:
        self.queue.put_nowait(record)

    async  def drain(self) -> None:
        with open(self.path, "a", encoding="utf-8") as f:
            while True:
                record = await self.queue.get()
                try:
                    f.write(record.model_dump_json() + "\n")
                    f.flush()
                finally:
                    self.queue.task_done()

