"""Contracts for isolated sandbox test execution."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class SandboxResult(BaseModel):
    """Bounded, explicit result from one sandbox execution."""

    model_config = ConfigDict(extra="forbid")

    status: Literal[
        "passed",
        "failed",
        "timed_out",
        "infrastructure_error",
        "rejected",
    ]
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool
    test_summary: str
    error: str | None
