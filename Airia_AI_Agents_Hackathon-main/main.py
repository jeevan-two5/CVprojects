"""
DocuSync AI — FastAPI Entry Point
Receives GitHub webhook events and orchestrates the full agent pipeline.

Pipeline (triggers on PR merged):
  GitHub Webhook
      → parse_and_enrich()      fetch PR metadata + changed files + raw diff
      → code_analysis.run()     call Airia: summary / impact / risk
      → [doc_generation.run()]  (Phase 3 next step)
      → [notification.run()]    (Phase 3 next step)
"""

import os
import logging
from fastapi import FastAPI, Request, Header, BackgroundTasks
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("docusync")

app = FastAPI(
    title="DocuSync AI",
    description="Autonomous Documentation Agent for Developer Workflows",
    version="0.2.0",
)

from routers.dashboard import router as dashboard_router
app.include_router(dashboard_router)


import asyncio

@app.on_event("startup")
async def startup():
    from routers.dashboard import set_event_loop
    set_event_loop(asyncio.get_event_loop())

# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health", tags=["utility"])
async def health():
    return {"status": "ok", "service": "docusync-ai", "version": "0.2.0"}


# ---------------------------------------------------------------------------
# Core pipeline (runs in background so webhook returns fast)
# ---------------------------------------------------------------------------

def run_docusync_pipeline(payload: dict):
    """
    Full DocuSync pipeline — called in the background after each merged PR.
    Current wiring:
      1. Parse webhook + fetch real diff from GitHub
      2. Code Analysis Agent → produces summary / impact / risk
      3. Doc Generation Agent (to be added next)
      4. Notification Agent  (to be added next)
    """
    from integrations.github_handler import parse_and_enrich
    from agents.code_analysis import run as analyse
    from agents.staging_store import mark_pr_processed, is_pr_processed
    from routers.dashboard import current_pr, emit_sub_log

    pr = payload.get("pull_request", {})
    pr_number = pr.get("number")
    merge_sha  = pr.get("merge_commit_sha", "")

    # Set the ContextVar so inner functions know which PR is active
    if pr_number:
        current_pr.set(pr_number)

    # -------------------------------------------------------------------
    # Idempotency guard (Feature 4)
    # Prevent duplicate pipeline runs when GitHub retries the webhook
    # -------------------------------------------------------------------
    if merge_sha and is_pr_processed(merge_sha):
        emit_sub_log(f"Idempotency: PR #{pr_number} already processed. Skipping.")
        log.warning(
            f"[DocuSync] ⛔ PR #{pr_number} (SHA: {merge_sha[:8]}) already processed. "
            f"Skipping duplicate webhook delivery."
        )
        return

    log.info("="*60)
    log.info(f"🚀 [STAGE 1] PIPELINE TRIGGERED FOR PR #{pr_number}")
    log.info("="*60)

    # Step 1 — Parse payload and enrich with real GitHub data (files + diff)
    try:
        log.info(f"[*] Fetching PR diff and files from GitHub API...")
        emit_sub_log(f"Fetching PR diff and files from GitHub API...")
        event = parse_and_enrich(payload)
        from routers.dashboard import emit_event
        emit_event({
            "pr_number": pr_number, 
            "title": event.pr_title,
            "jira_key": event.jira_issue_key,
            "agent": 1, 
            "status": "done", 
            "label": "Fetched PR diff",
            "diff": event.pr_diff
        })
        log.info(f"[+] Enrichment Success: {len(event.changed_files)} changed files, diff size={len(event.pr_diff)} chars.")
    except Exception as e:
        log.error(f"[!] Failed to enrich PR event from GitHub: {e}")
        return

    # Step 2 — Code Analysis Agent: summarise + impact + risk
    try:
        log.info("="*60)
        log.info(f"🧠 [STAGE 2] AIRIA CODE ANALYSIS")
        log.info("="*60)
        log.info(f"[*] Analyzing code diff to determine impact and risk...")
        emit_sub_log("Analyzing code diff to determine impact and risk...")
        analysis = analyse(event)
        emit_event({"pr_number": pr_number, "agent": 2, "status": "done", "label": "Analyzed impact"})
        log.info(f"[+] Analysis Complete:")
        log.info(f"    - SUMMARY: {analysis['summary']}")
        log.info(f"    - IMPACT : {analysis['impact']}")
        log.info(f"    - RISK   : {analysis['risk']}")
        emit_sub_log(f"Analysis Complete: {analysis['summary']} {analysis['impact']} {analysis['risk']}")
    except Exception as e:
        log.error(f"[!] Code Analysis Agent failed: {e}")
        return

    # Step 3 — Doc Generation: write to Confluence, auto-generate API docs if needed
    try:
        from agents.doc_generation import run as generate_docs
        log.info("="*60)
        log.info(f"📝 [STAGE 3] DOCUMENTATION GENERATION")
        log.info("="*60)
        log.info(f"[*] Classifying PR and generating documentation updates...")
        emit_sub_log("Classifying PR and determining documentation strategy...")
        doc_result = generate_docs(event, analysis)
        
        clf = doc_result.get("classification")
        clf_confidence = getattr(clf, "confidence", "") or (clf.get("confidence", "") if isinstance(clf, dict) else "")
        
        emit_event({
            "pr_number": pr_number, 
            "agent": 3, 
            "status": "done", 
            "label": "Generated updates", 
            "classification_label": getattr(clf, "case_label", "") or (clf.get("case_label", "") if isinstance(clf, dict) else ""),
            "confidence": clf_confidence,
            "old_text": doc_result.get("old_text", ""),
            "new_text": doc_result.get("new_text", ""),
            "uncertainty": doc_result.get("uncertainty", "")
        })
        
        log.info(f"[+] Changelog generated at: {doc_result['changelog_url']}")
        if doc_result["new_endpoints"]:
            log.info(f"[+] {len(doc_result['new_endpoints'])} new API endpoint(s) documented!")
            for url in doc_result["api_doc_urls"]:
                log.info(f"    -> API doc page: {url}")
    except Exception as e:
        log.error(f"[!] Doc Generation Agent failed: {e}")
        return

    # Step 4 — Slack Notification
    try:
        from agents.notification import run as notify
        from integrations.slack_client import send_approval_request
        
        hitl_enabled = os.getenv("HITL_ENABLED", "false").lower() == "true"
        
        # Check if there are any staged updates for this PR
        has_pending = any(
            url.startswith("pending-approval") 
            for d in doc_result.get("updated_doc_urls", []) 
            for url in ([d.get("url", "")] if isinstance(d, dict) else [])
        ) or any(
            url.startswith("pending-approval") 
            for url in doc_result.get("api_doc_urls", [])
        ) or str(doc_result.get("changelog_url", "")).startswith("pending-approval")

        log.info("="*60)
        log.info(f"💬 [STAGE 4] SLACK NOTIFICATION AND ROUTING")
        log.info("="*60)

        if hitl_enabled and has_pending:
            log.info(f"[*] HITL mode is enabled. Staged updates found.")
            log.info(f"[*] Requesting human approval via Slack...")
            emit_sub_log(f"Human-In-The-Loop: Requesting approval for {len(doc_result.get('updated_doc_urls', [])) + len(doc_result.get('api_doc_urls', [])) + 1} changes via Slack.")
            staging_count = len(doc_result.get("updated_doc_urls", [])) + len(doc_result.get("api_doc_urls", [])) + 1
            clf = doc_result.get("classification")
            clf_label      = getattr(clf, "case_label", "") or (clf.get("case_label", "") if isinstance(clf, dict) else "")
            
            send_approval_request(
                pr_number=pr_number,
                pr_title=event.pr_title,
                summary=analysis.get("summary", ""),
                impact=analysis.get("impact", ""),
                risk=analysis.get("risk", ""),
                staging_count=staging_count,
                classification_label=clf_label,
                classification_confidence=clf_confidence,
            )
            
            # Save context for final notification after human approval
            from agents.staging_store import save_pr_context
            save_pr_context(pr_number, {
                "pr_title": event.pr_title,
                "jira_key": event.jira_issue_key,
                "summary": analysis.get("summary", ""),
                "impact": analysis.get("impact", ""),
                "risk": analysis.get("risk", ""),
                "changelog_url": doc_result.get("changelog_url", ""),
                "api_doc_urls": doc_result.get("api_doc_urls", []),
                "updated_doc_urls": doc_result.get("updated_doc_urls", []),
                "new_endpoints": doc_result.get("new_endpoints", []),
                "classification_label": clf_label,
                "classification_confidence": clf_confidence,
            })
            
            log.info(f"[+] Slack Block Kit approval request delivered.")
            emit_event({
                "pr_number": pr_number, 
                "agent": 4, 
                "status": "hitl", 
                "label": "Awaiting review",
                "title": event.pr_title,
                "jira_key": event.jira_issue_key,
                "confidence": clf_confidence,
                "diff": event.pr_diff,
                "uncertainty": doc_result.get("uncertainty", "")
            })
            
            # Feature 6 dashboard explicitly requested to pause here:
            # "When confidence is below the existing threshold, emit a hitl status and pause
            # — do not call the Publisher. The pipeline resumes only when approve is called externally."
            return

        else:
            log.info(f"[*] HITL mode disabled or no staged docs. Sending final Slack report...")
            emit_event({"pr_number": pr_number, "agent": 4, "status": "done", "label": "Auto-approved"})
            
            notify(event, analysis, doc_result)
            emit_event({"pr_number": pr_number, "agent": 5, "status": "done", "label": "Pipeline complete"})
            emit_sub_log("Pipeline finalized and Slack notifications delivered.")
            log.info(f"[+] Slack notification sent.")
    except Exception as e:
        log.warning(f"[!] Slack notification failed (non-critical): {e}")

    log.info("="*60)
    # Mark this SHA as done so any GitHub webhook retry is silently skipped
    if merge_sha:
        mark_pr_processed(merge_sha)
        log.info(f"[+] PR #{pr_number} (SHA: {merge_sha[:8]}) marked as processed.")
    log.info(f"✅ PIPELINE FINISHED FOR PR #{pr_number}")
    log.info("="*60)


# ---------------------------------------------------------------------------
# GitHub Webhook Receiver
# ---------------------------------------------------------------------------

@app.post("/webhook/github", tags=["webhook"])
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_github_event: str = Header(default="ping"),
):
    """
    Receives GitHub webhook payloads.
    Only processes pull_request events with action=closed AND merged=true.
    The full pipeline runs in a background task so this endpoint
    responds to GitHub quickly (avoids timeout).
    """
    payload = await request.json()

    # --- Ping check (GitHub fires this when you first add the webhook) ---
    if x_github_event == "ping":
        log.info("[DocuSync] Received GitHub webhook ping ✅")
        return {"message": "pong — DocuSync webhook connected successfully"}

    # --- Only care about pull_request events ---
    if x_github_event != "pull_request":
        return {"message": f"Event '{x_github_event}' ignored"}

    action = payload.get("action", "")
    pr = payload.get("pull_request", {})
    merged = pr.get("merged", False)
    pr_number = pr.get("number")
    pr_title  = pr.get("title", "")

    # --- Only trigger pipeline on merged PRs ---
    if action == "closed" and merged:
        log.info(f"[DocuSync] PR #{pr_number} merged: '{pr_title}' — launching pipeline ...")
        background_tasks.add_task(run_docusync_pipeline, payload)
        return {
            "received": True,
            "status": "pipeline_started",
            "pr_number": pr_number,
            "pr_title": pr_title,
            "message": "DocuSync pipeline started in background",
        }

    # --- Closed but NOT merged (PR was simply closed/rejected) ---
    if action == "closed" and not merged:
        log.info(f"[DocuSync] PR #{pr_number} closed without merging — skipping.")
        return {"received": True, "status": "skipped", "reason": "PR closed but not merged"}

    # --- Other events (opened, synchronize, etc.) ---
    return {"received": True, "status": "ignored", "action": action}


# ---------------------------------------------------------------------------
# HITL Approval Endpoints
# ---------------------------------------------------------------------------

from fastapi.responses import HTMLResponse

@app.get("/approve/{pr_id}", tags=["hitl"])
async def approve(pr_id: int):
    """Approve a staged documentation update (Triggered via Browser link from Slack)."""
    from agents.staging_store import pop_staged_updates, get_pr_context
    from integrations.confluence_client import create_or_update_page, update_page
    from integrations.slack_client import send_message, send_pipeline_complete_notification
    from routers.dashboard import emit_event
    
    updates = pop_staged_updates(pr_id)
    if not updates:
        return HTMLResponse(content="<h1>No pending updates found for this PR.</h1><p>They might have been already approved or rejected.</p>")
        
    success_count = 0
    errors = []
    doc_urls = []
    api_urls = []
    changelog_url = ""
    
    for update in updates:
        action = update.get("action")
        kwargs = update.get("kwargs", {})
        try:
            if action == "create_or_update_page":
                result = create_or_update_page(**kwargs)
                title = kwargs.get("title", "New Page")
                url = result["url"]
                
                if title.startswith("PR #"):
                     changelog_url = url
                elif title.startswith("API: "):
                     api_urls.append(url)
                else:
                     doc_urls.append({"title": title, "url": url})
                     
            elif action == "update_page":
                result = update_page(**kwargs)
                doc_urls.append({"title": kwargs.get("title", "Updated Page"), "url": result.url})
            success_count += 1
        except Exception as e:
            errors.append(f"Failed to '{action}' for '{kwargs.get('title', 'Unknown')}': {e}")
            
    if errors:
        err_list = "".join(f"<li>{e}</li>" for e in errors)
        send_message(f"⚠️ DocuSync encountered errors while applying approved updates for PR #{pr_id}.")
        emit_event({"pr_number": pr_id, "status": "done", "label": "Approved with Errors", "agent": 4})
        return HTMLResponse(content=f"<h1>Approval Complete with Errors</h1><ul>{err_list}</ul><p>{success_count} updates were successful.</p>")
        
    # Emit event to dashboard
    emit_event({"pr_number": pr_id, "status": "done", "label": "Approved & Published", "agent": 4})
    emit_event({"pr_number": pr_id, "status": "done", "label": "Pipeline complete", "agent": 5})
    
    # Send Final Slack Notification
    context = get_pr_context(pr_id)
    if context:
        # Merge any newly discovered URLs with context ones
        existing_doc_urls = context.get("updated_doc_urls", [])
        if doc_urls:
             existing_doc_urls = doc_urls # override with the actual processed ones
             
        final_changelog = changelog_url if changelog_url else context.get("changelog_url", "")
        final_api_urls = api_urls if api_urls else context.get("api_doc_urls", [])
        print("Hello Abhiraj")
        send_message(f"✅ *DocuSync Updates Approved!* Successfully published Confluence pages for PR #{pr_id}.")
        send_pipeline_complete_notification(
            pr_number=pr_id,
            pr_title=context.get("pr_title", ""),
            jira_key=context.get("jira_key", ""),
            summary=context.get("summary", ""),
            impact=context.get("impact", ""),
            risk=context.get("risk", ""),
            changelog_url=final_changelog,
            api_doc_urls=final_api_urls,
            updated_doc_urls=existing_doc_urls,
            new_endpoints=context.get("new_endpoints", []),
            classification_label=context.get("classification_label", ""),
            classification_confidence=context.get("classification_confidence", ""),
        )
    else:
        # Fallback if no context found
        send_message(f"✅ *DocuSync Updates Approved!* Successfully published {success_count} Confluence pages for PR #{pr_id}.")
        
    return HTMLResponse(content=f"<h1>✅ Approval Successful</h1><p>Successfully published {success_count} documentation updates to Confluence!</p><p>You may close this tab.</p>")



@app.get("/preview/{pr_id}", tags=["hitl"])
async def preview(pr_id: int):
    """Preview staged documentation updates before approving."""
    from agents.staging_store import peek_staged_updates
    import html
    
    updates = peek_staged_updates(pr_id)
    if not updates:
        return HTMLResponse(content="<h1>No pending updates found for this PR.</h1><p>They might have been already approved, rejected, or an error occurred.</p>")
        
    html_content = f"<html><head><title>Preview PR #{pr_id} Docs</title><style>body {{ font-family: sans-serif; padding: 20px; }} .card {{ border: 1px solid #ccc; padding: 15px; margin-bottom: 20px; border-radius: 5px; background: #fafafa; }} pre {{ background: #eee; padding: 10px; overflow-x: auto; }}</style></head><body>"
    html_content += f"<h1>Staged Document Updates for PR #{pr_id}</h1>"
    
    for idx, update in enumerate(updates):
        action = update.get("action")
        kwargs = update.get("kwargs", {})
        title = kwargs.get("title", "Unknown Title")
        page_id = kwargs.get("page_id", "N/A - New Page")
        
        body_markdown = kwargs.get("body_markdown", "")
        raw_storage_xml = kwargs.get("raw_storage_xml", "")
        
        html_content += f"<div class='card'>"
        if action == "create_or_update_page":
            html_content += f"<h2>📄 [NEW] {title}</h2>"
        else:
            html_content += f"<h2>📝 [UPDATE] {title} (ID: {page_id})</h2>"
            
        if body_markdown:
            html_content += f"<h3>Markdown Content:</h3><pre>{html.escape(body_markdown)}</pre>"
        if raw_storage_xml:
            html_content += f"<h3>Confluence XML Injection:</h3><pre>{html.escape(raw_storage_xml)}</pre>"
            
        html_content += "</div>"
        
    html_content += "</body></html>"
    return HTMLResponse(content=html_content)

@app.get("/reject/{pr_id}", tags=["hitl"])
async def reject(pr_id: int):
    """Reject a staged documentation update (Triggered via Browser link from Slack)."""
    from agents.staging_store import clear_staged_updates
    from integrations.slack_client import send_message
    from routers.dashboard import emit_event
    
    clear_staged_updates(pr_id)
    send_message(f"❌ *DocuSync Updates Rejected.* The pending documentation changes for PR #{pr_id} have been discarded.")
    emit_event({"pr_number": pr_id, "status": "rejected", "label": "Changes Rejected", "agent": 4})
    
    return HTMLResponse(content="<h1>❌ Changes Rejected</h1><p>The pending documentation updates have been permanently discarded.</p><p>You may close this tab.</p>")

