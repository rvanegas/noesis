"""What noesis's HTTP API and its MCP server share: callers, libraries, locks.

Tokens are minted by scripts/add_token.py; users.toml keeps their SHA-256,
each with the user it belongs to, or "*" for a service (the nightly index).
People who sign up by email are accounts.py's. A user reaches their own
libraries, $NOESIS_DATA_DIR/libraries/<user>/<library>, and those an
application keeps for a group they belong to (members.py); one write at a
time per library, whoever writes.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import re
import tomllib
from pathlib import Path

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

# One run or MCP write at a time per library (SERVER.md, Phases 2 and 5).
locks: dict[Path, asyncio.Lock] = {}


class LibraryError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def data_dir() -> Path:
    return Path(os.environ.get("NOESIS_DATA_DIR", "/data"))


def user_for_token(token: str) -> str | None:
    """The user a bearer token belongs to, "*" for a service, None if unknown."""
    return user_for_token_hash(hashlib.sha256(token.strip().encode()).hexdigest())


def _tokens() -> list[dict]:
    try:
        users = tomllib.loads((data_dir() / "users.toml").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    return users.get("tokens", [])


def user_for_token_hash(digest: str) -> str | None:
    """As user_for_token, given the token's SHA-256."""
    for entry in _tokens():
        if hmac.compare_digest(str(entry.get("sha256", "")), digest):
            return str(entry["user"])
    return None


def token_users() -> set[str]:
    """The users users.toml has tokens for: the operator's, not signed up by email."""
    return {str(entry["user"]) for entry in _tokens()}


def library_root(user: str, library: str, who: str) -> Path:
    """A library's directory, for whoever may reach it: its owner, a service, or
    — for an application's library (members.py) — a member of its group."""
    from noesis import members
    if who not in (user, "*") and members.keeper(user) is None:
        raise LibraryError(403, "not your library")
    if not (NAME_RE.match(user) and NAME_RE.match(library)):
        raise LibraryError(404, "no such library")
    if who not in (user, "*"):
        found = members.group(user, library)
        if found is None or not found.admits(who):
            raise LibraryError(403, "not your library")
    root = data_dir() / "libraries" / user / library
    if not root.is_dir():
        raise LibraryError(404, "no such library")
    return root


def create_library(who: str, name: str) -> str:
    """A new library of the caller's own, its settings empty; its id."""
    if who == "*":
        raise LibraryError(400, "a service has no libraries of its own")
    if not NAME_RE.match(name):
        raise LibraryError(400, "a library's name is lowercase letters, digits, - and _")
    from noesis import accounts
    most = accounts.limits().libraries
    if accounts.is_free(who) and len(library_ids(who)) >= most:
        raise LibraryError(403, f"a free account keeps at most {most} libraries")
    root = data_dir() / "libraries" / who / name
    if root.exists():
        raise LibraryError(409, "that library already exists")
    root.mkdir(parents=True)
    from noesis.library import SETTINGS
    for filename, skeleton in SETTINGS.items():
        (root / filename).write_text(skeleton, encoding="utf-8")
    return f"{who}/{name}"


def library_ids(who: str) -> list[str]:
    """The ids of the libraries a caller reaches: their own, then their groups'."""
    base = data_dir() / "libraries"
    if not base.is_dir():
        return []
    users = [base / who] if who != "*" else sorted(p for p in base.iterdir() if p.is_dir())
    own = [
        f"{u.name}/{lib.name}"
        for u in users if u.is_dir()
        for lib in sorted(u.iterdir()) if lib.is_dir() and NAME_RE.match(lib.name)
    ]
    return own + [i for i in _groups(who) if i not in own]


def _groups(who: str) -> dict[str, str | None]:
    """The groups' libraries a person reaches (members.py), id → the group's name."""
    from noesis import members
    if who == "*" or members.keeper(who) is not None:
        return {}
    return {i: name for i, name in members.libraries_of(who).items() if (data_dir() / "libraries" / i).is_dir()}


def library_names(who: str) -> dict[str, str | None]:
    """The groups' libraries a person reaches, id → what to show, the id's
    second half being only an id: the group's name, or for a group without
    one (a channel nobody named), who else is in it, as The Floor shows it."""
    names = _groups(who)
    for i, name in names.items():
        if name is None:
            names[i] = _others(who, *i.split("/", 1))
    return names


def _others(who: str, owner: str, library: str) -> str | None:
    """A group's other members, by the names it gives them: "With Ann and Bob"."""
    from noesis import members
    try:
        found = members.group(owner, library)
    except LibraryError:
        return None
    others = [m.name or m.user for m in found.members if m.user != who] if found else []
    if not others:
        return None
    return "With " + (others[0] if len(others) == 1 else ", ".join(others[:-1]) + " and " + others[-1])


def lock_for(root: Path) -> asyncio.Lock:
    return locks.setdefault(root, asyncio.Lock())
