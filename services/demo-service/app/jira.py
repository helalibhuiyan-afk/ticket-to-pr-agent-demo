"""Fake Jira: tickets and comments."""
import re

import yaml
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from . import logs
from .config import SEED_DIR
from .db import connect, rows
from .util import ApiError, json_body, now_iso

FIRST_NEW_TICKET = 101
STATUSES = {"Open", "In Progress", "In Review", "Done", "Won't Fix"}
STOPWORDS = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "with", "some", "not", "are", "be"}


def seed_historical() -> None:
    path = SEED_DIR / "historical_tickets.yaml"
    if not path.exists():
        return
    data = yaml.safe_load(path.read_text()) or {}
    with connect() as conn:
        for t in data.get("tickets", []):
            num = int(t["key"].split("-")[1])
            ts = now_iso()
            conn.execute(
                "INSERT OR IGNORE INTO tickets (key, num, title, description, priority, status, reporter,"
                " resolution, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (t["key"], num, t["title"], t.get("description", ""), t.get("priority", "Medium"),
                 t.get("status", "Done"), "support-team", t.get("resolution"), ts, ts),
            )


def _get(conn, key: str) -> dict:
    row = conn.execute("SELECT * FROM tickets WHERE key = ?", (key.strip().upper(),)).fetchone()
    if row is None:
        raise ApiError(404, f"ticket {key} not found")
    ticket = dict(row)
    ticket["comments"] = rows(conn.execute(
        "SELECT author, body, created_at FROM comments WHERE ticket_key = ? ORDER BY id", (ticket["key"],)))
    return ticket


async def create_ticket(request: Request):
    body = await json_body(request)
    title = (body.get("title") or "").strip()
    if not title:
        raise ApiError(400, "title is required")
    scenario_id = body.get("scenario_id") or None
    ts = now_iso()
    with connect() as conn:
        num = max(conn.execute("SELECT COALESCE(MAX(num), 0) FROM tickets WHERE num >= ?",
                               (FIRST_NEW_TICKET,)).fetchone()[0] + 1, FIRST_NEW_TICKET)
        key = f"DEMO-{num}"
        conn.execute(
            "INSERT INTO tickets (key, num, title, description, priority, status, reporter, scenario_id,"
            " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (key, num, title, body.get("description", ""), body.get("priority", "Medium"), "Open",
             body.get("reporter", "demo-user"), scenario_id, ts, ts),
        )
        ticket = _get(conn, key)
    # Each new ticket brings fresh log activity (scenario signal + background noise).
    logs.generate_for_ticket(scenario_id)
    return JSONResponse(ticket, status_code=201)


async def get_ticket(request: Request):
    with connect() as conn:
        return JSONResponse(_get(conn, request.path_params["key"]))


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 1 and w not in STOPWORDS}


async def search_tickets(request: Request):
    """Keyword search ranked by number of matching words (OR semantics)."""
    query = request.query_params.get("query", "")
    status = request.query_params.get("status")
    limit = min(int(request.query_params.get("limit", 10)), 50)
    with connect() as conn:
        sql, args = "SELECT * FROM tickets", []
        if status:
            sql, args = sql + " WHERE status = ?", [status]
        candidates = rows(conn.execute(sql + " ORDER BY num DESC", args))
    terms = _words(query)
    if terms:
        scored = []
        for t in candidates:
            hay = _words(" ".join(filter(None, [t["key"], t["title"], t["description"], t.get("resolution")])))
            score = len(terms & hay)
            if score:
                scored.append((score, t))
        scored.sort(key=lambda s: (-s[0], -s[1]["num"]))
        candidates = [t for _, t in scored]
    return JSONResponse({"tickets": candidates[:limit]})


async def update_ticket(request: Request):
    body = await json_body(request)
    key = request.path_params["key"]
    with connect() as conn:
        _get(conn, key)
        if "status" in body:
            if body["status"] not in STATUSES:
                raise ApiError(400, f"status must be one of {sorted(STATUSES)}")
            conn.execute("UPDATE tickets SET status = ?, updated_at = ? WHERE key = ?",
                         (body["status"], now_iso(), key.upper()))
        if "resolution" in body:
            conn.execute("UPDATE tickets SET resolution = ?, updated_at = ? WHERE key = ?",
                         (body["resolution"], now_iso(), key.upper()))
        return JSONResponse(_get(conn, key))


async def add_comment(request: Request):
    body = await json_body(request)
    key = request.path_params["key"]
    text = (body.get("body") or "").strip()
    if not text:
        raise ApiError(400, "body is required")
    with connect() as conn:
        _get(conn, key)
        conn.execute("INSERT INTO comments (ticket_key, author, body, created_at) VALUES (?,?,?,?)",
                     (key.upper(), body.get("author", "agent"), text, now_iso()))
        conn.execute("UPDATE tickets SET updated_at = ? WHERE key = ?", (now_iso(), key.upper()))
        return JSONResponse(_get(conn, key), status_code=201)


routes = [
    Route("/tickets", create_ticket, methods=["POST"]),
    Route("/tickets", search_tickets, methods=["GET"]),
    Route("/tickets/{key}", get_ticket, methods=["GET"]),
    Route("/tickets/{key}", update_ticket, methods=["PATCH"]),
    Route("/tickets/{key}/comments", add_comment, methods=["POST"]),
]
