from __future__ import annotations
import re
from dataclasses import dataclass,field
from enum import StrEnum
from typing import Any

#许可类型
class PermissionDecision(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


# 检测 bash 命令是否操作 cwd 之外路径的正则规则列表（强制触发 ASK，不可被 allow_patterns 绕过）
OUTSIDE_CWD_HEURISTICS: list[str] = [
    r"(^|\s)/[^\s]",  # POSIX absolute path
    r"(^|\s)~",  # tilde home
    r"(^|\s)\.\.(/|\\|$|\s)",  # parent traversal (/ or \)
    r"\$\{?HOME\b",  # $HOME variable
    r"\$\{?PWD\b",  # $PWD variable
    r"(^|\s|;|&&|\|\|)cd(\s|$)",  # explicit cd
    r"(^|\s)[A-Za-z]:[\\/]",  # Windows drive path C:\ or C:/
    r"%USERPROFILE%",  # Windows home env var
    r"%HOMEDRIVE%|%HOMEPATH%",  # Windows home components
    r"%TEMP%|%TMP%",  # Windows temp dirs
    r"(^|\s)\\\\",  # UNC path \\server\share
    r"\$env:(USERPROFILE|HOMEPATH|TEMP|TMP)",  # PowerShell env vars
]

_OUTSIDE_CWD_RE: list[re.Pattern[str]] = [re.compile(p) for p in OUTSIDE_CWD_HEURISTICS]


# 判断 bash 命令是否命中 outside-cwd 启发式规则
def matches_outside_cwd(command: str) -> bool:
    return any(pat.search(command) for pat in _OUTSIDE_CWD_RE)

@dataclass
class ToolPolicy:
    default:PermissionDecision
    allow_patterns:list[str]=field(default_factory=list)
    deny_patterns:list[str]=field(default_factory=list)


DEFAULT_POLICIES: dict[str, ToolPolicy] = {
    "bash":       ToolPolicy(default=PermissionDecision.ASK),
    "write_file": ToolPolicy(default=PermissionDecision.ASK),
    "read_file":  ToolPolicy(default=PermissionDecision.ALLOW),
    "list_dir":   ToolPolicy(default=PermissionDecision.ALLOW),
    "note_save":  ToolPolicy(default=PermissionDecision.ALLOW),
}

# 未在 DEFAULT_POLICIES 中登记的工具的兜底策略
_UNKNOWN_TOOL_DEFAULT = PermissionDecision.ASK

# bash 参数中展示用的关键字段映射
_PREVIEW_KEY: dict[str, str] = {
    "bash":       "command",
    "read_file":  "path",
    "write_file": "path",
    "list_dir":   "path",
    "note_save":  "content",
}
_PREVIEW_MAX = 60

#权限的审核
def param_preview(tool_name:str,params:dict[str,Any])->str:
    key=_PREVIEW_KEY.get(tool_name)
    if key and key in params:
        val = " ".join(str(params[key]).split())
        if len(val) > _PREVIEW_MAX:
            val = val[:_PREVIEW_MAX] + "…"
        return f"{key}={val!r}"
    snippet = str(params)
    return snippet[:_PREVIEW_MAX] if len(snippet) > _PREVIEW_MAX else snippet

#对工具静态策略的评估 返回响应的状态吗
def evaluate(
        tool_name:str,
        params:dict[str,Any],
        policy:ToolPolicy|None=None,

)->PermissionDecision:
    if policy is None:
        policy = DEFAULT_POLICIES.get(tool_name)

    if policy is None:
        return _UNKNOWN_TOOL_DEFAULT

    command=str(params.get("command","")) if tool_name=="bash" else ""

    #四个状态的回归
    if command :
        for pat in policy.deny_patterns:
            if re.search(pat, command):
                return PermissionDecision.DENY

    if command and matches_outside_cwd(command):
        return PermissionDecision.ASK

    if command:
        for pat in policy.allow_patterns:
            if re.search(pat, command):
                return PermissionDecision.ALLOW

    return policy.default
