#!/usr/bin/env python3
"""Rename an account's user name, everywhere noesis keeps it.

An operator task, for a person who must be known by another name. Since
2026-11-02 a person renames themselves (PUT /me/user, or at The Floor through
the register), and this is the same rename (names.rename) for the operator:
with a plan first, and for an account or a reservation alike.

The name lives in the account, its spend and speaker names (accounts.db), its
OAuth grants (oauth.json: they keep working, now for the new name), and its
libraries' directory, /data/libraries/<user>/, and so in every library id,
`<user>/<library>`. Every application that keeps names (scripts/client_names.py)
is told, and rewrites the library ids it saved.

Without --apply it prints the plan and changes nothing. A run in progress in
one of the person's libraries refuses it.

    docker compose run --rm -T noesis python scripts/rename_user.py freeyourtime rochelle
    docker compose run --rm -T noesis python scripts/rename_user.py freeyourtime rochelle --apply
"""

from __future__ import annotations

import argparse

from noesis import accounts, names, service
from noesis.oauth import provider


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("old")
    parser.add_argument("new")
    parser.add_argument("--apply", action="store_true", help="rename; without it, the plan")
    args = parser.parse_args(argv)
    old, new = args.old, args.new
    found = accounts.account(old)
    held = accounts.reservation(old)
    if found is None and held is None:
        raise SystemExit(f"✗ {old} is not an account or a reservation")
    if old in service.token_users():
        raise SystemExit(f"✗ {old} holds a users.toml token: the operator's, renamed by hand")
    if not accounts.USER_NAME_RE.match(new):
        raise SystemExit(f"✗ not a user name: {new!r}")
    with accounts.connect() as db:
        if accounts._taken(db, new):
            raise SystemExit(f"✗ {new} is taken")

    ids = service.library_ids(old)
    data = provider._load()
    grants = [entry for kind in ("access", "refresh") for entry in data[kind].values() if entry["user"] == old]
    clients = sorted({entry["client_id"] for entry in grants})
    if found is not None:
        print(f"{old} -> {new}  ({found.email}, {found.plan})")
    else:
        print(f"{old} -> {new}  ({held}, reserved)")
    print(f"libraries: {', '.join(ids) or 'none'}")
    print(f"grants: {len(grants)} token(s), of {', '.join(clients) or 'no client'}")
    print(f"told: {', '.join(provider.name_keepers()) or 'no application'}")

    if not args.apply:
        print("\nA plan — pass --apply to rename.")
        return 0
    try:
        names.rename(old, new)
    except (names.Taken, names.Busy, names.Invalid) as exc:
        raise SystemExit(f"✗ {exc}") from None
    print("Renamed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
