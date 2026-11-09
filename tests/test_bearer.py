"""The tokens noesis takes now that sign-in is auth's (bearer.py), and leaving sign-in's data to auth."""

import hashlib
import importlib.util
import io
import json
import sqlite3
from contextlib import redirect_stdout
from pathlib import Path

import pytest

import auth_tokens
from noesis import accounts, bearer, members

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("NOESIS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NOESIS_CONFIG_DIR", str(tmp_path / "config"))
    (tmp_path / "users.toml").write_text(
        f'[[tokens]]\nuser = "rod"\nsha256 = "{hashlib.sha256(b"rod-token").hexdigest()}"\n')
    auth_tokens.install(monkeypatch)
    return tmp_path


def test_the_three_kinds_of_token(data):
    minted = bearer.access_token("rod-token")
    assert minted.subject == "rod" and set(minted.scopes) == {bearer.READ, bearer.IMPORT, bearer.API}
    issued = bearer.access_token(auth_tokens.token("ann", scopes=["noesis:read"], client="claude1"))
    assert issued.subject == "ann" and issued.client_id == "claude1" and issued.scopes == ["noesis:read"]
    confined, ttl = bearer.confined_token("thefloor", "thefloor/lunch")
    found = bearer.access_token(confined)
    assert found.subject == "thefloor" and found.scopes == [bearer.READ, "library:thefloor/lunch"] and ttl == 3600
    assert (data / "confined.json").stat().st_mode & 0o777 == 0o600
    assert bearer.access_token("nope") is None


def test_auths_keys_are_asked_again_for_one_noesis_does_not_know(data, monkeypatch):
    asked = []
    keys = {}
    monkeypatch.setattr(bearer, "_fetch_keys", lambda: asked.append(1) or dict(keys))
    token = auth_tokens.token("ann")
    assert bearer.access_token(token) is None and len(asked) == 1
    # auth rotated in a key: an unknown one is asked for again, but not more than every half minute.
    keys[auth_tokens.KID] = auth_tokens.KEY.public_key()
    assert bearer.access_token(token) is None and len(asked) == 1
    bearer._jwks["tried"] -= bearer.JWKS_RETRY
    assert bearer.access_token(token).subject == "ann" and len(asked) == 2

    def unreachable():
        raise OSError("auth is down")
    # auth down: the keys already known still verify.
    monkeypatch.setattr(bearer, "_fetch_keys", unreachable)
    bearer._jwks["fetched"] -= bearer.JWKS_TTL + 1
    bearer._jwks["tried"] -= bearer.JWKS_RETRY
    assert bearer.access_token(token).subject == "ann"


def test_noesis_asks_auth_for_its_own_token_and_keeps_it(data, monkeypatch):
    sent = []

    def urlopen(url, data, timeout):
        sent.append(data.decode())
        return io.BytesIO(json.dumps({"access_token": "own", "expires_in": 900}).encode())
    monkeypatch.setattr(bearer.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(bearer, "_own", {})
    with pytest.raises(OSError):
        bearer.own_token("thefloor:members")
    monkeypatch.setenv("NOESIS_AUTH_CLIENT_ID", "noesis")
    monkeypatch.setenv("NOESIS_AUTH_CLIENT_SECRET", "s")
    assert bearer.own_token("thefloor:members") == bearer.own_token("thefloor:members") == "own"
    assert len(sent) == 1 and "grant_type=client_credentials" in sent[0] and "scope=thefloor%3Amembers" in sent[0]


def test_sign_ins_data_is_left_to_auth(data):
    db = sqlite3.connect(data / "accounts.db")
    db.executescript("""
        CREATE TABLE accounts (user TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, plan TEXT NOT NULL DEFAULT 'free',
                               created_at REAL NOT NULL, disabled INTEGER NOT NULL DEFAULT 0,
                               extra_usd REAL NOT NULL DEFAULT 0);
        CREATE TABLE spend (user TEXT NOT NULL, month TEXT NOT NULL, usd REAL NOT NULL DEFAULT 0,
                            PRIMARY KEY (user, month));
        CREATE TABLE names (user TEXT PRIMARY KEY, names TEXT NOT NULL);
        CREATE TABLE reservations (user TEXT PRIMARY KEY, email TEXT, client TEXT, created_at REAL);
        CREATE TABLE sends (key TEXT, at REAL);
        INSERT INTO accounts VALUES ('ann', 'ann@example.com', 'unlimited', 1.0, 0, 2.5);
        INSERT INTO spend VALUES ('ann', '2026-11', 0.5);
    """)
    db.commit()
    db.close()
    (data / "oauth.json").write_text(json.dumps({"clients": {
        "thefloor": {"client_id": "thefloor", "keeps_libraries": "https://floor.example"},
        "claude1": {"client_id": "claude1"}}}))
    spec = importlib.util.spec_from_file_location("migrate_to_auth", REPO / "scripts" / "migrate_to_auth.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    with redirect_stdout(io.StringIO()):
        script.main([])
    assert (data / "oauth.json").exists() and members.keeper("thefloor") is None
    out = io.StringIO()
    with redirect_stdout(out):
        script.main(["--apply"])
    assert "keeper: thefloor at https://floor.example" in out.getvalue()
    assert accounts.account("ann") == accounts.Account("ann", "unlimited", 1.0, 2.5)
    assert sqlite3.connect(data / "accounts.db").execute("SELECT usd FROM spend WHERE user = 'ann'").fetchone() == (0.5,)
    accounts.set_plan("newcomer", accounts.FREE)  # the new table takes a row without an address
    tables = {r[0] for r in sqlite3.connect(data / "accounts.db").execute("SELECT name FROM sqlite_master")}
    assert not tables & {"reservations", "sends"}
    assert members.keeper("thefloor").url == "https://floor.example"
    assert not (data / "oauth.json").exists() and (data / script.BACKUP).exists()
