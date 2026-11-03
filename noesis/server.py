"""noesis's HTTP API, run by `noesis serve` (SERVER.md, Phase 2).

Every route but /healthz and the web client's pages needs a bearer token:
a minted one, which /data/users.toml maps by its SHA-256 to a user, or to "*"
for a service (the nightly index); or an OAuth access token issued to noesis's
own web client (oauth.API_CLIENTS). An application granted the import scope
(The Floor; oauth.IMPORT_SCOPE) reaches /import and PUT /me/names alone.
A user reaches only their own libraries,
/data/libraries/<user>/<library>. A library is files to sync and commands to
run:

- GET    /libraries                          the caller's library ids
- POST   /libraries {name}                   a new library of the caller's, its settings empty
- GET    /libraries/{user}/{library}/files   {rel_path: sha256}
- GET    …/files/{rel_path}                  the bytes, ETag their sha256, Last-Modified their mtime
- HEAD   …/files/{rel_path}                  the same headers, without the bytes
- PUT    …/files/{rel_path}                  If-None-Match: * creates; If-Match: "<sha>" replaces
- DELETE …/files/{rel_path}                  If-Match: "<sha>"
- POST   …/run {argv}                        server-sent events: output, then done
- POST   …/import?filename=…[&only=…&replace=true&document_of=…]   the body is the file; as /run
- GET    /me                                 the caller's account: plan, spend, storage, names,
                                             and the client the token was issued to (any
                                             client's token, not only the API's; CORS for
                                             the browser apps that sign in here, Roxana)
- PUT    /me/names {names}                   the headings that are the caller's voice in chats

The register of names (names.py) answers an application that keeps names
(The Floor), by its client id and secret as HTTP Basic, on nobody's behalf:

- POST   /names {email, suggest}             the address's name, reserved now if it has none
- PUT    /names {email, user}                that name for the address: reserved, or its reservation renamed
- PUT    /names/address {email, new_email}   a reservation moved to another address

A noesis account's name and address are fixed (names.py): only a reservation changes.

/run runs `noesis --lib <library> <argv>` in a subprocess from the library root:
file arguments are names, which noesis resolves across the library. Its output
streams as it is written (reply prints tokens without newlines), and the
last event says which files the run changed or deleted. A run knows the
library owner's voice by the names they keep here (accounts.speaker_names),
in NOESIS_USER_NAMES, whoever starts it: the owner, or the nightly index. One run at a time
per library; while it runs, writes to the library get 409. The run belongs
to the server, not the request: a client that goes away does not cut it short.

/import is how a conversation from elsewhere enters a library without a
client's own copy of it (a claude.ai export, saveai.net Markdown, any text;
nothing else, cmd_import.IMPORTABLE): the upload is kept outside the
library, `noesis import` writes from it into the year directories, and it is
deleted when the run ends.

Dotfiles, and so the index state in .noesis/, are never listed, read or written.

A free account (accounts.py) is held to its limits here: what it may store,
how many libraries, and a run that can spend (SPENDING) is refused once
its allowance is spent (402); any run while free runs fill their slots (503). Every run spends for the
library's owner, named to noesis in NOESIS_ACCOUNT, whose model clients charge it.

/web/ serves noesis's web client (noesis/web/): static files, which sign in through
noesis's OAuth server and then call this API like any other client.
"""

from __future__ import annotations

import asyncio
import codecs
import hashlib
import json
import os
import shutil
import sys
import tempfile
from contextlib import asynccontextmanager
from email.utils import formatdate
from pathlib import Path, PurePosixPath

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from mcp.server.auth.provider import AccessToken
from pydantic import BaseModel

from noesis import service
from noesis.service import LibraryError, create_library, library_ids, library_root, lock_for

# Written by bin/deploy into the package before the image is built, so it is
# baked in with the code it describes. Absent in a checkout, where the answer
# is "dev".
_DEPLOYED = Path(__file__).resolve().parent / "deployed.json"

# Subcommands a client may run. edit, config, sync and serve belong to the
# client's own machine or to the operator. files lists the files uploaded
# with the server's key, which only the server holds.
RUNNABLE = frozenset({
    "check", "validate", "fix", "new", "reply", "index",
    "argue", "analyze", "audit", "export", "pdf", "diff", "review", "files",
})
# Those that call a model (Anthropic or dianoia), and so are refused up front
# once a free account's allowance is spent; import too, which titles The
# Floor's transcripts with the index model. The rest cost nothing and always
# run. A command missing here is still stopped at its first model call, by
# the meter in the run itself (accounts.py), only less plainly.
SPENDING = frozenset({"reply", "index", "argue", "analyze", "audit", "review", "import"})

_runs: set[asyncio.Task] = set()
# Runs for free accounts at once, server-wide: the box is shared (rvanegas-site).
FREE_RUNS = 2
_free_runs: set[asyncio.Task] = set()

# The MCP server (SERVER.md, Phase 5) answers at /mcp, mounted below the
# API's routes; its session manager lives as long as the app.
from noesis.mcp_server import mcp_app, mcp_lifespan


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    async with mcp_lifespan():
        yield


app = FastAPI(title="noesis", lifespan=_lifespan)


def _deployed() -> dict:
    try:
        return json.loads(_DEPLOYED.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"commit": "dev"}


@app.get("/healthz")
def healthz() -> dict:
    """Unauthenticated: it says nothing but which commit is running."""
    return {"ok": True, **_deployed()}


# ---------------------------------------------------------------------------
# Callers and libraries
# ---------------------------------------------------------------------------

async def caller(authorization: str | None = Header(default=None)) -> str:
    """The user a bearer token belongs to, or "*" for a service."""
    from noesis.oauth import API_CLIENTS, provider
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "a bearer token is required")
    token = await provider.load_access_token(authorization.removeprefix("Bearer "))
    if token is None or token.client_id not in API_CLIENTS or not token.subject:
        raise HTTPException(401, "unknown token")
    return token.subject


async def anyone(authorization: str | None = Header(default=None)) -> AccessToken:
    """As caller, but any client's token, identity-only ones too: for what a person may read about themselves."""
    from noesis.oauth import provider
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "a bearer token is required")
    token = await provider.load_any_access_token(authorization.removeprefix("Bearer "))
    if token is None or not token.subject:
        raise HTTPException(401, "unknown token")
    return token


def library(user: str, library: str, who: str = Depends(caller)) -> Path:
    try:
        return library_root(user, library, who)
    except LibraryError as exc:
        raise HTTPException(exc.status, str(exc)) from None


async def filer(authorization: str | None = Header(default=None)) -> str:
    """As caller, and also an application granted the import scope (oauth.IMPORT_SCOPE)."""
    from noesis.oauth import API_CLIENTS, provider
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "a bearer token is required")
    token = await provider.load_access_token(authorization.removeprefix("Bearer "))
    if token is None or not token.subject or not (
            token.client_id in API_CLIENTS or provider.may_import(token)):
        raise HTTPException(401, "unknown token")
    return token.subject


def filed_library(user: str, library: str, who: str = Depends(filer)) -> Path:
    """As library, for what an importing application may reach: import, and nothing else."""
    try:
        return library_root(user, library, who)
    except LibraryError as exc:
        raise HTTPException(exc.status, str(exc)) from None


@app.get("/libraries")
def libraries(who: str = Depends(caller)) -> dict:
    return {"libraries": library_ids(who)}


# Any client's token: an application a person connected (The Floor, a
# connector) may say whose library it reaches, which writes nothing; an
# application that signs people in here (Roxana) learns who they are, and
# dianoia, handed that token, which client holds it.
@app.get("/me")
def me(token: AccessToken = Depends(anyone)) -> dict:
    from noesis import accounts
    who = token.subject
    found = accounts.account(who)
    free = accounts.is_free(who)
    limits = accounts.limits()
    return {
        "user": who,
        "email": found.email if found else None,
        "plan": accounts.plan_of(who),
        "month": accounts.month(),
        "spent_usd": round(accounts.spent(who), 4),
        "allowance_usd": accounts.allowance(who) if free else None,
        "stored_bytes": accounts.stored_bytes(who) if free else None,
        # Which libraries are theirs, so an application can offer a choice of
        # them (The Floor's per-channel toggles); ids as /libraries gives them.
        "libraries": library_ids(who),
        "storage_bytes": limits.storage_bytes if free else None,
        "names": list(accounts.speaker_names(who)),
        "client": token.client_id,
    }


# /me from the browser: only the origins of the apps that sign in here
# (oauth.browser_origins), which the operator registers. The SDK's OAuth
# routes (/token, /revoke) answer any origin themselves.
_ME_CORS = {"Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "authorization", "Access-Control-Max-Age": "600", "Vary": "Origin"}


@app.middleware("http")
async def me_cors(request: Request, call_next) -> Response:
    origin = request.headers.get("origin")
    if request.url.path != "/me" or not origin:
        return await call_next(request)
    from noesis.oauth import provider
    allowed = origin in provider.browser_origins()
    if request.method == "OPTIONS":
        return Response(status_code=204, headers={**_ME_CORS, "Access-Control-Allow-Origin": origin} if allowed else {})
    response = await call_next(request)
    if allowed:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
    return response


class SpeakerNames(BaseModel):
    names: list[str]


@app.put("/me/names")
def put_names(body: SpeakerNames, who: str = Depends(filer)) -> dict:
    """The chat headings, besides "Prompt", that are the caller's own voice."""
    from noesis import accounts
    if who == "*":
        raise HTTPException(400, "a service speaks in no chats")
    try:
        return {"names": list(accounts.set_speaker_names(who, body.names))}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


def _naming(change):
    """A change to the register, its refusals as sentences."""
    from noesis import names
    try:
        return change()
    except names.Taken as exc:
        raise HTTPException(409, str(exc)) from None
    except names.Invalid as exc:
        raise HTTPException(400, str(exc)) from None


async def name_keeper(authorization: str | None = Header(default=None)) -> str:
    """The application calling the register, by its client id and secret (HTTP Basic)."""
    import base64
    import binascii
    from noesis.oauth import provider
    if not authorization or not authorization.startswith("Basic "):
        raise HTTPException(401, "a client id and secret are required")
    try:
        client_id, _, secret = base64.b64decode(authorization.removeprefix("Basic ")).decode().partition(":")
    except (binascii.Error, UnicodeDecodeError):
        raise HTTPException(401, "a client id and secret are required") from None
    if not provider.keeps_names(client_id, secret):
        raise HTTPException(401, "not an application that keeps names")
    return client_id


class NameFor(BaseModel):
    email: str
    suggest: list[str] = []


class NameChoice(BaseModel):
    email: str
    user: str


class AddressMove(BaseModel):
    email: str
    new_email: str


@app.post("/names")
def post_name(body: NameFor, client: str = Depends(name_keeper)) -> dict:
    """An address's name, and whether it is a noesis account's; reserved for it now if it had none."""
    from noesis import names
    user, account = _naming(lambda: names.name_for(body.email, client, body.suggest[:5]))
    return {"user": user, "account": account}


@app.put("/names")
def put_name(body: NameChoice, client: str = Depends(name_keeper)) -> dict:
    """Makes a name the address's: reserved if it has none, renamed everywhere if it has another."""
    from noesis import names
    return {"user": _naming(lambda: names.choose(body.email, body.user, client))}


@app.put("/names/address")
def put_name_address(body: AddressMove, client: str = Depends(name_keeper)) -> dict:
    """A reservation moved to the address its person now signs in with at the application."""
    from noesis import names
    _naming(lambda: names.move(body.email, body.new_email))
    return {"moved": True}


class NewLibrary(BaseModel):
    name: str


@app.post("/libraries", status_code=201)
def new_library(body: NewLibrary, who: str = Depends(caller)) -> dict:
    try:
        return {"library": create_library(who, body.name)}
    except LibraryError as exc:
        raise HTTPException(exc.status, str(exc)) from None


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_hashes(root: Path) -> dict[str, str]:
    """{rel_path: sha256} of a library's visible files: no dotfiles, no symlinks."""
    hashes = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if any(part.startswith(".") for part in rel.parts) or path.is_symlink() or not path.is_file():
            continue
        hashes[rel.as_posix()] = _sha256(path)
    return hashes


def _file(root: Path, rel_path: str) -> Path:
    """A path within the library, refusing escapes, dotfiles and symlinks."""
    rel = PurePosixPath(rel_path)
    if rel.is_absolute() or not rel.parts or any(p in ("", ".", "..") or p.startswith(".") for p in rel.parts):
        raise HTTPException(400, f"not a library path: {rel_path!r}")
    path = root
    for part in rel.parts:
        path = path / part
        if path.is_symlink():
            raise HTTPException(400, f"a symlink is in the way: {rel_path!r}")
    return path


def _etag(sha256: str) -> str:
    return f'"{sha256}"'


def _unquote(tag: str) -> str:
    return tag.strip().removeprefix("W/").strip('"')


def _owner(root: Path) -> str:
    """The user whose library this is: libraries/<user>/<library>."""
    return root.parent.name


def _storable(root: Path, name: str, size: int, replacing: int = 0, types=None) -> None:
    from noesis import accounts
    why = accounts.storage_refusal(_owner(root), name, size, replacing,
                                   types=types or accounts.FREE_TYPES)
    if why:
        raise HTTPException(413, why)


def _may_run(root: Path, command: str) -> None:
    """A free account's run needs a free slot, and allowance left if it can spend."""
    from noesis import accounts
    owner = _owner(root)
    if not accounts.is_free(owner):
        return
    if command in SPENDING and (why := accounts.refusal(owner)):
        raise HTTPException(402, why)
    if len(_free_runs) >= FREE_RUNS:
        raise HTTPException(503, "the server is busy with other free accounts' runs; try again in a minute")


def _writable(root: Path) -> None:
    lock = service.locks.get(root)
    if lock is not None and lock.locked():
        raise HTTPException(409, "a run is in progress in this library")


@app.get("/libraries/{user}/{library}/files")
def list_files(root: Path = Depends(library)) -> dict:
    return {"files": tree_hashes(root)}


def _readable(root: Path, rel_path: str) -> Path:
    path = _file(root, rel_path)
    if not path.is_file():
        raise HTTPException(404, "no such file")
    return path


# no-cache: a browser would otherwise reuse a file it read before, which a run
# may since have rewritten, for as long as its Last-Modified suggests.
def _file_headers(path: Path, sha256: str) -> dict:
    return {"ETag": _etag(sha256), "Last-Modified": formatdate(path.stat().st_mtime, usegmt=True),
            "Cache-Control": "no-cache"}


@app.get("/libraries/{user}/{library}/files/{rel_path:path}")
def read_file(rel_path: str, root: Path = Depends(library)) -> Response:
    path = _readable(root, rel_path)
    data = path.read_bytes()
    return Response(data, media_type="application/octet-stream",
                    headers=_file_headers(path, hashlib.sha256(data).hexdigest()))


@app.head("/libraries/{user}/{library}/files/{rel_path:path}")
def file_head(rel_path: str, root: Path = Depends(library)) -> Response:
    path = _readable(root, rel_path)
    return Response(media_type="application/octet-stream",
                    headers={**_file_headers(path, _sha256(path)), "Content-Length": str(path.stat().st_size)})


@app.put("/libraries/{user}/{library}/files/{rel_path:path}")
async def write_file(
    rel_path: str,
    request: Request,
    root: Path = Depends(library),
    if_match: str | None = Header(default=None),
    if_none_match: str | None = Header(default=None),
) -> Response:
    path = _file(root, rel_path)
    _writable(root)
    if if_none_match is not None:
        if if_none_match.strip() != "*":
            raise HTTPException(400, "If-None-Match takes only *")
        if path.exists():
            raise HTTPException(412, "the file already exists")
    elif if_match is not None:
        if not path.is_file() or _sha256(path) != _unquote(if_match):
            raise HTTPException(412, "the file has changed")
    else:
        raise HTTPException(428, 'If-Match: "<sha256>" to replace, If-None-Match: * to create')
    data = await request.body()
    _storable(root, path.name, len(data), path.stat().st_size if path.is_file() else 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.put")
    tmp.write_bytes(data)
    tmp.replace(path)
    return Response(status_code=200, headers={"ETag": _etag(hashlib.sha256(data).hexdigest())})


@app.delete("/libraries/{user}/{library}/files/{rel_path:path}")
def delete_file(
    rel_path: str,
    root: Path = Depends(library),
    if_match: str | None = Header(default=None),
) -> Response:
    path = _file(root, rel_path)
    _writable(root)
    if if_match is None:
        raise HTTPException(428, 'If-Match: "<sha256>" is required')
    if not path.is_file() or _sha256(path) != _unquote(if_match):
        raise HTTPException(412, "the file has changed")
    path.unlink()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------

class Run(BaseModel):
    argv: list[str]


def _check_run(run: Run) -> None:
    if not run.argv or run.argv[0] not in RUNNABLE:
        raise HTTPException(400, f"runnable subcommands: {', '.join(sorted(RUNNABLE))}")
    if any(a == "--lib" or a.startswith("--lib=") for a in run.argv):
        raise HTTPException(400, "the library is the route's, not an argument")
    if run.argv[0] == "reply" and any(a in ("-W", "--watch") for a in run.argv):
        raise HTTPException(400, "reply --watch belongs to the client")


@app.post("/libraries/{user}/{library}/run")
async def run_command(run: Run, root: Path = Depends(library)) -> StreamingResponse:
    _check_run(run)
    lock = lock_for(root)
    if lock.locked():
        raise HTTPException(409, "a run is in progress in this library")
    _may_run(root, run.argv[0])
    await lock.acquire()
    return _stream(root, run.argv, lock)


@app.post("/libraries/{user}/{library}/import")
async def import_file(
    request: Request,
    filename: str,
    only: str | None = None,
    replace: bool = False,
    document_of: str | None = None,
    root: Path = Depends(filed_library),
) -> StreamingResponse:
    """`noesis import` on an uploaded file, kept outside the library while it runs;
    with document_of, as that chat's document."""
    if "/" in filename or "\\" in filename or filename.startswith(".") or not filename.strip():
        raise HTTPException(400, f"a file name, not a path: {filename!r}")
    if document_of is not None:
        chat = PurePosixPath(document_of)
        if chat.is_absolute() or ".." in chat.parts or not chat.name.endswith(".chat.md") \
                or not (root / chat).is_file():
            raise HTTPException(404, f"no chat {document_of!r} in this library")
    from noesis.cmd_import import IMPORTABLE
    if Path(filename).suffix.lower() not in IMPORTABLE:
        raise HTTPException(415, f"import takes Markdown or text, or claude.ai's export ({', '.join(sorted(IMPORTABLE))})")
    lock = lock_for(root)
    if lock.locked():
        raise HTTPException(409, "a run is in progress in this library")
    _may_run(root, "import")
    await lock.acquire()
    try:
        data = await request.body()
        _storable(root, filename, len(data), types=IMPORTABLE)
        staging = Path(tempfile.mkdtemp(prefix="noesis-import-"))
        upload = staging / filename
        upload.write_bytes(data)
    except BaseException:
        lock.release()
        raise
    argv = ["import", str(upload)]
    if only:
        argv += ["--only", only]
    if replace:
        argv.append("--replace")
    if document_of is not None:
        argv += ["--document-of", document_of]
    return _stream(root, argv, lock, cleanup=lambda: shutil.rmtree(staging, ignore_errors=True))


def _stream(root: Path, argv: list[str], lock: asyncio.Lock, cleanup=None) -> StreamingResponse:
    """Runs noesis in the library, whose lock the caller holds, as server-sent events."""
    events: asyncio.Queue = asyncio.Queue()
    task = asyncio.create_task(_execute(root, argv, events, lock, cleanup))
    _runs.add(task)
    task.add_done_callback(_runs.discard)
    from noesis import accounts
    if accounts.is_free(_owner(root)):
        _free_runs.add(task)
        task.add_done_callback(_free_runs.discard)

    async def stream():
        while (event := await events.get()) is not None:
            kind, payload = event
            yield f"event: {kind}\ndata: {json.dumps(payload)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def _execute(root: Path, argv: list[str], events: asyncio.Queue,
                   lock: asyncio.Lock, cleanup=None) -> None:
    from noesis import accounts
    try:
        before = await asyncio.to_thread(tree_hashes, root)
        # No editor either: a run has nobody at a terminal, and `new` opens what
        # it makes in $EDITOR, which on a machine that has one (a test on the
        # Mac) would open it there.
        env = {k: v for k, v in os.environ.items() if k not in ("NOESIS_LIBRARY", "EDITOR", "NOESIS_EDITOR")}
        # NOESIS_RUN_LOCAL: this noesis is the server's, never a client of it.
        # NOESIS_ACCOUNT: whose allowance the run's model calls spend (accounts.py).
        # NOESIS_USER_NAMES: whose voice is whose in the owner's chats.
        owner = _owner(root)
        env.update(NOESIS_USER_NAMES=",".join(accounts.speaker_names(owner)), PYTHONUNBUFFERED="1", NOESIS_RUN_LOCAL="1",
                   NOESIS_ACCOUNT=owner)
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "noesis", "--lib", str(root), *argv,
            cwd=root, env=env,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        while chunk := await process.stdout.read(4096):
            if text := decoder.decode(chunk):
                await events.put(("output", {"text": text}))
        if text := decoder.decode(b"", final=True):
            await events.put(("output", {"text": text}))
        exit_code = await process.wait()
        after = await asyncio.to_thread(tree_hashes, root)
        await events.put(("done", {
            "exit_code": exit_code,
            "changed": {rel: sha for rel, sha in after.items() if before.get(rel) != sha},
            "deleted": sorted(before.keys() - after.keys()),
        }))
    except Exception as exc:  # the stream must end, whatever happened
        await events.put(("error", {"message": str(exc)}))
    finally:
        if cleanup is not None:
            cleanup()
        lock.release()
        await events.put(None)


def run_serve(host: str, port: int) -> int:
    import uvicorn
    uvicorn.run(app, host=host, port=port)
    return 0


# ---------------------------------------------------------------------------
# Sign-in for noesis's OAuth server (oauth.py): an address, then the code mailed to it
# ---------------------------------------------------------------------------

TURNSTILE_VERIFY = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def _client_ip(request: Request) -> str:
    """The person's address: Caddy's X-Forwarded-For, since only Caddy reaches the port."""
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.rsplit(",", 1)[-1].strip() or (request.client.host if request.client else "")


def _human(form: dict, ip: str) -> bool:
    """Cloudflare Turnstile's verdict on the page's challenge; no check without its keys."""
    secret = os.environ.get("NOESIS_TURNSTILE_SECRET")
    if not secret:
        return True
    from urllib.parse import urlencode
    from urllib.request import urlopen
    body = urlencode({"secret": secret, "response": form.get("cf-turnstile-response", ""),
                      "remoteip": ip}).encode()
    try:
        with urlopen(TURNSTILE_VERIFY, data=body, timeout=10) as response:
            return bool(json.loads(response.read()).get("success"))
    except (OSError, ValueError):
        return False


def _login_page(request_id: str, sign_in, error: str = "") -> HTMLResponse:
    from html import escape
    from urllib.parse import urlparse
    from noesis.oauth import IMPORT_SCOPE, WEB_CLIENT_ID, provider
    client_name = escape(sign_in.client.client_name or "An application")
    redirect_host = escape(urlparse(str(sign_in.params.redirect_uri)).hostname or "")
    if sign_in.client.client_id == WEB_CLIENT_ID:
        asks = "to keep your libraries: to read and change them, and to run noesis's commands on them"
    elif provider.identity_only(sign_in.client.client_id):
        asks = "to know who you are: your noesis user name and email address, not your libraries"
    elif IMPORT_SCOPE in (sign_in.params.scopes or []) and provider.imports(sign_in.client.client_id):
        asks = ("to read your noesis libraries, and to add conversations to them when you send one "
                "— with the name you speak under there kept as yours")
    else:
        asks = "to read your noesis libraries"
    note = f'<p class="error">{escape(error)}</p>' if error else ""
    site_key = os.environ.get("NOESIS_TURNSTILE_SITE_KEY", "")
    request_field = f'<input type="hidden" name="request" value="{escape(request_id)}">'
    deny = '<button name="action" value="deny" formnovalidate class="quiet">Deny</button>'
    if sign_in.code_sha:
        form = f"""<p>A code is on its way to <b>{escape(sign_in.email)}</b>. It works for ten minutes.</p>
<form method="post" action="/oauth/login">{request_field}
<label>Code<br><input name="code" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9]{{6}}" maxlength="6" required autofocus></label>
<button name="action" value="verify">Sign in</button><button name="action" value="restart" formnovalidate class="quiet">Use another address</button>{deny}
</form>"""
        script = ""
    else:
        challenge = f'<div class="cf-turnstile" data-sitekey="{escape(site_key)}"></div>' if site_key else ""
        form = f"""<form method="post" action="/oauth/login">{request_field}
<label>Your email address<br><input name="email" type="email" autocomplete="email" required autofocus></label>
{challenge}
<button name="action" value="send">Send me a code</button>{deny}
</form>
<p class="hint">No account yet? Signing in makes one. A free account keeps up to a few libraries,
with a small monthly allowance for noesis's model commands.</p>"""
        script = ('<script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script>'
                  if site_key else "")
    # No form-action: the answer to a sign-in is a redirect to the client.
    csp = ("default-src 'none'; style-src 'unsafe-inline'; script-src https://challenges.cloudflare.com; "
           "frame-src https://challenges.cloudflare.com; connect-src https://challenges.cloudflare.com; "
           "frame-ancestors 'none'; base-uri 'none'")
    return HTMLResponse(f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sign in to noesis</title>{script}
<style>body{{font:16px/1.5 system-ui,sans-serif;max-width:32rem;margin:3rem auto;padding:0 1rem}}
input{{width:100%;font:inherit;padding:.4rem;box-sizing:border-box}}button{{font:inherit;margin:.8rem .6rem 0 0}}
.error{{color:#b00}}.hint{{color:#555;font-size:.9rem}}.cf-turnstile{{margin-top:.8rem}}</style></head><body>
<h1>Sign in to noesis</h1>
<p><b>{client_name}</b> ({redirect_host}) asks {asks}.</p>
{note}{form}
</body></html>""", headers={"Cache-Control": "no-store", "X-Frame-Options": "DENY",
                            "Referrer-Policy": "no-referrer", "Content-Security-Policy": csp})


@app.get("/oauth/login")
def oauth_login(request: str) -> Response:
    from noesis.oauth import provider
    sign_in = provider.pending(request)
    if sign_in is None:
        return PlainTextResponse("This sign-in has expired; start again from the app.", status_code=400)
    return _login_page(request, sign_in)


@app.post("/oauth/login")
async def oauth_login_submit(request: Request) -> Response:
    from urllib.parse import parse_qs
    from noesis.oauth import provider
    form = {k: v[0] for k, v in parse_qs((await request.body()).decode("utf-8", "replace")).items()}
    request_id, action = form.get("request", ""), form.get("action")
    if action == "deny":
        target = provider.refuse(request_id)
        return RedirectResponse(target, status_code=302) if target else PlainTextResponse("Expired.", status_code=400)
    sign_in = provider.pending(request_id)
    if sign_in is None:
        return PlainTextResponse("This sign-in has expired or had too many tries; start again.", status_code=400)
    if action == "restart":
        provider.restart(request_id)
        return _login_page(request_id, sign_in)
    if action == "send":
        ip = _client_ip(request)
        if not await asyncio.to_thread(_human, form, ip):
            return _login_page(request_id, sign_in, error="The check that you are a person did not pass; try again.")
        why = await asyncio.to_thread(provider.send_code, request_id, form.get("email", ""), ip)
        return _login_page(request_id, sign_in, error=why or "")
    if action == "verify":
        target = provider.verify_code(request_id, form.get("code", ""))
        if target is not None:
            return RedirectResponse(target, status_code=302)
        if provider.pending(request_id) is None:
            return PlainTextResponse("Too many wrong codes; start again from the app.", status_code=400)
        return _login_page(request_id, sign_in, error="That is not the code we sent.")
    return PlainTextResponse("Unknown action.", status_code=400)

# ---------------------------------------------------------------------------
# The web client (noesis/web/): static, signed in through the OAuth server above
# ---------------------------------------------------------------------------

_WEB = Path(__file__).resolve().parent / "web"
_WEB_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
              ".css": "text/css; charset=utf-8"}
# The page holds a refresh token, so nothing but this origin's own files may
# run in it, and nobody may frame it.
_WEB_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; img-src 'self' blob: data:; frame-ancestors 'none'; "
                               "base-uri 'none'; form-action 'self'; object-src 'none'",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-cache",
}


# The bare name is where people arrive (rvanegas.co links here); the client
# itself stays at /web/, its OAuth redirect, clear of the MCP and OAuth paths
# mounted at the root. Temporary, so / stays free for something else.
@app.get("/", include_in_schema=False)
def root() -> Response:
    return RedirectResponse("/web/", status_code=302)


@app.get("/web")
def web_root() -> Response:
    return RedirectResponse("/web/", status_code=308)


@app.get("/web/{name}")
@app.get("/web/", include_in_schema=False)
def web_file(name: str = "index.html") -> Response:
    path = _WEB / name
    if "/" in name or name.startswith(".") or path.suffix not in _WEB_TYPES or not path.is_file():
        raise HTTPException(404, "Not Found")
    return Response(path.read_bytes(), media_type=_WEB_TYPES[path.suffix], headers=_WEB_HEADERS)


# Last, so the API's own routes answer first.
app.mount("/", mcp_app)
