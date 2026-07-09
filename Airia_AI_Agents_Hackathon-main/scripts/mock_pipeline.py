import uvicorn
from fastapi import FastAPI, BackgroundTasks, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse
import asyncio
import json
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ui-test")

app = FastAPI()
templates = Jinja2Templates(directory="templates")
clients = []

@app.get("/dashboard", response_class=HTMLResponse)
async def serve_dashboard(request: Request):
    # We serve the same dashboard.html. 
    # To make it connect to THIS server instead of the main one, 
    # we'll inject a small script to override the EventSource URL if needed,
    # but since it's a relative path '/api/events', it will work automatically 
    # if opened on port 8001.
    return templates.TemplateResponse("dashboard.html", {"request": request})

@app.get("/api/events")
async def sse_events(request: Request):
    queue = asyncio.Queue()
    clients.append(queue)
    logger.info(f"Client connected. Total clients: {len(clients)}")
    
    async def event_generator():
        try:
            while True:
                data = await queue.get()
                yield {"data": json.dumps(data)}
        except asyncio.CancelledError:
            pass
        finally:
            if queue in clients:
                clients.remove(queue)
            logger.info(f"Client disconnected. Total clients: {len(clients)}")
            
    return EventSourceResponse(event_generator())

async def run_mock_pipeline(pr_number: int):
    """Simulates pipeline events without calling any external agents."""
    events = [
        {"pr_number": pr_number, "title": "Mock PR for UI Test", "agent": 1, "status": "done", "label": "Fetched PR diff", "diff": "--- a/test.py\n+++ b/test.py\n@@ -1,1 +1,1 @@\n-old\n+new"},
        {"pr_number": pr_number, "sub_log": "Connecting to GitHub API..."},
        {"pr_number": pr_number, "sub_log": "Authenticated successfully using GITHUB_TOKEN."},
        {"pr_number": pr_number, "sub_log": "Fetching pull request metadata..."},
        {"pr_number": pr_number, "sub_log": "Diff contains 3 files and 145 line additions."},
        {"pr_number": pr_number, "agent": 2, "status": "done", "label": "Analyzed impact"},
        {"pr_number": pr_number, "sub_log": "Sending diff to Airia Code Analysis pipeline..."},
        {"pr_number": pr_number, "sub_log": "Waiting for semantic analysis..."},
        {"pr_number": pr_number, "sub_log": "Received JSON response from Analyzer agent."},
    ]
    
    # Stress test: Add 25 more sub-logs to confirm scrolling works
    for i in range(1, 26):
        events.append({"pr_number": pr_number, "sub_log": f"Internal Step #{i}: Processing chunk of analysis data..."})

    events.extend([
        {"pr_number": pr_number, "sub_log": "Classified as Case 4: SECTION UPDATED (Confidence: 95%)"},
        {"pr_number": pr_number, "agent": 3, "status": "done", "label": "Generated updates", "classification_label": "SECTION UPDATED", "confidence": "95%", "new_text": "Updated content here..."},
        {"pr_number": pr_number, "sub_log": "Confluence Connection established..."},
        {"pr_number": pr_number, "sub_log": "Fetching Parent Page ID from space 'ENGINEERING'."},
        {"pr_number": pr_number, "sub_log": "Appended additive snippet to section: 'bottom of page'."},
        {"pr_number": pr_number, "sub_log": "Waiting for developer review on Slack..."},
        {"pr_number": pr_number, "agent": 4, "status": "hitl", "label": "Awaiting review", "uncertainty": "Low confidence in section mapping."}
    ])
    
    for event in events:
        if "sub_log" in event:
            await asyncio.sleep(0.5)
            logger.info(f"Emitting sub log: {event['sub_log']}")
        else:
            await asyncio.sleep(1.5) # Simulate processing time
            logger.info(f"Emitting event: {event['label']}")
            
        for queue in clients:
            await queue.put(event)

@app.post("/api/demo")
async def trigger_demo(background_tasks: BackgroundTasks):
    pr_num = 1337
    background_tasks.add_task(run_mock_pipeline, pr_num)
    return {"message": "Mock demo triggered"}

if __name__ == "__main__":
    print("\n" + "="*50)
    print("🚀 DocuSync UI Verification Server")
    print("This server runs a MOCK pipeline to test UI aesthetics and logic.")
    print("It uses the CORRECT SSE formatting to avoid JSON errors.")
    print("="*50)
    print("\n1. Open: http://localhost:8001/dashboard")
    print("2. Click 'Trigger Demo PR'")
    print("3. Verify that the pipeline appears without console errors.\n")
    
    uvicorn.run(app, host="127.0.0.1", port=8001)
