"""Pre/post verification for the safe-apply framework.

Runs the target's ``lint_command`` and ``test_command`` (from
``backoffice.yaml``) inside a worktree and reports pass/fail + a
truncated tail of output. The runner uses two of these — one before
mutation, one after — so a regression is detected by *change in pass
status*, not by any individual run failing on its own merits.

Empty / missing commands are recorded as ``None`` — that's not a
failure, just "didn't run."
"""
from __future__ import annotations

import logging
import shlex
import subprocess
from dataclasses import dataclass

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 600
OUTPUT_TAIL_BYTES = 2000


@dataclass
class VerifyResult:
    lint_passed: bool | None  # None = not configured / not run
    tests_passed: bool | None
    output: str

    def is_clean(self) -> bool:
        """True iff every configured check passed (None counts as pass)."""
        return (self.lint_passed in (True, None)) and (self.tests_passed in (True, None))


def _run_one(label: str, cmd: str, cwd: str) -> tuple[bool | None, str]:
    if not cmd or not cmd.strip():
        return None, ""
    try:
        # shell=False with shlex.split keeps us safe from string-injection,
        # which the QA scan flagged as F003. Existing target lint/test
        # commands are simple ("ruff check .", "pytest -q") and parse cleanly.
        argv = shlex.split(cmd)
        proc = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=DEFAULT_TIMEOUT_SECONDS,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError) as exc:
        return False, f"[{label}] failed to run: {exc}"
    tail = (proc.stdout + ("\n" + proc.stderr if proc.stderr else ""))[-OUTPUT_TAIL_BYTES:]
    return proc.returncode == 0, f"[{label}] exit={proc.returncode}\n{tail}"


def verify(repo_path: str, lint_command: str, test_command: str) -> VerifyResult:
    """Run lint + test in *repo_path*. Either may be empty (skipped)."""
    lint_passed, lint_out = _run_one("lint", lint_command, repo_path)
    tests_passed, test_out = _run_one("test", test_command, repo_path)
    parts = [out for out in (lint_out, test_out) if out]
    return VerifyResult(
        lint_passed=lint_passed,
        tests_passed=tests_passed,
        output="\n\n".join(parts),
    )
