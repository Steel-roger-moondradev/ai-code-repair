"""Workflow API routes."""

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException

from app.api.github import get_github_client
from app.agents.issue_workflow import build_issue_workflow, initial_state
from app.config import Settings, get_settings
from app.schemas.workflow import WorkflowRequest, WorkflowResponse
from app.services.github import GitHubClient
from app.services.github import parse_issue_url
from app.services.llm import GroqLLMAdapter
from app.tools.registry import ToolRegistry, build_repository_tool_registry

router = APIRouter(prefix="/api/v1/workflows", tags=["workflows"])


def get_llm_adapter(settings: Settings = Depends(get_settings)) -> GroqLLMAdapter:
    """Create the provider adapter lazily at request time."""

    return GroqLLMAdapter(settings)


def get_repository_tool_registry(
    settings: Settings = Depends(get_settings),
) -> ToolRegistry:
    """Create the explicit repository-tool registry at request time."""

    return build_repository_tool_registry(settings)


@router.post("/issue-analysis", response_model=WorkflowResponse)
async def issue_analysis(
    request: WorkflowRequest,
    github_client: GitHubClient = Depends(get_github_client),
    llm: GroqLLMAdapter = Depends(get_llm_adapter),
    tool_registry: ToolRegistry = Depends(get_repository_tool_registry),
    settings: Settings = Depends(get_settings),
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
    graph = build_issue_workflow(
        github_client,
        llm=llm,
        tool_registry=tool_registry,
        settings=settings,
    )
    result = await graph.ainvoke(state)
    return WorkflowResponse(
        workflow_id=workflow_id,
        status=result["status"],
        issue=result.get("issue"),
        analysis=result.get("analysis"),
        relevant_files=result.get("relevant_files", []),
        proposal=result.get("proposal"),
        validation=result.get("validation"),
        diff=result.get("diff"),
        sandbox_result=result.get("sandbox_result"),
        review=result.get("review"),
        errors=result.get("errors", []),
    )
