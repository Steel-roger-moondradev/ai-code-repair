"""GitHub read-only API routes."""

from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Path

from app.config import Settings, get_settings
from app.schemas.github import IssueData, RepositoryData
from app.services.github import GitHubClient, GitHubServiceError

router = APIRouter(prefix="/api/v1/repos", tags=["github"])


async def get_github_client(
    settings: Settings = Depends(get_settings),
) -> AsyncIterator[GitHubClient]:
    client = GitHubClient(settings)
    try:
        yield client
    finally:
        await client.aclose()


def _service_error(error: GitHubServiceError) -> HTTPException:
    status_code = {
        "not_found": 404,
        "forbidden": 403,
        "rate_limited": 429,
        "upstream_timeout": 504,
        "upstream_unavailable": 502,
        "upstream_server_error": 502,
        "invalid_upstream_response": 502,
        "invalid_issue": 422,
    }.get(error.category, 502)
    return HTTPException(status_code=status_code, detail=error.message)


@router.get("/{owner}/{repo}", response_model=RepositoryData)
async def get_repository(
    owner: str = Path(min_length=1),
    repo: str = Path(min_length=1),
    client: GitHubClient = Depends(get_github_client),
) -> RepositoryData:
    try:
        return await client.get_repository(owner, repo)
    except GitHubServiceError as exc:
        raise _service_error(exc) from exc


@router.get("/{owner}/{repo}/issues/{issue_number}", response_model=IssueData)
async def get_issue(
    owner: str = Path(min_length=1),
    repo: str = Path(min_length=1),
    issue_number: int = Path(gt=0),
    client: GitHubClient = Depends(get_github_client),
) -> IssueData:
    try:
        return await client.get_issue(owner, repo, issue_number)
    except GitHubServiceError as exc:
        raise _service_error(exc) from exc
