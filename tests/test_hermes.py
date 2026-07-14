"""HermesAdapter (server/adapters/hermes.py) — intent match + pending gate.

Everything external is mocked: no real subprocess, no real LLM.
"""
import pytest

from server.adapters import hermes as hermes_mod
from server.adapters.hermes import HermesAdapter


@pytest.fixture
def adapter():
    # llm=None keeps _do_mail_send on its offline branch (no LLM call).
    return HermesAdapter("/nonexistent/bin", llm=None)


def test_match_mail_check(adapter):
    assert adapter.match("check my email") == "mail_check"


def test_match_search(adapter):
    assert adapter.match("search the web for X") == "search"


def test_match_mail_send(adapter):
    assert adapter.match("send email to a@b.com about hello") == "mail_send"


def test_mail_send_parks_pending_then_cancel_clears(adapter, monkeypatch):
    # Guard: no real process may be spawned in this flow.
    def _boom(*a, **k):
        raise AssertionError("subprocess.run must not be called")

    monkeypatch.setattr(hermes_mod.subprocess, "run", _boom, raising=True)

    intent = adapter.match("send email to a@b.com about hello")
    assert intent == "mail_send"
    result = adapter.handle(intent, "send email to a@b.com about hello")
    assert result.pending is not None
    assert adapter.pending is not None
    assert adapter.pending["to"] == "a@b.com"

    # With a pending action, "cancel" resolves it and clears the state.
    assert adapter.match("cancel") == "resolve_pending"
    cancelled = adapter.handle("resolve_pending", "cancel")
    assert "Cancelled" in cancelled.text
    assert adapter.pending is None
