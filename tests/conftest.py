import re

import pytest

from gotourney.config import write_template
from gotourney.models import Player
from gotourney.players import save_players
from gotourney.rank import Rank

DEFAULT_CLUB_RULE = '[[pairing.rules]]\nfield  = "Club"\ntype   = "avoid_same"\npoints = 150\n'


@pytest.fixture
def make_tournament(tmp_path):
    """Create a tournament folder with players given as (gor, club, joker, rounds, extra) tuples.

    Keyword arguments replace "key = value" lines of the settings template. ``rules`` (TOML text)
    replaces the default club rule.
    """
    def make(players, rounds=3, rules=None, **settings):
        write_template(tmp_path, "Test", rounds)
        toml = tmp_path / "tournament.toml"
        text = toml.read_text(encoding="utf-8")
        for key, value in settings.items():
            text = re.sub(rf"^{key}\s*=.*$", f"{key} = {value}", text, flags=re.M)
        if rules is not None:
            assert DEFAULT_CLUB_RULE in text
            text = text.replace(DEFAULT_CLUB_RULE, "") + "\n" + rules
        toml.write_text(text, encoding="utf-8")
        ps = []
        for i, spec in enumerate(players, start=1):
            gor, club, joker, rs, extra = (list(spec) + [None] * 5)[:5]
            ps.append(Player(i, f"P{i}", "X", Rank.from_gor(gor), float(gor), club=club or "",
                             joker=bool(joker), rounds=set(rs) if rs else set(range(1, rounds + 1)),
                             extra=dict(extra or {})))
        save_players(tmp_path, ps, rounds, ["Fee paid", "Age group"])
        return tmp_path
    return make
