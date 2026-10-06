"""Case read models and actions (shared by the public and internal APIs)."""
import json
import logging

from . import demo_client, tasks
from . import state_machine as sm
from .db import add_event, connect, rows
from .util import ApiError, now_iso

log = logging.getLogger("control-plane")
CONFIDENCE = {"low", "medium", "high"}


def _investigation_out(row: dict) -> dict:
    row = dict(row)
    row["evidence"] = json.loads(row.pop("evidence_json"))
    row["files_to_change"] = json.loads(row.pop("files_to_change_json"))
    return row


def _jira_side_effect(case_id: int, fn, *args) -> None:
    """Best-effort update of the fake Jira; failures are recorded but never block the workflow."""
    try:
        fn(*args)
    except ApiError as exc:
        log.warning("jira side effect failed: %s", exc.detail)
        with connect() as conn:
            add_event(conn, case_id, "error", {"message": "Jira update failed", "error": exc.detail})


def create(title: str, description: str, priority: str, scenario_id: str | None) -> dict:
    ticket = demo_client.create_ticket(title, description, priority, scenario_id)
    ts = now_iso()
    with connect() as conn:
        cur = conn.execute("INSERT INTO cases (ticket_key, ticket_title, scenario_id, state, created_at, updated_at)"
                           " VALUES (?,?,?,?,?,?)", (ticket["key"], ticket["title"], scenario_id, sm.NEW, ts, ts))
        case_id = cur.lastrowid
        add_event(conn, case_id, "state_change", {"from": None, "to": sm.NEW, "reason": f"ticket {ticket['key']} created"})
        tasks.enqueue(conn, case_id, tasks.INVESTIGATE)
    return detail(case_id)


def list_cases() -> list[dict]:
    with connect() as conn:
        cases = rows(conn.execute("SELECT * FROM cases ORDER BY id DESC"))
        for c in cases:
            c["current_task"] = tasks.current_task(conn, c["id"])
            pr = conn.execute("SELECT pr_id FROM case_prs WHERE case_id=? ORDER BY created_at DESC LIMIT 1",
                              (c["id"],)).fetchone()
            c["pr_id"] = pr["pr_id"] if pr else None
    return cases


def _load(conn, case_id: int) -> dict:
    case = sm.get_case(conn, case_id)
    case["investigations"] = [_investigation_out(r) for r in rows(conn.execute(
        "SELECT * FROM investigations WHERE case_id=? ORDER BY version", (case_id,)))]
    case["reviews"] = rows(conn.execute("SELECT * FROM reviews WHERE case_id=? ORDER BY id", (case_id,)))
    case["pull_requests"] = rows(conn.execute("SELECT * FROM case_prs WHERE case_id=? ORDER BY created_at", (case_id,)))
    case["current_task"] = tasks.current_task(conn, case_id)
    return case


def detail(case_id: int) -> dict:
    with connect() as conn:
        case = _load(conn, case_id)
    try:
        case["ticket"] = demo_client.get_ticket(case["ticket_key"])
    except ApiError as exc:
        case["ticket"] = None
        case["ticket_error"] = exc.detail
    return case


def agent_context(case_id: int) -> dict:
    """What the agent sees about a case."""
    case = detail(case_id)
    ticket = case.get("ticket") or {}
    approved = None
    feedback = []
    for review in case["reviews"]:
        inv = next((i for i in case["investigations"] if i["id"] == review["investigation_id"]), None)
        if review["decision"] == "approve":
            approved = inv
        elif review["decision"] == "request_changes":
            feedback.append({"investigation_version": inv["version"] if inv else None, "feedback": review["comment"]})
    return {
        "case_id": case["id"],
        "state": case["state"],
        "ticket_key": case["ticket_key"],
        "ticket": {k: ticket.get(k) for k in ("title", "description", "priority", "status", "comments")},
        "investigations": [{k: i[k] for k in ("version", "summary", "root_cause", "evidence", "proposed_fix",
                                              "files_to_change", "confidence")} for i in case["investigations"]],
        "reviewer_feedback": feedback,
        "approved_investigation": approved and {k: approved[k] for k in (
            "version", "summary", "root_cause", "proposed_fix", "files_to_change")},
        "pull_requests": [p["pr_id"] for p in case["pull_requests"]],
    }


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    return [str(v) for v in value]


def submit_investigation(case_id: int, body: dict) -> dict:
    missing = [f for f in ("summary", "root_cause", "proposed_fix") if not str(body.get(f) or "").strip()]
    if missing:
        raise ApiError(400, f"missing required fields: {', '.join(missing)}")
    confidence = str(body.get("confidence") or "medium").lower()
    if confidence not in CONFIDENCE:
        confidence = "medium"
    with connect() as conn:
        case = sm.get_case(conn, case_id)
        if case["state"] != sm.INVESTIGATING:
            raise ApiError(409, f"case {case_id} is {case['state']}; investigations can only be submitted while INVESTIGATING")
        version = conn.execute("SELECT COALESCE(MAX(version),0)+1 FROM investigations WHERE case_id=?",
                               (case_id,)).fetchone()[0]
        conn.execute(
            "INSERT INTO investigations (case_id, version, summary, root_cause, evidence_json, proposed_fix,"
            " files_to_change_json, confidence, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (case_id, version, body["summary"].strip(), body["root_cause"].strip(),
             json.dumps(_as_list(body.get("evidence"))), body["proposed_fix"].strip(),
             json.dumps(_as_list(body.get("files_to_change"))), confidence, now_iso()))
        sm.transition(conn, case_id, sm.AWAITING_APPROVAL, f"investigation v{version} submitted")
        key = case["ticket_key"]
    _jira_side_effect(case_id, demo_client.comment, key,
                      f"Investigation v{version} ready for review.\n\nRoot cause: {body['root_cause'].strip()}\n\n"
                      f"Proposed fix: {body['proposed_fix'].strip()}")
    _jira_side_effect(case_id, demo_client.set_status, key, "In Progress")
    return {"case_id": case_id, "version": version, "state": sm.AWAITING_APPROVAL}


def record_pull_request(case_id: int, pr_id: str, summary: str = "") -> dict:
    pr = demo_client.get_pull(pr_id)
    if pr.get("case_id") not in (None, case_id):
        raise ApiError(400, f"{pr_id} belongs to case {pr['case_id']}, not case {case_id}")
    with connect() as conn:
        case = sm.get_case(conn, case_id)
        if case["state"] != sm.DEVELOPING:
            raise ApiError(409, f"case {case_id} is {case['state']}; PRs can only be recorded while DEVELOPING")
        conn.execute("INSERT OR IGNORE INTO case_prs (case_id, pr_id, summary, created_at) VALUES (?,?,?,?)",
                     (case_id, pr["id"], summary or pr["title"], now_iso()))
        sm.transition(conn, case_id, sm.PR_OPEN, f"{pr['id']} opened")
        key = case["ticket_key"]
    _jira_side_effect(case_id, demo_client.comment, key,
                      f"Pull request {pr['id']} opened: {pr['title']}\nFiles: {', '.join(pr['files_changed'])}\n"
                      f"Tests: {'passing' if pr['tests_passed'] else 'failing'}")
    _jira_side_effect(case_id, demo_client.set_status, key, "In Review")
    return {"case_id": case_id, "pr_id": pr["id"], "state": sm.PR_OPEN}


def _latest_investigation_id(conn, case_id: int) -> int | None:
    row = conn.execute("SELECT id FROM investigations WHERE case_id=? ORDER BY version DESC LIMIT 1",
                       (case_id,)).fetchone()
    return row["id"] if row else None


def review(case_id: int, decision: str, comment: str = "") -> dict:
    if decision in ("request_changes", "reject") and not comment.strip():
        raise ApiError(400, "a comment is required")
    target = {"approve": sm.APPROVED, "request_changes": sm.NEW, "reject": sm.REJECTED}[decision]
    with connect() as conn:
        case = sm.get_case(conn, case_id)
        if case["state"] != sm.AWAITING_APPROVAL:
            raise ApiError(409, f"case {case_id} is {case['state']}, not AWAITING_APPROVAL")
        conn.execute("INSERT INTO reviews (case_id, investigation_id, decision, comment, created_at) VALUES (?,?,?,?,?)",
                     (case_id, _latest_investigation_id(conn, case_id), decision, comment.strip(), now_iso()))
        sm.transition(conn, case_id, target, {"approve": "fix approved by reviewer",
                                              "request_changes": "reviewer requested changes",
                                              "reject": "fix rejected by reviewer"}[decision])
        if decision == "approve":
            tasks.enqueue(conn, case_id, tasks.DEVELOP)
        elif decision == "request_changes":
            tasks.enqueue(conn, case_id, tasks.INVESTIGATE)
        key = case["ticket_key"]
    if decision == "reject":
        _jira_side_effect(case_id, demo_client.comment, key, f"Proposed fix rejected: {comment.strip()}")
        _jira_side_effect(case_id, demo_client.set_status, key, "Won't Fix")
    elif decision == "request_changes":
        _jira_side_effect(case_id, demo_client.comment, key, f"Reviewer requested changes: {comment.strip()}")
    return detail(case_id)


def retry(case_id: int) -> dict:
    with connect() as conn:
        case = sm.get_case(conn, case_id)
        if case["state"] != sm.FAILED:
            raise ApiError(409, f"case {case_id} is {case['state']}; only FAILED cases can be retried")
        last = tasks.current_task(conn, case_id)
        task_type = last["type"] if last else tasks.INVESTIGATE
        sm.transition(conn, case_id, sm.NEW if task_type == tasks.INVESTIGATE else sm.APPROVED, "retry requested")
        tasks.enqueue(conn, case_id, task_type)
    return detail(case_id)


def events(case_id: int, after: int = 0) -> list[dict]:
    with connect() as conn:
        sm.get_case(conn, case_id)
        found = rows(conn.execute("SELECT * FROM events WHERE case_id=? AND id>? ORDER BY id LIMIT 500",
                                  (case_id, after)))
    for e in found:
        e["payload"] = json.loads(e.pop("payload_json"))
    return found


def add_agent_event(case_id: int, kind: str, payload: dict, task_id: int | None) -> None:
    if kind not in {"llm_message", "tool_call", "tool_result", "error", "info"}:
        raise ApiError(400, f"invalid event kind {kind}")
    with connect() as conn:
        sm.get_case(conn, case_id)
        add_event(conn, case_id, kind, payload, task_id)
