"""
Phase 3 Tests: Code Analysis Agent (Enhanced)
Verifies prompt construction, JSON parsing, and live Airia output.
"""

import os
import json
import pytest
from unittest.mock import patch
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

from integrations.github_handler import PREvent, fetch_pr_diff
from agents.code_analysis import build_analysis_prompt, parse_analysis_result, run


# ---------------------------------------------------------------------------
# Unit: Prompt builder
# ---------------------------------------------------------------------------

def test_prompt_contains_all_sections():
    """Prompt must request JSON with summary, impact, and risk keys."""
    event = PREvent(
        pr_number=54, pr_title="Add Stripe endpoint", pr_body="",
        head_sha="abc", base_branch="main", head_branch="feature/PAY-21",
        repo_full_name="org/repo", changed_files=["src/payments/api.py"],
        pr_diff="--- a/src/payments/api.py\n+++ b/src/payments/api.py\n+@app.post('/pay')\n+def pay(): pass",
        jira_issue_key="PAY-21"
    )
    prompt = build_analysis_prompt(event, "As a user, I want to pay via Stripe.")

    print("\n--- GENERATED PROMPT ---\n", prompt, "\n---\n")

    assert '"summary"' in prompt
    assert '"impact"'  in prompt
    assert '"risk"'    in prompt
    assert "+@app.post('/pay')" in prompt      # diff is in the prompt
    assert "As a user, I want to pay via Stripe." in prompt


# ---------------------------------------------------------------------------
# Unit: JSON parser
# ---------------------------------------------------------------------------

def test_parse_clean_json():
    """Parser correctly extracts summary/impact/risk from valid JSON."""
    raw = json.dumps({
        "summary": "Added Stripe endpoint.",
        "impact":  "Affects payment API.",
        "risk":    "Requires Stripe API key in production."
    })
    result = parse_analysis_result(raw)
    assert result["summary"] == "Added Stripe endpoint."
    assert result["impact"]  == "Affects payment API."
    assert result["risk"]    == "Requires Stripe API key in production."


def test_parse_json_in_markdown_block():
    """Parser handles JSON wrapped in markdown code fences (common LLM behavior)."""
    raw = '```json\n{"summary": "S", "impact": "I", "risk": "R"}\n```'
    result = parse_analysis_result(raw)
    assert result["summary"] == "S"
    assert result["impact"]  == "I"
    assert result["risk"]    == "R"


def test_parse_fallback_for_plain_text():
    """If Airia returns plain text (not JSON), put it in summary and leave others blank."""
    result = parse_analysis_result("Something changed.")
    assert result["summary"] == "Something changed."
    assert result["impact"]  == ""
    assert result["risk"]    == ""


# ---------------------------------------------------------------------------
# Unit: Agent run (mocked Airia)
# ---------------------------------------------------------------------------

@patch("agents.code_analysis.run_pipeline")
@patch.dict("os.environ", {"AIRIA_CODE_ANALYSIS_PIPELINE_ID": "mock-guid"})
def test_run_returns_three_sections(mock_pipeline):
    """Agent.run() should return a dict with all three keys."""
    mock_pipeline.return_value = {
        "result": '{"summary": "Added payment endpoint.", "impact": "Touches payment module.", "risk": "Breaking change for v1 clients."}'
    }
    event = PREvent(
        pr_number=1, pr_title="Add payments", pr_body="",
        head_sha="x", base_branch="main", head_branch="feat", repo_full_name="org/repo"
    )
    result = run(event)

    print(f"\n--- AGENT OUTPUT (mocked) ---")
    print(f"Summary : {result['summary']}")
    print(f"Impact  : {result['impact']}")
    print(f"Risk    : {result['risk']}")
    print(f"---\n")

    assert result["summary"] == "Added payment endpoint."
    assert result["impact"]  == "Touches payment module."
    assert result["risk"]    == "Breaking change for v1 clients."


# ---------------------------------------------------------------------------
# Live Test: Real PR diff → Live Airia Pipeline
# ---------------------------------------------------------------------------

_has_creds = bool(os.getenv("AIRIA_API_KEY") and os.getenv("AIRIA_CODE_ANALYSIS_PIPELINE_ID"))

@pytest.mark.skipif(not _has_creds, reason="Missing Airia credentials")
def test_run_agent_live():
    """
    Fetches a real PR diff from the public FastAPI GitHub repo
    and calls the live Airia pipeline. Prints the full three-section analysis.
    """
    REPO   = "fastapi/fastapi"
    PR_NUM = 11111

    print(f"\nFetching real diff from github.com/{REPO}/pull/{PR_NUM} ...")
    real_diff = fetch_pr_diff(REPO, PR_NUM)

    event = PREvent(
        pr_number=PR_NUM, pr_title="Fix typo in docs", pr_body="Small typo fix.",
        head_sha="", base_branch="master", head_branch="patch-1",
        repo_full_name=REPO, pr_diff=real_diff,
    )

    print("Calling live Airia Code Analysis pipeline ...")
    result = run(event)

    print("\n" + "=" * 50)
    print("LIVE AIRIA CODE ANALYSIS RESULT")
    print("=" * 50)
    print(f"  PR SUMMARY: {result['summary']}")
    print(f"  IMPACT    : {result['impact']}")
    print(f"  RISK      : {result['risk']}")
    print("=" * 50 + "\n")

    assert len(result["summary"]) > 0
