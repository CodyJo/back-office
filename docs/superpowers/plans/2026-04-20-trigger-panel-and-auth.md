# Trigger Panel and Auth Hardening Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the dashboard from a read-only viewer into an operator console: start scans and fix runs for any target repo from a dashboard panel, watch live job progress, and stop the open-access API server backdoor.

**Architecture:** Extend the existing `backoffice/api_server.py` with a fix endpoint and tightened auth (API key required on any non-loopback bind). Add a new "Run" slide-over panel in `dashboard/index.html` that drives those endpoints from the browser. The API key is stored per-browser in `localStorage` and sent on every mutating request as `X-API-Key`. Job progress flows through the existing `GET /api/jobs` + `.jobs.json` artifact — no new data model.

**Tech Stack:** Python stdlib (`http.server`, `hmac`), vanilla JS, existing `backoffice.config` for key material.

---

## Chunk 1: Auth hardening

### Task 1: Require an API key on mutating endpoints and for any public bind

**Files:**
- Modify: `backoffice/api_server.py:201-211` (`_check_auth`)
- Modify: `backoffice/api_server.py:443-527` (`main`)
- Test: `tests/test_api_server_auth.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api_server_auth.py
"""Auth contract for the API server.

Goal: production-bound traffic cannot trigger scans without a valid
X-API-Key, and the server refuses to start in an insecure configuration.
"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
import http.server

import pytest

from backoffice.api_server import create_api_handler


@pytest.fixture
def server(tmp_path):
    """A handler configured with a known key, bound to a free loopback port."""
    handler_cls = create_api_handler(
        root=tmp_path,
        api_key="test-key-abc",
        allowed_origins=["*"],
        targets={},
    )
    srv = http.server.HTTPServer(("127.0.0.1", 0), handler_cls)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield srv
    finally:
        srv.shutdown()
        srv.server_close()


def _post(url, body, headers=None):
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_post_without_key_is_rejected(server):
    port = server.server_address[1]
    code, body = _post(f"http://127.0.0.1:{port}/api/run-scan", {"department": "qa"})
    assert code == 401
    assert "error" in body


def test_post_with_wrong_key_is_rejected(server):
    port = server.server_address[1]
    code, _ = _post(
        f"http://127.0.0.1:{port}/api/run-scan",
        {"department": "qa"},
        headers={"X-API-Key": "nope"},
    )
    assert code == 401


def test_get_jobs_does_not_require_key(server):
    """Read-only endpoints stay open for dashboard polling."""
    port = server.server_address[1]
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/jobs") as resp:
        assert resp.status == 200


def test_main_refuses_public_bind_without_key():
    """A server bound to 0.0.0.0 with no api_key must refuse to start."""
    from backoffice.api_server import main
    from backoffice.config import Config

    cfg = Config()
    cfg.api.api_key = ""
    cfg.api.port = 0

    code = main(argv=["--bind", "0.0.0.0"], config=cfg)
    assert code == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api_server_auth.py -v`
Expected: the first three tests fail (auth is today optional); the fourth may or may not fail depending on current defaults — we will make it deterministic.

- [ ] **Step 3: Tighten `_check_auth`**

Replace `backoffice/api_server.py:201-211` with:

```python
def _check_auth(self) -> bool:
    """Return True if the request passes auth checks.

    Rules:
    - When ``api_key`` is empty the server treats the request as trusted
      (dev loopback only; :func:`main` refuses to start if this is paired
      with a non-loopback bind).
    - Otherwise the client must send ``X-API-Key`` and it must match via
      :func:`hmac.compare_digest`.
    """
    key = self._api_key
    if not key:
        return True
    provided = self.headers.get("X-API-Key", "")
    if not provided:
        return False
    return hmac.compare_digest(provided, key)
```

- [ ] **Step 4: Tighten `main()` — refuse public bind with no key**

Replace the security gate block near `backoffice/api_server.py:494`:

```python
# Security gate: non-loopback bind requires an API key.
if bind_addr not in ("127.0.0.1", "localhost", "::1") and not api_key:
    logger.error(
        "Refusing to start: non-loopback bind (%s) requires api.api_key in "
        "config/backoffice.yaml. Generate one with `openssl rand -hex 24`.",
        bind_addr,
    )
    return 1
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_api_server_auth.py -v`
Expected: PASS.

- [ ] **Step 6: Run full test suite to catch regressions**

Run: `pytest -x`
Expected: no new failures.

- [ ] **Step 7: Commit**

```bash
git add backoffice/api_server.py tests/test_api_server_auth.py
git commit -m "feat(api): require X-API-Key on mutating endpoints"
```

---

### Task 2: Add `/api/run-fix` endpoint

**Files:**
- Modify: `backoffice/api_server.py` (new handler + route)
- Test: `tests/test_api_server_run_fix.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api_server_run_fix.py
"""/api/run-fix launches agents/fix-bugs.sh for a configured target."""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
import http.server

import pytest

import backoffice.api_server as api


class _FakeTarget:
    def __init__(self, path):
        self.path = path


@pytest.fixture
def server(tmp_path, monkeypatch):
    calls = []

    def fake_run_fix_agent(target, preview=False, root=None):
        calls.append([target, str(preview)])
        return True

    monkeypatch.setattr(api, "run_fix_agent", fake_run_fix_agent)

    handler_cls = api.create_api_handler(
        root=tmp_path,
        api_key="k",
        allowed_origins=["*"],
        targets={"myrepo": _FakeTarget("/tmp/myrepo")},
    )
    srv = http.server.HTTPServer(("127.0.0.1", 0), handler_cls)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield srv, calls
    finally:
        srv.shutdown()
        srv.server_close()


def test_run_fix_happy_path(server):
    srv, calls = server
    port = srv.server_address[1]
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/run-fix",
        data=json.dumps({"target": "myrepo"}).encode(),
        headers={"Content-Type": "application/json", "X-API-Key": "k"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        body = json.loads(resp.read())
    assert body["status"] == "started"
    assert body["target"] == "/tmp/myrepo"
    assert calls == [["/tmp/myrepo", "False"]]


def test_run_fix_unknown_target(server):
    srv, _ = server
    port = srv.server_address[1]
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/run-fix",
        data=json.dumps({"target": "ghost"}).encode(),
        headers={"Content-Type": "application/json", "X-API-Key": "k"},
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req)
    assert exc.value.code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api_server_run_fix.py -v`
Expected: FAIL with `AttributeError: module 'backoffice.api_server' has no attribute 'run_fix_agent'`.

- [ ] **Step 3: Add the `run_fix_agent` helper**

Insert near `run_agent` in `backoffice/api_server.py`:

```python
running_fix: dict[str, threading.Thread] = {}
running_fix_lock = threading.Lock()


def run_fix_agent(target: str, *, preview: bool = False,
                  root: Path | None = None) -> bool:
    """Launch agents/fix-bugs.sh in a background thread.

    Returns ``True`` when the job was accepted, ``False`` if a fix is
    already running against the same target.
    """
    r = root or _root
    args = ["bash", str(r / "agents" / "fix-bugs.sh"), target, "--sync"]
    if preview:
        args.append("--preview")

    def _run() -> None:
        try:
            subprocess.run(args, cwd=str(r))
        finally:
            with running_fix_lock:
                running_fix.pop(target, None)

    with running_fix_lock:
        if target in running_fix:
            return False
        t = threading.Thread(target=_run, daemon=True)
        running_fix[target] = t

    t.start()
    logger.info("Started fix agent target=%s preview=%s", target, preview)
    return True
```

- [ ] **Step 4: Add the route handler**

In `APIHandler.do_POST`, add a branch:

```python
        elif path == "/api/run-fix":
            self._handle_run_fix()
```

And add the method on `APIHandler`:

```python
    def _handle_run_fix(self) -> None:
        body = self._read_body()
        if body is None:
            return
        site = body.get("target", body.get("site", ""))
        preview = bool(body.get("preview", False))

        target = resolve_target(site, self._targets)
        if not target:
            self._json_response(400, {
                "error": "Unknown target. Check config/backoffice.yaml.",
                "targets": list(self._targets.keys()),
            })
            return

        started = run_fix_agent(target, preview=preview, root=self._root)
        self._json_response(200 if started else 409, {
            "status": "started" if started else "already_running",
            "target": target,
            "preview": preview,
        })
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_api_server_run_fix.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backoffice/api_server.py tests/test_api_server_run_fix.py
git commit -m "feat(api): /api/run-fix endpoint launches fix agent"
```

---

## Chunk 2: Dashboard trigger panel

### Task 3: Run panel shell + open/close wiring

**Files:**
- Modify: `dashboard/index.html` (add the slide-over markup + CSS)
- Modify: `dashboard/app.js` (open/close + button)

- [ ] **Step 1: Add the "Run" button to the topbar**

In `dashboard/index.html` near line 561 (topbar-right), insert before `id="jobsBtn"`:

```html
<button class="topbar-btn topbar-btn--run" id="runBtn" aria-label="Open run panel">Run</button>
```

Add to the CSS block:

```css
.topbar-btn--run {
  border-color: color-mix(in srgb, var(--accent) 55%, transparent);
  color: var(--accent);
}
```

- [ ] **Step 2: Add the slide-over markup**

Near the existing slide-over panels, add the `<aside>` with sections for **Audit scan**, **Fix findings**, **Live jobs**, and a stop footer. Keep the DOM static — no dynamic string injection — and use `<select>`, `<label>`, `<button>` tags directly. Id hooks: `runPanel`, `runPanelClose`, `runTarget`, `runDept`, `runParallel`, `runScanBtn`, `runFixPreview`, `runFixBtn`, `runLiveJobs`, `runStopBtn`, `runStatus`.

```html
<aside id="runPanel" class="slide-over" hidden aria-labelledby="runPanelTitle">
  <header class="slide-over-header">
    <h2 id="runPanelTitle">Run</h2>
    <button class="slide-over-close" id="runPanelClose" aria-label="Close">×</button>
  </header>

  <section class="run-section">
    <h3>Audit scan</h3>
    <label for="runTarget">Target repository</label>
    <select id="runTarget" class="product-select"></select>

    <label for="runDept">Department</label>
    <select id="runDept" class="product-select">
      <option value="qa">QA</option>
      <option value="seo">SEO</option>
      <option value="ada">ADA</option>
      <option value="compliance">Compliance</option>
      <option value="monetization">Monetization</option>
      <option value="product">Product</option>
      <option value="cloud-ops">Cloud Ops</option>
      <option value="__all__">All departments</option>
    </select>

    <label><input type="checkbox" id="runParallel"> Run in parallel</label>
    <button class="run-primary" id="runScanBtn">Start scan</button>
  </section>

  <section class="run-section">
    <h3>Fix findings</h3>
    <p class="run-hint">
      Applies findings flagged <code>fixable_by_agent</code>. Preview lands
      changes on an isolated branch for review before merging to main.
    </p>
    <label><input type="checkbox" id="runFixPreview" checked> Preview mode (recommended)</label>
    <button class="run-primary" id="runFixBtn">Start fix</button>
  </section>

  <section class="run-section">
    <h3>Live jobs</h3>
    <pre id="runLiveJobs" aria-live="polite">Idle.</pre>
  </section>

  <footer class="run-footer">
    <button class="run-secondary" id="runStopBtn">Stop all</button>
    <span id="runStatus" class="run-status" aria-live="polite"></span>
  </footer>
</aside>
```

Add the CSS (near the other slide-over rules):

```css
.slide-over {
  position: fixed;
  top: 49px; right: 0; bottom: 0;
  width: min(420px, 92vw);
  background: var(--surface);
  border-left: 1px solid var(--border);
  box-shadow: var(--shadow-2);
  overflow-y: auto;
  z-index: 70;
  padding: var(--space-5);
}
.slide-over[hidden] { display: none; }
.slide-over-header {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: var(--space-4);
}
.slide-over-close {
  background: none; border: none; font-size: 1.6rem; color: var(--text-dim);
  cursor: pointer; line-height: 1;
}
.run-section { margin-bottom: var(--space-5); }
.run-section h3 {
  font-size: var(--text-sm);
  text-transform: uppercase; letter-spacing: 0.08em;
  color: var(--text-dim); margin-bottom: var(--space-3);
}
.run-section label { display: block; font-size: var(--text-sm); margin: var(--space-3) 0 var(--space-1); }
.run-section .product-select { width: 100%; }
.run-hint { font-size: var(--text-sm); color: var(--text-dim); margin-bottom: var(--space-3); }
.run-primary {
  display: block; width: 100%;
  background: var(--accent); color: var(--bg);
  border: none; border-radius: 8px;
  padding: var(--space-3); font-weight: 600;
  margin-top: var(--space-3); cursor: pointer;
}
.run-primary[disabled] { opacity: 0.5; cursor: not-allowed; }
.run-secondary {
  background: transparent; color: var(--text-dim);
  border: 1px solid var(--border); border-radius: 8px;
  padding: var(--space-2) var(--space-3); cursor: pointer;
}
.run-status { font-size: var(--text-sm); color: var(--text-dim); margin-left: var(--space-3); }
#runLiveJobs {
  font-family: var(--mono); font-size: var(--text-sm);
  color: var(--text); white-space: pre; overflow-x: auto;
  background: var(--surface-2); padding: var(--space-3); border-radius: 8px;
}
```

- [ ] **Step 3: Wire open/close in `app.js`**

```js
function openRunPanel() {
  const panel = document.getElementById('runPanel');
  panel.hidden = false;
  populateRunTargets();
  startLiveJobsPoll();
}
function closeRunPanel() {
  document.getElementById('runPanel').hidden = true;
  stopLiveJobsPoll();
}

document.getElementById('runBtn').addEventListener('click', openRunPanel);
document.getElementById('runPanelClose').addEventListener('click', closeRunPanel);
```

- [ ] **Step 4: Commit the shell**

```bash
git add dashboard/index.html dashboard/app.js
git commit -m "feat(dashboard): run panel shell"
```

---

### Task 4: Wire the scan + fix buttons to the API

**Files:**
- Modify: `dashboard/app.js`

- [ ] **Step 1: Add an API client with key retrieval**

Near the top of `app.js`:

```js
const API_KEY_STORAGE = 'bo.api_key';

function getApiKey() {
  let k = localStorage.getItem(API_KEY_STORAGE);
  if (!k) {
    k = prompt('Back Office API key (one-time):') || '';
    if (k) localStorage.setItem(API_KEY_STORAGE, k);
  }
  return k;
}

async function apiPost(path, body) {
  const key = getApiKey();
  if (!key) throw new Error('API key required');
  const resp = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-API-Key': key },
    body: JSON.stringify(body || {}),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const err = new Error(data.error || `HTTP ${resp.status}`);
    err.status = resp.status;
    err.data = data;
    throw err;
  }
  return data;
}

async function apiGet(path) {
  const resp = await fetch(path);
  if (!resp.ok) throw new Error(`GET ${path}: HTTP ${resp.status}`);
  return resp.json();
}
```

- [ ] **Step 2: Populate the target select from `/api/status`**

Build options with DOM methods (no innerHTML):

```js
async function populateRunTargets() {
  const select = document.getElementById('runTarget');
  if (select.dataset.populated === '1') return;
  while (select.firstChild) select.removeChild(select.firstChild);
  try {
    const status = await apiGet('/api/status');
    for (const t of status.targets || []) {
      const opt = document.createElement('option');
      opt.value = t;
      opt.textContent = t;
      select.appendChild(opt);
    }
    select.dataset.populated = '1';
  } catch (e) {
    const opt = document.createElement('option');
    opt.textContent = '— API unreachable —';
    opt.disabled = true;
    select.appendChild(opt);
  }
}
```

- [ ] **Step 3: Wire the Start scan button**

```js
document.getElementById('runScanBtn').addEventListener('click', async () => {
  const target = document.getElementById('runTarget').value;
  const dept = document.getElementById('runDept').value;
  const parallel = document.getElementById('runParallel').checked;
  const status = document.getElementById('runStatus');
  const btn = document.getElementById('runScanBtn');
  btn.disabled = true;
  status.textContent = 'Starting…';
  try {
    const path = dept === '__all__' ? '/api/run-all' : '/api/run-scan';
    const body = dept === '__all__' ? { target, parallel } : { target, department: dept };
    const r = await apiPost(path, body);
    status.textContent = r.status === 'started' ? 'Running' : r.status;
  } catch (e) {
    status.textContent = `Error: ${e.message}`;
  } finally {
    btn.disabled = false;
  }
});
```

- [ ] **Step 4: Wire the Start fix button**

```js
document.getElementById('runFixBtn').addEventListener('click', async () => {
  const target = document.getElementById('runTarget').value;
  const preview = document.getElementById('runFixPreview').checked;
  const status = document.getElementById('runStatus');
  const btn = document.getElementById('runFixBtn');
  btn.disabled = true;
  status.textContent = 'Starting fix…';
  try {
    const r = await apiPost('/api/run-fix', { target, preview });
    status.textContent = r.status === 'started'
      ? (preview ? 'Running (preview branch will appear in Review panel)' : 'Running')
      : r.status;
  } catch (e) {
    status.textContent = `Error: ${e.message}`;
  } finally {
    btn.disabled = false;
  }
});
```

- [ ] **Step 5: Wire Stop all**

```js
document.getElementById('runStopBtn').addEventListener('click', async () => {
  const status = document.getElementById('runStatus');
  try {
    const r = await apiPost('/api/stop', {});
    status.textContent = r.message || 'Stop requested';
  } catch (e) {
    status.textContent = `Error: ${e.message}`;
  }
});
```

- [ ] **Step 6: Live jobs poll (textContent only)**

```js
let _liveJobsTimer = null;

function renderLiveJobs(data) {
  const host = document.getElementById('runLiveJobs');
  if (!data || !data.jobs) { host.textContent = 'Idle.'; return; }
  const rows = Object.entries(data.jobs).map(([dept, j]) => {
    const state = (j.status || '?').padEnd(10);
    const elapsed = (j.elapsed ? `${j.elapsed}s` : '').padEnd(6);
    const found = j.findings_count != null ? `${j.findings_count} findings` : '';
    return `${dept.padEnd(14)} ${state} ${elapsed} ${found}`;
  });
  host.textContent = rows.join('\n') || 'Idle.';
}

function startLiveJobsPoll() {
  if (_liveJobsTimer) return;
  const tick = async () => {
    try { renderLiveJobs(await apiGet('/api/jobs')); }
    catch { /* keep trying */ }
  };
  tick();
  _liveJobsTimer = setInterval(tick, 3000);
}
function stopLiveJobsPoll() {
  if (_liveJobsTimer) clearInterval(_liveJobsTimer);
  _liveJobsTimer = null;
}
```

- [ ] **Step 7: Smoke check**

```bash
BACK_OFFICE_API_KEY=dev-key python3 -m backoffice api-server --port 8071 &
python3 -m backoffice serve --port 8070 &
```

Open `http://localhost:8070/`, click Run, paste `dev-key`, pick a target + QA, click Start scan. Expected: status reads "Running", Live jobs populates within a few seconds.

- [ ] **Step 8: Commit**

```bash
git add dashboard/app.js
git commit -m "feat(dashboard): wire run panel to /api/run-scan /api/run-fix /api/stop"
```

---

## Chunk 3: Docs + config

### Task 5: Document the API key setup

**Files:**
- Modify: `README.md`
- Modify: `config/backoffice.bunny.example.yaml`

- [ ] **Step 1: Add a "Dashboard triggers" section to README**

Insert after the existing "Dashboard" section:

```markdown
### Dashboard triggers

The dashboard's Run panel calls `backoffice/api_server.py` directly.

Setup:

1. Generate an API key: `openssl rand -hex 24`
2. Add to `config/backoffice.yaml`:

   ```yaml
   api:
     port: 8071
     api_key: <your-key>
     allowed_origins:
       - https://admin.codyjo.com
       - http://localhost:8070
   ```

3. Start the server: `python3 -m backoffice api-server --bind 0.0.0.0 --port 8071`
4. In the dashboard, click **Run** and paste the key when prompted
   (stored per-browser in localStorage under `bo.api_key`).

The server refuses to start on a non-loopback bind without a key.
```

- [ ] **Step 2: Mirror in the example config**

Add an `api:` block to `config/backoffice.bunny.example.yaml`:

```yaml
api:
  port: 8071
  # Generate with: openssl rand -hex 24
  api_key: "<required-when-binding-publicly>"
  allowed_origins:
    - https://admin.codyjo.com
    - http://localhost:8070
```

- [ ] **Step 3: Commit**

```bash
git add README.md config/backoffice.bunny.example.yaml
git commit -m "docs(api): dashboard trigger + key setup"
```

---

## Remember

- The API key must be required for any non-loopback bind — if a future change weakens this, self-audit will complain.
- `/api/jobs` stays open (read-only) so the dashboard can poll without re-prompting for a key on each page load.
- Never use `innerHTML` for anything the user or API could influence — build options/rows with `createElement` + `textContent`. The dashboard CSP blocks inline scripts, but DOM XSS via unsafe HTML would still be real.
- Ship Plan 3 (preview-mode fix) before making the Run panel visible to non-operators — without preview, the fix button edits `main` on target repos directly.
