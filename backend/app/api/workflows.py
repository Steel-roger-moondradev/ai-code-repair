"""Workflow API routes."""

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException

from app.api.github import get_github_client
from app.agents.issue_workflow import build_issue_workflow, initial_state
from app.schemas.workflow import WorkflowRequest, WorkflowResponse
from app.services.github import GitHubClient
from app.services.github import parse_issue_url

router = APIRouter(prefix="/api/v1/workflows", tags=["workflows"])


@router.post("/issue-analysis", response_model=WorkflowResponse)
async def issue_analysis(
    request: WorkflowRequest,
    github_client: GitHubClient = Depends(get_github_client),
) -> WorkflowResponse:
    """Fetch and normalize a GitHub issue through the minimal workflow."""

    try:
        reference = parse_issue_url(request.issue_url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    workflow_id = str(uuid4())
    state = initial_state(
        owner=reference.owner,
        repo=reference.repo,
        issue_number=reference.issue_number,
        workflow_id=workflow_id,
    )
    graph = build_issue_workflow(github_client)
    result = await graph.ainvoke(state)
    return WorkflowResponse(
        workflow_id=workflow_id,
        status=result["status"],
        issue=result.get("issue"),
        errors=result.get("errors", []),
    )
