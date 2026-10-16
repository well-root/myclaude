from __future__ import annotations

import argparse
import json
import sys

from rich.repr import Result

from myclaude.core.bus.envelope import JsonRpcError, JsonRpcSuccess


def main():
    import argparse
    parser=argparse.ArgumentParser(prog="myclaude",description="myclaude CLI")
    parser.add_argument("--version",action="store_true",help="Print version and exit")
    subprocess=parser.add_argument(dest="command",help="command to run")

    args=parser.parse_args()

    if args.version:
        cmd_version
        return

    config=get_config()
    setup_logging(config)

    if arg.command=="ping":
        cmd_ping(config)

    else:
        parser.print_help()
        sys.exit(1)


#CLI解析相应结构并且打印
raw=json.load(line)
if "error" in raw:
    err=JsonRpcError.model_validate(raw)
    print(f"error: {err.error.code} {err.error.message}",file=sys.stderr)
    sys.exit(1)

resp=JsonRpcSuccess.model_validate(raw)
result=PongResult.model_validate(resp.result)
print(f"pong server={result.server_version} uptime={result.uptime_ms} ms latency={result.latency} ms")

