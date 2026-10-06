"""Agent worker: polls the control plane for tasks and runs them with an LLM + MCP tools.

One task at a time. A role = system prompt + tool allowlist + step budget + the tool that finishes it.
"""
import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from mcp import Client

from . import control, llm
from .config import BACKENDS, HEARTBEAT_SECONDS, LLM_MODEL, MAX_TOOL_RESULT_CHARS, MCP_URL, POLL_SECONDS, WORKER_ID

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("agent")
for noisy in ("httpx", "httpx2", "httpcore", "httpcore2", "mcp"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
ROLES_DIR = Path(__file__).parent / "roles"


@dataclass
class Role:
    name: str
    prompt_file: str
    tools: list[str]
    finish_tool: str
    max_tool_calls: int


ROLES = {
    "INVESTIGATE": Role("investigator", "investigator.md", [
        "context_get_case", "logs_search", "jira_get_ticket", "jira_search_tickets",
        "repo_list_files", "repo_read_file", "repo_search_code", "context_submit_investigation",
    ], "context_submit_investigation", 20),
    "DEVELOP": Role("developer", "developer.md", [
        "context_get_case", "repo_list_files", "repo_read_file", "repo_search_code", "repo_run_tests",
        "repo_create_pull_request", "context_record_pull_request", "jira_add_comment",
    ], "context_record_pull_request", 25),
}


class TaskFailed(Exception):
    pass


def _inline_refs(schema: dict) -> dict:
    """Resolve local $ref/$defs: some OpenAI-compatible servers (e.g. Ollama) don't follow them."""
    defs = schema.get("$defs", {})

    def resolve(node):
        if isinstance(node, dict):
            if "$ref" in node and node["$ref"].startswith("#/$defs/"):
                return resolve(defs[node["$ref"].split("/")[-1]])
            return {k: resolve(v) for k, v in node.items() if k not in ("$defs", "title")}
        if isinstance(node, list):
            return [resolve(v) for v in node]
        return node

    return resolve(schema)


def _openai_tools(mcp_tools, allowed: list[str]) -> list[dict]:
    return [{"type": "function", "function": {
        "name": t.name, "description": t.description or "", "parameters": _inline_refs(t.input_schema)}}
        for t in mcp_tools if t.name in allowed]


def _result_text(result) -> str:
    parts = [c.text for c in result.content if getattr(c, "type", "") == "text"]
    text = "\n".join(parts) or json.dumps(result.structured_content or {})
    if len(text) > MAX_TOOL_RESULT_CHARS:
        text = text[:MAX_TOOL_RESULT_CHARS] + f"\n...[truncated {len(text) - MAX_TOOL_RESULT_CHARS} chars]"
    return text


def _is_error(result, text: str) -> bool:
    if result.is_error:
        return True
    try:
        data = json.loads(text)
    except ValueError:
        return False
    # "error" from a backend, or a dry run whose edits didn't apply / tests failed
    return isinstance(data, dict) and ("error" in data or data.get("applied") is False or data.get("tests_passed") is False)


async def _event(task: dict, kind: str, payload: dict) -> None:
    await asyncio.to_thread(control.event, task["case_id"], task["id"], kind, payload)


async def _heartbeat(task_id: int) -> None:
    while True:
        await asyncio.sleep(HEARTBEAT_SECONDS)
        try:
            await asyncio.to_thread(control.heartbeat, task_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("heartbeat failed: %s", exc)


async def run_role(task: dict) -> None:
    role = ROLES[task["type"]]
    case_id = task["case_id"]
    mode = task.get("llm_mode") if task.get("llm_mode") in BACKENDS else "real"
    model = BACKENDS[mode]["model"]
    system = (ROLES_DIR / role.prompt_file).read_text()
    user = (f"Case id: {case_id}\nTicket: {task['ticket_key']}\n"
            f"Start by calling context_get_case with case_id={case_id}. "
            f"You have at most {role.max_tool_calls} tool calls. Finish by calling {role.finish_tool}.")
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]

    async with Client(MCP_URL) as mcp:
        tools = _openai_tools((await mcp.list_tools()).tools, role.tools)
        await _event(task, "info", {"message": f"{role.name} started with model {model} ({mode} LLM)",
                                    "tools": [t["function"]["name"] for t in tools]})
        tool_calls_used, nudged = 0, False
        while tool_calls_used < role.max_tool_calls:
            message, stats = await asyncio.to_thread(llm.chat, messages, tools, mode)
            content = message.get("content") or ""
            reasoning = message.get("reasoning") or message.get("reasoning_content") or ""
            calls = message.get("tool_calls") or []
            await _event(task, "llm_message", {"role": role.name, "content": content, "reasoning": reasoning[:4000],
                                               "tool_calls": [c["function"]["name"] for c in calls], "model": model, **stats})
            for c in calls:
                c.setdefault("id", f"call_{uuid.uuid4().hex[:8]}")
                c.setdefault("type", "function")
            messages.append({"role": "assistant", "content": content, "tool_calls": calls} if calls
                            else {"role": "assistant", "content": content})

            if not calls:
                if nudged:
                    raise TaskFailed(f"model stopped without calling {role.finish_tool}")
                nudged = True
                messages.append({"role": "user", "content": f"You have not finished. Continue using tools, and "
                                                            f"you must call {role.finish_tool} to finish."})
                continue

            for call in calls:
                tool_calls_used += 1
                name = call["function"]["name"]
                raw_args = call["function"].get("arguments") or "{}"
                started = time.monotonic()
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
                except ValueError:
                    args, text, error = None, json.dumps({"error": "arguments were not valid JSON; try again"}), True
                if args is not None:
                    if "case_id" in args or name.startswith("context_") or name == "repo_create_pull_request":
                        args["case_id"] = case_id  # guardrail: never let the model act on another case
                    await _event(task, "tool_call", {"name": name, "arguments": args})
                    if name not in role.tools:
                        text, error = json.dumps({"error": f"tool {name} is not available to the {role.name}"}), True
                    else:
                        result = await mcp.call_tool(name, args)
                        text = _result_text(result)
                        error = _is_error(result, text)
                await _event(task, "tool_result", {"name": name, "is_error": error, "result": text[:3000],
                                                   "seconds": round(time.monotonic() - started, 2)})
                messages.append({"role": "tool", "tool_call_id": call["id"], "name": name, "content": text})
                if name == role.finish_tool and not error:
                    return
        raise TaskFailed(f"tool-call budget of {role.max_tool_calls} used up without calling {role.finish_tool}")


async def finalize(task: dict) -> bool:
    """Recover a finished-but-unrecorded result. Returns True if the task's goal is met."""
    if task["type"] == "DEVELOP":
        state = await asyncio.to_thread(control.case_state, task["case_id"])
        if state == "DEVELOPING":
            pr_id = await asyncio.to_thread(control.unrecorded_pr, task["case_id"])
            if pr_id:
                await asyncio.to_thread(control.record_pr, task["case_id"], pr_id)
                await _event(task, "info", {"message": f"worker recorded {pr_id} that the model created but did not record"})
                return True
    return False


def _root_cause(exc: BaseException) -> BaseException:
    """MCP's client wraps errors raised inside it in exception groups; surface the real one."""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return exc


async def handle(task: dict) -> None:
    log.info("task %s: %s for case %s (%s), attempt %s", task["id"], task["type"], task["case_id"],
             task["ticket_key"], task["attempts"])
    hb = asyncio.create_task(_heartbeat(task["id"]))
    try:
        try:
            await run_role(task)
        except Exception as exc:  # noqa: BLE001
            if not await finalize(task):
                raise
            log.info("task %s recovered by finalization after: %s", task["id"], exc)
        result = await asyncio.to_thread(control.complete, task["id"])
        log.info("task %s finished: %s", task["id"], result)
    except Exception as exc:  # noqa: BLE001
        log.exception("task %s failed", task["id"])
        exc = _root_cause(exc)
        await _event(task, "error", {"message": "agent error", "error": str(exc)[:2000]})
        try:
            result = await asyncio.to_thread(control.fail, task["id"], f"{type(exc).__name__}: {exc}")
            log.info("task %s marked: %s", task["id"], result)
        except Exception:  # noqa: BLE001
            log.exception("could not report failure; lease will expire")
    finally:
        hb.cancel()


async def main() -> None:
    log.info("agent %s starting; model=%s mcp=%s", WORKER_ID, LLM_MODEL, MCP_URL)
    while True:
        try:
            task = await asyncio.to_thread(control.claim)
        except Exception as exc:  # noqa: BLE001
            log.warning("control plane not reachable yet: %s", exc)
            await asyncio.sleep(POLL_SECONDS * 2)
            continue
        if task:
            await handle(task)
        else:
            await asyncio.sleep(POLL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
