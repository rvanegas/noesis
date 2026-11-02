"""The people who sign in to mdc by email, and what each may spend (SERVER.md, Phase 6).

Sign-up is open: an emailed code signs a person in, and the first sign-in
makes their account, its user name derived from the address. What an open
account could cost the operator is capped instead:

- **Model use** is metered in dollars, per user and calendar month (UTC):
  every Anthropic call by its tokens at list price, every dianoia call at a
  flat rate. A free account has a small monthly allowance, and all free
  accounts together a monthly cap; once either is spent, model commands are
  refused until the month turns. The operator can raise one account's
  allowance by a set amount (scripts/accounts.py raise), which it keeps every
  month. A default allowance of 0 stops free model use, except what such
  raises add.
- **Storage:** a free account keeps a few libraries, a bounded total, files
  of a bounded size and of the types mdc reads.
- **Sign-in mail** is rate-limited per address, per client address and in all.

Each user also keeps the names they go by in chats (speaker_names): the
headings, besides "Prompt", that are their own voice. Every run in their
libraries and every MCP read of them labels voices by these; any user has
them, an operator's as much as an account's.

A user with no account here was made by the operator (a users.toml token:
the Mac's CLI, the nightly service) and is unlimited; so is an account whose
plan is "unlimited" (scripts/accounts.py). The meter runs for everyone.

Kept in $MDC_DATA_DIR/accounts.db (SQLite, mode 600), which `mdc` itself
writes to from a run: the server names the library's owner in MDC_ACCOUNT,
and the model clients charge that user.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from mdc import service

FREE = "free"
UNLIMITED = "unlimited"
PLANS = (FREE, UNLIMITED)

# Sign-in mail: (key prefix, window in seconds, most sends in it).
SEND_LIMITS = (("email", 60 * 60, 5), ("ip", 60 * 60, 10), ("all", 24 * 60 * 60, 300))

# What a free account may upload: the types mdc reads (assets.py). What
# /import takes is cmd_import.IMPORTABLE.
FREE_TYPES = frozenset({".md", ".markdown", ".txt", ".rtf", ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp"})

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# A name is a speaker heading, so any words; MDC_USER_NAMES is comma-separated.
SPEAKER_NAME_RE = re.compile(r"^[^\s,](?:[^,\n\r]*[^\s,])?$")
MOST_SPEAKER_NAMES = 20


class AllowanceExhausted(RuntimeError):
    pass


@dataclass(frozen=True)
class Account:
    user: str
    email: str
    plan: str
    created_at: float
    disabled: bool
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
        allowance_usd=float(env("MDC_FREE_ALLOWANCE_USD", "1.00")),
        monthly_cap_usd=float(env("MDC_FREE_MONTHLY_CAP_USD", "25.00")),
        storage_bytes=int(float(env("MDC_FREE_STORAGE_MB", "50")) * 1024 * 1024),
        file_bytes=int(float(env("MDC_FREE_FILE_MB", "10")) * 1024 * 1024),
        libraries=int(env("MDC_FREE_LIBRARIES", "3")),
        dianoia_call_usd=float(env("MDC_DIANOIA_CALL_USD", "0.05")),
    )


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    user TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    plan TEXT NOT NULL DEFAULT 'free',
    created_at REAL NOT NULL,
    disabled INTEGER NOT NULL DEFAULT 0,
    extra_usd REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS spend (
    user TEXT NOT NULL,
    month TEXT NOT NULL,
    usd REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (user, month)
);
CREATE TABLE IF NOT EXISTS names (user TEXT PRIMARY KEY, names TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sends (key TEXT NOT NULL, at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS sends_key_at ON sends (key, at);
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
        yield db
    finally:
        db.close()


def _account(row) -> Account | None:
    if row is None:
        return None
    user, email, plan, created_at, disabled, extra_usd = row
    return Account(user, email, plan, created_at, bool(disabled), extra_usd)


_COLUMNS = "user, email, plan, created_at, disabled, extra_usd"


def normalize_email(value: str) -> str | None:
    email = value.strip().lower()
    return email if len(email) <= 254 and _EMAIL_RE.match(email) else None


def account_for_email(email: str) -> Account | None:
    with connect() as db:
        return _account(db.execute(f"SELECT {_COLUMNS} FROM accounts WHERE email = ?", (email,)).fetchone())


def account(user: str) -> Account | None:
    with connect() as db:
        return _account(db.execute(f"SELECT {_COLUMNS} FROM accounts WHERE user = ?", (user,)).fetchone())


def accounts() -> list[Account]:
    with connect() as db:
        return [_account(r) for r in db.execute(f"SELECT {_COLUMNS} FROM accounts ORDER BY created_at")]


def _taken(db: sqlite3.Connection, user: str) -> bool:
    """A user name in use: an account's, a users.toml token's, or a libraries directory's."""
    if db.execute("SELECT 1 FROM accounts WHERE user = ?", (user,)).fetchone():
        return True
    if (service.data_dir() / "libraries" / user).exists():
        return True
    return user in service.token_users()


def user_stem(email: str) -> str:
    """A user name's start from an address: its local part, as service.NAME_RE allows."""
    local = email.split("@", 1)[0].split("+", 1)[0].lower()
    stem = re.sub(r"[^a-z0-9_-]+", "-", local).strip("-_")[:24].strip("-_")
    return stem or "user"


def create_account(email: str) -> Account:
    """A free account for an address that has none; its user name made unique."""
    stem = user_stem(email)
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            existing = db.execute(f"SELECT {_COLUMNS} FROM accounts WHERE email = ?", (email,)).fetchone()
            if existing:
                db.execute("COMMIT")
                return _account(existing)
            user, n = stem, 1
            while _taken(db, user):
                n += 1
                user = f"{stem}-{n}"
            now = time.time()
            db.execute("INSERT INTO accounts (user, email, plan, created_at) VALUES (?, ?, ?, ?)",
                       (user, email, FREE, now))
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
    return Account(user, email, FREE, now, False)


def link(email: str, user: str, plan: str) -> Account:
    """An account for an existing user (one users.toml already names): the operator's."""
    if not service.NAME_RE.match(user):
        raise ValueError(f"not a user name: {user!r}")
    if plan not in PLANS:
        raise ValueError(f"a plan is one of {', '.join(PLANS)}")
    with connect() as db:
        db.execute("INSERT INTO accounts (user, email, plan, created_at) VALUES (?, ?, ?, ?)",
                   (user, email, plan, time.time()))
    return account(user)


def set_plan(user: str, plan: str) -> None:
    if plan not in PLANS:
        raise ValueError(f"a plan is one of {', '.join(PLANS)}")
    with connect() as db:
        if db.execute("UPDATE accounts SET plan = ? WHERE user = ?", (plan, user)).rowcount != 1:
            raise ValueError(f"no account {user!r}")


def raise_allowance(user: str, usd: float) -> float:
    """Adds to an account's monthly allowance (negative takes back, to the default); the new allowance."""
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            row = db.execute("SELECT extra_usd FROM accounts WHERE user = ?", (user,)).fetchone()
            if row is None:
                raise ValueError(f"no account {user!r}")
            extra = round(row[0] + usd, 2)
            if extra < 0:
                raise ValueError(f"{user} has only ${row[0]:.2f} above the default allowance to take back")
            db.execute("UPDATE accounts SET extra_usd = ? WHERE user = ?", (extra, user))
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
    return allowance(user)


def allowance(user: str) -> float:
    """A free account's monthly allowance: the default and whatever the operator added."""
    found = account(user)
    return limits().allowance_usd + (found.extra_usd if found else 0.0)


def set_disabled(user: str, disabled: bool) -> None:
    with connect() as db:
        if db.execute("UPDATE accounts SET disabled = ? WHERE user = ?", (int(disabled), user)).rowcount != 1:
            raise ValueError(f"no account {user!r}")


def is_active(user: str) -> bool:
    found = account(user)
    return found is not None and not found.disabled


def plan_of(user: str) -> str:
    """An account's plan; a user without one is the operator's, unlimited."""
    found = account(user)
    return found.plan if found is not None else UNLIMITED


def is_free(user: str) -> bool:
    return plan_of(user) == FREE


# ---------------------------------------------------------------------------
# Speaker names
# ---------------------------------------------------------------------------

def speaker_names(user: str) -> tuple[str, ...]:
    """The chat headings that are this user's own voice, besides "Prompt"."""
    with connect() as db:
        row = db.execute("SELECT names FROM names WHERE user = ?", (user,)).fetchone()
    return tuple(json.loads(row[0])) if row else ()


def set_speaker_names(user: str, names: list[str]) -> tuple[str, ...]:
    """Replaces a user's speaker names (none clears them); the names kept."""
    from mdc.config import PROMPT_HEADING
    kept = tuple(dict.fromkeys(n.strip() for n in names if n.strip() and n.strip() != PROMPT_HEADING))
    bad = [n for n in kept if len(n) > 80 or not SPEAKER_NAME_RE.match(n)]
    if bad:
        raise ValueError(f"a name is at most 80 characters, with no comma or line break: {bad}")
    if len(kept) > MOST_SPEAKER_NAMES:
        raise ValueError(f"at most {MOST_SPEAKER_NAMES} names")
    with connect() as db:
        if kept:
            db.execute("INSERT INTO names (user, names) VALUES (?, ?) "
                       "ON CONFLICT (user) DO UPDATE SET names = excluded.names", (user, json.dumps(kept)))
        else:
            db.execute("DELETE FROM names WHERE user = ?", (user,))
    return kept


# ---------------------------------------------------------------------------
# Sign-in mail
# ---------------------------------------------------------------------------

def allow_send(email: str, ip: str) -> bool:
    """Whether a code may go to this address from this client now; if so, counted."""
    now = time.time()
    keys = {"email": f"email:{email}", "ip": f"ip:{ip}", "all": "all"}
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            db.execute("DELETE FROM sends WHERE at < ?", (now - max(w for _, w, _ in SEND_LIMITS),))
            for kind, window, most in SEND_LIMITS:
                (count,) = db.execute("SELECT COUNT(*) FROM sends WHERE key = ? AND at > ?",
                                      (keys[kind], now - window)).fetchone()
                if count >= most:
                    db.execute("COMMIT")
                    return False
            db.executemany("INSERT INTO sends (key, at) VALUES (?, ?)", [(k, now) for k in keys.values()])
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
    return True


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
        (total,) = db.execute(
            "SELECT COALESCE(SUM(s.usd), 0) FROM spend s JOIN accounts a ON a.user = s.user "
            "WHERE s.month = ? AND a.plan = ?", (month(), FREE)).fetchone()
    return total


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


def charge(user: str, usd: float) -> None:
    if usd <= 0:
        return
    with connect() as db:
        db.execute("INSERT INTO spend (user, month, usd) VALUES (?, ?, ?) "
                   "ON CONFLICT (user, month) DO UPDATE SET usd = usd + excluded.usd",
                   (user, month(), usd))


def metered_user() -> str | None:
    """The user a run spends for: named by the server (MDC_ACCOUNT); None on the Mac."""
    return os.environ.get("MDC_ACCOUNT") or None


def check_spend() -> None:
    """Before a model call: refuses one the run's user may not make."""
    user = metered_user()
    if user is not None and (why := refusal(user)):
        raise AllowanceExhausted(why)


def anthropic_cost(model: str, usage) -> float:
    """A message's cost at list price; an unknown model at the dearest known rates."""
    from mdc.cmd_reply import _ANTHROPIC_PRICING
    from mdc.text_utils import _lookup_price
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
