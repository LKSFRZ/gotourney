import pytest

from gotourney.config import write_template
from gotourney.models import Player
from gotourney.players import save_players
from gotourney.rank import Rank


@pytest.fixture
def make_tournament(tmp_path):
    """Create a tournament folder with players given as (gor, club, joker, rounds) tuples."""
    def make(players, rounds=3, **settings):
        write_template(tmp_path, "Test", rounds)
        toml = tmp_path / "tournament.toml"
        text = toml.read_text()
        for key, value in settings.items():
            import re
            text = re.sub(rf"^{key}\s*=.*$", f"{key} = {value}", text, flags=re.M)
        toml.write_text(text)
        ps = []
        for i, spec in enumerate(players, start=1):
            gor, club, joker, rs = (list(spec) + [None, None, None])[:4]
            ps.append(Player(i, f"P{i}", "X", Rank.from_gor(gor), float(gor), club=club or "",
                             joker=bool(joker), rounds=set(rs) if rs else set(range(1, rounds + 1))))
        save_players(tmp_path, ps, rounds)
        return tmp_path
    return make
