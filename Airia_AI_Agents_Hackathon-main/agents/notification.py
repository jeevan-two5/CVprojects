"""
Notification Agent — Phase 3c

Formats and sends a rich Slack message after the full DocuSync pipeline completes.

Responsibilities:
  1. Receive the full pipeline result (analysis + doc generation output)
  2. Format a Slack Block Kit message (not just plain text)
  3. Send via the Slack Incoming Webhook

The message includes:
  - PR title, number, and Jira key
  - AI-generated summary, impact, and risk
  - Link to the Confluence changelog page
  - Links to any auto-generated API doc pages
  - Links to any existing docs that were updated
"""

from integrations.slack_client import send_pipeline_complete_notification
from integrations.github_handler import PREvent


def run(
    pr_event: PREvent,
    analysis: dict,
    doc_result: dict,
) -> bool:
    """
    Send the final Slack notification when the pipeline completes.

    Args:
        pr_event:   Full PREvent with PR metadata
        analysis:   Dict from code_analysis.run() — keys: summary, impact, risk
        doc_result: Dict from doc_generation.run() — keys:
                      changelog_url, api_doc_urls, new_endpoints, updated_doc_urls

    Returns:
        True if the Slack message was sent successfully.
    """
    classification = doc_result.get("classification")
    # ClassificationResult may be a dataclass instance or a dict
    if hasattr(classification, "case_label"):
        clf_label      = classification.case_label
        clf_confidence = classification.confidence
    elif isinstance(classification, dict):
        clf_label      = classification.get("case_label", "")
        clf_confidence = classification.get("confidence", "")
    else:
        clf_label = clf_confidence = ""

    # Prefer the new Writer Confidence score if available, otherwise fallback to PR Classifier confidence
    writer_cf = doc_result.get("writer_confidence")
    final_confidence = str(writer_cf) + "%" if writer_cf is not None else clf_confidence

    return send_pipeline_complete_notification(
        pr_number                 = pr_event.pr_number,
        pr_title                  = pr_event.pr_title,
        jira_key                  = pr_event.jira_issue_key or "",
        summary                   = analysis.get("summary", ""),
        impact                    = analysis.get("impact", ""),
        risk                      = analysis.get("risk", ""),
        changelog_url             = doc_result.get("changelog_url", ""),
        api_doc_urls              = doc_result.get("api_doc_urls", []),
        updated_doc_urls          = doc_result.get("updated_doc_urls", []),
        new_endpoints             = doc_result.get("new_endpoints", []),
        classification_label      = clf_label,
        classification_confidence = final_confidence,
    )
