# Simulator build — backlog

Owned by the simulator thread. Ids are `S1`, `S2`, ... The betting engine's
backlog is `BACKLOG.md` (ids `B...`) and is never edited from here.
`SIM-HANDOFF.md` is the brief this build works from.

## State on 2026-11-19

| | |
|---|---|
| Built | The test harness (S1). **No simulator yet.** |
| Files | `ff_sim.py`, `test_sim.py`, `sim_baseline.py`, `sim_reverts.py`, this file |
| Simulator suite | `python3 test_sim.py` → **397 checks, ALL PASS** |
| Engine suite | `python3 test_regression.py` → 1801, untouched. No existing file was edited. |
| Next | S4, the opportunity model |

```bash
python3 refresh.py
python3 test_regression.py                  # the engine's count
python3 test_sim.py                         # this build's count
python3 sim_baseline.py --current-week 11   # the yardsticks; about 2 minutes
python3 sim_reverts.py                      # break every behaviour; about 30 minutes
```

`--current-week` is the NFL week now in progress. On 2026-11-19 that is 11,
so Weeks 1 to 10 are graded.

---

## S1. The harness — DONE 2026-11-19

`ff_sim.py` grades a projection. It does not make one.

- **Walks forward.** Every regular-season week from 2024 Week 1. A projector
  is handed the games from earlier weeks and a list of who to project, and
  nothing else. 2023 is warm-up.
- **Two versions of every result.** A: the slate is who was active, and says
  who starts at quarterback. B: the slate is who had been playing for the
  team, with nothing saying who is up.
- **Its own lines.** A ladder of half-point lines around each player's median
  over his last eight games. These are stand-ins, not a book's lines.
- **Three reports.** The stat-line miss; calibration of single lines in
  probability bands; calibration of pairs, where a simulator's own "both
  happen" is scored beside "multiply the two" and beside the correlation
  table.
- **Three yardsticks** to put a simulator beside: season-to-date average,
  last-four average, and the game-log model the engine uses today. And one
  reference that matters more than any of them: knowing nothing about the
  player.

### What the yardsticks scored (`sim_baseline.py`, run 2026-11-19)

Sample: 46 weeks, 2024 Week 1 to 2026 Week 10, 694 games. Players with a
role, active list known. Every range is clustered by game.

**Typical miss of the single number** (half the time the miss is smaller;
mean miss in brackets), on the same player-games for all three:

| stat | player-games | season average | last four | game-log model |
|---|---|---|---|---|
| targets | 5,272 | 2.00 (2.30) | 2.00 (2.32) | 2.00 (2.30) |
| receptions | 5,272 | 1.50 (1.79) | 1.50 (1.80) | 1.50 (1.75) |
| receiving yards | 5,272 | 19.25 (24.60) | 19.50 (25.01) | 18.50 (23.57) |
| carries | 2,194 | 3.33 (4.11) | 3.25 (4.11) | 3.50 (4.37) |
| rushing yards | 2,194 | 20.00 (25.29) | 20.75 (25.69) | 20.50 (25.77) |
| pass attempts | 1,121 | 6.33 (7.63) | 6.25 (7.45) | 5.50 (7.02) |
| completions | 1,121 | 4.33 (5.30) | 4.50 (5.25) | 4.00 (4.85) |
| passing yards | 1,121 | 55.86 (65.94) | 57.25 (65.72) | 51.00 (61.09) |
| passing TDs | 1,121 | 1.00 (1.02) | 1.00 (1.03) | 1.00 (0.97) |

**Calibration of the game-log model**, all yardage and count stats, read on
the side it favoured:

| it said | happened | on legs it favoured OVER | on legs it favoured UNDER |
|---|---|---|---|
| 50-55% | 52.5% | 48.4% | 56.6% |
| 55-60% | 56.1% | 51.8% | 60.3% |
| 60-65% | 60.3% | 56.5% | 64.3% |
| 65-70% | 64.3% | 60.3% | 68.6% |
| 70-75% | 68.4% | 64.7% | 72.5% |
| 75-80% | 72.6% | 68.8% | 76.5% |
| 80-85% | 76.6% | 72.9% | 80.1% |
| 85-90% | 82.0% | 78.9% | 84.4% |
| 90-95% | 87.4% | 84.8% | 89.0% |

About 8,000 to 14,700 legs a band in the first column and 3,100 to 7,400 a
band by side, in 694 games. The 95% ranges are within a point either way
overall and within a point and a half by side.

### What that says, in order of how much it matters

1. **The engine's game-log model is too confident on overs, at every level.**
   What it calls a 60 to 65% over happened 56.5% of the time; a 70 to 75%
   over, 64.7%. Its unders are close to what it says up to about 80%. This
   is the same direction as the bet log (overs 35 of 68 against 42.2
   predicted, unders 10 of 19 against 10.2), now on about 57,000 over legs
   instead of 68. It holds for established receivers too (a median of 6 or
   more targets: a stated 60 to 65% over happened 57.2%, a stated 70 to 75%
   over 66.0%), so it is not only fringe players falling back.
2. **None of the three knows much more than nothing.** "Knowing nothing"
   means saying, for every player, the overall rate at which that stat and
   rung goes over. On the main line the game-log model's Brier score is
   0.2427 against 0.2449 for knowing nothing: a gap of −0.0022 with a
   standard error of 0.0011, which cannot be told from noise. The season
   average (0.2553) and last four (0.2621) are WORSE than knowing nothing.
   So the bar a simulator must clear is the know-nothing figure, not these
   three, and it is printed beside every score for that reason.
3. **The main stand-in line goes over only 43.1% of the time.** A player's
   next game is under his own trailing median more often than over it. Any
   model built on "what he has been doing" inherits this unless it pulls him
   back toward a norm.
4. **Touchdowns are badly calibrated at both ends, by every yardstick.** When
   the game-log blend said 0 to 10%, a touchdown came 16.7% of the time; when
   it said 50 to 60%, 42.3%. The engine has no touchdown model; that row is
   its blend on a log this harness built, and is labelled so.
5. **The weekly stat table hides one game in eight.** Of skill players who
   took an offensive snap, 12.6% have no stat row (tight ends 24.7%,
   receivers 10.7%, backs 5.8%). They are real games with nothing recorded.
   The engine's game log is built from stat rows, so it never sees them.
   This harness grades them as zeros.
6. **Pairs.** Same-team quarterback passing yards with his receiver's
   receiving yards: both went over 29.1% of the time, multiplying says 24.9%,
   the correlation table 28.4%; real lift 1.25 (±0.03), table 1.14.
   Quarterback pass TDs with a teammate's touchdown: real lift 1.34 (±0.05),
   table 1.28. Opposing backs' rushing yards: 0.88 (±0.06), table 0.96. In
   those three cells the table moves the right way and not far enough. Over
   all 331,089 pairs, pricing with the table instead of multiplying changes
   the Brier score by −0.00006 (se 0.00004): not a difference that can be
   told from noise, because the single legs' own error swamps it.
7. **Not knowing who is active.** Of role players projected from "has been
   playing for this team", 17.3% did not play for it (13.8% from Week 5 on).
   3.2% of role players who did play were not on that list at all. Counting
   a player who sat as a zero, the last-four miss on receiving yards goes
   from 25.1 to 27.4. No yardstick reads the slate, so for them the two
   versions agree number for number; that is the null a simulator's gain
   will be measured against.

### How it was checked

- **`sim_reverts.py`**: 257 behaviours of `ff_sim.py` each removed or reversed
  in a copy, one at a time, and the suite run against it: **257 caught, 0
  not** (2026-11-20). Two controls on the runner itself passed: the unbroken
  suite passes there, at the start and again at the end, and a broken week
  key fails. The first full pass caught 142 of 149 and the second 222 of
  228; each miss was a check that could not fail, and was rewritten.
- **Independent review**, three passes, by a reviewer given the code and a
  list of questions and none of the reasoning. The first pass returned twelve
  defects, the second ten, the third five (the last five small: one wrong
  read one miss away from an all-hit band, two reverts not caught, two
  first-game players left off a slate, a joint method set on an object not
  asked, and wording). Every one was acted on. **The fixes made after the
  third pass have not themselves been reviewed**; they are covered by the
  suite and by reverts, and are small: `rate_range`'s handful-of-misses
  rule, the snap-label spelling in `slate_active`, `_states_joint`, and the
  removal of a redundant filter.
- **Leak probe on every graded week**: 1,351,323 yardstick outputs and
  7,228,704 lines, roles and slate fields were identical after the week
  being projected, and everything after it, was overwritten.
- **Fresh clone** (2026-11-20, commit ba7019f, empty data cache, only the
  five files above added): `test_regression.py` 1801 ALL PASS,
  `test_sim.py` 397 ALL PASS, `sim_reverts.py --check` 259 of 259 apply,
  `sim_baseline.py --current-week 11` exit 0 with output identical to the
  working copy's, and the calls documented in `ff_sim.py` run as written.
  `git status` shows the five new files and no change to any other.

What the reviews found that a reader of the numbers would have been misled
by. Kept here because the same mistakes are available again:

- **A Brier score beside "a coin flip is 0.250".** On a ladder of lines most
  rungs are easy, so anything scores well under 0.250. The honest reference
  is the know-nothing rate per stat and rung, and the gap to it needs its
  own error: the game-log model's was −0.0008 with nothing beside it, and is
  noise.
- **Backup quarterbacks, twice.** A former starter still has a starter's
  median, and slate A is "took a snap", which a backup only does when
  something has gone wrong; grading him measured mop-up duty. The first fix
  lined "whoever on the slate threw 20 passes most recently", and that
  dropped a returning starter whenever the man who had filled in for him
  took a snap in the game being graded: a result reaching the test through
  who was on the slate, which the leak probe could not see. Now a
  quarterback has a line only if he STARTED, read from the play-by-play
  (the quarterback behind his team's first pass play; found for 1,932 of
  1,932 team-games). Who starts is announced before kickoff.
- **A 95% range of "rate ± 2 errors".** 40 hits in 40 has a range of exactly
  100% to 100% that way, and a correct 97% reads as wrong. Ranges are
  Wilson's on the effective sample; where every leg hit or missed, each
  game counts once.
- **A "+/-" twice too wide, called a floor.** The pair lift's error was the
  numerator's alone. The two single rates under it move with it game by
  game, so the true error is about half. It is now carried through, and
  agrees with resampling whole games.

And one found while checking the checks: the first version of the revert
runner linked `test_sim.py` into its work directory, Python resolved the
link, imported the unbroken `ff_sim.py`, and reported **0 of 148 reverts
caught**. A result that implausible was easy to see. The runner now carries
two controls on itself, run with every pass, for the case that is not.

---

## Open

| id | what | status |
|---|---|---|
| **S2** | **The test's own settings were chosen, not measured.** | **OPEN.** They define the test, not a projection, and every projector is graded by the same test; they do change what it is a test of and how far apart two projectors look. All of them: a role is a median of 3 targets / 5 carries / 20 pass attempts; the line window is 8 games, with no line under 4; rungs at 0.6, 0.8, 1.0, 1.25 and 1.6 times the median; the main line is the half point above the median; slate B looks back 4 of the team's games; no verdict under 30 games; ranges and verdicts at 95%; under five hits or five misses each game counts once in a range; the yardsticks' "share over the line" is pulled half a game toward 50%; which positions get a projection with no role. The role floors are the ones to replace first: with what real boards actually post, once S3 has enough weeks. |
| **S3** | **Grade against real book lines.** | **OPEN, small sample.** Book lines exist from about 2026-11-06 (about 30 games). The same calibration table on real lines, beside the market's own de-vigged probability, is the Phase 2 test. Worth setting up early so the weeks accumulate. The market's line is a benchmark there, never an input and never a lean. |
| **S4** | **The opportunity model** — team plays, pass rate, each player's share of snaps, targets and carries. Closing spread and total tested as inputs, with and without. | **NEXT.** It is the first projector that reads who is on the slate, so it is the first that can show a gap between versions A and B. Every number it uses must be estimated from the `History` it is handed, or from 2023 only. Bar to clear: the know-nothing reference, then the game-log model. |
| **S5** | **Version B does not know the roster.** | **NOTED.** It lists a player under the team he last played for, and gives the quarterback line to whoever started that team's last game. So it counts a traded player as "did not play" for his old team and misses him on his new one, and in Weeks 1 to 4 it reaches into last season. A weekly roster file would fix it; `ff_data` does not load one (see "Needs"). Version A is the one a live run is, and it does not have this problem. |
| **S6** | **Slate A is "has a snap row or a stat row", not the inactive list; the starter is "threw his team's first pass".** | **NOTED.** A man who dressed and never took a snap is missing rather than a zero. 232 of 24,976 skill-position snap rows had no id to join on; 27 players never have a snap row and appear only in games where they recorded a stat. A starter hurt before his team's first pass play would be read as not having started. |
| **S7** | **A week is the unit of time.** | **NOTED.** A Thursday game is not used for that Sunday. Stricter than the brief asks, and simple. Postseason games are in neither the history nor the test. |
| **S8** | **The leak probe sees only what passes through the frame.** | **STANDING RULE.** A projector that carries its own copy of the data, or a constant typed into one that was worked out over all seasons, is invisible to it. So is a result that decides WHO IS ON THE SLATE: that is how the first quarterback rule leaked. Estimate everything inside `project()`, and when adding anything to a slate, ask whether it was knowable before kickoff. |
| **S9** | **`ff_sim.gamelog_blend` is a copy of `ff_props.threshold_prob`'s arithmetic.** | **PINNED.** The original costs 4 ms a call. `test_sim.py` section 6 runs both on real logs for all nine engine stats and fails by name if they differ. |
| **S10** | **`ff_sim.corr_joint` reads `ff_boost._pair_weight`**, a private name. | **NOTED.** If the engine renames it the import fails and says why. It is the table's r as a plain point estimate. It is not what `ff_boost.joint_error` does, and no table here calls it "the engine's". |

## Needs from the engine thread

Nothing is blocking. Nothing here asks for a change to an engine file.

For its information, each measured above:

1. `threshold_prob` is too confident on overs across the whole range (finding
   1), and on the main line is not distinguishable from knowing nothing
   about the player (finding 2). The harness can grade any change to it in
   about two minutes.
2. `player_series` builds its log from weekly stat rows, so a game where the
   player was active and recorded nothing is not in it (finding 5).
3. `ff_props.opportunity_column("targets")` and `("attempts")` return None, so
   a targets or pass-attempts log is not filtered on opportunity the way a
   receptions or completions log is. The harness reproduces that as it is.
4. `player_series` keeps a log by display name. A player whose name is spelled
   two ways across seasons has a shorter log there (2 of 1,732 logs on three
   weeks).
5. If S5 is wanted: `ff_data.ASSETS` would need nflverse's weekly roster file.

## Decisions waiting for Dustin

None yet. The first one comes with S4: whether the game's closing spread and
total may be used as inputs, once he has seen what they are worth with and
without. The probability threshold is his to set after the first simulator
calibration table, not from the yardsticks above.
