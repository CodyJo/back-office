"""Tool selection: language string + physical markers → tool list.

The ``Target.language`` field in ``backoffice.yaml`` is a single
unvalidated string today (``"python"``, ``"typescript,terraform"``, ...).
Polyglot repos like ``analogify`` carry one declared language but
contain Python + Terraform + Astro/Node side-by-side, so we always
probe physical markers (``pyproject.toml``, ``package.json``, ``*.tf``)
in addition to honoring the declared language.

``gitleaks`` runs on every repo regardless of language — committed
secrets are language-agnostic and the scan is fast.
"""
from __future__ import annotations

import glob
import os
from dataclasses import dataclass, field


@dataclass
class ScannerContext:
    """Per-scan state passed to every tool adapter."""
    repo_name: str
    repo_path: str
    language: str
    tools: list[str] = field(default_factory=list)
    exclude_patterns: list[str] = field(default_factory=list)
    min_severity: str = "low"
    max_findings: int = 200


# Declared-language → base tool set.
LANGUAGE_TOOLS: dict[str, list[str]] = {
    "python":     ["semgrep", "ruff", "bandit", "pip-audit"],
    "javascript": ["semgrep", "npm-audit"],
    "typescript": ["semgrep", "npm-audit"],
    "js":         ["semgrep", "npm-audit"],
    "ts":         ["semgrep", "npm-audit"],
    "node":       ["semgrep", "npm-audit"],
    "astro":      ["semgrep", "npm-audit"],
    "terraform":  ["semgrep"],
    "hcl":        ["semgrep"],
    "go":         ["semgrep"],
    "rust":       ["semgrep"],
    "ruby":       ["semgrep"],
    "java":       ["semgrep"],
    "kotlin":     ["semgrep"],
}
DEFAULT_TOOLS: list[str] = ["semgrep"]
ALWAYS_RUN: list[str] = ["gitleaks"]


# Physical marker glob → tool to add.
# Probed at repo root and one level deep (catches polyglot subdirs).
MARKER_TOOLS: list[tuple[str, str]] = [
    ("pyproject.toml",   "ruff"),
    ("setup.py",         "ruff"),
    ("setup.cfg",        "ruff"),
    ("pyproject.toml",   "bandit"),
    ("setup.py",         "bandit"),
    ("requirements*.txt", "pip-audit"),
    ("pyproject.toml",   "pip-audit"),
    ("setup.py",         "pip-audit"),
    ("Pipfile",          "pip-audit"),
    ("package.json",     "npm-audit"),
    ("*.tf",             "semgrep"),
]


def _has_marker(repo_path: str, pattern: str) -> bool:
    """Return True if *pattern* matches any file at root or one level deep."""
    if glob.glob(os.path.join(repo_path, pattern)):
        return True
    return bool(glob.glob(os.path.join(repo_path, "*", pattern)))


def _split_languages(language: str) -> list[str]:
    """Split a language string on commas/slashes/whitespace into tokens."""
    if not language:
        return []
    out: list[str] = []
    for chunk in language.replace("/", ",").split(","):
        token = chunk.strip().lower()
        if token:
            out.append(token)
    return out


def _probe_markers(repo_path: str) -> list[str]:
    """Return tools triggered by physical markers in *repo_path*."""
    if not repo_path or not os.path.isdir(repo_path):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for pattern, tool in MARKER_TOOLS:
        if tool in seen:
            continue
        if _has_marker(repo_path, pattern):
            seen.add(tool)
            out.append(tool)
    return out


def discover_tools(repo_path: str, language: str) -> list[str]:
    """Return ordered, deduplicated tool list for *repo_path* / *language*.

    1. Union LANGUAGE_TOOLS for every declared-language token (or DEFAULT).
    2. Add tools triggered by physical markers (handles polyglot repos).
    3. Always append ALWAYS_RUN tools (gitleaks).
    """
    base: list[str] = []
    for token in _split_languages(language):
        base.extend(LANGUAGE_TOOLS.get(token, []))
    if not base:
        base = list(DEFAULT_TOOLS)
    base.extend(_probe_markers(repo_path))
    base.extend(ALWAYS_RUN)
    return list(dict.fromkeys(base))
