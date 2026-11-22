"""An EPUB's parts, for read_file: its chapters as its table of contents names
them, each as plain text, in its spine's order.

An EPUB is a zip of XHTML: META-INF/container.xml names the package file,
whose manifest names each file, whose spine orders them, and whose table of
contents (an EPUB 3 nav, else an EPUB 2 toc.ncx) titles them. A part begins
at each file the table of contents points to and runs until the next; with no
table of contents, each file is a part. Read with the standard library alone;
nothing outside the zip is ever resolved.
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
_NCX = "{http://www.daisy.org/z3986/2005/ncx/}"
_XHTML = "{http://www.w3.org/1999/xhtml}"
_OPS = "{http://www.idpf.org/2007/ops}"

# The most a book's files may inflate to: a zip's sizes are its own claim,
# so an entry, or a book, larger than this is refused rather than read.
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
    """An XHTML file's text in pieces, and where each anchor asked for begins."""

    def __init__(self, anchors: frozenset[str] = frozenset()) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skipping = 0
        self.anchors = anchors
        self.marks: dict[str, int] = {}

    def _mark(self, attrs) -> None:
        for key, value in attrs:
            if key in ("id", "name") and value in self.anchors:
                self.marks.setdefault(value, len(self.parts))

    def handle_starttag(self, tag: str, attrs) -> None:
        self._mark(attrs)
        if tag in _SKIPPED:
            self.skipping += 1
        elif tag in _BLOCKS:
            self.parts.append("\n")

    def handle_startendtag(self, tag: str, attrs) -> None:
        self._mark(attrs)
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


def _paragraphs(raw: str) -> str:
    """Pieces of text as paragraphs: a blank line between blocks, spaces collapsed."""
    lines = (re.sub(r"[ \t\r\f\v ]+", " ", line).strip() for line in raw.split("\n"))
    return "\n\n".join(line for line in lines if line)


def html_text(html: str) -> str:
    """An XHTML file as paragraphs."""
    return cut_html(html, [])[0][1]


def cut_html(html: str, anchors: list[str]) -> list[tuple[list[str], str]]:
    """An XHTML file's text cut where each anchor begins, in the file's order,
    each piece with the anchors it begins at: first the text before any (no
    anchors), then from each place an anchor is to the next. Anchors at one
    place share a piece; one the file lacks is left out."""
    parser = _Text(frozenset(anchors))
    parser.feed(html)
    parser.close()
    at: dict[int, list[str]] = {}
    for anchor in anchors:
        if anchor in parser.marks and anchor not in at.get(parser.marks[anchor], []):
            at.setdefault(parser.marks[anchor], []).append(anchor)
    bounds = [0, *sorted(at), len(parser.parts)]
    return [(at.get(a, []) if i else [], _paragraphs("".join(parser.parts[a:b])))
            for i, (a, b) in enumerate(zip(bounds, bounds[1:]))]


def _label(element: ElementTree.Element) -> str:
    return re.sub(r"\s+", " ", "".join(element.itertext())).strip()


def epub_parts(path: Path) -> list[tuple[str, str]]:
    """The book's parts, each a title and its text, in reading order."""
    try:
        with zipfile.ZipFile(path) as book:
            read_bytes = 0

            def read(name: str) -> bytes:
                nonlocal read_bytes
                info = book.getinfo(name)
                read_bytes += info.file_size
                if info.file_size > MAX_BYTES or read_bytes > MAX_BYTES:
                    raise NotAnEpub("it is larger than a book can be")
                return book.read(info)

            rootfile = ElementTree.fromstring(read("META-INF/container.xml")).find(f".//{_CONTAINER}rootfile")
            if rootfile is None or not rootfile.get("full-path"):
                raise NotAnEpub("its container names no package")
            package_path = rootfile.get("full-path")
            package = ElementTree.fromstring(read(package_path))

            def resolved(base_file: str, href: str) -> str:
                return posixpath.normpath(posixpath.join(posixpath.dirname(base_file), unquote(href.split("#", 1)[0])))

            def target(base_file: str, href: str) -> tuple[str, str | None]:
                """A link's file, and the anchor in it, if any."""
                fragment = unquote(href.split("#", 1)[1]) if "#" in href else None
                return resolved(base_file, href), fragment or None

            manifest = {item.get("id"): item for item in package.iter(f"{_OPF}item")}
            nav = next((resolved(package_path, item.get("href", "")) for item in manifest.values()
                        if "nav" in (item.get("properties") or "").split()), None)
            spine_element = package.find(f"{_OPF}spine")
            ncx_item = manifest.get(spine_element.get("toc")) if spine_element is not None else None
            ncx = resolved(package_path, ncx_item.get("href", "")) if ncx_item is not None else None

            # The table of contents, as (file, anchor, title) in its own order.
            entries: list[tuple[str, str | None, str]] = []
            if nav:
                try:
                    tree = ElementTree.fromstring(read(nav))
                    tocs = [n for n in tree.iter(f"{_XHTML}nav") if n.get(f"{_OPS}type") == "toc"]
                    for a in (tocs[0] if tocs else tree).iter(f"{_XHTML}a"):
                        if a.get("href"):
                            entries.append((*target(nav, a.get("href")), _label(a)))
                except (KeyError, ElementTree.ParseError):
                    entries = []
            if not entries and ncx:
                try:
                    for point in ElementTree.fromstring(read(ncx)).iter(f"{_NCX}navPoint"):
                        text, content = point.find(f"{_NCX}navLabel/{_NCX}text"), point.find(f"{_NCX}content")
                        if content is not None and content.get("src"):
                            entries.append((*target(ncx, content.get("src")), _label(text) if text is not None else ""))
                except (KeyError, ElementTree.ParseError):
                    entries = []

            parts: list[list] = []  # [titles, [texts]]

            def begin(titles: list[str], text: str) -> None:
                parts.append([titles, [text] if text else []])

            for ref in package.iter(f"{_OPF}itemref"):
                item = manifest.get(ref.get("idref"))
                if item is None or not item.get("href"):
                    continue
                name = resolved(package_path, item.get("href"))
                if name == nav:
                    continue
                here = [(anchor, title) for file, anchor, title in entries if file == name]
                anchors = list(dict.fromkeys(anchor for anchor, _ in here if anchor))
                try:
                    pieces = cut_html(read(name).decode("utf-8", errors="replace"), anchors)
                except KeyError:
                    continue
                for n, (at, text) in enumerate(pieces):
                    if n == 0:
                        # The file's start: a part where the contents point
                        # at the file itself, or where nothing came before.
                        titles = [title for anchor, title in here if anchor is None]
                        if titles or not entries or not parts:
                            begin(titles or ([text.split("\n", 1)[0][:80]] if text else []), text)
                        elif text:
                            parts[-1][1].append(text)
                    else:
                        begin([title for anchor, title in here if anchor in at], text)
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as e:
        raise NotAnEpub(str(e)) from e
    named = lambda titles: ": ".join(dict.fromkeys(t for t in titles if t)) or "Untitled"
    found = [(titles, "\n\n".join(texts)) for titles, texts in parts if texts]
    return [(named(titles), text) for titles, text in _to_headings(found)]


# How far past an anchor its heading is looked for, in paragraphs: about a page.
HEADING_WITHIN = 25


def _to_headings(parts: list[tuple[list[str], str]]) -> list[tuple[list[str], str]]:
    """Each part after the first begun at its heading rather than its anchor,
    where a paragraph soon after the anchor is its title, or the number its
    title ends with: a book converted from a PDF points its contents at the
    page a chapter starts on, so the cut falls mid-sentence, the chapter's
    heading somewhere below. What comes before the heading is the last part's."""
    moved = [[titles, text.split("\n\n")] for titles, text in parts]
    for previous, part in zip(moved, moved[1:]):
        wanted = set()
        for title in part[0]:
            wanted.add(title.casefold().strip())
            number = re.search(r"(\d+|\b[ivxlc]+)\s*$", title.casefold())
            if number:
                wanted.add(number.group(1))
        heading = next((i for i, paragraph in enumerate(part[1][:HEADING_WITHIN])
                        if paragraph.casefold().strip().rstrip(".") in wanted), 0)
        if heading:
            previous[1].extend(part[1][:heading])
            part[1] = part[1][heading:]
    return [(titles, "\n\n".join(paragraphs)) for titles, paragraphs in moved]
