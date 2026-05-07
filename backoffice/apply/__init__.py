"""Safe auto-remediation framework.

Takes a finding from the canonical schema, resolves a fix strategy,
applies it inside an isolated git worktree, verifies via the target's
own ``lint_command`` + ``test_command``, then commits — or rolls back
if verification fails.

Defaults to **dry-run**. Mutating runs require ``--apply`` *and* the
target's :class:`backoffice.config.Autonomy` policy to allow ``fix``.
Pushing branches, opening PRs, and deploying are explicitly out of
scope — those are touchpoints that demand operator consent.

Public entry point::

    python -m backoffice apply <target>
"""
