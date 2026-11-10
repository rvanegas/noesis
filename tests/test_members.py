"""Libraries an application keeps for its groups (members.py): The Floor's
channels, `thefloor/<handle>`, which every member reaches and nobody else.

The application is answered by a script kept here — who belongs to which
library, and who pays — which is all of its behaviour noesis sees.
"""

import hashlib
import io
import json
import urllib.error
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import auth_tokens
from noesis import accounts, members, server

LIB = "book-club-k3x9"
# The Floor's own token from auth (client_credentials).
FLOOR = auth_tokens.bearer("thefloor", scopes=["noesis:keep"], client="thefloor")
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
    auth_tokens.install(monkeypatch)
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
    assert members.keeper("thefloor").url == "https://floor.example"
    assert accounts.plan_of("thefloor") == accounts.UNLIMITED
    with pytest.raises(SystemExit, match="somebody's name"):
        mark(["ann", "https://ann.example"])
    with pytest.raises(SystemExit, match="https"):
        mark(["thefloor", "http://floor.example"])


def test_the_application_makes_its_group_s_library(client, floor):
    _made(client)
    for wrong in (auth_tokens.bearer("thefloor", scopes=["noesis:keep"], client="thefloor", key=auth_tokens.STRANGER),
                  auth_tokens.bearer("ann", scopes=["noesis:keep"], client="thefloor"),       # a person's
                  auth_tokens.bearer("other", scopes=["noesis:keep"], client="other")):       # not marked
        assert client.post("/libraries", json={"name": "other"}, headers=wrong).status_code == 401
    # Unmarked, it is nobody here.
    from scripts.client_libraries import main as mark
    mark(["thefloor", "--off"])
    assert client.post("/libraries", json={"name": "other"}, headers=FLOOR).status_code == 401


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


def test_a_group_without_a_name_is_shown_by_who_else_is_in_it(client, floor):
    groups, _ = floor
    _made(client)
    groups[LIB]["name"] = None
    names = lambda: client.get("/libraries", headers=ANN).json()["names"][f"thefloor/{LIB}"]
    assert names() is None  # nobody else
    groups[LIB]["members"] += [{"user": "bob", "pro": False, "name": "Bob B"}, {"user": "cy", "pro": False, "name": None}]
    members._cache.clear()
    assert names() == "With Bob B and cy"
    assert client.get("/libraries", headers=BOB).json()["names"] == {f"thefloor/{LIB}": "With Ann Example and cy"}


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


def test_each_member_is_their_own_voice_and_none_is_the_library_s(client, floor):
    from noesis.config import Speaker
    groups, _ = floor
    groups[LIB]["members"].append({"user": "bob", "pro": True, "name": "Bob, Jr."})
    groups[LIB]["members"].append({"user": "cy", "pro": False, "name": None})
    accounts.set_speaker_names("ann", ["Ann"])
    try:
        assert members.voices("thefloor", LIB) == ()
        assert members.speakers("thefloor", LIB) == (
            Speaker("ann", "Ann Example", ("Ann Example", "Ann")),
            Speaker("bob", "Bob, Jr.", ("Bob, Jr.",)),
            Speaker("cy", "cy", ("cy",)))                               # no display name: the user name
        assert members.voices("ann", "notes") == ("Ann",)
        assert members.speakers("ann", "notes") == ()
    finally:
        accounts.set_speaker_names("ann", [])


CHANNEL = ("\n# Lunch\n2026-10-30\n\n## Ann Example\n\nMine.\n\n## Bob\n\nHis.\n\n"
           "## Claude\n\nThe model's.\n\n## Dee\n\nA guest's.\n")


def test_whoever_reads_a_channel_s_chat_is_the_user_and_the_others_members(client, floor, monkeypatch):
    from noesis import mcp_server
    groups, _ = floor
    groups[LIB]["members"].append({"user": "bob", "pro": True, "name": "Bob"})
    root = Path("/srv/libraries/thefloor") / LIB

    def voiced(reader):
        return mcp_server._voiced(root, "2026-10-30-lunch.chat.md", CHANNEL, reader).split("\n", 1)[0]
    assert voiced("ann") == ("Voices: ## Ann Example is the user; ## Bob is another member of the channel, "
                             "speaking for themselves; ## Claude is a model; ## Dee is someone else.")
    assert voiced("bob") == ("Voices: ## Bob is the user; ## Ann Example is another member of the channel, "
                             "speaking for themselves; ## Claude is a model; ## Dee is someone else.")
    # The application's confined token, Claude's in the channel: nobody there is the user.
    assert voiced("thefloor") == ("Voices: no heading is the user; ## Ann Example, ## Bob are other members "
                                  "of the channel, each speaking for themselves; ## Claude is a model; "
                                  "## Dee is someone else.")
    monkeypatch.setattr(mcp_server, "_caller", lambda: "ann")
    monkeypatch.setattr(mcp_server, "_open_to", lambda ctx: [f"thefloor/{LIB}"])
    said = mcp_server.guide(None)
    assert "the sections headed ## Prompt, ## Ann Example are the user's own words" in said
    assert "the sections headed ## Bob are its other members'" in said
    assert "Claude's account of what each member thinks" in said


def test_the_application_is_asked_with_noesis_s_own_token(data, monkeypatch):
    from noesis import bearer
    from scripts.client_libraries import main as mark
    mark(["thefloor", "https://floor.example"])
    seen = {}
    monkeypatch.setattr(bearer, "own_token", lambda scope: seen.setdefault("scope", scope) and "noesis-own")

    def urlopen(request, timeout):
        seen["url"], seen["auth"] = request.full_url, request.headers["Authorization"]
        if request.full_url.endswith("/nothing"):
            raise urllib.error.HTTPError(request.full_url, 404, "no", {}, io.BytesIO(b""))
        return io.BytesIO(json.dumps({"name": "Book Club", "members": [{"user": "ANN", "pro": True}]}).encode())
    monkeypatch.setattr(members.urllib.request, "urlopen", urlopen)
    found = members.group("thefloor", LIB)
    assert seen == {"url": f"https://floor.example/noesis/libraries/{LIB}", "auth": "Bearer noesis-own",
                    "scope": "thefloor:members"}
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

    from noesis import bearer, mcp_server
    loaded = bearer.access_token(token)
    assert loaded is not None and loaded.subject == "thefloor"
    monkeypatch.setattr(mcp_server, "get_access_token", lambda: loaded)
    assert mcp_server._open_to(None) == [f"thefloor/{LIB}"]
    # Not the file and run API, which takes the web client's tokens alone.
    assert client.get(f"/libraries/thefloor/{LIB}/files",
                      headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_the_application_deletes_its_library_and_nobody_else_does(client, floor, data):
    _made(client)
    assert client.delete(f"/libraries/thefloor/{LIB}", headers=ANN).status_code == 403
    assert client.delete("/libraries/ann/notes", headers=ANN).status_code == 403
    assert client.delete(f"/libraries/thefloor/{LIB}", headers=FLOOR).status_code == 204
    assert not (data / "libraries" / "thefloor" / LIB).exists()
    assert client.delete(f"/libraries/thefloor/{LIB}", headers=FLOOR).status_code == 404


def test_a_person_s_display_name_is_auth_s_else_their_user_name(data, monkeypatch):
    from noesis import bearer
    monkeypatch.setattr(bearer, "own_token", lambda scope: "noesis-own")
    seen = []

    def urlopen(request, timeout):
        seen.append((request.full_url, request.headers["Authorization"]))
        user = request.full_url.rsplit("=", 1)[1]
        return io.BytesIO(json.dumps({"names": {user: "Ann Example" if user == "ann" else None}}).encode())
    monkeypatch.setattr(members.urllib.request, "urlopen", urlopen)
    assert members.display_name("ann") == "Ann Example"
    assert members.display_name("bob") == "bob"
    assert seen[0] == (f"{bearer.auth_url()}/names/display?user=ann", "Bearer noesis-own")
    members._cache.clear()

    def down(request, timeout):
        raise urllib.error.URLError("no")
    monkeypatch.setattr(members.urllib.request, "urlopen", down)
    assert members.display_name("ann") == "ann"                  # auth away: the user name


def _copied(response) -> dict:
    events = [block for block in response.text.strip().split("\n\n")]
    done = json.loads(events[-1].split("data: ", 1)[1])
    assert events[-1].startswith("event: done") and done["exit_code"] == 0, response.text
    return done


@pytest.fixture
def filed(client, floor, data, monkeypatch):
    """A transcript in the channel's library, as The Floor files it, and the run's environment."""
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).resolve().parent.parent))
    monkeypatch.setenv("NOESIS_CACHE_DIR", str(data / "cache"))
    groups, _ = floor
    groups[LIB]["members"][0]["pro"] = True
    groups[LIB]["members"].append({"user": "bob", "pro": True, "name": "Bob"})
    _made(client)
    (data / "libraries/thefloor" / LIB / "2026").mkdir()
    (data / "libraries/thefloor" / LIB / "2026/2026-10-30-lunch.chat.md").write_text(CHANNEL)
    yield f"/libraries/thefloor/{LIB}/copy"
    accounts.set_speaker_names("ann", [])
    accounts.set_speaker_names("bob", [])


def test_a_member_copies_a_channel_s_chat_and_its_lines_become_theirs(client, filed, data):
    response = client.post(filed, headers=ANN, json={"file": "2026/2026-10-30-lunch.chat.md", "to": "notes"})
    assert list(_copied(response)["changed"]) == ["2026/2026-10-30-lunch.chat.md"]
    assert "Mine." in (data / "libraries/ann/notes/2026/2026-10-30-lunch.chat.md").read_text()
    # The name The Floor gives her is now one of hers, so her library reads her lines as hers.
    assert accounts.speaker_names("ann") == ("Ann Example",)
    assert members.voices("ann", "notes") == ("Ann Example",)


def test_a_copier_none_of_whose_names_is_in_the_chat_is_asked(client, filed, data, floor):
    groups, _ = floor
    groups[LIB]["members"][0]["name"] = "Ann"                         # renamed since
    members._cache.clear()
    body = {"file": "2026/2026-10-30-lunch.chat.md", "to": "notes"}
    asked = client.post(filed, headers=ANN, json=body)
    assert asked.status_code == 409
    assert asked.json()["detail"]["speakers"] == ["Ann Example", "Bob", "Dee"]
    assert not (data / "libraries/ann/notes/2026").exists()
    # Somebody else's heading is never taken because it is close; only what the chat holds.
    assert client.post(filed, headers=ANN, json={**body, "names": ["Annie"]}).status_code == 400
    _copied(client.post(filed, headers=ANN, json={**body, "names": ["Ann Example"]}))
    assert accounts.speaker_names("ann") == ("Ann Example",)


def test_a_copier_who_was_not_in_it_says_so_and_takes_no_name(client, filed, data, floor):
    groups, _ = floor
    groups[LIB]["members"][0]["name"] = "Ann"
    members._cache.clear()
    body = {"file": "2026/2026-10-30-lunch.chat.md", "to": "notes", "names": []}
    _copied(client.post(filed, headers=ANN, json=body))
    assert accounts.speaker_names("ann") == ()


def test_a_copy_goes_only_into_the_copier_s_own_library(client, filed, data):
    body = {"file": "2026/2026-10-30-lunch.chat.md"}
    assert client.post(filed, headers=ANN, json={**body, "to": "missing"}).status_code == 404
    assert client.post(filed, headers=BOB, json={**body, "to": "notes"}).status_code == 404   # bob has none
    assert client.post(filed, headers=FLOOR, json={**body, "to": LIB}).status_code == 400    # the application
    assert client.post(filed, headers=ANN, json={"file": "KEYS.md", "to": "notes"}).status_code == 400
    assert client.post(filed, headers=ANN, json={"file": "2026/nope.chat.md", "to": "notes"}).status_code == 404
    assert client.post("/libraries/ann/notes/copy", headers=BOB,
                       json={"file": "x.chat.md", "to": "notes"}).status_code == 403


def test_a_member_who_does_not_pay_reads_and_nothing_more(client, filed, data, floor):
    groups, _ = floor
    groups[LIB]["members"][0]["pro"] = False
    members._cache.clear()
    base = f"/libraries/thefloor/{LIB}"
    rel = "2026/2026-10-30-lunch.chat.md"
    assert client.get(f"{base}/files", headers=ANN).status_code == 200
    assert client.get(f"{base}/files/{rel}", headers=ANN).status_code == 200
    assert client.post(filed, headers=ANN, json={"file": rel, "to": "notes"}).status_code == 403
    assert client.put(f"{base}/files/2026/x.document.md", headers={**ANN, "If-None-Match": "*"},
                      content=b"x").status_code == 403
    sha = _sha((data / "libraries/thefloor" / LIB / rel).read_bytes())
    assert client.delete(f"{base}/files/{rel}", headers={**ANN, "If-Match": f'"{sha}"'}).status_code == 403
    assert client.post(f"{base}/run", headers=ANN, json={"argv": ["check", "lunch"]}).status_code == 403
    assert client.post(f"{base}/import", headers=ANN, params={"filename": "x.md"}, content=b"x").status_code == 403
    # Bob pays: more than reading is his.
    assert client.put(f"{base}/files/2026/x.document.md", headers={**BOB, "If-None-Match": "*"},
                      content=b"x").status_code == 200
