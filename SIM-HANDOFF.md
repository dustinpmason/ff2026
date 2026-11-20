# Simulator build — handoff

Written 2026-11-19 by the betting-engine build thread. A NEW general
thread (not a project thread) builds the simulator from this file. The
betting-engine thread stays open and keeps owning everything that exists
today.

---

## First thing: get the state

```bash
rm -rf ~/ff && git clone --depth 1 https://github.com/dustinpmason/ff2026.git ~/ff && cd ~/ff && python3 refresh.py
python3 test_regression.py        # expect: "1801 checks run, 1801 passed, 0 failed", ALL PASS
```

Quote the count the suite prints and nothing else. Then read, in this
order: this file; `HANDOFF.md` from "SHIP GATE" to the end; the last four
dated sections of `BACKLOG.md`. Do not read `PROJECT-INSTRUCTIONS.md`
end to end. It is 3,600 lines for the project threads that run boosts,
and the simulator thread needs none of it in context.

`HANDOFF.md` is the previous handoff, from 2026-11-05. **Its "Current
state" and "Next, in order" sections are stale. Its SHIP GATE and
"Standing lessons" sections apply here in full.**

## Who this is for and how the work moves

Dustin is building a fantasy football and NFL betting copilot. He is not
reading the code. He reads replies, commits files, runs prompts and
places bets.

- **The build thread cannot push to GitHub.** It writes files; Dustin
  uploads them to the public repo. After he says he has committed, clone
  again and check every file byte for byte before going on.
- **Project threads** live in his Claude Project. They clone the repo
  fresh, have PropLine, FantasyPros and Google Drive tools, and run
  prompts a build thread writes. He pastes or links their output back. A
  `claude.ai/share/...` link cannot be read with WebFetch: use the
  built-in browser (`navigate`, then `get_page_text`; if the page comes
  back empty, read it a second time).
- **What Dustin has asked for, standing:**
  1. Work is checked before it is delivered, not corrected after a
     follow-up. He wants to trust the first output.
  2. Anything he has to do or decide is given as numbered steps, not
     buried in prose.
  3. Honest uncertainty over false confidence, and recommendations
     justified.
  4. Do not disturb what is working. His live boost process must behave
     exactly as it does now until he chooses otherwise.
- **Replies:** the bottom line first, plain words, no internal labels or
  function names unless he needs to type them. He engages with technical
  detail when it is explained, not when it is assumed.
- **His email address is private.** Never write it into a file, a commit,
  a log or a request to any outside service.

## The one rule that keeps two build threads from colliding

**The simulator thread creates new files and edits no existing one.**

| Owned by the simulator thread | Owned by the betting-engine thread (read, never edit) |
|---|---|
| `ff_sim.py` (and `ff_sim_*.py` if it needs to split) | every existing `ff_*.py` |
| `test_sim.py`, its own suite with its own count | `test_regression.py` (stays at its own count) |
| `SIM-BACKLOG.md`, ids `S1`, `S2`, ... | `BACKLOG.md` (ids `B...`), `HANDOFF.md` |
| `sim_*.py` measurement scripts | `PROJECT-INSTRUCTIONS.md`, every prompt file |
| `SIM-INSTRUCTIONS.md`, when there is something to run | `shipset.py`, `refresh.py` |

Import from the engine freely. If the simulator needs a change in an
engine file, do not make it: write it under "Needs from the engine
thread" in `SIM-BACKLOG.md` and tell Dustin, who carries it over. On
2026-11-17 a project thread and the build thread edited the same files
and it took a three-way merge and a renumbering to recover (B238).

## What Dustin asked for, in his words (2026-11-19)

> "I want to use the stats that we have access to run the simulations, to
> try to identify as accurately as possible what certain game stat lines
> are. I know it's going to be impossible to get that 100%, but when
> something happens 60% of the time or 65% of the time, we can make that
> threshold. Then maybe that's where it's identifying those and using
> those to build the slips. We can figure out how it's building those
> slips at a later time. I'm just trying to have this be more stats
> driven than just trying to identify the mispriced options."

So the goal of this build is **accurate stat-line projections with honest
probabilities, from the stats**. Slip building is a later stage. He will
choose the probability threshold AFTER he has seen how each probability
band has actually performed.

## What exists that the simulator should use

| Module | What it gives |
|---|---|
| `ff_data` | `load_weekly(yr)`, `load_pbp(yr)`, `load_snaps(yr)`, `load_roster(yr)`, `data_status(yr, current_week=)`. Seasons on file: **2023, 2024, 2025 (weeks 1-22) and 2026 (through week 10 on 2026-11-19)**. |
| `ff_scoring` | `prepare(weekly, pbp)`, fantasy scoring under each league's real rules |
| `ff_props` | `norm_player`, `flatten_odds`, `devig`, `devig_field`, `threshold_prob` (the game-log model in use today), `snap_trend` / `snap_trends`, `role_trend`, `usage_trend` |
| `ff_guillotine` | `build_meta`, `normalize_name`, `resolve`, and a lineup simulator for the elimination league |
| `ff_correlation` | measured pair correlations by market and team relation |
| `ff_backtest` | an earlier backtest harness. **Read it before writing a new one.** |
| `ff_betlog` | the bet log: about 1,100 records on Drive, graded legs with the fair and the result. `load_drive_search` pulls it in one call. |
| `ff_boost` | the boost engine. Of interest here: `ANCHOR_DRIFT_BY_HOURS` and `anchor_drift` |
| `anchor_maturity.py`, `snap_volatility.py`, `model_vs_fair.py` | measurement scripts, each with its numbers in the docstring: the pattern to follow |

Data facts that have each cost a session something:

- Weekly rows: one per player per game. The team column is `team`. Keep
  `season_type == "REG"` unless playoffs are wanted. Its 150 columns
  include `targets`, `receptions`, `receiving_yards`, `carries`,
  `rushing_yards`, `attempts`, `completions`, `passing_yards`, and TDs.
- Play-by-play has 372 columns, among them `posteam`, `defteam`,
  `play_type`, `pass`, `rush`, `receiver_player_id`, `rusher_player_id`,
  `td_player_id`, `yards_gained`, `air_yards`, `score_differential`,
  `down`, `ydstogo`, `yardline_100`, and the game's closing
  **`spread_line` and `total_line`**.
- Snap counts are keyed by a different id from weekly stats; the roster
  maps one to the other (`snap_trend` shows how).
- A player with no row in a week did not play. That is a state, not a
  zero. A player's team in his last row goes stale after a move.
- Books spell names differently; Bovada appends the team ("David
  Montgomery (HOU)"). `norm_player` handles it.
- A fresh pull calls the latest week "in progress" when teams on a bye
  have no rows. Pass `current_week`.

## Measured facts the simulator must respect

Each of these was measured in this project. None is an opinion.

1. **On single legs the sharp market has beaten the stats model.** On 175
   graded legs the market's de-vigged probability scored 0.248 (Brier,
   lower is better) against 0.312 for `threshold_prob`. Where the model
   sat 10 or more points above the market, 25 of 68 won. So a gap between
   the simulator and the market is **not an edge until grading says so**.
   The market's line is a benchmark to be graded against. It is not an
   input in Phase 1, and it is never to be presented as a lean.
2. **A backtest here cannot measure profit.** About 84 independent games
   of price history give an error bar of ±23% on return (`HANDOFF.md`).
   **Calibration can be measured**, on tens of thousands of player-games
   since 2023. Those are different questions; do not let the second
   borrow the first's confidence, or the reverse.
3. **Rungs of one player's ladder win or lose together.** Count one
   observation per player, market and side (B213), and one cluster per
   game when stating an error bar.
4. **An unsteady snap share predicts a near-zero game.** After an
   UNSTABLE or LOW-after-a-real-role window, the next game is at or under
   15% of snaps 10 to 19% of the time, against 1.4% for a steady role
   (`snap_volatility.py`).
5. **A player back from weeks out is described by an old role.** David
   Montgomery's "last four games" on 2026-11-18 ended in Week 5 (B244).
   A projection must say when its newest input is.
6. **By side, in the log (leg counts, small):** recommended unders won 10
   of 19 against 10.2 predicted by their fairs; overs won 35 of 68
   against 42.2.
7. **Dustin's rule, settled:** no UNDER on a starter. A starter is a
   quarterback with a posted line; QB1, RB1, TE1 or WR1 to WR3 on the
   FantasyPros depth chart; 50% or more of snaps over his last three
   games; or 50% or more in his last game. Apply it and show its cost. Do
   not argue it.

## The plan

| Phase | What gets built | What has to be true to move on |
|---|---|---|
| **1** | The simulator, and a walk-forward test over every game from 2024 on | Calibrated: what it calls 60% happens about 60% of the time, for single stat lines and for pairs, and it beats the simple yardsticks |
| 2 | Agreement with the market where the market is sharp; shadow runs beside the live engine for about two weeks | Its probabilities grade at least as well as what the engine uses today |
| 3 | Slips and a whole-night view built from the simulation | Dustin is satisfied with the shadow results |

Nothing in his live process changes before Phase 3. A separate Claude
Project for running the simulator is created when Phase 2 starts, not
before.

### Phase 1, first task: the test harness

Build the thing that grades a projection before building the projection.

- **Walk forward.** For each regular-season game from 2024 Week 1 to the
  newest complete week, project every player using only data from before
  that game. 2023 is warm-up. No value from the game being projected, or
  from later, may reach its projection. Write a check that would fail if
  one did.
- **Two versions of every result: knowing who was active, and not.**
  Inactives are public about 90 minutes before kickoff, so live runs will
  know them. The gap between the two versions is what availability is
  worth, and it keeps a good-looking number from hiding a leak.
- **Yardsticks to beat,** each run through the same harness: the player's
  season-to-date average; his last-four average; `ff_props.threshold_prob`.
- **What to report:**
  1. Stat-line error. For targets, receptions, receiving yards, carries,
     rushing yards, pass attempts, completions, passing yards and
     touchdowns: the typical miss of the projected median, beside each
     yardstick's.
  2. Calibration of single lines. Group predictions by stated probability
     (50 to 55%, 55 to 60%, ...) and give how often each group happened,
     with the count and an error bar clustered by game. Historical book
     lines exist only from about 2026-11-06, so before that use a
     stand-in line, such as the player's trailing median, and say so.
  3. Calibration of pairs. For same-team and opposing pairs, the
     simulated chance both happen against how often both did, beside
     "multiply the two" and beside `ff_correlation`'s adjustment.
- **Then the opportunity model**, the first piece of the simulator: team
  plays, pass rate, and each player's share of snaps, targets and
  carries. Test the game's closing spread and total as inputs, with and
  without, and report both. They are market numbers; whether to use them
  is Dustin's call once he sees what they are worth.

After that, in order, each one measured against the harness before the
next is started: efficiency (catch rate, yards per touch, pulled toward
position norms); opponent; game script; touchdowns, including first
touchdown.

**Show Dustin the first accuracy numbers before building further.** In
plain words: "on receptions its typical miss is X catches, against Y for
his season average", and the calibration table. He decides the threshold
from that.

### What the output should look like, eventually

Per game, one table per player: the projected stat line with its range;
the chance of clearing each posted line; beside every probability, how
that band has performed ("legs it rated 65 to 70% have hit 67% of the
time since 2024, N games"); when its newest input is; and any snap or
absence flag.

### Not in Phase 1

Prices, EV, slips, boosts, the market as an input, and any change to an
existing file.

## Design notes from the engine thread — a starting point, not a decision

- Two shapes were discussed. A **structural** simulation plays the game:
  team plays, run or pass, who is targeted, catch, yards, score. It
  produces how outcomes move together for free, and covers anytime and
  first touchdown. A **statistical** one gives each player's stat a
  distribution and ties them with measured correlations. It is quicker,
  and it is roughly what `ff_correlation` already does pair by pair, with
  the gaps that implies. The engine thread leans structural. **Let the
  harness decide**, and start with whichever gets a graded number in
  front of Dustin soonest.
- The pairs the current engine cannot price are the opening: anything
  with a touchdown, first touchdown, and any pair outside the measured
  table. `score_slip` reports NOT PRICED AS A PARLAY for every same-game
  slip today.
- A night of slips shares one game. A simulation can say how often all of
  them lose together. Dustin has lost three slips to one team's run game
  on one night.

## Before saying "done"

The SHIP GATE in `HANDOFF.md` is the full list. The four that have caught
the most this fortnight:

1. **Break every new check.** Remove the behaviour and confirm a check
   fails. A crash counts; a pass does not.
2. **Run it on a fresh clone** with only the files being shipped added.
3. **Run every call you document or put in a prompt**, against real data,
   exactly as written. On 2026-11-18 a prompt called a function with
   three arguments it did not take.
4. **Derive an expectation from the data, never from a named player or a
   typed week.** Live data moves under a test.

Put each measurement's numbers, date and sample in the script's
docstring and in `SIM-BACKLOG.md`. A number with no artefact gets
re-derived, differently, two sessions later.

---

## Opening message for the new thread

> Clone https://github.com/dustinpmason/ff2026.git, run `refresh.py` and
> `test_regression.py`, and read `SIM-HANDOFF.md`. You are the simulator
> build thread it describes. Tell me the suite count and what you
> understand the first task to be, in a few lines, before you write any
> code. Then start Phase 1's first task.
