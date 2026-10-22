"""Validated registry for explicitly exposed repository tools."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from app.config import Settings
from app.services.repository import RepositoryServiceError
from app.tools.repository_tools import (
    GetRepositoryTreeArguments,
    ReadRepositoryFileArguments,
    SearchRepositoryCodeArguments,
    get_repository_tree,
    read_repository_file,
    search_repository_code,
)

logger = logging.getLogger(__name__)
ArgumentsModel = TypeVar("ArgumentsModel", bound=BaseModel)
ToolCallable = Callable[..., Any]


class ToolResult(BaseModel):
    """Single result shape returned by every registered tool."""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    result: dict[str, Any] | list[Any] | str | None = None
    error: str | None = None

    @model_validator(mode="after")
    def validate_result_state(self) -> "ToolResult":
        if self.ok and self.error is not None:
            raise ValueError("successful tool results cannot contain an error")
        if not self.ok and not self.error:
            raise ValueError("failed tool results must contain an error")
        if self.result is not None:
            try:
                json.dumps(self.result)
            except (TypeError, ValueError) as exc:
                raise ValueError("tool results must be JSON serializable") from exc
        return self


@dataclass(frozen=True)
class ToolRegistration(Generic[ArgumentsModel]):
    """Description and callable for one explicitly registered tool."""

    name: str
    description: str
    arguments_model: type[ArgumentsModel]
    callable: ToolCallable


class ToolRegistry:
    """Deterministic registry that validates every call before execution."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolRegistration[Any]] = {}

    def register(self, registration: ToolRegistration[Any]) -> None:
        if registration.name in self._tools:
            raise ValueError(f"tool already registered: {registration.name}")
        if not registration.name.strip():
            raise ValueError("tool name must not be empty")
        self._tools[registration.name] = registration

    def get(self, name: str) -> ToolRegistration[Any] | None:
        return self._tools.get(name)

    def list_tools(self) -> list[ToolRegistration[Any]]:
        return [self._tools[name] for name in sorted(self._tools)]

    def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        workflow_id: str = "unknown",
    ) -> ToolResult:
        registration = self.get(name)
        if registration is None:
            return ToolResult(ok=False, error=f"unknown tool: {name}")

        try:
            unexpected_arguments = set(arguments) - set(
                registration.arguments_model.model_fields
            )
            if unexpected_arguments:
                unexpected = ", ".join(sorted(unexpected_arguments))
                return ToolResult(
                    ok=False,
                    error=f"invalid arguments for {name}: unexpected fields: {unexpected}",
                )
            parsed_arguments = registration.arguments_model.model_validate(arguments)
        except ValidationError as exc:
            return ToolResult(ok=False, error=f"invalid arguments for {name}: {exc}")

        try:
            result = registration.callable(**parsed_arguments.model_dump())
            try:
                return ToolResult(ok=True, result=result)
            except ValidationError:
                return ToolResult(ok=False, error="tool returned an invalid result")
        except (RepositoryServiceError, ValueError) as exc:
            return ToolResult(ok=False, error=str(exc))
        except Exception:
            logger.error(
                "registered tool failed unexpectedly: tool_name=%s workflow_id=%s",
                name,
                workflow_id,
            )
            return ToolResult(ok=False, error="tool execution failed")


def build_repository_tool_registry(settings: Settings | None = None) -> ToolRegistry:
    """Build a registry containing only the Day 3 repository tools."""

    registry = ToolRegistry()
    registry.register(
        ToolRegistration(
            name="get_repository_tree",
            description="List bounded Python files in a repository workspace.",
            arguments_model=GetRepositoryTreeArguments,
            callable=lambda repository_path: get_repository_tree(
                repository_path,
                settings=settings,
            ),
        )
    )
    registry.register(
        ToolRegistration(
            name="search_repository_code",
            description="Search bounded exact text matches in Python source files.",
            arguments_model=SearchRepositoryCodeArguments,
            callable=lambda repository_path, query, max_results=100: search_repository_code(
                repository_path,
                query,
                max_results=max_results,
                settings=settings,
            ),
        )
    )
    registry.register(
        ToolRegistration(
            name="read_repository_file",
            description="Read a bounded Python source file by repository-relative path.",
            arguments_model=ReadRepositoryFileArguments,
            callable=lambda repository_path, relative_path, start_line=None, end_line=None: read_repository_file(
                repository_path,
                relative_path,
                start_line=start_line,
                end_line=end_line,
                settings=settings,
            ),
        )
    )
    return registry
