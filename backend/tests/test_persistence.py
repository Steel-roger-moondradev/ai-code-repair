"""Offline tests for restart-safe workflow persistence."""

import pytest

from app.config import Settings
from app.schemas.workflow import WorkflowStatus
from app.services.persistence import PersistenceError, PersistenceService


def service(tmp_path):
    return PersistenceService(
        Settings(database_url=f"sqlite:///{tmp_path / 'history.db'}")
    )


def test_create_retrieve_and_recreate_service_preserves_history(tmp_path):
    first = service(tmp_path)
    first.create_run("wf-1", "octo", "repo", 42)
    first.update_status("wf-1", WorkflowStatus.RUNNING)
    first.save_artifact("wf-1", "proposal", {"summary": "safe", "api_key": "secret"})
    first.append_audit_event("wf-1", "test", {"stage": "sandbox"})

    second = service(tmp_path)
    result = second.get_run("wf-1")

    assert result["status"] == "running"
    assert result["artifacts"][0]["payload"]["summary"] == "safe"
    assert result["artifacts"][0]["payload"]["api_key"] == "[REDACTED]"
    assert result["audit_events"][0]["event_type"] == "workflow_created"


def test_artifacts_are_tied_to_patch_hash_and_unknown_workflow_fails(tmp_path):
    store = service(tmp_path)
    store.create_run("wf-1", "octo", "repo", 1)
    store.save_artifact("wf-1", "diff", {"diff_text": "bounded"}, patch_hash="abc")

    assert store.get_run("wf-1")["artifacts"][0]["patch_hash"] == "abc"
    with pytest.raises(PersistenceError, match="unknown workflow"):
        store.save_artifact("missing", "diff", {})


def test_illegal_transition_and_pagination_validation(tmp_path):
    store = service(tmp_path)
    store.create_run("wf-1", "octo", "repo", 1)
    store.update_status("wf-1", WorkflowStatus.RUNNING)
    with pytest.raises(PersistenceError):
        store.update_status("wf-1", WorkflowStatus.APPROVED)
    with pytest.raises(PersistenceError):
        store.list_runs(page=0)


def test_list_pagination(tmp_path):
    store = service(tmp_path)
    for index in range(3):
        store.create_run(f"wf-{index}", "octo", "repo", index + 1)

    result = store.list_runs(page=2, page_size=2)

    assert result["total"] == 3
    assert len(result["items"]) == 1
