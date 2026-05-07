# Theme and Design System Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the Back Office dashboard a proper design token system with light and dark themes, a persisted toggle, and a design polish pass so the UI matches the ambition of the product.

**Architecture:** Replace the current hard-coded `:root` CSS variable block in `dashboard/index.html` with a token file loaded by every dashboard page. Themes are selected via a `data-theme="light" | "dark"` attribute on `<html>`. A small `theme.js` module handles first-paint (reading `localStorage.theme`, falling back to `prefers-color-scheme`) and the toggle button. Tokens are grouped by role (surface, text, accent, semantic severity) so adding a third theme later is a palette swap, not a rewrite.

**Tech Stack:** Vanilla CSS custom properties, vanilla JS module, no build step. Same static-asset deploy path as today (`backoffice.sync`).

---

## Chunk 1: Token file and theme runtime

### Task 1: Extract tokens into a shared stylesheet

**Files:**
- Create: `dashboard/theme.css`
- Modify: `dashboard/index.html:11-31` (remove inline `:root` block, link new file)
- Test: `tests/dashboard/test_theme_tokens.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/dashboard/test_theme_tokens.py
"""Structural contract for the theme token file.

Pure text assertions so the test runs without a browser and still
catches the most common regression: someone re-adds a hard-coded
color where a token should live.
"""
from pathlib import Path

THEME_CSS = Path(__file__).resolve().parents[2] / "dashboard" / "theme.css"


REQUIRED_TOKENS = [
    "--bg", "--surface", "--surface-2", "--surface-3",
    "--border", "--text", "--text-dim",
    "--accent", "--accent-2",
    "--critical", "--high", "--medium", "--low", "--info", "--success",
    "--radius", "--sans", "--mono",
]


def test_theme_css_exists():
    assert THEME_CSS.exists(), f"missing {THEME_CSS}"


def test_dark_palette_defines_every_token():
    css = THEME_CSS.read_text()
    dark_block = _extract_block(css, selector=':root, [data-theme="dark"]')
    for token in REQUIRED_TOKENS:
        assert f"{token}:" in dark_block, f"dark theme missing {token}"


def test_light_palette_defines_every_surface_and_text_token():
    css = THEME_CSS.read_text()
    light_block = _extract_block(css, selector='[data-theme="light"]')
    # Light must override every surface/text/border/accent token;
    # semantic severities may share with dark.
    must_override = [
        "--bg", "--surface", "--surface-2", "--surface-3",
        "--border", "--text", "--text-dim",
    ]
    for token in must_override:
        assert f"{token}:" in light_block, f"light theme missing {token}"


def _extract_block(css: str, selector: str) -> str:
    start = css.index(selector)
    open_brace = css.index("{", start)
    close_brace = css.index("}", open_brace)
    return css[open_brace:close_brace]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/dashboard/test_theme_tokens.py -v`
Expected: FAIL with `FileNotFoundError` or `AssertionError: missing theme.css`

- [ ] **Step 3: Write `dashboard/theme.css`**

```css
/* Back Office — theme tokens
 *
 * Two palettes, switched by [data-theme] on <html>.
 * Dark is the default (matches first-paint for existing users).
 */

:root, [data-theme="dark"] {
  /* Surfaces */
  --bg:        #0a0a0f;
  --surface:   #12121a;
  --surface-2: #1a1a26;
  --surface-3: #22222e;
  --border:    #2a2a3a;

  /* Text */
  --text:     #e4e4ef;
  --text-dim: #8888a0;

  /* Brand */
  --accent:   #c4944a;
  --accent-2: #6c5ce7;

  /* Semantic severity */
  --critical: #ff4757;
  --high:     #ff8c42;
  --medium:   #ffd166;
  --low:      #4ecdc4;
  --info:     #74b9ff;
  --success:  #2ed573;

  /* Severity alpha overlays for cells/pills */
  --critical-soft: rgba(255, 71, 87, 0.15);
  --high-soft:     rgba(255, 140, 66, 0.15);
  --medium-soft:   rgba(255, 209, 102, 0.15);
  --low-soft:      rgba(78, 205, 196, 0.15);
  --info-soft:     rgba(116, 185, 255, 0.15);
  --success-soft:  rgba(46, 213, 115, 0.15);

  /* Shadows & radius */
  --radius:   12px;
  --shadow-1: 0 1px 2px rgba(0, 0, 0, 0.4);
  --shadow-2: 0 6px 18px rgba(0, 0, 0, 0.28);

  /* Typography */
  --sans: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
  --mono: 'JetBrains Mono', 'Fira Code', monospace;
}

[data-theme="light"] {
  --bg:        #f7f7fb;
  --surface:   #ffffff;
  --surface-2: #f1f2f7;
  --surface-3: #e6e7ef;
  --border:    #d9dbe5;

  --text:     #1c1d29;
  --text-dim: #5c5e70;

  --accent:   #9a6b1f;       /* darkened for AA contrast on white */
  --accent-2: #4b3fc7;

  --critical-soft: rgba(217, 43, 59, 0.12);
  --high-soft:     rgba(217, 110, 38, 0.12);
  --medium-soft:   rgba(201, 155, 36, 0.16);
  --low-soft:      rgba(36, 167, 157, 0.14);
  --info-soft:     rgba(44, 134, 214, 0.12);
  --success-soft:  rgba(30, 159, 86, 0.14);

  --critical: #d92b3b;
  --high:     #d96e26;
  --medium:   #a3791b;
  --low:      #24a79d;
  --info:     #2c86d6;
  --success:  #1e9f56;

  --shadow-1: 0 1px 2px rgba(20, 24, 40, 0.08);
  --shadow-2: 0 8px 24px rgba(20, 24, 40, 0.10);
}

/* Smooth the flip so toggling doesn't feel like a screen refresh. */
html { transition: background-color 0.15s ease, color 0.15s ease; }
body { background: var(--bg); color: var(--text); }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/dashboard/test_theme_tokens.py -v`
Expected: PASS

- [ ] **Step 5: Strip the inline `:root` block from `dashboard/index.html`**

Modify lines 11-31 of `dashboard/index.html`. Replace the current `<style>` block start:

```html
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<link rel="stylesheet" href="theme.css">
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: var(--sans);
    min-height: 100vh;
    padding-top: 49px;
  }
```

(Note the removed `background:` and `color:` on `body` — those now live in `theme.css`.)

- [ ] **Step 6: Repeat for the other dashboard HTML pages**

For each of `dashboard/migration.html`, `dashboard/deploy.html`, `dashboard/actions-history.html`:
- Add `<link rel="stylesheet" href="theme.css">` after the Google Fonts link.
- Delete the duplicate `:root { … }` block.

Skip `faq-content.html` and `docs-content.html` — they're fragments loaded into slide-overs and inherit tokens.

- [ ] **Step 7: Add `theme.css` to the sync manifest**

Modify `backoffice/sync/manifest.py`:

```python
DASHBOARD_FILES: list[str] = [
    "index.html",
    "migration.html",
    "deploy.html",
    "actions-history.html",
    "faq-content.html",
    "docs-content.html",
    "app.js",
    "theme.css",                                         # <-- added
    "theme.js",                                          # <-- added (next task)
    "site-branding.js", "department-context.js", "favicon.svg",
]
```

`deploy.html` and `actions-history.html` should already be in the list — if they are not, add them while you are here.

- [ ] **Step 8: Commit**

```bash
git add dashboard/theme.css dashboard/index.html dashboard/migration.html \
        dashboard/deploy.html dashboard/actions-history.html \
        backoffice/sync/manifest.py tests/dashboard/test_theme_tokens.py
git commit -m "feat(dashboard): shared theme.css with dark + light palettes"
```

---

### Task 2: Theme runtime (first-paint, toggle, persistence)

**Files:**
- Create: `dashboard/theme.js`
- Modify: `dashboard/index.html` (topbar button + script tag)
- Modify: `dashboard/migration.html`, `dashboard/deploy.html`, `dashboard/actions-history.html` (script tag only)
- Test: `tests/dashboard/test_theme_runtime.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/dashboard/test_theme_runtime.py
"""Smoke-level assertions on dashboard/theme.js.

We do not run the module in a browser here; we assert its public
contract (exports + inline pre-paint snippet) textually, which is
enough to catch accidental regressions like "someone deleted the
first-paint bootstrap and the page flashes dark on every load".
"""
from pathlib import Path

THEME_JS = Path(__file__).resolve().parents[2] / "dashboard" / "theme.js"


def test_theme_js_exists():
    assert THEME_JS.exists()


def test_exports_initThemeToggle():
    assert "export function initThemeToggle" in THEME_JS.read_text()


def test_exports_applyStoredTheme():
    """Called inline before first paint — must be side-effecting."""
    assert "export function applyStoredTheme" in THEME_JS.read_text()


def test_reads_prefers_color_scheme():
    """Fallback when localStorage has no value."""
    src = THEME_JS.read_text()
    assert "matchMedia" in src
    assert "prefers-color-scheme: light" in src


def test_persists_to_localstorage_under_known_key():
    src = THEME_JS.read_text()
    assert "localStorage.setItem('bo.theme'" in src or \
           'localStorage.setItem("bo.theme"' in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/dashboard/test_theme_runtime.py -v`
Expected: FAIL with `FileNotFoundError`

- [ ] **Step 3: Write `dashboard/theme.js`**

```js
// Back Office — theme runtime
//
// Exports two entry points:
//   applyStoredTheme()    — call before first paint (from an inline tag
//                           in <head>) so there is no dark-mode flash on
//                           light-mode users.
//   initThemeToggle(btn)  — wires up a toggle button: updates the DOM,
//                           persists to localStorage, flips the aria
//                           label.
//
// Storage key: 'bo.theme'. Values: 'light' | 'dark'.
// If nothing stored, falls back to prefers-color-scheme.

const KEY = 'bo.theme';

function preferred() {
  const stored = localStorage.getItem(KEY);
  if (stored === 'light' || stored === 'dark') return stored;
  if (window.matchMedia('(prefers-color-scheme: light)').matches) return 'light';
  return 'dark';
}

export function applyStoredTheme() {
  document.documentElement.setAttribute('data-theme', preferred());
}

export function initThemeToggle(btn) {
  if (!btn) return;
  const paint = () => {
    const theme = document.documentElement.getAttribute('data-theme') || 'dark';
    btn.setAttribute('aria-label', `Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`);
    btn.textContent = theme === 'dark' ? 'Light' : 'Dark';
  };
  paint();
  btn.addEventListener('click', () => {
    const next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem(KEY, next);
    paint();
  });
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/dashboard/test_theme_runtime.py -v`
Expected: PASS

- [ ] **Step 5: Insert pre-paint bootstrap into `dashboard/index.html`**

Inside the `<head>`, immediately **before** `<link rel="stylesheet" href="theme.css">`, add:

```html
<script type="module">
  import { applyStoredTheme } from './theme.js';
  applyStoredTheme();
</script>
```

This fires before CSS is applied, so the `data-theme` attribute is set the instant tokens are evaluated — no flash.

- [ ] **Step 6: Add the toggle button**

In `dashboard/index.html:561-563` (the topbar-right block), insert a new button just before the existing `id="docsBtn"` button:

```html
<button class="topbar-btn" id="themeToggle" aria-label="Switch theme">Light</button>
```

- [ ] **Step 7: Wire the toggle from `app.js`**

Near the top of `dashboard/app.js`, after other imports, add:

```js
import { initThemeToggle } from './theme.js';

document.addEventListener('DOMContentLoaded', () => {
  initThemeToggle(document.getElementById('themeToggle'));
});
```

Both `app.js` and `theme.js` must be served as ES modules — update the main `<script>` tag in `index.html` that loads `app.js` to `<script type="module" src="app.js"></script>` if it is not already.

- [ ] **Step 8: Repeat the bootstrap + toggle on the other pages**

For `migration.html`, `deploy.html`, `actions-history.html`:
- Add the pre-paint bootstrap script in `<head>`.
- Add the toggle button in the page's topbar-right if it has one; otherwise skip (the page will still respect the stored theme because the bootstrap runs everywhere).

- [ ] **Step 9: Manual smoke check**

Run: `python3 -m backoffice serve --port 8070`
Open: `http://localhost:8070/`
Click the "Light" button — the page should flip to the light palette and the button should now read "Dark".
Reload the page — the page should stay on the chosen theme (no flash to dark before flipping).

- [ ] **Step 10: Commit**

```bash
git add dashboard/theme.js dashboard/index.html dashboard/app.js \
        dashboard/migration.html dashboard/deploy.html \
        dashboard/actions-history.html \
        tests/dashboard/test_theme_runtime.py
git commit -m "feat(dashboard): light/dark theme toggle with localStorage"
```

---

## Chunk 2: Design polish pass

### Task 3: Audit hard-coded colors remaining in index.html

**Files:**
- Modify: `dashboard/index.html` (CSS block only)

The existing stylesheet has several inline style attributes using raw hex colors (e.g. `style="border-color:rgba(108,92,231,0.45);color:#b9acff;"` on the Migration button at line 557). These break in light mode because they were tuned for dark.

- [ ] **Step 1: Find every inline color style**

Run: `grep -n 'style="[^"]*\(#[0-9a-fA-F]\|rgba\|rgb(\)' dashboard/index.html`
Expected: a list of buttons and badges with hex/rgba inline styles.

- [ ] **Step 2: Replace each with a token class**

For each hit, add a named class to the stylesheet (not inline), e.g.:

```css
.topbar-btn--migration {
  border-color: color-mix(in srgb, var(--accent-2) 45%, transparent);
  color: var(--accent-2);
}
.topbar-btn--deploy {
  border-color: color-mix(in srgb, var(--success) 45%, transparent);
  color: var(--success);
}
.topbar-btn--actions {
  border-color: color-mix(in srgb, var(--accent) 45%, transparent);
  color: var(--accent);
}
```

Then delete the inline `style=` attribute and add the class instead:

```html
<a class="topbar-btn topbar-btn--migration" id="migrationBtn" href="migration.html">Migration</a>
```

`color-mix()` is supported in every browser the dashboard already targets (it is a hard dep on modern Chromium anyway, via the CSP `script-src 'self'`). No polyfill.

- [ ] **Step 3: Validate light mode visually**

Run: `python3 -m backoffice serve --port 8070`
Open each page, toggle light mode, confirm:
- Every button has enough contrast (eyeball the Migration/Deploy/Actions buttons).
- No element is invisible (white-on-white) or illegible (pale-on-pale).
- Severity pills in the matrix cells still read the correct color.

If anything looks wrong, tune the `--*-soft` tokens or the `.sev.*` rules — don't fall back to inline styles.

- [ ] **Step 4: Commit**

```bash
git add dashboard/index.html dashboard/migration.html dashboard/deploy.html
git commit -m "feat(dashboard): tokenize inline colors so they respect theme"
```

---

### Task 4: Typography + spacing rhythm

**Files:**
- Modify: `dashboard/theme.css` (add spacing tokens)
- Modify: `dashboard/index.html` (swap hard-coded rems for tokens)

The current stylesheet uses ad-hoc rems (0.5, 0.7, 0.75, 0.85, 1, 1.25, 1.5, 2). Round them to a 4-step scale.

- [ ] **Step 1: Add spacing + type tokens to `theme.css`**

Append to the `:root, [data-theme="dark"]` block (light inherits these):

```css
  /* Spacing scale — multiples of 4 so everything aligns. */
  --space-1: 0.25rem;   /* 4px */
  --space-2: 0.5rem;    /* 8px */
  --space-3: 0.75rem;   /* 12px */
  --space-4: 1rem;      /* 16px */
  --space-5: 1.5rem;    /* 24px */
  --space-6: 2rem;      /* 32px */

  /* Type scale */
  --text-xs:   0.7rem;
  --text-sm:   0.8rem;
  --text-base: 0.95rem;
  --text-lg:   1.1rem;
  --text-xl:   1.4rem;
  --text-2xl:  1.8rem;
```

- [ ] **Step 2: Swap the highest-traffic spots**

Use find/replace with care — only replace values in the `.container`, `.section-label`, `.score-row`, `.score-card`, `.matrix`, `.finding-row` rules. Example:

```css
.container { max-width: 1400px; margin: 0 auto; padding: var(--space-5); }
.score-row { gap: var(--space-3); margin-bottom: var(--space-5); }
.score-card { padding: var(--space-4); }
```

Don't grind through every rule — the goal is "things line up", not a dogmatic token purity pass.

- [ ] **Step 3: Commit**

```bash
git add dashboard/theme.css dashboard/index.html
git commit -m "feat(dashboard): spacing + type scale tokens"
```

---

### Task 5: Focus-visible + motion-reduced prefs

**Files:**
- Modify: `dashboard/theme.css`

The current stylesheet uses `:focus-visible` inconsistently and always animates `.skeleton`. Both fail accessibility audits on light mode.

- [ ] **Step 1: Add global focus ring and motion guard**

Append to `theme.css`:

```css
:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
  border-radius: 4px;
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
```

- [ ] **Step 2: Run the ADA self-audit as a sanity check**

```bash
python3 -m backoffice audit back-office --departments ada
```

Expected: no new ADA findings introduced by the theme work. Pre-existing findings may remain.

- [ ] **Step 3: Commit**

```bash
git add dashboard/theme.css
git commit -m "feat(dashboard): global focus-visible + reduced-motion guard"
```

---

## Remember

- The theme token file is the source of truth — no hex colors in `index.html` CSS after this plan.
- `applyStoredTheme()` must run pre-paint in a blocking module script, or users hit a theme flash on every load.
- All four HTML pages (`index.html`, `migration.html`, `deploy.html`, `actions-history.html`) get the same bootstrap.
- Everything deploys through the existing `backoffice.sync` — new files must be in `DASHBOARD_FILES` or they never reach the CDN (see the `app.js` incident from 2026-04-20).
