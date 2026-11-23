"""A PDF's parts: the whole of a short one, else page ranges by its
bookmarks, else by its section headings, else by tens, each given
either as its pages, a PDF of its own (read_file, for a model, which sees
them as they are printed), or as its text layer (read_text, for reading
aloud), both by pypdf.

A paper of up to MAX_PART_PAGES is one part, since it is read whole. A longer
one without bookmarks is cut at the numbered headings of its text layer, a
paper's "2. PERCEPTUAL EXPERIENCE", and at its notes and references: finding
them reads every page, so the parts are kept per file while it is unchanged. A scanned PDF has no text
layer and reads as nothing, though its pages are still given; an encrypted
one is read only when it opens without a password.
"""

from __future__ import annotations

import re
from functools import lru_cache
from io import BytesIO
from pathlib import Path

# Pages to a part where the PDF has neither bookmarks nor headings, and the
# most a part may run before it is split; a PDF no longer is read whole.
PAGES_PER_PART = 10
MAX_PART_PAGES = 25

# A section heading as a text layer gives it: an arabic or roman number, then
# a short title in capitals or title case, without a sentence's closing stop.
_HEADING_RE = re.compile(r"^(?:(\d{1,2})|([IVXLC]{1,6}))\.?\s+(\S.{0,100})$")
_ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}
END_MATTER = ("notes", "endnotes", "references", "bibliography", "works cited")


class NotAPdf(ValueError):
    """The file is not a PDF this can read."""


def _reader(path: Path):
    from pypdf import PdfReader
    reader = PdfReader(path)
    if reader.is_encrypted and not reader.decrypt(""):
        raise NotAPdf("it is encrypted")
    return reader


def _ranges(start: int, stop: int, size: int) -> list[range]:
    return [range(at, min(at + size, stop)) for at in range(start, stop, size)]


def _roman(numeral: str) -> int:
    values = [_ROMAN[c] for c in numeral]
    return sum(-v if v < after else v for v, after in zip(values, [*values[1:], 0]))


def _is_title(title: str) -> bool:
    words = re.findall(r"[^\W\d_][\w'’-]*", title)
    major = [w for w in words if len(w) > 3]
    return (0 < len(words) <= 12 and bool(major) and all(w[0].isupper() for w in major)
            and not title.rstrip().endswith((".", ",", ";", ":")))


def _headings(reader, count: int) -> list[tuple[int, str]]:
    """Where its sections begin, by its text layer: numbered headings in their
    order (1, 2, 3 or I, II, III), so a numbered premise in the text is not
    one, and its notes and references in its second half."""
    marks: list[tuple[int, str]] = []
    expected, ended = 1, set()
    for n in range(count):
        for line in (reader.pages[n].extract_text() or "").splitlines():
            line = " ".join(line.split())
            found = _HEADING_RE.match(line)
            if found and _is_title(found.group(3)):
                number = int(found.group(1)) if found.group(1) else _roman(found.group(2))
                if number == expected:
                    marks.append((n, line))
                    expected += 1
            elif line.lower() in END_MATTER and line.lower() not in ended and n >= count // 2:
                ended.add(line.lower())
                marks.append((n, line[:1].upper() + line[1:].lower()))
    return marks


def pdf_parts(path: Path) -> list[tuple[str, range]]:
    """The PDF's parts, each a title and its pages (0-based), in page order."""
    stat = path.stat()
    return _pdf_parts(str(path), stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=64)
def _pdf_parts(path_name: str, mtime_ns: int, size: int) -> list[tuple[str, range]]:
    path = Path(path_name)
    try:
        reader = _reader(path)
        count = len(reader.pages)
        if count <= MAX_PART_PAGES:
            return [("", range(count))] if count else []
        top = [entry for entry in reader.outline if not isinstance(entry, list)]
        if len(top) < 2:  # one bookmark for the whole: its children, if any
            nested = next((entry for entry in reader.outline if isinstance(entry, list)), [])
            top = [entry for entry in nested if not isinstance(entry, list)] or top
        marks: list[tuple[int, str]] = []
        for entry in top:
            try:
                page = reader.get_destination_page_number(entry)
            except Exception:
                continue
            if page is not None and 0 <= page < count and all(page != at for at, _ in marks):
                marks.append((page, str(entry.title or "").strip()))
        if len(marks) < 2:
            marks = []
            for page, title in _headings(reader, count):  # two on a page share its part
                if marks and marks[-1][0] == page:
                    marks[-1] = (page, f"{marks[-1][1]}; {title}")
                else:
                    marks.append((page, title))
        marks.sort()
    except NotAPdf:
        raise
    except Exception as e:  # pypdf raises many kinds on a malformed file
        raise NotAPdf(str(e)) from e
    if len(marks) < 2:
        return [("", pages) for pages in _ranges(0, count, PAGES_PER_PART)]
    if marks[0][0] > 0:
        marks.insert(0, (0, "Front matter"))
    parts: list[tuple[str, range]] = []
    for (start, title), (stop, _) in zip(marks, [*marks[1:], (count, "")]):
        pieces = _ranges(start, stop, MAX_PART_PAGES)
        for n, pages in enumerate(pieces, 1):
            parts.append((f"{title} ({n} of {len(pieces)})" if len(pieces) > 1 else title, pages))
    return parts


def pdf_pages_text(path: Path, pages: range) -> str:
    """The text of these pages, a blank line between pages; empty ones left out."""
    try:
        reader = _reader(path)
        texts = [(reader.pages[n].extract_text() or "").strip() for n in pages]
    except NotAPdf:
        raise
    except Exception as e:
        raise NotAPdf(str(e)) from e
    return "\n\n".join(text for text in texts if text)


def pdf_pages(path: Path, pages: range) -> bytes:
    """These pages as a PDF of their own."""
    from pypdf import PdfWriter
    try:
        reader = _reader(path)
        writer = PdfWriter()
        for n in pages:
            writer.add_page(reader.pages[n])
        out = BytesIO()
        writer.write(out)
    except NotAPdf:
        raise
    except Exception as e:
        raise NotAPdf(str(e)) from e
    return out.getvalue()
