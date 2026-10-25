from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import time
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio


@pytest.fixture
def free_port() -> Iterator[int]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    yield port


async def _wait_for_port(
    host: str, port: int, timeout: float = 10.0
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            _reader, writer = await asyncio.open_connection(
                host, port
            )
            writer.close()
            await writer.wait_closed()
            return
        except (ConnectionRefusedError, OSError):
            await asyncio.sleep(0.05)
    raise TimeoutError(
        f"daemon did not start on {host}:{port}"
    )


@pytest_asyncio.fixture
async def running_daemon(
    free_port: int,
) -> AsyncIterator[tuple[str, int]]:
    host = "127.0.0.1"
    env = os.environ.copy()
    env["MYCLAUDE_HOST"] = host
    env["MYCLAUDE_PORT"] = str(free_port)
    env["MYCLAUDE_LOG_FILE"] = ""
    env["MYCLAUDE_LOG_LEVEL"] = "WARNING"

    # 把 daemon 的 stderr 落到文件：启动失败时能直接看到原因
    log_path = Path("daemon-test.log")
    log_file = open(log_path, "wb")
    proc = subprocess.Popen(
        [sys.executable, "-m", "myclaude.core"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=log_file,
    )
    log_file.close()

    try:
        await _wait_for_port(host, free_port)
    except TimeoutError:
        proc.terminate()
        proc.wait(timeout=2)
        print(log_path.read_text(encoding="utf-8", errors="replace"))
        pytest.fail(
            "daemon did not start within 10 seconds "
            f"(see {log_path})"
        )

    yield host, free_port

    proc.terminate()
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()