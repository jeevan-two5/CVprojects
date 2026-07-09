"""
Airia API debug script — prints the full 400 error body so we can fix the request shape.
Run with: .venv\Scripts\python diagnose_airia.py
"""

import os
import httpx
from dotenv import load_dotenv

load_dotenv()

api_key     = os.getenv("AIRIA_API_KEY", "")
pipeline_id = os.getenv("AIRIA_CODE_ANALYSIS_PIPELINE_ID", "")
base_url    = os.getenv("AIRIA_API_BASE_URL", "https://api.airia.ai").rstrip("/")

url = f"{base_url}/v1/PipelineExecution/{pipeline_id}"

print(f"\n--- Airia Debug ---")
print(f"URL        : {url}")
print(f"Pipeline ID: {pipeline_id}")
print(f"API Key    : {api_key[:8]}...{api_key[-4:] if len(api_key) > 12 else '***'}\n")

# Try several payload variants to find what Airia accepts
payloads = [
    {"label": "Variant 1 — userMessage + asyncOutput",
     "body": {"userMessage": "Hello, summarise this PR.", "asyncOutput": False}},

    {"label": "Variant 2 — userInput only",
     "body": {"userInput": "Hello, summarise this PR."}},

    {"label": "Variant 3 — message only",
     "body": {"message": "Hello, summarise this PR."}},

    {"label": "Variant 4 — input only",
     "body": {"input": "Hello, summarise this PR."}},

    {"label": "Variant 5 — userMessage only (no asyncOutput)",
     "body": {"userMessage": "Hello, summarise this PR."}},
]

headers = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "X-API-Key": api_key,
}

for p in payloads:
    print(f"Trying {p['label']}...")
    try:
        r = httpx.post(url, json=p["body"], headers=headers, timeout=15)
        print(f"  Status : {r.status_code}")
        try:
            print(f"  Body   : {r.json()}")
        except Exception:
            print(f"  Body   : {r.text[:300]}")
    except Exception as e:
        print(f"  Error  : {e}")
    print()
