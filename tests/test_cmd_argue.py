import copy
from unittest.mock import patch

from noesis.argue import argument_to_markdown, check_argument, markdown_to_argument
from noesis.cmd_argue import run_argue
from noesis.config import AppConfig, Speaker

CHAT = "\n# Lunch\n2026-10-30\n\n## Ann\n\nAll men are mortal, so Socrates is.\n\n## Bob\n\nHe is no man.\n"
EXTRACTED = {"argument": [
    {"symbol": "1", "proposition": "All men are mortal.", "justifiers": [], "accepted": ["Ann", "Bob"]},
    {"symbol": "2", "proposition": "Socrates is a man.", "justifiers": [], "accepted": ["Ann"], "rejected": ["Bob", "Zed"]},
    {"symbol": "3", "proposition": "Socrates is mortal.", "justifiers": ["1", "2"], "accepted": ["Ann"]},
]}
CHANNEL = AppConfig(members=(Speaker("ann", "Ann", ("Ann",)), Speaker("bob", "Bob", ("Bob",)),
                             Speaker("bo", "Bo (guest)", ("Bo (guest)",))))


def _argue(path, config=AppConfig(), extracted=EXTRACTED):
    with patch("noesis.dianoia_client.extract", return_value=copy.deepcopy(extracted)) as extract, \
         patch("noesis.config.load_config", return_value=config):
        code = run_argue(path)
    return code, extract


def test_argue_extracts_from_a_chat_with_each_member_s_stances(tmp_path, capsys):
    chat = tmp_path / "2026-10-30-lunch.chat.md"
    chat.write_text(CHAT)
    code, extract = _argue(chat, CHANNEL)
    assert code == 0
    # A name its own punctuation would split is not one dianoia is given.
    assert extract.call_args.kwargs["participants"] == ["Ann", "Bob"]
    written = (tmp_path / "2026-10-30-lunch.argument.md").read_text()
    assert "- 2 (accepted: Ann; rejected: Bob): Socrates is a man." in written     # Zed is nobody here
    assert "- 3 (from: 1, 2; accepted: Ann): Socrates is mortal." in written
    assert check_argument(written) == []


def test_in_a_person_s_library_nobody_is_named(tmp_path):
    document = tmp_path / "2026-10-30-lunch.document.md"
    document.write_text("\n# Lunch\n2026-10-30\n\nProse.\n")
    code, extract = _argue(document, extracted={"argument": [
        {"symbol": "1", "proposition": "P.", "justifiers": [], "accepted": ["Ann"]}]})
    assert code == 0 and extract.call_args.kwargs["participants"] is None
    assert "- 1: P." in (tmp_path / "2026-10-30-lunch.argument.md").read_text()


def test_an_argument_file_reads_its_document_else_its_chat(tmp_path):
    chat = tmp_path / "2026-10-30-lunch.chat.md"
    chat.write_text(CHAT)
    code, extract = _argue(tmp_path / "2026-10-30-lunch.argument.md")
    assert code == 0 and extract.call_args.args[0] == CHAT


def test_argue_reads_neither_a_source_nor_a_review(tmp_path, capsys):
    source = tmp_path / "2026-10-27-essay.source.md"
    source.write_text("\n# Essay\n2026-10-27\n\nTheirs.\n")
    assert run_argue(source) == 1
    assert "neither a document nor a chat" in capsys.readouterr().out


def test_an_existing_argument_is_not_extracted_again(tmp_path, capsys):
    (tmp_path / "2026-10-27-essay.document.md").write_text("\n# Essay\n2026-10-27\n\nProse.\n")
    (tmp_path / "2026-10-27-essay.argument.md").write_text("## Argument\n- 1: p\n")
    assert run_argue(tmp_path / "2026-10-27-essay.document.md") == 0
    assert "already exists" in capsys.readouterr().out


def test_stances_round_trip_and_a_bad_clause_is_named():
    text = argument_to_markdown(EXTRACTED | {"argument": [
        {**s, "rejected": [n for n in s.get("rejected", []) if n != "Zed"]} for s in EXTRACTED["argument"]]},
        "Lunch", "2026-10-30")
    parsed = markdown_to_argument(text)["argument"]
    assert parsed[1]["accepted"] == ["Ann"] and parsed[1]["rejected"] == ["Bob"] and "rejected" not in parsed[0]
    assert argument_to_markdown({"argument": parsed}, "Lunch", "2026-10-30") == text
    assert check_argument("## Argument\n- 1 (accepted: Ann; denied: Bob): p\n") == [
        "line 2: cannot parse '(accepted: Ann; denied: Bob)': expected 'from:', 'accepted:' or 'rejected:', once each"]
    assert check_argument("## Argument\n- 1: p (an aside): q\n") == []
