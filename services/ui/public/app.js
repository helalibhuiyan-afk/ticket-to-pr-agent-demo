/* Ticket to PR demo UI: plain JS, no build step. Polls the control plane API every few seconds. */
const API = "/api";
const POLL_MS = 3000;
const app = document.getElementById("app");
let timers = [];

const STEPS = [
  ["NEW", "Ticket created"], ["INVESTIGATING", "Investigating"], ["AWAITING_APPROVAL", "Awaiting approval"],
  ["APPROVED", "Approved"], ["DEVELOPING", "Developing"], ["PR_OPEN", "PR open"],
];
const STATE_LABEL = {
  NEW: "New", INVESTIGATING: "Investigating", AWAITING_APPROVAL: "Awaiting approval", APPROVED: "Approved",
  DEVELOPING: "Developing", PR_OPEN: "PR open", REJECTED: "Rejected", FAILED: "Failed",
};
const ACTIVE = new Set(["NEW", "INVESTIGATING", "APPROVED", "DEVELOPING"]);

// ---------- helpers ----------
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
async function api(path, opts = {}) {
  const res = await fetch(API + path, {
    headers: { "Content-Type": "application/json" }, ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const data = res.status === 204 ? null : await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data?.error || `HTTP ${res.status}`);
  return data;
}
function ago(iso) {
  if (!iso) return "";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${Math.floor(s)}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return new Date(iso).toLocaleDateString();
}
function clock(iso) { return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }); }
function badge(state) {
  return `<span class="badge ${esc(state)} ${ACTIVE.has(state) ? "pulse" : ""}">${esc(STATE_LABEL[state] || state)}</span>`;
}
function toast(msg) {
  const el = document.createElement("div");
  el.className = "toast"; el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 4000);
}
function every(fn, ms = POLL_MS) { fn(); timers.push(setInterval(fn, ms)); }
function taskText(task, state) {
  if (!task) return "";
  if (task.status === "PENDING") return "Queued for agent";
  if (task.status === "CLAIMED") return `Agent working · attempt ${task.attempts}/${task.max_attempts}`;
  if (task.status === "FAILED" && state === "FAILED") return `Failed: ${task.last_error || ""}`;
  return "";
}

// ---------- router ----------
let info = null;
function setFooter() {
  const f = document.getElementById("footer-model");
  if (f && info) f.textContent = `Agent LLM: ${info.llm_mode === "mock" ? "Mock (scripted)" : info.model}`;
}
async function loadInfo(force = false) {
  if (info && !force) return info;
  try { info = await api("/info"); } catch { info = { llm_mode: "real", model: "unknown", provider: "", options: [] }; }
  setFooter();
  return info;
}

function llmHint(i) {
  if (!i) return "";
  const opt = (i.options || []).find(o => o.id === i.llm_mode) || {};
  return i.llm_mode === "mock"
    ? "Instant scripted responses for the three demo scenarios. Free-form tickets get a low-confidence placeholder."
    : `${opt.model || i.model} · ${opt.provider || i.provider}. On a CPU-only VM each step can take a while.`;
}

function llmSwitchHtml(variant = "") {
  const i = info || { llm_mode: "real", options: [] };
  const real = (i.options || []).find(o => o.id === "real") || { model: i.model };
  const btn = (mode, title, sub) => `
    <button type="button" role="radio" aria-checked="${i.llm_mode === mode}" class="${i.llm_mode === mode ? "on" : ""}" data-mode="${mode}">
      <strong>${esc(title)}</strong><small>${esc(sub)}</small></button>`;
  return `<div class="llm-switch ${variant}">
      <span class="ls-label">Agent LLM</span>
      <div class="ls-options" role="radiogroup" aria-label="Agent LLM">
        ${btn("real", "Real LLM", real.model || "model")}
        ${btn("mock", "Mock LLM", "instant, scripted")}
      </div>
    </div>
    <div class="ls-hint">${esc(llmHint(i))} Applies to the next task the agent picks up.</div>`;
}

function mountLlmSwitches() {
  document.querySelectorAll("[data-llm-switch]").forEach(el => {
    el.innerHTML = llmSwitchHtml(el.dataset.llmSwitch);
    el.querySelectorAll("button[data-mode]").forEach(b => b.addEventListener("click", async () => {
      if (info && b.dataset.mode === info.llm_mode) return;
      el.querySelectorAll("button").forEach(x => x.disabled = true);
      try {
        info = await api("/settings/llm", { method: "POST", body: { mode: b.dataset.mode } });
        setFooter();
        toast(b.dataset.mode === "mock" ? "Switched to the mock LLM" : "Switched to the real LLM");
      } catch (e) { toast(e.message); }
      mountLlmSwitches();
      const d = document.getElementById("diagram");
      if (d) d.innerHTML = archDiagram(info);
    }));
  });
}

function route() {
  timers.forEach(clearInterval); timers = [];
  const hash = location.hash || "#/";
  let m, nav = "home";
  if (hash === "#/new") { nav = "new"; renderNew(); }
  else if (hash.startsWith("#/architecture")) { nav = "architecture"; renderArchitecture(); }
  else if ((m = hash.match(/^#\/cases\/(\d+)/))) { nav = ""; renderCase(Number(m[1])); }
  else renderHome();
  document.querySelectorAll("[data-nav]").forEach(a => a.classList.toggle("active", a.dataset.nav === nav));
  window.scrollTo(0, 0);
}
window.addEventListener("hashchange", route);

// ---------- home / dashboard ----------
const HOW_STEPS = [
  ["Report", "Someone files a bug ticket describing what users are seeing.", "You"],
  ["Investigate", "The agent reads the ticket, searches logs and past incidents, reads the code and writes up the root cause with evidence.", "Agent"],
  ["Approve", "You review the proposed fix. Approve it, ask for changes, or reject it.", "You"],
  ["Open a PR", "The agent writes the patch and a regression test, runs the test suite and opens a pull request.", "Agent"],
];

function renderHome() {
  app.innerHTML = `
    <section class="hero">
      <div class="eyebrow">Agentic bug triage demo</div>
      <h1>From bug ticket to pull request, with a human approving every fix</h1>
      <p class="lead">File a ticket and an AI agent investigates it like an engineer on call: it reads the logs, past incidents
        and the code, explains the root cause and proposes a fix. Once you approve, it writes the patch, runs the tests
        and opens a pull request.</p>
      <div class="cta">
        <a class="btn btn-light" href="#/new">Create a ticket</a>
        <a class="btn btn-ghost-light" href="#/architecture">See how it works</a>
      </div>
      <div class="hero-switch" data-llm-switch="on-dark"></div>
    </section>

    <div class="stats" id="stats">
      ${[["Tickets", "total"], ["Agent working", "working"], ["Awaiting your approval", "attn"], ["Pull requests opened", "good"]]
        .map(([l, k]) => `<div class="stat ${k}"><div class="num" data-k="${k}">–</div><div class="label">${l}</div></div>`).join("")}
    </div>

    <div class="section-head"><h2>How it works</h2><a class="small" href="#/architecture">Architecture and design →</a></div>
    <div class="steps">${HOW_STEPS.map(([t, d, who], i) => `
      <div class="step-card"><div class="n">${i + 1}</div><strong>${t}</strong><p>${d}</p><span class="who">${who}</span></div>`).join("")}
    </div>

    <div class="section-head"><h2>Tickets</h2><a class="btn btn-sm" href="#/new">New ticket</a></div>
    <div class="card flush" id="list"><div class="muted" style="padding:14px">Loading…</div></div>`;

  mountLlmSwitches();
  loadInfo(true).then(mountLlmSwitches);

  every(async () => {
    try {
      const { cases } = await api("/cases");
      const counts = {
        total: cases.length,
        working: cases.filter(c => ["NEW", "INVESTIGATING", "APPROVED", "DEVELOPING"].includes(c.state)).length,
        attn: cases.filter(c => c.state === "AWAITING_APPROVAL").length,
        good: cases.filter(c => c.pr_id).length,
      };
      document.querySelectorAll("#stats .num").forEach(n => n.textContent = counts[n.dataset.k]);
      const el = document.getElementById("list");
      if (!el) return;
      if (!cases.length) {
        el.innerHTML = `<div class="empty"><p>No tickets yet. Pick a scenario with a real bug planted in the demo codebase.</p>
          <a class="btn btn-primary" href="#/new">Create the first ticket</a></div>`;
        return;
      }
      el.innerHTML = `<table class="cases"><thead><tr>
          <th>Ticket</th><th>Title</th><th>State</th><th class="hide-sm">Activity</th><th class="hide-sm">PR</th><th class="hide-sm">Updated</th>
        </tr></thead><tbody>${cases.map(c => `
        <tr class="row" data-id="${c.id}">
          <td><a href="#/cases/${c.id}"><strong>${esc(c.ticket_key)}</strong></a></td>
          <td>${esc(c.ticket_title)}</td>
          <td>${badge(c.state)}</td>
          <td class="hide-sm muted small">${esc(taskText(c.current_task, c.state))}</td>
          <td class="hide-sm">${c.pr_id ? `<span class="badge PR_OPEN">${esc(c.pr_id)}</span>` : ""}</td>
          <td class="hide-sm muted small">${ago(c.updated_at)}</td>
        </tr>`).join("")}</tbody></table>`;
      el.querySelectorAll("tr.row").forEach(tr => tr.onclick = () => location.hash = `#/cases/${tr.dataset.id}`);
    } catch (e) {
      const el = document.getElementById("list");
      if (el) el.innerHTML = `<div class="notice bad" style="margin:10px">Could not load tickets: ${esc(e.message)}</div>`;
    }
  });
}

// ---------- new ticket ----------
async function renderNew() {
  app.innerHTML = `
    <div class="page-head"><div><h1>New ticket</h1>
      <div class="muted">Pick a demo scenario to pre-fill a ticket whose logs and code contain a real bug, or write your own.</div></div></div>
    <div class="card llm-card"><div data-llm-switch=""></div></div>
    <div class="card">
      <h2>Scenario</h2>
      <div class="scenarios" id="scenarios"><div class="muted">Loading…</div></div>
    </div>
    <form class="card form-grid" id="form">
      <div><label for="title">Title</label><input type="text" id="title" required maxlength="200"></div>
      <div><label for="description">Description</label><textarea id="description"></textarea></div>
      <div style="max-width:220px"><label for="priority">Priority</label>
        <select id="priority"><option>Low</option><option selected>Medium</option><option>High</option><option>Critical</option></select></div>
      <div><button class="btn btn-primary" type="submit" id="submit">Create ticket</button></div>
    </form>`;
  mountLlmSwitches();
  loadInfo(true).then(mountLlmSwitches);
  let scenarioId = null;
  const box = document.getElementById("scenarios");
  try {
    const { scenarios } = await api("/scenarios");
    const all = [...scenarios, { id: null, title: "Blank ticket", description: "Write your own. The agent will still investigate, but there's no planted bug." }];
    box.innerHTML = all.map((s, i) => `
      <button type="button" class="scenario" data-i="${i}">
        <strong>${esc(s.title)}</strong>
        <span class="muted small">${esc((s.description || "").split("\n")[0].slice(0, 120))}</span>
      </button>`).join("");
    box.querySelectorAll(".scenario").forEach(btn => btn.onclick = () => {
      const s = all[Number(btn.dataset.i)];
      box.querySelectorAll(".scenario").forEach(b => b.classList.remove("selected"));
      btn.classList.add("selected");
      scenarioId = s.id;
      document.getElementById("title").value = s.id ? s.title : "";
      document.getElementById("description").value = s.id ? (s.description || "").trim() : "";
      document.getElementById("priority").value = s.priority || "Medium";
    });
  } catch (e) {
    box.innerHTML = `<div class="notice bad">Could not load scenarios: ${esc(e.message)}</div>`;
  }
  document.getElementById("form").onsubmit = async (ev) => {
    ev.preventDefault();
    const btn = document.getElementById("submit");
    btn.disabled = true; btn.textContent = "Creating…";
    try {
      const c = await api("/tickets", { method: "POST", body: {
        title: document.getElementById("title").value,
        description: document.getElementById("description").value,
        priority: document.getElementById("priority").value,
        scenario_id: scenarioId,
      } });
      location.hash = `#/cases/${c.id}`;
    } catch (e) {
      toast(e.message); btn.disabled = false; btn.textContent = "Create ticket";
    }
  };
}

// ---------- case detail ----------
function stepper(state, c) {
  let idx = STEPS.findIndex(([s]) => s === state);
  let failedAt = -1;
  if (state === "FAILED") failedAt = c.current_task?.type === "DEVELOP" ? 4 : 1;
  if (state === "REJECTED") failedAt = 2;
  if (failedAt >= 0) idx = failedAt;
  return `<div class="stepper">${STEPS.map(([s, label], i) => {
    let cls = i < idx ? "done" : i === idx ? "current" : "";
    if (i === failedAt) cls = "bad";
    if (state === "PR_OPEN" && i === idx) cls = "done";
    const text = i === failedAt ? (state === "REJECTED" ? "Rejected" : "Failed") : label;
    return `<div class="step ${cls}"><span class="dot"></span>${esc(text)}</div>`;
  }).join("")}</div>`;
}

function ticketSection(c) {
  const t = c.ticket;
  if (!t) return `<div class="card"><h2>Ticket</h2><div class="notice bad">${esc(c.ticket_error || "Ticket unavailable")}</div></div>`;
  return `<div class="card"><h2>Ticket ${esc(t.key)}</h2>
    <dl class="kv"><dt>Status</dt><dd>${esc(t.status)}</dd><dt>Priority</dt><dd>${esc(t.priority)}</dd>
      <dt>Reporter</dt><dd>${esc(t.reporter)}</dd></dl>
    <h3>Description</h3><div class="prose">${esc(t.description || "—")}</div>
    ${t.comments?.length ? `<h3>Comments</h3>${t.comments.map(cm => `
      <div class="comment"><div class="muted small">${esc(cm.author)} · ${ago(cm.created_at)}</div><div class="prose">${esc(cm.body)}</div></div>`).join("")}` : ""}
  </div>`;
}

function investigationBody(inv) {
  return `
    <p><strong>${esc(inv.summary)}</strong></p>
    <h3>Root cause</h3><div class="prose">${esc(inv.root_cause)}</div>
    <h3>Evidence</h3>${inv.evidence.length ? `<ul class="evidence">${inv.evidence.map(e => `<li>${esc(e)}</li>`).join("")}</ul>` : `<div class="muted">None given</div>`}
    <h3>Proposed fix</h3><div class="prose">${esc(inv.proposed_fix)}</div>
    ${inv.files_to_change.length ? `<h3>Files to change</h3><div>${inv.files_to_change.map(f => `<code>${esc(f)}</code>`).join(", ")}</div>` : ""}`;
}

function investigationSection(c) {
  const invs = c.investigations;
  if (!invs.length) {
    const msg = c.state === "FAILED" ? "The agent could not complete the investigation." : "The investigator agent is working on this ticket. Follow along in the agent activity panel.";
    return `<div class="card"><h2>Investigation</h2><div class="notice ${c.state === "FAILED" ? "bad" : "info"}">${esc(msg)}</div></div>`;
  }
  const latest = invs[invs.length - 1];
  const reviewFor = id => c.reviews.filter(r => r.investigation_id === id);
  const reviewHtml = rs => rs.map(r => `<div class="comment"><div class="muted small">Reviewer ${esc(r.decision.replace("_", " "))} · ${ago(r.created_at)}</div>${r.comment ? `<div class="prose">${esc(r.comment)}</div>` : ""}</div>`).join("");
  const reinvestigating = c.state === "NEW" || c.state === "INVESTIGATING";
  return `<div class="card">
    <div class="inv-head"><h2 style="margin:0">Investigation v${latest.version}</h2>
      <span class="badge">confidence: ${esc(latest.confidence)}</span></div>
    ${reinvestigating ? `<div class="notice info" style="margin-top:12px">Changes were requested. The agent is preparing a new investigation.</div>` : ""}
    ${investigationBody(latest)}
    ${reviewHtml(reviewFor(latest.id))}
    ${c.state === "AWAITING_APPROVAL" ? `
      <div class="actions">
        <label for="review-comment">Feedback <span class="muted small">(required to request changes or reject)</span></label>
        <textarea id="review-comment" placeholder="Optional for approval"></textarea>
        <div class="row">
          <button class="btn btn-ok" data-act="approve">Approve fix</button>
          <button class="btn" data-act="request-changes">Request changes</button>
          <button class="btn btn-bad" data-act="reject">Reject</button>
        </div>
      </div>` : ""}
    ${invs.length > 1 ? `<div class="older">${invs.slice(0, -1).reverse().map(i => `
      <details><summary>Investigation v${i.version} (superseded)</summary>${investigationBody(i)}${reviewHtml(reviewFor(i.id))}</details>`).join("")}</div>` : ""}
  </div>`;
}

function renderDiff(diff) {
  const files = [];
  let cur = null, oldLn = 0, newLn = 0;
  for (const line of diff.split("\n")) {
    if (line.startsWith("--- ")) continue;
    if (line.startsWith("+++ ")) { cur = { name: line.slice(4).replace(/^b\//, ""), rows: [] }; files.push(cur); continue; }
    if (!cur) continue;
    const h = line.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
    if (h) { oldLn = +h[1]; newLn = +h[2]; cur.rows.push(`<tr class="hunk"><td class="ln"></td><td class="ln"></td><td>${esc(line)}</td></tr>`); continue; }
    if (line.startsWith("+")) cur.rows.push(`<tr class="add"><td class="ln"></td><td class="ln">${newLn++}</td><td>${esc(line)}</td></tr>`);
    else if (line.startsWith("-")) cur.rows.push(`<tr class="del"><td class="ln">${oldLn++}</td><td class="ln"></td><td>${esc(line)}</td></tr>`);
    else if (line.startsWith(" ")) cur.rows.push(`<tr><td class="ln">${oldLn++}</td><td class="ln">${newLn++}</td><td>${esc(line)}</td></tr>`);
  }
  return files.map(f => `<div class="diff"><div class="file">${esc(f.name)}</div><table>${f.rows.join("")}</table></div>`).join("");
}

function prSection(c, pr) {
  if (c.state === "APPROVED" || c.state === "DEVELOPING")
    return `<div class="card"><h2>Pull request</h2><div class="notice info">The developer agent is implementing the approved fix.</div></div>`;
  if (c.state === "FAILED" && c.current_task?.type === "DEVELOP")
    return `<div class="card"><h2>Pull request</h2><div class="notice bad">The developer agent could not create a pull request.</div></div>`;
  if (!c.pull_requests.length) return "";
  if (!pr) return `<div class="card"><h2>Pull request</h2><div class="muted">Loading…</div></div>`;
  return `<div class="card">
    <div class="inv-head"><h2 style="margin:0">${esc(pr.id)}: ${esc(pr.title)}</h2>
      <span class="badge ${pr.tests_passed ? "PR_OPEN" : "FAILED"}">tests ${pr.tests_passed ? "passing" : "failing"}</span></div>
    <div class="prose" style="margin-top:12px">${esc(pr.description)}</div>
    <div class="muted small" style="margin-top:8px">${pr.files_changed.length} file(s) changed · ${ago(pr.created_at)}</div>
    ${renderDiff(pr.diff)}
    <details class="tests"><summary>Test output</summary><pre>${esc(pr.test_output)}</pre></details>
  </div>`;
}

function eventHtml(e) {
  const p = e.payload || {};
  let icon = "•", title = "", meta = "", body = "", extra = "";
  switch (e.kind) {
    case "state_change":
      icon = "◆"; title = `State → ${STATE_LABEL[p.to] || p.to}`; meta = p.reason || ""; break;
    case "info":
      icon = "i"; title = p.message || "";
      if (p.tools) body = p.tools.join(", ");
      break;
    case "llm_message": {
      icon = "AI";
      title = p.content ? p.content.slice(0, 220) + (p.content.length > 220 ? "…" : "") : (p.tool_calls?.length ? "Decided to call a tool" : "(no text)");
      const bits = [p.role, p.seconds != null ? `${p.seconds}s` : null,
        p.prompt_tokens ? `${p.prompt_tokens}→${p.completion_tokens ?? "?"} tokens` : null];
      meta = bits.filter(Boolean).join(" · ");
      if (p.tool_calls?.length) meta += ` · calls ${p.tool_calls.join(", ")}`;
      const parts = [];
      if (p.reasoning) parts.push(`Reasoning:\n${p.reasoning}`);
      if (p.content && p.content.length > 220) parts.push(p.content);
      body = parts.join("\n\n");
      break;
    }
    case "tool_call":
      icon = "→"; title = p.name; body = JSON.stringify(p.arguments, null, 2); meta = "tool call"; break;
    case "tool_result":
      icon = p.is_error ? "!" : "←"; title = `${p.name} ${p.is_error ? "returned a problem" : "returned"}`;
      meta = p.seconds != null ? `${p.seconds}s` : ""; body = p.result || "";
      if (p.is_error) extra = "is-error";
      break;
    case "error":
      icon = "!"; title = p.message || "Error"; body = p.error || ""; break;
  }
  return `<div class="ev ${esc(e.kind)} ${extra}"><div class="icon">${esc(icon)}</div><div>
    <div class="title">${esc(title)}</div>
    <div class="meta">${clock(e.created_at)}${meta ? " · " + esc(meta) : ""}</div>
    ${body ? `<details><summary>Details</summary><pre>${esc(body)}</pre></details>` : ""}
  </div></div>`;
}

function renderCase(id) {
  app.innerHTML = `<div id="case-head"><div class="muted">Loading…</div></div>
    <div id="stepper"></div>
    <div class="layout">
      <div><div id="sec-inv"></div><div id="sec-pr"></div><div id="sec-ticket"></div></div>
      <div class="card timeline-card"><div class="head"><h2>Agent activity</h2><span class="muted small" id="ev-count"></span></div>
        <div class="timeline" id="timeline"><div class="muted small" style="padding:8px">No activity yet.</div></div></div>
    </div>`;
  let lastSig = "", lastEvent = 0, pr = null, eventCount = 0;
  const set = (elId, html) => { const el = document.getElementById(elId); if (el) el.innerHTML = html; };

  async function refresh() {
    let c;
    try { c = await api(`/cases/${id}`); } catch (e) {
      set("case-head", `<div class="notice bad">Could not load case ${id}: ${esc(e.message)}</div>`); return;
    }
    if (c.pull_requests.length && (!pr || pr.id !== c.pull_requests.at(-1).pr_id)) {
      try { pr = await api(`/cases/${id}/pr`); } catch { pr = null; }
    }
    const sig = JSON.stringify([c.state, c.investigations.length, c.reviews.length, c.pull_requests.length, !!pr,
      c.current_task?.status, c.current_task?.attempts, c.ticket?.comments?.length, c.ticket?.status]);
    if (sig !== lastSig) {
      lastSig = sig;
      set("case-head", `<div class="page-head"><div>
          <div class="muted small"><a href="#/">Tickets</a> / ${esc(c.ticket_key)} · case #${c.id}</div>
          <h1>${esc(c.ticket?.title || c.ticket_title)}</h1>
          <div class="muted small" style="margin-top:4px">${esc(taskText(c.current_task, c.state))}</div></div>
        <div style="display:flex;gap:8px;align-items:center">${badge(c.state)}
          ${c.state === "FAILED" ? `<button class="btn btn-sm" id="retry">Retry</button>` : ""}</div></div>`);
      set("stepper", stepper(c.state, c));
      set("sec-inv", investigationSection(c));
      set("sec-pr", prSection(c, pr));
      set("sec-ticket", ticketSection(c));
      wireActions(c);
    }
    try {
      const { events } = await api(`/cases/${id}/events?after=${lastEvent}`);
      if (events.length) {
        const tl = document.getElementById("timeline");
        if (!tl) return;
        if (!lastEvent) tl.innerHTML = "";
        const nearBottom = tl.scrollHeight - tl.scrollTop - tl.clientHeight < 80;
        tl.insertAdjacentHTML("beforeend", events.map(eventHtml).join(""));
        lastEvent = events.at(-1).id; eventCount += events.length;
        set("ev-count", `${eventCount} events`);
        if (nearBottom) tl.scrollTop = tl.scrollHeight;
      }
    } catch { /* keep polling */ }
  }

  function wireActions(c) {
    document.getElementById("retry")?.addEventListener("click", async (ev) => {
      ev.target.disabled = true;
      try { await api(`/cases/${id}/retry`, { method: "POST", body: {} }); lastSig = ""; refresh(); }
      catch (e) { toast(e.message); ev.target.disabled = false; }
    });
    document.querySelectorAll("[data-act]").forEach(btn => btn.addEventListener("click", async () => {
      const act = btn.dataset.act;
      const comment = document.getElementById("review-comment").value.trim();
      if (act !== "approve" && !comment) { toast("Please add feedback first."); return; }
      document.querySelectorAll("[data-act]").forEach(b => b.disabled = true);
      const body = act === "request-changes" ? { feedback: comment } : act === "reject" ? { reason: comment } : { comment };
      try { await api(`/cases/${id}/${act}`, { method: "POST", body }); lastSig = ""; refresh(); }
      catch (e) { toast(e.message); document.querySelectorAll("[data-act]").forEach(b => b.disabled = false); }
    }));
  }

  every(refresh);
}

// ---------- architecture / how it works ----------
const ICONS = {
  search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>',
  person: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="8" r="4"/><path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6"/></svg>',
  check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 12l5 5L20 6"/></svg>',
};

function archDiagram(i) {
  const model = i ? ((i.options || []).find(o => o.id === "real") || {}).model || i.model : "";
  const box = (x, y, title, l1, l2, cls = "") => `
    <rect class="box ${cls}" x="${x}" y="${y}" width="150" height="96" rx="10"/>
    <text class="t" x="${x + 75}" y="${y + 38}" text-anchor="middle">${esc(title)}</text>
    <text class="s" x="${x + 75}" y="${y + 58}" text-anchor="middle">${esc(l1)}</text>
    ${l2 ? `<text class="s" x="${x + 75}" y="${y + 74}" text-anchor="middle">${esc(l2)}</text>` : ""}`;
  const edge = (d, agent = false) => `<path class="edge ${agent ? "agent" : ""}" d="${d}" marker-end="url(#${agent ? "arrA" : "arrG"})"/>`;
  const lbl = (x, y, t, anchor = "middle") => `<text class="lbl" x="${x}" y="${y}" text-anchor="${anchor}">${esc(t)}</text>`;
  return `<svg class="diagram" viewBox="0 0 1030 470" role="img" aria-label="Architecture diagram: browser to reverse proxy to web UI and control plane; agent worker polls the control plane, calls the LLM, and uses the MCP gateway, which calls the demo service and the control plane.">
    <defs>
      <marker id="arrG" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path class="arrow" d="M0,0 L10,5 L0,10 z"/></marker>
      <marker id="arrA" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path class="arrow agent" d="M0,0 L10,5 L0,10 z"/></marker>
    </defs>
    <rect class="zone" x="185" y="8" width="840" height="452" rx="14"/>
    <text class="zone-lbl" x="200" y="28">ONE VM · DOCKER COMPOSE</text>
    ${box(20, 160, "Browser", "Demo user", "")}
    ${box(200, 160, "Reverse proxy", "Caddy", "public port 80")}
    ${box(420, 30, "Web UI", "Static HTML / JS", "served by nginx")}
    ${box(420, 290, "Control plane", "Case state machine", "task queue · SQLite", "hl")}
    ${box(640, 30, "Agent worker", "Investigator and", "developer roles", "hl")}
    ${box(640, 290, "MCP gateway", "jira · logs · repo", "· context tools")}
    ${box(860, 30, "LLM", model || "Ollama", "or scripted mock", "ext")}
    ${box(860, 290, "Demo service", "Fake Jira · logs", "repo + PRs · SQLite")}
    ${edge("M170,208 H198")}
    ${edge("M350,208 H385 V78 H418")}
    ${edge("M385,208 V338 H418")}
    ${lbl(378, 140, "pages", "end")}
    ${lbl(378, 292, "/api/*", "end")}
    ${edge("M790,78 H858", true)}
    ${lbl(825, 66, "LLM calls")}
    ${edge("M715,126 V288", true)}
    ${lbl(723, 205, "tool calls", "start")}
    ${lbl(723, 220, "over MCP", "start")}
    ${edge("M640,100 H605 V320 H572", true)}
    ${lbl(597, 200, "polls tasks,", "end")}
    ${lbl(597, 215, "posts events", "end")}
    ${edge("M790,338 H858")}
    ${lbl(825, 330, "REST")}
    ${edge("M640,356 H572")}
    ${lbl(606, 348, "context")}
    ${edge("M495,386 V430 H935 V388")}
    ${lbl(715, 422, "creates tickets · reads PRs")}
  </svg>`;
}

const FLOW = [
  ["A user creates a ticket in the UI, optionally from a demo scenario.", "human", "You"],
  ["The control plane creates the ticket in the fake Jira, opens a case, and queues an investigate task.", "", "Control plane"],
  ["The agent, polling the task queue, claims the task with a time-limited lease.", "agent", "Agent"],
  ["As investigator, it reads the ticket, searches logs and resolved tickets, reads the code, and submits a root cause and proposed fix.", "agent", "Agent"],
  ["You approve the fix, request changes (the agent re-investigates with your feedback), or reject it.", "human", "You"],
  ["On approval, the control plane queues a develop task.", "", "Control plane"],
  ["As developer, the agent writes search/replace edits plus a regression test, runs the tests, and opens a pull request.", "agent", "Agent"],
  ["The PR, its diff and test results appear on the case, and the Jira ticket moves to In Review.", "human", "You"],
];

const COMPONENTS = [
  ["Web UI", "HTML · JS · nginx", "Create tickets, follow each case live, approve fixes, and read PR diffs and the agent's step-by-step activity."],
  ["Control plane", "Python · Starlette · SQLite", "The source of truth for workflow: case states, the task queue with leases and retries, investigations, reviews and the event timeline."],
  ["Agent worker", "Python · MCP client", "Polls for tasks and runs a tool-calling loop with the LLM. Each role has its own prompt, tool allowlist and step budget."],
  ["MCP gateway", "Python · MCP SDK", "One MCP server exposing Jira, logs, repository and case-context tools over streamable HTTP. The agent only acts through these tools."],
  ["Demo service", "Python · Starlette · SQLite", "Stands in for real systems: a Jira-like ticket store with history, an application log store, and a repository that applies edits, runs tests and renders diffs."],
  ["LLM", "Ollama or any OpenAI-compatible API", "A local open-weight model by default, so the demo runs with no external dependencies. A scripted mock LLM runs alongside it; switch between them from the dashboard."],
  ["Reverse proxy", "Caddy", "The only public entry point: serves the UI and routes /api to the control plane. Internal services are not exposed."],
];

const TOOLS = [
  ["jira_get_ticket", "Read a ticket with its comments", "Investigator"],
  ["jira_search_tickets", "Find similar resolved tickets and their root causes", "Investigator"],
  ["jira_add_comment", "Comment on the ticket", "Developer"],
  ["logs_search", "Search recent application logs by service, level and keywords", "Investigator"],
  ["repo_list_files · repo_read_file · repo_search_code", "Explore and read the codebase", "Both"],
  ["repo_run_tests", "Dry-run edits against the test suite and see the diff", "Developer"],
  ["repo_create_pull_request", "Open a PR. Only succeeds if the edits apply and all tests pass", "Developer"],
  ["context_get_case", "Case state, ticket, previous investigations and reviewer feedback", "Both"],
  ["context_submit_investigation", "Submit the root cause and proposed fix for review", "Investigator"],
  ["context_record_pull_request", "Link the PR to the case", "Developer"],
];

const CHOICES = [
  ["Human approval gate", "The agent can investigate on its own, but no code is written until a person approves the proposed fix."],
  ["Tools, not direct access", "The agent touches tickets, logs and code only through MCP tools, which keeps what it can do explicit and auditable."],
  ["Tests decide, not the model", "Edits are applied to a scratch copy and the full test suite runs before a PR can be created."],
  ["Polling with leases", "The agent claims tasks with a time-limited lease and heartbeats. If it crashes, the task is retried automatically."],
  ["Guardrails for small models", "Search/replace edits instead of diffs, truncated tool output, a forced case id, one nudge if the model stops early, and a check that recovers a PR it forgot to record."],
  ["Everything is observable", "Every model message and tool call is stored on the case and shown live in the activity panel."],
];

function renderArchitecture() {
  const lifecycle = ["NEW", "INVESTIGATING", "AWAITING_APPROVAL", "APPROVED", "DEVELOPING", "PR_OPEN"];
  app.innerHTML = `
    <div class="doc-hero">
      <div class="eyebrow">How it works</div>
      <h1>Architecture of the Ticket-to-PR Agent</h1>
      <p class="lead">An AI agent that turns bug tickets into tested pull requests. It works the way an on-call engineer would:
        read the report, check the logs and past incidents, find the bug in the code, propose a fix, and, once a human
        agrees, ship the patch.</p>
      <div class="toc">
        <a href="#arch-what">What it does</a><a href="#arch-diagram">Architecture</a><a href="#arch-flow">Request flow</a>
        <a href="#arch-components">Components</a><a href="#arch-lifecycle">Case lifecycle</a><a href="#arch-tools">Agent tools</a>
        <a href="#arch-choices">Design choices</a>
      </div>
    </div>

    <div class="section-head" id="arch-what"><h2>What it does</h2></div>
    <div class="pillars">
      <div class="pillar"><div class="ico">${ICONS.search}</div><strong>Investigates like an engineer</strong>
        <p>Correlates the ticket with error logs, similar resolved tickets and the actual source code, then explains the root cause with evidence.</p></div>
      <div class="pillar"><div class="ico">${ICONS.person}</div><strong>Keeps a human in charge</strong>
        <p>Every proposed fix waits for approval. Reviewers can approve, reject, or send feedback that the agent uses in a new investigation.</p></div>
      <div class="pillar"><div class="ico">${ICONS.check}</div><strong>Ships tested code</strong>
        <p>Implements the approved fix with a regression test, and only opens a pull request once the whole test suite passes.</p></div>
    </div>

    <div class="section-head" id="arch-diagram"><h2>Architecture</h2></div>
    <div class="card">
      <div class="diagram-wrap" id="diagram">${archDiagram(info)}</div>
      <div class="legend"><span><i></i>Service-to-service HTTP</span><span><i class="agent"></i>Agent traffic</span>
        <span>Highlighted: orchestration (control plane) and reasoning (agent)</span></div>
      <p class="muted small" style="margin:14px 0 0">Every component runs as its own Docker container on a single VM, started with one script.
        Only the reverse proxy is reachable from the internet.</p>
    </div>

    <div class="section-head" id="arch-flow"><h2>Request flow</h2></div>
    <div class="card"><ol class="flow">${FLOW.map(([t, cls, who]) => `<li><div>${esc(t)}</div><span class="actor ${cls}">${esc(who)}</span></li>`).join("")}</ol></div>

    <div class="section-head" id="arch-components"><h2>Components</h2></div>
    <div class="comp-grid">${COMPONENTS.map(([n, tech, d]) => `
      <div class="comp"><div class="head"><strong>${esc(n)}</strong><span class="tech">${esc(tech)}</span></div><p>${esc(d)}</p></div>`).join("")}
    </div>

    <div class="section-head" id="arch-lifecycle"><h2>Case lifecycle</h2></div>
    <div class="card">
      <div class="lifecycle">${lifecycle.map(s => `<span class="badge ${s}">${STATE_LABEL[s]}</span>`).join('<span class="arr">→</span>')}</div>
      <ul class="lifecycle-notes">
        <li><span class="badge AWAITING_APPROVAL">Awaiting approval</span> → <span class="badge NEW">New</span> when the reviewer requests changes; the agent re-investigates with that feedback.</li>
        <li><span class="badge AWAITING_APPROVAL">Awaiting approval</span> → <span class="badge REJECTED">Rejected</span> when the reviewer rejects the fix.</li>
        <li>Investigating or developing → <span class="badge FAILED">Failed</span> after the agent runs out of attempts. A retry puts the case back in the queue.</li>
      </ul>
    </div>

    <div class="section-head" id="arch-tools"><h2>Agent tools (MCP)</h2></div>
    <div class="card" style="overflow-x:auto"><table class="tools">
      <thead><tr><th>Tool</th><th>What it does</th><th>Used by</th></tr></thead>
      <tbody>${TOOLS.map(([n, d, r]) => `<tr><td><code>${esc(n)}</code></td><td>${esc(d)}</td><td class="muted">${esc(r)}</td></tr>`).join("")}</tbody>
    </table></div>

    <div class="section-head" id="arch-choices"><h2>Design choices</h2></div>
    <div class="card"><div class="choices">${CHOICES.map(([t, d]) => `<div class="choice"><strong>${esc(t)}</strong><p>${esc(d)}</p></div>`).join("")}</div></div>

    <div class="section-head"><h2>Tech stack</h2></div>
    <div class="stack">${["Python 3.12", "Starlette", "SQLite", "Model Context Protocol (MCP)", "Ollama", "OpenAI-compatible API",
      "Docker Compose", "Caddy", "nginx", "Plain HTML/CSS/JS"].map(t => `<span>${esc(t)}</span>`).join("")}</div>`;

  app.querySelectorAll(".toc a").forEach(a => a.addEventListener("click", (ev) => {
    ev.preventDefault();
    document.querySelector(a.getAttribute("href"))?.scrollIntoView({ behavior: "smooth", block: "start" });
  }));
  if (!info) loadInfo().then(i => { const d = document.getElementById("diagram"); if (d) d.innerHTML = archDiagram(i); });
}

loadInfo();
route();
