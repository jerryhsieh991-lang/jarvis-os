"""Step 1 — skill architecture.

Each skill is a folder under skills/ holding a SKILL.md with YAML-ish
frontmatter (name, description, triggers). Only the frontmatter is kept
resident; the body is loaded on demand so the context window is never
wasted on skills that aren't in play.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Skill:
    name: str
    description: str
    triggers: list[str]
    path: Path
    _body: str | None = field(default=None, repr=False)

    @property
    def body(self) -> str:
        """Full SKILL.md body — read lazily, cached."""
        if self._body is None:
            text = self.path.read_text(encoding="utf-8")
            self._body = _FRONTMATTER_RE.sub("", text, count=1).strip()
        return self._body

    def matches(self, text: str) -> bool:
        lowered = text.lower()
        return any(t.lower() in lowered for t in self.triggers)


_FRONTMATTER_RE = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)


def _parse_frontmatter(text: str) -> dict[str, str]:
    m = re.match(r"\A---\n(.*?)\n---", text, re.DOTALL)
    fields: dict[str, str] = {}
    if not m:
        return fields
    for line in m.group(1).splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
    return fields


def load_skills(skills_dir: Path) -> list[Skill]:
    skills: list[Skill] = []
    for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
        fm = _parse_frontmatter(skill_md.read_text(encoding="utf-8"))
        triggers = [t.strip() for t in fm.get("triggers", "").strip("[]").split(",") if t.strip()]
        skills.append(
            Skill(
                name=fm.get("name", skill_md.parent.name),
                description=fm.get("description", ""),
                triggers=triggers,
                path=skill_md,
            )
        )
    return skills
