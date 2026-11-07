"""Texts of the web interface in English and German."""

from __future__ import annotations

LANGUAGES = ("en", "de")

TEXTS: dict[str, dict[str, str]] = {
    "en": {
        "app_title": "Go tournament",
        "language": "Language",
        "home": "Tournaments",
        "dashboard": "Overview",
        "help": "Help",
        # home page
        "home_intro": "Run a Go tournament with tournament ratings (TGoR): registration, pairings, results, "
                      "standings, wall list, EGD file and award ceremony – step by step.",
        "recent": "Recently opened",
        "no_recent": "No tournaments opened yet.",
        "open_title": "Open a tournament",
        "open_text": "Folder of an existing tournament (contains tournament.toml):",
        "open_button": "Open",
        "create_title": "New tournament",
        "create_name": "Name of the tournament",
        "create_rounds": "Number of rounds",
        "create_language": "Language of the printouts",
        "create_folder": "Folder (created if needed)",
        "create_button": "Create tournament",
        "lang_en": "English", "lang_de": "German", "lang_fr": "French",
        "not_a_tournament": "{path} is not a tournament folder (no tournament.toml).",
        "created": "Tournament created in {path}.",
        # dashboard
        "players_count": "{n} players registered",
        "rounds_count": "{n} rounds",
        "round_n": "Round {r}",
        "of_rounds": "of {n}",
        "next_step": "Next step",
        "rounds_title": "Rounds",
        "files_title": "Files",
        "col_round": "Round",
        "col_status": "Status",
        "col_results": "Results",
        "col_files": "Files",
        "st_not_paired": "not paired",
        "st_paired": "paired, not started",
        "st_running": "running",
        "st_complete": "complete",
        "st_names": "names to confirm",
        "open_in_office": "open",
        "download": "download",
        "updated_on_disk": "A file was changed outside this page – the page was updated.",
        "locked_note": "{name} is open in LibreOffice.",
        # phases
        "ph_no_players_title": "Register the players",
        "ph_no_players_text": "Add the players with the registration window: search the EGD by name, check rank, "
                              "rounds and extra data, and add them. The window saves everything to players.ods.",
        "ph_registration_title": "Registration",
        "ph_registration_text": "{n} players are registered. Add more players if needed. When registration is "
                                "complete, check it and pair round 1.",
        "ph_names_title": "Round {r}: confirm players given by name",
        "ph_names_text": "round_{r}.ods contains boards where players were typed by name instead of ID. Confirming "
                         "them in the browser will come in a later version; for now run "
                         "'gotourney pair {r}' in a terminal, or enter the IDs in round_{r}.ods.",
        "ph_paired_title": "Round {r} is paired",
        "ph_paired_text": "Print the pairing (by board and alphabetical) and put it up. When the games begin, "
                          "start the round – from then on the boards are fixed.",
        "ph_running_title": "Round {r} is running",
        "ph_running_text": "{done} of {boards} results entered. Enter the results in round_{r}.ods: an x under "
                           "'White win', 'Draw' or 'Black win'. Save in .ods format and close the file – "
                           "this page updates itself.",
        "ph_running_late": "Latecomers registered for this round but not paired: {names}.",
        "ph_complete_title": "Round {r} is complete",
        "ph_complete_text": "Show the standings, then pair round {next}.",
        "ph_finished_title": "The tournament is finished",
        "ph_finished_text": "Create the final wall list, the result file for the EGD and the slides for the "
                            "award ceremony.",
        # actions
        "act_enter_results": "Enter results",
        "act_show_boards": "Show boards",
        "rp_title": "Round {r} – results",
        "rp_progress": "{done} of {boards} results entered",
        "rp_help": "Click the winner of each game; it is saved immediately in round_{r}.ods. "
                   "A forfeit counts as not played and is not rated.",
        "rp_only_missing": "Show only missing results",
        "rp_filter": "Find a player",
        "rp_board": "Board",
        "rp_white": "White",
        "rp_black": "Black",
        "rp_result": "Result",
        "rp_handicap": "Handicap",
        "rp_white_wins": "White wins",
        "rp_jigo": "Jigo",
        "rp_black_wins": "Black wins",
        "rp_more": "More",
        "rp_white_forfeit": "White wins by forfeit",
        "rp_black_forfeit": "Black wins by forfeit",
        "rp_both_forfeit": "Both lose (forfeit)",
        "rp_clear": "Clear result",
        "rp_forfeit_short": "forfeit",
        "rp_fixed": "fixed",
        "rp_locked": "round_{r}.ods is open in LibreOffice. Results cannot be saved here until it is saved and "
                     "closed there.",
        "rp_later": "Later rounds are already paired. Correcting a result here changes the ratings, but not the "
                    "pairings of the later rounds.",
        "rp_all_done": "All results of round {r} are entered.",
        "rp_saved": "Saved",
        "rp_error": "Not saved",
        "rp_no_match": "No board matches.",
        "act_registration": "Open registration window",
        "act_check_players": "Check registration",
        "act_pair": "Pair round {r}",
        "act_repair": "Pair round {r} again",
        "act_pair_late": "Pair latecomers",
        "act_start": "Start round {r}",
        "act_open_round": "Open round_{r}.ods",
        "act_check_results": "Check results",
        "act_standings": "Standings",
        "act_wall": "Wall list",
        "act_h9": "EGD result file",
        "act_awards": "Award slides",
        "act_pdf_board": "Pairing (by board)",
        "act_pdf_alpha": "Pairing (A–Z)",
        "confirm_repair": "Pair round {r} again? All boards without 'Finalized' get new pairings.",
        "confirm_start": "Start round {r}? The boards are fixed from now on.",
        # messages
        "msg_paired": "Round {r} paired: {boards} boards.",
        "msg_paired_late": "Latecomers paired on new board(s): {boards}.",
        "msg_nothing_new": "All players of round {r} already have a board.",
        "msg_started": "Round {r} started: {boards} boards are fixed now.",
        "msg_results_ok": "Round {r}: all {boards} results are entered.",
        "msg_results_missing": "Round {r}: {missing} of {boards} results are missing.",
        "msg_written": "Created {name}.",
        "msg_registration_ok": "Registration checked: no errors.",
        "msg_registration_errors": "Registration check: {n} error(s) – please fix them before pairing.",
        "msg_window_opened": "The registration window was opened (it may appear behind the browser).",
        "msg_file_opened": "{name} was opened. Save it in .ods format and close it when you are done.",
        "msg_missing_board": "Board {board}: {white} – {black}",
        "problem": "Not possible",
        "warning": "Note",
        # problems
        "pr_file_open": "{name} is open in LibreOffice. Save and close it there, then try again.",
        "pr_previous_incomplete": "Round {next} cannot be paired yet: round {r} still has missing results. "
                                  "Enter them in round_{r}.ods. A game that will not be played can be entered as a "
                                  "forfeit (x! for the winner, or ! in both win columns).",
        "pr_open_results": "Some boards already have results but are not fixed. Start the round to keep them.",
        "pr_names_need_confirmation": "round_{r}.ods has players given by name. Run 'gotourney pair {r}' in a terminal "
                                      "to confirm them, or enter the player IDs.",
        # help
        "help_title": "How does a tournament work?",
        "help_steps": "1. Register the players.|2. Check the registration and pair round 1.|"
                      "3. Print the pairing and start the round when the games begin.|"
                      "4. Enter the results in the round file; check them.|"
                      "5. Show the standings and pair the next round – until the last round.|"
                      "6. Create the wall list, the EGD result file and the award slides.",
        "help_files": "Everything is stored in the tournament folder as LibreOffice files. You can open and "
                      "correct them by hand at any time; save in .ods format and close them afterwards.",
    },
    "de": {
        "app_title": "Goturnier",
        "language": "Sprache",
        "home": "Turniere",
        "dashboard": "Übersicht",
        "help": "Hilfe",
        "home_intro": "Ein Goturnier mit Turnierwertung (TGoR) ausrichten: Anmeldung, Auslosung, Ergebnisse, "
                      "Tabelle, Wandtabelle, EGD-Datei und Siegerehrung – Schritt für Schritt.",
        "recent": "Zuletzt geöffnet",
        "no_recent": "Noch keine Turniere geöffnet.",
        "open_title": "Turnier öffnen",
        "open_text": "Ordner eines vorhandenen Turniers (enthält tournament.toml):",
        "open_button": "Öffnen",
        "create_title": "Neues Turnier",
        "create_name": "Name des Turniers",
        "create_rounds": "Anzahl der Runden",
        "create_language": "Sprache der Ausdrucke",
        "create_folder": "Ordner (wird bei Bedarf angelegt)",
        "create_button": "Turnier anlegen",
        "lang_en": "Englisch", "lang_de": "Deutsch", "lang_fr": "Französisch",
        "not_a_tournament": "{path} ist kein Turnierordner (keine tournament.toml).",
        "created": "Turnier in {path} angelegt.",
        "players_count": "{n} Spieler angemeldet",
        "rounds_count": "{n} Runden",
        "round_n": "Runde {r}",
        "of_rounds": "von {n}",
        "next_step": "Nächster Schritt",
        "rounds_title": "Runden",
        "files_title": "Dateien",
        "col_round": "Runde",
        "col_status": "Stand",
        "col_results": "Ergebnisse",
        "col_files": "Dateien",
        "st_not_paired": "nicht ausgelost",
        "st_paired": "ausgelost, nicht gestartet",
        "st_running": "läuft",
        "st_complete": "abgeschlossen",
        "st_names": "Namen bestätigen",
        "open_in_office": "öffnen",
        "download": "herunterladen",
        "updated_on_disk": "Eine Datei wurde außerhalb dieser Seite geändert – die Seite wurde aktualisiert.",
        "locked_note": "{name} ist in LibreOffice geöffnet.",
        "ph_no_players_title": "Spieler anmelden",
        "ph_no_players_text": "Melden Sie die Spieler im Anmeldefenster an: in der EGD nach Namen suchen, Rang, "
                              "Runden und Zusatzangaben prüfen und hinzufügen. Das Fenster speichert alles in "
                              "players.ods.",
        "ph_registration_title": "Anmeldung",
        "ph_registration_text": "{n} Spieler sind angemeldet. Melden Sie bei Bedarf weitere an. Wenn die Anmeldung "
                                "abgeschlossen ist, prüfen Sie sie und losen Sie Runde 1 aus.",
        "ph_names_title": "Runde {r}: Spieler mit Namen bestätigen",
        "ph_names_text": "round_{r}.ods enthält Bretter, bei denen Spieler mit Namen statt ID eingetragen sind. Das "
                         "Bestätigen im Browser kommt in einer späteren Version; bis dahin 'gotourney pair {r}' im "
                         "Terminal ausführen oder die IDs in round_{r}.ods eintragen.",
        "ph_paired_title": "Runde {r} ist ausgelost",
        "ph_paired_text": "Drucken Sie die Auslosung (nach Brett und alphabetisch) und hängen Sie sie aus. Wenn die "
                          "Partien beginnen, starten Sie die Runde – ab dann stehen die Bretter fest.",
        "ph_running_title": "Runde {r} läuft",
        "ph_running_text": "{done} von {boards} Ergebnissen eingetragen. Tragen Sie die Ergebnisse in round_{r}.ods "
                           "ein: ein x unter 'White win', 'Draw' oder 'Black win'. Im .ods-Format speichern und die "
                           "Datei schließen – diese Seite aktualisiert sich selbst.",
        "ph_running_late": "Nachzügler, die für diese Runde angemeldet, aber nicht gepaart sind: {names}.",
        "ph_complete_title": "Runde {r} ist abgeschlossen",
        "ph_complete_text": "Zeigen Sie die Tabelle an und losen Sie dann Runde {next} aus.",
        "ph_finished_title": "Das Turnier ist beendet",
        "ph_finished_text": "Erstellen Sie die Wandtabelle, die Ergebnisdatei für die EGD und die Folien für die "
                            "Siegerehrung.",
        "act_enter_results": "Ergebnisse eintragen",
        "act_show_boards": "Bretter anzeigen",
        "rp_title": "Runde {r} – Ergebnisse",
        "rp_progress": "{done} von {boards} Ergebnissen eingetragen",
        "rp_help": "Klicken Sie bei jeder Partie auf den Sieger; das wird sofort in round_{r}.ods gespeichert. "
                   "Kampflose Partien zählen als nicht gespielt und werden nicht gewertet.",
        "rp_only_missing": "Nur fehlende Ergebnisse zeigen",
        "rp_filter": "Spieler suchen",
        "rp_board": "Brett",
        "rp_white": "Weiß",
        "rp_black": "Schwarz",
        "rp_result": "Ergebnis",
        "rp_handicap": "Vorgabe",
        "rp_white_wins": "Weiß gewinnt",
        "rp_jigo": "Jigo",
        "rp_black_wins": "Schwarz gewinnt",
        "rp_more": "Mehr",
        "rp_white_forfeit": "Weiß gewinnt kampflos",
        "rp_black_forfeit": "Schwarz gewinnt kampflos",
        "rp_both_forfeit": "Beide verlieren kampflos",
        "rp_clear": "Ergebnis löschen",
        "rp_forfeit_short": "kampflos",
        "rp_fixed": "fest",
        "rp_locked": "round_{r}.ods ist in LibreOffice geöffnet. Ergebnisse können hier erst gespeichert werden, "
                     "wenn die Datei dort gespeichert und geschlossen ist.",
        "rp_later": "Spätere Runden sind schon ausgelost. Eine Korrektur hier ändert die Wertung, aber nicht die "
                    "Auslosung der späteren Runden.",
        "rp_all_done": "Alle Ergebnisse der Runde {r} sind eingetragen.",
        "rp_saved": "Gespeichert",
        "rp_error": "Nicht gespeichert",
        "rp_no_match": "Kein Brett passt.",
        "act_registration": "Anmeldefenster öffnen",
        "act_check_players": "Anmeldung prüfen",
        "act_pair": "Runde {r} auslosen",
        "act_repair": "Runde {r} neu auslosen",
        "act_pair_late": "Nachzügler auslosen",
        "act_start": "Runde {r} starten",
        "act_open_round": "round_{r}.ods öffnen",
        "act_check_results": "Ergebnisse prüfen",
        "act_standings": "Tabelle",
        "act_wall": "Wandtabelle",
        "act_h9": "EGD-Ergebnisdatei",
        "act_awards": "Folien Siegerehrung",
        "act_pdf_board": "Auslosung (nach Brett)",
        "act_pdf_alpha": "Auslosung (A–Z)",
        "confirm_repair": "Runde {r} neu auslosen? Alle Bretter ohne 'Finalized' werden neu gepaart.",
        "confirm_start": "Runde {r} starten? Die Bretter stehen dann fest.",
        "msg_paired": "Runde {r} ausgelost: {boards} Bretter.",
        "msg_paired_late": "Nachzügler auf neuen Brettern ausgelost: {boards}.",
        "msg_nothing_new": "Alle Spieler der Runde {r} haben bereits ein Brett.",
        "msg_started": "Runde {r} gestartet: {boards} Bretter stehen jetzt fest.",
        "msg_results_ok": "Runde {r}: alle {boards} Ergebnisse sind eingetragen.",
        "msg_results_missing": "Runde {r}: {missing} von {boards} Ergebnissen fehlen.",
        "msg_written": "{name} erstellt.",
        "msg_registration_ok": "Anmeldung geprüft: keine Fehler.",
        "msg_registration_errors": "Anmeldeprüfung: {n} Fehler – bitte vor der Auslosung beheben.",
        "msg_window_opened": "Das Anmeldefenster wurde geöffnet (es erscheint eventuell hinter dem Browser).",
        "msg_file_opened": "{name} wurde geöffnet. Im .ods-Format speichern und schließen, wenn Sie fertig sind.",
        "msg_missing_board": "Brett {board}: {white} – {black}",
        "problem": "Nicht möglich",
        "warning": "Hinweis",
        "pr_file_open": "{name} ist in LibreOffice geöffnet. Dort speichern und schließen, dann erneut versuchen.",
        "pr_previous_incomplete": "Runde {next} kann noch nicht ausgelost werden: In Runde {r} fehlen Ergebnisse. "
                                  "Tragen Sie sie in round_{r}.ods ein. Eine Partie, die nicht gespielt wird, kann als "
                                  "kampflos eingetragen werden (x! beim Sieger oder ! in beiden Siegspalten).",
        "pr_open_results": "Einige Bretter haben schon Ergebnisse, stehen aber nicht fest. Starten Sie die Runde, um "
                           "sie zu behalten.",
        "pr_names_need_confirmation": "round_{r}.ods enthält Spieler mit Namen. Führen Sie 'gotourney pair {r}' im "
                                      "Terminal aus, um sie zu bestätigen, oder tragen Sie die Spieler-IDs ein.",
        "help_title": "Wie läuft ein Turnier ab?",
        "help_steps": "1. Spieler anmelden.|2. Anmeldung prüfen und Runde 1 auslosen.|"
                      "3. Auslosung drucken und die Runde starten, wenn die Partien beginnen.|"
                      "4. Ergebnisse in die Rundendatei eintragen und prüfen.|"
                      "5. Tabelle anzeigen und die nächste Runde auslosen – bis zur letzten Runde.|"
                      "6. Wandtabelle, EGD-Ergebnisdatei und Folien für die Siegerehrung erstellen.",
        "help_files": "Alles wird im Turnierordner als LibreOffice-Dateien gespeichert. Sie können sie jederzeit "
                      "öffnen und von Hand korrigieren; im .ods-Format speichern und danach schließen.",
    },
}


def text(lang: str, key: str, **values) -> str:
    raw = TEXTS.get(lang, TEXTS["en"]).get(key) or TEXTS["en"].get(key, key)
    try:
        return raw.format(**values)
    except (KeyError, IndexError):
        return raw
