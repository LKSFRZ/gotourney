"""The state of a tournament, computed from players.ods and all round files."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .config import Config, load_config
from .models import Game, Player
from .ods import OdsError
from .players import load_players, starting_rating
from .rating import RatedGame, rate_round
from .rounds import RoundGames, load_round, round_file


class TournamentError(Exception):
    pass


@dataclass
class PlayedGame:
    """One game from the point of view of one player."""

    round: int
    board: int
    opponent: int
    colour: str               # "w" or "b"
    handicap: int
    score: float | None       # 1, 0.5, 0; None = forfeit or no result yet
    forfeit: bool
    has_result: bool

    @property
    def counts_as_played(self) -> bool:
        """Was the game actually played (and rated)?"""
        return self.has_result and not self.forfeit


@dataclass
class Tournament:
    directory: Path
    cfg: Config
    players: dict[int, Player]
    rounds: dict[int, RoundGames]
    start: dict[int, float]                         # starting TGoR (GoR capped at the top bar)
    ratings: list[dict[int, float]]                 # ratings[r] = TGoR after round r (ratings[0] = start)
    start_gor: dict[int, float] = field(default_factory=dict)   # real starting GoR (not capped)
    extra_fields: list[str] = field(default_factory=list)       # additional player data fields
    history: dict[int, list[PlayedGame]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    # ------------------------------------------------------------ loading

    @classmethod
    def load(cls, directory: Path, cfg: Config | None = None,
             names_allowed_in_round: int | None = None) -> "Tournament":
        """Load the tournament. Boards with names instead of IDs are only allowed in the round
        given by ``names_allowed_in_round`` (the round being paired); elsewhere they are an error."""
        directory = Path(directory)
        cfg = cfg or load_config(directory)
        pl = load_players(directory, cfg.tournament.rounds, cfg.registration.extra_fields)
        players = {p.id: p for p in pl.players}
        warnings = list(pl.warnings)
        errors = []
        start_gor = {}
        for p in players.values():
            try:
                start_gor[p.id] = starting_rating(p)
            except ValueError as e:
                errors.append(str(e))
        bar = cfg.rating.top_bar
        start = {pid: (min(g, bar) if bar is not None else g) for pid, g in start_gor.items()}
        rounds: dict[int, RoundGames] = {}
        for r in range(1, cfg.tournament.rounds + 1):
            if not round_file(directory, r).exists():
                continue
            try:
                rounds[r] = load_round(directory, r, cfg.handicap.komi_even)
            except OdsError as e:
                errors.append(str(e))
        for r, rg in rounds.items():
            if rg.unresolved and r != names_allowed_in_round:
                rows = ", ".join(str(u.line) for u in rg.unresolved)
                errors.append(f"{rg.path.name}, row(s) {rows}: players given by name, not ID. "
                              f"Run 'gotourney pair {r}' to look them up.")
            for g in rg.games:
                for pid in g.players():
                    if pid not in players:
                        errors.append(f"{rg.path.name}, board {g.board}: unknown player ID {pid}")
        if errors:
            raise TournamentError("\n".join(errors))
        existing = sorted(rounds)
        if existing and existing != list(range(1, existing[-1] + 1)):
            missing = sorted(set(range(1, existing[-1] + 1)) - set(existing))
            raise TournamentError(f"round file(s) missing for round(s) {', '.join(map(str, missing))}")
        t = cls(directory, cfg, players, rounds, start, [dict(start)], start_gor=start_gor,
                extra_fields=pl.extra_fields, warnings=warnings)
        t._compute()
        return t

    def _compute(self) -> None:
        self.history = {pid: [] for pid in self.players}
        ratings = dict(self.start)
        for r in sorted(self.rounds):
            rg = self.rounds[r]
            rated = []
            missing = 0
            for g in rg.games:
                for pid in g.players():
                    if not self.players[pid].plays(r):
                        self.warnings.append(f"round {r}, board {g.board}: {self.name(pid)} is not "
                                             f"registered for round {r}")
                self._add_history(r, g)
                if g.result is None:
                    missing += 1
                elif g.result.white_score is not None:
                    rated.append(RatedGame(g.white, g.black, g.handicap, g.result.white_score))
            if missing:
                self.warnings.append(f"round {r}: {missing} result(s) missing")
            ratings = rate_round(ratings, rated, self.cfg.rating.k_factor)
            self.ratings.append(dict(ratings))

    def _add_history(self, r: int, g: Game) -> None:
        has = g.result is not None
        forfeit = has and g.result.is_forfeit
        ws = g.result.white_score if has else None      # None for forfeits
        self.history[g.white].append(PlayedGame(
            r, g.board, g.black, "w", g.handicap, ws, forfeit, has))
        self.history[g.black].append(PlayedGame(
            r, g.board, g.white, "b", g.handicap, None if ws is None else 1.0 - ws, forfeit, has))

    # ------------------------------------------------------------ queries

    def name(self, pid: int) -> str:
        p = self.players.get(pid)
        return f"{p.name} (ID {pid})" if p else f"ID {pid}"

    @property
    def last_round(self) -> int:
        return max(self.rounds, default=0)

    def rating_before(self, r: int) -> dict[int, float]:
        """TGoR before round r (= after round r-1)."""
        if r - 1 >= len(self.ratings):
            raise TournamentError(f"round {r - 1} has not been played yet")
        return self.ratings[r - 1]

    def final_ratings(self) -> dict[int, float]:
        return self.ratings[-1]

    def played_pairs(self, before_round: int | None = None) -> set[frozenset[int]]:
        """Pairs that already met (forfeits included)."""
        pairs = set()
        for r, rg in self.rounds.items():
            if before_round is not None and r >= before_round:
                continue
            for g in rg.games:
                pairs.add(frozenset(g.players()))
        return pairs

    def colour_balance(self, pid: int, before_round: int) -> int:
        """Whites minus blacks in even games actually played before the given round."""
        return sum((1 if h.colour == "w" else -1) for h in self.history[pid]
                   if h.round < before_round and h.handicap == 0 and h.counts_as_played)

    def games_played(self, pid: int, before_round: int) -> int:
        return sum(1 for h in self.history[pid] if h.round < before_round and h.counts_as_played)

    def wins(self, pid: int) -> float:
        return sum(h.score for h in self.history[pid] if h.counts_as_played and h.score is not None)
