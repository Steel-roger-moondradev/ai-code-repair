"""Minimal LangGraph workflow for fetching one GitHub issue."""

from __future__ import annotations

from pathlib import Path

from langgraph.graph import END, START, StateGraph

from app.agents.state import PatchPilotState
from app.agents.issue_analyst import issue_analyst_node
from app.agents.repository_explorer import repository_explorer_node
from app.agents.patch_node import patch_node
from app.config import Settings
from app.schemas.patch import PatchProposal
from app.schemas.workflow import WorkflowStatus, transition_status
from app.services.github import GitHubClient, GitHubServiceError
from app.agents.issue_analyst import LLMAdapter
from app.tools.registry import ToolRegistry
from app.tools.diff_generator import generate_diff
from app.tools.patch_validator import validate_patch
from app.services.sandbox import SandboxService


async def fetch_issue_node(
    state: PatchPilotState,
    github_client: GitHubClient,
) -> PatchPilotState:
    """Fetch the issue and return only fields owned by this node."""

    try:
        issue = await github_client.get_issue(
            state["owner"],
            state["repo"],
            state["issue_number"],
        )
        return {
            "issue": issue,
            "status": transition_status(
                state.get("status", WorkflowStatus.QUEUED),
                WorkflowStatus.RUNNING,
            ),
        }
    except (GitHubServiceError, ValueError) as exc:
        current_status = state.get("status", WorkflowStatus.QUEUED)
        return {
            "status": transition_status(current_status, WorkflowStatus.FAILED),
            "errors": [f"{getattr(exc, 'category', 'invalid_request')}: {exc}"],
        }


def build_issue_workflow(
    github_client: GitHubClient,
    *,
    llm: LLMAdapter | None = None,
    tool_registry: ToolRegistry | None = None,
    settings: Settings | None = None,
    sandbox_service: SandboxService | None = None,
):
    """Compile the issue graph without performing any network calls."""

    graph = StateGraph(PatchPilotState)

    async def fetch_node(state: PatchPilotState) -> PatchPilotState:
        return await fetch_issue_node(state, github_client)

    graph.add_node("fetch_issue", fetch_node)
    if llm is None or tool_registry is None:
        graph.add_edge(START, "fetch_issue")
        graph.add_edge("fetch_issue", END)
    else:
        async def analyze_node(state: PatchPilotState) -> PatchPilotState:
            return await issue_analyst_node(state, llm)

        async def explore_node(state: PatchPilotState) -> PatchPilotState:
            return await repository_explorer_node(
                state,
                tool_registry=tool_registry,
                settings=settings,
            )

        async def patch_proposal_node(state: PatchPilotState) -> PatchPilotState:
            return await patch_node(state, llm)

        async def validate_and_diff_node(state: PatchPilotState) -> PatchPilotState:
            proposal = state.get("proposal")
            if not isinstance(proposal, PatchProposal):
                return {
                    "status": transition_status(
                        state.get("status", WorkflowStatus.RUNNING),
                        WorkflowStatus.FAILED,
                    ),
                    "errors": ["missing_proposal: validator requires a patch proposal"],
                }
            effective_settings = settings
            if effective_settings is None:
                from app.config import get_settings

                effective_settings = get_settings()
            repository_path = (
                Path(effective_settings.repository_root)
                / state["owner"]
                / state["repo"]
            )
            validation = validate_patch(
                repository_path,
                proposal,
                settings=effective_settings,
            )
            if not validation.valid:
                return {
                    "validation": validation,
                    "status": transition_status(
                        state.get("status", WorkflowStatus.RUNNING),
                        WorkflowStatus.FAILED,
                    ),
                    "errors": validation.errors,
                }
            return {
                "validation": validation,
                "diff": generate_diff(repository_path, proposal),
                "status": transition_status(
                    state.get("status", WorkflowStatus.RUNNING),
                    WorkflowStatus.PATCH_READY,
                ),
            }

        graph.add_node("issue_analyst", analyze_node)
        graph.add_node("repository_explorer", explore_node)
        graph.add_node("patch_node", patch_proposal_node)

        async def sandbox_node(state: PatchPilotState) -> PatchPilotState:
            if state.get("validation") is None or not state["validation"].valid:
                return {
                    "status": transition_status(
                        state.get("status", WorkflowStatus.RUNNING),
                        WorkflowStatus.FAILED,
                    ),
                    "errors": ["sandbox rejected: patch validation did not succeed"],
                }
            if state.get("diff") is None or sandbox_service is None:
                return {
                    "status": transition_status(
                        state.get("status", WorkflowStatus.RUNNING),
                        WorkflowStatus.FAILED,
                    ),
                    "errors": ["sandbox unavailable: no sandbox service configured"],
                }
            effective_settings = settings
            if effective_settings is None:
                from app.config import get_settings

                effective_settings = get_settings()
            result = sandbox_service.execute(
                Path(effective_settings.repository_root)
                / state["owner"]
                / state["repo"],
                state["proposal"],
            )
            if result.status != "passed":
                return {
                    "sandbox_result": result,
                    "status": transition_status(
                        state.get("status", WorkflowStatus.PATCH_READY),
                        WorkflowStatus.FAILED,
                    ),
                    "errors": [result.error or "sandbox execution failed"],
                }
            return {"sandbox_result": result}

        graph.add_node("validate_and_diff", validate_and_diff_node)
        if sandbox_service is not None:
            graph.add_node("sandbox", sandbox_node)
        graph.add_edge(START, "fetch_issue")
        graph.add_edge("fetch_issue", "issue_analyst")
        graph.add_edge("issue_analyst", "repository_explorer")
        graph.add_edge("repository_explorer", "patch_node")
        graph.add_edge("patch_node", "validate_and_diff")
        if sandbox_service is not None:
            graph.add_edge("validate_and_diff", "sandbox")
            graph.add_edge("sandbox", END)
        else:
            graph.add_edge("validate_and_diff", END)
    return graph.compile()


def initial_state(
    *,
    owner: str,
    repo: str,
    issue_number: int,
    workflow_id: str,
) -> PatchPilotState:
    """Create the complete initial state before graph invocation."""

    return {
        "owner": owner,
        "repo": repo,
        "issue_number": issue_number,
        "issue": None,
        "analysis": None,
        "repository_tree": [],
        "search_results": [],
        "relevant_files": [],
        "proposal": None,
        "validation": None,
        "diff": None,
        "sandbox_result": None,
        "review": None,
        "workflow_id": workflow_id,
        "status": WorkflowStatus.QUEUED,
        "repair_attempts": 0,
        "errors": [],
    }
