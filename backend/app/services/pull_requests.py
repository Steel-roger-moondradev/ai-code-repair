"""Exact-patch approval and idempotent GitHub pull-request publication."""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.config import Settings, get_settings
from app.schemas.workflow import WorkflowStatus
from app.services.github import GITHUB_API_BASE_URL, GitHubServiceError
from app.services.persistence import PersistenceError, PersistenceService


class ApprovalRequest(BaseModel):
    """Human approval for one exact, currently persisted patch."""

    model_config = ConfigDict(extra="forbid")

    workflow_id: str = Field(min_length=1, max_length=64)
    expected_patch_hash: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")


class PullRequestResult(BaseModel):
    """Safe publication result persisted with the workflow."""

    model_config = ConfigDict(extra="forbid")

    branch: str
    number: int
    url: str


class PullRequestWriter(Protocol):
    """Minimal GitHub write surface used by the publisher."""

    def publish(
        self,
        *,
        owner: str,
        repo: str,
        base_branch: str,
        branch: str,
        changes: list[dict[str, str]],
        title: str,
        body: str,
    ) -> PullRequestResult:
        ...


class GitHubPullRequestWriter:
    """Synchronous, fixed-host GitHub writer with no default-branch writes."""

    def __init__(self, settings: Settings | None = None, http_client: httpx.Client | None = None):
        self.settings = settings or get_settings()
        self.client = http_client or httpx.Client(
            base_url=GITHUB_API_BASE_URL,
            timeout=self.settings.request_timeout_seconds,
            headers=self._headers(),
        )
        self._owns_client = http_client is None

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def publish(
        self,
        *,
        owner: str,
        repo: str,
        base_branch: str,
        branch: str,
        changes: list[dict[str, str]],
        title: str,
        body: str,
    ) -> PullRequestResult:
        if branch == base_branch:
            raise GitHubServiceError("unsafe_branch", "publication branch cannot be the default branch")
        repository = f"/repos/{owner}/{repo}"
        base = self._request("GET", f"{repository}/git/ref/heads/{base_branch}")
        sha = base.get("object", {}).get("sha")
        if not isinstance(sha, str):
            raise GitHubServiceError("invalid_upstream_response", "GitHub returned no base commit")
        try:
            self._request("GET", f"{repository}/git/ref/heads/{branch}")
        except GitHubServiceError as exc:
            if exc.category != "not_found":
                raise
            self._request(
                "POST",
                f"{repository}/git/refs",
                json={"ref": f"refs/heads/{branch}", "sha": sha},
            )
        for change in changes:
            file_path = f"{repository}/contents/{change['path']}"
            file_payload = self._request(
                "GET",
                file_path,
                params={"ref": branch},
            )
            file_sha = file_payload.get("sha")
            if not isinstance(file_sha, str):
                raise GitHubServiceError(
                    "invalid_upstream_response",
                    f"GitHub returned no blob SHA for {change['path']}",
                )
            self._request(
                "PUT",
                file_path,
                json={
                    "message": title,
                    "content": base64.b64encode(change["content"].encode("utf-8")).decode("ascii"),
                    "branch": branch,
                    "sha": file_sha,
                },
            )
        response = self._request(
            "POST",
            f"{repository}/pulls",
            json={"title": title, "head": branch, "base": base_branch, "body": body},
        )
        number = response.get("number")
        url = response.get("html_url")
        if not isinstance(number, int) or not isinstance(url, str):
            raise GitHubServiceError("invalid_upstream_response", "GitHub returned an invalid pull request")
        return PullRequestResult(branch=branch, number=number, url=url)

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self.settings.github_token:
            headers["Authorization"] = "Bearer " + self.settings.github_token
        return headers

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self.client.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise GitHubServiceError("upstream_timeout", "GitHub request timed out") from exc
        except httpx.HTTPError as exc:
            raise GitHubServiceError("upstream_unavailable", "GitHub request failed") from exc
        if response.status_code in (401, 403):
            detail = _safe_github_detail(response)
            raise GitHubServiceError(
                "forbidden",
                f"GitHub write access was denied: {detail}",
                response.status_code,
            )
        if response.status_code == 404:
            raise GitHubServiceError("not_found", "GitHub resource was not found", 404)
        if response.status_code >= 500:
            raise GitHubServiceError("upstream_server_error", "GitHub service failed", response.status_code)
        if response.status_code >= 400:
            detail = _safe_github_detail(response)
            raise GitHubServiceError(
                "upstream_error",
                f"GitHub rejected the write: {detail}",
                response.status_code,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise GitHubServiceError("invalid_upstream_response", "GitHub returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise GitHubServiceError("invalid_upstream_response", "GitHub returned an invalid response")
        
        return payload


def _safe_github_detail(response: httpx.Response) -> str:
    """Return bounded, non-secret diagnostic text from a GitHub error response."""

    try:
        payload = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    if isinstance(payload, dict) and isinstance(payload.get("message"), str):
        detail = payload["message"].strip()
        if detail:
            return detail[:300]
    return f"HTTP {response.status_code}"


@dataclass
class PullRequestService:
    """Verify exact approval and publish one persisted patch idempotently."""

    persistence: PersistenceService
    writer: PullRequestWriter

    def approve_and_publish(self, approval: ApprovalRequest) -> PullRequestResult:
        run = self.persistence.get_run(approval.workflow_id)
        existing = next(
            (item["payload"] for item in run["artifacts"] if item["type"] == "pull_request"),
            None,
        )
        if existing:
            return PullRequestResult.model_validate(existing)
        if run["status"] not in {WorkflowStatus.NEEDS_HUMAN_REVIEW.value, WorkflowStatus.PATCH_READY.value}:
            raise PersistenceError("workflow is not eligible for approval")
        if run.get("patch_hash") != approval.expected_patch_hash:
            raise PersistenceError("patch hash is stale or does not match the current workflow")
        artifact_rows = run["artifacts"]
        artifacts = {item["type"]: item["payload"] for item in artifact_rows}
        proposal = artifacts.get("proposal")
        validation = artifacts.get("validation")
        diff = artifacts.get("diff")
        sandbox = artifacts.get("sandbox_result")
        review = artifacts.get("review")
        if not proposal or not validation or not diff or not sandbox or not review:
            raise PersistenceError("workflow is missing approval evidence")
        if validation.get("valid") is not True:
            raise PersistenceError("patch validation did not succeed")
        if sandbox.get("status") != "passed":
            raise PersistenceError("sandbox did not pass")
        if review.get("verdict") != "approved":
            raise PersistenceError("reviewer has a blocking verdict")
        if diff.get("patch_hash") != approval.expected_patch_hash:
            raise PersistenceError("stored diff hash does not match approval")

        branch = f"patchpilot/{_safe_workflow_id(approval.workflow_id)}"
        changes = _validated_changes(proposal)
        self.persistence.append_audit_event(
            approval.workflow_id,
            "human_approval",
            {"patch_hash": approval.expected_patch_hash, "branch": branch},
        )
        try:
            result = self.writer.publish(
                owner=run["owner"],
                repo=run["repo"],
                base_branch="main",
                branch=branch,
                changes=changes,
                title=str(proposal["summary"])[:120],
                body=_description(run, proposal, sandbox, review),
            )
        except (PersistenceError, GitHubServiceError, OSError, ValueError) as exc:
            self.persistence.append_audit_event(
                approval.workflow_id,
                "pull_request_failed",
                {"patch_hash": approval.expected_patch_hash, "error": _safe_error(exc)},
            )
            if isinstance(exc, (PersistenceError, GitHubServiceError)):
                raise
            raise GitHubServiceError("publication_failed", "pull request publication failed") from exc
        self.persistence.save_artifact(
            approval.workflow_id,
            "pull_request",
            result,
            patch_hash=approval.expected_patch_hash,
        )
        self.persistence.update_status(
            approval.workflow_id,
            WorkflowStatus.APPROVED,
            patch_hash=approval.expected_patch_hash,
            stage="human_approval",
        )
        self.persistence.update_status(
            approval.workflow_id,
            WorkflowStatus.PR_CREATED,
            patch_hash=approval.expected_patch_hash,
            stage="pull_request_created",
        )
        return result


def _safe_workflow_id(workflow_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9-]", "-", workflow_id)
    return safe[:48].strip("-") or "workflow"


def _validated_changes(proposal: dict[str, Any]) -> list[dict[str, str]]:
    changes: list[dict[str, str]] = []
    for change in proposal.get("changes", []):
        path = change.get("path")
        if (
            not isinstance(path, str)
            or not path.endswith(".py")
            or "\\" in path
            or path.startswith("/")
            or ".." in path.split("/")
            or path.startswith("tests/")
            or path.split("/")[-1].startswith("test_")
            or path.split("/")[-1].endswith("_test.py")
        ):
            raise PersistenceError("proposal contains an invalid publication path")
        changes.append({"path": path, "content": change.get("updated_content", "")})
    if not changes:
        raise PersistenceError("proposal contains no publishable changes")
    return changes


def _description(
    run: dict[str, Any],
    proposal: dict[str, Any],
    sandbox: dict[str, Any],
    review: dict[str, Any],
) -> str:
    return (
        f"Fixes #{run['issue_number']} in `{run['owner']}/{run['repo']}`.\n\n"
        f"{proposal.get('summary', '')}\n\n"
        f"Changed files: {', '.join(item['path'] for item in proposal.get('changes', []))}\n"
        f"Sandbox: {sandbox.get('test_summary', '')} (exit code {sandbox.get('exit_code')}).\n"
        f"Reviewer: {review.get('summary', '')}.\n\n"
        "This patch was generated by PatchPilot AI and requires human review."
    )


def _safe_error(error: Exception) -> str:
    return getattr(error, "category", "publication_failed")
