import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from main import app
from agents.staging_store import stage_pending_doc_update, peek_staged_updates, clear_staged_updates

client = TestClient(app)

TEST_PR_NUMBER = 9999

@pytest.fixture(autouse=True)
def clean_staging_store():
    """Ensure a clean staging store state before and after each test."""
    clear_staged_updates(TEST_PR_NUMBER)
    yield
    clear_staged_updates(TEST_PR_NUMBER)

def test_preview_endpoint_with_staged_docs():
    """Test that the /preview endpoint correctly renders staged updates as HTML."""
    stage_pending_doc_update(TEST_PR_NUMBER, "create_or_update_page", {
        "title": "Pytest Preview Doc",
        "body_markdown": "# Pytest Content"
    })
    
    response = client.get(f"/preview/{TEST_PR_NUMBER}")
    assert response.status_code == 200
    
    # Check that HTML is returned and contains our stub data
    assert "text/html" in response.headers["content-type"]
    assert "Pytest Preview Doc" in response.text
    assert "Pytest Content" in response.text

def test_preview_endpoint_empty():
    """Test that the /preview endpoint handles empty stores gracefully."""
    response = client.get(f"/preview/{TEST_PR_NUMBER}")
    assert response.status_code == 200
    assert "No pending updates found" in response.text

@patch("integrations.slack_client.send_message")
def test_reject_endpoint(mock_send_message):
    """Test that /reject appropriately drops staged docs and pings Slack."""
    stage_pending_doc_update(TEST_PR_NUMBER, "create_or_update_page", {"title": "Delete Me"})
    
    assert len(peek_staged_updates(TEST_PR_NUMBER)) == 1
    
    response = client.get(f"/reject/{TEST_PR_NUMBER}")
    assert response.status_code == 200
    assert "Changes Rejected" in response.text
    
    # Verify Slack was notified about the rejection
    mock_send_message.assert_called_once()
    assert "Rejected" in mock_send_message.call_args[0][0]
    
    # Verify the staging JSON is fully cleared
    assert len(peek_staged_updates(TEST_PR_NUMBER)) == 0

@patch("integrations.confluence_client.update_page")
@patch("integrations.confluence_client.create_or_update_page")
@patch("integrations.slack_client.send_message")
def test_approve_endpoint(mock_send_message, mock_create, mock_update):
    """Test that /approve commits changes to Confluence without making real API calls."""
    # We stage two actions to ensure it loops and processes both
    stage_pending_doc_update(TEST_PR_NUMBER, "create_or_update_page", {
        "title": "New Pytest Doc",
        "body_markdown": "Docs Content"
    })
    stage_pending_doc_update(TEST_PR_NUMBER, "update_page", {
        "page_id": "12345",
        "title": "Existing Pytest Doc",
        "body_markdown": "Updated Data",
        "current_version": 2
    })
    
    response = client.get(f"/approve/{TEST_PR_NUMBER}")
    assert response.status_code == 200
    assert "Approval Successful" in response.text
    
    # Verify the mocked Confluence endpoints were triggered with exactly the saved kwargs
    mock_create.assert_called_once_with(title="New Pytest Doc", body_markdown="Docs Content")
    mock_update.assert_called_once_with(page_id="12345", title="Existing Pytest Doc", body_markdown="Updated Data", current_version=2)
    
    # Verify Slack was notified
    mock_send_message.assert_called_once()
    assert "Approved" in mock_send_message.call_args[0][0]
    assert "2" in mock_send_message.call_args[0][0] # Should say "2 Confluence pages"
    
    # Verify the staging store was cleared by pop_staged_updates
    assert len(peek_staged_updates(TEST_PR_NUMBER)) == 0
