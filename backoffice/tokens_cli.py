"""``python -m backoffice tokens ...`` CLI.

Issuing a token prints the **plaintext** to stdout once. The
operator must capture it; only the SHA-256 hash is persisted.
"""
from __future__ import annotations

import argparse
import sys

from backoffice.auth import (
    DEFAULT_AGENT_SCOPES,
    issue_token,
    list_tokens,
    revoke_all_for_agent,
    revoke_token,
)
from backoffice.store import FileStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m backoffice tokens",
        description="Per-agent API tokens",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    issue = sub.add_parser("issue", help="Issue a new token (prints plaintext once)")
    issue.add_argument("--agent-id", required=True)
    issue.add_argument("--scopes", nargs="*", default=None,
                       help=f"Override default scopes (default: {list(DEFAULT_AGENT_SCOPES)})")
    issue.add_argument("--by", default="operator")

    rev = sub.add_parser("revoke", help="Revoke one token")
    rev.add_argument("--token", help="Plaintext token (alternative to --hash)")
    rev.add_argument("--hash", dest="token_hash", help="Token hash")
    rev.add_argument("--by", default="operator")

    rev_all = sub.add_parser("revoke-all", help="Revoke every token for an agent")
    rev_all.add_argument("--agent-id", required=True)
    rev_all.add_argument("--by", default="operator")

    sub.add_parser("list", help="List tokens (hashes only)")

    args = parser.parse_args(argv)
    store = FileStore()

    if args.cmd == "issue":
        token = issue_token(
            store,
            agent_id=args.agent_id,
            scopes=args.scopes,
            actor=args.by,
        )
        print(token)
        return 0

    if args.cmd == "revoke":
        if not (args.token or args.token_hash):
            print("--token or --hash is required", file=sys.stderr)
            return 2
        ok = revoke_token(
            store,
            token=args.token or "",
            token_hash=args.token_hash or "",
            actor=args.by,
        )
        return 0 if ok else 1

    if args.cmd == "revoke-all":
        n = revoke_all_for_agent(store, args.agent_id, actor=args.by)
        print(f"revoked {n} token(s) for {args.agent_id}")
        return 0

    if args.cmd == "list":
        tokens = list_tokens(store)
        if not tokens:
            print("(no tokens)")
            return 0
        for t in tokens:
            print(f"{t.token_hash[:16]}...\t{t.agent_id}\t{','.join(t.scopes)}\tlast_used={t.last_used_at or '-'}")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
