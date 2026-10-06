"""Task queue the agent polls. All functions expect an open connection (see db.connect)."""
from datetime import datetime, timedelta, timezone

from . import state_machine as sm
from .config import MAX_TASK_ATTEMPTS, TASK_LEASE_SECONDS
from .db import add_event
from .util import ApiError, now_iso

INVESTIGATE = "INVESTIGATE"
DEVELOP = "DEVELOP"

# Case states in which a task of the given type may run, and the state it moves the case to.
RUNNABLE = {INVESTIGATE: ({sm.NEW, sm.INVESTIGATING}, sm.INVESTIGATING),
            DEVELOP: ({sm.APPROVED, sm.DEVELOPING}, sm.DEVELOPING)}
DONE_STATE = {INVESTIGATE: sm.AWAITING_APPROVAL, DEVELOP: sm.PR_OPEN}


def _lease_deadline() -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=TASK_LEASE_SECONDS)).isoformat(timespec="seconds")


def enqueue(conn, case_id: int, task_type: str) -> int:
    ts = now_iso()
    cur = conn.execute("INSERT INTO tasks (case_id, type, status, created_at, updated_at) VALUES (?,?,?,?,?)",
                       (case_id, task_type, "PENDING", ts, ts))
    add_event(conn, case_id, "info", {"message": f"{task_type} task queued for the agent"}, cur.lastrowid)
    return cur.lastrowid


def get_task(conn, task_id: int) -> dict:
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None:
        raise ApiError(404, f"task {task_id} not found")
    return dict(row)


def _give_up_or_retry(conn, task: dict, error: str) -> dict:
    """Failed attempt: re-queue if attempts remain, otherwise fail the task and the case."""
    ts = now_iso()
    if task["attempts"] < MAX_TASK_ATTEMPTS:
        conn.execute("UPDATE tasks SET status='PENDING', claimed_by=NULL, lease_expires_at=NULL, last_error=?,"
                     " updated_at=? WHERE id=?", (error, ts, task["id"]))
        add_event(conn, task["case_id"], "error",
                  {"message": f"attempt {task['attempts']}/{MAX_TASK_ATTEMPTS} failed, will retry", "error": error},
                  task["id"])
        return {"status": "PENDING"}
    conn.execute("UPDATE tasks SET status='FAILED', lease_expires_at=NULL, last_error=?, updated_at=? WHERE id=?",
                 (error, ts, task["id"]))
    add_event(conn, task["case_id"], "error",
              {"message": f"{task['type']} failed after {task['attempts']} attempts", "error": error}, task["id"])
    case = sm.get_case(conn, task["case_id"])
    if sm.FAILED in sm.TRANSITIONS[case["state"]]:
        sm.transition(conn, task["case_id"], sm.FAILED, f"{task['type']} task failed", task["id"])
    return {"status": "FAILED"}


def sweep_expired(conn) -> None:
    expired = conn.execute("SELECT * FROM tasks WHERE status='CLAIMED' AND lease_expires_at < ?",
                           (now_iso(),)).fetchall()
    for task in expired:
        _give_up_or_retry(conn, dict(task), "lease expired (agent stopped responding)")


def claim(conn, worker_id: str) -> dict | None:
    sweep_expired(conn)
    while True:
        row = conn.execute("SELECT * FROM tasks WHERE status='PENDING' ORDER BY created_at, id LIMIT 1").fetchone()
        if row is None:
            return None
        task = dict(row)
        case = sm.get_case(conn, task["case_id"])
        allowed, running_state = RUNNABLE[task["type"]]
        if case["state"] not in allowed:  # stale task (e.g. case was rejected meanwhile)
            conn.execute("UPDATE tasks SET status='CANCELLED', updated_at=? WHERE id=?", (now_iso(), task["id"]))
            continue
        conn.execute("UPDATE tasks SET status='CLAIMED', attempts=attempts+1, claimed_by=?, lease_expires_at=?,"
                     " updated_at=? WHERE id=?", (worker_id, _lease_deadline(), now_iso(), task["id"]))
        if case["state"] != running_state:
            sm.transition(conn, case["id"], running_state, f"agent {worker_id} picked up {task['type']}", task["id"])
        task = get_task(conn, task["id"])
        task["ticket_key"] = case["ticket_key"]
        add_event(conn, case["id"], "info",
                  {"message": f"agent {worker_id} started {task['type']} (attempt {task['attempts']}/{MAX_TASK_ATTEMPTS})"},
                  task["id"])
        return task


def _require_claimed(conn, task_id: int, worker_id: str | None) -> dict:
    task = get_task(conn, task_id)
    if task["status"] != "CLAIMED":
        raise ApiError(409, f"task {task_id} is {task['status']}, not CLAIMED")
    if worker_id and task["claimed_by"] != worker_id:
        raise ApiError(409, f"task {task_id} is claimed by {task['claimed_by']}")
    return task


def heartbeat(conn, task_id: int, worker_id: str | None) -> dict:
    _require_claimed(conn, task_id, worker_id)
    deadline = _lease_deadline()
    conn.execute("UPDATE tasks SET lease_expires_at=?, updated_at=? WHERE id=?", (deadline, now_iso(), task_id))
    return {"lease_expires_at": deadline}


def complete(conn, task_id: int, worker_id: str | None) -> dict:
    task = _require_claimed(conn, task_id, worker_id)
    case = sm.get_case(conn, task["case_id"])
    if case["state"] != DONE_STATE[task["type"]]:
        return _give_up_or_retry(conn, task, f"task finished but case is {case['state']}, "
                                              f"expected {DONE_STATE[task['type']]}")
    conn.execute("UPDATE tasks SET status='DONE', lease_expires_at=NULL, updated_at=? WHERE id=?", (now_iso(), task_id))
    add_event(conn, task["case_id"], "info", {"message": f"{task['type']} completed"}, task_id)
    return {"status": "DONE"}


def fail(conn, task_id: int, worker_id: str | None, error: str) -> dict:
    task = _require_claimed(conn, task_id, worker_id)
    return _give_up_or_retry(conn, task, error or "unknown error")


def current_task(conn, case_id: int) -> dict | None:
    row = conn.execute("SELECT id, type, status, attempts, claimed_by, last_error, updated_at FROM tasks"
                       " WHERE case_id = ? ORDER BY id DESC LIMIT 1", (case_id,)).fetchone()
    if row is None:
        return None
    task = dict(row)
    task["max_attempts"] = MAX_TASK_ATTEMPTS
    return task
