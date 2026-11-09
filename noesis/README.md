# noesis

A CLI tool for managing hand-edited markdown conversation files — structured transcripts of AI conversations that you can edit, validate, and extend with live AI replies.

## Format

Each transcript is a plain `.md` file with a title, date, and labeled sections for each speaker:

```markdown

# My Question About Sorting Algorithms
2026-04-16

## Prompt

What is the difference between quicksort and mergesort?

## Claude

Quicksort and mergesort are both comparison-based sorting algorithms...
```

Files are human-editable at any point. Add a new `## Prompt` section, run `noesis reply`, and the AI's response is appended automatically.

## Installation

Requires Python 3.11+.

```bash
# From a wheel (recommended for distribution):
pipx install noesis-0.1.0-py3-none-any.whl

# From source:
pip install -e .
```

## Configuration

On first run, noesis writes a starter config to `~/.config/noesis/config.toml`. Edit it to suit your setup. `NOESIS_CONFIG_DIR` and `NOESIS_CACHE_DIR` move the config and cache directories elsewhere (the server sets both).

```toml
# ~/.config/noesis/config.toml

# Model used by "noesis reply". Required unless passed via --model each time.
model = "claude-sonnet-4-6"

# API key. Can also be set via the ANTHROPIC_API_KEY env var.
anthropic_api_key = "sk-ant-..."

# Directory of markdown files to use as a knowledge library (see "noesis index").
# Its SYSTEM_PROMPT.md, if any, is added to every reply's system prompt.
library_path = "~/notes"

# Model used by "noesis index". Default: claude-haiku-4-5.
index_model = "claude-haiku-4-5"

# Column width for paragraph wrapping in "noesis reply" edits. Default: 100.
wrap_width = 100

# Your name as a section heading, treated as your own voice beside "Prompt",
# which always is. NOESIS_USER_NAMES (comma-separated) overrides it for one run.
# On the server your names are kept with you instead (Your names, in the web
# client), and this is not sent.
user_names = ["YourName"]

# Section headings treated as LLM voice.
llm_names = ["Claude", "GPT"]

```

Run `noesis config` to print the resolved config file, cache directory, library, and the library's state directory.

## Global flags

| Flag | Description |
|------|-------------|
| `--lib PATH` | The library for a single invocation, overriding `NOESIS_LIBRARY` and `library_path` from config. Accepted before any subcommand: `noesis --lib ~/alt-notes index`. |

---

## Commands

### `noesis new`

Create a new transcript file in the current directory. The filename is derived from the title and today's date (`YYYY-MM-DD-slugified-title.md`). If `$EDITOR` is set, opens the new file(s) immediately.

```bash
noesis new                            # creates 2026-04-24-untitled.md
noesis new -t "My Question"           # creates 2026-04-24-my-question.md
noesis new -t "My Essay" --edit       # creates the essay file + an editor transcript
```

| Flag | Description |
|------|-------------|
| `-t`, `--title TITLE` | Title of the conversation. Defaults to `Untitled`. |
| `-e`, `--edit` | Also create a paired editor transcript (see [Writing assistant](#writing-assistant)). |

---

### `noesis reply`

Append one AI reply to a transcript. Finds the last unanswered human turn, streams the reply to stdout, and writes it to the file. A numbered backup of the previous file contents is saved automatically (`stem--1.md`, `stem--2.md`, …).

```bash
noesis reply conversation.md
noesis reply -m claude-opus-5-5 conversation.md
noesis reply -v -l -t "sorting algorithms" conversation.md
```

| Flag | Description |
|------|-------------|
| `path` | Path to the transcript. |
| `-m`, `--model MODEL` | Anthropic model to use (e.g. `claude-sonnet-4-6`). Overrides config. |
| `-r`, `--reasoning-effort` | `none` / `low` / `medium` / `high` / `xhigh`. Default: `low`. |
| `-v`, `--verbose` | Print progress messages and token usage / cost. |
| `-W`, `--watch` | Poll the transcript once per second and reply whenever a pending turn appears. Useful when editing in another window. |
| `-w`, `--web` | Enable Anthropic server-side web search and fetch. |
| `-l`, `--library` | Give the model access to the library index tools (`lookup_term`, `read_file`). Requires `library_path` in config. |
| `-t`, `--term TERM` | Pre-look up a library index term and inject the results into context before the model runs. Requires `-l`. May be repeated. |
| `--strict` | Abort if any `-t` term is not found in the index (default: warn and proceed). |

**Models:** Anthropic only (any `claude-*` model). `## GPT` turns in older transcripts are still read as the model's voice.

Local file references in markdown links (e.g. `[data](./data.csv)`) are collected and sent as context, with prompt caching. Uploaded files are cached by content, so a moved or renamed file is not uploaded again.

---

### `noesis check`

Validate a transcript's structure and report whether a reply is pending.

```bash
noesis check conversation.md
# OK: transcript is valid, 2 local asset(s) resolved, and a reply is pending for 'Prompt'.
```

| Argument | Description |
|----------|-------------|
| `path` | Path to the transcript. |

Exits 0 on success, 1 on any error.

In a library, names are unique, and so are slugs (`check`, `index`, `new` and `import` refuse a slug another date has), so a link names an asset bare (`[Parfit](2026-10-19-parfit2011.pdf)`) and finds it wherever the library keeps it, beside the transcript first; nothing outside the library is read. A dated file belongs in the year directory its name gives (`2026/2026-06-29-the-eleatic-critique.md`): `check` reports one that is elsewhere, and `noesis fix` moves it there with its companions.

---

### `noesis validate`

Run all format rules on one or more files and report violations.

```bash
noesis validate conversation.chat.md
noesis validate *.md
```

| Flag | Description |
|------|-------------|
| `file.md ...` | One or more files to check. |

The rules are the file's role's, from its name:

| File | Checked for |
|------|-------------|
| `.chat.md` | The transcript format (all twelve rules); in a library, `## Related` titles that resolve and precede it |
| `.document.md` | Encoding (`U+FFFC`, `[char]{dir="rtl"}`); and whether it reads like a chat, which would make its role `.chat.md` |
| `.source.md`, `SYSTEM_PROMPT.md`, other `.md` | Encoding |
| `.argument.md` | Encoding; one `## Argument` section, propositions numbered 1..N in plain integers |
| `KEYS.md` | Encoding; known sections (Plural, Alias, Exclude, Group), bullets only under a term in Alias and Group |
| `.analysis.md`, `.review.md`, generated files, `REVISIONS/`, `ASSESSMENTS/` | Encoding |

Exits 0 only if all files pass.

---

### `noesis fix`

Auto-fix correctable format violations. Shows a unified diff of proposed changes and prompts for confirmation before modifying each file. Outside a library, a `.bak` backup is created before writing; inside one, none is.

```bash
noesis fix conversation.md
noesis fix *.md
```

| Argument | Description |
|----------|-------------|
| `file.md ...` | One or more files to fix. |

Every file's encoding is repaired: `U+FFFC` (object replacement character) and `[char]{dir="rtl"}` pandoc RTL spans. Only a `.chat.md` takes a transcript's repairs: exported chats converted, missing blank lines around the title section and sections, `## ChatGPT` headers renamed to `## GPT`. A dated file elsewhere is moved into its year directory. What noesis writes (`.analysis.md`, `.review.md`, generated files, records) is left alone.

---

### `noesis diff`

Show changes made to a document by the most recent `noesis reply` edit. Compares the current file against its backup revisions and colorizes the output when running in a terminal.

```bash
noesis diff essay.md                # show the most recent change
noesis diff essay.md -d 2           # show the 2nd-most-recent change
noesis diff essay.md -r 3           # diff revision 3 against current
noesis diff essay.md -- -w          # pass -w (ignore whitespace) to diff
```

| Flag | Description |
|------|-------------|
| `path` | Path to the edited document (not the editor transcript). |
| `-r N`, `--revision N` | Diff backup revision N against the current file. |
| `-d N`, `--delta N` | Show the Nth most recent change. Default: 1 (most recent). |
| `-- ...` | Any trailing arguments after `--` are passed directly to the system `diff` command. |

---

### `noesis edit`

Open a file in `$EDITOR`. If `$EDITOR` is not set, prints the resolved path.

```bash
noesis edit conversation.md
```

| Argument | Description |
|----------|-------------|
| `path` | Path to the markdown file. Abbreviations are expanded as with other commands. |

---

### `noesis argue`

Extract a structured logical argument from a plain document, or evaluate a companion argument file via the dianoia API.

```bash
noesis argue essay.md              # extract argument → essay.argument.md
noesis argue essay.md              # (run again) evaluate the companion
noesis argue essay.argument.md     # evaluate directly
noesis argue essay.md P3           # evaluate only step P3 and its justifiers
```

On first run (no companion `.argument.md` exists), noesis calls dianoia to extract the argument from the document and writes `<stem>.argument.md`. Edit that file, then run again to submit it for evaluation.

On subsequent runs (companion exists), noesis submits the argument file to dianoia for formal and content evaluation and writes the results back into the companion.

| Argument | Description |
|----------|-------------|
| `path` | Plain document or companion `.argument.md` file. |
| `STEP` | Optional. Evaluate only this step and its direct justifiers. Requires a companion. |
| `-v`, `--verbose` | Show extra detail. |
| `-m N`, `--max-props N` | Maximum number of propositions passed to dianoia extract. |

### `noesis export`

Send a document's argument to Roxana as a new public discussion: its propositions, its arguments, and any analyses in `<stem>.analysis.md`. The web client's *Send to Roxana* runs it. The conclusion of the whole argument, its last proposition, is set as the sender's goal: by the noesis name Roxana knows them by, which a run on the server takes from who asked for it and one on the Mac from `roxana_user` in the config.

```bash
noesis export essay.md             # send essay.argument.md; prints the discussion's address
noesis export essay.md --new       # changed since it was sent: start another discussion
noesis export essay.md -n          # show what would be sent, sending nothing
```

A discussion in Roxana belongs to no one: anyone in it may accept or reject any proposition or argument. So noesis never replaces one. What it sent is recorded in the library's `.noesis/exports.json`; sending an unchanged argument again names the discussion it already has, and sending a changed one is refused until `--new`, which starts another discussion and keeps the earlier one's id.

---

### `noesis index`

Build or update the library document index. Scans `library_path` (or a path you supply), calls an AI model to generate a summary and index terms for each document, and writes two files into the library directory:

- **`MANIFEST.md`** — human-readable listing: title, word count, terms, and summary per document.
- **`INDEX.md`** — inverted term index for use as context during `noesis reply -l`.

State is cached; only changed documents are re-indexed on subsequent runs.

```bash
noesis index                        # use library_path from config
noesis --lib ~/notes index          # explicit path
noesis index --all                  # reindex everything from scratch
noesis index --refs-only-all        # extract references only, no AI calls
```

| Flag | Description |
|------|-------------|
| `--all` | Reindex all documents and rebuild all semantic relations from scratch. |
| `--refs-only-all` | Extract references from all documents without making any AI calls. |

After indexing, noesis automatically builds a **semantic relations map** between index terms so that `lookup_term` can suggest adjacent terms. Relations are derived from an AI semantic pass plus co-occurrence analysis of document tags.

#### KEYS.md

Place an optional `KEYS.md` in the library directory to control term canonicalization:

```markdown
## Plural
belief
concept

## Alias
free will
- freedom of the will
- libertarian free will

## Exclude
the
conversation

## Group
epistemology
- knowledge
- justification
- reliabilism
```

- **Plural** — each listed term's plural form (`term + "s"`) is auto-aliased to it.
- **Alias** — canonical term on a bare line; aliases as `- alias` bullets beneath it.
- **Exclude** — suppress these terms from the index entirely.
- **Group** — subterms appear nested under the parent in `INDEX.md`.

---

### `noesis review`

Run a staged AI review over an indexed document collection. Works in segments: each run processes one segment of documents, writes an interim assessment, and saves state so subsequent runs can resume. After all segments are done, it generates per-document reviews of the most-mentioned works and a final assessment.

Output files written to the library directory:

- **`REVIEW.md`** — full review: interim assessments and final synthesis.
- **`ASSESSMENT.md`** — final assessment only (extracted for quick reference).
- **`REVIEWS.md`** — individual per-document reviews only.
- **`ASSESSMENT.pdf`** / **`REVIEWS.pdf`** — PDF versions of the above (requires pandoc).

```bash
noesis review                              # use library_path from config
noesis --lib ~/notes review                # explicit path
noesis review --dry-run                    # show what would run without making API calls
noesis review --reset                      # discard saved state and start over
noesis review --since 2025-03-01-title.md  # re-review from this document onward
noesis review --rebuild                    # regenerate output files from saved state, no API calls
```

The review pauses between the segment pass and the final assessment to let you edit `REVIEW_INCLUDE.md`, which controls which documents receive individual reviews in the final pass.

| Flag | Description |
|------|-------------|
| `--reset` | Discard saved state and output files; start from scratch. |
| `--since DOC` | Re-review from the named document onward, rewinding state to the nearest segment boundary. |
| `--dry-run` | Show segments and document counts without making any API calls. |
| `--no-assessment` | Print doc reviews and save state but skip assessments; do not write output files. |
| `--rebuild` | Rebuild all output files from saved state without making API calls. |

#### REVIEW_INCLUDE.md

After all segments finish, noesis writes `REVIEW_INCLUDE.md` to the library directory containing the document titles extracted from the interim assessments. Edit this file to add or remove titles, then run `noesis review` again to proceed with the final per-document review pass.

#### Custom prompts

Place Markdown files in `~/.config/noesis/review/` to override the built-in prompts:

| File | Overrides |
|------|-----------|
| `system.md` | System prompt for all review calls |
| `interim.md` | Prompt for segment assessments |
| `final.md` | Prompt for the final synthesis |

---

### `noesis pdf`

Convert a markdown file to PDF via [pandoc](https://pandoc.org/) (must be installed separately), then open the result.

```bash
noesis pdf conversation.md          # convert and open
noesis pdf --quiet conversation.md  # convert without opening
```

| Flag | Description |
|------|-------------|
| `path` | Path to the markdown file. |
| `-q`, `--quiet` | Do not open the PDF after conversion. |

---

### `noesis config`

Print the resolved paths for configuration and data files, then exit.

```bash
noesis config
# Config file:   /Users/you/.config/noesis/config.toml
# Cache dir:     /Users/you/.cache/noesis
# Library:       /Users/you/notes
# Library state: /Users/you/notes/.noesis
```

---

### `noesis files`

Manage files uploaded to the Anthropic Files API.

```bash
noesis files ls                     # list files on the server
```

`noesis files ls` queries the Anthropic server directly and prints each file's ID, upload date, size, and filename.

---

### `noesis serve`

Run noesis's HTTP API with uvicorn. It is how noesis runs on the server (`SERVER.md`); on the Mac there is no reason to start it.

```bash
noesis serve                          # 127.0.0.1:8001
noesis serve --host 0.0.0.0 --port 8001
```

`GET /healthz` is open. Everything else needs `Authorization: Bearer <token>`, either an access token from auth (`auth.rvanegas.co`, where the web client signs in by an emailed code) carrying `noesis:api`, or one minted by `scripts/add_token.py` for the CLI and scripts, and works on the caller's libraries, `$NOESIS_DATA_DIR/libraries/<user>/<library>`:

```bash
curl -H "Authorization: Bearer $T" https://noesis.rvanegas.co/libraries
curl -H "Authorization: Bearer $T" https://noesis.rvanegas.co/libraries/rodvandur/philosophy/files
curl -N -H "Authorization: Bearer $T" -H "Content-Type: application/json" \
  -d '{"argv": ["reply", "eleatic"]}' \
  https://noesis.rvanegas.co/libraries/rodvandur/philosophy/run
```

**Claude as a client (MCP).** `/mcp` serves `reply`'s reading tools (`list_documents`, `lookup_term`, `read_file`) to MCP clients, and writes nothing: `edit_file` stays with `reply`. In claude.ai, edit with its own documents, and bring a conversation into the library with its export and `noesis import`. Claude Code sends the token as a header: `claude mcp add --transport http noesis https://noesis.rvanegas.co/mcp --header "Authorization: Bearer <token>"`. claude.ai's custom connector (Settings → Connectors → Add custom connector) needs only the URL, `https://noesis.rvanegas.co/mcp`: noesis names auth as its authorization server, so claude.ai registers itself there and opens auth's sign-in page, where you give your email address and then the code mailed to it (the first sign-in makes your account, the same one for noesis, Roxana and The Floor); claude.ai then holds short-lived tokens that reach `/mcp` alone. Anyone may sign up this way, and gets libraries of their own.

`PUT …/files/{path}` creates a file with `If-None-Match: *` and replaces one with `If-Match: "<sha256>"`; `DELETE` takes `If-Match`. `run` streams `output` events and ends with `done`: the exit code and the files the run changed or deleted — and, for an import, `titles`, each chat or document it wrote by the title it was given, a chat from The Floor's being a model's.

### `noesis import`

Turn conversations held elsewhere into library files, written into this year's directory like `noesis new`:

```bash
noesis import ~/Downloads/data-2026-10-27.zip                 # every claude.ai conversation
noesis import conversations.json --only "Being and Seeming"   # one, by name or uuid
noesis import 2026-08-03-verbal-disputes.md                   # a saveai.net export
noesis import notes-on-quine.md                               # anything else: a .document.md
noesis import draft.md --document-of 2026/2026-05-01-on-names.chat.md   # a chat's document
```

| Input | Becomes |
|---|---|
| claude.ai's data export (Settings → Privacy → Export data), the zip or its `conversations.json` | one `<date>-<slug>.chat.md` per conversation, its turns exactly as exported, along the branch shown last when messages were edited; attachments and tool calls noted as `\| [attachment: …]` / `\| [tool: …]` |
| a saveai.net (AI Chat Exporter) Markdown export | a `.chat.md` |
| anything else | a `.document.md`, its text as it is |

Headings inside a turn are promoted to `###`, as `reply` does. Each file is checked (`check` for a chat, the global checks for a document) before it is written. A file that already exists is skipped; `--replace` overwrites it.

`--document-of` brings in one text as a chat's document, `<stem>.document.md` beside the chat, as `noesis new --edit` pairs them: the position a conversation came to, written elsewhere (with Claude in claude.ai, or in an editor), from which `argue` then extracts the argument. It keeps its own `# Title` if it has one, else takes the chat's, and takes the chat's date. In the web client, a chat without a document offers *Import its document*.

### `noesis sync` and the server

With noesis's server configured, the model-backed commands (`reply`, `index`, `argue`, `analyze`, `audit`, `export`, `pdf`, `review`, `files`) run there, on its keys, and this machine holds none:

```toml
# ~/.config/noesis/config.toml
server_url = "https://noesis.rvanegas.co"
server_token = "..."          # minted on the server by scripts/add_token.py

[libraries."rodvandur/philosophy"]
local_root = "~/Documents/Writing/Chats"
```

In a mirrored library each such command syncs the library with the server's copy, runs there with its output streaming here, and syncs the results back. `noesis sync` syncs alone. `check`, `validate`, `fix`, `new`, `edit` and `diff` stay local.

Sync never merges. A file changed both here and on the server since they last agreed is a conflict: the server's version is saved beside yours as `<name>.server`, and a run will not start until it is settled. Delete the `.server` copy to keep yours (the next sync sends it), or replace yours with it.

## Editor Integration

The `editors/` directory contains plugins for Emacs and Sublime Text. Both auto-activate on any file whose name matches the NOESIS convention (`yyyy-mm-dd-*.md`).

### Emacs

Add to your init file (`~/.emacs.d/init.el` or `~/.emacs`):

```elisp
(add-to-list 'load-path "~/src/noesis/editors/emacs")
(require 'noesis)
(add-hook 'find-file-hook #'noesis-maybe-enable)
```

Key bindings (active in `noesis-mode`):

| Key | Command |
|-----|---------|
| `C-c C-r` | `noesis reply` |
| `C-c C-f` | `noesis fix` |
| `C-c C-k` | `noesis check` |
| `C-c C-v` | `noesis validate` |
| `C-c C-n` | New transcript |
| `C-c C-e` | Jump to the input section (last human turn) |
| `M-n` / `M-p` | Next / previous turn |

### Sublime Text

Symlink (or copy) the package directory into Sublime's `Packages` folder, then restart:

```bash
# macOS
ln -s ~/src/noesis/editors/sublime \
      ~/Library/Application\ Support/Sublime\ Text/Packages/noesis

# Linux
ln -s ~/src/noesis/editors/sublime \
      ~/.config/sublime-text/Packages/noesis
```

Commands are available via the command palette (`Cmd+Shift+P`, search `NOESIS`) and under **Tools → NOESIS**. Key bindings mirror the Emacs ones (`Ctrl+C, Ctrl+R/F/K/V`); `Alt+↑`/`Alt+↓` navigate between turns.

---

## Format Rules

Files must satisfy these rules, enforced by `noesis validate` and auto-fixed where possible by `noesis fix`:

1. Blank first line.
2. `# Title` as the first heading.
3. `yyyy-mm-dd` date line immediately after the title.
4. Filename derived from the slugified title and date (e.g. `2026-04-16-my-title.md`).
5. Blank line after the date.
6. `##` section headers with non-empty labels.
7. Use `## GPT` not `## ChatGPT`.
8. Each section preceded and followed by a blank line.
9. `## Notes` (if present) must come before `## Related`; `## Related` (if present) must come before `## References`; `## References` must be the final section.
10. Reference lines: `| Last, First (year) *Italicized Title*`.
11. Multi-author: `| Last1, First1, First2 Last2, ... (year) *Title*`.
12. Note lines: `| [n] Text` with n consecutive starting from 1.

---

## Writing Assistant

`noesis reply` supports an editing workflow where the AI rewrites your own document rather than just appending to the transcript.

### Setup

```bash
noesis new -t "My Essay" --edit
# creates: 2026-04-24-my-essay.document.md  ← the document
#          2026-04-24-my-essay.chat.md       ← the transcript that drives reply
```

When `noesis reply` runs against a `.chat.md` file, it automatically discovers any sibling `.document.md` and `.argument.md` companions with the same stem, loads them into the system prompt, and gives the model an `edit_file` tool.

### How edits work

- The model calls `edit_file` with `path`, `old_str`, and `new_str`; noesis does an exact-string replacement and rewrites the document.
- A numbered backup is saved before the first edit to each file (`stem--1.md`, `stem--2.md`, …).
- After each edit the tool returns a unified diff so the model can confirm what changed.
- Edited prose is reflowed to `wrap_width` columns (default 100). Code blocks and table/reference lines beginning with `|` are passed through unchanged.

Use `noesis diff essay.md` to review the changes the AI made.
