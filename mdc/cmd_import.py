"""mdc import: conversations held elsewhere become library files (SERVER.md, Phase 4).

- claude.ai's data export (the zip, or its conversations.json): each
  conversation becomes `<date>-<slug>.chat.md`, its turns exactly as exported,
  following the active branch when messages were edited — except that each
  turn's `## Related` and `## References` are gathered into one of each at
  the end, as `reply` keeps them.
- saveai.net exports (the "AI Chat Exporter" Markdown `mdc fix` converts:
  `# you asked` / `# claude response` blocks): a `.chat.md`.
- The Floor's shared text (a segment of a spoken conversation: `The Floor —
  <channel>`, a dated line of hours, then `<name> · <time>` blocks): a
  `.chat.md`, a section per speaker as named, titled by the channel. A file
  from before the text named them takes both from its download name, `The
  Floor — <channel> — <yyyy-mm-dd hhmm>`. A paste stays its author's, quoted;
  Claude's is Claude's turn.
- A zip that is not claude.ai's: each `.txt` and `.md` inside, as on its own.
- Anything else, or an export that does not parse: a `.document.md`, its
  text as it is.

Files go where their names put them, this year's directory of the library
(or the current directory outside one). Each is checked before it takes its
name; an existing one is skipped unless --replace. A title another file of
the library already has fails: `## Related` names a file by its title.
"""

from __future__ import annotations

import datetime
import json
import re
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePath

from mdc.config import ASSISTANT_NAME, PROMPT_HEADING, load_config
from mdc.form import _parse_exported_chat, check_file, is_exported_chat, slugify
from mdc.text_utils import _upgrade_reply_headings
from mdc.transcript import collect_citations, with_citations


@dataclass
class Imported:
    title: str
    date: str
    role: str  # "chat" or "document"
    body: str  # everything after the title and date


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
    return Imported(channel, date, "chat", _turns_text(turns))


def _quoted(text: str) -> str:
    return "\n".join(f"> {line}" if line.strip() else ">" for line in text.splitlines())


def as_document(text: str, name: PurePath, date: str) -> Imported:
    lines = text.strip("\n").splitlines()
    title = None
    if lines and lines[0].startswith("# "):
        title = lines[0][2:].strip()
        lines = lines[1:]
    title = title or name.stem.replace("-", " ").replace("_", " ").strip().title() or "Untitled"
    return Imported(title, date, "document", "\n".join(lines).strip("\n"))


def _file_date(path: Path) -> str:
    try:
        return datetime.date.fromtimestamp(path.stat().st_mtime).isoformat()
    except OSError:
        return datetime.date.today().isoformat()


def read_sources(path: Path, only: str | None) -> list[Imported]:
    """What one input file holds, as library files to be."""
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
        if conversations is not None:
            return _from_conversations(conversations, only)
    return [_from_text(text, path, _file_date(path))]


def _from_text(text: str, name: PurePath, date: str) -> Imported:
    if is_exported_chat(text) and (chat := from_saveai(text, name, date)):
        return chat
    return from_the_floor(text, name, date) or as_document(text, name, date)


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
# Writing
# ---------------------------------------------------------------------------

def render(item: Imported) -> str:
    """The file's text, spaced as `reply` saves a transcript."""
    from mdc.form import fix_section_spacing
    body = f"\n\n{item.body}" if item.body else ""
    return fix_section_spacing(f"\n# {item.title}\n{item.date}\n{body}\n")[0]


def _problems(path: Path, role: str) -> list[str]:
    if role == "chat":
        return check_file(path)
    from mdc.form import check_global_issues
    return check_global_issues(path)


def run_import(paths: list[Path], only: str | None = None, replace: bool = False) -> int:
    from mdc.cli import _collect_existing_slugs, _is_within
    from mdc.library import library_titles
    library = load_config().library_path
    in_library = library is not None and _is_within(Path.cwd().resolve(), library.resolve())
    taken = _collect_existing_slugs(library if in_library else None)
    # By slug, as `## Related` resolves a title.
    titled = {slugify(title): rel for rel, title in library_titles(library).items()} if in_library else {}

    written = skipped = failed = 0
    for source in paths:
        try:
            items = read_sources(source, only)
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            print(f"Error: {exc}")
            failed += 1
            continue
        for item in items:
            stem = f"{item.date}-{slugify(item.title)}"
            here = library / item.date[:4] if in_library else Path.cwd()
            target = here / f"{stem}.{item.role}.md"
            if stem in taken and not (replace and target.exists()):
                print(f"skipped  {target.name} (exists{'' if target.exists() else ' under another role'})")
                skipped += 1
                continue
            holder = titled.get(slugify(item.title))
            if holder and not (in_library and holder == target.relative_to(library).as_posix()):
                print(f"failed   {target.name}: the title \"{item.title}\" is {Path(holder).name}'s")
                failed += 1
                continue
            text = render(item)
            # Checked under its own name (the format rules derive it from the
            # title) before anything in the library is touched.
            with tempfile.TemporaryDirectory() as scratch:
                trial = Path(scratch) / target.name
                trial.write_text(text, encoding="utf-8")
                problems = _problems(trial, item.role)
            if problems:
                print(f"failed   {target.name}: {problems[0]}")
                failed += 1
                continue
            here.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(f".{target.name}.import")
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(target)
            taken.add(stem)
            if in_library:
                titled[slugify(item.title)] = target.relative_to(library).as_posix()
            print(f"imported {target.relative_to(library) if in_library else target.name}")
            written += 1
    print(f"{written} imported, {skipped} skipped, {failed} failed.")
    return 1 if failed else 0
