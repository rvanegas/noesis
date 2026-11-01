"""validate and fix answer to a file's role, not to how its content looks."""

from unittest.mock import patch

import pytest

import mdc.config
from mdc.argue import check_argument
from mdc.cli import main
from mdc.library import check_keys

CHAT = "\n# Old Roman\n2025-04-25\n\n## Prompt\n\nHello.\n\n## Claude\n\nHi.\n"
PROSE = "\n# Old Roman\n2025-04-25\n\nProse, with an [x]{dir=\"rtl\"} span.\n"
KEYS = "## Plural\n\nbelief\n\n## Alias\n\nKant, Immanuel\n- Kant\n\n## Exclude\n\nthing\n\n## Group\n\nethics\n- virtue\n"


@pytest.fixture
def library(tmp_path, monkeypatch):
    lib = tmp_path / "lib"
    (lib / "2025").mkdir(parents=True)
    monkeypatch.setattr(mdc.config, "DEFAULT_CONFIG_PATH", tmp_path / "config.toml")
    monkeypatch.setenv("MDC_LIBRARY", str(lib))
    monkeypatch.chdir(lib / "2025")
    return lib


def _put(library, name, text, where="2025"):
    path = library / where / name
    path.write_text(text)
    return path


@pytest.mark.parametrize("name", [
    "2025-04-25-x.document.md", "2025-04-25-x.source.md", "2025-04-25-x.analysis.md",
])
def test_prose_is_validated_for_encoding_not_as_a_transcript(library, capsys, name):
    _put(library, name, "No title, no sections: prose.\n")
    assert main(["validate", name]) == 0
    assert "OK" in capsys.readouterr().out


def test_fix_repairs_a_documents_encoding_and_nothing_else(library, capsys):
    path = _put(library, "2025-04-25-x.document.md", PROSE.lstrip("\n"))
    main(["fix", "--yes", path.name])
    assert path.read_text() == PROSE.lstrip("\n").replace('[x]{dir="rtl"}', "x")
    out = capsys.readouterr().out
    assert "blank first line" not in out and "error" not in out


def test_a_document_that_reads_like_a_chat_is_named_not_converted(library, capsys):
    text = "\n# Talk\n2025-04-25\n\nPrompt:\n\nHello.\n\nChatGPT:\n\nHi.\n"
    path = _put(library, "2025-04-25-x.document.md", text)
    assert main(["validate", path.name]) == 1
    assert "its role is .chat.md" in capsys.readouterr().out
    main(["fix", "--yes", path.name])
    assert path.read_text() == text


def test_a_chat_still_takes_a_transcripts_repairs(library):
    path = _put(library, "2025-04-25-old-roman.chat.md", CHAT.replace("\n\n## Claude", "\n## Claude"))
    main(["fix", "--yes", path.name])
    assert path.read_text() == CHAT


def test_what_mdc_writes_is_left_alone(library, capsys):
    path = _put(library, "2025-04-25-x.review.md", "unfixed")
    _put(library, "MANIFEST.md", "unfixed", where=".")
    assert main(["fix", "--yes", path.name]) == 1
    assert main(["fix", "--yes", "MANIFEST.md"]) == 1
    assert path.read_text() == "unfixed" and (library / "MANIFEST.md").read_text() == "unfixed"
    assert "never by hand" in capsys.readouterr().out


def test_settings(library, capsys):
    _put(library, "KEYS.md", KEYS, where=".")
    _put(library, "SYSTEM_PROMPT.md", "Answer briefly.\n", where=".")
    assert main(["validate", "KEYS.md", "SYSTEM_PROMPT.md"]) == 0
    assert main(["fix", "--yes", "SYSTEM_PROMPT.md"]) == 0
    assert (library / "SYSTEM_PROMPT.md").read_text() == "Answer briefly.\n"
    assert "error" not in capsys.readouterr().out


def test_keys():
    assert check_keys(KEYS) == []
    assert check_keys("loose\n## Plural\n- belief\n## Alias\n- Kant\n## Synonyms\nx\n") == [
        "line 1: 'loose' is outside any section",
        "line 3: '- belief': Plural takes bare terms, not bullets",
        "line 5: '- Kant' has no term above it to belong to",
        "line 6: unknown section '## Synonyms' (expected Plural, Alias, Exclude or Group)",
    ]


def test_argument(library, capsys):
    good = "## Argument\n\n- 1: a\n- 2: b\n- 3 (from: 1, 2): c\n"
    assert check_argument(good) == []
    assert check_argument("## Argument\n\n- 1: a\n- 3: c\n") == [
        "Proposition numbers must be a contiguous sequence starting at 1 with no gaps (missing: [2])."
    ]
    assert check_argument("## Argument\n\n- 1': a\n- 1: b\n") == ["invalid proposition symbol(s) [\"1'\"]: use plain integers only"]
    assert check_argument("## Notes\n\n- 1: a\n")[0].startswith("expected exactly one section")
    _put(library, "2025-04-25-x.argument.md", good)
    assert main(["validate", "2025-04-25-x.argument.md"]) == 0


def test_fix_keeps_no_backup_in_a_library(library, tmp_path, monkeypatch):
    path = _put(library, "2025-04-25-x.document.md", PROSE)
    main(["fix", "--yes", path.name])
    assert "rtl" not in path.read_text()
    assert sorted(p.name for p in path.parent.iterdir()) == [path.name]
    outside = tmp_path / "loose"
    outside.mkdir()
    (outside / "notes.md").write_text(PROSE)
    monkeypatch.chdir(outside)
    main(["fix", "--yes", "notes.md"])
    assert (outside / "notes.md.bak").read_text() == PROSE


def test_related_titles_resolve_from_the_files_not_index_state(library, capsys):
    _put(library, "2025-04-20-earlier.document.md", "\n# Earlier Thoughts\n2025-04-20\n\nProse.\n")
    _put(library, "2025-04-30-later.chat.md", "\n# Later Talk\n2025-04-30\n\n## Prompt\n\nHi.\n")
    related = "\n## Related\n\n| *{}*\n"
    path = _put(library, "2025-04-25-old-roman.chat.md", CHAT + related.format("Earlier Thoughts"))
    assert not (library / ".mdc").exists()
    assert main(["validate", path.name]) == 0
    capsys.readouterr()
    path.write_text(CHAT + related.format("Later Talk"))
    assert main(["validate", path.name]) == 1
    assert "does not precede this document" in capsys.readouterr().out
    path.write_text(CHAT + related.format("Nowhere"))
    assert main(["validate", path.name]) == 1
    assert "not found in library" in capsys.readouterr().out
