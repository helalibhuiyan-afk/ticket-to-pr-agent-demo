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
function route() {
  timers.forEach(clearInterval); timers = [];
  const hash = location.hash || "#/";
  document.querySelectorAll("[data-nav]").forEach(a => a.classList.remove("active"));
  let m;
  if (hash === "#/new") return renderNew();
  if ((m = hash.match(/^#\/cases\/(\d+)/))) return renderCase(Number(m[1]));
  return renderList();
}
window.addEventListener("hashchange", route);

// ---------- list ----------
function renderList() {
  app.innerHTML = `
    <div class="page-head">
      <div><h1>Tickets</h1><div class="muted">Each ticket becomes a case the agent investigates and fixes.</div></div>
      <a class="btn btn-primary" href="#/new">New ticket</a>
    </div>
    <div class="card" id="list"><div class="muted">Loading…</div></div>`;
  every(async () => {
    try {
      const { cases } = await api("/cases");
      const el = document.getElementById("list");
      if (!el) return;
      if (!cases.length) {
        el.innerHTML = `<div class="empty"><p>No tickets yet.</p><a class="btn btn-primary" href="#/new">Create the first ticket</a></div>`;
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
      if (el) el.innerHTML = `<div class="notice bad">Could not load tickets: ${esc(e.message)}</div>`;
    }
  });
}

// ---------- new ticket ----------
async function renderNew() {
  app.innerHTML = `
    <div class="page-head"><div><h1>New ticket</h1>
      <div class="muted">Pick a demo scenario to pre-fill a ticket whose logs and code contain a real bug, or write your own.</div></div></div>
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

route();
