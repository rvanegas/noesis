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
    (tmp_path / "2026" / "2026-06-29-the-eleatic-critique.source.pdf").write_bytes(b"%PDF\xff\xfe")
    assert "not text" in read_file(tmp_path, "2026-06-29-the-eleatic-critique.source.pdf")


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
