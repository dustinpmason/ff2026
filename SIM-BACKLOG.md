# Simulator build — backlog

Owned by the simulator thread. Ids are `S1`, `S2`, ... The betting engine's
backlog is `BACKLOG.md` (ids `B...`) and is never edited from here.
`SIM-HANDOFF.md` is the brief this build works from.

## State on 2026-11-20

| | |
|---|---|
| Built | The test harness (S1). The first piece of the simulator: an opportunity model for targets, carries and pass attempts (S4, first version, measured, with known weaknesses listed below). **Nothing yet projects catches, yards or touchdowns.** |
| Files | `ff_sim.py`, `ff_sim_opp.py`, `test_sim.py`, `sim_baseline.py`, `sim_opportunity.py`, `sim_reverts.py`, this file |
| Simulator suite | `python3 test_sim.py` → **518 checks, ALL PASS** |
| Engine suite | `python3 test_regression.py` → 1801, untouched. No existing file was edited. |
| Next | Dustin sees the S4 numbers and answers the two questions at the bottom. Then the open S4 items, then efficiency. |

```bash
python3 refresh.py
python3 test_regression.py                     # the engine's count
python3 test_sim.py                            # this build's count
python3 sim_baseline.py --current-week 11      # the yardsticks; about 2 minutes
python3 sim_opportunity.py --current-week 11   # the opportunity model; about 4 minutes
python3 sim_reverts.py                         # break every behaviour; about 50 minutes
```

`--current-week` is the NFL week now in progress. On 2026-11-20 that is 11,
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

## S4. The opportunity model — FIRST VERSION, MEASURED 2026-11-20

`ff_sim_opp.py` projects a player's targets, his carries, and the starting
quarterback's pass attempts, each as a count with a spread round it. It is
the first half of receptions and yards; the second half, what he does with
them, is not built.

How it works: the team's volume from its own recent games and what its
opponent has allowed; the player's share from his recent share, his
longer-run share and his position's norm; the shares of everyone ON THE
SLATE scaled to add up to the team; a negative-binomial count round the
result. Pass attempts are the team's projected attempts times the share
starters have thrown, given to whoever the slate names as the starter; it
says nothing of any other quarterback. Everything is fitted again each week
on earlier weeks only, except eight numbers set by hand and not tuned (S2).

**What it is not, against the brief.** SIM-HANDOFF.md says "team plays, pass
rate, each player's share of snaps, targets and carries". This version fits
team targets, carries and pass attempts directly rather than plays times
pass rate, and never reads a snap count. Each player's count stands alone:
it says nothing about two teammates together (S16).

### What it scored (`sim_opportunity.py`, run 2026-11-20)

Sample: 46 weeks, 2024 Week 1 to 2026 Week 10, 694 games. Players with a
role who played. Every error is clustered by game.

**Brier score on the main stand-in line** (lower is better; "know-nothing"
says each stat's own overall over-rate):

| | legs | know-nothing | game-log model | opportunity model | gap to know-nothing |
|---|---|---|---|---|---|
| **Active list known** | | | | | |
| targets | 5,272 | 0.2414 | 0.2429 | **0.2271** | −0.0143 (se 0.0017) |
| carries | 2,194 | 0.2445 | 0.2476 | **0.2193** | −0.0252 (se 0.0031) |
| pass attempts | 1,121 | 0.2500 | 0.2440 | **0.2348** | −0.0151 (se 0.0044) |
| **Active list not known** | | | | | |
| targets | 5,223 | 0.2417 | 0.2430 | 0.2498 | **+0.0081** (se 0.0024) |
| carries | 2,171 | 0.2445 | 0.2473 | 0.2582 | **+0.0137** (se 0.0041) |
| pass attempts | 1,070 | 0.2499 | 0.2428 | 0.2324 | −0.0175 (se 0.0044) |

**Mean miss of the single number** (typical miss in brackets), same
player-games in each row:

| | player-games | season average | last four | game-log model | opportunity model |
|---|---|---|---|---|---|
| **Active list known** | | | | | |
| targets | 5,272 | 2.30 (2.00) | 2.32 (2.00) | 2.30 (2.00) | **2.17 (1.77)** |
| carries | 2,194 | 4.11 (3.33) | 4.11 (3.25) | 4.37 (3.50) | **3.85 (3.17)** |
| pass attempts | 1,121 | 7.63 (6.33) | 7.45 (6.25) | 7.02 (5.50) | **6.64 (5.18)** |
| **Active list not known** | | | | | |
| targets | 5,223 | 2.30 (2.00) | 2.32 (2.00) | 2.30 (2.00) | 2.27 (1.76) |
| carries | 2,171 | 4.12 (3.36) | 4.12 (3.25) | 4.37 (3.50) | 4.35 (3.43) |
| pass attempts | 1,070 | 7.59 (6.32) | 7.57 (6.25) | 7.17 (5.50) | 6.76 (5.10) |

**Calibration, active list known**, targets, carries and pass attempts
together, read on the side it favoured:

| it said | happened | on legs it favoured OVER | on legs it favoured UNDER | game-log model, same legs |
|---|---|---|---|---|
| 50-55% | 53.6% | 56.6% | 50.6% | 52.9% |
| 60-65% | 61.3% | 65.5% | 57.6% | 60.9% |
| 70-75% | 71.5% | 76.4% | 67.7% | 68.3% |
| 80-85% | 82.0% | 83.1% | 81.5% | 77.3% |
| 90-95% | 91.5% | 92.4% | 91.3% | 87.7% |
| 95-100% | 96.6% | 94.5% | 97.0% | 92.2% |

3,164 to 5,010 legs a band; 95% ranges within a point and a half either way
overall and about two points by side.

**The closing spread and total as inputs** (Brier with them, minus without,
on the legs both priced):

| | active list known, main line | every rung | not known, main line | every rung |
|---|---|---|---|---|
| targets | −0.00087 (se 0.00018) | −0.00067 (se 0.00012) | −0.00121 (se 0.00020) | −0.00098 (se 0.00015) |
| carries | −0.00000 (se 0.00057) | −0.00016 (se 0.00035) | +0.00069 (se 0.00056) | +0.00042 (se 0.00036) |
| pass attempts | −0.00163 (se 0.00067) | −0.00061 (se 0.00027) | −0.00154 (se 0.00070) | −0.00066 (se 0.00028) |

### What that says, in order of how much it matters

1. **With the active list known it clears the bar no yardstick clears.** It
   beats know-nothing on all three stats by 3.4 to 8.3 standard errors on
   the main line, and the game-log model's mean miss by 0.135 targets
   (se 0.015), 0.481 carries (se 0.055) and 0.427 pass attempts (se 0.096).
2. **With the active list NOT known it is worse than knowing nothing on
   targets and carries.** "Not known" here is slate B, and slate B is not
   simply the model without a list: it is a list that includes players who
   will not play, and the model shares a team's volume among everyone on
   it. Of what it handed out on slate B, 20.1% of targets and 22.5% of
   carries went to players who then did not play, so everyone who did was
   given too little (its bias there is −0.99 targets and −2.00 carries).
   So the slate-B score is the missing list AND the cost of that sharing,
   together; what the model would score if it weighed each man's chance of
   playing is not known, because that is not built. Its probabilities on
   slate B are badly overconfident, worse than the game-log model's on the
   same slate (a stated 72.5% came in at 65.8% against 68.4%; 82.5% at
   72.4% against 77.4%). Pass attempts hold up either way (−0.0175 not
   known), because the team's attempts do not depend on the slate, only
   who is named the starter; slate B's man did not play in 12.3% of
   team-games. A live run sits between the two slates: slate A is a little
   more than an inactive list tells you (S6) and slate B a good deal less
   than anyone knows on a Sunday (S5). **This is the first thing to fix
   (S13).**
3. **Its probabilities are close overall and lean.** Active list known, it
   is within a point and a half of what it says in every band and reads
   "as stated" up to 90%; above that it is half a point to a point too
   sure, and its 95 to 100% overs more (94.5% for a stated 96.7%). From 55%
   to 80% its overs come in 3 to 5.5 points more often than it says and its
   unders 2.5 to 5 points less. The game-log model on the same legs is too
   sure on both sides from 75% up, its overs worst (3.6 to 8.6 points less
   often than stated).
4. **It gives players with a line about 4% too little.** Team totals are the
   right size (targets 2.23 expected against 2.22 actual over the whole
   slate; carries 1.93 and 1.93; a starter's pass attempts 31.26 and
   31.23). But players with a stand-in line are expected 4.98 targets and
   get 5.19 (+0.21, se 0.04), and 10.50 carries and get 10.93 (+0.43,
   se 0.08); their main-line overs are said to be 36.8% and 37.9% and come
   in at 40.0% and 42.3%. Small roles are given too much. The lean in
   finding 3 goes with this; that one causes the other is the likely
   reading and is not tested. Nor is it settled why big roles get too
   little: the share fit pulling big and small together, or first-game and
   fringe players being handed a position's average share, are not
   separated. Pass attempts cannot settle it: their gaps (+0.17, se 0.24;
   +2.1 points, se 1.3) are distinguishable neither from none nor from the
   targets gap (S11).
5. **One spread per stat does not fit every size of role.** For backs
   expected 13 or more carries the root mean squared miss was 5.64 and the
   model's counts imply 7.41; for those expected 1 to 4 it was 2.48 against
   1.82. Targets the same way, less strongly (S12).
6. **The closing spread and total add little.** Targets: a clear gain (4.8
   to 6.7 standard errors across both slates) and a small one, with the
   active list known about a sixteenth of the model's own gap to
   know-nothing. Pass attempts: about a tenth of its gap, at 2.2 to 2.4
   standard errors, so probably real and not beyond doubt. Carries: nothing
   either way. Dustin's call (see the bottom).
7. **Reporting the median instead of the expected count** changes the mean
   miss by −0.009 targets (se 0.006), +0.036 carries (se 0.014), +0.040
   pass attempts (se 0.019): it does not miss by less. Its bias is −0.58
   targets and −1.13 carries against −0.21 and −0.42 for the expected
   count. The expected count is the model's single number, and is what the
   next stage should multiply.

### How it was checked

- **`sim_reverts.py`**: 97 behaviours of `ff_sim_opp.py` each removed or
  reversed in a copy, one at a time: **97 caught, 0 not**. The runner now
  carries two controls for the second file as well, and `--show` prints
  which checks failed for each. The whole list was run again on the fresh
  clone, the harness's 258 included: **355 caught, 0 not** (2026-11-20, in
  seven blocks, controls passing in each). On the way there the first pass
  of the new reverts caught 29 of 37; each miss was a check that could not
  fail or a guard that did nothing, and was rewritten or removed.
- **Independent review**, two passes, each by a fresh reviewer given the
  code and a list of questions and none of the reasoning. Both reran the
  measurement and found every printed figure matching. The first returned
  fifteen defects, the second eighteen (the largest are listed below); every
  one was acted on. **The fixes made after the second pass have not
  themselves been reviewed.** They are covered by the suite and by reverts:
  only the named starter is given pass attempts; a non-numeric line, an
  empty table of lines and a player listed twice are refused; the
  expected-count table is pinned to the active slate; and the wording of
  this section and of `sim_opportunity.py`'s docstring.
- **Leak probe on every graded week**: 1,803,471 projector outputs (150,716
  from each of the three opportunity models) were identical after the week
  being projected, and everything after it, was overwritten. It cannot see
  the closing lines (S14).
- **By hand.** The suite re-derives everything the model learns from a
  history, and every expected count for a slate, with plain loops from the
  model's description, on a made-up league whose schedule rotates, and
  compares part by part; chances are summed from the negative binomial's
  formula, and their sum is checked against the expected count. The test
  keeps its own typed copy of the eight hand-set numbers. The by-hand
  version follows the same description as the code, so a mistake in the
  description itself would be in both.
- **Fresh clone** (2026-11-20, commit 950e48f, with `ff_sim_opp.py`,
  `sim_opportunity.py`, `test_sim.py`, `sim_reverts.py` and this file
  added or replaced and nothing else touched): `test_regression.py` 1801
  ALL PASS, `test_sim.py` 518 ALL PASS, `sim_reverts.py --check` 359 of 359
  apply, `sim_opportunity.py --current-week 11` exit 0 with output
  identical to the working copy's, the full revert run above, and the
  calls documented in `ff_sim_opp.py` and `sim_reverts.py` run as written.
  `ff_sim.py` and `sim_baseline.py` are byte for byte the committed ones.
  `git status` shows three files changed, two new, and no change to any
  other.

What the review found that a reader of the numbers would have been misled
by. Kept because the same mistakes are available again:

- **Only the flattering slate was reported.** The first write-up gave every
  score with the active list known and only the difference to not known.
  Not known, the model is worse than knowing nothing on two of its three
  stats. Both slates are now in every table.
- **Explanations stated as findings, three times.** "The shares are pulled
  together, and that is the lean", from two tables that sat near each
  other. Then "everything it adds comes from knowing who is on the field",
  when slate B also charges the model for sharing volume among players who
  will not play. Then pass attempts offered as the control that proved the
  first, on a sample too small to tell them apart. Each is now stated as
  what was measured, with what was not.
- **A spread measured on the wrong thing.** The pass-attempt spread was
  measured on TEAM attempts and applied to a starter's own. Starters leave
  games; their attempts are wider. Across the three stats, overs it called
  95 to 100% came in at 93.5% for a stated 97.3%. It is now measured on
  starters' own games (on the history before 2026 Week 9, a size of 22.5
  where the team's was 42.4). That band now reads 94.5% for a stated
  96.7%: better, and still too sure.
- **A number for a man it knew nothing about.** A quarterback on the slate
  who was not the starter was given the few attempts starters leave, with
  a starter's spread round them: expected 1.36, threw 5.13, with a stated
  spread of 1.20 against 8.78. Slate A lists a backup only when he took a
  snap (S6), so that row was mostly the slate. The model now says nothing
  about any quarterback but the named starter.
- **"Nothing else is set by hand."** There were five more numbers than the
  three half-lives. All eight are now named constants and listed in S2.
- **A fixture that could not tell two things apart.** Every made-up team
  played the same opponent every week, so "its own average" and "what its
  opponent allows" were the same column, and swapping them changed nothing.
  17 of the first reviewer's 38 new reverts survived, and 7 of the second's
  50. The fixture now rotates, and the suite went from 467 to 518
  checks.
- **The suite printed ALL PASS when the new module failed to import**,
  because the import sat outside any section. It is now inside one.
- **A line that was not a number became a projection that was not a
  number**, silently, for one game's players. A NaN spread or total now
  stops the run and names the game.

---

## Open

| id | what | status |
|---|---|---|
| **S2** | **Settings chosen, not measured: the test's, and now the model's.** | **OPEN.** The model's are eight numbers in `ff_sim_opp.py`: half-lives of 4 games (team volume), 3 (recent share) and 10 (longer-run share); no fit on fewer than 16 rows; the spread of targets and carries measured only on expected counts above 1 (on the history before 2026 Week 9 the targets size is 7.8 with the cut at 0, 8.5 at 1 and 11.3 at 3; carries 6.1, 6.4, 7.2); the spread held between sizes 1 and 500; a team never projected under 1. And one convention: with no start on record in the history, a starter is taken to throw every pass. None was tuned against the test. The test's own settings define the test, not a projection, and every projector is graded by the same test; they do change what it is a test of and how far apart two projectors look. All of them: a role is a median of 3 targets / 5 carries / 20 pass attempts; the line window is 8 games, with no line under 4; rungs at 0.6, 0.8, 1.0, 1.25 and 1.6 times the median; the main line is the half point above the median; slate B looks back 4 of the team's games; no verdict under 30 games; ranges and verdicts at 95%; under five hits or five misses each game counts once in a range; the yardsticks' "share over the line" is pulled half a game toward 50%; which positions get a projection with no role. The role floors are the ones to replace first: with what real boards actually post, once S3 has enough weeks. |
| **S3** | **Grade against real book lines.** | **OPEN, small sample.** Book lines exist from about 2026-11-06 (about 30 games). The same calibration table on real lines, beside the market's own de-vigged probability, is the Phase 2 test. Worth setting up early so the weeks accumulate. The market's line is a benchmark there, never an input and never a lean. |
| **S4** | **The opportunity model.** | **FIRST VERSION MEASURED 2026-11-20**, section above. Its open items are S11 to S16. |
| **S5** | **Version B does not know the roster.** | **NOTED.** It lists a player under every team he was active for in one of that team's last four games, and gives the quarterback line to whoever started that team's last game. So it counts a traded player as "did not play" for his old team and misses him on his new one, and in Weeks 1 to 4 it reaches into last season. A weekly roster file would fix it; `ff_data` does not load one (see "Needs"). Version A is the one a live run is, and it does not have this problem. |
| **S6** | **Slate A is "has a snap row or a stat row", not the inactive list; the starter is "threw his team's first pass".** | **NOTED, and now it matters.** The opportunity model reads the slate, so slate A tells it a little more than an inactive list would: a player who dressed and never took a snap is not on it, so nobody on it is given a share and then sits. How much of the model's gain on slate A is this cannot be measured without an inactive list, which is not on file. A man who dressed and never took a snap is missing rather than a zero. 232 of 24,976 skill-position snap rows had no id to join on; 27 players never have a snap row and appear only in games where they recorded a stat. A starter hurt before his team's first pass play would be read as not having started. |
| **S7** | **A week is the unit of time.** | **NOTED.** A Thursday game is not used for that Sunday. Stricter than the brief asks, and simple. Postseason games are in neither the history nor the test. |
| **S8** | **The leak probe sees only what passes through the frame.** | **STANDING RULE.** A projector that carries its own copy of the data, or a constant typed into one that was worked out over all seasons, is invisible to it. So is a result that decides WHO IS ON THE SLATE: that is how the first quarterback rule leaked. Estimate everything inside `project()`, and when adding anything to a slate, ask whether it was knowable before kickoff. |
| **S9** | **`ff_sim.gamelog_blend` is a copy of `ff_props.threshold_prob`'s arithmetic.** | **PINNED.** The original costs 4 ms a call. `test_sim.py` section 6 runs both on real logs for all nine engine stats and fails by name if they differ. |
| **S10** | **`ff_sim.corr_joint` reads `ff_boost._pair_weight`**, a private name. | **NOTED.** If the engine renames it the import fails and says why. It is the table's r as a plain point estimate. It is not what `ff_boost.joint_error` does, and no table here calls it "the engine's". |
| **S11** | **Players with a line are given too little, small roles too much.** | **OPEN, measured.** About 4% too little on targets and carries, and their overs come in 3 to 4 points more often than stated (S4 findings 3 and 4). Why is not settled: the share fit pulling big and small together, or first-game and fringe players handed a position's average. Things to try, each graded the same way: a snap share as an input (the brief asks for it and the model does not read one), a share fit that is not a straight line at the top, giving a new or unseen player less than his position's average. |
| **S12** | **One spread per stat does not fit every size of role.** | **OPEN, measured.** Too wide for the biggest roles, too narrow for small ones (S4 finding 5). It is also measured before shares are scaled to the slate and applied after. Either may be part of why the top band is too sure (96.6% for a stated 97.1%; overs 94.5% for 96.7%); neither is tested. |
| **S13** | **On slate B the model is worse than nothing on targets and carries.** | **OPEN, measured, and the first to fix.** It shares a team's volume among everyone listed, and on slate B a fifth of it goes to players who do not play (S4 finding 2). It needs each player's chance of playing, estimated from the history (games missed lately, how long since his last game), so that a doubtful player is given a part share and not a whole one. Then the two slates stop being all or nothing, and the slate-B score says something about the model and not only about the list. What a live run actually knows, and when, is a question for Dustin (bottom). |
| **S14** | **The closing spread and total reach the model outside the harness.** | **OPEN pending Dustin's decision.** They are handed over at construction, where the leak probe cannot see. What stands there: the model looks a line up only for games in its history or on its slate; the suite checks that, and that moving a later game's line moves nothing. `_market`'s own refusal cannot fire from the code as it stands; it is a tripwire for a later edit. If Dustin wants them used, the right home is the harness's slate, which is a change to `ff_sim.py` and its reverts. The table of lines holds only games played, so a live week needs its lines supplied; a missing or non-numeric line stops the run and names the game. |
| **S15** | **Team volume is three separate fits; no plays, no pass rate, no snaps.** | **NOTED.** A team's projected targets and its quarterback's projected attempts are not tied to each other (projected targets ran 0.92 to 0.97 of projected attempts in the reviewer's check). Whether plays times pass rate does better is measurable and not yet measured. |
| **S16** | **Counts are independent across players.** | **NOTED.** The model states no chance of two legs together, so the pair report has nothing of its own to score yet. Pairs wait for a game-level simulation. |

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

1. **May the closing spread and total be used as inputs?** What they are
   worth is in the S4 table. For: a clear gain on targets on both slates
   (4.8 to 6.7 standard errors), a probable one on pass attempts (2.2 to
   2.4), and with the active list known they take the pass-attempt bias
   from −0.15 to +0.03. Against: the gains are small (with the active list
   known, about a sixteenth and a tenth of what the model itself adds);
   carries gain nothing; not known, the pass-attempt bias goes the other
   way (+0.01 to +0.20). Recommendation: **leave them out for now.** The
   size of the gain is the main reason. The others: a live run would need
   the lines at run time; they reach the model where the leak probe cannot
   see (S14); and the Phase 2 test sets the simulator against the market's
   prop lines, which are a related market to the game spread and total, so
   a simulator fed them borrows a little of what it is being tested
   against. Ask again at the game-script stage, which is where a spread
   ought to matter most and is not built.
2. **When is a live run made: after the inactive lists are out (about 90
   minutes before kickoff), or earlier?** It decides how much S13 matters.
   After: the active-list-known numbers are close to what a live run would
   see, less whatever S6 hides. Earlier: the truth is between the two
   slates, and S13 comes before anything else.

The probability threshold is still his to set after a simulator calibration
table on catches and yards, not from targets and carries.
