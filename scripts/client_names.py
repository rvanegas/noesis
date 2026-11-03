#!/usr/bin/env python3
"""Mark a registered application as one that keeps names, with its hook, or unmark it.

An operator task (names.py, oauth.py *An application that keeps names*). A
client so marked calls the register (/names) with its id and secret — the
name of each person it signs up, and each rename one of them makes there —
and is told of every rename made anywhere else by a POST to its hook, signed
with its secret. The Floor's hook is its `/noesis/renamed`. Unmarking stops
both at once and drops the renames still owed to it; the secret is untouched,
so nobody is disconnected.

    docker compose run --rm -T noesis python scripts/client_names.py thefloor \\
        --hook https://thefloor.rvanegas.co/noesis/renamed
    docker compose run --rm -T noesis python scripts/client_names.py thefloor --off
"""

from __future__ import annotations

import argparse
from urllib.parse import urlparse

from noesis import accounts
from noesis.oauth import provider


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("client_id")
    parser.add_argument("--hook", help="where it is told of renames, https")
    parser.add_argument("--off", action="store_true", help="unmark it")
    args = parser.parse_args(argv)
    if bool(args.hook) == args.off:
        raise SystemExit("✗ either --hook or --off")
    data = provider._load()
    raw = data["clients"].get(args.client_id)
    if raw is None:
        raise SystemExit(f"✗ no registered client {args.client_id!r}")
    if not raw.get("client_secret"):
        raise SystemExit(f"✗ {args.client_id!r} has no secret")
    if args.off:
        raw.pop("names_hook", None)
        with accounts.connect() as db:
            db.execute("DELETE FROM name_changes WHERE client = ?", (args.client_id,))
    else:
        hook = urlparse(args.hook)
        if not (hook.scheme == "https" and hook.hostname):
            raise SystemExit(f"✗ the hook must be an https URL: {args.hook!r}")
        raw["names_hook"] = args.hook
    provider._save(data)
    print(f"{args.client_id}: {'keeps names, told at ' + args.hook if not args.off else 'keeps no names'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
