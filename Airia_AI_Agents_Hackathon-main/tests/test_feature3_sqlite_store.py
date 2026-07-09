"""
Feature 3 Tests — SQLite Staging Store

Verifies that the SQLite-backed store provides:
  1. Exact same public API behaviour as the old JSON store.
  2. Concurrent-safe: multiple staged entries for the same PR are ordered correctly.
  3. pop_staged_updates() atomically clears the rows.
  4. peek_staged_updates() is non-destructive.
  5. clear_staged_updates() silently drops all rows.
  6. Idempotency functions (mark/is processed) still work correctly.
  7. The DB file is actually created on disk.

All tests use a temp-path fixture to avoid touching data/docusync.db.
No LLM or HTTP calls are made.
"""

import os
import sys
import json
import sqlite3
import pytest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# Fixture — redirect DB_PATH to a temp directory for full isolation
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    import agents.staging_store as ss
    monkeypatch.setattr(ss, "DATA_DIR", tmp_path)
    monkeypatch.setattr(ss, "DB_PATH", tmp_path / "docusync_test.db")
    yield tmp_path / "docusync_test.db"


# ---------------------------------------------------------------------------
# Tests — staged_updates table
# ---------------------------------------------------------------------------

class TestStagedUpdates:

    def test_stage_and_peek_single_update(self):
        from agents.staging_store import stage_pending_doc_update, peek_staged_updates
        stage_pending_doc_update(1, "create_or_update_page", {"title": "Hello", "body_markdown": "# Hi"})
        updates = peek_staged_updates(1)
        assert len(updates) == 1
        assert updates[0]["action"] == "create_or_update_page"
        assert updates[0]["kwargs"]["title"] == "Hello"

    def test_peek_does_not_consume_updates(self):
        from agents.staging_store import stage_pending_doc_update, peek_staged_updates
        stage_pending_doc_update(2, "update_page", {"page_id": "abc", "title": "Old"})
        peek_staged_updates(2)
        # Second peek should still return the same row
        assert len(peek_staged_updates(2)) == 1

    def test_pop_returns_and_deletes(self):
        from agents.staging_store import stage_pending_doc_update, pop_staged_updates, peek_staged_updates
        stage_pending_doc_update(3, "create_or_update_page", {"title": "Pop me"})
        updates = pop_staged_updates(3)
        assert len(updates) == 1
        assert updates[0]["kwargs"]["title"] == "Pop me"
        # After pop, nothing should remain
        assert peek_staged_updates(3) == []

    def test_pop_empty_returns_empty_list(self):
        from agents.staging_store import pop_staged_updates
        assert pop_staged_updates(999) == []

    def test_multiple_updates_same_pr_ordered(self):
        """Multiple updates for the same PR should come back in insertion order."""
        from agents.staging_store import stage_pending_doc_update, peek_staged_updates
        stage_pending_doc_update(4, "create_or_update_page", {"title": "First"})
        stage_pending_doc_update(4, "update_page",           {"title": "Second"})
        stage_pending_doc_update(4, "create_or_update_page", {"title": "Third"})
        updates = peek_staged_updates(4)
        assert len(updates) == 3
        assert [u["kwargs"]["title"] for u in updates] == ["First", "Second", "Third"]

    def test_different_prs_are_isolated(self):
        """Updates for PR 10 must not appear when querying PR 11."""
        from agents.staging_store import stage_pending_doc_update, peek_staged_updates
        stage_pending_doc_update(10, "create_or_update_page", {"title": "PR10 Doc"})
        stage_pending_doc_update(11, "update_page",           {"title": "PR11 Doc"})
        assert peek_staged_updates(10)[0]["kwargs"]["title"] == "PR10 Doc"
        assert peek_staged_updates(11)[0]["kwargs"]["title"] == "PR11 Doc"

    def test_clear_staged_updates_removes_rows(self):
        from agents.staging_store import stage_pending_doc_update, clear_staged_updates, peek_staged_updates
        stage_pending_doc_update(5, "create_or_update_page", {"title": "Gone"})
        clear_staged_updates(5)
        assert peek_staged_updates(5) == []

    def test_clear_nonexistent_pr_does_not_raise(self):
        from agents.staging_store import clear_staged_updates
        clear_staged_updates(8888)  # must not raise

    def test_kwargs_with_nested_data_roundtrip(self):
        """Complex kwargs (nested dicts, lists) must survive the JSON round-trip."""
        from agents.staging_store import stage_pending_doc_update, peek_staged_updates
        complex_kwargs = {
            "title": "Complex",
            "body_markdown": "## Section\n- item1\n- item2",
            "metadata": {"version": 3, "tags": ["api", "docs"]},
        }
        stage_pending_doc_update(6, "update_page", complex_kwargs)
        result = peek_staged_updates(6)[0]["kwargs"]
        assert result["metadata"]["tags"] == ["api", "docs"]
        assert result["metadata"]["version"] == 3


# ---------------------------------------------------------------------------
# Tests — processed_prs table (idempotency, Feature 4 integrated)
# ---------------------------------------------------------------------------

class TestProcessedPRs:

    def test_unknown_sha_not_processed(self):
        from agents.staging_store import is_pr_processed
        assert is_pr_processed("unknown_sha") is False

    def test_marked_sha_is_processed(self):
        from agents.staging_store import mark_pr_processed, is_pr_processed
        mark_pr_processed("sha_abc")
        assert is_pr_processed("sha_abc") is True

    def test_double_mark_is_idempotent(self):
        from agents.staging_store import mark_pr_processed, is_pr_processed
        mark_pr_processed("sha_dup")
        mark_pr_processed("sha_dup")   # INSERT OR REPLACE — must not raise
        assert is_pr_processed("sha_dup") is True

    def test_different_shas_independent(self):
        from agents.staging_store import mark_pr_processed, is_pr_processed
        mark_pr_processed("sha_x")
        assert is_pr_processed("sha_x") is True
        assert is_pr_processed("sha_y") is False


# ---------------------------------------------------------------------------
# Tests — DB file creation & schema
# ---------------------------------------------------------------------------

class TestDatabaseFile:

    def test_db_file_created_on_first_use(self, isolated_db):
        from agents.staging_store import stage_pending_doc_update
        assert not isolated_db.exists()
        stage_pending_doc_update(1, "create_or_update_page", {"title": "Trigger"})
        assert isolated_db.exists(), "docusync.db was not created"

    def test_db_has_correct_tables(self, isolated_db):
        from agents.staging_store import stage_pending_doc_update
        stage_pending_doc_update(1, "create_or_update_page", {"title": "T"})
        conn = sqlite3.connect(str(isolated_db))
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        conn.close()
        assert "staged_updates" in tables
        assert "processed_prs" in tables

    def test_wal_mode_enabled(self, isolated_db):
        from agents.staging_store import stage_pending_doc_update
        stage_pending_doc_update(1, "create_or_update_page", {"title": "WAL"})
        conn = sqlite3.connect(str(isolated_db))
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        assert mode == "wal"
