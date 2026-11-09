#!/usr/bin/env python3
"""Mark an application as one that keeps libraries for its groups, or unmark it.

An operator task (members.py). A client so marked owns libraries under its
own id — The Floor's channels, `thefloor/<handle>` — and is asked, at the URL
given, who belongs to each. It signs in here with a token of its own from
auth (client_credentials, `noesis:keep`, which dianoia-auth's scripts/add_client.py
--credentials allows), and noesis asks it with noesis's own token (scope
`<client id>:members`). Marking makes `libraries/<client id>/`; hold the
name at auth too (its scripts/accounts.py hold), so no person signs up as it.
Unmarking stops every member's access at once and keeps the libraries.

    docker compose run --rm -T noesis python scripts/client_libraries.py thefloor https://thefloor.rvanegas.co
    docker compose run --rm -T noesis python scripts/client_libraries.py thefloor --off
"""

from __future__ import annotations

import argparse

from noesis import members, service


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("client_id")
    parser.add_argument("url", nargs="?", help="where the application answers, https://…")
    parser.add_argument("--off", action="store_true", help="unmark it")
    args = parser.parse_args(argv)
    if args.off:
        members.mark(args.client_id, None)
        print(f"{args.client_id}: keeps no libraries")
        return 0
    if not args.url or not args.url.startswith("https://"):
        raise SystemExit("✗ the URL it answers at, https://…")
    if not service.NAME_RE.match(args.client_id):
        raise SystemExit(f"✗ {args.client_id!r} is not a library owner's name")
    if members.keeper(args.client_id) is None and (service.data_dir() / "libraries" / args.client_id).exists():
        raise SystemExit(f"✗ {args.client_id!r} is somebody's name")
    (service.data_dir() / "libraries" / args.client_id).mkdir(parents=True, exist_ok=True)
    members.mark(args.client_id, args.url)
    print(f"{args.client_id}: keeps libraries, asking {args.url.rstrip('/')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
