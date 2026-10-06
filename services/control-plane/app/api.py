import yaml
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from . import cases, settings, tasks
from .config import SEED_DIR
from .db import connect
from .util import ApiError, json_body

PRIORITIES = {"Low", "Medium", "High", "Critical"}


def _case_id(request: Request) -> int:
    try:
        return int(request.path_params["case_id"])
    except ValueError:
        raise ApiError(400, "case id must be an integer")


# ---------- public API (/api) ----------

async def health(request):
    return JSONResponse({"status": "ok", "service": "control-plane"})


async def info(request):
    """What the UI shows about the running setup, including the selected LLM."""
    with connect() as conn:
        mode = settings.llm_mode(conn)
    options = settings.llm_options()
    current = next(o for o in options if o["id"] == mode)
    return JSONResponse({"llm_mode": mode, "model": current["model"], "provider": current["provider"], "options": options})


async def set_llm(request: Request):
    body = await json_body(request)
    with connect() as conn:
        settings.set_llm_mode(conn, str(body.get("mode") or ""))
    return await info(request)


async def list_scenarios(request):
    path = SEED_DIR / "scenarios.yaml"
    data = yaml.safe_load(path.read_text()) if path.exists() else {}
    return JSONResponse({"scenarios": [
        {k: s.get(k) for k in ("id", "title", "description", "priority")} for s in data.get("scenarios", [])]})


async def create_ticket(request: Request):
    body = await json_body(request)
    title = str(body.get("title") or "").strip()
    if not title:
        raise ApiError(400, "title is required")
    priority = body.get("priority") or "Medium"
    if priority not in PRIORITIES:
        raise ApiError(400, f"priority must be one of {sorted(PRIORITIES)}")
    case = cases.create(title, str(body.get("description") or ""), priority, body.get("scenario_id") or None)
    return JSONResponse(case, status_code=201)


async def list_cases(request):
    return JSONResponse({"cases": cases.list_cases()})


async def get_case(request):
    return JSONResponse(cases.detail(_case_id(request)))


async def get_events(request):
    after = int(request.query_params.get("after", 0))
    return JSONResponse({"events": cases.events(_case_id(request), after)})


async def get_pr(request):
    from . import demo_client
    case = cases.detail(_case_id(request))
    if not case["pull_requests"]:
        raise ApiError(404, "this case has no pull request yet")
    return JSONResponse(demo_client.get_pull(case["pull_requests"][-1]["pr_id"]))


async def approve(request):
    body = await json_body(request)
    return JSONResponse(cases.review(_case_id(request), "approve", str(body.get("comment") or "")))


async def request_changes(request):
    body = await json_body(request)
    return JSONResponse(cases.review(_case_id(request), "request_changes", str(body.get("feedback") or "")))


async def reject(request):
    body = await json_body(request)
    return JSONResponse(cases.review(_case_id(request), "reject", str(body.get("reason") or "")))


async def retry(request):
    return JSONResponse(cases.retry(_case_id(request)))


public_routes = [
    Route("/health", health),
    Route("/info", info),
    Route("/settings/llm", set_llm, methods=["POST"]),
    Route("/scenarios", list_scenarios),
    Route("/tickets", create_ticket, methods=["POST"]),
    Route("/cases", list_cases),
    Route("/cases/{case_id}", get_case),
    Route("/cases/{case_id}/events", get_events),
    Route("/cases/{case_id}/pr", get_pr),
    Route("/cases/{case_id}/approve", approve, methods=["POST"]),
    Route("/cases/{case_id}/request-changes", request_changes, methods=["POST"]),
    Route("/cases/{case_id}/reject", reject, methods=["POST"]),
    Route("/cases/{case_id}/retry", retry, methods=["POST"]),
]


# ---------- internal API (/internal, Compose network only) ----------

async def claim_task(request: Request):
    body = await json_body(request)
    with connect() as conn:
        task = tasks.claim(conn, str(body.get("worker_id") or "agent"))
    return JSONResponse(task) if task else Response(status_code=204)


async def _task_action(request: Request, action: str):
    body = await json_body(request)
    task_id = int(request.path_params["task_id"])
    worker = body.get("worker_id")
    with connect() as conn:
        if action == "heartbeat":
            result = tasks.heartbeat(conn, task_id, worker)
        elif action == "complete":
            result = tasks.complete(conn, task_id, worker)
        else:
            result = tasks.fail(conn, task_id, worker, str(body.get("error") or ""))
    return JSONResponse(result)


async def heartbeat(request):
    return await _task_action(request, "heartbeat")


async def complete(request):
    return await _task_action(request, "complete")


async def fail(request):
    return await _task_action(request, "fail")


async def context(request):
    return JSONResponse(cases.agent_context(_case_id(request)))


async def submit_investigation(request):
    body = await json_body(request)
    return JSONResponse(cases.submit_investigation(_case_id(request), body), status_code=201)


async def record_pr(request):
    body = await json_body(request)
    pr_id = str(body.get("pr_id") or "").strip()
    if not pr_id:
        raise ApiError(400, "pr_id is required")
    return JSONResponse(cases.record_pull_request(_case_id(request), pr_id, str(body.get("summary") or "")),
                        status_code=201)


async def post_event(request):
    body = await json_body(request)
    cases.add_agent_event(_case_id(request), str(body.get("kind")), body.get("payload") or {}, body.get("task_id"))
    return JSONResponse({"ok": True}, status_code=201)


internal_routes = [
    Route("/tasks/claim", claim_task, methods=["POST"]),
    Route("/tasks/{task_id}/heartbeat", heartbeat, methods=["POST"]),
    Route("/tasks/{task_id}/complete", complete, methods=["POST"]),
    Route("/tasks/{task_id}/fail", fail, methods=["POST"]),
    Route("/cases/{case_id}/context", context),
    Route("/cases/{case_id}/investigation", submit_investigation, methods=["POST"]),
    Route("/cases/{case_id}/pull-request", record_pr, methods=["POST"]),
    Route("/cases/{case_id}/events", post_event, methods=["POST"]),
]
