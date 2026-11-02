# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

**NOESIS** is a CLI tool for managing hand-edited markdown conversation files — structured transcripts of AI conversations (Claude; older ones also GPT). It validates, fixes, and extends these files by appending AI replies.

## Development Philosophy

No backwards compatibility in code — deprecation shims, compatibility flags, and legacy fallbacks are not welcome. If something changes, change it completely. Data migrations are still required when existing files would otherwise break.

## Development Setup

```bash
pip install -e .          # Install in development mode
python -m noesis --help      # Run via module
noesis --help                # Run via installed command
```

## Commands

```bash
pytest tests/             # Run tests (suite is planned but not yet implemented)
```

No linter is configured. Tests use pytest (`testpaths = ["tests"]` in pyproject.toml).

## Architecture

The tool has two main pipelines: **CLI → Transcript parsing → Format validation → Asset collection → API client** (for conversation files), and **CLI → Library scanning → AI summarization → Index writing** (for the document library).

### Key modules

- **`cli.py`** — the subcommands, among them `index`, `new`, `import`, `check`, `validate`, `fix`, `reply`, `pdf`, `argue`, `analyze`, `audit`, `export`, `sync`, `serve`
- **`cmd_import.py`** — `noesis import`: only text and claude.ai's export (`IMPORTABLE`); claude.ai data exports (zip or `conversations.json`, active branch) saveai.net Markdown (`form._parse_exported_chat`) and The Floor's shared text (`from_the_floor`: a section per speaker as named; titled by `index_model` from what was said, told in the same exchange when its title is taken (`name_conversation`), and known on re-import by its turns; an older file dated by its download name) become `.chat.md`; an noesis chat (named `.chat.md`, or by `## Prompt` or speaker labels) a `.chat.md`; any other text a `.document.md`; any other zip, each `.txt`/`.md` inside; checked in a scratch directory under its own name before it is written, repaired as `fix` would, a chat that still fails written as a document and only what fails even so refused (`settle`), and refused when another file of the library has its title
- **`transcript.py`** — Core parsing: splits markdown into preamble + conversational turns, detects pending human turns awaiting reply, manages reference sections
- **`form.py`** — Enforces the 12-rule transcript format (blank lines, headers, speaker labels, reference formatting, filename derivation); `validate` and `fix` apply it to `.chat.md` alone, and to other files the checks of their role (`cli._form_of`: encoding for all, `argue.check_argument`, `library.check_keys`, a document that reads like a chat named as such); fix leaves what noesis writes alone
- **`assets.py`** — Collects local file references from markdown links (a bare name resolves anywhere in the run's library, beside the transcript first; nothing outside the library), builds API-specific inputs with caching directives
- **`config.py`** — Loads `config.toml` from `NOESIS_CONFIG_DIR` (default `~/.config/noesis`); env fallbacks for keys and service URLs; resolves the run's library (`NOESIS_LIBRARY`) and user names (`NOESIS_USER_NAMES`); builds the system prompt from a base plus the library's `SYSTEM_PROMPT.md`
- **`library.py`** — Library indexing: scans a directory of markdown documents, generates AI summaries and index terms, writes `MANIFEST.md` and `INDEX.md`, reads `KEYS.md` for term canonicalization
- **`accounts.py`**, **`oauth.py`**, **`mail.py`** — the server's identity: open sign-up by emailed code, noesis as the OAuth authorization server for every client (claude.ai, the web client, later The Floor), and what a free account may spend and store; a run's model calls charge `NOESIS_ACCOUNT` (SERVER.md, Phase 6)
- **`anthropic_client.py`** — the streaming model client; noesis uses Anthropic alone (OpenAI and Ollama retired 2026-10-26; `## GPT` headings are still read as LLM voice)

### Data flow for `noesis reply`

1. `cli.py` reads config + transcript file
2. `transcript.py` parses the file and finds the pending human turn
3. `assets.py` collects any local asset references from that turn
4. The appropriate client streams the reply (with token cost output)
5. `transcript.py` appends the reply and writes the file back

### Key design patterns

- **Frozen dataclasses** for core data types (`Turn`, `Transcript`, `Preamble`, `LocalAssetReference`)
- **Streaming via callbacks** — clients accept an `on_delta` callable and print progressively
- **`TranscriptError`** for all validation failures
- **Anthropic prompt caching** — up to 4 cache slots; 3 are allocated to assets
- **Asset uploads** — remote file IDs are cached by content (`asset_cache.py`)
- **Heading promotion** — `##` headings in replies are automatically promoted to `###` to avoid conflicts with the transcript structure

## Transcript Format

Files must satisfy 12 rules enforced by `form.py`:
1. Blank first line
2. `# Title` as first heading
3. `yyyy-mm-dd` date line immediately after title
4. Filename derived from slugified title + date
5. Blank line after the date
6–9. `##` section headers naming the speaker (`Claude`/`GPT`, or any name, spaces allowed: a file's role, not its headings, says it is a chat)
10. References section (if present) must be the final section
11–12. Reference lines formatted as `| Author (year) *Italicized Title*`

## Distribution

To build a wheel for distribution:

```bash
pip install build
python -m build
# produces dist/noesis-0.1.0-py3-none-any.whl
```

Recipients install it with:

```bash
pip install noesis-0.1.0-py3-none-any.whl
# or, recommended for CLI tools:
pipx install noesis-0.1.0-py3-none-any.whl
```

Bump `version` in `pyproject.toml` before each build. The wheel filename reflects that version.

## Library Index

`noesis index [library_path]` scans a directory of markdown documents, calls an AI model to generate summaries and index terms per document, and writes:
- **`MANIFEST.md`** — human-readable document listing with title, word count, terms, and summary per document
- **`INDEX.md`** — inverted term index for use as `reply` context (`-i` flag)

State lives in the library itself, in `.noesis/` (`manifest.json`, `index.json`, `relations.json`), so each library carries its own; only changed documents are re-indexed. `scripts/migrate_library.py` moved it there from `~/.local/state/noesis`.

### KEYS.md

An optional `KEYS.md` in the library directory controls term canonicalization with four sections:

- **`## Plural`** — each line is a canonical term; its plural (`term + "s"`) is auto-aliased to it
- **`## Alias`** — groups of aliases mapping to a canonical: the canonical is a bare line, aliases are `- alias` bullets beneath it
- **`## Exclude`** — terms to suppress from the index entirely
- **`## Group`** — hierarchical grouping: a parent term followed by `- subterm` bullets; subterms appear nested under the parent in `INDEX.md`

### Semantic relations

`noesis relate` builds a relations map between index terms, used by `lookup_term` to suggest adjacent terms during `noesis reply -l`. Several tactics combine to produce it:

- **AI semantic pass** — the model is shown all terms and asked to identify related ones per batch; inclusion criteria cover same-concept-different-angle, broader/narrower forms, frequent co-occurrence in the literature, and morphological variants of the same root
- **Co-occurrence supplementation** — after the AI pass, term pairs that co-occur as document tags in at least 2 documents are automatically added as related; this catches corpus-specific clustering the model might miss by reasoning from general knowledge rather than the actual library
- **KEYS.md Alias** — terms aliased to a canonical are resolved before lookup, so a query for an alias navigates to the canonical's relations transparently

## Roles and Companion Files

Every dated file names its role in a secondary suffix: `YYYY-MM-DD-slug.{role}.{ext}` (`library.role_of`). There are no bare dated files: `check` rejects one, and `index` refuses a library that has any (`scripts/migrate_layout.py` named the roles of `rodvandur/philosophy` from noesis's old guess by headings). Files sharing a stem are companions:

| Role | What it is |
|---|---|
| `.chat.md` | A transcript; drives `noesis reply`, which auto-discovers the `.document.md` and `.argument.md` of its stem |
| `.document.md` | The user's own prose |
| `.source.{ext}` | Third-party material, in any format: a paper, an uploaded markdown file, notes from elsewhere |
| `.argument.md` | A pure numbered list of propositions, extracted by `noesis argue` |
| `.analysis.md` | Per-argument dianoia analysis, produced by `noesis analyze <doc> <proposition>`; never hand-edited |
| `.review.md` | A document's review, written by `noesis review` |

Another format keeps its role: `noesis pdf` turns `x.chat.md` into `x.chat.pdf`. Undated files are the library's own: `KEYS.md`, `SYSTEM_PROMPT.md`, the generated `INDEX.md`/`MANIFEST.md`/…, `ASSESSMENTS/`, `REVISIONS/`.

The library indexer indexes `.chat.md` and `.document.md` (`library.INDEXED_ROLES`), labelling voice by role: a document is the user's own writing, a chat section by section from its speaker headings. Sources are not indexed: the index is of the library author's thought, and a source is someone else's, there only for the documents that cite it (`read_file` reaches it by name).

### Argument files

`.argument.md` files contain exactly one section, `## Argument`, a list of propositions:

```
## Argument
- 1: premise text
- 2 (from: 1): premise text
- 3 (from: 1, 2): conclusion text
```

Proposition numbers are a strict integer succession starting at 1 with no gaps, and are never renumbered once assigned (`validate_proposition_numbering` in `argue.py` enforces this on every AI-driven edit). A proposition with justifiers (a `(from: ...)` clause) is an "argument" — its justifiers are premises, itself the conclusion. `noesis analyze <doc> <proposition>` submits one argument's chain to dianoia and writes the result to `<stem>.analysis.md`, labeling it with a letter (A, B, C, …, Z, AA, …) following Roxana's convention exactly: computed from the proposition's ascending position among all justified propositions, never persisted (`assign_argument_labels` / `_to_alpha_index` in `argue.py`).

`noesis audit <doc>` checks the whole `.argument.md` companion against dianoia's structural conditions (connectivity, order-independence, conclusion legibility) via dianoia's `/argument/audit` route, printing per-finding issues and revision pointers; exits 1 when findings exist.

## Writing Assistant

NOESIS supports a document-editing workflow where the AI reads and rewrites the user's own files rather than just appending replies to the transcript.

### Setup

1. Create a writing session with `noesis new "My Essay" -e`. This produces two files:
   - `YYYY-MM-DD-my-essay.document.md` — the document being written/edited
   - `YYYY-MM-DD-my-essay.chat.md` — the transcript file that drives `noesis reply`

2. When `noesis reply` runs against a `.chat.md` file, it automatically discovers any sibling `.document.md` and `.argument.md` files with the same stem, loads them into the system prompt, and gives the model an `edit_file` tool.

### How it works

- `resolve_edit_targets` (`edit_tools.py`) discovers companion `.document.md` and `.argument.md` files by stripping the `.chat.md` suffix and checking for siblings with those extensions.
- `build_edit_context` injects the target files into the system prompt between `--- filename ---` fences, preceded by editing instructions.
- `make_edit_executor` returns a tool executor for the `edit_file` tool. The tool takes `path`, `old_str`, and `new_str`; the executor does an exact-string replacement and rewrites the file.
- Before the first edit to a file, a numbered backup is saved automatically (`stem--1.ext`, `stem--2.ext`, …).
- After each edit the tool returns a unified diff, which the model uses to confirm what changed.
- `noesis diff <chat-file>` shows the diff between the current document and its most recent backup.

### Paragraph wrapping

Edited content is reflowed via `wrap_paragraphs` at `config.wrap_width` (default 80). Code blocks and lines beginning with `|` (tables/references) are passed through unchanged.

### VOICE labels

When a document is indexed for the library, each section is annotated with a `[VOICE: ...]` label:

- `[VOICE: user]` — direct words of the user
- `[VOICE: llm — collaborative elaboration, implicitly endorsed unless contradicted]` — AI-generated reply sections
- `[VOICE: third-party]` — external sources or quoted voices
- `[VOICE: this entire document is the user's own writing]` — plain documents with no transcript structure

These labels are stripped before sending to the model during `reply` but are present in library context so the model can reason about authorship.

## Server

noesis is moving onto the `commons` box behind `noesis.rvanegas.co` (`SERVER.md`, phase by phase).

- **Where things live.** System-wide: keys (env), the config (`NOESIS_CONFIG_DIR`, `etc/config.toml` in the image) and the asset cache (`NOESIS_CACHE_DIR`, since file IDs belong to the API key). Per user: their names as chat headings (`accounts.speaker_names`, set by `PUT /me/names` or `scripts/accounts.py names`; `Prompt` is always a user heading), given to every run in their libraries as `NOESIS_USER_NAMES` and used by the MCP tools to say whose voice each heading is. Per run: the library (`--lib`, which sets `NOESIS_LIBRARY` for every `load_config()`). Per library, in its tree: `SYSTEM_PROMPT.md`, `KEYS.md`, and index state in `.noesis/`. There is no per-user config on the server; a library's id is `<user>/<library>`, its path `/data/libraries/<user>/<library>`.
- **`noesis serve`** (`server.py`) runs the FastAPI app: `GET /healthz` (open; the commit from `noesis/deployed.json`, stamped by `bin/deploy`), and, behind bearer tokens (minted ones hashed in `$NOESIS_DATA_DIR/users.toml` by `scripts/add_token.py`, or OAuth access tokens issued to the web client, `oauth.API_CLIENTS`; a connector's stay on `/mcp`), `GET /libraries` and `POST /libraries` (a new, empty library of the caller's), file sync under `/libraries/{user}/{library}/files` with HTTP preconditions (`If-None-Match: *`, `If-Match: "<sha>"`; dotfiles hidden, symlinks and escapes refused), `GET /me` and `PUT /me/names`, and `POST …/run`, which runs `noesis --lib <library> <argv>` as a subprocess from the library root and streams its output as server-sent events, ending with the files it changed; and `POST …/import?filename=`, which stages the uploaded body outside the library and runs `noesis import` on it the same way. One run per library at a time (`_locks`); the run outlives its request. `noesis fix --yes` answers fix's questions in advance, since a run has no stdin. `bin/nightly-index` indexes every library through it. `main()` dispatches `serve` before writing a default config.
- **`Dockerfile` / `docker-compose.yml`**: `python:3.13-slim` with pandoc and XeTeX, on `127.0.0.1:8001`, as uid 1000, with `/srv/noesis` mounted at `/data`.
- **`mcp_server.py`** — the MCP server at `/mcp` in `noesis serve` (SERVER.md, Phase 5): `guide` (the instructions as a tool: claude.ai ignores server instructions, so essential rules also live in the tool descriptions), `list_documents`, `lookup_term`, `read_document`, `read_file` — reading only, files returned as they are but for a chat of more speakers than `Prompt` and a model, which comes after one `Voices:` line naming whose each heading is, by the owner's names (`_voiced`; `guide` names the caller's headings too): not `edit_file`, which is `noesis reply`'s alone, and no `append_turn` — claude.ai edits with its own documents, and a conversation reaches the library by its export and `noesis import`, which gathers each turn's `## Related`/`## References` at the end (`transcript.collect_citations`/`with_citations`); bearer tokens checked by the OAuth provider (`oauth.py`): its own access tokens, or a minted noesis token sent as it is; a fresh `MCPServer` per app lifespan behind `_Mount`. `ToolError` for failures the model should read.
- **`web/`** — noesis's web client at `/web/` (SERVER.md, *The web client*): static HTML, JS and CSS, no build step, served under a CSP admitting only its own files. It signs in as the built-in public client `noesis-web` (PKCE; its only redirect is `/web/`) and then uses the files, run and import routes: create a library (with empty `KEYS.md` and `SYSTEM_PROMPT.md`, `library.SETTINGS`), browse, view, download, delete, import, check/validate/fix (fix previews, then applies with `--yes`), index, and a Markdown file's PDF (not listed but fetched from its file's view, made again by `noesis pdf` unless newer than the file, by `Last-Modified`); no upload, no command line, no reply. Only the settings are edited in place (a plain textarea); writing is done in the user's own editor and arrives by import, and sources by the CLI's sync alone. Files noesis writes (the generated uppercase files, records, `.analysis.md`, `.review.md`) open view only.
- **`oauth.py`** — noesis's own OAuth authorization server for claude.ai's connector (Phase 5b) and the web client: the SDK's provider interface, dynamic registration limited to claude.ai/claude.com/localhost redirects, sign-in at `/oauth/login` (in `server.py`) by pasting the person's noesis token, hashed tokens in `$NOESIS_DATA_DIR/oauth.json`, each tied to the noesis token that signed in. Applications with servers of their own (The Floor) are registered by `scripts/add_client.py`; one that only signs people in (Roxana, a browser app) with `--public`, as an identity-only client whose tokens answer `/me` alone (`load_any_access_token`; `/mcp` and the API refuse them), its redirects' origins the only ones `/me` answers by CORS (`browser_origins`). `/me` names the token's client, which dianoia checks before accepting a Roxana caller. `scripts/link_accounts.py` linked Roxana's Cognito users to accounts under their Cognito usernames.
- **`service.py`** — what `/run` and `/mcp` share: `user_for_token`, `library_root`, `library_ids`, the per-library `locks`.
- **`remote.py`** — the CLI as the API's client (Phase 3): in a library mirrored by `[libraries."<id>"] local_root` with `server_url`/`server_token`, `main()` hands `REMOTE_COMMANDS` and `sync` to it. Three-way sync per file against `.noesis/sync.json` (push, pull, or a conflict saved as `<name>.server`, never merged; editor scratch and `.bak` files never synced, either way; a conflict stops a run; a first sync into an empty copy pulls; deleting from the server is asked first, and never done without a terminal), then the run's SSE stream printed as it comes, then a sync back. `NOESIS_RUN_LOCAL` (set by the server's runs) keeps it off.
- **`bin/deploy`**: tests, rsync to `~/noesis` on the box, `docker compose up --build`, then `/healthz` on the box and at the public name. Never touches `.env` or `/srv/noesis`.
- **Library layout** (`SERVER.md`, *Library layout*): names are unique across a library; a dated file lives in its year directory (`library.misplaced`; `check` reports, `fix` moves it with its stem-mates via `library.move_documents`, which carries index state); links name assets bare and resolve library-wide (`assets._AssetScope`); assets are dated by their earliest linking document; the asset cache (`asset_cache.py`, shared by both clients) is keyed by content sha256.
- **`scripts/migrate_library.py`** (the data migration into `.noesis/` and `SYSTEM_PROMPT.md`) and **`scripts/migrate_layout.py`** (the data migration into the year layout; prints its plan unless `--apply`).

## Configuration

Users create `~/.config/noesis/config.toml`:
```toml
model = "claude-sonnet-4-6"
anthropic_api_key = "sk-ant-..."
library_path = "~/notes"
index_model = "claude-haiku-4-5"
```
