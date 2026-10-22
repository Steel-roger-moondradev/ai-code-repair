"""Offline tests for safe Python repository operations."""

import subprocess
from pathlib import Path

import pytest

from app.config import Settings
from app.services.repository import (
    RepositoryService,
    RepositoryServiceError,
    parse_github_clone_url,
)


def make_service(tmp_path: Path, **overrides) -> RepositoryService:
    values = {
        "repository_root": str(tmp_path / "repositories"),
        "max_repository_files": 10,
        "max_file_bytes": 100,
        "max_context_chars": 200,
        "request_timeout_seconds": 1,
    }
    values.update(overrides)
    return RepositoryService(Settings(**values))


def create_repository(tmp_path: Path) -> tuple[RepositoryService, Path]:
    service = make_service(tmp_path)
    root = service.repository_root / "octo" / "repo"
    root.mkdir(parents=True)
    return service, root


def test_parse_clone_url_accepts_https_github_urls() -> None:
    assert parse_github_clone_url("https://github.com/octo/repo.git") == ("octo", "repo")
    assert parse_github_clone_url("https://github.com/octo/repo") == ("octo", "repo")


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/octo/repo",
        "https://evil.example/octo/repo",
        "https://user:pass@github.com/octo/repo",
        "https://github.com:443/octo/repo",
        "https://github.com/octo/repo?token=secret",
        "https://github.com/octo/repo#fragment",
        "https://github.com/octo/../repo",
    ],
)
def test_parse_clone_url_rejects_unsafe_urls(url: str) -> None:
    with pytest.raises(ValueError):
        parse_github_clone_url(url)


def test_clone_uses_fixed_public_url_and_rejects_mismatched_existing_origin(
    tmp_path: Path,
    monkeypatch,
) -> None:
    service = make_service(tmp_path)
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        commands.append(command)
        target = Path(command[-1])
        target.mkdir(parents=True)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    path = service.clone_repository("https://github.com/octo/repo")
    assert path == service.repository_root / "octo" / "repo"
    assert commands[0][:4] == ["git", "clone", "--depth", "1"]
    assert "secret" not in " ".join(commands[0])

    monkeypatch.setattr(
        service,
        "_origin_url",
        lambda repository_path: "https://github.com/other/repo.git",
    )
    with pytest.raises(RepositoryServiceError, match="origin"):
        service.clone_repository("https://github.com/octo/repo")


def test_clone_timeout_is_safe_error(tmp_path: Path, monkeypatch) -> None:
    service = make_service(tmp_path)

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 1)

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(RepositoryServiceError, match="timed out"):
        service.clone_repository("https://github.com/octo/repo")


def test_tree_excludes_ignored_non_python_and_symlink_files(tmp_path: Path) -> None:
    service, root = create_repository(tmp_path)
    (root / "src").mkdir()
    (root / "src" / "main.py").write_text("print('ok')", encoding="utf-8")
    (root / "README.md").write_text("readme", encoding="utf-8")
    (root / ".venv").mkdir()
    (root / ".venv" / "ignored.py").write_text("ignored", encoding="utf-8")
    external = tmp_path / "external.py"
    external.write_text("outside", encoding="utf-8")
    try:
        (root / "escape.py").symlink_to(external)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable in this environment")

    assert service.get_repository_tree(root) == ["src/main.py"]


def test_search_is_exact_and_bounded(tmp_path: Path) -> None:
    service = make_service(tmp_path, max_file_bytes=500)
    root = service.repository_root / "octo" / "repo"
    root.mkdir(parents=True)
    (root / "main.py").write_text("needle\nneedle\n" + "x" * 200, encoding="utf-8")
    (root / "binary.py").write_bytes(b"\x00needle")
    results = service.search_repository_code(root, "needle", max_results=1)

    assert results == [{"path": "main.py", "line": 1, "content": "needle"}]


def test_oversized_files_are_skipped(tmp_path: Path) -> None:
    service, root = create_repository(tmp_path)
    (root / "large.py").write_text("needle" * 100, encoding="utf-8")

    assert service.search_repository_code(root, "needle") == []


def test_read_rejects_traversal_absolute_windows_and_non_python_paths(tmp_path: Path) -> None:
    service, root = create_repository(tmp_path)
    (root / "main.py").write_text("one\ntwo\nthree\n", encoding="utf-8")
    for path in ("../main.py", "C:\\main.py", "/main.py", "README.md"):
        with pytest.raises((ValueError, RepositoryServiceError)):
            service.read_repository_file(root, path)


def test_read_supports_bounded_line_ranges_and_missing_files(tmp_path: Path) -> None:
    service, root = create_repository(tmp_path)
    (root / "main.py").write_text("one\ntwo\nthree\n", encoding="utf-8")

    assert service.read_repository_file(root, "main.py", start_line=2, end_line=3) == {
        "path": "main.py",
        "start_line": 2,
        "end_line": 3,
        "content": "two\nthree",
    }
    with pytest.raises(RepositoryServiceError, match="does not exist"):
        service.read_repository_file(root, "missing.py")
    with pytest.raises(ValueError):
        service.read_repository_file(root, "main.py", start_line=3, end_line=2)


def test_read_rejects_symlink_escape_and_operations_do_not_change_root(tmp_path: Path) -> None:
    service, root = create_repository(tmp_path)
    target = root / "main.py"
    target.write_text("needle", encoding="utf-8")
    external = tmp_path / "external.py"
    external.write_text("secret", encoding="utf-8")
    try:
        (root / "link.py").symlink_to(external)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable in this environment")

    before = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
    with pytest.raises(RepositoryServiceError):
        service.read_repository_file(root, "link.py")
    service.get_repository_tree(root)
    service.search_repository_code(root, "needle")
    after = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
    assert after == before
