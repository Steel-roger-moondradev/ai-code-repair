"""Thin, explicit wrappers for safe repository operations."""

from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from app.services.repository import RepositoryService


def get_repository_tree(
    repository_path: Path,
    settings: Settings | None = None,
) -> list[str]:
    """Return bounded Python paths from a repository workspace."""

    return RepositoryService(settings or get_settings()).get_repository_tree(repository_path)


def search_repository_code(
    repository_path: Path,
    query: str,
    *,
    max_results: int = 100,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """Return bounded exact matches from Python source files."""

    return RepositoryService(settings or get_settings()).search_repository_code(
        repository_path,
        query,
        max_results=max_results,
    )


def read_repository_file(
    repository_path: Path,
    relative_path: str,
    *,
    start_line: int | None = None,
    end_line: int | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Read a bounded Python source file."""

    return RepositoryService(settings or get_settings()).read_repository_file(
        repository_path,
        relative_path,
        start_line=start_line,
        end_line=end_line,
    )
