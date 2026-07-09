"""
Phase 2 Tests: Confluence Client
- Unit tests for markdown-to-storage converter (no credentials needed)
- Live tests: create a page, verify it, update it, check version bumped
  (requires CONFLUENCE_* credentials in .env)
"""

import os
import sys
import pytest
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integrations.confluence_client import (
    ConfluencePage,
    _markdown_to_storage,
    get_page_by_title,
    create_page,
    update_page,
    create_or_update_page,
)

# ---------------------------------------------------------------------------
# Credentials check
# ---------------------------------------------------------------------------

_has_creds = all([
    os.getenv("CONFLUENCE_BASE_URL"),
    os.getenv("CONFLUENCE_EMAIL"),
    os.getenv("CONFLUENCE_API_TOKEN"),
    os.getenv("CONFLUENCE_SPACE_KEY"),
])
_skip_msg = "Set CONFLUENCE_BASE_URL, CONFLUENCE_EMAIL, CONFLUENCE_API_TOKEN, CONFLUENCE_SPACE_KEY in .env"

# Shared state across live tests — filled by test_create_page_live
_created_page: ConfluencePage | None = None


# ---------------------------------------------------------------------------
# Unit tests: Markdown → Confluence Storage Format converter
# ---------------------------------------------------------------------------

def test_markdown_h1():
    result = _markdown_to_storage("# Hello")
    assert '<h1 id="hello">Hello</h1>' in result


def test_markdown_h2():
    result = _markdown_to_storage("## Section")
    assert '<h2 id="section">Section</h2>' in result


def test_markdown_paragraph():
    result = _markdown_to_storage("This is a paragraph.")
    assert "This is a paragraph." in result


def test_markdown_code_block():
    result = _markdown_to_storage("```\nprint('hello')\n```")
    assert "ac:structured-macro" in result
    assert "print" in result


def test_markdown_multiblock():
    result = _markdown_to_storage("# Title\n\nSome text.\n\n## Sub")
    assert '<h1 id="title">Title</h1>' in result
    assert "Some text." in result
    assert '<h2 id="sub">Sub</h2>' in result


# ---------------------------------------------------------------------------
# Live tests: create → get → update cycle
# ---------------------------------------------------------------------------

TEST_PAGE_TITLE = "[DocuSync AI] Phase 2 Smoke Test Page"
TEST_BODY_V1 = "# DocuSync Test\n\nThis page was auto-created by DocuSync AI smoke test."
TEST_BODY_V2 = "# DocuSync Test\n\nThis page was **updated** by DocuSync AI smoke test (v2)."


@pytest.mark.skipif(not _has_creds, reason=_skip_msg)
def test_create_page_live():
    """Create a test page in Confluence."""
    global _created_page
    # If page already exists (re-running tests), use create_or_update_page
    page = create_or_update_page(TEST_PAGE_TITLE, TEST_BODY_V1)
    _created_page = page
    print(f"\n[OK] Page created/updated: {page.get('title')} | ID: {page.get('page_id')} | URL: {page.get('url')}")
    assert isinstance(page, dict)
    assert page.get("page_id") != ""
    assert page.get("url") != ""


@pytest.mark.skipif(not _has_creds, reason=_skip_msg)
def test_get_page_by_title_live():
    """Find the page we just created by its title."""
    page = get_page_by_title(TEST_PAGE_TITLE)
    assert page is not None, f"Expected to find page titled '{TEST_PAGE_TITLE}'"
    assert page.title == TEST_PAGE_TITLE
    print(f"\n[OK] Found page: {page.title} | Version: {page.version}")


@pytest.mark.skipif(not _has_creds, reason=_skip_msg)
def test_update_page_live():
    """Update the page and verify the version number incremented."""
    page = get_page_by_title(TEST_PAGE_TITLE)
    assert page is not None
    old_version = page.version

    updated = update_page(page.page_id, TEST_PAGE_TITLE, TEST_BODY_V2, old_version)
    print(f"\n[OK] Updated page: {updated.title} | Old version: {old_version} | New version: {updated.version}")
    assert updated.version == old_version + 1


@pytest.mark.skipif(not _has_creds, reason=_skip_msg)
def test_get_page_nonexistent():
    """Looking up a page that does not exist should return None gracefully."""
    result = get_page_by_title("__THIS_PAGE_SHOULD_NOT_EXIST_DOCUSYNC__")
    assert result is None
