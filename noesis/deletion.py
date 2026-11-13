"""What is deleted at noesis: gone at once, removed for good thirty days later (2026-11-09).

One recovery window everywhere, as at The Floor: a deletion takes effect at
once for everybody, and for thirty days the operator can still undo it by
hand, which nothing in a client can.

- **A file** deleted through the API (the web client's *Delete*, the CLI's
  sync) moves to `$NOESIS_DATA_DIR/trash/<user>/<library>/<day>/<path>`
  (`trash`), outside the library, where nothing that reads a library (the
  index, the name checks, asset lookup, sync, /mcp) can see it, and where it
  counts toward nobody's storage. `scripts/libraries.py trash` lists and
  restores.
- **A person** whose account was deleted at auth is told so by auth
  (`DELETE /users/<user>`, server.py) and is deleted here (`delete_user`):
  their libraries move to `$NOESIS_DATA_DIR/deleted/<user>/`, and their
  tokens are refused from then on (bearer.py). Thirty days later the
  libraries, their trash, and their plan and spend go
  (`sweep`). `scripts/accounts.py deleted` lists and restores. A user with a
  minted users.toml token is the operator's, and is reported rather than
  swept.

`sweep` runs in `noesis serve`, at start and every six hours.
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

from noesis import service

DAYS = 30
DAY_SECONDS = 24 * 60 * 60


def _day(at: float) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(at))


def libraries_dir() -> Path:
    return service.data_dir() / "libraries"


def trash_dir() -> Path:
    return service.data_dir() / "trash"


def deleted_dir() -> Path:
    return service.data_dir() / "deleted"


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

def trash(root: Path, path: Path, now: float | None = None) -> Path:
    """Moves a library's file to the trash, under today; where it went."""
    rel = path.relative_to(root)
    base, day = trash_dir() / root.relative_to(libraries_dir()), _day(time.time() if now is None else now)
    # The same path deleted twice in a day: the second under `<day>~2`, and so on.
    dest, n = base / day / rel, 1
    while dest.exists():
        n += 1
        dest = base / f"{day}~{n}" / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    os.replace(path, dest)
    return dest


def trashed(library_id: str) -> list[str]:
    """A library's trash, each `<day>/<path>`, oldest first."""
    base = trash_dir() / library_id
    if not base.is_dir():
        return []
    return sorted(p.relative_to(base).as_posix() for p in base.rglob("*") if p.is_file())


def restore_file(library_id: str, entry: str) -> Path:
    """A trashed file (`<day>/<path>`, as `trashed` names it) back where it was."""
    source = trash_dir() / library_id / entry
    _, _, rel = entry.partition("/")
    if not rel or ".." in Path(entry).parts or not source.is_file():
        raise ValueError(f"not in {library_id}'s trash: {entry}")
    dest = libraries_dir() / library_id / rel
    if dest.exists():
        raise ValueError(f"{dest.relative_to(libraries_dir() / library_id)} is there again; move it first")
    dest.parent.mkdir(parents=True, exist_ok=True)
    os.replace(source, dest)
    return dest


# ---------------------------------------------------------------------------
# People
# ---------------------------------------------------------------------------

def delete_user(user: str, now: float | None = None) -> None:
    """A person deleted at auth: refused from now on, their libraries moved out of
    reach. Again for somebody already deleted changes nothing."""
    from noesis import accounts
    with accounts.connect() as db:
        db.execute("INSERT OR IGNORE INTO deleted (user, at) VALUES (?, ?)", (user, time.time() if now is None else now))
    source, dest = libraries_dir() / user, deleted_dir() / user
    if source.is_dir() and not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, dest)


def is_deleted(user: str) -> bool:
    from noesis import accounts
    with accounts.connect() as db:
        return db.execute("SELECT 1 FROM deleted WHERE user = ?", (user,)).fetchone() is not None


def deleted() -> list[tuple[str, float]]:
    """(user, when) of each person deleted and not yet swept."""
    from noesis import accounts
    with accounts.connect() as db:
        return db.execute("SELECT user, at FROM deleted ORDER BY at").fetchall()


def restore_user(user: str) -> None:
    """Undoes delete_user within the window: the libraries back, the tokens taken again.
    The account at auth is another matter, and the operator's there."""
    from noesis import accounts
    source, dest = deleted_dir() / user, libraries_dir() / user
    if not is_deleted(user):
        raise ValueError(f"{user} is not deleted")
    if source.is_dir():
        if dest.exists():
            raise ValueError(f"{dest} exists; move it first")
        os.replace(source, dest)
    with accounts.connect() as db:
        db.execute("DELETE FROM deleted WHERE user = ?", (user,))


def sweep(now: float | None = None) -> list[str]:
    """Removes for good what was deleted more than DAYS ago; what it removed, and what it kept and why."""
    from noesis import accounts
    now = time.time() if now is None else now
    cutoff = now - DAYS * DAY_SECONDS
    done = []
    if trash_dir().is_dir():
        for day in sorted(trash_dir().glob("*/*/*")):
            # A day whose last moment is older than the window; `<day>~2` with its day.
            if day.is_dir() and day.name.split("~")[0] < _day(cutoff):
                shutil.rmtree(day)
                done.append(f"trash {day.relative_to(trash_dir())}")
                for parent in (day.parent, day.parent.parent):
                    if not any(parent.iterdir()):
                        parent.rmdir()
    operators = service.token_users()
    for user, at in deleted():
        if at > cutoff:
            continue
        if user in operators:
            done.append(f"kept {user}: a users.toml token is the operator's, removed by hand")
            continue
        for base in (deleted_dir(), trash_dir()):
            if (base / user).exists():
                shutil.rmtree(base / user)
        with accounts.connect() as db:
            for table in ("accounts", "spend", "deleted"):
                db.execute(f"DELETE FROM {table} WHERE user = ?", (user,))
        done.append(f"user {user}")
    return done
