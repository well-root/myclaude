from __future__ import annotations
from pathlib import Path

import os
from dotenv import load_dotenv
import tomllib
from dataclasses import dataclass,field
from typing import Any


_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 7437
_DEFAULT_LOG_LEVEL = "INFO"
_DEFAULT_LOG_FILE = "~/.myclaude/logs/core.log"
_DEFAULT_LOG_FORMAT = "text"  # "text" | "json"
_DEFAULT_CONFIG_PATH = "~/.myclaude/config.toml"
#定义loggingconfig
@dataclass
class LoggingConfig:
    level: str = _DEFAULT_LOG_LEVEL
    file: str = _DEFAULT_LOG_FILE
    format: str = _DEFAULT_LOG_FORMAT
#定义myclaudeconfig
@dataclass
class myclaudeconfig:
    host: str = _DEFAULT_HOST
    port: int = _DEFAULT_PORT
    logging: LoggingConfig = field(default_factory=LoggingConfig)

#默认值 → TOML → .env → 系统环境变量
def get_config()->myclaudeconfig:
    config=myclaudeconfig()
    # .env 必须在读取 MYCLAUDE_CONFIG 之前加载，以便 .env 中的 MYCLAUDE_CONFIG 能影响 TOML 路径
    load_dotenv(".env",override=False)

    config_path=Path(os.environ.get("MYCLADUE_CONFIG",_DEFAULT_CONFIG_PATH)).expanduser()
    if config_path.exists():
        try:

            with open(config_path,"rb") as f:

                data=tomllib.load(f)
        except tomllib.TOMLDecodeError as e:

            raise SystemExit(f"Config parse error({config_path}): {e}") from e
        _apply_toml(config,data)
    _apply_env(config)
    return config

#解析toml文件并且写入config,若有错误推出进程
def _apply_toml(config:myclaudeconfig,data:dict[str,Any])->None:
    unknown=set(data.keys())-{"core","logging"}
    if unknown:
        raise SystemExit(f"Unknown top-level config keys: {', '.join(sorted(unknown))}")
    if "core" in data:
        core=data["core"]
        if not isinstance(core,dict):
            #SystemExit是系统推出并且返回
            raise SystemExit("Config error: [core] must be a table")
        unknown_core:set[str]=set(core.keys())-{"host","port"}

        if unknown_core:
            raise SystemExit(f"Unknown [core] keys: {', '.join(sorted(unknown_core))}")
        if "host" in core:
            val = core["host"]
            if not isinstance(val, str):
                raise SystemExit("Config error: core.host must be a string")
            config.host = val
        if "port" in core:
            val = core["port"]
            if not isinstance(val, int):
                raise SystemExit("Config error: core.port must be an integer")
            config.port = val



    if "logging" in data:
        log = data["logging"]
        if not isinstance(log, dict):
            raise SystemExit("Config error: [logging] must be a table")
        unknown_log: set[str] = set(log.keys()) - {"level", "file", "format"}
        if unknown_log:
            raise SystemExit(f"Unknown [logging] keys: {', '.join(sorted(unknown_log))}")
        for key in ("level", "file", "format"):
            if key in log:
                val = log[key]
                if not isinstance(val, str):
                    raise SystemExit(f"Config error: logging.{key} must be a string")
                setattr(config.logging, key, val)


#myclaude的环境变量覆盖config
def _apply_env(config:myclaudeconfig)->None:
    host=os.environ.get("MYCLAUDE_HOST")
    if host is not None:
        config.host=host

    port_str=os.environ.get("MYCLAUDE_PORT")
    if port_str is not None:
        try:
            config.port=int(port_str)
        except ValueError:
            raise SystemExit(f"Config error: MYCLAUDE_PORT must be an integer, got: {port_str!r}")
        log_level=os.environ.get("MYCLAUDE_LOG_LEVEL")
        if log_level is not None:
            config.logging.level=log_level

        log_file=os.environ.get("MYCLAUDE_LOG_FILE")
        if log_file is not None:
            config.logging.level=log_level

        log_format=os.environ.get("MYCLAUDE_LOG_FORMAT")
        if log_format is not None:
            config.logging.level=log_level





