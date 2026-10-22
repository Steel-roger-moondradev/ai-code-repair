"""Offline tests for GitHub parsing, normalization, and API error handling."""

import httpx
import pytest
from fastapi.testclient import TestClient
from collections.abc import AsyncIterator

from app.api.github import get_github_client
from app.config import Settings
from app.main import app
from app.schemas.github import IssueData
from app.services.github import GitHubClient, GitHubServiceError, parse_issue_url


def settings(token: str | None = None) -> Settings:
    return Settings(github_token=token)


def test_parse_issue_url_accepts_only_canonical_issue_url() -> None:
    assert parse_issue_url("https://github.com/octo/repo/issues/42").model_dump() == {
        "owner": "octo",
        "repo": "repo",
        "issue_number": 42,
    }


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/octo/repo/issues/42",
        "https://evil.example/octo/repo/issues/42",
        "https://github.com/octo/repo/pull/42",
        "https://github.com/octo/repo/issues/0",
        "https://user:pass@github.com/octo/repo/issues/42",
        "https://github.com/octo/repo/issues/42?owner=other",
        "https://github.com/octo/repo/issues/42#fragment",
    ],
)
def test_parse_issue_url_rejects_invalid_inputs(url: str) -> None:
    with pytest.raises(ValueError):
        parse_issue_url(url)


@pytest.mark.asyncio
async def test_repository_and_issue_are_normalized_without_live_network() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/octo/repo":
            return httpx.Response(
                200,
                json={
                    "full_name": "octo/repo",
                    "private": False,
                    "default_branch": "main",
                    "html_url": "https://github.com/octo/repo",
                    "clone_url": "https://github.com/octo/repo.git",
                },
            )
        if request.url.path.endswith("/issues/42"):
            return httpx.Response(
                200,
                json={
                    "title": "Fix it",
                    "body": None,
                    "state": "open",
                    "html_url": "https://github.com/octo/repo/issues/42",
                    "labels": [{"name": "bug"}],
                    "comments": 1,
                },
            )
        return httpx.Response(200, json=[{"body": "A comment"}])

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        base_url="https://api.github.com",
        transport=transport,
    ) as http_client:
        client = GitHubClient(settings("secret"), http_client)
        repository = await client.get_repository("octo", "repo")
        issue = await client.get_issue("octo", "repo", 42)

    assert repository.full_name == "octo/repo"
    assert issue == IssueData(
        owner="octo",
        repo="repo",
        issue_number=42,
        title="Fix it",
        body="",
        state="open",
        html_url="https://github.com/octo/repo/issues/42",
        labels=["bug"],
        comments=["A comment"],
    )


@pytest.mark.asyncio
async def test_malformed_repository_response_is_rejected() -> None:
    async with httpx.AsyncClient(
        base_url="https://api.github.com",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
    ) as http_client:
        client = GitHubClient(settings(), http_client)
        with pytest.raises(GitHubServiceError) as error:
            await client.get_repository("octo", "repo")

    assert error.value.category == "invalid_upstream_response"


@pytest.mark.asyncio
async def test_timeout_is_mapped_to_safe_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out")

    async with httpx.AsyncClient(
        base_url="https://api.github.com",
        transport=httpx.MockTransport(handler),
    ) as http_client:
        client = GitHubClient(settings(), http_client)
        with pytest.raises(GitHubServiceError) as error:
            await client.get_repository("octo", "repo")

    assert error.value.category == "upstream_timeout"


@pytest.mark.asyncio
async def test_pull_request_payload_is_rejected() -> None:
    async with httpx.AsyncClient(
        base_url="https://api.github.com",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"pull_request": {}})
        ),
    ) as http_client:
        client = GitHubClient(settings(), http_client)
        with pytest.raises(GitHubServiceError) as error:
            await client.get_issue("octo", "repo", 42)

    assert error.value.category == "invalid_issue"


@pytest.mark.asyncio
async def test_invalid_identifiers_are_rejected_before_network() -> None:
    async with httpx.AsyncClient(
        base_url="https://api.github.com",
        transport=httpx.MockTransport(
            lambda request: pytest.fail("network must not be called")
        ),
    ) as http_client:
        client = GitHubClient(settings(), http_client)
        with pytest.raises(ValueError):
            await client.get_repository("../octo", "repo")
        with pytest.raises(ValueError):
            await client.get_issue("octo", "repo", 0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "headers", "category"),
    [
        (404, {}, "not_found"),
        (401, {}, "forbidden"),
        (403, {"X-RateLimit-Remaining": "0"}, "rate_limited"),
        (429, {}, "rate_limited"),
        (500, {}, "upstream_server_error"),
    ],
)
async def test_upstream_failures_are_categorized(status_code, headers, category) -> None:
    async with httpx.AsyncClient(
        base_url="https://api.github.com",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(status_code, headers=headers, json={})
        ),
    ) as http_client:
        client = GitHubClient(settings(), http_client)
        with pytest.raises(GitHubServiceError) as error:
            await client.get_repository("octo", "repo")

    assert error.value.category == category


def test_api_routes_return_normalized_data_and_safe_errors(monkeypatch) -> None:
    async def fake_client() -> AsyncIterator[GitHubClient]:
        yield GitHubClient(settings(), httpx.AsyncClient(
            base_url="https://api.github.com",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    404,
                    json={},
                )
            ),
        ))

    app.dependency_overrides[get_github_client] = fake_client
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/repos/octo/repo")
        assert response.status_code == 404
        assert response.json() == {"detail": "GitHub resource was not found"}
    finally:
        app.dependency_overrides.clear()


def test_api_rejects_invalid_issue_number(client) -> None:
    response = client.get("/api/v1/repos/octo/repo/issues/0")

    assert response.status_code == 422


def test_token_is_sent_only_as_auth_header_and_not_in_response() -> None:
    seen_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.update(dict(request.headers))
        return httpx.Response(200, json={
            "full_name": "octo/repo",
            "private": False,
            "default_branch": "main",
            "html_url": "https://github.com/octo/repo",
            "clone_url": "https://github.com/octo/repo.git",
        })

    async def run() -> None:
        async with httpx.AsyncClient(
            base_url="https://api.github.com",
            transport=httpx.MockTransport(handler),
        ) as http_client:
            await GitHubClient(settings("secret-token"), http_client).get_repository("octo", "repo")

    import asyncio

    asyncio.run(run())
    assert seen_headers["authorization"] == "Bearer secret-token"
