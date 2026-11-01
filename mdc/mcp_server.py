"""claude.ai's way into a library: an MCP server at /mcp (SERVER.md, Phase 5).

The reading tools `mdc reply` gives the model, on the caller's libraries, for
Claude anywhere a custom connector reaches (claude.ai on the web and the
phone, Claude Desktop, Claude Code). They run in-process on the server's copy
of the library, which is canonical.

Callers authenticate with a bearer token: an OAuth access token from mdc's
own authorization server (oauth.py; claude.ai's connector signs in there with
the person's mdc token), or a minted mdc token sent as it is (Claude Code).

**Which libraries** (2026-11-01): a grant reaches all of a person's. An
address may narrow a request to some, `/mcp?libraries=<id>,<id>` — The
Floor's per-channel selection, enforced here — and then a search spans every
one open and labels each result. Without it, a person with several names them
in the conversation, and guide and the errors tell Claude to ask.

Nothing here writes. edit_file is `mdc reply`'s alone, and append_turn is
gone: claude.ai edits with its own documents, and a conversation reaches the
library by its export and `mdc import`, which is whole where a turn-by-turn
write depended on Claude remembering to make it.

Files come back as they are. A chat whose headings go beyond Prompt and the
model's comes after one line saying whose voice each heading is: the
library owner's by the names they keep (accounts.speaker_names), the
model's, anyone else's. Without it a chat of several people says nothing of
which of them is the user.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings

from mdc import library as lib
from mdc.oauth import provider
from mdc.service import LibraryError, library_ids, library_root


INSTRUCTIONS = "\n\n".join([
    "These tools reach the user's mdc library: their own writing (chats, documents, "
    "argument files) and the sources they keep. Files are named "
    "<date>-<slug>.<role>.<ext>, the role one of chat, document, source, argument, "
    "analysis, review; a name is unique across the library. Use list_documents to find "
    "names and read_file to read one. Nothing in the library is written from here.",
    lib.LIBRARY_TOOLS_PROMPT,
    "A chat's ## headings name its speakers. A chat with more speakers than Prompt and "
    "a model is read after a 'Voices:' line saying which headings are the user; any "
    "other heading is someone else, however much it sounds like the user.",
])


_TOOLS: list = []


def _tool(fn):
    _TOOLS.append(fn)
    return fn


def build() -> MCPServer:
    """A fresh MCP server: a streamable-HTTP session manager runs only once."""
    server = MCPServer(
        name="mdc",
        title="mdc library",
        instructions=INSTRUCTIONS,
        # mdc is its own authorization server (oauth.py), whose provider also
        # takes a minted mdc token sent as it is.
        auth_server_provider=provider,
        auth=AuthSettings(
            issuer_url=public_url(),
            resource_server_url=f"{public_url()}/mcp",
            validate_token_resource=False,  # the provider knows its tokens
            client_registration_options=ClientRegistrationOptions(enabled=True),
            revocation_options=RevocationOptions(enabled=True),
        ),
    )
    for fn in _TOOLS:
        server.add_tool(fn)
    return server


def public_url() -> str:
    return os.environ.get("MDC_PUBLIC_URL", "https://mdc.rvanegas.co").rstrip("/")


class _Mount:
    """The ASGI app mounted in mdc serve; forwards to this lifespan's MCP app."""

    def __init__(self) -> None:
        self.app = None

    async def __call__(self, scope, receive, send) -> None:
        if self.app is None:  # not started (or stopped): nothing is here
            from starlette.responses import PlainTextResponse
            await PlainTextResponse("Not Found", status_code=404)(scope, receive, send)
            return
        await self.app(scope, receive, send)


mcp_app = _Mount()


@asynccontextmanager
async def mcp_lifespan():
    server = build()
    mcp_app.app = server.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[public_url().split("://", 1)[1], "127.0.0.1:*", "localhost:*", "testserver"],
            allowed_origins=["https://claude.ai", "https://claude.com"],
        ),
    )
    async with server.session_manager.run():
        try:
            yield
        finally:
            mcp_app.app = None


# ---------------------------------------------------------------------------
# The caller's library
# ---------------------------------------------------------------------------

def _caller() -> str:
    token = get_access_token()
    if token is None or not token.subject:
        raise ToolError("not authenticated")
    return token.subject


def _open_to(ctx: Context | None) -> list[str]:
    """The caller's libraries this request may read: all of them, or those its
    address names in `?libraries=` (ids, comma-separated) — how The Floor
    passes a channel's selection, so mdc rather than a prompt enforces it.
    A claude.ai connector names none, and its person names them in the
    conversation instead (guide)."""
    ids = library_ids(_caller())
    request = getattr(ctx.request_context, "request", None) if ctx is not None else None
    raw = request.query_params.get("libraries") if request is not None else None
    if raw is None:
        return ids
    named = {part.strip() for part in raw.split(",") if part.strip()}
    return [i for i in ids if i in named]


def _restricted(ctx: Context | None) -> bool:
    request = getattr(ctx.request_context, "request", None) if ctx is not None else None
    return request is not None and "libraries" in request.query_params


def _roots(library: str | None, ctx: Context | None, many: bool) -> list[tuple[str, Path]]:
    """The libraries a tool reads: the one named, else every one open to this
    request where a search may span several (`many`), else the only one."""
    who = _caller()
    ids = _open_to(ctx)
    if library is not None:
        if library not in ids:
            raise ToolError(f"not a library open to this conversation: {library!r}; "
                            f"open: {', '.join(ids) or 'none'}")
        ids = [library]
    elif not ids:
        raise ToolError("no library is open to this conversation" if _restricted(ctx)
                        else "this user has no library yet")
    elif len(ids) > 1 and not many:
        raise ToolError(f"name the library: one of {', '.join(ids)} — the one a search gave")
    elif len(ids) > 1 and not _restricted(ctx):
        # claude.ai: the person chooses, in the conversation.
        raise ToolError(f"this user keeps several libraries: {', '.join(ids)}. Use the ones they "
                        "named in this conversation, passing each as library; if they named "
                        "none, ask them which before searching")
    roots = []
    for lib_id in ids:
        user, _, name = lib_id.partition("/")
        try:
            roots.append((lib_id, library_root(user, name, who)))
        except LibraryError as exc:
            raise ToolError(str(exc)) from None
    return roots


def _root(library: str | None, ctx: Context | None = None) -> Path:
    return _roots(library, ctx, many=False)[0][1]


def _voiced(root: Path, name: str, text: str) -> str:
    """A chat of more than Prompt and a model, after a line saying whose each heading is."""
    from mdc import accounts
    from mdc.config import PROMPT_HEADING, load_config
    from mdc.library import _STRUCTURAL_HEADINGS
    from mdc.transcript import HEADING_RE
    if lib.role_of(name) != "chat":
        return text
    speakers = list(dict.fromkeys(
        m.group(2).strip() for m in HEADING_RE.finditer(text) if m.group(2).strip() not in _STRUCTURAL_HEADINGS))
    llm = set(load_config().llm_names)
    if set(speakers) <= {PROMPT_HEADING} | llm:
        return text
    mine = {PROMPT_HEADING, *accounts.speaker_names(root.parent.name)}

    def headings(group: list[str], one: str, many: str) -> str:
        return f"{', '.join(f'## {s}' for s in group)} {one if len(group) == 1 else many}"

    users = [s for s in speakers if s in mine]
    models = [s for s in speakers if s in llm]
    others = [s for s in speakers if s not in mine and s not in llm]
    parts = [headings(users, "is the user", "are the user") if users else "no heading is the user"]
    if models:
        parts.append(headings(models, "is a model", "are models"))
    if others:
        parts.append(headings(others, "is someone else", "are other people"))
    return f"Voices: {'; '.join(parts)}.\n" + text


def _find(root: Path, name: str) -> Path:
    from mdc.cli import _library_files
    if "/" in name or name.startswith("."):
        raise ToolError(f"a file is named, not pathed: {name!r}")
    found = [p for p in _library_files(root) if p.name == name]
    if not found:
        raise ToolError(f"no file named {name!r} in the library")
    return found[0]


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@_tool
def guide(ctx: Context) -> str:
    """The user's mdc library: read this once per conversation, before the other
    mdc tools. How the library is organized, which of the user's libraries to
    use, how to find and cite its documents, and which voices in a chat are
    the user's."""
    from mdc import accounts
    from mdc.config import PROMPT_HEADING
    who = _caller()
    if who == "*":
        return INSTRUCTIONS
    open_ids = _open_to(ctx)
    if _restricted(ctx):
        which = (f"This conversation may read these libraries: {', '.join(open_ids)}. "
                 "list_documents and lookup_term search all of them and say which each "
                 "result is in; read_document and read_file take that library."
                 if open_ids else "No library is open to this conversation.")
    elif len(open_ids) > 1:
        which = (f"This user keeps several libraries: {', '.join(open_ids)}. Use only the ones "
                 "they name in the conversation, passing each as the tools' library; if they "
                 "have named none, ask which before searching.")
    else:
        which = f"This user's library: {open_ids[0]}." if open_ids else "This user has no library yet."
    names = ", ".join(f"## {n}" for n in (PROMPT_HEADING, *accounts.speaker_names(who)))
    return (f"{INSTRUCTIONS}\n\n{which}\n\nIn this user's chats, the sections headed {names} are the "
            "user's own words. A section under any other name is someone else's, the "
            "model's or another person's, even where it sounds like the user.")


@_tool
def list_documents(ctx: Context, query: str = "", library: str | None = None) -> str:
    """List the library's indexed documents: name and title, newest first. With a
    query, only those whose title, summary or index terms match it, best first.
    Files are named <date>-<slug>.<role>.<ext> (role: chat, document, source, argument, analysis or review; e.g. 2026-06-29-the-eleatic-critique.chat.md), kept in a folder per year, and a name is unique across the library. Call guide first if you have not."""
    roots = _roots(library, ctx, many=True)
    lines = []
    for lib_id, root in roots:
        entries = lib.load_entries(root)
        if query:
            entries = lib.search_library(entries, query)
        else:
            entries = sorted(entries, key=lambda e: Path(e.rel_path).name, reverse=True)
        where = f" [{lib_id}]" if len(roots) > 1 else ""
        lines += [f"{Path(e.rel_path).name} — {e.title}{where}" for e in entries[:200]]
    return "\n".join(lines) if lines else "No documents found."


@_tool
def lookup_term(ctx: Context, term: str, library: str | None = None) -> str:
    """Look up an index term: the documents that carry it, with summaries, and
    related terms to follow. Look up every plausibly relevant term before
    answering; the documents are the user's own writing, dated, and later ones
    may supersede earlier. Call guide first if you have not."""
    roots = _roots(library, ctx, many=True)
    if len(roots) == 1:
        return lib.lookup_term(roots[0][1], term)
    return "\n\n".join(f"# Library {lib_id}\n\n{lib.lookup_term(root, term)}" for lib_id, root in roots)


@_tool
def read_document(ctx: Context, path: str, library: str | None = None) -> str:
    """Read an indexed document in full, by the path lookup_term gives (e.g.
    2026/<name>). A chat of several people comes after a 'Voices:' line
    saying which headings are the user. Cite a library document only after
    reading it, under a '## Related' section, one per line as '| *Exact Title*'."""
    root = _root(library, ctx)
    text = lib.read_document(root, path)
    target = (root / path).resolve()
    if not (target.is_relative_to(root.resolve()) and target.is_file()):
        found = lib.resolve_title(root, path)
        if found is None:
            return text
        target = root / found
    return _voiced(root, target.name, text)


@_tool
def read_file(ctx: Context, name: str, library: str | None = None) -> str:
    """Read any text file of the library by its name. Files are named <date>-<slug>.<role>.<ext> (role: chat, document, source, argument, analysis or review; e.g. 2026-06-29-the-eleatic-critique.chat.md), kept in a folder per year, and a name is unique across the library. A source is
    third-party material, not the user's writing, and is not indexed: it is
    reached by name from the documents that cite it. An analysis or review is
    written by mdc. A chat of several people comes after a 'Voices:' line
    saying which headings are the user."""
    root = _root(library, ctx)
    path = _find(root, name)
    try:
        return _voiced(root, name, path.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        return f"{name} is not text (a {path.suffix} file); it can be linked from a chat, not read here."
