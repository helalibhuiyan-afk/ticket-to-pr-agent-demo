# ticket-to-pr-agent-demo — Detailed Design

This expands the README into something buildable. Decisions made here are deliberately the
simplest thing that makes the demo reliable on a single CPU-only VM (4 vCPU, 32 GB RAM).

## 1. Decisions at a glance

| Topic | Decision |
|---|---|
| Language / frameworks | Python 3.12 + Starlette for all backend services; plain HTML/JS UI (no build step) |
| Packaging | One container per component, wired with Docker Compose |
| Lifecycle | `./demo.sh` — setup / start / stop / restart / status / logs / reset |
| Security | None. Short-lived demo; only the reverse proxy port is published |
| LLM | Ollama, default model `gpt-oss:20b`, swappable via `.env` (any OpenAI-compatible endpoint) |
| MCP | One gateway, Python MCP SDK v2 (`MCPServer`), streamable HTTP at `/mcp`, tools prefixed by module (`jira_`, `logs_`, `repo_`, `context_`) |
| Agent work pickup | Agent **polls** the control plane task table and claims tasks with a lease |
| Results write-back | Through MCP write tools on the Context module (control plane = source of truth) |
| Ticket vs. case ownership | Fake Jira owns ticket content; control plane owns workflow state |
| Code edits | Search/replace edit format, validated + tested by the repo service before a PR is created |
| Demo reliability | Pre-scripted scenarios: seeded repo bug + matching logs + similar past tickets |
| Observability | Every LLM step and tool call is stored as a case event and shown as a timeline in the UI |

## 2. Components and containers

```
                      :80
 browser ──────────► proxy (Caddy)
                      ├── /        → ui            (static React build, nginx)
                      └── /api/*   → control-plane (FastAPI, controlplane.db)
                                          │  ▲
                 creates tickets, reads   │  │ claim tasks, post events (REST)
                 PRs (REST)               ▼  │
                                   demo-service ◄──── mcp-gateway ◄──── agent ────► ollama
                                   (FastAPI, demo.db)  (FastMCP)        (worker)    (LLM)
                                     /jira /logs /repo   jira, logs,
                                                         repo, context ──► control-plane /internal
```

| Container | Image / stack | Published? | Persistent volume |
|---|---|---|---|
| `proxy` | `caddy:2` | **yes, :80** | — |
| `ui` | static files on `nginx:alpine` | no | — |
| `control-plane` | python:3.12-slim + Starlette | no | `cp-data` (SQLite) |
| `demo-service` | python:3.12-slim + Starlette | no | `demo-data` (SQLite) |
| `mcp-gateway` | python:3.12-slim + `mcp` SDK | no | — |
| `agent` | python:3.12-slim + `mcp` client + `requests` | no | — |
| `ollama` | `ollama/ollama` | no | `ollama-models` (kept across resets) |

`/internal/*` routes on the control plane are reachable only on the Compose network (the proxy
does not route them), which is the only "protection" we need for a throwaway demo.

## 3. Data ownership

- **Fake Jira (demo-service)** owns the ticket: key (`DEMO-123`), title, description, priority,
  reporter, status, comments. It also holds **resolved historical tickets** that act as
  "previous case history" for the investigator.
- **Control plane** owns the workflow: case state, tasks, investigations (versioned), approvals,
  the PR link, and the event timeline. It stores only the ticket key, never a copy of ticket
  content (the UI fetches ticket content through the control plane, which proxies to Jira).
- **Repo service (demo-service)** owns the demo repository and the PRs (diff, description,
  test results).

## 4. Case lifecycle

```
            create ticket
                 │
                 ▼
   ┌────────►  NEW ──(task claimed)──► INVESTIGATING ──(submit_investigation)──► AWAITING_APPROVAL
   │                                        │                                   │      │      │
   │                                        │ retries exhausted        request  │      │      │ reject
   │                                        ▼                          changes  │      │      ▼
   │  retry ◄───────────────────────────  FAILED ◄────────┐                     │      │   REJECTED (terminal)
   │                                                      │                     │      │ approve
   └───────────────────────────────────────────────────── │ ────────────────────┘      ▼
                                                          │                         APPROVED
                                                          │                            │ (task claimed)
                                                          │                            ▼
                                                          └──── retries exhausted ── DEVELOPING
                                                                                       │ (PR recorded)
                                                                                       ▼
                                                                                    PR_OPEN (terminal)
```

| From | Event | To | Side effects |
|---|---|---|---|
| — | `POST /api/tickets` | NEW | create Jira ticket; create case; enqueue `INVESTIGATE` task |
| NEW | agent claims INVESTIGATE | INVESTIGATING | — |
| INVESTIGATING | `context.submit_investigation` | AWAITING_APPROVAL | store investigation vN; Jira comment |
| AWAITING_APPROVAL | user approves | APPROVED | record approval; enqueue `DEVELOP` task |
| AWAITING_APPROVAL | user requests changes (feedback) | NEW | record feedback; enqueue `INVESTIGATE` (feedback in context) |
| AWAITING_APPROVAL | user rejects (reason) | REJECTED | record rejection; Jira status `Won't Fix` |
| APPROVED | agent claims DEVELOP | DEVELOPING | — |
| DEVELOPING | PR recorded | PR_OPEN | link PR; Jira comment with PR id; Jira status `In Review` |
| INVESTIGATING / DEVELOPING | task fails after max attempts | FAILED | store error |
| FAILED | user clicks retry | NEW or APPROVED | re-enqueue the failed task type |

Transitions are enforced in one place (`control-plane/app/state_machine.py`); illegal transitions
return HTTP 409.

## 5. Task queue (agent polling)

Table `tasks`:

| column | notes |
|---|---|
| `id`, `case_id` | |
| `type` | `INVESTIGATE` \| `DEVELOP` |
| `status` | `PENDING` \| `CLAIMED` \| `DONE` \| `FAILED` |
| `attempts` | incremented on each claim; max 2 (configurable) |
| `claimed_by`, `lease_expires_at` | lease = 20 min (CPU inference is slow); extended by heartbeat |
| `last_error`, `created_at`, `updated_at` | |

- Agent loop: `POST /internal/tasks/claim {worker_id}` every 3 s → `200 task` or `204`.
- Claim is a single SQLite transaction (`UPDATE … WHERE id = (SELECT … PENDING or lease expired
  ORDER BY created_at LIMIT 1)`), so a crashed agent's task is re-claimed after the lease expires.
- Heartbeat every 30 s while working; `complete` or `fail {error}` at the end.
- The worker runs **one task at a time** (CPU-bound LLM).

## 6. Agent

One worker process, two roles. A role = system prompt + tool allowlist + step budget.

| | Investigator | Developer |
|---|---|---|
| Trigger | `INVESTIGATE` task | `DEVELOP` task |
| Tools | `jira.get_ticket`, `jira.search_tickets`, `logs.search_logs`, `repo.list_files`, `repo.read_file`, `repo.search_code`, `context.get_case_context`, `context.submit_investigation` | `context.get_case_context`, `repo.list_files`, `repo.read_file`, `repo.search_code`, `repo.run_tests`, `repo.create_pull_request`, `context.record_pull_request`, `jira.add_comment` |
| Step budget | 20 tool calls | 25 tool calls |
| Done when | an investigation is stored for this case | a PR is recorded for this case |

Loop (`agent/worker.py`): plain OpenAI-compatible chat-completions loop with tool calling; MCP
tools are listed from the gateway, filtered by the role allowlist, and converted to the OpenAI
tool schema. No agent framework.

Guardrails that make a small model workable:
- Tool outputs are truncated (e.g., logs ≤ 50 lines, files ≤ 300 lines per read with ranges).
- If the model stops without calling the "done" tool, the worker sends one nudge
  ("You must call `context.submit_investigation` now"), then fails the attempt.
- **Finalization check**: after the developer loop, if the repo service has a PR for the case
  that wasn't recorded, the worker records it itself.
- Every assistant message, tool call and tool result is posted to
  `POST /internal/cases/{id}/events` for the UI timeline.

## 7. MCP gateway tools

Single MCP server (SDK v2 `MCPServer`), streamable HTTP at `http://mcp-gateway:8000/mcp`. Tool names use a
module prefix with an underscore (`jira_get_ticket`), because OpenAI-style tool names can't contain dots.

**jira** → demo-service `/jira`
- `get_ticket(key)`
- `search_tickets(query, status?)` — includes resolved historical tickets
- `add_comment(key, body)`

**logs** → demo-service `/logs`
- `search_logs(service?, level?, query?, since_minutes=60, limit=50)`

**repo** → demo-service `/repo`
- `list_files(path="")`
- `read_file(path, start_line?, end_line?)`
- `search_code(query)`
- `run_tests(edits)` — dry run: apply edits to a scratch copy, run tests, return results
- `create_pull_request(case_id, title, description, edits)`

  `edits = [{ "path": str, "search": str, "replace": str }]`. Each `search` must match exactly
  once in the file (otherwise a descriptive error is returned so the model can retry). The
  service applies edits on a copy of the repo, runs `pytest`, renders a unified diff, and stores
  the PR (`PR-1`, `PR-2`, …) with diff, description and test results. Tests use the standard library
  `unittest` runner, so the demo-service image needs no test dependencies. A PR whose tests fail is
  rejected with the test output.

**context** → control-plane `/internal`
- `get_case_context(case_id)` — state, ticket key, investigation history, reviewer feedback,
  approved investigation
- `submit_investigation(case_id, summary, root_cause, evidence[], proposed_fix, files_to_change[], confidence)`
- `record_pull_request(case_id, pr_id, summary)`

## 8. APIs

### Control plane — public (via proxy at `/api`)
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/scenarios` | scenario templates for the "new ticket" form |
| POST | `/api/tickets` | `{title, description, priority, scenario_id?}` → creates ticket + case |
| GET | `/api/cases` | list with state, ticket key/title, timestamps |
| GET | `/api/cases/{id}` | case + ticket (proxied) + investigations + approvals + PR summary |
| GET | `/api/cases/{id}/events?after={event_id}` | timeline (UI polls incrementally) |
| GET | `/api/cases/{id}/pr` | PR detail incl. diff and test results (proxied) |
| POST | `/api/cases/{id}/approve` | |
| POST | `/api/cases/{id}/request-changes` | `{feedback}` |
| POST | `/api/cases/{id}/reject` | `{reason}` |
| POST | `/api/cases/{id}/retry` | only from FAILED |
| GET | `/api/health` | |

### Control plane — internal (Compose network only)
`POST /internal/tasks/claim`, `POST /internal/tasks/{id}/heartbeat|complete|fail`,
`GET /internal/cases/{id}/context`, `POST /internal/cases/{id}/investigation`,
`POST /internal/cases/{id}/pull-request`, `POST /internal/cases/{id}/events`.

### Demo service
- `/jira`: `POST /tickets`, `GET /tickets/{key}`, `GET /tickets?query=&status=`,
  `PATCH /tickets/{key}`, `POST /tickets/{key}/comments`
- `/logs`: `GET /search?service=&level=&query=&since_minutes=&limit=`
- `/repo`: `GET /files`, `GET /files/{path}`, `GET /search?q=`, `POST /test`, `POST /pulls`,
  `GET /pulls?case_id=`, `GET /pulls/{id}`

## 9. Data model (SQLite)

**controlplane.db**: `cases(id, ticket_key, scenario_id, state, created_at, updated_at)`,
`tasks(...)` (§5), `investigations(id, case_id, version, summary, root_cause, evidence_json,
proposed_fix, files_to_change_json, confidence, created_at)`, `reviews(id, case_id,
investigation_id, decision[approve|request_changes|reject], comment, created_at)`,
`case_prs(case_id, pr_id, summary, created_at)`, `events(id, case_id, task_id, kind[state_change|
llm_message|tool_call|tool_result|error], payload_json, created_at)`.

**demo.db**: `tickets`, `comments`, `log_lines(id, ts, service, level, message, scenario_id)`,
`pulls(id, case_id, title, description, edits_json, diff, test_output, tests_passed, created_at)`.

Both DBs are created and seeded on first start if missing; `./demo.sh reset` wipes them.

## 10. Scenarios (demo reliability)

`seed/scenarios.yaml` defines each scenario: ticket template, log generator, related historical
tickets. Seeded logs are timestamped relative to "now" when a ticket is created from a scenario.
The demo repository `seed/demo-repo/` is a tiny **orders-service** Python package with `pytest`
tests; each scenario has one planted bug and one currently-failing (or missing-coverage) test
that passes once fixed.

| id | Ticket | Planted bug | Log signal | Similar past ticket |
|---|---|---|---|---|
| `negative-total` | "Checkout fails for some coupon orders" | discount not clamped, total goes negative | `PaymentError: amount must be >= 0` in `payments` | DEMO-12 rounding error in tax calc |
| `pagination-gap` | "Order history skips items" | off-by-one in page offset | `returned 19 of 20 items` warnings in `orders-api` | DEMO-7 duplicate rows on page 2 |
| `tz-date` | "Order dates show the wrong day" | naive datetime formatted in UTC | `created_at=…T23:30Z rendered as next day` in `orders-api` | DEMO-15 DST report bug |

Free-form tickets still work (the agent will look at generic logs and the repo), but the
scenarios are what you demo.

## 11. UI

Single page app, polling every 3 s (no websockets).
- **Tickets list**: key, title, state badge, updated time; "New ticket" button.
- **New ticket**: scenario dropdown (pre-fills title/description) or blank form.
- **Case detail**:
  - state stepper (NEW → … → PR_OPEN);
  - ticket panel;
  - investigation card (root cause, evidence, proposed fix, confidence) with
    **Approve / Request changes / Reject** while AWAITING_APPROVAL;
  - PR panel: description, test results, side-by-side diff (`diff2html`);
  - **Agent timeline**: collapsible list of LLM messages and tool calls with timings.

## 12. LLM

- `ollama` container; model pulled by `./demo.sh start` on first run into the `ollama-models` volume.
- Agent talks to `http://ollama:11434/v1` via the OpenAI client. Config in `.env`:
  ```
  LLM_BASE_URL=http://ollama:11434/v1
  LLM_MODEL=gpt-oss:20b
  LLM_API_KEY=ollama
  OLLAMA_CONTEXT_LENGTH=16384
  ```
- Alternatives: `qwen3:8b` (lighter), `qwen2.5-coder:7b`. To use a hosted model for a fast live
  demo, point `LLM_BASE_URL`/`LLM_API_KEY`/`LLM_MODEL` at any OpenAI-compatible endpoint; the
  ollama container can then be skipped (`COMPOSE_PROFILES` without `local-llm`).
- Expect minutes, not seconds, per agent run on 4 CPU cores. The timeline makes the wait watchable.

## 13. `demo.sh`

```
./demo.sh setup      # install Docker Engine + compose plugin if missing, create .env from .env.example
./demo.sh start      # docker compose up -d --build, pull LLM model if needed, wait for health, print URL
./demo.sh stop       # docker compose stop (keeps data)
./demo.sh restart    # stop + start
./demo.sh status     # container status + health of each service
./demo.sh logs [svc] # follow logs (all or one service)
./demo.sh reset      # down + delete DB volumes (keeps the downloaded model), then start fresh
```

The script is idempotent, uses `set -euo pipefail`, and prints the public URL using the
machine's public IP.

## 14. Repository layout

```
demo.sh
docker-compose.yml
.env.example
Caddyfile
seed/
  scenarios.yaml
  historical_tickets.yaml
  demo-repo/                 # orders-service + tests (the code the agent fixes)
services/
  control-plane/  app/{main.py, api_public.py, api_internal.py, state_machine.py, tasks.py, db.py, jira_client.py}
  demo-service/   app/{main.py, jira.py, logs.py, repo.py, seed.py, db.py}
  mcp-gateway/    app/{server.py, jira.py, logs.py, repo.py, context.py}
  agent/          app/{worker.py, llm.py, mcp_client.py, roles/{investigator.md, developer.md}}
  ui/             src/{App.tsx, pages/, components/, api.ts}
```

## 15. Build plan

1. Compose skeleton, `demo.sh`, health endpoints for every service.
2. demo-service: Jira, logs, repo (+ edit/test/diff), seeding, demo repo with planted bugs.
3. control-plane: state machine, tasks, public + internal APIs.
4. mcp-gateway: four modules.
5. agent: worker loop, roles, event posting, finalization check.
6. UI.
7. End-to-end on the VM with each scenario; tune prompts and step budgets for the chosen model.

## 16. Implementation notes (as built)

- Backend services use Starlette rather than FastAPI and the UI is plain HTML/JS. Both keep dependencies
  minimal and let everything be run and tested without a package build step.
- MCP tool names: `jira_get_ticket`, `jira_search_tickets`, `jira_add_comment`, `logs_search`,
  `repo_list_files`, `repo_read_file`, `repo_search_code`, `repo_run_tests`, `repo_create_pull_request`,
  `context_get_case`, `context_submit_investigation`, `context_record_pull_request`.
- The worker forces `case_id` in tool arguments to the task's case, inlines JSON-schema `$ref`s for
  servers that don't resolve them (Ollama), nudges the model once if it stops early, and records an
  unrecorded PR on its own (finalization check).
- `ticket_title` is cached on the case for the list view only; Jira remains the owner of ticket content.
- `services/agent/tests/mock_llm.py` is a scripted OpenAI-compatible server used to smoke-test the
  full pipeline (`COMPOSE_PROFILES=mock-llm`).
