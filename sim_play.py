#!/usr/bin/env python3
"""S13. Each player's chance of playing, from the injury report and games
missed, and what the simulator scores with it when the active list is not
known.

    python3 sim_play.py --current-week 11

`--current-week` is the NFL week now in progress; every week before it is
graded. It takes about six minutes; the control runs first.

What it runs. `ff_sim.walk_forward` over every regular-season week from 2024
Week 1 with four projectors: the engine's game-log model; the simulator as
it was (`EfficiencyModel()`); the simulator with chances of playing counted
from games missed alone; and with the injury report as well. The last two
are scored on the harness's slate B, the list of who had been playing for
each team, which is the nearest thing here to the list in hand before
inactives are posted. Section 1 is not from the harness: it sets the chance
each listed player was given beside whether he played
(`ff_sim_play.chance_vs_played`). Section 5 is the by-rung calibration
table asked for on 2026-11-20.

RESULTS, run 2026-11-20. Sample: 46 weeks, 2024 Week 1 to 2026 Week 10,
694 games; every error counts a game once. "List not known" is the
harness's slate B. Scores are on the legs all four projectors here priced,
so the "list known" column can differ from `sim_efficiency.py`'s in the
third decimal (that script also needs a season average to exist).

THE SHORT OF IT. With a chance of playing on every listed player, the
simulator with the active list NOT known scores close to what it scores
with the list known (a little behind on most stats, and on a slightly
different set of players: the list-not-known slate cannot grade a man
new to a team or back after more than four games). Without it, it was
worse than knowing nothing. Most of the gain comes from counting games
missed; in THIS test the injury report adds little on top (carries, 2.4
errors; the rest noise). This test cannot see most of what a report is
worth: the player ruled out is never graded, a quarterback ruled out
changes nothing here because the starter is whoever started last week,
and stand-in lines do not move on news as a book's do.

  The chance of playing itself. 25,328 listed player-games; 29.2% did not
  play for that team.
                         listed   it said   played
    not on the report    21,007    73.8%     72.0%
    on it, no status      2,497    92.2%     91.6%
    questionable            861    65.8%     62.0%   (gap -3.7, se 1.6)
    doubtful                114     1.3%      0.0%
    out                     849     0.0%      0.0%
    missed 0 of last 4   19,394    88.2%     87.2%
    missed 1              2,468    27.0%     23.5%
    missed 2              1,872    18.8%     15.3%
    missed 3              1,594    15.2%      9.8%
    everyone             25,328    72.5%     70.8%   (gap -1.7, se 0.3)
    Week 1                1,642    76.6%     49.5%   (gap -27.1, se 1.4)
    Weeks 2 to 4          6,396    63.1%     60.2%   (gap -3.0)
    Week 5 on            17,290    75.6%     76.8%   (gap +1.2)
    Week 2 on            23,686    72.2%     72.3%   (gap +0.1, se 0.2)
  From Week 2 on it is not biased overall. IN WEEK 1 IT IS BADLY WRONG:
  the "last four games" are last season's, and half the players listed
  from them are gone. That one week is the whole of the 1.7-point gap for
  everyone. Elsewhere it is uneven: where it says 5 to 25% (4,571
  player-games) they played 11.7% against 15.4%; where it says 25 to 50%
  (250, nearly all from the first two weeks of 2024) 13.2% against 28.7%;
  questionable 3.7 points high. Brier score of the chance: 0.0934 with the
  report, 0.1192 from games missed alone, 0.2066 saying the overall rate
  for everyone.

  Brier score on the MAIN line, gap to knowing nothing (standard errors):
                    list KNOWN    |           list NOT known
                    simulator     | game-log   as it was   games missed  +report
    targets         -0.0141 (8.6) | +0.0013    +0.0078     -0.0127       -0.0138 (8.0)
    carries         -0.0227 (7.7) | +0.0026    +0.0130     -0.0181       -0.0212 (7.4)
    receptions      -0.0137 (8.5) | -0.0035    +0.0030     -0.0135       -0.0135 (7.9)
    receiving yards -0.0129 (7.9) | -0.0042    -0.0019     -0.0136       -0.0135 (8.2)
    rushing yards   -0.0103 (3.4) | +0.0010    +0.0067     -0.0093       -0.0089 (2.9)
    pass attempts   -0.0179 (4.3) | -0.0066    -0.0184     -0.0184       -0.0184 (4.3)
    completions     -0.0123 (2.7) | -0.0087    -0.0112     -0.0112       -0.0112 (2.5)
    passing yards   -0.0128 (3.3) | -0.0086    -0.0111     -0.0111       -0.0111 (2.8)
  The three passing stats do not move: the chance of playing changes how
  targets and carries are shared and nothing else.
  With the report, list not known, on the legs both priced (main line):
    against the simulator as it was: targets -0.0215 (se 0.0022), carries
      -0.0343 (se 0.0033), receptions -0.0165 (se 0.0019), receiving yards
      -0.0116 (se 0.0016), rushing yards -0.0156 (se 0.0026).
    against the game-log model: -0.0151 (se 0.0018), -0.0238 (se 0.0035),
      -0.0099 (se 0.0017), -0.0093 (se 0.0015), -0.0099 (se 0.0033) in the
      same order; pass attempts -0.0117 (se 0.0036); completions -0.0025
      and passing yards -0.0024 (se 0.0038 and 0.0032: noise).
    against games missed alone: targets -0.0010 (se 0.0007, noise),
      carries -0.0031 (se 0.0013), receptions, receiving yards and rushing
      yards +0.0000 to +0.0004 (noise).

  Mean miss and bias (projected minus actual):
                     list known       NOT known, as it was   with the report
    targets          2.17 (-0.21)     2.26 (-0.96)           2.19 (+0.11)
    carries          3.88 (-0.43)     4.34 (-1.95)           3.96 (-0.04)
    receptions       1.68 (-0.14)     1.73 (-0.65)           1.70 (+0.08)
    receiving yards  23.14 (-1.73)    23.28 (-7.50)          23.53 (+0.69)
    rushing yards    23.93 (-2.14)    24.75 (-8.72)          24.47 (-0.43)
  The large bias is gone. The mean miss is still a little worse than with
  the list known on all five (on different players, as above), and on
  receiving yards it went UP a quarter of a yard as the bias went: a
  number that runs low is flattered by the mean miss on stats that lean
  right.

  Calibration, list NOT known, with the report: receptions, completions
  and the three yardages (the stats props are written on; two of them,
  completions and passing yards, are not moved by the chance of playing),
  read on the side favoured (2,233 to 10,488 legs a band):
    it said    happened   favoured OVER   favoured UNDER   as it was
    50-55%      52.0%        52.5%           51.5%          51.2%
    60-65%      62.1%        62.5%           61.8%          59.0%
    70-75%      72.3%        71.5%           72.8%          64.8%
    80-85%      82.3%        83.0%           82.0%          74.7%
    90-95%      92.9%        91.5%           93.3%          87.6%
    95-100%     96.9%        91.4%           97.7%          93.2%
  Pooled over the rungs it is within 1.1 points in every band and "as
  stated" in nine of ten, where the simulator as it was is 4 to 8 points
  too sure from 65% up. Up to 75% overs and unders both read as stated.
  From 75% up the overs come in BELOW the unders in four bands of five
  (75-80%: 74.9% against 77.2%; 95-100%: 91.4% against 97.7%), and the
  single number now runs slightly high on three stats of five (targets,
  receptions, receiving yards). So with the chance of playing the lean has
  turned: it is the confident OVERS that are overstated.

  RUNG BY RUNG (section 5), same five stats, favoured side. Pooling the
  rungs hides opposite errors. Two rungs that land on one line are one leg
  under the rung nearer the main line, so the columns are not all the same
  players.
    simulator as it was, list known:
    it said    x0.6     x0.8     main     x1.25    x1.6
    65-70%     72.6%    66.7%    61.1%    66.1%    67.3%
    70-75%     74.0%    72.3%    67.9%    69.7%    70.3%
    75-80%     80.3%    75.3%    72.6%    75.3%    77.0%
    with the report, list not known:
    65-70%     68.8%    68.2%    63.4%    67.9%    68.3%
    70-75%     74.1%    69.0%    69.0%    73.3%    74.9%
    75-80%     76.6%    73.1%    72.6%    77.0%    78.7%
  On the MAIN line, legs it put at 65% or better:
    simulator as it was, list known:  overs 920 legs, stated 72.5%,
      happened 67.5% (-5.0, se 1.8); unders 5,874, 73.5% -> 68.6% (-4.9,
      se 0.7).
    with the report, list not known:  overs 1,183, 72.0% -> 65.5% (-6.5,
      se 1.6); unders 4,346, 72.6% -> 69.9% (-2.7, se 0.8).
    game-log model, list known:       overs 1,424, 69.7% -> 57.9% (-11.8,
      se 1.5); unders 2,754, 72.4% -> 69.7% (-2.7, se 1.0).
  So on the main line, the rung most like a posted line, every model here
  is too sure. The simulator as it was: about 5 points on both sides.
  With the report: overs 6.5 points, unders 2.7; its main-line bands from
  65 to 80% come in 3.4 to 4.8 points under what it says. The game-log
  model: overs 12 points. In the simulator as it was the low rung (x0.6)
  errs the other way, most at 65-70% (72.6% for a stated 67.5%); with the
  report that is gone, and what is left at the low rungs is close. The
  pooled tables above average the main line's error away.

  Control: leak probe clean on all 46 weeks, 1,669,578 projector outputs,
  407,853 from each of the three simulators.

Limits, stated because the figures get quoted:
  - Lines are the harness's STAND-INS, not a book's.
  - The "list not known" slate is everyone active for a team in one of its
    last four games, and whoever started its last game at quarterback. A
    real run has a depth chart, which is better than that, and names its
    own starter.
  - The report's status is the last one on file for the week. In 2023 and
    2024 the file carries time stamps and 18 of 11,405 were from game day
    or later (left out); the 2025 and 2026 files carry none, so for those
    seasons it is taken on trust that the status is the pre-game one. The
    rates at which each status played are the same in all three graded
    seasons, which is what a pre-game status would show.
  - The reports reach the model outside the harness, where the leak probe
    cannot see. A report is only looked up for a game in the history by
    its own week, or for the week being projected.
  - On the "list known" slate the chance models are NOT the right tool:
    there everyone listed plays, and a questionable player's teammates
    would be given a little too much. Their numbers are shown on the
    list-not-known slate only. After inactives are posted, hand in 1 for
    everyone active.
  - Everything the opportunity and efficiency models get wrong (S11, S12,
    S18, S19, S20) is still in these numbers.

The control runs FIRST. If the leak probe finds anything, or cannot
measure, the run prints that and stops without a table.
"""
from __future__ import annotations

import argparse
import sys
import warnings

warnings.filterwarnings("ignore")

import pandas as pd

import ff_sim as fs
from ff_sim_eff import COUNTS, EFF_STATS, YARDS, EfficiencyModel
from ff_sim_play import (STATUSES, ChanceOpportunity, PlayChance,
                         chance_vs_played, load_reports)
from sim_baseline import LABEL as BASE_LABEL, PLAIN, YEARS, hdr, newest_complete, show_cal

LABEL = dict(BASE_LABEL, efficiency="simulator, as it was",
             eff_missed="...with games missed", eff_report="...and the report")
NEW = (*COUNTS, *YARDS)
CHANCE_BANDS = (0.0, 0.05, 0.25, 0.5, 0.75, 0.9, 1.0001)
RUNGS = ("x0.6", "x0.8", fs.MAIN, "x1.25", "x1.6")


def gamelog():
    return [p for p in fs.yardsticks() if p.name == "gamelog_model"][0]


def show_chance(frame: pd.DataFrame, reports: pd.DataFrame, weeks) -> None:
    hdr("1. THE CHANCE OF PLAYING ITSELF — every player the list-not-known "
        "slate names, each week")
    cv = chance_vs_played(PlayChance(reports), frame, weeks)
    print(f"   {len(cv):,} listed player-games in {cv.game_id.nunique()} games; "
          f"{1 - cv.played.mean():.1%} of them did not play for that team.")

    def line(label, d):
        gap, se, n, _ = fs.cluster_mean(d.played.astype(float) - d.chance, d.game_id)
        print(f"   {label:<26}{n:>8,}{d.chance.mean():>10.1%}"
              f"{d.played.mean():>9.1%}{gap:>+8.1%}{se:>7.1%}")

    head = f"   {'':<26}{'listed':>8}{'it said':>10}{'played':>9}{'gap':>8}{'se':>7}"
    print("\n   by standing on that week's injury report\n" + head)
    for s in STATUSES:
        if (cv.status == s).any():
            line(s, cv[cv.status == s])
    print("\n   by how many of the team's last four games he had missed\n" + head)
    for m in sorted(cv.missed.dropna().unique()):
        line(f"missed {int(m)}", cv[cv.missed == m])
    print("\n   by the chance it gave\n" + head)
    for lo, hi in zip(CHANCE_BANDS, CHANCE_BANDS[1:]):
        d = cv[(cv.chance >= lo) & (cv.chance < hi)]
        if len(d):
            line(f"{lo:.0%} to {min(hi, 1.0):.0%}", d)
    line("everyone", cv)
    print("\n   by the week of the season (in Week 1 the 'last four games' are "
          "last season's)\n" + head)
    wk = cv.t % 100
    for label, d in (("Week 1", cv[wk == 1]), ("Weeks 2 to 4", cv[(wk >= 2) & (wk <= 4)]),
                     ("Week 5 on", cv[wk >= 5]), ("Week 2 on", cv[wk >= 2])):
        line(label, d)
    cv2 = chance_vs_played(PlayChance(), frame, weeks)
    b1 = ((cv.played.astype(float) - cv.chance) ** 2).mean()
    b2 = ((cv2.played.astype(float) - cv2.chance) ** 2).mean()
    b0 = ((cv.played.astype(float) - cv.played.mean()) ** 2).mean()
    print(f"\n   Brier score of the chance: {b1:.4f} with the report, {b2:.4f} "
          f"from games missed alone, {b0:.4f} saying the overall rate for "
          f"everyone.")


def show_scores(run: fs.Run) -> None:
    hdr("2. AGAINST KNOWING NOTHING ABOUT THE PLAYER — Brier score on the "
        "MAIN line, lower is better")
    print("   Gap to knowing nothing, in standard errors in brackets. The "
          "first column is the simulator with\n   the active list KNOWN; "
          "the other four are with it NOT known.")
    names = ("gamelog_model", "efficiency", "eff_missed", "eff_report")
    print(f"   {'':<17}{'list known':>18} |" + "".join(f"{LABEL[n]:>24}" for n in names))
    for rung, label in ((fs.MAIN, "main line"), (None, "every rung")):
        print(f"   — {label}")
        for stat in EFF_STATS:
            a = fs.compare_reference(run, "efficiency", version="A", stats=[stat],
                                     rung=rung)
            cells = f"{a['diff']:+.4f} ({abs(a['diff']) / a['se']:.1f})".rjust(18) + " |"
            for n in names:
                c = fs.compare_reference(run, n, version="B", stats=[stat], rung=rung)
                cells += f"{c['diff']:+.4f} ({abs(c['diff']) / c['se']:.1f})".rjust(24)
            print(f"   {PLAIN[stat]:<17}{cells}")
    print("\n   With the report, minus the simulator as it was; and minus the "
          "game-log model. List not known, main line, legs both priced:")
    for stat in EFF_STATS:
        c1 = fs.compare_brier(run, "eff_report", "efficiency", version="B",
                              stats=[stat], rung=fs.MAIN)
        c2 = fs.compare_brier(run, "eff_report", "gamelog_model", version="B",
                              stats=[stat], rung=fs.MAIN)
        c3 = fs.compare_brier(run, "eff_report", "eff_missed", version="B",
                              stats=[stat], rung=fs.MAIN)
        print(f"   {PLAIN[stat]:<17}{c1['n']:>6,} legs   vs as it was "
              f"{c1['diff']:+.4f} (se {c1['se']:.4f})   vs game-log "
              f"{c2['diff']:+.4f} (se {c2['se']:.4f})   vs games missed alone "
              f"{c3['diff']:+.4f} (se {c3['se']:.4f})")


def show_error(run: fs.Run) -> None:
    hdr("3. STAT-LINE MISS — players with a role who played; mean miss, and "
        "bias (projected minus actual)")
    ea = fs.stat_error(run, version="A")
    eb = fs.stat_error(run, version="B")
    names = ("gamelog_model", "efficiency", "eff_missed", "eff_report")
    print(f"   {'':<17}{'list known':>18} |" + "".join(f"{LABEL[n]:>24}" for n in names))
    for stat in EFF_STATS:
        a = ea[(ea.stat == stat)].set_index("projector").loc["efficiency"]
        b = eb[(eb.stat == stat)].set_index("projector")
        cells = f"{a.mean_miss:.2f} ({a.bias:+.2f})".rjust(18) + " |"
        for n in names:
            cells += f"{b.loc[n, 'mean_miss']:.2f} ({b.loc[n, 'bias']:+.2f})".rjust(24)
        print(f"   {PLAIN[stat]:<17}{cells}")


def show_calibration(run: fs.Run) -> None:
    hdr("4. CALIBRATION — receptions, completions and the three yardages, "
        "read on the side each favoured")
    print("   These are the stats props are written on. Two of the five "
          "(completions, passing yards) are not\n   moved by the chance of "
          "playing; targets and carries, which are, are not in these tables.")
    for name, version, what in (("eff_report", "B", "list NOT known"),
                                ("efficiency", "B", "list NOT known"),
                                ("efficiency", "A", "list known")):
        g = fs.graded_legs(run, name, version=version, stats=list(NEW))
        print(f"\n   {LABEL[name]}, {what}: every leg")
        show_cal(fs.calibration(g))
        if name == "eff_report":
            for side in ("OVER", "UNDER"):
                print(f"\n   {LABEL[name]}, {what}: legs it favoured the {side} on")
                show_cal(fs.calibration(g[g.side == side]))


def show_rungs(run: fs.Run) -> None:
    hdr("5. CALIBRATION RUNG BY RUNG — pooling the rungs hides opposite "
        "errors (engine thread, 2026-11-20)")
    print("   Receptions, completions and the three yardages, read on the side "
          "favoured. Each cell: happened (legs).\n   'x0.6' is the line at 0.6 "
          "of his median, and so on; 'main' is the half point above his median. "
          "Two\n   rungs that land on one line are one leg, kept under the rung "
          "nearer the main line, so the columns\n   are not all the same "
          "players.")
    for name, version, what in (("efficiency", "A", "list known"),
                                ("eff_report", "B", "list NOT known"),
                                ("gamelog_model", "A", "list known")):
        print(f"\n   {LABEL[name]}, {what}")
        tabs = {r: fs.calibration(fs.graded_legs(run, name, version=version,
                                                 stats=list(NEW), rung=r)
                                  ).set_index("band") for r in RUNGS}
        bands = list(tabs[fs.MAIN].index)
        print(f"   {'it said':<10}" + "".join(f"{r:>17}" for r in RUNGS))
        for b in bands:
            cells = "".join(
                (f"{tabs[r].happened[b]:.1%} ({int(tabs[r].n[b]):,})" if tabs[r].n[b]
                 else "-").rjust(17) for r in RUNGS)
            print(f"   {b:<10}{cells}")
        g = fs.graded_legs(run, name, version=version, stats=list(NEW), rung=fs.MAIN)
        for side in ("OVER", "UNDER"):
            d = g[(g.side == side) & (g.p_side >= 0.65)]
            gap, se, n, _ = fs.cluster_mean(d.hit.astype(float) - d.p_side, d.game_id)
            print(f"   main line, {side}S it put at 65% or better: {n:,} legs, "
                  f"stated {d.p_side.mean():.1%}, happened {d.hit.mean():.1%} "
                  f"({gap:+.1%}, se {se:.1%})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--current-week", type=int, default=None)
    args = ap.parse_args()
    pd.set_option("display.width", 200)

    through = newest_complete(args.current_week)
    frame = fs.load_frame(YEARS)
    reports = load_reports(YEARS)
    print("injury reports: " + str(reports.attrs["report"]))

    def projectors():
        return [gamelog(), EfficiencyModel("efficiency"),
                EfficiencyModel("eff_missed", opportunity=ChanceOpportunity(
                    "opp_missed", chance=PlayChance())),
                EfficiencyModel("eff_report", opportunity=ChanceOpportunity(
                    "opp_report", chance=PlayChance(reports)))]

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
    print(f"   control passed on all {len(run.weeks)} graded weeks. It does "
          f"not cover the injury reports, which reach the model outside the "
          f"harness.")

    show_chance(frame, reports, run.weeks)
    show_scores(run)
    show_error(run)
    show_calibration(run)
    show_rungs(run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
