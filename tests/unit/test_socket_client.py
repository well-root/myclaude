from __future__ import annotations

import asyncio
import json

import pytest

from myclaude.core.transport.socket_client import (
    IpcError,
    SocketClient,
)


async def _start_server(handler):
    server = await asyncio.start_server(
        handler, "127.0.0.1", 0
    )
    port = server.sockets[0].getsockname()[1]
    return server, port


async def _stop_server(server) -> None:
    server.close()
    await server.wait_closed()


@pytest.mark.asyncio
async def test_send_command_resolves_future() -> None:
    async def handler(reader, writer):
        line = await reader.readline()
        req = json.loads(line)
        response = {
            "jsonrpc": "2.0",
            "id": req["id"],
            "result": {"ok": True},
        }
        writer.write(
            (json.dumps(response) + "\n").encode()
        )
        await writer.drain()
        writer.close()

    server, port = await _start_server(handler)
    client = SocketClient("127.0.0.1", port)
    await client.connect()
    loop_task = asyncio.create_task(client.run_event_loop())

    try:
        result = await asyncio.wait_for(
            client.send_command("core.ping", {}),
            timeout=2.0,
        )
        assert result == {"ok": True}
    finally:
        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass
        await client.close()
        await _stop_server(server)


@pytest.mark.asyncio
async def test_error_response_raises_ipc_error() -> None:
    async def handler(reader, writer):
        line = await reader.readline()
        req = json.loads(line)
        response = {
            "jsonrpc": "2.0",
            "id": req["id"],
            "error": {
                "code": -32601,
                "message": "Method not found",
            },
        }
        writer.write(
            (json.dumps(response) + "\n").encode()
        )
        await writer.drain()
        writer.close()

    server, port = await _start_server(handler)
    client = SocketClient("127.0.0.1", port)
    await client.connect()
    loop_task = asyncio.create_task(client.run_event_loop())

    try:
        with pytest.raises(IpcError) as exc_info:
            await asyncio.wait_for(
                client.send_command("nope", {}),
                timeout=2.0,
            )
        assert exc_info.value.code == -32601
    finally:
        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass
        await client.close()
        await _stop_server(server)


@pytest.mark.asyncio
async def test_event_push_calls_handler() -> None:
    async def handler(reader, writer):
        event = {
            "kind": "event",
            "event": {
                "type": "run.started",
                "run_id": "r1",
            },
        }
        writer.write(
            (json.dumps(event) + "\n").encode()
        )
        await writer.drain()
        await asyncio.sleep(0.2)
        writer.close()

    server, port = await _start_server(handler)
    client = SocketClient("127.0.0.1", port)
    await client.connect()

    received: list[dict] = []
    got_event = asyncio.Event()

    async def on_event(event: dict) -> None:
        received.append(event)
        got_event.set()

    client.on_event(on_event)
    loop_task = asyncio.create_task(client.run_event_loop())

    try:
        await asyncio.wait_for(got_event.wait(), timeout=2.0)
        assert received[0]["type"] == "run.started"
    finally:
        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass
        await client.close()
        await _stop_server(server)


@pytest.mark.asyncio
async def test_disconnect_cancels_pending() -> None:
    async def handler(reader, writer):
        await reader.readline()
        writer.close()
        await writer.wait_closed()

    server, port = await _start_server(handler)
    client = SocketClient("127.0.0.1", port)
    await client.connect()
    loop_task = asyncio.create_task(client.run_event_loop())

    try:
        with pytest.raises(
            (asyncio.CancelledError, ConnectionError)
        ):
            await asyncio.wait_for(
                client.send_command(
                    "agent.run", {"goal": "x"}
                ),
                timeout=2.0,
            )
    finally:
        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass
        await client.close()
        await _stop_server(server)