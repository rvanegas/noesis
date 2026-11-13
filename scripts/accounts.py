#!/usr/bin/env python3
"""What people may spend and store at noesis: list them, change a plan or allowance, restore the deleted.

An operator task (SERVER.md, Phase 6), run in the container. Who a person is,
their address, and disabling them, are auth's (its scripts/accounts.py).

    docker compose run --rm noesis python scripts/accounts.py list
    docker compose run --rm noesis python scripts/accounts.py plan ann unlimited
    docker compose run --rm noesis python scripts/accounts.py raise ann 5
    docker compose run --rm noesis python scripts/accounts.py raised
    docker compose run --rm noesis python scripts/accounts.py deleted
    docker compose run --rm noesis python scripts/accounts.py restore ann

`list` is every user with libraries here or a plan of their own, with this
month's spend. `raise` adds dollars to a free account's monthly allowance,
kept every month until changed; a negative amount takes back, never below
the default; `raised` lists the accounts whose allowance is not the default
(ts cap, from the Mac). `deleted` lists the people who deleted their account at auth, each with the
day their libraries go for good (deletion.py); `restore` brings one back
within that window (their account at auth is auth's operator's to restore).
"""

from __future__ import annotations

import argparse
import time

from noesis import accounts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="every account, with this month's spend")
    plan = sub.add_parser("plan", help="change an account's plan")
    plan.add_argument("user")
    plan.add_argument("plan", choices=accounts.PLANS)
    more = sub.add_parser("raise", help="add dollars to an account's monthly allowance")
    more.add_argument("user")
    more.add_argument("usd", type=float, help="dollars a month; negative takes back")
    sub.add_parser("raised", help="the accounts whose allowance is not the default")
    sub.add_parser("deleted", help="the people deleted, and when each is removed for good")
    sub.add_parser("restore", help="undo a deletion within its window").add_argument("user")
    args = parser.parse_args(argv)

    if args.command == "list":
        from noesis import service
        base = service.data_dir() / "libraries"
        users = {p.name for p in base.iterdir() if p.is_dir()} if base.is_dir() else set()
        rows = {found.user: found for found in accounts.accounts()}
        for user in sorted(users | rows.keys()):
            plan = accounts.plan_of(user)
            created = time.strftime("%Y-%m-%d", time.gmtime(rows[user].created_at)) if user in rows else " " * 10
            budget = f" of ${accounts.allowance(user):.2f}" if plan == accounts.FREE else ""
            print(f"{user:<24} {plan:<9} {created}  ${accounts.spent(user):.2f}{budget}")
        return 0
    if args.command == "raised":
        free = accounts.limits()
        print(f"default ${free.allowance_usd:.2f} a month; free accounts together ${free.monthly_cap_usd:.2f}, "
              f"${accounts.free_spent():.2f} spent in {accounts.month()}")
        raised = [found for found in accounts.accounts() if found.extra_usd]
        if not raised:
            print("no account's allowance is raised")
        for found in raised:
            plan = "" if found.plan == accounts.FREE else f"  ({found.plan}: not limited)"
            print(f"{found.user:<24} +${found.extra_usd:.2f} = "
                  f"${accounts.allowance(found.user):.2f}, ${accounts.spent(found.user):.2f} spent{plan}")
        return 0
    if args.command == "deleted":
        from noesis import deletion
        for user, at in deletion.deleted():
            gone = time.strftime("%Y-%m-%d", time.gmtime(at + deletion.DAYS * deletion.DAY_SECONDS))
            print(f"{user:<24} deleted {time.strftime('%Y-%m-%d', time.gmtime(at))}, removed after {gone}")
        return 0
    if args.command == "restore":
        from noesis import deletion
        try:
            deletion.restore_user(args.user)
        except ValueError as exc:
            raise SystemExit(f"✗ {exc}") from None
        print(f"✓ {args.user} restored")
        return 0
    try:
        if args.command == "plan":
            accounts.set_plan(args.user, args.plan)
        elif args.command == "raise":
            mine = accounts.raise_allowance(args.user, args.usd)
            print(f"✓ {args.user}: ${mine:.2f} a month")
            return 0
    except (ValueError, accounts.sqlite3.IntegrityError) as exc:
        raise SystemExit(f"✗ {exc}") from None
    print(f"✓ {args.command} {args.user}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
