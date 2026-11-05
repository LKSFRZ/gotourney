# Clarifying questions – tournament rules

Write your answers below each question, after "Answer:".

## General

0. `gor to elo conversion.txt` is empty. Did you mean to paste something into it?
   Answer:

## Rating update (TGoR)

1. Which GoR formula? The EGD changed its rating system in 2021. Use the current EGD
   formula (rating-dependent `con` and `a`, plus the bonus term), or something simpler
   such as plain Elo with a fixed K?
   Answer: Current formula

2. What does "higher k-factor" mean exactly?
   (a) EGD's `con` multiplied by a factor, e.g. x3, or
   (b) `con` replaced by one fixed K for everyone?
   Should the EGD bonus term stay?
   Answer: a) but remove the bonus term

3. When are ratings updated? Assumption: all games in a round are rated from the TGoR
   values before that round, and everyone is updated together after the round.
   Is that right? (The alternative is to update after each single game, in the order
   results come in.)
   Answer: The Assumption is correct

4. Starting TGoR for players without a GoR (no PIN, or no rated games). Should their
   rating come from their declared rank (1k = 2000, 1d = 2100, ...), or would you set
   it by hand?
   Answer: from their declared rank

5. Which GoR counts as the start value? The current EGD GoR on registration day, or the
   GoR at a fixed date?
   Answer: The current EGD GoR on registration day

## Handicap

6. What decides "full handicap"? The difference in current TGoR (e.g. 100 points per
   stone), the declared ranks, or the starting GoR? How is it rounded, and is there a
   maximum (9 stones)?
   Answer: The difference in current TGoR,rounded to the nearest 100 and then one stone per 100 points.

7. What komi goes with each handicap? E.g. 6.5 for even games, 0.5 for handicap games.
   And does handicap 1 mean "no komi, black plays first"?
   Answer: yes, but komi is part of the tournament settings

8. What are the other handicap options, and who chooses? E.g. "full minus N", a cap,
   or even games. Is it set for the whole tournament, for each round, or for each
   single game in the round file?
   Answer: For each single game in the round file, but it should be setby default. The players can agree to a different one, which would then be entered in the rounds file. The "full minus N" can be a setting. Handicaps should also be capped at 9

9. Rating handicap games. Assumption: the EGD method, where each stone shifts the
   expected result by about 100 GoR and komi is accounted for. Is that what you want?
   Answer: yes

## Pairing

10. What exactly should the pairing minimise? The sum of |dTGoR|, or the sum of squares?
    Squares avoid one very uneven pair and favour many medium ones.
    Answer:sum of squares sounds good

11. How is the same-club penalty counted? Proposal: add it in GoR points, e.g.
    "same club counts like 150 extra points of difference". Should the same idea apply
    to the same country, or to family members?
    Answer: just to the club for now. And yes add it to the TGoR difference

12. Are rematches strictly forbidden? Or may they happen as a last resort if no pairing
    is possible otherwise? That can happen with few players.
    Answer: rematches are strictly forbidden for the pairing algorithm, but the tournament director may pair them by hand.

13. Odd number of players: who gets the bye? For example the lowest TGoR, or someone who
    hasn't had a bye yet. Should a bye or a skipped round leave TGoR unchanged?
    Answer: In the player registration you can mark a Joker-Player that does not play in uneven rounds

14. Colours in even games: nigiri (random), or balanced across rounds?
    Answer: balanced across rounds as far as possible

15. Board order: highest TGoR on board 1?
    Answer: yes

## Results and final ranking

16. Which results do you need? Jigo (counted as 1/2)? Forfeits (suggestion: no rating
    change)? Both players lose?
    Answer: Jigo can be possible, forfeits count like the game did not happen.

17. Tie-breaker: what if two players end with the same TGoR? And how many decimal places
    should TGoR be stored and shown with?
    Answer: no decimal places. TGoR is rounded to the next integer. Tie breaker goes to the person with the lower starting GoR. If that is also the same, then random.

18. Wall list: is your specification still to come? Or should I propose columns from
    these rules: place, name, club, starting GoR, results per round, TGoR after each
    round, final TGoR?
    Answer: example in T260926G.h9 This format is standard, but includes MacMahon scores. These should not be in there, since it is not a MacMahon Tournament

## Other

19. EGD upload: should the tournament be sent to the EGD as normal games, which then get
    normal GoR updates? If so, I'd add an export of the results file the EGD expects.
    Answer: yes, this is important, the wall list must be in the appropriate format.

---

# Round 2 – follow-up questions

Write your answers below each question, after "Answer:".

## Still open from round 1

20. Question 0: `gor to elo conversion.txt` is still empty. Was it meant to hold the
    rating formula or a rank-to-GoR table? If you have a reference for the exact EGD
    formula (especially the handicap/komi adjustment), please paste it there.
    Answer: yes placeholder. if you can look up the EGD documentation then do that instead

21. Language: is Python OK?
    Answer:yes

## Rating

22. Rounding of TGoR: round to an integer after every round (and use the rounded value
    from then on), or keep full precision internally and round only for display?
    Answer: only for display

23. Starting rating for a player who has a PIN but a clearly outdated GoR (e.g. no games
    for 10 years): always use the EGD GoR, or may the director overwrite it in
    `players.ods`? (Proposal: the GoR column is editable, the tool uses whatever is there.)
    Answer: Exactly,the director has to overwrite it but should get a warning if they need to take action

## Handicap and komi

24. Rounding the TGoR difference: is exactly 150 one stone or two? (Proposal: halves round up.)
    Answer: halves round down

25. Komi: one setting for even games (e.g. 6.5) and one for handicap games (e.g. 0.5)?
    Answer: yes

26. Handicap 1: weaker player takes black, no handicap stones, komi 0.5. Correct?
    Answer:yes

27. With "full minus N": does a difference that would give 1 stone (after subtracting N)
    become an even game with komi, or a handicap-1 game?
    Answer: a handicap-1 game

## Joker

28. Only one joker per tournament, or several (one is chosen per round)?
    Answer: several

29. Does the joker get a TGoR and appear on the wall list and in the EGD upload like
    everybody else?
    Answer: Yes

30. What if a round has an odd number of players and the joker is not registered for
    that round (or there is no joker)? Proposal: the tool stops and asks the director
    to fix the registration.
    Answer: yes, ask the director to nominate a joker

## Colours

31. Does colour balance count only even games, or also handicap games (where the
    weaker player is always black)?
    Answer: only even games

## Wall list / EGD export

32. The example has these columns between club and the rounds: MMS, wins, MMS again,
    then two tie-breakers. What should our file show instead? Proposal:
    `Wins  StartGoR  FinalTGoR`.
    Answer: That is fine

33. Forfeits count as if the game did not happen. In the `.h9`, should they appear as
    `0=` (not played), or with the EGD forfeit notation (e.g. `12+!/w`) so the EGD
    knows about them but doesn't rate them?
    Answer: 0=

34. Should the tool also write an editable `wall_list.ods` from which the `.h9` is
    generated, or is it enough to generate the `.h9` directly from the round files?
    Answer: That would be great

35. Header fields: the tournament code (TC, e.g. `T260926G`), class (CL) and the
    "submitted by" comment. Should these simply be settings in `tournament.toml`?
    And should `HA[h9]` reflect the handicap settings (e.g. `h8` with "full minus 1")?
    Answer: Yes this is metadata that has to be specified in the tournament settings. The Tournament code is left empty as it is decided after upload to the egd

36. Players without an EGD PIN: in the `.h9`, leave the `|PIN` part empty?
    Answer: yes

## Hand edits

37. If the director changes a pairing by hand after `gotourney pair`, e.g. swaps two
    players, should the tool recompute the default handicap and komi for the changed
    boards (when checking results), or always trust what is written in the file?
    Answer: The manual pairing should happen before the automatic pairing. The automatic pairing only pairs playes that have not been paired manually

---

# Round 3 – last few questions

Write your answers below each question, after "Answer:".

38. Several jokers: in an odd round, which joker sits out? Proposal: the joker who has
    sat out the fewest rounds so far; if tied, the one with the lowest TGoR.
    Answer: the one with the most games already played, otherwise by random choice

39. Warning for an outdated GoR: when should the tool warn? Proposal: the player's last
    EGD tournament is more than 5 years ago (configurable). Also warn when the declared
    rank and the GoR differ by more than 300 points?
    Answer: Sounds good

40. Does a forfeited game count as "already played" for the rematch rule, or may the
    same two players be paired again later?
    Answer: does count as already played

41. `HA[...]` in the .h9 header: the example says `h9`. With "full minus 1", should it
    say `h8`, or something else? (I don't know the EGD's exact convention here.)
    Answer: Standard handicap reduction, prefixed with h (e.g. h2 = handicap reduced by 2 stones; h0 = full handicap; h9 = no handicap). The system infers colours and handicap per game when not specified. Implicit handicap never exceeds (9 − reduction) — e.g. in a h2 tournament, implicit handicap ≤ 7. Per-game handicap overrides this when set.

42. Wins column in the .h9: does a jigo count as half a win?
    Answer: yes

43. Komi in rating: the EGD formula uses only the number of handicap stones, not komi.
    Is that fine, even though komi is a setting?
    Answer: yes, the setting is only to choose between accepted standards, 6.5 or 7, or 7.5 for chinese rules
