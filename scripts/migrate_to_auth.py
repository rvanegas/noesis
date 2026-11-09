#!/usr/bin/env python3
"""Leave sign-in's data to auth, once, at the cut-over (2026-11-08).

An operator task, run after dianoia-auth's scripts/migrate_from_noesis.py has read
this data directory and before the new noesis serves (its accounts table no
longer has an address):

- **accounts.db**: `accounts` keeps user, plan, created_at and extra_usd;
  addresses and the disabled flag are auth's now. `reservations` and `sends`
  are dropped. Spend and speaker names stay as they are.
- **keepers.json**: the applications marked as keeping libraries, from
  oauth.json's `keeps_libraries`, by client id and URL (members.py).
- **oauth.json** is renamed `oauth.json.bak-2026-11-08`: clients, grants and
  secrets are auth's now. Delete it once auth has run a week.

Without --apply it prints what it would do and changes nothing.

    docker compose run --rm -T noesis python scripts/migrate_to_auth.py
    docker compose run --rm -T noesis python scripts/migrate_to_auth.py --apply
"""

from __future__ import annotations

import argparse
import json
import sqlite3

from noesis import members, service

BACKUP = "oauth.json.bak-2026-11-08"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    data = service.data_dir()
    oauth = data / "oauth.json"
    clients = json.loads(oauth.read_text(encoding="utf-8")).get("clients", {}) if oauth.exists() else {}
    keepers = {cid: raw["keeps_libraries"] for cid, raw in clients.items() if raw.get("keeps_libraries")}
    db = sqlite3.connect(data / "accounts.db", isolation_level=None)
    try:
        columns = [row[1] for row in db.execute("PRAGMA table_info(accounts)")]
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        (count,) = db.execute("SELECT COUNT(*) FROM accounts").fetchone() if "accounts" in tables else (0,)
        print(f"accounts: {count}, columns {', '.join(columns)}")
        print(f"drop: {', '.join(sorted(tables & {'reservations', 'sends'})) or 'nothing'}")
        for cid, url in keepers.items():
            print(f"keeper: {cid} at {url}")
        print(f"oauth.json: {'renamed ' + BACKUP if oauth.exists() else 'none'}")
        if not args.apply:
            print("nothing changed: --apply to do it")
            return 0
        db.execute("BEGIN IMMEDIATE")
        if "email" in columns:
            db.execute("CREATE TABLE accounts_new (user TEXT PRIMARY KEY, plan TEXT NOT NULL DEFAULT 'free', "
                       "created_at REAL NOT NULL, extra_usd REAL NOT NULL DEFAULT 0)")
            db.execute("INSERT INTO accounts_new SELECT user, plan, created_at, extra_usd FROM accounts")
            db.execute("DROP TABLE accounts")
            db.execute("ALTER TABLE accounts_new RENAME TO accounts")
        db.execute("DROP TABLE IF EXISTS reservations")
        db.execute("DROP TABLE IF EXISTS sends")
        db.execute("COMMIT")
    finally:
        db.close()
    for cid, url in keepers.items():
        members.mark(cid, url)
    if oauth.exists():
        oauth.rename(data / BACKUP)
    print("applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
