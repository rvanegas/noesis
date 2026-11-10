"""noesis's HTTP API, run by `noesis serve` (SERVER.md, Phase 2).

Every route but /healthz and the web client's pages needs a bearer token
(bearer.py): a minted one, which /data/users.toml maps by its SHA-256 to a
user, or to "*" for a service (the nightly index); or an access token from
auth (`auth.rvanegas.co`, where people sign in) carrying `noesis:api` (the
web client's). One carrying `noesis:import` (The Floor) reaches /import and
PUT /me/names alone; an application's own token carrying `noesis:keep` makes
it the owner of the libraries it keeps (members.py).
A user reaches only their own libraries,
/data/libraries/<user>/<library>. A library is files to sync and commands to
run:

- GET    /libraries                          the caller's library ids
- POST   /libraries {name}                   a new library of the caller's, its settings empty
- GET    /libraries/{user}/{library}/files   {rel_path: sha256}
- GET    …/files/{rel_path}                  the bytes, ETag their sha256, Last-Modified their mtime
- HEAD   …/files/{rel_path}                  the same headers, without the bytes
- PUT    …/files/{rel_path}                  If-None-Match: * creates; If-Match: "<sha>" replaces
- DELETE …/files/{rel_path}                  If-Match: "<sha>"; kept thirty days (deletion.py)
- POST   …/run {argv}                        server-sent events: output, then done
- POST   …/import?filename=…[&only=…&replace=true&document_of=…]   the body is the file; as /run
- POST   …/copy {file, to[, names]}          a chat or document into the caller's own library `to`,
                                             their lines theirs; as /import
- GET    /me                                 the caller's account here: plan, spend, storage,
                                             libraries, names, and the client the token was
                                             issued to (any of auth's tokens for a person;
                                             who they are is auth's own /me)
- PUT    /me/names {names}                   the headings that are the caller's voice in chats
- DELETE /users/{user}                       auth's alone (scope noesis:erase): the person deleted
                                             their account, and their libraries go (deletion.py)

/run runs `noesis --lib <library> <argv>` in a subprocess from the library root:
file arguments are names, which noesis resolves across the library. Its output
streams as it is written (reply prints tokens without newlines), and the
last event says which files the run changed or deleted. A run knows the
library owner's voice by the names they keep here (accounts.speaker_names),
in NOESIS_USER_NAMES, whoever starts it: the owner, or the nightly index; a
channel's library has no owner's voice but its members', each their own, in
NOESIS_MEMBERS (members.speakers). One run at a time
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

/web/ serves noesis's web client (noesis/web/): static files, which sign in at
auth and then call this API like any other client.
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
from fastapi.responses import RedirectResponse, StreamingResponse
from mcp.server.auth.provider import AccessToken
from pydantic import BaseModel

from noesis import service
from noesis.service import LibraryError, create_library, library_ids, library_root, lock_for

# Written by ts deploy into the package before the image is built, so it is
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


# What was deleted thirty days ago is removed for good (deletion.py), this often.
SWEEP_SECONDS = 6 * 60 * 60


async def _sweep_forever() -> None:
    from noesis import deletion
    while True:
        try:
            if service.data_dir().is_dir():
                for line in await asyncio.to_thread(deletion.sweep):
                    print(f"deletion: {line}", file=sys.stderr)
        except Exception as exc:
            print(f"deletion: the sweep failed: {exc}", file=sys.stderr)
        await asyncio.sleep(SWEEP_SECONDS)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    sweeping = asyncio.create_task(_sweep_forever())
    try:
        async with mcp_lifespan():
            yield
    finally:
        sweeping.cancel()


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

def _token(authorization: str | None) -> AccessToken:
    """The bearer token's meaning (bearer.py), or 401."""
    from noesis import bearer
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "a bearer token is required")
    token = bearer.access_token(authorization.removeprefix("Bearer "))
    if token is None or not token.subject:
        raise HTTPException(401, "unknown token")
    return token


def _keeping(token: AccessToken) -> str | None:
    """An application that keeps libraries, signed in by its own token: their owner (members.py)."""
    from noesis import bearer, members
    if bearer.KEEP not in (token.scopes or []):
        return None
    owner = members.keeper_for(token)
    if owner is None:
        raise HTTPException(401, "not an application that keeps libraries here")
    return owner


async def caller(authorization: str | None = Header(default=None)) -> str:
    """The user a bearer token belongs to, "*" for a service, or the owner an
    application that keeps libraries signs in as."""
    from noesis import bearer
    token = _token(authorization)
    if owner := _keeping(token):
        return owner
    if bearer.API not in (token.scopes or []):
        raise HTTPException(401, "this token does not reach noesis's API")
    return token.subject


async def anyone(authorization: str | None = Header(default=None)) -> AccessToken:
    """As caller, but any token of a person's: for what they may read about themselves here."""
    from noesis import bearer
    token = _token(authorization)
    if bearer.KEEP in (token.scopes or []):
        raise HTTPException(401, "an application's own token is nobody's")
    return token


def library(user: str, library: str, who: str = Depends(caller)) -> Path:
    try:
        return library_root(user, library, who)
    except LibraryError as exc:
        raise HTTPException(exc.status, str(exc)) from None


async def filer(authorization: str | None = Header(default=None)) -> str:
    """As caller, and also a token granted the import scope (bearer.IMPORT)."""
    from noesis import bearer
    token = _token(authorization)
    if owner := _keeping(token):
        return owner
    if not {bearer.API, bearer.IMPORT} & set(token.scopes or []):
        raise HTTPException(401, "this token does not reach noesis's API")
    return token.subject


def filed_library(user: str, library: str, who: str = Depends(filer)) -> Path:
    """As library, for what an importing application may reach: import, and nothing else."""
    try:
        return library_root(user, library, who)
    except LibraryError as exc:
        raise HTTPException(exc.status, str(exc)) from None


@app.get("/libraries")
def libraries(who: str = Depends(caller)) -> dict:
    # names: what to show for a group's library, whose id says nothing (members.py):
    # its name, or who else is in it.
    return {"libraries": library_ids(who), "names": service.library_names(who)}


class ConsultedLibrary(BaseModel):
    library: str


@app.post("/applications/token")
def consult_token(body: ConsultedLibrary, who: str = Depends(caller)) -> dict:
    """A token for /mcp that reaches one of an application's libraries and
    nothing else, for Claude to consult it with (members.py): The Floor hands
    it to Anthropic's servers at a press of *Ask Claude*."""
    from noesis import bearer, members
    if members.keeper(who) is None:
        raise HTTPException(403, "only an application that keeps libraries")
    try:
        library_root(who, body.library, who)
    except LibraryError as exc:
        raise HTTPException(exc.status, str(exc)) from None
    token, ttl = bearer.confined_token(who, f"{who}/{body.library}")
    return {"access_token": token, "expires_in": ttl}


@app.get("/applications/spending")
def spending(month: str | None = None, who: str = Depends(caller)) -> dict:
    """What each of an application's libraries spent in a month, for it to
    divide among whoever pays in each group (members.py)."""
    from noesis import accounts, members
    if members.keeper(who) is None:
        raise HTTPException(403, "only an application that keeps libraries")
    month = month or accounts.month()
    return {"month": month, "libraries": accounts.spending_under(who, month)}


# Any token of a person's: an application a person connected (The Floor, a
# connector) may say whose library it reaches, which writes nothing. Who they
# are, their address among it, is auth's /me.
@app.get("/me")
def me(token: AccessToken = Depends(anyone)) -> dict:
    from noesis import accounts
    who = token.subject
    free = accounts.is_free(who)
    limits = accounts.limits()
    return {
        "user": who,
        "plan": accounts.plan_of(who),
        "month": accounts.month(),
        "spent_usd": round(accounts.spent(who), 4),
        "allowance_usd": accounts.allowance(who) if free else None,
        "stored_bytes": accounts.stored_bytes(who) if free else None,
        # Which libraries are theirs, so an application can offer a choice of
        # them (The Floor's per-channel toggles); ids as /libraries gives them.
        "libraries": library_ids(who),
        "library_names": service.library_names(who),
        "storage_bytes": limits.storage_bytes if free else None,
        "names": list(accounts.speaker_names(who)),
        "client": token.client_id,
    }


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


def _titles(root: Path, rels) -> dict[str, str]:
    """{rel_path: title} of the chats and documents among rels, as their heads
    say: what an import named what it wrote, which a caller cannot tell from
    the file name, a chat's title being a model's."""
    from noesis.library import _extract_title, role_of
    return {rel: _extract_title((root / rel).read_text(encoding="utf-8", errors="replace"), PurePosixPath(rel).stem)
            for rel in rels if role_of(PurePosixPath(rel).name) in ("chat", "document")}


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


def _metered(root: Path) -> str:
    """Whose meter and limits a library's runs and files count against: its
    owner's, or for an application's group, the library's own (members.py)."""
    from noesis import members
    return members.metered(_owner(root), root.name)


def _storable(root: Path, name: str, size: int, replacing: int = 0, types=None) -> None:
    from noesis import accounts
    why = accounts.storage_refusal(_metered(root), name, size, replacing,
                                   types=types or accounts.FREE_TYPES)
    if why:
        raise HTTPException(413, why)


def _may_run(root: Path, command: str) -> None:
    """A free account's run needs a free slot, and allowance left if it can spend;
    a group's, somebody in it who pays."""
    from noesis import accounts, members
    if command in SPENDING and members.keeper(_owner(root)) is not None:
        found = members.group(_owner(root), root.name)
        if found is None or not found.funded:
            raise HTTPException(402, "nobody in this library's group pays for model use")
    owner = _metered(root)
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
    from noesis import deletion
    deletion.trash(root, path)
    return Response(status_code=204)


@app.delete("/libraries/{user}/{library}")
def delete_library(root: Path = Depends(library), who: str = Depends(caller)) -> Response:
    """An application's library, deleted whole by the application (members.py):
    The Floor's, thirty days after its channel was deleted. Nobody else deletes a
    library here — a person's goes by the operator's hand."""
    from noesis import members
    if members.keeper(who) is None or _owner(root) != who:
        raise HTTPException(403, "only the application whose library it is")
    _writable(root)
    shutil.rmtree(root)
    return Response(status_code=204)


@app.delete("/users/{user}")
def delete_user(user: str, authorization: str | None = Header(default=None)) -> Response:
    """Auth's word that a person deleted their account (dianoia-auth's departures.py):
    their libraries go, kept thirty days for the operator (deletion.py). 204
    whether or not noesis knew them, so auth may say it again."""
    from noesis import bearer, deletion
    token = _token(authorization)
    if token.client_id != bearer.AUTH_CLIENT or bearer.ERASE not in (token.scopes or []):
        raise HTTPException(403, "only auth says who deleted their account")
    if not service.NAME_RE.match(user):
        raise HTTPException(400, "not a user name")
    deletion.delete_user(user)
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
async def run_command(run: Run, root: Path = Depends(library),
                      who: str = Depends(caller)) -> StreamingResponse:
    _check_run(run)
    lock = lock_for(root)
    if lock.locked():
        raise HTTPException(409, "a run is in progress in this library")
    _may_run(root, run.argv[0])
    await lock.acquire()
    return _stream(root, run.argv, lock, who=who)


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
    options = []
    if only:
        options += ["--only", only]
    if replace:
        options.append("--replace")
    if document_of is not None:
        options += ["--document-of", document_of]
    return await _import(root, filename, request.body, options)


async def _import(root: Path, filename: str, body, options: list[str]) -> StreamingResponse:
    """`noesis import` on `await body()`, staged outside the library while it runs."""
    from noesis.cmd_import import IMPORTABLE
    lock = lock_for(root)
    if lock.locked():
        raise HTTPException(409, "a run is in progress in this library")
    _may_run(root, "import")
    await lock.acquire()
    try:
        data = await body()
        _storable(root, filename, len(data), types=IMPORTABLE)
        staging = Path(tempfile.mkdtemp(prefix="noesis-import-"))
        upload = staging / filename
        upload.write_bytes(data)
    except BaseException:
        lock.release()
        raise
    return _stream(root, ["import", str(upload), *options], lock,
                   cleanup=lambda: shutil.rmtree(staging, ignore_errors=True))


class Copy(BaseModel):
    file: str
    to: str
    # The chat's headings the caller says are theirs, once asked (409); [] for none.
    names: list[str] | None = None


def _people(text: str) -> list[str]:
    """A chat's speakers but Prompt and the models: the headings whose voice is in question."""
    from noesis.config import PROMPT_HEADING, load_config
    from noesis.library import _STRUCTURAL_HEADINGS
    from noesis.transcript import HEADING_RE
    skip = {PROMPT_HEADING, *_STRUCTURAL_HEADINGS, *load_config().llm_names}
    return list(dict.fromkeys(m.group(2).strip() for m in HEADING_RE.finditer(text)
                              if m.group(2).strip() not in skip))


@app.post("/libraries/{user}/{library}/copy")
async def copy_file(body: Copy, root: Path = Depends(library), who: str = Depends(caller)) -> StreamingResponse:
    """A chat or a document copied into a library of the caller's own, by
    import, as the caller's: since 2026-11-10, for The Floor's channel
    libraries above all (members.py), whose transcripts belong to nobody.

    **The copier's lines become theirs.** A chat is read by its owner's names
    (accounts.speaker_names), so the copy adds to them the heading the caller
    goes by in the source: in a group's library, the name the application
    gives them. Where none of the chat's people is the caller by either, it
    asks (409, `speakers`) rather than guessing, and is called again with
    `names`, the ones they chose, or none."""
    from noesis import accounts, members
    from noesis.library import role_of
    source = _readable(root, body.file)
    if role_of(source.name) not in ("chat", "document"):
        raise HTTPException(400, "only a chat or a document is copied")
    if who == "*" or members.keeper(who) is not None:
        raise HTTPException(400, "only a person copies into a library of their own")
    try:
        target = library_root(who, body.to, who)
    except LibraryError as exc:
        raise HTTPException(exc.status, str(exc)) from None
    if target == root:
        raise HTTPException(400, "it is already in that library")
    data = source.read_bytes()
    if role_of(source.name) == "chat":
        people = _people(data.decode("utf-8", errors="replace"))
        names = accounts.speaker_names(who)
        group = await asyncio.to_thread(members.speakers, _owner(root), root.name)
        theirs = {h for m in group if m.user == who for h in m.headings}
        known = [h for h in people if h in names or h in theirs]
        if body.names is not None:
            if unknown := [n for n in body.names if n not in people]:
                raise HTTPException(400, f"not a speaker in this chat: {unknown}")
            known = list(dict.fromkeys([*known, *body.names]))
        elif people and not known:
            raise HTTPException(409, {"message": "which of these speakers are you?", "speakers": people})
        if added := [h for h in known if h not in names]:
            try:
                accounts.set_speaker_names(who, [*names, *added])
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from None

    async def read() -> bytes:
        return data
    return await _import(target, source.name, read, [])


def _stream(root: Path, argv: list[str], lock: asyncio.Lock, cleanup=None,
            who: str | None = None) -> StreamingResponse:
    """Runs noesis in the library, whose lock the caller holds, as server-sent events."""
    events: asyncio.Queue = asyncio.Queue()
    task = asyncio.create_task(_execute(root, argv, events, lock, cleanup, who))
    _runs.add(task)
    task.add_done_callback(_runs.discard)
    from noesis import accounts
    if accounts.is_free(_metered(root)):
        _free_runs.add(task)
        task.add_done_callback(_free_runs.discard)

    async def stream():
        while (event := await events.get()) is not None:
            kind, payload = event
            yield f"event: {kind}\ndata: {json.dumps(payload)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def _execute(root: Path, argv: list[str], events: asyncio.Queue,
                   lock: asyncio.Lock, cleanup=None, who: str | None = None) -> None:
    from noesis import accounts
    try:
        before = await asyncio.to_thread(tree_hashes, root)
        # No editor either: a run has nobody at a terminal, and `new` opens what
        # it makes in $EDITOR, which on a machine that has one (a test on the
        # Mac) would open it there.
        env = {k: v for k, v in os.environ.items() if k not in ("NOESIS_LIBRARY", "EDITOR", "NOESIS_EDITOR")}
        # NOESIS_RUN_LOCAL: this noesis is the server's, never a client of it.
        # NOESIS_ACCOUNT: whose allowance the run's model calls spend (accounts.py).
        # NOESIS_USER_NAMES: the owner's headings in a person's chats.
        # NOESIS_MEMBERS: a channel's members, each their own voice (members.speakers).
        # NOESIS_OWNER: a person's library's owner (below).
        # NOESIS_CALLER: who asked for the run, a person, not a service (cmd_export.py).
        from noesis import members
        voices = await asyncio.to_thread(members.voices, _owner(root), root.name)
        speakers = await asyncio.to_thread(members.speakers, _owner(root), root.name)
        # NOESIS_OWNER: a person's library's owner, by their display name at auth,
        # whose stances an argument records (config.people).
        owner = None if speakers else {"user": _owner(root),
                                        "name": await asyncio.to_thread(members.display_name, _owner(root))}
        env.update(NOESIS_USER_NAMES=",".join(voices), PYTHONUNBUFFERED="1", NOESIS_RUN_LOCAL="1",
                   NOESIS_ACCOUNT=_metered(root),
                   NOESIS_MEMBERS=json.dumps([{"user": m.user, "name": m.name, "headings": list(m.headings)}
                                              for m in speakers]),
                   NOESIS_OWNER=json.dumps(owner) if owner else "")
        env.pop("NOESIS_CALLER", None)
        if who and who != "*":
            env["NOESIS_CALLER"] = who
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
        changed = {rel: sha for rel, sha in after.items() if before.get(rel) != sha}
        done = {"exit_code": exit_code, "changed": changed, "deleted": sorted(before.keys() - after.keys())}
        if argv[0] == "import":
            done["titles"] = await asyncio.to_thread(_titles, root, changed)
        await events.put(("done", done))
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
# The web client (noesis/web/): static, signed in at auth
# ---------------------------------------------------------------------------

_WEB = Path(__file__).resolve().parent / "web"
AUTH_PLACEHOLDER = "{{auth}}"
# And Roxana's web app, where an argument already sent opens its discussion.
ROXANA_PLACEHOLDER = "{{roxana}}"
_WEB_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
              ".css": "text/css; charset=utf-8"}
# The page holds a refresh token, so nothing but this origin's own files may
# run in it, and nobody may frame it.
# It signs in at auth, so auth's /token and /revoke are the one other origin
# it may call; index.html names auth for app.js (AUTH_PLACEHOLDER).
_WEB_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; img-src 'self' blob: data:; frame-ancestors 'none'; "
                               "base-uri 'none'; form-action 'self'; object-src 'none'; "
                               "connect-src 'self' {auth}",
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
    from noesis.bearer import auth_url
    body = path.read_bytes()
    if path.suffix == ".html":
        from noesis.config import load_config
        body = body.replace(AUTH_PLACEHOLDER.encode(), auth_url().encode())
        body = body.replace(ROXANA_PLACEHOLDER.encode(), (load_config().roxana_web_url or "").encode())
    headers = {**_WEB_HEADERS, "Content-Security-Policy": _WEB_HEADERS["Content-Security-Policy"].format(auth=auth_url())}
    return Response(body, media_type=_WEB_TYPES[path.suffix], headers=headers)


# Last, so the API's own routes answer first.
app.mount("/", mcp_app)
