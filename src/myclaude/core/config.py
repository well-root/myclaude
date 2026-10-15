from pathlib import Path
import os
from dotenv import load_dotenv
import tomllib

from pydantic.dataclasses import dataclass


def get_config()->mycladueconfig:
    config=myclaudeconfig()
    load_dotenv(".env",override=False)

    config_path=Path(os.environ.get("myclaude_config",_DEFAULT_CONFIG_PATH)).expanduser()
    if config_path.exists():
        with open(config_path,"rb") as f:

            data=tomllib.load(f)
        _apply_toml(config,data)
    _apply_toml(config)
    return config

@dataclass
class myclaudeconfig:
    pass



