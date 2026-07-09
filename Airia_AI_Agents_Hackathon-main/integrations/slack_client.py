"""
Slack Client — Upgraded with Block Kit
Sends structured, rich-formatted messages to Slack via Incoming Webhook.
"""

import os
import httpx
from dotenv import load_dotenv

load_dotenv()


def send_message(text: str) -> bool:
    """
    Send a plain-text message to the configured Slack channel.
    Requires SLACK_WEBHOOK_URL in .env.
    """
    webhook_url = os.getenv("SLACK_WEBHOOK_URL", "")
    if not webhook_url:
        raise ValueError("SLACK_WEBHOOK_URL is not set in .env")

    payload = {"text": text}
    with httpx.Client(timeout=10) as client:
        response = client.post(webhook_url, json=payload)
        response.raise_for_status()
    return response.text == "ok"


def send_blocks(blocks: list, fallback_text: str = "DocuSync notification") -> bool:
    """
    Send a Slack Block Kit message (rich formatting).
    Requires SLACK_WEBHOOK_URL in .env.
    """
    webhook_url = os.getenv("SLACK_WEBHOOK_URL", "")
    if not webhook_url:
        raise ValueError("SLACK_WEBHOOK_URL is not set in .env")

    payload = {"text": fallback_text, "blocks": blocks}
    with httpx.Client(timeout=10) as client:
        response = client.post(webhook_url, json=payload)
        response.raise_for_status()
    return response.text == "ok"


def send_pipeline_complete_notification(
    pr_number: int,
    pr_title: str,
    jira_key: str,
    summary: str,
    impact: str,
    risk: str,
    changelog_url: str,
    api_doc_urls: list[str],
    updated_doc_urls: list[dict],   # list of {"title": ..., "url": ...}
    new_endpoints: list[dict],      # list of {"method": ..., "path": ...}
    classification_label: str = "",      # e.g. "functionality_changed"
    classification_confidence: str = "", # "high" | "medium" | "low"
) -> bool:
    """
    Send a rich Block Kit Slack notification after the full DocuSync pipeline completes.
    Includes: PR summary, risk level, links to Confluence docs, and any new API endpoints.
    """

    # --- Risk emoji ---
    risk_lower = risk.lower() if risk else ""
    if "high" in risk_lower:
        risk_emoji = "🔴"
    elif "medium" in risk_lower or "moderate" in risk_lower:
        risk_emoji = "🟡"
    else:
        risk_emoji = "🟢"

    # --- Build blocks ---
    blocks = [
        # Header
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"📄 DocuSync — Docs Updated for PR #{pr_number}",
                "emoji": True,
            },
        },
        # PR title + Jira key
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"*Pull Request:*\n<https://github.com|PR #{pr_number}: {pr_title}>",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Jira Issue:*\n{jira_key if jira_key else '_None detected_'}",
                },
            ],
        },
        {"type": "divider"},
        # AI Summary
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*🧠 AI Summary*\n{summary or '_No summary available_'}",
            },
        },
        # Impact + Risk
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"*📊 Impact*\n{impact or '_Not assessed_'}",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*{risk_emoji} Risk*\n{risk or '_Not assessed_'}",
                },
            ],
        },
        {"type": "divider"},
    ]

    # --- Classification block (show AI self-awareness) ---
    if classification_label:
        # Map confidence string to a display percentage for readability
        _conf_pct = {"high": "95%", "medium": "70%", "low": "40%"}
        conf_display = _conf_pct.get(classification_confidence.lower(), classification_confidence)
        label_human = classification_label.replace("_", " ").title()
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*🤖 AI Classification*\n"
                    f"Classified as: *{label_human}* "
                    f"(confidence: `{conf_display}`)"
                ),
            },
        })

    # --- Confluence changelog link ---
    if changelog_url:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*📝 Change Log Page*\n<{changelog_url}|View PR #{pr_number} Change Log on Confluence>",
            },
        })

    # --- New API endpoint docs ---
    if new_endpoints and api_doc_urls:
        ep_lines = []
        for ep, url in zip(new_endpoints, api_doc_urls):
            label = f"`{ep['method']} {ep['path']}`"
            ep_lines.append(f"• {label} → <{url}|View API Docs>" if url else f"• {label}")
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*🚀 New API Endpoints Documented*\n" + "\n".join(ep_lines),
            },
        })

    # --- Updated existing docs ---
    if updated_doc_urls:
        doc_lines = [
            f"• <{d['url']}|{d['title']}>" for d in updated_doc_urls if d.get("url")
        ]
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*🔄 Existing Docs Auto-Updated*\n" + "\n".join(doc_lines),
            },
        })

    # --- Footer context ---
    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": "⚡ Powered by *DocuSync AI* | Airia × GitHub × Confluence",
            }
        ],
    })

    fallback = f"DocuSync: Docs updated for PR #{pr_number} — {pr_title}"
    return send_blocks(blocks, fallback_text=fallback)


def send_doc_update_notification(
    pr_number: int,
    pr_title: str,
    jira_key: str,
    summary: str,
    doc_url: str,
) -> bool:
    """Legacy plain-text notification — kept for backward compatibility."""
    jira_line = f"Issue: {jira_key}\n" if jira_key else ""
    doc_line  = f"Link: {doc_url}" if doc_url else ""
    message = (
        f"*Documentation Updated*\n"
        f"PR #{pr_number}: {pr_title}\n"
        f"{jira_line}"
        f"Summary: {summary}\n"
        f"{doc_line}"
    ).strip()
    return send_message(message)

def send_approval_request(
    pr_number: int,
    pr_title: str,
    summary: str,
    impact: str,
    risk: str,
    staging_count: int,
    classification_label: str = "",      # e.g. "functionality_changed"
    classification_confidence: str = "", # "high" | "medium" | "low"
) -> bool:
    """
    Send a Slack Block Kit message requesting human approval for staged docs.
    """
    ngrok_url = os.getenv("NGROK_URL", "http://localhost:8000")
    
    # --- Risk emoji ---
    risk_lower = risk.lower() if risk else ""
    if "high" in risk_lower:
        risk_emoji = "🔴"
    elif "medium" in risk_lower or "moderate" in risk_lower:
        risk_emoji = "🟡"
    else:
        risk_emoji = "🟢"

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"⏳ DocuSync — Approval Required for PR #{pr_number}",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Pull Request:*\n<https://github.com|PR #{pr_number}: {pr_title}>\n\nDocuSync has generated *{staging_count}* documentation updates that are waiting for your approval before being written to Confluence.",
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"*🧠 AI Summary*\n{summary or '_No summary available_'}",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*{risk_emoji} Risk*\n{risk or '_Not assessed_'}",
                },
            ],
        },
        *([
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*🤖 AI Classification*\n"
                        f"Classified as: *{classification_label.replace('_', ' ').title()}* "
                        f"(confidence: `{ {'high': '95%', 'medium': '70%', 'low': '40%'}.get(classification_confidence.lower(), classification_confidence) }`)"
                    ),
                },
            }
        ] if classification_label else []),
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "🔍 Preview Changes",
                        "emoji": True
                    },
                    "url": f"{ngrok_url.rstrip('/')}/preview/{pr_number}"
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "✅ Approve Changes",
                        "emoji": True
                    },
                    "style": "primary",
                    "url": f"{ngrok_url.rstrip('/')}/approve/{pr_number}"
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "❌ Reject Changes",
                        "emoji": True
                    },
                    "style": "danger",
                    "url": f"{ngrok_url.rstrip('/')}/reject/{pr_number}"
                }
            ]
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "⚡ Powered by *DocuSync AI* | Click a button above to open the approval endpoint in your browser",
                }
            ],
        }
    ]

    fallback = f"DocuSync: Approval required for PR #{pr_number} — {pr_title}"
    return send_blocks(blocks, fallback_text=fallback)

