from mdc.cmd_argue import run_argue


def test_argue_reads_a_document_alone(tmp_path, capsys):
    chat = tmp_path / "2026-10-27-essay.chat.md"
    chat.write_text("\n# Essay\n2026-10-27\n\n## Prompt\n\nAn argument?\n")
    assert run_argue(chat) == 1
    assert "not a document" in capsys.readouterr().out
    assert chat.exists()


def test_an_existing_argument_is_not_extracted_again(tmp_path, capsys):
    (tmp_path / "2026-10-27-essay.document.md").write_text("\n# Essay\n2026-10-27\n\nProse.\n")
    (tmp_path / "2026-10-27-essay.argument.md").write_text("## Argument\n- 1: p\n")
    assert run_argue(tmp_path / "2026-10-27-essay.document.md") == 0
    assert "already exists" in capsys.readouterr().out
