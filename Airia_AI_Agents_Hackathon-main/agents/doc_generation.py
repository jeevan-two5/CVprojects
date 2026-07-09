"""
Documentation Generation Agent — Phase 7 (13-Case Architecture)

Responsibilities:
  1. Write a PR change-log entry to Confluence (all cases)
  2. Auto-generate dedicated API reference pages for newly detected endpoints
  3. Route to the correct doc-update strategy based on ClassificationResult:

     Case  1 → create_new_page()           (brand-new doc with full Airia-generated content)
     Case  2 → insert_in_context()          (append to best-fit existing section)
     Case  3 → changelog_only()             [handled implicitly — no step 3]
     Case  4 → replace_section()            (Storage XML heading-level rewrite)
     Case  5 → create_migration_guide()     (new "Migration Guide" page + mark old pages)
     Case  6 → mark_deprecated()            (prepend deprecation banner via Storage XML)
     Case  7 → find_and_replace_refs()      (rename all references across target pages)
     Case  8 → update_env_tables()          (append new rows to env-var / config tables)
     Case  9 → no_op (log only)            [deterministic exit in classifier]
     Case 10 → hitl_slack_alert()           (block; send Slack alert with approval request)
     Case 11 → no_op                        [deterministic exit]
     Case 12 → partial_sync_hitl()          (changelog only; Slack alert; await human)
     Case 13 → security_block()             (block all auto-writes; urgent Slack alert)
"""

import os
import re
import json
import markdown2 as _md2
from typing import List

from routers.dashboard import emit_sub_log
from integrations.confluence_client import (
    create_or_update_page,
    fetch_page_content,
    fetch_page_as_storage_xml,
    update_page,
    ConfluencePage,
    get_page_by_title,
)
from integrations.airia_client import run_pipeline, run_pipeline_with_files
from integrations.github_handler import PREvent
from agents.pr_classifier import ClassificationResult, RoutingTarget
from agents.staging_store import stage_pending_doc_update

# ---------------------------------------------------------------------------
# HITL Interceptors
# ---------------------------------------------------------------------------

def _is_hitl_enabled() -> bool:
    return os.getenv("HITL_ENABLED", "false").lower() == "true"

def _safe_create_or_update_page(pr_number: int, **kwargs) -> dict:
    if _is_hitl_enabled():
        print(f"[DocGen] HITL ENABLED: Staging create_or_update_page for '{kwargs.get('title')}'")
        stage_pending_doc_update(pr_number, "create_or_update_page", kwargs)
        return {"url": f"pending-approval-{pr_number}"}
    return create_or_update_page(**kwargs)

def _safe_update_page(pr_number: int, **kwargs):
    if _is_hitl_enabled():
        print(f"[DocGen] HITL ENABLED: Staging update_page for '{kwargs.get('title')}'")
        stage_pending_doc_update(pr_number, "update_page", kwargs)
        # Return a dummy ConfluencePage object
        from dataclasses import dataclass
        @dataclass
        class DummyPage:
            url: str = f"pending-approval-{pr_number}"
        return DummyPage()
    return update_page(**kwargs)



# ---------------------------------------------------------------------------
# Endpoint detection (unchanged)
# ---------------------------------------------------------------------------

_ENDPOINT_PATTERNS = [
    re.compile(
        r'^\+\s*@(?:\w+)\.(?P<method>get|post|put|patch|delete|head|options)\s*\(\s*["\'](?P<path>[^"\']+)["\']',
        re.IGNORECASE | re.MULTILINE
    ),
    re.compile(
        r'^\+\s*@(?:\w+)\.route\s*\(\s*["\'](?P<path>[^"\']+)["\'].*?methods\s*=\s*\[.*?["\'](?P<method>GET|POST|PUT|PATCH|DELETE)["\']',
        re.IGNORECASE | re.DOTALL | re.MULTILINE
    ),
]
_FUNC_NAME_PATTERN = re.compile(r'^\+?\s*async def\s+(\w+)|^\+?\s*def\s+(\w+)', re.MULTILINE)


def detect_new_endpoints(diff: str) -> List[dict]:
    found, seen = [], set()
    for pattern in _ENDPOINT_PATTERNS:
        for match in pattern.finditer(diff):
            method = match.group("method").upper()
            path   = match.group("path")
            key    = f"{method}:{path}"
            if key in seen:
                continue
            seen.add(key)
            snippet     = diff[match.end():match.end() + 300]
            func_match  = _FUNC_NAME_PATTERN.search(snippet)
            func_name   = (func_match.group(1) or func_match.group(2)) if func_match else "unknown"
            found.append({"method": method, "path": path, "func": func_name})
    
    if found:
        from routers.dashboard import emit_sub_log
        emit_sub_log(f"Endpoint Detection: Found {len(found)} new API routes in diff.")
    return found


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _pipeline_id() -> str:
    return os.getenv("AIRIA_DOC_GEN_PIPELINE_ID")


def _markdown_to_storage(md: str) -> str:
    """Full-fidelity Markdown → Confluence Storage HTML via markdown2."""
    html = _md2.markdown(md, extras=["fenced-code-blocks", "tables", "strike", "break-on-newline"])
    # Convert <pre><code class="language-X"> → ac:structured-macro
    def _repl(m):
        lang  = re.search(r'class="language-(\w+)"', m.group(1))
        code  = re.sub(r'<[^>]+>', '', m.group(2))
        lang_val = lang.group(1) if lang else "none"
        return (
            f'<ac:structured-macro ac:name="code">'
            f'<ac:parameter ac:name="language">{lang_val}</ac:parameter>'
            f'<ac:plain-text-body><![CDATA[{code}]]></ac:plain-text-body>'
            f'</ac:structured-macro>'
        )
    return re.sub(r'<pre><code([^>]*)>(.*?)</code></pre>', _repl, html, flags=re.DOTALL)


def _info_panel(message: str) -> str:
    """Return a Confluence Storage Format info panel macro."""
    return (
        f'<ac:structured-macro ac:name="info">'
        f'<ac:rich-text-body><p>{message}</p></ac:rich-text-body>'
        f'</ac:structured-macro>'
    )


def _warning_panel(message: str) -> str:
    """Return a Confluence Storage Format warning panel macro."""
    return (
        f'<ac:structured-macro ac:name="warning">'
        f'<ac:rich-text-body><p>{message}</p></ac:rich-text-body>'
        f'</ac:structured-macro>'
    )


# ---------------------------------------------------------------------------
# Case 1 — create_new_page
# ---------------------------------------------------------------------------

def create_new_page(
    target: RoutingTarget,
    pr_event: PREvent,
    analysis: dict,
    space_key: str,
) -> str:
    """Generate a brand-new documentation page using Airia."""
    new_page_title = getattr(target, 'page_title', '') or f"Docs: {pr_event.pr_title}"

    doc_file  = ("changes.diff", (pr_event.pr_diff or "")[:50000].encode(), "text/plain")
    prompt    = (
        f"You are a technical writer creating NEW documentation for a software feature.\n\n"
        f"A new feature was merged via PR: '{pr_event.pr_title}'\n"
        f"AI Summary: {analysis.get('summary', '')}\n"
        f"AI Impact : {analysis.get('impact', '')}\n\n"
        f"The diff file is attached. Write a complete, well-structured Markdown documentation page "
        f"titled '{new_page_title}'. Include: Overview, Key Concepts, API/Usage, Examples, Notes."
    )
    try:
        result  = run_pipeline_with_files(_pipeline_id(), prompt, [doc_file])
        content = result.get("result", "").strip()
    except Exception as e:
        print(f"[DocGen] Case 1: Airia call failed: {e}")
        return ""

    if not content:
        return ""

    resp = _safe_create_or_update_page(
        pr_event.pr_number,
        title=new_page_title, body_markdown=content,
        space_key=space_key, parent_title="Documentation"
    )
    emit_sub_log(f"Created new Confluence page: '{new_page_title}'")
    return resp.get("url", "")


# ---------------------------------------------------------------------------
# Case 2 — insert_in_context (append to best-fit section)
# ---------------------------------------------------------------------------

def insert_in_context(
    target: RoutingTarget,
    pr_event: PREvent,
    analysis: dict,
) -> str:
    """Append a small additive change to the most relevant section."""
    storage_xml, version = fetch_page_as_storage_xml(target.page_id)
    if not storage_xml:
        return ""

    prompt = (
        f"You are a technical writer making a small additive update to a Confluence page.\n\n"
        f"Page: '{target.page_title}'\n"
        f"Target section hint: '{target.section_hint}'\n"
        f"PR Summary: {analysis.get('summary', '')}\n"
        f"PR Impact : {analysis.get('impact', '')}\n\n"
        f"The current page XML (first 6000 chars):\n{storage_xml[:6000]}\n\n"
        f"Output ONLY the Confluence Storage Format XML snippet to INSERT into the "
        f"'{target.section_hint or 'most relevant section'}'. "
        f"Do not output the full page. Output only the new content snippet."
    )
    try:
        result  = run_pipeline(_pipeline_id(), prompt)
        
        content, conf, reason = _parse_writer_output(result.get("output", ""))
        if conf > 0:
            emit_sub_log(f"Topic Synthesis Confidence: {conf}% - {reason}")
            
        snippet = content.strip()
    except Exception as e:
        print(f"[DocGen] Case 2: Airia call failed: {e}")
        return ""

    if not snippet:
        return ""

    # Inject after the target section heading
    if target.section_hint:
        heading_escaped = re.escape(target.section_hint)
        pattern = re.compile(rf'(<h[1-6][^>]*>\s*{heading_escaped}\s*</h[1-6]>)', re.IGNORECASE)
        updated_xml = pattern.sub(rf'\1\n{snippet}', storage_xml, count=1)
        if updated_xml == storage_xml:
            # heading not found — append at bottom
            updated_xml = storage_xml + f"\n{snippet}"
    else:
        updated_xml = storage_xml + f"\n{snippet}"

    page = _safe_update_page(pr_event.pr_number, page_id=target.page_id, title=target.page_title, body_markdown="", current_version=version, raw_storage_xml=updated_xml)
    emit_sub_log(f"Appended additive snippet to section: '{target.section_hint or 'bottom of page'}' in '{target.page_title}'")
    return page.url


# ---------------------------------------------------------------------------
# Case 4 — replace_section (Storage XML heading-level rewrite)
# ---------------------------------------------------------------------------

def replace_section(
    target: RoutingTarget,
    pr_event: PREvent,
    analysis: dict,
) -> str:
    """Replace the content of specific sections identified by the classifier."""
    storage_xml, version = fetch_page_as_storage_xml(target.page_id)
    if not storage_xml:
        return ""

    # Extract all headings to give the LLM accurate names
    heading_texts = re.findall(r'<h[1-6][^>]*>\s*(.*?)\s*</h[1-6]>', storage_xml,
                               flags=re.IGNORECASE | re.DOTALL)
    heading_texts = [re.sub(r'<[^>]+>', '', h).strip() for h in heading_texts]

    hint_context = f"Focus especially on the section: '{target.section_hint}'." if target.section_hint else ""

    prompt = (
        f"You are a technical writer updating Confluence documentation.\n\n"
        f"Page: '{target.page_title}'\n"
        f"Reason: {target.reason}\n"
        f"PR Summary: {analysis.get('summary', '')}\n"
        f"PR Impact : {analysis.get('impact', '')}\n"
        f"{hint_context}\n\n"
        f"Available headings in the page:\n{json.dumps(heading_texts, indent=2)}\n\n"
        f"Output a JSON object mapping each heading that needs updating to its new Markdown content.\n"
        f"Use exact heading text as keys. For new sections: key = 'NEW: <Heading Text>'.\n"
        f"If nothing needs changing, output: {{}}\n"
        f"Output ONLY the JSON object."
    )
    try:
        result     = run_pipeline(_pipeline_id(), prompt)
        
        content, conf, reason = _parse_writer_output(result.get("output", ""))
        if conf > 0:
            emit_sub_log(f"Section Update Confidence: {conf}% - {reason}")
            # If generating a result dict, we should attach it to the parent scope later
            
        raw        = content.strip()
    except Exception as e:
        print(f"[DocGen] Case 4: Airia call failed: {e}")
        return ""

    json_match = re.search(r'\{.*\}', raw, re.DOTALL)
    if not json_match:
        return ""
    try:
        updates: dict = json.loads(json_match.group())
    except json.JSONDecodeError:
        return ""

    if not updates:
        return ""

    updated_xml   = storage_xml
    changes_made  = False

    for heading_key, new_markdown in updates.items():
        new_html = _markdown_to_storage(new_markdown)

        if heading_key.startswith("NEW:"):
            new_h = heading_key[4:].strip()
            updated_xml += f"\n<h2>{new_h}</h2>\n{new_html}\n"
            print(f"[DocGen]   [+] New section: '{new_h}'")
            emit_sub_log(f"Created new section '{new_h}' in '{target.page_title}'")
            changes_made = True
        else:
            clean_h = re.sub(r'<[^>]+>', '', heading_key).strip().lstrip('#').strip()
            level_m = re.match(r'^(#+)\s*', heading_key)
            level   = len(level_m.group(1)) if level_m else 2

            h_rx    = re.compile(
                rf'(<h{level}[^>]*>\s*{re.escape(clean_h)}\s*</h{level}>)',
                re.IGNORECASE | re.DOTALL
            )
            h_match = h_rx.search(updated_xml)
            if not h_match:
                print(f"[DocGen]   [!] Heading not found: '{clean_h}'")
                continue

            next_h_rx = re.compile(rf'<h[1-{level}][^>]*>', re.IGNORECASE)
            next_m    = next_h_rx.search(updated_xml, h_match.end())
            end_pos   = next_m.start() if next_m else len(updated_xml)

            updated_xml  = (updated_xml[:h_match.start()]
                            + h_match.group(0) + "\n" + new_html + "\n"
                            + updated_xml[end_pos:])
            print(f"[DocGen]   [+] Replaced section: '{clean_h}'")
            emit_sub_log(f"Replaced content in section '{clean_h}' in '{target.page_title}'")
            changes_made = True

    if not changes_made:
        return ""

    page = _safe_update_page(pr_event.pr_number, page_id=target.page_id, title=target.page_title, body_markdown="", current_version=version, raw_storage_xml=updated_xml)
    return page.url


# ---------------------------------------------------------------------------
# Case 5 — create_migration_guide
# ---------------------------------------------------------------------------

def create_migration_guide(
    targets: List[RoutingTarget],
    pr_event: PREvent,
    analysis: dict,
    space_key: str,
) -> List[str]:
    """
    Create a Migration Guide page for breaking changes.
    Also prepend a 'this page is outdated' warning to existing affected pages.
    """
    updated_urls = []
    doc_file = ("changes.diff", (pr_event.pr_diff or "")[:50000].encode(), "text/plain")

    prompt = (
        f"You are a technical writer. A breaking change was merged.\n\n"
        f"PR: '{pr_event.pr_title}'\n"
        f"Summary : {analysis.get('summary', '')}\n"
        f"Impact  : {analysis.get('impact', '')}\n\n"
        f"The diff is attached. Write a complete Migration Guide in Markdown with sections:\n"
        f"## What Changed\n## Breaking Changes\n## Migration Steps\n## Before/After Examples"
    )
    try:
        result  = run_pipeline_with_files(_pipeline_id(), prompt, [doc_file])
        content = result.get("result", "").strip()
    except Exception as e:
        print(f"[DocGen] Case 5: Migration guide generation failed: {e}")
        content = ""

    if content:
        title = f"Migration Guide: {pr_event.pr_title}"
        resp  = _safe_create_or_update_page(
            pr_event.pr_number,
            title=title, body_markdown=content,
            space_key=space_key, parent_title="Migration Guides"
        )
        url = resp.get("url", "")
        if url:
            print(f"[DocGen] Case 5: Migration guide created → {url}")
            updated_urls.append(url)

    # Prepend warning banner to existing affected pages
    for target in targets:
        if target.strategy == "create_new" or not target.page_id:
            continue
        storage_xml, version = fetch_page_as_storage_xml(target.page_id)
        if not storage_xml:
            continue
        warning = _warning_panel(
            f"⚠️ <strong>Breaking Change:</strong> This page may be outdated. "
            f"See the <a href='#'>Migration Guide: {pr_event.pr_title}</a> for details."
        )
        updated_xml = warning + "\n" + storage_xml
        page = _safe_update_page(pr_event.pr_number, page_id=target.page_id, title=target.page_title, body_markdown="", current_version=version, raw_storage_xml=updated_xml)
        updated_urls.append(page.url)
        print(f"[DocGen] Case 5: Warning banner added to '{target.page_title}'")
        emit_sub_log(f"Prepended Outdated Warning banner to '{target.page_title}'")

    return updated_urls


# ---------------------------------------------------------------------------
# Case 6 — mark_deprecated
# ---------------------------------------------------------------------------

def mark_deprecated(
    target: RoutingTarget,
    pr_event: PREvent,
    analysis: dict,
) -> str:
    """Prepend a deprecation notice banner to the target page."""
    storage_xml, version = fetch_page_as_storage_xml(target.page_id)
    if not storage_xml:
        return ""

    banner = _warning_panel(
        f"🚫 <strong>DEPRECATED:</strong> This feature has been deprecated as of "
        f"<a href='#'>PR: {pr_event.pr_title}</a>. "
        f"It will be removed in a future release. {analysis.get('impact', '')}"
    )
    updated_xml = banner + "\n" + storage_xml
    page = _safe_update_page(pr_event.pr_number, page_id=target.page_id, title=target.page_title, body_markdown="", current_version=version, raw_storage_xml=updated_xml)
    print(f"[DocGen] Case 6: Deprecation banner added to '{target.page_title}'")
    emit_sub_log(f"Prepended Deprecation banner to '{target.page_title}'")
    return page.url


# ---------------------------------------------------------------------------
# Case 7 — find_and_replace_refs
# ---------------------------------------------------------------------------

def find_and_replace_refs(
    target: RoutingTarget,
    pr_event: PREvent,
    analysis: dict,
) -> str:
    """
    For renames/refactors: ask Airia to identify old → new name mappings,
    then perform find-and-replace in the page's Storage XML.
    """
    storage_xml, version = fetch_page_as_storage_xml(target.page_id)
    current_content = fetch_page_content(target.page_id)
    if not storage_xml:
        return ""

    prompt = (
        f"A refactor/rename PR was merged: '{pr_event.pr_title}'\n"
        f"Summary: {analysis.get('summary', '')}\n\n"
        f"Analyze the changes and output a JSON object of name replacements needed in "
        f"the documentation page '{target.page_title}':\n"
        f"{{\"old_name\": \"new_name\", ...}}\n\n"
        f"Current page content (excerpt):\n{current_content[:4000]}\n\n"
        f"Output ONLY the JSON object. If no renames apply to this page, output: {{}}"
    )
    try:
        result = run_pipeline(_pipeline_id(), prompt)
        raw    = result.get("result", "").strip()
    except Exception as e:
        print(f"[DocGen] Case 7: Airia call failed: {e}")
        return ""

    json_match = re.search(r'\{.*\}', raw, re.DOTALL)
    if not json_match:
        return ""
    try:
        renames: dict = json.loads(json_match.group())
    except json.JSONDecodeError:
        return ""

    if not renames:
        return ""

    updated_xml = storage_xml
    for old, new in renames.items():
        updated_xml = updated_xml.replace(old, new)
        print(f"[DocGen] Case 7: '{old}' → '{new}' in '{target.page_title}'")

    page = _safe_update_page(pr_event.pr_number, page_id=target.page_id, title=target.page_title, body_markdown="", current_version=version, raw_storage_xml=updated_xml)
    emit_sub_log(f"Updated renames/refactors on page: '{target.page_title}'")
    return page.url


# ---------------------------------------------------------------------------
# Case 8 — update_env_tables
# ---------------------------------------------------------------------------

def update_env_tables(
    target: RoutingTarget,
    pr_event: PREvent,
    analysis: dict,
) -> str:
    """
    Append new environment variables / config keys introduced in the PR
    into the existing env-var table on the target page.
    """
    # Detect new env vars from the diff
    diff = pr_event.pr_diff or ""
    env_pattern = re.compile(
        r'^\+.*?(?:os\.getenv|os\.environ\[|getenv)\s*\(["\']([A-Z_][A-Z0-9_]+)["\']',
        re.MULTILINE
    )
    new_env_vars = list(set(env_pattern.findall(diff)))

    if not new_env_vars:
        print(f"[DocGen] Case 8: No new env vars detected for '{target.page_title}'. Skipping.")
        return ""

    storage_xml, version = fetch_page_as_storage_xml(target.page_id)
    if not storage_xml:
        return ""

    env_summary = ", ".join(f"`{v}`" for v in new_env_vars)
    prompt = (
        f"New environment variables were added in PR '{pr_event.pr_title}': {env_summary}\n"
        f"PR Summary: {analysis.get('summary', '')}\n\n"
        f"The documentation page '{target.page_title}' (Confluence Storage XML, first 5000 chars):\n"
        f"{storage_xml[:5000]}\n\n"
        f"Output ONLY the Confluence Storage Format XML <tr> rows to add to the env-var table. "
        f"Each row should have columns: Variable Name | Description | Required | Default Value.\n"
        f"Output exactly the XML rows, nothing else."
    )
    try:
        result = run_pipeline(_pipeline_id(), prompt)
        content, conf, reason = _parse_writer_output(result.get("output", ""))
        
        if conf > 0:
            emit_sub_log(f"Env Table Update Confidence: {conf}% - {reason}")
            
        new_rows = content.strip()
    except Exception as e:
        print(f"[DocGen] Case 8: Airia call failed: {e}")
        return ""

    if not new_rows:
        return ""

    if "</tbody>" in storage_xml:
        updated_xml = storage_xml.replace("</tbody>", f"{new_rows}\n</tbody>", 1)
    elif "</table>" in storage_xml:
        updated_xml = storage_xml.replace("</table>", f"<tr>{new_rows}</tr>\n</table>", 1)
    else:
        # No table found — append as a code block
        updated_xml = storage_xml + f"\n<h3>New Environment Variables</h3>\n<p>{env_summary}</p>"

    page = _safe_update_page(pr_event.pr_number, page_id=target.page_id, title=target.page_title, body_markdown="", current_version=version, raw_storage_xml=updated_xml)
    print(f"[DocGen] Case 8: Env table updated in '{target.page_title}'")
    return page.url


# ---------------------------------------------------------------------------
# Case 10a — append_api (new endpoint to API listing)
# ---------------------------------------------------------------------------

def append_api(
    target: RoutingTarget,
    pr_event: PREvent,
    analysis: dict,
) -> str:
    """Append newly detected API endpoints to an existing API listing page."""
    new_endpoints = detect_new_endpoints(pr_event.pr_diff or "")
    if not new_endpoints:
        return ""

    storage_xml, version = fetch_page_as_storage_xml(target.page_id)
    if not storage_xml:
        return ""

    endpoints_summary = "\n".join(
        f"  - {ep['method']} {ep['path']}  (function: {ep['func']})"
        for ep in new_endpoints
    )
    prompt = (
        f"New API endpoints added in PR '{pr_event.pr_title}':\n{endpoints_summary}\n\n"
        f"Summary: {analysis.get('summary', '')}\n\n"
        f"The page '{target.page_title}' XML (first 6000 chars):\n{storage_xml[:6000]}\n\n"
        f"Output ONLY the Confluence Storage XML snippet to append these endpoints.\n"
        f"- If page has <table>: output new <tr> rows.\n"
        f"- If page has <ul>: output new <li> items.\n"
        f"- Otherwise: output a new <h3> + <p> block.\n"
        f"Output only the XML snippet, nothing else."
    )
    try:
        result      = run_pipeline(_pipeline_id(), prompt)
        content, conf, reason = _parse_writer_output(result.get("output", ""))
        
        if conf > 0:
            emit_sub_log(f"API Append Confidence: {conf}% - {reason}")
            
        new_snippet = content.strip()
    except Exception as e:
        print(f"[DocGen] append_api: Airia call failed: {e}")
        return ""

    if not new_snippet:
        return ""

    if "</tbody>" in storage_xml:
        updated_xml = storage_xml.replace("</tbody>", f"{new_snippet}\n</tbody>", 1)
    elif "</ul>" in storage_xml:
        updated_xml = storage_xml.replace("</ul>", f"{new_snippet}\n</ul>", 1)
    else:
        updated_xml = storage_xml + f"\n{new_snippet}"

    page = _safe_update_page(pr_event.pr_number, page_id=target.page_id, title=target.page_title, body_markdown="", current_version=version, raw_storage_xml=updated_xml)
    return page.url


# ---------------------------------------------------------------------------
# Strategy dispatcher
# ---------------------------------------------------------------------------

def _dispatch_target(
    target: RoutingTarget,
    pr_event: PREvent,
    analysis: dict,
    space_key: str,
    result: ClassificationResult,
) -> str:
    """Route a single RoutingTarget to its handler based on strategy."""
    strategy = target.strategy
    print(f"[DocGen] Dispatching '{target.page_title}' via [{strategy}]")

    if strategy == "append_api":
        return append_api(target, pr_event, analysis)
    elif strategy == "insert_in_context":
        return insert_in_context(target, pr_event, analysis)
    elif strategy == "replace_section":
        return replace_section(target, pr_event, analysis)
    elif strategy == "mark_deprecated":
        return mark_deprecated(target, pr_event, analysis)
    elif strategy == "find_replace":
        return find_and_replace_refs(target, pr_event, analysis)
    elif strategy == "update_env_table":
        return update_env_tables(target, pr_event, analysis)
    elif strategy == "create_new":
        return create_new_page(target, pr_event, analysis, space_key)
    elif strategy == "full_rewrite":
        return _full_rewrite(target, pr_event, analysis)
    else:
        # Default: replace_section
        return replace_section(target, pr_event, analysis)


def _full_rewrite(target: RoutingTarget, pr_event: PREvent, analysis: dict) -> str:
    """Full page rewrite — upload doc + diff as files to Airia."""
    current_content          = fetch_page_content(target.page_id)
    storage_xml, version     = fetch_page_as_storage_xml(target.page_id)
    if not current_content:
        return ""
    doc_file  = ("existing_doc.md", current_content.encode(), "text/markdown")
    diff_file = ("changes.diff",    (pr_event.pr_diff or "")[:50000].encode(), "text/plain")
    instruction = (
        f"Two files are attached. Produce the COMPLETE updated documentation page in Markdown.\n"
        f"Page: '{target.page_title}'\n"
        f"Reason: {target.reason}\n"
        f"PR Summary: {analysis.get('summary', '')}\n"
        f"Preserve all still-accurate content. Output only the full updated Markdown."
    )
    try:
        result  = run_pipeline_with_files(_pipeline_id(), instruction, [doc_file, diff_file])
        content, conf, reason = _parse_writer_output(result.get("output", ""))
        
        if conf > 0:
            emit_sub_log(f"Consolidation Confidence: {conf}% - {reason}")
            
        new_md  = content.strip()
    except Exception as e:
        print(f"[DocGen] full_rewrite: Airia failed: {e}")
        return ""
    if not new_md:
        return ""
    page = _safe_update_page(pr_event.pr_number, page_id=target.page_id, title=target.page_title, body_markdown=new_md, current_version=version)
    return page.url


# ---------------------------------------------------------------------------
# sync_related_docs — master orchestrator
# ---------------------------------------------------------------------------

    updated   = []
    space_key = os.getenv("CONFLUENCE_SPACE_KEY", "")

    # Special multi-target case handlers
    if result.case == 5:
        urls = create_migration_guide(result.targets, pr_event, analysis, space_key)
        for url in urls:
            if url:
                updated.append({"title": f"Migration Guide: {pr_event.pr_title}", "url": url})
        return updated

    if result.case in (10, 12, 13):
        # These cases are handled at the Slack alert level in run() — no doc writes here
        return updated

    if result.case in (3, 9, 11):
        # Changelog only — no doc sync needed
        return updated

    for target in result.targets:
        if not target.page_id:
            print(f"[DocGen] Skipping unresolved target: '{target.page_title}'")
            continue

        try:
            url = _dispatch_target(target, pr_event, analysis, space_key, result)
        except Exception as e:
            print(f"[DocGen] Update failed for '{target.page_title}': {e}")
            url = ""

        if url:
            print(f"[DocGen] ✓ Updated: '{target.page_title}' → {url}")
            updated.append({"title": target.page_title, "url": url})
        else:
            print(f"[DocGen] ~ No changes: '{target.page_title}'")

    return updated


# ---------------------------------------------------------------------------
# Changelog + API doc builders
# ---------------------------------------------------------------------------

def _build_changelog_body(pr_event: PREvent, analysis: dict, case_label: str) -> str:
    lines = [
        f"## PR #{pr_event.pr_number}: {pr_event.pr_title}",
        "",
        f"**Branch:** `{pr_event.head_branch}` → `{pr_event.base_branch}`",
        f"**Classification:** `{case_label}`",
    ]
    if pr_event.jira_issue_key:
        lines.append(f"**Jira:** [{pr_event.jira_issue_key}]")
    if pr_event.changed_files:
        files_str = ", ".join("`" + f + "`" for f in pr_event.changed_files)
        lines.append(f"**Changed Files:** {files_str}")
    lines += [
        "",
        "### Summary",
        analysis.get("summary", "_No summary available_"),
        "",
        "### Impact",
        analysis.get("impact", "_No impact analysis available_"),
        "",
        "### Risk",
        analysis.get("risk", "_No risk analysis available_"),
    ]
    return "\n".join(lines)


def _parse_writer_output(raw_output: str) -> tuple[str, int, str]:
    """
    Parses the JSON output from the Airia 2-node Writer Agent pipeline.
    Returns (updated_content, writer_confidence, writer_reason).
    If it's not JSON (fallback to single node), returns the raw text and default confidence.
    """
    import re
    json_match = re.search(r'\{.*\}', raw_output, re.DOTALL)
    if not json_match:
        return raw_output, 0, "Pipeline did not return Confidence JSON."
        
    try:
        data = json.loads(json_match.group())
        content = data.get("updated_content", raw_output)
        
        # In case the model returns the score as a string like "85%"
        conf_raw = data.get("writer_confidence", 0)
        if isinstance(conf_raw, str):
            conf_str = re.sub(r'[^\d]', '', conf_raw)
            conf = int(conf_str) if conf_str else 0
        else:
            conf = int(conf_raw)
            
        reason = data.get("writer_reason", "")
        return content, conf, reason
    except json.JSONDecodeError:
        # Fallback if the user is still using a single-node text output pipeline
        return raw_output, 0, "Pipeline did not return Confidence JSON."

def _generate_api_doc_for_endpoint(endpoint: dict, pr_event: PREvent, diff_context: str) -> str:
    prompt = "\n".join([
        "You are a technical writer. Generate complete API documentation in Markdown.",
        "",
        f"HTTP Method : {endpoint['method']}",
        f"Path        : {endpoint['path']}",
        f"Function    : {endpoint['func']}",
        f"PR Title    : {pr_event.pr_title}",
        "",
        "Relevant diff context:",
        "```diff",
        diff_context[:3000],
        "```",
        "",
        f"## `{endpoint['method']} {endpoint['path']}`",
        "### Description\n### Parameters\n### Request Body\n### Response\n### Example",
    ])
    result = run_pipeline(_pipeline_id(), prompt)
    
    content, conf, reason = _parse_writer_output(result.get("output", ""))
    
    if conf > 0:
        emit_sub_log(f"API Doc Generation Confidence: {conf}% - {reason}")
        
    return content.strip()


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run(pr_event: PREvent, analysis: dict) -> dict:
    """
    Full documentation pipeline for a merged PR.
    Returns:
      - classification:    ClassificationResult (case, label, confidence, reasoning)
      - changelog_url:     Confluence URL of the PR change-log page
      - api_doc_urls:      list of URLs for new API doc pages
      - new_endpoints:     list of detected endpoint dicts
      - updated_doc_urls:  list of {title, url} for all synced pages
      - requires_human_approval: bool
      - slack_alert_level: str
    """
    from agents.page_router import route_pr_to_pages
    space_key = os.getenv("CONFLUENCE_SPACE_KEY", "")

    # Step 0 — Classify the PR (two-stage)
    classification = route_pr_to_pages(pr_event, analysis)
    print(
        f"[DocGen] 📋 PR classified as Case {classification.case} "
        f"({classification.case_label}) [{classification.stage}]"
    )

    result = {
        "classification":         classification,
        "changelog_url":          "",
        "api_doc_urls":           [],
        "new_endpoints":          [],
        "updated_doc_urls":       [],
        "requires_human_approval": classification.requires_human_approval,
        "slack_alert_level":      classification.slack_alert_level,
    }

    # Step 1 — PR Changelog (always written, regardless of case)
    changelog_title   = f"PR #{pr_event.pr_number}: {pr_event.pr_title}"
    changelog_content = _build_changelog_body(pr_event, analysis, classification.case_label)
    changelog_resp    = _safe_create_or_update_page(
        pr_event.pr_number,
        title=changelog_title, body_markdown=changelog_content,
        space_key=space_key, parent_title="DocuSync Change Log",
    )
    result["changelog_url"] = changelog_resp.get("url", "")

    # Step 2 — Auto-generate dedicated API docs for new endpoints (Cases 1, 2, 4)
    new_endpoints = detect_new_endpoints(pr_event.pr_diff or "")
    result["new_endpoints"] = new_endpoints
    if new_endpoints and classification.case not in (3, 9, 11, 12, 13):
        print(f"[DocGen] 🚀 {len(new_endpoints)} new endpoint(s) — generating API docs on single page …")
        emit_sub_log(f"Detected {len(new_endpoints)} new API endpoints. Aggregating documentation...")
        
        combined_api_docs = []
        for endpoint in new_endpoints:
            api_doc_md = _generate_api_doc_for_endpoint(endpoint, pr_event, pr_event.pr_diff or "")
            combined_api_docs.append(api_doc_md)
        
        if combined_api_docs:
            full_markdown = "\n\n---\n\n".join(combined_api_docs)
            api_page_title = "API Reference"
            
            # Check if API Reference exists, otherwise create it
            existing_page = get_page_by_title(api_page_title)
            
            if existing_page:
                from integrations.confluence_client import fetch_page_as_storage_xml
                storage_xml, version = fetch_page_as_storage_xml(existing_page.page_id)
                new_html = _markdown_to_storage(full_markdown)
                updated_xml = storage_xml + f"\n<hr/>\n{new_html}"
                
                api_resp = _safe_update_page(
                    pr_event.pr_number, 
                    page_id=existing_page.page_id, 
                    title=existing_page.title, 
                    body_markdown="", 
                    current_version=version, 
                    raw_storage_xml=updated_xml
                )
                url = api_resp.url if hasattr(api_resp, 'url') else getattr(api_resp, 'get', lambda x, y="": y)("url")
            else:
                api_resp = _safe_create_or_update_page(
                    pr_event.pr_number,
                    title=api_page_title, body_markdown=full_markdown,
                    space_key=space_key, parent_title="Documentation",
                )
                url = api_resp.get("url", "")
                
            if url:
                result["api_doc_urls"].append(url)
                print(f"[DocGen]   ✅ Appended endpoints to {api_page_title} → {url}")
                emit_sub_log(f"Appended endpoint documentation to '{api_page_title}' page.")

    # Step 3 — Doc sync via classification (skipped for HITL, security, tests, doc-only, bug-fix)
    try:
        updated = sync_related_docs(pr_event, analysis, classification)
        result["updated_doc_urls"] = updated
    except Exception as e:
        print(f"[DocGen] Doc sync error: {e}")

    return result
