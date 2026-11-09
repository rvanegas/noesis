from pathlib import Path
from unittest.mock import patch

import pytest

import noesis.config
from noesis.cmd_reply import run_reply

CHAT = "\n# Essay\n2026-10-27\n\n## Prompt\n\nTighten it.\n"


@pytest.fixture
def session(tmp_path, monkeypatch):
    config = tmp_path / "config.toml"
    config.write_text('model = "claude-sonnet-5"\n')
    monkeypatch.setattr(noesis.config, "DEFAULT_CONFIG_PATH", config)
    monkeypatch.delenv("NOESIS_LIBRARY", raising=False)
    chat = tmp_path / "2026-10-27-essay.chat.md"
    chat.write_text(CHAT)
    return tmp_path, chat


def _edit_flag(chat: Path, **kwargs) -> bool:
    with patch("noesis.cmd_reply._reply_anthropic", return_value="Done.\n") as reply:
        assert run_reply(chat, **kwargs) == 0
    return reply.call_args.kwargs["edit"]


def test_a_companion_is_loaded_without_asking(session):
    tmp, chat = session
    (tmp / "2026-10-27-essay.document.md").write_text("\n# Essay\n2026-10-27\n\nProse.\n")
    assert _edit_flag(chat) is True


def test_no_companion_no_edit_mode(session):
    tmp, chat = session
    assert _edit_flag(chat) is False
    assert not (tmp / "2026-10-27-essay.document.md").exists()


def test_dash_e_still_creates_the_document(session):
    tmp, chat = session
    assert _edit_flag(chat, edit=True) is True
    assert (tmp / "2026-10-27-essay.document.md").exists()


def test_a_speaker_of_several_words_is_a_turn_like_any(session):
    tmp, chat = session
    chat.write_text("\n# Essay\n2026-10-27\n\n## Mary Ann\n\nWhat about Kant?\n")
    assert _edit_flag(chat) is False


def test_reply_answers_a_chat_alone(session, capsys):
    tmp, chat = session
    document = tmp / "2026-10-27-essay.document.md"
    document.write_text(CHAT)
    with patch("noesis.cmd_reply._reply_anthropic") as reply:
        assert run_reply(document) == 1
    reply.assert_not_called()
    assert "not a chat" in capsys.readouterr().out


def test_in_a_channel_the_document_is_claude_s_account_of_its_members(tmp_path):
    from noesis.config import Speaker
    from noesis.edit_tools import build_edit_context, channel_note
    channel = (Speaker("ann", "Ann", ("Ann",)), Speaker("bob", "Bob", ("Bob",)))
    document = tmp_path / "2026-10-27-essay.document.md"
    document.write_text("\n# Essay\n2026-10-27\n\nProse.\n")
    argument = tmp_path / "2026-10-27-essay.argument.md"
    argument.write_text("\n# Essay\n2026-10-27\n\n## Argument\n- 1: P\n")
    told = build_edit_context([document, argument], members=channel)
    assert "an account of what each member of the channel thinks" in told
    assert "The channel's members write the propositions." in told and "inference accepted:" in told
    alone = build_edit_context([document, argument])
    assert "member" not in alone and "The user writes the propositions." in alone
    assert channel_note(channel).startswith("This chat is a channel's, whose members are Ann, Bob.")
