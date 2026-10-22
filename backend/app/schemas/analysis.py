"""Structured issue-analysis contract."""

from pydantic import BaseModel, ConfigDict, Field


class IssueAnalysis(BaseModel):
    """Validated issue understanding produced by the analyst."""

    model_config = ConfigDict(extra="forbid")

    summary: str
    problem_type: str
    expected_behavior: str
    acceptance_criteria: list[str]
    constraints: list[str]
    keywords: list[str]
    confidence: float = Field(ge=0, le=1)
    needs_clarification: bool
