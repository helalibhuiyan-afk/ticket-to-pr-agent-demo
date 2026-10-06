"""Jira MCP module -> demo-service /jira."""
from typing import Annotated

from pydantic import Field

from .http import demo


def register(mcp):
    @mcp.tool()
    def jira_get_ticket(key: Annotated[str, Field(description="Ticket key, e.g. DEMO-101")]) -> dict:
        """Get a Jira ticket with its description, status and comments."""
        return demo("GET", f"/jira/tickets/{key}")

    @mcp.tool()
    def jira_search_tickets(
        query: Annotated[str, Field(description="Keywords, e.g. 'coupon checkout payment'")],
        status: Annotated[str | None, Field(description="Optional status filter, e.g. 'Done' for resolved tickets")] = None,
    ) -> dict:
        """Search tickets by keywords. Resolved ('Done') tickets include a resolution describing past root causes and fixes."""
        params = {"query": query, "limit": 5}
        if status:
            params["status"] = status
        result = demo("GET", "/jira/tickets", params=params)
        for t in result.get("tickets", []):
            for field in ("num", "reporter", "created_at", "updated_at", "scenario_id"):
                t.pop(field, None)
        return result

    @mcp.tool()
    def jira_add_comment(
        key: Annotated[str, Field(description="Ticket key, e.g. DEMO-101")],
        body: Annotated[str, Field(description="Comment text")],
    ) -> dict:
        """Add a comment to a Jira ticket."""
        result = demo("POST", f"/jira/tickets/{key}/comments", json={"author": "ticket-to-pr-agent", "body": body})
        return {"ok": True} if "error" not in result else result
