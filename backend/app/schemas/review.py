"""Evidence-based patch review contract."""

from pydantic import BaseModel, ConfigDict
from typing import Literal


class ReviewerResult(BaseModel):
    """Structured reviewer judgment separated from observed evidence."""

    model_config = ConfigDict(extra="forbid")

    verdict: Literal["approved", "needs_changes", "needs_human_review", "rejected"]
    correctness_concerns: list[str]
    security_concerns: list[str]
    maintainability_notes: list[str]
    test_coverage_notes: list[str]
    evidence: list[str]
    summary: str
