# gotourney

Command line tools for running a Go tournament with **tournament ratings (TGoR)** instead of
McMahon scores. Every player starts at their EGD GoR, capped at a configurable top bar. After each
round all ratings are updated with the EGD formula, using a higher k-factor. Pairings minimise the
TGoR difference (blossom algorithm), with full handicap by default. The winner is the player with
the highest final TGoR.

The tools read and write LibreOffice Calc files (`.ods`), so every step can be checked and edited
by hand. Features:

- **Registration** with a window that autocompletes from the EGD player list (works offline). You can
  record extra data per player, as free text or with dropdowns.
- **Pairing**, with boards you fix yourself ("finalized"), latecomers paired after the round has started, jokers for odd rounds and configurable pairing rules (avoid
  same club, children preferably against children, …). Each round also gets two printable pairing
  PDFs: one by board, one with all players sorted by surname.
- **Results** are entered as `x` marks in the round file. Standings are written as `.ods` and as a
  printable cross table PDF.
- **Wall list** and the **EGD result file** (`.h9`).
- **Award ceremony** slides (PDF), with configurable prizes. Club codes are shown as full club names,
  using the built-in `src/gotourney/data/clubs.csv` (from the
  [EGD club name list](https://info.go361.eu/wiki/EGD-Clubnamen) of the Karlsruher Go-Turnierhandbuch).
  A `clubs.csv` in the tournament folder can add or override clubs.
- PDFs in English, German, French or a custom language.

The full documentation is in [`Guide.pdf`](Guide.pdf) (English) and
[`Anleitung.pdf`](Anleitung.pdf) (German).

## Installation

You need:

- **Python 3.11 or newer**, with Tkinter for the registration window;
- **LibreOffice**, to edit the `.ods` files;
- **this project folder** on your computer.

The examples assume the folder is `TournamentOrgaTool` in your home folder.

### Linux

Ubuntu / Debian:

```sh
sudo apt install python3 python3-venv python3-tk fonts-dejavu-core libreoffice-calc
cd ~/TournamentOrgaTool
python3 -m venv .venv
.venv/bin/pip install -e .
source .venv/bin/activate
gotourney --help
```

Other distributions use other package names:

- Fedora: `sudo dnf install python3 python3-tkinter dejavu-sans-fonts libreoffice-calc`
- Arch: `sudo pacman -S python tk ttf-dejavu libreoffice-fresh`

### macOS

1. **Python 3.12 or newer.** Install it from [python.org](https://www.python.org/downloads/); Tkinter is
   included. The `python3` that comes with Apple's developer tools is too old. With Homebrew instead:
   `brew install python@3.12 python-tk@3.12`.
2. **LibreOffice.** Install it from [libreoffice.org](https://www.libreoffice.org/), or with
   `brew install --cask libreoffice`.
3. **The tool.** In the *Terminal* app:

   ```sh
   cd ~/TournamentOrgaTool
   python3 -m venv .venv
   .venv/bin/pip install -e .
   source .venv/bin/activate
   gotourney --help
   ```

4. **Fonts (optional).** The PDFs use Arial Unicode or Arial, which come with macOS. For the same look
   as on Linux, install DejaVu: `brew install --cask font-dejavu`.

### Windows

1. **Python 3.12 or newer.** Install it from [python.org](https://www.python.org/downloads/). Tick
   **"Add python.exe to PATH"** in the installer, and keep *tcl/tk and IDLE* selected (the default).
2. **LibreOffice.** Install it from [libreoffice.org](https://www.libreoffice.org/).
3. **The tool.** In PowerShell:

   ```powershell
   cd $HOME\TournamentOrgaTool
   py -m venv .venv
   .venv\Scripts\pip install -e .
   .venv\Scripts\activate
   gotourney --help
   ```

   PowerShell may refuse to run `activate` ("running scripts is disabled"). Either run
   `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, or call the tool without activating:
   `.venv\Scripts\gotourney --help`.
4. **Fonts (optional).** Without extra fonts the PDFs use Arial, and the star on the award slides
   becomes `*`. For all symbols, install the free [DejaVu fonts](https://dejavu-fonts.github.io/):
   right-click `DejaVuSans.ttf` and `DejaVuSans-Bold.ttf`, then choose *Install*.

### After the installation

- **Every new terminal:** activate the environment again (`source .venv/bin/activate`; Windows:
  `.venv\Scripts\activate`). Or call the tool by its full path (`.venv/bin/gotourney`; Windows:
  `.venv\Scripts\gotourney`). With the environment active, `python -m gotourney` works too.
- **pipx:** `pipx install -e ~/TournamentOrgaTool` makes `gotourney` available in every terminal
  without activating anything.
- **EGD player list:** run `gotourney egd update` once to download it. It is cached in
  `~/.cache/gotourney` and refreshed daily, so search keeps working at a venue without internet.
- **Font:** to choose a font for the PDFs yourself, set `GOTOURNEY_FONT` to a `.ttf` file. It must
  contain ○ and ●.
- **Updating:** replace the project folder with the new version and run `pip install -e .` again.
  Tournament folders are not affected.

## Quick start

```sh
gotourney init my_tournament --name "Spring Go Cup 2026" --rounds 5 --language en
cd my_tournament
# edit tournament.toml (place, dates, k-factor, top bar, pairing rules, prizes, ...)

gotourney gui                  # register players (EGD autocomplete)
gotourney players check

gotourney pair 1               # round_1.ods + printable round_1.pdf / round_1_alphabetical.pdf
gotourney start 1              # round begins: all boards finalized; 'pair 1' now only pairs latecomers
# enter the results in round_1.ods: x under "White win", "Draw" or "Black win"
gotourney results check 1
gotourney standings            # standings.ods and standings.pdf
gotourney pair 2               # ... and so on for every round

gotourney wall                 # final wall list (wall_list.ods)
gotourney h9                   # result file for the EGD
gotourney awards               # slides for the award ceremony (awards.pdf)
```

Every command accepts `--help`, and `-d <folder>` selects the tournament folder. After each step the
tool prints **Next steps**, so you always know what to do next (switch off with
`GOTOURNEY_NO_HINTS=1`).

## Web interface (preview)

```sh
gotourney web                  # opens the browser; or: gotourney web -d my_tournament
```

A local web page (only reachable from your own computer) with an overview of the tournament and a
button for the next step: create or open a tournament, pair and start rounds, check results, create
standings, wall list, EGD file and award slides. Results are still entered in the round file
(LibreOffice opens with one click); entering them in the browser, registration and a settings form
will follow. The interface is available in English and German.

## Development

```sh
.venv/bin/pip install -e '.[test]'     # Windows: .venv\Scripts\pip install -e ".[test]"
.venv/bin/pytest
```

The source code is in `src/gotourney/` and the tests are in `tests/`. The guides are generated from
`docs/guide.html` and `docs/guide_de.html`.
