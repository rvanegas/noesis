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
        "line 2: cannot parse '(accepted: Ann; denied: Bob)': expected 'from:', 'accepted:', 'rejected:', "
        "'inference accepted:', 'inference rejected:', once each"]
    assert check_argument("## Argument\n- 1: p (an aside): q\n") == []


def test_an_inference_has_stances_of_its_own():
    text = "## Argument\n- 1 (accepted: Ann, Bob): P\n" \
           "- 2 (from: 1; accepted: Ann; rejected: Bob; inference accepted: Ann, Bob): Q\n"
    assert check_argument(text) == []
    step = markdown_to_argument(text)["argument"][1]
    assert step["inference_accepted"] == ["Ann", "Bob"] and "inference_rejected" not in step
    assert argument_to_markdown({"argument": markdown_to_argument(text)["argument"]}, "T", "2026-11-09").endswith(
        "- 2 (from: 1; accepted: Ann; rejected: Bob; inference accepted: Ann, Bob): Q\n")
    # No inference without justifiers, and nobody on both sides of one.
    assert "need its justifiers" in check_argument("## Argument\n- 1 (inference accepted: Ann): P\n")[0]
    assert "both accept and reject" in check_argument(
        "## Argument\n- 1: P\n- 2 (from: 1; inference accepted: Ann; inference rejected: Ann): Q\n")[0]


def test_argue_keeps_an_inference_only_where_there_is_one(tmp_path):
    chat = tmp_path / "2026-10-30-lunch.chat.md"
    chat.write_text(CHAT)
    extracted = {"argument": [
        {"symbol": "1", "proposition": "P.", "justifiers": [], "accepted": ["Ann"], "inference_accepted": ["Ann"]},
        {"symbol": "2", "proposition": "Q.", "justifiers": ["1"], "rejected": ["Bob"],
         "inference_accepted": ["Bob", "Zed"], "inference_rejected": ["Bob", "Ann"]},
    ]}
    assert _argue(chat, CHANNEL, extracted)[0] == 0
    written = (tmp_path / "2026-10-30-lunch.argument.md").read_text()
    assert "- 1 (accepted: Ann): P." in written
    assert "- 2 (from: 1; rejected: Bob; inference accepted: Bob; inference rejected: Ann): Q." in written


def test_in_a_person_s_library_the_owner_is_the_one_participant(tmp_path):
    chat = tmp_path / "2026-10-30-essay.chat.md"
    chat.write_text("\n# Essay\n2026-10-30\n\n## Prompt\n\nP, so Q.\n\n## Claude\n\nNot Q.\n\n## Ann\n\nQ.\n")
    owner = AppConfig(owner=Speaker("ann", "Ann Example", ("Prompt", "Ann")))
    assert owner.people == (owner.owner,)
    code, extract = _argue(chat, owner, {"argument": [
        {"symbol": "1", "proposition": "P.", "justifiers": [], "accepted": ["Ann Example", "Claude"]}]})
    assert code == 0 and extract.call_args.kwargs["participants"] == ["Ann Example"]
    # Her headings are her name to dianoia; Claude's stays Claude's, and is nobody's stance.
    sent = extract.call_args.args[0]
    assert "## Ann Example\n\nP, so Q." in sent and "## Claude\n\nNot Q." in sent and "## Ann Example\n\nQ." in sent
    assert "- 1 (accepted: Ann Example): P." in (tmp_path / "2026-10-30-essay.argument.md").read_text()
    # Her own document is said to be hers.
    document = tmp_path / "2026-10-31-notes.document.md"
    document.write_text("\n# Notes\n2026-10-31\n\nProse.\n")
    _, extract = _argue(document, owner, {"argument": [{"symbol": "1", "proposition": "P.", "justifiers": []}]})
    assert extract.call_args.args[0].startswith("[Written by Ann Example.]\n")


def test_a_proposition_that_names_a_participant_is_warned_of(tmp_path, capsys):
    from noesis.argue import naming
    argument = [
        {"symbol": "12", "proposition": "Rodrigo's rationality standard would permit belief in it."},
        {"symbol": "13", "proposition": "JENSEN conceded the point."},
        {"symbol": "14", "proposition": "Flat-earth belief is irrational though it entails no contradiction."},
        {"symbol": "15", "proposition": "Danielle is a name, and so is Rod."},
    ]
    assert naming(argument, ["Rodrigo", "Daniel Jensen"]) == [("12", "Rodrigo"), ("13", "Daniel Jensen")]
    chat = tmp_path / "2026-10-30-lunch.chat.md"
    chat.write_text(CHAT)
    _argue(chat, CHANNEL, {"argument": [
        {"symbol": "1", "proposition": "Bob's view is that P.", "justifiers": [], "accepted": ["Ann"]}]})
    out = capsys.readouterr().out
    assert "Warning: these propositions name a participant" in out and "1 names Bob" in out
