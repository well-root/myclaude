from __future__ import annotations
import re

from dataclasses import dataclass,field
from pathlib import Path

@dataclass
class Skill:
    name:str
    description:str
    system_prompt_template:str
    allowed_tools:list[str]=field(default_factory=list)

#re.compile通过Match对象，可以获取匹配的内容以及匹配的位置等信息
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

#解析markdown和 skill 然后提取提示词
def _parse_skill_file(path: Path) -> Skill:
    text = path.read_text(encoding="utf-8")
    name = path.parent.name if path.name == "SKILL.md" else path.stem
    description = ""
    allowed_tools: list[str] = []
    body = text

    m = _FRONTMATTER_RE.match(text)
    if m:
        front = m.group(1)
        body = text[m.end():]
        lines = front.splitlines()
        i = 0
        in_allowed = False
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            if stripped.startswith("name:"):
                name = stripped[len("name:"):].strip().strip('"').strip("'")
                in_allowed = False
            elif stripped.startswith("description:"):
                val = stripped[len("description:"):].strip().strip('"').strip("'")
                # YAML 块标量：> (折叠) 或 | (保留换行)，后续缩进行是内容
                if val in (">", "|"):
                    fold = val == ">"
                    parts: list[str] = []
                    i += 1
                    while i < len(lines) and (lines[i].startswith(" ") or lines[i].startswith("\t")):
                        parts.append(lines[i].strip())
                        i += 1
                    description = (" ".join(parts) if fold else "\n".join(parts)).strip()
                    in_allowed = False
                    continue
                description = val
                in_allowed = False
            elif stripped.startswith("allowed_tools:"):
                in_allowed = True
                inline = stripped[len("allowed_tools:"):].strip()
                # 支持 allowed_tools: [read_file, bash] 这种行内写法
                if inline.startswith("[") and inline.endswith("]"):
                    allowed_tools.extend(
                        x.strip().strip('"').strip("'")
                        for x in inline[1:-1].split(",")
                        if x.strip()
                    )
                    in_allowed = False
            elif in_allowed and stripped.startswith("- "):
                allowed_tools.append(stripped[2:].strip())
            elif stripped and not line.startswith((" ", "\t")):
                # 遇到下一个顶层键，结束 allowed_tools 段
                in_allowed = False
            i += 1

    return Skill(
        name=name,
        description=description,
        system_prompt_template=body.strip(),
        allowed_tools=allowed_tools,
    )


#从全局寻找并且解析skill

class SkillLoader:
    _BUILTIN_DIR = Path(__file__).parent / "builtin"

    # 按优先级查找 skill 文件；未找到返回 None
    def resolve(self, name: str) -> Skill | None:
        for path in self._search_paths(name):
            if path.is_file():
                try:
                    return _parse_skill_file(path)
                except Exception:
                    return None
        return None


    #寻找出候选的列表
    def _search_paths(self, name: str) -> list[Path]:
        dirs = [
            Path(".myclaude/skills"),
            Path("~/.myclaude/skills").expanduser(),
            self._BUILTIN_DIR,
        ]
        paths: list[Path] = []
        for d in dirs:
            paths.append(d / f"{name}.md")
            paths.append(d / name / "SKILL.md")
        return paths

    #列出所有的skill名字
    def list_all(self) -> list[str]:
        seen: dict[str, None] = {}
        for d in [
            self._BUILTIN_DIR,
            Path("~/.myclaude/skills").expanduser(),
            Path(".myclaude/skills"),
        ]:
            if d.is_dir():
                for f in sorted(d.glob("*.md")):
                    seen[f.stem] = None
                for f in sorted(d.glob("*/SKILL.md")):
                    seen[f.parent.name] = None
        return list(seen)

    #列出所有可用的skill
    def list_all_skills(self) -> list[Skill]:
        seen: dict[str, Skill] = {}
        for d in [
            self._BUILTIN_DIR,
            Path("~/.myclaude/skills").expanduser(),
            Path(".myclaude/skills"),
        ]:
            if d.is_dir():
                for f in sorted(d.glob("*.md")):
                    try:
                        skill = _parse_skill_file(f)
                        seen[skill.name] = skill
                    except Exception:
                        pass
                for f in sorted(d.glob("*/SKILL.md")):
                    try:
                        skill = _parse_skill_file(f)
                        seen[skill.name] = skill
                    except Exception:
                        pass
        return list(seen.values())

    #转换为字符串
    def render_prompt(self, skill: Skill, arguments: str) -> str:
        return skill.system_prompt_template.replace("$ARGUMENTS", arguments)