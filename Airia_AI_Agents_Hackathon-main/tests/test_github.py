"""
Phase 2 Tests: GitHub Webhook Handler
- Group A: Fixture-based (always run, no credentials needed)
- Group B: Live GitHub API (requires GITHUB_TOKEN + real repo in .env)
"""

import json
import os
import sys
import pytest
from dotenv import load_dotenv

# Load .env BEFORE any os.getenv() calls
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integrations.github_handler import (
    PREvent,
    parse_pr_payload,
    extract_jira_key,
    fetch_changed_files,
    parse_and_enrich,
)

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "sample_pr_payload.json")


@pytest.fixture
def sample_payload():
    with open(FIXTURE_PATH) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Group A: Fixture-based tests (zero credentials needed)
# ---------------------------------------------------------------------------

def test_parse_returns_pr_event(sample_payload):
    assert isinstance(parse_pr_payload(sample_payload), PREvent)


def test_pr_number(sample_payload):
    assert parse_pr_payload(sample_payload).pr_number == 54


def test_pr_title(sample_payload):
    assert "Payment" in parse_pr_payload(sample_payload).pr_title


def test_pr_body_not_empty(sample_payload):
    assert len(parse_pr_payload(sample_payload).pr_body) > 0


def test_head_sha(sample_payload):
    assert parse_pr_payload(sample_payload).head_sha.startswith("abc123")


def test_repo_full_name(sample_payload):
    assert "/" in parse_pr_payload(sample_payload).repo_full_name


def test_base_branch(sample_payload):
    assert parse_pr_payload(sample_payload).base_branch == "main"


# ---------------------------------------------------------------------------
# Jira key extraction tests
# ---------------------------------------------------------------------------

def test_extract_jira_key_from_branch():
    assert extract_jira_key("feature/PAY-21-payment-api") == "PAY-21"


def test_extract_jira_key_from_title():
    assert extract_jira_key("Add payment endpoint [PAY-21]") == "PAY-21"


def test_extract_jira_key_from_body():
    assert extract_jira_key("Related Jira issue: PAY-21") == "PAY-21"


def test_extract_jira_key_not_found():
    assert extract_jira_key("no issue here") == ""


def test_jira_key_extracted_from_fixture(sample_payload):
    """Branch name 'feature/PAY-21-payment-api' should yield PAY-21."""
    event = parse_pr_payload(sample_payload)
    assert event.jira_issue_key == "PAY-21"


# ---------------------------------------------------------------------------
# Group B: Live GitHub API test (skip if no token configured)
# ---------------------------------------------------------------------------

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_TEST_REPO = os.getenv("GITHUB_TEST_REPO", "")   # e.g. "yourorg/your-repo"
GITHUB_TEST_PR   = int(os.getenv("GITHUB_TEST_PR", "0"))


@pytest.mark.skipif(
    not GITHUB_TOKEN or not GITHUB_TEST_REPO or not GITHUB_TEST_PR,
    reason="Set GITHUB_TOKEN, GITHUB_TEST_REPO, GITHUB_TEST_PR in .env to run live API test",
)
def test_fetch_changed_files_live():
    """Live call: fetch the changed files list from a real GitHub PR."""
    files = fetch_changed_files(GITHUB_TEST_REPO, GITHUB_TEST_PR)
    print(f"\n[OK] Changed files in PR #{GITHUB_TEST_PR}: {files}")
    assert isinstance(files, list)
    assert len(files) > 0, "Expected at least one changed file in the test PR"
    assert all(isinstance(f, str) for f in files)
