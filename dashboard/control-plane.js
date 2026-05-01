/* Back Office — Control Plane card.
 *
 * Renders four small cards at the bottom of the main dashboard:
 *
 *   • Agents       — agent registry snapshot (/api/agents)
 *   • Recent runs  — last N runs (/api/runs)
 *   • Activity     — last N audit events (/api/audit-events)
 *   • Tokens       — operator-only issue/revoke (auth required)
 *
 * Each card fetches independently and degrades gracefully when an
 * endpoint is unreachable (no API key, server down, etc.). The
 * existing department + matrix + queue surface is untouched.
 *
 * No innerHTML is used anywhere; every node is constructed with
 * textContent + appendChild so untrusted server fields cannot
 * inject markup.
 */
(function () {
  "use strict";

  const ENDPOINTS = {
    agents: "/api/agents",
    runs: "/api/runs",
    audit: "/api/audit-events",
    tokens: "/api/tokens",
  };

  function authHeaders() {
    const apiKey =
      (typeof localStorage !== "undefined" && localStorage.getItem("bo.api_key")) || "";
    return apiKey ? { Authorization: "Bearer " + apiKey } : {};
  }

  async function fetchJson(url) {
    const r = await fetch(url, {
      method: "GET",
      headers: { Accept: "application/json", ...authHeaders() },
      credentials: "same-origin",
    });
    if (!r.ok) {
      const e = new Error("HTTP " + r.status);
      e.status = r.status;
      throw e;
    }
    return r.json();
  }

  async function postJson(url, body) {
    const r = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        ...authHeaders(),
      },
      credentials: "same-origin",
      body: JSON.stringify(body || {}),
    });
    let payload = {};
    try {
      payload = await r.json();
    } catch {
      payload = {};
    }
    if (!r.ok) {
      const e = new Error(payload.error || "HTTP " + r.status);
      e.status = r.status;
      e.payload = payload;
      throw e;
    }
    return payload;
  }

  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    for (const k in attrs || {}) {
      if (k === "class") node.className = attrs[k];
      else if (k === "text") node.textContent = attrs[k];
      else node.setAttribute(k, attrs[k]);
    }
    (children || []).forEach((c) => {
      if (c == null) return;
      node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    });
    return node;
  }

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function fmtTime(iso) {
    if (!iso) return "—";
    try {
      const d = new Date(iso);
      if (isNaN(d.getTime())) return iso;
      const now = new Date();
      const diff = (now - d) / 1000;
      if (diff < 60) return Math.max(1, Math.round(diff)) + "s ago";
      if (diff < 3600) return Math.round(diff / 60) + "m ago";
      if (diff < 86400) return Math.round(diff / 3600) + "h ago";
      return d.toISOString().slice(0, 10);
    } catch {
      return iso;
    }
  }

  function fmtState(state) {
    return el("span", { class: "ops-badge ops-badge-" + (state || "idle") }, [state || "—"]);
  }

  function emptyMessage(text) {
    return el("div", { class: "support-loading", text: text });
  }

  // ─── Agents card ────────────────────────────────────────────────

  async function renderAgents(host) {
    clear(host);
    host.appendChild(
      el("div", { class: "ops-card-header" }, [
        el("div", { class: "ops-card-title", text: "Agents" }),
        el("div", { class: "ops-card-subtitle", text: "Registry · live" }),
      ]),
    );
    try {
      const payload = await fetchJson(ENDPOINTS.agents);
      const agents = payload.agents || [];
      if (!agents.length) {
        host.appendChild(emptyMessage("No agents registered yet."));
        return;
      }
      const list = el("div", {});
      agents.forEach((a) => {
        list.appendChild(
          el("div", { class: "jobs-dept-row" }, [
            el("div", { class: "jobs-dept-name", text: a.name || a.id }),
            fmtState(a.status),
            el("div", { class: "jobs-dept-elapsed", text: a.role || "—" }),
            el("div", { class: "jobs-dept-elapsed", text: a.adapter_type || "—" }),
            el("div", { class: "jobs-dept-elapsed", text: fmtTime(a.updated_at) }),
          ]),
        );
      });
      host.appendChild(list);
    } catch (e) {
      host.appendChild(
        emptyMessage(
          e.status === 401 ? "Sign in (Run · enter API key) to view agents." : "Could not load agents.",
        ),
      );
    }
  }

  // ─── Runs card ──────────────────────────────────────────────────

  async function renderRuns(host) {
    clear(host);
    host.appendChild(
      el("div", { class: "ops-card-header" }, [
        el("div", { class: "ops-card-title", text: "Recent runs" }),
        el("div", { class: "ops-card-subtitle", text: "Last 10" }),
      ]),
    );
    try {
      const payload = await fetchJson(ENDPOINTS.runs);
      const recent = (payload.recent || []).slice(0, 10);
      if (!recent.length) {
        host.appendChild(emptyMessage("No runs yet."));
        return;
      }
      const list = el("div", {});
      recent.forEach((r) => {
        list.appendChild(
          el("div", { class: "jobs-dept-row" }, [
            el("div", { class: "jobs-dept-name", text: r.id }),
            fmtState(r.state),
            el("div", { class: "jobs-dept-elapsed", text: r.task_id || "—" }),
            el("div", { class: "jobs-dept-elapsed", text: r.agent_id || "—" }),
            el("div", { class: "jobs-dept-elapsed", text: fmtTime(r.started_at || r.ended_at) }),
          ]),
        );
      });
      host.appendChild(list);
    } catch (e) {
      host.appendChild(
        emptyMessage(
          e.status === 401 ? "Sign in (Run · enter API key) to view runs." : "Could not load runs.",
        ),
      );
    }
  }

  // ─── Activity feed (audit events) ───────────────────────────────

  async function renderActivity(host) {
    clear(host);
    host.appendChild(
      el("div", { class: "ops-card-header" }, [
        el("div", { class: "ops-card-title", text: "Activity" }),
        el("div", { class: "ops-card-subtitle", text: "Audit log · last 50" }),
      ]),
    );
    try {
      const payload = await fetchJson(ENDPOINTS.audit);
      const events = (payload.events || []).slice(-50).reverse();
      if (!events.length) {
        host.appendChild(emptyMessage("No audit events yet."));
        return;
      }
      const list = el("div", {});
      events.forEach((evt) => {
        list.appendChild(
          el("div", { class: "jobs-dept-row" }, [
            el("div", { class: "jobs-dept-elapsed", text: fmtTime(evt.at) }),
            el("div", { class: "jobs-dept-name", text: evt.action || "—" }),
            el("div", {
              class: "jobs-dept-elapsed",
              text: (evt.subject_kind || "?") + ":" + (evt.subject_id || "?"),
            }),
            el("div", { class: "jobs-dept-elapsed", text: evt.actor_id || "—" }),
            el("div", { class: "jobs-dept-elapsed", text: (evt.reason || "").slice(0, 60) }),
          ]),
        );
      });
      host.appendChild(list);
    } catch (e) {
      host.appendChild(
        emptyMessage(
          e.status === 401
            ? "Sign in (Run · enter API key) to view activity."
            : "Could not load activity.",
        ),
      );
    }
  }

  // ─── Tokens card (operator only) ────────────────────────────────

  async function renderTokens(host) {
    clear(host);
    host.appendChild(
      el("div", { class: "ops-card-header" }, [
        el("div", { class: "ops-card-title", text: "Agent tokens" }),
        el("div", { class: "ops-card-subtitle", text: "Operator only" }),
      ]),
    );

    const agentInput = el("input", {
      class: "ops-form-input",
      type: "text",
      placeholder: "agent-fix",
      id: "bo-token-agent",
    });
    const issueBtn = el("button", { class: "ops-btn ops-btn-primary", type: "submit", text: "Issue" });
    const feedback = el("div", { class: "ops-feedback", id: "bo-token-feedback" });
    const form = el("form", { class: "ops-form-group", id: "bo-token-form" }, [
      el("label", { class: "ops-form-label", text: "Issue token for agent_id" }),
      el("div", { class: "ops-form-row" }, [agentInput, issueBtn]),
      feedback,
    ]);
    host.appendChild(form);

    const list = el("div", { id: "bo-token-list" });
    host.appendChild(list);

    function setFeedback(kind, text, codeText) {
      clear(feedback);
      feedback.classList.remove("success", "error");
      feedback.classList.add(kind);
      feedback.appendChild(document.createTextNode(text));
      if (codeText) {
        feedback.appendChild(document.createElement("br"));
        const code = document.createElement("code");
        code.textContent = codeText;
        feedback.appendChild(code);
      }
    }

    async function refresh() {
      clear(list);
      try {
        const payload = await fetchJson(ENDPOINTS.tokens);
        const tokens = payload.tokens || [];
        if (!tokens.length) {
          list.appendChild(emptyMessage("No tokens issued."));
          return;
        }
        tokens.forEach((t) => {
          const revokeBtn = el("button", {
            class: "ops-btn ops-btn-danger ops-btn-sm",
            type: "button",
            text: "Revoke",
          });
          revokeBtn.addEventListener("click", async () => {
            try {
              await postJson("/api/tokens/revoke", { token_hash: t.token_hash, by: "dashboard" });
              await refresh();
            } catch (e) {
              alert("Revoke failed: " + ((e.payload && e.payload.error) || e.message));
            }
          });
          list.appendChild(
            el("div", { class: "jobs-dept-row" }, [
              el("div", { class: "jobs-dept-elapsed", text: t.token_hash.slice(0, 12) + "…" }),
              el("div", { class: "jobs-dept-name", text: t.agent_id }),
              el("div", { class: "jobs-dept-elapsed", text: (t.scopes || []).length + " scopes" }),
              el("div", { class: "jobs-dept-elapsed", text: fmtTime(t.created_at) }),
              el("div", { class: "jobs-dept-elapsed", text: fmtTime(t.last_used_at) }),
              revokeBtn,
            ]),
          );
        });
      } catch (e) {
        list.appendChild(
          emptyMessage(
            e.status === 401
              ? "Sign in (Run · enter API key) to manage tokens."
              : "Could not load tokens.",
          ),
        );
      }
    }

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const agent = agentInput.value.trim();
      if (!agent) {
        setFeedback("error", "agent_id required");
        return;
      }
      try {
        const result = await postJson("/api/tokens/issue", { agent_id: agent });
        setFeedback("success", "Issued — store this token now (it is not retrievable):", result.token || "");
        await refresh();
      } catch (e) {
        setFeedback("error", "Issue failed: " + ((e.payload && e.payload.error) || e.message));
      }
    });

    await refresh();
  }

  // ─── Mount ──────────────────────────────────────────────────────

  function mount() {
    const main = document.getElementById("main-content");
    if (!main) return;
    if (document.getElementById("bo-control-plane")) return;

    const wrap = el("section", { id: "bo-control-plane", class: "ops-section active" }, [
      el("div", { class: "section-label", text: "Control plane" }),
    ]);
    const grid = el("div", {
      style:
        "display:grid;grid-template-columns:repeat(auto-fit,minmax(380px,1fr));gap:1rem;margin-bottom:1.5rem;",
    });
    const agents = el("div", { class: "ops-card" });
    const runs = el("div", { class: "ops-card" });
    const activity = el("div", { class: "ops-card" });
    const tokens = el("div", { class: "ops-card" });
    grid.appendChild(agents);
    grid.appendChild(runs);
    grid.appendChild(activity);
    grid.appendChild(tokens);
    wrap.appendChild(grid);
    main.appendChild(wrap);

    renderAgents(agents);
    renderRuns(runs);
    renderActivity(activity);
    renderTokens(tokens);

    // Refresh activity every 30s. Other cards refresh on action.
    setInterval(() => renderActivity(activity), 30000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mount);
  } else {
    mount();
  }
})();
