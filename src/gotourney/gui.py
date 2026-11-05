"""Registration window (Tkinter) with autocomplete from the EGD player list.

Every change is written to players.ods immediately. The file is re-read before each
write, so edits made by hand in LibreOffice (after saving and closing it) are kept.
"""

from __future__ import annotations

import datetime as dt
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from . import egd
from .config import Config
from .models import Player
from .ods import OdsError
from .players import PLAYERS_FILE, load_players, save_players
from .rank import Rank, RankError
from .registration import RegistrationError, check_players, new_player, tournament_date

SEARCH_DELAY_MS = 150
FILE_POLL_MS = 2000


def rank_from_egd(p: egd.EGDPlayer) -> Rank:
    try:
        return Rank.parse(p.grade)
    except RankError:
        return Rank.from_gor(p.gor)


class RegistrationApp:
    def __init__(self, root: tk.Tk, directory: Path, cfg: Config, refresh_list: bool | None = None):
        self.root = root
        self.dir = Path(directory)
        self.path = self.dir / PLAYERS_FILE
        self.cfg = cfg
        self.rounds = cfg.tournament.rounds
        self.index: egd.PlayerIndex | None = None
        self.players: list[Player] = []
        self.results: list[egd.EGDPlayer] = []
        self.editing_id: int | None = None        # ID of the registered player shown in the form
        self.egd_extra = {"egd_gor": None, "egd_last_tournament": ""}
        self.events: queue.Queue = queue.Queue()
        self._search_job = None
        self._file_mtime = None

        root.title(f"Registration - {cfg.tournament.name or self.dir.resolve().name}")
        root.minsize(900, 640)
        style = ttk.Style(root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Warn.TLabel", foreground="#b35c00")
        style.configure("Ok.TLabel", foreground="#2e7d32")

        self._build_search()
        self._build_form()
        self._build_table()
        self.reload_players()
        self.clear_form()

        threading.Thread(target=self._load_index, args=(refresh_list,), daemon=True).start()
        root.after(100, self._process_events)
        root.after(FILE_POLL_MS, self._poll_file)
        self.search_entry.focus_set()

    # ------------------------------------------------------------ layout

    def _build_search(self):
        frame = ttk.LabelFrame(self.root, text="Search EGD (name or PIN)", padding=6)
        frame.pack(fill="x", padx=8, pady=(8, 4))
        top = ttk.Frame(frame)
        top.pack(fill="x")
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(top, textvariable=self.search_var, font=("TkDefaultFont", 12))
        self.search_entry.pack(side="left", fill="x", expand=True)
        self.list_status = ttk.Label(top, text="Loading EGD player list ...", width=40, anchor="e")
        self.list_status.pack(side="right", padx=(8, 0))
        self.search_var.trace_add("write", lambda *_: self._schedule_search())
        self.search_entry.bind("<Down>", self._focus_results)
        self.search_entry.bind("<Return>", lambda e: self._choose_result(0))
        self.search_entry.bind("<Escape>", lambda e: self.search_var.set(""))

        cols = ("name", "country", "club", "grade", "gor", "pin", "last")
        self.result_tree = ttk.Treeview(frame, columns=cols, show="headings", height=7,
                                        selectmode="browse")
        for col, title, width, anchor in [
            ("name", "Name", 260, "w"), ("country", "Country", 75, "center"),
            ("club", "Club", 70, "center"), ("grade", "Grade", 60, "center"),
            ("gor", "GoR", 60, "e"), ("pin", "PIN", 90, "center"),
            ("last", "Last tournament", 140, "center"),
        ]:
            self.result_tree.heading(col, text=title)
            self.result_tree.column(col, width=width, anchor=anchor, stretch=(col == "name"))
        self.result_tree.pack(fill="x", pady=(6, 0))
        self.result_tree.bind("<Return>", lambda e: self._choose_selected_result())
        self.result_tree.bind("<Double-1>", lambda e: self._choose_selected_result())
        self.result_tree.bind("<Escape>", lambda e: self.search_entry.focus_set())

    def _build_form(self):
        frame = ttk.LabelFrame(self.root, text="Player", padding=6)
        frame.pack(fill="x", padx=8, pady=4)
        self.form_title = ttk.Label(frame, text="", font=("TkDefaultFont", 10, "bold"))
        self.form_title.grid(row=0, column=0, columnspan=8, sticky="w", pady=(0, 4))

        self.vars: dict[str, tk.StringVar] = {}
        fields = [
            ("surname", "Surname", 0, 0, 22), ("first_name", "First name", 0, 2, 22),
            ("rank", "Rank", 0, 4, 6), ("gor", "GoR", 0, 6, 7),
            ("pin", "EGD PIN", 1, 0, 12), ("country", "Country", 1, 2, 5),
            ("club", "Club", 1, 4, 8),
        ]
        for key, label, r, c, width in fields:
            ttk.Label(frame, text=label).grid(row=r + 1, column=c, sticky="e", padx=(8, 3), pady=2)
            var = tk.StringVar()
            entry = ttk.Entry(frame, textvariable=var, width=width)
            entry.grid(row=r + 1, column=c + 1, sticky="w", pady=2)
            entry.bind("<Return>", lambda e: self.submit())
            var.trace_add("write", lambda *_: self._update_hints())
            self.vars[key] = var

        self.joker_var = tk.BooleanVar()
        ttk.Checkbutton(frame, text="Joker (may sit out odd rounds)", variable=self.joker_var) \
            .grid(row=2, column=6, columnspan=2, sticky="w", padx=(8, 0))

        ttk.Label(frame, text="Rounds").grid(row=3, column=0, sticky="e", padx=(8, 3), pady=2)
        rframe = ttk.Frame(frame)
        rframe.grid(row=3, column=1, columnspan=7, sticky="w")
        self.round_vars = []
        for i in range(1, self.rounds + 1):
            v = tk.BooleanVar(value=True)
            ttk.Checkbutton(rframe, text=str(i), variable=v).pack(side="left", padx=(0, 6))
            self.round_vars.append(v)
        ttk.Button(rframe, text="all", width=4, command=lambda: self._set_rounds(True)).pack(side="left", padx=2)
        ttk.Button(rframe, text="none", width=5, command=lambda: self._set_rounds(False)).pack(side="left", padx=2)

        ttk.Label(frame, text="Notes").grid(row=4, column=0, sticky="e", padx=(8, 3), pady=2)
        self.vars["notes"] = tk.StringVar()
        ttk.Entry(frame, textvariable=self.vars["notes"], width=70) \
            .grid(row=4, column=1, columnspan=7, sticky="we", pady=2)

        self.hint = ttk.Label(frame, text="", style="Warn.TLabel", wraplength=850, justify="left")
        self.hint.grid(row=5, column=0, columnspan=8, sticky="w", pady=(4, 2))

        buttons = ttk.Frame(frame)
        buttons.grid(row=6, column=0, columnspan=8, sticky="w", pady=(4, 0))
        self.submit_button = ttk.Button(buttons, text="Add player", command=self.submit)
        self.submit_button.pack(side="left")
        ttk.Button(buttons, text="New / clear", command=self.clear_form).pack(side="left", padx=6)
        self.remove_button = ttk.Button(buttons, text="Remove player", command=self.remove)
        self.remove_button.pack(side="left")

    def _build_table(self):
        frame = ttk.LabelFrame(self.root, text="Registered players", padding=6)
        frame.pack(fill="both", expand=True, padx=8, pady=(4, 8))
        cols = ("id", "name", "rank", "gor", "country", "club", "rounds", "joker")
        self.table = ttk.Treeview(frame, columns=cols, show="headings", selectmode="browse")
        for col, title, width, anchor in [
            ("id", "ID", 40, "e"), ("name", "Name", 260, "w"), ("rank", "Rank", 50, "center"),
            ("gor", "GoR", 60, "e"), ("country", "Country", 75, "center"),
            ("club", "Club", 70, "center"), ("rounds", "Rounds", 120, "w"),
            ("joker", "Joker", 50, "center"),
        ]:
            self.table.heading(col, text=title)
            self.table.column(col, width=width, anchor=anchor, stretch=(col == "name"))
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        self.table.pack(side="left", fill="both", expand=True)
        scroll.pack(side="left", fill="y")
        self.table.bind("<<TreeviewSelect>>", lambda e: self._edit_selected())

        side = ttk.Frame(frame)
        side.pack(side="left", fill="y", padx=(8, 0))
        self.count_label = ttk.Label(side, text="")
        self.count_label.pack(anchor="w")
        ttk.Button(side, text="Check registration", command=self.show_check).pack(fill="x", pady=(8, 0))
        ttk.Button(side, text="Update EGD list", command=self.refresh_list).pack(fill="x", pady=(4, 0))

    # ------------------------------------------------------------ EGD list (background)

    def _load_index(self, refresh):
        try:
            index = egd.PlayerIndex.load(refresh=refresh)
            self.events.put(("index", index))
        except Exception as e:  # noqa: BLE001 - report anything to the user
            self.events.put(("index_error", str(e)))

    def refresh_list(self):
        self.list_status.config(text="Updating EGD player list ...")
        threading.Thread(target=self._load_index, args=(True,), daemon=True).start()

    def _fetch_live(self, pin):
        try:
            self.events.put(("live", egd.fetch_by_pin(pin)))
        except egd.EGDError as e:
            self.events.put(("live_error", (pin, str(e))))

    def _process_events(self):
        try:
            while True:
                kind, data = self.events.get_nowait()
                if kind == "index":
                    self.index = data
                    age = egd.list_age()
                    date = dt.datetime.fromtimestamp(egd.list_path().stat().st_mtime).strftime("%Y-%m-%d")
                    self.list_status.config(
                        text=f"EGD list from {date}: {len(data.players)} players"
                        + (" (old)" if age and age > egd.LIST_MAX_AGE else ""))
                    self._search()
                elif kind == "index_error":
                    self.list_status.config(text="EGD list not available")
                    messagebox.showwarning(
                        "EGD", f"{data}\n\nYou can still register players by typing their data.")
                elif kind == "live":
                    self._apply_live(data)
                elif kind == "live_error":
                    pin, msg = data
                    if self.vars["pin"].get().strip() == pin:
                        self._extra_hint = f"Live EGD data not available ({msg}); using the EGD list."
                        self._update_hints()
        except queue.Empty:
            pass
        self.root.after(100, self._process_events)

    # ------------------------------------------------------------ search

    def _schedule_search(self):
        if self._search_job:
            self.root.after_cancel(self._search_job)
        self._search_job = self.root.after(SEARCH_DELAY_MS, self._search)

    def _search(self):
        self._search_job = None
        self.result_tree.delete(*self.result_tree.get_children())
        if not self.index:
            self.results = []
            return
        self.results = self.index.search(self.search_var.get(), limit=50)
        registered = {p.pin for p in self.players if p.pin}
        for i, p in enumerate(self.results):
            name = p.name + ("   (registered)" if p.pin in registered else "")
            self.result_tree.insert("", "end", iid=str(i), values=(
                name, p.country, p.club, p.grade, p.gor, p.pin, p.last_appearance))

    def _focus_results(self, _event=None):
        children = self.result_tree.get_children()
        if children:
            self.result_tree.focus_set()
            self.result_tree.selection_set(children[0])
            self.result_tree.focus(children[0])
        return "break"

    def _choose_selected_result(self):
        sel = self.result_tree.selection()
        if sel:
            self._choose_result(int(sel[0]))

    def _choose_result(self, i: int):
        if not 0 <= i < len(self.results):
            return
        p = self.results[i]
        existing = next((x for x in self.players if x.pin == p.pin), None)
        if existing:
            self._select_in_table(existing.id)
            return
        self.clear_form(keep_search=True)
        self._fill_from_egd(p)
        threading.Thread(target=self._fetch_live, args=(p.pin,), daemon=True).start()
        self.submit_button.focus_set()

    def _fill_from_egd(self, p: egd.EGDPlayer):
        self.vars["surname"].set(p.surname)
        self.vars["first_name"].set(p.first_name)
        self.vars["rank"].set(str(rank_from_egd(p)))
        self.vars["gor"].set(str(p.gor))
        self.vars["pin"].set(p.pin)
        self.vars["country"].set(p.country)
        self.vars["club"].set(p.club)
        self.egd_extra = {"egd_gor": float(p.gor), "egd_last_tournament": p.last_appearance}
        self._update_hints()

    def _apply_live(self, p: egd.EGDPlayer):
        """Update the form with live EGD data, if the form still shows this (new) player."""
        if self.editing_id is not None or self.vars["pin"].get().strip() != p.pin:
            return
        old_gor = self.vars["gor"].get()
        self._fill_from_egd(p)
        if old_gor != str(p.gor):
            self._extra_hint = f"GoR updated from live EGD data ({old_gor} -> {p.gor})."
            self._update_hints()

    # ------------------------------------------------------------ form

    _extra_hint = ""

    def _set_rounds(self, value: bool):
        for v in self.round_vars:
            v.set(value)

    def clear_form(self, keep_search: bool = False):
        self.editing_id = None
        self._extra_hint = ""
        for v in self.vars.values():
            v.set("")
        self.joker_var.set(False)
        self._set_rounds(True)
        self.egd_extra = {"egd_gor": None, "egd_last_tournament": ""}
        self.form_title.config(text="New player")
        self.submit_button.config(text="Add player")
        self.remove_button.state(["disabled"])
        if self.table.selection():
            self.table.selection_remove(self.table.selection())
        if not keep_search:
            self.search_var.set("")
            self.search_entry.focus_set()
        self._update_hints()

    def _form_player(self, others: list[Player]) -> Player:
        gor_text = self.vars["gor"].get().strip().replace(",", ".")
        try:
            gor = float(gor_text) if gor_text else None
        except ValueError:
            raise RegistrationError(f"GoR {gor_text!r} is not a number") from None
        player = new_player(
            others,
            surname=self.vars["surname"].get(),
            first_name=self.vars["first_name"].get(),
            rank=self.vars["rank"].get().strip() or None,
            gor=gor,
            pin=self.vars["pin"].get(),
            country=self.vars["country"].get(),
            club=self.vars["club"].get(),
            rounds={i + 1 for i, v in enumerate(self.round_vars) if v.get()},
            joker=self.joker_var.get(),
            notes=self.vars["notes"].get().strip(),
        )
        player.egd_gor = self.egd_extra["egd_gor"]
        player.egd_last_tournament = self.egd_extra["egd_last_tournament"]
        return player

    def _update_hints(self):
        hints = []
        if self._extra_hint:
            hints.append(self._extra_hint)
        pin = self.vars["pin"].get().strip()
        if pin and self.editing_id is None:
            dup = next((p for p in self.players if p.pin == pin), None)
            if dup:
                hints.append(f"Already registered as ID {dup.id} ({dup.name}).")
        rank_text, gor_text = self.vars["rank"].get().strip(), self.vars["gor"].get().strip()
        try:
            rank = Rank.parse(rank_text) if rank_text else None
            gor = float(gor_text) if gor_text else None
            if rank and gor is not None and rank.kind != "p":
                diff = abs(rank.to_gor() - gor)
                if diff > self.cfg.registration.rank_gor_tolerance:
                    hints.append(f"Rank {rank} and GoR {gor:.0f} differ by {diff:.0f} points - "
                                 f"check which one is right.")
        except (RankError, ValueError):
            hints.append("Rank or GoR is not valid.")
        last = tournament_date(self.egd_extra["egd_last_tournament"] or "")
        if last:
            years = (dt.date.today() - last).days / 365.25
            if years > self.cfg.registration.gor_outdated_years:
                hints.append(f"Last EGD tournament {self.egd_extra['egd_last_tournament']} was "
                             f"{years:.0f} years ago - the GoR may be outdated; correct it if needed.")
        self.hint.config(text="  ".join(hints))

    # ------------------------------------------------------------ players file

    def reload_players(self):
        try:
            pl = load_players(self.dir, self.rounds)
        except OdsError as e:
            messagebox.showerror("players.ods", str(e))
            return False
        self.players = pl.players
        self._file_mtime = self.path.stat().st_mtime if self.path.exists() else None
        self._fill_table()
        return True

    def _poll_file(self):
        try:
            mtime = self.path.stat().st_mtime if self.path.exists() else None
            if mtime != self._file_mtime:
                selected = self.editing_id
                if self.reload_players() and selected is not None:
                    self._select_in_table(selected, load_form=False)
        finally:
            self.root.after(FILE_POLL_MS, self._poll_file)

    def _fill_table(self):
        self.table.delete(*self.table.get_children())
        for p in sorted(self.players, key=lambda p: p.id):
            rounds = " ".join(str(r) if p.plays(r) else "-" for r in range(1, self.rounds + 1))
            gor = "" if p.gor is None else f"{p.gor:.0f}"
            self.table.insert("", "end", iid=str(p.id), values=(
                p.id, p.name, str(p.rank or ""), gor, p.country, p.club, rounds,
                "x" if p.joker else ""))
        jokers = sum(p.joker for p in self.players)
        n = len(self.players)
        self.count_label.config(text=f"{n} player{'s' if n != 1 else ''}\n{jokers} joker{'s' if jokers != 1 else ''}")
        if self.index:
            self._search()

    def _write(self, players: list[Player]) -> bool:
        lock = self.path.with_name(f".~lock.{self.path.name}#")
        if lock.exists():
            messagebox.showerror("players.ods", "players.ods is open in LibreOffice.\n"
                                 "Save and close it there first, then try again.")
            return False
        save_players(self.dir, players, self.rounds)
        self.players = players
        self._file_mtime = self.path.stat().st_mtime
        self._fill_table()
        return True

    def submit(self):
        if not self.reload_players():
            return
        try:
            if self.editing_id is None:
                player = self._form_player(self.players)
                players = self.players + [player]
            else:
                others = [p for p in self.players if p.id != self.editing_id]
                if len(others) == len(self.players):
                    raise RegistrationError(f"ID {self.editing_id} is no longer in players.ods")
                player = self._form_player(others)
                player.id = self.editing_id
                players = others + [player]
        except (RegistrationError, RankError) as e:
            messagebox.showerror("Player", str(e))
            return
        if self._write(players):
            verb = "Added" if self.editing_id is None else "Saved"
            self.list_status.config(text=f"{verb} ID {player.id}: {player.name}")
            self.clear_form()

    def remove(self):
        if self.editing_id is None:
            return
        p = next((p for p in self.players if p.id == self.editing_id), None)
        if p and messagebox.askyesno("Remove player", f"Remove ID {p.id} {p.name} from the list?"):
            self.reload_players()
            if self._write([x for x in self.players if x.id != p.id]):
                self.clear_form()

    def _select_in_table(self, pid: int, load_form: bool = True):
        if self.table.exists(str(pid)):
            self._suppress_select = not load_form
            self.table.selection_set(str(pid))
            self.table.see(str(pid))

    _suppress_select = False

    def _edit_selected(self):
        if self._suppress_select:
            self._suppress_select = False
            return
        sel = self.table.selection()
        if not sel:
            return
        p = next((x for x in self.players if x.id == int(sel[0])), None)
        if p is None:
            return
        self.editing_id = p.id
        self._extra_hint = ""
        self.vars["surname"].set(p.surname)
        self.vars["first_name"].set(p.first_name)
        self.vars["rank"].set(str(p.rank or ""))
        self.vars["gor"].set("" if p.gor is None else f"{p.gor:g}")
        self.vars["pin"].set(p.pin)
        self.vars["country"].set(p.country)
        self.vars["club"].set(p.club)
        self.vars["notes"].set(p.notes)
        self.joker_var.set(p.joker)
        for i, v in enumerate(self.round_vars):
            v.set(p.plays(i + 1))
        self.egd_extra = {"egd_gor": p.egd_gor, "egd_last_tournament": p.egd_last_tournament}
        self.form_title.config(text=f"Edit ID {p.id}")
        self.submit_button.config(text="Save changes")
        self.remove_button.state(["!disabled"])
        self._update_hints()

    def show_check(self):
        if not self.reload_players():
            return
        issues = check_players(self.players, self.cfg)
        win = tk.Toplevel(self.root)
        win.title("Registration check")
        text = tk.Text(win, width=100, height=20, wrap="word")
        text.pack(fill="both", expand=True, padx=6, pady=6)
        text.tag_configure("error", foreground="#c62828")
        text.tag_configure("warning", foreground="#b35c00")
        if not issues:
            text.insert("end", "No problems found.\n")
        for i in issues:
            text.insert("end", f"{i.level.capitalize()}: {i.message}\n", i.level)
        text.config(state="disabled")
        ttk.Button(win, text="Close", command=win.destroy).pack(pady=(0, 6))


def run(directory: Path, cfg: Config, refresh_list: bool | None = None) -> None:
    root = tk.Tk()
    RegistrationApp(root, directory, cfg, refresh_list)
    root.mainloop()
