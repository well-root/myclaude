from __future__ import annotations

import argparse
import json
import sys


from myclaude.cli.commands.ping import cmd_ping
from myclaude.cli.commands.version import cmd_version
from myclaude.core.config import get_config
from myclaude.core.logging_setup import setup_logging
from myclaude.cli.commands.run import cmd_run
#cli的主入口：解析命令并且发放到子任务

def main()->None:
    #用于将命令行字符串解析为 Python 对象的对象(ArgumentParser)
    parser = argparse.ArgumentParser(prog="myclaude", description="myclaude CLI")
    parser.add_argument("--version", action="store_true", help="Print version and exit")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("ping", help="Ping the core daemon")

    run_parser = subparsers.add_parser("run", help="Run an agent task")
    run_parser.add_argument("--goal", required=True, help="Goal for the agent to accomplish")
    args = parser.parse_args()

    if args.version:
        cmd_version()
        return

    config = get_config()
    setup_logging(config)

    if args.command=="ping":
        cmd_ping(config)

    elif args.command=="run":
        cmd_run(args.goal,config)

    else:
        parser.print_help()
        sys.exit(1)

