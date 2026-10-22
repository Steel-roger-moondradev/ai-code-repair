"""Canonical structured patch and diff contracts."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FileChange(BaseModel):
    """One source-grounded Python file change."""

    model_config = ConfigDict(extra="forbid")

    path: str
    operation: Literal["create", "modify"]
    rationale: str
    original_content: str | None
    updated_content: str


class PatchProposal(BaseModel):
    """Structured patch proposal produced by the fixer."""

    model_config = ConfigDict(extra="forbid")

    summary: str
    assumptions: list[str]
    risks: list[str]
    tests_to_add: list[str]
    changes: list[FileChange] = Field(min_length=1)


class PatchValidationResult(BaseModel):
    """Deterministic result of validating a patch proposal."""

    model_config = ConfigDict(extra="forbid")

    valid: bool
    errors: list[str]
    validated_paths: list[str]
    patch_hash: str | None


class DiffResult(BaseModel):
    """Locally generated unified diff and change counts."""

    model_config = ConfigDict(extra="forbid")

    patch_hash: str
    diff_text: str
    changed_files: list[str]
    additions: int
    deletions: int
