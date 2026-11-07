"""Local web interface: ``gotourney web`` opens it in the browser.

Runs only on this computer (127.0.0.1). The tournament files stay the only record: every page reads
them fresh, every action writes them, and LibreOffice can be used for the same files at any time.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import secrets
import subprocess
import sys
import threading
from pathlib import Path

from flask import (Flask, abort, flash, jsonify, redirect, render_template, request, send_from_directory,
                   url_for)

from .. import __version__, egd, workflow
from ..config import CONFIG_FILE
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
    subprocess.Popen([sys.executable, "-m", "gotourney", "gui", "-d", str(directory)], env=env)


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

    @app.context_processor
    def helpers():
        l = lang()
        from ..i18n import builtin
        return {"t": lambda key, **kw: text(l, key, **kw), "lang": l, "languages": LANGUAGES,
                "csrf": app.config["CSRF"], "version": __version__,
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
        return render_template("home.html", recent=load_recent(), default_folder=default_folder(lang()))

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
            t = workflow.load(d)
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
        if d is None or p.name != name or p.suffix.lower() not in DOWNLOADABLE or not (d / name).is_file():
            abort(404)
        return send_from_directory(d, name, as_attachment=request.args.get("dl") == "1")

    # ------------------------------------------------------------ results of a round

    @app.get("/round/<int:r>")
    def round_page(r: int):
        d = tdir()
        if d is None:
            return redirect(url_for("home", choose=1))
        try:
            t = workflow.load(d)
        except workflow.Problem as e:
            flash(str(e), "error")
            return redirect(url_for("dashboard"))
        rg = t.rounds.get(r)
        if rg is None:
            return redirect(url_for("dashboard"))
        return render_template("round.html", tour=t, r=r, rows=board_rows(t, r),
                               summary=round_summary(t, r), next_card=phase_card(t, lang()),
                               locked=workflow.is_open_in_libreoffice(d / f"round_{r}.ods"),
                               later=any(x > r for x in t.rounds), folder_version=folder_version(d))

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
        elif action == "registration":
            app.config["REGISTRATION"](d)
            say("info", "msg_window_opened")
        else:
            abort(404)

    return app


def _folder_name(name: str) -> str:
    keep = "".join(c if c.isalnum() or c in " -_" else "_" for c in name).strip()
    return keep or "tournament"


# ---------------------------------------------------------------- dashboard content

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
    files = lambda *names: [{"label": label, "file": name} for label, name in names
                            if (t.directory / name).exists()]
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
                    actions=[act(tx("act_open_round", r=r), "open_file", name=f"round_{r}.ods")])
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
                    actions=[act(tx("act_standings"), "standings"),
                             act(tx("act_pair", r=r + 1), "pair", primary=True, round=r + 1)],
                    files=files((tx("act_standings"), "standings.pdf")))
    else:
        card.update(title=tx("ph_finished_title"), text=tx("ph_finished_text"),
                    actions=[act(tx("act_standings"), "standings"), act(tx("act_wall"), "wall", primary=True),
                             act(tx("act_h9"), "h9"), act(tx("act_awards"), "awards")],
                    files=files((tx("act_standings"), "standings.pdf"), (tx("act_awards"), "awards.pdf")))
    return card


def run(directory: Path | None = None, port: int = 8765, open_browser: bool = True, start_path: str = "/") -> None:
    """Start the local web interface (blocks until stopped with Ctrl+C)."""
    import webbrowser

    app = create_app(directory)
    app.config["EGD"].ensure()                    # load the EGD player list in the background
    if directory is not None:
        remember(Path(directory).resolve())
    url = f"http://127.0.0.1:{port}{start_path}"
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    print(f"gotourney web interface: {url}   (stop with Ctrl+C)")
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)
