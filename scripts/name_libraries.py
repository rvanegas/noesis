#!/usr/bin/env python3
"""Give each person's library the name it is shown by.

Since 2026-11-11 a library is made from a name, "Philosophy", its id's second
half being that name's slug, and the name is kept in `.noesis/library.json`
(service.name_library). A library made before then was made from its slug, so
this names it from the slug: `philosophy` "Philosophy", `my-notes` "My notes".
An application's libraries are left alone, being named by its groups.

    python3 scripts/name_libraries.py                 # what it would do
    python3 scripts/name_libraries.py --apply
    docker compose exec -T noesis python scripts/name_libraries.py --apply

Idempotent: a library that has its name keeps it.

Run on the server 2026-11-11, before the deploy that reads the names, with
these names but for rochelle/executive_assistance, named "Executive Assistance".
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from noesis import members  # noqa: E402
from noesis.service import data_dir, library_name, name_library  # noqa: E402


def name_from(slug: str) -> str:
    words = re.sub(r"[-_]+", " ", slug).strip()
    return words[:1].upper() + words[1:]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--apply", action="store_true", help="write the names, not only say them")
    args = parser.parse_args(argv)
    base = data_dir() / "libraries"
    for owner in sorted(p for p in base.iterdir() if p.is_dir()) if base.is_dir() else []:
        if members.keeper(owner.name) is not None:
            continue
        for root in sorted(p for p in owner.iterdir() if p.is_dir()):
            if library_name(root) is not None:
                continue
            name = name_from(root.name)
            print(f"{owner.name}/{root.name}: {name}")
            if args.apply:
                name_library(root, name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
