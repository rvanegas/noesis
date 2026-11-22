import datetime
from pathlib import Path

import pytest
import noesis.library

from noesis.library import (
    INDEX_FILENAME,
    KEYS_FILENAME,
    MANIFEST_FILENAME,
    DocEntry,
    build_index,
    parse_keys_md,
    NotFound,
    find_file,
    read_file,
    slug_conflicts,
    render_manifest,
    search_library,
    write_index,
    write_manifest,
)


def _entry(rel_path="a.md", title="A", wc=100, summary="Summary of A.", terms=("foo", "bar")):
    return DocEntry(rel_path=rel_path, title=title, word_count=wc, summary=summary, terms=terms)


# ---------------------------------------------------------------------------
# write_manifest / MANIFEST.md output
# ---------------------------------------------------------------------------

def test_write_manifest_creates_file(tmp_path):
    entries = [_entry()]
    write_manifest(tmp_path, entries, datetime.datetime(2024, 1, 1))
    manifest = tmp_path / MANIFEST_FILENAME
    assert manifest.exists()
    text = manifest.read_text()
    assert "# Manifest" in text
    assert "a.md" in text
    assert "100w" in text
    assert "foo; bar" in text
    assert "Summary of A." in text


def test_write_manifest_empty(tmp_path):
    write_manifest(tmp_path, [], datetime.datetime(2024, 1, 1))
    text = (tmp_path / MANIFEST_FILENAME).read_text()
    assert "0 document(s)" in text


def test_write_manifest_escapes_special_chars(tmp_path):
    e = _entry(title="Title_with_underscores", summary="Has *bold* and [link].")
    write_manifest(tmp_path, [e], datetime.datetime(2024, 1, 1))
    text = (tmp_path / MANIFEST_FILENAME).read_text()
    assert r"\_with\_underscores" in text or "Title\\_with\\_underscores" in text or r"Title\_with\_underscores" in text


# ---------------------------------------------------------------------------
# write_index / INDEX.md output
# ---------------------------------------------------------------------------

def test_write_index_creates_file(tmp_path):
    entries = [_entry(terms=("philosophy", "stoicism"))]
    write_index(tmp_path, entries)
    index = tmp_path / INDEX_FILENAME
    assert index.exists()
    text = index.read_text()
    assert "philosophy" in text
    assert "stoicism" in text
    assert "a.md" in text


def test_write_index_no_duplicate_paths(tmp_path):
    e1 = _entry("a.md", terms=("topic",))
    e2 = _entry("b.md", terms=("topic",))
    write_index(tmp_path, [e1, e2])
    text = (tmp_path / INDEX_FILENAME).read_text()
    lines_with_a = [l for l in text.splitlines() if "a.md" in l]
    lines_with_b = [l for l in text.splitlines() if "b.md" in l]
    assert len(lines_with_a) == 1
    assert len(lines_with_b) == 1


# ---------------------------------------------------------------------------
# parse_keys_md
# ---------------------------------------------------------------------------

def test_parse_keys_md_no_file(tmp_path):
    alias_map, canonicals, exclusions = parse_keys_md(tmp_path)
    assert alias_map == {}
    assert canonicals == set()
    assert exclusions == set()


def test_parse_keys_md_plural(tmp_path):
    (tmp_path / KEYS_FILENAME).write_text("## Plural\nconcept\n")
    alias_map, canonicals, exclusions = parse_keys_md(tmp_path)
    assert "concepts" in alias_map
    assert alias_map["concepts"] == "concept"
    assert "concept" in canonicals


def test_parse_keys_md_alias(tmp_path):
    (tmp_path / KEYS_FILENAME).write_text("## Alias\nKant, Immanuel\n- Kant\n")
    alias_map, canonicals, exclusions = parse_keys_md(tmp_path)
    assert alias_map["Kant"] == "Kant, Immanuel"
    assert "Kant, Immanuel" in canonicals


def test_parse_keys_md_exclude(tmp_path):
    (tmp_path / KEYS_FILENAME).write_text("## Exclude\nfoo\n")
    _, _, exclusions = parse_keys_md(tmp_path)
    assert "foo" in exclusions


def test_parse_keys_md_group(tmp_path):
    # ## Group is documented but not yet implemented; section is silently ignored.
    (tmp_path / KEYS_FILENAME).write_text("## Group\nparent\n- child\n")
    alias_map, canonicals, exclusions = parse_keys_md(tmp_path)
    assert alias_map == {}
    assert canonicals == set()
    assert exclusions == set()


# ---------------------------------------------------------------------------
# read_file / find_file
# ---------------------------------------------------------------------------

def _stem_files(root, stem="2026-06-29-the-eleatic-critique", roles=("chat", "document", "source", "argument")):
    (root / "2026").mkdir(exist_ok=True)
    for role in roles:
        (root / "2026" / f"{stem}.{role}.md").write_text(f"\n# The Eleatic Critique\n2026-06-29\n\n{role} text\n")


@pytest.mark.parametrize("query", [
    "2026-06-29-the-eleatic-critique", "the-eleatic-critique", "The Eleatic Critique",
    "| *The Eleatic Critique*", "2026/the-eleatic-critique", "elsewhere/2026-06-29-the-eleatic-critique",
])
def test_read_file_a_stem_slug_or_title_reads_the_document(tmp_path, query):
    _stem_files(tmp_path)
    found, companions = find_file(tmp_path, query)
    assert found.name == "2026-06-29-the-eleatic-critique.document.md"
    assert [p.name.split(".")[1] for p in companions] == ["chat", "source", "argument"]


def test_read_file_follows_the_order_without_a_document(tmp_path):
    _stem_files(tmp_path, roles=("argument", "source", "chat", "review"))
    assert find_file(tmp_path, "the-eleatic-critique")[0].name.endswith(".chat.md")
    _stem_files(tmp_path, "2026-07-01-zeno", roles=("argument", "source"))
    assert find_file(tmp_path, "zeno")[0].name.endswith(".source.md")


def test_read_file_by_name_reads_that_file_and_names_its_companions(tmp_path):
    _stem_files(tmp_path)
    text = read_file(tmp_path, "2026-06-29-the-eleatic-critique.argument.md")
    head, body = text.split("\n\n", 1)
    assert head.startswith("2026-06-29-the-eleatic-critique.argument.md, the argument.")
    assert "2026-06-29-the-eleatic-critique.document.md (document)" in head
    assert "argument text" in body


def test_read_file_says_a_source_is_someone_elses(tmp_path):
    _stem_files(tmp_path, roles=("source",))
    assert "third-party material" in read_file(tmp_path, "the-eleatic-critique").split("\n", 1)[0]


def test_read_file_finds_a_title_its_slug_has_left(tmp_path):
    _stem_files(tmp_path, roles=("document",))
    path = tmp_path / "2026" / "2026-06-29-the-eleatic-critique.document.md"
    path.write_text("\n# Parmenides Answered\n2026-06-29\n\nprose\n")
    assert find_file(tmp_path, "Parmenides Answered")[0] == path


def test_read_file_undated_files_by_name(tmp_path):
    (tmp_path / "KEYS.md").write_text("## Alias\n")
    assert read_file(tmp_path, "KEYS.md").endswith("## Alias\n")


def test_read_file_not_text(tmp_path):
    _stem_files(tmp_path, roles=("document",))
    (tmp_path / "2026" / "parmenides.png").write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe")
    assert "not text" in read_file(tmp_path, "parmenides.png")


def _pdf(path, pages):
    """A minimal PDF, a line of Helvetica on each page; empty strings make blank pages."""
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", None,
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for line in pages:
        stream = f"BT /F1 12 Tf 72 720 Td ({line}) Tj ET".encode("latin-1") if line else b""
        objects.append(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream))
        content = len(objects)
        objects.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                       b"/Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>" % content)
        kids.append(len(objects))
    objects[1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (
        b" ".join(b"%d 0 R" % k for k in kids), len(kids))
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    path.write_bytes(bytes(out))


PDF_NAME = "2026-06-29-the-eleatic-critique.source.pdf"


def test_read_file_lists_a_pdf_in_runs_of_pages_without_bookmarks(tmp_path, monkeypatch):
    import noesis.pdf_text
    monkeypatch.setattr(noesis.pdf_text, "PAGES_PER_PART", 2)
    _stem_files(tmp_path, roles=("document",))
    _pdf(tmp_path / "2026" / PDF_NAME, ["First page", "", "Third page"])
    head, outline = read_file(tmp_path, PDF_NAME).split("\n\n", 1)
    assert "the source: third-party material" in head
    assert outline.endswith("Its 2 parts:\n\n1. pages 1–2\n2. page 3")
    assert read_file(tmp_path, PDF_NAME, part=1).endswith("Part 1 of 2: pages 1–2.\n\nFirst page")
    assert read_file(tmp_path, PDF_NAME, part=2).endswith("\n\nThird page")


def test_read_file_parts_a_pdf_by_its_bookmarks(tmp_path, monkeypatch):
    import noesis.pdf_text
    from pypdf import PdfWriter
    monkeypatch.setattr(noesis.pdf_text, "MAX_PART_PAGES", 2)
    path = tmp_path / "2026" / PDF_NAME
    (tmp_path / "2026").mkdir()
    _pdf(path, ["Cover", "One a", "One b", "One c", "Two a"])
    writer = PdfWriter(clone_from=path)
    writer.add_outline_item(title="Chapter One", page_number=1)
    writer.add_outline_item(title="Chapter Two", page_number=4)
    writer.write(path)
    outline = read_file(tmp_path, PDF_NAME).split("parts:\n\n", 1)[1]
    assert outline.split("\n") == [
        "1. Front matter, page 1",
        "2. Chapter One (1 of 2), pages 2–3",
        "3. Chapter One (2 of 2), page 4",
        "4. Chapter Two, page 5",
    ]
    assert read_file(tmp_path, PDF_NAME, part=2).endswith("\n\nOne a\n\nOne b")


def test_read_file_a_pdf_without_text_or_broken(tmp_path):
    _stem_files(tmp_path, roles=("document",))
    folder = tmp_path / "2026"
    _pdf(folder / PDF_NAME, [""])
    assert "no text layer" in read_file(tmp_path, PDF_NAME, part=1)
    (folder / PDF_NAME).write_bytes(b"%PDF\xff\xfe")
    assert read_file(tmp_path, PDF_NAME).endswith("a PDF that could not be read.")


def test_read_file_excludes_the_chat_being_replied_to(tmp_path):
    _stem_files(tmp_path, roles=("chat", "argument"))
    chat = "2026/2026-06-29-the-eleatic-critique.chat.md"
    found, companions = find_file(tmp_path, "the-eleatic-critique", exclude=chat)
    assert found.name.endswith(".argument.md") and companions == []
    with pytest.raises(NotFound):
        find_file(tmp_path, "2026-06-29-the-eleatic-critique.chat.md", exclude=chat)


@pytest.mark.parametrize("query", ["../../etc/passwd", "nonexistent.md", ".noesis/manifest.json"])
def test_read_file_finds_nothing_outside_the_library_or_hidden(tmp_path, query):
    (tmp_path / ".noesis").mkdir()
    (tmp_path / ".noesis" / "manifest.json").write_text("{}")
    with pytest.raises(NotFound):
        find_file(tmp_path, query)


def test_a_slug_on_two_dates_is_a_conflict_read_file_refuses(tmp_path):
    _stem_files(tmp_path, roles=("chat",))
    _stem_files(tmp_path, "2026-07-01-the-eleatic-critique", roles=("document",))
    assert slug_conflicts(tmp_path) == {
        "the-eleatic-critique": ["2026-06-29-the-eleatic-critique", "2026-07-01-the-eleatic-critique"]}
    with pytest.raises(NotFound, match="names"):
        find_file(tmp_path, "the-eleatic-critique")
    assert find_file(tmp_path, "2026-07-01-the-eleatic-critique")[0].name.endswith(".document.md")


# ---------------------------------------------------------------------------
# search_library
# ---------------------------------------------------------------------------

def test_search_library_returns_matches(tmp_path):
    entries = [
        _entry("stoicism.md", title="Stoicism", summary="Stoic philosophy."),
        _entry("epicureanism.md", title="Epicureanism", summary="Epicurean thought."),
    ]
    results = search_library(entries, "stoic")
    assert any(e.rel_path == "stoicism.md" for e in results)


def test_search_library_empty_query_returns_empty(tmp_path):
    entries = [_entry()]
    assert search_library(entries, "") == []


def test_search_library_max_five_results(tmp_path):
    entries = [_entry(f"{i}.md", summary="common word") for i in range(10)]
    results = search_library(entries, "common")
    assert len(results) <= 5


# ---------------------------------------------------------------------------
# build_index incremental caching
# ---------------------------------------------------------------------------

def test_build_index_caches_unchanged_file(tmp_path):
    import os
    import time

    doc = tmp_path / "doc.document.md"
    doc.write_text("# Doc\nContent here.")
    # Set mtime to 10s ago so it's clearly before the build_index now_ts.
    old = time.time() - 10
    os.utime(doc, (old, old))

    calls = []

    def summarize(content, wc, role):
        calls.append(content)
        return "A summary.", ["term1"]

    build_index(tmp_path, summarize=summarize)
    assert len(calls) == 1

    # Second run: file unchanged, summarize should not be called again.
    build_index(tmp_path, summarize=summarize)
    assert len(calls) == 1


def test_build_index_reindexes_modified_file(tmp_path):
    doc = tmp_path / "doc.document.md"
    doc.write_text("# Doc\nOriginal content.")

    calls = []

    def summarize(content, wc, role):
        calls.append(content)
        return "A summary.", ["term1"]

    build_index(tmp_path, summarize=summarize)
    assert len(calls) == 1

    # Touch the file to simulate modification.
    import time
    time.sleep(0.05)
    doc.write_text("# Doc\nUpdated content.")

    build_index(tmp_path, summarize=summarize)
    assert len(calls) == 2


def test_build_index_excludes_manifest_and_index(tmp_path):
    (tmp_path / MANIFEST_FILENAME).write_text("# Index\n")
    (tmp_path / INDEX_FILENAME).write_text("# Terms\n")
    doc = tmp_path / "real.document.md"
    doc.write_text("# Real\nContent.")

    seen = []

    def summarize(content, wc, role):
        seen.append(content)
        return "s", ["t"]

    entries, _ = build_index(tmp_path, summarize=summarize)
    assert all(e.rel_path == "real.document.md" for e in entries)
    assert len(entries) == 1


# ---------------------------------------------------------------------------
# render_manifest
# ---------------------------------------------------------------------------

def test_render_manifest_includes_all_entries():
    entries = [_entry("a.md", title="Alpha"), _entry("b.md", title="Beta")]
    text = render_manifest(entries)
    assert "a.md" in text
    assert "b.md" in text
    assert "Alpha" in text
    assert "Beta" in text


def test_what_changes_the_index():
    from noesis.library import changes_index
    assert changes_index("2026/2026-01-02-essay.document.md")
    assert changes_index("2026/2026-01-02-talk.chat.md")
    assert changes_index("KEYS.md")
    for rel in ("2026/2026-01-02-paper.source.md", "2026/2026-01-02-essay.argument.md", "INDEX.md",
                "SYSTEM_PROMPT.md", "REVISIONS/2026-01-02-essay--1.document.md", "2026/2026-01-02-talk.chat.pdf",
                "notes/KEYS.md"):
        assert not changes_index(rel), rel


def test_index_files_are_written_whole(tmp_path):
    from noesis.library import _write
    (tmp_path / "INDEX.md").write_text("old")
    _write(tmp_path / "INDEX.md", "new")
    assert (tmp_path / "INDEX.md").read_text() == "new"
    assert [p.name for p in tmp_path.iterdir()] == ["INDEX.md"]


EPUB_NAME = "2026-06-29-the-eleatic-critique.source.epub"


def _epub(path, chapters, order=None, nav=None, ncx=None):
    """A minimal EPUB: chapters by id, in the spine's `order` (their own by
    default), with an EPUB 3 nav or an EPUB 2 ncx: (chapter id, title) pairs."""
    import zipfile
    path.parent.mkdir(exist_ok=True)

    def href(c):  # a chapter id, with an anchor after a '#'
        file, _, anchor = c.partition("#")
        return f"text/{file}.xhtml" + (f"#{anchor}" if anchor else "")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml",
                   '<?xml version="1.0"?><container version="1.0" '
                   'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
                   '<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
                   '</rootfiles></container>')
        items = "".join(f'<item id="{c}" href="text/{c}.xhtml" media-type="application/xhtml+xml"/>' for c in chapters)
        spine = "".join(f'<itemref idref="{c}"/>' for c in (order or list(chapters)))
        if nav:
            items += '<item id="nav" href="nav.xhtml" properties="nav" media-type="application/xhtml+xml"/>'
            spine = '<itemref idref="nav"/>' + spine
            links = "".join(f'<li><a href="{href(c)}">{t}</a></li>' for c, t in nav)
            z.writestr("OEBPS/nav.xhtml",
                       '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><body>'
                       f'<nav epub:type="toc"><ol>{links}</ol></nav></body></html>')
        if ncx:
            items += '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
            points = "".join(f'<navPoint id="p{i}"><navLabel><text>{t}</text></navLabel>'
                             f'<content src="{href(c)}"/></navPoint>' for i, (c, t) in enumerate(ncx))
            z.writestr("OEBPS/toc.ncx",
                       f'<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/"><navMap>{points}</navMap></ncx>')
        z.writestr("OEBPS/content.opf",
                   '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
                   f'<manifest>{items}</manifest><spine{" toc=\"ncx\"" if ncx else ""}>{spine}</spine></package>')
        for c, body in chapters.items():
            z.writestr(f"OEBPS/text/{c}.xhtml",
                       f'<html xmlns="http://www.w3.org/1999/xhtml"><head><title>T</title>'
                       f'<style>p {{}}</style></head><body>{body}</body></html>')


def test_read_file_lists_an_epub_without_contents_a_file_a_part_in_its_spines_order(tmp_path):
    _stem_files(tmp_path, roles=("document",))
    _epub(tmp_path / "2026" / EPUB_NAME,
          {"one": "<h1>Capítulo 1</h1><p>Las  hormigas&nbsp;trabajan.</p>", "two": "<p>Segundo<br/>capítulo.</p>"},
          order=["two", "one"])
    text = read_file(tmp_path, "2026/" + EPUB_NAME)
    head, outline = text.split("\n\n", 1)
    assert "the source: third-party material" in head
    assert "2026-06-29-the-eleatic-critique.document.md (document)" in head
    assert outline.endswith("Its 2 parts:\n\n1. Segundo — 2 words\n2. Capítulo 1 — 5 words")
    part = read_file(tmp_path, EPUB_NAME, part=2)
    assert part.endswith("Part 2 of 2: Capítulo 1 — 5 words.\n\nCapítulo 1\n\nLas hormigas trabajan.")
    assert "<style>" not in part and "T\n" not in part


@pytest.mark.parametrize("contents", ["nav", "ncx"])
def test_read_file_parts_an_epub_by_its_contents(tmp_path, contents):
    toc = [("one", "Prólogo"), ("three", "Capítulo 1")]
    _epub(tmp_path / "2026" / EPUB_NAME,
          {"cover": "<p>Cover</p>", "one": "<p>Pro</p>", "two": "<p>logo</p>", "three": "<p>Uno</p>"},
          **{contents: toc})
    outline = read_file(tmp_path, EPUB_NAME).split("parts:\n\n", 1)[1]
    assert outline.split("\n") == ["1. Cover — 1 words", "2. Prólogo — 2 words", "3. Capítulo 1 — 1 words"]
    assert read_file(tmp_path, EPUB_NAME, part=2).endswith("\n\nPro\n\nlogo")


def test_read_file_parts_an_epub_at_the_anchors_its_contents_point_to(tmp_path):
    book = tmp_path / "2026" / EPUB_NAME
    _epub(book, {"all": '<p>Title</p><p id="p4">Pro</p><p>logo</p><h2 id="p16">Uno</h2><p>uno</p><div id="p28">Dos</div>'},
          ncx=[("all#p4", "Prólogo"), ("all#p16", "Primera parte"), ("all#p16", "Capítulo 1"), ("all#p28", "Capítulo 2")])
    outline = read_file(tmp_path, EPUB_NAME).split("parts:\n\n", 1)[1]
    assert outline.split("\n") == ["1. Title — 1 words", "2. Prólogo — 2 words",
                                   "3. Primera parte: Capítulo 1 — 2 words", "4. Capítulo 2 — 1 words"]
    assert read_file(tmp_path, EPUB_NAME, part=3).endswith("\n\nUno\n\nuno")


def test_read_file_begins_an_epubs_part_at_its_heading_past_a_page_anchor(tmp_path):
    # Converted from a PDF: the contents point at the page, the heading below.
    _epub(tmp_path / "2026" / EPUB_NAME,
          {"all": '<p>Uno</p><p>uno, por</p><p id="p33">ejemplo fin.</p><p><b>3</b></p><p>El cuento</p><p>tres</p>'},
          ncx=[("all", "Capítulo 1"), ("all#p33", "Capítulo 3")])
    assert read_file(tmp_path, EPUB_NAME, part=1).endswith("\n\nUno\n\nuno, por\n\nejemplo fin.")
    assert read_file(tmp_path, EPUB_NAME, part=2).endswith("\n\n3\n\nEl cuento\n\ntres")


def test_read_file_splits_a_long_part_between_paragraphs(tmp_path, monkeypatch):
    monkeypatch.setattr(noesis.library, "MAX_PART_WORDS", 4)
    _epub(tmp_path / "2026" / EPUB_NAME, {"one": "<p>a b c</p><p>d e f</p><p>g h</p>"}, nav=[("one", "Long")])
    outline = read_file(tmp_path, EPUB_NAME).split("parts:\n\n", 1)[1]
    assert outline.split("\n") == ["1. Long (1 of 2) — 6 words", "2. Long (2 of 2) — 2 words"]
    assert read_file(tmp_path, EPUB_NAME, part=2).endswith("\n\ng h")


def test_read_file_refuses_a_part_it_does_not_have(tmp_path):
    from noesis.library import NoSuchPart
    _stem_files(tmp_path, roles=("document",))
    _epub(tmp_path / "2026" / EPUB_NAME, {"one": "<p>a</p>"})
    with pytest.raises(NoSuchPart, match="has parts 1 to 1, not 2"):
        read_file(tmp_path, EPUB_NAME, part=2)
    with pytest.raises(NoSuchPart, match="read whole"):
        read_file(tmp_path, "the-eleatic-critique", part=1)


def test_read_file_an_epub_that_is_not_one(tmp_path):
    _stem_files(tmp_path, roles=("document",))
    (tmp_path / "2026" / EPUB_NAME).write_bytes(b"PK\x03\x04 broken")
    assert read_file(tmp_path, EPUB_NAME).endswith("an EPUB that could not be read.")
