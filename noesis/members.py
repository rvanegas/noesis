"""Libraries an application keeps for its groups, whose members it decides.

Since 2026-11-07 (planning/decision/2026-11-07-an-application-keeps-libraries-for-its-groups.md):
The Floor gives a channel a library of its own, `thefloor/<handle>`, which
every member of the channel reaches and nobody else does. The application is
the owner, as a person is the owner of `<user>/<library>`, and **it alone
says who belongs**: noesis asks it rather than being told, so the two can
never disagree about who may read, and somebody leaving loses the library at
the next asking with nothing sent.

- **An application keeps libraries** once the operator marks its client id
  here with the URL it answers at (`scripts/client_libraries.py`, kept in
  $NOESIS_DATA_DIR/keepers.json), which also makes `libraries/<client id>/`;
  auth holds the name, so no person can sign up as it (its `held` names).
  Its client id is the owner's name.
- **noesis asks two questions**, with its own token from auth
  (`bearer.own_token`, scope `<client id>:members`, which the application
  checks against auth's keys): `GET <url>/noesis/libraries/<name>`, the
  group's name and members — each by user name, whether they pay, and the
  name they go by in its transcripts — and `GET <url>/noesis/users/<user>/
  libraries`, the groups somebody belongs to. Answers are kept a minute.
- **The application itself** signs in with a token of its own from auth
  (client_credentials, scope `noesis:keep`), and is then the owner
  (`caller`): it makes its groups' libraries and files into them.
- **Reading is every member's; more is a paying member's** (since
  2026-11-10): one who does not pay lists and reads the library's files and
  does nothing else there, nor copies out of it (server._paying).
- **Spending** is metered per library, as `<owner>/<library>`, for the
  application to divide among whoever pays (`GET /applications/spending`);
  the owner has no account, so nothing caps it here, and a group with nobody
  paying is refused whatever would spend (server.py, `_may_run`).
- **Voice** (since 2026-11-09, planning/decision/2026-11-09-a-channel-s-voices-are-its-members.md):
  each member is their own voice, named by the display name the application
  gives them, their headings that name and the names they keep here
  (`speakers`). No heading is the library's own: who is "the user" is
  whoever reads (mcp_server._voiced), and a run, which nobody reads, names
  each member instead.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from noesis.config import Speaker
from noesis.service import LibraryError

# How long an answer is believed: long enough that a session's reads ask once,
# short enough that leaving a group closes its library within the minute.
TTL_SECONDS = 60

_cache: dict[tuple[str, ...], tuple[float, object]] = {}


@dataclass(frozen=True)
class Keeper:
    owner: str  # the client id, and the libraries' owner
    url: str


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


def _path():
    from noesis import service
    return service.data_dir() / "keepers.json"


def keepers() -> dict[str, Keeper]:
    """The applications the operator marked as keeping libraries, by owner."""
    try:
        marked = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {cid: Keeper(cid, url.rstrip("/")) for cid, url in marked.items()}


def mark(client_id: str, url: str | None) -> None:
    """Marks an application as keeping libraries at a URL, or (None) unmarks it."""
    marked = {k.owner: k.url for k in keepers().values()}
    if url is None:
        marked.pop(client_id, None)
    else:
        marked[client_id] = url.rstrip("/")
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(".keepers.json.tmp")
    tmp.write_text(json.dumps(marked, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def keeper(owner: str) -> Keeper | None:
    return keepers().get(owner)


def keeper_for(token) -> str | None:
    """The owner an application's own token (bearer.KEEP) signs in as, or None."""
    from noesis.bearer import KEEP
    if KEEP not in (token.scopes or []) or token.subject != token.client_id:
        return None
    found = keeper(token.client_id)
    return found.owner if found is not None else None


def _get(found: Keeper, path: str) -> dict | None:
    """The application's answer, None for a 404; LibraryError when it cannot be asked."""
    from noesis import bearer
    try:
        token = bearer.own_token(f"{found.owner}:members")
    except (OSError, ValueError, KeyError):
        raise LibraryError(503, "noesis could not get its own token from auth; try again in a minute") from None
    request = urllib.request.Request(found.url + path, headers={"Authorization": f"Bearer {token}"})
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
    """The headings that are the library's owner: a person's own names, and none
    of a group's, whose members are each their own voice (speakers)."""
    from noesis import accounts
    return accounts.speaker_names(owner) if keeper(owner) is None else ()


def display_name(user: str) -> str:
    """The name a person is shown by, as auth keeps it (since 2026-11-09), else
    their user name: auth not answering costs a run nothing but the name.

    Asked with noesis's own token from auth, which answers `/names/display`
    for any token it signed; the scope is the one noesis's client is allowed.
    """
    from noesis import bearer

    def ask() -> str | None:
        token = bearer.own_token("thefloor:members")
        request = urllib.request.Request(
            f"{bearer.auth_url()}/names/display?{urllib.parse.urlencode({'user': user})}",
            headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(request, timeout=10) as response:
            return (json.loads(response.read().decode()).get("names") or {}).get(user.lower())

    try:
        return _cached(("display", user), ask) or user
    except (OSError, ValueError, KeyError):
        return user


def speakers(owner: str, library: str) -> tuple[Speaker, ...]:
    """A group's members, each by the name the application gives them (else
    their user name) and their headings: that name and the names they keep
    here. None for a person's library."""
    from noesis import accounts
    if keeper(owner) is None:
        return ()
    found = group(owner, library)
    return tuple(
        Speaker(member.user, member.name or member.user,
                tuple(dict.fromkeys(h for h in (member.name or member.user, *accounts.speaker_names(member.user)) if h)))
        for member in (found.members if found else ()))


def metered(owner: str, library: str) -> str:
    """Whose meter a library's spending runs: its owner's, or the library's own for a group."""
    return f"{owner}/{library}" if keeper(owner) is not None else owner
