"""What a person may spend and keep at noesis (SERVER.md, Phase 6); who they are is auth's."""

import hashlib
import importlib.util
import io
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from noesis import accounts, server

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("NOESIS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NOESIS_CONFIG_DIR", str(tmp_path / "config"))
    for name in ("NOESIS_ACCOUNT", "NOESIS_FREE_ALLOWANCE_USD", "NOESIS_FREE_MONTHLY_CAP_USD", "NOESIS_FREE_STORAGE_MB",
                 "NOESIS_FREE_FILE_MB", "NOESIS_FREE_LIBRARIES"):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / "users.toml").write_text(
        f'[[tokens]]\nuser = "ann"\nsha256 = "{hashlib.sha256(b"ann-token").hexdigest()}"\n'
        f'[[tokens]]\nuser = "rod"\nsha256 = "{hashlib.sha256(b"rod-token").hexdigest()}"\n'
    )
    (tmp_path / "libraries" / "ann" / "notes").mkdir(parents=True)
    (tmp_path / "libraries" / "rod" / "philosophy").mkdir(parents=True)
    return tmp_path


ANN = {"Authorization": "Bearer ann-token"}
ROD = {"Authorization": "Bearer rod-token"}


def test_operators_users_are_unlimited_until_given_a_plan(data):
    # rod holds a minted token: the operator's.
    assert accounts.plan_of("rod") == accounts.UNLIMITED and accounts.account("rod") is None
    accounts.set_plan("rod", accounts.FREE)
    assert accounts.is_free("rod")
    # Anybody else signed in at auth is free until given a plan.
    assert accounts.is_free("newcomer") and accounts.account("newcomer") is None
    accounts.set_plan("newcomer", accounts.UNLIMITED)
    assert not accounts.is_free("newcomer")
    # A group library's own meter is its application's to divide, never capped here.
    assert accounts.plan_of("thefloor/lunch") == accounts.UNLIMITED
    with pytest.raises(ValueError):
        accounts.set_plan("Not A Name", accounts.FREE)


def test_a_free_account_spends_its_allowance_and_then_stops(data, monkeypatch):
    monkeypatch.setenv("NOESIS_ACCOUNT", "zedd")
    accounts.check_spend()
    # A million output tokens of Haiku 4.5: $5, more than the $1 allowance.
    accounts.charge_anthropic("claude-haiku-4-5", SimpleNamespace(input_tokens=0, output_tokens=200_000))
    assert accounts.spent("zedd") == pytest.approx(1.0)
    with pytest.raises(accounts.AllowanceExhausted, match="allowance"):
        accounts.check_spend()
    # Allowance 0: free model use is off.
    monkeypatch.setenv("NOESIS_FREE_ALLOWANCE_USD", "0")
    assert "allowance" in accounts.refusal("yann")


def test_free_accounts_together_have_a_cap(data, monkeypatch):
    monkeypatch.setenv("NOESIS_FREE_MONTHLY_CAP_USD", "1.50")
    accounts.charge("xavi", 0.80)
    accounts.charge("yoli", 0.80)
    assert "paused" in accounts.refusal("walt")
    # The operator's spending does not count, and is never refused.
    accounts.charge("rod", 100)
    assert accounts.refusal("rod") is None


def test_the_meter_is_off_outside_a_server_run(data):
    accounts.charge("zedd", 50)
    accounts.check_spend()  # no NOESIS_ACCOUNT: the Mac, or a test
    accounts.charge_dianoia()
    assert accounts.spent("zedd") == 50


def test_cost_at_list_price():
    usage = SimpleNamespace(input_tokens=1_000_000, output_tokens=1_000_000,
                            cache_creation_input_tokens=1_000_000, cache_read_input_tokens=1_000_000)
    assert accounts.anthropic_cost("claude-haiku-4-5", usage) == pytest.approx(1 + 5 + 1.25 + 0.10)
    # An unknown model costs as much as the dearest known one.
    assert accounts.anthropic_cost("claude-unknown", SimpleNamespace(output_tokens=1_000_000)) == pytest.approx(75)


def test_a_free_account_stores_within_its_limits(data, monkeypatch):
    monkeypatch.setenv("NOESIS_FREE_STORAGE_MB", "0.01")  # 10 KiB
    accounts.set_plan("ann", accounts.FREE)
    client = TestClient(server.app)
    put = lambda path, body: client.put(f"/libraries/ann/notes/files/{path}", headers={**ANN, "If-None-Match": "*"},
                                        content=body)
    assert put("2026/a.document.md", b"x" * 6000).status_code == 200
    full = put("2026/b.document.md", b"x" * 6000)
    assert full.status_code == 413 and "at most" in full.json()["detail"]
    assert "files" in put("2026/c.exe", b"x").json()["detail"]
    # Replacing counts the file it replaces.
    sha = hashlib.sha256(b"x" * 6000).hexdigest()
    assert client.put("/libraries/ann/notes/files/2026/a.document.md", content=b"y" * 9000,
                      headers={**ANN, "If-Match": f'"{sha}"'}).status_code == 200
    # Libraries: three.
    for name in ("two", "three"):
        assert client.post("/libraries", headers=ANN, json={"name": name}).status_code == 201
    assert client.post("/libraries", headers=ANN, json={"name": "four"}).status_code == 403
    # The operator's user has no such limits.
    assert client.put("/libraries/rod/philosophy/files/big.bin", headers={**ROD, "If-None-Match": "*"},
                      content=b"x" * 20000).status_code == 200


def test_a_free_accounts_spending_run_needs_allowance(data, monkeypatch):
    # The run's subprocess imports this checkout's noesis.
    monkeypatch.setenv("PYTHONPATH", str(REPO))
    accounts.set_plan("ann", accounts.FREE)
    accounts.charge("ann", 5)
    client = TestClient(server.app)
    refused = client.post("/libraries/ann/notes/run", headers=ANN, json={"argv": ["index"]})
    assert refused.status_code == 402 and "allowance" in refused.json()["detail"]
    # What costs nothing still runs.
    checked = client.post("/libraries/ann/notes/run", headers=ANN, json={"argv": ["check"]})
    assert checked.status_code == 200 and '"exit_code"' in checked.text
    imported = client.post("/libraries/ann/notes/import?filename=a.md", headers=ANN, content=b"hi")
    assert imported.status_code == 402
    me = client.get("/me", headers=ANN).json()
    assert me["plan"] == "free" and me["spent_usd"] == 5 and me["storage_bytes"] == 50 * 1024 * 1024


def test_the_accounts_script(data):
    spec = importlib.util.spec_from_file_location("accounts_script", REPO / "scripts" / "accounts.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    out = io.StringIO()
    with redirect_stdout(out):
        script.main(["plan", "zedd", "free"])
        script.main(["list"])
    listed = out.getvalue()
    assert "rod" in listed and "unlimited" in listed and "zedd" in listed
    with pytest.raises(SystemExit):
        script.main(["plan", "Not A Name", "free"])
    with pytest.raises(SystemExit):
        script.main(["link", "rod@example.com", "rod"])  # auth's now


def test_the_model_client_charges_the_run_and_refuses_past_the_allowance(data, monkeypatch):
    from noesis.anthropic_client import AnthropicChatClient
    monkeypatch.setenv("NOESIS_CACHE_DIR", str(data / "cache"))
    monkeypatch.setenv("NOESIS_ACCOUNT", "zedd")
    calls = []

    class Stream:
        text_stream = ["Hi."]
        def __enter__(self): return self
        def __exit__(self, *exc): return False
        def get_final_message(self):
            return SimpleNamespace(usage=SimpleNamespace(input_tokens=100_000, output_tokens=150_000),
                                   stop_reason="end_turn", content=[])

    client = AnthropicChatClient(model="claude-haiku-4-5", api_key="test")
    monkeypatch.setattr(client._client, "messages", SimpleNamespace(stream=lambda **kw: calls.append(kw) or Stream()))
    assert client.generate_reply("system", [{"role": "user", "content": "Hello"}]).text == "Hi."
    assert accounts.spent("zedd") == pytest.approx(0.1 + 0.75)
    client.generate_reply("system", [{"role": "user", "content": "Again"}])
    with pytest.raises(accounts.AllowanceExhausted):
        client.generate_reply("system", [{"role": "user", "content": "Once more"}])
    assert len(calls) == 2


def test_the_operator_raises_one_accounts_allowance(data, monkeypatch):
    accounts.charge("zedd", 1.20)
    assert "($1.00) is used up" in accounts.refusal("zedd")
    assert accounts.raise_allowance("zedd", 5) == pytest.approx(6.0)
    assert accounts.refusal("zedd") is None
    # It is kept as the default moves, and stays when the default is 0.
    monkeypatch.setenv("NOESIS_FREE_ALLOWANCE_USD", "0")
    assert accounts.allowance("zedd") == pytest.approx(5.0)
    assert accounts.refusal("zedd") is None
    monkeypatch.delenv("NOESIS_FREE_ALLOWANCE_USD")
    # Taking back stops at the default.
    assert accounts.raise_allowance("zedd", -2) == pytest.approx(4.0)
    with pytest.raises(ValueError, match="only \\$3.00"):
        accounts.raise_allowance("zedd", -4)
    client = TestClient(server.app)
    accounts.set_plan("ann", accounts.FREE)
    accounts.raise_allowance("ann", 2.5)
    assert client.get("/me", headers=ANN).json()["allowance_usd"] == pytest.approx(3.5)


def test_the_accounts_script_raises(data):
    spec = importlib.util.spec_from_file_location("accounts_script", REPO / "scripts" / "accounts.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    out = io.StringIO()
    with redirect_stdout(out):
        script.main(["raise", "zedd", "5"])
        script.main(["list"])
    assert "zedd: $6.00 a month" in out.getvalue() and "$0.00 of $6.00" in out.getvalue()
    with pytest.raises(SystemExit):
        script.main(["raise", "zedd", "-10"])
    out = io.StringIO()
    with redirect_stdout(out):
        script.main(["raised"])
    listed = out.getvalue()
    assert listed.startswith("default $1.00 a month; free accounts together $25.00")
    assert "zedd" in listed and "+$5.00 = $6.00" in listed and "yann" not in listed


def test_speaker_names_are_any_users_and_replaced_whole(data):
    assert accounts.speaker_names("rod") == ()
    assert accounts.set_speaker_names("rod", ["Rodrigo", "Prompt", " Rodrigo ", "Rodrigo Vanegas"]) == (
        "Rodrigo", "Rodrigo Vanegas")
    assert accounts.speaker_names("rod") == ("Rodrigo", "Rodrigo Vanegas")
    assert accounts.speaker_names("ann") == ()
    accounts.set_speaker_names("rod", ["Rod"])
    assert accounts.speaker_names("rod") == ("Rod",)
    accounts.set_speaker_names("rod", [])
    assert accounts.speaker_names("rod") == ()
    for bad in (["a,b"], ["x" * 81], [f"n{i}" for i in range(accounts.MOST_SPEAKER_NAMES + 1)]):
        with pytest.raises(ValueError):
            accounts.set_speaker_names("rod", bad)


def test_the_libraries_report(data):
    import json
    spec = importlib.util.spec_from_file_location("libraries_script", REPO / "scripts" / "libraries.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    notes = data / "libraries" / "ann" / "notes"
    (notes / "2026").mkdir()
    (notes / "2026" / "2026-10-30-a.document.md").write_text("\n# A\n2026-10-30\n\nText.\n")
    (notes / "2026" / "2026-10-30-b.source.md").write_text("\n# B\n2026-10-30\n\nText.\n")
    (notes / ".noesis").mkdir()
    (notes / ".noesis" / "manifest.json").write_text(json.dumps({"entries": [
        {"rel_path": "2026/2026-10-30-a.document.md", "title": "A", "word_count": 1,
         "summary": "", "terms": [], "refs": [], "related": []}]}))
    accounts.set_plan("ann", accounts.FREE)
    out = io.StringIO()
    with redirect_stdout(out):
        script.main([])
    lines = out.getvalue().splitlines()
    assert lines[0] == "ann  free"
    assert lines[1].split() == ["notes", "1", "indexed", "2", "files"]
    assert lines[2] == "rod  unlimited"
    assert lines[3].split() == ["philosophy", "0", "indexed", "0", "files"]
    assert lines[1].index("indexed") == lines[3].index("indexed")


def _script(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    return script


def test_the_operator_renames_a_user_everywhere_noesis_keeps_the_name(data):
    script = _script("rename_user")
    old = "freeyourtime"
    (data / "libraries" / old / "notes").mkdir(parents=True)
    accounts.set_plan(old, accounts.FREE)
    accounts.set_speaker_names(old, ["Rochelle"])
    accounts.charge(old, 0.25)
    out = io.StringIO()
    with redirect_stdout(out):
        script.main([old, "rochelle"])
    assert f"{old}/notes" in out.getvalue() and (data / "libraries" / old).exists()  # a plan changes nothing
    for bad in ([old, "ann"], [old, "Bad Name"], ["ann", "x"]):  # taken, invalid, operator
        with pytest.raises(SystemExit):
            script.main(bad)
    with redirect_stdout(io.StringIO()):
        script.main([old, "rochelle", "--apply"])
    assert accounts.account(old) is None and accounts.account("rochelle").plan == accounts.FREE
    assert accounts.speaker_names("rochelle") == ("Rochelle",) and accounts.spent("rochelle") == 0.25
    assert (data / "libraries" / "rochelle" / "notes").is_dir() and not (data / "libraries" / old).exists()
