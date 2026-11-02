#!/usr/bin/env python3
"""Rename an account's user name, everywhere noesis keeps it.

An operator task, for a person who must be known by another name: Roxana
knows people by their noesis user name, and one who signed up here first
(by The Floor) may already be known there by another.

The name lives in the account, its spend and speaker names (accounts.db), its
OAuth grants (oauth.json: they keep working, now for the new name), and its
libraries' directory, /data/libraries/<user>/, and so in every library id,
`<user>/<library>`. An application that saved a library id (The Floor's
channel selections) holds the old one afterwards: the plan lists them, to
choose again there.

Without --apply it prints the plan and changes nothing. Run it when nothing
runs in the person's libraries: a run in progress holds the old path.

    docker compose run --rm -T noesis python scripts/rename_user.py freeyourtime rochelle
    docker compose run --rm -T noesis python scripts/rename_user.py freeyourtime rochelle --apply
"""

from __future__ import annotations

import argparse

from noesis import accounts, service
from noesis.oauth import provider


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("old")
    parser.add_argument("new")
    parser.add_argument("--apply", action="store_true", help="rename; without it, the plan")
    args = parser.parse_args(argv)
    old, new = args.old, args.new
    found = accounts.account(old)
    if found is None:
        raise SystemExit(f"✗ {old} is not an account")
    if old in service.token_users():
        raise SystemExit(f"✗ {old} holds a users.toml token: the operator's, renamed by hand")
    if not service.NAME_RE.match(new):
        raise SystemExit(f"✗ not a user name: {new!r}")
    with accounts.connect() as db:
        if accounts._taken(db, new):
            raise SystemExit(f"✗ {new} is taken")

    libraries = service.data_dir() / "libraries"
    ids = service.library_ids(old)
    data = provider._load()
    grants = [entry for kind in ("access", "refresh") for entry in data[kind].values() if entry["user"] == old]
    clients = sorted({entry["client_id"] for entry in grants})
    print(f"{old} -> {new}  ({found.email}, {found.plan})")
    print(f"libraries: {', '.join(ids) or 'none'}")
    print(f"grants: {len(grants)} token(s), of {', '.join(clients) or 'no client'}")
    if ids and clients:
        print(f"  an application that saved a library id holds {old}/…: choose again there")

    if not args.apply:
        print("\nA plan — pass --apply to rename.")
        return 0
    with accounts.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            for table in ("accounts", "spend", "names"):
                db.execute(f"UPDATE {table} SET user = ? WHERE user = ?", (new, old))
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
    data = provider._load()
    for kind in ("access", "refresh"):
        for entry in data[kind].values():
            if entry["user"] == old:
                entry["user"] = new
    provider._save(data)
    if (libraries / old).exists():
        (libraries / old).rename(libraries / new)
    print("Renamed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
