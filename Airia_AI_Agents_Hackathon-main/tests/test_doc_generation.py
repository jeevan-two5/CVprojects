"""
Phase 3b Tests: Doc Generation Agent
Tests endpoint detection, Confluence page creation, and API doc generation.
"""

import os
import pytest
from unittest.mock import patch
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

from integrations.github_handler import PREvent
from agents.doc_generation import detect_new_endpoints, run


# ---------------------------------------------------------------------------
# Unit: Endpoint detection from diff
# ---------------------------------------------------------------------------

def test_detect_fastapi_post_endpoint():
    """Should detect a new FastAPI POST endpoint from the diff."""
    diff = (
        "--- a/src/api/payments.py\n"
        "+++ b/src/api/payments.py\n"
        "@@ -10,0 +11,5 @@\n"
        '+@app.post("/payments/charge")\n'
        "+async def charge_payment(amount: int):\n"
        "+    return stripe.Charge.create(amount=amount)\n"
    )
    endpoints = detect_new_endpoints(diff)
    assert len(endpoints) == 1
    assert endpoints[0]["method"] == "POST"
    assert endpoints[0]["path"]   == "/payments/charge"
    assert endpoints[0]["func"]   == "charge_payment"
    print(f"\nDetected endpoint: {endpoints[0]}")


def test_detect_multiple_endpoints():
    """Should detect multiple different method endpoints from one diff."""
    diff = (
        '+@router.get("/users")\n'
        "+async def list_users(): pass\n"
        "+\n"
        '+@router.post("/users")\n'
        "+async def create_user(): pass\n"
        "+\n"
        '+@router.delete("/users/{user_id}")\n'
        "+async def delete_user(user_id: int): pass\n"
    )
    endpoints = detect_new_endpoints(diff)
    methods = {e["method"] for e in endpoints}
    assert "GET"    in methods
    assert "POST"   in methods
    assert "DELETE" in methods
    assert len(endpoints) == 3
    labels = [e["method"] + " " + e["path"] for e in endpoints]
    print(f"\nDetected {len(endpoints)} endpoints: {labels}")


def test_detect_no_endpoints_in_plain_code():
    """Should return empty list if no route decorators are added."""
    diff = (
        "+def helper_function():\n"
        "+    return 42\n"
        "+\n"
        '+CONSTANT = "hello"\n'
    )
    endpoints = detect_new_endpoints(diff)
    assert endpoints == []


def test_detect_ignores_removed_endpoints():
    """Should NOT detect endpoints on removed (-) lines."""
    diff = (
        '-@app.get("/old-endpoint")\n'
        "-def old_func(): pass\n"
        "+# endpoint removed\n"
    )
    endpoints = detect_new_endpoints(diff)
    assert endpoints == []


# ---------------------------------------------------------------------------
# Unit: doc generation agent (mocked Confluence + Airia)
# ---------------------------------------------------------------------------

@patch("agents.doc_generation.create_or_update_page")
@patch("agents.doc_generation.run_pipeline")
@patch.dict("os.environ", {"CONFLUENCE_SPACE_KEY": "DS", "AIRIA_CODE_ANALYSIS_PIPELINE_ID": "mock-id"})
def test_run_with_new_api_endpoint(mock_pipeline, mock_confluence):
    """
    When the PR diff contains a new endpoint, run() should:
    - Create a changelog Confluence page
    - Detect the endpoint
    - Call Airia to generate API docs
    - Create a second API Reference Confluence page
    """
    mock_confluence.return_value = {"url": "https://confluence.example.com/page/123"}
    mock_pipeline.return_value   = {"result": "## `POST /payments`\nProcesses a payment."}

    event = PREvent(
        pr_number=99, pr_title="Add payment endpoint", pr_body="",
        head_sha="a1b2", base_branch="main", head_branch="feature/pay",
        repo_full_name="org/repo",
        pr_diff='+@app.post("/payments")\n+async def process_payment(amount: int): pass',
    )

    analysis = {
        "summary": "Added a POST /payments endpoint.",
        "impact":  "Affects the payments module.",
        "risk":    "Minimal.",
    }

    result = run(event, analysis)

    print(f"\nChangelog URL  : {result['changelog_url']}")
    print(f"API Doc URLs   : {result['api_doc_urls']}")
    print(f"New Endpoints  : {result['new_endpoints']}")

    # Should have written 2 Confluence pages (changelog + API doc)
    assert mock_confluence.call_count == 2
    assert len(result["new_endpoints"]) == 1
    assert result["new_endpoints"][0]["method"] == "POST"
    assert len(result["api_doc_urls"]) == 1


@patch("agents.doc_generation.create_or_update_page")
@patch.dict("os.environ", {"CONFLUENCE_SPACE_KEY": "DS"})
def test_run_without_endpoints_skips_api_docs(mock_confluence):
    """When the diff has no API endpoints, only one Confluence page is created."""
    mock_confluence.return_value = {"url": "https://confluence.example.com/page/456"}

    event = PREvent(
        pr_number=100, pr_title="Fix typo", pr_body="",
        head_sha="z1z2", base_branch="main", head_branch="fix/typo",
        repo_full_name="org/repo",
        pr_diff="+# Fixed a typo in the comment",
    )

    result = run(event, {"summary": "Fixed typo.", "impact": "None.", "risk": "None."})

    assert mock_confluence.call_count == 1    # only changelog page
    assert result["api_doc_urls"] == []
    assert result["new_endpoints"] == []
