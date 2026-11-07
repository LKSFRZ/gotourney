import re
from pathlib import Path

import pytest

from gotourney import workflow
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


from gotourney import egd as egd_module

FAKE_EGD = [
    egd_module.EGDPlayer("34567890", "Mueller", "Andreas", "DE", "Mus", "1k", 2010, 25, "T260912A"),
    egd_module.EGDPlayer("45678901", "Mueller", "Sophie", "DE", "Bsp", "4k", 1720, 12, "T150501B"),
    egd_module.EGDPlayer("56789012", "Klein", "Tim", "AT", "Wien", "37k", -833, 6, "T250815C"),
]


def players_client(directory):
    app, c = client_for(directory)
    app.config["EGD"].index = egd_module.PlayerIndex(FAKE_EGD)
    app.config["EGD_FETCH"] = lambda pin: next(p for p in FAKE_EGD if p.pin == pin)
    return app, c


def test_egd_search_api(make_tournament):
    d = make_tournament([(2000,)], rounds=2)
    app, c = players_client(d)
    data = c.get("/api/egd/search?q=mueller").get_json()
    assert [r["first_name"] for r in data["results"]] == ["Andreas", "Sophie"]
    sophie = data["results"][1]
    assert sophie["outdated"] and sophie["outdated"] >= 10            # last tournament 2015
    assert c.get("/api/egd/search?q=klein").get_json()["results"][0]["rank"] == "29k"   # 37k is no rank -> from GoR
    assert c.get("/api/egd/pin/34567890").get_json()["gor"] == 2010


def test_register_edit_remove_players(make_tournament):
    from gotourney.players import load_players
    d = make_tournament([(2000,)], rounds=3)
    app, c = players_client(d)
    r = c.get("/players")
    assert r.status_code == 200 and "Search the EGD" in page(r) and "Fee paid" in page(r)
    r = post(c, app, "/players/save", surname="Mueller", first_name="Andreas", rank="1k", gor="2010",
             pin="34567890", country="DE", club="Mus", round_1="on", round_3="on", extra_0="yes",
             extra_1="U15", egd_gor="2010", egd_last_tournament="T260912A")
    assert "Added Mueller Andreas (ID 2)" in page(r)
    p = next(p for p in load_players(d, 3, ["Fee paid", "Age group"]).players if p.id == 2)
    assert (p.rounds, p.club, p.extra, p.egd_last_tournament) == ({1, 3}, "Mus", {"Fee paid": "yes", "Age group": "U15"},
                                                                  "T260912A")
    # the same PIN again is refused, and the form keeps what was typed
    r = post(c, app, "/players/save", surname="Mueller", first_name="Again", rank="1k", pin="34567890")
    assert r.status_code == 422 and "already registered" in page(r) and 'value="Again"' in page(r)
    # invalid dropdown value
    r = post(c, app, "/players/save", surname="Neu", rank="5k", extra_1="U12")
    assert r.status_code == 422 and "not allowed" in page(r)
    # edit
    assert 'value="Andreas"' in page(c.get("/players?edit=2"))
    r = post(c, app, "/players/save", id="2", surname="Mueller", first_name="Andreas", rank="1k", gor="1950",
             pin="34567890", round_2="on", joker="on")
    assert "Saved Mueller Andreas" in page(r)
    p = next(p for p in load_players(d, 3, ["Fee paid", "Age group"]).players if p.id == 2)
    assert (p.gor, p.rounds, p.joker, p.egd_last_tournament) == (1950, {2}, True, "T260912A")
    # remove
    r = post(c, app, "/players/2/remove")
    assert "Removed Mueller Andreas" in page(r)
    assert [p.id for p in load_players(d, 3).players] == [1]


def test_players_in_a_round_cannot_be_removed(make_tournament):
    d = make_tournament([(2000,), (1990,)], rounds=1)
    app, c = players_client(d)
    post(c, app, "/do/pair", round="1")
    r = post(c, app, "/players/1/remove")
    assert "cannot be removed" in page(r)


def test_players_page_refuses_while_open_in_libreoffice(make_tournament):
    d = make_tournament([(2000,)], rounds=1)
    app, c = players_client(d)
    (d / ".~lock.players.ods#").write_text("x")
    assert "players.ods is open in LibreOffice" in page(c.get("/players"))
    r = post(c, app, "/players/save", surname="Neu", rank="5k")
    assert r.status_code == 422 and "LibreOffice" in page(r)


def test_dashboard_links_to_players_page(make_tournament):
    d = make_tournament([(2000,), (1990,)], rounds=1)
    app, c = players_client(d)
    r = c.get("/dashboard")
    assert "Register players" in page(r) and 'href="/players"' in page(r)
    r = post(c, app, "/do/check_players", next="/players")
    assert r.request.path == "/players"


def test_pairing_tools_on_round_page(make_tournament):
    d = make_tournament([(2000,), (1990,), (1500,), (1490,)], rounds=1)
    app, c = client_for(d)
    post(c, app, "/do/pair", round="1")
    r = c.get("/round/1")
    assert "Pair again" in page(r) and "Pair two players by hand" in page(r) and "Start round 1" in page(r)
    r = post(c, app, "/round/1/manual", white="1", black="4", handicap="")
    assert "Fixed board" in page(r)
    t = Tournament.load(d)
    g = next(g for g in t.rounds[1].games if set(g.players()) == {1, 4})
    assert g.finalized
    r = post(c, app, "/round/1/board", board=str(g.board), what="swap")
    r = post(c, app, "/round/1/board", board=str(g.board), what="release")
    assert not next(x for x in Tournament.load(d).rounds[1].games if x.board == g.board).finalized
    r = post(c, app, "/round/1/board", board=str(g.board), what="dissolve")
    assert "dissolved" in page(r) and "Registered but not on a board" in page(r)
    post(c, app, "/do/pair", round="1", next="/round/1")
    assert len(Tournament.load(d).rounds[1].games) == 2
    post(c, app, "/do/start", round="1", next="/round/1")
    r = c.get("/round/1")
    assert "Pair again" not in page(r)                       # started: only results


def test_confirm_names_in_browser(make_tournament):
    from gotourney.ods import write_sheets
    from gotourney.rounds import COLUMNS
    d = make_tournament([(2000,), (1990,), (1500,), (1490,)], rounds=1)
    write_sheets(d / "round_1.ods", [("Pairing", COLUMNS, [[None, None, None, "P1", None, None, None, "P4",
                                                           None, None, None, None, ""]])])
    app, c = client_for(d)
    r = c.get("/dashboard")
    assert "Confirm players given by name" in page(r)
    r = c.get("/round/1")
    assert "Confirm and pair" in page(r) and "pick_0" in page(r) and "pick_1" in page(r)
    r = post(c, app, "/round/1/resolve", pick_0="1", pick_1="4")
    assert "Round 1 paired" in page(r)
    pairs = {frozenset(g.players()) for g in Tournament.load(d).rounds[1].games}
    assert frozenset({1, 4}) in pairs and len(pairs) == 2


def test_settings_page(make_tournament):
    from gotourney.config import load_config
    d = make_tournament([(2000,), (1990,)], rounds=3)
    app, c = client_for(d)
    r = c.get("/settings")
    assert r.status_code == 200 and "Pairing rules" in page(r) and "Award ceremony" in page(r)
    version = re.search(r'name="version" value="([^"]+)"', page(r)).group(1)
    form = {"version": version, "name": "Renamed Cup", "place": "DE, Sampletown", "date_first": "2026-04-18",
            "date_last": "2026-04-19", "class": "B", "time": "60", "rounds": "4", "comment": "",
            "language": "de", "translation_file": "translation.toml", "k_factor": "2.5", "top_bar": "2d",
            "reduction": "1", "floor": "15k", "komi_even": "7.0", "komi_handicap": "0.5", "random_seed": "7",
            "rule_field_0": "Club", "rule_type_0": "avoid_same", "rule_points_0": "100", "rule_groups_0": "",
            "rule_field_1000": "Age group", "rule_type_1000": "prefer_same", "rule_points_1000": "200",
            "rule_groups_1000": "U7, U11 | U15",
            "gor_outdated_years": "4", "rank_gor_tolerance": "250",
            "xf_name_0": "Fee paid", "xf_values_0": "yes, no", "xf_name_1": "Age group",
            "xf_values_1": "U7, U11, U15, U19", "xf_name_1000": "Email", "xf_values_1000": "",
            "title_slide": "on", "pz_type_0": "place", "pz_title_0": "{place}. Platz", "pz_places_0": "3, 2, 1"}
    r = post(c, app, "/settings", **form)
    assert "Settings saved" in page(r)
    cfg = load_config(d)
    assert (cfg.tournament.name, cfg.tournament.dates, cfg.tournament.klass, cfg.tournament.rounds) == \
        ("Renamed Cup", ["2026-04-18", "2026-04-19"], "B", 4)
    assert (cfg.output.language, cfg.rating.k_factor, cfg.rating.top_bar, cfg.handicap.reduction) == ("de", 2.5, 2200, 1)
    assert cfg.handicap.floor == 600
    assert 'name="floor" type="text" value="600"' in page(c.get("/settings"))
    assert [(x.field, x.type, x.points, x.groups) for x in cfg.pairing.rules] == \
        [("Club", "avoid_same", 100, []), ("Age group", "prefer_same", 200, [["U7", "U11"], ["U15"]])]
    assert cfg.registration.extra_fields == ["Fee paid", "Age group", "Email"]
    assert cfg.registration.values_for("Email") is None
    assert [(p.type, p.title, p.places) for p in cfg.awards.prizes] == [("place", "{place}. Platz", [3, 2, 1])]
    text = (d / "tournament.toml").read_text()
    assert "# EGD metadata, written to the .h9 header" in text          # comments kept
    # invalid input is not saved and explained
    r = post(c, app, "/settings", **{**form, "version": re.search(r'name="version" value="([^"]+)"',
                                                                    page(c.get("/settings"))).group(1),
                                     "komi_even": "5.5"})
    assert r.status_code == 422 and "komi_even" in page(r) and load_config(d).handicap.komi_even == 7.0
    # stale form: file changed meanwhile
    r = post(c, app, "/settings", **{**form, "version": "0-0"})
    assert r.status_code == 422 and "changed elsewhere" in page(r)


def test_extra_fields_follow_the_settings(make_tournament):
    from gotourney.ods import read_sheet
    d = make_tournament([(2000,), (1990,)], rounds=3)
    app, c = client_for(d)
    assert "Age group" in page(c.get("/players"))
    form = {"name": "Cup", "class": "A", "time": "60", "rounds": "3", "language": "en",
            "translation_file": "translation.toml", "k_factor": "3", "top_bar": "3d", "reduction": "0",
            "komi_even": "6.5", "komi_handicap": "0.5", "random_seed": "1", "gor_outdated_years": "5",
            "rank_gor_tolerance": "300", "rule_field_0": "Club", "rule_type_0": "avoid_same", "rule_points_0": "150",
            "xf_name_0": "Fee paid", "xf_values_0": "yes, no", "xf_name_1": "Shirt size", "xf_values_1": "S, M, L",
            "pz_type_0": "place", "pz_places_0": "3, 2, 1"}
    version = re.search(r'name="version" value="([^"]+)"', page(c.get("/settings"))).group(1)
    r = post(c, app, "/settings", version=version, **form)
    assert "Settings saved" in page(r)
    html = page(c.get("/players"))
    assert "Age group" not in html and "Shirt size" in html
    assert "Age group" not in page(c.get("/settings"))
    header = read_sheet(d / "players.ods").header           # the columns follow at once
    assert "Shirt size" in header and "Age group" not in header


def test_settings_cannot_reduce_rounds_below_paired(make_tournament):
    from gotourney.config import load_config
    d = make_tournament([(2000,), (1990,)], rounds=3)
    app, c = client_for(d)
    post(c, app, "/do/pair", round="1")
    from gotourney.settings import read_settings, save_settings
    cfg, v = read_settings(d)
    save_settings(d, {"tournament": {"rounds": 2}}, v)
    assert load_config(d).tournament.rounds == 2
    with pytest.raises(Exception, match="already paired"):
        import shutil
        shutil.copy(d / "round_1.ods", d / "round_2.ods")
        cfg, v = read_settings(d)
        save_settings(d, {"tournament": {"rounds": 1}}, v)


def test_documents_page(make_tournament):
    d = make_tournament([(2000,), (1990,), (1500,), (1490,)], rounds=1)
    app, c = client_for(d)
    r = c.get("/documents")
    assert r.status_code == 200 and "Starting list" in page(r) and "Needs at least one paired round" in page(r)
    post(c, app, "/do/pair", round="1")
    r = c.get("/documents")
    assert "Standings after round 1" in page(r) and "Needs all results" in page(r)
    assert "before_pairing_round_1" in page(r)                        # automatic backup
    finish(d, 1)
    r = c.get("/dashboard")
    assert "Standings &amp; documents" in page(r)
    for action, expect in [("standings", "standings.pdf"), ("wall", "wall_list.ods"), ("h9", ".h9"),
                           ("awards", "awards.pdf")]:
        r = post(c, app, f"/do/{action}", next="/documents")
        assert r.request.path == "/documents" and expect in page(r)
    r = c.get("/documents")
    assert "Content of the EGD file" in page(r) and "; TC[]" in page(r)
    assert "Prize winners" in page(r) and "1st place" in page(r)
    r = post(c, app, "/do/backup", next="/documents")
    assert "by_hand" in page(r)
    name = re.search(r'href="/backup/([^"]+by_hand[^"]*)"', page(r)).group(1)
    assert c.get(f"/backup/{name}").status_code == 200
    assert c.get("/backup/../players.ods").status_code == 404


def test_pdfs_are_created_when_opened(make_tournament):
    d = make_tournament([(2000,), (1990,), (1500,), (1490,)], rounds=1)
    app, c = client_for(d)
    post(c, app, "/do/pair", round="1")
    # standings were never created explicitly
    assert not (d / "standings.pdf").exists()
    r = c.get("/file/standings.pdf")
    assert r.status_code == 200 and r.data.startswith(b"%PDF")
    # award slides need all results: refused with an explanation instead of a stale file
    r = c.get("/file/awards.pdf", follow_redirects=True)
    assert "missing results" in page(r) and not (d / "awards.pdf").exists()
    finish(d, 1)
    r = c.get("/dashboard")
    assert "Standings (PDF)" in page(r) and 'action="/do/standings"' not in page(r)
    assert c.get("/file/awards.pdf").data.startswith(b"%PDF")
    # the pairing PDF reflects a change made after pairing
    import os, time
    before = (d / "round_1.pdf").stat().st_mtime_ns
    time.sleep(0.01)
    assert c.get("/file/round_1_alphabetical.pdf").status_code == 200
    assert (d / "round_1.pdf").stat().st_mtime_ns > before
    # the EGD file needs the wall list, then is made fresh from it
    r = c.get("/file/Test.h9", follow_redirects=True)
    assert "wall_list.ods" in page(r) or r.status_code in (200, 404)
    post(c, app, "/do/wall", next="/documents")
    r = c.get("/file/Test.h9")
    assert r.status_code == 200 and b"; TC[]" in r.data


# ---------------------------------------------------------------- packaging / launcher

def test_ping_and_launch(make_tournament):
    d = make_tournament([(2000,), (1990,)], rounds=1)
    app, c = client_for(None)
    assert c.get("/api/ping").get_json()["app"] == "gotourney"
    assert c.get(f"/launch/wrong?path={d}").status_code == 403
    r = c.get(f"/launch/{app.config['LAUNCH']}", query_string={"path": str(d)})
    assert r.status_code == 302 and r.headers["Location"].endswith("/dashboard")
    assert app.config["TOURNAMENT_DIR"] == d.resolve()
    r = c.get(f"/launch/{app.config['LAUNCH']}", query_string={"path": str(d / "nothing")}, follow_redirects=True)
    assert "tournament" in page(r).lower() and app.config["TOURNAMENT_DIR"] == d.resolve()


def test_home_lists_tournaments_in_the_default_folder(tmp_path, monkeypatch):
    from gotourney.web import find_tournaments
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / "Documents").mkdir()
    workflow.create_tournament(tmp_path / "Documents" / "Go tournaments" / "Spring Cup", "Spring Cup", 3, "en")
    workflow.create_tournament(tmp_path / "Documents" / "Go-Turniere" / "Herbstturnier", "Herbst", 3, "de")
    (tmp_path / "Documents" / "Go tournaments" / "not a tournament").mkdir()
    names = [Path(p).name for p in find_tournaments()]
    assert sorted(names) == ["Herbstturnier", "Spring Cup"]
    app, c = client_for(None)
    html = page(c.get("/"))
    assert "Spring Cup" in html and "Herbstturnier" in html


def test_real_server_and_second_start(tmp_path):
    import threading
    from gotourney.web import create_app, free_port, make_server, port_free, running_instance
    port = free_port()
    assert port_free(port) and not running_instance(port)
    server = make_server(create_app(None), port)
    threading.Thread(target=server.run, daemon=True).start()
    try:
        assert not port_free(port) and running_instance(port)
    finally:
        server.close()


def test_bundled_font_is_used():
    from gotourney.printing import find_fonts
    regular, bold, _ = find_fonts()
    assert regular.name == "DejaVuSans.ttf" and "gotourney" in str(regular.parent)


def test_help_opens_the_quick_start():
    app, c = client_for(None)
    r = c.get("/help")
    assert r.status_code == 200 and r.mimetype == "application/pdf"
    c.get("/lang/de")
    r = c.get("/help")
    assert r.status_code == 200 and "Schnellstart" in r.headers.get("Content-Disposition", "Schnellstart")


# ---------------------------------------------------------------- help pages

@pytest.mark.parametrize("language, words", [("en", ["The tournament system", "Pairing rules of this tournament"]),
                                             ("de", ["Das Turniersystem", "Auslosungsregeln dieses Turniers"])])
def test_system_page_uses_the_tournament_settings(make_tournament, language, words):
    from gotourney import settings as st
    d = make_tournament([(2000,), (1990,)], rounds=3)
    _, version = st.read_settings(d)
    st.save_settings(d, {"rating": {"k_factor": 2.5, "top_bar": "2d"}, "handicap": {"reduction": 1}}, version)
    app, c = client_for(d)
    c.get(f"/lang/{language}")
    html = page(c.get("/system"))
    for w in words:
        assert w in html
    assert "2.5" in html and "2200 (2d)" in html          # k-factor and top bar of this tournament
    assert "Club" in html and "150" in html               # the default club rule
    # without a tournament: the defaults
    app, c = client_for(None)
    html = page(c.get("/system"))
    assert "default settings" in html and "2300 (3d)" in html


def test_rating_api_matches_the_rating_module():
    from gotourney.rating import game_changes
    app, c = client_for(None)
    data = c.get("/api/rating?white=1850&black=1700&handicap=1&k=3").get_json()
    dw, db = game_changes(1850, 1700, 1, 1.0, 3)
    assert data["white"] == {"white": round(dw, 1), "black": round(db, 1)}
    assert 0.5 < data["expected_white"] < 1
    assert c.get("/api/rating?white=x&black=1").status_code == 400
    assert c.get("/api/rating?white=1000&black=1000&handicap=12").status_code == 400


def test_docs_page_and_navigation():
    app, c = client_for(None)
    html = page(c.get("/docs"))
    assert "Documentation" in html and 'href="/system"' in html and 'href="/docs"' in html
    assert "Pairing a round" in html
    c.get("/lang/de")
    assert "Eine Runde auslosen" in page(c.get("/docs"))


def test_system_page_explains_the_floor(make_tournament):
    from gotourney import settings as st
    d = make_tournament([(2000,), (1990,)], rounds=1)
    app, c = client_for(d)
    html = page(c.get("/system"))
    assert "Handicap floor" in html and "100 (20k)" in html and "FLOOR = 100.0" in html
    _, version = st.read_settings(d)
    st.save_settings(d, {"handicap": {"floor": "none"}}, version)
    html = page(c.get("/system"))
    assert "Handicap floor:" not in html and "FLOOR = null" in html


def test_tournament_name_is_the_headline(make_tournament):
    d = make_tournament([(2000,), (1990,)], rounds=1)
    app, c = client_for(d)
    for url in ("/dashboard", "/players", "/settings", "/system"):
        assert 'class="tournament-name" href="/dashboard" title="Test">Test</a>' in page(c.get(url)), url
    app, c = client_for(None)
    assert "tournament-name" not in page(c.get("/"))


def test_players_form_marks_unsaved_input_after_an_error(make_tournament):
    d = make_tournament([(2000,), (1990,)], rounds=1)
    app, c = client_for(d)
    html = page(c.get("/players"))
    assert 'data-unsaved="false"' in html and 'id="unsaved"' in html
    r = post(c, app, "/players/save", surname="Neu", rank="99x")      # invalid rank: form is shown again
    assert r.status_code == 422 and 'data-unsaved="true"' in page(r)


def test_overview_has_a_button_per_round(make_tournament):
    def button(html, r):
        m = re.search(r'<a class="button small ?(primary)?"\s+href="/round/%d">([^<]+)</a>' % r, html)
        return m and (m.group(2), bool(m.group(1)))
    d = make_tournament([(2000,), (1990,), (1500,), (1490,)], rounds=3)
    app, c = client_for(d)
    post(c, app, "/do/pair", round="1")
    assert button(page(c.get("/dashboard")), 1) == ("Show boards", False)      # paired, not started
    post(c, app, "/do/start", round="1")
    assert button(page(c.get("/dashboard")), 1) == ("Enter results", True)     # running: highlighted
    finish(d, 1)
    html = page(c.get("/dashboard"))
    assert button(html, 1) == ("Show results", False)
    assert button(html, 2) is None                                             # not paired: no button


# ---------------------------------------------------------------- the web interface explains itself

def test_web_texts_never_send_the_user_to_the_command_line_or_file_columns():
    from gotourney.web.texts import TEXTS
    for lang, texts in TEXTS.items():
        for key, value in texts.items():
            for bad in ("gotourney ", "terminal", "Finalized", "x under", "x unter", "x!", "(Joker column)"):
                assert bad not in value, (lang, key, bad)


def test_running_round_next_step_is_the_browser(make_tournament):
    d = make_tournament([(2000,), (1990,), (1500,), (1490,)], rounds=2)
    app, c = client_for(d)
    post(c, app, "/do/pair", round="1")
    post(c, app, "/do/start", round="1")
    html = page(c.get("/dashboard"))
    assert "Click &#39;Enter results&#39; and then the winner" in html
    card = html[html.index("Next step"):html.index("Rounds")]
    assert "Open round_1.ods" not in card and "round_1.ods" not in card.split("Pairing (by board)")[0]


def test_pairing_problems_are_explained_for_the_browser(make_tournament):
    d = make_tournament([(2000,), (1990,), (1500,)], rounds=1)        # odd, no joker
    app, c = client_for(d)
    html = page(post(c, app, "/do/pair", round="1"))
    message = re.search(r'<p class="msg error">([^<]*)</p>', html).group(1)
    assert "3 players are registered for it" in message and "tick &#39;Joker&#39;" in message
    assert "players.ods" not in message


# ---------------------------------------------------------------- editing must not replace a player by somebody else

def test_saving_another_person_over_a_registered_player_is_refused(make_tournament):
    from gotourney.players import load_players
    d = make_tournament([(2000,), (1990,)], rounds=1)
    workflow.save_player(d, workflow.PlayerData(surname="Binder", first_name="Em", rank="16k", pin="20750807",
                                                rounds={1}), 2)
    data = workflow.PlayerData(surname="Becker", first_name="Heiko", rank="6k", pin="14001482", rounds={1})
    with pytest.raises(workflow.Problem) as e:                      # other PIN and other surname
        workflow.save_player(d, data, 2)
    assert e.value.code == "replaces_player"
    # correcting the spelling, or the PIN of the same person, still works
    workflow.save_player(d, workflow.PlayerData(surname="Binder", first_name="Emma", rank="16k", pin="20750808",
                                                rounds={1}), 2)
    # the web page explains it and offers the data as a new player
    app, c = client_for(d)
    r = post(c, app, "/players/save", id="2", surname="Becker", first_name="Heiko", rank="6k", pin="14001482",
             round_1="on")
    html = page(r)
    assert r.status_code == 422 and "Not saved: this would replace Binder Emma (ID 2) by Becker Heiko" in html
    assert 'name="id" value=""' in html and "Add player" in html
    names = [p.name for p in load_players(d, 1, ["Fee paid", "Age group"]).players]
    assert "Binder Emma" in names and "Becker Heiko" not in names


def test_players_page_tells_the_script_who_is_being_edited(make_tournament):
    d = make_tournament([(2000,), (1990,)], rounds=1)
    workflow.save_player(d, workflow.PlayerData(surname="Binder", first_name="Em", rank="16k", pin="20750807",
                                                rounds={1}), 2)
    app, c = client_for(d)
    html = page(c.get("/players?edit=2"))
    assert 'data-edit-name="Binder Em"' in html and 'data-edit-pin="20750807"' in html
    assert 'data-edit-name=""' in page(c.get("/players"))           # new player: nothing to protect
