#!/usr/bin/env python3
"""Link many addresses to user names at once: Roxana's people, before they first sign in.

An operator task. Roxana signs people in through noesis (oauth.py, an
identity-only client) and knows them by their noesis user name, which must
be the name its discussions already record: their Cognito username. So each
address gets its account, under that name, before its first sign-in would make
one named after the address.

The mapping is read from a file or stdin, one `email<TAB>user` per line; blank
lines and `#` comments, whole lines or after a tab, are skipped. Without --apply it prints the plan, every
line marked, and then the accounts noesis already holds, so the two can be
matched by hand; nothing changes. With --apply it links the lines marked
`link` and leaves the rest. A free plan, unless the user is the operator's (a
users.toml token, no account yet), who stays unlimited.

    ssh commons 'cd ~/noesis && docker compose run --rm -T noesis python scripts/link_accounts.py' < roxana-users.tsv
    ssh commons 'cd ~/noesis && docker compose run --rm -T noesis python scripts/link_accounts.py --apply' < roxana-users.tsv
"""

from __future__ import annotations

import argparse
import sys

from noesis import accounts, service


def plan(lines: list[str]) -> list[tuple[str, str, str]]:
    """(email, user, what happens): `link`, `done`, or why not."""
    rows, emails, users = [], set(), set()
    for number, line in enumerate(lines, 1):
        line = line.split("\t#", 1)[0].strip()
        if not line or line.startswith("#"):
            continue
        email, _, user = (part.strip() for part in line.partition("\t"))
        address = accounts.normalize_email(email)
        if address is None or not user:
            rows.append((email, user, f"line {number}: not `email<TAB>user`"))
            continue
        rows.append((address, user, _verdict(address, user, emails, users)))
        emails.add(address)
        users.add(user)
    return rows


def _verdict(email: str, user: str, emails: set[str], users: set[str]) -> str:
    if not service.NAME_RE.match(user):
        return "not a noesis user name (lowercase letters, digits, - and _)"
    if email in emails:
        return "address named twice"
    if user in users:
        return "user named twice"
    by_email, by_user = accounts.account_for_email(email), accounts.account(user)
    if by_email is not None and by_email.user == user:
        return "done"
    if by_email is not None:
        return f"the address is already {by_email.user}'s"
    if by_user is not None:
        return f"{user} is already an account, of {by_user.email}"
    if (service.data_dir() / "libraries" / user).exists() and user not in service.token_users():
        return f"{user} already has libraries"
    return "link"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mapping", nargs="?", help="email<TAB>user lines; stdin without it")
    parser.add_argument("--apply", action="store_true", help="link the lines marked link")
    args = parser.parse_args(argv)
    text = open(args.mapping, encoding="utf-8").read() if args.mapping else sys.stdin.read()
    rows = plan(text.splitlines())
    operators = service.token_users()
    for email, user, verdict in rows:
        print(f"{verdict:<10}  {user:<24}  {email}")
        if verdict == "link" and args.apply:
            accounts.link(email, user, accounts.UNLIMITED if user in operators else accounts.FREE)
    counts = {v: sum(1 for *_, w in rows if w == v) for v in ("link", "done")}
    refused = len(rows) - counts["link"] - counts["done"]
    print(f"\n{'linked' if args.apply else 'to link'}: {counts['link']}, done already: {counts['done']}, "
          f"refused: {refused}")
    if not args.apply:
        print("\nnoesis's accounts now:")
        for found in accounts.accounts():
            print(f"  {found.user:<24}  {found.email}  {found.plan}{'  disabled' if found.disabled else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
