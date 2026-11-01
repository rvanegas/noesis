#!/usr/bin/env python3
"""Every user's libraries, with how many documents each holds.

An operator task (SERVER.md), run in the container — from the Mac,
bin/libraries:

    docker compose run --rm -T mdc python scripts/libraries.py

A line per library, `libraries/<user>/<library>` under $MDC_DATA_DIR: the
documents in its index (what lookups and searches reach, so what was last
indexed), and its files (everything kept, sources and records but not
mdc's state or REVISIONS). A user's account address follows their name where
they signed up by email (accounts.py).
"""

from __future__ import annotations

import argparse

from mdc import accounts, service
from mdc.cli import _library_files
from mdc.library import load_entries


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args(argv)
    base = service.data_dir() / "libraries"
    users = sorted(p for p in base.iterdir() if p.is_dir()) if base.is_dir() else []
    if not users:
        print("no libraries")
        return 0
    for user in users:
        found = accounts.account(user.name)
        print(f"{user.name}  {found.email}" if found else user.name)
        libraries = [p for p in sorted(user.iterdir()) if p.is_dir() and service.NAME_RE.match(p.name)]
        if not libraries:
            print("  (no library)")
        for library in libraries:
            indexed = len(load_entries(library))
            files = len(_library_files(library))
            print(f"  {library.name:<24} {indexed:>6} indexed  {files:>6} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
