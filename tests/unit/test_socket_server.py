from __future__ import annotations

import asyncio
import json

import pytest

from myclaude.core.bus.commands import EventSubscriberResult
from myclaude.core.transport.ipc_broadcaster import (
    IpcEventBroadcaster,
)
from myclaude.core.transport.socket_server import (
    SocketServer,
    get_connection_writer,
)


@pytest.mark.asyncio
async def test_subscribe_uses_context_writer_and_disconnect_cleans(
    free_port: int,
) -> None:
    broadcaster = IpcEventBroadcaster()
    server = SocketServer(
        "127.0.0.1", free_port, broadcaster
    )

    async def subscribe_handler(params: dict):
        writer = get_connection_writer()
        sub_id = broadcaster.subscribe(
            writer, params["topics"]
        )
        return EventSubscriberResult(
            subscriber_id=sub_id
        )

    server.register("event.subscribe", subscribe_handler)
    addr = await server.start()
    assert addr == f"127.0.0.1:{free_port}"

    reader, writer = await asyncio.open_connection(
        "127.0.0.1", free_port
    )
    request = {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "event.subscribe",
        "params": {"topics": ["run.*"]},
    }
    writer.write(
        (json.dumps(request) + "\n").encode()
    )
    await writer.drain()

    response_line = await asyncio.wait_for(
        reader.readline(), timeout=2.0
    )
    response = json.loads(response_line)
    assert "result" in response
    assert len(broadcaster.subscriptions) == 1

    writer.close()
    await writer.wait_closed()

    for _ in range(50):
        if not broadcaster.subscriptions:
            break
        await asyncio.sleep(0.02)

    assert broadcaster.subscriptions == []
    await server.stop()


@pytest.mark.asyncio
async def test_invalid_json_returns_parse_error(
    free_port: int,
) -> None:
    server = SocketServer("127.0.0.1", free_port)
    await server.start()

    reader, writer = await asyncio.open_connection(
        "127.0.0.1", free_port
    )
    writer.write(b"not json\n")
    await writer.drain()

    line = await asyncio.wait_for(
        reader.readline(), timeout=2.0
    )
    response = json.loads(line)
    assert response["error"]["code"] == -32700

    writer.close()
    await writer.wait_closed()
    await server.stop()