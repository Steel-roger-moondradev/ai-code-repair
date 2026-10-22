"""Workflow request, response, status, and transition contracts."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.github import IssueData


class WorkflowStatus(StrEnum):
    """Canonical workflow statuses."""

    QUEUED = "queued"
    RUNNING = "running"
    PATCH_READY = "patch_ready"
    TESTING = "testing"
    NEEDS_HUMAN_REVIEW = "needs_human_review"
    APPROVED = "approved"
    PR_CREATED = "pr_created"
    FAILED = "failed"
    REJECTED = "rejected"


_ALLOWED_TRANSITIONS: dict[WorkflowStatus, frozenset[WorkflowStatus]] = {
    WorkflowStatus.QUEUED: frozenset({WorkflowStatus.RUNNING, WorkflowStatus.FAILED}),
    WorkflowStatus.RUNNING: frozenset({WorkflowStatus.FAILED}),
    WorkflowStatus.PATCH_READY: frozenset({WorkflowStatus.TESTING, WorkflowStatus.NEEDS_HUMAN_REVIEW}),
    WorkflowStatus.TESTING: frozenset({WorkflowStatus.PATCH_READY, WorkflowStatus.FAILED}),
    WorkflowStatus.NEEDS_HUMAN_REVIEW: frozenset({WorkflowStatus.APPROVED, WorkflowStatus.REJECTED}),
    WorkflowStatus.APPROVED: frozenset({WorkflowStatus.PR_CREATED}),
    WorkflowStatus.PR_CREATED: frozenset(),
    WorkflowStatus.FAILED: frozenset(),
    WorkflowStatus.REJECTED: frozenset(),
}


def transition_status(current: WorkflowStatus, target: WorkflowStatus) -> WorkflowStatus:
    """Return a valid target status or reject the transition."""

    if target not in _ALLOWED_TRANSITIONS[current]:
        raise ValueError(f"invalid workflow status transition: {current} -> {target}")
    return target


class WorkflowRequest(BaseModel):
    """Public request contract for the Day 5 issue-analysis workflow."""

    model_config = ConfigDict(extra="forbid")

    issue_url: str = Field(min_length=1)


class WorkflowResponse(BaseModel):
    """Stable response shape across workflow success and failure."""

    model_config = ConfigDict(extra="forbid")

    workflow_id: str
    status: WorkflowStatus
    issue: IssueData | None = None
    analysis: dict[str, Any] | None = None
    relevant_files: list[dict[str, Any]] = Field(default_factory=list)
    proposal: dict[str, Any] | None = None
    validation: dict[str, Any] | None = None
    diff: dict[str, Any] | None = None
    sandbox_result: dict[str, Any] | None = None
    review: dict[str, Any] | None = None
    errors: list[str] = Field(default_factory=list)
