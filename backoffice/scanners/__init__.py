"""Deterministic scanner layer (Phase 1: QA only).

Free OSS tools (semgrep, ruff, bandit, pip-audit, npm audit, gitleaks)
produce findings in the canonical schema, replacing the bulk of the
Claude-driven QA work that was burning the org's monthly budget.

Public entry point::

    from backoffice.scanners.runner import run_scan
    run_scan(repo_name, repo_path, language, results_dir)

CLI::

    python -m backoffice scan <target>
"""
