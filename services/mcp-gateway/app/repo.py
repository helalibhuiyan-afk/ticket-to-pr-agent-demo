"""Repository MCP module -> demo-service /repo."""
from typing import Annotated

from pydantic import BaseModel, Field

from .http import demo


class Edit(BaseModel):
    path: str = Field(description="File path relative to the repo root, e.g. orders_service/pricing.py")
    search: str = Field(description="Exact existing text to replace (copied from read_file WITHOUT the line-number "
                                    "prefix, including indentation). Must match exactly once. Empty string = create a new file.")
    replace: str = Field(description="New text that replaces 'search'")


def _summarize(result: dict) -> dict:
    """Keep tool output small for the model."""
    if "error" in result:
        return result
    out = {k: result[k] for k in ("applied", "errors", "tests_passed", "files_changed") if k in result}
    if "test_output" in result:
        out["test_output"] = result["test_output"][-1500:]
    if "diff" in result:
        out["diff"] = result["diff"][:3000]
    return out


def register(mcp):
    @mcp.tool()
    def repo_list_files(path: Annotated[str, Field(description="Optional directory prefix")] = "") -> dict:
        """List files in the demo repository (orders-service)."""
        return demo("GET", "/repo/files", params={"path": path})

    @mcp.tool()
    def repo_read_file(
        path: Annotated[str, Field(description="File path, e.g. orders_service/pricing.py")],
        start_line: Annotated[int, Field(description="First line to return (1-based)")] = 1,
        end_line: Annotated[int | None, Field(description="Last line to return")] = None,
    ) -> dict:
        """Read a file. Each line is prefixed with its line number and '| ' (the prefix is not part of the file)."""
        params = {"start_line": start_line}
        if end_line:
            params["end_line"] = end_line
        return demo("GET", f"/repo/files/{path.lstrip('/')}", params=params)

    @mcp.tool()
    def repo_search_code(query: Annotated[str, Field(description="Case-insensitive text to find, e.g. 'def paginate'")]) -> dict:
        """Search the repository for a string. Returns file paths, line numbers and matching lines."""
        return demo("GET", "/repo/search", params={"q": query})

    @mcp.tool()
    def repo_run_tests(edits: list[Edit]) -> dict:
        """Dry run: apply edits to a scratch copy of the repo, run the unit tests, and return the diff and test results.
        Nothing is saved. Use this to check edits before creating a pull request."""
        return _summarize(demo("POST", "/repo/test", json={"edits": [e.model_dump() for e in edits]}))

    @mcp.tool()
    def repo_create_pull_request(
        case_id: Annotated[int, Field(description="The case id you are working on")],
        title: Annotated[str, Field(description="Short PR title")],
        description: Annotated[str, Field(description="What changed and why; reference the ticket key")],
        edits: list[Edit],
    ) -> dict:
        """Create a pull request from search/replace edits. The edits are applied and the unit tests are run;
        the PR is only created if the edits apply cleanly and all tests pass. Returns the PR id (e.g. PR-3)."""
        result = demo("POST", "/repo/pulls", json={"case_id": case_id, "title": title, "description": description,
                                                    "edits": [e.model_dump() for e in edits]})
        if "error" in result:
            return result
        return {"pr_id": result["id"], "files_changed": result["files_changed"], "tests_passed": result["tests_passed"],
                "next_step": f"Call context_record_pull_request with case_id={case_id} and pr_id={result['id']}"}
