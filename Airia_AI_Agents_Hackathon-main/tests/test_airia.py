"""
Phase 2 Tests: Airia Client
- Unit tests: validate request payload construction (no credentials needed)
- Live test: call a real Airia pipeline and verify a non-empty response
  (requires AIRIA_API_KEY + AIRIA_TEST_PIPELINE_ID in .env)
"""

import os
import sys
import pytest
from unittest.mock import patch, MagicMock
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integrations.airia_client import run_pipeline

# ---------------------------------------------------------------------------
# Credentials check
# ---------------------------------------------------------------------------

AIRIA_API_KEY          = os.getenv("AIRIA_API_KEY", "")
AIRIA_TEST_PIPELINE_ID = os.getenv("AIRIA_CODE_ANALYSIS_PIPELINE_ID", "")

_has_creds = bool(AIRIA_API_KEY and AIRIA_TEST_PIPELINE_ID)
_skip_msg  = "Set AIRIA_API_KEY and AIRIA_CODE_ANALYSIS_PIPELINE_ID in .env"


# ---------------------------------------------------------------------------
# Unit tests: mock the HTTP call, verify request shape
# ---------------------------------------------------------------------------

def _make_mock_response(result_text: str) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"result": result_text, "outputs": []}
    return mock_resp


def test_run_pipeline_returns_dict():
    """run_pipeline should return a dict with 'result' and 'outputs' keys."""
    with patch("integrations.airia_client.httpx.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_client.post.return_value = _make_mock_response("Test output")
        result = run_pipeline("fake-pipeline-id", "Hello Airia")

    assert isinstance(result, dict)
    assert "result" in result
    assert "outputs" in result
    assert "_raw" in result


def test_run_pipeline_result_text():
    """The 'result' key should contain the text from the API response."""
    with patch("integrations.airia_client.httpx.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_client.post.return_value = _make_mock_response("Added payment endpoint")
        result = run_pipeline("fake-pipeline-id", "Summarise this PR")

    assert result["result"] == "Added payment endpoint"


def test_run_pipeline_sends_correct_payload():
    """Verify the payload sent to Airia contains userMessage."""
    with patch("integrations.airia_client.httpx.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_client.post.return_value = _make_mock_response("ok")
        run_pipeline("fake-id", "my prompt")

    call_kwargs = mock_client.post.call_args
    sent_payload = call_kwargs.kwargs.get("json") or call_kwargs.args[1]
    assert sent_payload["UserInput"] == "my prompt"
    assert sent_payload["asyncOutput"] is False


def test_run_pipeline_sends_api_key_header():
    """Verify the X-API-Key header is included in the request."""
    with patch.dict(os.environ, {"AIRIA_API_KEY": "test-key-123"}):
        with patch("integrations.airia_client.httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.post.return_value = _make_mock_response("ok")
            run_pipeline("fake-id", "prompt")

        call_kwargs = mock_client.post.call_args
        sent_headers = call_kwargs.kwargs.get("headers") or {}
        assert sent_headers.get("X-API-Key") == "test-key-123"


def test_run_pipeline_raises_without_api_key():
    """run_pipeline should raise ValueError if AIRIA_API_KEY is not set."""
    with patch.dict(os.environ, {"AIRIA_API_KEY": ""}):
        # reload to pick up patched env
        import importlib
        import integrations.airia_client as mod
        importlib.reload(mod)
        with pytest.raises(ValueError, match="AIRIA_API_KEY"):
            mod.run_pipeline("fake-id", "prompt")


# ---------------------------------------------------------------------------
# Live test: real Airia pipeline call
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _has_creds, reason=_skip_msg)
def test_run_pipeline_live():
    """
    Calls the real Airia Code Analysis pipeline with a sample PR description.
    Asserts the response contains non-empty text.
    """
    test_input = (
        "Summarise this pull request in one sentence:\n"
        "PR Title: Add Payment API endpoint\n"
        "Changed files: src/payments/api.py, src/auth/middleware.py\n"
        "PR Body: Introduces POST /payments to handle payment processing. "
        "Also updates auth middleware to support the new endpoint."
    )

    result = run_pipeline(AIRIA_TEST_PIPELINE_ID, test_input)

    print(f"\n[OK] Airia pipeline response:\n{result['result']}")
    assert isinstance(result["result"], str)
    assert len(result["result"]) > 0, "Expected a non-empty response from Airia pipeline"
