"""
Airia Client — Phase 2 (complete implementation)
Calls Airia AI pipeline endpoints via REST API.

Endpoint: POST /v1/PipelineExecution/{pipelineId}
Auth:      X-API-Key header
Docs:      https://api.airia.ai/docs
"""

import os
import httpx
from typing import Any
from dotenv import load_dotenv

load_dotenv()


def run_pipeline(pipeline_id: str, user_input: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Invoke an Airia pipeline by ID with the given user input.

    Args:
        pipeline_id: The pipeline GUID from Airia (e.g. AIRIA_CODE_ANALYSIS_PIPELINE_ID)
        user_input:  The main text prompt / message sent to the pipeline
        variables:   Optional dict of extra variables the pipeline may expect

    Requires in .env:
        AIRIA_API_BASE_URL  — e.g. https://api.airia.ai
        AIRIA_API_KEY       — your Airia API key

    Returns:
        dict with the pipeline result. Key fields:
          - "result"  : the main text output from the pipeline
          - "outputs" : list of all output nodes (raw)
          - full raw response dict for debugging

    Raises:
        httpx.HTTPStatusError on non-2xx responses.
    """
    base_url = os.getenv("AIRIA_API_BASE_URL", "https://api.airia.ai").rstrip("/")
    api_key  = os.getenv("AIRIA_API_KEY", "")

    if not api_key:
        raise ValueError("AIRIA_API_KEY must be set in .env")

    url = f"{base_url}/v1/PipelineExecution/{pipeline_id}"

    payload: dict[str, Any] = {
        "UserInput": user_input,       # PascalCase — confirmed by Airia validation error
        "asyncOutput": False,          # synchronous — wait for result
    }
    if variables:
        payload["variables"] = variables

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-API-Key": api_key,
    }

    with httpx.Client(timeout=60) as client:
        response = client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()

    # Normalise: pull the most useful text output to a top-level "result" key
    result_text = (
        data.get("result")
        or data.get("output")
        or data.get("message")
        or ""
    )

    # Some pipelines return outputs as a list of nodes
    outputs = data.get("outputs", [])
    if not result_text and outputs:
        result_text = outputs[0].get("value", "") if isinstance(outputs[0], dict) else str(outputs[0])

    return {
        "result": result_text,
        "outputs": outputs,
        "_raw": data,
    }


def run_pipeline_with_files(
    pipeline_id: str,
    user_input: str,
    files: list[tuple[str, bytes, str]],   # list of (filename, content_bytes, mime_type)
) -> dict[str, Any]:
    """
    Invoke an Airia pipeline using the Multipart endpoint.
    This allows sending actual files (PDFs, Markdown docs, diff files, etc.)
    directly to the LLM instead of embedding them as text strings.

    Endpoint: POST /v1/PipelineExecution/Multipart/{pipelineId}
    Content-Type: multipart/form-data

    Args:
        pipeline_id: The pipeline GUID from Airia
        user_input:  The instruction (e.g. "Update the docs based on the diff")
        files:       List of (filename, bytes_content, mime_type) tuples
                     Supported types: .md, .txt, .pdf, .json, .csv, .docx, .diff
                     Example: [("changes.md", b"# Doc content", "text/markdown"),
                               ("pr.diff",   diff_bytes,       "text/plain")]

    Returns:
        Same dict as run_pipeline(): {"result": str, "outputs": list, "_raw": dict}
    """
    base_url = os.getenv("AIRIA_API_BASE_URL", "https://api.airia.ai").rstrip("/")
    api_key  = os.getenv("AIRIA_API_KEY", "")

    if not api_key:
        raise ValueError("AIRIA_API_KEY must be set in .env")

    url = f"{base_url}/v1/PipelineExecution/Multipart/{pipeline_id}"

    headers = {
        "Accept": "application/json",
        "X-API-Key": api_key,
        # NOTE: Do NOT set Content-Type — httpx sets it automatically with the boundary
    }

    # Build multipart form data
    # Airia Multipart schema: FileAttachment (binary, per file) + UserInput (text)
    multipart_files = []
    for filename, content_bytes, mime_type in files:
        multipart_files.append(
            ("FileAttachment", (filename, content_bytes, mime_type))
        )

    form_data = {"UserInput": user_input}

    with httpx.Client(timeout=120) as client:
        response = client.post(url, files=multipart_files, data=form_data, headers=headers)
        response.raise_for_status()
        data = response.json()

    # Normalise response (same as run_pipeline)
    result_text = (
        data.get("result")
        or data.get("output")
        or data.get("message")
        or ""
    )
    outputs = data.get("outputs", [])
    if not result_text and outputs:
        result_text = outputs[0].get("value", "") if isinstance(outputs[0], dict) else str(outputs[0])

    return {
        "result": result_text,
        "outputs": outputs,
        "_raw": data,
    }

