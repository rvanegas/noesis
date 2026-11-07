"""Libraries an application keeps for its groups, whose members it decides.

Since 2026-11-07 (planning/decision/2026-11-07-an-application-keeps-libraries-for-its-groups.md):
The Floor gives a channel a library of its own, `thefloor/<handle>`, which
every member of the channel reaches and nobody else does. The application is
the owner, as a person is the owner of `<user>/<library>`, and **it alone
says who belongs**: noesis asks it rather than being told, so the two can
never disagree about who may read, and somebody leaving loses the library at
the next asking with nothing sent.

- **An application keeps libraries** once the operator marks its client with
  the URL it answers at (`scripts/client_libraries.py`), which also makes
  `libraries/<client id>/`, so the name is taken in the register
  (`accounts._taken`) and no person can sign up as it. Its client id is the
  owner's name.
- **noesis asks two questions**, with the application's own id and secret as
  HTTP Basic, the pair it presents here: `GET <url>/noesis/libraries/<name>`,
  the group's name and members — each by user name, whether they pay, and the
  name they go by in its transcripts — and `GET <url>/noesis/users/<user>/
  libraries`, the groups somebody belongs to. Answers are kept a minute.
- **The application itself** signs in with the same pair as HTTP Basic, and
  is then the owner (`caller`): it makes its groups' libraries and files into
  them.
- **Spending** is metered per library, as `<owner>/<library>`, for the
  application to divide among whoever pays (`GET /applications/spending`);
  the owner has no account, so nothing caps it here, and a group with nobody
  paying is refused whatever would spend (server.py, `_may_run`).
- **Voice**: every member's lines are the library's own, by the names the
  application gives and the names each keeps here; anybody else's are context.
"""

from __future__ import annotations

import base64
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from noesis.service import LibraryError

# How long an answer is believed: long enough that a session's reads ask once,
# short enough that leaving a group closes its library within the minute.
TTL_SECONDS = 60

_cache: dict[tuple[str, ...], tuple[float, object]] = {}


@dataclass(frozen=True)
class Keeper:
    owner: str  # the client id, and the libraries' owner
    url: str
    secret: str


@dataclass(frozen=True)
class Member:
    user: str
    pays: bool
    name: str | None  # what they are called in the group's transcripts


@dataclass(frozen=True)
class Group:
    name: str | None
    members: tuple[Member, ...]

    def admits(self, user: str) -> bool:
        return any(m.user == user.lower() for m in self.members)

    @property
    def funded(self) -> bool:
        return any(m.pays for m in self.members)


def keepers() -> dict[str, Keeper]:
    """The applications the operator marked as keeping libraries, by owner."""
    from noesis.oauth import provider
    return {cid: Keeper(cid, url.rstrip("/"), secret) for cid, (url, secret) in provider.library_keepers().items()}


def keeper(owner: str) -> Keeper | None:
    return keepers().get(owner)


def keeper_for_basic(authorization: str) -> str | None:
    """The owner an application's HTTP Basic credentials sign in as, or None."""
    try:
        cid, _, secret = base64.b64decode(authorization.removeprefix("Basic ").strip()).decode().partition(":")
    except ValueError:
        return None
    found = keeper(cid)
    if found is None or not secrets.compare_digest(found.secret.encode(), secret.encode()):
        return None
    return found.owner


def _get(found: Keeper, path: str) -> dict | None:
    """The application's answer, None for a 404; LibraryError when it cannot be asked."""
    basic = base64.b64encode(f"{found.owner}:{found.secret}".encode()).decode()
    request = urllib.request.Request(found.url + path, headers={"Authorization": f"Basic {basic}"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise LibraryError(503, f"{found.owner} did not say who belongs ({exc.code})") from None
    except (OSError, ValueError):
        raise LibraryError(503, f"{found.owner} did not answer; try again in a minute") from None


def _cached(key: tuple[str, ...], ask):
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and hit[0] > now:
        return hit[1]
    value = ask()
    _cache[key] = (now + TTL_SECONDS, value)
    return value


def group(owner: str, library: str) -> Group | None:
    """Who belongs to an application's library, None for one it does not know."""
    found = keeper(owner)
    if found is None:
        return None

    def ask() -> Group | None:
        answer = _get(found, f"/noesis/libraries/{urllib.parse.quote(library)}")
        if answer is None:
            return None
        members = tuple(
            Member(str(m["user"]).lower(), bool(m.get("pro")), m.get("name") or None)
            for m in answer.get("members") or [] if isinstance(m, dict) and m.get("user"))
        return Group(answer.get("name") or None, members)
    return _cached(("group", owner, library), ask)


def libraries_of(user: str) -> dict[str, str | None]:
    """The applications' libraries somebody belongs to, id → the group's name.
    An application that does not answer lists none, rather than failing the list."""
    found: dict[str, str | None] = {}
    for keeping in keepers().values():
        def ask(keeping=keeping) -> dict[str, str | None]:
            answer = _get(keeping, f"/noesis/users/{urllib.parse.quote(user)}/libraries") or {}
            return {f"{keeping.owner}/{g['handle']}": g.get("name") or None
                    for g in answer.get("libraries") or [] if isinstance(g, dict) and g.get("handle")}
        try:
            found.update(_cached(("libraries", keeping.owner, user), ask))
        except LibraryError:
            continue
    return found


def voices(owner: str, library: str) -> tuple[str, ...]:
    """The headings that are the library's own voice: a person's own names, or
    every member's of a group — the name the application gives, and theirs here."""
    from noesis import accounts
    if keeper(owner) is None:
        return accounts.speaker_names(owner)
    found = group(owner, library)
    names: list[str] = []
    for member in found.members if found else ():
        for name in (member.name, *accounts.speaker_names(member.user)):
            # A comma or line break would split NOESIS_USER_NAMES (server.py).
            if name and name not in names and not any(c in name for c in ",\n\r"):
                names.append(name)
    return tuple(names)


def metered(owner: str, library: str) -> str:
    """Whose meter a library's spending runs: its owner's, or the library's own for a group."""
    return f"{owner}/{library}" if keeper(owner) is not None else owner
