"""
Jira Client — Phase 2 (complete implementation)
Fetches issue details from Jira REST API v3.
"""

import os
import httpx
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class JiraIssue:
    key: str
    summary: str
    description: str   # plain text extracted from Atlassian Document Format
    status: str
    assignee: str


def _extract_adf_text(adf: dict | None) -> str:
    """
    Recursively extract plain text from an Atlassian Document Format (ADF) node.
    Jira REST API v3 returns descriptions as ADF, not plain text.
    """
    if not adf:
        return ""
    text_parts = []
    node_type = adf.get("type", "")
    if node_type == "text":
        text_parts.append(adf.get("text", ""))
    for child in adf.get("content", []):
        text_parts.append(_extract_adf_text(child))
    return " ".join(part for part in text_parts if part).strip()


def get_issue(issue_key: str) -> JiraIssue:
    """
    Fetch a Jira issue by key (e.g. 'PAY-21').

    Requires in .env:
      JIRA_BASE_URL  — e.g. https://yourorg.atlassian.net
      JIRA_EMAIL     — your Atlassian account email
      JIRA_API_TOKEN — from https://id.atlassian.com/manage-profile/security/api-tokens

    Raises httpx.HTTPStatusError on non-2xx responses.
    """
    base_url   = os.getenv("JIRA_BASE_URL", "").rstrip("/")
    email      = os.getenv("JIRA_EMAIL", "")
    api_token  = os.getenv("JIRA_API_TOKEN", "")

    if not all([base_url, email, api_token]):
        raise ValueError("JIRA_BASE_URL, JIRA_EMAIL, and JIRA_API_TOKEN must be set in .env")

    url = f"{base_url}/rest/api/3/issue/{issue_key}"
    headers = {"Accept": "application/json"}

    with httpx.Client(timeout=15, auth=(email, api_token)) as client:
        response = client.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()

    fields   = data.get("fields", {})
    assignee = fields.get("assignee") or {}

    return JiraIssue(
        key=data.get("key", issue_key),
        summary=fields.get("summary", ""),
        description=_extract_adf_text(fields.get("description")),
        status=fields.get("status", {}).get("name", ""),
        assignee=assignee.get("displayName", "Unassigned"),
    )
