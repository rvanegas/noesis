#!/usr/bin/env python3
"""Every user's libraries, with how many documents each holds; a library's trash, and restoring from it.

An operator task (SERVER.md), run in the container — from the Mac,
ts libraries:

    docker compose run --rm -T noesis python scripts/libraries.py
    docker compose run --rm -T noesis python scripts/libraries.py --trash ann/philosophy
    docker compose run --rm -T noesis python scripts/libraries.py --trash ann/philosophy --restore 2026-11-09/2026/x.chat.md

A line per library, `libraries/<user>/<library>` under $NOESIS_DATA_DIR: the
documents in its index (what lookups and searches reach, so what was last
indexed), and its files (everything kept, sources and records but not
noesis's state or REVISIONS). A user's account address follows their name where
they signed up by email (accounts.py).

A file deleted through the API is kept thirty days in the library's trash
(deletion.py): `--trash` lists it, each entry `<day>/<path>`, and
`--restore` puts one back where it was.
"""

from __future__ import annotations

import argparse

from noesis import accounts, deletion, service
from noesis.cli import _library_files
from noesis.library import load_entries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--trash", metavar="LIBRARY", help="a library's trash, by its id, <user>/<library>")
    parser.add_argument("--restore", metavar="ENTRY", help="with --trash: put this entry back")
    args = parser.parse_args(argv)
    if args.trash:
        if args.restore:
            try:
                restored = deletion.restore_file(args.trash, args.restore)
            except ValueError as exc:
                raise SystemExit(f"✗ {exc}") from None
            print(f"✓ restored {restored.relative_to(deletion.libraries_dir() / args.trash)}")
            return 0
        entries = deletion.trashed(args.trash)
        print("\n".join(entries) if entries else "nothing in the trash")
        return 0
    base = service.data_dir() / "libraries"
    users = sorted(p for p in base.iterdir() if p.is_dir()) if base.is_dir() else []
    if not users:
        print("no libraries")
        return 0
    held = {user: [p for p in sorted(user.iterdir()) if p.is_dir() and service.NAME_RE.match(p.name)]
            for user in users}
    width = max((len(p.name) for libraries in held.values() for p in libraries), default=0)
    for user, libraries in held.items():
        print(f"{user.name}  {accounts.plan_of(user.name)}")
        if not libraries:
            print("  (no library)")
        for library in libraries:
            indexed = len(load_entries(library))
            files = len(_library_files(library))
            print(f"  {library.name:<{width}} {indexed:>6} indexed  {files:>6} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
