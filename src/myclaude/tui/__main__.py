import argparse
from myclaude.core.config import get_config
from myclaude.tui.app import MyClaudeTuiApp
def main()->None:

    parser=argparse.ArgumentParser(prog="myclaude-tui",description="myclaude TUI")
    parser.add_argument(
        "--replay",
        metavar="RUN_ID",
        help="Replay events from a past run on connect",
    )
    args = parser.parse_args()
    config = get_config()
    app=MyClaudeTuiApp(
        config.host,
        config.port,
        replay_run_id=args.replay
    )
    app.run()


#这里我们要对于pyproject.toml的声明入口 其他三个也一样
if __name__ == "__main__":
    main()

