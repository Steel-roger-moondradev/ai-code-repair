"""The single shared state contract for PatchPilot workflows."""

from typing import TypedDict

from app.schemas.github import IssueData
from app.schemas.workflow import WorkflowStatus


class PatchPilotState(TypedDict, total=False):
    """Partial state updates exchanged by workflow nodes."""

    owner: str
    repo: str
    issue_number: int
    issue: IssueData | None
    analysis: dict | None
    repository_tree: list[str]
    search_results: list[dict]
    relevant_files: list[dict]
    proposal: dict | None
    validation: dict | None
    diff: dict | None
    sandbox_result: dict | None
    review: dict | None
    workflow_id: str
    status: WorkflowStatus
    repair_attempts: int
    errors: list[str]
