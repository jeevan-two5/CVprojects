# DocuSync AI: Documentation Generation Pipeline

## 1. Pipeline Overview
The DocuSync AI pipeline is automatically triggered when a Pull Request is merged. The orchestration is handled via background tasks to ensure rapid webhook responses to GitHub and zero timeouts.

### Pipeline Stages
1. **GitHub Webhook Reception**:
   - Listens for `pull_request` events where `action=closed` and `merged=true`.
   - Responds quickly to the GitHub event and hands off processing to the `run_docusync_pipeline()` background task.

2. **Stage 1: Parse & Enrich**:
   - **Idempotency Check**: Uses the PR's `merge_commit_sha` to verify if the PR has already been processed, preventing duplicate documentation runs.
   - Fetches PR metadata, the list of changed files, and the raw diff directly via the GitHub API.

3. **Stage 2: Code Analysis (Airia LLM)**:
   - Analyzes the raw code diff.
   - Generates three core metrics: **Summary**, **Impact**, and **Risk**.

4. **Stage 3: Documentation Generation**:
   - Understands the PR through a **Two-Stage PR Classifier**, mapping it to one of 13 specific cases to decide how the wiki should change.
   - Executes precise Doc Generation strategies (creating new Markdown pages, modifying sections, prepending XML headers) targeting Confluence.
   - Auto-detects new API endpoints (`detect_new_endpoints()`) directly from the diff and documents them.

5. **Stage 4: Slack Notification & HITL (Human-In-The-Loop)**:
   - **If HITL is enabled & updates are staged**: The pipeline pauses and sends an actionable Block Kit message to Slack. This message contains links to **Preview**, **Approve**, and **Reject** the Confluence changes.
   - **If Auto-approved (or HITL disabled)**: The pipeline applies Confluence updates instantly and sends a final published summary notification to Slack.

---

## 2. PR Classification & The 13 Cases Architecture
DocuSync utilizes a clever two-stage classification system. This routes PR changes to the correct documentation target and prevents unnecessary LLM execution.

### Stage 1: Deterministic Pre-Classifier
These cases are evaluated first, triggering instantly based on file patterns and regex without hitting the LLM API.
* **Case 3 (Bug Fix)**: Detected via PR title or branch name (e.g., `fix/`, `bug/`). Requires a changelog entry only.
* **Case 9 (Tests Only)**: Triggered when *only* test files are modified (e.g., `test_*.py`). It simply logs the coverage update; no docs written.
* **Case 11 (Doc Only)**: Triggered when *only* markdown/doc files are changed. Prevents infinite doc-generation loops.
* **Case 12 (Massive PR)**: Triggered if the PR contains >50 changed files. Forces a partial sync with mandatory HITL approval due to scale.
* **Case 13 (Security Sensitive)**: Triggered by regex matches on security keywords (e.g., `auth`, `jwt`, `rbac`). Auto-updating is strictly blocked and escalates for human approval.

### Stage 2: Airia LLM Semantic Classifier
If the deterministic stage yields no matches, an LLM evaluates the PR context dynamically against the entire Confluence page catalogue to route the documentation update.

* **Case 1 (New Feature)**:
  * *Trigger*: A brand new feature that no existing document accommodates.
  * *Strategy*: `create_new_page()` uses Airia to write a perfectly formatted Markdown setup guide / manual from scratch.
* **Case 2 (Small Additive)**:
  * *Trigger*: Minor additions (e.g., a new parameter or a tiny feature addition to a class).
  * *Strategy*: `insert_in_context()` targets the best-fit existing section and strictly injects an additive XML snippet.
* **Case 4 (Functionality Changed)**:
  * *Trigger*: Existing logic, algorithm, or UI behavior has significantly mutated.
  * *Strategy*: `replace_section()` parses HTML headings, selectively requests rewritten content for precise sections, and replaces them inline via Storage XML.
* **Case 5 (Breaking Change)**:
  * *Trigger*: Disruption to backward compatibility or removed API surface.
  * *Strategy*: `create_migration_guide()` provisions a dedicated Migration Guide, while prepending obsolete pages with "Breaking Change" XML warning banners alerting readers to migrate.
* **Case 6 (Feature Deprecated)**:
  * *Trigger*: A system is flagged for removal.
  * *Strategy*: `mark_deprecated()` automatically inserts a bold deprecation warning banner to the top of the affected Confluence pages.
* **Case 7 (Rename / Refactor)**:
  * *Trigger*: Code was restructured or names modified with zero behavior change.
  * *Strategy*: `find_and_replace_refs()` dynamically maps old names to new names via LLM and executes a system-wide find-and-replace across identified Confluence pages.
* **Case 8 (Config / Environment)**:
  * *Trigger*: The system detects `os.getenv` or similar config keys in the PR diff.
  * *Strategy*: `update_env_tables()` builds Confluence XML `<tr>` instances and automatically appends them into existing environment variable/configuration tables.
* **Case 10 (Architecture Refactor)**:
  * *Trigger*: Deep system architecture changes (e.g., new databases, replaced dependencies).
  * *Strategy*: Flags changes as excessively risky for auto-writing, triggering `hitl_slack_alert()`.

*(Note: The system occasionally utilizes a 10a strategy: `append_api`. This behaves similarly to Case 2 but specifically appends extracted API definitions via `detect_new_endpoints()` directly into bullet/table lists on API documentation pages).*

---

## 3. Key Pipeline Features

1. **Two-Stage Intelligent Routing**: By prioritizing deterministic regex heuristics over expensive LLM invocations, system latency is reduced and prompt injection costs are minimized.
2. **Confluence Storage XML Surgical Injector**: Rather than blindly overwriting entire Confluence pages—which risks deleting human-authored context—DocuSync precisely extracts and injects XML at specific HTML Headers (`<h1>`, `<h2>`).
3. **Idempotency Safeguard**: Employs `merge_commit_sha` hashing to prevent multiple webhooks from duplicating documents inside the corporate Wiki.
4. **Endpoint Signature Extractor**: Unassisted by the LLM, traditional Regex continually scans diffs for patterns indicative of new Flask/FastAPI routes (e.g., `@app.route(...)`, `@router.get(...)`). It parses out `method`, `path`, and `function` for documentation.
5. **Integrated Staging Store (HITL)**:
    - Wraps all Confluence creation logic in `_safe_create_or_update_page` traps.
    - If `HITL_ENABLED=true`, Confluence writes are serialized into an in-memory staging store.
    - Resolves via `/approve/{pr_id}`, `/reject/{pr_id}`, and `/preview/{pr_id}` FastAPI webhook receivers connected seamlessly into the Slack approval flow.
