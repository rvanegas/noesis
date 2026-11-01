#!/usr/bin/env python3
"""The accounts people sign up for by email: list them, link, change a plan or allowance, disable.

An operator task (SERVER.md, Phase 6), run in the container:

    docker compose run --rm mdc python scripts/accounts.py list
    docker compose run --rm mdc python scripts/accounts.py link rodrigo@example.com rodvandur --plan unlimited
    docker compose run --rm mdc python scripts/accounts.py plan ann unlimited
    docker compose run --rm mdc python scripts/accounts.py raise ann 5
    docker compose run --rm mdc python scripts/accounts.py disable ann

`link` gives an existing user (one users.toml names, whose libraries are
already on the server) the address they sign in with, so signing in reaches
those libraries rather than making a new account. `raise` adds dollars to a
free account's monthly allowance, kept every month until changed; a negative
amount takes back, never below the default. Disabling ends every OAuth
grant the account has; its libraries stay.
"""

from __future__ import annotations

import argparse
import time

from mdc import accounts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="every account, with this month's spend")
    link = sub.add_parser("link", help="an address for an existing user")
    link.add_argument("email")
    link.add_argument("user")
    link.add_argument("--plan", default=accounts.UNLIMITED, choices=accounts.PLANS)
    plan = sub.add_parser("plan", help="change an account's plan")
    plan.add_argument("user")
    plan.add_argument("plan", choices=accounts.PLANS)
    more = sub.add_parser("raise", help="add dollars to an account's monthly allowance")
    more.add_argument("user")
    more.add_argument("usd", type=float, help="dollars a month; negative takes back")
    for name in ("disable", "enable"):
        sub.add_parser(name).add_argument("user")
    args = parser.parse_args(argv)

    if args.command == "list":
        for found in accounts.accounts():
            created = time.strftime("%Y-%m-%d", time.gmtime(found.created_at))
            state = "  disabled" if found.disabled else ""
            budget = f" of ${accounts.allowance(found.user):.2f}" if found.plan == accounts.FREE else ""
            print(f"{found.user:<24} {found.email:<36} {found.plan:<9} {created}  "
                  f"${accounts.spent(found.user):.2f}{budget}{state}")
        return 0
    try:
        if args.command == "link":
            email = accounts.normalize_email(args.email)
            if email is None:
                raise ValueError(f"not an email address: {args.email!r}")
            accounts.link(email, args.user, args.plan)
        elif args.command == "plan":
            accounts.set_plan(args.user, args.plan)
        elif args.command == "raise":
            mine = accounts.raise_allowance(args.user, args.usd)
            print(f"✓ {args.user}: ${mine:.2f} a month")
            return 0
        else:
            accounts.set_disabled(args.user, args.command == "disable")
    except (ValueError, accounts.sqlite3.IntegrityError) as exc:
        raise SystemExit(f"✗ {exc}") from None
    print(f"✓ {args.command} {args.user}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
