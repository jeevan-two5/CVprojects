"""
GitHub Webhook Handler — Phase 2 (complete implementation)
Parses GitHub pull_request webhook payloads into a clean PREvent dataclass,
and fetches the list of changed files via the GitHub REST API.
"""

import os
import re
import httpx
from dataclasses import dataclass, field
from typing import List


@dataclass
class PREvent:
    pr_number: int
    pr_title: str
    pr_body: str
    head_sha: str
    base_branch: str
    head_branch: str
    repo_full_name: str
    changed_files: List[str] = field(default_factory=list)
    pr_diff: str = ""          # The raw patch diff of the PR
    jira_issue_key: str = ""   # e.g. "PAY-21" extracted from branch/title


# ---------------------------------------------------------------------------
# Jira key extraction
# ---------------------------------------------------------------------------

_JIRA_KEY_PATTERN = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")


def extract_jira_key(text: str) -> str:
    """
    Extract the first Jira-style issue key (e.g. PAY-21) from any string.
    Searches the branch name, PR title, and PR body in that order.
    Returns an empty string if nothing found.
    """
    match = _JIRA_KEY_PATTERN.search(text or "")
    return match.group(1) if match else ""


# ---------------------------------------------------------------------------
# Parse raw webhook payload
# ---------------------------------------------------------------------------

def parse_pr_payload(payload: dict) -> PREvent:
    """
    Parse a raw GitHub pull_request webhook payload into a PREvent.
    Does NOT call the GitHub API — changed_files is empty here.
    Call fetch_changed_files() separately to populate it.
    """
    pr = payload.get("pull_request", {})
    repo = payload.get("repository", {})

    head_branch = pr.get("head", {}).get("ref", "")
    pr_title = pr.get("title", "")
    pr_body = pr.get("body") or ""

    # Try to find a Jira key in branch → title → body (in priority order)
    jira_key = (
        extract_jira_key(head_branch)
        or extract_jira_key(pr_title)
        or extract_jira_key(pr_body)
    )

    return PREvent(
        pr_number=pr.get("number", 0),
        pr_title=pr_title,
        pr_body=pr_body,
        head_sha=pr.get("head", {}).get("sha", ""),
        base_branch=pr.get("base", {}).get("ref", "main"),
        head_branch=head_branch,
        repo_full_name=repo.get("full_name", ""),
        changed_files=[],        # populated by fetch_changed_files()
        pr_diff="",              # populated by fetch_pr_diff()
        jira_issue_key=jira_key,
    )


# ---------------------------------------------------------------------------
# Fetch changed files via GitHub REST API
# ---------------------------------------------------------------------------

def fetch_changed_files(repo_full_name: str, pr_number: int) -> List[str]:
    """
    Call GitHub REST API to get the list of files changed in a PR.

    Requires GITHUB_TOKEN environment variable (a Personal Access Token
    with at minimum 'repo' scope for private repos, or no scope for public).

    Returns a list of file paths, e.g. ["src/payments/api.py", "README.md"]
    Raises httpx.HTTPStatusError on non-2xx responses.
    """
    token = os.getenv("GITHUB_TOKEN", "")
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    url = f"https://api.github.com/repos/{repo_full_name}/pulls/{pr_number}/files"

    with httpx.Client(timeout=15) as client:
        response = client.get(url, headers=headers)
        response.raise_for_status()
        files_data = response.json()

    return [f["filename"] for f in files_data]


# ---------------------------------------------------------------------------
# Fetch raw PR diff (patch)
# ---------------------------------------------------------------------------

def fetch_pr_diff(repo_full_name: str, pr_number: int) -> str:
    """
    Call GitHub REST API to get the raw patch diff of the PR.
    This provides the actual code changes for the LLM to analyze.
    """
    token = os.getenv("GITHUB_TOKEN", "")
    headers = {"Accept": "application/vnd.github.v3.diff"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    url = f"https://api.github.com/repos/{repo_full_name}/pulls/{pr_number}"

    with httpx.Client(timeout=15) as client:
        response = client.get(url, headers=headers)
        response.raise_for_status()
        return response.text


# ---------------------------------------------------------------------------
# Convenience: parse payload and immediately fetch extra data
# ---------------------------------------------------------------------------

def parse_and_enrich(payload: dict) -> PREvent:
    """
    Parse the webhook payload AND call the GitHub API to populate changed_files and pr_diff.
    This is the main entry point used by main.py.
    """
    from routers.dashboard import emit_sub_log
    
    event = parse_pr_payload(payload)
    if event.jira_issue_key:
        emit_sub_log(f"Linked PR to Jira issue: {event.jira_issue_key}")
    else:
        emit_sub_log("No Jira issue key detected in PR metadata.")

    if event.repo_full_name and event.pr_number:
        emit_sub_log(f"Fetching metadata for PR #{event.pr_number} from GitHub...")
        event.changed_files = fetch_changed_files(event.repo_full_name, event.pr_number)
        event.pr_diff = fetch_pr_diff(event.repo_full_name, event.pr_number)
        emit_sub_log(f"Enrichment Success: Fetched {len(event.changed_files)} files and raw diff.")
        
    return event

