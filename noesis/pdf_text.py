"""A PDF's text, for read_file: its text layer, page after page, by pypdf.

A scanned PDF has no text layer and reads as nothing; an encrypted one is read
only when it opens without a password.
"""

from __future__ import annotations

from pathlib import Path


class NotAPdf(ValueError):
    """The file is not a PDF this can read."""


def pdf_text(path: Path) -> str:
    """The text of each page, a blank line between pages; empty pages left out."""
    from pypdf import PdfReader
    try:
        reader = PdfReader(path)
        if reader.is_encrypted and not reader.decrypt(""):
            raise NotAPdf("it is encrypted")
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
    except NotAPdf:
        raise
    except Exception as e:  # pypdf raises many kinds on a malformed file
        raise NotAPdf(str(e)) from e
    return "\n\n".join(page for page in pages if page)
