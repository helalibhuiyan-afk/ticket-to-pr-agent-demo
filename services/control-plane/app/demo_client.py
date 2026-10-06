"""Client for the demo service (fake Jira + repo)."""
import requests

from .config import DEMO_SERVICE_URL
from .util import ApiError

TIMEOUT = 15


def _call(method: str, path: str, **kwargs):
    try:
        resp = requests.request(method, DEMO_SERVICE_URL + path, timeout=TIMEOUT, **kwargs)
    except requests.RequestException as exc:
        raise ApiError(502, f"demo-service unreachable: {exc}")
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("error", resp.text)
        except ValueError:
            detail = resp.text
        raise ApiError(resp.status_code if resp.status_code < 500 else 502, detail)
    return resp.json()


def create_ticket(title, description, priority, scenario_id):
    return _call("POST", "/jira/tickets", json={"title": title, "description": description,
                                               "priority": priority, "scenario_id": scenario_id})


def get_ticket(key):
    return _call("GET", f"/jira/tickets/{key}")


def comment(key, body, author="ticket-to-pr-agent"):
    return _call("POST", f"/jira/tickets/{key}/comments", json={"author": author, "body": body})


def set_status(key, status):
    return _call("PATCH", f"/jira/tickets/{key}", json={"status": status})


def get_pull(pr_id):
    return _call("GET", f"/repo/pulls/{pr_id}")
