#!/usr/bin/env python3
"""Move each library's record of what it sent to Roxana into the argument files.

Until 2026-11-09 export kept it beside the library, in `.noesis/exports.json`,
by the argument file's path, where nobody saw it and where an argument
extracted again inherited the record of the one it replaced. Since then it is
a line in the argument file under its date (argue.Sent):

    Sent to Roxana: d4r4, 2026-11-09, digest 4214a2e2465d2e6a; earlier: 5e48

This writes that line into each argument file exports.json names, unless the
file already has one, and then deletes exports.json. An entry whose file is
gone is dropped, since what it recorded went with the file.

    python3 scripts/migrate_exports.py <library>...             # what it would do
    python3 scripts/migrate_exports.py --all --apply             # every library on the server
    docker compose exec -T noesis python scripts/migrate_exports.py --all --apply

Idempotent: run again, it finds no exports.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from noesis.argue import Sent, sent_of, with_sent  # noqa: E402


def migrate(library: Path, apply: bool) -> None:
    exports = library / ".noesis" / "exports.json"
    if not exports.exists():
        return
    for rel, record in json.loads(exports.read_text(encoding="utf-8")).items():
        argument = library / rel
        if not argument.exists():
            print(f"{library}: {rel} is gone; its record ({record['discussion_id']}) is dropped")
            continue
        text = argument.read_text(encoding="utf-8")
        if sent_of(text):
            print(f"{library}: {rel} already says where it was sent")
            continue
        sent = Sent(record["discussion_id"], record["exported_at"], record["digest"], tuple(record.get("earlier", ())))
        print(f"{library}: {rel}: {sent.line()}")
        if apply:
            argument.write_text(with_sent(text, sent), encoding="utf-8")
    if apply:
        exports.unlink()
        print(f"{library}: exports.json deleted")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("libraries", nargs="*", type=Path)
    parser.add_argument("--all", action="store_true", help="every library under $NOESIS_DATA_DIR/libraries")
    parser.add_argument("--apply", action="store_true", help="write, rather than say what would be written")
    args = parser.parse_args(argv)
    libraries = list(args.libraries)
    if args.all:
        from noesis.service import data_dir
        libraries += sorted(p for p in (data_dir() / "libraries").glob("*/*") if p.is_dir())
    for library in libraries:
        migrate(library, args.apply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
