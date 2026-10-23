"""Day 15 deployment configuration checks."""

from pathlib import Path

from app.config import Settings


ROOT = Path(__file__).parents[2]


def test_api_image_is_non_root_and_excludes_runtime_data():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert "USER patchpilot" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "COPY .env" not in dockerfile
    for entry in ("data/repositories", "data/workspaces", "data/indexes", "data/*.db"):
        assert entry in dockerignore


def test_compose_keeps_sandbox_and_docker_socket_out_of_api_service():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "services:" in compose
    assert "api:" in compose
    assert "docker.sock" not in compose
    assert "privileged:" not in compose
    assert "patchpilot-data:/app/data" in compose
    assert "healthcheck:" in compose


def test_cors_is_explicit_and_disabled_by_default():
    assert Settings().cors_allowed_origins == ""
    assert Settings(cors_allowed_origins="https://app.example, https://admin.example").cors_allowed_origins == (
        "https://app.example, https://admin.example"
    )
