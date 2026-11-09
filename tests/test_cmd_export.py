import json
from pathlib import Path
from unittest.mock import patch

import pytest

from noesis.cmd_export import _argument_contents, _layout_entry, member_goals, run_export
from noesis.roxana_client import _ID_ALPHABET, generate_discussion_id


ARGUMENT_TEXT = """
# Sample Argument
2026-07-08

## Argument
- 1: All humans are mortal.
- 2: Socrates is a human.
- 3 (from: 1, 2): Socrates is mortal.
- 4 (from: 3): Socrates will die.
"""


@pytest.fixture
def argument_file(tmp_path: Path) -> Path:
    companion = tmp_path / "2026-07-08-sample-argument.argument.md"
    companion.write_text(ARGUMENT_TEXT, encoding="utf-8")
    return companion


def test_argument_contents_order():
    argument = [
        {"symbol": "4", "proposition": "d", "justifiers": ["3"]},
        {"symbol": "1", "proposition": "a", "justifiers": []},
        {"symbol": "3", "proposition": "c", "justifiers": ["1", "2"]},
        {"symbol": "2", "proposition": "b", "justifiers": []},
    ]
    assert _argument_contents(argument) == ["1 2 3", "3 4"]


def test_layout_entry_shape():
    entry = _layout_entry(2, "abc-123")
    assert entry == {
        "index": 2,
        "id": "abc-123",
        "status": "committed",
        "accepted": [],
        "rejected": [],
        "cleared": [],
        "goal": [],
        "hidden": False,
    }


def test_generate_discussion_id():
    for _ in range(50):
        discussion_id = generate_discussion_id()
        assert len(discussion_id) == 4
        assert all(c in _ID_ALPHABET for c in discussion_id)


def test_dry_run_makes_no_network_calls(argument_file, capsys):
    with patch("noesis.roxana_client._graphql") as graphql:
        assert run_export(argument_file, dry_run=True) == 0
        graphql.assert_not_called()
    out = capsys.readouterr().out
    assert "Socrates is mortal." in out
    assert "1 2 3" in out
    assert "Goal: proposition 4" in out
    assert "Dry run" in out


def test_missing_companion(tmp_path, capsys):
    doc = tmp_path / "2026-07-08-sample.document.md"
    doc.write_text("\n# Sample\n2026-07-08\n\nText.\n", encoding="utf-8")
    assert run_export(doc) == 1
    assert "noesis argue" in capsys.readouterr().out


def test_bad_extension(tmp_path, capsys):
    path = tmp_path / "notes.txt"
    assert run_export(path) == 1
    assert ".md extension" in capsys.readouterr().out


class FakeRoxana:
    def __init__(self, fail_on_call: int | None = None):
        self.calls: list[tuple] = []
        self.sentence_count = 0
        self.fail_on_call = fail_on_call

    def generate_discussion_id(self):
        return "k2rw"

    def discussion_exists(self, url, api_key, discussion_id):
        self.calls.append(("exists", discussion_id))
        return False

    def create_sentence(self, url, api_key, content, discussion_id):
        self.sentence_count += 1
        if self.fail_on_call == self.sentence_count:
            raise RuntimeError("boom")
        sentence_id = f"s{self.sentence_count}"
        self.calls.append(("sentence", content, discussion_id, sentence_id))
        return sentence_id

    def create_discussion(self, url, api_key, discussion_id, layout, analysis_results=None, goals_summary=""):
        self.calls.append(("discussion", discussion_id, layout))
        self.analysis_results = analysis_results
        self.goals_summary = goals_summary

    def delete_sentence(self, url, api_key, sentence_id):
        self.calls.append(("delete", sentence_id))


@pytest.fixture
def configured(tmp_path, monkeypatch):
    monkeypatch.delenv("NOESIS_CALLER", raising=False)
    with patch("noesis.config.load_config") as load_config:
        config = load_config.return_value
        config.library_path = tmp_path
        config.roxana_api_url = "https://example/graphql"
        config.roxana_api_key = "da2-test"
        config.roxana_web_url = "https://roxana.example"
        config.roxana_user = None
        config.members = ()
        yield config


def _run_with(fake: FakeRoxana, path: Path, new: bool = False) -> int:
    with patch.multiple(
        "noesis.roxana_client",
        generate_discussion_id=fake.generate_discussion_id,
        discussion_exists=fake.discussion_exists,
        create_sentence=fake.create_sentence,
        create_discussion=fake.create_discussion,
        delete_sentence=fake.delete_sentence,
    ):
        return run_export(path, new=new)


def test_export_flow(argument_file, configured, capsys):
    fake = FakeRoxana()
    assert _run_with(fake, argument_file) == 0

    kinds = [c[0] for c in fake.calls]
    assert kinds == ["exists"] + ["sentence"] * 6 + ["discussion"]

    sentence_contents = [c[1] for c in fake.calls if c[0] == "sentence"]
    assert sentence_contents == [
        "All humans are mortal.",
        "Socrates is a human.",
        "Socrates is mortal.",
        "Socrates will die.",
        "1 2 3",
        "3 4",
    ]

    layout = json.loads(fake.calls[-1][2])
    assert [e["index"] for e in layout["propositions"]] == [1, 2, 3, 4]
    assert [e["id"] for e in layout["propositions"]] == ["s1", "s2", "s3", "s4"]
    assert [e["id"] for e in layout["arguments"]] == ["s5", "s6"]

    out = capsys.readouterr().out
    assert "4 propositions, 2 arguments" in out
    assert "https://roxana.example/discussions/k2rw" in out
    assert fake.analysis_results is None
    assert all(e["goal"] == [] for e in layout["propositions"])
    assert fake.goals_summary == ""
    assert "nobody's goal" in out


def test_conclusion_is_the_senders_goal(argument_file, configured, monkeypatch, capsys):
    monkeypatch.setenv("NOESIS_CALLER", "zedd")
    fake = FakeRoxana()
    assert _run_with(fake, argument_file) == 0
    layout = json.loads(fake.calls[-1][2])
    assert [e["goal"] for e in layout["propositions"]] == [[], [], [], ["zedd"]]
    assert all(e["goal"] == [] for e in layout["arguments"])
    assert fake.goals_summary == "Socrates will die (zedd)"
    assert "Proposition 4, the conclusion, is zedd's goal." in capsys.readouterr().out


def test_on_the_mac_the_sender_is_roxana_user(argument_file, configured):
    configured.roxana_user = "ann"
    fake = FakeRoxana()
    assert _run_with(fake, argument_file) == 0
    assert json.loads(fake.calls[-1][2])["propositions"][-1]["goal"] == ["ann"]


def test_the_servers_caller_comes_before_roxana_user(argument_file, configured, monkeypatch):
    configured.roxana_user = "ann"
    monkeypatch.setenv("NOESIS_CALLER", "zedd")
    fake = FakeRoxana()
    assert _run_with(fake, argument_file) == 0
    assert json.loads(fake.calls[-1][2])["propositions"][-1]["goal"] == ["zedd"]


ANALYSIS_TEXT = """
# Sample Argument
2026-07-08

## Audit

- satisfied

## Argument A (proposition 3) — Analysis

### Truth

- 1 truth: 0.9 — Solid.

## Argument B (proposition 4) — Analysis

### Formal validity

- 4 validity: 1 — Follows.
- argument validity: 1
"""


@pytest.fixture
def analysis_file(argument_file: Path) -> Path:
    analysis = argument_file.with_suffix("").with_suffix(".analysis.md")
    analysis.write_text(ANALYSIS_TEXT, encoding="utf-8")
    return analysis


def test_export_maps_analyses_to_argument_positions(argument_file, analysis_file, configured):
    fake = FakeRoxana()
    assert _run_with(fake, argument_file) == 0

    results = json.loads(fake.analysis_results)
    # Proposition 3 is argument position 1, proposition 4 is position 2
    # (justified propositions ordered by ascending conclusion symbol).
    assert set(results) == {"1", "2"}
    assert results["1"]["truthEvaluations"] == [
        {"symbol": "1", "truth_value": 0.9, "reasoning": "Solid."},
    ]
    assert results["2"]["argumentValidity"] == 1
    assert results["2"]["propositionEvaluations"] == [
        {"symbol": "4", "validity": 1, "reasoning": "Follows."},
    ]


def test_export_summary_counts_analyses(argument_file, analysis_file, configured, capsys):
    fake = FakeRoxana()
    assert _run_with(fake, argument_file) == 0
    assert "2 analyses" in capsys.readouterr().out


def test_dry_run_lists_analysis_positions(argument_file, analysis_file, capsys):
    with patch("noesis.roxana_client._graphql") as graphql:
        assert run_export(argument_file, dry_run=True) == 0
        graphql.assert_not_called()
    assert "Analyses: positions 1, 2" in capsys.readouterr().out


def test_cleanup_on_midflight_failure(argument_file, configured, capsys):
    fake = FakeRoxana(fail_on_call=3)
    assert _run_with(fake, argument_file) == 1

    deleted = [c[1] for c in fake.calls if c[0] == "delete"]
    assert deleted == ["s1", "s2"]
    assert not any(c[0] == "discussion" for c in fake.calls)
    assert "boom" in capsys.readouterr().err


def test_missing_config(argument_file, configured, capsys):
    configured.roxana_api_url = None
    with patch("noesis.roxana_client._graphql") as graphql:
        assert run_export(argument_file) == 1
        graphql.assert_not_called()
    assert "roxana_api_url" in capsys.readouterr().out


def _exports(library: Path) -> dict:
    return json.loads((library / ".noesis" / "exports.json").read_text(encoding="utf-8"))


def test_export_is_recorded(argument_file, configured):
    assert _run_with(FakeRoxana(), argument_file) == 0
    record = _exports(configured.library_path)[argument_file.name]
    assert record["discussion_id"] == "k2rw"
    assert "earlier" not in record


def test_unchanged_argument_names_its_discussion(argument_file, configured, capsys):
    assert _run_with(FakeRoxana(), argument_file) == 0
    capsys.readouterr()
    again = FakeRoxana()
    assert _run_with(again, argument_file) == 0
    assert again.calls == []
    out = capsys.readouterr().out
    assert "Already in Roxana as discussion k2rw" in out
    assert "https://roxana.example/discussions/k2rw" in out


def test_changed_argument_is_not_sent_without_new(argument_file, configured, capsys):
    assert _run_with(FakeRoxana(), argument_file) == 0
    argument_file.write_text(ARGUMENT_TEXT.replace("Socrates will die.", "Socrates will die one day."),
                             encoding="utf-8")
    capsys.readouterr()
    again = FakeRoxana()
    assert _run_with(again, argument_file) == 1
    assert again.calls == []
    out = capsys.readouterr().out
    assert "--new" in out
    assert "https://roxana.example/discussions/k2rw" in out


class NextRoxana(FakeRoxana):
    def generate_discussion_id(self):
        return "m7qp"


def test_new_starts_another_discussion_and_keeps_the_first(argument_file, configured, capsys):
    assert _run_with(FakeRoxana(), argument_file) == 0
    argument_file.write_text(ARGUMENT_TEXT.replace("Socrates will die.", "Socrates will die one day."),
                             encoding="utf-8")
    assert _run_with(NextRoxana(), argument_file, new=True) == 0
    record = _exports(configured.library_path)[argument_file.name]
    assert record["discussion_id"] == "m7qp"
    assert record["earlier"] == ["k2rw"]
    assert "https://roxana.example/discussions/m7qp" in capsys.readouterr().out


CHANNEL_ARGUMENT = """
# Lunch
2026-10-30

## Argument
- 1 (accepted: Ann, Bob): All humans are mortal.
- 2 (accepted: Ann; rejected: Bob): Socrates is a human.
- 3 (from: 1, 2; accepted: Ann): Socrates is mortal.
- 4 (from: 3; accepted: Ann): Socrates will die.
- 5 (accepted: Cy): Socrates is a god.
- 6 (from: 5; accepted: Cy; rejected: Ann): Socrates will not die.
"""


def test_each_member_s_goal_is_what_they_justify_or_what_they_contest():
    from noesis.argue import markdown_to_argument
    argument = markdown_to_argument(CHANNEL_ARGUMENT)["argument"]
    # Ann justifies 3 and then 4, the last; Cy justifies 6; Bob justifies
    # nothing and rejects 2, which Ann's goal rests on. Dee has no stance.
    assert member_goals(argument, ["Ann", "Bob", "Cy", "Dee"]) == {"Ann": "4", "Cy": "6", "Bob": "4"}


def test_a_channel_s_argument_carries_each_member_s_stances_and_goal(tmp_path, configured, capsys):
    from noesis.config import Speaker
    configured.members = (Speaker("ann", "Ann", ("Ann",)), Speaker("bob", "Bob", ("Bob",)),
                          Speaker("cy", "Cy", ("Cy",)))
    companion = tmp_path / "2026-10-30-lunch.argument.md"
    companion.write_text(CHANNEL_ARGUMENT, encoding="utf-8")
    fake = FakeRoxana()
    assert _run_with(fake, companion) == 0
    propositions = json.loads(fake.calls[-1][2])["propositions"]
    assert [(e["accepted"], e["rejected"]) for e in propositions] == [
        (["ann", "bob"], []), (["ann"], ["bob"]), (["ann"], []), (["ann"], []), (["cy"], []), (["cy"], ["ann"])]
    assert [e["goal"] for e in propositions] == [[], [], [], ["ann", "bob"], [], ["cy"]]
    assert fake.goals_summary == "Socrates will die (ann, bob) \u2014 Socrates will not die (cy)"
    out = capsys.readouterr().out
    assert "Proposition 4 is the goal of ann, bob." in out and "Proposition 6 is the goal of cy." in out
