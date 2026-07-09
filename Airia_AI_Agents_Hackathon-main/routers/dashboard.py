import asyncio
import json
import sqlite3
import contextvars
from typing import AsyncGenerator
from contextlib import asynccontextmanager
from fastapi import APIRouter, Request, BackgroundTasks
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse

from agents.staging_store import DB_PATH, pop_staged_updates, clear_staged_updates
from integrations.confluence_client import create_or_update_page, update_page
from datetime import datetime, timezone

router = APIRouter()

# Context variable to hold the PR number within the background task pipeline
current_pr: contextvars.ContextVar[int | None] = contextvars.ContextVar("current_pr", default=None)

templates = Jinja2Templates(directory="templates")

# Global async list of queues for SSE clients
clients = []

# Store a reference to the running event loop so background threads can safely post events
_event_loop: asyncio.AbstractEventLoop | None = None

def set_event_loop(loop: asyncio.AbstractEventLoop):
    """Called once at startup from the async context to capture the running loop."""
    global _event_loop
    _event_loop = loop

def emit_event(data: dict):
    """
    Thread-safe event emission. Push an event dict to all connected SSE clients.
    Uses call_soon_threadsafe so that background pipeline threads can safely
    enqueue events onto the main asyncio event loop.
    """
    loop = _event_loop
    if loop is None:
        # Fallback: try to get running loop (only works if called from async context)
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            return

    for queue in list(clients):  # copy to avoid mutation-during-iteration
        try:
            if loop.is_running():
                loop.call_soon_threadsafe(queue.put_nowait, data)
            else:
                queue.put_nowait(data)
        except Exception:
            pass

def emit_sub_log(msg: str):
    """
    Helper to emit a sub-log event for the currently executing PR pipeline.
    Requires 'current_pr' contextvar to be set.
    """
    pr_id = current_pr.get()
    if pr_id is not None:
        emit_event({"pr_number": pr_id, "sub_log": msg})

@router.get("/dashboard", response_class=HTMLResponse)
async def serve_dashboard(request: Request):
    """Serve the dashboard HTML template."""
    # Capture the running event loop the first time a request comes in
    global _event_loop
    if _event_loop is None:
        _event_loop = asyncio.get_event_loop()
    return templates.TemplateResponse("dashboard.html", {"request": request})

@router.get("/api/events")
async def sse_events(request: Request):
    """Stream pipeline events to the frontend in real time using Server-Sent Events."""
    # Capture the event loop if not yet set
    global _event_loop
    if _event_loop is None:
        _event_loop = asyncio.get_event_loop()

    queue = asyncio.Queue()
    clients.append(queue)
    
    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=15.0)
                    # CHANGE THIS: wrap your dict as JSON string in 'data' key
                    yield {"data": json.dumps(data)}
                except asyncio.TimeoutError:
                    yield {"data": "keepalive", "event": "ping"}
        except asyncio.CancelledError:
            pass
        finally:
            if queue in clients:
                clients.remove(queue)
            
    return EventSourceResponse(event_generator())

@router.post("/api/demo")
async def trigger_demo(background_tasks: BackgroundTasks):
    """
    Fire a realistic hardcoded PR payload simulating a functionality change
    through the same pipeline function the real GitHub webhook uses.
    """
    from main import run_docusync_pipeline
    
    # Capture the loop now (in async context) before handing off to thread
    global _event_loop
    if _event_loop is None:
        _event_loop = asyncio.get_event_loop()
    
    demo_payload = {
        "pull_request": {
            "number": 420,
            "title": "feat/oauth-token-refresh (JIRA-291)",
            "body": "Updates oauth token refresh expiry auth. Changed token expiry to 30 mins.",
            "head": {"sha": "demoabc1234", "ref": "feat/oauth-token-refresh"},
            "base": {"ref": "main"},
            "merge_commit_sha": f"demomerge{int(datetime.now().timestamp())}"  # Unique sha for idempotency bypass
        },
        "repository": {
            "full_name": "company/backend-api"
        }
    }
    
    background_tasks.add_task(run_demo_pipeline, demo_payload)
    return {"message": "Demo triggered"}

def run_demo_pipeline(payload):
    """Wrapper to mock the GitHub API for the demo run, then call the real pipeline."""
    from unittest.mock import patch
    from main import run_docusync_pipeline

    demo_diff = '''diff --git a/auth/token.py b/auth/token.py
index a1b2c3d..e4f5g6h 100644
--- a/auth/token.py
+++ b/auth/token.py
@@ -10,7 +10,7 @@
-def refresh_token(token: str):
-    expiry = 60
+def refresh_token(token: str, silent: bool = True):
+    expiry = 30
     # logic to refresh token
'''
    
    with patch("integrations.github_handler.fetch_changed_files", return_value=["auth/token.py"]), \
         patch("integrations.github_handler.fetch_pr_diff", return_value=demo_diff):
        
        run_docusync_pipeline(payload)
