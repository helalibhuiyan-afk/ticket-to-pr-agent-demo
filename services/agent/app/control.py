"""Control-plane and demo-service REST calls used by the worker itself (not by the model)."""
import requests

from .config import CONTROL_PLANE_URL, DEMO_SERVICE_URL, WORKER_ID

TIMEOUT = 30


def _post(path: str, body: dict) -> requests.Response:
    return requests.post(CONTROL_PLANE_URL + path, json=body, timeout=TIMEOUT)


def claim() -> dict | None:
    resp = _post("/internal/tasks/claim", {"worker_id": WORKER_ID})
    if resp.status_code == 204:
        return None
    resp.raise_for_status()
    return resp.json()


def heartbeat(task_id: int) -> None:
    _post(f"/internal/tasks/{task_id}/heartbeat", {"worker_id": WORKER_ID}).raise_for_status()


def complete(task_id: int) -> dict:
    resp = _post(f"/internal/tasks/{task_id}/complete", {"worker_id": WORKER_ID})
    resp.raise_for_status()
    return resp.json()


def fail(task_id: int, error: str) -> dict:
    resp = _post(f"/internal/tasks/{task_id}/fail", {"worker_id": WORKER_ID, "error": error[:2000]})
    resp.raise_for_status()
    return resp.json()


def event(case_id: int, task_id: int, kind: str, payload: dict) -> None:
    try:
        _post(f"/internal/cases/{case_id}/events", {"kind": kind, "payload": payload, "task_id": task_id})
    except requests.RequestException:
        pass  # the timeline is best-effort


def case_state(case_id: int) -> str:
    resp = requests.get(f"{CONTROL_PLANE_URL}/internal/cases/{case_id}/context", timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()["state"]


def unrecorded_pr(case_id: int) -> str | None:
    """Finalization check: a PR created for this case that the model forgot to record."""
    resp = requests.get(f"{DEMO_SERVICE_URL}/repo/pulls", params={"case_id": case_id}, timeout=TIMEOUT)
    resp.raise_for_status()
    pulls = resp.json()["pulls"]
    return pulls[0]["id"] if pulls else None


def record_pr(case_id: int, pr_id: str) -> None:
    resp = _post(f"/internal/cases/{case_id}/pull-request", {"pr_id": pr_id, "summary": "recorded by worker finalization"})
    resp.raise_for_status()
