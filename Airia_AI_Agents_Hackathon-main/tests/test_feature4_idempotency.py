"""
Feature 4 Tests — Webhook Idempotency

Verifies that:
1. An unknown SHA is NOT flagged as processed.
2. After mark_pr_processed(), the SHA IS flagged.
3. A second mark call for the same SHA is idempotent (no error).
4. Different SHAs are tracked independently.
5. The pipeline skips gracefully when merge_commit_sha is empty.

No LLM or HTTP calls — purely tests the JSON-backed store functions.
"""

import os
import sys
import json
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """
    Redirect DB_PATH to a temp directory so tests don't pollute
    data/docusync.db and don't interfere with each other.
    """
    import agents.staging_store as ss
    monkeypatch.setattr(ss, "DATA_DIR", tmp_path)
    monkeypatch.setattr(ss, "DB_PATH", tmp_path / "docusync_test.db")
    yield tmp_path / "docusync_test.db"


# ---------------------------------------------------------------------------
# Unit tests — is_pr_processed / mark_pr_processed
# ---------------------------------------------------------------------------

class TestIdempotencyFunctions:

    def test_unknown_sha_is_not_processed(self):
        from agents.staging_store import is_pr_processed
        assert is_pr_processed("deadbeef1234") is False

    def test_sha_is_processed_after_marking(self):
        from agents.staging_store import mark_pr_processed, is_pr_processed
        sha = "abc123deadbeef"
        assert is_pr_processed(sha) is False
        mark_pr_processed(sha)
        assert is_pr_processed(sha) is True

    def test_double_mark_does_not_raise(self):
        from agents.staging_store import mark_pr_processed, is_pr_processed
        sha = "duplicate_sha_test"
        mark_pr_processed(sha)
        mark_pr_processed(sha)          # must not raise
        assert is_pr_processed(sha) is True

    def test_different_shas_are_independent(self):
        from agents.staging_store import mark_pr_processed, is_pr_processed
        sha_a = "sha_for_pr_10"
        sha_b = "sha_for_pr_11"
        mark_pr_processed(sha_a)
        assert is_pr_processed(sha_a) is True
        assert is_pr_processed(sha_b) is False

    def test_processed_record_has_timestamp(self, isolated_db):
        import sqlite3
        from agents.staging_store import mark_pr_processed
        mark_pr_processed("ts_sha")
        conn = sqlite3.connect(str(isolated_db))
        row = conn.execute("SELECT processed_at FROM processed_prs WHERE sha='ts_sha'").fetchone()
        conn.close()
        assert row is not None
        # Timestamp must be an ISO-8601 string with a T separator
        assert "T" in row[0]

    def test_missing_file_returns_false_gracefully(self):
        """is_pr_processed must not raise if the file doesn't exist yet."""
        from agents.staging_store import is_pr_processed
        # With the isolated fixture the file was never created yet
        assert is_pr_processed("ghost_sha") is False


# ---------------------------------------------------------------------------
# Integration test — pipeline skips on duplicate SHA (no HTTP/LLM calls)
# ---------------------------------------------------------------------------

class TestPipelineIdempotency:

    def test_pipeline_skips_on_duplicate_sha(self, caplog):
        """
        run_docusync_pipeline() must return early without calling parse_and_enrich
        when the merge SHA has already been processed.
        """
        import logging
        from agents.staging_store import mark_pr_processed

        sha = "pipeline_test_sha_001"
        mark_pr_processed(sha)

        payload = {
            "pull_request": {
                "number": 42,
                "title": "Duplicate PR",
                "merge_commit_sha": sha,
            }
        }

        # parse_and_enrich would make a real GitHub API call — it must never be called
        with patch("integrations.github_handler.parse_and_enrich") as mock_enrich, \
             caplog.at_level(logging.WARNING, logger="docusync"):
            from main import run_docusync_pipeline
            run_docusync_pipeline(payload)

        mock_enrich.assert_not_called()
        assert any("already processed" in r.message.lower() or "already processed" in r.getMessage().lower()
                   for r in caplog.records), \
            "Expected a warning about already-processed PR in logs"

    def test_pipeline_runs_normally_for_new_sha(self):
        """
        run_docusync_pipeline() must NOT skip when the SHA is fresh.
        (We only check that is_pr_processed returns False — full pipeline
        execution is tested by other existing tests.)
        """
        from agents.staging_store import is_pr_processed
        assert is_pr_processed("brand_new_sha_xyz") is False

    def test_pipeline_tolerates_missing_sha(self):
        """
        If merge_commit_sha is absent from the payload (edge case),
        the pipeline must not raise — idempotency check is simply skipped.
        """
        payload = {
            "pull_request": {
                "number": 99,
                "title": "No SHA PR",
                # no merge_commit_sha key
            }
        }
        # parse_and_enrich will fail without network — that is expected.
        # We only care it doesn't raise from our idempotency code.
        with patch("integrations.github_handler.parse_and_enrich", side_effect=Exception("no github")), \
             patch("agents.staging_store.is_pr_processed") as mock_check:
            from main import run_docusync_pipeline
            run_docusync_pipeline(payload)

        # When sha is empty, is_pr_processed should never even be called
        mock_check.assert_not_called()
