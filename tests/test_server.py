import hashlib
import json
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from noesis import server

REPO = Path(__file__).resolve().parent.parent
CHAT = "\n# Old Roman\n2025-04-25\n\n## Prompt\n\nHello.\n\n## Claude\n\nHi.\n"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("NOESIS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NOESIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("NOESIS_CACHE_DIR", str(tmp_path / "cache"))
    # The run's subprocess imports this checkout's noesis.
    monkeypatch.setenv("PYTHONPATH", str(REPO))
    (tmp_path / "users.toml").write_text(
        f'[[tokens]]\nuser = "ann"\nsha256 = "{_sha(b"ann-token")}"\n'
        f'[[tokens]]\nuser = "bob"\nsha256 = "{_sha(b"bob-token")}"\n'
        f'[[tokens]]\nuser = "*"\nsha256 = "{_sha(b"service-token")}"\n'
    )
    lib = tmp_path / "libraries" / "ann" / "philosophy"
    (lib / "2025").mkdir(parents=True)
    (lib / "2025" / "2025-04-25-old-roman.chat.md").write_text(CHAT)
    (lib / ".noesis").mkdir()
    (lib / ".noesis" / "manifest.json").write_text("{}")
    (tmp_path / "libraries" / "bob" / "notes").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def client(data):
    return TestClient(server.app)


ANN = {"Authorization": "Bearer ann-token"}
BASE = "/libraries/ann/philosophy"


def _events(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def test_healthz_in_a_checkout_says_dev(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_DEPLOYED", tmp_path / "deployed.json")
    response = TestClient(server.app).get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "commit": "dev"}


def test_healthz_reports_the_deployed_commit(tmp_path, monkeypatch):
    stamp = tmp_path / "deployed.json"
    stamp.write_text(json.dumps({"commit": "abc1234", "branch": "master", "deployedAt": "2026-10-25T00:00:00Z"}))
    monkeypatch.setattr(server, "_DEPLOYED", stamp)
    body = TestClient(server.app).get("/healthz").json()
    assert body["commit"] == "abc1234"


def test_a_token_is_required(client):
    assert client.get("/libraries").status_code == 401
    assert client.get("/libraries", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get(f"{BASE}/files").status_code == 401


def test_each_user_sees_their_own_libraries(client):
    ids = lambda headers: [l["id"] for l in client.get("/libraries", headers=headers).json()["libraries"]]
    assert ids(ANN) == ["ann/philosophy"]
    service = {"Authorization": "Bearer service-token"}
    assert ids(service) == ["ann/philosophy", "bob/notes"]
    assert client.get(f"{BASE}/files", headers={"Authorization": "Bearer bob-token"}).status_code == 403
    assert client.get(f"{BASE}/files", headers=service).status_code == 200


def test_a_library_is_listed_with_its_owner_and_how_many_documents_it_holds(client, data):
    lib = data / "libraries/ann/philosophy"
    (lib / "2025" / "2025-04-26-a-thought.document.md").write_text("x")
    (lib / "2025" / "2025-04-26-a-thought.source.md").write_text("x")  # not a document
    (lib / "REVISIONS").mkdir()
    (lib / "REVISIONS" / "2025-04-26-a-thought.document.md").write_text("x")  # a record
    assert client.get("/libraries", headers=ANN).json() == {"libraries": [
        {"id": "ann/philosophy", "name": None, "users": ["ann"], "documents": 2}]}


def test_a_user_creates_a_library_of_their_own(client, data):
    response = client.post("/libraries", headers=ANN, json={"name": "drafts"})
    assert response.status_code == 201
    assert response.json() == {"library": "ann/drafts"}
    assert (data / "libraries/ann/drafts").is_dir()
    assert [l["id"] for l in client.get("/libraries", headers=ANN).json()["libraries"]] == ["ann/drafts", "ann/philosophy"]
    files = client.get("/libraries/ann/drafts/files", headers=ANN).json()["files"]
    assert sorted(files) == ["KEYS.md", "SYSTEM_PROMPT.md"]
    assert (data / "libraries/ann/drafts/KEYS.md").read_text().startswith("## Plural\n")
    assert (data / "libraries/ann/drafts/SYSTEM_PROMPT.md").read_text() == ""


def test_a_library_is_made_from_a_name_its_id_the_name_s_slug(client, data):
    response = client.post("/libraries", headers=ANN, json={"name": "  Ética  de   Spinoza "})
    assert response.json() == {"library": "ann/etica-de-spinoza"}
    listed = {l["id"]: l["name"] for l in client.get("/libraries", headers=ANN).json()["libraries"]}
    assert listed["ann/etica-de-spinoza"] == "Ética de Spinoza"
    # The name is the library's, not a file of it.
    assert ".noesis/library.json" not in client.get("/libraries/ann/etica-de-spinoza/files", headers=ANN).json()["files"]
    # A path is only a name: its slug stays inside the user's libraries.
    assert client.post("/libraries", headers=ANN, json={"name": "../bob"}).json() == {"library": "ann/bob"}


def test_a_new_library_needs_a_fresh_valid_name_and_a_user(client):
    assert client.post("/libraries", headers=ANN, json={"name": "Philosophy"}).status_code == 409
    for name in ["", "  ", "—", "../"]:
        assert client.post("/libraries", headers=ANN, json={"name": name}).status_code == 400
    service = {"Authorization": "Bearer service-token"}
    assert client.post("/libraries", headers=service, json={"name": "drafts"}).status_code == 400
    assert client.post("/libraries", json={"name": "drafts"}).status_code == 401


def test_listing_hides_dotfiles(client):
    files = client.get(f"{BASE}/files", headers=ANN).json()["files"]
    assert files == {"2025/2025-04-25-old-roman.chat.md": _sha(CHAT.encode())}


@pytest.mark.parametrize("rel", ["../../bob/notes/x.md", ".noesis/manifest.json", "2025/.hidden", "%2e%2e/x"])
def test_paths_stay_inside_and_visible(client, rel):
    assert client.get(f"{BASE}/files/{rel}", headers=ANN).status_code in (400, 404)
    assert client.put(f"{BASE}/files/{rel}", headers={**ANN, "If-None-Match": "*"}, content=b"x").status_code in (400, 404)


def test_symlinks_are_refused(client, data):
    (data / "libraries/ann/philosophy/link").symlink_to(data / "users.toml")
    assert client.get(f"{BASE}/files/link", headers=ANN).status_code == 400


def test_read_write_delete_with_preconditions(client):
    rel = f"{BASE}/files/2026/2026-01-02-new.document.md"
    assert client.put(rel, headers=ANN, content=b"one").status_code == 428
    created = client.put(rel, headers={**ANN, "If-None-Match": "*"}, content=b"one")
    assert created.status_code == 200 and created.headers["ETag"] == f'"{_sha(b"one")}"'
    assert client.put(rel, headers={**ANN, "If-None-Match": "*"}, content=b"again").status_code == 412
    got = client.get(rel, headers=ANN)
    assert got.content == b"one" and got.headers["ETag"] == f'"{_sha(b"one")}"'
    assert client.put(rel, headers={**ANN, "If-Match": '"stale"'}, content=b"two").status_code == 412
    assert client.put(rel, headers={**ANN, "If-Match": f'"{_sha(b"one")}"'}, content=b"two").status_code == 200
    assert client.delete(rel, headers=ANN).status_code == 428
    assert client.delete(rel, headers={**ANN, "If-Match": f'"{_sha(b"one")}"'}).status_code == 412
    assert client.delete(rel, headers={**ANN, "If-Match": f'"{_sha(b"two")}"'}).status_code == 204
    assert client.get(rel, headers=ANN).status_code == 404


def test_read_says_when_the_file_was_last_modified(client, data):
    path = data / "libraries/ann/philosophy/notes.md"
    path.write_text("x")
    os.utime(path, (1_700_000_000, 1_700_000_000))
    got = client.get(f"{BASE}/files/notes.md", headers=ANN)
    assert got.headers["Last-Modified"] == "Tue, 14 Nov 2023 22:13:20 GMT"
    assert got.headers["Cache-Control"] == "no-cache"
    head = client.head(f"{BASE}/files/notes.md", headers=ANN)
    assert head.status_code == 200 and head.content == b""
    assert {k: head.headers[k] for k in ("ETag", "Last-Modified", "Content-Length")} == {
        "ETag": f'"{_sha(b"x")}"', "Last-Modified": got.headers["Last-Modified"], "Content-Length": "1"}
    assert client.head(f"{BASE}/files/missing.md", headers=ANN).status_code == 404


def test_run_streams_and_reports_changes(client, data, monkeypatch, tmp_path):
    # An editor that leaves a mark if it is ever started: a run never starts one.
    opened = tmp_path / "opened"
    editor = tmp_path / "editor"
    editor.write_text(f"#!/bin/sh\ntouch {opened}\n")
    editor.chmod(0o755)
    monkeypatch.setenv("EDITOR", str(editor))
    monkeypatch.setenv("NOESIS_EDITOR", str(editor))
    response = client.post(f"{BASE}/run", headers=ANN, json={"argv": ["new", "Fresh", "Start"]})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _events(response.text)
    assert events[-1][0] == "done"
    done = events[-1][1]
    assert done["exit_code"] == 0
    assert [rel.split("/")[-1].split("-", 3)[-1] for rel in done["changed"]] == ["fresh-start.chat.md"]
    assert "fresh-start.chat.md" in "".join(e[1]["text"] for e in events if e[0] == "output")
    assert not opened.exists()


def test_run_resolves_names_across_the_library(client):
    events = _events(client.post(f"{BASE}/run", headers=ANN, json={"argv": ["check", "old-roman"]}).text)
    assert events[-1][1]["exit_code"] == 0
    assert "OK: transcript is valid" in "".join(e[1]["text"] for e in events if e[0] == "output")


@pytest.mark.parametrize("argv", [["edit", "x"], ["config"], ["serve"], ["--lib", "/", "check", "x"],
                                  ["check", "--lib=/", "x"], ["reply", "-W", "x"], []])
def test_run_refuses(client, argv):
    assert client.post(f"{BASE}/run", headers=ANN, json={"argv": argv}).status_code in (400, 422)


@pytest.mark.parametrize("names, status", [(["Mary Ann"], 200), (["Ann,Bo"], 400), (["Ann\nBo"], 400)])
def test_a_user_name_may_have_spaces_not_commas(client, names, status):
    assert client.put("/me/names", headers=ANN, json={"names": names}).status_code == status


def test_names_are_kept_with_the_user(client):
    assert client.get("/me", headers=ANN).json()["names"] == []
    saved = client.put("/me/names", headers=ANN, json={"names": [" Ann ", "Prompt", "Ann", "Mary Ann"]})
    assert saved.json() == {"names": ["Ann", "Mary Ann"]}
    assert client.get("/me", headers=ANN).json()["names"] == ["Ann", "Mary Ann"]
    assert client.get("/me", headers={"Authorization": "Bearer bob-token"}).json()["names"] == []
    service = {"Authorization": "Bearer service-token"}
    assert client.put("/me/names", headers=service, json={"names": ["X"]}).status_code == 400


def test_a_run_knows_the_owners_names_whoever_starts_it(client, monkeypatch):
    import asyncio
    envs = []
    spawn = asyncio.create_subprocess_exec

    async def spy(*args, env, **kwargs):
        envs.append(env)
        return await spawn(*args, env=env, **kwargs)

    monkeypatch.setattr(server.asyncio, "create_subprocess_exec", spy)
    from noesis import members
    monkeypatch.setattr(members, "display_name", lambda user: {"ann": "Ann Example"}.get(user, user))
    client.put("/me/names", headers=ANN, json={"names": ["Ann", "Mary Ann"]})
    for who in (ANN, {"Authorization": "Bearer service-token"}):
        client.post(f"{BASE}/run", headers=who, json={"argv": ["check", "old-roman"]})
    assert [e["NOESIS_USER_NAMES"] for e in envs] == ["Ann,Mary Ann", "Ann,Mary Ann"]
    assert [e["NOESIS_MEMBERS"] for e in envs] == ["[]", "[]"]              # a person's library has none
    # Its owner instead, by the display name auth keeps, whose stances an argument records.
    assert [json.loads(e["NOESIS_OWNER"]) for e in envs] == [{"user": "ann", "name": "Ann Example"}] * 2
    # Who started it, though, is a person's name or none (cmd_export.py).
    assert [e.get("NOESIS_CALLER") for e in envs] == ["ann", None]


def test_one_run_at_a_time_and_no_writes_meanwhile(client, data):
    import asyncio
    from noesis import service
    lock = service.lock_for(data / "libraries/ann/philosophy")
    asyncio.run(lock.acquire())
    try:
        assert client.post(f"{BASE}/run", headers=ANN, json={"argv": ["check", "old-roman"]}).status_code == 409
        assert client.put(f"{BASE}/files/2026/x.document.md", headers={**ANN, "If-None-Match": "*"}, content=b"x").status_code == 409
    finally:
        lock.release()
        service.locks.clear()


def test_import_writes_into_the_library_and_keeps_nothing_else(client, data):
    import tempfile
    staged = set(Path(tempfile.gettempdir()).glob("noesis-import-*"))
    body = b"# Notes on Quine\n\nTwo dogmas, one paragraph.\n"
    response = client.post(f"{BASE}/import", headers=ANN, params={"filename": "notes-on-quine.md"}, content=body)
    events = _events(response.text)
    assert events[-1][0] == "done" and events[-1][1]["exit_code"] == 0
    changed = list(events[-1][1]["changed"])
    assert len(changed) == 1 and changed[0].endswith("-notes-on-quine.document.md")
    assert events[-1][1]["titles"] == {changed[0]: "Notes on Quine"}
    assert "Two dogmas" in (data / "libraries/ann/philosophy" / changed[0]).read_text()
    assert set(Path(tempfile.gettempdir()).glob("noesis-import-*")) == staged


def test_import_as_a_chats_document(client, data):
    lib = data / "libraries/ann/philosophy"
    (lib / "2026").mkdir(exist_ok=True)
    (lib / "2026/2026-05-01-on-names.chat.md").write_text(
        "\n# On Names\n2026-05-01\n\n## Prompt\n\nWhat is a name?\n\n## Claude\n\nA rigid designator.\n")
    response = client.post(f"{BASE}/import", headers=ANN, content=b"Names designate rigidly.\n",
                           params={"filename": "draft.md", "document_of": "2026/2026-05-01-on-names.chat.md"})
    events = _events(response.text)
    assert events[-1][0] == "done" and events[-1][1]["exit_code"] == 0
    assert list(events[-1][1]["changed"]) == ["2026/2026-05-01-on-names.document.md"]


@pytest.mark.parametrize("chat", ["../x.chat.md", "/etc/x.chat.md", "2026/missing.chat.md", "2026/x.document.md"])
def test_import_as_a_document_needs_a_chat_here(client, chat):
    response = client.post(f"{BASE}/import", headers=ANN, content=b"x",
                           params={"filename": "draft.md", "document_of": chat})
    assert response.status_code == 404


@pytest.mark.parametrize("filename", ["../x.md", "a/b.md", ".hidden", " "])
def test_import_takes_a_name_not_a_path(client, filename):
    assert client.post(f"{BASE}/import", headers=ANN, params={"filename": filename}, content=b"x").status_code == 400


def test_import_takes_only_text_and_claude_exports(client):
    for filename in ["paper.pdf", "photo.png", "notes.rtf"]:
        response = client.post(f"{BASE}/import", headers=ANN, params={"filename": filename}, content=b"x")
        assert response.status_code == 415


def test_import_is_a_run(client, data):
    import asyncio
    from noesis import service
    lock = service.lock_for(data / "libraries/ann/philosophy")
    asyncio.run(lock.acquire())
    try:
        assert client.post(f"{BASE}/import", headers=ANN, params={"filename": "x.md"}, content=b"x").status_code == 409
    finally:
        lock.release()
        service.locks.clear()
    assert client.post("/libraries/ann/philosophy/import", params={"filename": "x.md"}, content=b"x").status_code == 401


def test_the_bare_name_leads_to_the_web_client(data):
    # With the app's lifespan, so the MCP app mounted at the root is up, and
    # still answers its own paths beside the redirect.
    with TestClient(server.app) as client:
        response = client.get("/", follow_redirects=False)
        assert response.status_code == 302 and response.headers["location"] == "/web/"
        assert client.get("/.well-known/oauth-protected-resource/mcp").status_code == 200
        assert client.get("/mcp").status_code == 401


def test_the_web_client_is_served_with_its_policy(client):
    assert client.get("/web", follow_redirects=False).headers["location"] == "/web/"
    page = client.get("/web/")
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    assert "default-src 'self'" in page.headers["content-security-policy"]
    assert '<script src="app.js"' in page.text
    # It signs in at auth: the page names it, and the policy lets it call auth alone besides noesis.
    from noesis.bearer import auth_url
    assert f'<meta name="auth" content="{auth_url()}">' in page.text and "{{auth}}" not in page.text
    # And names Roxana, where an argument already sent opens its discussion.
    assert '<meta name="roxana" content="' in page.text and "{{roxana}}" not in page.text
    assert f"connect-src 'self' {auth_url()}" in page.headers["content-security-policy"]
    assert client.get("/web/app.js").headers["content-type"].startswith("text/javascript")
    assert client.get("/web/style.css").status_code == 200
    for missing in ("/web/nothing.js", "/web/..%2Fserver.py", "/web/README.md"):
        assert client.get(missing).status_code == 404


def test_add_token(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("add_token", REPO / "scripts" / "add_token.py")
    add_token = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(add_token)
    users = tmp_path / "users.toml"
    import contextlib, io
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        add_token.main(["ann", "--note", "Mac CLI", "--users", str(users)])
    token = out.getvalue().strip()
    import tomllib
    entry = tomllib.loads(users.read_text())["tokens"][0]
    assert entry == {"user": "ann", "sha256": _sha(token.encode()), "note": "Mac CLI"}
    assert users.stat().st_mode & 0o777 == 0o600


def test_the_web_client_names_the_roxana_the_server_is_configured_with(client, monkeypatch, tmp_path):
    import noesis.config
    config = tmp_path / "roxana.toml"
    config.write_text('roxana_web_url = "https://roxana.example"\n')
    monkeypatch.setattr(noesis.config, "DEFAULT_CONFIG_PATH", config)
    assert '<meta name="roxana" content="https://roxana.example">' in client.get("/web/").text
