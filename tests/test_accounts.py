"""Accounts made by signing in, and what a free one may spend and keep (SERVER.md, Phase 6)."""

import hashlib
import importlib.util
import io
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from mdc import accounts, server

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("MDC_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MDC_CONFIG_DIR", str(tmp_path / "config"))
    for name in ("MDC_ACCOUNT", "MDC_FREE_ALLOWANCE_USD", "MDC_FREE_MONTHLY_CAP_USD", "MDC_FREE_STORAGE_MB",
                 "MDC_FREE_FILE_MB", "MDC_FREE_LIBRARIES"):
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


def test_user_names_come_from_the_address_and_are_unique(data):
    assert accounts.user_stem("Jane.Doe+mdc@example.com") == "jane-doe"
    assert accounts.user_stem("..@example.com") == "user"
    # Taken by users.toml (and its libraries directory), by an account, then free.
    assert accounts.create_account("ann@a.example").user == "ann-2"
    assert accounts.create_account("ann@b.example").user == "ann-3"
    assert accounts.create_account("zed@c.example").user == "zed"
    # The same address is the same account.
    assert accounts.create_account("zed@c.example").user == "zed"
    assert (data / "accounts.db").stat().st_mode & 0o777 == 0o600


def test_operators_users_are_unlimited_until_given_a_plan(data):
    assert accounts.plan_of("rod") == accounts.UNLIMITED and not accounts.is_active("rod")
    accounts.link("rod@example.com", "rod", accounts.UNLIMITED)
    assert accounts.is_active("rod") and not accounts.is_free("rod")
    accounts.set_plan("rod", accounts.FREE)
    assert accounts.is_free("rod")
    accounts.set_disabled("rod", True)
    assert not accounts.is_active("rod")


def test_sign_in_mail_is_limited(data):
    for _ in range(5):
        assert accounts.allow_send("a@example.com", "1.1.1.1")
    assert not accounts.allow_send("a@example.com", "2.2.2.2")  # the address's five an hour
    for n in range(5):
        assert accounts.allow_send(f"b{n}@example.com", "1.1.1.1")
    assert not accounts.allow_send("c@example.com", "1.1.1.1")  # the client's ten an hour
    assert accounts.allow_send("c@example.com", "3.3.3.3")


def test_a_free_account_spends_its_allowance_and_then_stops(data, monkeypatch):
    accounts.create_account("zed@example.com")
    monkeypatch.setenv("MDC_ACCOUNT", "zed")
    accounts.check_spend()
    # A million output tokens of Haiku 4.5: $5, more than the $1 allowance.
    accounts.charge_anthropic("claude-haiku-4-5", SimpleNamespace(input_tokens=0, output_tokens=200_000))
    assert accounts.spent("zed") == pytest.approx(1.0)
    with pytest.raises(accounts.AllowanceExhausted, match="allowance"):
        accounts.check_spend()
    # Allowance 0: free model use is off.
    monkeypatch.setenv("MDC_FREE_ALLOWANCE_USD", "0")
    accounts.create_account("yan@example.com")
    assert "allowance" in accounts.refusal("yan")


def test_free_accounts_together_have_a_cap(data, monkeypatch):
    monkeypatch.setenv("MDC_FREE_MONTHLY_CAP_USD", "1.50")
    for name in ("x", "y"):
        accounts.create_account(f"{name}@example.com")
    accounts.charge("x", 0.80)
    accounts.charge("y", 0.80)
    accounts.create_account("w@example.com")
    assert "paused" in accounts.refusal("w")
    # The operator's spending does not count, and is never refused.
    accounts.charge("rod", 100)
    assert accounts.refusal("rod") is None


def test_the_meter_is_off_outside_a_server_run(data):
    accounts.create_account("zed@example.com")
    accounts.charge("zed", 50)
    accounts.check_spend()  # no MDC_ACCOUNT: the Mac, or a test
    accounts.charge_dianoia()
    assert accounts.spent("zed") == 50


def test_cost_at_list_price():
    usage = SimpleNamespace(input_tokens=1_000_000, output_tokens=1_000_000,
                            cache_creation_input_tokens=1_000_000, cache_read_input_tokens=1_000_000)
    assert accounts.anthropic_cost("claude-haiku-4-5", usage) == pytest.approx(1 + 5 + 1.25 + 0.10)
    # An unknown model costs as much as the dearest known one.
    assert accounts.anthropic_cost("claude-unknown", SimpleNamespace(output_tokens=1_000_000)) == pytest.approx(75)


def test_a_free_account_stores_within_its_limits(data, monkeypatch):
    monkeypatch.setenv("MDC_FREE_STORAGE_MB", "0.01")  # 10 KiB
    accounts.link("ann@example.com", "ann", accounts.FREE)
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
    # The run's subprocess imports this checkout's mdc.
    monkeypatch.setenv("PYTHONPATH", str(REPO))
    accounts.link("ann@example.com", "ann", accounts.FREE)
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
        script.main(["link", "Rod@Example.com", "rod"])
        script.main(["list"])
    assert "rod@example.com" in out.getvalue() and "unlimited" in out.getvalue()
    with pytest.raises(SystemExit):
        script.main(["link", "rod@example.com", "rod"])  # the address is taken
    with pytest.raises(SystemExit):
        script.main(["plan", "nobody", "free"])


def test_the_model_client_charges_the_run_and_refuses_past_the_allowance(data, monkeypatch):
    from mdc.anthropic_client import AnthropicChatClient
    monkeypatch.setenv("MDC_CACHE_DIR", str(data / "cache"))
    accounts.create_account("zed@example.com")
    monkeypatch.setenv("MDC_ACCOUNT", "zed")
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
    assert accounts.spent("zed") == pytest.approx(0.1 + 0.75)
    client.generate_reply("system", [{"role": "user", "content": "Again"}])
    with pytest.raises(accounts.AllowanceExhausted):
        client.generate_reply("system", [{"role": "user", "content": "Once more"}])
    assert len(calls) == 2


def test_the_operator_raises_one_accounts_allowance(data, monkeypatch):
    accounts.create_account("zed@example.com")
    accounts.charge("zed", 1.20)
    assert "($1.00) is used up" in accounts.refusal("zed")
    assert accounts.raise_allowance("zed", 5) == pytest.approx(6.0)
    assert accounts.refusal("zed") is None
    # It is kept as the default moves, and stays when the default is 0.
    monkeypatch.setenv("MDC_FREE_ALLOWANCE_USD", "0")
    assert accounts.allowance("zed") == pytest.approx(5.0)
    assert accounts.refusal("zed") is None
    monkeypatch.delenv("MDC_FREE_ALLOWANCE_USD")
    # Taking back stops at the default.
    assert accounts.raise_allowance("zed", -2) == pytest.approx(4.0)
    with pytest.raises(ValueError, match="only \\$3.00"):
        accounts.raise_allowance("zed", -4)
    with pytest.raises(ValueError, match="no account"):
        accounts.raise_allowance("nobody", 1)
    client = TestClient(server.app)
    accounts.link("ann@example.com", "ann", accounts.FREE)
    accounts.raise_allowance("ann", 2.5)
    assert client.get("/me", headers=ANN).json()["allowance_usd"] == pytest.approx(3.5)


def test_the_accounts_script_raises(data):
    spec = importlib.util.spec_from_file_location("accounts_script", REPO / "scripts" / "accounts.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    accounts.create_account("zed@example.com")
    out = io.StringIO()
    with redirect_stdout(out):
        script.main(["raise", "zed", "5"])
        script.main(["list"])
    assert "zed: $6.00 a month" in out.getvalue() and "$0.00 of $6.00" in out.getvalue()
    with pytest.raises(SystemExit):
        script.main(["raise", "zed", "-10"])
    accounts.create_account("yan@example.com")
    out = io.StringIO()
    with redirect_stdout(out):
        script.main(["raised"])
    listed = out.getvalue()
    assert listed.startswith("default $1.00 a month; free accounts together $25.00")
    assert "zed" in listed and "+$5.00 = $6.00" in listed and "yan" not in listed
