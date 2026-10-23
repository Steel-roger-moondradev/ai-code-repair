"""Offline tests for disposable Docker sandbox execution."""

import subprocess

from app.config import Settings
from app.schemas.patch import FileChange, PatchProposal
from app.services.sandbox import MAX_OUTPUT_CHARS, SandboxService


def proposal(original: str = "value = 1\n", updated: str = "value = 2\n") -> PatchProposal:
    return PatchProposal(
        summary="change value",
        assumptions=[],
        risks=[],
        tests_to_add=[],
        changes=[
            FileChange(
                path="main.py",
                operation="modify",
                rationale="update value",
                original_content=original,
                updated_content=updated,
            )
        ],
    )


class FakeRunner:
    def __init__(self, completed=None, error=None):
        self.completed = completed
        self.error = error
        self.arguments = None

    def run(self, arguments, *, timeout):
        self.arguments = arguments
        if self.error is not None:
            raise self.error
        return self.completed


def service(tmp_path, runner):
    return SandboxService(
        Settings(workspace_root=str(tmp_path / "workspaces")),
        runner=runner,
    )


def repository(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "main.py").write_text("value = 1\n", encoding="utf-8")
    return root


def test_passed_run_uses_fixed_restricted_command_and_cleans_workspace(tmp_path):
    runner = FakeRunner(subprocess.CompletedProcess([], 0, "1 passed\n", ""))
    sandbox = service(tmp_path, runner)
    source = repository(tmp_path)

    result = sandbox.execute(source, proposal())

    assert result.status == "passed"
    assert result.exit_code == 0
    assert result.timed_out is False
    assert list((tmp_path / "workspaces").iterdir()) == []
    assert source.joinpath("main.py").read_text(encoding="utf-8") == "value = 1\n"
    assert "--network" in runner.arguments
    assert runner.arguments[runner.arguments.index("--network") + 1] == "none"
    assert "docker.sock" not in " ".join(runner.arguments)
    assert "GROQ_API_KEY" not in " ".join(runner.arguments)
    assert runner.arguments[-3:] == ["-m", "pytest", "-q"]


def test_failed_run_preserves_exit_code_and_output(tmp_path):
    runner = FakeRunner(subprocess.CompletedProcess([], 1, "2 failed\n", "failure"))
    result = service(tmp_path, runner).execute(repository(tmp_path), proposal())

    assert result.status == "failed"
    assert result.exit_code == 1
    assert result.error == "sandbox tests failed"
    assert result.test_summary == "2 failed"


def test_timeout_is_explicit_and_cleanup_runs(tmp_path):
    runner = FakeRunner(error=subprocess.TimeoutExpired(["docker"], 1))
    result = service(tmp_path, runner).execute(repository(tmp_path), proposal())

    assert result.status == "timed_out"
    assert result.timed_out is True
    assert result.exit_code is None
    assert list((tmp_path / "workspaces").iterdir()) == []


def test_docker_unavailable_is_infrastructure_error(tmp_path):
    result = service(tmp_path, FakeRunner(error=FileNotFoundError("docker"))).execute(
        repository(tmp_path), proposal()
    )

    assert result.status == "infrastructure_error"
    assert result.exit_code is None
    assert "unavailable" in result.error


def test_invalid_patch_is_rejected_without_runner_call(tmp_path):
    runner = FakeRunner(subprocess.CompletedProcess([], 0, "", ""))
    invalid = proposal(original="wrong\n")
    result = service(tmp_path, runner).execute(repository(tmp_path), invalid)

    assert result.status == "rejected"
    assert runner.arguments is None


def test_output_is_bounded(tmp_path):
    runner = FakeRunner(
        subprocess.CompletedProcess([], 1, "x" * (MAX_OUTPUT_CHARS + 10), "")
    )
    result = service(tmp_path, runner).execute(repository(tmp_path), proposal())

    assert len(result.stdout) <= MAX_OUTPUT_CHARS + len("\n...[output truncated]...")
    assert "output truncated" in result.stdout


def test_workspace_paths_are_contained(tmp_path):
    sandbox = service(tmp_path, FakeRunner())
    outside = tmp_path / "outside"
    outside.mkdir()

    import pytest

    with pytest.raises(ValueError):
        sandbox.build_docker_arguments(outside)
