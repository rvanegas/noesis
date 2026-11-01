"""mdc's HTTP API, run by `mdc serve` (SERVER.md, Phase 2).

Every route but /healthz and the web client's pages needs a bearer token:
a minted one, which /data/users.toml maps by its SHA-256 to a user, or to "*"
for a service (the nightly index); or an OAuth access token issued to mdc's
own web client (oauth.API_CLIENTS). A user reaches only their own libraries,
/data/libraries/<user>/<library>. A library is files to sync and commands to
run:

- GET    /libraries                          the caller's library ids
- POST   /libraries {name}                   a new, empty library of the caller's
- GET    /libraries/{user}/{library}/files   {rel_path: sha256}
- GET    …/files/{rel_path}                  the bytes, ETag their sha256
- PUT    …/files/{rel_path}                  If-None-Match: * creates; If-Match: "<sha>" replaces
- DELETE …/files/{rel_path}                  If-Match: "<sha>"
- POST   …/run {argv, user_names}            server-sent events: output, then done
- POST   …/import?filename=…[&only=…&replace=true]   the body is the file; as /run

/run runs `mdc --lib <library> <argv>` in a subprocess from the library root:
file arguments are names, which mdc resolves across the library. Its output
streams as it is written (reply prints tokens without newlines), and the
last event says which files the run changed or deleted. One run at a time
per library; while it runs, writes to the library get 409. The run belongs
to the server, not the request: a client that goes away does not cut it short.

/import is how a conversation from elsewhere enters a library without a
client's own copy of it (a claude.ai export, saveai.net Markdown, any text):
the upload is kept outside the library, `mdc import` writes from it into the
year directories, and it is deleted when the run ends.

Dotfiles, and so the index state in .mdc/, are never listed, read or written.

/web/ serves mdc's web client (mdc/web/): static files, which sign in through
mdc's OAuth server and then call this API like any other client.
"""

from __future__ import annotations

import asyncio
import codecs
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path, PurePosixPath

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel

from mdc import service
from mdc.service import LibraryError, create_library, library_ids, library_root, lock_for

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
# A name is a speaker heading, so any words; MDC_USER_NAMES is comma-separated.
_USER_NAME_RE = re.compile(r"^[^\s,](?:[^,\n\r]*[^\s,])?$")

_runs: set[asyncio.Task] = set()

# The MCP server (SERVER.md, Phase 5) answers at /mcp, mounted below the
# API's routes; its session manager lives as long as the app.
from mdc.mcp_server import mcp_app, mcp_lifespan


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    async with mcp_lifespan():
        yield


app = FastAPI(title="mdc", lifespan=_lifespan)


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
    from mdc.oauth import API_CLIENTS, provider
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "a bearer token is required")
    token = await provider.load_access_token(authorization.removeprefix("Bearer "))
    if token is None or token.client_id not in API_CLIENTS or not token.subject:
        raise HTTPException(401, "unknown token")
    return token.subject


def library(user: str, library: str, who: str = Depends(caller)) -> Path:
    try:
        return library_root(user, library, who)
    except LibraryError as exc:
        raise HTTPException(exc.status, str(exc)) from None


@app.get("/libraries")
def libraries(who: str = Depends(caller)) -> dict:
    return {"libraries": library_ids(who)}


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


def _writable(root: Path) -> None:
    lock = service.locks.get(root)
    if lock is not None and lock.locked():
        raise HTTPException(409, "a run is in progress in this library")


@app.get("/libraries/{user}/{library}/files")
def list_files(root: Path = Depends(library)) -> dict:
    return {"files": tree_hashes(root)}


@app.get("/libraries/{user}/{library}/files/{rel_path:path}")
def read_file(rel_path: str, root: Path = Depends(library)) -> Response:
    path = _file(root, rel_path)
    if not path.is_file():
        raise HTTPException(404, "no such file")
    data = path.read_bytes()
    return Response(data, media_type="application/octet-stream",
                    headers={"ETag": _etag(hashlib.sha256(data).hexdigest())})


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
    user_names: list[str] = []


def _check_run(run: Run) -> None:
    if not run.argv or run.argv[0] not in RUNNABLE:
        raise HTTPException(400, f"runnable subcommands: {', '.join(sorted(RUNNABLE))}")
    if any(a == "--lib" or a.startswith("--lib=") for a in run.argv):
        raise HTTPException(400, "the library is the route's, not an argument")
    if run.argv[0] == "reply" and any(a in ("-W", "--watch") for a in run.argv):
        raise HTTPException(400, "reply --watch belongs to the client")
    bad = [n for n in run.user_names if not _USER_NAME_RE.match(n)]
    if bad:
        raise HTTPException(400, f"a user name has no comma, line break, or space at either end: {bad}")


@app.post("/libraries/{user}/{library}/run")
async def run_command(run: Run, root: Path = Depends(library)) -> StreamingResponse:
    _check_run(run)
    lock = lock_for(root)
    if lock.locked():
        raise HTTPException(409, "a run is in progress in this library")
    await lock.acquire()
    return _stream(root, run.argv, run.user_names, lock)


@app.post("/libraries/{user}/{library}/import")
async def import_file(
    request: Request,
    filename: str,
    only: str | None = None,
    replace: bool = False,
    root: Path = Depends(library),
) -> StreamingResponse:
    """`mdc import` on an uploaded file, kept outside the library while it runs."""
    if "/" in filename or "\\" in filename or filename.startswith(".") or not filename.strip():
        raise HTTPException(400, f"a file name, not a path: {filename!r}")
    lock = lock_for(root)
    if lock.locked():
        raise HTTPException(409, "a run is in progress in this library")
    await lock.acquire()
    try:
        data = await request.body()
        staging = Path(tempfile.mkdtemp(prefix="mdc-import-"))
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
    return _stream(root, argv, [], lock, cleanup=lambda: shutil.rmtree(staging, ignore_errors=True))


def _stream(root: Path, argv: list[str], user_names: list[str], lock: asyncio.Lock,
            cleanup=None) -> StreamingResponse:
    """Runs mdc in the library, whose lock the caller holds, as server-sent events."""
    events: asyncio.Queue = asyncio.Queue()
    task = asyncio.create_task(_execute(root, argv, user_names, events, lock, cleanup))
    _runs.add(task)
    task.add_done_callback(_runs.discard)

    async def stream():
        while (event := await events.get()) is not None:
            kind, payload = event
            yield f"event: {kind}\ndata: {json.dumps(payload)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def _execute(root: Path, argv: list[str], user_names: list[str], events: asyncio.Queue,
                   lock: asyncio.Lock, cleanup=None) -> None:
    try:
        before = await asyncio.to_thread(tree_hashes, root)
        env = {k: v for k, v in os.environ.items() if k != "MDC_LIBRARY"}
        # MDC_RUN_LOCAL: this mdc is the server's, never a client of it.
        env.update(MDC_USER_NAMES=",".join(user_names), PYTHONUNBUFFERED="1", MDC_RUN_LOCAL="1")
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "mdc", "--lib", str(root), *argv,
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
# Sign-in for mdc's OAuth server (oauth.py): claude.ai sends the person here
# ---------------------------------------------------------------------------

def _login_page(request_id: str, client_name: str, redirect_host: str, error: str = "") -> HTMLResponse:
    from html import escape
    note = f'<p class="error">{escape(error)}</p>' if error else ""
    return HTMLResponse(f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sign in to mdc</title>
<style>body{{font:16px/1.5 system-ui,sans-serif;max-width:32rem;margin:3rem auto;padding:0 1rem}}
input{{width:100%;font:inherit;padding:.4rem;box-sizing:border-box}}button{{font:inherit;margin:.8rem .6rem 0 0}}
.error{{color:#b00}}</style></head><body>
<h1>Sign in to mdc</h1>
<p><b>{escape(client_name)}</b> ({escape(redirect_host)}) asks to use your mdc libraries:
to read them and to edit their documents.</p>
{note}
<form method="post" action="/oauth/login">
<input type="hidden" name="request" value="{escape(request_id)}">
<label>Your mdc token<br><input name="token" type="password" autocomplete="off" required autofocus></label>
<button name="action" value="allow">Allow</button><button name="action" value="deny" formnovalidate>Deny</button>
</form></body></html>""", headers={"Cache-Control": "no-store", "X-Frame-Options": "DENY"})


@app.get("/oauth/login")
def oauth_login(request: str) -> Response:
    from urllib.parse import urlparse
    from mdc.oauth import provider
    sign_in = provider.pending(request)
    if sign_in is None:
        return PlainTextResponse("This sign-in has expired; start again from the app.", status_code=400)
    return _login_page(request, sign_in.client.client_name or "An application",
                       urlparse(str(sign_in.params.redirect_uri)).hostname or "")


@app.post("/oauth/login")
async def oauth_login_submit(request: Request) -> Response:
    from urllib.parse import parse_qs, urlparse
    from mdc.oauth import provider
    form = {k: v[0] for k, v in parse_qs((await request.body()).decode("utf-8", "replace")).items()}
    request_id = form.get("request", "")
    if form.get("action") == "deny":
        target = provider.refuse(request_id)
        return RedirectResponse(target, status_code=302) if target else PlainTextResponse("Expired.", status_code=400)
    sign_in = provider.pending(request_id)
    if sign_in is None:
        return PlainTextResponse("This sign-in has expired or had too many tries; start again.", status_code=400)
    target = provider.complete(request_id, form.get("token", ""))
    if target is None:
        return _login_page(request_id, sign_in.client.client_name or "An application",
                           urlparse(str(sign_in.params.redirect_uri)).hostname or "",
                           error="That is not an mdc token.")
    return RedirectResponse(target, status_code=302)


# ---------------------------------------------------------------------------
# The web client (mdc/web/): static, signed in through the OAuth server above
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
