from __future__ import annotations
import asyncio
import logging
import fnmatch
import uuid
from dataclasses import dataclass
from pydantic import BaseModel
#吧所有的订阅都遍历 然后按照过滤后的消息 推送
from myclaude.core.bus.envelope import EventPushEnvelope
import datetime
from myclaude.core.trace.record import TraceRecord
from myclaude.core.trace.writer import TraceWriter

def _now()->str:
    return datetime.datetime.now(datetime.UTC).isoformat()

logger = logging.getLogger(__name__)

@dataclass
class Subscription:
    sub_id: str
    writer:asyncio.StreamWriter
    topics: list[str]
    scope:str


class IpcEventBroadcaster:
    def __init__(self,*,trace:TraceWriter|None=None)->None:
        self.subscriptions: list[Subscription] = []
        self.trace = trace

    #注册订阅返回id
    def subscribe(
            self,
            writer: asyncio.StreamWriter,
            topics: list[str],
            scope: str="global",
    )->str:
        sub_id = f"sub-{uuid.uuid4().hex[:8]}"
        sub = Subscription(
            sub_id=sub_id, writer=writer, topics=topics, scope=scope
        )
        self.subscriptions.append(sub)
        return sub_id

    #删除指定的订阅
    def unsubscribe(self,writer: asyncio.StreamWriter)->None:
        self.subscriptions=[s for s in self.subscriptions if s.writer is not writer]


    #事务推到订阅的客户端
    async def handle(self,event:BaseModel)->None:
        event_dict = event.model_dump()
        event_type:str =event_dict.get("type","")
        run_id:str |None =(event_dict.get("run_id") or None)

        dead:list[asyncio.StreamWriter]=[]

        for sub in list(self.subscriptions):
            if not self.matches_topic(event_type,sub.topics):
                continue
            if not self.matches_scope(run_id,sub.scope):
                continue

            try:
                envelope = EventPushEnvelope(event=event_dict)
                sub.writer.write(envelope.model_dump_json().encode()+ b"\n")
                await sub.writer.drain()

                # 埋点 ②：只记谁收到了什么类型
                if self.trace is not None:
                    self.trace.emit(
                        TraceRecord(
                            ts=_now(),
                            direction="CORE→CLIENT",
                            layer="ipc",
                            kind="push",
                            run_id=run_id,
                            client_id=str(
                                sub.writer.get_extra_info(
                                    "peername", "<unknown>"
                                )
                            ),
                            data={
                                "sub_id": sub.sub_id,
                                "event_type": event_type,
                            },
                        )
                    )



            except(ConnectionResetError,BrokenPipeError,OSError):
                logger.debug(
                    "dead connection for sub %s,scheduling cleanup",
                    sub.sub_id,
                )

                dead.append(sub.writer)

        #不能遍历直接删 不然后面的用户会被跳过
        for writer in dead:
            self.unsubscribe(writer)

    # 过滤 , 匹配想要的started and finished
    @staticmethod
    def matches_topic(event_type:str, topics:list[str]) -> bool:
        return any(
            fnmatch.fnmatch(event_type, pattern) for pattern in topics
        )


    @staticmethod
    def matches_scope(run_id:str | None ,scope:str) -> bool:
        if scope =="global":
            return True
        if scope.startswith("run"):
            return run_id==scope[4:]
        return False



