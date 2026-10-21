#把事件记录下来 events.jsonl
from __future__ import annotations

import logging
from pathlib import Path
from typing import IO

from pydantic import BaseModel

from myclaude.core.events.bus import EventBus

logger = logging.getLogger(__name__)

class EventWriter(BaseModel):
    def __init__(self, path: Path) -> None:
        self._path = path
        self._file: IO[str] | None = None

    #打开事务文件 供异步使用
    async def __aenter__(self) -> EventWriter:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(self._path, 'a', encoding='utf-8')
        return self

    #关闭事务文件
    async def __aexit__(self, *args:object)-> None:
        if self._file is not None:
            self._file.close()
            self._file = None

    #把事务序列化为json
    async def handle(self, event: EventBus) -> None:
        if self._file is  None:
            return
        try:
            self._file.write(event.model_dump_json()+"\n")
            self._file.flush()

        except(OSError,ValueError) as e:
            logger.error("EventWriter: failed to write event: %s", e)

        # 将 handle 注册为 bus 的订阅者
    def subscribe(self, bus: EventBus) -> None:
        bus.subscribe(self.handle)




