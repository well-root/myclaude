#run_id与runs的目录约定


from __future__ import annotations
#根据一些东西生成特定的数字 如时间戳等
import uuid
from datetime import datetime

from pathlib import Path

RUN_DIR=Path("runs")

#指定对应的路径
def run_dir(run_id:str) -> Path:
    return RUN_DIR / run_id
#指定run_id的事件日志路径
def events_file(run_id:str) -> Path:
    return run_dir(run_id) / "events.jsonl"

def event_file(run_id:str) -> Path:
    """内部统一events_file"""
    return events_file(run_id)

#生成唯一的run id
def new_run_id() -> str:
    ts=datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix=uuid.uuid4().hex[:6]
    return f"{ts}-{suffix}"

#创建 含父级的目录并且返回
def ensure_run_dir(run_id:str) -> Path:
    path = run_dir(run_id)
    path.mkdir(parents=True, exist_ok=True)
    return path





