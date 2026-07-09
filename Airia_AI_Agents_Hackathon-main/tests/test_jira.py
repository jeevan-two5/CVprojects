"""
Phase 2 Tests: Jira Client
Live tests — require JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN, JIRA_TEST_ISSUE in .env
"""

import os
import sys
import pytest
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integrations.jira_client import get_issue, JiraIssue, _extract_adf_text

# ---------------------------------------------------------------------------
# Credentials check
# ---------------------------------------------------------------------------

JIRA_BASE_URL   = os.getenv("JIRA_BASE_URL", "")
JIRA_EMAIL      = os.getenv("JIRA_EMAIL", "")
JIRA_API_TOKEN  = os.getenv("JIRA_API_TOKEN", "")
JIRA_TEST_ISSUE = os.getenv("JIRA_TEST_ISSUE", "")   # e.g. "PAY-21"

_has_creds = all([JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN, JIRA_TEST_ISSUE])
_skip_msg  = "Set JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN, JIRA_TEST_ISSUE in .env"


# ---------------------------------------------------------------------------
# Unit test: ADF text extractor (no credentials needed)
# ---------------------------------------------------------------------------

def test_extract_adf_text_simple():
    """ADF extractor should pull plain text out of a simple ADF node."""
    adf = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Hello"},
                    {"type": "text", "text": "world"},
                ]
            }
        ]
    }
    result = _extract_adf_text(adf)
    assert "Hello" in result
    assert "world" in result


def test_extract_adf_text_none():
    assert _extract_adf_text(None) == ""


def test_extract_adf_text_empty():
    assert _extract_adf_text({}) == ""


# ---------------------------------------------------------------------------
# Live Jira API tests
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _has_creds, reason=_skip_msg)
def test_get_issue_returns_jira_issue():
    """Fetch a real Jira issue and verify the return type."""
    issue = get_issue(JIRA_TEST_ISSUE)
    assert isinstance(issue, JiraIssue)


@pytest.mark.skipif(not _has_creds, reason=_skip_msg)
def test_get_issue_key_matches():
    """The returned issue key should match what we requested."""
    issue = get_issue(JIRA_TEST_ISSUE)
    assert issue.key == JIRA_TEST_ISSUE


@pytest.mark.skipif(not _has_creds, reason=_skip_msg)
def test_get_issue_summary_not_empty():
    """Issue summary should be a non-empty string."""
    issue = get_issue(JIRA_TEST_ISSUE)
    print(f"\n[OK] Jira Issue: {issue.key} | {issue.summary} | Status: {issue.status}")
    assert isinstance(issue.summary, str)
    assert len(issue.summary) > 0


@pytest.mark.skipif(not _has_creds, reason=_skip_msg)
def test_get_issue_status_not_empty():
    """Issue status should be a non-empty string (e.g. 'In Progress')."""
    issue = get_issue(JIRA_TEST_ISSUE)
    assert len(issue.status) > 0


@pytest.mark.skipif(not _has_creds, reason=_skip_msg)
def test_get_issue_description_is_string():
    """Description should always be a string (even if empty for issues with no desc)."""
    issue = get_issue(JIRA_TEST_ISSUE)
    assert isinstance(issue.description, str)
