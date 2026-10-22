"""Tests for explicit, schema-validated tool registration."""

from pathlib import Path

import pytest
from pydantic import BaseModel

from app.config import Settings
from app.services.repository import RepositoryServiceError
from app.tools.registry import (
    ToolRegistration,
    ToolRegistry,
    ToolResult,
    build_repository_tool_registry,
)


def test_tool_result_enforces_one_consistent_shape() -> None:
    assert ToolResult(ok=True, result={"value": 1}).model_dump() == {
        "ok": True,
        "result": {"value": 1},
        "error": None,
    }
    with pytest.raises(ValueError):
        ToolResult(ok=True, error="not allowed")
    with pytest.raises(ValueError):
        ToolResult(ok=False)
    with pytest.raises(ValueError):
        ToolResult(ok=True, result=object())


def test_valid_call_passes_typed_arguments_and_returns_json_result() -> None:
    class Arguments(BaseModel):
        value: int

    registry = ToolRegistry()
    registry.register(
        ToolRegistration(
            name="double",
            description="Double a number.",
            arguments_model=Arguments,
            callable=lambda value: {"value": value * 2},
        )
    )

    result = registry.execute("double", {"value": 3})

    assert result == ToolResult(ok=True, result={"value": 6})


def test_missing_extra_and_incorrect_arguments_do_not_invoke_callable() -> None:
    class Arguments(BaseModel):
        value: int

    invoked = False

    def callable(value: int) -> int:
        nonlocal invoked
        invoked = True
        return value

    registry = ToolRegistry()
    registry.register(ToolRegistration("identity", "Identity.", Arguments, callable))

    for arguments in ({}, {"value": "bad"}, {"value": 1, "extra": True}):
        result = registry.execute("identity", arguments)
        assert result.ok is False
        assert "invalid arguments" in result.error
    assert invoked is False


def test_unknown_tools_never_trigger_dynamic_lookup() -> None:
    registry = ToolRegistry()

    result = registry.execute("run_arbitrary_command", {"command": "whoami"})

    assert result == ToolResult(ok=False, error="unknown tool: run_arbitrary_command")


def test_duplicate_registration_is_rejected() -> None:
    class Arguments(BaseModel):
        pass

    registry = ToolRegistry()
    registration = ToolRegistration("same", "Same.", Arguments, lambda: "ok")
    registry.register(registration)

    with pytest.raises(ValueError, match="already registered"):
        registry.register(registration)


def test_expected_and_unexpected_callable_errors_are_safe(caplog) -> None:
    class Arguments(BaseModel):
        pass

    registry = ToolRegistry()
    registry.register(
        ToolRegistration(
            "expected",
            "Expected failure.",
            Arguments,
            lambda: (_ for _ in ()).throw(RepositoryServiceError("failure", "safe expected error")),
        )
    )
    registry.register(
        ToolRegistration(
            "unexpected",
            "Unexpected failure.",
            Arguments,
            lambda: (_ for _ in ()).throw(RuntimeError("secret internal detail")),
        )
    )

    expected = registry.execute("expected", {}, workflow_id="workflow-1")
    with caplog.at_level("ERROR"):
        unexpected = registry.execute("unexpected", {}, workflow_id="workflow-2")

    assert expected == ToolResult(ok=False, error="safe expected error")
    assert unexpected == ToolResult(ok=False, error="tool execution failed")
    assert "workflow-2" in caplog.text
    assert "secret internal detail" not in unexpected.error


def test_repository_registry_exposes_only_three_tools(tmp_path: Path) -> None:
    settings = Settings(repository_root=str(tmp_path / "repositories"))
    registry = build_repository_tool_registry(settings)

    assert [tool.name for tool in registry.list_tools()] == [
        "get_repository_tree",
        "read_repository_file",
        "search_repository_code",
    ]
    assert registry.get("execute_shell") is None


def test_repository_tool_validation_precedes_callable(tmp_path: Path) -> None:
    settings = Settings(repository_root=str(tmp_path / "repositories"))
    registry = build_repository_tool_registry(settings)

    result = registry.execute(
        "read_repository_file",
        {"repository_path": str(tmp_path), "relative_path": "../secret.py"},
    )

    assert result.ok is False
    assert "tool execution failed" not in result.error
