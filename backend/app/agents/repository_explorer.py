"""Deterministic Python repository exploration node."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from app.agents.state import PatchPilotState
from app.config import Settings, get_settings
from app.schemas.workflow import WorkflowStatus, transition_status
from app.tools.registry import ToolRegistry, build_repository_tool_registry


async def repository_explorer_node(
    state: PatchPilotState,
    *,
    tool_registry: ToolRegistry,
    settings: Settings | None = None,
    max_keywords: int = 8,
    max_files: int = 5,
) -> PatchPilotState:
    """Search and read bounded Python context with source provenance."""

    settings = settings or get_settings()
    analysis = state.get("analysis")
    if analysis is None:
        return _failure(state, "missing_analysis: analysis must be produced first")

    repository_path = Path(state["owner"]) / state["repo"]
    tree_result = tool_registry.execute(
        "get_repository_tree",
        {"repository_path": repository_path},
        workflow_id=state.get("workflow_id", "unknown"),
    )
    if not tree_result.ok:
        return _failure(state, f"repository_tree_failed: {tree_result.error}")

    keywords = [
        keyword
        for keyword in analysis.keywords
        if isinstance(keyword, str) and keyword.strip()
    ][:max_keywords]
    search_results: list[dict[str, Any]] = []
    for keyword in keywords:
        result = tool_registry.execute(
            "search_repository_code",
            {"repository_path": repository_path, "query": keyword, "max_results": 20},
            workflow_id=state.get("workflow_id", "unknown"),
        )
        if result.ok and isinstance(result.result, list):
            search_results.extend(result.result)

    ranked_paths = _rank_paths(search_results, keywords)[:max_files]
    relevant_files: list[dict[str, Any]] = []
    for path in ranked_paths:
        result = tool_registry.execute(
            "read_repository_file",
            {"repository_path": repository_path, "relative_path": path},
            workflow_id=state.get("workflow_id", "unknown"),
        )
        if not result.ok or not isinstance(result.result, dict):
            continue
        content = result.result["content"]
        relevant_files.append(
            {
                "path": result.result["path"],
                "start_line": result.result["start_line"],
                "end_line": result.result["end_line"],
                "content": content,
                "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            }
        )

    return {
        "repository_tree": tree_result.result if isinstance(tree_result.result, list) else [],
        "search_results": search_results,
        "relevant_files": relevant_files,
        "status": state.get("status", WorkflowStatus.RUNNING),
    }


def _rank_paths(results: list[dict[str, Any]], keywords: list[str]) -> list[str]:
    scores: dict[str, int] = {}
    for result in results:
        path = result.get("path")
        content = result.get("content", "")
        if not isinstance(path, str):
            continue
        score = scores.get(path, 0) + 1
        score += sum(1 for keyword in keywords if keyword in content)
        scores[path] = score
    return [
        path
        for path, _score in sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    ]


def _failure(state: PatchPilotState, error: str) -> PatchPilotState:
    current_status = state.get("status", WorkflowStatus.RUNNING)
    return {
        "status": (
            current_status
            if current_status == WorkflowStatus.FAILED
            else transition_status(current_status, WorkflowStatus.FAILED)
        ),
        "errors": [error],
    }
