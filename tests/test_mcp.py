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


CHAT = "\n# Old Roman\n2025-04-25\n\n## Prompt\n\nHello.\n\n## Claude\n\nHi.\n\n## Related\n\n| *Essay*\n"
DOC = "\n# Essay\n2026-10-27\n\nProse here.\n"

# The codes the server mailed, by address: mail.send_code, replaced.
SENT: dict[str, str] = {}


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
    mp.setattr("noesis.mail.send_code", lambda to, code, client_name: SENT.__setitem__(to, code))
    # Every test here signs in from 127.0.0.1; the limits have tests of their own.
    mp.setattr("noesis.accounts.SEND_LIMITS", (("email", 3600, 100), ("ip", 3600, 100), ("all", 86400, 1000)))
    (data / "users.toml").write_text(
        f'[[tokens]]\nuser = "ann"\nsha256 = "{hashlib.sha256(b"ann").hexdigest()}"\n'
        f'[[tokens]]\nuser = "bob"\nsha256 = "{hashlib.sha256(b"bob").hexdigest()}"\n'
    )
    from noesis import accounts, server
    # ann was the operator's before she signed in by email: linked, as scripts/accounts.py does.
    accounts.link("ann@example.com", "ann", accounts.UNLIMITED)
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
    assert list(tools) == ["guide", "list_documents", "lookup_term", "read_document",
                           "read_file"]
    # claude.ai shows the model tool descriptions, not server instructions:
    # the guidance travels in guide, and the essentials in the descriptions.
    assert "<date>-<slug>.<role>.<ext>" in text(call(url, "ann", "guide", {}))
    assert "<date>-<slug>.<role>.<ext>" in tools["list_documents"]
    assert "| *Exact Title*" in tools["read_document"]
    assert "'Voices:'" in tools["read_document"] and "'Voices:'" in tools["read_file"]
    assert httpx.post(f"{url}/mcp", json={}).status_code == 401
    assert httpx.post(f"{url}/mcp", json={}, headers={"Authorization": "Bearer nope"}).status_code == 401
    meta = httpx.get(f"{url}/.well-known/oauth-protected-resource/mcp").json()
    assert meta["authorization_servers"] == [url] or meta["authorization_servers"] == [url + "/"]


def test_reading(library):
    root, url = library
    assert "2026-10-27-essay.document.md — Essay" in text(call(url, "ann", "list_documents", {}))
    assert "Essay" in text(call(url, "ann", "list_documents", {"query": "prose"}))
    assert "Essay" in text(call(url, "ann", "lookup_term", {"term": "prose"}))
    assert "Prose here." in text(call(url, "ann", "read_file", {"name": "2026-10-27-essay.document.md"}))
    assert "Prose here." in text(call(url, "ann", "read_document", {"path": "2026/2026-10-27-essay.document.md"}))
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


def _pkce():
    import base64
    import secrets
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


CALLBACK = "https://claude.ai/api/mcp/auth_callback"


def _register(url, redirect=CALLBACK):
    return httpx.post(f"{url}/register", json={
        "redirect_uris": [redirect], "client_name": "Claude",
        "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"],
        "token_endpoint_auth_method": "client_secret_post"})


def _authorize(url, client, challenge, state="s1"):
    r = httpx.get(f"{url}/authorize", params={
        "response_type": "code", "client_id": client["client_id"], "redirect_uri": CALLBACK,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": state})
    assert r.status_code == 302, r.text
    login = r.headers["location"]
    assert "/oauth/login?request=" in login
    return login.split("request=")[1]


def _sign_in(url, request_id, email="ann@example.com"):
    sent = httpx.post(f"{url}/oauth/login", data={"request": request_id, "email": email, "action": "send"})
    assert sent.status_code == 200 and "on its way" in sent.text, sent.text
    return httpx.post(f"{url}/oauth/login", data={"request": request_id, "code": SENT[email], "action": "verify"})


def test_claude_ai_signs_in_with_an_emailed_code(library, live):
    from urllib.parse import parse_qs, urlparse
    data, url = live
    root, _ = library
    assert "token_endpoint" in httpx.get(f"{url}/.well-known/oauth-authorization-server").json()
    assert _register(url, "https://evil.example/cb").status_code == 400
    client = _register(url).json()
    verifier, challenge = _pkce()
    request_id = _authorize(url, client, challenge)
    page = httpx.get(f"{url}/oauth/login", params={"request": request_id})
    assert page.status_code == 200 and "Claude" in page.text and "claude.ai" in page.text
    assert "to read your noesis libraries" in page.text and 'type="email"' in page.text
    bad = httpx.post(f"{url}/oauth/login", data={"request": request_id, "email": "nope", "action": "send"})
    assert "not an email address" in bad.text
    sent = httpx.post(f"{url}/oauth/login", data={"request": request_id, "email": " Ann@Example.com ", "action": "send"})
    assert "on its way to <b>ann@example.com</b>" in sent.text
    code = SENT["ann@example.com"]
    wrong = httpx.post(f"{url}/oauth/login", data={
        "request": request_id, "code": f"{(int(code) + 1) % 10**6:06d}", "action": "verify"})
    assert wrong.status_code == 200 and "not the code" in wrong.text
    back = httpx.post(f"{url}/oauth/login", data={"request": request_id, "code": code, "action": "verify"})
    assert back.status_code == 302 and back.headers["location"].startswith(CALLBACK)
    query = parse_qs(urlparse(back.headers["location"]).query)
    assert query["state"] == ["s1"]
    tokens = httpx.post(f"{url}/token", data={
        "grant_type": "authorization_code", "code": query["code"][0], "redirect_uri": CALLBACK,
        "client_id": client["client_id"], "client_secret": client["client_secret"],
        "code_verifier": verifier}).json()
    assert tokens["token_type"] == "Bearer" and tokens["expires_in"] == 3600
    # The OAuth token reaches the library as its user.
    assert "Prose here." in text(call(url, tokens["access_token"], "read_file", {"name": "2026-10-27-essay.document.md"}))
    # Refresh rotates: the new pair works, the old refresh token does not.
    refreshed = httpx.post(f"{url}/token", data={
        "grant_type": "refresh_token", "refresh_token": tokens["refresh_token"],
        "client_id": client["client_id"], "client_secret": client["client_secret"]}).json()
    assert "Prose here." in text(call(url, refreshed["access_token"], "read_file", {"name": "2026-10-27-essay.document.md"}))
    again = httpx.post(f"{url}/token", data={
        "grant_type": "refresh_token", "refresh_token": tokens["refresh_token"],
        "client_id": client["client_id"], "client_secret": client["client_secret"]})
    assert again.status_code == 400
    # Disabling the account takes its OAuth access with it.
    from noesis import accounts
    accounts.set_disabled("ann", True)
    try:
        assert httpx.post(f"{url}/mcp", json={}, headers={
            "Authorization": f"Bearer {refreshed['access_token']}", "Content-Type": "application/json"}).status_code == 401
    finally:
        accounts.set_disabled("ann", False)


def test_wrong_codes_end_the_sign_in(library, live):
    data, url = live
    client = _register(url).json()
    _, challenge = _pkce()
    request_id = _authorize(url, client, challenge)
    httpx.post(f"{url}/oauth/login", data={"request": request_id, "email": "ann@example.com", "action": "send"})
    code = SENT["ann@example.com"]
    wrong = f"{(int(code) + 1) % 10**6:06d}"
    for _ in range(4):
        assert "not the code" in httpx.post(f"{url}/oauth/login", data={
            "request": request_id, "code": wrong, "action": "verify"}).text
    last = httpx.post(f"{url}/oauth/login", data={"request": request_id, "code": wrong, "action": "verify"})
    assert last.status_code == 400 and "Too many" in last.text
    # The right code no longer helps.
    assert httpx.post(f"{url}/oauth/login", data={
        "request": request_id, "code": code, "action": "verify"}).status_code == 400


def test_a_new_address_makes_a_free_account(library, live):
    from urllib.parse import parse_qs, urlparse
    data, url = live
    redirect = f"{url}/web/"
    verifier, challenge = _pkce()
    r = httpx.get(f"{url}/authorize", params={
        "response_type": "code", "client_id": "noesis-web", "redirect_uri": redirect,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": "n1"})
    request_id = r.headers["location"].split("request=")[1]
    # "ann" is taken, by the operator's user: the new account is ann1.
    back = _sign_in(url, request_id, "ann+noesis@elsewhere.example")
    code = parse_qs(urlparse(back.headers["location"]).query)["code"][0]
    tokens = httpx.post(f"{url}/token", data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": redirect,
        "client_id": "noesis-web", "code_verifier": verifier}).json()
    bearer = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = httpx.get(f"{url}/me", headers=bearer).json()
    assert me["user"] == "ann1" and me["plan"] == "free" and me["email"] == "ann+noesis@elsewhere.example"
    assert me["spent_usd"] == 0 and me["allowance_usd"] == 1.0
    assert httpx.get(f"{url}/libraries", headers=bearer).json() == {"libraries": [], "names": {}}
    assert httpx.get(f"{url}/libraries/ann/philosophy/files", headers=bearer).status_code == 403


def test_deny_sends_access_denied(library, live):
    data, url = live
    client = _register(url).json()
    _, challenge = _pkce()
    request_id = _authorize(url, client, challenge, state="s2")
    back = httpx.post(f"{url}/oauth/login", data={"request": request_id, "action": "deny"})
    assert back.status_code == 302 and "error=access_denied" in back.headers["location"] and "state=s2" in back.headers["location"]


def test_the_web_client_signs_in_and_reaches_the_api(library, live):
    from urllib.parse import parse_qs, urlparse
    data, url = live
    redirect = f"{url}/web/"
    verifier, challenge = _pkce()
    r = httpx.get(f"{url}/authorize", params={
        "response_type": "code", "client_id": "noesis-web", "redirect_uri": redirect,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": "w1"})
    assert r.status_code == 302, r.text
    request_id = r.headers["location"].split("request=")[1]
    page = httpx.get(f"{url}/oauth/login", params={"request": request_id})
    assert "noesis on the web" in page.text and "run noesis's commands" in page.text
    back = _sign_in(url, request_id)
    assert back.status_code == 302 and back.headers["location"].startswith(redirect)
    code = parse_qs(urlparse(back.headers["location"]).query)["code"][0]
    # A public client: no secret, the verifier alone.
    tokens = httpx.post(f"{url}/token", data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": redirect,
        "client_id": "noesis-web", "code_verifier": verifier}).json()
    bearer = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert httpx.get(f"{url}/libraries", headers=bearer).json() == {"libraries": ["ann/philosophy"], "names": {}}
    assert "2026/2026-10-27-essay.document.md" in httpx.get(
        f"{url}/libraries/ann/philosophy/files", headers=bearer).json()["files"]
    assert httpx.get(f"{url}/libraries/bob/notes/files", headers=bearer).status_code == 403
    # Signing out revokes, as the page sends it: a public client, an empty secret.
    revoked = httpx.post(f"{url}/revoke", data={
        "client_id": "noesis-web", "client_secret": "", "token": tokens["refresh_token"]})
    assert revoked.status_code == 200
    assert httpx.get(f"{url}/libraries", headers=bearer).status_code == 401
    # Its only redirect is the page: a code cannot be sent anywhere else.
    elsewhere = httpx.get(f"{url}/authorize", params={
        "response_type": "code", "client_id": "noesis-web", "redirect_uri": "https://evil.example/web/",
        "code_challenge": challenge, "code_challenge_method": "S256", "state": "w2"})
    assert elsewhere.status_code == 400


def test_roxana_signs_people_in_and_learns_only_who_they_are(library, live):
    """An identity-only public client, as Roxana's browser runs it: PKCE, /me
    from its own origin, refresh, revoke; never /mcp or the API."""
    import importlib.util
    import io
    from contextlib import redirect_stdout
    from urllib.parse import parse_qs, urlparse
    data, url = live
    spec = importlib.util.spec_from_file_location("add_client", Path(__file__).parent.parent / "scripts" / "add_client.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    redirect, origin = "https://roxana.example/signin", "https://roxana.example"
    with redirect_stdout(io.StringIO()):
        script.main(["roxana", "--public", "--name", "Roxana", "--redirect", redirect])
    verifier, challenge = _pkce()
    r = httpx.get(f"{url}/authorize", params={
        "response_type": "code", "client_id": "roxana", "redirect_uri": redirect,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": "r1"})
    request_id = r.headers["location"].split("request=")[1]
    page = httpx.get(f"{url}/oauth/login", params={"request": request_id}).text
    assert "Roxana" in page and "not your libraries" in page
    back = _sign_in(url, request_id)
    code = parse_qs(urlparse(back.headers["location"]).query)["code"][0]
    exchanged = httpx.post(f"{url}/token", headers={"Origin": origin}, data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": redirect,
        "client_id": "roxana", "code_verifier": verifier})
    assert exchanged.headers["access-control-allow-origin"] in ("*", origin)
    tokens = exchanged.json()
    bearer = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = httpx.get(f"{url}/me", headers={**bearer, "Origin": origin})
    assert me.json()["user"] == "ann" and me.json()["client"] == "roxana"
    assert me.headers["access-control-allow-origin"] == origin
    assert httpx.get(f"{url}/libraries", headers=bearer).status_code == 401
    assert httpx.post(f"{url}/mcp", json={}, headers=bearer).status_code == 401
    refreshed = httpx.post(f"{url}/token", data={
        "grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "client_id": "roxana"}).json()
    assert httpx.get(f"{url}/me", headers={"Authorization": f"Bearer {refreshed['access_token']}"}).status_code == 200
    assert httpx.post(f"{url}/revoke", data={
        "client_id": "roxana", "client_secret": "", "token": refreshed["refresh_token"]}).status_code == 200
    assert httpx.get(f"{url}/me", headers={"Authorization": f"Bearer {refreshed['access_token']}"}).status_code == 401


def test_a_connectors_token_does_not_reach_the_api(library, live):
    from urllib.parse import parse_qs, urlparse
    data, url = live
    client = _register(url).json()
    verifier, challenge = _pkce()
    request_id = _authorize(url, client, challenge)
    back = _sign_in(url, request_id)
    code = parse_qs(urlparse(back.headers["location"]).query)["code"][0]
    tokens = httpx.post(f"{url}/token", data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": CALLBACK,
        "client_id": client["client_id"], "client_secret": client["client_secret"],
        "code_verifier": verifier}).json()
    bearer = {"Authorization": f"Bearer {tokens['access_token']}"}
    # It reads through /mcp, and the API, which writes, refuses it.
    assert "Prose here." in text(call(url, tokens["access_token"], "read_file", {"name": "2026-10-27-essay.document.md"}))
    assert httpx.get(f"{url}/libraries", headers=bearer).status_code == 401
    assert httpx.delete(f"{url}/libraries/ann/philosophy/files/2026/2026-10-27-essay.document.md",
                        headers={**bearer, "If-Match": "*"}).status_code == 401


def _floor_client(url, *, imports=True):
    """The Floor as the operator registers it: confidential, and marked to file conversations."""
    import importlib.util
    import io
    from contextlib import redirect_stdout
    scripts = Path(__file__).parent.parent / "scripts"
    out = io.StringIO()
    with redirect_stdout(out):
        for name, argv in (("add_client", ["thefloor", "--name", "The Floor", "--redirect", FLOOR_CALLBACK]),
                           ("client_imports", ["thefloor"] if imports else None)):
            if argv is None:
                continue
            spec = importlib.util.spec_from_file_location(name, scripts / f"{name}.py")
            script = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(script)
            script.main(argv)
    lines = dict(line.split("=", 1) for line in out.getvalue().split() if "=" in line)
    return lines["NOESIS_CLIENT_SECRET"]


FLOOR_CALLBACK = "https://floor.example/noesis/callback"


def _floor_tokens(url, secret, scope):
    from urllib.parse import parse_qs, urlparse
    verifier, challenge = _pkce()
    r = httpx.get(f"{url}/authorize", params={
        "response_type": "code", "client_id": "thefloor", "redirect_uri": FLOOR_CALLBACK,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": "f1", "scope": scope})
    request_id = r.headers["location"].split("request=")[1]
    page = httpx.get(f"{url}/oauth/login", params={"request": request_id}).text
    back = _sign_in(url, request_id)
    code = parse_qs(urlparse(back.headers["location"]).query)["code"][0]
    tokens = httpx.post(f"{url}/token", data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": FLOOR_CALLBACK,
        "client_id": "thefloor", "client_secret": secret, "code_verifier": verifier}).json()
    return tokens, page


def test_the_floor_files_a_conversation_and_nothing_else(library, live, monkeypatch):
    """A client the operator marked asks for `import`, the sign-in says so, and its
    token reaches import and the speaker names — not the rest of the file and run API."""
    data, url = live
    # The import's subprocess imports this checkout's noesis.
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parent.parent))
    secret = _floor_client(url)
    tokens, page = _floor_tokens(url, secret, "import")
    assert "add conversations to them" in page
    assert tokens["scope"] == "import"
    bearer = {"Authorization": f"Bearer {tokens['access_token']}"}
    imported = httpx.post(f"{url}/libraries/ann/philosophy/import?filename=lunch.md", headers=bearer,
                          content=b"Said at lunch.\n", timeout=60)
    assert imported.status_code == 200 and '"exit_code": 0' in imported.text, imported.text
    assert httpx.put(f"{url}/me/names", headers=bearer, json={"names": ["Ann"]}).json()["names"] == ["Ann"]
    # Not another person's library, and nothing else of the API.
    assert httpx.post(f"{url}/libraries/bob/notes/import?filename=a.md", headers=bearer,
                      content=b"x").status_code in (403, 404)
    assert httpx.get(f"{url}/libraries", headers=bearer).status_code == 401
    assert httpx.post(f"{url}/libraries/ann/philosophy/run", headers=bearer,
                      json={"argv": ["check"]}).status_code == 401
    assert httpx.put(f"{url}/libraries/ann/philosophy/files/2026/x.document.md",
                     headers={**bearer, "If-None-Match": "*"}, content=b"x").status_code == 401
    # A refresh keeps the scope; the operator's unmarking stops it at once.
    refreshed = httpx.post(f"{url}/token", data={
        "grant_type": "refresh_token", "refresh_token": tokens["refresh_token"],
        "client_id": "thefloor", "client_secret": secret}).json()
    assert refreshed["scope"] == "import"
    _script = Path(__file__).parent.parent / "scripts" / "client_imports.py"
    import importlib.util, io
    from contextlib import redirect_stdout
    spec = importlib.util.spec_from_file_location("client_imports", _script)
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    with redirect_stdout(io.StringIO()):
        script.main(["thefloor", "--off"])
    again = {"Authorization": f"Bearer {refreshed['access_token']}"}
    assert httpx.put(f"{url}/me/names", headers=again, json={"names": ["Ann"]}).status_code == 401
    assert httpx.get(f"{url}/me", headers=again).status_code == 200


def test_only_the_operators_mark_grants_import(library, live):
    data, url = live
    # Unmarked, The Floor cannot ask for it at all.
    secret = _floor_client(url, imports=False)
    _, challenge = _pkce()
    refused = httpx.get(f"{url}/authorize", params={
        "response_type": "code", "client_id": "thefloor", "redirect_uri": FLOOR_CALLBACK,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": "f2", "scope": "import"})
    assert "invalid_scope" in refused.headers.get("location", "")
    # A self-registered client claiming the scope is let ask, and is not given it.
    from urllib.parse import parse_qs, urlparse
    claimed = httpx.post(f"{url}/register", json={
        "redirect_uris": [CALLBACK], "client_name": "Claude", "scope": "import",
        "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"],
        "token_endpoint_auth_method": "client_secret_post"}).json()
    verifier, challenge = _pkce()
    r = httpx.get(f"{url}/authorize", params={
        "response_type": "code", "client_id": claimed["client_id"], "redirect_uri": CALLBACK,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": "c1", "scope": "import"})
    request_id = r.headers["location"].split("request=")[1]
    assert "add conversations" not in httpx.get(f"{url}/oauth/login", params={"request": request_id}).text
    back = _sign_in(url, request_id)
    code = parse_qs(urlparse(back.headers["location"]).query)["code"][0]
    tokens = httpx.post(f"{url}/token", data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": CALLBACK,
        "client_id": claimed["client_id"], "client_secret": claimed["client_secret"],
        "code_verifier": verifier}).json()
    assert "scope" not in tokens or not tokens["scope"]
    assert httpx.post(f"{url}/libraries/ann/philosophy/import?filename=a.md",
                      headers={"Authorization": f"Bearer {tokens['access_token']}"}, content=b"x").status_code == 401


FLOOR = ("\n# Lunch\n2026-10-30\n\n## Ann\n\nMine.\n\n## Bea\n\nHers.\n\n"
         "## Claude\n\nThe model's.\n\n## Related\n\n| *Essay*\n")


def test_a_chat_of_several_people_says_whose_voice_each_heading_is(library):
    from noesis import accounts
    root, url = library
    (root / "2026" / "2026-10-30-lunch.chat.md").write_text(FLOOR)
    accounts.set_speaker_names("ann", ["Ann"])
    try:
        voices = "Voices: ## Ann is the user; ## Claude is a model; ## Bea is someone else.\n"
        assert text(call(url, "ann", "read_file", {"name": "2026-10-30-lunch.chat.md"})) == voices + FLOOR
        assert text(call(url, "ann", "read_document", {"path": "2026/2026-10-30-lunch.chat.md"})) == voices + FLOOR
        assert "the sections headed ## Prompt, ## Ann are the user's own words" in text(call(url, "ann", "guide", {}))
        # Prompt and a model need no saying; nor does anything but a chat.
        assert text(call(url, "ann", "read_file", {"name": "2025-04-25-old-roman.chat.md"})) == CHAT
        assert text(call(url, "ann", "read_file", {"name": "2026-10-27-essay.document.md"})) == DOC
        accounts.set_speaker_names("ann", [])
        assert text(call(url, "ann", "read_file", {"name": "2026-10-30-lunch.chat.md"})).startswith(
            "Voices: no heading is the user; ## Claude is a model; ## Ann, ## Bea are other people.\n")
        assert "Error" in text(call(url, "ann", "read_document", {"path": "../../bob/x.chat.md"}))
    finally:
        accounts.set_speaker_names("ann", [])
