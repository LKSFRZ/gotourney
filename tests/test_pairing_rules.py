import pytest
from typer.testing import CliRunner

from gotourney.cli import app
from gotourney.config import ConfigError, PairingRule, parse_config
from gotourney.pairing import PairingError, pair_round, rule_applies
from gotourney.players import load_players
from gotourney.registration import check_players
from gotourney.tournament import Tournament

runner = CliRunner()


def pairs(result):
    return {frozenset(g.players()) for g in result.games}


# ---------------------------------------------------------------- settings

def test_default_rules_and_fields(tmp_path):
    from gotourney.config import load_config, write_template
    cfg = parse_config({})
    assert [(r.field, r.type, r.points) for r in cfg.pairing.rules] == [("Club", "avoid_same", 150)]
    assert cfg.registration.extra_fields == []          # only what tournament.toml lists
    write_template(tmp_path, "Test")                    # a new tournament lists the two default fields
    cfg = load_config(tmp_path)
    assert cfg.registration.extra_fields == ["Fee paid", "Age group"]
    assert cfg.registration.values_for("fee PAID") == ["yes", "no"]
    assert cfg.registration.values_for("Age group") == ["U7", "U11", "U15", "U19", "Ü50"]


def test_old_club_penalty_still_works():
    assert parse_config({"pairing": {"club_penalty": 80}}).pairing.rules[0].points == 80


def test_no_rules_at_all():
    assert parse_config({"pairing": {"rules": []}}).pairing.rules == []


@pytest.mark.parametrize("pairing, msg", [
    ({"club_penalty": 100, "rules": []}, "cannot be combined"),
    ({"rules": [{"field": "Club", "type": "avoid"}]}, "type must be"),
    ({"rules": [{"field": "Club", "type": "prefer_same"}]}, "needs 'points'"),
    ({"rules": [{"field": "Club", "type": "avoid_same", "points": -1}]}, "negative"),
    ({"rules": [{"field": "GoR", "type": "forbid_same"}]}, "cannot be used"),
    ({"rules": [{"type": "forbid_same"}]}, "'field' is missing"),
    ({"rules": [{"field": "Club", "type": "forbid_same", "weight": 3}]}, "unknown key"),
])
def test_invalid_rules(pairing, msg):
    with pytest.raises(ConfigError, match=msg):
        parse_config({"pairing": pairing})


def test_rule_field_names_are_case_insensitive_for_builtins():
    cfg = parse_config({"pairing": {"rules": [{"field": "club", "type": "forbid_same"}]}})
    assert cfg.pairing.rules[0].field == "Club"


def test_field_values_must_belong_to_extra_fields():
    with pytest.raises(ConfigError, match="not in registration.extra_fields"):
        parse_config({"registration": {"extra_fields": ["Email"], "field_values": {"Size": ["S", "M"]}}})
    cfg = parse_config({"registration": {"extra_fields": ["Email"]}})
    assert cfg.registration.field_values == {} and cfg.registration.values_for("Email") is None


# ---------------------------------------------------------------- rule semantics

@pytest.mark.parametrize("type_, values, a, b, applies", [
    ("avoid_same", [], "HH", "hh", True),
    ("avoid_same", [], "HH", "B", False),
    ("avoid_same", [], "", "", False),            # no club is not "the same club"
    ("avoid_same", ["HH"], "B", "B", False),
    ("prefer_same", [], "U11", "U15", True),
    ("prefer_same", [], "", "", False),           # two adults (empty) count as the same
    ("prefer_same", [], "U11", "", True),
    ("prefer_same", ["U11"], "U19", "", False),   # rule only for U11
    ("prefer_same", ["U11"], "U11", "", True),
    ("prefer_same", ["U7", "U11", "U15"], "U11", "U15", False),   # children among themselves
    ("prefer_same", ["U7", "U11", "U15"], "U15", "", True),       # child vs adult
    ("prefer_same", ["U7", "U11", "U15"], "Ü50", "", False),      # adults among themselves
    ("avoid_same", ["HH", "HHA"], "HH", "hha", True),             # one group counts as the same
    ("avoid_same", ["HH"], "B", "B", False),
    ("forbid_same", [], "Smith", "smith", True),
    ("require_same", [], "A", "B", True),
])
def test_rule_applies(type_, values, a, b, applies):
    assert rule_applies(PairingRule("F", type_, 100, values), a, b) is applies


# ---------------------------------------------------------------- pairing

CHILDREN = [(2000, None, None, None, {}), (1990, None, None, None, {"Age group": "U11"}),
            (1980, None, None, None, {}), (1970, None, None, None, {"Age group": "U11"})]


def test_prefer_same_pairs_children_together(make_tournament):
    assert pairs(pair_round(Tournament.load(make_tournament(CHILDREN)), 1)) == \
        {frozenset({1, 2}), frozenset({3, 4})}
    d = make_tournament(CHILDREN, rules='[[pairing.rules]]\nfield = "Age group"\ntype = "prefer_same"\n'
                                        'points = 200\nvalues = ["U7", "U11"]\n')
    result = pair_round(Tournament.load(d), 1)
    assert pairs(result) == {frozenset({1, 3}), frozenset({2, 4})}
    assert sum(result.rule_hits.values()) == 0


def test_forbid_same(make_tournament):
    players = [(2000, None, None, None, {"Age group": "U11"}), (1990, None, None, None, {"Age group": "U11"}),
               (1500, None, None, None, {}), (1490, None, None, None, {})]
    d = make_tournament(players, rules='[[pairing.rules]]\nfield = "Age group"\ntype = "forbid_same"\n')
    assert frozenset({1, 2}) not in pairs(pair_round(Tournament.load(d), 1))


def test_require_same_impossible(make_tournament):
    players = [(2000, "HH"), (1990, "B")]
    d = make_tournament(players, rounds=1, rules='[[pairing.rules]]\nfield = "Club"\ntype = "require_same"\n')
    with pytest.raises(PairingError, match="forbidden pairs"):
        pair_round(Tournament.load(d), 1)


def test_rule_on_unknown_field(make_tournament):
    d = make_tournament([(2000,), (1990,)], rounds=1,
                        rules='[[pairing.rules]]\nfield = "Family"\ntype = "forbid_same"\n')
    with pytest.raises(PairingError, match="no column 'Family'"):
        pair_round(Tournament.load(d), 1)


def test_cli_pair_reports_rule_hits(make_tournament):
    d = make_tournament([(2000, "HH"), (1990, "HH")], rounds=1)
    r = runner.invoke(app, ["pair", "1", "-d", str(d)])
    assert r.exit_code == 0, r.output
    assert "Rule Club: avoid same (150 points): applies to 1 board" in r.output


# ---------------------------------------------------------------- dropdown values

def test_cli_dropdown_values(tmp_path):
    d = str(tmp_path)
    runner.invoke(app, ["init", d, "--rounds", "1"])
    r = runner.invoke(app, ["players", "add", "Doe", "Jo", "-r", "20k", "-x", "age group=u11",
                            "-x", "Fee paid=YES", "-d", d])
    assert r.exit_code == 0, r.output
    p = load_players(tmp_path, 1, ["Fee paid", "Age group"]).players[0]
    assert p.extra == {"Age group": "U11", "Fee paid": "yes"}
    r = runner.invoke(app, ["players", "add", "Roe", "Jo", "-r", "20k", "-x", "Age group=U12", "-d", d])
    assert r.exit_code == 1 and "choose one of" in r.output


def test_check_warns_about_values_not_in_list(make_tournament):
    d = make_tournament([(2000, None, None, None, {"Age group": "U12"}), (1990,)], rounds=1)
    t = Tournament.load(d)
    warnings = [i.message for i in check_players(list(t.players.values()), t.cfg) if i.level == "warning"]
    assert any("Age group 'U12' is not one of" in w for w in warnings)


@pytest.mark.parametrize("groups, a, b, applies", [
    ([["U7", "U11"], ["U15", "U19"]], "U7", "U11", False),
    ([["U7", "U11"], ["U15", "U19"]], "U11", "U15", True),
    ([["U7", "U11"], ["U15", "U19"]], "U19", "", True),
    ([["U7", "U11"], ["U15", "U19"]], "Ü50", "", False),
])
def test_prefer_same_with_groups(groups, a, b, applies):
    assert rule_applies(PairingRule("Age group", "prefer_same", 200, [], groups), a, b) is applies


@pytest.mark.parametrize("rule, msg", [
    ({"values": ["U7"], "groups": [["U11"]]}, "not both"),
    ({"groups": [["U7", "U11"], ["U11"]]}, "more than one group"),
    ({"groups": ["U7", "U11"]}, "list of lists"),
    ({"groups": [[]]}, "empty group"),
])
def test_invalid_groups(rule, msg):
    with pytest.raises(ConfigError, match=msg):
        parse_config({"pairing": {"rules": [dict(field="Age group", type="prefer_same", points=100, **rule)]}})


def test_groups_in_template_describe():
    rule = PairingRule("Age group", "prefer_same", 200, [], [["U7", "U11"], ["U15"]])
    assert rule.describe() == "Age group: prefer same (200 points) for {U7, U11} / {U15}"


def test_children_of_different_age_groups_play_each_other(make_tournament):
    # an U11 and an U15 child between two adults: with one children's group they play each other
    players = [(2000, None, None, None, {}), (1990, None, None, None, {"Age group": "U11"}),
               (1900, None, None, None, {"Age group": "U15"}), (1890, None, None, None, {})]
    rule = '[[pairing.rules]]\nfield = "Age group"\ntype = "prefer_same"\npoints = 200\n'
    d = make_tournament(players, rounds=1, rules=rule + 'values = ["U7", "U11", "U15"]\n')
    assert pairs(pair_round(Tournament.load(d), 1)) == {frozenset({2, 3}), frozenset({1, 4})}
    # with separate groups for U11 and U15 they count as different, so rating decides again
    d = make_tournament(players, rounds=1, rules=rule + 'groups = [["U7", "U11"], ["U15", "U19"]]\n')
    assert pairs(pair_round(Tournament.load(d), 1)) == {frozenset({1, 2}), frozenset({3, 4})}
