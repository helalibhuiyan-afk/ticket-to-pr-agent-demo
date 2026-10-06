"""Log MCP module -> demo-service /logs."""
from typing import Annotated

from pydantic import Field

from .http import demo


def register(mcp):
    @mcp.tool()
    def logs_search(
        query: Annotated[str | None, Field(description="Words that must all appear in the message, e.g. 'PaymentError'")] = None,
        service: Annotated[str | None, Field(description="Service name, e.g. 'payments'. Omit to search all services")] = None,
        level: Annotated[str | None, Field(description="Minimum level: DEBUG, INFO, WARN or ERROR")] = None,
        since_minutes: Annotated[int, Field(description="How far back to look")] = 120,
        limit: Annotated[int, Field(description="Max lines to return (<= 50)")] = 30,
    ) -> dict:
        """Search recent application logs. Returns matching lines (oldest first) and the list of known services."""
        params = {"since_minutes": since_minutes, "limit": max(1, min(limit, 50))}
        for name, value in (("query", query), ("service", service), ("level", level)):
            if value:
                params[name] = value
        return demo("GET", "/logs/search", params=params)
