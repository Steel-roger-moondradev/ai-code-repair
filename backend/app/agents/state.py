"""The single shared state contract for PatchPilot workflows."""

from typing import TypedDict

from app.schemas.analysis import IssueAnalysis
from app.schemas.github import IssueData
from app.schemas.patch import DiffResult, PatchProposal, PatchValidationResult
from app.schemas.sandbox import SandboxResult
from app.schemas.workflow import WorkflowStatus


class PatchPilotState(TypedDict, total=False):
    """Partial state updates exchanged by workflow nodes."""

    owner: str
    repo: str
    issue_number: int
    issue: IssueData | None
    analysis: IssueAnalysis | None
    repository_tree: list[str]
    search_results: list[dict]
    relevant_files: list[dict]
    proposal: PatchProposal | None
    validation: PatchValidationResult | None
    diff: DiffResult | None
    sandbox_result: SandboxResult | None
    review: dict | None
    workflow_id: str
    status: WorkflowStatus
    repair_attempts: int
    errors: list[str]
