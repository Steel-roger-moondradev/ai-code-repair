"""Offline tests for the Day 12 workflow API lifecycle."""

from collections.abc import AsyncIterator

from fastapi.testclient import TestClient

from app.api.github import get_github_client
from app.api.workflows import (
    get_llm_adapter,
    get_persistence_service,
    get_repository_tool_registry,
    get_sandbox_service,
)
from app.config import Settings, get_settings
from app.main import app
from app.services.persistence import PersistenceService
from tests.test_workflow import (
    FakeGitHubClient,
    FakeLLM,
    FakeSandboxService,
    FakeToolRegistry,
)


def configured_client(tmp_path):
    async def fake_client() -> AsyncIterator[FakeGitHubClient]:
        yield FakeGitHubClient()

    app.dependency_overrides[get_github_client] = fake_client
    app.dependency_overrides[get_llm_adapter] = lambda: FakeLLM()
    app.dependency_overrides[get_repository_tool_registry] = lambda: FakeToolRegistry()
    app.dependency_overrides[get_sandbox_service] = lambda: FakeSandboxService()
    app.dependency_overrides[get_settings] = lambda: Settings(
        repository_root=str(tmp_path),
        database_url=f"sqlite:///{tmp_path / 'history.db'}",
    )
    app.dependency_overrides[get_persistence_service] = lambda: PersistenceService(
        Settings(database_url=f"sqlite:///{tmp_path / 'history.db'}")
    )
    repository = tmp_path / "octo" / "repo"
    repository.mkdir(parents=True)
    (repository / "main.py").write_text("old\n", encoding="utf-8")


def test_create_poll_and_idempotent_replay(tmp_path):
    configured_client(tmp_path)
    try:
        with TestClient(app) as client:
            payload = {
                "issue_url": "https://github.com/octo/repo/issues/42",
                "idempotency_key": "request-1",
            }
            first = client.post(
                "/api/v1/workflows",
                json=payload,
                headers={"X-Request-ID": "req-1"},
            )
            second = client.post("/api/v1/workflows", json=payload)
            workflow_id = first.json()["workflow_id"]
            polled = client.get(f"/api/v1/workflows/{workflow_id}")
            listed = client.get("/api/v1/workflows?page=1&page_size=10")
    finally:
        app.dependency_overrides.clear()

    assert first.status_code == 200
    assert first.headers["X-Request-ID"] == "req-1"
    assert second.status_code == 200
    assert second.json()["workflow_id"] == workflow_id
    assert second.json()["errors"] == ["idempotent_replay"]
    assert polled.status_code == 200
    assert polled.json()["status"] == "patch_ready"
    assert listed.status_code == 200
    assert listed.json()["total"] == 1


def test_unknown_workflow_and_invalid_pagination_are_safe_errors():
    with TestClient(app) as client:
        unknown = client.get("/api/v1/workflows/does-not-exist")
        invalid_page = client.get("/api/v1/workflows?page=0")

    assert unknown.status_code == 404
    assert unknown.json() == {"detail": "unknown workflow ID"}
    assert invalid_page.status_code == 422
    assert "page must be positive" in invalid_page.json()["detail"]


def test_oversized_request_is_rejected_before_route_execution():
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/workflows",
            content="x" * 70000,
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 413
    assert response.json() == {"detail": "request body too large"}
