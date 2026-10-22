"""Fail-closed validation and canonical hashing for patch proposals."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath

from app.config import Settings, get_settings
from app.schemas.patch import PatchProposal, PatchValidationResult

PROTECTED_NAMES = {"conftest.py", "pyproject.py", "setup.py"}
PROTECTED_DIRECTORIES = {"tests", "test", ".git", ".venv", "venv"}
DRIVE_PATH = re.compile(r"^[A-Za-z]:")


def canonical_proposal_bytes(proposal: PatchProposal) -> bytes:
    """Serialize a proposal once for deterministic hashes and later approval."""

    payload = proposal.model_dump(mode="json", exclude_none=False)
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def proposal_hash(proposal: PatchProposal) -> str:
    """Return the canonical SHA-256 proposal hash."""

    return hashlib.sha256(canonical_proposal_bytes(proposal)).hexdigest()


def validate_patch(
    repository_path: Path,
    proposal: PatchProposal,
    *,
    settings: Settings | None = None,
) -> PatchValidationResult:
    """Validate without writing any source file."""

    settings = settings or get_settings()
    errors: list[str] = []
    paths: list[str] = []
    seen: set[str] = set()
    total_bytes = 0

    if not proposal.changes:
        errors.append("proposal must contain at least one change")
    if len(proposal.changes) > settings.max_patch_files:
        errors.append("proposal exceeds maximum file count")

    root = repository_path.expanduser().resolve()
    for change in proposal.changes:
        normalized = _validate_path(change.path, errors)
        if normalized is None:
            continue
        if normalized in seen:
            errors.append(f"duplicate path: {normalized}")
            continue
        seen.add(normalized)
        paths.append(normalized)

        target = root.joinpath(*normalized.split("/"))
        if target.is_symlink():
            errors.append(f"symlink path is not allowed: {normalized}")
            continue
        try:
            target.resolve().relative_to(root)
        except ValueError:
            errors.append(f"path escapes repository: {normalized}")
            continue

        updated_bytes = _utf8_size(change.updated_content, normalized, errors)
        total_bytes += updated_bytes
        if change.operation == "create":
            if change.original_content is not None:
                errors.append(f"create change must not include original content: {normalized}")
            if target.exists():
                errors.append(f"create target already exists: {normalized}")
        elif change.operation == "modify":
            if change.original_content is None:
                errors.append(f"modify change requires original content: {normalized}")
            elif not target.is_file():
                errors.append(f"modify target does not exist: {normalized}")
            elif target.is_symlink():
                errors.append(f"modify target is a symlink: {normalized}")
            else:
                try:
                    current = target.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    errors.append(f"modify target is unreadable: {normalized}")
                else:
                    if current != change.original_content:
                        errors.append(f"original content mismatch: {normalized}")

    if total_bytes > settings.max_patch_bytes:
        errors.append("proposal exceeds maximum byte count")
    return PatchValidationResult(
        valid=not errors,
        errors=errors,
        validated_paths=paths if not errors else [],
        patch_hash=proposal_hash(proposal) if not errors else None,
    )


def _validate_path(path: str, errors: list[str]) -> str | None:
    if not path or "\\" in path or DRIVE_PATH.match(path) or path.startswith("//"):
        errors.append(f"invalid repository-relative path: {path!r}")
        return None
    pure = PurePosixPath(path)
    if (
        pure.is_absolute()
        or ".." in pure.parts
        or any(not part for part in pure.parts)
        or pure.suffix.lower() != ".py"
    ):
        errors.append(f"invalid Python path: {path!r}")
        return None
    if (
        any(part in PROTECTED_DIRECTORIES for part in pure.parts)
        or pure.name in PROTECTED_NAMES
        or pure.name.startswith("test_")
        or pure.name.endswith("_test.py")
    ):
        errors.append(f"protected path: {path}")
        return None
    return pure.as_posix()


def _utf8_size(content: str, path: str, errors: list[str]) -> int:
    try:
        return len(content.encode("utf-8"))
    except UnicodeEncodeError:
        errors.append(f"updated content is not valid UTF-8: {path}")
        return 0
