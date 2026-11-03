#!/usr/bin/env python3
"""Reconcile an application's existing names with the register, once, before it enforces it.

An operator task (names.py), run when an application with accounts of its own
starts asking noesis for names: The Floor had given out usernames for months
before the register existed, so noesis has to learn them, and where the two
disagree noesis — the source of truth — wins and the application is told.

The pairs are read from a file or stdin, one `email<TAB>username` per line,
as The Floor's `bin/export-names` prints them; the username may be empty. Each
line is one of:

- `same`      the address already has this name here
- `reserve`   the address has no name here and this one is free: reserved
- `takes X`   the application's account takes X, noesis's: the address already
              has X here, or the name is somebody else's here, or not a name
              noesis gives (then X is reserved, from it or from the address)

Without --apply it prints the plan and changes nothing. With --apply it
reserves, and owes the application a rename for each `takes` (old name → X),
which is sent at once and retried by the server until answered — the same
rename it is told of any other way. Run it again until every line is `same`.

    ssh commons 'cd ~/noesis && docker compose run --rm -T noesis python scripts/reserve_names.py' < floor-names.tsv
    ssh commons 'cd ~/noesis && docker compose run --rm -T noesis python scripts/reserve_names.py --apply' < floor-names.tsv
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from noesis import accounts, names
from noesis.oauth import provider


def plan(lines: list[str]) -> list[tuple[str, str, str, str | None]]:
    """(email, the application's name, verdict, noesis's name where it decides one)."""
    rows, seen = [], set()
    for number, line in enumerate(lines, 1):
        line = line.split("\t#", 1)[0].rstrip("\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        email, _, given = (part.strip() for part in line.partition("\t"))
        address = accounts.normalize_email(email)
        if address is None:
            rows.append((email, given, f"line {number}: not an address", None))
            continue
        if address in seen:
            rows.append((address, given, "address named twice", None))
            continue
        seen.add(address)
        folded = given.lstrip("@").lower()
        pair = names.pair_for(address)
        if pair is not None:
            rows.append((address, given, "same" if pair[0] == folded else "takes", pair[0]))
        elif accounts.USER_NAME_RE.match(folded) and not _taken(folded):
            rows.append((address, given, "reserve", folded))
        else:
            rows.append((address, given, "takes", None))
    return rows


def _taken(user: str) -> bool:
    with accounts.connect() as db:
        return accounts._taken(db, user)


def apply(rows, client: str) -> None:
    owed = []
    for i, (address, given, verdict, user) in enumerate(rows):
        if verdict == "reserve":
            try:
                names.choose(address, user, client)
                continue
            except names.Taken:  # taken by a line before it
                verdict = "takes"
        if verdict == "takes":
            user = user or names.name_for(address, client, [given.lstrip("@")])[0]
            owed.append(json.dumps({"email": address, "old": given.lstrip("@"), "new": user}))
        rows[i] = (address, given, verdict, user)
    with accounts.connect() as db:
        db.executemany("INSERT INTO name_changes (client, body, next_at) VALUES (?, ?, ?)",
                       [(client, body, time.time()) for body in owed])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pairs", nargs="?", help="email<TAB>username lines; stdin without it")
    parser.add_argument("--client", default="thefloor", help="the application, marked by client_names.py")
    parser.add_argument("--apply", action="store_true", help="reserve, and owe the renames")
    args = parser.parse_args(argv)
    if args.client not in provider.name_keepers():
        raise SystemExit(f"✗ {args.client!r} keeps no names: scripts/client_names.py first")
    text = open(args.pairs, encoding="utf-8").read() if args.pairs else sys.stdin.read()
    rows = plan(text.splitlines())
    if args.apply:
        apply(rows, args.client)
    for address, given, verdict, user in rows:
        shown = f"takes {user or '(a name from it)'}" if verdict == "takes" else verdict
        print(f"{shown:<32}  {given or '-':<24}  {address}")
    counts = {v: sum(1 for row in rows if row[2] == v) for v in ("same", "reserve", "takes")}
    print(f"\nsame: {counts['same']}, {'reserved' if args.apply else 'to reserve'}: {counts['reserve']}, "
          f"{'renamed there' if args.apply else 'to rename there'}: {counts['takes']}, "
          f"refused: {len(rows) - sum(counts.values())}")
    if args.apply and counts["takes"]:
        print(f"answered by {args.client} now: {names.deliver()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
