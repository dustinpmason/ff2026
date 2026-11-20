#!/usr/bin/env python3
"""S17. Efficiency on top of the opportunity model, through the harness:
receptions, receiving yards, rushing yards, completions and passing yards.

    python3 sim_efficiency.py --current-week 11

`--current-week` is the NFL week now in progress; every week before it is
graded. It takes about five minutes; the control runs first.

What it runs. `ff_sim.walk_forward` over every regular-season week from 2024
Week 1 with four projectors: the three yardsticks and `EfficiencyModel()`,
which sits on `OpportunityModel()` with no market numbers. Only the five
stats efficiency adds are reported; targets, carries and pass attempts are
in `sim_opportunity.py` and pass through unchanged. Sections 4 and 5 are
not from the harness: they set the model's expected numbers and spreads
(`ff_sim_eff.expected_vs_actual`) beside what happened, and list how hard
each rate was pulled toward the position.

RESULTS, run 2026-11-20. Sample: 46 weeks, 2024 Week 1 to 2026 Week 10,
694 games; players with a role who played; every error counts a game once.
"Know-nothing" says each stat and rung's own overall over-rate. "Simulator"
is the opportunity model with efficiency on top.

THE SHORT OF IT. With the active list known the simulator beats
know-nothing on the main line on all five stats: clearly on receptions,
receiving yards and rushing yards (6.7, 7.8 and 3.4 errors), thinly on
completions and passing yards (2.2 and 2.6). It beats the engine's
game-log model clearly on the first three; on the two passing stats its
single number is better and its main-line chances are not distinguishably
so. With the list NOT known it is no better than know-nothing on
receptions and receiving yards and worse on rushing yards: the
opportunity model's fault (S13), carried through. And its distributions
LEAN RIGHT where players' results do not: on every stat, players beat its
expected number 3 to 5 points more often than it says they will.

  Brier score on the MAIN line, lower is better (gap to know-nothing, se):
                          know-nothing  game-log            simulator
  ACTIVES KNOWN
    receptions      5,272   0.2421   0.2384 (-0.0036)   0.2287 (-0.0133, 0.0017)
    receiving yards 5,272   0.2481   0.2442 (-0.0039)   0.2367 (-0.0114, 0.0017)
    rushing yards   2,194   0.2474   0.2489 (+0.0014)   0.2364 (-0.0110, 0.0032)
    completions     1,121   0.2500   0.2417 (-0.0083)   0.2396 (-0.0104, 0.0047)
    passing yards   1,121   0.2500   0.2422 (-0.0078)   0.2394 (-0.0106, 0.0041)
  ACTIVES NOT KNOWN
    receptions      5,223   0.2423   0.2386 (-0.0038)   0.2463 (+0.0040, 0.0022)
    receiving yards 5,223   0.2482   0.2442 (-0.0040)   0.2478 (-0.0003, 0.0021)
    rushing yards   2,171   0.2475   0.2487 (+0.0012)   0.2556 (+0.0081, 0.0039)
    completions     1,070   0.2499   0.2404 (-0.0095)   0.2383 (-0.0116, 0.0046)
    passing yards   1,070   0.2500   0.2423 (-0.0077)   0.2409 (-0.0091, 0.0041)
  The simulator's gap to know-nothing is 6.7 to 7.8 errors on the two
  receiving stats, 3.4 on rushing yards, and only 2.2 and 2.6 on
  completions and passing yards. The game-log model's own gap is 2.2 to
  2.5 errors on receiving yards, completions and passing yards (on
  completions more errors than the simulator's, 2.5 against 2.2), and
  nothing on receptions (1.9) or rushing yards.
  Over EVERY RUNG the simulator's gap, known: receptions -0.0107,
  receiving yards -0.0120, rushing yards -0.0128, passing yards -0.0074
  (3.4 to 9.1 errors), and completions -0.0035 (se 0.0022, 1.6 errors:
  NOT distinguishable from knowing nothing). Not known: receptions +0.0037
  (2.3 errors, WORSE), receiving yards -0.0013 and rushing yards +0.0043
  (noise), completions -0.0042 (1.9, noise), passing yards -0.0069 (3.2).

  Simulator minus game-log model, Brier, on the legs both priced:
                     ACTIVES KNOWN                          NOT KNOWN, main
    receptions       main -0.0101 (se 0.0018)  all -0.0101  +0.0066 (se 0.0025)
    receiving yards  main -0.0091 (se 0.0017)  all -0.0107  +0.0023 (se 0.0024)
    rushing yards    main -0.0117 (se 0.0033)  all -0.0149  +0.0057 (se 0.0044)
    completions      main -0.0047 (se 0.0037)  all -0.0045  -0.0025 (se 0.0038)
    passing yards    main -0.0040 (se 0.0031)  all -0.0048  -0.0024 (se 0.0032)
  Known: clear on receptions, receiving yards and rushing yards (3.5 to
  5.7 errors on the main line, 6.1 to 8.0 over every rung). On completions
  and passing yards the main line is 1.3 errors, noise; over every rung it
  is 2.5 and 3.0. Not known: WORSE than the game-log model on receptions
  (2.6 errors), not distinguishable on the other four.

  Mean miss of the single number, same player-games in each row, and the
  simulator's bias (projected minus actual):
  ACTIVES KNOWN            season avg  last four  game-log  simulator   bias
    receptions      5,272     1.79       1.80       1.75      1.68     -0.14
    receiving yards 5,272    24.60      25.01      23.57     23.17     -1.83
    rushing yards   2,194    25.29      25.69      25.77     24.01     -2.25
    completions     1,121     5.30       5.25       4.85      4.75     -0.13
    passing yards   1,121    65.94      65.72      61.09     59.03     -3.68
  ACTIVES NOT KNOWN
    receptions      5,223     1.78       1.80       1.75      1.73     -0.67
    receiving yards 5,223    24.57      24.99      23.57     23.23     -7.74
    rushing yards   2,171    25.40      25.77      25.82     24.90     -9.09
    completions     1,070     5.24       5.29       4.92      4.81     -0.02
    passing yards   1,070    65.53      66.29      62.07     60.04     -2.55
  Simulator minus game-log model on the player-games both projected
  (5,719 / 5,719 / 2,381 / 1,211 / 1,211 known), in the order above:
  -0.071 (se 0.011), -0.531 (se 0.125), -1.770 (se 0.264), -0.154
  (se 0.060), -2.245 (se 0.642). Not known: -0.020 (se 0.013, noise),
  -0.429, -1.010, -0.126, -2.270, all distinguishable; but not known its
  single number runs 7.7 receiving yards and 9.1 rushing yards LOW, and on
  stats that lean right a low number is flattered by the mean miss.
  These are small in football terms: half a yard to two yards a game. On
  typical miss it is level with the game-log model on receiving yards
  (18.54 against 18.50). The single number is distinguishably better than
  the game-log model's on all five stats known (2.6 to 6.7 errors),
  completions and passing yards included.

  Calibration with actives known, the five stats together, read on the
  side favoured (2,835 to 10,718 legs a band; 95% ranges about a point
  either way overall):
    it said    happened   favoured OVER   favoured UNDER   game-log model
    50-55%      52.3%        55.0%           49.7%            52.4%
    60-65%      63.0%        65.5%           60.7%            59.8%
    70-75%      70.8%        72.7%           69.7%            68.3%
    80-85%      81.0%        82.7%           80.4%            76.4%
    90-95%      92.0%        91.6%           92.0%            87.1%
    95-100%     96.7%        93.4%           97.1%            91.7%
  Overall it is within 1.6 points of what it says in every band, and a
  little too sure from 70% to 90% (1.1 to 1.6 points). It still LEANS: up
  to 70% its overs come in 2.5 to 3.0 points MORE often than it says, and
  its unders 1.5 to 4.6 points LESS up to 90%. The game-log model on the
  same legs is 2.7 to 6.3 points too sure from 60% up. By family: receiving
  is within 2.4 points everywhere; RUSHING YARDS ARE TOO SURE by 2.4 to
  3.6 points in every band from 65% up; passing is, if anything, NOT SURE
  ENOUGH (a stated 82.5% came in at 85.9%, 62.5% at 66.3%; the rest as
  stated). With actives NOT known the simulator is badly overconfident,
  and up to 90% worse than the game-log model on that slate: 72.4% stated
  came in at 64.8% (game-log 68.4%), 82.5% at 74.7% (game-log 76.4%).
  Above 90% the two are level (92.5% came in at 87.6% and 87.2%).

  Expected number and spread beside what happened (section 4), actives
  known. "spread" is the root mean squared miss, "stated" what the model's
  own distribution implies:
    players with a stand-in line, and their main line:
      receptions      5,719: 3.50 actual vs 3.36 expected (+0.14, se 0.03);
                      said over 37.3%, went over 40.4% (+3.1 points, se 0.6)
      receiving yards 5,719: 40.08 vs 38.35 (+1.73, se 0.42);
                      said over 42.5%, went over 45.0% (+2.5, se 0.6)
      rushing yards   2,381: 47.90 vs 45.75 (+2.14, se 0.57);
                      said over 41.8%, went over 44.3% (+2.5, se 0.9)
      completions     1,211: 20.52 vs 20.37 (+0.14, se 0.17);
                      said over 45.7%, went over 49.5% (+3.8, se 1.4)
      passing yards   1,211: 227.68 vs 224.59 (+3.09, se 2.30);
                      said over 45.8%, went over 50.1% (+4.3, se 1.4)
    whole slate: receptions 1.52 expected, 1.50 actual; receiving yards
      16.66, 16.49; rushing yards 8.41, 8.38; a starter's completions
      20.33, 20.26 and passing yards 223.2, 222.9. No gap shown in any.
    by size: receiving yards 45 to 70 expected got 59.06 against 55.06
      (+4.00, se 1.01); 10 to 25 got 15.39 against 16.52 (-1.12, se 0.27).
      Rushing yards 60 to 90 got 74.83 against 70.67 (+4.15, se 1.55).
    spread, whole slate (actual, stated): receptions 1.46, 1.43; receiving
      yards 19.76, 20.40; rushing yards 13.63, 12.94; completions 6.10,
      6.13; passing yards 76.15, 81.56. By size: rushing yards 10 to 30
      expected 20.42 against 17.59 stated (too narrow); receiving yards
      70+ 44.55 against 50.65 and receptions 6+ 3.03 against 3.46 (too
      wide).
    THE SHAPE: how often he finished above the model's own expected
      number, against how often its distribution says he would:
                         every starter (1,388)      players with a line
      completions      51.0% vs 47.2% (+3.8, se 1.3)  52.3% vs 47.2% (+5.1)
      passing yards    50.6% vs 46.0% (+4.6, se 1.4)  52.7% vs 46.1% (+6.6)
      receptions                                      47.4% vs 44.4% (+3.0, se 0.7)
      receiving yards                                 44.4% vs 41.4% (+3.0, se 0.7)
      rushing yards                                   45.0% vs 42.2% (+2.8, se 0.9)
    rushing yards below zero, which the model cannot give: 6.4% of the
      5,709 player-games with a carry (9.2% at or below zero).
    where the quarterbacks sit: 1,044 of 1,388 starters are expected 18 to
      21 completions and 1,278 are expected 190 to 250 yards. It does not
      tell quarterbacks far apart.
  Read: totals are the right size. Players with a line are given 4 to 5%
  too little on receptions and yards, the opportunity model's shortfall
  carried through (S11). But the larger part of the lean is SHAPE. For
  starting quarterbacks the expected number is the right size (20.33
  against 20.26 completions, 223.2 against 222.9 yards) and they still
  beat it 51% of the time where the model's distribution says 46 to 47%:
  the model's counts lean right, and results do not. The same is in every
  count here; for receivers and rushers the table cannot separate it from
  their 4% shortfall. Spreads: receptions, receiving yards and completions
  close overall; passing yards about 7% too WIDE (81.56 stated against
  76.15), which goes with passing not being sure enough; rushing yards 5%
  too narrow overall and 16% too narrow at 10 to 30 yards expected (and
  4.83 against 4.09 under 10), which goes with rushing being too sure.
  Why is not established for either. NONE OF THIS IS FIXED HERE.

  How hard each rate was pulled toward the position, picked each week on
  that week's history: catch rate 80 targets in all 46 weeks; yards per
  catch 40 catches in all 46; yards per carry 160 carries in 43 weeks and
  80 in 3; completion rate 320 attempts in 32 weeks and 640 in 14; yards
  per attempt 160 attempts in all 46. Never at an end of the list. Read
  with the 16-game half-life, under which a player's leaned totals level
  off at about 24 games' worth: at 33 attempts a game a quarterback's
  completion rate is half his own after about 12 games at a pull of 320,
  and never more than about 70% his own. At 640 it takes about 40 games
  to be half his own and never passes about 55%.

  Control: leak probe clean on all 46 weeks, 1,759,176 projector outputs,
  407,853 of them the simulator's.

Limits, stated because the figures get quoted:
  - Lines are the harness's STAND-INS, not a book's. Nothing here is a
    price or an edge, and nothing here has been set beside a market line.
  - No opponent, no game script, no touchdowns: later stages.
  - "Actives known" is the harness's slate A: everyone who took a snap or
    recorded a stat, and who started at quarterback (SIM-BACKLOG S6). That
    is a little MORE than an inactive list tells you. "Not known" is slate
    B: everyone who played for a team in one of its last four games, and
    whoever started its last game (S5); the model shares a team's volume
    among all of them, including those who will not play (S13). A run made
    with the injury report in hand sits between the two, nearer the first.
  - The model reads the slate and the yardsticks do not.
  - Everything the opportunity model gets wrong is carried into these
    numbers: players with a line are given about 4% too few targets and
    carries (S11), and one spread per stat does not fit every role (S12).
  - The hand-set numbers (`ff_sim_eff.py`: a 16-game half-life, the list
    the pull is picked from, the fewest games a rate is learned from, the
    fewest catches before a position has its own spread, the floor under
    yards each) were chosen before the first run and not tuned. `BANDS`
    below is this script's own and only decides how section 4 is cut.

The control runs FIRST. If the leak probe finds anything, or cannot
measure, the run prints that and stops without a table.
"""
from __future__ import annotations

import argparse
import collections
import math
import statistics
import sys
import warnings

warnings.filterwarnings("ignore")

import pandas as pd

import ff_sim as fs
from ff_sim_eff import (COUNTS, ONE, RATES, YARDS, EfficiencyModel,
                        expected_vs_actual, with_main_line)
from sim_baseline import LABEL as BASE_LABEL, PLAIN, YEARS, hdr, newest_complete, show_cal

NEW = (*COUNTS, *YARDS)       # the five stats this stage adds
LABEL = dict(BASE_LABEL, efficiency="simulator so far")
SLATE = {"A": "ACTIVES KNOWN (slate A)", "B": "ACTIVES NOT KNOWN (slate B)"}
FAMILY = (("receiving", ("receptions", "receiving_yards")),
          ("rushing", ("rushing_yards",)),
          ("passing", ("completions", "passing_yards")))


def show_error(run: fs.Run) -> None:
    hdr("1. STAT-LINE MISS — players with a role who played; the same "
        "player-games for all four in each block")
    print("   typical miss = half the time it misses by less than this. "
          "bias = projected minus actual.")
    for version in ("A", "B"):
        e = fs.stat_error(run, version=version)
        for stat in NEW:
            s = e[e.stat == stat].set_index("projector")
            print(f"\n   {SLATE[version]} — {PLAIN[stat]}, "
                  f"{int(s.n.iloc[0]):,} player-games")
            print(f"   {'':<20}{'typical miss':>13}{'mean miss':>11}{'se':>7}"
                  f"{'bias':>8}")
            for n in run.names:
                print(f"   {LABEL[n]:<20}{s.loc[n, 'typical_miss']:>13.2f}"
                      f"{s.loc[n, 'mean_miss']:>11.2f}"
                      f"{s.loc[n, 'mean_miss_se']:>7.2f}{s.loc[n, 'bias']:>+8.2f}")
    print("\n   Pair by pair, on the player-games BOTH projected (so the "
          "counts differ from the blocks above):")
    for version in ("A", "B"):
        print(f"   {SLATE[version]}")
        for b in ("gamelog_model", "season_avg"):
            c = fs.compare_error(run, "efficiency", b, version=version)
            for stat in NEW:
                r = c[c.stat == stat].iloc[0]
                print(f"     {LABEL['efficiency']} minus {LABEL[b]}, "
                      f"{PLAIN[stat]} ({int(r['n']):,}): mean miss "
                      f"{r['diff']:+.3f} (se {r['se']:.3f}) — {r['read']}")


def show_scores(run: fs.Run) -> None:
    hdr("2. AGAINST KNOWING NOTHING ABOUT THE PLAYER — Brier score, lower is "
        "better")
    print("   'Knowing nothing' says each stat and rung's own overall rate, "
          "worked out on the legs it is scored on.")
    for version in ("A", "B"):
        for label, rung in (("the main line only", fs.MAIN),
                            ("every rung of the ladder", None)):
            for stat in NEW:
                ref = fs.reference_brier(run, version=version, stats=[stat],
                                         rung=rung)
                print(f"\n   {SLATE[version]} — {PLAIN[stat]}, {label}: "
                      f"{ref['n']:,} legs in {ref['games']} games; knowing "
                      f"nothing {ref['brier']:.4f}")
                for n in run.names:
                    c = fs.compare_reference(run, n, version=version,
                                             stats=[stat], rung=rung)
                    print(f"   {LABEL[n]:<20} {ref['brier'] + c['diff']:.4f}   "
                          f"({c['diff']:+.4f}, se {c['se']:.4f}, "
                          f"{abs(c['diff']) / c['se']:.2f} errors — {c['read']})")
    print("\n   The simulator minus the game-log model, on the legs both "
          "priced (actives known, then not known):")
    for version in ("A", "B"):
        for stat in NEW:
            for label, rung in (("main line", fs.MAIN), ("every rung", None)):
                c = fs.compare_brier(run, "efficiency", "gamelog_model",
                                     version=version, stats=[stat], rung=rung)
                print(f"   {'known' if version == 'A' else 'not known':<10} "
                      f"{PLAIN[stat]:<16} "
                      f"{label:<10} {c['n']:>6,} legs  Brier {c['diff']:+.4f} "
                      f"(se {c['se']:.4f}, {abs(c['diff']) / c['se']:.1f} "
                      f"errors) — {c['read']}")


def show_calibration(run: fs.Run) -> None:
    hdr("3. CALIBRATION — the five stats together, read on the side each "
        "favoured")
    for name in ("efficiency", "gamelog_model"):
        g = fs.graded_legs(run, name, stats=list(NEW))
        print(f"\n   {LABEL[name]}, actives known: every leg")
        show_cal(fs.calibration(g))
        for side in ("OVER", "UNDER"):
            print(f"\n   {LABEL[name]}, actives known: legs it favoured the "
                  f"{side} on")
            show_cal(fs.calibration(g[g.side == side]))
    for family, stats in FAMILY:
        print(f"\n   {LABEL['efficiency']}, actives known, {family} only "
              f"({', '.join(PLAIN[s] for s in stats)}): every leg")
        show_cal(fs.calibration(fs.graded_legs(run, "efficiency",
                                               stats=list(stats))))
    for name in ("efficiency", "gamelog_model"):
        print(f"\n   {LABEL[name]}, actives NOT known: every leg")
        show_cal(fs.calibration(fs.graded_legs(run, name, version="B",
                                               stats=list(NEW))))


#: Bands of the model's expected number, per stat, for section 4. This
#: script's own; they only decide how the table is cut.
BANDS = {"receptions": (0, 1, 2, 4, 6, 999),
         "receiving_yards": (0, 10, 25, 45, 70, 999),
         "rushing_yards": (0, 10, 30, 60, 90, 999),
         "completions": (0, 18, 21, 24, 999),
         "passing_yards": (0, 190, 220, 250, 999)}


def show_sizes(run: fs.Run, frame: pd.DataFrame) -> None:
    hdr("4. IS THE EXPECTED NUMBER THE RIGHT SIZE, AND ITS SPREAD THE RIGHT "
        "WIDTH — actives known")
    print("   Every player on the slate given a number, not only those with "
          "a role. 'gap' is actual minus\n   expected; its error counts a "
          "game once. 'spread' is the root of the mean squared miss; "
          "'stated'\n   is the same thing as the model's own distribution "
          "would have it.")
    rows = expected_vs_actual(EfficiencyModel(), frame, run.weeks, stats=NEW)
    for stat in NEW:
        r = rows[rows.stat == stat]
        print(f"\n   {PLAIN[stat]}")
        print(f"   {'expected':<12}{'player-games':>13}{'expected':>10}"
              f"{'actual':>9}{'gap':>9}{'se':>7}{'spread':>9}{'stated':>9}   read")
        edges = BANDS[stat]
        bands = [(lo, hi, r[(r.expected >= lo) & (r.expected < hi)])
                 for lo, hi in zip(edges, edges[1:])] + [(None, None, r)]
        for lo, hi, b in bands:
            if not len(b):
                continue
            gap, se, n, games = fs.cluster_mean(b.actual - b.expected, b.game_id)
            label = ("everyone" if lo is None else
                     f"{lo}+" if hi == 999 else f"{lo} to {hi}")
            if games < fs.MIN_GAMES_FOR_VERDICT or not se > 0:
                read = "too few games to say"
            elif abs(gap) < fs.Z95 * se:
                read = "no gap shown"
            else:
                read = ("he gets MORE than expected" if gap > 0
                        else "he gets LESS than expected")
            print(f"   {label:<12}{n:>13,}{b.expected.mean():>10.2f}"
                  f"{b.actual.mean():>9.2f}{gap:>+9.2f}{se:>7.2f}"
                  f"{math.sqrt(((b.actual - b.expected) ** 2).mean()):>9.2f}"
                  f"{math.sqrt(b.variance.mean()):>9.2f}   {read}")

    j = with_main_line(run, rows, "efficiency", stats=NEW)
    print("\n   Players with a stand-in line only, and their MAIN line (the "
          "players sections 2 and 3 are about)")
    print(f"   {'stat':<17}{'player-games':>13}{'expected':>10}{'actual':>9}"
          f"{'gap':>9}{'se':>7}{'said over':>12}{'went over':>11}{'gap':>8}"
          f"{'se':>7}")
    for stat in NEW:
        b = j[j.stat == stat]
        gap, se, n, _ = fs.cluster_mean(b.actual - b.expected, b.game_id)
        og, ose, _, _ = fs.cluster_mean(b.over.astype(float) - b.said, b.game_id)
        print(f"   {PLAIN[stat]:<17}{n:>13,}{b.expected.mean():>10.2f}"
              f"{b.actual.mean():>9.2f}{gap:>+9.2f}{se:>7.2f}"
              f"{b.said.mean():>12.1%}{b.over.mean():>11.1%}{og:>+8.1%}{ose:>7.1%}")

    print("\n   THE SHAPE. How often he finished ABOVE the model's own expected "
          "number, beside how often the\n   model's distribution says he "
          "would. Where the expected number is the right size (completions "
          "and\n   passing yards) a gap here is the SHAPE of the distribution "
          "alone; for receivers and rushers with\n   a line it also holds "
          "their expected number running about 4% low.")
    print(f"   {'stat':<17}{'who':<22}{'player-games':>13}{'model says':>12}"
          f"{'he did':>9}{'gap':>8}{'se':>7}")
    for stat in NEW:
        for who, d in (("with a line", j[j.stat == stat]),
                       ("everyone given one", rows[rows.stat == stat])):
            did = (d.actual > d.expected).astype(float)
            gap, se, n, _ = fs.cluster_mean(did - d.said_above, d.game_id)
            print(f"   {PLAIN[stat]:<17}{who:<22}{n:>13,}{d.said_above.mean():>12.1%}"
                  f"{did.mean():>9.1%}{gap:>+8.1%}{se:>7.1%}")
    ran = frame[frame.t.isin(list(run.weeks)) & (frame.carries > 0)]
    print(f"\n   Rushing yards below zero, which the model cannot give: "
          f"{(ran.rushing_yards < 0).mean():.1%} of the {len(ran):,} "
          f"player-games with a carry\n   ({(ran.rushing_yards <= 0).mean():.1%} "
          f"at or below zero). No line is set there.")


def show_pull(run: fs.Run, frame: pd.DataFrame) -> None:
    hdr("5. HOW HARD EACH RATE WAS PULLED TOWARD THE POSITION — picked each "
        "week on that week's history")
    print("   In the rate's own opportunities: a pull of 80 on the catch "
          "rate means a player with 80 targets\n   behind him is half "
          "himself and half his position.")
    picked = collections.defaultdict(list)
    model = EfficiencyModel()
    for t in run.weeks:
        fit = model.fit(fs.History(frame[frame.t < t], t))
        for rate in RATES:
            picked[rate].append(fit.rate[rate]["k"])
    for rate, (num, den) in RATES.items():
        ks = picked[rate]
        counts = ", ".join(f"{k:g} in {n} weeks"
                           for k, n in sorted(collections.Counter(ks).items()))
        print(f"   {rate.replace('_', ' '):<18} ({PLAIN[num]} per "
              f"{ONE[den]}): median {statistics.median(ks):g}; {counts}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--current-week", type=int, default=None)
    args = ap.parse_args()
    pd.set_option("display.width", 200)

    through = newest_complete(args.current_week)
    frame = fs.load_frame(YEARS)

    def projectors():
        return [*fs.yardsticks(), EfficiencyModel("efficiency")]

    if args.current_week is None:
        print(f"NOTE: no --current-week given, so the newest week on file is "
              f"treated as unfinished. Grading through {through}.")
    run = fs.walk_forward(frame, projectors(), through=through)
    print(run.describe())

    hdr("CONTROL — run before any table")
    probe = fs.leak_probe(frame, projectors(), run.weeks)
    print("   " + probe.describe())
    print("   outputs compared, by projector: " + str(probe.outputs))
    if not (probe.clean and not run.unverified):
        print("   THIS RUN IS VOID — no table is printed")
        return 1
    print(f"   control passed on all {len(run.weeks)} graded weeks.")

    show_error(run)
    show_scores(run)
    show_calibration(run)
    show_sizes(run, frame)
    show_pull(run, frame)
    return 0


if __name__ == "__main__":
    sys.exit(main())
