from __future__ import annotations

import re
import sys
from pathlib import Path


def _print_argument(args_dict: dict) -> None:
    from noesis.argue import _clauses, assign_argument_labels

    argument = args_dict.get("argument", [])
    labels = assign_argument_labels(argument)
    print("Argument:")
    for s in argument:
        j = _clauses(s)
        label = f" [{labels[s['symbol']]}]" if s["symbol"] in labels else ""
        print(f"  {s['symbol']}{j}{label}: {s['proposition']}")


def _as_named(text: str, path: Path, people) -> str:
    """The text as dianoia reads it: each person's chat headings as the name
    they are given (`## Prompt` is the owner), and a person's own document
    said to be theirs, which nothing in it says."""
    if not people:
        return text
    if path.name.endswith(".chat.md"):
        named = {h: m.name for m in people for h in m.headings}
        # A turn's heading alone, never the line breaks after it.
        heading = re.compile(r"^(##)[ \t]+(.+?)[ \t]*$", re.MULTILINE)
        return heading.sub(lambda h: f"{h.group(1)} {named.get(h.group(2), h.group(2))}", text)
    if len(people) == 1:
        return f"[Written by {people[0].name}.]\n{text}"
    return text


def run_argue(path: Path, max_props: int | None = None) -> int:
    from noesis.argue import (INFERENCE_STANCES, PROPOSITION_STANCES, _read_title_date,
                              argument_to_markdown, nameable, source_of)
    from noesis import dianoia_client
    from noesis.config import load_config
    from noesis.form import check_global_issues

    def _read_file(p: Path) -> str:
        try:
            return p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = p.read_text(encoding="latin-1")
            p.with_suffix(p.suffix + ".bak").write_bytes(p.read_bytes())
            p.write_text(text, encoding="utf-8")
            print(f"Warning: {p.name} was not UTF-8; converted in place (backup: {p.name}.bak).", file=sys.stderr)
            return text

    # From a document or a chat; an argument file's stem prefers its document.
    if path.name.endswith(".argument.md"):
        companion = path
        path = source_of(path)
    elif path.name.endswith((".document.md", ".chat.md")):
        companion = path.with_suffix("").with_suffix(".argument.md")
    else:
        print(f"Error: '{path.name}' is neither a document nor a chat: argue reads a .document.md or a .chat.md.")
        return 1
    if not path.exists() and not companion.exists():
        print(f"Error: '{path}' does not exist.")
        return 1

    if companion.exists():
        print(f"'{companion.name}' already exists. To analyze an argument in it, run: noesis analyze {path.name} <proposition>")
        return 0

    # Extract: no companion yet — validate and extract from the primary document
    text = _read_file(path)
    errs = check_global_issues(path)
    if errs:
        for e in errs:
            print(f"  error: {e}")
        return 1

    # One argument every person in it took part in, with who accepts and who
    # rejects each proposition and inference, by display name: a channel's
    # members, or a person's library's owner (config.people). Claude is none.
    people = [m for m in load_config().people if nameable(m.name)]
    participants = [m.name for m in people]
    print("Extracting argument…")
    try:
        args_dict = dianoia_client.extract(_as_named(text, path, people), max_props=max_props,
                                           participants=participants or None)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    # Members alone, never on both sides of a pair, and an inference only
    # where the step has justifiers to infer from.
    for step in args_dict.get("argument") or []:
        for accepting, rejecting in (PROPOSITION_STANCES, INFERENCE_STANCES):
            accepted = [n for n in step.pop(accepting, None) or [] if n in participants]
            rejected = [n for n in step.pop(rejecting, None) or [] if n in participants and n not in accepted]
            if accepting in INFERENCE_STANCES and not step.get("justifiers"):
                continue
            for stance, named in ((accepting, accepted), (rejecting, rejected)):
                if named:
                    step[stance] = named
    try:
        title, date_str = _read_title_date(text)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    try:
        companion_text = argument_to_markdown(args_dict, title, date_str)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    companion.write_text(companion_text, encoding="utf-8")
    _print_argument(args_dict)
    print(f"\nWritten to {companion.name}. Edit it, then run: noesis analyze {path.name} <proposition>")
    return 0
