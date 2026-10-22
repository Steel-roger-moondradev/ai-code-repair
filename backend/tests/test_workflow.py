"""Offline tests for the Day 5 issue workflow."""

from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.github import get_github_client
from app.api.workflows import (
    get_llm_adapter,
    get_repository_tool_registry,
    get_sandbox_service,
)
from app.config import Settings, get_settings
from app.agents.issue_workflow import build_issue_workflow, initial_state
from app.main import app
from app.schemas.github import IssueData
from app.schemas.workflow import WorkflowStatus, transition_status
from app.services.github import GitHubClient, GitHubServiceError
from app.schemas.sandbox import SandboxResult


def issue() -> IssueData:
    return IssueData(
        owner="octo",
        repo="repo",
        issue_number=42,
        title="Fix it",
        body="Expected behavior",
        state="open",
        html_url="https://github.com/octo/repo/issues/42",
        labels=["bug"],
        comments=[],
    )


class FakeGitHubClient:
    async def get_issue(self, owner: str, repo: str, issue_number: int) -> IssueData:
        return issue()


class FailingGitHubClient:
    async def get_issue(self, owner: str, repo: str, issue_number: int) -> IssueData:
        raise GitHubServiceError("not_found", "GitHub resource was not found", 404)


class FakeLLM:
    def __init__(self):
        self.calls = 0

    async def complete(self, **kwargs):
        from app.services.llm import LLMResponse

        self.calls += 1
        if self.calls > 1:
            return LLMResponse(
                text='{"summary":"Fix","assumptions":[],"risks":[],"tests_to_add":[],"changes":['
                '{"path":"main.py","operation":"modify","rationale":"Fix","original_content":"old\\n",'
                '"updated_content":"new\\n"}]}',
                usage={},
            )
        return LLMResponse(
            text='{"summary":"Fix it","problem_type":"bug","expected_behavior":"Work",'
            '"acceptance_criteria":["Works"],"constraints":[],"keywords":["Fix"],'
            '"confidence":0.9,"needs_clarification":false}',
            usage={},
        )


class FakeToolRegistry:
    def execute(self, name, arguments, *, workflow_id="unknown"):
        from app.tools.registry import ToolResult

        if name == "get_repository_tree":
            return ToolResult(ok=True, result=["main.py"])
        if name == "search_repository_code":
            return ToolResult(ok=True, result=[{"path": "main.py", "line": 1, "content": "parse"}])
        return ToolResult(
            ok=True,
            result={
                "path": "main.py",
                "start_line": 1,
                "end_line": 1,
                "content": "old\n",
            },
        )


class FakeSandboxService:
    def execute(self, repository_path, proposal):
        return SandboxResult(
            status="passed",
            exit_code=0,
            stdout="1 passed",
            stderr="",
            duration_ms=1,
            timed_out=False,
            test_summary="1 passed",
            error=None,
        )


@pytest.mark.asyncio
async def test_graph_success_preserves_shared_state_contract() -> None:
    state = initial_state(owner="octo", repo="repo", issue_number=42, workflow_id="wf-1")
    result = await build_issue_workflow(FakeGitHubClient()).ainvoke(state)

    assert result["status"] == WorkflowStatus.RUNNING
    assert result["issue"] == issue()
    assert result["workflow_id"] == "wf-1"
    assert result["repository_tree"] == []
    assert result["errors"] == []


@pytest.mark.asyncio
async def test_graph_failure_is_explicit_and_terminal() -> None:
    state = initial_state(owner="octo", repo="repo", issue_number=42, workflow_id="wf-2")
    result = await build_issue_workflow(FailingGitHubClient()).ainvoke(state)

    assert result["status"] == WorkflowStatus.FAILED
    assert result["issue"] is None
    assert result["errors"] == ["not_found: GitHub resource was not found"]


def test_status_transitions_are_validated_in_one_place() -> None:
    assert transition_status(WorkflowStatus.QUEUED, WorkflowStatus.RUNNING) == WorkflowStatus.RUNNING
    with pytest.raises(ValueError, match="invalid workflow status transition"):
        transition_status(WorkflowStatus.FAILED, WorkflowStatus.RUNNING)


def test_workflow_endpoint_returns_stable_success_shape(tmp_path) -> None:
    async def fake_client() -> AsyncIterator[GitHubClient]:
        yield FakeGitHubClient()

    app.dependency_overrides[get_github_client] = fake_client
    app.dependency_overrides[get_llm_adapter] = lambda: FakeLLM()
    app.dependency_overrides[get_repository_tool_registry] = lambda: FakeToolRegistry()
    repository = tmp_path / "octo" / "repo"
    repository.mkdir(parents=True)
    (repository / "main.py").write_text("old\n", encoding="utf-8")
    app.dependency_overrides[get_settings] = lambda: Settings(repository_root=str(tmp_path))
    app.dependency_overrides[get_sandbox_service] = lambda: FakeSandboxService()
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/workflows/issue-analysis",
                json={"issue_url": "https://github.com/octo/repo/issues/42"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "patch_ready"
    assert payload["issue"]["title"] == "Fix it"
    assert payload["analysis"]["summary"] == "Fix it"
    assert payload["proposal"]["summary"] == "Fix"
    assert payload["validation"]["valid"] is True
    assert payload["diff"]["additions"] == 1
    assert payload["diff"]["deletions"] == 1
    assert payload["sandbox_result"]["status"] == "passed"
    assert payload["review"] is None
    assert payload["errors"] == []


def test_invalid_request_is_rejected_before_graph_execution() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/workflows/issue-analysis",
            json={"issue_url": "https://github.com/octo/repo/pull/42"},
        )

    assert response.status_code == 422
    assert "issue URL" in response.json()["detail"]


def test_graph_compilation_does_not_make_network_calls() -> None:
    class ExplodingClient:
        async def get_issue(self, *args: Any, **kwargs: Any):
            pytest.fail("network must not be called during graph compilation")

    build_issue_workflow(ExplodingClient())
