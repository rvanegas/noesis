"""A PDF's parts, for read_file: page ranges by its bookmarks, else by tens,
each read as its text layer by pypdf.

The outline is had without extracting any text, so a long PDF's parts are
listed cheaply and only the part asked for is read. A scanned PDF has no text
layer and reads as nothing; an encrypted one is read only when it opens
without a password.
"""

from __future__ import annotations

from pathlib import Path

# Pages to a part where the PDF has no bookmarks, and the most a bookmarked
# part may run before it is split.
PAGES_PER_PART = 10
MAX_PART_PAGES = 25


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


def pdf_parts(path: Path) -> list[tuple[str, range]]:
    """The PDF's parts, each a title and its pages (0-based), in page order."""
    try:
        reader = _reader(path)
        count = len(reader.pages)
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
        marks.sort()
    except NotAPdf:
        raise
    except Exception as e:  # pypdf raises many kinds on a malformed file
        raise NotAPdf(str(e)) from e
    if not count:
        return []
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
