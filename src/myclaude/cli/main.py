from __future__ import annotations

import argparse
import json
import sys


from myclaude.cli.commands.ping import cmd_ping
from myclaude.cli.commands.version import cmd_version
from myclaude.core.config import get_config
from myclaude.core.logging_setup import setup_logging
#cli的主入口：解析命令并且发放到子任务

def main()->None:
    #用于将命令行字符串解析为 Python 对象的对象(ArgumentParser)
    parser = argparse.ArgumentParser(prog="myclaude", description="myclaude CLI")
    parser.add_argument("--version", action="store_true", help="Print version and exit")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("ping", help="Ping the core daemon")
    args=parser.parse_args()

    if args.version:
        cmd_version()
        return

    if args.command=="ping":
        config = get_config()
        setup_logging(config)
        cmd_ping(config)

    else:
        parser.print_help()
        sys.exit(1)

