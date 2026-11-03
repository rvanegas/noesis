"""The register of people's names across applications: one user name per address.

noesis is the identity for people (rvanegas-site's PROJECTS.md, Shared rules),
and since 2026-11-02 the source of truth for their names as well: an
application with accounts of its own (The Floor) asks here for the name of
each person it signs up. So a person is the same name at both ends, and an
address is one name throughout. The Floor keeps the case its people type; the
pair is the same name compared without case.

- **A pair is an account's or a reservation's.** Somebody The Floor signed up
  who has never signed in here has a reservation: the address and the name are
  both taken, and nothing else exists — no account, no library, no /me. Their
  first sign-in makes the account under the reserved name
  (accounts.create_account).
- **A name chosen from now on** is accounts.USER_NAME_RE: lowercase letters,
  digits and _, four to thirty. Older names (with -, or shorter) stand.
- **Only a reservation changes.** An application may rename one, or move it to
  another address, while its person has no account here. **A noesis account's
  name and address are fixed**: renaming one would have to reach every
  application that saved its library ids and every one that knows the person
  by name, and nothing here can make that reliable. Until sign-in itself moves
  out of both applications, being unable to change them is the simple rule.
  The operator's scripts/rename_user.py is the exception, done by hand.
"""

from __future__ import annotations

import time

from noesis import accounts, service

FIXED = ("Your username and address are also your noesis account's, "
         "and cannot be changed once that account exists.")


class Taken(ValueError):
    """The name or the address is somebody else's, or is fixed."""


class Invalid(ValueError):
    """Not a user name noesis gives out, or not an address."""


class Busy(RuntimeError):
    """A run holds one of the libraries a rename would move."""


def _address(email: str) -> str:
    address = accounts.normalize_email(email)
    if address is None:
        raise Invalid("That is not an email address.")
    return address


def _check(user: str) -> str:
    name = user.strip().lstrip("@").lower()
    if not accounts.USER_NAME_RE.match(name):
        raise Invalid(f"A user name is {accounts.MIN_USER_NAME} to {accounts.MAX_USER_NAME} "
                      "lowercase letters, digits and underscores.")
    return name


def pair_for(email: str) -> tuple[str, bool] | None:
    """The name an address has here, and whether it is an account's rather than a reservation's."""
    address = _address(email)
    found = accounts.account_for_email(address)
    if found is not None:
        return found.user, True
    held = accounts.reservation_for_email(address)
    return (held[0], False) if held else None


def name_for(email: str, client: str, suggestions: list[str] | tuple[str, ...] = ()) -> tuple[str, bool]:
    """An address's name, reserving one for it if it has none: the suggestions' first free, else the address's."""
    address = _address(email)
    with accounts.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            row = db.execute("SELECT user FROM accounts WHERE email = ?", (address,)).fetchone()
            if row:
                db.execute("COMMIT")
                return row[0], True
            row = db.execute("SELECT user FROM reservations WHERE email = ?", (address,)).fetchone()
            if row:
                db.execute("COMMIT")
                return row[0], False
            stems = [s for s in (*map(accounts.user_stem, suggestions), accounts.user_stem(address)) if s]
            user = accounts.free_name(db, stems)
            db.execute("INSERT INTO reservations (user, email, client, created_at) VALUES (?, ?, ?, ?)",
                       (user, address, client, time.time()))
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
    return user, False


def choose(email: str, user: str, client: str) -> str:
    """Makes `user` the address's name: reserved if it has none, its reservation renamed if it has another."""
    address, name = _address(email), _check(user)
    with accounts.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            if db.execute("SELECT 1 FROM accounts WHERE email = ?", (address,)).fetchone():
                raise Taken(FIXED)
            held = db.execute("SELECT user FROM reservations WHERE email = ?", (address,)).fetchone()
            if held and held[0] == name:
                db.execute("COMMIT")
                return name
            if accounts._taken(db, name):
                raise Taken("That user name is taken.")
            if held:
                db.execute("UPDATE reservations SET user = ? WHERE email = ?", (name, address))
            else:
                db.execute("INSERT INTO reservations (user, email, client, created_at) VALUES (?, ?, ?, ?)",
                           (name, address, client, time.time()))
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
    return name


def move(email: str, new_email: str) -> None:
    """Moves a reservation to another address; an account's address is fixed."""
    address, target = _address(email), _address(new_email)
    if address == target:
        return
    with accounts.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            if db.execute("SELECT 1 FROM accounts WHERE email = ?", (address,)).fetchone():
                raise Taken(FIXED)
            if (db.execute("SELECT 1 FROM accounts WHERE email = ?", (target,)).fetchone()
                    or db.execute("SELECT 1 FROM reservations WHERE email = ?", (target,)).fetchone()):
                raise Taken("That address already has a username at noesis, somebody else's.")
            db.execute("UPDATE reservations SET email = ? WHERE email = ?", (target, address))
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise


def rename_account(old: str, new: str) -> str:
    """The operator's rename of an account (scripts/rename_user.py): the account, grants and libraries.

    Nothing tells the applications: The Floor's username and the library ids it
    saved are renamed there by hand, as the script's plan says.
    """
    from noesis.oauth import provider
    new = _check(new)
    if old in service.token_users():
        raise Invalid(f"{old} holds a users.toml token: the operator's, renamed by hand")
    base = service.data_dir() / "libraries"
    if any(lock.locked() and (path == base / old or base / old in path.parents)
           for path, lock in service.locks.items()):
        raise Busy("Something is running in one of the libraries; try again when it has finished.")
    with accounts.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            if accounts._taken(db, new):
                raise Taken("That user name is taken.")
            if not db.execute("SELECT 1 FROM accounts WHERE user = ?", (old,)).fetchone():
                raise Invalid(f"{old} is not an account")
            for table in ("accounts", "spend", "names"):
                db.execute(f"UPDATE {table} SET user = ? WHERE user = ?", (new, old))
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
    provider.rename_grants(old, new)
    if (base / old).exists():
        (base / old).rename(base / new)
    return new
