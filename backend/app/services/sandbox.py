"""Disposable Docker sandbox for applying and testing validated proposals."""

from __future__ import annotations

import shutil
import os
import subprocess
import time
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from app.config import Settings, get_settings
from app.schemas.patch import PatchProposal
from app.schemas.sandbox import SandboxResult
from app.tools.patch_validator import validate_patch

MAX_OUTPUT_CHARS = 12_000
SANDBOX_IMAGE = "patchpilot-sandbox:latest"


class DockerRunner(Protocol):
    """Small interface that keeps Docker execution replaceable in tests."""

    def run(self, arguments: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
        ...


class SubprocessDockerRunner:
    """Docker CLI runner with no shell interpretation."""

    def run(self, arguments: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["docker", *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )


class SandboxService:
    """Create isolated copies, apply validated changes, and run fixed tests."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        runner: DockerRunner | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.runner = runner or SubprocessDockerRunner()
        self.workspace_root = Path(self.settings.workspace_root).expanduser().resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True)

    def execute(
        self,
        repository_path: Path,
        proposal: PatchProposal,
    ) -> SandboxResult:
        started = time.monotonic()
        workspace: Path | None = None
        try:
            source = repository_path.expanduser().resolve()
            if not source.is_dir():
                return self._result(
                    started,
                    status="rejected",
                    error="repository path is not a directory",
                )
            workspace = self._create_workspace()
            self._copy_repository(source, workspace)
            result = self._execute_in_workspace(workspace, proposal, started)
        except (OSError, ValueError) as exc:
            result = self._result(
                started,
                status="infrastructure_error",
                error=f"sandbox setup failed: {exc}",
            )
        if workspace is not None:
            try:
                shutil.rmtree(workspace)
            except OSError as exc:
                cleanup_error = f"sandbox cleanup failed: {exc}"
                result = result.model_copy(
                    update={
                        "error": (
                            f"{result.error}; {cleanup_error}"
                            if result.error
                            else cleanup_error
                        )
                    }
                )
        return result

    def _execute_in_workspace(
        self,
        workspace: Path,
        proposal: PatchProposal,
        started: float,
    ) -> SandboxResult:
        validation = validate_patch(workspace, proposal, settings=self.settings)
        if not validation.valid:
            return self._result(
                started,
                status="rejected",
                error="patch validation failed: " + "; ".join(validation.errors),
            )
        self._apply_patch(workspace, proposal)
        arguments = self.build_docker_arguments(workspace)
        try:
            completed = self.runner.run(
                arguments,
                timeout=self.settings.sandbox_timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return self._result(
                started,
                status="timed_out",
                timed_out=True,
                error="sandbox execution timed out",
            )
        except (FileNotFoundError, OSError) as exc:
            return self._result(
                started,
                status="infrastructure_error",
                error=f"sandbox infrastructure unavailable: {exc}",
            )
        stdout = _truncate(completed.stdout or "")
        stderr = _truncate(completed.stderr or "")
        passed = completed.returncode == 0
        return self._result(
            started,
            status="passed" if passed else "failed",
            exit_code=completed.returncode,
            stdout=stdout,
            stderr=stderr,
            test_summary=_summary(completed.returncode, stdout, stderr),
            error=None if passed else "sandbox tests failed",
        )

    def build_docker_arguments(self, workspace: Path) -> list[str]:
        """Build the fixed, non-networked Docker command argument array."""

        resolved = workspace.resolve()
        resolved.relative_to(self.workspace_root)
        return [
            "run",
            "--rm",
            "--network",
            "none",
            "--cpus",
            "1.0",
            "--memory",
            "512m",
            "--pids-limit",
            "128",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=64m",
            "--mount",
            f"type=bind,source={resolved},target=/workspace,readonly",
            "--workdir",
            "/workspace",
            SANDBOX_IMAGE,
            "-m",
            "pytest",
            "-q",
        ]

    def _create_workspace(self) -> Path:
        workspace = (self.workspace_root / uuid4().hex).resolve()
        workspace.relative_to(self.workspace_root)
        workspace.mkdir(parents=True, exist_ok=False)
        return workspace

    @staticmethod
    def _copy_repository(source: Path, workspace: Path) -> None:
        for current, directories, files in os.walk(source):
            for name in [*directories, *files]:
                if Path(current, name).is_symlink():
                    raise ValueError("source repository contains a symlink")
        for item in source.iterdir():
            if item.name == ".git":
                continue
            destination = workspace / item.name
            if item.is_symlink():
                raise ValueError("source repository contains a symlink")
            if item.is_dir():
                shutil.copytree(
                    item,
                    destination,
                    symlinks=False,
                    ignore=shutil.ignore_patterns(".git"),
                )
            else:
                shutil.copy2(item, destination)

    def _apply_patch(self, workspace: Path, proposal: PatchProposal) -> None:
        for change in proposal.changes:
            target = workspace.joinpath(*change.path.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(change.updated_content, encoding="utf-8")

    def _result(
        self,
        started: float,
        *,
        status: str,
        exit_code: int | None = None,
        stdout: str = "",
        stderr: str = "",
        timed_out: bool = False,
        test_summary: str = "",
        error: str | None = None,
    ) -> SandboxResult:
        return SandboxResult(
            status=status,
            exit_code=exit_code,
            stdout=_truncate(stdout),
            stderr=_truncate(stderr),
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
            timed_out=timed_out,
            test_summary=test_summary,
            error=error,
        )


def _truncate(output: str) -> str:
    if len(output) <= MAX_OUTPUT_CHARS:
        return output
    return output[:MAX_OUTPUT_CHARS] + "\n...[output truncated]..."


def _summary(exit_code: int, stdout: str, stderr: str) -> str:
    output = (stdout or stderr).strip().splitlines()
    return output[-1] if output else f"pytest exited with code {exit_code}"
