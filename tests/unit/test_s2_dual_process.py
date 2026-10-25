from __future__ import annotations

import asyncio
import time

import pytest

from myclaude.core.transport.socket_client import SocketClient


class EventClient:
    def __init__(self, host: str, port: int) -> None:
        self.client = SocketClient(host, port)
        self.queue: asyncio.Queue[dict] = asyncio.Queue()
        self.loop_task: asyncio.Task[None] | None = None

    async def connect(self) -> None:
        await self.client.connect()

        async def on_event(event: dict) -> None:
            await self.queue.put(event)

        self.client.on_event(on_event)
        self.loop_task = asyncio.create_task(
            self.client.run_event_loop()
        )

    async def subscribe(
        self,
        topics: list[str],
        replay_from_run: str | None = None,
    ) -> dict:
        params: dict = {
            "topic": topics,
            "scope": "global",
        }
        if replay_from_run is not None:
            params["replay_from_run"] = replay_from_run
        return await self.client.send_command(
            "event.subscribe", params
        )

    async def next_event(
        self, event_type: str, timeout: float = 5.0
    ) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise asyncio.TimeoutError(
                    f"no {event_type} event"
                )
            event = await asyncio.wait_for(
                self.queue.get(), timeout=remaining
            )
            if event.get("type") == event_type:
                return event

    async def close(self) -> None:
        if self.loop_task is not None:
            self.loop_task.cancel()
            try:
                await self.loop_task
            except asyncio.CancelledError:
                pass
        await self.client.close()


@pytest.mark.asyncio
async def test_agent_run_returns_matching_run_id(
    running_daemon: tuple[str, int],
) -> None:
    host, port = running_daemon
    client = EventClient(host, port)
    await client.connect()

    try:
        await client.subscribe(["run.*"])
        result = await client.client.send_command(
            "agent.run", {"goal": "hello"}
        )
        run_id = result["run_id"]

        event = await client.next_event("run.started")
        assert event["run_id"] == run_id
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_two_clients_both_receive_broadcast(
    running_daemon: tuple[str, int],
) -> None:
    host, port = running_daemon
    c1 = EventClient(host, port)
    c2 = EventClient(host, port)
    await c1.connect()
    await c2.connect()

    try:
        await c1.subscribe(["run.*"])
        await c2.subscribe(["run.*"])

        await c1.client.send_command(
            "agent.run", {"goal": "broadcast test"}
        )

        e1 = await c1.next_event("run.started")
        e2 = await c2.next_event("run.started")
        assert e1["run_id"] == e2["run_id"]
    finally:
        await c1.close()
        await c2.close()


@pytest.mark.asyncio
async def test_replay_after_run(
    running_daemon: tuple[str, int],
) -> None:
    host, port = running_daemon
    c1 = EventClient(host, port)
    await c1.connect()

    try:
        await c1.subscribe(["run.*"])
        result = await c1.client.send_command(
            "agent.run", {"goal": "replay test"}
        )
        run_id = result["run_id"]

        await c1.next_event("run.started")
        # EventWriter 每条事件都 flush，run.started 已经落盘
        await asyncio.sleep(0.1)
    finally:
        await c1.close()

    c2 = EventClient(host, port)
    await c2.connect()

    try:
        sub = await c2.subscribe(
            ["run.*"], replay_from_run=run_id
        )
        assert sub["replayed_count"] >= 1

        replayed = await c2.next_event("run.started")
        assert replayed["run_id"] == run_id
    finally:
        await c2.close()