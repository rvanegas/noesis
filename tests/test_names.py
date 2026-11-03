"""The register of names across applications (names.py): one name per address, renamed from either end."""

import asyncio
import base64
import hashlib
import hmac
import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from noesis import accounts, names, server, service

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("NOESIS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NOESIS_CONFIG_DIR", str(tmp_path / "config"))
    (tmp_path / "users.toml").write_text(
        f'[[tokens]]\nuser = "rod"\nsha256 = "{hashlib.sha256(b"rod-token").hexdigest()}"\n')
    (tmp_path / "libraries" / "rod" / "philosophy").mkdir(parents=True)
    # Nothing is posted from a test unless the test posts it.
    monkeypatch.setattr(names, "_post", lambda *_: False)
    monkeypatch.setattr(names, "_soon", lambda: None)
    return tmp_path


def _script(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    return script


@pytest.fixture
def floor(data):
    """The Floor, registered and marked as keeping names; its Basic credentials."""
    out = io.StringIO()
    with redirect_stdout(out):
        _script("add_client").main(["thefloor", "--name", "The Floor",
                                    "--redirect", "https://floor.example/noesis/callback"])
        _script("client_names").main(["thefloor", "--hook", "https://floor.example/noesis/renamed"])
    secret = dict(line.split("=", 1) for line in out.getvalue().split() if "=" in line)["NOESIS_CLIENT_SECRET"]
    return {"Authorization": "Basic " + base64.b64encode(f"thefloor:{secret}".encode()).decode()}, secret


def _issue(client_id, user):
    from noesis.oauth import provider
    data = provider._load()
    token = provider._issue(data, client_id, user, [], None)
    provider._save(data)
    return token


def test_a_reservation_holds_name_and_address_until_the_first_sign_in(data):
    assert names.name_for("Mei.Lin@example.com", "thefloor", ["Mei"]) == ("mei1", False)
    # The same address is the same name, whoever asks again and whatever they suggest.
    assert names.name_for("mei.lin@example.com", "thefloor", ["other"]) == ("mei1", False)
    # Nobody else is given it, and there is no account yet.
    assert names.name_for("mei@b.example", "thefloor", ["Mei"]) == ("mei2", False)
    assert accounts.account("mei1") is None
    assert accounts.create_account("someone@example.com").user != "mei1"
    # The first sign-in at noesis makes the account under the reserved name.
    assert accounts.create_account("mei.lin@example.com").user == "mei1"
    assert accounts.reservation("mei1") is None
    assert names.name_for("mei.lin@example.com", "thefloor") == ("mei1", True)


def test_a_suggestion_nothing_can_be_made_of_falls_back_to_the_address(data):
    assert names.name_for("anna.k@example.com", "thefloor", ["芽衣"]) == ("anna_k", False)


def test_choosing_a_name_reserves_it_or_renames_the_pair(data):
    assert names.choose("ann@example.com", "@AnnaK", "thefloor") == "annak"
    assert accounts.reservation("annak") == "ann@example.com"
    with pytest.raises(names.Taken):
        names.choose("bob@example.com", "annak", "thefloor")
    with pytest.raises(names.Invalid):
        names.choose("bob@example.com", "bob", "thefloor")  # under four
    with pytest.raises(names.Invalid):
        names.choose("bob@example.com", "bo-b", "thefloor")
    assert names.choose("ann@example.com", "anna_k", "thefloor") == "anna_k"
    assert accounts.reservation("annak") is None and accounts.reservation("anna_k") == "ann@example.com"
    # A libraries directory with no account behind it holds its name too.
    (data / "libraries" / "carlos").mkdir()
    with pytest.raises(names.Taken):
        names.choose("carl@example.com", "carlos", "thefloor")


def test_an_accounts_rename_moves_everything_and_keeps_its_grants(data):
    found = accounts.create_account("freeyourtime@example.com")
    (data / "libraries" / found.user / "notes").mkdir(parents=True)
    accounts.set_speaker_names(found.user, ["Rochelle"])
    accounts.charge(found.user, 0.25)
    issued = _issue("thefloor", found.user)
    assert names.rename(found.user, "rochelle") == "rochelle"
    assert accounts.account(found.user) is None and accounts.account("rochelle").email == "freeyourtime@example.com"
    assert accounts.speaker_names("rochelle") == ("Rochelle",) and accounts.spent("rochelle") == 0.25
    assert service.library_ids("rochelle") == ["rochelle/notes"]
    me = TestClient(server.app).get("/me", headers={"Authorization": f"Bearer {issued.access_token}"}).json()
    assert me["user"] == "rochelle"


def test_a_rename_waits_for_a_run_in_the_libraries(data):
    found = accounts.create_account("busy@example.com")
    root = data / "libraries" / found.user / "notes"
    root.mkdir(parents=True)
    lock = service.lock_for(root)

    async def held():
        async with lock:
            with pytest.raises(names.Busy):
                names.rename(found.user, "busy_one")
    asyncio.run(held())
    assert names.rename(found.user, "busy_one") == "busy_one"


def test_only_a_reservations_address_moves(data):
    names.name_for("old@example.com", "thefloor")
    names.move("old@example.com", "new@example.com")
    assert names.pair_for("new@example.com") == ("old1", False) and names.pair_for("old@example.com") is None
    accounts.create_account("mine@example.com")
    with pytest.raises(names.Taken):
        names.move("mine@example.com", "elsewhere@example.com")
    with pytest.raises(names.Taken):
        names.move("new@example.com", "mine@example.com")


def test_the_register_answers_only_an_application_that_keeps_names(data, floor):
    basic, _ = floor
    client = TestClient(server.app)
    assert client.post("/names", json={"email": "a@example.com"}).status_code == 401
    wrong = {"Authorization": "Basic " + base64.b64encode(b"thefloor:nope").decode()}
    assert client.post("/names", json={"email": "a@example.com"}, headers=wrong).status_code == 401
    answer = client.post("/names", json={"email": "Alice@example.com", "suggest": ["Alice"]}, headers=basic)
    assert answer.json() == {"user": "alice", "account": False}
    assert client.put("/names", json={"email": "alice@example.com", "user": "Alice_B"}, headers=basic).json() == \
        {"user": "alice_b"}
    names.name_for("bob@example.com", "thefloor", ["bob"])
    taken = client.put("/names", json={"email": "bob@example.com", "user": "alice_b"}, headers=basic)
    assert taken.status_code == 409 and "taken" in taken.json()["detail"]
    assert client.put("/names", json={"email": "bob@example.com", "user": "b"}, headers=basic).status_code == 400
    moved = client.put("/names/address", json={"email": "alice@example.com", "new_email": "al@example.com"},
                       headers=basic)
    assert moved.status_code == 200 and names.pair_for("al@example.com") == ("alice_b", False)
    # The Floor asked for these itself, so it is owed none of them.
    assert names.owed() == []


def test_a_rename_at_noesis_is_owed_to_the_floor_until_it_answers(data, floor):
    _, secret = floor
    found = accounts.create_account("dee@example.com")
    web = _issue("noesis-web", found.user)
    client = TestClient(server.app)
    bearer = {"Authorization": f"Bearer {web.access_token}"}
    assert client.put("/me/user", json={"user": "a"}, headers=bearer).status_code == 400
    assert client.put("/me/user", json={"user": "rod"}, headers=bearer).status_code == 400
    assert client.put("/me/user", json={"user": "dee_dee"}, headers=bearer).json() == {"user": "dee_dee"}
    assert names.owed() == [("thefloor", {"email": "dee@example.com", "old": found.user, "new": "dee_dee"}, 0)]

    posted = []
    assert names.deliver(post=lambda *call: posted.append(call) or False) == 0
    assert names.owed()[0][2] == 1
    # Not again before its time; then answered, and owed no longer.
    assert names.deliver(post=lambda *call: posted.append(call) or True) == 0
    assert names.deliver(now=10 ** 11, post=lambda *call: posted.append(call) or True) == 1
    assert names.owed() == []
    url, body, signed = posted[-1]
    assert url == "https://floor.example/noesis/renamed"
    assert json.loads(body) == {"email": "dee@example.com", "old": found.user, "new": "dee_dee"}
    assert signed == "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_unmarking_drops_what_was_owed(data, floor):
    names.name_for("eve@example.com", "thefloor")
    names.rename("eve1", "eve_x", by=None)
    assert len(names.owed()) == 1
    with redirect_stdout(io.StringIO()):
        _script("client_names").main(["thefloor", "--off"])
    assert names.owed() == []
    with pytest.raises(SystemExit):
        _script("client_names").main(["thefloor", "--hook", "http://floor.example/x"])


def test_the_operators_link_respects_reservations(data):
    names.name_for("fay@example.com", "thefloor", ["fay_f"])
    with pytest.raises(ValueError):
        accounts.link("other@example.com", "fay_f", accounts.FREE)
    assert accounts.link("fay@example.com", "fay_f", accounts.FREE).user == "fay_f"
    assert accounts.reservation("fay_f") is None


def test_the_floors_names_are_reconciled_and_noesis_wins(data, floor):
    script = _script("reserve_names")
    accounts.create_account("gus@example.com")              # gus1 here, @Gus there
    names.name_for("hal@example.com", "thefloor", ["hal_h"])
    (data / "libraries" / "irene").mkdir()                  # irene is a libraries directory's
    pairs = "\n".join([
        "# The Floor's names",
        "Gus@example.com\tGus",
        "hal@example.com\tHal_H",
        "ida@example.com\tIdaB",
        "irene@example.com\tirene",
        "jo@example.com\t",
        "ida@example.com\tIdaC",
        "",
    ])
    path = data / "pairs.tsv"
    path.write_text(pairs, encoding="utf-8")
    out = io.StringIO()
    with redirect_stdout(out):
        script.main([str(path)])
    assert names.pair_for("ida@example.com") is None and names.owed() == []  # a plan changes nothing
    verdicts = [line.split()[0:2] for line in out.getvalue().splitlines()[:6]]
    assert verdicts == [["takes", "gus1"], ["same", "Hal_H"], ["reserve", "IdaB"], ["takes", "(a"],
                        ["takes", "(a"], ["address", "named"]]

    posted = []
    names._post = lambda *call: posted.append(call) or True
    with redirect_stdout(io.StringIO()):
        script.main([str(path), "--apply"])
    assert names.pair_for("ida@example.com") == ("idab", False)
    assert names.pair_for("irene@example.com") == ("irene2", False)
    assert sorted(json.loads(body)["new"] for _, body, _ in posted) == ["gus1", "irene2", "jo01"]
    assert {json.loads(body)["old"] for _, body, _ in posted} == {"Gus", "irene", ""}
    assert names.owed() == []
