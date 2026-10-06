"""The single place where case state transitions are defined and enforced."""
from .db import add_event
from .util import ApiError, now_iso

NEW = "NEW"
INVESTIGATING = "INVESTIGATING"
AWAITING_APPROVAL = "AWAITING_APPROVAL"
APPROVED = "APPROVED"
DEVELOPING = "DEVELOPING"
PR_OPEN = "PR_OPEN"
REJECTED = "REJECTED"
FAILED = "FAILED"

STATES = [NEW, INVESTIGATING, AWAITING_APPROVAL, APPROVED, DEVELOPING, PR_OPEN, REJECTED, FAILED]

TRANSITIONS: dict[str, set[str]] = {
    NEW: {INVESTIGATING},
    INVESTIGATING: {AWAITING_APPROVAL, FAILED},
    AWAITING_APPROVAL: {APPROVED, NEW, REJECTED},   # NEW = reviewer requested changes
    APPROVED: {DEVELOPING},
    DEVELOPING: {PR_OPEN, FAILED},
    FAILED: {NEW, APPROVED},                        # retry the failed step
    PR_OPEN: set(),
    REJECTED: set(),
}


def get_case(conn, case_id: int) -> dict:
    row = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    if row is None:
        raise ApiError(404, f"case {case_id} not found")
    return dict(row)


def transition(conn, case_id: int, to: str, reason: str = "", task_id: int | None = None) -> dict:
    case = get_case(conn, case_id)
    frm = case["state"]
    if to not in TRANSITIONS[frm]:
        raise ApiError(409, f"case {case_id} is {frm}; cannot move to {to}")
    conn.execute("UPDATE cases SET state = ?, updated_at = ? WHERE id = ?", (to, now_iso(), case_id))
    add_event(conn, case_id, "state_change", {"from": frm, "to": to, "reason": reason}, task_id)
    case["state"] = to
    return case
