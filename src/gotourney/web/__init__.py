"""Local web interface: ``gotourney web`` opens it in the browser.

Runs only on this computer (127.0.0.1). The tournament files stay the only record: every page reads
them fresh, every action writes them, and LibreOffice can be used for the same files at any time.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import threading
from pathlib import Path

from flask import (Flask, abort, flash, jsonify, redirect, render_template, request, send_from_directory,
                   url_for)

from .. import __version__, egd, workflow
from ..config import CONFIG_FILE
from ..summary import SUMMARY_FILE
from .texts import LANGUAGES, text

DOWNLOADABLE = {".pdf", ".ods", ".h9", ".toml", ".csv"}


# ---------------------------------------------------------------- recent tournaments / folders

def config_dir() -> Path:
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "gotourney"


def load_recent() -> list[str]:
    try:
        data = json.loads((config_dir() / "recent.json").read_text(encoding="utf-8"))
        return [p for p in data if (Path(p) / CONFIG_FILE).exists()][:10]
    except (OSError, ValueError):
        return []


def remember(path: Path) -> None:
    recent = [str(path)] + [p for p in load_recent() if p != str(path)]
    try:
        config_dir().mkdir(parents=True, exist_ok=True)
        (config_dir() / "recent.json").write_text(json.dumps(recent[:10], indent=1), encoding="utf-8")
    except OSError:
        pass


def default_folder(lang: str) -> Path:
    docs = Path.home() / "Documents"
    return (docs if docs.is_dir() else Path.home()) / ("Go-Turniere" if lang == "de" else "Go tournaments")


def find_tournaments() -> list[str]:
    """Recently opened tournaments, then the other ones in the default folders (newest first)."""
    found = []
    for base in {default_folder("en"), default_folder("de")}:
        try:
            found += [c for c in base.iterdir() if (c / CONFIG_FILE).is_file()]
        except OSError:
            continue

    def changed(path: Path) -> float:
        try:
            return (path / CONFIG_FILE).stat().st_mtime
        except OSError:
            return 0.0
    recent = load_recent()
    known = {os.path.normcase(str(Path(p).resolve())) for p in recent}
    others = [str(c.resolve()) for c in sorted(found, key=changed, reverse=True)
              if os.path.normcase(str(c.resolve())) not in known]
    return recent + others


def open_with_system(path: Path) -> None:
    """Open a file with its usual program (e.g. LibreOffice for .ods)."""
    if sys.platform.startswith("win"):
        os.startfile(str(path))                     # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def start_registration_window(directory: Path) -> None:
    env = dict(os.environ, GOTOURNEY_NO_HINTS="1")
    # the packaged program runs the command line itself when it gets arguments (see app.py)
    command = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, "-m", "gotourney"]
    subprocess.Popen(command + ["gui", "--classic", "-d", str(directory)], env=env)


class EgdIndex:
    """The EGD player list, loaded once in the background and kept in memory."""

    def __init__(self):
        self.index: egd.PlayerIndex | None = None
        self.error = ""
        self.loading = False
        self._lock = threading.Lock()

    def ensure(self, refresh: bool | None = None) -> None:
        with self._lock:
            if self.loading or (self.index is not None and not refresh):
                return
            self.loading, self.error = True, ""
        threading.Thread(target=self._load, args=(refresh,), daemon=True).start()

    def _load(self, refresh) -> None:
        try:
            self.index = egd.PlayerIndex.load(refresh=refresh)
        except Exception as e:                    # noqa: BLE001 - shown to the user
            self.error = str(e)
        finally:
            self.loading = False

    def status(self) -> dict:
        age = egd.list_age()
        date = (dt.datetime.fromtimestamp(egd.list_path().stat().st_mtime).strftime("%Y-%m-%d")
                if age is not None and egd.list_path().exists() else "")
        return {"loaded": self.index is not None, "loading": self.loading, "error": self.error,
                "players": len(self.index.players) if self.index else 0, "date": date}


def rank_text(p: "egd.EGDPlayer") -> str:
    from ..rank import Rank, RankError
    try:
        return str(Rank.parse(p.grade))
    except RankError:
        return str(Rank.from_gor(p.gor))


def folder_version(directory: Path) -> str:
    """Changes whenever a file in the tournament folder changes (for reloading open pages)."""
    h = hashlib.sha1()
    try:
        for p in sorted(Path(directory).iterdir()):
            if p.is_file():
                st = p.stat()
                h.update(f"{p.name}|{st.st_mtime_ns}|{st.st_size}".encode())
    except OSError:
        pass
    return h.hexdigest()


# ---------------------------------------------------------------- the app

def create_app(directory: Path | None = None) -> Flask:
    app = Flask(__name__)
    app.secret_key = secrets.token_hex(32)
    app.config["TOURNAMENT_DIR"] = Path(directory).resolve() if directory else None
    app.config["CSRF"] = secrets.token_urlsafe(24)
    app.config["LAUNCH"] = secrets.token_urlsafe(24)       # lets the launcher window open a folder
    app.config["OPENER"] = open_with_system
    app.config["REGISTRATION"] = start_registration_window
    app.config["EGD"] = EgdIndex()
    app.config["EGD_FETCH"] = egd.fetch_by_pin

    def lang() -> str:
        chosen = request.cookies.get("lang")
        if chosen in LANGUAGES:
            return chosen
        return request.accept_languages.best_match(LANGUAGES) or "en"

    def tdir() -> Path | None:
        d = app.config["TOURNAMENT_DIR"]
        return d if d and (d / CONFIG_FILE).exists() else None

    @app.before_request
    def protect():
        # only this computer: refuse other host names (protects against DNS rebinding)
        host = (request.host or "").rsplit(":", 1)[0].strip("[]")
        if host not in ("127.0.0.1", "localhost", "::1"):
            abort(403)
        # forms must come from our own pages (protects against other websites sending requests)
        if request.method == "POST" and request.form.get("csrf") != app.config["CSRF"]:
            abort(403)

    def tournament_name() -> str:
        """Name of the open tournament for the header ("" if none); the folder name if the settings are broken."""
        from ..config import ConfigError, load_config
        d = tdir()
        if d is None:
            return ""
        try:
            return load_config(d).tournament.name.strip() or d.name
        except ConfigError:
            return d.name

    @app.context_processor
    def helpers():
        l = lang()
        from ..i18n import builtin
        return {"t": lambda key, **kw: text(l, key, **kw), "lang": l, "languages": LANGUAGES,
                "csrf": app.config["CSRF"], "version": __version__, "has_tournament": tdir() is not None,
                "tournament_name": tournament_name(),
                "dates": lambda ds: builtin(l).date_range(list(ds))}

    def say(category: str, key: str, **kw) -> None:
        flash(text(lang(), key, **kw), category)

    def explain(e: workflow.Problem, round_no: int | None = None) -> None:
        d = e.data
        if e.code == "file_open":
            say("error", "pr_file_open", name=Path(d["path"]).name)
        elif e.code == "previous_incomplete":
            say("error", "pr_previous_incomplete", r=d["round"], next=round_no)
            for board, white, black in d["boards"]:
                say("error", "msg_missing_board", board=board, white=white, black=black)
        elif e.code == "open_results":
            say("error", "pr_open_results")
        elif e.code == "names_need_confirmation":
            say("error", "pr_names_need_confirmation", r=round_no)
        else:
            flash(str(e), "error")

    # ------------------------------------------------------------ pages

    @app.get("/")
    def home():
        if tdir() and not request.args.get("choose"):
            return redirect(url_for("dashboard"))
        return render_template("home.html", recent=find_tournaments(), default_folder=default_folder(lang()))

    @app.get("/help")
    def help_page():
        """The quick-start guide (PDF) in the language of the interface."""
        name = "Schnellstart.pdf" if lang() == "de" else "Quickstart.pdf"
        return send_from_directory(Path(__file__).parent.parent / "data" / "docs", name)

    def current_config():
        """(settings of the open tournament or the defaults, True if they belong to a tournament)."""
        from ..config import ConfigError, load_config, parse_config
        d = tdir()
        if d is not None:
            try:
                return load_config(d), True
            except ConfigError:
                pass
        return parse_config({}), False

    @app.get("/system")
    def system_page():
        """How the TGoR tournament system works, with the values of the open tournament."""
        from ..i18n import builtin
        from ..summary import game_lines
        cfg, own = current_config()
        return render_template(f"help/system_{lang()}.html", cfg=cfg, own=own, rank_of=rank_of_gor,
                               summary_file=SUMMARY_FILE, game_text=" ".join(game_lines(cfg, builtin(lang()))),
                               examples=rating_examples(cfg.rating.k_factor),
                               handicaps=handicap_table(cfg.handicap.reduction, cfg.handicap.komi_even,
                                                        cfg.handicap.komi_handicap))

    @app.get("/docs")
    def docs_page():
        """Documentation of the program."""
        cfg, own = current_config()
        return render_template(f"help/docs_{lang()}.html", cfg=cfg, own=own)

    @app.get("/api/rating")
    def api_rating():
        """Rating changes of one game, for the calculator on the system page."""
        from ..rating import expected_score, game_changes
        try:
            white = float(request.args["white"])
            black = float(request.args["black"])
            handicap = int(request.args.get("handicap", 0))
            k = float(request.args.get("k", 3))
            if not (-900 <= white <= 3000 and -900 <= black <= 3000 and 0 <= handicap <= 9 and 0 < k <= 20):
                raise ValueError
            result = {}
            for name, score in (("white", 1.0), ("jigo", 0.5), ("black", 0.0)):
                dw, db = game_changes(white, black, handicap, score, k)
                result[name] = {"white": round(dw, 1), "black": round(db, 1)}
            return jsonify(expected_white=round(expected_score(white, black, 0, handicap), 3), **result)
        except (KeyError, ValueError):
            return jsonify(error="invalid"), 400

    @app.get("/api/ping")
    def api_ping():
        return jsonify(app="gotourney", version=__version__)

    @app.get("/launch/<token>")
    def launch(token: str):
        """Used by the launcher window ("Open tournament folder ..."): open that folder."""
        if not secrets.compare_digest(token, app.config["LAUNCH"]):
            abort(403)
        if request.args.get("path"):
            path = Path(request.args["path"]).expanduser()
            if not (path / CONFIG_FILE).exists():
                say("error", "not_a_tournament", path=path)
                return redirect(url_for("home", choose=1))
            app.config["TOURNAMENT_DIR"] = path.resolve()
            remember(path.resolve())
            return redirect(url_for("dashboard"))
        return redirect(url_for("home"))

    @app.get("/lang/<code>")
    def set_lang(code: str):
        resp = redirect(request.referrer or url_for("home"))
        if code in LANGUAGES:
            resp.set_cookie("lang", code, max_age=3600 * 24 * 365, samesite="Strict")
        return resp

    @app.post("/open")
    def open_tournament():
        path = Path(request.form.get("path", "").strip()).expanduser()
        if not (path / CONFIG_FILE).exists():
            say("error", "not_a_tournament", path=path)
            return redirect(url_for("home", choose=1))
        app.config["TOURNAMENT_DIR"] = path.resolve()
        remember(path.resolve())
        return redirect(url_for("dashboard"))

    @app.post("/create")
    def create():
        name = request.form.get("name", "").strip()
        base = Path(request.form.get("folder", "").strip() or default_folder(lang())).expanduser()
        target = base / _folder_name(name)          # each tournament gets its own folder
        try:
            rounds = max(1, min(20, int(request.form.get("rounds", "5"))))
        except ValueError:
            rounds = 5
        language = request.form.get("language", "en")
        try:
            workflow.create_tournament(target, name, rounds, language)
        except workflow.Problem as e:
            flash(str(e), "error")
            return redirect(url_for("home", choose=1))
        app.config["TOURNAMENT_DIR"] = target.resolve()
        remember(target.resolve())
        say("success", "created", path=target)
        return redirect(url_for("dashboard"))

    @app.get("/dashboard")
    def dashboard():
        d = tdir()
        if d is None:
            return redirect(url_for("home", choose=1))
        try:
            t = workflow.load_for_display(d)
        except workflow.Problem as e:
            flash(str(e), "error")
            return render_template("dashboard.html", tour=None, d=d, rounds=[], files=[], card=None,
                                   folder_version=folder_version(d))
        return render_template("dashboard.html", tour=t, d=d, card=phase_card(t, lang()), rounds=round_rows(t),
                               files=other_files(d), folder_version=folder_version(d))

    @app.get("/api/version")
    def api_version():
        d = tdir()
        return jsonify(v=folder_version(d) if d else "")

    @app.get("/file/<path:name>")
    def download(name: str):
        d = tdir()
        p = Path(name)
        if d is None or p.name != name or p.suffix.lower() not in DOWNLOADABLE:
            abort(404)
        # documents made from the tournament files are created fresh, so they are always up to date
        try:
            refresh_generated(d, name)
        except workflow.Problem as e:
            explain(e)
            return redirect(request.referrer or url_for("documents_page"))
        if not (d / name).is_file():
            abort(404)
        return send_from_directory(d, name, as_attachment=request.args.get("dl") == "1", max_age=0)

    # ------------------------------------------------------------ results of a round

    @app.get("/round/<int:r>")
    def round_page(r: int):
        d = tdir()
        if d is None:
            return redirect(url_for("home", choose=1))
        try:
            t = workflow.load(d, names_allowed_in_round=r)
        except workflow.Problem as e:
            flash(str(e), "error")
            return redirect(url_for("dashboard"))
        rg = t.rounds.get(r)
        if rg is None:
            return redirect(url_for("dashboard"))
        started = bool(rg.games) and all(g.finalized for g in rg.games)
        on_board = {pid for g in rg.games for pid in g.players()}
        from ..rounds import read_not_playing
        joker_out = {pid for pid, _, reason in read_not_playing(rg.path) if "joker" in reason.lower()}
        waiting = [p for p in sorted(t.players.values(), key=lambda p: p.name.casefold())
                   if p.plays(r) and p.id not in on_board]
        unpaired = [p for p in waiting if p.id not in joker_out]
        sitting_out = [p for p in waiting if p.id in joker_out]
        ratings = t.rating_before(r)
        board_of = {pid: g.board for g in rg.games for pid in g.players()}
        participants = [{"id": p.id, "label": f"{p.name} ({p.rank or '?'}, {ratings[p.id]:.0f})",
                         "board": board_of.get(p.id)}
                        for p in sorted(t.players.values(), key=lambda p: p.name.casefold())
                        if p.plays(r) or p.id in on_board]
        return render_template("round.html", tour=t, r=r, rows=board_rows(t, r),
                               summary=round_summary(t, r), started=started, unpaired=unpaired,
                               sitting_out=sitting_out,
                               participants=participants, names=workflow.name_candidates(d, r) if rg.unresolved else [],
                               locked=workflow.is_open_in_libreoffice(d / f"round_{r}.ods"),
                               later=any(x > r for x in t.rounds), folder_version=folder_version(d))

    @app.post("/round/<int:r>/board")
    def board_change(r: int):
        d = tdir()
        if d is None:
            abort(404)
        board = request.form.get("board", type=int)
        what = request.form.get("what", "")
        try:
            if what == "fix":
                workflow.update_board(d, r, board, finalized=True)
            elif what == "release":
                workflow.update_board(d, r, board, finalized=False)
            elif what == "swap":
                workflow.update_board(d, r, board, swap=True)
            elif what == "handicap":
                workflow.update_board(d, r, board, handicap=request.form.get("handicap", type=int))
            elif what == "dissolve":
                workflow.dissolve_board(d, r, board)
                say("info", "rp_dissolved", board=board)
            else:
                abort(400)
        except workflow.Problem as e:
            explain(e, r)
        return redirect(url_for("round_page", r=r) + (f"#board-{board}" if what != "dissolve" else ""))

    @app.post("/round/<int:r>/manual")
    def board_manual(r: int):
        d = tdir()
        if d is None:
            abort(404)
        white, black = request.form.get("white", type=int), request.form.get("black", type=int)
        handicap = request.form.get("handicap", "")
        try:
            out = workflow.pair_by_hand(d, r, white, black, int(handicap) if handicap.isdigit() else None)
            say("success", "rp_manual_done", board=next(g.board for g in out.games if set(g.players()) == {white, black}))
            for w in out.warnings:
                flash(w, "warning")
        except workflow.Problem as e:
            explain(e, r)
        return redirect(url_for("round_page", r=r))

    @app.post("/round/<int:r>/resolve")
    def board_resolve(r: int):
        d = tdir()
        if d is None:
            abort(404)
        chosen = {}
        for i, entry in enumerate(workflow.name_candidates(d, r)):
            pid = request.form.get(f"pick_{i}", type=int)
            if pid:
                chosen[entry["where"]] = pid

        def resolver(where, text, candidates, round_no):
            return next((p for p in candidates if p.id == chosen.get(where)), None)

        try:
            out = workflow.pair(d, r, resolver=resolver)
            say("success", "msg_paired", r=r, boards=len(out.games))
        except workflow.Problem as e:
            explain(e, r)
        return redirect(url_for("round_page", r=r))

    @app.post("/round/<int:r>/result")
    def set_result(r: int):
        d = tdir()
        if d is None:
            abort(404)
        board = request.form.get("board", type=int)
        value = request.form.get("result", "")
        partial = request.headers.get("X-Requested-With") == "fetch"
        try:
            out = workflow.set_result(d, r, board, value)
        except workflow.Problem as e:
            if partial:
                key = "pr_file_open" if e.code == "file_open" else None
                msg = text(lang(), key, name=f"round_{r}.ods") if key else str(e)
                return jsonify(ok=False, message=msg), 409
            explain(e, r)
            return redirect(url_for("round_page", r=r))
        t = out.tournament
        row = next(x for x in board_rows(t, r) if x["board"] == board)
        if partial:
            return jsonify(ok=True, row=render_template("_board_row.html", row=row, r=r),
                           summary=round_summary(t, r), version=folder_version(d))
        return redirect(url_for("round_page", r=r) + f"#board-{board}")

    # ------------------------------------------------------------ registration

    def player_form(p=None) -> dict:
        if p is None:
            return {"id": "", "surname": "", "first_name": "", "rank": "", "gor": "", "pin": "", "country": "",
                    "club": "", "joker": False, "rounds": None, "notes": "", "extra": {}, "egd_gor": "",
                    "egd_last_tournament": ""}
        return {"id": p.id, "surname": p.surname, "first_name": p.first_name, "rank": str(p.rank or ""),
                "gor": "" if p.gor is None else f"{p.gor:g}", "pin": p.pin, "country": p.country, "club": p.club,
                "joker": p.joker, "rounds": p.rounds, "notes": p.notes, "extra": dict(p.extra),
                "egd_gor": "" if p.egd_gor is None else f"{p.egd_gor:g}",
                "egd_last_tournament": p.egd_last_tournament}

    def render_players(form: dict, status: int = 200):
        d = tdir()
        cfg, pl = workflow.load_registration(d)
        fields = [{"name": f, "values": cfg.registration.values_for(f)} for f in pl.extra_fields]
        app.config["EGD"].ensure()
        players = sorted(pl.players, key=lambda p: (p.surname.casefold(), p.first_name.casefold()))
        return render_template("players.html", cfg=cfg, players=players, fields=fields, form=form,
                               rounds=range(1, cfg.tournament.rounds + 1), egd_status=app.config["EGD"].status(),
                               locked=workflow.is_open_in_libreoffice(d / "players.ods"),
                               form_unsaved=status >= 400,            # shown again after an error: not saved
                               folder_version=folder_version(d)), status

    @app.get("/players")
    def players_page():
        d = tdir()
        if d is None:
            return redirect(url_for("home", choose=1))
        try:
            form = player_form()
            edit_id = request.args.get("edit", type=int)
            if edit_id is not None:
                _, pl = workflow.load_registration(d)
                p = next((x for x in pl.players if x.id == edit_id), None)
                if p is not None:
                    form = player_form(p)
            return render_players(form)
        except workflow.Problem as e:
            flash(str(e), "error")
            return redirect(url_for("dashboard"))

    @app.post("/players/save")
    def players_save():
        d = tdir()
        if d is None:
            abort(404)
        f = request.form
        cfg, pl = workflow.load_registration(d)
        rounds = {r for r in range(1, cfg.tournament.rounds + 1) if f.get(f"round_{r}")}
        extra = {name: f.get(f"extra_{i}", "") for i, name in enumerate(pl.extra_fields)}
        try:
            egd_gor = float(f.get("egd_gor")) if f.get("egd_gor") else None
        except ValueError:
            egd_gor = None
        data = workflow.PlayerData(
            surname=f.get("surname", ""), first_name=f.get("first_name", ""), rank=f.get("rank", ""),
            gor=f.get("gor", ""), pin=f.get("pin", ""), country=f.get("country", ""), club=f.get("club", ""),
            joker=bool(f.get("joker")), rounds=rounds, notes=f.get("notes", ""), extra=extra,
            egd_gor=egd_gor, egd_last_tournament=f.get("egd_last_tournament", ""))
        player_id = f.get("id", type=int)
        try:
            player, issues = workflow.save_player(d, data, player_id)
        except workflow.Problem as e:
            if e.code == "file_open":
                say("error", "pr_file_open", name="players.ods")
            else:
                flash(str(e), "error")
            form = {"id": player_id or "", "surname": data.surname, "first_name": data.first_name, "rank": data.rank,
                    "gor": data.gor, "pin": data.pin, "country": data.country, "club": data.club,
                    "joker": data.joker, "rounds": rounds, "notes": data.notes, "extra": extra,
                    "egd_gor": f.get("egd_gor", ""), "egd_last_tournament": data.egd_last_tournament}
            return render_players(form, 422)
        say("success", "pl_saved" if player_id else "pl_added", name=player.name, id=player.id)
        for i in issues:
            flash(i.message, {"error": "error", "warning": "warning"}.get(i.level, "info"))
        return redirect(url_for("players_page"))

    @app.post("/players/<int:pid>/remove")
    def players_remove(pid: int):
        d = tdir()
        if d is None:
            abort(404)
        try:
            player = workflow.remove_player(d, pid)
            say("success", "pl_removed", name=player.name)
        except workflow.Problem as e:
            if e.code == "file_open":
                say("error", "pr_file_open", name="players.ods")
            else:
                flash(str(e), "error")
        return redirect(url_for("players_page"))

    @app.post("/players/egd-update")
    def egd_update():
        app.config["EGD"].ensure(refresh=True)
        say("info", "pl_egd_updating")
        return redirect(url_for("players_page"))

    @app.get("/api/egd/search")
    def api_egd_search():
        holder = app.config["EGD"]
        holder.ensure()
        if holder.index is None:
            return jsonify(status=holder.status(), results=[])
        q = request.args.get("q", "")
        d = tdir()
        registered, outdated_years = {}, 5
        if d is not None:
            try:
                cfg, pl = workflow.load_registration(d)
                registered = {p.pin: p.id for p in pl.players if p.pin}
                outdated_years = cfg.registration.gor_outdated_years
            except workflow.Problem:
                pass
        from ..registration import tournament_date
        results = []
        for p in holder.index.search(q, limit=25):
            last = tournament_date(p.last_appearance or "")
            years = round((dt.date.today() - last).days / 365.25) if last else None
            results.append({"pin": p.pin, "surname": p.surname, "first_name": p.first_name, "country": p.country,
                            "club": p.club, "grade": p.grade, "rank": rank_text(p), "gor": p.gor,
                            "last": p.last_appearance, "registered": registered.get(p.pin),
                            "outdated": years if years is not None and years > outdated_years else None})
        return jsonify(status=holder.status(), results=results)

    @app.get("/api/egd/pin/<pin>")
    def api_egd_pin(pin: str):
        if not pin.isdigit():
            abort(404)
        try:
            p = app.config["EGD_FETCH"](pin)
        except egd.EGDError as e:
            return jsonify(ok=False, error=str(e))
        return jsonify(ok=True, gor=p.gor, rank=rank_text(p), club=p.club, country=p.country,
                       last=p.last_appearance, surname=p.surname, first_name=p.first_name)

    # ------------------------------------------------------------ standings and documents

    @app.get("/documents")
    def documents_page():
        d = tdir()
        if d is None:
            return redirect(url_for("home", choose=1))
        try:
            t = workflow.load_for_display(d)
        except workflow.Problem as e:
            flash(str(e), "error")
            return redirect(url_for("dashboard"))
        complete = bool(t.rounds) and all(rg.complete for rg in t.rounds.values())
        if (d / "wall_list.ods").exists():
            try:
                workflow.make_h9(d)                   # keep the preview up to date
            except workflow.Problem:
                pass
        winners, notes = [], []
        if complete:
            from ..awards import AwardError, compute_awards
            try:
                tr, _ = workflow.translator(t)
                winners, notes = compute_awards(t, tr)
            except (AwardError, workflow.Problem) as e:
                notes = [str(e)]
        return render_template("documents.html", tour=t, standings=standings_preview(t), docs=document_cards(t, complete),
                               complete=complete, winners=winners, award_notes=notes, h9=h9_preview(t),
                               backups=workflow.list_backups(d), folder_version=folder_version(d))

    @app.get("/backup/<name>")
    def download_backup(name: str):
        d = tdir()
        folder = d / workflow.BACKUP_DIR if d else None
        if folder is None or Path(name).name != name or not name.endswith(".zip") or not (folder / name).is_file():
            abort(404)
        return send_from_directory(folder, name, as_attachment=True)

    # ------------------------------------------------------------ settings

    @app.route("/settings", methods=["GET", "POST"])
    def settings_page():
        from .. import settings as st
        from ..config import RULE_BUILTIN_FIELDS, RULE_TYPES, PRIZE_TYPES
        d = tdir()
        if d is None:
            return redirect(url_for("home", choose=1))
        errors = []
        if request.method == "POST":
            try:
                changes = settings_from_form(request.form)
                old_fields = st.read_settings(d)[0].registration.extra_fields
                cfg = st.save_settings(d, changes, request.form.get("version", ""))
                say("success", "st_saved")
                if cfg.registration.extra_fields != old_fields:
                    try:
                        if not workflow.sync_player_columns(d):
                            say("warning", "st_columns_locked")
                    except workflow.Problem as e:
                        flash(str(e), "error")
                return redirect(url_for("settings_page"))
            except ValueError as e:
                errors.append(str(e))
            except workflow.Problem as e:
                errors.append(text(lang(), "st_changed") if e.code == "changed" else str(e))
        try:
            cfg, version = st.read_settings(d)
        except workflow.Problem as e:
            flash(str(e), "error")
            return redirect(url_for("dashboard"))
        from ..config import GAME_RULES, TIME_SYSTEMS, USUAL_KOMI
        from ..i18n import builtin
        from ..summary import game_lines
        return render_template("settings.html", cfg=cfg, settings_version=version, errors=errors,
                               game_rules=GAME_RULES, time_systems=TIME_SYSTEMS,
                               usual_komi={k: f"{v}" for k, v in USUAL_KOMI.items()},
                               clock_text=" ".join(game_lines(cfg, builtin(lang()))),
                               rule_fields=list(RULE_BUILTIN_FIELDS) + list(cfg.registration.extra_fields),
                               rule_types=RULE_TYPES,
                               prize_types=PRIZE_TYPES, groups_text=groups_text), (422 if errors else 200)

    # ------------------------------------------------------------ actions

    @app.post("/do/<action>")
    def do(action: str):
        d = tdir()
        if d is None:
            return redirect(url_for("home", choose=1))
        r = request.form.get("round", type=int)
        try:
            run_action(action, d, r)
        except workflow.Problem as e:
            explain(e, r)
        back = request.form.get("next", "")
        if back.startswith("/") and not back.startswith("//"):
            return redirect(back)
        return redirect(url_for("dashboard"))

    def run_action(action: str, d: Path, r: int | None) -> None:
        if action == "pair":
            out = workflow.pair(d, r)
            if out.started_before and out.new_boards:
                say("success", "msg_paired_late", boards=", ".join(map(str, out.new_boards)))
            elif out.kept and not out.new_boards:
                say("info", "msg_nothing_new", r=r)
            else:
                say("success", "msg_paired", r=r, boards=len(out.games))
            for w in out.warnings:
                flash(w, "warning")
        elif action == "start":
            out = workflow.start(d, r)
            say("success", "msg_started", r=r, boards=out.boards)
        elif action == "check_results":
            check = workflow.check_results(workflow.load(d), r)
            if check.complete:
                say("success", "msg_results_ok", r=r, boards=check.boards)
            else:
                say("warning", "msg_results_missing", r=r, missing=len(check.missing), boards=check.boards)
                for board, white, black in check.missing:
                    say("warning", "msg_missing_board", board=board, white=white, black=black)
        elif action == "check_players":
            from ..registration import check_players
            t = workflow.load(d)
            issues = check_players(list(t.players.values()), t.cfg)
            errors = [i for i in issues if i.level == "error"]
            say("error" if errors else "success",
                "msg_registration_errors" if errors else "msg_registration_ok", n=len(errors))
            for i in issues:
                flash(i.message, {"error": "error", "warning": "warning"}.get(i.level, "info"))
        elif action == "standings":
            out = workflow.make_standings(d)
            say("success", "msg_written", name="standings.pdf")
            if out.pdf_error:
                flash(out.pdf_error, "warning")
        elif action == "wall":
            path, _ = workflow.make_wall(d)
            say("success", "msg_written", name=path.name)
        elif action == "h9":
            path, _, warnings = workflow.make_h9(d)
            say("success", "msg_written", name=path.name)
            for w in warnings:
                flash(w, "warning")
        elif action == "awards":
            out = workflow.make_awards(d)
            say("success", "msg_written", name=out.path.name)
            for w in out.notes + out.warnings:
                flash(w, "warning")
        elif action == "open_file":
            name = request.form.get("name", "")
            if Path(name).name != name or not (d / name).is_file():
                abort(404)
            app.config["OPENER"](d / name)
            say("info", "msg_file_opened", name=name)
        elif action == "backup":
            path = workflow.backup(d, "by_hand")
            say("success" if path else "warning", "doc_backup_done" if path else "doc_backup_failed",
                name=path.name if path else "")
        elif action == "registration":
            app.config["REGISTRATION"](d)
            say("info", "msg_window_opened")
        else:
            abort(404)

    return app


def groups_text(groups) -> str:
    """[['U7', 'U11'], ['U15']] -> 'U7, U11 | U15' (as shown in the settings form)."""
    return " | ".join(", ".join(g) for g in groups)


def _groups(text: str) -> list[list[str]]:
    return [[v.strip() for v in part.split(",") if v.strip()] for part in text.split("|") if part.strip()]


def settings_from_form(f) -> dict:
    """The settings form as {section: {key: value}} in the structure of tournament.toml."""
    def num(name, kind=float, label=None):
        raw = f.get(name, "").strip().replace(",", ".")
        try:
            return kind(raw) if kind is float else int(raw)
        except ValueError:
            raise ValueError(f"{label or name}: {raw!r} is not a number") from None

    dates = [x for x in (f.get("date_first", "").strip(), f.get("date_last", "").strip()) if x]
    def count(name: str, default: int) -> int:
        """A whole number; empty = the default (fields of other clock systems may be left empty)."""
        return num(name, int) if f.get(name, "").strip() else default

    def rating_value(name: str):
        """A rank ('3d', '20k') stays text, a number becomes a number, empty = 'none'."""
        raw = f.get(name, "").strip().replace(",", ".") or "none"
        try:
            return float(raw)
        except ValueError:
            return raw

    top_bar = rating_value("top_bar")
    changes = {
        "tournament": {"name": f.get("name", "").strip(), "place": f.get("place", "").strip(), "dates": dates,
                       "class": f.get("class", "A"), "time": num("time", int, "time"),
                       "comment": f.get("comment", "").strip(), "rounds": num("rounds", int, "rounds")},
        "output": {"language": f.get("language", "en"),
                   "translation_file": f.get("translation_file", "").strip() or "translation.toml"},
        "rating": {"k_factor": num("k_factor", float, "k-factor"), "top_bar": top_bar},
        "handicap": {"reduction": num("reduction", int, "reduction"), "floor": rating_value("floor"),
                     "komi_even": num("komi_even"),
                     "komi_handicap": num("komi_handicap")},
        "pairing": {"random_seed": num("random_seed", int, "random seed"), "rules": []},
        "registration": {"gor_outdated_years": num("gor_outdated_years", int),
                         "rank_gor_tolerance": num("rank_gor_tolerance", int),
                         "extra_fields": [], "field_values": {}},
        "awards": {"title_slide": bool(f.get("title_slide")), "prizes": []},
        "game": {"rules": f.get("game_rules", "").strip(), "time_system": f.get("time_system", "").strip(),
                 "byoyomi_periods": count("byoyomi_periods", 5), "byoyomi_seconds": count("byoyomi_seconds", 30),
                 "canadian_stones": count("canadian_stones", 15), "canadian_minutes": count("canadian_minutes", 5),
                 "fischer_seconds": count("fischer_seconds", 20), "fischer_max": count("fischer_max", 0)},
    }
    indices = lambda prefix: sorted({int(k[len(prefix):]) for k in f if k.startswith(prefix) and k[len(prefix):].isdigit()})
    for i in indices("rule_field_"):
        if not f.get(f"rule_field_{i}", "").strip():
            continue
        rule = {"field": f.get(f"rule_field_{i}").strip(), "type": f.get(f"rule_type_{i}", "avoid_same")}
        if rule["type"] in ("avoid_same", "prefer_same"):
            rule["points"] = num(f"rule_points_{i}", float, f"rule {i + 1}: points")
        groups = _groups(f.get(f"rule_groups_{i}", ""))
        if len(groups) == 1:
            rule["values"] = groups[0]
        elif groups:
            rule["groups"] = groups
        changes["pairing"]["rules"].append(rule)
    for i in indices("xf_name_"):
        name = f.get(f"xf_name_{i}", "").strip()
        if not name:
            continue
        changes["registration"]["extra_fields"].append(name)
        values = [v.strip() for v in f.get(f"xf_values_{i}", "").split(",") if v.strip()]
        if values:
            changes["registration"]["field_values"][name] = values
    for i in indices("pz_type_"):
        prize = {"type": f.get(f"pz_type_{i}")}
        if f.get(f"pz_title_{i}", "").strip():
            prize["title"] = f.get(f"pz_title_{i}").strip()
        if prize["type"] == "place":
            try:
                prize["places"] = [int(x) for x in f.get(f"pz_places_{i}", "").replace(" ", "").split(",") if x]
            except ValueError:
                raise ValueError(f"prize {i + 1}: places must be numbers like 3, 2, 1") from None
        elif prize["type"] == "wins":
            prize["min_wins"] = num(f"pz_min_wins_{i}", float, f"prize {i + 1}: minimum wins")
        elif prize["type"] == "best_in_group":
            prize["field"] = f.get(f"pz_field_{i}", "").strip()
            groups = _groups(f.get(f"pz_groups_{i}", ""))
            if len(groups) == 1:
                prize["values"] = groups[0]
            elif groups:
                prize["groups"] = groups
        if prize["type"] in ("best_in_group", "rating_gain") and f.get(f"pz_count_{i}", "").strip():
            prize["count"] = num(f"pz_count_{i}", int, f"prize {i + 1}: count")
        if f.get(f"pz_exclusive_{i}"):
            prize["exclusive"] = True
        changes["awards"]["prizes"].append(prize)
    return changes


def _folder_name(name: str) -> str:
    keep = "".join(c if c.isalnum() or c in " -_" else "_" for c in name).strip()
    return keep or "tournament"


# ---------------------------------------------------------------- dashboard content

GENERATED_ROUND = re.compile(r"^round_(\d+)(_alphabetical)?\.pdf$")


def refresh_generated(d: Path, name: str) -> None:
    """Create a generated document (PDFs, standings.ods, .h9) fresh before it is shown."""
    from ..config import load_config
    from ..wall import h9_filename
    m = GENERATED_ROUND.match(name)
    if m:
        paths, error, _ = workflow.pairing_pdfs(d, int(m.group(1)))
        if error:
            raise workflow.Problem("pdf", f"PDF not written: {error}")
    elif name in ("standings.pdf", "standings.ods"):
        out = workflow.make_standings(d)
        if out.pdf_error and name.endswith(".pdf"):
            raise workflow.Problem("pdf", f"PDF not written: {out.pdf_error}")
    elif name == "awards.pdf":
        workflow.make_awards(d)
    elif name == SUMMARY_FILE:
        workflow.make_summary(d)
    elif name.endswith(".h9") and name == h9_filename(load_config(d)):
        workflow.make_h9(d)


def standings_preview(t) -> list[dict]:
    from ..wall import ranking
    r = t.last_round
    order = ranking(t, r)
    ratings = t.ratings[r]
    rows = []
    for place, pid in enumerate(order, start=1):
        p = t.players[pid]
        games = sum(1 for h in t.history[pid] if h.counts_as_played)
        rows.append({"place": place, "name": p.name, "rank": str(p.rank or ""), "club": p.club,
                     "tgor": round(ratings[pid]), "change": round(ratings[pid] - t.start[pid]),
                     "wins": t.wins(pid), "games": games})
    return rows


def document_cards(t, complete: bool) -> list[dict]:
    """What can be created at the end (or now), with state and files."""
    from ..wall import h9_filename
    d = t.directory
    newest_input = max([p.stat().st_mtime for p in d.glob("round_*.ods")] + [(d / "players.ods").stat().st_mtime])

    def card(key, action, names, needs=None, generated=False):
        files = [{"name": n, "exists": (d / n).exists(), "locked": workflow.is_open_in_libreoffice(d / n)}
                 for n in names]
        main = d / names[0]
        made = main.stat().st_mtime if main.exists() else None
        if generated:
            for f in files:
                f["exists"] = needs is None           # created when opened
        return {"key": key, "action": action, "files": files, "needs": needs, "generated": generated,
                "made": dt.datetime.fromtimestamp(made).strftime("%Y-%m-%d %H:%M") if made else "",
                "outdated": bool(made and made < newest_input)}

    h9 = h9_filename(t.cfg)
    return [
        card("summary", "summary", [SUMMARY_FILE], generated=True),
        card("standings", "standings", ["standings.pdf", "standings.ods"], None if t.rounds else "doc_needs_round",
             generated=True),
        card("wall", "wall", ["wall_list.ods"], None if complete else "doc_needs_results"),
        card("h9", "h9", [h9], None if (d / "wall_list.ods").exists() else "doc_needs_wall", generated=True),
        card("awards", "awards", ["awards.pdf"], None if complete else "doc_needs_results", generated=True),
    ]


def h9_preview(t) -> str:
    from ..wall import h9_filename
    p = t.directory / h9_filename(t.cfg)
    if not p.exists():
        return ""
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[:40] + (["…"] if len(lines) > 40 else []))


def round_rows(t) -> list[dict]:
    rows = []
    for r in range(1, t.cfg.tournament.rounds + 1):
        rg = t.rounds.get(r)
        row = {"r": r, "status": "st_not_paired", "done": 0, "boards": 0, "files": []}
        if rg:
            row["boards"] = len(rg.games)
            row["done"] = sum(1 for g in rg.games if g.result is not None)
            if rg.unresolved:
                row["status"] = "st_names"
            elif rg.games and row["done"] == row["boards"]:
                row["status"] = "st_complete"
            elif workflow.round_started(t, r) or row["done"]:
                row["status"] = "st_running"
            else:
                row["status"] = "st_paired"
            for name in (f"round_{r}.ods", f"round_{r}.pdf", f"round_{r}_alphabetical.pdf"):
                p = t.directory / name
                if p.exists():
                    row["files"].append({"name": name, "locked": workflow.is_open_in_libreoffice(p)})
        rows.append(row)
    return rows


def board_rows(t, r: int) -> list[dict]:
    """The boards of a round for the results page."""
    from ..rounds import player_label

    rg = t.rounds[r]
    ratings = t.rating_before(r)
    rows = []
    for g in sorted(rg.games, key=lambda g: g.board):
        w, b = t.players[g.white], t.players[g.black]
        rows.append({
            "board": g.board, "result": workflow.result_value(g.result),
            "white": player_label(w), "black": player_label(b),
            "white_tgor": round(ratings.get(g.white, 0)), "black_tgor": round(ratings.get(g.black, 0)),
            "handicap": g.handicap, "komi": f"{g.komi:g}", "finalized": g.finalized,
            "started": all(x.finalized for x in rg.games),
            "search": f"{w.name} {b.name}".lower(),
        })
    return rows


def round_summary(t, r: int) -> dict:
    rg = t.rounds[r]
    done = sum(1 for g in rg.games if g.result is not None)
    return {"done": done, "boards": len(rg.games), "missing": len(rg.games) - done,
            "percent": round(100 * done / len(rg.games)) if rg.games else 0}


def other_files(d: Path) -> list[dict]:
    names = ["players.ods", "standings.pdf", "standings.ods", "wall_list.ods", "awards.pdf", CONFIG_FILE]
    names += sorted(p.name for p in d.glob("*.h9"))
    return [{"name": n, "locked": workflow.is_open_in_libreoffice(d / n)} for n in names if (d / n).exists()]


def phase_card(t, lang: str) -> dict:
    """Title, explanation and buttons for the next step."""
    s = workflow.status(t)
    r = s.round
    tx = lambda key, **kw: text(lang, key, **kw)
    act = lambda label, action, primary=False, confirm=None, **form: {
        "label": label, "action": action, "primary": primary, "confirm": confirm, "form": form}
    files = lambda *names: [{"label": label, "file": name} for label, name in names]   # created when opened
    card = {"title": "", "text": "", "extra": "", "actions": [], "files": [], "link": None, "link_primary": False}
    if s.phase == "no_players":
        card.update(title=tx("ph_no_players_title"), text=tx("ph_no_players_text"),
                    link={"label": tx("act_register"), "href": "/players"}, link_primary=True)
    elif s.phase == "registration":
        card.update(title=tx("ph_registration_title"), text=tx("ph_registration_text", n=s.players),
                    link={"label": tx("act_register"), "href": "/players"},
                    actions=[act(tx("act_check_players"), "check_players"),
                             act(tx("act_pair", r=1), "pair", primary=True, round=1)])
    elif s.phase == "names_pending":
        card.update(title=tx("ph_names_title", r=r), text=tx("ph_names_text", r=r),
                    link={"label": tx("rp_names_title"), "href": f"/round/{r}"}, link_primary=True)
    elif s.phase == "paired":
        card.update(title=tx("ph_paired_title", r=r), text=tx("ph_paired_text"),
                    link={"label": tx("act_show_boards"), "href": f"/round/{r}"},
                    actions=[act(tx("act_repair", r=r), "pair", confirm=tx("confirm_repair", r=r), round=r),
                             act(tx("act_start", r=r), "start", primary=True,
                                 confirm=tx("confirm_start", r=r), round=r)],
                    files=files((tx("act_pdf_board"), f"round_{r}.pdf"),
                                (tx("act_pdf_alpha"), f"round_{r}_alphabetical.pdf")))
    elif s.phase == "running":
        card.update(title=tx("ph_running_title", r=r),
                    text=tx("ph_running_text", r=r, done=s.boards - s.missing, boards=s.boards),
                    actions=[act(tx("act_open_round", r=r), "open_file", name=f"round_{r}.ods"),
                             act(tx("act_check_results"), "check_results", round=r)],
                    link={"label": tx("act_enter_results"), "href": f"/round/{r}"}, link_primary=True,
                    files=files((tx("act_pdf_board"), f"round_{r}.pdf"),
                                (tx("act_pdf_alpha"), f"round_{r}_alphabetical.pdf")))
        late = workflow.check_results(t, r).unpaired
        if late:
            card["extra"] = tx("ph_running_late", names=", ".join(n for _, n in late))
            card["actions"].insert(1, act(tx("act_pair_late"), "pair", round=r))
    elif s.phase == "round_complete":
        card.update(title=tx("ph_complete_title", r=r), text=tx("ph_complete_text", next=r + 1),
                    link={"label": tx("documents_title"), "href": "/documents"},
                    actions=[act(tx("act_pair", r=r + 1), "pair", primary=True, round=r + 1)],
                    files=files((tx("act_standings_pdf"), "standings.pdf")))
    else:
        card.update(title=tx("ph_finished_title"), text=tx("ph_finished_text"),
                    link={"label": tx("documents_title"), "href": "/documents"}, link_primary=True,
                    actions=[],
                    files=files((tx("act_standings_pdf"), "standings.pdf"), (tx("act_awards"), "awards.pdf")))
    return card


def rank_of_gor(gor: float | None) -> str:
    from ..rank import Rank
    return "" if gor is None else str(Rank.from_gor(gor))


def rating_examples(k: float) -> list[dict]:
    """Example games for the system page: rating changes if White / Black wins."""
    from ..pairing import default_handicap
    from ..rating import game_changes
    rows = []
    for white, black in ((2000, 2000), (2000, 1800), (1000, 1000), (2300, 2200), (1500, 1100)):
        h = default_handicap(white - black, 0)
        ww = game_changes(white, black, h, 1.0, k)
        bw = game_changes(white, black, h, 0.0, k)
        egd = game_changes(white, black, h, 1.0, 1.0)
        rows.append({"white": white, "black": black, "handicap": h, "white_wins": ww, "black_wins": bw,
                     "egd_white_wins": egd})
    return rows


def handicap_table(reduction: int, komi_even: float, komi_handicap: float) -> list[dict]:
    from ..pairing import default_handicap
    rows = []
    for low in range(0, 1000, 100):
        h = default_handicap(low, reduction)
        rows.append({"low": low, "high": None if low == 900 else low + 99, "stones": h,
                     "komi": komi_handicap if h > 0 else komi_even})
    return rows


DEFAULT_PORT = 8765


def running_instance(port: int) -> bool:
    """Is a gotourney web interface already answering on this port (e.g. started twice)?"""
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=1) as r:
            return json.loads(r.read().decode()).get("app") == "gotourney"
    except (OSError, ValueError):
        return False


def port_free(port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def free_port() -> int:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def make_server(app: Flask, port: int):
    """A waitress server on 127.0.0.1 (call .run() to serve, .close() to stop)."""
    from waitress import create_server
    return create_server(app, host="127.0.0.1", port=port, threads=8, ident="gotourney")


def run(directory: Path | None = None, port: int = DEFAULT_PORT, open_browser: bool = True,
        start_path: str = "/") -> None:
    """Start the local web interface (blocks until stopped with Ctrl+C)."""
    import webbrowser

    if not port_free(port):
        if running_instance(port) and directory is None:
            url = f"http://127.0.0.1:{port}{start_path}"
            print(f"gotourney is already running: {url}")
            if open_browser:
                webbrowser.open(url)
            return
        port = free_port()
    app = create_app(directory)
    app.config["EGD"].ensure()                    # load the EGD player list in the background
    if directory is not None:
        remember(Path(directory).resolve())
    url = f"http://127.0.0.1:{port}{start_path}"
    server = make_server(app, port)
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    print(f"gotourney web interface: {url}   (stop with Ctrl+C)")
    try:
        server.run()
    except KeyboardInterrupt:
        pass
    finally:
        server.close()
