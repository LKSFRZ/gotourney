"""The double-clickable program: starts the web interface and shows a small control window.

Without arguments it starts the local web interface, opens the browser and shows a window with
"Open in browser", "Open tournament folder ..." and "Quit" (closing the window stops the program).
With arguments it behaves like the ``gotourney`` command line, e.g. ``gotourney-app pair -d folder``.
"""

from __future__ import annotations

import locale
import os
import sys
import threading
import urllib.parse
import webbrowser
from pathlib import Path

TEXTS = {
    "en": {
        "title": "Go Tournament",
        "running": "The tournament program is running.",
        "browser_note": "It is shown in your web browser. If you closed the browser tab:",
        "open_browser": "Open in browser",
        "open_folder": "Open tournament folder …",
        "choose_folder": "Choose a tournament folder (it contains tournament.toml)",
        "not_tournament": "This folder is not a tournament: it has no tournament.toml.",
        "quit_note": "Closing this window stops the program. Your files are always saved.",
        "quit": "Quit",
        "already": "The tournament program is already running – it was opened in your browser.",
    },
    "de": {
        "title": "Go-Turnier",
        "running": "Das Turnierprogramm läuft.",
        "browser_note": "Es wird in Ihrem Webbrowser angezeigt. Falls Sie den Browser-Tab geschlossen haben:",
        "open_browser": "Im Browser öffnen",
        "open_folder": "Turnierordner öffnen …",
        "choose_folder": "Turnierordner wählen (er enthält tournament.toml)",
        "not_tournament": "Dieser Ordner ist kein Turnier: Er enthält keine tournament.toml.",
        "quit_note": "Wenn Sie dieses Fenster schließen, wird das Programm beendet. Ihre Dateien sind immer gespeichert.",
        "quit": "Beenden",
        "already": "Das Turnierprogramm läuft bereits – es wurde in Ihrem Browser geöffnet.",
    },
}


def system_language() -> str:
    for var in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        if os.environ.get(var, "").lower().startswith("de"):
            return "de"
    try:
        code = locale.getlocale()[0] or ""
    except ValueError:
        code = ""
    if sys.platform.startswith("win"):
        try:
            import ctypes
            code = locale.windows_locale.get(ctypes.windll.kernel32.GetUserDefaultUILanguage(), code)
        except Exception:                          # noqa: BLE001 - only a guess for the window language
            pass
    return "de" if code.lower().startswith(("de", "german")) else "en"


def _log_to_file() -> None:
    """A windowed program has no console (sys.stdout is None): write messages to a log file instead."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    from .web import config_dir
    try:
        config_dir().mkdir(parents=True, exist_ok=True)
        log = open(config_dir() / "gotourney.log", "a", encoding="utf-8", buffering=1)
    except OSError:
        log = open(os.devnull, "w")
    sys.stdout = sys.stdout or log
    sys.stderr = sys.stderr or log


def main() -> None:
    _log_to_file()
    if len(sys.argv) > 1:                          # used like the command line
        from .cli import app
        app()
        return
    from .web import (DEFAULT_PORT, create_app, free_port, make_server, port_free, remember,
                      running_instance)
    tx = TEXTS[system_language()]
    port = DEFAULT_PORT
    if not port_free(port):
        if running_instance(port):                 # started a second time: just show the first one
            webbrowser.open(f"http://127.0.0.1:{port}/")
            _message(tx["title"], tx["already"])
            return
        port = free_port()

    app = create_app(None)
    app.config["EGD"].ensure()
    server = make_server(app, port)
    threading.Thread(target=server.run, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    threading.Timer(0.8, lambda: webbrowser.open(base + "/")).start()

    def open_folder(path: str) -> None:
        remember(Path(path).resolve())
        query = urllib.parse.urlencode({"path": path})
        webbrowser.open(f"{base}/launch/{app.config['LAUNCH']}?{query}")

    try:
        window(tx, base, open_folder)
    except Exception as e:                         # noqa: BLE001 - no display / no Tk: run in the console
        print(f"{tx['running']} {base}   (Ctrl+C)  [{e}]")
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
    finally:
        server.close()


def _message(title: str, message: str) -> None:
    try:
        import tkinter
        from tkinter import messagebox
        root = tkinter.Tk()
        root.withdraw()
        messagebox.showinfo(title, message)
        root.destroy()
    except Exception:                              # noqa: BLE001
        print(message)


def window(tx: dict, base: str, open_folder) -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    from .config import CONFIG_FILE

    root = tk.Tk()
    root.title(tx["title"])
    try:
        icon = tk.PhotoImage(file=str(Path(__file__).parent / "data" / "icon.png"))
        root.iconphoto(True, icon)
    except tk.TclError:
        pass
    root.resizable(False, False)
    frame = ttk.Frame(root, padding=18)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="○●  " + tx["title"], font=("TkDefaultFont", 15, "bold")).pack(anchor="w")
    ttk.Label(frame, text=tx["running"]).pack(anchor="w", pady=(10, 2))
    ttk.Label(frame, text=tx["browser_note"], wraplength=380, foreground="#555").pack(anchor="w")
    link = ttk.Label(frame, text=base, foreground="#1a5fb4", cursor="hand2")
    link.pack(anchor="w", pady=(2, 10))
    link.bind("<Button-1>", lambda e: webbrowser.open(base + "/"))

    def choose() -> None:
        folder = filedialog.askdirectory(parent=root, title=tx["choose_folder"], mustexist=True)
        if not folder:
            return
        if not (Path(folder) / CONFIG_FILE).is_file():
            messagebox.showwarning(tx["title"], tx["not_tournament"], parent=root)
            return
        open_folder(folder)

    buttons = ttk.Frame(frame)
    buttons.pack(fill="x")
    ttk.Button(buttons, text=tx["open_browser"], command=lambda: webbrowser.open(base + "/")).pack(side="left")
    ttk.Button(buttons, text=tx["open_folder"], command=choose).pack(side="left", padx=8)
    ttk.Separator(frame).pack(fill="x", pady=12)
    ttk.Label(frame, text=tx["quit_note"], wraplength=380, foreground="#555").pack(anchor="w")
    ttk.Button(frame, text=tx["quit"], command=root.destroy).pack(anchor="e", pady=(10, 0))
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    root.mainloop()


if __name__ == "__main__":
    main()
