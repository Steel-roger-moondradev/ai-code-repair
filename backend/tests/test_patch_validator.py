"""Tests for fail-closed patch validation and deterministic hashing."""

from pathlib import Path

import pytest

from app.config import Settings
from app.schemas.patch import FileChange, PatchProposal
from app.tools.patch_validator import proposal_hash, validate_patch


def proposal(path: str = "src/main.py", operation: str = "modify", original: str | None = "old\n") -> PatchProposal:
    return PatchProposal(
        summary="Update source",
        assumptions=[],
        risks=[],
        tests_to_add=[],
        changes=[
            FileChange(
                path=path,
                operation=operation,
                rationale="Fix behavior",
                original_content=original,
                updated_content="new\n",
            )
        ],
    )


def test_valid_modification_and_creation(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "main.py").write_text("old\n", encoding="utf-8")

    modified = validate_patch(root, proposal(), settings=Settings(max_patch_bytes=1000))
    created = validate_patch(
        root,
        proposal("src/new.py", "create", None),
        settings=Settings(max_patch_bytes=1000),
    )

    assert modified.valid is True
    assert created.valid is True
    assert modified.patch_hash == proposal_hash(proposal())
    assert not (root / "src" / "new.py").exists()


@pytest.mark.parametrize(
    "change",
    [
        {"path": "README.md"},
        {"path": "../main.py"},
        {"path": "/main.py"},
        {"path": "C:/main.py"},
        {"path": "//server/main.py"},
        {"path": "tests/test_main.py"},
        {"path": "conftest.py"},
    ],
)
def test_unsafe_paths_fail_closed(tmp_path: Path, change: dict) -> None:
    result = validate_patch(tmp_path, proposal(**change), settings=Settings())
    assert result.valid is False
    assert result.patch_hash is None


def test_duplicate_mismatch_missing_and_existing_create_fail(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "main.py").write_text("current\n", encoding="utf-8")

    mismatch = validate_patch(root, proposal("main.py"), settings=Settings())
    missing = validate_patch(
        root,
        proposal("missing.py", "modify", "old\n"),
        settings=Settings(),
    )
    existing_create = validate_patch(
        root,
        proposal("main.py", "create", None),
        settings=Settings(),
    )
    duplicate = PatchProposal(
        summary="duplicate",
        assumptions=[],
        risks=[],
        tests_to_add=[],
        changes=[proposal("a.py").changes[0], proposal("a.py").changes[0]],
    )

    assert any("original content mismatch" in error for error in mismatch.errors)
    assert any("modify target does not exist" in error for error in missing.errors)
    assert any("create target already exists" in error for error in existing_create.errors)
    assert any("duplicate path" in error for error in validate_patch(root, duplicate).errors)


def test_limits_and_proposal_schema_are_enforced(tmp_path: Path) -> None:
    result = validate_patch(
        tmp_path,
        proposal("main.py", "create", None),
        settings=Settings(max_patch_bytes=1, max_patch_files=1),
    )
    assert result.valid is False
    assert "maximum byte count" in result.errors[0]
    with pytest.raises(ValueError):
        PatchProposal(summary="empty", assumptions=[], risks=[], tests_to_add=[], changes=[])
