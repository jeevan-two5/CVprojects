"""
Confluence diagnostics — finds your correct CONFLUENCE_BASE_URL and CONFLUENCE_SPACE_KEY.
Run with: .venv\Scripts\python diagnose_confluence.py
"""

import os
import httpx
from dotenv import load_dotenv

load_dotenv()

base_url  = os.getenv("CONFLUENCE_BASE_URL", "").rstrip("/")
email     = os.getenv("CONFLUENCE_EMAIL", "")
api_token = os.getenv("CONFLUENCE_API_TOKEN", "")

print(f"\n--- Current .env values ---")
print(f"CONFLUENCE_BASE_URL  = {base_url!r}")
print(f"CONFLUENCE_EMAIL     = {email!r}")
print(f"CONFLUENCE_SPACE_KEY = {os.getenv('CONFLUENCE_SPACE_KEY', '')!r}")

# Determine the correct base (strip /wiki if user added it inside URL already,
# then re-add it to make the REST path).
if "/wiki" in base_url:
    rest_base = base_url.rstrip("/")
else:
    rest_base = base_url.rstrip("/") + "/wiki"

print(f"\n--- Trying REST base: {rest_base} ---")

try:
    with httpx.Client(timeout=15, auth=(email, api_token),
                      headers={"Accept": "application/json"}) as client:
        r = client.get(f"{rest_base}/rest/api/space", params={"limit": 20})
        r.raise_for_status()
        spaces = r.json().get("results", [])

    print(f"\n[OK] Connected! Found {len(spaces)} space(s):\n")
    print(f"  {'SPACE KEY':<25} {'DISPLAY NAME'}")
    print(f"  {'-'*25} {'-'*30}")
    for s in spaces:
        print(f"  {s['key']:<25} {s['name']}")

    print(f"\n--- Fix for your .env ---")
    print(f"CONFLUENCE_BASE_URL={rest_base}")
    print(f"CONFLUENCE_SPACE_KEY=<pick the KEY from the table above (left column)>")

except httpx.HTTPStatusError as e:
    print(f"\n[FAIL] HTTP {e.response.status_code}: {e.response.text[:300]}")
except Exception as e:
    print(f"\n[FAIL] {e}")
