"""claude.ai's way into a library: an MCP server at /mcp (SERVER.md, Phase 5).

The reading tools `noesis reply` gives the model, on the caller's libraries, for
Claude anywhere a custom connector reaches (claude.ai on the web and the
phone, Claude Desktop, Claude Code). They run in-process on the server's copy
of the library, which is canonical.

Callers authenticate with a bearer token carrying `noesis:read` (bearer.py):
an access token from auth (`auth.rvanegas.co`), where claude.ai's connector
signs the person in, or a minted noesis token sent as it is (Claude Code).

**Which libraries** (2026-11-01): a grant reaches all of a person's. An
address may narrow a request to some, `/mcp?libraries=<id>,<id>` — The
Floor's per-channel selection, enforced here — and then a search spans every
one open and labels each result. Without it, a person with several names them
in the conversation, and guide and the errors tell Claude to ask. They list
each by its id and by the name the id slugs (2026-11-11, `_named`): a person
calls a library "Philosophy", and a channel's by the channel's name.

Nothing here writes. edit_file is `noesis reply`'s alone, and append_turn is
gone: claude.ai edits with its own documents, and a conversation reaches the
library by its export and `noesis import`, which is whole where a turn-by-turn
write depended on Claude remembering to make it.

Files come back as they are. A chat whose headings go beyond Prompt and the
model's comes after one line saying whose voice each heading is: the
library owner's by the names they keep (accounts.speaker_names), the
model's, anyone else's. In a channel's library the user is whoever reads,
and each other member is named as one, speaking for themselves (_heard).
Without it a chat of several people says nothing of which of them is the
user.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings

from noesis import library as lib
from noesis import members
from noesis import bearer
from noesis.service import LibraryError, library_ids, library_names, library_root


INSTRUCTIONS = "\n\n".join([
    "These tools reach the user's noesis library: their own writing (chats, documents, "
    "argument files) and the sources they keep. Files are named "
    "<date>-<slug>.<role>.<ext>, the role one of chat, document, source, argument, "
    "analysis, review; a name is unique across the library, and so is a slug. Use "
    "list_documents to find names and read_file to read one. Nothing in the library is written from here.",
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
        name="noesis",
        title="noesis library",
        instructions=INSTRUCTIONS,
        # auth is the authorization server; noesis checks its tokens, and its
        # own minted and confined ones (bearer.py), and names auth in its
        # protected-resource metadata.
        token_verifier=bearer.Verifier(),
        auth=AuthSettings(
            issuer_url=bearer.auth_url(),
            resource_server_url=f"{public_url()}/mcp",
            required_scopes=[bearer.READ],
            validate_token_resource=False,  # bearer.py checks the audience
        ),
    )
    for fn in _TOOLS:
        server.add_tool(fn)
    return server


def public_url() -> str:
    return os.environ.get("NOESIS_PUBLIC_URL", "https://noesis.rvanegas.co").rstrip("/")


class _Mount:
    """The ASGI app mounted in noesis serve; forwards to this lifespan's MCP app."""

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
    passes a channel's selection, so noesis rather than a prompt enforces it.
    A claude.ai connector names none, and its person names them in the
    conversation instead (guide)."""
    ids = library_ids(_caller())
    # A token confined to one library (bearer.confined_token, an application's
    # for Claude) reaches that one whatever the address says.
    from noesis.bearer import LIBRARY_SCOPE
    token = get_access_token()
    confined = {s.removeprefix(LIBRARY_SCOPE) for s in (token.scopes or []) if s.startswith(LIBRARY_SCOPE)}
    if confined:
        ids = [i for i in ids if i in confined]
    request = getattr(ctx.request_context, "request", None) if ctx is not None else None
    raw = request.query_params.get("libraries") if request is not None else None
    if raw is None:
        return ids
    named = {part.strip() for part in raw.split(",") if part.strip()}
    return [i for i in ids if i in named]


def _named(ids: list[str], who: str) -> str:
    """Libraries as the model is told of them: each id, the thing a tool takes,
    and the name its people call it, of which the id is the slug
    (library_names: one's own by the name it was made with, a channel's by
    the channel's)."""
    names = library_names(who) if who != "*" else {}
    return ", ".join(f'{i} ("{names[i]}")' if names.get(i) else i for i in ids) or "none"


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
                            f"open: {_named(ids, who)}")
        ids = [library]
    elif not ids:
        raise ToolError("no library is open to this conversation" if _restricted(ctx)
                        else "this user has no library yet")
    elif len(ids) > 1 and not many:
        raise ToolError(f"name the library: one of {_named(ids, who)} — the one a search gave")
    elif len(ids) > 1 and not _restricted(ctx):
        # claude.ai: the person chooses, in the conversation.
        raise ToolError(f"this user keeps several libraries: {_named(ids, who)}. Use the ones they "
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


def _heard(owner: str, library: str, reader: str) -> tuple[set[str], set[str]]:
    """The headings that are the reader's own, and those of a channel's other
    members: in a person's library the owner's names are the user's, and in a
    channel's only the reader's are, each other member being their own voice."""
    from noesis.config import PROMPT_HEADING
    group = members.speakers(owner, library)
    if not group:
        return {PROMPT_HEADING, *members.voices(owner, library)}, set()
    me = next((m for m in group if m.user == reader), None)
    mine = {PROMPT_HEADING, *(me.headings if me else ())}
    return mine, {h for m in group if m is not me for h in m.headings} - mine


def _voiced(root: Path, name: str, text: str, reader: str) -> str:
    """A chat of more than Prompt and a model, after a line saying whose each heading is."""
    from noesis.config import PROMPT_HEADING, load_config
    from noesis.library import _STRUCTURAL_HEADINGS
    from noesis.transcript import HEADING_RE
    if lib.role_of(name) != "chat":
        return text
    speakers = list(dict.fromkeys(
        m.group(2).strip() for m in HEADING_RE.finditer(text) if m.group(2).strip() not in _STRUCTURAL_HEADINGS))
    llm = set(load_config().llm_names)
    if set(speakers) <= {PROMPT_HEADING} | llm:
        return text
    mine, fellows = _heard(root.parent.name, root.name, reader)

    def headings(group: list[str], one: str, many: str) -> str:
        return f"{', '.join(f'## {s}' for s in group)} {one if len(group) == 1 else many}"

    users = [s for s in speakers if s in mine]
    models = [s for s in speakers if s in llm]
    members_ = [s for s in speakers if s in fellows and s not in llm]
    others = [s for s in speakers if s not in mine and s not in llm and s not in fellows]
    parts = [headings(users, "is the user", "are the user") if users else "no heading is the user"]
    if members_:
        parts.append(headings(members_, "is another member of the channel, speaking for themselves",
                              "are other members of the channel, each speaking for themselves"))
    if models:
        parts.append(headings(models, "is a model", "are models"))
    if others:
        parts.append(headings(others, "is someone else", "are other people"))
    return f"Voices: {'; '.join(parts)}.\n" + text


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@_tool
def guide(ctx: Context) -> str:
    """The user's noesis library: read this once per conversation, before the other
    noesis tools. How the library is organized, which of the user's libraries to
    use, how to find and cite its documents, and which voices in a chat are
    the user's."""
    from noesis import accounts
    from noesis.config import PROMPT_HEADING
    who = _caller()
    if who == "*":
        return INSTRUCTIONS
    open_ids = _open_to(ctx)
    if _restricted(ctx):
        which = (f"This conversation may read these libraries: {_named(open_ids, who)}. "
                 "list_documents and lookup_term search all of them and say which each "
                 "result is in; read_file takes that library."
                 if open_ids else "No library is open to this conversation.")
    elif len(open_ids) > 1:
        which = (f"This user keeps several libraries: {_named(open_ids, who)}. Use only the ones "
                 "they name in the conversation, passing each as the tools' library; if they "
                 "have named none, ask which before searching.")
    else:
        which = f"This user's library: {_named(open_ids, who)}." if open_ids else "This user has no library yet."
    if any(library_names(who).get(i) for i in open_ids):
        which += (" A quoted name after a library's id is what its people call it, which is "
                  "how the user may name it; the tools take the id.")
    # One library's voices where only one is open — in a channel's, the
    # caller's and the other members' (_heard) — else the caller's own names.
    if len(open_ids) == 1:
        mine, fellows = _heard(*open_ids[0].split("/", 1), who)
    else:
        mine, fellows = {PROMPT_HEADING, *accounts.speaker_names(who)}, set()
    names = ", ".join(f"## {n}" for n in (PROMPT_HEADING, *sorted(mine - {PROMPT_HEADING})))
    said = (f"{INSTRUCTIONS}\n\n{which}\n\nIn this user's chats, the sections headed {names} are the "
            "user's own words. ")
    if fellows:
        said += (f"This library is a channel's: the sections headed "
                 f"{', '.join(f'## {n}' for n in sorted(fellows))} are its other members', each "
                 "speaking for themselves, and its documents are Claude's account of what each "
                 "member thinks, naming them. ")
    return said + ("A section under any other name is someone else's, the "
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
def read_file(ctx: Context, name: str, library: str | None = None) -> str:
    """Read any file of the library in full: by its name (e.g.
    2026-06-29-the-eleatic-critique.chat.md), its stem
    (2026-06-29-the-eleatic-critique), its slug (the-eleatic-critique) or its
    title, any directory before it ignored. A stem, slug or title reads its
    document, else its chat, source, argument, analysis or review, in that
    order; the result names the companions, the other files of its stem, each
    read by its name. A source is third-party material, not the user's
    writing. An analysis or review is written by noesis. A chat of several
    people comes after a 'Voices:' line saying which headings are the user.
    Cite a chat or document only after reading it, under a '## Related'
    section, one per line as '| *Exact Title*'."""
    root = _root(library, ctx)
    try:
        return lib.read_file(root, name, voiced=lambda found, text: _voiced(root, found, text, _caller()))
    except lib.NotFound as exc:
        raise ToolError(str(exc)) from None
