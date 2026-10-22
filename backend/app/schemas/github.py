"""GitHub API request and response contracts."""

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class IssueReference(BaseModel):
    """A validated GitHub issue identity."""

    owner: str = Field(min_length=1)
    repo: str = Field(min_length=1)
    issue_number: int = Field(gt=0)


class IssueData(BaseModel):
    """Normalized GitHub issue data used by the workflow."""

    owner: str
    repo: str
    issue_number: int = Field(gt=0)
    title: str
    body: str
    state: str
    html_url: HttpUrl
    labels: list[str]
    comments: list[str]


class RepositoryData(BaseModel):
    """Normalized repository metadata returned by the GitHub client."""

    model_config = ConfigDict(extra="forbid")

    owner: str
    repo: str
    full_name: str
    private: bool
    default_branch: str
    html_url: HttpUrl
    clone_url: HttpUrl

    @field_validator("owner", "repo", "full_name", "default_branch")
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be empty")
        return value
