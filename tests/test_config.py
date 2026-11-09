from pathlib import Path

import pytest

import noesis.config
from noesis.config import load_config


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    monkeypatch.setattr(noesis.config, "DEFAULT_CONFIG_PATH", path)
    for var in ("NOESIS_LIBRARY", "NOESIS_USER_NAMES", "NOESIS_OWNER", "NOESIS_MEMBERS"):
        monkeypatch.delenv(var, raising=False)
    return path


def test_user_names_always_include_prompt(config_file):
    config_file.write_text('user_names = ["Rodrigo"]\n')
    assert load_config().user_names == ("Prompt", "Rodrigo")


def test_user_names_from_the_run_replace_the_config(config_file, monkeypatch):
    config_file.write_text('user_names = ["Prompt", "Rodrigo"]\n')
    monkeypatch.setenv("NOESIS_USER_NAMES", "Ana, Prompt,Bea")
    assert load_config().user_names == ("Prompt", "Ana", "Bea")


def test_run_library_overrides_config(config_file, tmp_path, monkeypatch):
    configured = tmp_path / "configured"
    chosen = tmp_path / "chosen"
    configured.mkdir()
    chosen.mkdir()
    config_file.write_text(f'library_path = "{configured}"\n')
    assert load_config().library_path == configured.resolve()
    monkeypatch.setenv("NOESIS_LIBRARY", str(chosen))
    assert load_config().library_path == chosen.resolve()


def test_system_prompt_ends_with_the_librarys(config_file, tmp_path, monkeypatch):
    library = tmp_path / "lib"
    library.mkdir()
    (library / "SYSTEM_PROMPT.md").write_text("Write in continuous prose.\n")
    monkeypatch.setenv("NOESIS_LIBRARY", str(library))
    prompt = load_config().system_prompt
    assert prompt.startswith("You are continuing a hand-edited markdown chat transcript.")
    assert prompt.endswith("Write in continuous prose.")


def test_no_library_no_library_prompt(config_file):
    config_file.write_text("")
    config = load_config()
    assert config.library_path is None
    assert "Last, First (year)" in config.system_prompt


def test_a_person_s_library_has_its_owner_whose_headings_are_the_user_names(config_file, monkeypatch):
    import json
    monkeypatch.setenv("NOESIS_USER_NAMES", "Ann")
    monkeypatch.setenv("NOESIS_OWNER", json.dumps({"user": "ann", "name": "Ann Example"}))
    owner = load_config().owner
    assert (owner.user, owner.name, owner.headings) == ("ann", "Ann Example", ("Prompt", "Ann"))
    # On the Mac, with no server to say, roxana_user by user name.
    monkeypatch.delenv("NOESIS_OWNER")
    config_file.write_text('roxana_user = "ann"\n')
    assert load_config().owner.name == "ann"
    # A channel's members come first.
    monkeypatch.setenv("NOESIS_MEMBERS", json.dumps([{"user": "bob", "name": "Bob", "headings": ["Bob"]}]))
    assert [m.user for m in load_config().people] == ["bob"]
