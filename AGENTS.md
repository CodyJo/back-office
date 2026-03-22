# Project Agent Rules

Follow the workspace rules in [/home/merm/projects/AGENTS.md](/home/merm/projects/AGENTS.md).

## Required Handoff

For any meaningful or unfinished work in this repo:

- create or update `docs/HANDOFF.md` before stopping
- if `docs/HANDOFF.md` does not exist, create it
- link it from `README.md` when practical

The handoff must cover current direction, completed work, pending work, constraints, key files, integrations, next steps, and verification state.

## Context Hygiene

Back Office should optimize for small, effective context windows.

Core rules:

- load only the files needed for the current task
- prefer summaries over dumping large blobs into prompts
- delegate narrow subproblems instead of handing one agent the whole repo
- keep prompts explicit about desired output shape
- avoid re-reading the same large files unless something materially changed

## Effective Use Patterns

Use these patterns as the default operating model:

- `inspect -> summarize -> act`
  Read the minimum relevant files, summarize the situation, then modify or delegate.
- `delegate narrowly`
  Send Claude or another agent a bounded analysis task, not a vague whole-repo mission.
- `gate with facts`
  Use real repo scripts, test output, and audit artifacts as gates instead of narrative confidence.
- `refresh only when needed`
  Recompute dashboards and audit payloads when work changes the underlying state, not on every tiny step.
- `handoff before stop`
  If work is substantial or incomplete, update the repo handoff before ending.
