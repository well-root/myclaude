from __future__ import annotations
from pathlib import Path

import os
from dotenv import load_dotenv
import tomllib
from dataclasses import dataclass,field
from typing import Any

_DEFAULT_TRACE_FILE = "~/.myclaude/traces/daemon.jsonl"
_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 7437
_DEFAULT_LOG_LEVEL = "INFO"
_DEFAULT_LOG_FILE = "~/.myclaude/logs/core.log"
_DEFAULT_LOG_FORMAT = "text"  # "text" | "json"
_DEFAULT_CONFIG_PATH = "~/.myclaude/config.toml"
_DEFAULT_MAX_STEP=20
_DEFAULT_MODEL="deepseek-flash"
#定义LLM和Agent
@dataclass
class AgentConfig:
    max_steps: int = _DEFAULT_MAX_STEP

@dataclass
class LlmConfig:
    default_model: str = _DEFAULT_MODEL
    router: str = "static"  # "static" | "rule_based" (S4) | "cost_budget" (S6)

@dataclass
class TraceConfig:
    trace_file: str = _DEFAULT_TRACE_FILE
    enabled:bool=True
    include_llm_payload:bool=True


#定义loggingconfig
@dataclass
class LoggingConfig:
    level: str = _DEFAULT_LOG_LEVEL
    file: str = _DEFAULT_LOG_FILE
    format: str = _DEFAULT_LOG_FORMAT

@dataclass
class PermissionConfig:
    timeout_s:float=60.0

@dataclass
class CompactionConfig:
    auto_threshold: float = 0.0  # context_pct 触发自动压缩的阈值（0 表示禁用）
    tool_result_limit: int = 8_000  # tool_result 截断触发字符数
    tool_result_keep: int = 4_000  # 截断后保留的前缀字符数

@dataclass
class McpServerConfig:
    name:str
    transport:str="stdio"
    command:str=""
    args:list[str]=field(default_factory=list)
    env:dict[str,str]=field(default_factory=dict)
    host:str="localhost"
    port:int=3000 #host和port是给TCP的

@dataclass
class McpConfig:
    servers: list[McpServerConfig] = field(default_factory=list)



#定义myclaudeconfig
@dataclass
class myclaudeconfig:
    host: str = _DEFAULT_HOST
    port: int = _DEFAULT_PORT
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    llm: LlmConfig = field(default_factory=LlmConfig)
    trace:TraceConfig=field(default_factory=TraceConfig)
    permission:PermissionConfig=field(default_factory=PermissionConfig)
    compaction:CompactionConfig=field(default_factory=CompactionConfig)
    mcp:McpConfig=field(default_factory=McpConfig)



#默认值 → TOML → .env → 系统环境变量
def get_config()->myclaudeconfig:
    config=myclaudeconfig()
    # .env 必须在读取 MYCLAUDE_CONFIG 之前加载，以便 .env 中的 MYCLAUDE_CONFIG 能影响 TOML 路径
    load_dotenv(".env",override=False)

    explicit = os.environ.get("MYCLAUDE_CONFIG")
    if explicit:
        config_paths = [Path(explicit).expanduser()]
    else:
        config_paths = [
            Path(_DEFAULT_CONFIG_PATH).expanduser(),
            Path(".myclaude/config.toml"),
        ]

    for config_path in config_paths:
        if config_path.is_file():
            try:
                with open(config_path, "rb") as f:
                    data = tomllib.load(f)
            except tomllib.TOMLDecodeError as e:
                raise SystemExit(f"Config parse error({config_path}): {e}") from e
            _apply_toml(config, data)
    _apply_env(config)
    return config

#解析toml文件并且写入config,若有错误推出进程
def _apply_toml(config:myclaudeconfig,data:dict[str,Any])->None:
    unknown=set(data.keys())-{"core","logging","agent","llm","trace","permission","compaction"}
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


    if "agent" in data:
        agent = data["agent"]
        if not isinstance(agent, dict):
            raise SystemExit("Config error: [agent] must be a table")
        unknown_agent = set(agent.keys()) - {"max_steps"}
        if unknown_agent:
            raise SystemExit(f"Unknown [agent] keys: {', '.join(sorted(unknown_agent))}")
        if "max_steps" in agent:
            val = agent["max_steps"]
            if not isinstance(val, int) or isinstance(val, bool) or val <= 0:
                raise SystemExit("Config error: agent.max_steps must be a positive integer")
            config.agent.max_steps = val

    if "llm" in data:
        llm = data["llm"]
        if not isinstance(llm, dict):
            raise SystemExit("Config error: [llm] must be a table")
        unknown_llm = set(llm.keys()) - {"default_model", "router"}
        if unknown_llm:
            raise SystemExit(f"Unknown [llm] keys: {', '.join(sorted(unknown_llm))}")
        for key in ("default_model", "router"):
            if key in llm:
                val = llm[key]
                if not isinstance(val, str):
                    raise SystemExit(f"Config error: llm.{key} must be a string")
                setattr(config.llm, key, val)


    if "trace" in data:
        trace = data["trace"]
        if not isinstance(trace, dict):
            raise SystemExit("Config error: [trace] must be a table")
        unknown_trace = set(trace.keys()) - {
            "enabled", "file", "include_llm_payload"
        }
        if unknown_trace:
            raise SystemExit(
                "Unknown [trace] keys: "
                + ", ".join(sorted(unknown_trace))
            )

        if "enabled" in trace:
            val = trace["enabled"]
            if not isinstance(val, bool):
                raise SystemExit(
                    "Config error: trace.enabled must be a boolean"
                )
            config.trace.enabled = val

        if "file" in trace:
            val = trace["file"]
            if not isinstance(val, str):
                raise SystemExit(
                    "Config error: trace.file must be a string"
                )
            config.trace.trace_file = val

        if "include_llm_payload" in trace:
            val = trace["include_llm_payload"]
            if not isinstance(val, bool):
                raise SystemExit(
                    "Config error: trace.include_llm_payload "
                    "must be a boolean"
                )
            config.trace.include_llm_payload = val

    if "permission" in data:
        perm = data["permission"]
        if not isinstance(perm, dict):
            raise SystemExit("Config error: [permission] must be a table")
        unknown_perm: set[str] = set(perm.keys()) - {"timeout_s"}
        if unknown_perm:
            raise SystemExit(
                "Unknown [permission] keys: "
                + ", ".join(sorted(unknown_perm))
            )
        if "timeout_s" in perm:
            val = perm["timeout_s"]
            if not isinstance(val, (int, float)) or val < 0:
                raise SystemExit(
                    "Config error: permission.timeout_s "
                    "must be a non-negative number"
                )
            config.permission.timeout_s = float(val)

    if "compaction" in data:
        comp = data["compaction"]
        if not isinstance(comp, dict):
            raise SystemExit("Config error: [compaction] must be a table")
        unknown_comp: set[str] = set(comp.keys()) - {
            "auto_threshold", "tool_result_limit", "tool_result_keep"
        }
        if unknown_comp:
            raise SystemExit(
                "Unknown [compaction] keys: "
                + ", ".join(sorted(unknown_comp))
            )
        if "auto_threshold" in comp:
            val = comp["auto_threshold"]
            if (
                    not isinstance(val, (int, float))
                    or isinstance(val, bool)
                    or not (0.0 <= val <= 1.0)
            ):
                raise SystemExit(
                    "Config error: compaction.auto_threshold "
                    "must be between 0 and 1"
                )
            config.compaction.auto_threshold = float(val)
        if "tool_result_limit" in comp:
            val = comp["tool_result_limit"]
            if not isinstance(val, int) or isinstance(val, bool) or val <= 0:
                raise SystemExit(
                    "Config error: compaction.tool_result_limit "
                    "must be a positive integer"
                )
            config.compaction.tool_result_limit = val
        if "tool_result_keep" in comp:
            val = comp["tool_result_keep"]
            if not isinstance(val, int) or isinstance(val, bool) or val <= 0:
                raise SystemExit(
                    "Config error: compaction.tool_result_keep "
                    "must be a positive integer"
                )
            config.compaction.tool_result_keep = val
        if config.compaction.tool_result_keep >= config.compaction.tool_result_limit:
            raise SystemExit(
                "Config error: compaction.tool_result_keep "
                "must be smaller than compaction.tool_result_limit"
            )

        if "mcp" in data:
            mcp = data["mcp"]
            if not isinstance(mcp, dict):
                raise SystemExit("Config error: [mcp] must be a table")
            unknown_mcp: set[str] = set(mcp.keys()) - {"servers"}
            if unknown_mcp:
                raise SystemExit(
                    "Unknown [mcp] keys: " + ", ".join(sorted(unknown_mcp))
                )
            servers_raw = mcp.get("servers", [])
            if not isinstance(servers_raw, list):
                raise SystemExit("Config error: mcp.servers must be an array of tables")
            for i, srv in enumerate(servers_raw):
                if not isinstance(srv, dict):
                    raise SystemExit(
                        f"Config error: mcp.servers[{i}] must be a table"
                    )
                name = srv.get("name")
                if not isinstance(name, str) or not name:
                    raise SystemExit(
                        f"Config error: mcp.servers[{i}].name "
                        "must be a non-empty string"
                    )
                transport = srv.get("transport", "stdio")
                if transport not in ("stdio", "tcp"):
                    raise SystemExit(
                        f"Config error: mcp.servers[{i}].transport "
                        "must be 'stdio' or 'tcp'"
                    )
                server = McpServerConfig(name=name, transport=transport)
                if "command" in srv:
                    val = srv["command"]
                    if not isinstance(val, str):
                        raise SystemExit(
                            f"Config error: mcp.servers[{i}].command must be a string"
                        )
                    server.command = val
                if "args" in srv:
                    val = srv["args"]
                    if not isinstance(val, list):
                        raise SystemExit(
                            f"Config error: mcp.servers[{i}].args must be an array"
                        )
                    server.args = [str(a) for a in val]
                if "env" in srv:
                    val = srv["env"]
                    if not isinstance(val, dict):
                        raise SystemExit(
                            f"Config error: mcp.servers[{i}].env must be a table"
                        )
                    server.env = {str(k): str(v) for k, v in val.items()}
                if "host" in srv:
                    val = srv["host"]
                    if not isinstance(val, str):
                        raise SystemExit(
                            f"Config error: mcp.servers[{i}].host must be a string"
                        )
                    server.host = val
                if "port" in srv:
                    val = srv["port"]
                    if not isinstance(val, int) or isinstance(val, bool):
                        raise SystemExit(
                            f"Config error: mcp.servers[{i}].port must be an integer"
                        )
                    server.port = val
                # 项目本地配置覆盖全局同名 server
                config.mcp.servers = [
                    existing
                    for existing in config.mcp.servers
                    if existing.name != server.name
                ]
                config.mcp.servers.append(server)


#布尔解析器
def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in ("1", "true", "yes", "on"):
        return True
    if value in ("0", "false", "no", "off"):
        return False
    raise SystemExit(
        f"Config error: {name} must be a boolean, got: {raw!r}"
    )


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
        config.logging.file=log_file

    log_format=os.environ.get("MYCLAUDE_LOG_FORMAT")
    if log_format is not None:
        config.logging.format=log_format

    max_steps_str = os.environ.get("MYCLAUDE_MAX_STEPS")
    if max_steps_str is not None:
        try:
            val = int(max_steps_str)
        except ValueError:
            raise SystemExit(
                f"Config error: MYCLAUDE_MAX_STEPS must be an integer, got: {max_steps_str!r}"
            )

        if val <= 0:
            raise SystemExit(
                "Config error: MYCLAUDE_MAX_STEPS must be a positive integer,"
                f" got: {max_steps_str!r}"
            )
        config.agent.max_steps = val

    default_model = os.environ.get("MYCLAUDE_LLM_DEFAULT_MODEL")
    if default_model is not None:
        config.llm.default_model = default_model





    config.trace.enabled = _env_bool(
        "MYCLAUDE_TRACE_ENABLED", config.trace.enabled
    )

    trace_file = os.environ.get("MYCLAUDE_TRACE_FILE")
    if trace_file is not None:
        config.trace.trace_file = trace_file

    config.trace.include_llm_payload = _env_bool(
        "MYCLAUDE_TRACE_INCLUDE_LLM_PAYLOAD",
        config.trace.include_llm_payload,
    )



    perm_timeout = os.environ.get("MYCLAUDE_PERMISSION_TIMEOUT_S")
    if perm_timeout is not None:
        try:
            val = float(perm_timeout)
            if val < 0:
                raise SystemExit(
                    "Config error: MYCLAUDE_PERMISSION_TIMEOUT_S "
                    f"must be >= 0, got: {perm_timeout!r}"
                )
            config.permission.timeout_s = val
        except ValueError:
            raise SystemExit(
                "Config error: MYCLAUDE_PERMISSION_TIMEOUT_S "
                f"must be a number, got: {perm_timeout!r}"
            )
    compact_threshold = os.environ.get("MYCLAUDE_COMPACT_THRESHOLD")
    if compact_threshold is not None:
        try:
            threshold_val = float(compact_threshold)
        except ValueError:
            raise SystemExit(
                "Config error: MYCLAUDE_COMPACT_THRESHOLD "
                f"must be a number, got: {compact_threshold!r}"
            )
        if not (0.0 <= threshold_val <= 1.0):
            raise SystemExit(
                "Config error: MYCLAUDE_COMPACT_THRESHOLD "
                f"must be between 0 and 1, got: {compact_threshold!r}"
            )
        config.compaction.auto_threshold = threshold_val

    compact_tool_limit = os.environ.get("MYCLAUDE_COMPACT_TOOL_LIMIT")
    if compact_tool_limit is not None:
        try:
            limit_val = int(compact_tool_limit)
        except ValueError:
            raise SystemExit(
                "Config error: MYCLAUDE_COMPACT_TOOL_LIMIT "
                f"must be an integer, got: {compact_tool_limit!r}"
            )
        if limit_val <= 0:
            raise SystemExit(
                "Config error: MYCLAUDE_COMPACT_TOOL_LIMIT "
                f"must be a positive integer, got: {compact_tool_limit!r}"
            )
        config.compaction.tool_result_limit = limit_val

    compact_tool_keep = os.environ.get("MYCLAUDE_COMPACT_TOOL_KEEP")
    if compact_tool_keep is not None:
        try:
            keep_val = int(compact_tool_keep)
        except ValueError:
            raise SystemExit(
                "Config error: MYCLAUDE_COMPACT_TOOL_KEEP "
                f"must be an integer, got: {compact_tool_keep!r}"
            )
        if keep_val <= 0:
            raise SystemExit(
                "Config error: MYCLAUDE_COMPACT_TOOL_KEEP "
                f"must be a positive integer, got: {compact_tool_keep!r}"
            )
        config.compaction.tool_result_keep = keep_val

    if config.compaction.tool_result_keep >= config.compaction.tool_result_limit:
        raise SystemExit(
            "Config error: compaction.tool_result_keep "
            "must be smaller than compaction.tool_result_limit"
        )




