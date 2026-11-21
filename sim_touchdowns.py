#!/usr/bin/env python3
"""S24. Touchdowns: what the simulator scores on anytime touchdowns (rushing
or receiving) and on passing touchdowns.

    python3 sim_touchdowns.py --current-week 11

`--current-week` is the NFL week now in progress; every week before it is
graded. It takes about seven minutes; the control runs first.

What it runs. `ff_sim.walk_forward` over every regular-season week from 2024
Week 1 with three projectors: the engine's game-log model; the touchdown
model on the simulator as it was (`TouchdownModel()`); and the touchdown
model on the simulator with a chance of playing from the injury report.
The first two are scored on both of the harness's slates, the third on the
list-not-known slate, where it belongs. Sections 5 and 6 are not from the
harness: they set the model's expected counts beside what happened
(`ff_sim_td.parts_vs_actual`), with the active list known, for every
active quarterback, back, receiver and tight end.

RESULTS: see SIM-BACKLOG.md, S24, for the run of record. They are kept
there and not here so that this file and the backlog cannot disagree.

Limits, stated because the figures get quoted:
  - The anytime line is always a half (did he score), so there is one leg
    a player-game and no ladder. Passing touchdowns have a short ladder of
    stand-in lines round each quarterback's median, mostly 0.5, 1.5 and
    2.5; a book's line and price would differ.
  - "List not known" is the harness's slate B: everyone active for a team
    in one of its last four games, and whoever started its last game at
    quarterback. A real run names its own starter.
  - Sections 1 to 4 score only players the harness gives a line to: those
    with a role (four recent games and a median of 3 targets or 5 carries
    in them; 20 pass attempts for a passing line). Sections 5 and 6 count
    every active quarterback, back, receiver and tight end, and say which
    had a line. Most of those without one have the games and not the role.
  - The splits in sections 5 and 6 (who had a line; chances against rate)
    are worked out in this script, which the suite does not import. The
    table they are made from, `ff_sim_td.parts_vs_actual`, is in the suite.
  - FIRST TOUCHDOWN is not built and not measured here.
  - Everything the opportunity model gets wrong is still in these numbers.

The control runs FIRST. If the leak probe finds anything, or cannot
measure, the run prints that and stops without a table.
"""
from __future__ import annotations

import argparse
import sys
import warnings

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

import ff_sim as fs
from ff_sim_eff import EfficiencyModel
from ff_sim_play import ChanceOpportunity, PlayChance, load_reports
from ff_sim_td import (TD_RATES, TD_SHRINK_GRID, TouchdownModel,
                       parts_vs_actual, pulls_picked)
from sim_baseline import LABEL as BASE_LABEL, PLAIN, YEARS, hdr, newest_complete, show_cal

LABEL = dict(BASE_LABEL, td="simulator, as it was", td_report="...with the report")
TD = fs.TD_STAT
RUNGS = ("x0.6", "x0.8", fs.MAIN, "x1.25", "x1.6")
POSITIONS = ("QB", "RB", "WR", "TE")
ALL_B = ("gamelog_model", "td", "td_report")


def gamelog():
    return [p for p in fs.yardsticks() if p.name == "gamelog_model"][0]


def cell(c: dict, width: int = 22) -> str:
    return f"{c['diff']:+.4f} ({abs(c['diff']) / c['se']:.1f})".rjust(width)


def show_scores(run: fs.Run) -> None:
    hdr("1. AGAINST KNOWING NOTHING ABOUT THE PLAYER — Brier score, lower is "
        "better")
    print("   Gap to knowing nothing, with its size in standard errors in "
          "brackets. Knowing nothing is saying,\n   for every player, the "
          "share of such legs that went over. An anytime line is always a "
          "half.")
    print(f"   {'':<28}{'legs':>7}{'know-nothing':>14} |" + "".join(
        f"{LABEL[n]:>22}" for n in ALL_B))
    for version, what in (("A", "list known"), ("B", "list NOT known")):
        print(f"   — {what}")
        for stat, rung, label in ((TD, None, "anytime touchdown"),
                                  ("passing_tds", fs.MAIN, "passing TDs, main line"),
                                  ("passing_tds", None, "passing TDs, every rung")):
            ref = fs.reference_brier(run, version=version, stats=[stat], rung=rung)
            cells = "".join(
                cell(fs.compare_reference(run, n, version=version, stats=[stat],
                                          rung=rung))
                if not (version == "A" and n == "td_report") else "-".rjust(22)
                for n in ALL_B)
            print(f"   {label:<28}{ref['n']:>7,}{ref['brier']:>14.4f} |{cells}")
    print("\n   Head to head on the legs both priced (minus is better for the "
          "first named):")
    for a, b, version, what in (("td", "gamelog_model", "A", "list known"),
                                ("td", "gamelog_model", "B", "list NOT known"),
                                ("td_report", "gamelog_model", "B", "list NOT known"),
                                ("td_report", "td", "B", "list NOT known")):
        for stat, rung, label in ((TD, None, "anytime"),
                                  ("passing_tds", fs.MAIN, "passing TDs, main"),
                                  ("passing_tds", None, "passing TDs, every rung")):
            c = fs.compare_brier(run, a, b, version=version, stats=[stat], rung=rung)
            print(f"   {LABEL[a]} vs {LABEL[b]}, {what}, {label}: {c['n']:,} "
                  f"legs, {c['diff']:+.4f} (se {c['se']:.4f})")


def show_error(run: fs.Run) -> None:
    hdr("2. STAT-LINE MISS — players with a role who played; mean miss, and "
        "bias (projected minus actual)")
    for version, what in (("A", "list known"), ("B", "list NOT known")):
        e = fs.stat_error(run, version=version)
        print(f"   — {what}")
        for stat in (TD, "passing_tds"):
            s = e[e.stat == stat].set_index("projector")
            print(f"   {PLAIN[stat]:<26}" + "".join(
                f"{LABEL[n]}: {s.loc[n, 'mean_miss']:.3f} ({s.loc[n, 'bias']:+.3f})   "
                for n in ALL_B if not (version == "A" and n == "td_report")))
    print("   The game-log model's single number is a median, which for "
          "touchdowns is mostly 0: its mean miss\n   is flattered and its "
          "bias is not a fault. The simulator's is the expected count.")


def show_anytime(run: fs.Run) -> None:
    hdr("3. ANYTIME TOUCHDOWN — the chance it gave of scoring, beside how "
        "often he scored")
    for name, version, what in (("td", "A", "list known"),
                                ("td_report", "B", "list NOT known"),
                                ("td", "B", "list NOT known"),
                                ("gamelog_model", "A", "list known")):
        g = fs.graded_legs(run, name, version=version, stats=[TD])
        print(f"\n   {LABEL[name]}, {what}")
        show_cal(fs.calibration(g, folded=False), unit="p-games")
        gap, se, n, _ = fs.cluster_mean(g.over.astype(float) - g.p, g.game_id)
        print(f"   everyone with a line: {n:,} player-games, it said {g.p.mean():.1%}, "
              f"scored {g.over.mean():.1%} ({gap:+.1%}, se {se:.1%})")
    for name, version, what in (("td", "A", "list known"),
                                ("td_report", "B", "list NOT known")):
        g = fs.graded_legs(run, name, version=version, stats=[TD])
        print(f"\n   {LABEL[name]}, {what}, by position and by how likely it "
              f"made him")
        print(f"   {'':<22}{'p-games':>9}{'it said':>9}{'scored':>9}{'gap':>8}{'se':>7}")

        def line(label, d):
            if not len(d):
                return
            gap, se, n, _ = fs.cluster_mean(d.over.astype(float) - d.p, d.game_id)
            print(f"   {label:<22}{n:>9,}{d.p.mean():>9.1%}{d.over.mean():>9.1%}"
                  f"{gap:>+8.1%}{se:>7.1%}")

        for pos in POSITIONS:
            line(pos, g[g.position == pos])
        for lo, hi in ((0.30, 1.01), (0.40, 1.01), (0.50, 1.01)):
            line(f"{lo:.0%} or better", g[(g.p >= lo) & (g.p < hi)])
        for season in sorted(g.season.unique()):
            line(str(season), g[g.season == season])


def show_passing(run: fs.Run) -> None:
    hdr("4. PASSING TOUCHDOWNS — by line, and rung by rung")
    for name, version, what in (("td", "A", "list known"),
                                ("td", "B", "list NOT known"),
                                ("gamelog_model", "A", "list known")):
        g = fs.graded_legs(run, name, version=version, stats=["passing_tds"])
        print(f"\n   {LABEL[name]}, {what}: the chance it gave of MORE than "
              f"the line, beside how often")
        print(f"   {'line':<8}{'legs':>7}{'it said':>9}{'went over':>11}{'gap':>8}{'se':>7}")
        for ln in sorted(g.line.unique()):
            d = g[g.line == ln]
            gap, se, n, _ = fs.cluster_mean(d.over.astype(float) - d.p, d.game_id)
            print(f"   {ln:<8}{n:>7,}{d.p.mean():>9.1%}{d.over.mean():>11.1%}"
                  f"{gap:>+8.1%}{se:>7.1%}")
        print(f"   read on the side it favoured, every rung pooled")
        show_cal(fs.calibration(g))
        tabs = {r: fs.calibration(fs.graded_legs(
            run, name, version=version, stats=["passing_tds"], rung=r)
        ).set_index("band") for r in RUNGS}
        print(f"   rung by rung, side favoured; each cell: happened (legs). "
              f"Two rungs on one line are one leg,\n   under the rung nearer "
              f"the main line.")
        print(f"   {'it said':<10}" + "".join(f"{r:>17}" for r in RUNGS))
        for b in tabs[fs.MAIN].index:
            if not any(tabs[r].n[b] for r in RUNGS):
                continue
            print(f"   {b:<10}" + "".join(
                (f"{tabs[r].happened[b]:.1%} ({int(tabs[r].n[b]):,})"
                 if tabs[r].n[b] else "-").rjust(17) for r in RUNGS))
        m = fs.graded_legs(run, name, version=version, stats=["passing_tds"],
                           rung=fs.MAIN)
        for side in ("OVER", "UNDER"):
            d = m[(m.side == side) & (m.p_side >= 0.60)]
            if len(d):
                gap, se, n, _ = fs.cluster_mean(d.hit.astype(float) - d.p_side,
                                                d.game_id)
                print(f"   main line, {side}S it put at 60% or better: {n:,} "
                      f"legs, stated {d.p_side.mean():.1%}, happened "
                      f"{d.hit.mean():.1%} ({gap:+.1%}, se {se:.1%})")


def with_lines(run: fs.Run, frame: pd.DataFrame) -> pd.DataFrame:
    """`ff_sim_td.parts_vs_actual` for the plain model on the four skill
    positions, with `lined`: whether the harness gave him an anytime line
    that week (list known), and `lined_pass`: a passing-touchdown line."""
    d = parts_vs_actual(TouchdownModel(), frame, run.weeks)
    other = int((~d.position.isin(POSITIONS)).sum())
    d = d[d.position.isin(POSITIONS)].reset_index(drop=True)
    g = fs.graded_legs(run, "td", version="A", stats=[TD])
    at = pd.MultiIndex.from_frame(d[["game_id", "player_id"]])
    d["lined"] = at.isin(pd.MultiIndex.from_frame(g[["game_id", "player_id"]]))
    q = fs.graded_legs(run, "td", version="A", stats=["passing_tds"], rung=fs.MAIN)
    d["lined_pass"] = at.isin(pd.MultiIndex.from_frame(q[["game_id", "player_id"]]))
    d.attrs["other"] = other
    return d


def pairs(g: pd.DataFrame, cols) -> str:
    return "".join(f"{g[e].sum():>9,.0f} / {g[a].sum():<7,.0f}" for e, a, _ in cols)


def show_totals(d: pd.DataFrame, picks: pd.DataFrame, own: dict, other: int) -> None:
    hdr("5. WHERE THE EXPECTED COUNT IS OFF — every active QB, RB, WR and TE, "
        "list known; totals over the whole run")
    rec = (("e_targets", "targets", "targets"), ("e_rec_td", "receiving_tds", "receiving TDs"))
    rush = (("e_carries", "carries", "carries"), ("e_rush_td", "rushing_tds", "rushing TDs"))
    print(f"   Each pair is expected / happened. {len(d):,} player-games; "
          f"{other:,} more at other positions are left out.")

    def table(by, cols, title):
        print(f"\n   {title}")
        print(f"   {'':<22}{'p-games':>8}" + "".join(f"{b:>19}" for _, _, b in cols))
        for key, g in by:
            print(f"   {str(key):<22}{len(g):>8,}{pairs(g, cols)}")

    table(d.groupby("position"), (*rec, *rush), "by position")
    table(d.groupby(d.t // 100), (*rec, *rush), "by season")
    table([("everyone", d)], (*rec, *rush), "all four positions")
    table(d.groupby(pd.cut(d.e_targets, [-1, 1, 3, 5, 7, 99])), rec,
          "by the targets it expected")
    table(d.groupby(pd.cut(d.e_carries, [-1, 1, 5, 10, 15, 99])), rush,
          "by the carries it expected")
    lab = d.lined.map({True: "with a line", False: "no line"})
    table(d.groupby(lab), (*rec, *rush), "by whether the harness gave him an "
          "anytime line (a role: four recent games and a median of 3 targets "
          "or 5 carries in them)")
    table(d.groupby([lab, d.position]), (*rec, *rush), "...and by position")

    print("\n   The same split, as the chance of scoring it gave beside how "
          "often he scored")
    print(f"   {'':<22}{'p-games':>8}{'it said':>9}{'scored':>9}{'gap':>8}{'se':>7}")
    one = (d[TD] >= 1).astype(float)
    for label, m in (("with a line", d.lined), ("no line", ~d.lined),
                     *((f"no line, {q}", ~d.lined & (d.position == q)) for q in POSITIONS),
                     ("everyone", d.lined | ~d.lined)):
        gap, se, n, _ = fs.cluster_mean((one - d.p1)[m], d.game_id[m])
        print(f"   {label:<22}{n:>8,}{d.p1[m].mean():>9.2%}{one[m].mean():>9.2%}"
              f"{gap:>+8.2%}{se:>7.2%}")

    print("\n   How much of each gap is the number of chances and how much "
          "the rate. 'chances' is (seen - expected)\n   x the expected rate; "
          "'rate' is the rest. '+/-' is the spread over 500 redraws of the "
          "games. A minus\n   is more expected than scored.")
    print(f"   {'':<26}{'TDs exp / scored':>20}{'gap':>7}{'chances':>9}{'+/-':>5}"
          f"{'rate':>7}{'+/-':>5}{'per 100, exp / seen':>24}")

    def split(g, eo, ao, et, at_):
        E, A, Oe, Oa = g[et].sum(), g[at_].sum(), g[eo].sum(), g[ao].sum()
        vol = (Oa - Oe) * E / Oe
        return E, A, vol, A - E - vol, 100 * E / Oe, 100 * A / Oa

    def spread(g, kinds):
        """sd of the chances and rate parts over redraws of the games."""
        by = g.groupby("game_id")[[c for k in kinds for c in k]].sum()
        rng, out = np.random.default_rng(0), []
        for _ in range(500):
            b = by.iloc[rng.integers(0, len(by), len(by))]
            parts = [split(b, *k) for k in kinds]
            out.append((sum(x[2] for x in parts), sum(x[3] for x in parts)))
        return np.std(out, axis=0)

    R = ("e_targets", "targets", "e_rec_td", "receiving_tds")
    U = ("e_carries", "carries", "e_rush_td", "rushing_tds")
    groups = [("with a line", d[d.lined]),
              *((f"with a line, {q}", d[d.lined & (d.position == q)]) for q in POSITIONS),
              ("no line", d[~d.lined])]
    for label, g in groups:
        for kind, cols in (("receiving", (R,)), ("rushing", (U,)), ("both", (R, U))):
            if kind != "both" and label not in ("with a line", "no line"):
                continue
            parts = [split(g, *k) for k in cols]
            E, A = sum(x[0] for x in parts), sum(x[1] for x in parts)
            vol, rate = sum(x[2] for x in parts), sum(x[3] for x in parts)
            sv, sr = spread(g, cols)
            per = (f"{parts[0][4]:>14.2f} / {parts[0][5]:<.2f}" if kind != "both" else "")
            print(f"   {label + ', ' + kind:<26}{E:>10,.0f} / {A:<7,.0f}{A - E:>7,.0f}"
                  f"{vol:>9,.0f}{sv:>5,.0f}{rate:>7,.0f}{sr:>5,.0f}{per}")

    q = d[d.starter & d.e_pass_td.notna()]
    qb = (("e_attempts", "attempts", "pass attempts"),
          ("e_pass_td", "passing_tds", "passing TDs"))
    table([*q.groupby(q.t // 100), ("all", q)], qb,
          "named starting quarterbacks, by season")
    table(q.groupby(q.lined_pass.map({True: "with a passing line",
                                      False: "no passing line"})), qb,
          "...and by whether the harness gave him a passing line (a role: a "
          "median of 20 attempts)")
    for label, g in q.groupby(q.lined_pass.map({True: "with a passing line",
                                                False: "no passing line"})):
        E, A, vol, rate, pe, pa = split(g, "e_attempts", "attempts", "e_pass_td",
                                        "passing_tds")
        print(f"   {label}: gap {A - E:+,.0f}, of it chances {vol:+,.0f} and rate "
              f"{rate:+,.0f}; per 100 attempts {pe:.2f} expected, {pa:.2f} seen")

    print("\n   The pull picked each week (how many targets, carries or "
          "attempts of the position's rate are\n   mixed into a player's "
          "own), and in how many of the weeks; the list runs "
          f"{TD_SHRINK_GRID[0]:g} to {TD_SHRINK_GRID[-1]:g}:")
    for r in TD_RATES:
        counts = picks[r].value_counts().sort_index()
        print(f"   {r:<16}" + ", ".join(f"{k:g} in {n} weeks" for k, n in counts.items()))
    print("   Positions with a rate of their own on the newest history "
          "(200 or more of the thing; the rest take the all-player rate):")
    for r in TD_RATES:
        print(f"   {r:<16}" + ", ".join(
            f"{q} {100 * v:.2f}" for q, v in sorted(own[r]["by_pos"].items()))
            + f"; all players {100 * own[r]['overall']:.2f} (per 100)")


def show_two(d: pd.DataFrame) -> None:
    hdr("6. TWO OR MORE — a check on the spread, which no line here grades")
    print("   The chance it gave of two or more touchdowns, beside how often; "
          "every active QB, RB, WR and TE,\n   list known.")
    print(f"   {'it said':<14}{'p-games':>9}{'it said':>9}{'happened':>10}{'gap':>8}{'se':>7}")
    two = (d[TD] >= 2).astype(float)
    for lo, hi in ((0.0, 0.01), (0.01, 0.03), (0.03, 0.06), (0.06, 0.10),
                   (0.10, 1.01), (0.0, 1.01)):
        m = (d.p2 >= lo) & (d.p2 < hi)
        if m.any():
            gap, se, n, _ = fs.cluster_mean((two - d.p2)[m], d.game_id[m])
            label = "everyone" if hi - lo > 1 else f"{lo:.0%} to {min(hi, 1):.0%}"
            print(f"   {label:<14}{n:>9,}{d.p2[m].mean():>9.2%}{two[m].mean():>10.2%}"
                  f"{gap:>+8.2%}{se:>7.2%}")
    for label, m in (("with a line", d.lined), ("no line", ~d.lined)):
        gap, se, n, _ = fs.cluster_mean((two - d.p2)[m], d.game_id[m])
        print(f"   {label:<14}{n:>9,}{d.p2[m].mean():>9.2%}{two[m].mean():>10.2%}"
              f"{gap:>+8.2%}{se:>7.2%}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--current-week", type=int, default=None)
    args = ap.parse_args()
    pd.set_option("display.width", 200)

    through = newest_complete(args.current_week)
    frame = fs.load_frame(YEARS)
    reports = load_reports(YEARS)

    def projectors():
        return [gamelog(), TouchdownModel("td"),
                TouchdownModel("td_report", efficiency=EfficiencyModel(
                    "eff_report", opportunity=ChanceOpportunity(
                        "opp_report", chance=PlayChance(reports))))]

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

    show_scores(run)
    show_error(run)
    show_anytime(run)
    show_passing(run)
    d = with_lines(run, frame)
    newest = TouchdownModel().fit(fs.History(frame[frame.t < run.weeks[-1]],
                                             run.weeks[-1]))
    show_totals(d, pulls_picked(TouchdownModel(), frame, run.weeks), newest.rate,
                d.attrs["other"])
    show_two(d)
    return 0


if __name__ == "__main__":
    sys.exit(main())
