"""
PR Classifier — Phase 7 (13-Case Architecture)

Two-stage classification pipeline:
  Stage 1: Deterministic rules — handles Cases 3, 9, 11, 12, 13 instantly (zero LLM cost).
  Stage 2: Airia LLM Classifier — single structured JSON call for Cases 1,2,4,5,6,7,8,10.

The classifier output (ClassificationResult) drives the strategy dispatcher in doc_generation.py.

Case Map:
  1  = new_feature          → create_new_page
  2  = small_additive       → insert_in_context (append_api or add_to_section)
  3  = bug_fix              → changelog_only  [deterministic]
  4  = functionality_changed→ replace_section
  5  = breaking_change      → create_migration_guide + slack_alert(breaking)
  6  = feature_deprecated   → mark_deprecated
  7  = rename_or_refactor   → find_and_replace_refs
  8  = config_or_env        → update_env_tables
  9  = tests_only           → log_coverage   [deterministic]
  10 = architecture_refactor→ hitl_required + slack_alert(hitl)
  11 = doc_only             → no_op          [deterministic]
  12 = massive_pr           → partial_sync_hitl [deterministic]
  13 = security_sensitive   → block_for_security [deterministic]
"""

import os
import re
import json
from dataclasses import dataclass, field
from typing import Optional

from integrations.airia_client import run_pipeline
from integrations.confluence_client import fetch_all_page_titles
from integrations.github_handler import PREvent


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class RoutingTarget:
    """A single Confluence page that needs updating, with full context."""
    page_title:   str
    page_id:      str = ""
    page_url:     str = ""
    page_version: int = 0
    strategy:     str = "update_section"   # append_api | update_section | replace_section | full_rewrite
    section_hint: str = ""                  # exact heading the LLM identified, if any
    reason:       str = ""


@dataclass
class ClassificationResult:
    """Full output of the two-stage classifier."""
    case:                 int              # 1–13
    case_label:           str              # e.g. "functionality_changed"
    confidence:           str = "high"    # high | medium | low
    reasoning:            str = ""
    targets:              list[RoutingTarget] = field(default_factory=list)
    requires_human_approval: bool = False
    slack_alert_level:    str = "normal"  # normal | warning | breaking | hitl
    stage:                str = "llm"     # "deterministic" or "llm"


# ---------------------------------------------------------------------------
# Stage 1 — Deterministic Pre-Classifier
# ---------------------------------------------------------------------------

# File patterns used for deterministic classification
_TEST_FILE_PATTERNS = re.compile(
    r'(^test_|_test\.py$|\.spec\.(ts|js)$|\.test\.(ts|js)$|/tests?/)',
    re.IGNORECASE
)
_DOC_FILE_PATTERNS = re.compile(
    r'\.(md|rst|txt|mdx)$',
    re.IGNORECASE
)
_SECURITY_PATTERNS = re.compile(
    r'(auth|oauth|jwt|token|secret|password|crypt|permission|rbac|acl|cors|ssl|tls)',
    re.IGNORECASE
)
_BUG_FIX_TITLE = re.compile(
    r'^(fix|hotfix|bug|patch|bugfix)\b',
    re.IGNORECASE
)

_MASSIVE_PR_THRESHOLD = 50


def _classify_deterministic(pr_event: PREvent) -> Optional[ClassificationResult]:
    """
    Stage 1: Attempt to classify the PR using deterministic signals only.
    Returns a ClassificationResult if confident, or None to proceed to Stage 2.
    """
    files = pr_event.changed_files or []

    # Case 11: Doc-only PR (all changed files are documentation)
    if files and all(_DOC_FILE_PATTERNS.search(f) for f in files):
        print("[Classifier] Stage 1 → Case 11 (doc_only): all changes are documentation files.")
        return ClassificationResult(
            case=11, case_label="doc_only",
            reasoning="All changed files are documentation — no code was modified.",
            stage="deterministic"
        )

    # Case 9: Tests only changed
    if files and all(_TEST_FILE_PATTERNS.search(f) for f in files):
        print("[Classifier] Stage 1 → Case 9 (tests_only): only test files changed.")
        return ClassificationResult(
            case=9, case_label="tests_only",
            reasoning="Only test files were changed — no documentation updates needed.",
            slack_alert_level="normal",
            stage="deterministic"
        )

    # Case 13: Security-sensitive files changed
    security_files = [f for f in files if _SECURITY_PATTERNS.search(f)]
    if security_files:
        print(f"[Classifier] Stage 1 → Case 13 (security_sensitive): {security_files}")
        return ClassificationResult(
            case=13, case_label="security_sensitive",
            confidence="high",
            reasoning=f"Security-sensitive files changed: {', '.join(security_files)}. Auto-update blocked.",
            requires_human_approval=True,
            slack_alert_level="breaking",
            stage="deterministic"
        )

    # Case 12: Massive PR (too many files to reliably auto-update)
    if len(files) > _MASSIVE_PR_THRESHOLD:
        print(f"[Classifier] Stage 1 → Case 12 (massive_pr): {len(files)} files changed.")
        return ClassificationResult(
            case=12, case_label="massive_pr",
            reasoning=f"PR touches {len(files)} files (>{_MASSIVE_PR_THRESHOLD} threshold). Partial sync with HITL.",
            requires_human_approval=True,
            slack_alert_level="warning",
            stage="deterministic"
        )

    # Case 3: Bug fix with no interface change signals
    if _BUG_FIX_TITLE.match(pr_event.pr_title or ""):
        # Only classify as bug fix if branch name also suggests it
        branch = (pr_event.head_branch or "").lower()
        if any(kw in branch for kw in ["fix", "bug", "hotfix", "patch"]):
            print("[Classifier] Stage 1 → Case 3 (bug_fix): title + branch both indicate bug fix.")
            return ClassificationResult(
                case=3, case_label="bug_fix",
                reasoning="PR title and branch name both indicate a bug fix. Only changelog entry written.",
                stage="deterministic"
            )

    # No deterministic match — escalate to Stage 2
    return None


# ---------------------------------------------------------------------------
# Stage 2 — Airia LLM Semantic Classifier
# ---------------------------------------------------------------------------

_LLM_CLASSIFIER_SYSTEM_PROMPT = """\
You are a Pull Request Documentation Classifier.

Given context about a merged Pull Request and a list of all Confluence pages in the wiki,
you must:
1. Classify the PR into exactly ONE of these cases.
2. Identify which specific Confluence pages need updating and exactly how.

## Case Definitions

| Case | Label | Trigger | Doc Action |
|------|-------|---------|------------|
| 1 | new_feature | Brand new feature, no existing doc covers it | Create a new Confluence page from scratch |
| 2 | small_additive | Minor addition to existing feature (new param, new field, small endpoint) | Insert/append to the best-fit section only |
| 4 | functionality_changed | Existing logic, algorithm, or API behavior is significantly changed | Replace the specific sections that are now inaccurate |
| 5 | breaking_change | Old API removed/renamed, backward-incompatible interface change | Create a Migration Guide page + mark old docs as outdated |
| 6 | feature_deprecated | A feature, endpoint, or module is being removed or soft-deprecated | Prepend a deprecation banner to the relevant page |
| 7 | rename_or_refactor | Internal rename/refactor only, no behavior change (renamed class, moved module) | Find all name references and update them across pages |
| 8 | config_or_env | New environment variable, config key, or feature flag introduced | Update setup/configuration/env-var table pages |
| 10 | architecture_refactor | Significant change to system architecture, new service, new DB schema, new dependency | Flag for human review — too risky to auto-write |

## Output Format
Output ONLY a valid JSON object. No prose, no markdown fences.

{
  "case": <integer 1-10>,
  "case_label": "<label>",
  "confidence": "high" | "medium" | "low",
  "reasoning": "<one clear sentence>",
  "targets": [
    {
      "page_title": "<exact title from page list>",
      "strategy": "append_api" | "insert_in_context" | "replace_section" | "create_new" | "mark_deprecated" | "find_replace" | "update_env_table" | "full_rewrite",
      "section_hint": "<exact heading text to target, or empty string if not applicable>",
      "reason": "<one sentence why this page>"
    }
  ],
  "requires_human_approval": true | false,
  "slack_alert_level": "normal" | "warning" | "breaking" | "hitl",
  "new_page_title": "<only for case 1 — the title of the new page to create, else empty>"
}

## Hard Rules
- Use EXACT page titles from the provided list as `page_title` values.
- For case 1, targets array may be empty; populate new_page_title instead.
- For case 5, include both a "create_new" target for the Migration Guide AND any existing pages to mark as outdated.
- For case 10, set requires_human_approval: true and targets: [].
- NEVER include changelog pages (titles containing "PR #") as targets.
"""


def _build_llm_classifier_prompt(
    pr_event: PREvent,
    analysis: dict,
    page_list: list[dict],
) -> str:
    """Build the user-turn prompt for the LLM classifier."""
    titles_only = [p["title"] for p in page_list]
    return (
        f"## All Confluence Pages\n"
        f"{json.dumps(titles_only, indent=2)}\n\n"
        f"## PR Context\n"
        f"Title        : {pr_event.pr_title}\n"
        f"Branch       : {pr_event.head_branch} → {pr_event.base_branch}\n"
        f"Changed Files: {', '.join(pr_event.changed_files or [])}\n"
        f"Jira Issue   : {pr_event.jira_issue_key or 'N/A'}\n\n"
        f"## AI Analysis\n"
        f"Summary:\n{analysis.get('summary', '')}\n\n"
        f"Impact:\n{analysis.get('impact', '')}\n\n"
        f"Risk:\n{analysis.get('risk', '')}\n\n"
        f"Classify this PR and identify documentation targets."
    )


def _classify_with_llm(
    pr_event: PREvent,
    analysis: dict,
    page_list: list[dict],
) -> Optional[ClassificationResult]:
    """
    Stage 2: Call Airia LLM Classifier. Returns ClassificationResult or None on failure.
    """
    pipeline_id = (
        os.getenv("AIRIA_PR_CLASSIFIER_PIPELINE_ID")
        or os.getenv("AIRIA_PAGE_ROUTER_PIPELINE_ID")
        or os.getenv("AIRIA_CODE_ANALYSIS_PIPELINE_ID", "")
    )
    if not pipeline_id:
        print("[Classifier] Stage 2: No pipeline ID configured. Skipping LLM classification.")
        return None

    prompt = _build_llm_classifier_prompt(pr_event, analysis, page_list)

    try:
        result     = run_pipeline(pipeline_id, prompt, variables={"system_prompt": _LLM_CLASSIFIER_SYSTEM_PROMPT})
        raw_output = result.get("result", "").strip()
    except Exception as e:
        print(f"[Classifier] Stage 2: Airia call failed: {e}")
        return None

    # Strip ```json fences if present
    json_match = re.search(r'\{.*\}', raw_output, re.DOTALL)
    if not json_match:
        print(f"[Classifier] Stage 2: Could not parse JSON. Response: {raw_output[:300]}")
        return None

    try:
        data = json.loads(json_match.group())
    except json.JSONDecodeError as e:
        print(f"[Classifier] Stage 2: JSON decode error: {e}")
        return None

    # Build RoutingTarget list, resolving page_id/url from the catalogue
    catalogue_index = {p["title"].lower(): p for p in page_list}
    targets = []
    for t in data.get("targets", []):
        title = t.get("page_title", "").strip()
        cat   = catalogue_index.get(title.lower(), {})
        targets.append(RoutingTarget(
            page_title   = title,
            page_id      = cat.get("page_id", ""),
            page_url     = cat.get("url", ""),
            page_version = cat.get("version", 0),
            strategy     = t.get("strategy", "update_section"),
            section_hint = t.get("section_hint", ""),
            reason       = t.get("reason", ""),
        ))

    cr = ClassificationResult(
        case                  = int(data.get("case", 4)),
        case_label            = data.get("case_label", "unknown"),
        confidence            = data.get("confidence", "medium"),
        reasoning             = data.get("reasoning", ""),
        targets               = targets,
        requires_human_approval = data.get("requires_human_approval", False),
        slack_alert_level     = data.get("slack_alert_level", "normal"),
        stage                 = "llm",
    )
    # Stash new_page_title for Case 1 handler
    cr.__dict__["new_page_title"] = data.get("new_page_title", "")
    return cr


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def classify_pr(pr_event: PREvent, analysis: dict) -> ClassificationResult:
    """
    Main entry point. Runs Stage 1 (deterministic) then Stage 2 (LLM) if needed.
    """
    from routers.dashboard import emit_sub_log

    # Stage 1
    result = _classify_deterministic(pr_event)
    if result:
        emit_sub_log(f"Stage 1 (Deterministic): Classified as '{result.case_label}' based on file patterns.")
        return result

    # Stage 2: fetch page catalogue once, then call LLM
    space_key = os.getenv("CONFLUENCE_SPACE_KEY", "")
    emit_sub_log("Stage 1 inconclusive. Fetching wiki page list for Stage 2 LLM analysis...")
    page_list = fetch_all_page_titles(space_key)

    emit_sub_log(f"Stage 2 (LLM): Analyzing semantics with Airia...")
    result = _classify_with_llm(pr_event, analysis, page_list)

    if result:
        emit_sub_log(f"Stage 2 Result: '{result.case_label}' (Confidence: {result.confidence})")
        if result.targets:
            emit_sub_log(f"Identified {len(result.targets)} target pages for synchronization.")
        return result

    # Fallback
    emit_sub_log("Stage 2 failed. Falling back to default 'functionality_changed' strategy.")
    return ClassificationResult(
        case=4, case_label="functionality_changed",
        confidence="low",
        reasoning="Classification failed — defaulting to functionality_changed.",
        stage="llm"
    )

