from __future__ import annotations
import asyncio
#它提供了与 C 语言兼容的数据类型
import ctypes
import  os
import signal
#用于创建和管理子进程，执行外部命令
import subprocess
import sys
from pathlib import Path
from myclaude.core.config import myclaudeconfig
_PID_FILE=Path("~/.myclaude/myclaude-core.pid").expanduser()

#链接daemon 返回 若失败就抛出OSE
async def ping_check(config: myclaudeconfig) -> None:
    r,w=await asyncio.open_connection(config.host, config.port)
    w.close()
    await w.wait_closed()


#win32API查询退出
def pid_alive(pid:int)->bool:
    if sys.platform == "win32":
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        if not handle:
            return False
        try:
            exit_code =ctypes.c_ulong()
            ok = ctypes.windll.kernel32.GetExitCodeProcess(
                handle, ctypes.byref(exit_code)
            )
            return bool(ok) and exit_code.value == STILL_ACTIVE
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)

    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True

#读取进程看是否还在
def running_pid() -> int | None:
    if not _PID_FILE.exists():
        return None
    try:
        pid = int(_PID_FILE.read_text().strip())

    except ValueError:
        _PID_FILE.unlink(missing_ok=True)
        return None

    if pid_alive(pid):
        return pid

    _PID_FILE.unlink(missing_ok=True)
    return None

#打印状态
def cmd_core_status(config: myclaudeconfig) -> None:
    try:
        asyncio.run(ping_check(config))
        print(f"running  ({config.host}:{config.port})")
    except (ConnectionRefusedError, OSError):
        print("not running")

#后台启动
def cmd_core_start(config: myclaudeconfig) -> None:
    try:
        asyncio.run(ping_check(config))
        print(f"running  ({config.host}:{config.port})")
        return
    except (ConnectionRefusedError, OSError):
        pass

    kwargs:dict[str,object] = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.DETACHED_PROCESS
        )
    else:
        kwargs["start_new_session"] = True

    proc = subprocess.Popen(
        [sys.executable, "-m", "myclaude.core"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **kwargs,
    )

    _PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PID_FILE.write_text(str(proc.pid))
    print(f"started  pid={proc.pid}  ({config.host}:{config.port})")


#停止操作
def cmd_core_stop(config: myclaudeconfig) -> None:
    pid = running_pid()
    if pid is None:
        print("not running")
        return

    os.kill(pid, signal.SIGTERM)
    print(f"stopped  pid={pid}  ({config.host}:{config.port})")




