"""What is deleted at noesis: a file to the trash, a person at auth's word, each removed for good thirty days on (deletion.py)."""

import hashlib
import time

import pytest
from fastapi.testclient import TestClient

import auth_tokens
from noesis import accounts, deletion, server

DAY = deletion.DAY_SECONDS
ANN = {"Authorization": "Bearer ann-token"}
BASE = "/libraries/ann/philosophy"
CHAT = "2025/2025-04-25-old-roman.chat.md"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("NOESIS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NOESIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("NOESIS_PUBLIC_URL", "https://noesis.test")
    auth_tokens.install(monkeypatch)
    (tmp_path / "users.toml").write_text(
        f'[[tokens]]\nuser = "ann"\nsha256 = "{_sha(b"ann-token")}"\n'
        f'[[tokens]]\nuser = "rod"\nsha256 = "{_sha(b"rod-token")}"\n')
    lib = tmp_path / "libraries" / "ann" / "philosophy"
    (lib / "2025").mkdir(parents=True)
    (lib / CHAT).write_text("one")
    (tmp_path / "libraries" / "bob" / "notes").mkdir(parents=True)
    (tmp_path / "libraries" / "bob" / "notes" / "x.md").write_text("bob's")
    return tmp_path


@pytest.fixture
def client(data):
    return TestClient(server.app)


def _erase(user, **kwargs):
    defaults = {"scopes": ["noesis:erase"], "client": "dianoia-auth"}
    return auth_tokens.bearer("dianoia-auth", **{**defaults, **kwargs})


# --- files -------------------------------------------------------------------

def test_a_deleted_file_goes_to_the_trash_out_of_every_view(client, data):
    assert client.delete(f"{BASE}/files/{CHAT}", headers={**ANN, "If-Match": f'"{_sha(b"one")}"'}).status_code == 204
    assert client.get(f"{BASE}/files/{CHAT}", headers=ANN).status_code == 404
    assert CHAT not in client.get(f"{BASE}/files", headers=ANN).json()["files"]
    assert not (data / "libraries/ann/philosophy" / CHAT).exists()
    (entry,) = deletion.trashed("ann/philosophy")
    assert entry.endswith(f"/{CHAT}") and accounts.stored_bytes("ann") == 0
    # The same path deleted again the same day is kept beside the first.
    (data / "libraries/ann/philosophy" / CHAT).write_text("two")
    client.delete(f"{BASE}/files/{CHAT}", headers={**ANN, "If-Match": f'"{_sha(b"two")}"'})
    assert len(deletion.trashed("ann/philosophy")) == 2
    # The operator restores one, but not over a file there again.
    restored = deletion.restore_file("ann/philosophy", entry)
    assert restored.read_text() == "one"
    with pytest.raises(ValueError):
        deletion.restore_file("ann/philosophy", deletion.trashed("ann/philosophy")[0])


def test_the_trash_is_swept_after_thirty_days_and_not_before(data):
    root = data / "libraries/ann/philosophy"
    now = time.time()
    deletion.trash(root, root / CHAT, now=now)
    assert deletion.sweep(now + 29 * DAY) == [] and deletion.trashed("ann/philosophy")
    assert deletion.sweep(now + 31 * DAY) and deletion.trashed("ann/philosophy") == []
    assert not (data / "trash").exists() or not any((data / "trash").iterdir())


# --- people ------------------------------------------------------------------

def test_only_auths_own_token_deletes_a_person(client):
    for headers in (ANN, auth_tokens.bearer("ann"), _erase("bob", client="thefloor"),
                    _erase("bob", scopes=["noesis:keep"])):
        assert client.delete("/users/bob", headers=headers).status_code in (401, 403)
    assert not deletion.is_deleted("bob")
    assert client.delete("/users/bob", headers=_erase("bob")).status_code == 204
    # Again changes nothing, and somebody noesis never knew is answered the same.
    assert client.delete("/users/bob", headers=_erase("bob")).status_code == 204
    assert client.delete("/users/nobody", headers=_erase("nobody")).status_code == 204


def test_a_deleted_person_is_refused_at_once_and_swept_after_thirty_days(client, data):
    accounts.charge("bob", 0.25)
    bob = auth_tokens.bearer("bob")
    assert client.get("/libraries", headers=bob).json()["libraries"][0]["id"] == "bob/notes"
    client.delete("/users/bob", headers=_erase("bob"))
    assert client.get("/libraries", headers=bob).status_code == 401
    assert "bob/notes" not in [l["id"] for l in client.get("/libraries", headers={"Authorization": "Bearer ann-token"}).json()["libraries"]]
    assert (data / "deleted/bob/notes/x.md").read_text() == "bob's"
    (when,) = [at for user, at in deletion.deleted() if user == "bob"]
    assert deletion.sweep(when + 29 * DAY) == [] and deletion.is_deleted("bob")
    assert deletion.sweep(when + 31 * DAY) == ["user bob"]
    assert not (data / "deleted/bob").exists() and not deletion.is_deleted("bob")
    assert accounts.spent("bob") == 0


def test_a_deleted_person_is_restored_within_the_window(client, data):
    client.delete("/users/bob", headers=_erase("bob"))
    deletion.restore_user("bob")
    assert (data / "libraries/bob/notes/x.md").exists()
    assert client.get("/libraries", headers=auth_tokens.bearer("bob")).json()["libraries"][0]["id"] == "bob/notes"


def test_the_operators_users_are_kept_for_the_operator(data):
    deletion.delete_user("rod", now=0)
    assert deletion.sweep(31 * DAY) == ["kept rod: a users.toml token is the operator's, removed by hand"]
    assert deletion.is_deleted("rod")
