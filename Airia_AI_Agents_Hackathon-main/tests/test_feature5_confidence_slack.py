"""
Feature 5 Tests — Classifier Confidence in Slack Notifications

All tests mock the outbound HTTP call so they cost nothing and work offline.
They verify that the classification label and confidence are correctly embedded
in the Slack Block Kit payload for both the completion and approval messages.
"""

import pytest
from unittest.mock import patch, MagicMock
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

@dataclass
class FakeClassification:
    case: int = 4
    case_label: str = "functionality_changed"
    confidence: str = "high"
    reasoning: str = "test"
    targets: list = field(default_factory=list)
    requires_human_approval: bool = False
    slack_alert_level: str = "normal"
    stage: str = "llm"


def _call_pipeline_notification(label: str, confidence: str, **kwargs):
    """Helper: call send_pipeline_complete_notification with only the fields under test."""
    from integrations.slack_client import send_pipeline_complete_notification
    return send_pipeline_complete_notification(
        pr_number=1,
        pr_title="Test PR",
        jira_key="",
        summary="summary",
        impact="impact",
        risk="low risk",
        changelog_url="",
        api_doc_urls=[],
        updated_doc_urls=[],
        new_endpoints=[],
        classification_label=label,
        classification_confidence=confidence,
        **kwargs,
    )


def _call_approval_notification(label: str, confidence: str):
    """Helper: call send_approval_request with classification fields."""
    from integrations.slack_client import send_approval_request
    return send_approval_request(
        pr_number=1,
        pr_title="Test PR",
        summary="summary",
        impact="impact",
        risk="low risk",
        staging_count=2,
        classification_label=label,
        classification_confidence=confidence,
    )


# ---------------------------------------------------------------------------
# Tests — send_pipeline_complete_notification
# ---------------------------------------------------------------------------

class TestPipelineNotificationClassification:

    @patch("integrations.slack_client.send_blocks")
    def test_classification_block_present_when_label_given(self, mock_send_blocks):
        """The Block Kit payload must contain a classification block with label + confidence."""
        mock_send_blocks.return_value = True
        _call_pipeline_notification("functionality_changed", "high")

        assert mock_send_blocks.called
        blocks = mock_send_blocks.call_args[0][0]

        # Find the classification section block
        clf_block = next(
            (b for b in blocks if b.get("type") == "section"
             and "AI Classification" in b.get("text", {}).get("text", "")),
            None,
        )
        assert clf_block is not None, "Classification block missing from Slack payload"

    @patch("integrations.slack_client.send_blocks")
    def test_high_confidence_shows_95_percent(self, mock_send_blocks):
        mock_send_blocks.return_value = True
        _call_pipeline_notification("functionality_changed", "high")
        blocks = mock_send_blocks.call_args[0][0]
        clf_text = next(
            b["text"]["text"] for b in blocks
            if b.get("type") == "section" and "AI Classification" in b.get("text", {}).get("text", "")
        )
        assert "95%" in clf_text

    @patch("integrations.slack_client.send_blocks")
    def test_medium_confidence_shows_70_percent(self, mock_send_blocks):
        mock_send_blocks.return_value = True
        _call_pipeline_notification("small_additive", "medium")
        blocks = mock_send_blocks.call_args[0][0]
        clf_text = next(
            b["text"]["text"] for b in blocks
            if b.get("type") == "section" and "AI Classification" in b.get("text", {}).get("text", "")
        )
        assert "70%" in clf_text

    @patch("integrations.slack_client.send_blocks")
    def test_low_confidence_shows_40_percent(self, mock_send_blocks):
        mock_send_blocks.return_value = True
        _call_pipeline_notification("functionality_changed", "low")
        blocks = mock_send_blocks.call_args[0][0]
        clf_text = next(
            b["text"]["text"] for b in blocks
            if b.get("type") == "section" and "AI Classification" in b.get("text", {}).get("text", "")
        )
        assert "40%" in clf_text

    @patch("integrations.slack_client.send_blocks")
    def test_label_humanised_in_block(self, mock_send_blocks):
        """Underscores in the label should be replaced with spaces and title-cased."""
        mock_send_blocks.return_value = True
        _call_pipeline_notification("functionality_changed", "high")
        blocks = mock_send_blocks.call_args[0][0]
        clf_text = next(
            b["text"]["text"] for b in blocks
            if b.get("type") == "section" and "AI Classification" in b.get("text", {}).get("text", "")
        )
        assert "Functionality Changed" in clf_text
        assert "functionality_changed" not in clf_text  # raw label must NOT appear

    @patch("integrations.slack_client.send_blocks")
    def test_no_classification_block_when_label_empty(self, mock_send_blocks):
        """If no label is passed, the classification block must not appear."""
        mock_send_blocks.return_value = True
        _call_pipeline_notification("", "")
        blocks = mock_send_blocks.call_args[0][0]
        clf_block = next(
            (b for b in blocks if b.get("type") == "section"
             and "AI Classification" in b.get("text", {}).get("text", "")),
            None,
        )
        assert clf_block is None, "Classification block should be absent when label is empty"

    @patch("integrations.slack_client.send_blocks")
    def test_backward_compatible_no_classification_args(self, mock_send_blocks):
        """Calling without optional classification args must not raise."""
        from integrations.slack_client import send_pipeline_complete_notification
        mock_send_blocks.return_value = True
        result = send_pipeline_complete_notification(
            pr_number=1, pr_title="T", jira_key="", summary="s",
            impact="i", risk="r", changelog_url="", api_doc_urls=[],
            updated_doc_urls=[], new_endpoints=[],
        )
        assert result is True


# ---------------------------------------------------------------------------
# Tests — send_approval_request
# ---------------------------------------------------------------------------

class TestApprovalRequestClassification:

    @patch("integrations.slack_client.send_blocks")
    def test_classification_block_present_in_approval(self, mock_send_blocks):
        mock_send_blocks.return_value = True
        _call_approval_notification("new_feature", "medium")
        blocks = mock_send_blocks.call_args[0][0]
        clf_block = next(
            (b for b in blocks if b.get("type") == "section"
             and "AI Classification" in b.get("text", {}).get("text", "")),
            None,
        )
        assert clf_block is not None

    @patch("integrations.slack_client.send_blocks")
    def test_no_classification_block_in_approval_when_empty(self, mock_send_blocks):
        mock_send_blocks.return_value = True
        _call_approval_notification("", "")
        blocks = mock_send_blocks.call_args[0][0]
        clf_block = next(
            (b for b in blocks if b.get("type") == "section"
             and "AI Classification" in b.get("text", {}).get("text", "")),
            None,
        )
        assert clf_block is None

    @patch("integrations.slack_client.send_blocks")
    def test_approval_backward_compatible_no_classification(self, mock_send_blocks):
        """Old callers without classification args must not break."""
        from integrations.slack_client import send_approval_request
        mock_send_blocks.return_value = True
        result = send_approval_request(
            pr_number=1, pr_title="T", summary="s",
            impact="i", risk="r", staging_count=1,
        )
        assert result is True


# ---------------------------------------------------------------------------
# Tests — notification agent (notification.py)
# ---------------------------------------------------------------------------

class TestNotificationAgent:

    @patch("integrations.slack_client.send_blocks")
    def test_notification_run_passes_classification(self, mock_send_blocks):
        """notification.run() must extract and forward classification to Slack."""
        from agents import notification
        from integrations.github_handler import PREvent

        mock_send_blocks.return_value = True
        clf = FakeClassification(case_label="new_feature", confidence="medium")

        pr_event = PREvent(
            pr_number=1, pr_title="Test", pr_body="", head_sha="abc123",
            head_branch="feat", base_branch="main", repo_full_name="org/repo",
            changed_files=[], pr_diff="", jira_issue_key="",
        )
        analysis = {"summary": "s", "impact": "i", "risk": "r"}
        doc_result = {
            "classification": clf,
            "changelog_url": "",
            "api_doc_urls": [],
            "updated_doc_urls": [],
            "new_endpoints": [],
        }

        notification.run(pr_event, analysis, doc_result)

        assert mock_send_blocks.called
        blocks = mock_send_blocks.call_args[0][0]
        clf_block = next(
            (b for b in blocks if b.get("type") == "section"
             and "AI Classification" in b.get("text", {}).get("text", "")),
            None,
        )
        assert clf_block is not None, "notification.run() did not forward classification to Slack"
        assert "New Feature" in clf_block["text"]["text"]
        assert "70%" in clf_block["text"]["text"]  # medium → 70%

    @patch("integrations.slack_client.send_blocks")
    def test_notification_run_handles_missing_classification(self, mock_send_blocks):
        """notification.run() must not crash when classification is absent."""
        from agents import notification
        from integrations.github_handler import PREvent

        mock_send_blocks.return_value = True
        pr_event = PREvent(
            pr_number=2, pr_title="No clf", pr_body="", head_sha="xyz",
            head_branch="feat", base_branch="main", repo_full_name="org/repo",
            changed_files=[], pr_diff="", jira_issue_key="",
        )
        doc_result = {
            "changelog_url": "", "api_doc_urls": [], "updated_doc_urls": [], "new_endpoints": [],
        }
        notification.run(pr_event, {}, doc_result)  # no 'classification' key
        assert mock_send_blocks.called
