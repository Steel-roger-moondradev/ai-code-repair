"""Safe, bounded operations for Python GitHub repositories."""

from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from app.config import Settings

GITHUB_IDENTIFIER = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]*[A-Za-z0-9])?$")
IGNORED_DIRECTORIES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "build",
    "dist",
    "node_modules",
    ".tox",
}
MAX_SEARCH_RESULTS = 100
MAX_LINE_LENGTH = 4000


class RepositoryServiceError(Exception):
    """Safe, categorized repository operation error."""

    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category
        self.message = message


def parse_github_clone_url(url: str) -> tuple[str, str]:
    """Validate and return owner/repository identifiers from a GitHub URL."""

    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("repository URL must be an HTTPS github.com URL")

    segments = parsed.path.split("/")
    if len(segments) != 3 or segments[0] or not segments[1] or not segments[2]:
        raise ValueError("repository URL must match /OWNER/REPO or /OWNER/REPO.git")

    owner = segments[1]
    repo = segments[2][:-4] if segments[2].endswith(".git") else segments[2]
    if not GITHUB_IDENTIFIER.fullmatch(owner) or not GITHUB_IDENTIFIER.fullmatch(repo):
        raise ValueError("repository URL contains invalid owner or repository")
    return owner, repo


class RepositoryService:
    """Repository clone, tree, search, and read operations."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.repository_root = Path(settings.repository_root).expanduser().resolve()
        self.repository_root.mkdir(parents=True, exist_ok=True)

    def clone_repository(self, clone_url: str) -> Path:
        """Clone a GitHub repository into its deterministic root-contained path."""

        owner, repo = parse_github_clone_url(clone_url)
        target = self._contained_path(Path(owner) / repo)
        if target.exists():
            if not target.is_dir():
                raise RepositoryServiceError("workspace_conflict", "repository path is not a directory")
            if self._origin_url(target) != self._canonical_clone_url(owner, repo):
                raise RepositoryServiceError(
                    "workspace_conflict",
                    "existing repository origin does not match requested repository",
                )
            return target

        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(
                [
                    "git",
                    "clone",
                    "--depth",
                    "1",
                    "--",
                    self._canonical_clone_url(owner, repo),
                    str(target),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=self.settings.request_timeout_seconds,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            self._remove_empty_clone_target(target)
            raise RepositoryServiceError("clone_timeout", "repository clone timed out") from exc
        except (OSError, subprocess.CalledProcessError) as exc:
            self._remove_empty_clone_target(target)
            raise RepositoryServiceError("clone_failed", "repository clone failed") from exc
        return target

    def get_repository_tree(self, repository_path: Path) -> list[str]:
        """List bounded, relative POSIX Python paths without following symlinks."""

        root = self._repository_path(repository_path)
        paths: list[str] = []
        for current, directories, files in self._walk_without_symlinks(root):
            directories[:] = [
                name
                for name in directories
                if name not in IGNORED_DIRECTORIES
                and not (current / name).is_symlink()
            ]
            for name in sorted(files):
                path = current / name
                if path.is_symlink() or path.suffix.lower() != ".py":
                    continue
                paths.append(self._relative_path(root, path))
                if len(paths) >= self.settings.max_repository_files:
                    return paths
        return paths

    def search_repository_code(
        self,
        repository_path: Path,
        query: str,
        *,
        max_results: int = MAX_SEARCH_RESULTS,
    ) -> list[dict[str, Any]]:
        """Search bounded exact text matches in eligible Python files."""

        if not query or len(query) > MAX_LINE_LENGTH:
            raise ValueError("search query must be non-empty and bounded")
        if max_results <= 0:
            raise ValueError("max_results must be positive")

        root = self._repository_path(repository_path)
        results: list[dict[str, Any]] = []
        total_chars = 0
        for path in self.get_repository_tree(root):
            file_path = self._safe_file_path(root, path)
            content = self._read_text(file_path, allow_missing=False)
            if content is None:
                continue
            for line_number, line in enumerate(content.splitlines(), start=1):
                if query not in line:
                    continue
                result = {
                    "path": path,
                    "line": line_number,
                    "content": line[:MAX_LINE_LENGTH],
                }
                encoded_size = len(str(result))
                if total_chars + encoded_size > self.settings.max_context_chars:
                    return results
                results.append(result)
                total_chars += encoded_size
                if len(results) >= min(max_results, MAX_SEARCH_RESULTS):
                    return results
        return results

    def read_repository_file(
        self,
        repository_path: Path,
        relative_path: str,
        *,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> dict[str, Any]:
        """Read a safe bounded Python file and optionally return a line range."""

        root = self._repository_path(repository_path)
        file_path = self._safe_file_path(root, relative_path)
        if start_line is not None and start_line <= 0:
            raise ValueError("start_line must be positive")
        if end_line is not None and end_line <= 0:
            raise ValueError("end_line must be positive")
        if start_line is not None and end_line is not None and start_line > end_line:
            raise ValueError("start_line must not exceed end_line")

        content = self._read_text(file_path, allow_missing=False)
        if content is None:
            raise RepositoryServiceError("file_unreadable", "repository file could not be read")
        lines = content.splitlines()
        first = (start_line or 1) - 1
        last = end_line or len(lines)
        if first > len(lines):
            raise ValueError("start_line is outside the file")
        selected = lines[first:last]
        return {
            "path": self._relative_path(root, file_path),
            "start_line": first + 1,
            "end_line": min(last, len(lines)),
            "content": "\n".join(selected),
        }

    def _repository_path(self, repository_path: Path) -> Path:
        root = self._contained_path(repository_path)
        if not root.is_dir():
            raise RepositoryServiceError("repository_missing", "repository workspace does not exist")
        return root

    def _safe_file_path(self, root: Path, relative_path: str) -> Path:
        if not relative_path or "\\" in relative_path:
            raise ValueError("repository paths must be non-empty POSIX paths")
        pure = PurePosixPath(relative_path)
        if pure.is_absolute() or ".." in pure.parts or any(not part for part in pure.parts):
            raise ValueError("repository path traversal is not allowed")
        if pure.suffix.lower() != ".py":
            raise ValueError("only Python files are supported")
        file_path = root.joinpath(*pure.parts)
        if file_path.is_symlink() or not file_path.is_file():
            raise RepositoryServiceError("file_missing", "repository file does not exist")
        resolved = file_path.resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError("repository path escapes workspace") from exc
        return resolved

    def _read_text(self, file_path: Path, *, allow_missing: bool) -> str | None:
        try:
            if file_path.stat().st_size > self.settings.max_file_bytes:
                return None
            raw = file_path.read_bytes()
            if b"\x00" in raw:
                return None
            return raw.decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            if allow_missing:
                return None
            raise RepositoryServiceError("file_unreadable", "repository file could not be read") from exc

    def _walk_without_symlinks(self, root: Path):
        return root.walk() if hasattr(root, "walk") else self._legacy_walk(root)

    @staticmethod
    def _legacy_walk(root: Path):
        import os

        return ((Path(current), directories, files) for current, directories, files in os.walk(root, followlinks=False))

    def _contained_path(self, path: Path) -> Path:
        candidate = path if path.is_absolute() else self.repository_root / path
        resolved = candidate.resolve()
        try:
            resolved.relative_to(self.repository_root)
        except ValueError as exc:
            raise ValueError("repository path escapes configured root") from exc
        return resolved

    @staticmethod
    def _relative_path(root: Path, path: Path) -> str:
        return path.relative_to(root).as_posix()

    @staticmethod
    def _canonical_clone_url(owner: str, repo: str) -> str:
        return f"https://github.com/{owner}/{repo}.git"

    @staticmethod
    def _origin_url(repository_path: Path) -> str | None:
        try:
            result = subprocess.run(
                ["git", "-C", str(repository_path), "config", "--get", "remote.origin.url"],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
                shell=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        origin = result.stdout.strip().removesuffix("/")
        if origin.endswith(".git"):
            origin = origin[:-4]
        return origin + ".git" if origin else None

    @staticmethod
    def _remove_empty_clone_target(target: Path) -> None:
        if target.exists() and not any(target.iterdir()):
            target.rmdir()
