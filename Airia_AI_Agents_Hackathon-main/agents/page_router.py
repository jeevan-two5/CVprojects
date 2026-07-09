"""
Page Router — Phase 7 (13-Case Architecture)

Now a thin adapter: delegates all classification to pr_classifier.py
and resolves ConfluencePage objects for targets that have page_ids.

The heavy lifting (Stage 1 deterministic + Stage 2 LLM) is entirely
inside pr_classifier.ClassificationResult.
"""

import os
from integrations.confluence_client import get_page_by_title, ConfluencePage
from integrations.github_handler import PREvent
from agents.pr_classifier import classify_pr, ClassificationResult, RoutingTarget


def route_pr_to_pages(pr_event: PREvent, analysis: dict) -> ClassificationResult:
    """
    Classify the PR and resolve every RoutingTarget to a full ConfluencePage object.

    Returns the ClassificationResult with each RoutingTarget's page_id, page_url,
    and page_version populated (by looking up via Confluence API where not already
    resolved by the classifier's catalogue lookup).
    """
    result = classify_pr(pr_event, analysis)

    # Resolve any targets that didn't get a page_id from the catalogue
    resolved_targets = []
    for target in result.targets:
        if not target.page_id and target.page_title:
            page = get_page_by_title(target.page_title)
            if page:
                target.page_id      = page.page_id
                target.page_url     = page.url
                target.page_version = page.version
            else:
                print(f"[Router] Could not resolve page '{target.page_title}' — will skip.")
                continue
        resolved_targets.append(target)

    result.targets = resolved_targets
    return result
