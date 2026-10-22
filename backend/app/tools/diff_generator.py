"""Deterministic unified diff generation for validated proposals."""

from __future__ import annotations

import difflib
from pathlib import Path

from app.schemas.patch import DiffResult, PatchProposal
from app.tools.patch_validator import proposal_hash


def generate_diff(
    repository_path: Path,
    proposal: PatchProposal,
) -> DiffResult:
    """Generate a local diff from proposal contents, never from model diff text."""

    diffs: list[str] = []
    additions = 0
    deletions = 0
    changed_files: list[str] = []
    for change in sorted(proposal.changes, key=lambda item: item.path):
        original = "" if change.operation == "create" else (change.original_content or "")
        old_path = "/dev/null" if change.operation == "create" else f"a/{change.path}"
        new_path = f"b/{change.path}"
        lines = list(
            difflib.unified_diff(
                original.splitlines(keepends=True),
                change.updated_content.splitlines(keepends=True),
                fromfile=old_path,
                tofile=new_path,
                lineterm="",
            )
        )
        if lines:
            diffs.extend(lines)
            changed_files.append(change.path)
            additions += sum(
                1 for line in lines[2:] if line.startswith("+") and not line.startswith("+++")
            )
            deletions += sum(
                1 for line in lines[2:] if line.startswith("-") and not line.startswith("---")
            )

    return DiffResult(
        patch_hash=proposal_hash(proposal),
        diff_text="\n".join(diffs),
        changed_files=changed_files,
        additions=additions,
        deletions=deletions,
    )
