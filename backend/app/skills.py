"""Skills, the way Claude gets them: the model first sees only each skill's name and description, and pulls the
full SKILL.md (or one of its reference files) with the load_skill tool when it decides it needs it."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import config


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    path: Path

    @property
    def references(self) -> list[str]:
        ref = self.path.parent / "references"
        return sorted(p.name for p in ref.glob("*.md")) if ref.is_dir() else []


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Minimal YAML frontmatter: `key: value` lines, plus folded (>) or literal (|) multi-line values."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?", text, re.S)
    if not m:
        return {}, text
    meta: dict[str, str] = {}
    key, block = None, []
    for line in m.group(1).splitlines():
        km = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if km and not line.startswith((" ", "\t")):
            if key and block:
                meta[key] = " ".join(block).strip()
            key, value = km.group(1), km.group(2).strip()
            block = [] if value in (">", "|", ">-", "|-") else [value.strip("\"'")]
        elif key and line.strip():
            block.append(line.strip())
    if key and block:
        meta[key] = " ".join(block).strip()
    return meta, text[m.end():]


def discover(dirs: list[Path] | None = None) -> dict[str, Skill]:
    skills: dict[str, Skill] = {}
    for d in dirs or config.SKILL_DIRS:
        for path in sorted(Path(d).glob("*/SKILL.md")):
            meta, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
            name = meta.get("name") or path.parent.name
            skills.setdefault(name, Skill(name, meta.get("description", ""), path))
    return skills


def catalog(skills: dict[str, Skill]) -> str:
    lines = []
    for s in skills.values():
        refs = f" (references: {', '.join(s.references)})" if s.references else ""
        lines.append(f"- {s.name}: {s.description}{refs}")
    return "\n".join(lines)


def load(skills: dict[str, Skill], name: str, reference: str | None = None) -> str:
    s = skills.get(name)
    if not s:
        raise KeyError(f"no skill named {name!r}; available: {', '.join(skills)}")
    if reference:
        if reference not in s.references:  # only the listed files: no path tricks
            raise KeyError(f"skill {name!r} has no reference {reference!r}; available: {', '.join(s.references) or 'none'}")
        return (s.path.parent / "references" / reference).read_text(encoding="utf-8")
    return s.path.read_text(encoding="utf-8")
