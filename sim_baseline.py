#!/usr/bin/env python3
"""S1. The yardsticks, through the harness: what any simulator has to beat.

    python3 sim_baseline.py --current-week 11

`--current-week` is the NFL week now in progress, the same number the
engine's `data_status(current_week=)` takes. Every week before it is graded.
Without it the newest week on file is treated as half-played and left out.
It takes about two minutes; most of that is the control, which runs first.

What it runs. `ff_sim.walk_forward` over every regular-season week from 2024
Week 1, with three yardsticks: the player's season-to-date average, his
last-four average, and the game-log model the engine uses today
(`ff_props.threshold_prob`). No simulator is in this file. These are the
numbers the simulator will be put beside.

RESULTS — run 2026-11-19 on nflverse data pulled that day. 46 weeks, 2024
Week 1 to 2026 Week 10, 694 games. Players with a role, active list known.

  Typical miss (mean miss), on the same player-games for all three:
                         n    season avg      last four       game-log
    receptions       5,272   1.50  (1.79)   1.50  (1.80)   1.50  (1.75)
    receiving yards  5,272  19.25 (24.60)  19.50 (25.01)  18.50 (23.57)
    rushing yards    2,194  20.00 (25.29)  20.75 (25.69)  20.50 (25.77)
    passing yards    1,121  55.86 (65.94)  57.25 (65.72)  51.00 (61.09)

  Game-log model, what it said against what happened:
    60-65%  ->  60.3% overall;  56.5% where it favoured the OVER,
                                64.3% where it favoured the UNDER
    70-75%  ->  68.4% overall;  64.7% OVER, 72.5% UNDER
  The main stand-in line went over 43.1% of the time (26,763 legs).

  Brier on the main line, 24,688 legs: knowing nothing about the player
  0.2449; game-log model 0.2427 (-0.0022, se 0.0011: 1.96 errors, right on
  the edge of noise); season average 0.2553 and last four 0.2621, both
  WORSE than nothing.

  Touchdowns, the game-log blend: said 0-10%, happened 16.7%; said 50-60%,
  happened 42.3%.

  Pairs, 331,089: same-team passing yards with a receiver's yards went over
  together 29.1% of the time; multiplying says 24.9%, the correlation table
  28.4%; real lift 1.25 +/- 0.03.

  Active list unknown: 17.3% of role players projected did not play for
  the team; 3.2% of those who did play were not on the list.

  Control: leak probe on all 46 weeks, 1,351,323 yardstick outputs, no
  leak through the harness.

Limits, stated because the figures get quoted:
  - The lines are STAND-INS, a ladder around each player's median over his
    last eight games. They are not a book's lines. Book lines on file start
    about 2026-11-06.
  - "A role" is a stand-in too: a median of 3 targets, 5 carries or 20 pass
    attempts over that window, and for a quarterback only if he is the one
    starting. Those are judgement, like every other setting of the test (S2).
  - Nothing here says anything about price, and nothing here is an edge.
    A model can be perfectly calibrated and still lose to the market's line.
  - A Brier score is only read beside the know-nothing reference printed
    with it. On a ladder most rungs are easy, so every yardstick scores
    well under a coin flip's 0.250 without knowing anything.
  - For touchdowns the third yardstick is NOT an engine model. The engine
    builds no touchdown log; this is its blend on a log the harness built.
  - The pair table uses the game-log model's single-leg probabilities, which
    this run shows are too high on overs. A pair's "both" rate is therefore
    below the product in most cells before any correlation is considered;
    `real lift` is the column that takes that out. Its +/- is the lift's own
    95% range, clustered by game.
  - "Table" means `ff_correlation`'s r applied as a plain point estimate
    (`ff_sim.corr_joint`). It is not what `ff_boost.joint_error` does,
    which scores a pair pessimistically and reports a bound, not a price.
    "Recorded" r's were measured on 2023-2026, the same games they are
    graded on here. "Earlier seasons only" is the fair version.

The control runs FIRST. If the leak probe finds anything, or cannot
measure, the run prints that and stops without a table.
"""
from __future__ import annotations

import argparse
import sys
import warnings

warnings.filterwarnings("ignore")

import pandas as pd

import ff_correlation
import ff_data
import ff_sim as fs

YEARS = (2023, 2024, 2025, 2026)
COUNT_STATS = [s for s in fs.STATS if s != fs.TD_STAT]
LABEL = {"season_avg": "season average", "last4_avg": "last four",
         "gamelog_model": "game-log model"}
PLAIN = {"targets": "targets", "receptions": "receptions",
         "receiving_yards": "receiving yards", "carries": "carries",
         "rushing_yards": "rushing yards", "attempts": "pass attempts",
         "completions": "completions", "passing_yards": "passing yards",
         "passing_tds": "passing TDs", fs.TD_STAT: "touchdowns (rush + rec)"}


def newest_complete(current_week: int | None) -> int:
    """The newest gradeable week, as a key like 202610."""
    season = max(YEARS)
    wk = ff_data.load_weekly(season)
    reg = wk[wk.season_type == "REG"]
    done = ff_data.complete_weeks(reg, current_week)
    if not done:
        raise SystemExit(f"no complete week in {season} yet")
    return fs.tkey(season, max(done))


def hdr(title: str) -> None:
    print("\n" + title)
    print("-" * len(title))


def show_error(run: fs.Run) -> None:
    e = fs.stat_error(run)
    hdr("1. STAT-LINE MISS — players with a role, actives known, the same "
        "player-games for all three")
    print("   typical miss = half the time it misses by less than this; "
          "mean miss in brackets")
    print(f"   {'stat':<24}{'player-games':>13}"
          + "".join(f"{LABEL[n]:>22}" for n in run.names))
    for stat in fs.STATS:
        s = e[e.stat == stat].set_index("projector")
        if s.empty:
            continue
        cells = "".join(
            f"{s.loc[n, 'typical_miss']:>12.2f} ({s.loc[n, 'mean_miss']:.2f})".rjust(22)
            for n in run.names)
        print(f"   {PLAIN[stat]:<24}{int(s.n.iloc[0]):>13,}{cells}")
    print("   Bias (projected minus actual, + is too high), "
          + "/".join(LABEL[n] for n in run.names) + ": "
          + "; ".join(f"{PLAIN[st]} "
                      + "/".join(f"{e[(e.stat == st) & (e.projector == n)].bias.iloc[0]:+.2f}"
                                 for n in run.names)
                      for st in ("receptions", "receiving_yards", "rushing_yards",
                                 "passing_yards")))
    print("   A projected median TD count is 0 for most players, so read "
          "touchdowns in section 3, as a probability.")
    cov = e.groupby("projector").coverage.agg(["min", "max"])
    print("   Share of role player-games each could project at all, lowest "
          "to highest stat: "
          + ", ".join(f"{LABEL[n]} {cov.loc[n, 'min']:.0%} to "
                      f"{cov.loc[n, 'max']:.0%}" for n in run.names))
    qb = run.points[(run.points.version == "A") & run.points.role
                    & (run.points.stat == "attempts")]
    in_table = int(e[e.stat == "attempts"].n.iloc[0])
    print(f"   Passing rows are the quarterback who STARTED, and only him: "
          f"{len(qb):,} starts by a quarterback with a role, {in_table:,} of "
          f"them in the table (where all three yardsticks had a number). "
          f"He threw under 10 passes in {int((qb.actual < 10).sum())} of the "
          f"{len(qb):,}.")
    c = fs.compare_error(run, "gamelog_model", "season_avg")
    for stat in ("receptions", "receiving_yards", "rushing_yards"):
        r = c[c.stat == stat].iloc[0]
        print(f"   game-log model vs season average on {PLAIN[stat]}: "
              f"mean miss {r['diff']:+.3f} (se {r['se']:.3f}) — {r['read']}")


def show_cal(table: pd.DataFrame, unit: str = "legs",
             indent: str = "   ") -> None:
    print(f"{indent}{'it said':<10}{unit:>8}{'games':>7}{'stated':>9}"
          f"{'happened':>10}{'95% range':>17}   read")
    for r in table.itertuples():
        if r.n == 0:
            continue
        rng = f"{r.lo:.1%} to {r.hi:.1%}"
        print(f"{indent}{r.band:<10}{r.n:>8,}{r.games:>7}{r.stated:>9.1%}"
              f"{r.happened:>10.1%}{rng:>17}   {r.read}")


def show_singles(run: fs.Run) -> None:
    hdr("2. CALIBRATION OF SINGLE LINES — stand-in lines, yardage and count "
        "stats, actives known")
    print("   Each leg is read on the side the yardstick favours. The range "
          "is clustered by game.")
    for n in run.names:
        print(f"\n   {LABEL[n]}")
        show_cal(fs.calibration(fs.graded_legs(run, n, stats=COUNT_STATS)))
    g = fs.graded_legs(run, "gamelog_model", stats=COUNT_STATS)
    for side in ("OVER", "UNDER"):
        print(f"\n   game-log model, legs it favoured the {side} on")
        show_cal(fs.calibration(g[g.side == side]))
    # Established receivers only: a main targets line of 6.5 or more, which
    # is a median of at least 6 targets over his last eight games.
    keys = ["game_id", "team", "player_id"]
    a_legs = run.legs[run.legs.version == "A"]
    heavy = a_legs.loc[(a_legs.stat == "targets") & (a_legs.rung == fs.MAIN)
                       & (a_legs.line >= 6.5), keys].drop_duplicates()
    est = g.merge(heavy, on=keys)
    est = est[est.stat.isin(["targets", "receptions", "receiving_yards"])
              & (est.side == "OVER")]
    print(f"\n   game-log model, receivers with a median of 6 or more "
          f"targets ({len(heavy):,} player-games), their targets, receptions "
          f"and receiving yards only, legs it favoured the OVER on")
    show_cal(fs.calibration(est))
    m = fs.graded_legs(run, "gamelog_model", stats=COUNT_STATS, rung=fs.MAIN)
    print(f"\n   The main stand-in line went over {m.over.mean():.1%} of the "
          f"time ({len(m):,} legs); the game-log model said "
          f"{m.p.mean():.1%} on average.")
    for label, rung in (("every rung of the ladder", None),
                        ("the main line only", fs.MAIN)):
        sc = fs.score_legs(run, stats=COUNT_STATS, rung=rung)
        ref = fs.reference_brier(run, stats=COUNT_STATS, rung=rung)
        print(f"\n   Accuracy on the same legs, {label} (Brier score, lower "
              f"is better; {int(sc.n.iloc[0]):,} legs, "
              f"{int(sc.games.iloc[0])} games)")
        print(f"   {'knowing nothing about the player':<34} {ref['brier']:.4f}"
              f"   (each stat and rung's own rate, worked out on these legs)")
        for r in sc.itertuples():
            c = fs.compare_reference(run, r.projector, stats=COUNT_STATS,
                                     rung=rung)
            print(f"   {LABEL[r.projector]:<34} {r.brier:.4f}   "
                  f"({c['diff']:+.4f} against knowing nothing, se "
                  f"{c['se']:.4f}, {abs(c['diff']) / c['se']:.2f} errors — "
                  f"{c['read']})")
    for a, b in (("gamelog_model", "season_avg"), ("gamelog_model", "last4_avg")):
        c = fs.compare_brier(run, a, b, stats=COUNT_STATS)
        print(f"   {LABEL[a]} minus {LABEL[b]}, every rung: {c['diff']:+.4f} "
              f"(se {c['se']:.4f}) — {c['read']}")


def show_tds(run: fs.Run) -> None:
    hdr("3. TOUCHDOWNS — the chance of a rushing or receiving TD, as stated")
    print("   The third is NOT an engine model: the engine builds no "
          "touchdown log. It is the engine's blend on a log the harness made.")
    for n in run.names:
        name = "game-log blend (not an engine model)" if n == "gamelog_model" \
            else LABEL[n]
        print(f"\n   {name}")
        show_cal(fs.calibration(fs.graded_legs(run, n, stats=[fs.TD_STAT]),
                                folded=False))


def corr_tables() -> dict:
    """{season: {cell: r}} measured on EARLIER seasons only."""
    wk = ff_data.load_weekly(list(YEARS))
    wk = wk[wk.season_type == "REG"]
    out = {}
    for y in YEARS:
        if y < fs.FIRST_TEST_SEASON:
            continue
        prior = tuple(p for p in YEARS if p < y)
        t = ff_correlation.market_side_table(
            wk[wk.season < y], ff_correlation.CorrFilter(seasons=prior))
        out[y] = t.as_dict() if t.usable else {}
        print(f"   correlations for {y} measured on {prior}: "
              f"{len(out[y])} cells, control "
              f"{'recovered' if t.control_ok else 'FAILED — product used'}")
    return out


def show_pairs(run: fs.Run) -> None:
    hdr("4. PAIRS — both legs OVER their main stand-in line (or TD yes), "
        "game-log model's singles")
    pairs = fs.build_pairs(fs.side_legs(run, "gamelog_model"), run.joints)
    pairs = fs.add_corr(pairs, ff_correlation.recorded(
        ff_correlation.RECORDED_MARKET_SIDE), "recorded")
    pairs = fs.add_corr(pairs, corr_tables(), "earlier")
    print(f"   {len(pairs):,} pairs in {pairs.game_id.nunique()} games; "
          f"{pairs.earlier_measured.mean():.1%} sit in a cell measured on "
          f"earlier seasons. No yardstick states a joint of its own; a "
          f"simulator's will be scored in this table.")
    cells = fs.pair_cells(pairs, ("product", "recorded", "earlier"))
    cells["table_lift"] = cells["earlier"] / cells["product"]
    cells["gap"] = (cells.measured_lift - 1).abs()
    print("\n   The cells furthest from independent (at least 1,000 pairs). "
          "Lift = how much more often both happen than two separate legs "
          "would; 'table' is ff_correlation's r, earlier seasons only.")
    print(f"   {'pair':<34}{'pairs':>8}{'both':>8}{'multiply':>10}"
          f"{'table':>8}{'real lift':>11}{'+/-':>6}{'table lift':>12}")
    big = cells[cells.n >= 1000].sort_values("gap", ascending=False).head(12)
    for r in big.itertuples():
        name = f"{r.relation} team: {r.side_a} x {r.side_b}"
        print(f"   {name:<34}{r.n:>8,}{r.both:>8.1%}{r.product:>10.1%}"
              f"{r.earlier:>8.1%}{r.measured_lift:>11.2f}"
              f"{fs.Z95 * r.lift_se:>6.2f}{r.table_lift:>12.2f}")
    small = cells[(cells.relation == "same") & cells.side_a.isin(["PASS", "PASS_TD"])
                  & cells.side_b.isin(["PASS", "PASS_TD"])]
    for r in small.itertuples():
        print(f"   same team: {r.side_a} x {r.side_b} (two quarterbacks): both "
              f"happened {r.both:.1%} of {r.n} pairs in {r.games} games; "
              f"multiplying says {r.product:.1%}")
    if small.empty:
        print("   No team has two lined quarterbacks, so there is no "
              "two-quarterback cell.")
    print("\n   Accuracy of each way of pricing 'both' (Brier, lower is better)")
    for r in fs.pair_score(pairs, ["product", "recorded", "earlier"]).itertuples():
        what = {"product": "multiply the two",
                "recorded": "table correlation, recorded (same games)",
                "earlier": "table correlation, earlier seasons only"}[r.method]
        print(f"   {what:<44} {r.brier:.5f}   vs multiplying "
              f"{r.diff_vs_first:+.5f} (se {r.se:.5f}) — {r.read}")
    print("\n   Same-team pairs: stated chance both happen, table "
          "correlation (earlier seasons)")
    show_cal(fs.pair_calibration(pairs, "earlier", "same"), unit="pairs")


def show_availability(run: fs.Run) -> None:
    hdr("5. NOT KNOWING WHO IS ACTIVE")
    av = {n: fs.availability(run, n) for n in run.names}
    one = av["last4_avg"]
    print("   Projecting everyone who had been playing for the team (active "
          "in one of its last four games):")
    print(f"   {one['b_did_not_play']:.1%} of the {one['b_role_players']:,} "
          f"role players projected that way did not play for it.")
    print(f"   {one['a_not_on_b']:.1%} of the {one['a_role_players']:,} role "
          f"players who did play were not on that list at all (back from "
          f"weeks out, or new to the team).")
    b = run.points[(run.points.version == "B") & run.points.role]
    late = b[b.week >= 5].drop_duplicates(["game_id", "team", "player_id"])
    print(f"   From Week 5 on, when the last four games are all this season: "
          f"{(~late.played).mean():.1%} did not play.")
    # Each on every player-game the last-four average could project, so a
    # player who sat is not dropped for want of a season average.
    a = fs.stat_error(run, version="A", common=False).set_index(
        ["stat", "projector"])
    z = fs.stat_error(run, version="B", dnp_as_zero=True,
                      common=False).set_index(["stat", "projector"])
    for stat in ("receptions", "receiving_yards", "rushing_yards"):
        print(f"   {PLAIN[stat]}, last four: mean miss "
              f"{a.loc[(stat, 'last4_avg'), 'mean_miss']:.2f} over "
              f"{int(a.loc[(stat, 'last4_avg'), 'n']):,} players known to be "
              f"active; {z.loc[(stat, 'last4_avg'), 'mean_miss']:.2f} over "
              f"{int(z.loc[(stat, 'last4_avg'), 'n']):,} projected without "
              f"knowing, a player who sat counted as a zero")
    print("   On the players both versions projected, each yardstick gives "
          "the same number either way (difference "
          + ", ".join(f"{LABEL[n]} {av[n]['miss_diff']:+.3f}" for n in run.names)
          + "): none of them reads who is on the slate. A simulator that "
          "shares out targets will.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--current-week", type=int, default=None)
    args = ap.parse_args()
    pd.set_option("display.width", 200)

    through = newest_complete(args.current_week)
    frame = fs.load_frame(YEARS)
    print(fs.describe_frame(frame))
    by_pos = frame.attrs["report"]["share_on_field_no_stat_row_by_position"]
    print("On the field with no stat row, by position: "
          + ", ".join(f"{p} {by_pos[p]:.1%}" for p in ("WR", "TE", "RB", "QB")
                      if p in by_pos))
    if args.current_week is None:
        print(f"NOTE: no --current-week given, so the newest week on file is "
              f"treated as unfinished. Grading through {through}.")
    run = fs.walk_forward(frame, fs.yardsticks(), through=through)
    print(run.describe())

    hdr("CONTROL — run before any table")
    probe = fs.leak_probe(frame, fs.yardsticks(), run.weeks)
    print("   " + probe.describe())
    gaps = {n: fs.version_gap(run, n, counts=True) for n in run.names}
    print("   numbers that changed when the active list was hidden "
          "(changed, compared): " + str(gaps))
    ok = (probe.clean and not run.unverified
          and all(d == 0 and c > 0 for d, c in gaps.values()))
    if not ok:
        print("   THIS RUN IS VOID — no table is printed")
        return 1
    print(f"   control passed on all {len(run.weeks)} graded weeks: no "
          f"RESULT from a week being projected, or from a later one, reached "
          f"a yardstick through the harness. (Who was active and who started "
          f"that week did, by design: both are public before kickoff.)")

    show_error(run)
    show_singles(run)
    show_tds(run)
    show_pairs(run)
    show_availability(run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
