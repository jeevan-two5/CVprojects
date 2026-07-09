"""
Code Analysis Agent — Phase 3 (Enhanced)
Calls the Airia Code Analysis pipeline to generate three outputs:
  1. PR Summary  — one-line description of what changed
  2. Impact Analysis — what parts of the system this touches
  3. Risk Analysis  — potential risks or breaking changes

The Airia pipeline's system prompt must instruct it to respond in JSON:
{
  "summary":  "...",
  "impact":   "...",
  "risk":     "..."
}
See the Airia Setup section in the README for exact system prompt wording.
"""

import json
import os
import re
from integrations.github_handler import PREvent
from integrations.airia_client import run_pipeline


# ---------------------------------------------------------------------------
# Prompt Builder
# ---------------------------------------------------------------------------

def build_analysis_prompt(pr_event: PREvent, jira_description: str = "") -> str:
    """
    Construct the full analysis prompt with PR metadata + raw patch diff.
    Instructs the LLM to return structured JSON with 3 sections.
    """
    lines = [
        "Analyze the following pull request and respond ONLY with a valid JSON object in the exact format below.",
        "",
        "Required JSON format:",
        '{',
        '  "summary": "One concise sentence describing WHAT changed.",',
        '  "impact":  "One or two sentences describing WHICH parts of the system are affected and HOW (e.g. API surface, database schema, authentication flow).",',
        '  "risk":    "One or two sentences identifying potential RISKS or breaking changes (e.g. could break existing clients, requires DB migration, affects performance)."',
        '}',
        "",
        "--- Pull Request Metadata ---",
        f"PR Title: {pr_event.pr_title}",
        f"PR Body: {pr_event.pr_body or '(no description provided)'}",
    ]

    if pr_event.changed_files:
        lines.append("Changed Files:")
        for f in pr_event.changed_files:
            lines.append(f"  - {f}")

    if jira_description:
        lines.append(f"\nJira Issue Context ({pr_event.jira_issue_key}):")
        lines.append(jira_description)

    if pr_event.pr_diff:
        # Truncate diff to ~8000 chars to stay within model context limits
        diff = pr_event.pr_diff[:8000]
        if len(pr_event.pr_diff) > 8000:
            diff += "\n\n... (diff truncated for length)"
        lines.append("\n--- Raw Code Diff ---")
        lines.append("```diff")
        lines.append(diff)
        lines.append("```")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Response Parser
# ---------------------------------------------------------------------------

def parse_analysis_result(raw: str) -> dict:
    """
    Extract the JSON object from the Airia response string.
    Returns a dict with keys: summary, impact, risk.
    Falls back gracefully if JSON parsing fails.
    """
    # Try direct JSON parse first
    try:
        data = json.loads(raw.strip())
        return {
            "summary": data.get("summary", "").strip(),
            "impact":  data.get("impact",  "").strip(),
            "risk":    data.get("risk",    "").strip(),
        }
    except json.JSONDecodeError:
        pass

    # Try to extract JSON from markdown code block (e.g. ```json { ... } ```)
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1))
            return {
                "summary": data.get("summary", "").strip(),
                "impact":  data.get("impact",  "").strip(),
                "risk":    data.get("risk",    "").strip(),
            }
        except json.JSONDecodeError:
            pass

    # Fallback: treat the whole response as the summary
    return {
        "summary": raw.strip(),
        "impact":  "",
        "risk":    "",
    }


# ---------------------------------------------------------------------------
# Agent entry point
# ---------------------------------------------------------------------------

def run(pr_event: PREvent, jira_description: str = "") -> dict:
    """
    Analyze a PR using the Airia Code Analysis pipeline.
    """
    from routers.dashboard import emit_sub_log
    
    pipeline_id = os.getenv("AIRIA_CODE_ANALYSIS_PIPELINE_ID", "")
    if not pipeline_id:
        raise ValueError("AIRIA_CODE_ANALYSIS_PIPELINE_ID must be set in .env")

    file_count = len(pr_event.changed_files or [])
    emit_sub_log(f"Analyzing {file_count} changed files for impact and risk...")

    user_input = build_analysis_prompt(pr_event, jira_description)
    result = run_pipeline(pipeline_id, user_input)
    raw_text = result.get("result", "")

    analysis = parse_analysis_result(raw_text)
    
    if analysis.get("summary"):
        emit_sub_log(f"Analysis complete: {analysis['summary'][:100]}...")
        
    return analysis

