"""Repeatable Day 14 fixture evaluation and security-boundary checks."""

import json
import logging
from pathlib import Path

import pytest

from app.schemas.patch import FileChange, PatchProposal
from app.services.observability import log_stage
from app.tools.patch_validator import validate_patch
from app.config import Settings

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "evaluation"


def fixture_cases() -> list[Path]:
    return sorted(path for path in FIXTURE_ROOT.iterdir() if path.is_dir())


def test_all_evaluation_fixtures_are_repeatable_and_measure_actual_outcomes():
    metrics = {
        "fixture_count": 0,
        "expected_patchable": 0,
        "expected_safe_stops": 0,
        "validated_invalid": 0,
    }
    for case in fixture_cases():
        issue = json.loads((case / "issue.json").read_text(encoding="utf-8"))
        expected = json.loads((case / "expected.json").read_text(encoding="utf-8"))
        source_files = sorted(
            path.name for path in case.glob("*.py")
        )
        assert expected["relevant_files"] == source_files or not expected["relevant_files"]
        assert issue["expected_terminal_state"] == expected["expected_terminal_state"]
        metrics["fixture_count"] += 1
        if issue["patch_allowed"]:
            metrics["expected_patchable"] += 1
        else:
            metrics["expected_safe_stops"] += 1

        original = (
            (case / source_files[0]).read_text(encoding="utf-8")
            if issue["patch_allowed"]
            else ""
        )
        proposal = PatchProposal(
            summary=issue["title"],
            assumptions=[],
            risks=[],
            tests_to_add=[],
            changes=[
                FileChange(
                    path="../../outside.py" if case.name == "malicious_path" else source_files[0],
                    operation="modify",
                    rationale="synthetic evaluation",
                    original_content=original,
                    updated_content="changed\n",
                )
            ],
        )
        result = validate_patch(case, proposal, settings=Settings())
        if not result.valid:
            metrics["validated_invalid"] += 1

    assert metrics == {
        "fixture_count": 6,
        "expected_patchable": 2,
        "expected_safe_stops": 4,
        "validated_invalid": 4,
    }


def test_structured_logs_contain_metadata_but_not_secrets(caplog):
    with caplog.at_level(logging.INFO, logger="patchpilot.workflow"):
        log_stage(
            workflow_id="wf-safe",
            node="sandbox",
            status="failed",
            duration_ms=12,
            error_category="timeout",
        )

    message = caplog.records[-1].getMessage()
    assert "wf-safe" in message
    assert "sandbox" in message
    assert "timeout" in message
    assert "GROQ_API_KEY" not in message
    assert "source_content" not in message


def test_fixture_corpus_has_no_real_credentials():
    for path in FIXTURE_ROOT.rglob("*"):
        if path.is_file() and path.suffix in {".json", ".py"}:
            content = path.read_text(encoding="utf-8")
            assert "ghp_" not in content
            assert "Bearer " not in content
            assert "GROQ_API_KEY" not in content


@pytest.mark.parametrize(
    "path",
    ["../outside.py", "C:/outside.py", "//server/outside.py", "tests/test_x.py"],
)
def test_security_fixture_paths_are_rejected(tmp_path, path):
    proposal = PatchProposal(
        summary="unsafe",
        assumptions=[],
        risks=[],
        tests_to_add=[],
        changes=[
            FileChange(
                path=path,
                operation="create",
                rationale="unsafe",
                original_content=None,
                updated_content="bad\n",
            )
        ],
    )
    result = validate_patch(tmp_path, proposal)
    assert result.valid is False
