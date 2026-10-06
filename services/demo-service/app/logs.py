"""Fake log service: scenario-driven log lines plus background noise."""
import random
from datetime import datetime, timedelta, timezone

import yaml
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .config import SEED_DIR
from .db import connect, rows

LEVELS = ["DEBUG", "INFO", "WARN", "ERROR"]
NOISE_LINES_PER_TICKET = 40


def load_scenarios() -> dict:
    path = SEED_DIR / "scenarios.yaml"
    return yaml.safe_load(path.read_text()) if path.exists() else {"scenarios": [], "noise": []}


def _fill(template: str) -> str:
    return template.format(
        order_id=f"o-{random.randint(10000, 99999)}",
        customer_id=f"c-{random.randint(1000, 9999)}",
        amount=f"{random.uniform(8, 400):.2f}",
        n=random.randint(1, 250),
    )


def _ts(minutes_ago: float) -> str:
    t = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago, seconds=random.randint(0, 50))
    return t.isoformat(timespec="milliseconds")


def generate_for_ticket(scenario_id: str | None) -> None:
    data = load_scenarios()
    lines = []
    for _ in range(NOISE_LINES_PER_TICKET):
        tpl = random.choice(data.get("noise") or [{"service": "app", "level": "INFO", "message": "heartbeat"}])
        lines.append((_ts(random.uniform(0, 90)), tpl["service"], tpl["level"], _fill(tpl["message"]), None))
    scenario = next((s for s in data.get("scenarios", []) if s["id"] == scenario_id), None)
    if scenario:
        for spec in scenario.get("logs", []):
            for i in range(int(spec.get("repeat", 1))):
                minutes = max(float(spec["minutes_ago"]) - i * 1.5, 0.2)
                lines.append((_ts(minutes), spec["service"], spec["level"], _fill(spec["message"]), scenario_id))
    with connect() as conn:
        conn.executemany("INSERT INTO log_lines (ts, service, level, message, scenario_id) VALUES (?,?,?,?,?)", lines)


async def search_logs(request: Request):
    q = request.query_params
    since = int(q.get("since_minutes", 120))
    limit = max(1, min(int(q.get("limit", 50)), 200))
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=since)).isoformat(timespec="milliseconds")
    sql, args = ["SELECT ts, service, level, message FROM log_lines WHERE ts >= ?"], [cutoff]
    if q.get("service"):
        sql.append("AND service = ?")
        args.append(q["service"])
    if q.get("level"):
        level = q["level"].upper().replace("WARNING", "WARN")
        if level in LEVELS:  # level means "this level or more severe"
            allowed = LEVELS[LEVELS.index(level):]
            sql.append(f"AND level IN ({','.join('?' * len(allowed))})")
            args.extend(allowed)
    if q.get("query"):
        for word in q["query"].split():
            sql.append("AND message LIKE ?")
            args.append(f"%{word}%")
    sql.append("ORDER BY ts DESC LIMIT ?")
    args.append(limit)
    with connect() as conn:
        found = rows(conn.execute(" ".join(sql), args))
        services = [r[0] for r in conn.execute("SELECT DISTINCT service FROM log_lines ORDER BY service")]
    found.reverse()  # chronological
    return JSONResponse({"count": len(found), "lines": found, "known_services": services})


routes = [Route("/search", search_logs, methods=["GET"])]
