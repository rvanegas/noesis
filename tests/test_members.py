"""Libraries an application keeps for its groups (members.py): The Floor's
channels, `thefloor/<handle>`, which every member reaches and nobody else.

The application is answered by a script kept here — who belongs to which
library, and who pays — which is all of its behaviour noesis sees.
"""

import base64
import hashlib
import io
import json
import urllib.error

import pytest
from fastapi.testclient import TestClient

from noesis import accounts, members, server

LIB = "book-club-k3x9"
SECRET = "floor-secret"
FLOOR = {"Authorization": "Basic " + base64.b64encode(f"thefloor:{SECRET}".encode()).decode()}
ANN = {"Authorization": "Bearer ann-token"}
BOB = {"Authorization": "Bearer bob-token"}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("NOESIS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NOESIS_CONFIG_DIR", str(tmp_path / "config"))
    (tmp_path / "users.toml").write_text(
        f'[[tokens]]\nuser = "ann"\nsha256 = "{_sha(b"ann-token")}"\n'
        f'[[tokens]]\nuser = "bob"\nsha256 = "{_sha(b"bob-token")}"\n'
    )
    (tmp_path / "libraries" / "ann" / "notes").mkdir(parents=True)
    (tmp_path / "oauth.json").write_text(json.dumps({"clients": {
        "thefloor": {"client_id": "thefloor", "client_secret": SECRET,
                     "redirect_uris": ["https://floor.example/noesis/callback"]},
    }, "access": {}, "refresh": {}}))
    members._cache.clear()
    return tmp_path


@pytest.fixture
def floor(data, monkeypatch):
    """The Floor, marked as keeping libraries, and what it answers."""
    from scripts.client_libraries import main as mark
    assert mark(["thefloor", "https://floor.example"]) == 0
    groups = {LIB: {"handle": LIB, "name": "Book Club", "members": [
        {"user": "ann", "pro": False, "name": "Ann Example"}]}}
    asked: list[str] = []

    def get(keeper, path):
        asked.append(path)
        if path.startswith("/noesis/libraries/"):
            return groups.get(path.rsplit("/", 1)[1])
        user = path.split("/")[3]
        return {"libraries": [{"handle": h, "name": g["name"]} for h, g in groups.items()
                              if any(m["user"] == user for m in g["members"])]}
    monkeypatch.setattr(members, "_get", get)
    return groups, asked


@pytest.fixture
def client(data):
    return TestClient(server.app)


def _made(client) -> None:
    response = client.post("/libraries", json={"name": LIB}, headers=FLOOR)
    assert response.status_code == 201, response.text
    assert response.json() == {"library": f"thefloor/{LIB}"}


def test_marking_takes_the_name_and_refuses_a_person_s(data):
    from scripts.client_libraries import main as mark
    assert mark(["thefloor", "https://floor.example"]) == 0
    assert (data / "libraries" / "thefloor").is_dir()
    with accounts.connect() as db:
        assert accounts._taken(db, "thefloor")
    raw = json.loads((data / "oauth.json").read_text())["clients"]
    raw["ann"] = {"client_id": "ann", "client_secret": "x", "redirect_uris": []}
    (data / "oauth.json").write_text(json.dumps({"clients": raw, "access": {}, "refresh": {}}))
    with pytest.raises(SystemExit, match="somebody's name"):
        mark(["ann", "https://ann.example"])
    with pytest.raises(SystemExit, match="https"):
        mark(["thefloor", "http://floor.example"])


def test_the_application_makes_its_group_s_library(client, floor):
    _made(client)
    wrong = {"Authorization": "Basic " + base64.b64encode(b"thefloor:guess").decode()}
    assert client.post("/libraries", json={"name": "other"}, headers=wrong).status_code == 401


def test_a_member_reaches_it_and_nobody_else(client, floor):
    _made(client)
    assert client.get(f"/libraries/thefloor/{LIB}/files", headers=ANN).status_code == 200
    assert client.get(f"/libraries/thefloor/{LIB}/files", headers=BOB).status_code == 403
    assert client.get(f"/libraries/thefloor/{LIB}/files", headers=FLOOR).status_code == 200


def test_leaving_closes_it_at_the_next_asking(client, floor):
    groups, _ = floor
    _made(client)
    assert client.get(f"/libraries/thefloor/{LIB}/files", headers=ANN).status_code == 200
    groups[LIB]["members"] = []
    assert client.get(f"/libraries/thefloor/{LIB}/files", headers=ANN).status_code == 200  # within the minute
    members._cache.clear()
    assert client.get(f"/libraries/thefloor/{LIB}/files", headers=ANN).status_code == 403


def test_a_library_the_application_does_not_know_is_nobody_s(client, floor):
    _made(client)
    floor[0].clear()
    members._cache.clear()
    assert client.get(f"/libraries/thefloor/{LIB}/files", headers=ANN).status_code == 403


def test_a_member_lists_it_beside_their_own_by_the_group_s_name(client, floor):
    _made(client)
    assert client.get("/libraries", headers=ANN).json() == {
        "libraries": ["ann/notes", f"thefloor/{LIB}"], "names": {f"thefloor/{LIB}": "Book Club"}}
    assert client.get("/libraries", headers=BOB).json() == {"libraries": [], "names": {}}


def test_a_group_s_library_not_made_yet_is_not_listed(client, floor):
    assert client.get("/libraries", headers=ANN).json() == {"libraries": ["ann/notes"], "names": {}}


def test_an_application_that_does_not_answer_lists_nothing_and_admits_nobody(client, floor, monkeypatch):
    _made(client)

    def down(keeper, path):
        raise members.LibraryError(503, "thefloor did not answer")
    monkeypatch.setattr(members, "_get", down)
    members._cache.clear()
    assert client.get("/libraries", headers=ANN).json() == {"libraries": ["ann/notes"], "names": {}}
    assert client.get(f"/libraries/thefloor/{LIB}/files", headers=ANN).status_code == 503


def test_nobody_paying_refuses_what_would_spend(client, floor, data):
    groups, _ = floor
    _made(client)
    root = data / "libraries" / "thefloor" / LIB
    with pytest.raises(server.HTTPException) as refused:
        server._may_run(root, "index")
    assert refused.value.status_code == 402
    server._may_run(root, "check")                                   # costs nothing
    groups[LIB]["members"][0]["pro"] = True
    members._cache.clear()
    server._may_run(root, "index")


def test_spending_is_metered_per_library_and_read_by_the_application(client, floor, data):
    _made(client)
    root = data / "libraries" / "thefloor" / LIB
    assert server._metered(root) == f"thefloor/{LIB}"
    assert server._metered(data / "libraries" / "ann" / "notes") == "ann"
    accounts.charge(f"thefloor/{LIB}", 0.25)
    accounts.charge("ann", 1.0)
    month = accounts.month()
    assert client.get("/applications/spending", headers=FLOOR).json() == {
        "month": month, "libraries": {f"thefloor/{LIB}": 0.25}}
    assert client.get("/applications/spending", headers=ANN).status_code == 403


def test_every_member_s_lines_are_the_library_s_own_voice(client, floor):
    groups, _ = floor
    groups[LIB]["members"].append({"user": "bob", "pro": True, "name": "Bob, Jr."})
    groups[LIB]["members"].append({"user": "cy", "pro": False, "name": "Cy"})
    accounts.set_speaker_names("ann", ["Ann"])
    assert members.voices("thefloor", LIB) == ("Ann Example", "Ann", "Cy")    # a comma would split the list
    accounts.set_speaker_names("ann", [])
    assert members.voices("ann", "notes") == ()


def test_the_application_is_asked_with_its_own_pair(data, monkeypatch):
    from scripts.client_libraries import main as mark
    mark(["thefloor", "https://floor.example"])
    seen = {}

    def urlopen(request, timeout):
        seen["url"], seen["auth"] = request.full_url, request.headers["Authorization"]
        if request.full_url.endswith("/nothing"):
            raise urllib.error.HTTPError(request.full_url, 404, "no", {}, io.BytesIO(b""))
        return io.BytesIO(json.dumps({"name": "Book Club", "members": [{"user": "ANN", "pro": True}]}).encode())
    monkeypatch.setattr(members.urllib.request, "urlopen", urlopen)
    found = members.group("thefloor", LIB)
    assert seen == {"url": f"https://floor.example/noesis/libraries/{LIB}", "auth": FLOOR["Authorization"]}
    assert found.admits("ann") and found.funded and found.name == "Book Club"
    assert members.group("thefloor", "nothing") is None


def test_claude_is_handed_a_token_for_one_library_and_nothing_else(client, floor, data, monkeypatch):
    _made(client)
    assert client.post("/libraries", json={"name": "other-x2y3"}, headers=FLOOR).status_code == 201
    answer = client.post("/applications/token", json={"library": LIB}, headers=FLOOR)
    assert answer.status_code == 200 and answer.json()["expires_in"] == 3600
    token = answer.json()["access_token"]
    assert client.post("/applications/token", json={"library": "nothing"}, headers=FLOOR).status_code == 404
    assert client.post("/applications/token", json={"library": LIB}, headers=ANN).status_code == 403

    import asyncio
    from noesis import mcp_server
    from noesis.oauth import provider
    loaded = asyncio.run(provider.load_access_token(token))
    assert loaded is not None and loaded.subject == "thefloor"
    monkeypatch.setattr(mcp_server, "get_access_token", lambda: loaded)
    assert mcp_server._open_to(None) == [f"thefloor/{LIB}"]
    # Not the file and run API, which takes the web client's tokens alone.
    assert client.get(f"/libraries/thefloor/{LIB}/files",
                      headers={"Authorization": f"Bearer {token}"}).status_code == 401
