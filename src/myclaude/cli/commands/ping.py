from __future__ import annotations
import asyncio
import sys
import time
import json

from myclaude.core.bus.commands import PongResult
import myclaude
from myclaude.core.bus.commands import PongResult
from myclaude.core.bus.envelope import JsonRpcError, JsonRpcSuccess
from myclaude.core.config import myclaudeconfig

def cmd_ping(config:myclaudeconfig)->None:
    try:
        asyncio.run(_ping(config))
    except(ConnectionResetError,OSError):
        print(f"error:core not running({config.host}:{config.port})",file=sys.stderr)
        sys.exit(1)

#同时在进程里面 开始异步请求
async def _ping(config:myclaudeconfig)->None:
    t0=time.monotonic()
    reader, writer = await asyncio.open_connection(config.host, config.port)
    #套用json协议
    req={
        "jsonrpc":"2.0",
        "id":"cli-1",
        "method":"core.ping",
        "params":{"client":f"cli/{myclaude.__version__}"},


    }

    writer.write((json.dumps(req)+"\n").encode())
    await writer.drain()

    line=await asyncio.wait_for(reader.readline(),timeout=10.0)
    latency_ms=int((time.monotonic()-t0)*1000)

    #关闭资源
    writer.close()
    await writer.wait_closed()

    raw=json.loads(line)
    if "error" in raw:
        err=JsonRpcError.model_validate(raw)
        print(f"error: {err.error.code} {err.error.message}", file=sys.stderr)
        sys.exit(1)

    resp = JsonRpcSuccess.model_validate(raw)
    result=PongResult.model_validate(resp.result)
