#!/usr/bin/env python3
"""Mark a registered application as one that keeps names, or unmark it.

An operator task (names.py, oauth.py *An application that keeps names*). A
client so marked calls the register (/names) with its id and secret: the name
of each person it signs up, and the renames and address changes of people who
have no noesis account yet. The mark is the operator's alone; unmarking stops
it at once, and the secret is untouched, so nobody is disconnected.
add_client.py replaces a registration whole, mark and all, so mark it again
after registering it again.

    docker compose run --rm -T noesis python scripts/client_names.py thefloor
    docker compose run --rm -T noesis python scripts/client_names.py thefloor --off
"""

from __future__ import annotations

import argparse

from noesis.oauth import provider


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("client_id")
    parser.add_argument("--off", action="store_true", help="unmark it")
    args = parser.parse_args(argv)
    data = provider._load()
    raw = data["clients"].get(args.client_id)
    if raw is None:
        raise SystemExit(f"✗ no registered client {args.client_id!r}")
    if not raw.get("client_secret"):
        raise SystemExit(f"✗ {args.client_id!r} has no secret")
    if args.off:
        raw.pop("keeps_names", None)
    else:
        raw["keeps_names"] = True
    provider._save(data)
    print(f"{args.client_id}: {'keeps no names' if args.off else 'keeps names'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
