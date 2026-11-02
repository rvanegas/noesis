"""noesis import: conversations held elsewhere become library files (SERVER.md, Phase 4).

- claude.ai's data export (the zip, or its conversations.json): each
  conversation becomes `<date>-<slug>.chat.md`, its turns exactly as exported,
  following the active branch when messages were edited — except that each
  turn's `## Related` and `## References` are gathered into one of each at
  the end, as `reply` keeps them.
- saveai.net exports (the "AI Chat Exporter" Markdown `noesis fix` converts:
  `# you asked` / `# claude response` blocks): a `.chat.md`.
- The Floor's shared text (a segment of a spoken conversation: `The Floor —
  <channel>`, a dated line of hours, then `<name> · <time>` blocks): a
  `.chat.md`, a section per speaker as named. A channel's sittings share its
  name, so the title is the index model's, from what was said, and asked
  for again in the same exchange while the one it gives is taken; one
  imported before is known by its turns, and keeps the title it was given.
  A file from before the text named its channel and date takes both from
  its download name, `The Floor — <channel> — <yyyy-mm-dd hhmm>`. A paste
  stays its author's, quoted; Claude's is Claude's turn.
- An noesis chat: a file named `.chat.md`, or one with `## Prompt` sections
  or speaker labels (`Prompt:`), its title and date as written.
- A zip that is not claude.ai's: each `.txt` and `.md` inside, as on its own.
- Any other text: a `.document.md`, its text as it is.

Nothing else is imported (IMPORTABLE): a source reaches the library by the
CLI's sync alone.

Files go where their names put them, this year's directory of the library
(or the current directory outside one). Each is checked before it takes its
name, and repaired as `noesis fix` would; a chat that still fails becomes a
document of the same text, and only what fails even as a document is
refused. An existing one is skipped unless --replace. A title another file
of the library already has fails: `## Related` names a file by its title.
"""

from __future__ import annotations

import datetime
import json
import re
import tempfile
import zipfile
from dataclasses import dataclass, replace as with_fields
from pathlib import Path, PurePath

from noesis.config import ASSISTANT_NAME, PROMPT_HEADING, load_config
from noesis.form import (
    _parse_exported_chat, check_file, fix_object_replacement, fix_rtl_spans, fix_section_spacing,
    fix_title_section, has_bare_labels, is_exported_chat, slugify,
)
from noesis.text_utils import _upgrade_reply_headings
from noesis.transcript import collect_citations, with_citations


# What import reads: text, and claude.ai's export (its zip or json).
IMPORTABLE = frozenset({".md", ".markdown", ".txt", ".zip", ".json"})


@dataclass
class Imported:
    title: str
    date: str
    role: str  # "chat" or "document"
    body: str  # everything after the title and date
    untitled: bool = False  # the title is a hint, and one is to be given


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

def _claude_conversations(data: object) -> list[dict] | None:
    if isinstance(data, list) and data and all(isinstance(c, dict) and "chat_messages" in c for c in data):
        return data
    return None


def _active_branch(messages: list[dict], leaf: str | None) -> list[dict]:
    """The messages of the branch shown last, when the export says which."""
    by_uuid = {m.get("uuid"): m for m in messages}
    if not leaf or leaf not in by_uuid or not any(m.get("parent_message_uuid") for m in messages):
        return messages
    branch, current = [], by_uuid.get(leaf)
    while current is not None:
        branch.append(current)
        current = by_uuid.get(current.get("parent_message_uuid"))
    return list(reversed(branch))


def _message_text(message: dict) -> str:
    parts: list[str] = []
    blocks = message.get("content")
    if isinstance(blocks, list) and blocks:
        for block in blocks:
            kind = block.get("type")
            if kind == "text" and block.get("text", "").strip():
                parts.append(block["text"].strip())
            elif kind == "tool_use":
                parts.append(f"| [tool: {block.get('name', 'tool')}]")
    elif str(message.get("text", "")).strip():
        parts.append(str(message["text"]).strip())
    for attachment in message.get("attachments") or []:
        parts.append(f"| [attachment: {attachment.get('file_name', 'file')}]")
    for file in message.get("files") or []:
        parts.append(f"| [file: {file.get('file_name', 'file')}]")
    return "\n\n".join(parts)


def _turns_text(turns: list[tuple[str, str]]) -> str:
    """`## <speaker>` sections, consecutive turns of one speaker joined.

    A turn's own '## Related' and '## References' (reply's convention, which
    claude.ai follows through the MCP guide) are taken out of it and gathered
    into one of each at the end, as reply keeps them.
    """
    merged: list[tuple[str, str]] = []
    related: list[str] = []
    references: list[str] = []
    for speaker, text in turns:
        text, cited, refs = collect_citations(_upgrade_reply_headings(text))
        related += cited
        references += refs
        text = text.strip()
        if not text:
            continue
        if merged and merged[-1][0] == speaker:
            merged[-1] = (speaker, merged[-1][1] + "\n\n" + text)
        else:
            merged.append((speaker, text))
    body = "\n\n".join(f"## {speaker}\n\n{text}" for speaker, text in merged)
    return with_citations(body, related, references).strip("\n")


def from_claude_conversation(conversation: dict) -> Imported | None:
    messages = _active_branch(conversation.get("chat_messages") or [], conversation.get("current_leaf_message_uuid"))
    turns = []
    for message in messages:
        text = _message_text(message)
        if text:
            speaker = PROMPT_HEADING if message.get("sender") == "human" else ASSISTANT_NAME
            turns.append((speaker, text))
    if not turns:
        return None
    title = str(conversation.get("name") or "").strip() or "Untitled"
    date = str(conversation.get("created_at") or "")[:10] or datetime.date.today().isoformat()
    return Imported(title, date, "chat", _turns_text(turns))


def from_saveai(text: str, name: PurePath, date: str) -> Imported | None:
    messages = _parse_exported_chat(text)
    if not messages:
        return None
    stem = name.stem
    dated = stem[:10] if len(stem) > 11 and stem[4] == "-" and stem[7] == "-" and stem[10] == "-" else None
    title_stem = stem[11:] if dated else stem
    date = dated or next((ts for _, ts, _ in messages if ts), None) or date
    title = title_stem.replace("-", " ").replace("_", " ").strip().title() or "Untitled"
    turns = [(header.removeprefix("## "), content) for header, _, content in messages]
    return Imported(title, date, "chat", _turns_text(turns))


_FLOOR_NAME_RE = re.compile(r"^The Floor — (?P<channel>.+) — (?P<date>\d{4}-\d{2}-\d{2}) \d{4}$")
_FLOOR_HEAD_RE = re.compile(r"^The Floor — (?P<channel>.+)$")
_FLOOR_HOURS_RE = re.compile(r"^(?:(?P<date>\d{4}-\d{2}-\d{2})|[^·]+) · \S.*[–-].+$")
_FLOOR_ENTRY_RE = re.compile(
    r"^(?P<who>.+) · \d{1,2}[:.]\d{2}(?:[\s\u202f]*[ap]\.?[\s\u202f]?m\.?)?$", re.IGNORECASE)
_FLOOR_PASTED = ("Pasted by ", "Pegado por ")


def from_the_floor(text: str, name: PurePath, date: str) -> Imported | None:
    """The Floor's shared text of one segment, or None if this is not one."""
    blocks = [b for b in re.split(r"\n[ \t]*\n", text.replace("\r\n", "\n").strip()) if b.strip()]
    if len(blocks) < 2:
        return None
    head = blocks[0].splitlines()
    named = _FLOOR_NAME_RE.match(name.stem)
    channel = named["channel"] if named else None
    if len(head) == 2 and (m := _FLOOR_HEAD_RE.match(head[0])):
        channel = m["channel"].strip()
        head = head[1:]
    hours = _FLOOR_HOURS_RE.match(head[0]) if len(head) == 1 else None
    if not hours or not channel:
        return None
    date = hours["date"] or (named["date"] if named else date)
    turns: list[tuple[str, str]] = []
    for block in blocks[1:]:
        first, _, rest = block.partition("\n")
        entry = _FLOOR_ENTRY_RE.match(first.strip())
        if entry is None:
            if not turns:
                return None
            # A paste's own blank lines.
            speaker, said = turns[-1]
            turns[-1] = (speaker, f"{said}\n\n{_quoted(block) if said.startswith('>') else block}")
            continue
        who = entry["who"].strip()
        pasted = next((who[len(p):].strip() for p in _FLOOR_PASTED if who.startswith(p)), None)
        if pasted == ASSISTANT_NAME:
            turns.append((ASSISTANT_NAME, rest))
        elif pasted is not None:
            turns.append((pasted or "Someone", _quoted(rest)))
        else:
            turns.append(("Someone" if who == "null" else who, rest))
    if not turns:
        return None
    return Imported(channel, date, "chat", _turns_text(turns), untitled=True)


def _quoted(text: str) -> str:
    return "\n".join(f"> {line}" if line.strip() else ">" for line in text.splitlines())


_DATE_LINE_RE = re.compile(r"^\*?(\d{4}-\d{2}-\d{2})\*?$")
_DATED_STEM_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-(.+)$")
_PROMPT_SECTION_RE = re.compile(rf"^## {PROMPT_HEADING}\s*$", re.MULTILINE)


def _stem(name: PurePath) -> str:
    """The name without its extension and role: `x.chat.md` is `x`."""
    stem = name.stem
    return stem.rsplit(".", 1)[0] if PurePath(stem).suffix in (".chat", ".document") else stem


def _headed(text: str, name: PurePath, date: str, role: str) -> Imported:
    """A file as it is, its title and date taken from its head as noesis writes
    them (`# Title`, then the date), else from its name."""
    lines = text.strip("\n").splitlines()
    dated = _DATED_STEM_RE.match(_stem(name))
    date = dated[1] if dated else date
    title = None
    if lines and lines[0].startswith("# "):
        title = lines.pop(0)[2:].strip()
        if lines and (line := _DATE_LINE_RE.match(lines[0].strip())):
            date = line[1]
            lines.pop(0)
    words = dated[2] if dated else _stem(name)
    title = title or words.replace("-", " ").replace("_", " ").strip().title() or "Untitled"
    return Imported(title, date, role, "\n".join(lines).strip("\n"))


def is_noesis_chat(text: str, name: PurePath) -> bool:
    """Named a chat, or one by its speakers; a file named a document is one."""
    if name.name.endswith(".document.md"):
        return False
    return name.name.endswith(".chat.md") or bool(_PROMPT_SECTION_RE.search(text)) or has_bare_labels(text)


def as_document(text: str, name: PurePath, date: str) -> Imported:
    return _headed(text, name, date, "document")


def _file_date(path: Path) -> str:
    try:
        return datetime.date.fromtimestamp(path.stat().st_mtime).isoformat()
    except OSError:
        return datetime.date.today().isoformat()


def read_sources(path: Path, only: str | None) -> list[Imported]:
    """What one input file holds, as library files to be."""
    if path.suffix.lower() not in IMPORTABLE:
        raise ValueError(f"{path.name}: import takes Markdown or text, or claude.ai's export "
                         f"({', '.join(sorted(IMPORTABLE))})")
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            name = next((n for n in archive.namelist() if n.endswith("conversations.json")), None)
            if name is None:
                return _from_archive(archive, path)
            data = json.loads(archive.read(name))
        conversations = _claude_conversations(data)
        if conversations is None:
            raise ValueError(f"{path.name}: conversations.json is not a claude.ai export")
        return _from_conversations(conversations, only)
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() == ".json":
        try:
            conversations = _claude_conversations(json.loads(text))
        except ValueError:
            conversations = None
        if conversations is None:
            raise ValueError(f"{path.name}: not claude.ai's conversations.json")
        return _from_conversations(conversations, only)
    return [_from_text(text, path, _file_date(path))]


def _from_text(text: str, name: PurePath, date: str) -> Imported:
    if is_exported_chat(text) and (chat := from_saveai(text, name, date)):
        return chat
    if floor := from_the_floor(text, name, date):
        return floor
    return _headed(text, name, date, "chat" if is_noesis_chat(text, name) else "document")


def _from_archive(archive: zipfile.ZipFile, path: Path) -> list[Imported]:
    """Each text inside, as on its own; a zip's furniture (__MACOSX, dotfiles) left out."""
    members = [m for m in archive.infolist()
               if not m.is_dir() and PurePath(m.filename).suffix.lower() in (".txt", ".md")
               and not any(part.startswith((".", "__MACOSX")) for part in PurePath(m.filename).parts)]
    if not members:
        raise ValueError(f"{path.name}: no conversations.json, .txt or .md inside")
    return [_from_text(archive.read(m).decode("utf-8", errors="replace"), PurePath(_member_name(m)),
                       datetime.date(*m.date_time[:3]).isoformat())
            for m in members]


def _member_name(member: zipfile.ZipInfo) -> str:
    """Its name as written: Finder writes UTF-8 without the flag that says so,
    which zipfile then reads as cp437."""
    if member.flag_bits & 0x800:
        return member.filename
    try:
        return member.filename.encode("cp437").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return member.filename


def _from_conversations(conversations: list[dict], only: str | None) -> list[Imported]:
    if only:
        wanted = only.casefold()
        conversations = [c for c in conversations
                         if wanted in (str(c.get("uuid", "")).casefold(), str(c.get("name", "")).casefold())]
    return [i for i in (from_claude_conversation(c) for c in conversations) if i]


# ---------------------------------------------------------------------------
# Titles
# ---------------------------------------------------------------------------

TITLE_TRIES = 3
# About 35K tokens: the first hour and more of talk, enough to say what it is about.
_TITLE_SAMPLE_CHARS = 120_000
_TITLE_SYSTEM = "You title conversations for a personal library of writing and conversations."


def _title_prompt(item: Imported) -> str:
    return (
        "Below is the transcript of a spoken conversation, made by speech recognition, so words "
        f"may be misheard and names misspelled. It took place in a channel called \"{item.title}\", "
        "which every conversation there shares.\n\n"
        "Give it a title: a few words, at most eight, naming what it is actually about, specific "
        "enough to tell it apart from the channel's other conversations. Title case; no quotation "
        "marks, no date, and not the channel's name unless that is its subject. Reply with the "
        "title alone.\n\n"
        f"<transcript>\n{item.body[:_TITLE_SAMPLE_CHARS]}\n</transcript>"
    )


def _clean_title(reply: str) -> str:
    line = next((ln.strip() for ln in reply.splitlines() if ln.strip()), "")
    line = re.sub(r"^(?:#+\s*|title:\s*)", "", line, flags=re.IGNORECASE)
    return line.strip("*_\"'“”‘’ ").rstrip(".").strip()


def name_conversation(item: Imported, free, ask) -> str | None:
    """A title for a conversation that came without one, or None.

    `ask(messages)` is the model's reply; a title `free` refuses is answered,
    in the same exchange, with the fact that it is taken, up to TITLE_TRIES.
    """
    messages: list[dict[str, object]] = [{"role": "user", "content": _title_prompt(item)}]
    for _ in range(TITLE_TRIES):
        reply = ask(messages)
        title = _clean_title(reply)
        if title and free(title):
            return title
        messages += [
            {"role": "assistant", "content": reply.strip() or "(no title)"},
            {"role": "user", "content": (
                f"\"{title}\" is already the title of another conversation in the library. "
                "Give a different one, telling this conversation apart from that."
                if title else "Reply with the title alone.")},
        ]
    return None


def _title_asker():
    """The index model, asked for a title."""
    from noesis.anthropic_client import AnthropicChatClient
    config = load_config()
    if not config.index_model.startswith("claude-"):
        raise ValueError(f"index_model must be an Anthropic model (claude-*), not '{config.index_model}'")
    if not config.anthropic_api_key:
        raise ValueError("titling it needs an Anthropic key (ANTHROPIC_API_KEY, or anthropic_api_key in config.toml)")
    client = AnthropicChatClient(model=config.index_model, api_key=config.anthropic_api_key)
    return lambda messages: client.generate_reply(_TITLE_SYSTEM, messages).text


def _imported_before(item: Imported, here: Path) -> Path | None:
    """A file of its date with the same turns: this conversation, imported
    before under the title it was given then."""
    rest = render(item).split("\n", 3)[3:]
    for path in sorted(here.glob(f"{item.date}-*.{item.role}.md")):
        try:
            if path.read_text(encoding="utf-8").split("\n", 3)[3:] == rest:
                return path
        except (OSError, UnicodeDecodeError):
            continue
    return None


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def render(item: Imported) -> str:
    """The file's text, spaced as `reply` saves a transcript."""
    from noesis.form import fix_section_spacing
    body = f"\n{item.body}" if item.body else ""
    return fix_section_spacing(f"\n# {item.title}\n{item.date}\n{body}\n")[0]


def _problems(path: Path, role: str) -> list[str]:
    if role == "chat":
        return check_file(path)
    from noesis.form import check_global_issues
    return check_global_issues(path)


_BARE_LABEL_RE = re.compile(r"^(\s*)(Prompt:|ChatGPT:|Response:|References:)\s*$", re.MULTILINE)


def repaired(text: str, role: str) -> str:
    """The text as `noesis fix` would leave it; in a document, a speaker label
    is set in bold, so that it does not read as a chat."""
    lines, _ = fix_object_replacement(text.split("\n"))
    lines, _ = fix_rtl_spans(lines)
    if role == "chat":
        lines, _ = fix_title_section(lines)
        return fix_section_spacing("\n".join(lines))[0]
    return _BARE_LABEL_RE.sub(r"\1**\2**", "\n".join(lines))


def _checked(item: Imported, name: str) -> tuple[str, list[str]]:
    """Its text, repaired, and what is still wrong with it under that name
    (the format rules derive the name from the title)."""
    text = repaired(render(item), item.role)
    with tempfile.TemporaryDirectory() as scratch:
        trial = Path(scratch) / name
        trial.write_text(text, encoding="utf-8")
        problems = _problems(trial, item.role)
        if not problems:
            text = trial.read_text(encoding="utf-8")
    return text, problems


def settle(item: Imported, stem: str) -> tuple[Imported, str, list[str], str | None]:
    """What is written: the item and its text, repaired, or what is still
    wrong with it. A chat that still fails is a document of the same text,
    and the last is why."""
    text, problems = _checked(item, f"{stem}.{item.role}.md")
    if not problems or item.role != "chat":
        return item, text, problems, None
    document = with_fields(item, role="document")
    text, still = _checked(document, f"{stem}.document.md")
    return (item, text, problems, None) if still else (document, text, [], problems[0])


def run_import(paths: list[Path], only: str | None = None, replace: bool = False,
               document_of: str | None = None) -> int:
    from noesis.cli import _collect_existing_slugs, _is_within
    from noesis.library import library_titles
    if document_of is not None:
        return _import_document_of(paths, document_of, replace)
    library = load_config().library_path
    in_library = library is not None and _is_within(Path.cwd().resolve(), library.resolve())
    taken = _collect_existing_slugs(library if in_library else None)
    # By slug, as `## Related` resolves a title.
    titled = {slugify(title): rel for rel, title in library_titles(library).items()} if in_library else {}

    ask = None

    def free(date: str, title: str) -> bool:
        slug = slugify(title)
        return bool(slug) and slug not in titled and f"{date}-{slug}" not in taken

    written = skipped = failed = 0
    for source in paths:
        try:
            items = read_sources(source, only)
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            print(f"Error: {exc}")
            failed += 1
            continue
        for item in items:
            here = library / item.date[:4] if in_library else Path.cwd()
            if item.untitled:
                before = _imported_before(item, here)
                if before is not None:
                    item = with_fields(item, title=before.read_text(encoding="utf-8").split("\n")[1][2:].strip(),
                                       untitled=False)
                else:
                    import anthropic
                    try:
                        ask = ask or _title_asker()
                        title = name_conversation(item, lambda t, d=item.date: free(d, t), ask)
                    except (anthropic.AnthropicError, ValueError) as exc:
                        print(f"failed   {source.name}: no title: {exc}")
                        failed += 1
                        continue
                    if title is None:
                        print(f"failed   {source.name}: no title the library does not have, in {TITLE_TRIES} tries")
                        failed += 1
                        continue
                    item = with_fields(item, title=title, untitled=False)
            stem = f"{item.date}-{slugify(item.title)}"
            item, text, problems, demoted = settle(item, stem)
            target = here / f"{stem}.{item.role}.md"
            if problems:
                print(f"failed   {target.name}: {problems[0]}")
                failed += 1
                continue
            if stem in taken and not (replace and target.exists()):
                print(f"skipped  {target.name} (exists{'' if target.exists() else ' under another role'})")
                skipped += 1
                continue
            holder = titled.get(slugify(item.title))
            if holder and not (in_library and holder == target.relative_to(library).as_posix()):
                print(f"failed   {target.name}: the title \"{item.title}\" is {Path(holder).name}'s")
                failed += 1
                continue
            here.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(f".{target.name}.import")
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(target)
            taken.add(stem)
            if in_library:
                titled[slugify(item.title)] = target.relative_to(library).as_posix()
            print(f"imported {target.relative_to(library) if in_library else target.name}"
                  + (f" (as a chat, {demoted})" if demoted else ""))
            written += 1
    print(f"{written} imported, {skipped} skipped, {failed} failed.")
    return 1 if failed else 0


def _import_document_of(paths: list[Path], chat_name: str, replace: bool) -> int:
    """One text as a chat's document, `<stem>.document.md` beside it, as
    `noesis new --edit` pairs them: written elsewhere (claude.ai, an editor)
    and brought in as the position the conversation came to. It keeps its own
    `# Title` if it has one, else takes the chat's; the date is the chat's."""
    from noesis.cli import _is_within
    from noesis.library import _extract_title, library_titles
    library = load_config().library_path
    chat = (library / chat_name).resolve() if library else None
    if chat is None or not chat.name.endswith(".chat.md") or not chat.is_file() \
            or not _is_within(chat, library.resolve()):
        print(f"Error: {chat_name} is not a chat in this library.")
        return 1
    if len(paths) != 1 or paths[0].suffix.lower() not in {".md", ".markdown", ".txt"}:
        print("Error: a chat's document is one Markdown or text file.")
        return 1
    source = paths[0]
    stem = chat.name[: -len(".chat.md")]
    target = chat.with_name(f"{stem}.document.md")
    rel = target.relative_to(library.resolve()).as_posix()
    if target.exists() and not replace:
        print(f"skipped  {target.name} (exists)")
        print("0 imported, 1 skipped, 0 failed.")
        return 0
    text = source.read_text(encoding="utf-8", errors="replace")
    chat_title = _extract_title(chat.read_text(encoding="utf-8", errors="replace"), stem)
    item = _headed(text, PurePath(f"{stem}.document.md"), stem[:10], "document")
    if not text.lstrip("\n").startswith("# "):
        item = with_fields(item, title=chat_title)
    dated = _DATED_STEM_RE.match(stem)
    if dated:
        item = with_fields(item, date=dated[1])
    pair = {chat.relative_to(library.resolve()).as_posix(), rel}
    holder = {slugify(title): r for r, title in library_titles(library).items()}.get(slugify(item.title))
    if holder and holder not in pair:
        print(f"failed   {target.name}: the title \"{item.title}\" is {Path(holder).name}'s")
        print("0 imported, 0 skipped, 1 failed.")
        return 1
    item, written, problems, _ = settle(item, stem)
    if problems:
        print(f"failed   {target.name}: {problems[0]}")
        print("0 imported, 0 skipped, 1 failed.")
        return 1
    tmp = target.with_name(f".{target.name}.import")
    tmp.write_text(written, encoding="utf-8")
    tmp.replace(target)
    print(f"imported {rel} (the document of {chat.name})")
    print("1 imported, 0 skipped, 0 failed.")
    return 0
