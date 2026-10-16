from __future__ import annotations
import asyncio

import time
import json

from  ...core.config import myclaudeconfig

def cmd_ping(config:myclaudeconfig)->None:
    try:
        asyncio.run(_ping(config))
    except(ConnectionResetError,OSError):
        import sys
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