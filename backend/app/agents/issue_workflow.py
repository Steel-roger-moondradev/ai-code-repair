"""Minimal LangGraph workflow for fetching one GitHub issue."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.agents.state import PatchPilotState
from app.schemas.workflow import WorkflowStatus, transition_status
from app.services.github import GitHubClient, GitHubServiceError


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


def build_issue_workflow(github_client: GitHubClient):
    """Compile the issue graph without performing any network calls."""

    graph = StateGraph(PatchPilotState)

    async def fetch_node(state: PatchPilotState) -> PatchPilotState:
        return await fetch_issue_node(state, github_client)

    graph.add_node("fetch_issue", fetch_node)
    graph.add_edge(START, "fetch_issue")
    graph.add_edge("fetch_issue", END)
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
