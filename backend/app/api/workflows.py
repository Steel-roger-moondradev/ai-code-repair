"""Workflow API routes."""

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.api.github import get_github_client
from app.agents.issue_workflow import build_issue_workflow, initial_state
from app.config import Settings, get_settings
from app.schemas.workflow import WorkflowRequest, WorkflowResponse, WorkflowStatus
from app.services.github import GitHubClient, GitHubServiceError
from app.services.github import parse_issue_url
from app.services.llm import GroqLLMAdapter
from app.services.sandbox import SandboxService
from app.services.persistence import PersistenceError, PersistenceService
from app.services.pull_requests import (
    ApprovalRequest,
    GitHubPullRequestWriter,
    PullRequestResult,
    PullRequestService,
)
from app.services.observability import log_stage
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


def get_sandbox_service(settings: Settings = Depends(get_settings)) -> SandboxService:
    """Create the disposable sandbox service at request time."""

    return SandboxService(settings)


def get_persistence_service(settings: Settings = Depends(get_settings)) -> PersistenceService:
    """Create a request-scoped persistence service."""

    return PersistenceService(settings)


def get_pull_request_service(
    settings: Settings = Depends(get_settings),
    persistence: PersistenceService = Depends(get_persistence_service),
) -> PullRequestService:
    """Create the exact-patch publication service at request time."""

    return PullRequestService(persistence, GitHubPullRequestWriter(settings))


@router.post("", response_model=WorkflowResponse)
@router.post("/issue-analysis", response_model=WorkflowResponse, include_in_schema=False)
async def issue_analysis(
    request: WorkflowRequest,
    http_request: Request,
    response: Response,
    github_client: GitHubClient = Depends(get_github_client),
    llm: GroqLLMAdapter = Depends(get_llm_adapter),
    tool_registry: ToolRegistry = Depends(get_repository_tool_registry),
    settings: Settings = Depends(get_settings),
    sandbox_service: SandboxService = Depends(get_sandbox_service),
    persistence: PersistenceService = Depends(get_persistence_service),
) -> WorkflowResponse:
    """Analyze an issue, validate a patch, and test it in an isolated sandbox."""

    try:
        reference = parse_issue_url(request.issue_url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    request_id = http_request.headers.get("x-request-id") or str(uuid4())
    response.headers["X-Request-ID"] = request_id
    workflow_id = str(uuid4())
    existing = (
        persistence.find_by_idempotency_key(request.idempotency_key)
        if request.idempotency_key
        else None
    )
    if existing is not None:
        return WorkflowResponse(
            workflow_id=existing["workflow_id"],
            request_id=request_id,
            status=existing["status"],
            errors=["idempotent_replay"],
        )
    try:
        persistence.create_run(
            workflow_id,
            reference.owner,
            reference.repo,
            reference.issue_number,
            idempotency_key=request.idempotency_key,
        )
    except PersistenceError as exc:
        raise HTTPException(status_code=503, detail="workflow persistence unavailable") from exc
    persistence.update_status(workflow_id, WorkflowStatus.RUNNING, stage="fetch_issue")
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
        sandbox_service=sandbox_service,
    )
    result = await graph.ainvoke(state)
    final_status = result["status"]
    if final_status in {WorkflowStatus.NEEDS_HUMAN_REVIEW, WorkflowStatus.REJECTED}:
        persistence.update_status(
            workflow_id,
            WorkflowStatus.PATCH_READY,
            patch_hash=result.get("validation").patch_hash
            if result.get("validation")
            else None,
            stage="patch_ready",
        )
    persistence.update_status(
        workflow_id,
        final_status,
        patch_hash=result.get("validation").patch_hash if result.get("validation") else None,
        stage="workflow_complete",
    )
    log_stage(
        workflow_id=workflow_id,
        node="workflow",
        status=final_status.value,
        error_category=(result.get("errors") or [None])[0],
    )
    for artifact_type in ("proposal", "validation", "diff", "sandbox_result", "review"):
        artifact = result.get(artifact_type)
        if artifact is not None:
            persistence.save_artifact(
                workflow_id,
                artifact_type,
                artifact,
                patch_hash=result.get("validation").patch_hash
                if result.get("validation")
                else None,
            )
    return WorkflowResponse(
        workflow_id=workflow_id,
        request_id=request_id,
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


@router.post("/{workflow_id}/approve", response_model=PullRequestResult)
def approve_workflow(
    workflow_id: str,
    request: ApprovalRequest,
    service: PullRequestService = Depends(get_pull_request_service),
) -> PullRequestResult:
    if request.workflow_id != workflow_id:
        raise HTTPException(status_code=422, detail="workflow ID does not match approval path")
    try:
        return service.approve_and_publish(request)
    except PersistenceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except GitHubServiceError as exc:
        raise HTTPException(status_code=502, detail=f"{exc.category}: {exc}") from exc


@router.get("/{workflow_id}/proposal")
def get_workflow_proposal(
    workflow_id: str,
    persistence: PersistenceService = Depends(get_persistence_service),
) -> dict:
    return _get_artifact_response(workflow_id, "proposal", persistence)


@router.get("/{workflow_id}/results")
def get_workflow_results(
    workflow_id: str,
    persistence: PersistenceService = Depends(get_persistence_service),
) -> dict:
    try:
        run = persistence.get_run(workflow_id)
    except PersistenceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "workflow_id": workflow_id,
        "status": run["status"],
        "artifacts": [
            artifact
            for artifact in run["artifacts"]
            if artifact["type"] in {"diff", "sandbox_result", "review"}
        ],
    }


@router.get("/{workflow_id}")
def get_workflow(
    workflow_id: str,
    persistence: PersistenceService = Depends(get_persistence_service),
) -> dict:
    try:
        return persistence.get_run(workflow_id)
    except PersistenceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("")
def list_workflows(
    page: int = 1,
    page_size: int = 20,
    persistence: PersistenceService = Depends(get_persistence_service),
) -> dict:
    try:
        return persistence.list_runs(page=page, page_size=page_size)
    except PersistenceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _get_artifact_response(
    workflow_id: str,
    artifact_type: str,
    persistence: PersistenceService,
) -> dict:
    try:
        run = persistence.get_run(workflow_id)
    except PersistenceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    for artifact in reversed(run["artifacts"]):
        if artifact["type"] == artifact_type:
            return {"workflow_id": workflow_id, "artifact": artifact}
    raise HTTPException(status_code=404, detail=f"{artifact_type} artifact not found")
