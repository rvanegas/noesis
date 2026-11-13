#!/usr/bin/env python3
"""Rename the names people kept as their voice to their display name, in their own chats.

A one-time migration (2026-11-13). Until then noesis kept, per person, the
chat headings besides Prompt that were their voice (accounts.db's `names`,
set by the web client's *Your names*, by The Floor and by a copy). Since
then a person's voice is Prompt and their display name at auth alone
(members.voices), so a heading they kept that is not their display name
would read as somebody else's. This renames each such heading, in the chats
of each person's own libraries, to their display name, and then drops the
table. A person whose display name auth does not give is left as they are
and named; the table stays until every person is done, so the script can be
run again. A chat renamed by hand since is put right the same way, with the
web client's *Speakers*.

Without --apply it prints the plan and changes nothing.

    docker compose run --rm -T noesis python scripts/migrate_names.py
    docker compose run --rm -T noesis python scripts/migrate_names.py --apply
"""

from __future__ import annotations

import argparse
import json
import sqlite3

from noesis import members, service
from noesis.library import role_of
from noesis.transcript import HEADING_RE, rename_speakers


def kept() -> dict[str, tuple[str, ...]]:
    """Each person's kept names, read from the table the code no longer has."""
    path = service.data_dir() / "accounts.db"
    if not path.exists():
        return {}
    with sqlite3.connect(path) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'names'").fetchone():
            return {}
        return {user: tuple(json.loads(names)) for user, names in db.execute("SELECT user, names FROM names")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="rename and drop the table; without it, the plan")
    args = parser.parse_args(argv)
    base = service.data_dir() / "libraries"
    if not (rows := kept()):
        print("No names are kept: nothing to do.")
        return 0
    left = []
    for user, names in sorted(rows.items()):
        shown = members.display_name(user)
        if shown == user:
            left.append(user)
            print(f"{user}: auth gives no display name; left as is (kept: {', '.join(names)})")
            continue
        renamed = {name: shown for name in names if name != shown}
        print(f"{user}: {', '.join(renamed) or 'nothing'} -> {shown}")
        for chat in sorted((base / user).rglob("*.chat.md")) if renamed else ():
            rel = chat.relative_to(base)
            if role_of(chat.name) != "chat" or any(p.startswith(".") for p in rel.parts):
                continue
            text = chat.read_text(errors="replace")
            if not {m.group(2) for m in HEADING_RE.finditer(text)} & renamed.keys():
                continue
            print(f"  {rel}")
            if args.apply:
                chat.write_text(rename_speakers(text, renamed))
    if not args.apply:
        print("\nA plan — pass --apply to rename.")
        return 0
    if left:
        print(f"\nThe table stays, for {', '.join(left)}: run again once auth names them.")
        return 0
    with sqlite3.connect(service.data_dir() / "accounts.db") as db:
        db.execute("DROP TABLE IF EXISTS names")
    print("Renamed, and the table dropped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
