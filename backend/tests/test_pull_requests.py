"""Offline tests for exact-hash approval and PR publication."""

import pytest

from app.config import Settings
from app.schemas.workflow import WorkflowStatus
from app.services.persistence import PersistenceError, PersistenceService
from app.services.pull_requests import (
    ApprovalRequest,
    PullRequestResult,
    PullRequestService,
)


class FakeWriter:
    def __init__(self):
        self.calls = []

    def publish(self, **kwargs):
        self.calls.append(kwargs)
        assert kwargs["branch"] != kwargs["base_branch"]
        assert all(item["path"].endswith(".py") for item in kwargs["changes"])
        return PullRequestResult(
            branch=kwargs["branch"],
            number=7,
            url="https://github.com/octo/repo/pull/7",
        )


def setup_store(tmp_path):
    store = PersistenceService(
        Settings(database_url=f"sqlite:///{tmp_path / 'history.db'}")
    )
    store.create_run("wf-1", "octo", "repo", 42)
    store.update_status("wf-1", WorkflowStatus.RUNNING)
    store.update_status("wf-1", WorkflowStatus.PATCH_READY, patch_hash="a" * 64)
    store.save_artifact(
        "wf-1",
        "proposal",
        {
            "summary": "Fix",
            "changes": [{"path": "main.py", "updated_content": "new\n"}],
        },
        patch_hash="a" * 64,
    )
    store.save_artifact("wf-1", "validation", {"valid": True}, patch_hash="a" * 64)
    store.save_artifact(
        "wf-1",
        "diff",
        {"patch_hash": "a" * 64, "diff_text": "diff"},
        patch_hash="a" * 64,
    )
    store.save_artifact(
        "wf-1",
        "sandbox_result",
        {"status": "passed", "exit_code": 0, "test_summary": "passed"},
        patch_hash="a" * 64,
    )
    store.save_artifact(
        "wf-1",
        "review",
        {"verdict": "approved", "summary": "safe"},
        patch_hash="a" * 64,
    )
    return store


def test_exact_hash_approval_publishes_and_is_idempotent(tmp_path):
    store = setup_store(tmp_path)
    writer = FakeWriter()
    service = PullRequestService(store, writer)
    approval = ApprovalRequest(workflow_id="wf-1", expected_patch_hash="a" * 64)

    first = service.approve_and_publish(approval)
    second = service.approve_and_publish(approval)

    assert first == second
    assert len(writer.calls) == 1
    assert store.get_run("wf-1")["status"] == "pr_created"


@pytest.mark.parametrize(
    "approval_hash, message",
    [
        ("b" * 64, "stale"),
        ("", "String should have at least 64 characters"),
    ],
)
def test_missing_or_stale_approval_is_rejected(tmp_path, approval_hash, message):
    store = setup_store(tmp_path)
    writer = FakeWriter()
    service = PullRequestService(store, writer)
    if approval_hash:
        with pytest.raises(PersistenceError, match="stale"):
            service.approve_and_publish(
                ApprovalRequest(workflow_id="wf-1", expected_patch_hash=approval_hash)
            )
    else:
        with pytest.raises(ValueError, match=message):
            ApprovalRequest(workflow_id="wf-1", expected_patch_hash=approval_hash)


def test_failed_sandbox_and_test_path_cannot_publish(tmp_path):
    store = setup_store(tmp_path)
    store.save_artifact(
        "wf-1",
        "sandbox_result",
        {"status": "failed", "exit_code": 1},
        patch_hash="a" * 64,
    )
    with pytest.raises(PersistenceError, match="sandbox"):
        PullRequestService(store, FakeWriter()).approve_and_publish(
            ApprovalRequest(workflow_id="wf-1", expected_patch_hash="a" * 64)
        )

    store = setup_store(tmp_path / "second")
    store.save_artifact(
        "wf-1",
        "proposal",
        {
            "summary": "unsafe",
            "changes": [{"path": "tests/test_main.py", "updated_content": "bad"}],
        },
        patch_hash="a" * 64,
    )
    with pytest.raises(PersistenceError, match="publication path"):
        PullRequestService(store, FakeWriter()).approve_and_publish(
            ApprovalRequest(workflow_id="wf-1", expected_patch_hash="a" * 64)
        )
