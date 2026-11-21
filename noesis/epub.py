"""An EPUB's text, for read_file: its spine's chapters in reading order, as plain text.

An EPUB is a zip of XHTML: META-INF/container.xml names the package file,
whose manifest names each chapter and whose spine orders them. Read with the
standard library alone; nothing outside the zip is ever resolved.
"""

from __future__ import annotations

import posixpath
import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote
from xml.etree import ElementTree

_CONTAINER = "{urn:oasis:names:tc:opendocument:xmlns:container}"
_OPF = "{http://www.idpf.org/2007/opf}"

# The most a book's chapters may inflate to: a zip's sizes are its own claim,
# so an entry larger than this is refused rather than read.
MAX_BYTES = 64 * 1024 * 1024

_BLOCKS = frozenset({
    "address", "article", "aside", "blockquote", "br", "dd", "div", "dl", "dt", "figcaption",
    "figure", "footer", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li", "ol", "p",
    "pre", "section", "table", "td", "th", "tr", "ul",
})
_SKIPPED = frozenset({"head", "script", "style", "title"})


class NotAnEpub(ValueError):
    """The file is not an EPUB this can read."""


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skipping = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _SKIPPED:
            self.skipping += 1
        elif tag in _BLOCKS:
            self.parts.append("\n")

    def handle_startendtag(self, tag: str, attrs) -> None:
        if tag in _BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED:
            self.skipping = max(0, self.skipping - 1)
        elif tag in _BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skipping:
            self.parts.append(data)


def html_text(html: str) -> str:
    """An XHTML chapter as paragraphs: a blank line between blocks, spaces collapsed."""
    parser = _Text()
    parser.feed(html)
    parser.close()
    lines = (re.sub(r"[ \t\r\f\v ]+", " ", line).strip() for line in "".join(parser.parts).split("\n"))
    return "\n\n".join(line for line in lines if line)


def epub_text(path: Path) -> str:
    """The book's text, chapter after chapter in its spine's order."""
    try:
        with zipfile.ZipFile(path) as book:
            def read(name: str) -> bytes:
                info = book.getinfo(name)
                if info.file_size > MAX_BYTES:
                    raise NotAnEpub(f"{name} is larger than a book's chapter can be")
                return book.read(info)

            rootfile = ElementTree.fromstring(read("META-INF/container.xml")).find(f".//{_CONTAINER}rootfile")
            if rootfile is None or not rootfile.get("full-path"):
                raise NotAnEpub("its container names no package")
            package_path = rootfile.get("full-path")
            package = ElementTree.fromstring(read(package_path))
            base = posixpath.dirname(package_path)
            hrefs = {item.get("id"): item.get("href") for item in package.iter(f"{_OPF}item")}
            chapters, total = [], 0
            for ref in package.iter(f"{_OPF}itemref"):
                href = hrefs.get(ref.get("idref"))
                if not href:
                    continue
                name = posixpath.normpath(posixpath.join(base, unquote(href.split("#", 1)[0])))
                try:
                    raw = read(name)
                except KeyError:
                    continue
                total += len(raw)
                if total > MAX_BYTES:
                    raise NotAnEpub("its chapters are larger than a book can be")
                text = html_text(raw.decode("utf-8", errors="replace"))
                if text:
                    chapters.append(text)
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as e:
        raise NotAnEpub(str(e)) from e
    return "\n\n".join(chapters)
