# Go Tournament Organisation Tool – Plan

Status: **draft, to iterate on**. Decisions come from `tournament rules.txt` and the
answers in `questions.md` (rounds 1–3). All questions are answered.

## 0. Guiding principles

- Command-line tools written in **Python**; each step reads and writes
  **LibreOffice Calc files (`.ods`)**.
- Every `.ods` file can be edited by hand between steps. The tools must accept
  hand edits: tolerant parsing, clear error messages naming the sheet, row and column.
- The `.ods` files are the source of truth. There is no hidden database. A tool
  can be re-run at any time and gives the same result for the same input.
- All files for one tournament live in one tournament directory.
- Final output is a wall list in **EGD `.h9` format** for upload to the EGD.

## 1. Tournament format

- Every player has a **tournament rating TGoR**. It starts at the value in the GoR column
  of `players.ods`. That column is filled from the EGD GoR on registration day; players
  without a GoR get the value of their declared rank (1k = 2000, 1d = 2100, …, 100 points
  per rank). The director may overwrite it by hand (e.g. outdated GoR, see §5.3).
- After each round, TGoR is updated with the **current (2021) EGD formula**, except that
  `con` is multiplied by the tournament parameter `k_factor` and the **bonus term is removed**.
- All games of a round are rated from the TGoR values **before** that round; everyone
  is updated together after the round.
- TGoR is kept at **full precision internally** and **rounded to an integer only for display**.
- **Winner** = highest final TGoR. Tie-break: lower starting GoR ranks higher; if still tied,
  random (seed stored so the result is reproducible).
- Not a McMahon tournament: no MMS columns anywhere.
- Forfeits count as if the game did not happen (no rating change, `0=` in the `.h9`).
- Skipped rounds (joker, absent): TGoR unchanged.

### 1.1 Rating formula

Source: the 2021 EGF rating system as implemented in the `skillratings` crate (`egf.rs`) and
described on the EGD pages (`EGF_rating_system.php`; handicap part from
`EGF_rating_system_old.php`, which still applies). To be checked against the EGD
GoR calculator (`gor_calculator.php`) in unit tests.

For players A and B with TGoR `r_A`, `r_B`, result `S_A` ∈ {1, ½, 0}, and handicap `H`
(number of stones, given to the weaker player):

```
h(H)      = 0                 if H = 0
          = 100 · (H − 0.5)   otherwise          # handicap 1 counts as 50 points
β(r, H)   = −7 · ln(3300 − h(H) − r)              # H is used only for the player who receives the stones
SE_A      = 1 / (1 + exp(β(r_B, H_B) − β(r_A, H_A)))
con(r)    = ((3300 − r) / 200) ^ 1.6
r_A_new   = max(r_A + k_factor · con(r_A) · (S_A − SE_A), −900)
```

- The EGD bonus `ln(1 + exp((2300 − r)/80)) / 5` is **omitted** (as decided).
- Komi does not enter the formula; only the handicap does. The komi setting only chooses
  between accepted standards.
- The −900 lower bound comes from the EGD system.

## 2. Technology

| Concern | Choice |
|---|---|
| Language | Python 3.12 |
| CLI | `typer`: one entry point `gotourney` with subcommands |
| ODS read/write | `odfpy` with a small wrapper (column widths, bold header, frozen header row) |
| Blossom / max-weight matching | `networkx.max_weight_matching` (Edmonds' blossom) |
| EGD access | `requests` against the EGD JSON API |
| Tests | `pytest`, sample tournaments under `tests/data/` |
| Packaging | `pyproject.toml`, run with `uv run` or install with `pipx` |

## 3. Directory layout of a tournament

```
my_tournament/
  tournament.toml       # settings (see §4)
  players.ods           # step 1: registration
  round_1.ods           # step 2: pairing (manual pre-pairings + automatic); results entered here
  round_2.ods
  …
  standings.ods         # TGoR after each round (for checking and announcing)
  wall_list.ods         # step 4: editable wall list
  <name>.h9             # step 5: EGD export, generated from wall_list.ods
```

## 4. Tournament settings (`tournament.toml`)

```toml
[tournament]           # EGD metadata, written to the .h9 header
code    = ""                                   # TC – left empty, assigned by the EGD after upload
name    = "21. Schweriner Drachenschlacht"     # EV
place   = "DE, Schwerin"                       # PC
dates   = ["2026-09-26", "2026-09-27"]         # DT
class   = "A"                                  # CL
time    = 75                                   # TM, minutes
comment = "(submitted by …)"                   # CM
rounds  = 5

[rating]
k_factor = 3.0

[handicap]
reduction     = 0       # "full minus N"; written as HA[h<reduction>] (h0 = full, h9 = no handicap)
komi_even     = 6.5     # accepted standards: 6.5, 7, 7.5 (Chinese rules); written as KM
komi_handicap = 0.5

[pairing]
club_penalty = 150      # added to the TGoR difference of same-club pairs
random_seed  = 12345    # colour choice and random tie-breaks

[registration]
gor_outdated_years = 5    # warn if a player's last EGD tournament is older than this
rank_gor_tolerance = 300  # warn if declared rank and GoR differ by more than this
```

The `.h9` header `HA[...]` is `h<reduction>`: the EGD convention for the standard
handicap reduction (h0 = full handicap, h2 = reduced by 2 stones, h9 = no handicap).

## 5. Step 1 – Player registration (`gotourney players …`)

### 5.1 `players.ods` columns

| Column | Notes |
|---|---|
| ID | Running number, stable, never reused |
| Surname, First name | From EGD when a PIN is given |
| Rank | Declared rank (`5k`, `1d`, …) |
| GoR | Starting TGoR. Filled from EGD or from rank; editable |
| EGD GoR, Last EGD tournament | Read-only info for the director |
| EGD PIN | 8 digits, empty if the player is not in EGD |
| Country, Club | EGD codes (`DE`, `HH`, …) |
| Joker | `x` = may be used as joker (several allowed) |
| R1 … Rn | `x` = plays this round |
| Notes | Free text |

### 5.2 Commands

- `gotourney init <dir>` – creates `tournament.toml` and an empty `players.ods`.
- `gotourney players add --pin 12345678 [--rank 3k] [--rounds 1,2,3] [--joker]`
- `gotourney players add --name "Doe, John" …` – EGD lookup by name; choose if several match.
- `gotourney players sync` – refresh name, country, club, EGD GoR and last tournament from EGD;
  report changes. The GoR column (starting TGoR) is only filled when empty, never
  overwritten, so hand edits survive. Frozen once round 1 has been paired.
- `gotourney players check` – duplicate PINs, invalid ranks, unknown PINs, and for each
  round whether the number of players is even or can be made even with a joker.

### 5.3 Warnings that need action by the director
- GoR probably outdated (last EGD tournament older than `gor_outdated_years`) → check and overwrite GoR.
- No GoR and no rank → cannot start.
- Declared rank differs from GoR by more than `rank_gor_tolerance` (300 points).
- Odd number of players in a round and no joker available → nominate a joker.

### 5.4 EGD access
- `GetPlayerDataByPIN.php?pin=<PIN>` and `GetPlayerDataByData.php?lastname=…&name=…`
  on `www.europeangodatabase.eu/EGD/` (to verify; the server blocks some automated
  requests, so we may need a proper User-Agent or the offline file).
- Offline fallback: downloaded full EGD player list.
- Responses cached in the tournament directory.

## 6. Step 2 – Pairing (`gotourney pair <round>`)

### 6.1 Workflow
1. (Optional) The director enters **manual pairings** first in `round_r.ods`
   (`gotourney pair <r> --template` writes an empty round file, or they create the boards
   by hand). Manual boards may be rematches; handicap/komi may be left empty.
2. `gotourney pair <r>` keeps all manual boards, fills in default handicap/komi/colours
   where they are empty, and pairs **only the remaining players** automatically.
3. The director can still edit handicap/komi per game afterwards (players agree on a
   different handicap); the tools always trust what is in the file.

### 6.2 Algorithm for the remaining players
1. Participants = players marked for round *r* who are not on a manual board.
2. If the number is odd, one joker sits out (§6.3). No joker available → stop and ask
   the director to nominate one.
3. Complete graph over the participants, without pairs that already played each other
   (**rematches forbidden for the algorithm**; forfeited games count as played).
4. Cost of a pair = `(|TGoR_A − TGoR_B| + club_penalty · [same club])²`;
   matching weight = `C − cost`, with `C` large enough that all weights are positive.
5. `max_weight_matching(maxcardinality=True)` → minimal total cost among perfect matchings.
   No perfect matching possible → stop with a message so the director pairs by hand.

### 6.3 Joker
- Several players can be marked as joker. In a round with an odd number of participants,
  exactly one joker sits out: the joker with the **most games already played**;
  if tied, a random choice (stored seed).
- Jokers have a TGoR and appear on the wall list and in the `.h9` like everybody else.

### 6.4 Handicap and komi (defaults)
- `full = round_half_down(|ΔTGoR| / 100)` (e.g. 150 → 1, 151 → 2)
- `H = max(min(full, 9) − reduction, 0)`, so the implicit handicap never exceeds `9 − reduction`
  (e.g. ≤ 7 in an h2 tournament). A handicap entered per game in the round file overrides this.
- H = 0: even game, komi `komi_even`, colours balanced (§6.5)
- H = 1: weaker player black, no stones, komi `komi_handicap`
- H ≥ 2: weaker player black with H stones, komi `komi_handicap`

### 6.5 Colours in even games
- Only even games count. The player with more whites in even games gets black;
  if equal, random with the stored seed.

### 6.6 Board order
- Board 1 = pair with the highest TGoR; manual boards are sorted in as well.

### 6.7 `round_r.ods` columns

| Board | White ID | White name | White TGoR | Black ID | Black name | Black TGoR | Handicap | Komi | Manual | Result |
|---|---|---|---|---|---|---|---|---|---|---|

- `Manual` = `x` for boards entered by the director.
- Results: `1-0` (white wins), `0-1` (black wins), `jigo` (also `½-½`, `0.5-0.5`),
  `1-0!` / `0-1!` = forfeit (as if not played).
- `gotourney pair` refuses to overwrite a round that already has results, unless `--force`.

## 7. Step 3 – Results and standings

- Results are entered **by hand** in the Result column.
- `gotourney results check <round>`: every board has a valid result; flags players
  appearing twice, players not registered for the round, and (warning only) rematches.
- `gotourney standings [--round r]`: TGoR after each round → `standings.ods`.

## 8. Step 4 – Wall list (`gotourney wall`)

- Reads everything, computes final TGoR and places, writes **`wall_list.ods`** (editable).

## 9. Step 5 – EGD export (`gotourney h9`)

Generates the `.h9` from `wall_list.ods` (so hand corrections are included).

### 9.1 Format (from the example `T260926G.h9`)

Header (TC empty, filled in by the EGD):
```
; TC[]
; CL[A]
; EV[21. Schweriner Drachenschlacht]
; PC[DE, Schwerin]
; DT[2026-09-26,2026-09-27]
; HA[h9]
; KM[6.5]
; TM[75]
; CM[(submitted by …)]
;.
```

One line per player, fixed-width columns:
```
 1 Maekawa Kaku          6d DE  K     4  2187  2254  5+/b    6+/w    3+/w    2+/w    4-/w     |20633162
```
- Place, `Surname Firstname` (spaces inside a name part become `_`), rank, country, club.
- Score columns: **Wins** (jigo = ½), **Start GoR**, **Final TGoR** (rounded).
- One field per round: `<opponent place><result>/<colour><handicap>`
  - result `+` win, `-` loss, `=` jigo; colour `w`/`b`; handicap omitted when 0.
  - `0=` = did not play (joker, absent, forfeit).
- `|<EGD PIN>` at the end; empty for players without a PIN.

## 10. Implementation order (milestones)

1. ✅ **Skeleton**: project setup, CLI entry point, `tournament.toml`, ODS helper, tests.
2. ✅ **Data model**: `Player`, `Rank`, `Game`, `Round`, `Tournament`; load/save `.ods`.
3. ✅ **Rating engine**: formula of §1.1; verified against the reference values of the
   `skillratings` EGF implementation (the EGD site blocks automated access to its calculator).
4. ✅ **Registration**: `init`, `players add/list/check` without EGD.
5. **EGD client**: lookup by PIN and name, `players sync`, warnings, cache, offline list.
6. **Results and standings**: parse round files, `results check`, `standings`.
7. **Wall list and EGD export**: `wall_list.ods`, `.h9`; test by re-creating the example layout.
8. **Pairing**: manual boards, cost function, blossom matching, joker, handicap, colours,
   board order; tests with hand-checked scenarios (rematch blocking, club penalty, odd counts).
9. **Polish**: nicer formatting, printable pairings/standings.
