"""Bounded GitHub REST API integration."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.config import Settings
from app.schemas.github import IssueData, IssueReference, RepositoryData

GITHUB_API_BASE_URL = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"
MAX_ISSUE_COMMENTS = 20
GITHUB_IDENTIFIER = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]*[A-Za-z0-9])?$")


class GitHubServiceError(Exception):
    """Safe, categorized error raised by the GitHub service."""

    def __init__(self, category: str, message: str, status_code: int | None = None):
        super().__init__(message)
        self.category = category
        self.message = message
        self.status_code = status_code


def parse_issue_url(url: str) -> IssueReference:
    """Parse an exact HTTPS GitHub issue URL."""

    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("issue URL must be an HTTPS github.com issue URL")

    segments = parsed.path.split("/")
    if len(segments) != 5 or segments[0] or segments[3] != "issues":
        raise ValueError("issue URL must match /OWNER/REPO/issues/NUMBER")

    owner, repo, issue_number_text = segments[1], segments[2], segments[4]
    if (
        not GITHUB_IDENTIFIER.fullmatch(owner)
        or not GITHUB_IDENTIFIER.fullmatch(repo)
        or not issue_number_text.isdecimal()
    ):
        raise ValueError("issue URL must contain an owner, repository, and positive issue number")

    issue_number = int(issue_number_text)
    if issue_number <= 0:
        raise ValueError("issue number must be greater than zero")

    return IssueReference(owner=owner, repo=repo, issue_number=issue_number)


class GitHubClient:
    """Async client for the fixed GitHub REST API host."""

    def __init__(
        self,
        settings: Settings,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._http_client = http_client or httpx.AsyncClient(
            base_url=GITHUB_API_BASE_URL,
            timeout=settings.request_timeout_seconds,
            headers=self._headers(),
        )
        self._owns_http_client = http_client is None
        if http_client is not None:
            self._http_client.headers.update(self._headers())

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        }
        if self._settings.github_token:
            headers["Authorization"] = f"Bearer {self._settings.github_token}"
        return headers

    async def aclose(self) -> None:
        if self._owns_http_client:
            await self._http_client.aclose()

    async def get_repository(self, owner: str, repo: str) -> RepositoryData:
        self._validate_identifiers(owner, repo)
        payload = await self._request(f"/repos/{owner}/{repo}")
        try:
            return RepositoryData(
                owner=owner,
                repo=repo,
                full_name=payload["full_name"],
                private=payload["private"],
                default_branch=payload["default_branch"],
                html_url=payload["html_url"],
                clone_url=payload["clone_url"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise GitHubServiceError(
                "invalid_upstream_response",
                "GitHub returned an invalid repository response",
            ) from exc

    async def get_issue(self, owner: str, repo: str, issue_number: int) -> IssueData:
        self._validate_identifiers(owner, repo)
        if issue_number <= 0:
            raise ValueError("issue number must be greater than zero")

        payload = await self._request(f"/repos/{owner}/{repo}/issues/{issue_number}")
        if "pull_request" in payload:
            raise GitHubServiceError(
                "invalid_issue",
                "Pull requests are not valid issue inputs",
            )

        labels = payload.get("labels", [])
        if not isinstance(labels, list):
            raise GitHubServiceError(
                "invalid_upstream_response",
                "GitHub returned an invalid issue response",
            )

        try:
            issue = IssueData(
                owner=owner,
                repo=repo,
                issue_number=issue_number,
                title=payload["title"],
                body=payload.get("body") or "",
                state=payload["state"],
                html_url=payload["html_url"],
                labels=[
                    label["name"]
                    for label in labels
                    if isinstance(label, dict) and isinstance(label.get("name"), str)
                ],
                comments=[],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise GitHubServiceError(
                "invalid_upstream_response",
                "GitHub returned an invalid issue response",
            ) from exc

        if payload.get("comments", 0):
            comments = await self._request(
                f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
                params={"per_page": MAX_ISSUE_COMMENTS},
            )
            if not isinstance(comments, list):
                raise GitHubServiceError(
                    "invalid_upstream_response",
                    "GitHub returned an invalid comments response",
                )
            issue.comments = [
                comment["body"] or ""
                for comment in comments[:MAX_ISSUE_COMMENTS]
                if isinstance(comment, dict) and isinstance(comment.get("body"), (str, type(None)))
            ]

        return issue

    @staticmethod
    def _validate_identifiers(owner: str, repo: str) -> None:
        if not GITHUB_IDENTIFIER.fullmatch(owner) or not GITHUB_IDENTIFIER.fullmatch(repo):
            raise ValueError("owner and repository names contain invalid characters")

    async def _request(self, path: str, **kwargs: Any) -> Any:
        try:
            response = await self._http_client.get(path, **kwargs)
        except httpx.TimeoutException as exc:
            raise GitHubServiceError("upstream_timeout", "GitHub request timed out") from exc
        except httpx.HTTPError as exc:
            raise GitHubServiceError("upstream_unavailable", "GitHub request failed") from exc

        if response.status_code == 404:
            raise GitHubServiceError("not_found", "GitHub resource was not found", 404)
        if response.status_code in (401, 403):
            category = "rate_limited" if response.headers.get("X-RateLimit-Remaining") == "0" else "forbidden"
            raise GitHubServiceError(category, "GitHub access was denied or rate limited", response.status_code)
        if response.status_code == 429:
            raise GitHubServiceError("rate_limited", "GitHub rate limit exceeded", 429)
        if response.status_code >= 500:
            raise GitHubServiceError("upstream_server_error", "GitHub service failed", response.status_code)
        if response.status_code >= 400:
            raise GitHubServiceError("upstream_error", "GitHub rejected the request", response.status_code)

        try:
            return response.json()
        except ValueError as exc:
            raise GitHubServiceError(
                "invalid_upstream_response",
                "GitHub returned invalid JSON",
                response.status_code,
            ) from exc
