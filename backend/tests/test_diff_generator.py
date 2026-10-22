"""Tests for deterministic local diff generation."""

from pathlib import Path

from app.schemas.patch import FileChange, PatchProposal
from app.tools.diff_generator import generate_diff


def test_diff_counts_creation_and_modification() -> None:
    proposal = PatchProposal(
        summary="changes",
        assumptions=[],
        risks=[],
        tests_to_add=[],
        changes=[
            FileChange(
                path="new.py",
                operation="create",
                rationale="add",
                original_content=None,
                updated_content="one\ntwo\n",
            ),
            FileChange(
                path="old.py",
                operation="modify",
                rationale="change",
                original_content="old\n",
                updated_content="new\n",
            ),
        ],
    )

    result = generate_diff(Path("."), proposal)

    assert result.changed_files == ["new.py", "old.py"]
    assert result.additions == 3
    assert result.deletions == 1
    assert "diff --" not in result.diff_text
    assert "--- /dev/null" in result.diff_text
    assert result.patch_hash


def test_diff_is_deterministic() -> None:
    proposal = PatchProposal(
        summary="same",
        assumptions=[],
        risks=[],
        tests_to_add=[],
        changes=[
            FileChange(
                path="main.py",
                operation="modify",
                rationale="same",
                original_content="a\n",
                updated_content="b\n",
            )
        ],
    )

    first = generate_diff(Path("."), proposal)
    second = generate_diff(Path("."), proposal)

    assert first == second
