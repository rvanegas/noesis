"""The register of people's names across applications: one user name per address.

noesis is the identity for people (rvanegas-site's PROJECTS.md, Shared rules),
and since 2026-11-02 the source of truth for their names as well: an
application with accounts of its own (The Floor) asks here for the name of
each person it signs up, and has a rename made here before it makes it
itself. So a person is the same name at both ends, and an address is one name
throughout. The Floor keeps the case its people type; the pair is the same
name compared without case.

- **A pair is an account's or a reservation's.** Somebody The Floor signed up
  who has never signed in here has a reservation: the address and the name are
  both taken, and nothing else exists — no account, no library, no /me. Their
  first sign-in makes the account under the reserved name
  (accounts.create_account).
- **A name chosen from now on** is accounts.USER_NAME_RE: lowercase letters,
  digits and _, four to thirty. Older names (with -, or shorter) stand until
  renamed.
- **A rename works from either end** and reaches every other: for an account
  it is the account, its spend and speaker names, its grants and its
  libraries' directory, so every library id `<user>/<library>`; it is refused
  while a run holds one of those libraries. Each application the operator
  marked as keeping names (scripts/client_names.py) is told, but the one that
  asked, by a signed call to its hook — retried until it answers, since an
  application whose person never connected has no grant to notice with.
- **An address moves** only while it is a reservation's: a noesis account's
  address is how its owner signs in here, and is not an application's to move.

The hook's call is a POST of `{"email", "old", "new"}`, signed with the
client's own secret: `X-Noesis-Signature: sha256=<hex HMAC-SHA256 of the body>`.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
import urllib.error
import urllib.request

from noesis import accounts, service

# How long a hook that did not answer waits before it is asked again, at most.
RETRY_CAP = 60 * 60
HOOK_TIMEOUT = 10


class Taken(ValueError):
    """The name, or the address, is somebody else's."""


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
    """Makes `user` the address's name: reserved if it has none, renamed if it has another."""
    address, name = _address(email), _check(user)
    current = pair_for(address)
    if current is None:
        with accounts.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                if accounts._taken(db, name):
                    raise Taken("That user name is taken.")
                db.execute("INSERT INTO reservations (user, email, client, created_at) VALUES (?, ?, ?, ?)",
                           (name, address, client, time.time()))
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise
        return name
    return rename(current[0], name, by=client)


def rename(old: str, new: str, *, by: str | None = None) -> str:
    """Renames a pair everywhere noesis keeps the name, and owes every other application the news."""
    from noesis.oauth import provider
    new = _check(new)
    if new == old:
        return new
    if old in service.token_users():
        raise Invalid(f"{old} holds a users.toml token: the operator's, renamed by hand")
    base = service.data_dir() / "libraries"
    if any(lock.locked() and (path == base / old or base / old in path.parents)
           for path, lock in service.locks.items()):
        raise Busy("Something is running in one of your libraries; try again when it has finished.")
    hooks = [c for c in provider.name_keepers() if c != by]
    with accounts.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            if accounts._taken(db, new):
                raise Taken("That user name is taken.")
            row = (db.execute("SELECT email FROM accounts WHERE user = ?", (old,)).fetchone()
                   or db.execute("SELECT email FROM reservations WHERE user = ?", (old,)).fetchone())
            if row is None:
                raise Invalid(f"{old} is nobody's name")
            for table in ("accounts", "reservations", "spend", "names"):
                db.execute(f"UPDATE {table} SET user = ? WHERE user = ?", (new, old))
            body = json.dumps({"email": row[0], "old": old, "new": new})
            db.executemany("INSERT INTO name_changes (client, body, next_at) VALUES (?, ?, ?)",
                           [(client, body, time.time()) for client in hooks])
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
    provider.rename_grants(old, new)
    if (base / old).exists():
        (base / old).rename(base / new)
    if hooks:
        _soon()
    return new


def _soon() -> None:
    """Delivers what a rename now owes, off the request; the server's loop retries what fails."""
    threading.Thread(target=deliver, daemon=True).start()


def move(email: str, new_email: str) -> None:
    """Moves a reservation to another address; an account's address is not an application's to move."""
    address, target = _address(email), _address(new_email)
    if address == target:
        return
    with accounts.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            if db.execute("SELECT 1 FROM accounts WHERE email = ?", (address,)).fetchone():
                raise Taken("Your address is also how you sign in to noesis, where your username is kept, "
                            "so it cannot be changed from another application.")
            if (db.execute("SELECT 1 FROM accounts WHERE email = ?", (target,)).fetchone()
                    or db.execute("SELECT 1 FROM reservations WHERE email = ?", (target,)).fetchone()):
                raise Taken("That address already has a username at noesis, somebody else's.")
            db.execute("UPDATE reservations SET email = ? WHERE email = ?", (target, address))
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise


def signature(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


_delivering = threading.Lock()


def deliver(now: float | None = None, post=None) -> int:
    """Sends every rename now due to its application's hook; how many were answered."""
    from noesis.oauth import provider
    post = post or _post
    if not _delivering.acquire(blocking=False):
        return 0
    try:
        now = time.time() if now is None else now
        with accounts.connect() as db:
            due = db.execute("SELECT id, client, body, attempts FROM name_changes WHERE next_at <= ? ORDER BY id",
                             (now,)).fetchall()
        answered = 0
        for change_id, client, body, attempts in due:
            hook, secret = provider.name_hook(client)
            ok = hook is not None and post(hook, body.encode(), signature(secret, body.encode()))
            with accounts.connect() as db:
                if ok or hook is None:
                    db.execute("DELETE FROM name_changes WHERE id = ?", (change_id,))
                else:
                    db.execute("UPDATE name_changes SET attempts = ?, next_at = ? WHERE id = ?",
                               (attempts + 1, now + min(RETRY_CAP, 60 * 2 ** attempts), change_id))
            answered += bool(ok)
        return answered
    finally:
        _delivering.release()


def owed() -> list[tuple[str, dict, int]]:
    """The renames not yet answered: the application, the change, and how often it was tried."""
    with accounts.connect() as db:
        return [(client, json.loads(body), attempts)
                for client, body, attempts in db.execute("SELECT client, body, attempts FROM name_changes ORDER BY id")]


def _post(url: str, body: bytes, signed: str) -> bool:
    request = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json", "X-Noesis-Signature": signed})
    try:
        with urllib.request.urlopen(request, timeout=HOOK_TIMEOUT) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, OSError):
        return False
