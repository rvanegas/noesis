"""What each person may spend and store at noesis (SERVER.md, Phase 6).

Who a person is is auth's (`auth.twohands.co`, since 2026-11-08): they sign
in there, and noesis knows them by the user name in its tokens (bearer.py).
What they may do here is noesis's, kept per user name:

- **A plan**, `free` or `unlimited`, which noesis no longer keeps: a person
  is unlimited when auth says so (since 2026-11-22, auth's
  `planning/decision/2026-11-22-unlimited-is-one-mark-kept-here.md`), the
  one mark The Floor reads too, set there by the operator; a user with a
  minted users.toml token (the Mac's CLI, the nightly service) and an
  application keeping libraries are the operator's, unlimited; anybody else
  is free. The meter runs for everyone.
- **Model use** is metered in dollars, per user and calendar month (UTC):
  every Anthropic call by its tokens at list price, every dianoia call at a
  flat rate. A free account has a small monthly allowance, and all free
  accounts together a monthly cap; once either is spent, model commands are
  refused until the month turns. The operator can raise one account's
  allowance by a set amount (scripts/accounts.py raise), which it keeps every
  month. A default allowance of 0 stops free model use, except what such
  raises add.
- **Storage:** a free account keeps a few libraries, a bounded total, files
  of a bounded size and of the types noesis reads.

A person who deletes their account at auth is deleted here too, and their
plan and spend go thirty days later (deletion.py, which keeps who and
when in `deleted`).

Kept in $NOESIS_DATA_DIR/accounts.db (SQLite, mode 600), which `noesis` itself
writes to from a run: the server names the library's owner in NOESIS_ACCOUNT,
and the model clients charge that user. A user has a row once the operator
gives them a raise.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from noesis import service

FREE = "free"
UNLIMITED = "unlimited"

# What a free account may upload: the types noesis reads (assets.py). What
# /import takes is cmd_import.IMPORTABLE.
FREE_TYPES = frozenset({".md", ".markdown", ".txt", ".rtf", ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp"})


class AllowanceExhausted(RuntimeError):
    pass


@dataclass(frozen=True)
class Account:
    """A user the operator has given a raise."""
    user: str
    created_at: float
    extra_usd: float = 0.0


@dataclass(frozen=True)
class Limits:
    """A free account's limits, from the environment so the operator can turn them."""
    allowance_usd: float
    monthly_cap_usd: float
    storage_bytes: int
    file_bytes: int
    libraries: int
    dianoia_call_usd: float


def limits() -> Limits:
    env = os.environ.get
    return Limits(
        allowance_usd=float(env("NOESIS_FREE_ALLOWANCE_USD", "1.00")),
        monthly_cap_usd=float(env("NOESIS_FREE_MONTHLY_CAP_USD", "25.00")),
        storage_bytes=int(float(env("NOESIS_FREE_STORAGE_MB", "50")) * 1024 * 1024),
        file_bytes=int(float(env("NOESIS_FREE_FILE_MB", "10")) * 1024 * 1024),
        libraries=int(env("NOESIS_FREE_LIBRARIES", "3")),
        dianoia_call_usd=float(env("NOESIS_DIANOIA_CALL_USD", "0.05")),
    )


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    user TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    extra_usd REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS spend (
    user TEXT NOT NULL,
    month TEXT NOT NULL,
    usd REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (user, month)
);
CREATE TABLE IF NOT EXISTS deleted (user TEXT PRIMARY KEY, at REAL NOT NULL);
"""


def _path() -> Path:
    return service.data_dir() / "accounts.db"


@contextmanager
def connect():
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    db = sqlite3.connect(path, timeout=10, isolation_level=None)
    if new:
        path.chmod(0o600)
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript(_SCHEMA)
        # The plan each row kept until 2026-11-22, when auth's mark replaced it.
        if any(row[1] == "plan" for row in db.execute("PRAGMA table_info(accounts)")):
            db.execute("ALTER TABLE accounts DROP COLUMN plan")
        yield db
    finally:
        db.close()


_COLUMNS = "user, created_at, extra_usd"


def account(user: str) -> Account | None:
    with connect() as db:
        row = db.execute(f"SELECT {_COLUMNS} FROM accounts WHERE user = ?", (user,)).fetchone()
    return Account(*row) if row else None


def accounts() -> list[Account]:
    with connect() as db:
        return [Account(*r) for r in db.execute(f"SELECT {_COLUMNS} FROM accounts ORDER BY created_at")]


def _row(db: sqlite3.Connection, user: str) -> None:
    """A user's row, made if it had none."""
    if not service.NAME_RE.match(user):
        raise ValueError(f"not a user name: {user!r}")
    db.execute("INSERT OR IGNORE INTO accounts (user, created_at) VALUES (?, ?)", (user, time.time()))


def raise_allowance(user: str, usd: float) -> float:
    """Adds to an account's monthly allowance (negative takes back, to the default); the new allowance."""
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            _row(db, user)
            (extra,) = db.execute("SELECT extra_usd FROM accounts WHERE user = ?", (user,)).fetchone()
            new = round(extra + usd, 2)
            if new < 0:
                raise ValueError(f"{user} has only ${extra:.2f} above the default allowance to take back")
            db.execute("UPDATE accounts SET extra_usd = ? WHERE user = ?", (new, user))
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
    return allowance(user)


def allowance(user: str) -> float:
    """A free account's monthly allowance: the default and whatever the operator added."""
    found = account(user)
    return limits().allowance_usd + (found.extra_usd if found else 0.0)


# How long auth's answer is believed: a mark set or taken there reaches noesis
# within this, and a session's checks ask once.
UNLIMITED_TTL = 60

_unlimited: tuple[float, frozenset[str]] | None = None


def _unlimited_path() -> Path:
    return service.data_dir() / "unlimited.json"


def unlimited_users() -> frozenset[str]:
    """The people auth says are unlimited (`GET /unlimited`, noesis's own token),
    kept a minute. When auth cannot be asked, its last answer, kept on disk so a
    run's process and a restart have it too; none ever, nobody."""
    global _unlimited
    now = time.monotonic()
    if _unlimited is not None and _unlimited[0] > now:
        return _unlimited[1]
    import urllib.request
    from noesis import bearer
    try:
        token = bearer.own_token("thefloor:members")
        request = urllib.request.Request(f"{bearer.auth_url()}/unlimited",
                                         headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(request, timeout=10) as response:
            users = frozenset(str(u).lower() for u in json.loads(response.read().decode())["users"])
    except (OSError, ValueError, KeyError, TypeError):
        try:
            return frozenset(json.loads(_unlimited_path().read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            return frozenset()
    _unlimited = (now + UNLIMITED_TTL, users)
    path = _unlimited_path()
    try:
        tmp = path.with_name(".unlimited.json.tmp")
        tmp.write_text(json.dumps(sorted(users)), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass
    return users


def plan_of(user: str) -> str:
    """A user's plan: unlimited where auth marks them, or for the operator's (a minted token, an
    application keeping libraries, a group library's own meter, `<owner>/<library>`); else free."""
    from noesis import members
    if "/" in user or user in service.token_users() or members.keeper(user) is not None:
        return UNLIMITED
    return UNLIMITED if user.lower() in unlimited_users() else FREE


def is_free(user: str) -> bool:
    return plan_of(user) == FREE


def rename(old: str, new: str) -> None:
    """A user's plan and spend, under a new name (scripts/rename_user.py)."""
    with connect() as db:
        for table in ("accounts", "spend"):
            db.execute(f"UPDATE {table} SET user = ? WHERE user = ?", (new, old))


# ---------------------------------------------------------------------------
# The meter
# ---------------------------------------------------------------------------

def month() -> str:
    return time.strftime("%Y-%m", time.gmtime())


def spent(user: str) -> float:
    with connect() as db:
        row = db.execute("SELECT usd FROM spend WHERE user = ? AND month = ?", (user, month())).fetchone()
    return row[0] if row else 0.0


def free_spent() -> float:
    """What every free account together has spent this month."""
    with connect() as db:
        rows = db.execute("SELECT user, usd FROM spend WHERE month = ?", (month(),)).fetchall()
    return sum(usd for user, usd in rows if "/" not in user and is_free(user))


def refusal(user: str) -> str | None:
    """Why this user may not spend now, or None if they may."""
    if not is_free(user):
        return None
    free = limits()
    mine = allowance(user)
    if spent(user) >= mine:
        return (f"this month's free allowance (${mine:.2f}) is used up; "
                "model commands are available again next month")
    if free_spent() >= free.monthly_cap_usd:
        return "free model use is paused for the rest of this month"
    return None


def spending_under(owner: str, month_: str) -> dict[str, float]:
    """What each of an application's libraries spent in a month, by id (members.metered)."""
    with connect() as db:
        rows = db.execute("SELECT user, usd FROM spend WHERE month = ? AND user LIKE ? ESCAPE '\\'",
                          (month_, owner.replace("_", "\\_") + "/%")).fetchall()
    return {user: usd for user, usd in rows}


def charge(user: str, usd: float) -> None:
    if usd <= 0:
        return
    with connect() as db:
        db.execute("INSERT INTO spend (user, month, usd) VALUES (?, ?, ?) "
                   "ON CONFLICT (user, month) DO UPDATE SET usd = usd + excluded.usd",
                   (user, month(), usd))


def metered_user() -> str | None:
    """The user a run spends for: named by the server (NOESIS_ACCOUNT); None on the Mac."""
    return os.environ.get("NOESIS_ACCOUNT") or None


def check_spend() -> None:
    """Before a model call: refuses one the run's user may not make."""
    user = metered_user()
    if user is not None and (why := refusal(user)):
        raise AllowanceExhausted(why)


def anthropic_cost(model: str, usage) -> float:
    """A message's cost at list price; an unknown model at the dearest known rates."""
    from noesis.cmd_reply import _ANTHROPIC_PRICING
    from noesis.text_utils import _lookup_price
    in_rate, out_rate = _lookup_price(model, _ANTHROPIC_PRICING) or max(_ANTHROPIC_PRICING.values())
    return (
        (getattr(usage, "input_tokens", 0) or 0) * in_rate
        + (getattr(usage, "output_tokens", 0) or 0) * out_rate
        + (getattr(usage, "cache_creation_input_tokens", 0) or 0) * in_rate * 1.25
        + (getattr(usage, "cache_read_input_tokens", 0) or 0) * in_rate * 0.10
    ) / 1_000_000


def charge_anthropic(model: str, usage) -> None:
    user = metered_user()
    if user is not None and usage is not None:
        charge(user, anthropic_cost(model, usage))


def charge_dianoia() -> None:
    user = metered_user()
    if user is not None:
        charge(user, limits().dianoia_call_usd)


# ---------------------------------------------------------------------------
# Storage limits
# ---------------------------------------------------------------------------

def stored_bytes(user: str) -> int:
    """Everything under the user's libraries, their index state included."""
    base = service.data_dir() / "libraries" / user
    if not base.is_dir():
        return 0
    return sum(p.stat().st_size for p in base.rglob("*") if p.is_file() and not p.is_symlink())


def storage_refusal(user: str, name: str, size: int, replacing: int = 0, *, types=FREE_TYPES) -> str | None:
    """Why a free account may not store this file, or None if it may."""
    if not is_free(user):
        return None
    free = limits()
    if Path(name).suffix.lower() not in types:
        return f"a free account keeps only {', '.join(sorted(types))} files"
    if size > free.file_bytes:
        return f"a file of a free account is at most {free.file_bytes // (1024 * 1024)} MB"
    if stored_bytes(user) - replacing + size > free.storage_bytes:
        return f"a free account keeps at most {free.storage_bytes // (1024 * 1024)} MB"
    return None
