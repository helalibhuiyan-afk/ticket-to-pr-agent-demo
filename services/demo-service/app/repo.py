"""Fake repository + pull request service.

The demo repository (seed/demo-repo) is read-only. Edits are applied to a temporary copy,
the repo's unittest suite is run against it, and a unified diff is produced.
"""
import difflib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .config import REPO_DIR, TEST_TIMEOUT_SECONDS
from .db import connect, rows
from .util import ApiError, json_body, now_iso

IGNORED = {"__pycache__", ".git", ".pytest_cache"}
MAX_OUTPUT = 4000


def _all_files(root: Path = REPO_DIR) -> list[str]:
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in IGNORED)
        for f in sorted(filenames):
            if not f.endswith(".pyc"):
                out.append(str(Path(dirpath, f).relative_to(root)))
    return out


def _safe_path(root: Path, rel: str) -> Path:
    rel = rel.strip().lstrip("/")
    if rel.startswith("a/") or rel.startswith("b/"):
        rel = rel[2:]
    p = (root / rel).resolve()
    if root.resolve() not in p.parents and p != root.resolve():
        raise ApiError(400, f"path escapes repository: {rel}")
    return p


async def list_files(request: Request):
    prefix = request.query_params.get("path", "").strip("/")
    files = [f for f in _all_files() if f.startswith(prefix)]
    return JSONResponse({"files": files})


async def read_file(request: Request):
    path = _safe_path(REPO_DIR, request.path_params["path"])
    if not path.is_file():
        raise ApiError(404, f"file not found: {request.path_params['path']}. Use list_files to see paths.")
    lines = path.read_text().splitlines()
    start = max(int(request.query_params.get("start_line", 1)), 1)
    end = min(int(request.query_params.get("end_line", start + 299)), len(lines))
    numbered = "\n".join(f"{i:4d}| {lines[i - 1]}" for i in range(start, end + 1))
    return JSONResponse({"path": str(path.relative_to(REPO_DIR.resolve())), "start_line": start,
                         "end_line": end, "total_lines": len(lines), "content": numbered})


async def search_code(request: Request):
    query = request.query_params.get("q", "").strip()
    if not query:
        raise ApiError(400, "q is required")
    matches = []
    for rel in _all_files():
        for n, line in enumerate((REPO_DIR / rel).read_text(errors="ignore").splitlines(), 1):
            if query.lower() in line.lower():
                matches.append({"path": rel, "line": n, "text": line.strip()})
    return JSONResponse({"count": len(matches), "matches": matches[:50]})


def _normalize_edits(raw) -> list[dict]:
    if not isinstance(raw, list) or not raw:
        raise ApiError(400, "edits must be a non-empty list of {path, search, replace}")
    edits = []
    for i, e in enumerate(raw):
        if not isinstance(e, dict) or "path" not in e or "replace" not in e:
            raise ApiError(400, f"edit #{i + 1} must have 'path', 'search' and 'replace'")
        edits.append({"path": str(e["path"]), "search": str(e.get("search") or ""), "replace": str(e["replace"])})
    return edits


def _apply(workdir: Path, edits: list[dict]) -> list[str]:
    """Apply search/replace edits in workdir. Returns errors (empty list on success)."""
    errors = []
    for i, e in enumerate(edits, 1):
        target = _safe_path(workdir, e["path"])
        if not target.exists():
            if e["search"]:
                errors.append(f"edit #{i}: file {e['path']} does not exist (use empty 'search' to create a new file)")
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(e["replace"])
            continue
        text = target.read_text()
        if not e["search"]:
            errors.append(f"edit #{i}: 'search' is empty but {e['path']} already exists")
            continue
        count = text.count(e["search"])
        if count == 0:
            # Common small-model slip: whitespace differences. Give a helpful hint.
            stripped = [ln.strip() for ln in e["search"].splitlines() if ln.strip()]
            hint = ""
            if stripped and stripped[0] in text:
                hint = " (the first line exists; check indentation/whitespace of the following lines)"
            errors.append(f"edit #{i}: 'search' text not found in {e['path']}{hint}. "
                          "Copy it exactly from read_file output, without the line-number prefix.")
        elif count > 1:
            errors.append(f"edit #{i}: 'search' text matches {count} times in {e['path']}; include more context")
        else:
            target.write_text(text.replace(e["search"], e["replace"], 1))
    return errors


def _run_tests(workdir: Path) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."],
            cwd=workdir, capture_output=True, text=True, timeout=TEST_TIMEOUT_SECONDS,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        output = (proc.stdout + proc.stderr).strip()
        return proc.returncode == 0, output[-MAX_OUTPUT:]
    except subprocess.TimeoutExpired:
        return False, f"tests timed out after {TEST_TIMEOUT_SECONDS}s"


def _diff(workdir: Path) -> tuple[str, list[str]]:
    chunks, changed = [], []
    for rel in sorted(set(_all_files(REPO_DIR)) | set(_all_files(workdir))):
        old_p, new_p = REPO_DIR / rel, workdir / rel
        old = old_p.read_text().splitlines(keepends=True) if old_p.exists() else []
        new = new_p.read_text().splitlines(keepends=True) if new_p.exists() else []
        if old != new:
            changed.append(rel)
            chunks.extend(difflib.unified_diff(
                old, new, fromfile=f"a/{rel}" if old_p.exists() else "/dev/null", tofile=f"b/{rel}"))
    return "".join(chunks), changed


def evaluate(edits: list[dict]) -> dict:
    """Apply edits to a scratch copy, run tests, return diff + results."""
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp) / "repo"
        shutil.copytree(REPO_DIR, workdir, ignore=shutil.ignore_patterns(*IGNORED, "*.pyc"))
        errors = _apply(workdir, edits)
        if errors:
            return {"applied": False, "errors": errors}
        diff, changed = _diff(workdir)
        if not changed:
            return {"applied": False, "errors": ["edits did not change any file"]}
        passed, output = _run_tests(workdir)
        return {"applied": True, "tests_passed": passed, "test_output": output, "diff": diff, "files_changed": changed}


async def test_edits(request: Request):
    body = await json_body(request)
    return JSONResponse(evaluate(_normalize_edits(body.get("edits"))))


def _pull_out(row: dict) -> dict:
    row = dict(row)
    row["files_changed"] = json.loads(row.pop("files_changed_json"))
    row["edits"] = json.loads(row.pop("edits_json"))
    row["tests_passed"] = bool(row["tests_passed"])
    return row


async def create_pull(request: Request):
    body = await json_body(request)
    title = (body.get("title") or "").strip()
    if not title:
        raise ApiError(400, "title is required")
    edits = _normalize_edits(body.get("edits"))
    result = evaluate(edits)
    if not result["applied"]:
        raise ApiError(422, "edits could not be applied: " + "; ".join(result["errors"]))
    if not result["tests_passed"]:
        raise ApiError(422, "tests fail with these edits, PR not created. Test output:\n" + result["test_output"])
    with connect() as conn:
        num = conn.execute("SELECT COALESCE(MAX(num), 0) + 1 FROM pulls").fetchone()[0]
        pr_id = f"PR-{num}"
        conn.execute(
            "INSERT INTO pulls (id, num, case_id, title, description, edits_json, diff, files_changed_json,"
            " test_output, tests_passed, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (pr_id, num, body.get("case_id"), title, body.get("description", ""), json.dumps(edits),
             result["diff"], json.dumps(result["files_changed"]), result["test_output"], 1, now_iso()),
        )
        row = conn.execute("SELECT * FROM pulls WHERE id = ?", (pr_id,)).fetchone()
    return JSONResponse(_pull_out(row), status_code=201)


async def get_pull(request: Request):
    with connect() as conn:
        row = conn.execute("SELECT * FROM pulls WHERE id = ?", (request.path_params["pr_id"].upper(),)).fetchone()
    if row is None:
        raise ApiError(404, "pull request not found")
    return JSONResponse(_pull_out(row))


async def list_pulls(request: Request):
    case_id = request.query_params.get("case_id")
    with connect() as conn:
        if case_id:
            found = rows(conn.execute("SELECT * FROM pulls WHERE case_id = ? ORDER BY num DESC", (int(case_id),)))
        else:
            found = rows(conn.execute("SELECT * FROM pulls ORDER BY num DESC"))
    return JSONResponse({"pulls": [_pull_out(r) for r in found]})


routes = [
    Route("/files", list_files, methods=["GET"]),
    Route("/files/{path:path}", read_file, methods=["GET"]),
    Route("/search", search_code, methods=["GET"]),
    Route("/test", test_edits, methods=["POST"]),
    Route("/pulls", create_pull, methods=["POST"]),
    Route("/pulls", list_pulls, methods=["GET"]),
    Route("/pulls/{pr_id}", get_pull, methods=["GET"]),
]
