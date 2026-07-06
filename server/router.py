"""The intent router — the article's three-lane brain:

1. Regex fast-paths  → instant, zero LLM cost (time, open app, notes…)
2. Skill dispatch    → only the matched SKILL.md body is injected as system
                       prompt, so the context window stays lean
3. General LLM chat  → everything else goes to the local model with vault
                       context when it helps
"""
from __future__ import annotations

import datetime as _dt
import re
import subprocess
from dataclasses import dataclass

from .llm import LocalLLM
from .memory import Vault
from .skills_loader import Skill


@dataclass
class RouteResult:
    text: str
    lane: str            # "fast" | "skill:<name>" | "chat"
    saved_to: str | None = None


class Router:
    def __init__(self, llm: LocalLLM, vault: Vault, skills: list[Skill], assistant_name: str,
                 hermes=None):
        self.llm = llm
        self.vault = vault
        self.skills = skills
        self.assistant_name = assistant_name
        self.hermes = hermes  # optional HermesAdapter — None on clean installs

    # ---------------------------------------------------------------- fast
    _TIME_RE = re.compile(r"\b(time|clock)\b|幾點|几点", re.I)
    _DATE_RE = re.compile(r"\b(date|today)\b|日期|幾號|几号", re.I)
    _OPEN_RE = re.compile(r"^(?:open|launch|打開|打开)\s+(.+)$", re.I)
    _NOTE_RE = re.compile(r"^(?:note|remember|筆記|笔记|記下|记下)[:,\s]+(.+)$", re.I)

    def _fast_path(self, text: str) -> RouteResult | None:
        t = text.strip()
        if self._TIME_RE.search(t) and len(t) < 40:
            return RouteResult(_dt.datetime.now().strftime("It's %H:%M."), "fast")
        if self._DATE_RE.search(t) and len(t) < 40:
            return RouteResult(_dt.date.today().strftime("Today is %A, %B %d, %Y."), "fast")
        if m := self._OPEN_RE.match(t):
            app = m.group(1).strip().title()
            try:
                subprocess.run(["open", "-a", app], check=True, capture_output=True, timeout=10)
                return RouteResult(f"Opening {app}.", "fast")
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                return RouteResult(f"I couldn't find an app called {app}.", "fast")
        if m := self._NOTE_RE.match(t):
            note = m.group(1).strip()
            path = self.vault.write_note(note[:60], note, links=["Inbox"])
            return RouteResult("Noted.", "fast", saved_to=str(path))
        return None

    # --------------------------------------------------------------- skill
    def _match_skill(self, text: str) -> Skill | None:
        for skill in self.skills:
            if skill.name != "system" and skill.matches(text):
                return skill
        return None

    # ---------------------------------------------------------------- main
    def handle(self, text: str) -> RouteResult:
        self.vault.append_session("user", text)
        result = self._route(text)
        self.vault.append_session(self.assistant_name, result.text)
        return result

    def _route(self, text: str) -> RouteResult:
        # a pending Hermes confirmation outranks everything — "confirm"/"cancel"
        if self.hermes and self.hermes.pending and (intent := self.hermes.match(text)):
            result = self.hermes.handle(intent, text)
            return RouteResult(result.text, "hermes")

        if fast := self._fast_path(text):
            return fast

        if self.hermes and (intent := self.hermes.match(text)):
            result = self.hermes.handle(intent, text)
            lane = "hermes:pending-confirm" if result.pending else f"hermes:{intent}"
            return RouteResult(result.text, lane)

        if skill := self._match_skill(text):
            system = (
                f"You are {self.assistant_name}, a local voice OS. "
                f"Load and obey this skill exactly:\n\n{skill.body}"
            )
            answer = self.llm.chat(text, system=system)
            saved = None
            if len(answer) > 400:  # substantial outputs become vault reports
                path = self.vault.write_report(
                    f"{skill.name} — {text[:40]}", answer,
                    links=[skill.name.replace("_", " ").title()],
                )
                saved = str(path)
            return RouteResult(answer, f"skill:{skill.name}", saved_to=saved)

        # general chat — give the model a peek at relevant memory
        context = ""
        hits = self.vault.search(text, limit=2)
        if hits:
            joined = "\n".join(f"- {p.name}: {s[:200]}" for p, s in hits)
            context = f"\n\nRelevant notes from your vault:\n{joined}"
        system = (
            f"You are {self.assistant_name}, a concise local assistant. "
            "Answer in the user's language. Two sentences unless asked for more."
            f"{context}"
        )
        return RouteResult(self.llm.chat(text, system=system), "chat")
