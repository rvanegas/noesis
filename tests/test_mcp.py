"""The MCP server at /mcp (SERVER.md, Phase 5), driven by the SDK's own client
over HTTP, as Claude Code or a claude.ai connector would."""

import asyncio
import hashlib
import json
import socket
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn

import auth_tokens


CHAT = "\n# Old Roman\n2025-04-25\n\n## Prompt\n\nHello.\n\n## Claude\n\nHi.\n\n## Related\n\n| *Essay*\n"
DOC = "\n# Essay\n2026-10-27\n\nProse here.\n"



@pytest.fixture(scope="module")
def live(tmp_path_factory):
    data = tmp_path_factory.mktemp("data")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    mp = pytest.MonkeyPatch()
    mp.setenv("NOESIS_DATA_DIR", str(data))
    mp.setenv("NOESIS_CONFIG_DIR", str(data / "config"))
    mp.setenv("NOESIS_PUBLIC_URL", f"http://127.0.0.1:{port}")
    auth_tokens.install(mp)
    (data / "users.toml").write_text(
        f'[[tokens]]\nuser = "ann"\nsha256 = "{hashlib.sha256(b"ann").hexdigest()}"\n'
        f'[[tokens]]\nuser = "bob"\nsha256 = "{hashlib.sha256(b"bob").hexdigest()}"\n'
    )
    from noesis import server
    uv = uvicorn.Server(uvicorn.Config(server.app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=uv.run, daemon=True)
    thread.start()
    while not uv.started:
        time.sleep(0.05)
    yield data, f"http://127.0.0.1:{port}"
    uv.should_exit = True
    thread.join(5)
    mp.undo()


@pytest.fixture
def library(live):
    data, url = live
    root = data / "libraries" / "ann" / "philosophy"
    import shutil
    shutil.rmtree(root, ignore_errors=True)
    (root / "2025").mkdir(parents=True)
    (root / "2026").mkdir()
    (root / "2025" / "2025-04-25-old-roman.chat.md").write_text(CHAT)
    (root / "2026" / "2026-10-27-essay.document.md").write_text(DOC)
    (root / "2026" / "2026-10-19-parfit2011.source.md").write_text("\n# Parfit\n2026-10-19\n\nNot yours to edit.\n")
    (root / ".noesis").mkdir()
    (root / ".noesis" / "manifest.json").write_text(json.dumps({"entries": [
        {"rel_path": "2026/2026-10-27-essay.document.md", "title": "Essay", "word_count": 2,
         "summary": "On prose.", "terms": ["prose"], "refs": [], "related": []},
    ]}))
    (root / ".noesis" / "index.json").write_text(json.dumps({"terms": {
        "prose": [{"rel_path": "2026/2026-10-27-essay.document.md", "title": "Essay"}]}}))
    (data / "libraries" / "bob" / "notes").mkdir(parents=True, exist_ok=True)
    return root, url


def call(url, token, tool, args, path="/mcp"):
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from mcp.shared._httpx_utils import create_mcp_http_client

    async def go():
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        async with create_mcp_http_client(headers=headers) as http:
            async with streamable_http_client(f"{url}{path}", http_client=http) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    if tool is None:
                        return await session.list_tools()
                    return await session.call_tool(tool, args)

    return asyncio.run(go())


def text(result) -> str:
    return "\n".join(c.text for c in result.content)


def test_tools_and_auth(library):
    root, url = library
    tools = {t.name: t.description for t in call(url, "ann", None, None).tools}
    assert list(tools) == ["guide", "list_documents", "lookup_term", "read_file"]
    # claude.ai shows the model tool descriptions, not server instructions:
    # the guidance travels in guide, and the essentials in the descriptions.
    assert "<date>-<slug>.<role>.<ext>" in text(call(url, "ann", "guide", {}))
    assert "Read a document in full if you read it at all" in text(call(url, "ann", "guide", {}))
    assert "<date>-<slug>.<role>.<ext>" in tools["list_documents"]
    assert "| *Exact Title*" in tools["read_file"] and "'Voices:'" in tools["read_file"]
    assert httpx.post(f"{url}/mcp", json={}).status_code == 401
    assert httpx.post(f"{url}/mcp", json={}, headers={"Authorization": "Bearer nope"}).status_code == 401


def test_reading(library):
    root, url = library
    assert "2026-10-27-essay.document.md — Essay" in text(call(url, "ann", "list_documents", {}))
    assert "Essay" in text(call(url, "ann", "list_documents", {"query": "prose"}))
    assert "Essay" in text(call(url, "ann", "lookup_term", {"term": "prose"}))
    assert "Prose here." in text(call(url, "ann", "read_file", {"name": "2026-10-27-essay.document.md"}))
    assert "Prose here." in text(call(url, "ann", "read_file", {"name": "2026/2026-10-27-essay.document.md"}))
    assert "Prose here." in text(call(url, "ann", "read_file", {"name": "Essay"}))
    bad = call(url, "ann", "read_file", {"name": "../users.toml"})
    assert bad.is_error


def test_nothing_writes(library):
    # claude.ai edits with its own documents, and a conversation reaches the
    # library by its export and noesis import: edit_file is noesis reply's alone,
    # and append_turn is gone.
    root, url = library
    for tool, args in (
        ("edit_file", {"name": "2026-10-27-essay.document.md", "old_str": "Prose here.", "new_str": "Edited."}),
        ("append_turn", {"name": "2025-04-25-old-roman.chat.md", "speaker": "Prompt", "text": "Hi."}),
    ):
        assert call(url, "ann", tool, args).is_error
        assert tool not in text(call(url, "ann", "guide", {}))
    assert (root / "2026" / "2026-10-27-essay.document.md").read_text() == DOC
    assert (root / "2025" / "2025-04-25-old-roman.chat.md").read_text() == CHAT


def test_another_users_library_is_out_of_reach(library):
    root, url = library
    result = call(url, "bob", "read_file", {"name": "2026-10-27-essay.document.md", "library": "ann/philosophy"})
    assert result.is_error and "not a library open to this conversation" in text(result)


@pytest.fixture
def two_libraries(library):
    """ann keeps a second library, with an essay of its own."""
    root, url = library
    import shutil
    notes = root.parent / "notes"
    shutil.rmtree(notes, ignore_errors=True)
    (notes / "2026").mkdir(parents=True)
    (notes / "2026" / "2026-10-30-fragment.document.md").write_text("\n# Fragment\n2026-10-30\n\nOn prose, briefly.\n")
    (notes / ".noesis").mkdir()
    (notes / ".noesis" / "manifest.json").write_text(json.dumps({"entries": [
        {"rel_path": "2026/2026-10-30-fragment.document.md", "title": "Fragment", "word_count": 3,
         "summary": "Prose, briefly.", "terms": ["prose"], "refs": [], "related": []},
    ]}))
    (notes / ".noesis" / "index.json").write_text(json.dumps({"terms": {
        "prose": [{"rel_path": "2026/2026-10-30-fragment.document.md", "title": "Fragment"}]}}))
    yield root, url
    shutil.rmtree(notes, ignore_errors=True)


def test_a_connector_without_a_selection_asks_which_library(two_libraries):
    root, url = two_libraries
    guide = text(call(url, "ann", "guide", {}))
    assert "several libraries: ann/notes, ann/philosophy" in guide and "ask which" in guide
    searched = call(url, "ann", "lookup_term", {"term": "prose"})
    assert searched.is_error and "ask them which" in text(searched)
    named = text(call(url, "ann", "lookup_term", {"term": "prose", "library": "ann/notes"}))
    assert "Fragment" in named and "Essay" not in named


def test_an_address_naming_libraries_opens_those_and_searches_them_all(two_libraries):
    root, url = two_libraries
    both = "/mcp?libraries=ann/philosophy,ann/notes"
    found = text(call(url, "ann", "lookup_term", {"term": "prose"}, path=both))
    assert "# Library ann/notes" in found and "# Library ann/philosophy" in found
    listed = text(call(url, "ann", "list_documents", {}, path=both))
    assert "[ann/notes]" in listed and "[ann/philosophy]" in listed
    assert "may read these libraries: ann/notes, ann/philosophy" in text(call(url, "ann", "guide", {}, path=both))
    unnamed = call(url, "ann", "read_file", {"name": "2026-10-27-essay.document.md"}, path=both)
    assert unnamed.is_error and "name the library" in text(unnamed)
    assert "Prose here." in text(call(url, "ann", "read_file", {
        "name": "2026-10-27-essay.document.md", "library": "ann/philosophy"}, path=both))

    one = "/mcp?libraries=ann/notes"
    assert "Fragment" in text(call(url, "ann", "lookup_term", {"term": "prose"}, path=one))
    shut = call(url, "ann", "read_file", {"name": "2026-10-27-essay.document.md", "library": "ann/philosophy"}, path=one)
    assert shut.is_error and "not a library open to this conversation" in text(shut)
    # Somebody else's library named in the address opens nothing.
    none = call(url, "bob", "lookup_term", {"term": "prose"}, path="/mcp?libraries=ann/philosophy")
    assert none.is_error and "no library is open" in text(none)


def test_noesis_names_auth_as_its_authorization_server(library, live):
    data, url = live
    found = httpx.get(f"{url}/.well-known/oauth-protected-resource/mcp").json()
    assert [a.rstrip("/") for a in found["authorization_servers"]] == [auth_tokens.AUTH]
    assert found["resource"].rstrip("/") == f"{url}/mcp"
    # Nothing of an authorization server is left here.
    assert httpx.get(f"{url}/.well-known/oauth-authorization-server").status_code == 404
    assert httpx.post(f"{url}/register", json={}).status_code in (404, 405)
    unauthorized = httpx.post(f"{url}/mcp", json={})
    assert unauthorized.status_code == 401 and "oauth-protected-resource" in unauthorized.headers["www-authenticate"]


def test_a_connectors_token_reads_and_does_not_reach_the_api(library, live):
    data, url = live
    connector = auth_tokens.token("ann", scopes=["noesis:read"], client="claude1", aud=f"{url}/mcp")
    assert "Prose here." in text(call(url, connector, "read_file", {"name": "2026-10-27-essay.document.md"}))
    bearer = {"Authorization": f"Bearer {connector}"}
    assert httpx.get(f"{url}/libraries", headers=bearer).status_code == 401
    assert httpx.delete(f"{url}/libraries/ann/philosophy/files/2026/2026-10-27-essay.document.md",
                        headers={**bearer, "If-Match": "*"}).status_code == 401


def test_a_token_noesis_cannot_trust_reaches_nothing(library, live):
    data, url = live
    for bad in (auth_tokens.token("ann", ttl=-60),                                  # expired
                auth_tokens.token("ann", key=auth_tokens.STRANGER),                 # not auth's key
                auth_tokens.token("ann", issuer="https://elsewhere.example"),       # not auth
                auth_tokens.token("ann", aud="https://dianoia.example"),            # for another service
                auth_tokens.token("ann", scopes=["identity"], client="roxana"),     # who, not what
                "not-a-token"):
        bearer = {"Authorization": f"Bearer {bad}"}
        assert httpx.get(f"{url}/libraries", headers=bearer).status_code == 401
        assert httpx.post(f"{url}/mcp", json={}, headers={**bearer, "Content-Type": "application/json"}).status_code in (401, 403)


def test_the_web_clients_token_reaches_the_api_as_its_person(library, live):
    data, url = live
    bearer = auth_tokens.bearer("ann")
    assert httpx.get(f"{url}/libraries", headers=bearer).json()["libraries"][0]["id"] == "ann/philosophy"
    assert "2026/2026-10-27-essay.document.md" in httpx.get(
        f"{url}/libraries/ann/philosophy/files", headers=bearer).json()["files"]
    assert httpx.get(f"{url}/libraries/bob/notes/files", headers=bearer).status_code == 403


def test_somebody_new_is_on_the_free_plan(library, live):
    data, url = live
    bearer = auth_tokens.bearer("newcomer")
    me = httpx.get(f"{url}/me", headers=bearer).json()
    assert me["user"] == "newcomer" and me["plan"] == "free" and "email" not in me
    assert me["spent_usd"] == 0 and me["allowance_usd"] == 1.0 and me["client"] == "noesis-web"
    assert httpx.get(f"{url}/libraries", headers=bearer).json() == {"libraries": []}
    assert httpx.get(f"{url}/libraries/ann/philosophy/files", headers=bearer).status_code == 403


def test_the_floor_files_a_conversation_and_nothing_else(library, live, monkeypatch):
    """A token granted `noesis:import` reaches import and the speaker names —
    not the rest of the file and run API."""
    data, url = live
    # The import's subprocess imports this checkout's noesis.
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parent.parent))
    bearer = auth_tokens.bearer("ann", scopes=["noesis:read", "noesis:import"], client="thefloor")
    imported = httpx.post(f"{url}/libraries/ann/philosophy/import?filename=lunch.md", headers=bearer,
                          content=b"Said at lunch.\n", timeout=60)
    assert imported.status_code == 200 and '"exit_code": 0' in imported.text, imported.text
    assert httpx.post(f"{url}/libraries/bob/notes/import?filename=a.md", headers=bearer,
                      content=b"x").status_code in (403, 404)
    assert httpx.get(f"{url}/libraries", headers=bearer).status_code == 401
    assert httpx.post(f"{url}/libraries/ann/philosophy/run", headers=bearer,
                      json={"argv": ["check"]}).status_code == 401
    assert httpx.put(f"{url}/libraries/ann/philosophy/files/2026/x.document.md",
                     headers={**bearer, "If-None-Match": "*"}, content=b"x").status_code == 401
    # Without the scope, neither.
    reader = auth_tokens.bearer("ann", scopes=["noesis:read"], client="claude1")
    assert httpx.get(f"{url}/me", headers=reader).status_code == 200


FLOOR = ("\n# Lunch\n2026-10-30\n\n## Ann\n\nMine.\n\n## Bea\n\nHers.\n\n"
         "## Claude\n\nThe model's.\n\n## Related\n\n| *Essay*\n")


def test_a_chat_of_several_people_says_whose_voice_each_heading_is(library, monkeypatch):
    from noesis import members
    root, url = library
    (root / "2026" / "2026-10-30-lunch.chat.md").write_text(FLOOR)
    shown = {"ann": "Ann"}                                    # her display name at auth
    monkeypatch.setattr(members, "display_name", lambda user: shown.get(user, user))
    voices = "Voices: ## Ann is the user; ## Claude is a model; ## Bea is someone else.\n"

    def read(name):  # the file, after the lines naming it and its companions
        head, body = text(call(url, "ann", "read_file", {"name": name})).split("\n\n", 1)
        assert head.startswith(name.rsplit("/", 1)[-1].split(".")[0])
        return body
    assert read("2026-10-30-lunch.chat.md") == voices + FLOOR
    assert read("2026/2026-10-30-lunch.chat.md") == voices + FLOOR
    assert "the sections headed ## Prompt, ## Ann are the user's own words" in text(call(url, "ann", "guide", {}))
    # Prompt and a model need no saying; nor does anything but a chat.
    assert read("2025-04-25-old-roman.chat.md") == CHAT
    assert read("2026-10-27-essay.document.md") == DOC
    shown["ann"] = "Ann Example"                          # renamed since
    assert read("2026-10-30-lunch.chat.md").startswith(
        "Voices: no heading is the user; ## Claude is a model; ## Ann, ## Bea are other people.\n")
    assert call(url, "ann", "read_file", {"name": "../../bob/x.chat.md"}).is_error
