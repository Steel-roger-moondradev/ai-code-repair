"""Day 16 clean-room and final-delivery checks."""

from pathlib import Path

from app.schemas.workflow import WorkflowResponse


ROOT = Path(__file__).parents[2]


def test_documented_delivery_surfaces_exist_and_are_consistent():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    security = (ROOT / "docs" / "security.md").read_text(encoding="utf-8")
    evaluation = (ROOT / "docs" / "evaluation.md").read_text(encoding="utf-8")
    demo = (ROOT / "docs" / "demo.md").read_text(encoding="utf-8")
    interview = (ROOT / "docs" / "interview-notes.md").read_text(encoding="utf-8")

    for text in (readme, security, evaluation, demo, interview):
        assert "Python" in text
    for text in (readme, security, demo):
        assert "Docker" in text
    for text in (readme, demo):
        assert "approval" in text.lower()
    assert "patch_hash" in readme
    assert "PatchPilotState" in readme
    assert "workflow_id" in demo


def test_generated_data_and_secret_patterns_are_not_tracked():
    tracked = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in tracked
    assert "data/*.db" in tracked
    assert "data/repositories/" in tracked
    assert "data/workspaces/" in tracked


def test_public_response_contract_remains_typed():
    fields = set(WorkflowResponse.model_fields)
    assert {"workflow_id", "status", "errors"}.issubset(fields)
