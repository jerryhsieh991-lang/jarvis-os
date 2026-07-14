"""Vault (server/memory.py) — plain-markdown knowledge store."""
from server.memory import Vault


def _vault(tmp_path):
    return Vault(tmp_path, inbox="00_Inbox", reports="10_Reports", sessions="20_Sessions")


def test_write_note_creates_file_with_backlink(tmp_path):
    v = _vault(tmp_path)
    path = v.write_note("Groceries", "buy milk", links=["Inbox"])
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "buy milk" in text
    assert "[[Inbox]]" in text


def test_search_finds_note_by_term(tmp_path):
    v = _vault(tmp_path)
    v.write_note("Groceries", "buy milk today", links=["Inbox"])
    hits = v.search("milk")
    assert hits, "expected the milk note to be found"
    found_path, snippet = hits[0]
    assert "milk" in snippet.lower()


def test_search_misses_absent_term(tmp_path):
    v = _vault(tmp_path)
    v.write_note("Groceries", "buy milk", links=["Inbox"])
    assert v.search("quantum") == []


def test_stats_counts_notes_and_links(tmp_path):
    v = _vault(tmp_path)
    v.write_note("One", "alpha", links=["Inbox"])
    v.write_note("Two", "beta", links=["Inbox", "Projects"])
    stats = v.stats()
    assert stats["notes"] == 2
    # 1 link in the first note + 2 in the second
    assert stats["links"] == 3
