"""Optional Hermes adapter — bridges voice commands to a locally-installed
Hermes agent stack (https://…/.hermes) via its CLIs.

Design rules:
- The repo stays clean: if the bin dir doesn't exist, the adapter reports
  unavailable and jarvis-os behaves exactly as before.
- Hermes owns its own credentials/state (~/.hermes is never written here).
- Read-only intents (inbox, search, news, calendar) run immediately.
- Side-effect intents (send email) ALWAYS park a pending action that the
  user must approve with "confirm" — voice or text — or drop with "cancel".
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class HermesResult:
    text: str
    pending: dict | None = None  # set when a side-effect awaits confirmation


class HermesAdapter:
    def __init__(self, bin_dir: str | Path, llm=None):
        self.bin = Path(bin_dir).expanduser()
        self.llm = llm
        self.pending: dict | None = None

    def available(self) -> bool:
        return (self.bin / "hermes-google").exists()

    # ------------------------------------------------------------- intents
    _SEARCH_RE = re.compile(r"^(?:search(?: the web)?(?: for)?|google|搜尋|搜索)\s+(.+)$", re.I)
    _NEWS_RE = re.compile(r"^(?:news(?: about| on)?|新聞)\s*(.*)$", re.I)
    _MAIL_CHECK_RE = re.compile(r"\b(?:check|read|list|any)\b.*\b(?:e?mails?|inbox)\b|(?:看|查).*(?:郵件|信箱)", re.I)
    _CAL_RE = re.compile(r"\b(?:calendar|agenda|events?)\b|行事曆|日曆", re.I)
    _MAIL_SEND_RE = re.compile(
        r"^(?:send|write)\s+(?:an?\s+)?e?mail\s+to\s+(?P<to>\S+@\S+)\s+(?:about|saying|that)?\s*(?P<topic>.+)$", re.I)
    _CONFIRM_RE = re.compile(r"^(?:confirm|yes,? send(?: it)?|確認|發送)\b", re.I)
    _CANCEL_RE = re.compile(r"^(?:cancel|no|abort|取消)\b", re.I)

    def match(self, text: str) -> str | None:
        t = text.strip()
        if self.pending and (self._CONFIRM_RE.match(t) or self._CANCEL_RE.match(t)):
            return "resolve_pending"
        if self._MAIL_SEND_RE.match(t):
            return "mail_send"
        if self._SEARCH_RE.match(t):
            return "search"
        if self._NEWS_RE.match(t) and len(t) < 80:
            return "news"
        if self._MAIL_CHECK_RE.search(t):
            return "mail_check"
        if self._CAL_RE.search(t) and len(t) < 60:
            return "calendar"
        return None

    # -------------------------------------------------------------- handle
    def handle(self, intent: str, text: str) -> HermesResult:
        try:
            return getattr(self, f"_do_{intent}")(text)
        except subprocess.TimeoutExpired:
            return HermesResult("Hermes took too long — try again.")
        except (subprocess.CalledProcessError, json.JSONDecodeError, OSError) as e:
            return HermesResult(f"Hermes error: {type(e).__name__}. Is the Hermes stack healthy? (hermes-health)")

    def _cli(self, name: str, *args: str, timeout: int = 60):
        out = subprocess.run(
            [str(self.bin / name), *args],
            capture_output=True, text=True, check=True, timeout=timeout,
        ).stdout
        return json.loads(out) if out.strip() else []

    # -- read-only lanes --------------------------------------------------
    def _do_mail_check(self, text: str) -> HermesResult:
        query = "is:unread" if re.search(r"unread|新", text, re.I) else ""
        args = ["gmail", "list", "--limit", "5"] + (["--query", query] if query else [])
        mails = self._cli("hermes-google", *args)
        if not mails:
            return HermesResult("Inbox is clear — nothing new.")
        lines = [f"{i}. {_sender(m['from'])} — {m['subject']}" for i, m in enumerate(mails, 1)]
        return HermesResult(f"Latest {len(mails)} emails:\n" + "\n".join(lines))

    def _do_search(self, text: str) -> HermesResult:
        query = self._SEARCH_RE.match(text.strip()).group(1)
        hits = self._cli("hermes-search", "search", query, "--limit", "3")
        if not hits:
            return HermesResult(f"No results for {query}.")
        if self.llm:  # voice-friendly digest via the local brain
            corpus = "\n\n".join(f"{h['title']}\n{h['content'][:500]}" for h in hits)
            summary = self.llm.chat(
                f"Question: {query}\n\nSources:\n{corpus}",
                system="Answer the question from the sources in 2 short sentences, in the question's language.")
            return HermesResult(summary + "\n\nSources:\n" + "\n".join(f"- {h['title']} — {h['url']}" for h in hits))
        return HermesResult("\n".join(f"- {h['title']} — {h['url']}" for h in hits))

    def _do_news(self, text: str) -> HermesResult:
        topic = self._NEWS_RE.match(text.strip()).group(1) or "today"
        items = self._cli("hermes-search", "news", topic, "--limit", "5")
        if not items:
            return HermesResult(f"No news found for {topic}.")
        return HermesResult(f"News on {topic}:\n" + "\n".join(f"- {n.get('title', '?')}" for n in items[:5]))

    def _do_calendar(self, _text: str) -> HermesResult:
        events = self._cli("hermes-google", "calendar", "list", "--limit", "5")
        if not events:
            return HermesResult("Calendar is empty ahead.")
        lines = [f"- {e['start'][11:16] if 'T' in e.get('start', '') else e.get('start', '')} {e['summary']}"
                 for e in events]
        return HermesResult("Next events:\n" + "\n".join(lines))

    # -- side-effect lane (confirmation gated) -----------------------------
    def _do_mail_send(self, text: str) -> HermesResult:
        m = self._MAIL_SEND_RE.match(text.strip())
        to, topic = m.group("to"), m.group("topic")
        if self.llm:
            draft = self.llm.chat(
                f"Write a short email about: {topic}. "
                'Reply ONLY with JSON: {"subject": "...", "body": "..."} — body under 120 words, '
                "in the topic's language, no placeholders.",
                system="You draft ready-to-send emails. JSON only.")
            try:
                parsed = json.loads(re.search(r"\{.*\}", draft, re.DOTALL).group(0))
                subject, body = parsed["subject"], parsed["body"]
            except (AttributeError, KeyError, json.JSONDecodeError):
                subject, body = topic[:60], draft
        else:
            subject, body = topic[:60], topic
        self.pending = {"kind": "mail_send", "to": to, "subject": subject, "body": body}
        return HermesResult(
            f"Draft ready — to {to}\nSubject: {subject}\n\n{body}\n\nSay “confirm” to send or “cancel”.",
            pending=self.pending,
        )

    def _do_resolve_pending(self, text: str) -> HermesResult:
        action, self.pending = self.pending, None
        if self._CANCEL_RE.match(text.strip()) or action is None:
            return HermesResult("Cancelled — nothing was sent.")
        if action["kind"] == "mail_send":
            self._cli("hermes-google", "gmail", "send",
                      "--to", action["to"], "--subject", action["subject"], "--body", action["body"])
            return HermesResult(f"Sent to {action['to']}.")
        return HermesResult("Nothing pending.")


def _sender(raw: str) -> str:
    return re.sub(r"\s*<[^>]*>", "", raw).strip() or raw
