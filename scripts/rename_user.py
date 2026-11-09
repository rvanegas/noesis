#!/usr/bin/env python3
"""Rename a user everywhere noesis keeps the name: libraries, plan, spend and speaker names.

An operator task, for a person who must be known by another name. The name
is auth's first: rename the account there (dianoia-auth's scripts/rename_user.py),
then here. The name lives in accounts.db (plan, spend, speaker names) and in
the libraries' directory, /data/libraries/<user>/, and so in every library
id, `<user>/<library>`. **Nothing tells The Floor**: rename the person there
to match (its bin/rename-users), and they choose their channels' libraries
again.

Without --apply it prints the plan and changes nothing. A run in progress in
one of the person's libraries refuses it.

    docker compose run --rm -T noesis python scripts/rename_user.py freeyourtime rochelle
    docker compose run --rm -T noesis python scripts/rename_user.py freeyourtime rochelle --apply
"""

from __future__ import annotations

import argparse

from noesis import accounts, service


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("old")
    parser.add_argument("new")
    parser.add_argument("--apply", action="store_true", help="rename; without it, the plan")
    args = parser.parse_args(argv)
    old, new = args.old, args.new
    if old in service.token_users():
        raise SystemExit(f"✗ {old} holds a users.toml token: the operator's, renamed by hand")
    if not service.NAME_RE.match(new):
        raise SystemExit(f"✗ not a user name: {new!r}")
    base = service.data_dir() / "libraries"
    if (base / new).exists() or accounts.account(new) is not None:
        raise SystemExit(f"✗ {new} is taken")
    print(f"{old} -> {new}  ({accounts.plan_of(old)})")
    print(f"libraries: {', '.join(service.library_ids(old)) or 'none'}")
    if not args.apply:
        print("\nA plan — pass --apply to rename.")
        return 0
    if any(lock.locked() and (path == base / old or base / old in path.parents)
           for path, lock in service.locks.items()):
        raise SystemExit("✗ something is running in one of the libraries; try again when it has finished")
    accounts.rename(old, new)
    if (base / old).exists():
        (base / old).rename(base / new)
    print("Renamed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
