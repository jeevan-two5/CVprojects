import os
import json
from integrations.github_handler import PREvent
from agents.pr_classifier import classify_pr

# Mock a PR event that adds a new endpoint
mock_pr_event = PREvent(
    pr_number=101,
    pr_title="feat(users): add invite user endpoint",
    pr_body="This PR adds a new endpoint to invite users to a workspace.",
    head_sha="abcdef123456",
    base_branch="main",
    head_branch="feat/invite-user",
    repo_full_name="myorg/backend",
    changed_files=["src/routes/users.py", "src/services/email.py"],
    pr_diff='''
+++ b/src/routes/users.py
@@ -10,0 +11,5 @@
+@router.post("/users/invite")
+async def invite_user(email: str):
+    """Invite a user to the workspace."""
+    return {"status": "invited", "email": email}
''',
    jira_issue_key="PAY-21"
)

# Mock Airia analysis
mock_analysis = {
    "summary": "Added a new POST endpoint at /users/invite to handle user invitations. Includes email sending logic.",
    "impact": "Expands user service API. May increase email volume.",
    "risk": "Low. Endpoint is appropriately shielded."
}

# Run the classifier!
print("--- Running Classifier Test ---")
result = classify_pr(mock_pr_event, mock_analysis)

print("\n--- Final Output ---")
dump = {
    "case": result.case,
    "case_label": result.case_label,
    "confidence": result.confidence,
    "reasoning": result.reasoning,
    "slack_alert_level": result.slack_alert_level,
    "requires_human_approval": result.requires_human_approval,
    "targets": [
        {
            "page_title": t.page_title,
            "strategy": t.strategy,
            "section_hint": t.section_hint,
            "reason": t.reason
        }
        for t in result.targets
    ]
}

print(json.dumps(dump, indent=2))
