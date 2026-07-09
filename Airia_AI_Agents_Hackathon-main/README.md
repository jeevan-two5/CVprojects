# DocuSync AI 🔄📄

DocuSync AI is an autonomous, event-driven multi-agent system that bridges the gap between codebase evolution and project documentation. 

Triggered by GitHub webhooks, DocuSync orchestrates specialized AI agents (powered by Airia) to analyze code changes, route intelligent updates to Confluence, notify teams via Slack, and display real-time execution in a dynamic frontend dashboard.

---

## ✨ Features

### 1. 🔍 Event Gateway & Webhook Router
- Listens to GitHub webhooks for Pull Request events (Merged, Opened, Synchronized) and Jira ticket updates.
- Extracts linked Jira numbers intelligently from branch names or PR titles.
- **Idempotency Engine:** Backed by an embedded SQLite database (`docusync.db`), DocuSync tracks Webhook Delivery IDs to guarantee pipelines are never double-executed, preventing duplicate Confluence updates.

### 2. 🧠 Code Analysis & Enrichment Agent
- Fetches **raw code diffs** and enriches them with descriptions directly from linked Jira tickets.
- Uses Airia AI to synthesize deeply technical code diffs into a human-readable **Summary, Technical Impact, and Risk Assessment**.

### 3. 🎯 Intelligent PR Routing & Classification
- Analyzes the specific nature of the PR to determine what needs to be updated.
- Determines whether a change requires a brand new Confluence page, an API endpoint section addition, a deprecation banner, or just a Slack ping.

### 4. 📝 Documentation Writer Agent
- **Automated API Reference:** Dynamically detects any newly added REST/GraphQL endpoints in the code and autonomously synthesizes them into a single, aggressively unified `API Reference` Confluence page to avoid clutter.
- **Semantic Section Replacement:** Rather than overwriting entire wiki pages, the agent intelligently target-replaces only the specific markdown headings affected by the code diff.
- **Banners:** Automatically prepends "Outdated Warning" or "Deprecation" macros onto Confluence pages matching certain risk profiles.

### 5. 💬 Team Notification Agent
- Sends highly structured, color-coded **Slack Block Kit** messages directly to engineering channels on successful merge.
- Displays AI-generated Confidence Scores so developers know exactly how much to trust the automated documentation update.

### 6. 🌐 Live Pipeline Viewer (Frontend Dashboard)
- A dedicated, real-time UI available at `/dashboard` featuring a sleek, Glassmorphism-inspired aesthetic and live terminal rendering.
- Powered natively by **Server-Sent Events (SSE)** and Python `contextvars`. As asynchronous AI background threads run, the specific sub-logs ("Appended snippet to API reference...", "Intercepted idempotent webhook...") cascade straight into the browser without polling or reloading.

---

## 🚀 Setup & Installation

### 1. Environment variables
Copy the template and fill in your actual credentials:
```bash
cp .env.example .env
```
Ensure you have API keys and tokens configured for:
- **GitHub** (Webhook Secret & PAT)
- **Jira** (Base URL, Email, Token)
- **Confluence** (Base URL, Email, Token, Target Space Key)
- **Slack** (Incoming Webhook URL)
- **Airia** (API Key, Base URL, Pipeline IDs)

### 2. Install Dependencies
```bash
python -m venv .venv
# Activate virtual environment (Windows)
.venv\Scripts\activate
# Install requirements
pip install -r requirements.txt
```

### 3. Running the System locally (Two Terminals)

**Terminal 1 — The FastAPI Server:**
```bash
.venv\Scripts\activate
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```
*(Navigate to http://localhost:8000/dashboard to view the live dashboard!)*

**Terminal 2 — The Ngrok Tunnel (For GitHub Webhooks):**
```bash
ngrok http 8000
```
*Note: Copy the `https://...ngrok-free.app` forwarding URL and add `/webhook/github` to it. Paste this into your GitHub Repository Webhooks setting to start receiving live PR events.*

### 4. Testing the UI
If you don't want to wait for a GitHub PR to trigger the dashboard, you can run a mock pipeline in a separate terminal:
```bash
.venv\Scripts\activate
python scripts/mock_pipeline.py
```
*(Navigate to http://localhost:8001/dashboard and click "Trigger Demo PR")*

