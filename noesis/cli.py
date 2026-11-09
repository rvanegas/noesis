from __future__ import annotations

import argparse
import datetime
import difflib
import os
import re
import subprocess
import sys
from pathlib import Path

from noesis.config import load_config
from noesis.remote import REMOTE_COMMANDS
from noesis.form import check_encoding, check_file, fix_exported_chat, fix_object_replacement, fix_rtl_spans, fix_section_spacing, fix_title_section, slugify
from noesis.transcript import TranscriptError, parse_transcript
from noesis.assets import collect_local_assets
from noesis.edit_tools import create_document_file

from noesis.cmd_diff import run_diff, run_files_ls
from noesis.cmd_argue import run_argue
from noesis.cmd_analyze import run_analyze
from noesis.cmd_audit import run_audit
from noesis.cmd_export import run_export
from noesis.cmd_pdf import run_pdf
from noesis.cmd_index import run_index
from noesis.cmd_reply import run_reply, _LibraryTermNotFoundError
from noesis.cmd_review import run_review


def _read_file(path: Path) -> str:
    """Read a file as UTF-8, converting from latin-1 in place if needed."""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="latin-1")
        path.with_suffix(path.suffix + ".bak").write_bytes(path.read_bytes())
        path.write_text(text, encoding="utf-8")
        print(f"Warning: {path.name} was not UTF-8; converted in place (backup: {path.name}.bak).", file=sys.stderr)
        return text


def _require_md(path: Path) -> int:
    """Return 1 and print an error if path doesn't have a .md suffix, else 0."""
    if path.suffix.lower() != ".md":
        print(f"Error: '{path}' does not have a .md extension.")
        return 1
    return 0


def _require_bare(s: str) -> int:
    """Return 1 and print an error if s contains a directory separator, else 0."""
    if "/" in s:
        print(f"Error: '{s}' — pass a bare filename, not a path (noesis works in the current directory)")
        return 1
    return 0


_DATED_SLUG_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-.+\.md$")


def _primary(companion: Path) -> Path:
    """Return the primary document path for a companion file (*.chat.md, *.document.md, *.argument.md)."""
    return companion.with_suffix("").with_suffix(".md")


def _resolve_path_abbrev(s: str, cwd: Path, *, secondary_priority: tuple[str, ...] = ()) -> Path | None:
    """Resolve a file argument: a path, a name anywhere in the library, or an abbreviation.

    1. `s` names an existing file, absolute or relative to cwd.
    2. In a library, `s` is the name of a file anywhere in it: names are unique.
    3. `s` is a case-insensitive substring of the date-slug stem of role-named
       .md files, matched in cwd first and then across the library. Among
       files sharing a stem, the role earliest in `secondary_priority` wins
       (default: chat, document, source).

    Returns the Path on an unambiguous match, or None after printing an error.
    """
    from noesis.library import role_of
    candidate = Path(s)
    if not candidate.is_absolute():
        candidate = cwd / s
    if candidate.exists():
        return candidate

    library = load_config().library_path
    in_library = library is not None and _is_within(cwd.resolve(), library.resolve())
    if in_library and "/" not in s:
        named = [p for p in _library_files(library) if p.name == s]
        if len(named) == 1:
            return named[0]

    roles = secondary_priority or ("chat", "document", "source")
    abbrev = s.lower()
    scopes = [sorted(cwd.iterdir())] + ([_library_files(library)] if in_library else [])
    matches: list[Path] = []
    for files in scopes:
        best: dict[str, Path] = {}
        for p in files:
            if not (p.is_file() and _DATED_SLUG_RE.match(p.name) and role_of(p.name) in roles):
                continue
            stem = p.name.split(".")[0]
            if abbrev not in stem.lower():
                continue
            if stem not in best or roles.index(role_of(p.name)) < roles.index(role_of(best[stem].name)):
                best[stem] = p
        matches = sorted(best.values(), key=lambda p: p.name)
        if matches:
            break

    if not matches:
        print(f"Error: '{s}' not found.")
        return None
    if len(matches) == 1:
        return matches[0]
    print(f"Ambiguous abbreviation '{s}' matches multiple files:")
    for p in matches:
        print(f"  {p.name}")
    return None


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _library_files(library: Path) -> list[Path]:
    """Every file of a library but its backups and state."""
    from noesis.config import LIBRARY_STATE_DIRNAME
    skip = {LIBRARY_STATE_DIRNAME, "REVISIONS"}
    return sorted(
        p for p in library.rglob("*")
        if p.is_file() and not skip.intersection(p.relative_to(library).parts)
    )


_COMPANION_SUFFIXES = ("document", "chat", "argument")

# Import wrap_paragraphs for backward compatibility (used by tests and external code)
from noesis.text_utils import wrap_paragraphs, _upgrade_reply_headings, _parse_index_reply  # noqa: F401


def _resolve_edit_paths(s: str, cwd: Path) -> list[Path]:
    """Return all companion files sharing the same primary stem as `s`.

    If `s` names an existing file directly, return just that file.  Otherwise
    find the primary stem via abbreviation match and return all companions
    (.document.md, .chat.md, .argument.md) plus the bare .md if present.
    """
    candidate = Path(s) if Path(s).is_absolute() else cwd / s
    if candidate.exists():
        return [candidate]

    primary = _resolve_path_abbrev(s, cwd, secondary_priority=_COMPANION_SUFFIXES)
    if primary is None:
        return []

    stem = primary.name.split(".")[0]

    results = []
    for sec in _COMPANION_SUFFIXES:
        p = primary.parent / f"{stem}.{sec}.md"
        if p.exists():
            results.append(p)
    return results or [primary]


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(raw_argv)

    if args.command == "serve":
        from noesis.server import run_serve
        return run_serve(host=args.host, port=args.port)

    from noesis.config import DEFAULT_CONFIG_PATH, _write_default_config
    if not DEFAULT_CONFIG_PATH.exists():
        _write_default_config(DEFAULT_CONFIG_PATH)

    # The run's library, for every load_config() below.
    if args.lib:
        os.environ["NOESIS_LIBRARY"] = str(Path(args.lib).expanduser().resolve())

    # In a library mirrored from noesis's server, model-backed commands run there
    # (SERVER.md, Phase 3); sync runs alone.
    if args.command in REMOTE_COMMANDS or args.command == "sync":
        from noesis.remote import mirror_for, remote_argv, run_remote, watch_remote
        config = load_config()
        mirror = mirror_for(config, Path.cwd())
        if mirror:
            library_id, root = mirror
            run_argv = [] if args.command == "sync" else remote_argv(raw_argv, Path.cwd())
            if args.command == "reply" and args.watch:
                return watch_remote(config, library_id, root, run_argv, args.path)
            return run_remote(config, library_id, root, run_argv)
        if args.command == "sync":
            print("Error: sync needs server_url, server_token and a [libraries] entry whose local_root holds this directory.")
            return 1

    try:
        if args.command == "review":
            return run_review(
                reset=args.reset,
                theme=args.theme,
                selection=args.selection,
                doc_start=args.doc_start,
                docs=args.docs,
                evaluate=args.evaluate,
                pass2=args.pass2,
                final=args.final,
                afterword=args.afterword,
                intro=args.intro,
                compile_=args.compile_,
                action=args.action,
                action_themes=args.action_themes,
            )
        if args.command == "index":
            return run_index(
                refs_only=args.refs_only_all,
                reprocess_all=args.all,
                verbose=args.verbose,
            )
        if args.command == "import":
            from noesis.cmd_import import run_import
            return run_import([Path(p).expanduser() for p in args.files], only=args.only, replace=args.replace,
                              document_of=args.document_of)
        if args.command == "new":
            config = load_config()
            return run_new(" ".join(args.title_words) or None, edit=args.edit, library_path=config.library_path)
        if args.command == "check":
            if _require_bare(args.path):
                return 1
            path = _resolve_path_abbrev(args.path, Path.cwd())
            if path is None:
                return 1
            return run_check(path)
        if args.command == "validate":
            paths = []
            for p in args.paths:
                if _require_bare(p):
                    return 1
                resolved = _resolve_path_abbrev(p, Path.cwd())
                if resolved is None:
                    return 1
                paths.append(resolved)
            return run_validate(paths)
        if args.command == "fix":
            paths = []
            for p in args.paths:
                if _require_bare(p):
                    return 1
                resolved = _resolve_path_abbrev(p, Path.cwd())
                if resolved is None:
                    return 1
                paths.append(resolved)
            return run_fix(paths, yes=args.yes)
        if args.command == "reply":
            if args.terms and not args.library:
                print("Error: -t/--term requires -l/--library.")
                return 1
            if _require_bare(args.path):
                return 1
            path = _resolve_path_abbrev(args.path, Path.cwd(), secondary_priority=("chat",))
            if path is None:
                return 1
            return run_reply(
                path,
                model=args.model,
                reasoning_effort=args.reasoning_effort,
                verbose=args.verbose,
                watch=args.watch,
                library=args.library,
                terms=args.terms,
                strict=args.strict,
                web=args.web,
                edit=args.edit,
            )
        if args.command == "diff":
            extra = args.diff_args or []
            if extra and extra[0] == "--":
                extra = extra[1:]
            config = load_config()
            _rev_dir = (config.library_path / "REVISIONS") if config.library_path else None
            if _require_bare(args.path):
                return 1
            path = _resolve_path_abbrev(args.path, Path.cwd(), secondary_priority=("document", "chat", "argument"))
            if path is None:
                return 1
            return run_diff(
                path,
                revision=args.revision,
                delta=args.delta,
                diff_args=extra or None,
                revisions_dir=_rev_dir,
            )
        if args.command == "config":
            return run_config()
        if args.command == "argue":
            if _require_bare(args.path):
                return 1
            path = _resolve_path_abbrev(args.path, Path.cwd(), secondary_priority=("argument", "document"))
            if path is None:
                return 1
            return run_argue(path, max_props=args.max_props)
        if args.command == "analyze":
            if _require_bare(args.path):
                return 1
            path = _resolve_path_abbrev(args.path, Path.cwd(), secondary_priority=("argument", "document"))
            if path is None:
                return 1
            return run_analyze(path, args.proposition, verbose=args.verbose)
        if args.command == "audit":
            if _require_bare(args.path):
                return 1
            path = _resolve_path_abbrev(args.path, Path.cwd(), secondary_priority=("argument", "document"))
            if path is None:
                return 1
            return run_audit(path)
        if args.command == "export":
            if _require_bare(args.path):
                return 1
            path = _resolve_path_abbrev(args.path, Path.cwd(), secondary_priority=("argument", "document"))
            if path is None:
                return 1
            return run_export(path, dry_run=args.dry_run, new=args.new)
        if args.command == "edit":
            if _require_bare(args.path):
                return 1
            paths = _resolve_edit_paths(args.path, Path.cwd())
            if not paths:
                return 1
            return run_edit(paths)
        if args.command == "files":
            if getattr(args, "files_command", None) == "ls":
                return run_files_ls()
            args._files_parser.print_help()
            return 1
        if args.command == "pdf":
            if _require_bare(args.path):
                return 1
            path = _resolve_path_abbrev(args.path, Path.cwd())
            if path is None:
                return 1
            return run_pdf(path, quiet=args.quiet)
    except TranscriptError as exc:
        print(f"Error: {exc}")
        return 1
    except FileNotFoundError as exc:
        print(f"Error: {exc}")
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 1
    except Exception as exc:
        print(f"Error: {exc}")
        return 1

    parser.print_help()
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="noesis",
        description="Work with noesis-format markdown conversation files.",
    )
    parser.add_argument(
        "--lib",
        default=None,
        metavar="PATH",
        help="The library for this invocation, overriding NOESIS_LIBRARY and library_path from config.",
    )
    subparsers = parser.add_subparsers(dest="command")

    # review
    review_parser = subparsers.add_parser(
        "review",
        help="Run a staged AI review over an indexed document collection.",
    )
    review_parser.add_argument(
        "--reset",
        action="store_true",
        default=False,
        help="Discard saved state and start the review from scratch.",
    )
    review_parser.add_argument(
        "--theme",
        default=None,
        metavar="NAME",
        help="Theme code or name (required for --docs and --assess).",
    )
    review_parser.add_argument(
        "--selection",
        action="store_true",
        default=False,
        help="Interactively classify documents into themes; updates THEMES.md.",
    )
    review_parser.add_argument(
        "--start",
        default=None,
        metavar="N",
        dest="doc_start",
        type=int,
        help="Begin --selection at document N (1-based).",
    )
    review_parser.add_argument(
        "--docs",
        action="store_true",
        default=False,
        help="Run individual doc reviews for all theme-assigned documents that lack one.",
    )
    review_parser.add_argument(
        "--evaluate",
        action="store_true",
        default=False,
        help="Synthesize individual document reviews into a thematic assessment.",
    )
    review_parser.add_argument(
        "--pass2",
        action="store_true",
        default=False,
        help="With --evaluate: generate a second-pass assessment using sibling pass1 assessments as context.",
    )
    review_parser.add_argument(
        "--final",
        action="store_true",
        default=False,
        help="Generate the final cross-theme assessment from all pass2 assessments.",
    )
    review_parser.add_argument(
        "--afterword",
        action="store_true",
        default=False,
        help="Generate an afterword; pass the response document title as the argument.",
    )
    review_parser.add_argument(
        "--intro",
        action="store_true",
        default=False,
        help="Generate INTRODUCTION.md with a table of contents and process description.",
    )
    review_parser.add_argument(
        "--compile",
        action="store_true",
        default=False,
        dest="compile_",
        help="Concatenate all review outputs into COMPILED.md (intro, assessments, final, afterword).",
    )
    review_parser.add_argument(
        "action",
        nargs="?",
        default=None,
        metavar="ACTION",
        help="Subcommand: 'tokens' to show review token counts by theme.",
    )
    review_parser.add_argument(
        "action_themes",
        nargs="*",
        metavar="THEME",
        help="Theme codes or names for the action subcommand.",
    )

    # relate
    # index
    index_parser = subparsers.add_parser(
        "index",
        help="Build or update the library document index using an AI model for summaries.",
    )
    index_parser.add_argument(
        "--all",
        action="store_true",
        default=False,
        help="Reindex all documents and rebuild all relations from scratch.",
    )
    index_parser.add_argument(
        "--refs-only-all",
        action="store_true",
        default=False,
        help="Extract references from all documents without calling any AI model.",
    )
    index_parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        default=False,
        help="Print warnings about unused KEYS.md entries.",
    )

    # new
    new_parser = subparsers.add_parser(
        "new",
        help="Create a new noesis conversation file in the current directory.",
    )
    new_parser.add_argument(
        "title_words",
        nargs="*",
        metavar="WORD",
        help="Title of the conversation.",
    )
    new_parser.add_argument(
        "-e", "--edit",
        action="store_true",
        help="Also create an editor file with '(Editor)' appended to the title.",
    )

    # check
    check_parser = subparsers.add_parser(
        "check",
        help="Validate transcript structure and report reply status.",
    )
    check_parser.add_argument("path", help="Path to the markdown transcript.")

    # validate
    validate_parser = subparsers.add_parser(
        "validate",
        help="Run noesis format rules on one or more files.",
    )
    validate_parser.add_argument("paths", nargs="+", metavar="file.md")

    # fix
    fix_parser = subparsers.add_parser(
        "fix",
        help="Auto-fix correctable noesis format violations (modifies files in place).",
    )
    fix_parser.add_argument("paths", nargs="+", metavar="file.md")
    fix_parser.add_argument(
        "-y", "--yes",
        action="store_true",
        default=False,
        help="Apply every fix and move without asking (a run on the server has no one to ask).",
    )

    # reply
    reply_parser = subparsers.add_parser(
        "reply",
        help="Append one AI assistant reply to a transcript.",
    )
    reply_parser.add_argument(
        "-m", "--model",
        default=None,
        help="Anthropic model to use (e.g. claude-sonnet-4-6). Overrides config file.",
    )
    reply_parser.add_argument(
        "-r", "--reasoning-effort",
        choices=("none", "low", "medium", "high", "xhigh"),
        default="low",
        help="Set the model's reasoning effort (default: low).",
    )
    reply_parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        default=False,
        help="Print progress messages while fetching a reply.",
    )
    reply_parser.add_argument(
        "-W", "--watch",
        action="store_true",
        default=False,
        help="Poll the transcript every second and reply whenever a pending turn is found.",
    )
    reply_parser.add_argument(
        "-l", "--library",
        action="store_true",
        default=False,
        help="Enable library tool access (requires library_path in config).",
    )
    reply_parser.add_argument(
        "-t", "--term",
        action="append",
        dest="terms",
        default=[],
        metavar="TERM",
        help="Pre-look up a library index term and inject results into context. Requires -l. May be repeated.",
    )
    reply_parser.add_argument(
        "--strict",
        action="store_true",
        default=False,
        help="Abort if any library term lookup fails (default: warn and proceed).",
    )
    reply_parser.add_argument(
        "-w", "--web",
        action="store_true",
        default=False,
        help="Enable Anthropic web search and fetch (server-side tools).",
    )
    reply_parser.add_argument(
        "-e", "--edit",
        action="store_true",
        default=False,
        help="Create the companion .document.md if missing. A .chat.md's existing companions are always loaded and editable.",
    )
    reply_parser.add_argument("path", help="Path to the markdown transcript.")

    # pdf
    pdf_parser = subparsers.add_parser(
        "pdf",
        help="Convert a markdown file to PDF via pandoc.",
    )
    pdf_parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        default=False,
        help="Do not open the PDF after conversion.",
    )
    pdf_parser.add_argument("path", help="Path to the markdown file.")

    # diff
    diff_parser = subparsers.add_parser(
        "diff",
        help="Show changes made to a file by the last noesis reply edit.",
    )
    diff_parser.add_argument("path", help="Path to the edited file.")
    diff_parser.add_argument(
        "-r", "--revision",
        type=int,
        default=None,
        metavar="N",
        help="Diff revision N against the current file.",
    )
    diff_parser.add_argument(
        "-d", "--delta",
        type=int,
        default=None,
        metavar="N",
        help="Show the Nth most recent change (default: 1).",
    )
    diff_parser.add_argument(
        "diff_args",
        nargs=argparse.REMAINDER,
        help=argparse.SUPPRESS,
    )

    # edit
    edit_parser = subparsers.add_parser(
        "edit",
        help="Open a file in $EDITOR.",
    )
    edit_parser.add_argument("path", help="Path to the markdown file.")

    # config
    subparsers.add_parser(
        "config",
        help="Show configuration and data file locations.",
    )

    # serve
    serve_parser = subparsers.add_parser(
        "serve",
        help="Run noesis's HTTP API (SERVER.md).",
    )
    serve_parser.add_argument("--host", default="127.0.0.1", help="Interface to bind. Default: 127.0.0.1.")
    serve_parser.add_argument("--port", type=int, default=8001, help="Port to bind. Default: 8001.")

    # import
    import_parser = subparsers.add_parser(
        "import",
        help="Turn conversations from elsewhere into library files (claude.ai export, saveai.net, or a document).",
    )
    import_parser.add_argument("files", nargs="+", help="A claude.ai export (zip or conversations.json), saveai.net Markdown, or any text file.")
    import_parser.add_argument("--only", metavar="NAME", help="From a claude.ai export, only the conversation with this name or uuid.")
    import_parser.add_argument("--replace", action="store_true", help="Overwrite a file the import would otherwise skip as existing.")
    import_parser.add_argument("--document-of", metavar="CHAT", help="Import one Markdown or text file as this chat's document: <stem>.document.md beside it (a path in the library).")

    # sync
    subparsers.add_parser(
        "sync",
        help="Sync this library with its copy on noesis's server (SERVER.md, Phase 3).",
    )

    # files
    files_parser = subparsers.add_parser(
        "files",
        help="Manage files uploaded to the Anthropic Files API.",
    )
    files_sub = files_parser.add_subparsers(dest="files_command")
    files_sub.add_parser(
        "ls",
        help="List locally cached file uploads.",
    )
    files_parser.set_defaults(_files_parser=files_parser)

    # argue
    argue_parser = subparsers.add_parser(
        "argue",
        help="Extract a structured argument from a document or a chat.",
    )
    argue_parser.add_argument("path", help="A .document.md or .chat.md. Extracts its argument to <stem>.argument.md if absent.")
    argue_parser.add_argument(
        "-m", "--max-props",
        metavar="N",
        type=int,
        default=None,
        help="Maximum total number of propositions passed to dianoia extract.",
    )

    # analyze
    analyze_parser = subparsers.add_parser(
        "analyze",
        help="Analyze a single argument (a proposition and its justifier chain) in a companion argument file, via dianoia.",
    )
    analyze_parser.add_argument("path", help="Document or companion .argument.md file.")
    analyze_parser.add_argument(
        "proposition",
        type=int,
        metavar="PROPOSITION",
        help="Proposition number identifying the argument to analyze (that proposition and its justifier chain).",
    )
    analyze_parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show extra detail.",
    )

    # audit
    audit_parser = subparsers.add_parser(
        "audit",
        help="Audit a companion argument file against the structural conditions, via dianoia.",
    )
    audit_parser.add_argument("path", help="Document or companion .argument.md file.")

    # export
    export_parser = subparsers.add_parser(
        "export",
        help="Export a companion argument file as a new public Roxana discussion.",
    )
    export_parser.add_argument("path", help="Document or companion .argument.md file.")
    export_parser.add_argument(
        "-n", "--dry-run",
        action="store_true",
        help="Print what would be created without contacting Roxana.",
    )
    export_parser.add_argument(
        "--new",
        action="store_true",
        help="Start another discussion for an argument already sent, after it has changed.",
    )

    return parser


def run_config() -> int:
    from noesis.config import DEFAULT_CONFIG_PATH, _cache_dir, library_state_dir
    config = load_config()
    print(f"Config file:   {DEFAULT_CONFIG_PATH}")
    print(f"Cache dir:     {_cache_dir}")
    print(f"Library:       {config.library_path or '(none)'}")
    if config.library_path:
        print(f"Library state: {library_state_dir(config.library_path)}")
    return 0


def get_editor() -> str | None:
    return os.environ.get("NOESIS_EDITOR") or os.environ.get("EDITOR")


def run_edit(paths: list[Path]) -> int:
    editor_cmd = get_editor()
    if not editor_cmd:
        for p in paths:
            print(str(p))
        return 0
    subprocess.run([editor_cmd, *[str(p) for p in paths]])
    return 0


def _slug_map(*roots: Path) -> dict[str, list[Path]]:
    seen: dict[str, list[Path]] = {}
    visited: set[Path] = set()
    for root in roots:
        if not root.is_dir():
            continue
        resolved = root.resolve()
        if resolved in visited:
            continue
        visited.add(resolved)
        for p in root.rglob("*.md"):
            if (root / "REVISIONS") in p.parents:
                continue
            seen.setdefault(p.stem, []).append(p)
    return seen


def _collect_existing_slugs(extra_root: Path | None) -> set[str]:
    slugs = {p.name.split(".")[0] for p in Path.cwd().glob("*.md")}
    if extra_root and extra_root.is_dir():
        slugs |= {p.name.split(".")[0] for paths in _slug_map(extra_root).values() for p in paths}
    return slugs


def run_new(title: str | None, edit: bool = False, library_path: Path | None = None) -> int:
    from noesis.library import slug_of, slug_stems
    today = datetime.date.today().isoformat()
    existing = _collect_existing_slugs(library_path)
    # A slug is one stem's, whatever its date (library.slug_stems).
    held = {slug_of(stem): stem for stem in existing if slug_of(stem)}
    if library_path and library_path.is_dir():
        held.update({slug: min(stems) for slug, stems in slug_stems(library_path).items()})
    if title is None:
        base = "Untitled"
        candidate = base
        n = 2
        while slugify(candidate) in held:
            candidate = f"{base} {n}"
            n += 1
        title = candidate
    slug = slugify(title)
    if slug in held and held[slug] != f"{today}-{slug}":
        print(f"Error: the slug '{slug}' is {held[slug]}'s.")
        return 1
    # In a library a new file goes where its name puts it: this year's directory.
    here = Path.cwd()
    if library_path and _is_within(here.resolve(), library_path.resolve()):
        here = library_path / today[:4]
        here.mkdir(exist_ok=True)
    if edit:
        document_filename = f"{today}-{slug}.document.md"
        chat_filename = f"{today}-{slug}.chat.md"
        document_path = here / document_filename
        chat_path = here / chat_filename
        if document_path.exists():
            print(f"Error: '{document_filename}' already exists.")
            return 1
        if chat_path.exists():
            print(f"Error: '{chat_filename}' already exists.")
            return 1
        create_document_file(document_path, title, today)
        chat_path.write_text(
            f"\n# {title}\n{today}\n\n## Prompt\n\n",
            encoding="utf-8",
        )
        print(document_filename)
        print(chat_filename)
        paths = [str(chat_path), str(document_path)]
    else:
        filename = f"{today}-{slug}.chat.md"
        path = here / filename
        if path.exists():
            print(f"Error: '{filename}' already exists.")
            return 1
        path.write_text(f"\n# {title}\n{today}\n\n## Prompt\n\n", encoding="utf-8")
        print(filename)
        paths = [str(path)]
    editor_cmd = get_editor()
    if editor_cmd:
        subprocess.run([editor_cmd, *paths])
    return 0


def run_check(path: Path) -> int:
    if _require_md(path):
        return 1
    from noesis.library import lacks_role
    if lacks_role(path.name):
        print(f"Error: '{path.name}' does not name its role: .chat.md, .document.md or .source.<ext>.")
        return 1
    misplaced_at = _misplaced(path)
    if misplaced_at:
        print(f"Error: '{path.name}' belongs in {misplaced_at.parent.name}/. Run: noesis fix {path.name}")
        return 1
    others = _slug_holders(path)
    if others:
        print(f"Error: '{path.name}' has the slug of {', '.join(others)}; a slug is one stem's. Rename one.")
        return 1
    transcript = parse_transcript(_read_file(path))
    assets_by_turn = collect_local_assets(transcript, path)
    asset_count = sum(len(assets) for assets in assets_by_turn.values())
    if transcript.pending:
        print(
            "OK: transcript is valid, "
            f"{asset_count} local asset(s) resolved, "
            f"and a reply is pending for '{transcript.pending_turn.speaker}'."
        )
    else:
        print(f"OK: transcript is valid, {asset_count} local asset(s) resolved, and no reply is pending.")
    return 0


def _misplaced(path: Path) -> Path | None:
    from noesis.library import misplaced
    library = load_config().library_path
    return misplaced(library, path) if library else None


def _slug_holders(path: Path) -> list[str]:
    """The other stems of the library with this file's slug."""
    from noesis.library import slug_of, slug_stems
    library = load_config().library_path
    if not library or not slug_of(path.name) or not _is_within(path.resolve(), library.resolve()):
        return []
    stem = path.name.split(".")[0]
    return sorted(slug_stems(library).get(slug_of(path.name), set()) - {stem})


def _ask(question: str, yes: bool) -> bool:
    """A y/N question, answered yes in advance by --yes."""
    if yes:
        print(f"{question} y")
        return True
    try:
        return input(f"{question} ").strip().lower() == "y"
    except EOFError:
        return False


def _offer_move(path: Path, yes: bool = False) -> Path | None:
    """Offer to move a misplaced file, with its companions, into its year directory."""
    from noesis.library import move_documents, same_stem_files
    target = _misplaced(path)
    if not target:
        return None
    group = same_stem_files(path)
    print(f"{path}:")
    for p in group:
        print(f"  would move: {p.name} → {target.parent.name}/")
    if not _ask("Move? [y/N]", yes):
        print("  Skipped.")
        return None
    move_documents(load_config().library_path, {p: target.parent / p.name for p in group})
    print("  Moved.")
    return target


def _form_of(path: Path) -> str:
    """Which rules a file answers to, by its name: its role (chat, document,
    source, argument), "keys", "written" for what noesis writes, else "plain"."""
    from noesis.library import GENERATED_FILENAMES, KEYS_FILENAME, RECORD_DIRS, role_of
    if path.name == KEYS_FILENAME:
        return "keys"
    if path.name in GENERATED_FILENAMES or RECORD_DIRS.intersection(p.name for p in path.parents):
        return "written"
    role = role_of(path.name)
    if role in ("analysis", "review"):
        return "written"
    return role or "plain"


def _form_issues(path: Path, form: str) -> list[str]:
    """What is wrong with a file by the rules of its form."""
    from noesis.argue import check_argument
    from noesis.form import has_bare_labels, is_exported_chat
    from noesis.library import check_keys
    if form == "chat":
        return check_file(path)
    errs = check_encoding(path)
    text = _read_file(path)
    if form == "document" and (has_bare_labels(text) or is_exported_chat(text)):
        errs.append("reads like a chat (speaker labels such as 'Prompt:' or an exported chat's headings): "
                    "if it is one, its role is .chat.md")
    elif form == "argument":
        errs += check_argument(text)
    elif form == "keys":
        errs += check_keys(text)
    return errs


def run_validate(paths: list[Path]) -> int:
    from noesis.library import library_titles, resolve_title_among

    config = load_config()
    lib = config.library_path if config.library_path and config.library_path.is_dir() else None
    # From the files, not index state: a mirror's copy of that is never updated.
    titles = library_titles(lib) if lib else {}
    # In chronological order: their names begin with their date.
    doc_order = {name: i for i, name in enumerate(sorted(Path(rel).name for rel in titles))}

    any_errors = False
    for path in paths:
        if _require_md(path):
            any_errors = True
            continue
        form = _form_of(path)
        errs = _form_issues(path, form)
        if form == "chat" and lib and not errs:
            try:
                transcript = parse_transcript(_read_file(path))
                for entry in transcript.related:
                    rel_path = resolve_title_among(titles, entry)
                    if rel_path is None:
                        errs.append(f"Related title not found in library: {entry!r}")
                    elif doc_order.get(Path(rel_path).name, -1) >= doc_order.get(path.name, -1):
                        errs.append(f"Related title does not precede this document: {entry!r}")
            except TranscriptError:
                pass

        if errs:
            print(f"{path} [{form}]:")
            for e in errs:
                print(f"  error: {e}")
            any_errors = True
        else:
            print(f"{path}: OK [{form}]")
    return 1 if any_errors else 0


def run_fix(paths: list[Path], yes: bool = False) -> int:
    # A library keeps no backups beside its files: the diff is shown before
    # anything is applied, and a mirrored library's server holds a copy.
    library = load_config().library_path
    any_errors = False
    for path in paths:
        if _require_md(path):
            any_errors = True
            continue
        form = _form_of(path)
        if form == "written":
            print(f"{path}: written by noesis, never by hand; fix leaves it alone.")
            any_errors = True
            continue
        raw = _read_file(path)
        # Only a chat takes a transcript's repairs; every file, the encoding's.
        lines, applied = raw.split("\n"), []
        if form == "chat":
            lines, applied = fix_exported_chat(lines, path)
        lines, orc_applied = fix_object_replacement(lines)
        lines, rtl_applied = fix_rtl_spans(lines)
        applied += orc_applied + rtl_applied
        new_text = "\n".join(lines)
        if form == "chat":
            title_lines, title_applied = fix_title_section(lines)
            new_text, spacing_applied = fix_section_spacing("\n".join(title_lines))
            applied += title_applied + spacing_applied

        if applied:
            diff = list(difflib.unified_diff(
                raw.splitlines(keepends=True),
                new_text.splitlines(keepends=True),
                fromfile=f"{path} (original)",
                tofile=f"{path} (fixed)",
            ))
            print(f"{path}:")
            for fix in applied:
                print(f"  would fix: {fix}")
            print()
            sys.stdout.writelines(diff)
            print()
            if _ask("Apply changes? [y/N]", yes):
                if not (library and _is_within(path.resolve(), library.resolve())):
                    path.with_suffix(".md.bak").write_text(raw, encoding="utf-8")
                path.write_text(new_text, encoding="utf-8")
                print("  Applied.")
            else:
                print("  Skipped.")
                print()
                continue

        moved_to = _offer_move(path, yes)
        if moved_to:
            applied.append("moved into its year directory")
            path = moved_to

        errs = _form_issues(path, form)

        if not applied and not errs:
            print(f"{path}: OK")
        elif errs:
            if not applied:
                print(f"{path}:")
            for e in errs:
                print(f"  error: {e}")
            any_errors = True

    return 1 if any_errors else 0

