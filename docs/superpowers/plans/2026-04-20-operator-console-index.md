# Operator Console — Index

**What:** Four plans that together turn the Back Office dashboard from a read-only viewer into a full operator console: scans and fixes trigger from the UI, fixes land on preview branches, reviewers walk a checklist, and approvals merge or open PRs. Along the way the UI gains a proper design token system and a light/dark toggle.

**Why now:** admin.codyjo.com already renders the data; the dashboard has never had a way to *act* on it, so operators still shell into the server. These plans close that loop while keeping the conservative-by-default posture of the existing autonomy policy.

**Ship order (each ships on its own):**

1. [2026-04-20-theme-and-design-system.md](2026-04-20-theme-and-design-system.md)
   Design tokens, light/dark themes with a persisted toggle, and a design polish pass. Independent of the other three — ship first and the dashboard gets a visible win before any trigger work lands.

2. [2026-04-20-trigger-panel-and-auth.md](2026-04-20-trigger-panel-and-auth.md)
   Adds the Run slide-over, `/api/run-fix`, and hardens the API server so non-loopback binds require a key. Depends on nothing, but the Fix button is safer after Plan 3 lands — the button checkbox defaults to Preview so the correct path is the default once Plan 3 ships.

3. [2026-04-20-preview-mode-fix-agent.md](2026-04-20-preview-mode-fix-agent.md)
   Teaches `agents/fix-bugs.sh` to land changes on `back-office/preview/<job-id>` and emit `preview.json`. Adds a `backoffice preview` CLI and extends the sync engine to upload preview artifacts. No UI changes.

4. [2026-04-20-review-and-approve-panel.md](2026-04-20-review-and-approve-panel.md)
   Review slide-over reads `preview.json` artifacts, drives a gated checklist, and calls new `/api/approve` / `/api/discard` endpoints. Auto-merge when the per-target autonomy policy allows it, otherwise `gh pr create`.

**Dependency graph:**

```
Plan 1 (theme)        →  (independent)
Plan 2 (trigger UI)   →  hardens API + adds Run button
Plan 3 (preview fix)  →  changes the contract of the Fix button
Plan 4 (review)       →  needs Plan 3's preview.json artifacts
```

Minimum viable slice: Plans 1 + 2 ship a usable operator console with live jobs (no preview yet; fix button should be hidden or disabled until Plan 3 lands, or run against a throwaway target). Plans 3 + 4 unlock the full preview → checklist → approve workflow.

**Scope boundaries (explicitly out):**

- No new data model. All state flows through existing artifacts: `.jobs.json`, `results/<repo>/preview-<job>.json`, the autonomy block in `config/backoffice.yaml`.
- No in-UI diff viewer. The Review panel links to GitHub's compare view; keeping the diff rendering out of the dashboard keeps the surface area small and avoids shipping a second copy of a tool that already exists.
- No multi-operator coordination (no locks, no presence). If two operators hit approve at the same time, the second one sees a merge conflict and retries — acceptable at current team size.
- No schedule-from-UI. The overnight loop keeps owning scheduled runs; the Run panel is for ad-hoc interactive work.

**Tests:** Every plan is TDD — each task has a failing test first, then minimal code, then a passing test. Plans 1, 3, and 4 each land with ≥4 new tests; Plan 2 lands with ≥3 (auth, run-fix, and an e2e smoke verified manually). Run `pytest -x` after each plan's last commit before starting the next.

**Execution:** Use superpowers:subagent-driven-development if available, otherwise superpowers:executing-plans inline. Commit after every green test — the per-task commit messages in each plan are the expected cadence.
