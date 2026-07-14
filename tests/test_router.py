"""Router fast-path lanes (server/router.py) — zero LLM, zero network."""
import re

import pytest

from server.llm import LocalLLM
from server.memory import Vault
from server.router import Router


@pytest.fixture
def router(tmp_path, monkeypatch):
    llm = LocalLLM("http://127.0.0.1:11434", "test-model")
    # Canned, offline stand-ins so the router never reaches ollama.
    monkeypatch.setattr(llm, "chat", lambda *a, **k: "canned answer", raising=True)
    monkeypatch.setattr(
        llm, "chat_stream", lambda *a, **k: iter(["canned ", "stream"]), raising=True
    )
    vault = Vault(tmp_path, inbox="00_Inbox", reports="10_Reports", sessions="20_Sessions")
    return Router(llm, vault, skills=[], assistant_name="JARVIS")


def test_time_fastpath(router):
    result = router.handle("what time is it")
    assert result.lane == "fast"
    assert re.match(r"It's \d{2}:\d{2}\.", result.text)


def test_note_fastpath_text_and_lane(router):
    result = router.handle("note buy milk")
    assert result.lane == "fast"
    assert result.text == "Noted."
    assert result.saved_to is not None


def test_note_fastpath_writes_vault_file(router, tmp_path):
    result = router.handle("note buy milk")
    written = tmp_path / "00_Inbox"
    notes = list(written.glob("*.md"))
    assert notes, "expected a note file under the inbox folder"
    body = notes[0].read_text(encoding="utf-8")
    assert "buy milk" in body
    assert "[[Inbox]]" in body
