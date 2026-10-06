"""Context MCP module -> control-plane /internal (case context + write tools)."""
from typing import Annotated, Literal

from pydantic import Field

from .http import control


def register(mcp):
    @mcp.tool()
    def context_get_case(case_id: Annotated[int, Field(description="The case id you are working on")]) -> dict:
        """Get the case: state, ticket, previous investigations, reviewer feedback and the approved investigation."""
        return control("GET", f"/internal/cases/{case_id}/context")

    @mcp.tool()
    def context_submit_investigation(
        case_id: Annotated[int, Field(description="The case id you are working on")],
        summary: Annotated[str, Field(description="One or two sentence summary of the problem")],
        root_cause: Annotated[str, Field(description="The likely root cause, naming the file and function")],
        evidence: Annotated[list[str], Field(description="Supporting facts: log lines, code lines, similar past tickets")],
        proposed_fix: Annotated[str, Field(description="The concrete code change you propose")],
        files_to_change: Annotated[list[str], Field(description="Repo paths that need to change")],
        confidence: Annotated[Literal["low", "medium", "high"], Field(description="Your confidence in the root cause")],
    ) -> dict:
        """Submit your investigation report for human review. This finishes the investigation."""
        return control("POST", f"/internal/cases/{case_id}/investigation", json={
            "summary": summary, "root_cause": root_cause, "evidence": evidence, "proposed_fix": proposed_fix,
            "files_to_change": files_to_change, "confidence": confidence})

    @mcp.tool()
    def context_record_pull_request(
        case_id: Annotated[int, Field(description="The case id you are working on")],
        pr_id: Annotated[str, Field(description="PR id returned by repo_create_pull_request, e.g. PR-3")],
        summary: Annotated[str, Field(description="One-line summary of the change")] = "",
    ) -> dict:
        """Link the pull request to the case. This finishes the development task."""
        return control("POST", f"/internal/cases/{case_id}/pull-request", json={"pr_id": pr_id, "summary": summary})
