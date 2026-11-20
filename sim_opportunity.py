#!/usr/bin/env python3
"""S4. The opportunity model, through the harness: with the active list
known and not known, and with and without the closing spread and total.

    python3 sim_opportunity.py --current-week 11

`--current-week` is the NFL week now in progress; every week before it is
graded. It takes about four minutes; the control runs first.

What it runs. `ff_sim.walk_forward` over every regular-season week from 2024
Week 1 with six projectors: the three yardsticks, `OpportunityModel()`,
`OpportunityModel(lines=closing_lines)`, and `OpportunityModel(single=
"median")`, which states the same chances as the first and reports the
count's median as its single number instead of the expected count. The
model projects targets, carries and pass attempts only, so only those three
are reported. Section 6 is not from the harness: it sets the model's
expected counts and spreads (`ff_sim_opp.expected_vs_actual`) beside what
happened.

RESULTS, run 2026-11-20. Sample: 46 weeks, 2024 Week 1 to 2026 Week 10,
694 games; players with a role who played; every error counts a game once.
"Know-nothing" says each stat and rung's own overall over-rate.

THE SHORT OF IT. With the active list known the model beats know-nothing
and all three yardsticks on targets, carries and pass attempts. With it NOT
known the model is WORSE than know-nothing on targets and carries, and
still better on pass attempts. "Not known" is the harness's slate B, which
lists players who will not play; the model shares a team's volume among
everyone listed and hands those players a fifth of it (20.1% of targets,
22.5% of carries), so the ones who do play are given too little. What it
would score if it weighed each man's chance of playing is not built (S13).

  Mean miss of the single number (typical miss in brackets), and its bias
  (projected minus actual), on the same player-games for all six:
  ACTIVES KNOWN     n      season avg   last four    game-log     opportunity  +spread,total  its median
    targets       5,272  2.30 (2.00)  2.32 (2.00)  2.30 (2.00)  2.17 (1.77)  2.16 (1.77)    2.16 (2.00)
      bias                 +0.03        +0.21        -0.12        -0.21        -0.18          -0.58
    carries       2,194  4.11 (3.33)  4.11 (3.25)  4.37 (3.50)  3.85 (3.17)  3.84 (3.16)    3.88 (3.00)
      bias                 +0.03        +0.34        -0.26        -0.42        -0.44          -1.13
    pass attempts 1,121  7.63 (6.33)  7.45 (6.25)  7.02 (5.50)  6.64 (5.18)  6.62 (5.21)    6.69 (5.00)
      bias                 -0.51        -0.16        -0.49        -0.15        +0.03          -0.76
  ACTIVES NOT KNOWN
    targets       5,223  2.30 (2.00)  2.32 (2.00)  2.30 (2.00)  2.27 (1.76)  2.26 (1.75)    2.34 (2.00)
      bias                 +0.02        +0.19        -0.14        -0.99        -0.96          -1.32
    carries       2,171  4.12 (3.36)  4.12 (3.25)  4.37 (3.50)  4.35 (3.43)  4.35 (3.47)    4.51 (3.00)
      bias                 +0.04        +0.35        -0.27        -2.00        -2.02          -2.63
    pass attempts 1,070  7.59 (6.32)  7.57 (6.25)  7.17 (5.50)  6.76 (5.10)  6.73 (5.15)    6.80 (5.00)
      bias                 +0.05        +0.25        -0.28        +0.01        +0.20          -0.60
  Opportunity minus game-log model, mean miss, on the player-games both
  projected (5,719 / 2,381 / 1,211 known; 5,538 / 2,287 / 1,117 not):
    known:     targets -0.135 (se 0.015), carries -0.481 (se 0.055),
               pass attempts -0.427 (se 0.096)
    not known: targets -0.036 (se 0.019) and carries -0.023 (se 0.061),
               neither distinguishable from none; pass attempts -0.422
               (se 0.097). Against the season average its carries are
               WORSE not known: +0.224 (se 0.061, on 2,171).
  Reporting the median instead of the expected count changes the mean miss
  by -0.009 (se 0.006), +0.036 (se 0.014) and +0.040 (se 0.019): nothing
  on targets, slightly worse on the other two. The median's bias is -0.58
  targets and -1.13 carries, against -0.21 and -0.42 for the expected
  count, which is what the next stage should multiply.

  Brier score on the MAIN line, lower is better (gap to know-nothing, se):
                       know-nothing  game-log  opportunity
  ACTIVES KNOWN
    targets       5,272   0.2414     0.2429    0.2271  (-0.0143, 0.0017)
    carries       2,194   0.2445     0.2476    0.2193  (-0.0252, 0.0031)
    pass attempts 1,121   0.2500     0.2440    0.2348  (-0.0151, 0.0044)
  ACTIVES NOT KNOWN
    targets       5,223   0.2417     0.2430    0.2498  (+0.0081, 0.0024)
    carries       2,171   0.2445     0.2473    0.2582  (+0.0137, 0.0041)
    pass attempts 1,070   0.2499     0.2428    0.2324  (-0.0175, 0.0044)
  Every rung tells the same story: known -0.0121, -0.0194, -0.0062; not
  known +0.0058, +0.0115, -0.0067. With actives known no yardstick is
  distinguishably better than know-nothing on any of the three, and the
  season average and last four are worse on targets and pass attempts.
  Not known, one is: the game-log model on main-line pass attempts
  (-0.0071, 2.2 errors).

  What the closing spread and total add (with, minus without), Brier, on
  the legs both priced:
                     ACTIVES KNOWN                      ACTIVES NOT KNOWN
    targets        main -0.00087 (se 0.00018)   main -0.00121 (se 0.00020)
                   all  -0.00067 (se 0.00012)   all  -0.00098 (se 0.00015)
    carries        main -0.00000 (se 0.00057)   main +0.00069 (se 0.00056)
                   all  -0.00016 (se 0.00035)   all  +0.00042 (se 0.00036)
    pass attempts  main -0.00163 (se 0.00067)   main -0.00154 (se 0.00070)
                   all  -0.00061 (se 0.00027)   all  -0.00066 (se 0.00028)
  Targets: a clear gain (4.8 to 6.7 errors) and a small one: with actives
  known, about a sixteenth of the model's own main-line gap to
  know-nothing (that gap is on a slightly smaller set of legs). Pass
  attempts: about a tenth of its gap, at 2.2 to 2.4 errors: probably real,
  not beyond doubt. Carries: nothing either way (not known they lean the
  wrong way, +0.00069, 1.2 errors: noise). On the mean miss only targets
  shows anything (-0.005, se 0.002 known; -0.009, se 0.001 not). With the
  lines the pass-attempt bias moves from -0.15 to +0.03 known and from
  +0.01 to +0.20 not known.

  Calibration with actives known, no market numbers, read on the side it
  favoured (3,164 to 5,010 legs a band; 95% ranges within a point and a
  half either way overall, up to two and a half points by side):
    it said    happened   favoured OVER   favoured UNDER   game-log model
    50-55%      53.6%        56.6%           50.6%            52.9%
    60-65%      61.3%        65.5%           57.6%            60.9%
    70-75%      71.5%        76.4%           67.7%            68.3%
    80-85%      82.0%        83.1%           81.5%            77.3%
    90-95%      91.5%        92.4%           91.3%            87.7%
    95-100%     96.6%        94.5%           97.0%            92.2%
  Overall it is within a point and a half of what it says in every band,
  and reads "as stated" up to 90%; above that it is half a point to a
  point too sure, and its 95 to 100% overs more than that (94.5% for a
  stated 96.7%). It LEANS: from 55% to 80% its overs come in 3 to 5.5
  points MORE often than it says and its unders 2.5 to 5 points LESS. The
  game-log model on the same legs is too sure on both sides from 75% up
  (4 to 6 points overall from 70% up), its overs worst: 3.6 to 8.6 points
  less often than stated at every level. With actives NOT known the
  opportunity model is badly overconfident, and worse than the game-log
  model on that slate: 72.5% stated came in at 65.8% (game-log 68.4%),
  82.5% at 72.4% (game-log 77.4%).

  Expected count and spread beside what happened (section 6), actives
  known, every slate player. "spread" is the root mean squared miss, and
  "stated" what the model's own counts imply:
    whole slate   targets 2.23 expected, 2.22 actual; carries 1.93, 1.93
    targets  1 to 3 expected: 1.74 actual vs 1.88 (-0.14, se 0.02)
             5 to 7 expected: 6.25 vs 5.87 (+0.38, se 0.08)
             7+ expected:     8.39 vs 8.16 (+0.23, se 0.12: no gap shown);
                              spread 3.44, stated 4.01
    carries  1 to 4 expected: 2.19 vs 2.33 (-0.15, se 0.05);
                              spread 2.48, stated 1.82
             4 to 8:          5.36 vs 5.67 (-0.32, se 0.09);
                              spread 4.07, stated 3.30
             8 to 13:         10.97 vs 10.40 (+0.58, se 0.17)
             13+:             16.22 vs 15.76 (+0.46, se 0.18);
                              spread 5.64, stated 7.41
    pass attempts, every named starter (1,388): 31.23 actual vs 31.26;
             spread 8.77, stated 8.49
    players with a stand-in line, and their main line:
             targets  5,719: 5.19 actual vs 4.98 expected (+0.21, se 0.04);
                      said over 36.8%, went over 40.0% (+3.2 points, se 0.7)
             carries  2,381: 10.93 vs 10.50 (+0.43, se 0.08);
                      said over 37.9%, went over 42.3% (+4.3 points, se 0.8)
             pass attempts 1,211: 31.45 vs 31.28 (+0.17, se 0.24);
                      said over 47.3%, went over 49.4% (+2.1 points, se 1.3)
  Read: team totals are the right size. Players with a line are given
  about 4% too little on targets and carries, small roles too much, and
  those players' main-line overs come in 3 to 4 points more often than it
  says. The lean in the calibration goes with that. That the one causes
  the other is the likely reading and has not been tested here; a
  reviewer's rough correction of the means removed part of the lean and
  not all of it. Nor is it settled WHY big roles get too little: the
  share fit pulling big and small together, or first-game and fringe
  players being handed a position's average share, are not separated. On
  pass attempts the gaps are +0.17 (se 0.24) and +2.1 points (se 1.3):
  not distinguishable from none, and not from the targets gap either. One
  spread per stat does not fit every size of role: too wide for the
  biggest roles, too narrow for small ones. NONE OF THIS IS FIXED HERE; it
  is shown first.

  Slate A against slate B, mean miss on the player-games both projected:
    targets       -0.098 (se 0.014);  Weeks 1-4 -0.187,  Week 5 on -0.067
    carries       -0.480 (se 0.043);  Weeks 1-4 -0.942,  Week 5 on -0.324
  No yardstick changes at all. This is the worth of the list AND the cost
  of sharing volume among players who will not play, together: of what
  the model handed out on slate B, 20.1% of targets and 22.5% of carries
  went to players who did not play. Early weeks are worse because slate B
  then reaches into last season's rosters (S5). For pass attempts the two
  slates differ only in who is named the starter; slate B's man did not
  play in 171 of 1,388 team-games (12.3%).

  Control: leak probe clean on all 46 weeks, 1,803,471 projector outputs
  (150,716 from each of the three opportunity models).

Limits, stated because the figures get quoted:
  - Lines are the harness's STAND-INS, not a book's. Nothing here is a
    price or an edge.
  - Targets, carries and pass attempts are not what most props are written
    on. They are the first half of receptions and yards; the second half
    (what he does with them) is not built.
  - "Actives known" is the harness's slate A: everyone who took a snap or
    recorded a stat, and who started at quarterback (SIM-BACKLOG S6). That
    is a little MORE than an inactive list tells you. "Not known" is slate
    B: everyone who played for a team in one of its last four games,
    under every team that is true of, and whoever started its last game
    (S5). That is a good deal LESS than anyone knows on a Sunday morning.
    A live run sits between the two.
  - The model reads the slate and the yardsticks do not. On slate A that is
    an advantage the comparison is meant to show, not a flaw in it; on
    slate B it is a handicap, because the model hands a share to players
    who will not play.
  - The model's hand-set numbers (three half-lives, the fewest rows a fit
    may have, the smallest expected count its spread is measured on, the
    two ends of the range the spread is held to, the floor under a team's
    volume: eight in all) were chosen before the first run and not tuned. `SIZE_BANDS` below is this
    script's own and only decides how section 6 is cut.
  - The closing spread and total reach the model outside the harness's
    slate. The leak probe cannot see that path. What stands there is that
    the model looks up a line only for games in its history or on its
    slate; `test_sim.py` checks that, and that a later game's line moves
    nothing.
  - "Closing" means the number at kickoff. A live run would have the line
    as it stood when the run was made.

The control runs FIRST. If the leak probe finds anything, or cannot
measure, the run prints that and stops without a table.
"""
from __future__ import annotations

import argparse
import math
import sys
import warnings

warnings.filterwarnings("ignore")

import pandas as pd

import ff_sim as fs
from ff_sim_opp import (OPP_STATS, OpportunityModel, closing_lines,
                        expected_vs_actual, with_main_line)
from sim_baseline import LABEL as BASE_LABEL, PLAIN, YEARS, hdr, newest_complete, show_cal

LABEL = dict(BASE_LABEL, opportunity="opportunity model",
             opp_market="...with spread & total",
             opp_median="...its median instead")
SLATE = {"A": "ACTIVES KNOWN (slate A)", "B": "ACTIVES NOT KNOWN (slate B)"}
#: The median variant states the same chances, so it is left out of the
#: tables that score chances.
PRICED = ("season_avg", "last4_avg", "gamelog_model", "opportunity", "opp_market")


def sub_run(run: fs.Run, stat: str, weeks=None) -> fs.Run:
    """The same run, one stat only, and optionally some weeks of the season."""
    pts = run.points[run.points.stat == stat]
    legs = run.legs[run.legs.stat == stat]
    if weeks is not None:
        pts, legs = pts[pts.week.isin(weeks)], legs[legs.week.isin(weeks)]
    return fs.Run(points=pts, legs=legs, names=run.names, weeks=run.weeks)


def show_error(run: fs.Run) -> None:
    hdr("1. STAT-LINE MISS — players with a role who played; the same "
        "player-games for all six in each block")
    print("   typical miss = half the time it misses by less than this. "
          "bias = projected minus actual.")
    for version in ("A", "B"):
        e = fs.stat_error(run, version=version)
        for stat in OPP_STATS:
            s = e[e.stat == stat].set_index("projector")
            print(f"\n   {SLATE[version]} — {PLAIN[stat]}, "
                  f"{int(s.n.iloc[0]):,} player-games")
            print(f"   {'':<26}{'typical miss':>13}{'mean miss':>11}{'se':>7}"
                  f"{'bias':>8}")
            for n in run.names:
                print(f"   {LABEL[n]:<26}{s.loc[n, 'typical_miss']:>13.2f}"
                      f"{s.loc[n, 'mean_miss']:>11.2f}"
                      f"{s.loc[n, 'mean_miss_se']:>7.2f}{s.loc[n, 'bias']:>+8.2f}")
    print("\n   Pair by pair, on the player-games BOTH projected (so the "
          "counts differ from the blocks above):")
    for version, pairs in (
            ("A", (("opportunity", "gamelog_model"), ("opportunity", "season_avg"),
                   ("opp_median", "opportunity"), ("opp_market", "opportunity"))),
            ("B", (("opportunity", "gamelog_model"), ("opportunity", "season_avg"),
                   ("opp_market", "opportunity")))):
        print(f"   {SLATE[version]}")
        for a, b in pairs:
            c = fs.compare_error(run, a, b, version=version)
            for stat in OPP_STATS:
                r = c[c.stat == stat].iloc[0]
                print(f"     {LABEL[a]} minus {LABEL[b]}, {PLAIN[stat]} "
                      f"({int(r['n']):,}): mean miss {r['diff']:+.3f} "
                      f"(se {r['se']:.3f}) — {r['read']}")


def show_scores(run: fs.Run) -> None:
    hdr("2. AGAINST KNOWING NOTHING ABOUT THE PLAYER — Brier score, lower is "
        "better")
    print("   'Knowing nothing' says each stat and rung's own overall rate, "
          "worked out on the legs it is scored on.")
    for version in ("A", "B"):
        for label, rung in (("the main line only", fs.MAIN),
                            ("every rung of the ladder", None)):
            for stat in OPP_STATS:
                ref = fs.reference_brier(run, version=version, stats=[stat],
                                         rung=rung)
                print(f"\n   {SLATE[version]} — {PLAIN[stat]}, {label}: "
                      f"{ref['n']:,} legs in {ref['games']} games; knowing "
                      f"nothing {ref['brier']:.4f}")
                for n in PRICED:
                    c = fs.compare_reference(run, n, version=version,
                                             stats=[stat], rung=rung)
                    print(f"   {LABEL[n]:<26} {ref['brier'] + c['diff']:.4f}   "
                          f"({c['diff']:+.4f}, se {c['se']:.4f}, "
                          f"{abs(c['diff']) / c['se']:.2f} errors — {c['read']})")


def show_market(run: fs.Run) -> None:
    hdr("3. WHAT THE CLOSING SPREAD AND TOTAL ADD — the same model with them, "
        "minus without, on the legs both priced")
    for version in ("A", "B"):
        print(f"   {SLATE[version]}")
        for stat in OPP_STATS:
            for label, rung in (("main line", fs.MAIN), ("every rung", None)):
                c = fs.compare_brier(run, "opp_market", "opportunity",
                                     version=version, stats=[stat], rung=rung)
                print(f"     {PLAIN[stat]:<14} {label:<10} {c['n']:>6,} legs  "
                      f"Brier {c['diff']:+.5f} (se {c['se']:.5f}, "
                      f"{abs(c['diff']) / c['se']:.1f} errors) — {c['read']}")


def show_calibration(run: fs.Run) -> None:
    hdr("4. CALIBRATION — targets, carries and pass attempts together, read on "
        "the side each favoured")
    for name in ("opportunity", "gamelog_model"):
        g = fs.graded_legs(run, name, stats=list(OPP_STATS))
        print(f"\n   {LABEL[name]}, actives known: every leg")
        show_cal(fs.calibration(g))
        for side in ("OVER", "UNDER"):
            print(f"\n   {LABEL[name]}, actives known: legs it favoured the "
                  f"{side} on")
            show_cal(fs.calibration(g[g.side == side]))
    for name in ("opportunity", "gamelog_model"):
        print(f"\n   {LABEL[name]}, actives NOT known: every leg")
        show_cal(fs.calibration(fs.graded_legs(run, name, version="B",
                                               stats=list(OPP_STATS))))


def show_availability(run: fs.Run) -> None:
    hdr("5. SLATE A AGAINST SLATE B — what the difference is, and what it "
        "costs")
    print("   Mean miss on slate A minus on slate B, on the player-games both "
          "projected and he played.\n   Slate B is not 'the model without "
          "the active list': it is the model handed a list that includes\n"
          "   players who will not play, and it shares the team's volume "
          "among all of them. So this difference\n   is the worth of the "
          "list AND the cost of that sharing, together. Weeks 1 to 4 are "
          "shown apart\n   because slate B then reaches into last season's "
          "rosters.")
    early = (1, 2, 3, 4)
    late = tuple(range(5, 30))
    for stat in ("targets", "carries"):
        for label, weeks in (("all weeks", None), ("Weeks 1-4", early),
                             ("Week 5 on", late)):
            av = fs.availability(sub_run(run, stat, weeks), "opportunity")
            print(f"   {PLAIN[stat]:<14} {label:<10} {av['miss_diff']:+.3f} "
                  f"(se {av['se']:.3f}, {av['n']:,} player-games)")
        av = fs.availability(sub_run(run, stat), "last4_avg")
        print(f"   {PLAIN[stat]:<14} last four, all weeks: {av['miss_diff']:+.3f} "
              f"(it does not read the slate)")
    print("\n   Of everything the model handed out on slate B, the share it "
          "gave to players who then did not play\n   (over the player-games "
          "the harness records a number for):")
    b = run.points[run.points.version == "B"]
    for stat in OPP_STATS:
        d = b[(b.stat == stat) & b["pt_opportunity"].notna()]
        gone = d[~d.played.astype(bool)]
        print(f"   {PLAIN[stat]:<14} {gone['pt_opportunity'].sum() / d['pt_opportunity'].sum():.1%} "
              f"of the expected {PLAIN[stat]}, to {len(gone):,} of {len(d):,} "
              f"player-games")
    print("   For pass attempts the two slates differ only in WHO is named the "
          "starter: the model gives the\n   team's attempts to that man and "
          "says nothing of anyone else. Where both name the same man its\n"
          "   number is the same; the line above is how often slate B's man "
          "did not play.")


#: Bands of the model's expected count, per stat, for section 6. This
#: script's own; they only decide how the table is cut.
SIZE_BANDS = {"targets": (0, 1, 3, 5, 7, 99), "carries": (0, 1, 4, 8, 13, 99),
              "attempts": (0, 10, 30, 34, 99)}


def show_sizes(run: fs.Run, frame: pd.DataFrame) -> None:
    hdr("6. IS THE EXPECTED COUNT THE RIGHT SIZE, AND ITS SPREAD THE RIGHT "
        "WIDTH — actives known")
    print("   Every player on the slate, not only those with a role. 'gap' is "
          "actual minus expected; its error\n   counts a game once. 'spread' "
          "is the root of the mean squared miss; 'stated' is the same thing "
          "as\n   the model's own counts would have it.")
    rows = expected_vs_actual(OpportunityModel(), frame, run.weeks)
    for stat in OPP_STATS:
        r = rows[rows.stat == stat]
        print(f"\n   {PLAIN[stat]}")
        print(f"   {'expected':<12}{'player-games':>13}{'expected':>10}"
              f"{'actual':>9}{'gap':>9}{'se':>7}{'spread':>9}{'stated':>9}   read")
        edges = SIZE_BANDS[stat]
        bands = [(lo, hi, r[(r.expected >= lo) & (r.expected < hi)])
                 for lo, hi in zip(edges, edges[1:])] + [(None, None, r)]
        for lo, hi, b in bands:
            if not len(b):
                continue
            gap, se, n, games = fs.cluster_mean(b.actual - b.expected, b.game_id)
            label = ("everyone" if lo is None else
                     f"{lo}+" if hi == 99 else f"{lo} to {hi}")
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

    j = with_main_line(run, rows, "opportunity")
    print("\n   Players with a stand-in line only, and their MAIN line (the "
          "players sections 2 to 4 are about)")
    print(f"   {'stat':<15}{'player-games':>13}{'expected':>10}{'actual':>9}"
          f"{'gap':>9}{'se':>7}{'said over':>12}{'went over':>11}{'gap':>8}"
          f"{'se':>7}")
    for stat in OPP_STATS:
        b = j[j.stat == stat]
        gap, se, n, _ = fs.cluster_mean(b.actual - b.expected, b.game_id)
        og, ose, _, _ = fs.cluster_mean(b.over.astype(float) - b.said, b.game_id)
        print(f"   {PLAIN[stat]:<15}{n:>13,}{b.expected.mean():>10.2f}"
              f"{b.actual.mean():>9.2f}{gap:>+9.2f}{se:>7.2f}"
              f"{b.said.mean():>12.1%}{b.over.mean():>11.1%}{og:>+8.1%}{ose:>7.1%}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--current-week", type=int, default=None)
    args = ap.parse_args()
    pd.set_option("display.width", 200)

    through = newest_complete(args.current_week)
    frame = fs.load_frame(YEARS)
    lines = closing_lines(YEARS)

    def projectors():
        return [*fs.yardsticks(), OpportunityModel("opportunity"),
                OpportunityModel("opp_market", lines=lines),
                OpportunityModel("opp_median", single="median")]

    if args.current_week is None:
        print(f"NOTE: no --current-week given, so the newest week on file is "
              f"treated as unfinished. Grading through {through}.")
    run = fs.walk_forward(frame, projectors(), through=through)
    print(run.describe())

    hdr("CONTROL — run before any table")
    probe = fs.leak_probe(frame, projectors(), run.weeks)
    print("   " + probe.describe())
    print("   outputs compared, by projector: " + str(probe.outputs))
    ok = probe.clean and not run.unverified
    if not ok:
        print("   THIS RUN IS VOID — no table is printed")
        return 1
    print(f"   control passed on all {len(run.weeks)} graded weeks. It does "
          f"not cover the closing lines, which reach the model outside the "
          f"harness.")

    show_error(run)
    show_scores(run)
    show_market(run)
    show_calibration(run)
    show_availability(run)
    show_sizes(run, frame)
    return 0


if __name__ == "__main__":
    sys.exit(main())
