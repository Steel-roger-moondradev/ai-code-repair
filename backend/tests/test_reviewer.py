"""Offline tests for evidence-based review and bounded repair behavior."""

import pytest

from app.agents.reviewer import reviewer_node
from app.agents.issue_workflow import initial_state
from app.schemas.analysis import IssueAnalysis
from app.schemas.github import IssueData
from app.schemas.patch import DiffResult
from app.schemas.review import ReviewerResult
from app.schemas.sandbox import SandboxResult
from app.schemas.workflow import WorkflowStatus
from app.services.llm import LLMResponse


def review_state(status=WorkflowStatus.PATCH_READY, sandbox_status="passed"):
    state = initial_state(owner="octo", repo="repo", issue_number=1, workflow_id="wf")
    state.update(
        {
            "status": status,
            "issue": IssueData(
                owner="octo",
                repo="repo",
                issue_number=1,
                title="Fix",
                body="Make it work",
                state="open",
                html_url="https://github.com/octo/repo/issues/1",
                labels=[],
                comments=[],
            ),
            "analysis": IssueAnalysis(
                summary="Fix",
                problem_type="bug",
                expected_behavior="Works",
                acceptance_criteria=["Works"],
                constraints=[],
                keywords=["work"],
                confidence=0.9,
                needs_clarification=False,
            ),
            "diff": DiffResult(
                patch_hash="hash",
                diff_text="diff",
                changed_files=["main.py"],
                additions=1,
                deletions=1,
            ),
            "sandbox_result": SandboxResult(
                status=sandbox_status,
                exit_code=0 if sandbox_status == "passed" else 1,
                stdout="1 passed" if sandbox_status == "passed" else "",
                stderr="",
                duration_ms=1,
                timed_out=sandbox_status == "timed_out",
                test_summary="1 passed",
                error=None if sandbox_status == "passed" else "failed",
            ),
        }
    )
    return state


class FakeLLM:
    def __init__(self, payload):
        self.payload = payload

    async def complete(self, **kwargs):
        return LLMResponse(text=self.payload, usage={})


def payload(verdict: str) -> str:
    return (
        '{"verdict":"' + verdict + '","correctness_concerns":[],"security_concerns":[],'
        '"maintainability_notes":[],"test_coverage_notes":[],"evidence":["exit code 0"],'
        '"summary":"reviewed"}'
    )


@pytest.mark.asyncio
async def test_passing_sandbox_can_be_approved() -> None:
    result = await reviewer_node(
        review_state(),
        FakeLLM(payload("approved")),
    )

    assert result["review"] == ReviewerResult.model_validate_json(payload("approved"))
    assert result["status"] == WorkflowStatus.PATCH_READY


@pytest.mark.asyncio
async def test_failed_sandbox_cannot_be_reviewed_as_approved() -> None:
    result = await reviewer_node(
        review_state(sandbox_status="failed"),
        FakeLLM(payload("approved")),
    )

    assert result["status"] == WorkflowStatus.FAILED
    assert "invalid_review_input" in result["errors"][0]


@pytest.mark.asyncio
async def test_invalid_reviewer_output_fails_closed() -> None:
    result = await reviewer_node(
        review_state(),
        FakeLLM('{"verdict":"approved"}'),
    )

    assert result["status"] == WorkflowStatus.FAILED
    assert "review" not in result


@pytest.mark.asyncio
async def test_human_review_and_rejection_are_terminal_statuses() -> None:
    human = await reviewer_node(review_state(), FakeLLM(payload("needs_human_review")))
    rejected = await reviewer_node(review_state(), FakeLLM(payload("rejected")))

    assert human["status"] == WorkflowStatus.NEEDS_HUMAN_REVIEW
    assert rejected["status"] == WorkflowStatus.REJECTED
