from __future__ import annotations

import argparse
import sys

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
