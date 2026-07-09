"""
Phase 2 Tests: Slack Client
- test_send_message_live: sends a real message to Slack (requires SLACK_WEBHOOK_URL in .env)
- test_send_doc_update_notification_live: sends a structured doc-update message
"""

import os
import sys
import pytest
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integrations.slack_client import send_message, send_doc_update_notification

SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")


@pytest.mark.skipif(
    not SLACK_WEBHOOK_URL,
    reason="Set SLACK_WEBHOOK_URL in .env to run live Slack tests",
)
def test_send_message_live():
    """Sends a plain test message to the configured Slack channel."""
    result = send_message("[DocuSync AI] Phase 2 smoke test - plain message. Ignore this.")
    assert result is True, "Slack webhook did not return 'ok'"


@pytest.mark.skipif(
    not SLACK_WEBHOOK_URL,
    reason="Set SLACK_WEBHOOK_URL in .env to run live Slack tests",
)
def test_send_doc_update_notification_live():
    """Sends a structured doc-update notification to the configured Slack channel."""
    result = send_doc_update_notification(
        pr_number=54,
        pr_title="Add Payment API endpoint",
        jira_key="PAY-21",
        summary="Added new payment API endpoint and updated authentication logic.",
        doc_url="https://github.com/yourorg/your-repo/blob/main/docs/api/payments.md",
    )
    assert result is True, "Slack webhook did not return 'ok'"


@pytest.mark.skipif(
    not SLACK_WEBHOOK_URL,
    reason="Set SLACK_WEBHOOK_URL in .env to run live Slack tests",
)
def test_send_message_without_jira_key():
    """Notification should work even when there is no Jira key."""
    result = send_doc_update_notification(
        pr_number=99,
        pr_title="Refactor README",
        jira_key="",
        summary="Updated README with setup instructions.",
        doc_url="",
    )
    assert result is True
