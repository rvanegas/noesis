"""Conversion between noesis's argument markdown format and dianoia's Arguments JSON."""

from __future__ import annotations

import re
from pathlib import Path


# `- 3 (from: 1, 2; accepted: Ann; rejected: Cy; inference accepted: Ann, Cy;
# inference rejected: Bob): text`: justifiers, and in a channel's library which
# members accept and reject the proposition, and, where it has justifiers, the
# inference to it from them (STANCES; the clause is the key, spaced).
_ARGUMENT_RE = re.compile(r"^- (\d+)(?:\s+\(([^()]*)\))?\s*:\s+(.+)$")
STANCES = ("accepted", "rejected", "inference_accepted", "inference_rejected")
# The proposition's pair, and its inference's: Roxana's stances on a
# proposition, and on the argument a step with justifiers makes.
PROPOSITION_STANCES = STANCES[:2]
INFERENCE_STANCES = STANCES[2:]
_CLAUSES = ("from", *(stance.replace("_", " ") for stance in STANCES))
_CLAUSE_RE = re.compile(rf"^({'|'.join(_CLAUSES)}):\s*(.*)$")
# What a name in a stance cannot hold, being the clause's own punctuation.
_STANCE_PUNCTUATION = set(",;()")
_PROP_SYMBOL_RE = re.compile(r"^- (\d+)[\s:(]")
_DECORATED_PROP_RE = re.compile(r"^- (\d[\w'*]*)[\s:(]")


def _read_title_date(text: str) -> tuple[str, str]:
    """Extract title and date from the first few lines of an noesis preamble."""
    lines = text.splitlines()
    title: str | None = None
    date_str: str | None = None
    for line in lines[:6]:
        line = line.strip()
        if line.startswith("# ") and title is None:
            title = line[2:].strip()
        elif re.match(r"^\d{4}-\d{2}-\d{2}$", line) and date_str is None:
            date_str = line
        if title and date_str:
            break
    if not title:
        raise ValueError("could not find '# Title' in preamble")
    if not date_str:
        raise ValueError("could not find date line in preamble")
    return title, date_str


def source_of(companion: Path) -> Path:
    """What an argument file is extracted from: its stem's document, else its chat
    (cmd_argue), the document named where there is neither."""
    document = companion.with_suffix("").with_suffix(".document.md")
    chat = companion.with_suffix("").with_suffix(".chat.md")
    return chat if chat.exists() and not document.exists() else document


def naming(argument: list[dict], names: list[str]) -> list[tuple[str, str]]:
    """The propositions that name a participant, (symbol, name): who holds a
    proposition is its stances, and a proposition that names one ("Ann's
    standard…", "Ann herself judged…") puts the attribution where the content
    should be (dianoia's extraction prompt says so; this catches what slips
    through). A name is found whole or by any word of it of three letters or
    more, as a whole word and in any case."""
    found = []
    for step in argument:
        text = step.get("proposition", "")
        for name in names:
            words = [name, *(w for w in name.split() if len(w) >= 3)]
            if any(re.search(rf"(?<!\w){re.escape(w)}(?!\w)", text, re.IGNORECASE) for w in words):
                found.append((str(step.get("symbol")), name))
                break
    return found


def nameable(name: str) -> bool:
    """Whether a member's name can stand in a stance: not empty, and none of its punctuation."""
    return bool(name.strip()) and not _STANCE_PUNCTUATION & set(name)


def _clauses(step: dict) -> str:
    """A step's parenthesis: its justifiers, then who accepts and who rejects it and its inference."""
    clauses = [f"from: {', '.join(step['justifiers'])}"] if step.get("justifiers") else []
    for stance in STANCES:
        names = step.get(stance) or []
        label = stance.replace("_", " ")
        bad = [n for n in names if not nameable(n)]
        if bad:
            raise ValueError(f"name(s) {bad} cannot stand in '{label}': no commas, semicolons or parentheses")
        if names and stance in INFERENCE_STANCES and not step.get("justifiers"):
            raise ValueError(f"step {step.get('symbol')} has no justifiers, so no inference to stand on")
        if names:
            clauses.append(f"{label}: {', '.join(names)}")
    return f" ({'; '.join(clauses)})" if clauses else ""


def _parse_clauses(raw: str | None, lineno: int) -> dict[str, list[str]]:
    """The parenthesis back into justifiers (`from`) and stances (by STANCES' keys)."""
    parsed: dict[str, list[str]] = {}
    for clause in (raw or "").split(";"):
        if not clause.strip():
            continue
        m = _CLAUSE_RE.match(clause.strip())
        key = m.group(1).replace(" ", "_") if m else None
        if not m or key in parsed:
            raise ValueError(f"line {lineno}: cannot parse '({raw})': expected "
                             f"{', '.join(repr(c + ':') for c in _CLAUSES)}, once each")
        values = [v.strip() for v in m.group(2).split(",") if v.strip()]
        if key == "from" and not all(v.isdigit() for v in values):
            raise ValueError(f"line {lineno}: justifiers must be proposition numbers: '({raw})'")
        parsed[key] = values
    if any(parsed.get(stance) for stance in INFERENCE_STANCES) and not parsed.get("from"):
        raise ValueError(f"line {lineno}: an inference's stances need its justifiers, 'from:': '({raw})'")
    for accepting, rejecting in (PROPOSITION_STANCES, INFERENCE_STANCES):
        both = set(parsed.get(accepting, [])) & set(parsed.get(rejecting, []))
        if both:
            raise ValueError(f"line {lineno}: {sorted(both)} both accept and reject the same thing: '({raw})'")
    return parsed


def _to_alpha_index(n: int) -> str:
    """Convert a 0-based index to a base-26 letter label: 0->A, 25->Z, 26->AA, ...

    Direct port of Roxana's toAlphaIndex (~/src/roxana/src/app/util.tsx).
    """
    base = ord("A")
    letters: list[str] = []
    while n >= 0:
        n, remainder = divmod(n, 26)
        letters.append(chr(base + remainder))
        n -= 1
    return "".join(reversed(letters))


def assign_argument_labels(argument: list[dict]) -> dict[str, str]:
    """Map each justified proposition's symbol to a Roxana-style letter label.

    Only propositions with at least one justifier are "arguments" in Roxana's
    sense (premises -> conclusion); labels are assigned in ascending order of
    proposition number, matching the "ordered according to the proposition
    being argued for" rule. Labels are computed on demand, never persisted.
    """
    justified = sorted(int(s["symbol"]) for s in argument if s.get("justifiers"))
    return {str(sym): _to_alpha_index(i) for i, sym in enumerate(justified)}


def argument_to_markdown(args_dict: dict, title: str, date_str: str) -> str:
    """Convert a dianoia Arguments dict to companion argument markdown.

    Raises ValueError on malformed input.
    """
    argument = args_dict.get("argument")

    if argument is None:
        raise ValueError("argument dict must have an 'argument' key")
    if not isinstance(argument, list):
        raise ValueError("'argument' must be a list")
    if not argument:
        raise ValueError("argument must have at least one step")

    lines = ["", f"# {title}", date_str, "", "## Argument"]
    symbols: list[int] = []
    for step in argument:
        symbol = step.get("symbol", "")
        prop = step.get("proposition", "")
        if not symbol or not prop:
            raise ValueError(f"argument step missing symbol or proposition: {step!r}")
        lines.append(f"- {symbol}{_clauses(step)}: {prop}")
        symbols.append(int(symbol))
    lines.append("")

    err = _check_full_sequence(set(symbols))
    if err:
        raise ValueError(err)

    return "\n".join(lines)


_CORE_SECTIONS = {"Argument"}


def extract_core_sections(text: str) -> str:
    """Return only the preamble and the core ## Argument section.

    Raises ValueError if any other section (e.g. a legacy ## Definitions or
    evaluation section) is present — argument files must contain nothing but
    the proposition list.
    """
    # Split on ## headings, keeping the delimiters
    parts = re.split(r"(?=^## )", text, flags=re.MULTILINE)
    kept: list[str] = []
    for part in parts:
        m = re.match(r"^## (\S+)", part)
        if m is None:
            # Preamble (before the first ## heading)
            kept.append(part)
        elif m.group(1) in _CORE_SECTIONS:
            kept.append(part)
        else:
            raise ValueError(
                f"Unexpected section '## {m.group(1)}' in argument file. "
                "Argument files must contain only a ## Argument section."
            )
    return "".join(kept)


def markdown_to_argument(text: str) -> dict:
    """Parse companion argument markdown back to a dianoia Arguments dict.

    Retains only the preamble and core sections before parsing.
    Raises ValueError on parse failure.
    """
    text = extract_core_sections(text)

    argument: list[dict] = []
    current_section: str | None = None

    for lineno, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.strip()

        if line == "## Argument":
            current_section = "argument"
            continue
        if line.startswith("## "):
            current_section = None
            continue

        if not line or line.startswith("#"):
            continue

        if current_section == "argument" and line.startswith("- "):
            m = _ARGUMENT_RE.match(line)
            if not m:
                raise ValueError(f"line {lineno}: cannot parse argument step: {raw_line!r}")
            clauses = _parse_clauses(m.group(2), lineno)
            argument.append({
                "symbol": m.group(1),
                "proposition": m.group(3).strip(),
                "justifiers": clauses.get("from", []),
                # required by dianoia's Step wire schema; not part of noesis's own
                # format and never round-tripped through argument_to_markdown
                "truth_score": "",
                # A channel's stances, only where the file has them.
                **{stance: clauses[stance] for stance in STANCES if clauses.get(stance)},
            })
            continue

    if not argument:
        raise ValueError("no argument steps found in file")

    return {"argument": argument}


def _prop_numbers_in_sections(text: str) -> tuple[set[int], list[str]]:
    """Return (integer proposition numbers, decorated symbols) found in the Argument section."""
    numbers: set[int] = set()
    decorated: list[str] = []
    in_target = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "## Argument":
            in_target = True
            continue
        if stripped.startswith("## "):
            in_target = False
            continue
        if in_target and stripped.startswith("- "):
            if _PROP_SYMBOL_RE.match(stripped):
                numbers.add(int(_PROP_SYMBOL_RE.match(stripped).group(1)))
            elif _DECORATED_PROP_RE.match(stripped):
                decorated.append(_DECORATED_PROP_RE.match(stripped).group(1))
    return numbers, decorated


def _check_full_sequence(nums: set[int]) -> str | None:
    """Return an error message if nums isn't a contiguous 1..N sequence, else None."""
    expected = set(range(1, len(nums) + 1))
    if nums != expected:
        missing = sorted(expected - nums)
        return (
            f"Proposition numbers must be a contiguous sequence starting at 1 "
            f"with no gaps (missing: {missing})."
        )
    return None


def check_argument(text: str) -> list[str]:
    """What is wrong with an .argument.md: one ## Argument, numbered 1..N."""
    sections = [line.strip() for line in text.splitlines() if line.strip().startswith("## ")]
    if sections != ["## Argument"]:
        return [f"expected exactly one section, '## Argument'; found {sections or 'none'}"]
    numbers, decorated = _prop_numbers_in_sections(text)
    errors = []
    for lineno, line in enumerate(text.splitlines(), 1):
        m = _ARGUMENT_RE.match(line.strip())
        if m:
            try:
                _parse_clauses(m.group(2), lineno)
            except ValueError as e:
                errors.append(str(e))
    if decorated:
        errors.append(f"invalid proposition symbol(s) {decorated}: use plain integers only")
    gap = _check_full_sequence(numbers)
    if gap:
        errors.append(gap)
    return errors


def validate_proposition_numbering(old_text: str, new_text: str) -> str | None:
    """Return an error message if the edit violates proposition numbering rules, else None."""
    old_nums, _ = _prop_numbers_in_sections(old_text)
    new_nums, decorated = _prop_numbers_in_sections(new_text)

    if decorated:
        return (
            f"Invalid proposition symbol(s) {decorated}: use plain integers only "
            "(no subscripts, primes, apostrophes, or asterisks)."
        )

    missing = old_nums - new_nums
    if missing:
        return (
            f"Proposition(s) {sorted(missing)} were renumbered or removed. "
            "Existing proposition numbers must not change."
        )

    added = new_nums - old_nums
    if added and old_nums:
        max_old = max(old_nums)
        conflicts = sorted(n for n in added if n <= max_old)
        if conflicts:
            return (
                f"New proposition number(s) {conflicts} fall within the existing range "
                f"(current max: {max_old}). New propositions must be numbered after the maximum."
            )

    return _check_full_sequence(new_nums)
