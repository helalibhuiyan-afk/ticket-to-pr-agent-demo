"""MCP gateway: one MCP server exposing the jira, logs, repo and context modules over streamable HTTP."""
from mcp.server import MCPServer
from starlette.responses import JSONResponse

from . import context, jira, logs, repo

mcp = MCPServer("ticket-to-pr-gateway")
for module in (jira, logs, repo, context):
    module.register(mcp)


@mcp.custom_route("/health", methods=["GET"])
async def health(request):
    return JSONResponse({"status": "ok", "service": "mcp-gateway"})


app = mcp.streamable_http_app(streamable_http_path="/mcp", host="0.0.0.0")
