import json
import shutil
import zipfile
from pathlib import Path

import pytest

import mdc.config
from mdc.cli import main
from mdc.form import check_file

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def library(tmp_path, monkeypatch):
    lib = tmp_path / "lib"
    lib.mkdir()
    monkeypatch.setattr(mdc.config, "DEFAULT_CONFIG_PATH", tmp_path / "config.toml")
    monkeypatch.setenv("MDC_LIBRARY", str(lib))
    monkeypatch.delenv("MDC_SERVER_URL", raising=False)
    monkeypatch.chdir(lib)
    return lib


def test_claude_export_becomes_exact_chats(library, capsys):
    assert main(["import", str(FIXTURES / "claude_export.json")]) == 0
    chat = library / "2026" / "2026-09-14-being-and-seeming.chat.md"
    text = chat.read_text()
    assert text.startswith("\n# Being and Seeming\n2026-09-14\n\n## Prompt\n\nIs seeming a kind of being?")
    assert "| [attachment: notes.txt]" in text
    assert "\n### Two readings" in text and "\n## Two readings" not in text   # promoted, as reply does
    assert "hidden" not in text                                          # thinking is not a turn
    assert "Take the phenomenal reading." in text
    assert "edited away" not in text                                      # the active branch only
    assert "| [tool: web_search]" in text and "Meinong" in text
    assert check_file(chat) == []
    untitled = library / "2026" / "2026-10-01-untitled.chat.md"
    assert "A quick answer." in untitled.read_text()
    out = capsys.readouterr().out
    assert "2 imported, 0 skipped, 0 failed." in out                      # the empty one is nothing


def test_each_turns_related_and_references_go_to_the_end(library):
    def says(sender, text):
        return {"sender": sender, "content": [{"type": "text", "text": text}]}
    src = library.parent / "conversations.json"
    src.write_text(json.dumps([{"uuid": "c-9", "name": "Attention", "created_at": "2026-10-27T10:00:00Z",
                                "chat_messages": [
        says("human", "What did I say about attention?"),
        says("assistant", "You called it a kind of will.\n\n## Related\n\n| *On Attention*\n\n"
                          "## References\n\n| James (1890) *Principles of Psychology*"),
        says("human", "And Kant?"),
        says("assistant", "He came first.\n\n## Related\n\n| *On Attention*\n| *Free Will*\n\n"
                          "## References\n\n| Kant (1781) *Critique of Pure Reason*"),
    ]}]))
    assert main(["import", str(src)]) == 0
    chat = library / "2026" / "2026-10-27-attention.chat.md"
    text = chat.read_text()
    assert check_file(chat) == []
    assert text.count("## Related") == 1 and text.count("## References") == 1
    assert text.index("He came first.") < text.index("## Related") < text.index("## References")
    assert "## Related\n\n| *On Attention*\n| *Free Will*\n\n" in text
    assert text.endswith("## References\n\n| James (1890) *Principles of Psychology*\n"
                         "| Kant (1781) *Critique of Pure Reason*\n")


def test_saveai_export_becomes_a_chat(library):
    src = library.parent / "2026-08-03-verbal-disputes.md"
    shutil.copy(FIXTURES / "saveai_export.md", src)
    assert main(["import", str(src)]) == 0
    chat = library / "2026" / "2026-08-03-verbal-disputes.chat.md"
    text = chat.read_text()
    assert "## Prompt\n\nWhat is a verbal dispute?" in text
    assert "### Short answer" in text
    assert "message time" not in text and "From:" not in text
    assert check_file(chat) == []


def test_anything_else_is_a_document(library):
    src = library.parent / "notes-on-quine.md"
    src.write_text("# Notes on Quine\n\nTwo dogmas, one paragraph.\n")
    assert main(["import", str(src)]) == 0
    docs = list((library).rglob("*-notes-on-quine.document.md"))
    assert len(docs) == 1
    assert docs[0].read_text().startswith("\n# Notes on Quine\n")
    assert "Two dogmas, one paragraph." in docs[0].read_text()


def test_zip_only_skip_and_replace(library, capsys):
    archive = library.parent / "data-2026-10-27.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.write(FIXTURES / "claude_export.json", "data/conversations.json")
    assert main(["import", str(archive), "--only", "Being and Seeming"]) == 0
    assert [p.name for p in (library / "2026").iterdir()] == ["2026-09-14-being-and-seeming.chat.md"]
    chat = library / "2026" / "2026-09-14-being-and-seeming.chat.md"
    chat.write_text(chat.read_text() + "\n## Prompt\n\nMy own addition.\n")
    capsys.readouterr()
    main(["import", str(archive), "--only", "c-1"])
    assert "skipped" in capsys.readouterr().out
    assert "My own addition." in chat.read_text()
    main(["import", str(archive), "--only", "c-1", "--replace"])
    assert "My own addition." not in chat.read_text()


def test_a_file_that_fails_its_check_is_not_written(library, monkeypatch, capsys):
    import mdc.cmd_import as imp
    monkeypatch.setattr(imp, "_problems", lambda path, role: ["broken"])
    existing = library / "2026" / "2026-09-14-being-and-seeming.chat.md"
    existing.parent.mkdir()
    existing.write_text("keep me")
    main(["import", str(FIXTURES / "claude_export.json"), "--only", "c-1", "--replace"])
    assert existing.read_text() == "keep me"
    assert "failed" in capsys.readouterr().out


FLOOR = """The Floor — Reading Group
2026-10-30 · 2:21 PM–4:09 PM

Rodrigo (A) · 2:22 PM
Afternoon.
I was there.

null · 2:23 PM
Who said that?

Pasted by Golf · 2:24 PM
A paragraph of Bach.

And another.

Pasted by Claude · 2:25 PM
Bach reads Kant through computation.

Rodrigo (A) · 2:26 PM
Exactly.
"""


def test_the_floor_becomes_a_chat_by_its_speakers(library):
    src = library.parent / "anything.txt"
    src.write_text(FLOOR)
    assert main(["import", str(src)]) == 0
    chat = library / "2026" / "2026-10-30-reading-group.chat.md"
    text = chat.read_text()
    assert text.startswith("\n# Reading Group\n2026-10-30\n\n## Rodrigo (A)\n\nAfternoon.\nI was there.\n")
    assert "## Someone\n\nWho said that?" in text
    assert "## Golf\n\n> A paragraph of Bach.\n\n> And another." in text
    assert "## Claude\n\nBach reads Kant through computation." in text
    assert check_file(chat) == []


def test_an_older_floor_text_is_named_by_its_download(library):
    src = library.parent / "The Floor — Reading Group — 2026-10-30 1609.txt"
    src.write_text(FLOOR.split("\n", 1)[1].replace("2026-10-30 ·", "Fri, Oct 30 ·"))
    assert main(["import", str(src)]) == 0
    assert (library / "2026" / "2026-10-30-reading-group.chat.md").exists()


def test_a_zip_imports_each_text_inside(library):
    archive = library.parent / "transcript.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("transcript/segment.txt", FLOOR)
        z.writestr("__MACOSX/transcript/._segment.txt", "resource fork")
    assert main(["import", str(archive)]) == 0
    assert [p.name for p in (library / "2026").iterdir()] == ["2026-10-30-reading-group.chat.md"]


def test_a_finder_zip_name_is_read_as_utf8():
    from mdc.cmd_import import _member_name
    name = "The Floor — Reading Group — 2026-10-30 1609.txt"
    # Finder writes UTF-8 without the flag that says so; zipfile reads cp437.
    assert _member_name(zipfile.ZipInfo(name.encode("utf-8").decode("cp437"))) == name
    assert _member_name(zipfile.ZipInfo("plain.txt")) == "plain.txt"


def test_a_title_the_library_has_fails(library, capsys):
    src = library.parent / "anything.txt"
    src.write_text(FLOOR)
    assert main(["import", str(src)]) == 0
    src.write_text(FLOOR.replace("2026-10-30 ·", "2026-10-31 ·"))
    capsys.readouterr()
    assert main(["import", str(src)]) == 1
    assert "the title \"Reading Group\" is 2026-10-30-reading-group.chat.md's" in capsys.readouterr().out
    assert not (library / "2026" / "2026-10-31-reading-group.chat.md").exists()
    capsys.readouterr()
    src.write_text(FLOOR)
    assert main(["import", str(src), "--replace"]) == 0                  # its own file, replaced
