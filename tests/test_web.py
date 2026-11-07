import re

import pytest

from gotourney.models import Result
from gotourney.rounds import player_label, read_not_playing, save_round
from gotourney.tournament import Tournament
from gotourney.web import create_app


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "config"))


def client_for(directory=None):
    app = create_app(directory)
    app.config["OPENED"] = []
    app.config["OPENER"] = lambda path: app.config["OPENED"].append(path.name)
    app.config["REGISTRATION"] = lambda d: app.config["OPENED"].append("registration")
    c = app.test_client()
    c.environ_base["HTTP_HOST"] = "127.0.0.1:8765"
    return app, c


def post(c, app, url, **data):
    return c.post(url, data={"csrf": app.config["CSRF"], **data}, follow_redirects=True)


def finish(d, r):
    t = Tournament.load(d)
    rg = t.rounds[r]
    for g in rg.games:
        g.result = Result.WHITE_WINS
    save_round(rg.path, rg.games, {p: player_label(t.players[p]) for p in t.players}, t.rating_before(r),
               read_not_playing(rg.path))


def page(resp) -> str:
    return resp.get_data(as_text=True)


def test_home_and_create(tmp_path):
    app, c = client_for()
    r = c.get("/")
    assert r.status_code == 200 and "New tournament" in page(r)
    r = post(c, app, "/create", name="Spring Cup", rounds="3", language="de", folder=str(tmp_path))
    assert "Tournament created" in page(r)
    assert (tmp_path / "Spring Cup" / "tournament.toml").exists()
    assert "Register the players" in page(r)
    assert "Spring Cup" in page(c.get("/?choose=1"))           # remembered as recent


def test_open_wrong_folder(tmp_path):
    app, c = client_for()
    r = post(c, app, "/open", path=str(tmp_path))
    assert "is not a tournament folder" in page(r)


def test_whole_tournament_through_the_dashboard(make_tournament):
    d = make_tournament([(2000,), (1990,), (1500,), (1490,)], rounds=2)
    app, c = client_for(d)
    r = c.get("/dashboard")
    assert "Registration" in page(r) and "Pair round 1" in page(r)
    r = post(c, app, "/do/pair", round="1")
    assert "Round 1 paired: 2 boards." in page(r)
    assert "Round 1 is paired" in page(r) and "Start round 1" in page(r)
    r = post(c, app, "/do/start", round="1")
    assert "Round 1 started" in page(r) and "Round 1 is running" in page(r)
    assert "0 of 2 results entered" in page(r)
    r = post(c, app, "/do/open_file", name="round_1.ods")
    assert app.config["OPENED"] == ["round_1.ods"] and "was opened" in page(r)
    r = post(c, app, "/do/check_results", round="1")
    assert "2 of 2 results are missing" in page(r)
    finish(d, 1)
    r = c.get("/dashboard")
    assert "Round 1 is complete" in page(r) and "Pair round 2" in page(r)
    r = post(c, app, "/do/standings")
    assert "Created standings.pdf" in page(r)
    post(c, app, "/do/pair", round="2")
    finish(d, 2)
    r = c.get("/dashboard")
    assert "The tournament is finished" in page(r)
    for action, name in [("wall", "wall_list.ods"), ("h9", ".h9"), ("awards", "awards.pdf")]:
        r = post(c, app, f"/do/{action}")
        assert "Created" in page(r) and name in page(r)


def test_problems_are_explained(make_tournament):
    d = make_tournament([(2000,), (1990,), (1500,), (1490,)], rounds=3)
    app, c = client_for(d)
    post(c, app, "/do/pair", round="1")
    r = post(c, app, "/do/pair", round="2")
    assert "cannot be paired yet" in page(r) and "Board 1:" in page(r)
    (d / ".~lock.round_1.ods#").write_text("x")
    r = post(c, app, "/do/pair", round="1")
    assert "is open in LibreOffice" in page(r)


def test_german_interface(make_tournament):
    d = make_tournament([(2000,), (1990,)], rounds=1)
    app, c = client_for(d)
    c.get("/lang/de")
    r = c.get("/dashboard")
    assert "Nächster Schritt" in page(r) and "Runde 1 auslosen" in page(r)
    r = c.get("/dashboard", headers={"Accept-Language": "de"})
    assert "Anmeldung" in page(r)


def test_registration_window_and_players_check(make_tournament):
    d = make_tournament([(2000,), (1990,), (1980,)], rounds=1)
    app, c = client_for(d)
    r = post(c, app, "/do/registration")
    assert app.config["OPENED"] == ["registration"]
    r = post(c, app, "/do/check_players")
    assert "error(s)" in page(r) and "joker" in page(r)


def test_security(make_tournament):
    d = make_tournament([(2000,), (1990,)], rounds=1)
    app, c = client_for(d)
    assert c.post("/do/pair", data={"round": "1"}).status_code == 403              # no CSRF token
    assert c.get("/dashboard", headers={"Host": "evil.example:8765"}).status_code == 403
    assert c.get("/file/../tournament.toml").status_code == 404
    assert c.get("/file/players.ods").status_code == 200
    assert c.get("/file/notes.txt").status_code == 404


def test_version_changes_when_files_change(make_tournament):
    d = make_tournament([(2000,), (1990,)], rounds=1)
    app, c = client_for(d)
    v1 = c.get("/api/version").get_json()["v"]
    (d / "players.ods").touch()
    import os, time
    os.utime(d / "players.ods", (time.time() + 5, time.time() + 5))
    assert c.get("/api/version").get_json()["v"] != v1


def test_results_page(make_tournament):
    d = make_tournament([(2000,), (1990,), (1500,), (1490,)], rounds=2)
    app, c = client_for(d)
    post(c, app, "/do/pair", round="1")
    r = c.get("/round/1")
    assert r.status_code == 200 and "0 of 2 results entered" in page(r) and "White wins" in page(r)
    # click without JavaScript: form post + redirect
    r = post(c, app, "/round/1/result", board="1", result="white")
    assert "1 of 2 results entered" in page(r)
    t = Tournament.load(d)
    g1 = next(g for g in t.rounds[1].games if g.board == 1)
    assert g1.result is Result.WHITE_WINS and g1.finalized          # board fixed by the result
    # click with JavaScript: JSON with the new row
    r = c.post("/round/1/result", data={"csrf": app.config["CSRF"], "board": "2", "result": "both_forfeit"},
               headers={"X-Requested-With": "fetch"})
    data = r.get_json()
    assert data["ok"] and data["summary"] == {"done": 2, "boards": 2, "missing": 0, "percent": 100}
    assert 'id="board-2"' in data["row"] and "Both lose" in data["row"]
    assert Tournament.load(d).rounds[1].complete
    # clearing a result
    r = c.post("/round/1/result", data={"csrf": app.config["CSRF"], "board": "2", "result": ""},
               headers={"X-Requested-With": "fetch"})
    assert r.get_json()["summary"]["missing"] == 1
    # dashboard links to the page
    assert "/round/1" in page(c.get("/dashboard"))


def test_results_page_refuses_while_open_in_libreoffice(make_tournament):
    d = make_tournament([(2000,), (1990,)], rounds=1)
    app, c = client_for(d)
    post(c, app, "/do/pair", round="1")
    (d / ".~lock.round_1.ods#").write_text("x")
    assert "is open in LibreOffice" in page(c.get("/round/1"))
    r = c.post("/round/1/result", data={"csrf": app.config["CSRF"], "board": "1", "result": "white"},
               headers={"X-Requested-With": "fetch"})
    assert r.status_code == 409 and "LibreOffice" in r.get_json()["message"]
    assert Tournament.load(d).rounds[1].games[0].result is None


def test_bad_result_values(make_tournament):
    d = make_tournament([(2000,), (1990,)], rounds=1)
    app, c = client_for(d)
    post(c, app, "/do/pair", round="1")
    r = c.post("/round/1/result", data={"csrf": app.config["CSRF"], "board": "1", "result": "draw!!"},
               headers={"X-Requested-With": "fetch"})
    assert r.status_code == 409
    r = c.post("/round/1/result", data={"csrf": app.config["CSRF"], "board": "9", "result": "white"},
               headers={"X-Requested-With": "fetch"})
    assert r.status_code == 409 and "no board 9" in r.get_json()["message"]
