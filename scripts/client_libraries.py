#!/usr/bin/env python3
"""Mark a registered application as one that keeps libraries for its groups, or unmark it.

An operator task (members.py, oauth.py *An application that keeps libraries*).
A client so marked owns libraries under its own id — The Floor's channels,
`thefloor/<handle>` — and is asked, at the URL given, who belongs to each.
Marking makes `libraries/<client id>/`, which takes the name in the register
so that no person can sign up as it; a name a person already holds refuses.
Unmarking stops every member's access at once and keeps the libraries.
add_client.py replaces a registration whole, mark and all, so mark it again
after registering it again.

    docker compose run --rm -T noesis python scripts/client_libraries.py thefloor https://thefloor.rvanegas.co
    docker compose run --rm -T noesis python scripts/client_libraries.py thefloor --off
"""

from __future__ import annotations

import argparse

from noesis import accounts, service
from noesis.oauth import provider


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("client_id")
    parser.add_argument("url", nargs="?", help="where the application answers, https://…")
    parser.add_argument("--off", action="store_true", help="unmark it")
    args = parser.parse_args(argv)
    data = provider._load()
    raw = data["clients"].get(args.client_id)
    if raw is None:
        raise SystemExit(f"✗ no registered client {args.client_id!r}")
    if not raw.get("client_secret"):
        raise SystemExit(f"✗ {args.client_id!r} has no secret")
    if args.off:
        raw.pop("keeps_libraries", None)
    else:
        if not args.url or not args.url.startswith("https://"):
            raise SystemExit("✗ the URL it answers at, https://…")
        if not service.NAME_RE.match(args.client_id):
            raise SystemExit(f"✗ {args.client_id!r} is not a library owner's name")
        # Taken by anybody is refused, unless by this mark itself: marking again
        # only changes the URL.
        if not raw.get("keeps_libraries"):
            with accounts.connect() as db:
                if accounts._taken(db, args.client_id):
                    raise SystemExit(f"✗ {args.client_id!r} is somebody's name")
        (service.data_dir() / "libraries" / args.client_id).mkdir(parents=True, exist_ok=True)
        raw["keeps_libraries"] = args.url.rstrip("/")
    provider._save(data)
    print(f"{args.client_id}: {'keeps no libraries' if args.off else 'keeps libraries, asking ' + raw['keeps_libraries']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
