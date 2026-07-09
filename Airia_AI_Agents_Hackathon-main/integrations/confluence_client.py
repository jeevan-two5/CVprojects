"""
Confluence Client — Phase 6 (Architecture Overhaul)
Creates and updates Confluence pages via REST API v1.

Key improvements over Phase 2:
  - _markdown_to_storage() now uses the `markdown2` library for full CommonMark
    support (bold, italic, tables, ordered/unordered lists, links, nested lists).
    Code blocks are post-processed into Confluence <ac:structured-macro> format.
  - fetch_page_as_storage_xml() returns raw Confluence Storage XML for structural
    updates without lossy round-trips through Markdown.
  - fetch_all_page_titles() fetches all page titles in a space (paginated) for
    use by the Intent-Aware Page Router Agent.
  - update_page() accepts either Markdown (auto-converts) or raw Storage XML.
"""

import os
import re
import html as html_module
import markdown2
import httpx
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class ConfluencePage:
    page_id: str
    title: str
    url: str
    version: int


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_client() -> tuple[str, str, httpx.Client]:
    """
    Build an authenticated httpx client from .env credentials.
    Returns (base_url, space_key, client).
    """
    base_url  = os.getenv("CONFLUENCE_BASE_URL", "").rstrip("/")
    email     = os.getenv("CONFLUENCE_EMAIL", "")
    api_token = os.getenv("CONFLUENCE_API_TOKEN", "")
    space_key = os.getenv("CONFLUENCE_SPACE_KEY", "")

    if not all([base_url, email, api_token, space_key]):
        raise ValueError(
            "CONFLUENCE_BASE_URL, CONFLUENCE_EMAIL, CONFLUENCE_API_TOKEN, "
            "and CONFLUENCE_SPACE_KEY must be set in .env"
        )

    client = httpx.Client(
        timeout=30,
        auth=(email, api_token),
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    return base_url, space_key, client


def _clean_base_url(base_url: str) -> str:
    """Strip trailing /wiki to avoid /wiki/wiki/ double-paths."""
    return base_url[:-5] if base_url.endswith("/wiki") else base_url


def _markdown_to_storage(markdown: str) -> str:
    """
    Convert Markdown → Confluence Storage Format (XHTML).

    Uses `markdown2` for full CommonMark fidelity (bold, italic, tables,
    ordered/unordered/nested lists, links, inline code, blockquotes).

    Post-processing converts HTML <pre><code> blocks to Confluence's native
    <ac:structured-macro ac:name="code"> so they render with syntax coloring.
    """
    # Convert Markdown → HTML via markdown2 with useful extras enabled
    html_output = markdown2.markdown(
        markdown,
        extras=[
            "fenced-code-blocks",   # ```lang ... ``` blocks
            "tables",               # GFM tables
            "strike",               # ~~strikethrough~~
            "task_list",            # - [x] checkboxes
            "break-on-newline",     # single newline = <br>
            "header-ids",           # anchored headings
        ],
    )

    # Post-process: replace <pre><code class="language-X">...</code></pre>
    # with Confluence native code macro (preserves syntax highlighting)
    def _replace_code_block(match: re.Match) -> str:
        lang_match = re.search(r'class="language-(\w+)"', match.group(1))
        language   = lang_match.group(1) if lang_match else "none"
        inner_code = match.group(2)
        # Unescape HTML entities inside the raw code block
        inner_code = html_module.unescape(inner_code)
        return (
            f'<ac:structured-macro ac:name="code">'
            f'<ac:parameter ac:name="language">{language}</ac:parameter>'
            f'<ac:plain-text-body><![CDATA[{inner_code}]]></ac:plain-text-body>'
            f'</ac:structured-macro>'
        )

    html_output = re.sub(
        r'<pre><code([^>]*)>(.*?)</code></pre>',
        _replace_code_block,
        html_output,
        flags=re.DOTALL,
    )

    # Wrap in a root div so it is valid XHTML for Confluence storage
    return html_output.strip()


# ---------------------------------------------------------------------------
# Public API — Read operations
# ---------------------------------------------------------------------------

def get_page_by_title(title: str) -> ConfluencePage | None:
    """
    Search for an existing Confluence page by title in the configured space.
    Returns ConfluencePage if found, None otherwise.
    """
    base_url, space_key, client = _get_client()
    with client:
        response = client.get(
            f"{base_url}/rest/api/content",
            params={
                "title": title,
                "spaceKey": space_key,
                "expand": "version",
            },
        )
        response.raise_for_status()
        results = response.json().get("results", [])

    if not results:
        return None

    page = results[0]
    clean_base = _clean_base_url(base_url)

    return ConfluencePage(
        page_id=page["id"],
        title=page["title"],
        url=f"{clean_base}/wiki/spaces/{space_key}/pages/{page['id']}",
        version=page["version"]["number"],
    )


def search_pages_by_keywords(keywords: list[str], max_results: int = 5) -> list[ConfluencePage]:
    """
    Use Confluence CQL to search for pages whose title OR body contains keywords.
    Kept for backward compatibility; new flow uses fetch_all_page_titles + Page Router.
    """
    base_url, space_key, client = _get_client()

    kw_clauses = " OR ".join(
        f'(title~"{kw}" OR text~"{kw}")' for kw in keywords if kw.strip()
    )
    if not kw_clauses:
        return []

    cql = f'space="{space_key}" AND type=page AND ({kw_clauses})'

    with client:
        response = client.get(
            f"{base_url}/rest/api/content/search",
            params={"cql": cql, "limit": max_results, "expand": "version"},
        )
        response.raise_for_status()
        results = response.json().get("results", [])

    clean_base = _clean_base_url(base_url)

    return [
        ConfluencePage(
            page_id=p["id"],
            title=p["title"],
            url=f"{clean_base}/wiki/spaces/{space_key}/pages/{p['id']}",
            version=p["version"]["number"],
        )
        for p in results
    ]


def fetch_page_content(page_id: str) -> str:
    """
    Fetch the full body of a Confluence page and convert it back to *approximate* Markdown.
    Kept for backward compatibility with the semantic relevance scorer.
    For structural updates, prefer fetch_page_as_storage_xml().
    """
    import html as _html

    base_url, space_key, client = _get_client()
    with client:
        response = client.get(
            f"{base_url}/rest/api/content/{page_id}",
            params={"expand": "body.storage"},
        )
        response.raise_for_status()
        data = response.json()

    raw_html = data.get("body", {}).get("storage", {}).get("value", "")
    if not raw_html:
        return ""

    # 1. Extract code blocks safely
    code_blocks = []
    def repl_code(m):
        code = m.group(1).strip()
        code_blocks.append(f"```\n{code}\n```")
        return f"__CODE_BLOCK_{len(code_blocks)-1}__"

    raw_html = re.sub(
        r'<ac:structured-macro[^>]+ac:name="code"[^>]*>.*?<ac:plain-text-body><!\[CDATA\[(.*?)\]\]></ac:plain-text-body>.*?</ac:structured-macro>',
        repl_code, raw_html, flags=re.DOTALL | re.IGNORECASE
    )

    # 2. Convert Headers
    for i in range(1, 7):
        raw_html = re.sub(
            f'<h{i}[^>]*>(.*?)</h{i}>',
            f'\n\n{"#" * i} \\1\n\n',
            raw_html, flags=re.IGNORECASE | re.DOTALL
        )

    # 3. Paragraphs & line breaks
    raw_html = re.sub(r'<p[^>]*>(.*?)</p>', r'\n\n\1\n\n', raw_html, flags=re.IGNORECASE | re.DOTALL)
    raw_html = re.sub(r'<br\s*/?>', r'\n', raw_html, flags=re.IGNORECASE)

    # 4. Lists
    raw_html = re.sub(r'<li[^>]*>(.*?)</li>', r'\n- \1', raw_html, flags=re.IGNORECASE | re.DOTALL)

    # 5. Basic formatting
    raw_html = re.sub(r'<strong[^>]*>(.*?)</strong>', r'**\1**', raw_html, flags=re.IGNORECASE | re.DOTALL)
    raw_html = re.sub(r'<em[^>]*>(.*?)</em>', r'*\1*', raw_html, flags=re.IGNORECASE | re.DOTALL)
    raw_html = re.sub(r'<code[^>]*>(.*?)</code>', r'`\1`', raw_html, flags=re.IGNORECASE | re.DOTALL)

    # 6. Strip remaining HTML
    markdown = re.sub(r"<[^>]+>", "", raw_html)
    markdown = _html.unescape(markdown)

    # 7. Restore code blocks
    for i, block in enumerate(code_blocks):
        markdown = markdown.replace(f"__CODE_BLOCK_{i}__", block)

    # 8. Clean up excessive newlines
    markdown = re.sub(r'\n{3,}', '\n\n', markdown)

    return markdown.strip()


def fetch_page_as_storage_xml(page_id: str) -> tuple[str, int]:
    """
    [NEW — Pillar 3] Fetch the raw Confluence Storage Format XML for a page.

    Returns (storage_xml: str, current_version: int).

    This is used by the new section-level updater to parse the document
    structure, find specific heading nodes, and replace them without
    a lossy Markdown round-trip.
    """
    base_url, space_key, client = _get_client()
    with client:
        response = client.get(
            f"{base_url}/rest/api/content/{page_id}",
            params={"expand": "body.storage,version"},
        )
        response.raise_for_status()
        data = response.json()

    storage_xml = data.get("body", {}).get("storage", {}).get("value", "")
    version     = data.get("version", {}).get("number", 1)
    return storage_xml, version


def fetch_all_page_titles(space_key: str = "") -> list[dict]:
    """
    [NEW — Pillar 2] Fetch EVERY page title in the Confluence space (paginated).

    Returns a list of dicts: [{"page_id": str, "title": str}, ...]
    Used by the Intent-Aware Page Router Agent to give the LLM full visibility
    of what pages exist before deciding which ones need updating.
    """
    base_url, default_space, client = _get_client()
    space = space_key or default_space
    clean_base = _clean_base_url(base_url)

    pages = []
    start = 0
    limit = 50

    with client:
        while True:
            response = client.get(
                f"{base_url}/rest/api/content",
                params={
                    "spaceKey": space,
                    "type": "page",
                    "limit": limit,
                    "start": start,
                    "expand": "version",
                },
            )
            response.raise_for_status()
            data    = response.json()
            results = data.get("results", [])

            for p in results:
                pages.append({
                    "page_id": p["id"],
                    "title":   p["title"],
                    "url":     f"{clean_base}/wiki/spaces/{space}/pages/{p['id']}",
                    "version": p["version"]["number"],
                })

            # Confluence paginates — stop when we get fewer results than requested
            if len(results) < limit:
                break
            start += limit

    return pages


# ---------------------------------------------------------------------------
# Public API — Write operations
# ---------------------------------------------------------------------------

def create_page(title: str, body_markdown: str, space_key: str = "", parent_title: str = "") -> ConfluencePage:
    """
    Create a new Confluence page.
    body_markdown is converted to Confluence Storage Format via markdown2.
    Optional parent_title places the page as a child of an existing page.
    """
    base_url, default_space, client = _get_client()
    space        = space_key or default_space
    storage_body = _markdown_to_storage(body_markdown)

    payload = {
        "type":  "page",
        "title": title,
        "space": {"key": space},
        "body":  {
            "storage": {
                "value":          storage_body,
                "representation": "storage",
            }
        },
    }

    if parent_title:
        parent = get_page_by_title(parent_title)
        if parent:
            payload["ancestors"] = [{"id": parent.page_id}]

    with client:
        response = client.post(f"{base_url}/rest/api/content", json=payload)
        response.raise_for_status()
        data = response.json()

    clean_base = _clean_base_url(base_url)
    return ConfluencePage(
        page_id=data["id"],
        title=data["title"],
        url=f"{clean_base}/wiki/spaces/{space}/pages/{data['id']}",
        version=data["version"]["number"],
    )


def update_page(
    page_id: str,
    title: str,
    body_markdown: str,
    current_version: int,
    raw_storage_xml: str = "",
) -> ConfluencePage:
    """
    Update an existing Confluence page.

    If raw_storage_xml is provided, it is used directly (for Pillar 3
    section-level updates that work with the native XML). Otherwise,
    body_markdown is converted via markdown2.

    Confluence requires version number to be incremented on every update.
    """
    base_url, space_key, client = _get_client()

    if raw_storage_xml:
        storage_body = raw_storage_xml
    else:
        storage_body = _markdown_to_storage(body_markdown)

    payload = {
        "type":    "page",
        "title":   title,
        "version": {"number": current_version + 1},
        "body":    {
            "storage": {
                "value":          storage_body,
                "representation": "storage",
            }
        },
    }

    with client:
        response = client.put(f"{base_url}/rest/api/content/{page_id}", json=payload)
        response.raise_for_status()
        data = response.json()

    clean_base = _clean_base_url(base_url)
    return ConfluencePage(
        page_id=data["id"],
        title=data["title"],
        url=f"{clean_base}/wiki/spaces/{space_key}/pages/{data['id']}",
        version=data["version"]["number"],
    )


def create_or_update_page(
    title: str,
    body_markdown: str,
    space_key: str = "",
    parent_title: str = "",
) -> dict:
    """
    Convenience function: creates or updates a page by title.
    Returns a plain dict: {page_id, title, url, version}.
    """
    existing = get_page_by_title(title)
    if existing:
        page = update_page(existing.page_id, title, body_markdown, existing.version)
    else:
        page = create_page(title, body_markdown, space_key=space_key, parent_title=parent_title)
    return {"page_id": page.page_id, "title": page.title, "url": page.url, "version": page.version}
