# Simulator build — backlog

Owned by the simulator thread. Ids are `S1`, `S2`, ... The betting engine's
backlog is `BACKLOG.md` (ids `B...`) and is never edited from here.
`SIM-HANDOFF.md` is the brief this build works from.

## State on 2026-11-21 (after S28)

| | |
|---|---|
| Built | The test harness (S1). An opportunity model for targets, carries and pass attempts (S4). Efficiency on top of it: receptions, receiving yards, rushing yards, completions, passing yards (S17). A chance of playing for every listed player, from the injury report and games missed, or handed in at run time, and the opportunity model that uses it (S13). Touchdowns on top of all of it: anytime (rushing or receiving) and passing (S24). A script that runs all of it on a week not yet played, from files a project thread saves (S28). **First touchdown is not built, nothing has been graded against a book's line, and no shadow run has been made yet.** |
| Files | `ff_sim.py`, `ff_sim_opp.py`, `ff_sim_eff.py`, `ff_sim_play.py`, `ff_sim_td.py`, `test_sim.py`, `sim_baseline.py`, `sim_opportunity.py`, `sim_efficiency.py`, `sim_play.py`, `sim_touchdowns.py`, `ff_sim_live.py`, `sim_live.py`, `sim_record.py` (made by `sim_live.py --record`), `sim_reverts.py`, this file |
| Simulator suite | `python3 test_sim.py` → **824 checks, ALL PASS** |
| Engine suite | `python3 test_regression.py` → 1801, untouched. No existing file was edited. |
| Next | Shadow runs, in a project thread (S28 says how). Then grading them (S29), and the parked calibration items: S11, S12, S18, S19, S20, S25. |

```bash
python3 refresh.py
python3 test_regression.py                     # the engine's count
python3 test_sim.py                            # this build's count
python3 sim_baseline.py --current-week 11      # the yardsticks; about 2 minutes
python3 sim_opportunity.py --current-week 11   # targets, carries, pass attempts; about 4 minutes
python3 sim_efficiency.py --current-week 11    # catches and yards; about 4 minutes
python3 sim_play.py --current-week 11          # chance of playing; about 6 minutes
python3 sim_touchdowns.py --current-week 11    # touchdowns; about 7 minutes
python3 sim_live.py --week 11 --inputs week11.json odds/*.json   # a shadow run; seconds
python3 sim_live.py --record --current-week 11 # rebuild the record; about 10 minutes
python3 sim_reverts.py                         # break every behaviour; about 9 hours in full
python3 sim_reverts.py --fast 613 614          # ...the live file's reverts only; about 12 s each
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

## S17. Efficiency — FIRST VERSION, MEASURED 2026-11-20

`ff_sim_eff.py` turns the opportunity model's targets, carries and pass
attempts into receptions, receiving yards, rushing yards, completions and
passing yards. With it the simulator gives a number and a chance for the
stats props are written on, touchdowns excepted.

How it works: five rates per player (catch rate, yards per catch, yards per
carry, completion rate, yards per pass attempt), each from his own games
leaning on the newest and pulled toward what his position does; how hard to
pull is picked each week, per rate, as whichever of a fixed list would have
predicted the history best. Receptions are his targets thinned at his catch
rate. Yards are a sum, over however many catches or carries he turns out
to have, of a random number of yards each, whose spread is measured on the
history per position. No opponent, no game script, no touchdowns.

### What it scored (`sim_efficiency.py`, run 2026-11-20)

Sample: 46 weeks, 2024 Week 1 to 2026 Week 10, 694 games. Players with a
role who played. Every error is clustered by game. "Simulator" is the
opportunity model with efficiency on top.

**Brier score on the main stand-in line** (lower is better; the gap to
know-nothing in brackets):

| | legs | know-nothing | game-log model | simulator |
|---|---|---|---|---|
| **Active list known** | | | | |
| receptions | 5,272 | 0.2421 | 0.2384 (−0.0036) | **0.2287** (−0.0133, se 0.0017) |
| receiving yards | 5,272 | 0.2481 | 0.2442 (−0.0039) | **0.2367** (−0.0114, se 0.0017) |
| rushing yards | 2,194 | 0.2474 | 0.2489 (+0.0014) | **0.2364** (−0.0110, se 0.0032) |
| completions | 1,121 | 0.2500 | 0.2417 (−0.0083) | 0.2396 (−0.0104, se 0.0047) |
| passing yards | 1,121 | 0.2500 | 0.2422 (−0.0078) | 0.2394 (−0.0106, se 0.0041) |
| **Active list not known** | | | | |
| receptions | 5,223 | 0.2423 | 0.2386 (−0.0038) | 0.2463 (+0.0040, se 0.0022) |
| receiving yards | 5,223 | 0.2482 | 0.2442 (−0.0040) | 0.2478 (−0.0003, se 0.0021) |
| rushing yards | 2,171 | 0.2475 | 0.2487 (+0.0012) | 0.2556 (**+0.0081**, se 0.0039) |
| completions | 1,070 | 0.2499 | 0.2404 (−0.0095) | 0.2383 (−0.0116, se 0.0046) |
| passing yards | 1,070 | 0.2500 | 0.2423 (−0.0077) | 0.2409 (−0.0091, se 0.0041) |

**Simulator minus game-log model**, Brier, on the legs both priced, active
list known: receptions −0.0101 (se 0.0018), receiving yards −0.0091
(se 0.0017), rushing yards −0.0117 (se 0.0033), completions −0.0047
(se 0.0037), passing yards −0.0040 (se 0.0031).

**Mean miss of the single number**, active list known, same player-games in
each row:

| | player-games | season average | last four | game-log model | simulator |
|---|---|---|---|---|---|
| receptions | 5,272 | 1.79 | 1.80 | 1.75 | **1.68** |
| receiving yards | 5,272 | 24.60 | 25.01 | 23.57 | **23.17** |
| rushing yards | 2,194 | 25.29 | 25.69 | 25.77 | **24.01** |
| completions | 1,121 | 5.30 | 5.25 | 4.85 | **4.75** |
| passing yards | 1,121 | 65.94 | 65.72 | 61.09 | **59.03** |

**Calibration, active list known**, the five stats together, read on the
side it favoured:

| it said | happened | on legs it favoured OVER | on legs it favoured UNDER | game-log model, same legs |
|---|---|---|---|---|
| 50-55% | 52.3% | 55.0% | 49.7% | 52.4% |
| 60-65% | 63.0% | 65.5% | 60.7% | 59.8% |
| 70-75% | 70.8% | 72.7% | 69.7% | 68.3% |
| 80-85% | 81.0% | 82.7% | 80.4% | 76.4% |
| 90-95% | 92.0% | 91.6% | 92.0% | 87.1% |
| 95-100% | 96.7% | 93.4% | 97.1% | 91.7% |

2,835 to 10,718 legs a band; 95% ranges about a point either way overall.

### What that says, in order of how much it matters

1. **Active list known, the simulator beats knowing nothing on the main
   line on all five stats: clearly on three, thinly on two.** Receptions,
   receiving yards and rushing yards by 7.8, 6.7 and 3.4 standard errors;
   completions and passing yards by 2.2 and 2.6. Over every rung of the
   ladder completions is NOT distinguishable from knowing nothing (−0.0035,
   1.6 standard errors); the other four are (3.4 to 9.1). The game-log
   model clears knowing nothing on completions by more standard errors than
   the simulator does (2.5 against 2.2).
2. **Against the engine's game-log model, active list known:** the
   simulator's probabilities are clearly better on receptions, receiving
   yards and rushing yards (5.7, 5.3 and 3.5 standard errors on the main
   line). On completions and passing yards the main line is 1.3 standard
   errors, noise (2.5 and 3.0 over every rung). Its single number is
   distinguishably better on all five (2.6 to 6.7 standard errors), by
   0.07 receptions, 0.5 receiving yards, 1.8 rushing yards, 0.15
   completions and 2.2 passing yards a game: real and small. It does not
   tell quarterbacks far apart: 1,278 of 1,388 starters are expected 190
   to 250 passing yards.
3. **Its probabilities are within 1.6 points of what it says in every band,
   active list known**, where the game-log model on the same legs is 2.7 to
   6.3 points too sure from 60% up. It is a little too sure from 70% to
   90% (1.1 to 1.6 points). By family: receiving within 2.4 points
   everywhere; **rushing yards too sure by 2.4 to 3.6 points in every band
   from 65% up** (S18); **passing, if anything, not sure enough** (a
   stated 82.5% came in at 85.9%; S20).
4. **Its distributions lean right and players' results do not: the first
   thing to fix before a threshold is set from these tables (S19).**
   Starting quarterbacks' expected numbers are the right size (20.33
   completions against 20.26; 223.2 yards against 222.9), and they still
   beat that number 51.0% and 50.6% of the time where the model's own
   distribution says 47.2% and 46.0% (+3.8 and +4.6 points, se 1.3 and
   1.4). Players with a line beat it 2.8 to 6.6 points more often than it
   says on all five stats. On the main line the overs come in 2.5 to 4.3
   points more often than stated; by band, up to 70% its overs come in 2.5
   to 3.0 points more often and up to 90% its unders 1.5 to 4.6 points
   less. For receivers and rushers part of this is also the expected
   number running 4 to 5% low, the opportunity model's shortfall carried
   through (S11); the tables cannot split the two for them. Until it is
   fixed: a stated under is worth a few points less than it says, a stated
   over a few points more.
5. **Active list not known, it is no better than knowing nothing on
   receptions and receiving yards and worse on rushing yards** on the main
   line (over every rung: worse on receptions, 2.3 standard errors; noise
   on the other two), and worse than the game-log model on receptions (2.6
   standard errors). This is the opportunity model's fault carried
   through: it shares a team's volume among everyone listed (S13); its
   single number there runs 7.7 receiving yards and 9.1 rushing yards low.
   Its probabilities are badly overconfident up to 90% (a stated 72.4%
   came in at 64.8%; the game-log model's 68.4%). Completions and passing
   yards hold up either way.
6. **How hard each rate is pulled was learned, and came out steady.** Catch
   rate: a pull of 80 targets in all 46 weeks. Yards per catch: 40 catches
   in all 46. Yards per carry: 160 carries (80 in 3 weeks). Completion
   rate: 320 attempts (640 in 14 weeks). Yards per attempt: 160. Never at
   an end of the list. With the 16-game half-life a player's own totals
   level off at about 24 games' worth, so at a pull of 320 a quarterback's
   completion rate is half his own after about 12 games and never more
   than about 70% his own.
7. **Totals are the right size; spreads are close for three stats and off
   for two.** Whole slate, expected against actual: receptions 1.52 and
   1.50, receiving yards 16.66 and 16.49, rushing yards 8.41 and 8.38, a
   starter's passing yards 223.2 and 222.9. Root mean squared miss against
   what the model implies: receptions 1.46 and 1.43, receiving yards 19.76
   and 20.40, completions 6.10 and 6.13; **rushing yards 13.63 and 12.94
   (5% too narrow; 16% too narrow for backs expected 10 to 30 yards)**;
   **passing yards 76.15 and 81.56 (7% too wide)**. 6.4% of player-games
   with a carry finish below zero rushing yards, which the model cannot
   give.

Read with the same limits as S4: "active list known" is slate A, which is a
little more than an inactive list tells you (S6); the simulator reads the
slate and the yardsticks do not; lines are stand-ins, not a book's.

### How it was checked

- **`sim_reverts.py`**: 89 behaviours of `ff_sim_eff.py` each removed or
  reversed in a copy, one at a time: **89 caught, 0 not**, on a fresh clone
  (2026-11-20, three blocks, the runner's six controls passing in each;
  two of the six are new, for the third file). The first 82 were all
  caught on the first pass; seven were added after the review. The 355
  earlier reverts were NOT all run again: `ff_sim.py`, `ff_sim_opp.py` and
  sections 1 to 20 of the suite are byte for byte what they were when all
  355 were caught, so that result stands; twelve of them, every thirtieth,
  were rerun here and were caught.
- **Independent review**, one pass, by a fresh reviewer given the code and
  a list of questions and none of the reasoning. It reran the measurement
  and found every printed figure matching, and no wrong number. It
  returned thirteen defects, the largest listed below; every one was acted
  on. **The fixes made after it have not themselves been reviewed.** They
  are covered by the suite and by reverts: the fit is no longer remembered
  before it is finished; `expected_vs_actual` carries the model's own
  chance of beating its expected number; the shape table in
  `sim_efficiency.py`; seven more checks and reverts; and the wording of
  this section and of that script's docstring.
- **Leak probe on every graded week**: 1,759,176 projector outputs, 407,853
  of them the simulator's, were identical after the week being projected,
  and everything after it, was overwritten.
- **By hand.** The suite re-derives everything the model learns from a
  history and every expected number, spread and variance for a slate with
  plain loops, on a made-up league with drawn catches and yards. The
  yardage distribution is checked three ways that do not share its code:
  against the closed-form tail of a sum of exponentials; and by adding up
  the chances it states over a fine grid of lines, which must give back
  the expected number and the variance it reports.
- **Fresh clone** (2026-11-20, commit c13acd9, with `ff_sim_eff.py`,
  `sim_efficiency.py`, `test_sim.py`, `sim_reverts.py` and this file added
  or replaced and nothing else touched): `test_regression.py` 1801 ALL
  PASS, `test_sim.py` 606 ALL PASS, `sim_reverts.py --check` 450 of 450
  apply, `sim_efficiency.py --current-week 11` exit 0 with output
  identical to the working copy's, and the revert runs above. `ff_sim.py`,
  `ff_sim_opp.py`, `sim_baseline.py` and `sim_opportunity.py` are byte for
  byte the committed ones. `git status` shows three files changed, two
  new, and no change to any other.

What the review found that a reader of the numbers would have been misled
by. Kept because the same mistakes are available again:

- **"The value is in the probabilities, not in the point."** Written from
  the receiving stats; for quarterbacks the output says the reverse (the
  single number is 2.6 and 3.5 standard errors better than the game-log
  model's, the main-line probabilities 1.3). A sentence that sums up five
  stats has to be checked against all five.
- **"Beats know-nothing on all five."** True on the main line, where two of
  the five are at 2.2 and 2.6 standard errors; over every rung completions
  is noise. The every-rung figures had been quoted only where they helped.
- **A reading of a number without its half-life.** "A pull of 320 attempts
  is ten games" ignored that a player's own totals are leaned and level
  off; at 320 a quarterback is never more than about 70% himself.
- **A guess labelled "not tested" that could be tested in ten lines.** The
  lean toward the under was put down to shape with no evidence. The
  reviewer ran it: starters' expected numbers are right and they beat them
  51% of the time against a stated 46 to 47%. That table is now in the
  script, and it is the most useful thing in this section.
- **"Close" for a spread that is 7% too wide**, and a row in the open table
  that contradicted a finding in the same file.

---

## S13. Chance of playing — MEASURED 2026-11-20

`ff_sim_play.py`. `PlayChance` puts a chance of playing on every listed
player from his status on that week's injury report and how many of his
team's last four games he has missed, counted on earlier weeks only; a
chance can be handed in instead (`given={player_id: chance}`), which is
the run-time input. `ChanceOpportunity` is the opportunity model with each
teammate counted at his chance: a player's line is worked out as if he
plays. With every chance at 1 it is the opportunity model number for
number; with a teammate at 0 it is the opportunity model on a slate
without him. Injury reports come from nflverse's `injuries` release,
fetched by this file into the engine's cache.

### What was measured (`sim_play.py`, run 2026-11-20)

46 weeks, 694 games. "List not known" is the harness's slate B: everyone
active for a team in one of its last four games.

**Brier score on the main line, gap to knowing nothing** (standard errors
in brackets):

| | list known: simulator | list NOT known: game-log | as it was | with games missed | and the report |
|---|---|---|---|---|---|
| targets | −0.0141 (8.6) | +0.0013 | +0.0078 | −0.0127 | **−0.0138 (8.0)** |
| carries | −0.0227 (7.7) | +0.0026 | +0.0130 | −0.0181 | **−0.0212 (7.4)** |
| receptions | −0.0137 (8.5) | −0.0035 | +0.0030 | −0.0135 | **−0.0135 (7.9)** |
| receiving yards | −0.0129 (7.9) | −0.0042 | −0.0019 | −0.0136 | **−0.0135 (8.2)** |
| rushing yards | −0.0103 (3.4) | +0.0010 | +0.0067 | −0.0093 | **−0.0089 (2.9)** |

Pass attempts, completions and passing yards do not move (−0.0184, −0.0112,
−0.0111 in every list-not-known column).

1. **With a chance of playing, the simulator with the list not known is
   close to what it is with the list known**: a little behind on most
   stats (table above; mean miss 2.19 against 2.17 targets, 3.96 against
   3.88 carries, 23.53 against 23.14 receiving yards), and on a slightly
   different set of players, since the list-not-known slate cannot grade a
   man new to a team or back after more than four games. Against the
   simulator as it was, on the same legs: targets −0.0215 (se 0.0022),
   carries −0.0343 (se 0.0033), receptions −0.0165 (se 0.0019), receiving
   yards −0.0116 (se 0.0016), rushing yards −0.0156 (se 0.0026). The large
   bias is gone: targets −0.96 to +0.11, carries −1.95 to −0.04, receiving
   yards −7.50 to +0.69.
2. **Pooled over the rungs, its probabilities there are within 1.1 points
   of what it says in every band** (receptions, completions and the three
   yardages). As it was, it was 4 to 8 points too sure from 65% up. This
   table flatters the main line: see "What is weak".
3. **Most of the gain is games missed; in this test the report adds
   little.** Report on top of games missed: carries −0.0031 (se 0.0013);
   targets −0.0010 (se 0.0007) and the other three, noise. The report
   makes the chance itself much better (Brier of the chance 0.0934 against
   0.1192). The test cannot see most of what a report is worth: the player
   ruled out is never graded; a quarterback ruled out changes nothing
   here, because the starter is whoever started last week; and stand-in
   lines do not move on news as a book's do.
4. **The chance is not biased from Week 2 on, and badly wrong in Week 1.**
   Week 2 on: said 72.2%, played 72.3% (23,686 listed player-games). Week
   1: said 76.6%, played 49.5% (1,642). Out and doubtful: said 0 to 1%,
   played 0%. Questionable: said 65.8%, played 62.0%. Where it says 5 to
   25% (4,571) they played 11.7% against 15.4%.

### What is weak

- **On the MAIN line its confident legs are too sure, the overs most
  (S21).** With the report, list not known: overs it put at 65% or better,
  1,183 legs, stated 72.0%, happened 65.5% (se 1.6); unders 4,346 legs,
  72.6% against 69.9% (se 0.8); its main-line bands from 65 to 80% come
  in 3.4 to 4.8 points under what they say. With the chance of playing
  the old lean toward the under has turned: from 75% up it is the overs
  that come in short.
- **Week 1 (S23).** A team's games are taken as one run across seasons, so
  in Week 1 "played the team's last game" means last season's finale. The
  chance it puts on that is 27 points too high. A real depth chart makes
  the list right; the chance on it would still need its own Week 1 count.
- **The starting quarterback has to be named.** The model gives the pass
  attempts to whoever the slate names; if he is out, his backup gets none.
- **Past reports cannot be dated for 2025 and 2026.** Those files carry no
  time stamps. In 2023 and 2024, 18 of 11,405 stamped rows were from game
  day or later and are left out. Each status played at the same rate in
  all three graded seasons (questionable 62%, 64%, 59%), which is what
  pre-game statuses would show; it is not proof. A Saturday downgrade
  would be in there, and would be a fair input.
- **It reads the game status only**, not practice participation, and
  knows nothing of injured reserve except through games missed.
- **"As if he plays, teammates at their chance" is an approximation.** It
  understates a player's expected share a little, most when one heavy
  teammate is near 50%. Argued, not measured.
- **The harness's list is cruder than a depth chart.** A real run should
  do better than "active in one of the last four games".
- **Not right for the list-known slate.** There everyone plays, and a
  questionable player's teammates would get a little too much. After
  inactives are posted, hand in 1 for everyone active.

### How it was checked

Within the budget set on 2026-11-20: the suite (657 checks, 51 of them
new); the leak probe on all 46 weeks (1,669,578 outputs identical; it
cannot see the reports); the walk-forward measurement above; reverts for
the new file only, each run once (62 in the end, 62 caught; the first pass
was 61 written and 58 caught, the 3 not caught being edits that changed
nothing, which were dropped along with the redundant filter they pointed
at); and ONE independent review pass.

The review reran the measurement, found every figure matching and no leak,
and returned fourteen defects. None was a wrong measured number, so there
was no second pass; **the fixes below have not been reviewed.** The ones
that mattered:

- **This week's injury report was being thrown away.** Reports were kept
  only for teams whose game was already on file, so for a live week every
  out or questionable player in a game not yet played read as "not on the
  report". The measurement could not see it; a shadow run would have been
  wrong from its first line. Fixed, and the suite now checks on real data
  that the newest week's report is there for every team that filed one.
- **"It runs 1 to 5 points high everywhere"** was one bad week averaged
  over the rest (finding 4).
- **"As good with the list not known as with it known"** compared two
  columns on different players and ignored that the point estimates and
  the mean miss are a little worse (finding 1).
- **"About 5 points too sure on both sides"** was the old model's figure
  under the new model's heading; and the lean "not being there" held only
  below 75%.
- **A check that could not fail** (an `or` that made a whole condition
  true), and a two-reports-in-a-week test whose rows happened to be in
  order already.

Fresh clone at commit d250e84 with the new and changed files added: engine
suite 1801, simulator suite 657, `sim_play.py` output identical to the
working copy's. No earlier revert was rerun: `ff_sim.py`, `ff_sim_opp.py`,
`ff_sim_eff.py` and sections 1 to 24 of the suite are byte for byte the
committed ones.

## S24. Touchdowns — MEASURED 2026-11-20

`ff_sim_td.py`. `TouchdownModel` sits on the efficiency model, passes its
eight stats through untouched, and adds two: `anytime_tds` (a player's
rushing plus receiving touchdowns, which is how an anytime prop settles)
and `passing_tds` (the named starter's). Three rates per player
(touchdowns per target, per carry, per pass attempt), each his own totals
leaning on the newest and pulled toward his position's rate; how hard to
pull is picked each week on the history, as for catches and yards. A
position has a rate of its own only on 200 or more targets, carries or
attempts in the history; a thinner one takes the all-player rate. A
player's receiving touchdowns are spread as his targets are and his
rushing touchdowns as his carries; the chance he scores is one minus the
chance of none of either. To put it on the chance-of-playing model:
`TouchdownModel("td", efficiency=EfficiencyModel("eff",
opportunity=ChanceOpportunity("opp", chance=PlayChance(reports))))`.

### What was measured (`sim_touchdowns.py`, run 2026-11-20)

46 weeks, 2024 Week 1 to 2026 Week 10, 694 games. An anytime line is
always a half (did he score), one leg a player-game. Passing touchdowns
have a short ladder of stand-in lines, 0.5 to 4.5.

**Brier score, gap to knowing nothing** (its size in standard errors in
brackets; knowing nothing scores 0.206 on anytime, 0.239 on the passing
main line):

| | list known: game-log | simulator | list NOT known: game-log | as it was | with the report |
|---|---|---|---|---|---|
| anytime touchdown (7,177 / 6,931 legs) | −0.0018 (1.0) | **−0.0112 (10.4)** | −0.0018 (1.0) | −0.0075 (6.5) | **−0.0116 (10.5)** |
| passing TDs, main line (1,211 / 1,117) | −0.0088 (2.2) | **−0.0177 (4.6)** | −0.0091 (2.2) | −0.0181 (4.7) | −0.0181 (4.7) |
| passing TDs, every rung (3,023 / 2,817) | −0.0027 (1.1) | **−0.0100 (3.7)** | −0.0030 (1.2) | −0.0098 (3.5) | −0.0098 (3.5) |

1. **It beats knowing nothing and the game-log model on both stats, on
   both slates.** Head to head with the game-log model on the same legs,
   list known: anytime −0.0094 (se 0.0013); passing main line −0.0089 (se
   0.0028); passing every rung −0.0073 (se 0.0019). List not known:
   anytime −0.0057 (se 0.0016) as it was and −0.0098 (se 0.0013) with the
   report; passing main line −0.0090 (se 0.0028); every rung −0.0068 (se
   0.0020). The gain over knowing nothing is real and small: about 5% off
   the know-nothing score on anytime.
2. **With the list not known the chance of playing matters for anytime**
   (−0.0075 without it, −0.0116 with; head to head −0.0041, se 0.0006)
   and changes nothing for passing touchdowns.
3. **The game-log model's anytime chances are badly spread**: where it
   said 0 to 10% they scored 16.7%, where it said 60 to 70%, 48.3%. The
   simulator's come in ABOVE what it said in every band of 100
   player-games or more: by 2 to 5 points with the list known, by 1 to 3
   with the report and the list not known (four of those five bands are
   inside their own range and read "as stated"; see "What is weak"). As
   it was, with the list not known, the bands from 10% to 60% come in 5
   to 10 points above.
4. **The pull is steady, and a regular's rate is still partly his own.**
   It mixes in 160 of the position's targets in 20 weeks, 320 in 25 and
   640 in 1; 160 carries in all 46; 320 pass attempts in all 46. By
   arithmetic, with the 16-game half-life a player's leaning total can be
   at most 23.6 games' worth: a receiver on 8 targets a game has at most
   189 behind him, so his rate is 37% his own at a pull of 320 and 54% at
   160; a back on 15 carries, 69% at 160; a starter on 34 attempts, 71%
   at 320.

### What is weak

- **It is low on the regulars and high on the fringe, and the two cancel
  (S25).** Anytime, list known, every active quarterback, back, receiver
  and tight end (17,642 player-games): said 15.63%, scored 15.98% (+0.35,
  se 0.24). That is two opposite errors. The 7,171 with a line: said
  26.0%, scored 29.0% (+3.0, se 0.5). The 10,471 without: said 8.52%,
  scored 7.05% (−1.47, se 0.23); quarterbacks −2.74 (se 0.79), backs
  −2.46 (se 0.53), receivers −1.45 (se 0.38), tight ends −0.19 (se 0.41).
  **The players a prop is written on are the ones it is low on.** With
  the report and the list not known, which is nearer a main run: said
  27.4%, scored 29.2% (+1.8, se 0.5); by band 10-20% said 16.5% scored
  17.3%, 20-30% 24.8% and 27.2%, 30-40% 34.2% and 35.3%, 40-50% 44.2%
  and 46.8%, 50-60% 53.7% and 56.6%; backs +2.2 (se 1.0), receivers +0.8
  (se 0.8), tight ends +3.2 (se 1.2), quarterbacks +2.8 (se 2.5).
  Where the gap comes from, list known (section 5; "give or take" is
  the spread over redraws of the games). Players with a line: 2,284
  touchdowns expected, 2,555 scored, 271 short. Too few targets and
  carries account for 97 of it (give or take 11; this is S11, parked),
  the rate for 173 (give or take 43): they scored 4.89 times per 100
  targets where it expected 4.60, and 3.70 per 100 carries where it
  expected 3.40. It is not the same at every position: for receivers the
  chances are the larger part (38 against 27, give or take 30); for
  backs, tight ends and quarterbacks the rate is (65, 50 and 30).
  Players without a line go the other way, 963 expected and 801 scored,
  and there it is mostly too MANY chances (102 of the 162) and a rushing
  rate that is too high (2.91 per 100 carries seen, 3.58 expected;
  quarterbacks 186 rushing touchdowns expected and 140 scored, backs 195
  and 141). Their receiving rate is right (4.58 seen, 4.51 expected).
  So a position's one rushing rate is too low for its regulars and too
  high for its fringe; for receiving that shows for the regulars only.
  Why is not tested.
- **Passing touchdowns run low in the middle of the ladder.** List known:
  over 0.5 said 72.2%, went over 74.6% (+2.4, se 1.6); over 1.5, 41.8% and
  46.8% (+5.1, se 1.6); over 2.5, 20.8% and 25.3% (+4.5, se 1.8); over
  3.5, +0.6; over 4.5, −2.0 (se 1.4). List not known it is the same or a
  little worse (over 1.5 +5.6, over 2.5 +5.2). With the list known,
  named starters were expected 1,949 touchdown passes and threw 2,018,
  and that too is two opposite errors: the 1,211 starts with a passing
  line, 1,722 expected and 1,837 thrown, nearly all of it rate (4.82 per
  100 attempts against 4.54 expected); the 177 without, 228 expected and
  181 thrown. Starters with a role are short 0.095 a game with the list
  known and 0.113 with it not known. On the main line the unders it put
  at 60% or better came in under what it said: 811 legs, stated 71.7%, happened 67.1% (−4.6, se 1.7) with the
  list known, 757 legs and −4.7 with it not known; the overs came in
  above, on few legs (116, +6.3, se 4.0; and 94, +10.4, se 4.3). **At 0.5,
  1.5 and 2.5 the game-log model's chances are nearer what happened**
  (over 1.5: said 47.5%, went over 46.8%), though it scores worse
  overall. On these stand-in lines a main-line passing-touchdown UNDER
  from the simulator is overstated.
- **Nothing about the offence or the opponent.** A player's rate is his
  own and his position's. A good offence shows up only through his own
  past touchdowns, and where on the field his touches come is not read at
  all. The closing total would be the obvious input; it is out by
  Dustin's decision of 2026-11-20 until the game-script stage.
- **FIRST TOUCHDOWN is not built (S26).** The brief asks for it. It needs
  every scorer in the game put in order, which is the game-level
  simulation, and the harness has no first-touchdown result to grade.
- **Two or more touchdowns is priced but barely checked.** No stand-in
  line grades it. Beside results, list known, the same 17,642: said
  2.35%, happened 2.70% (+0.35, se 0.12); players with a line 4.86% and
  5.83% (+0.97, se 0.27); where it said 10% or more (782 player-games),
  14.6% and 17.1% (se 1.3). The shortfall is on the players with a
  line, as it is for one-or-more; without a line it is right (0.63% and
  0.56%).
- **A player's rushing and receiving touchdowns are added as unrelated**,
  and each is spread exactly as his targets or carries are. Argued, not
  measured beyond the line above.
- **The 200 a position needs is a step.** Tight ends' carries passed 200
  in the history at 2025 Week 10, and that week every tight end's rate
  per carry went from the all-player 3.4 per 100 to tight ends' own (7.2
  now; by the reviewer's count about half of those carries and
  touchdowns are one player's). The reviewer put the largest move in a
  chance at about 3 points.
- **A whole team has to be on the slate, and the starter named** (for the
  live-run script to enforce). The model shares a team's targets and
  carries among whoever is listed: a receiver listed alone is given all
  of them. With no starter named, every passing number is blank and
  nothing says why. The plain model does not check that the slate is for
  the week its history stops at; the chance-of-playing model does.
- **The efficiency model's position rates have the hole this stage's
  review found here (S27).** `ff_sim_eff.py` gives a position its own
  catch rate, yards per catch and so on from any number of plays. It
  matters only for odd positions (a cornerback's targets, a non-
  quarterback's passes); the four skill positions are not touched.
- **Stand-in lines, and no prices.** An anytime "yes" at a book carries a
  wide margin. Nothing here says any of these chances beats a price.
- **Everything the opportunity model gets wrong is still in these
  numbers.**

### How it was checked

Within the budget set on 2026-11-20: the suite (710 checks, 53 of them
new); the leak probe on all 46 weeks (1,384,731 outputs identical; it
cannot see the reports); the walk-forward measurement above; reverts for
the new file only (95 in the end; see below); and an independent review.

**The review found a wrong number, so there was a second pass.** The
first pass reran the measurement (every figure matched, no leak) and
re-derived the model's numbers by plain loops on a real week to 1e-15.
What it found:

- **A position's rate was taken at face value on any number of plays.**
  A cornerback with targets was given a scoring chance of exactly 0 on
  three graded legs (his position had never scored) and scored on one; a
  defensive tackle was given 42%; a starter listed at running back would
  have been expected 6.2 touchdown passes. Fixed: a position needs 200
  of the thing for its own rate. The suite checks it on the fixture, at
  exactly 200 and 199, and on real history. The score table above is the
  same to four decimals before and after.
- **"Over everyone it is about right" hid two opposite errors**, and the
  write-up blamed too few chances first when the rate is the larger part
  (173 of 271). Both are now measured in the script (section 5) and
  stated above. A sentence blaming a thin first season was not supported
  (by the reviewer's count 2024 and 2025 differ by 1.1 points, se 1.1)
  and is gone.
- **A chance could come out a hair below zero** (−2e-16) far out on the
  ladder, which the harness refuses, and a far line lost precision.
  Chances are now added from the top: exact, never negative. A line that
  is not a number is refused by name.
- **The table behind the "where it is off" figures was in the script,
  untested.** It is now `ff_sim_td.parts_vs_actual`, checked by hand in
  the suite and covered by reverts. The splits made from it (who had a
  line; chances against rate) are still worked out in the script, which
  the suite does not import; the second pass rebuilt them independently
  and matched every figure.
- Smaller: figures quoted without their slate; "players" for
  player-games; sections 5 and 6 counted punters and linemen (now the
  four skill positions, 1,747 other player-games left out and said so).

**The second pass** was kept to the fixes and the rewritten write-up. It
found no wrong number: 54,000 chances against brute-force sums (worst
error 4e-14, none outside 0 to 1), the position floor recounted, every
figure in sections 5 and 6 rebuilt on all 19,389 rows. It did find
claims and a test to fix, and **those fixes have not been reviewed**:

- "One rate for a position is too low for its regulars and too high for
  its fringe" was stated as fact and is false for receiving on the
  fringe. The split for players without a line is now printed and the
  paragraph above says what it shows.
- The check that a player with no number is left out of the table could
  not fail. Replaced; the revert that had slipped past it is now caught.
- The 173 against 97 carried no error (now printed: give or take 43 and
  11), and the passing total pooled two opposite errors (now split).
- The label on players without a line said "not enough recent games";
  8,850 of the 10,471 had the games and not the role.

**Reverts, each run once on the file as it then stood.** One pass of all
95 after the first review's fixes: 93 caught, 2 not. One was an edit
that changed nothing (a guard the rewritten chance had made redundant;
guard and entry dropped). The other was the check above that could not
fail. The 18 entries those two edits touch were then run again: 18
caught. The other 77 were not rerun after those two edits. An earlier
pass on the code before the first review's fixes was stopped at 55 of 69
(54 caught; the one not caught was an edit that changed nothing, and
was dropped).

Fresh clone at commit 7175346 with the two new files and three changed
ones added: engine suite 1801, simulator suite 710, every revert entry
applies (611), `sim_touchdowns.py` output identical to the working
copy's. No engine file and no earlier simulator module was edited:
`ff_sim.py`, `ff_sim_opp.py`, `ff_sim_eff.py`, `ff_sim_play.py` and the
four earlier measurement scripts are byte for byte the committed ones,
and sections 1 to 28 of the suite are unchanged (the new sections are
added after them). No earlier revert was rerun.

---

## S28. The live-run script — BUILT 2026-11-21

`ff_sim_live.py` (the work, in the suite) and `sim_live.py` (the command).
It measures nothing new: it runs the simulator as measured in S13 and S24
on a week not yet played and sets the result beside that measurement.

```
python3 sim_live.py --week 11 --inputs week11.json odds/*.json
python3 sim_live.py --week 11 --inputs week11.json --ladders --out week11.csv odds/*.json
python3 sim_live.py --record --current-week 11     # rebuild sim_record.py, about 10 minutes
```

### What goes in

A shadow run happens in a project thread that has the PropLine and
FantasyPros tools. That thread saves files; this reads them.

1. **One saved `propline_get_odds` response per game** (pulled with
   `event_id`, `markets` and `bookmakers`): the dict, its text, the file
   the harness saved, with or without the harness's wrapper round it.
   Outcomes are paired by the engine's `ff_props.flatten_odds`. Only the
   lines are kept. **Prices are not read into the run, printed or saved.**
2. **An inputs file**: the week, each team's starting quarterback, and
   optionally injury statuses, chances of playing and players to add.

   ```json
   {"season": 2026, "week": 11,
    "starters": {"DEN": "Bo Nix", "LV": "Fernando Mendoza"},
    "statuses": [{"team": "DEN", "player": "Courtland Sutton", "status": "questionable"}],
    "chances":  [{"team": "LV", "player": "Brock Bowers", "chance": 0.0}],
    "add":      [{"team": "LV", "player": "Somebody Back", "position": "WR"}]}
   ```

   A team is its code or its full name. A player is his name, his
   nflverse id, or `espn:<id>`. A status is `out`, `doubtful`,
   `questionable`, `listed` (on the report, no game status) or `none`.
   A status handed in replaces the file's for that player and his chance
   is then counted from it as from any report; a chance handed in
   overrides both. Anything else in the file is refused, so a misspelt
   key cannot quietly lose a hand-in.
3. **This week's injury report**, which it fetches itself (nflverse).
4. **The record**, `sim_record.py`: the walk-forward record of this
   set-up, kept in the repository so a run takes seconds.

### What comes out

For every player with a posted line: his chance of playing and where it
came from, his projected stat line, and for each posted line the chance
of over and of under, the books posting it, the record of the band that
chance falls in, and any caution. Then what was posted for a player it
could not price, and why. Notes at the top say what the injury file has
for these teams, which teams have a bye-or-missing last game, what in a
file was passed over (markets it has no stat for, labels it could not
read), and how many ladder lines were priced and not shown. By default
only each book's main line and the anytime touchdown are shown;
`--ladders` shows every rung, alternate and 2+/3+ touchdown line;
`--out` saves the lines shown as a table to grade after the games.

- **The slate** is the harness's "list not known" slate, the one the
  record was measured on: everyone active for the team in one of its last
  four games, plus anyone added, plus the named starter.
- **Every number is "if he plays".**
- **The record beside a line** is read on HIS OWN stand-in rung nearest
  the posted line: the ladder the harness would give him this week (main
  line the half point above his eight-game median, the other rungs
  multiples of that median). So "his main line" is not the book's, and
  the S21 caution goes by his. A line further off either end of his
  ladder than half the gap to the next rung has no record. That holds
  for every stat, passing touchdowns included: a quarterback whose
  median is one touchdown pass has a record at 0.5 and 1.5 and none at
  2.5 and up. An anytime touchdown is read on the chance of scoring as
  stated. Two or more touchdowns has no record.
- **A player the record does not cover gets no record, and it says so.**
  The record grades only players the harness gives a stand-in line: four
  recent games and a role in them (a median of 3 targets, 5 carries or
  20 pass attempts; a passing role only for the starter).
- **Standing cautions, printed at the top and on the lines they touch:**
  what the record covers; the S21 main-line figures, with each stat's own
  on every line on a player's main line that it puts at 65% or better;
  **every passing-touchdown line marked "the UNDER is unreliable"
  (Dustin, 2026-11-21)**; S25.
- **A player is matched by the book's ESPN id** through the nflverse
  roster. With no id the roster has, he is matched by name on the two
  teams' slates if exactly one player has it, and the line says so.
- **Which team he is priced for.** The team the odds file puts him on,
  when it says (PropLine's `player_team`), and he must be on that team's
  slate; if he is not (he has just moved), he is listed under "posted
  but not priced" with that reason and is priced once he is added. Every
  outcome for him is pooled first, across books, and an outcome with no
  id is taken to be the player another outcome gives an id under the
  same name. If the file puts him on more than one team, or on a team
  that is not in the game, he is not priced. A name with no id is never
  enough when two players on these teams share it (a receiver and a
  linebacker of the same name): that line is not priced. When the file
  does not say,
  he is priced for the one slate he is on, unless the roster has him on
  the other team in this game, in which case he is not priced; on both
  teams' slates he is not priced. A slate player the roster has on any
  other team is named in a note at the top, because he is still counted
  as someone who may play for that team until his chance is handed in
  as 0.
- **Adding a player** takes anyone the roster or this season has: by id,
  or by name when nobody on the team has that name and one player in the
  league does. So a man who joined this week can be added before the
  roster file catches up. A starter, a chance or a status must name a
  player on the team or one added to it.

### It stops, saying what, when

an odds file cannot be read, is not an event response, or has outcomes
that do not pair up or are not in the shape of one; a team name is
unknown; a game is in progress, has kicked off, is outside the season,
or is not in this week (the Wednesday-to-Tuesday week after last week's
Sunday, from the game dates on file; with no dates to go by, more than
eight days off, and it prints that this was all it could check); no
week is given, it is not a whole number from 1 to 22, or it disagrees
with the inputs; the season is not the newest on file; the inputs hold
anything it does not know, list a player twice under statuses, chances
or add, or add a player at a position that is not QB, RB, FB, WR or TE;
a status is handed in for a player who is on both teams' slates (a
status goes with the player, so it would count for both: hand in a
chance for each team); a team in the files has no starter
named, or the starter is not listed at quarterback (add him with that
position if he really is starting); a name cannot be placed on its team
(the roster has him there, or he has played for it this season), two
players share it, or an id is given for a team the player is not on;
a status is not one of the five; a chance or a status is handed in for
someone not on the slate; last week is not on file, or fewer than half
the teams' games are; a game in the files has already been played; the
injury file has nobody from these teams this week (unless
`--allow-no-report`, which prints a warning first); the history is too
thin; `sim_record.py` is missing, not whole, or was built from other
model code; or the table cannot be saved. Anything it did not foresee,
and a failure to load the data or the record at all, also stops it with
words and not a traceback, under exit code 3 where the others give 2.

### Checked against a real response

One real `propline_get_odds` response was pulled on 2026-11-21 (Las Vegas
at Denver, DraftKings, passing touchdowns and 2+ touchdowns). The
engine's `flatten_odds` fits it as it is: an over/under pair comes back
as one line at its point, an "N+" rung with its number, a 2+ touchdown
outcome under the player's name, the D/ST row with no id. A trimmed copy
is in the suite, and the suite runs the real Week 11 slate on it: both
quarterbacks and every listed player found by id, including one the book
spells without his "Jr.". The other ten market keys it reads were all in
that event's own list of markets; their responses were not pulled.

### What is weak

- **Only passing touchdowns and 2+ touchdowns were seen in a real
  response.** Yardage, receptions, attempts, completions, targets, 3+
  touchdowns and the anytime touchdown are handled by the same code and
  tested on made-up boards in the real shape; none has been through a
  real file. The first shadow run is that test. What it cannot read it
  counts and says, and does not guess.
- **The record is on stand-in lines.** Nothing has been graded against a
  book's line (S3). A book's main line is often not the player's
  stand-in main line, which is why each line is read on his own nearest
  rung; how well a stand-in rung's record describes a book's line at the
  same number is not known.
- **The record is of a narrower run than a live one**, and the printout
  says so: it was graded with each team's last game's starter (not the
  one named), the injury file as it stood (nothing handed in), nobody
  added, and only for players with a stand-in line who went on to play.
  The starter differs in about 1 starter-week in 13 (the second review
  counted 106 of 1,388): a live run gives the passing record to the man
  named, the record was earned with the man who started the week before.
- **The injury file can be days behind, and it cannot tell.** On the
  night of Friday 2026-11-20 nflverse's Week 11 file had 293 players, 9
  of them out and 6 questionable, which reads like a midweek report and
  not the league's final one. So at a main run, hand in the statuses the
  thread can see (FantasyPros) for every game being priced; that is what
  `statuses` in the inputs is for. The printout gives the file's counts
  for the teams being priced and names any team with nobody on it.
- **Nothing checks the matchup against a schedule.** The week is what
  the inputs say. A game already on file is refused, and so is one whose
  kickoff is outside this week, but a wrong pairing inside the week
  would run. The week's dates come from last week's games in the
  play-by-play file; in Week 1, or without that file, it falls back to
  "not more than eight days off", which next week's Thursday game can
  pass from Wednesday on, and a note in the printout says so. A team
  whose last game is missing from the
  data cannot be told from a team coming off a bye: both get the same
  note.
- **A player back after more than four of his team's games out, or new to
  the team, is not on the slate** until he is added in the inputs. He
  shows up under "posted but not priced" with that reason. One case
  still prices a moved player for his old team: the book does not say
  which team he is on AND the roster file has not caught up with the
  move. Every player outcome in the real response carried the team, so
  this needs both sources to fail at once; the note at the top names
  him as soon as the roster does.
- **A player on both teams' slates whom the book does not place stays
  unpriced.** Nothing in the inputs settles it.
- **838 of 962 quarterbacks, backs, receivers and tight ends on the 2026
  roster have an ESPN id** (2026-11-21). The rest can only be matched by
  name.
- **A book's anytime touchdown pays on a return or a recovery; the model
  counts rushing and receiving.**
- **Saved runs are not yet graded.** `--out` keeps what is needed (S29).
- **`sim_live.py`'s own argument handling and `--record` writing are not
  in the suite**; what they call is (`shadow_run`, `build_record`), and
  the suite checks that the committed record matches the committed code.
- **The record does not grow by itself.** It is through 2026 Week 10 and
  stays valid as weeks are played, only older. It must be rebuilt, and
  committed, whenever one of the five model files changes; until then
  the script refuses to run. A change to how the record is built or laid
  out needs `LAYOUT` in `ff_sim_live.py` raised by hand.

### How it was checked

Within the budget: the suite (824 checks, 114 of them new); the leak probe, inside the
record build, on all 46 weeks; no walk-forward measurement of its own
(the record is S13's and S24's set-up again; its S21 figures on all nine
laddered stats are overs 72.2% stated and 66.9% happened on 1,823 legs,
unders 73.2% and 70.7% on 7,790, and the first review reproduced S13's
72.0%/65.5% and 72.6%/69.9% from its five-stat subset); reverts for the
new file only; an independent review, a second pass because the first
found wrong numbers, a third, narrow one on the fixes because the second
found one more, and a re-check of the third's findings by the same
reviewer. That is more review than the budget's one pass; every pass
found a wrong number, which is the budget's own condition for another.

**The reviews**, each by a reviewer given the code and questions, not
the reasoning.

- *First pass.* Two kinds of wrong number: a player on both teams'
  slates was priced for the home team without saying so, and the record
  was read on the wrong rung. Eight lesser defects. The module was
  rewritten.
- *Second pass.* One more wrong number: a traded player who was only on
  his old team's slate was priced for the old team though the book named
  the new one. Also passing touchdowns read against other quarterbacks'
  records, next week's Thursday game passing the eight-day rule, and
  inputs that should have been refused. It recomputed 629 priced lines
  with no other mismatch and found no leak.
- *Third pass, on those fixes only.* About 230 replays of real 2026
  players who changed teams; 256 passing-touchdown lines for 32 starters
  with no mismatch in rung, band or caution; 61 week windows over 903
  real games from 2023 to 2026 with no game refused or let in wrongly. It
  still found wrong numbers at the edges: the book's team not honoured
  when one outcome carried the player's id and another did not; a status
  handed in for a player's old team also counting on his new one; a team
  outside the game ignored; the eight-day fallback used without saying
  so; and a roster that had not caught up blocking a legitimate add.
- *Re-check by the same reviewer.* All of those fixed. It found one case
  the fix had opened: a line with a bare name was tied to a namesake's
  id in the same file and priced for the wrong man. That is fixed too: a
  bare name is tied to an id only when nobody else in the league has the
  name, and is not priced at all when two players on these teams share
  it. **This last fix has not been reviewed independently.** It was
  checked by the suite, by its own reverts, and by rerunning the
  reviewer's two reproductions, which now print no line for the
  namesake.

**Reverts** (`sim_reverts.py --fast`, the new file only). 380 reverts of
`ff_sim_live.py`. One pass of 378: 365 caught, 13 not. Three of the 13
change nothing and were dropped; nine showed a check that could not
fail, and each check was added or tightened; one was the namesake case
above. The 37 entries concerned were then run on the final file: 37
caught. The other 343 were not rerun after the last edit, which changed
only how a posted player is matched to a slate row. The runner's
controls passed in both runs. `--fast` is new: it runs the suite's
earlier sections once and each revert of this file on the rest; twelve
entries run both ways gave the same verdicts and the same failing
checks. The record in `sim_reverts.py` has the detail.

**Fresh clone** (2026-11-21: commit 5f441e8 with these six files laid
over it). Engine suite 1801, simulator suite 824, `sim_reverts.py
--check` 993 entries all applying. Sections 1 to 31 of the suite are byte
for byte as committed. `sim_live.py` on the real Week 11 file ran clean
and saved 17 lines with no price among them. By hand, since the command
itself is not in the suite: a broken `sim_record.py`, a missing one, a
week that disagrees with the inputs and a team with no starter each
stop it with words.

---

## Open

| id | what | status |
|---|---|---|
| **S2** | **Settings chosen, not measured: the test's, and now the model's.** | **OPEN.** The model's are eight numbers in `ff_sim_opp.py`: half-lives of 4 games (team volume), 3 (recent share) and 10 (longer-run share); no fit on fewer than 16 rows; the spread of targets and carries measured only on expected counts above 1 (on the history before 2026 Week 9 the targets size is 7.8 with the cut at 0, 8.5 at 1 and 11.3 at 3; carries 6.1, 6.4, 7.2); the spread held between sizes 1 and 500; a team never projected under 1. And one convention: with no start on record in the history, a starter is taken to throw every pass. None was tuned against the test. The test's own settings define the test, not a projection, and every projector is graded by the same test; they do change what it is a test of and how far apart two projectors look. All of them: a role is a median of 3 targets / 5 carries / 20 pass attempts; the line window is 8 games, with no line under 4; rungs at 0.6, 0.8, 1.0, 1.25 and 1.6 times the median; the main line is the half point above the median; slate B looks back 4 of the team's games; no verdict under 30 games; ranges and verdicts at 95%; under five hits or five misses each game counts once in a range; the yardsticks' "share over the line" is pulled half a game toward 50%; which positions get a projection with no role. The role floors are the ones to replace first: with what real boards actually post, once S3 has enough weeks. |
| **S3** | **Grade against real book lines.** | **OPEN, small sample.** Book lines exist from about 2026-11-06 (about 30 games). The same calibration table on real lines, beside the market's own de-vigged probability, is the Phase 2 test. Worth setting up early so the weeks accumulate. The market's line is a benchmark there, never an input and never a lean. |
| **S4** | **The opportunity model.** | **FIRST VERSION MEASURED 2026-11-20**, section above. Its open items are S11 to S16. |
| **S5** | **Version B does not know the roster.** | **NOTED.** It lists a player under every team he was active for in one of that team's last four games, and gives the quarterback line to whoever started that team's last game. So it counts a traded player as "did not play" for his old team and misses him on his new one, and in Weeks 1 to 4 it reaches into last season. A weekly roster file would fix it; `ff_data` does not load one (see "Needs"). A live run before inactives (S28) is this kind of slate, with the starter named and players added by hand; the traded player shows there on his old team's slate (and on both, if the two teams now meet), and S28 prices him only for the team the book puts him on, once he is on that team's slate. |
| **S6** | **Slate A is "has a snap row or a stat row", not the inactive list; the starter is "threw his team's first pass".** | **NOTED, and now it matters.** The opportunity model reads the slate, so slate A tells it a little more than an inactive list would: a player who dressed and never took a snap is not on it, so nobody on it is given a share and then sits. How much of the model's gain on slate A is this cannot be measured without an inactive list, which is not on file. A man who dressed and never took a snap is missing rather than a zero. 232 of 24,976 skill-position snap rows had no id to join on; 27 players never have a snap row and appear only in games where they recorded a stat. A starter hurt before his team's first pass play would be read as not having started. |
| **S7** | **A week is the unit of time.** | **NOTED.** A Thursday game is not used for that Sunday. Stricter than the brief asks, and simple. Postseason games are in neither the history nor the test. |
| **S8** | **The leak probe sees only what passes through the frame.** | **STANDING RULE.** A projector that carries its own copy of the data, or a constant typed into one that was worked out over all seasons, is invisible to it. So is a result that decides WHO IS ON THE SLATE: that is how the first quarterback rule leaked. Estimate everything inside `project()`, and when adding anything to a slate, ask whether it was knowable before kickoff. |
| **S9** | **`ff_sim.gamelog_blend` is a copy of `ff_props.threshold_prob`'s arithmetic.** | **PINNED.** The original costs 4 ms a call. `test_sim.py` section 6 runs both on real logs for all nine engine stats and fails by name if they differ. |
| **S10** | **`ff_sim.corr_joint` reads `ff_boost._pair_weight`**, a private name. | **NOTED.** If the engine renames it the import fails and says why. It is the table's r as a plain point estimate. It is not what `ff_boost.joint_error` does, and no table here calls it "the engine's". |
| **S11** | **Players with a line are given too little, small roles too much.** | **OPEN, measured.** About 4% too little on targets and carries, and their overs come in 3 to 4 points more often than stated (S4 findings 3 and 4). Why is not settled: the share fit pulling big and small together, or first-game and fringe players handed a position's average. Things to try, each graded the same way: a snap share as an input (the brief asks for it and the model does not read one), a share fit that is not a straight line at the top, giving a new or unseen player less than his position's average. |
| **S12** | **One spread per stat does not fit every size of role.** | **OPEN, measured.** Too wide for the biggest roles, too narrow for small ones (S4 finding 5). It is also measured before shares are scaled to the slate and applied after. Either may be part of why the top band is too sure (96.6% for a stated 97.1%; overs 94.5% for 96.7%); neither is tested. |
| **S13** | **Each player's chance of playing.** | **DONE 2026-11-20**, section above. Left open inside it: Week 1 (S23); practice participation is not read; the starting quarterback must be named at run time; the slate it is graded on is cruder than a depth chart; a status never seen in the history takes the all-player rate (every status has been seen since 2023). Hand-set numbers, not tuned: the look-back of four team-games (the harness's own), a pull of 20 rows toward each status's rate, no counting on fewer than 100 listed player-games. |
| **S14** | **The closing spread and total reach the model outside the harness.** | **OPEN pending Dustin's decision.** They are handed over at construction, where the leak probe cannot see. What stands there: the model looks a line up only for games in its history or on its slate; the suite checks that, and that moving a later game's line moves nothing. `_market`'s own refusal cannot fire from the code as it stands; it is a tripwire for a later edit. If Dustin wants them used, the right home is the harness's slate, which is a change to `ff_sim.py` and its reverts. The table of lines holds only games played, so a live week needs its lines supplied; a missing or non-numeric line stops the run and names the game. |
| **S15** | **Team volume is three separate fits; no plays, no pass rate, no snaps.** | **NOTED.** A team's projected targets and its quarterback's projected attempts are not tied to each other (projected targets ran 0.92 to 0.97 of projected attempts in the reviewer's check). Whether plays times pass rate does better is measurable and not yet measured. |
| **S16** | **Counts are independent across players.** | **NOTED.** The model states no chance of two legs together, so the pair report has nothing of its own to score yet. Pairs wait for a game-level simulation. |
| **S17** | **Efficiency.** | **FIRST VERSION MEASURED 2026-11-20**, section above. Its hand-set numbers, none tuned against the test: a 16-game half-life on a player's own totals; the list the pull is picked from (2 to 1,280, ten values); no rate learned from fewer than 16 games with an opportunity; a position needs 200 catches, carries or attempts in the history before it has its own spread of yards; yards per catch or carry never under a tenth of a yard. Open items S18 and S19. |
| **S18** | **Rushing yards are too sure.** | **OPEN, measured.** 2.4 to 3.6 points in every band from 65% up. The stated spread is 5% too narrow overall, 16% for backs expected 10 to 30 yards (20.42 actual against 17.59) and 18% for those expected under 10 (4.83 against 4.09). Why is not established. Candidates, none tested: the one-spread-per-stat carries count (S12; a reviewer found the squared miss per carry flat in carries, which points there rather than at yards per carry); the game script, not built; and 6.4% of player-games with a carry finishing below zero, which a gamma cannot give. |
| **S19** | **The distributions lean right and results do not.** | **OPEN, measured; WAITS until shadow runs start.** Every count here is a negative binomial, with more of its weight below its own average than above. Starters beat the model's expected completions and passing yards 51.0% and 50.6% of the time where it says 47.2% and 46.0%, with the expected numbers the right size. **Corrected 2026-11-20:** this section used to say "a stated over is worth a few points more than it says". That is true of the pooled table and of the low rungs and FALSE for confident overs on the main line, which come in about 5 points LESS often than stated (S21). Do not read a direction for a bet off S19. To try: a count with less lean for the same spread; a quarterback's attempts as a share of team plays rather than a free count. |
| **S20** | **Passing yards are spread too wide, and not sure enough.** | **OPEN, measured.** Stated spread 81.56 against 76.15 actual; a stated 82.5% came in at 85.9%. The model takes the variance of a game's passing yards to grow in step with attempts; a reviewer's check on the last graded history found the squared miss per attempt falling from about 120 below 29 attempts to 74 to 88 above 36, so it does not. Attempts and yards per attempt are not independent either (a quarterback throwing 45 times is usually behind). |
| **S21** | **Calibration pooled over all rungs hides opposite errors by rung.** | **OPEN, measured; found by the engine thread 2026-11-20 and reproduced here.** Simulator as it was, list known, catches and yards, favoured side: on the main line a stated 65-70% came in 61.1%, 70-75% 67.9%, 75-80% 72.6%; on the x0.6 rung the same bands came in 72.6%, 74.0%, 80.3%. Main-line legs it put at 65% or better: overs 920 legs, stated 72.5%, happened 67.5% (se 1.8); unders 5,874 legs, 73.5% against 68.6% (se 0.7). With the chance of playing, list not known: overs 72.0% against 65.5%, unders 72.6% against 69.9%. The game-log model's confident main-line overs: 69.7% stated, 57.9% happened. So every pooled calibration table in this file flatters the main line, which is the rung most like a posted line. `sim_play.py` section 5 prints the table rung by rung; `sim_opportunity.py` and `sim_efficiency.py` do not yet. A threshold must be read from the main-line row, and better from real posted lines (S3). |
| **S22** | **Parked until shadow runs start (Dustin, 2026-11-20):** S11, S12, S18, S19, S20. | **WAITING.** |
| **S23** | **The chance of playing is 27 points too high in Week 1.** | **OPEN, measured.** Said 76.6%, played 49.5% on 1,642 listed player-games; from Week 2 on, 72.2% against 72.3%. The count treats a team's games as one run across seasons. Fix: count season-openers apart (there are two seasons of them to count on by 2026), or do not carry a list across a season at all. Does not touch a shadow run started mid-season. |
| **S24** | **Touchdowns.** | **FIRST VERSION MEASURED 2026-11-20**, section above. Hand-set numbers, none tuned against the test: the efficiency model's 16-game half-life on a player's own totals and its floor of 16 games with an opportunity; the list the pull is picked from (20 to 10,240, ten values); 200 targets, carries or attempts before a position has a rate of its own. Open items S25, S26, S27. |
| **S25** | **Touchdown chances are low for regulars and high for fringe players.** | **OPEN, measured.** Anytime, list known: players with a line said 26.0%, scored 29.0% (se 0.5); players without said 8.52%, scored 7.05% (se 0.23). With the report and the list not known, players with a line +1.8 (se 0.5). Passing: over 1.5 said 41.8%, went over 46.8% (list known). Of the 271 touchdowns short on players with a line, too few targets and carries (S11) is 97 (give or take 11) and the rate 173 (give or take 43); on players without a line, of 162 too many, 102 is too many chances and the rest a rushing rate that is too high. One rate for a whole position is the likely cause on the rushing side; not tested. To try, each graded the same way: a position rate that rises with the size of the role; the team's scoring level; the closing total (Dustin's to decide, at the game-script stage). |
| **S26** | **First touchdown is not built.** | **OPEN.** The brief asks for it. It needs the game-level simulation (every scorer in order) and a first-touchdown result in the frame to grade against; play-by-play has it. |
| **S27** | **`ff_sim_eff.py` gives a position its own rates from any number of plays.** | **NOTED.** The hole the touchdown review found (S24), in the committed efficiency file: catch rate, yards per catch, yards per carry, completion rate and yards per attempt by position, on one play if that is all there is. Only odd positions are affected (a cornerback's targets; a starter not listed at quarterback would be pulled toward a few trick plays' completion rate). Fix with a floor like S24's when that file is next opened; its reverts then need rerunning. |
| **S28** | **The live-run script.** | **BUILT 2026-11-21**, section above. Hand-set, none tuned: the S21 caution starts at 65% (the engine thread's figure); a line is read on the player's own stand-in rung nearest it, and has no record further off his ladder than half the gap to the next rung; a week runs from 09:00 UTC on the Wednesday after last week's Sunday for seven days, and with no dates to go by a game more than 8 days off is refused; last week counts as on file when at least half the teams have a game in it. |
| **S29** | **Grade the shadow runs.** | **OPEN, next after the first runs.** `sim_live.py --out` saves each run's priced lines. Nothing yet joins a saved run to what happened, or sets it beside the book's own price (the saved odds files have the prices; reading them is Phase 2). This is also where S3 gets its first real lines. |

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
6. `ff_sim_play.py` fetches nflverse's `injuries` release itself, into
   `ff_data.CACHE` as `injuries_<year>.parquet`, using `ff_data.BASE` and
   `ff_data._is_stale` (a private name: if it is renamed the first fetch
   fails with an AttributeError naming it). `refresh.py` does not refresh it; it
   refreshes itself when older than the engine's six hours. If the engine
   wants injury reports too, the clean home is an `injuries` entry in
   `ff_data.ASSETS`.
7. **A shadow run needs steps in the project instructions** (the simulator
   thread does not edit them). In a project thread: for each game, pull
   `propline_get_odds` with `event_id`, the markets wanted (any of
   `player_pass_yds`, `player_pass_attempts`, `player_pass_completions`,
   `player_pass_tds`, `player_rush_yds`, `player_rush_attempts`,
   `player_reception_yds`, `player_receptions`, `player_reception_targets`,
   `player_anytime_td`, `player_2plus_td`, `player_3plus_td`) and the
   bookmakers, and let the harness save it; write the inputs file (S28)
   with every team's starting quarterback and the injury status of every
   listed player in those games as FantasyPros has it (the nflverse file
   can be days behind); run
   `python3 sim_live.py --week N --inputs FILE --ladders --out wkN.csv
   <the saved files>` (without `--ladders` only main lines and the
   anytime touchdown are shown); paste the printout. It is the simulator's shadow output, to
   be shown beside the engine's, never as a lean.

## Decided by Dustin

- **2026-11-20. The closing spread and total stay OUT for now.** Ask again
  at the game-script stage. (What they were worth: S4, finding 6.)
- **2026-11-20. Order of work:** efficiency first (done, S17), then the
  chance-of-playing fix (S13), built to accept each player's chance of
  playing as an input from the injury report at run time.
- **2026-11-20. How a live run is made:** the main run 3 to 6 hours before
  kickoff, before inactives, with a re-check after they post; early looks 1
  to 4 days out. By the main run the injury report and depth chart are
  known.
- **2026-11-20. Priority is a shadow run:** a script he can run on a real
  slate that prints each player's stat line and the chance of clearing
  each posted line. Order: S13 (done), touchdowns (done, S24), the
  live-run script.
  S11, S12, S18, S19, S20 wait until shadow runs have started.
- **2026-11-20. Testing budget per stage:** the suite, the leak probe, the
  walk-forward measurement, reverts for the new code only (run once), and
  ONE independent review pass; no second pass unless the first finds a
  wrong number; old reverts are not rerun. Write-ups keep to what was
  measured, what is weak, and what he needs to do.
- **2026-11-21. S25 is parked** with the other calibration items until
  shadow runs have started. One exception carried into the live output:
  **passing-touchdown unders are marked unreliable**, since they are
  overstated by about 5 points.
- **2026-11-21. A shadow run happens in a project thread** that has the
  PropLine and FantasyPros tools. The script's inputs are files that
  thread saves: a `get_odds` response for the posted lines (through
  `ff_props.flatten_odds`), the named starting quarterback per team, and
  any chance of playing handed in (built so a status can be handed in
  too, since the injury file lags). It prints each player's stat line and
  the chance of clearing each posted line, with the band's record and the
  S21 main-line caution, and stops, saying what, when something is
  missing.
- **2026-11-20. Past injury reports** are fetched by a simulator file of
  its own (he was offered that or the engine's loader, did not choose,
  and said to go straight on; this was the recommended option).

## Decisions waiting for Dustin

None. The probability threshold is his to set from the calibration tables
in S17 and S24; what those tables do not yet have is a book's line beside
them (S3). The first shadow runs (S28) and their grading (S29) are where
that starts.
