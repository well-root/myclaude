import asyncio


def cmd_ping(config:myclaudeconfig)->None:
    try:
        asyncio.run(_ping(config))
    except(ConnectionResetError,OSError):
        import sys
        print(f"error:core not running({config.host}:{config.port}:{config.port})",file=sys.stderr)
        sys.exit(1)
