#!/usr/bin/env python3
"""
ff_sim_td.py — S24. Touchdowns: anytime (rushing or receiving) and passing.

It sits on `ff_sim_eff.EfficiencyModel`, passes everything that model gives
through unchanged, and adds two stats:

    anytime_tds     a player's rushing plus receiving touchdowns, which is
                    how an anytime-touchdown prop is settled
    passing_tds     the starting quarterback's touchdown passes

HOW IT WORKS

  1. Three rates per player, each from his own games leaning on the newest
     and pulled toward what his position does, exactly as the efficiency
     rates are (`ff_sim_eff.pulled`; how hard to pull is picked each week
     on the history from a fixed list):
       touchdowns per target, touchdowns per carry, touchdown passes per
       pass attempt.
     A position has a rate of its own only once it has 200 targets,
     carries or attempts in the history. A thinner one (a cornerback's
     targets, a running back's pass attempts) is given the all-player
     rate, as is a position never seen.

  2. Counts. Each target is a touchdown at his rate, each carry at his
     rate, each pass attempt at his rate. Thinning a negative binomial
     leaves one of the same size, so his receiving touchdowns are spread
     as his targets are, his rushing touchdowns as his carries, and the two
     are added as if unrelated. The chance he scores is one minus the
     chance of none of either.

WHAT IT LEAVES OUT, ON PURPOSE OR NOT YET
  - FIRST TOUCHDOWN. Not built: it needs every scorer in the game set in
    order, and the harness has no first-touchdown result to grade against.
  - How good the OFFENCE is. A player's rate is his own pulled toward his
    position's, with nothing for his team scoring more or less than most,
    nothing for the opponent, and nothing for where on the field his
    touches come. Goal-line roles show up only through his own past
    touchdowns.
  - Touchdowns that are neither rushing nor receiving (returns, fumble
    recoveries) and two-point tries: not counted, as the prop does not.
  - His rushing and receiving touchdowns in one game are taken as
    unrelated given his expected targets and carries.

SET BY HAND, NOT TUNED (S2): the half-life of a player's totals (the
efficiency model's 16 games), the list the pull is picked from, the
fewest games a rate is learned from (the efficiency model's 16), and the
200 opportunities a position needs for a rate of its own.

MEASURED (sim_touchdowns.py; SIM-BACKLOG.md S24 has the run of record): it
beats knowing nothing and the game-log model on both stats, and its chances
run a few points LOW for the players who have a line (S25).

    python3 sim_touchdowns.py --current-week 11

Owned by the simulator thread. It imports the engine and edits none of it.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

import ff_data

ff_data.ensure_deps("scipy")

from scipy.stats import nbinom  # noqa: E402

from ff_sim import (TD_STAT, History, Projection, Projector,  # noqa: E402
                    slate_active)
from ff_sim_eff import (EFF_STATS, HALF_LIFE_RATE, MIN_RATE_ROWS,  # noqa: E402
                        ONE, EfficiencyModel, leaning_sum, pulled)

#: rate -> (what is counted, out of what)
TD_RATES = {
    "td_per_target": ("receiving_tds", "targets"),
    "td_per_carry": ("rushing_tds", "carries"),
    "td_per_attempt": ("passing_tds", "attempts"),
}
#: The two parts an anytime touchdown is made of: (opportunity, rate).
ANYTIME_PARTS = (("targets", "td_per_target"), ("carries", "td_per_carry"))
PASSING = ("attempts", "td_per_attempt")
TD_STATS = ("passing_tds", TD_STAT)
#: Everything this model gives a number for.
ALL_STATS = (*EFF_STATS, *TD_STATS)

# CHOSEN, NOT TUNED (S2).
#: How hard to pull a touchdown rate toward the position's, in targets,
#: carries or attempts. One is picked per rate, per week, on the history.
TD_SHRINK_GRID = (20.0, 40.0, 80.0, 160.0, 320.0, 640.0, 1280.0, 2560.0,
                  5120.0, 10240.0)
#: A position has its own touchdown rate once the history holds this many
#: of its targets, carries or attempts; a thinner one is given the
#: all-player rate. (The efficiency model's figure for a position's own
#: spread of yards.) Without it one catch by a tackle is a rate of 1.0.
MIN_POSITION_UNITS = 200.0


class TdFit:
    """Everything learned from one History. See `TouchdownModel.fit`."""

    def __init__(self):
        self.ok = False
        self.why = ""
        self.rate = {}      # rate -> dict(k, miss, by_pos, overall, num_now, den_now)


class TouchdownModel(Projector):
    """Anytime and passing touchdowns, on top of an efficiency model.

        TouchdownModel()                        its own EfficiencyModel()
        TouchdownModel("td", efficiency=m)      on top of the one given
    """
    uses_actives = True

    def __init__(self, name: str = "touchdowns",
                 efficiency: EfficiencyModel | None = None):
        self.name = name
        self.eff = efficiency if efficiency is not None else EfficiencyModel(
            f"{name}_efficiency")
        self._last = (None, None)

    def fit(self, hist: History) -> TdFit:
        """Learn the three touchdown rates' pull and norms from `hist` alone."""
        if self._last[0] is hist:
            return self._last[1]
        fit = TdFit()
        F = hist.frame          # each player's games together, oldest first
        for rate, (num_col, den_col) in TD_RATES.items():
            num, den = F[num_col], F[den_col]
            had = (den > 0).to_numpy()
            if int(had.sum()) < MIN_RATE_ROWS:
                fit.why = (f"only {int(had.sum())} player-games with a "
                           f"{ONE[den_col]} in the history; needs {MIN_RATE_ROWS}")
                self._last = (hist, fit)
                return fit
            overall = float(num.sum() / den.sum())
            pos_num = num.groupby(F.position).sum()
            pos_den = den.groupby(F.position).sum()
            own = pos_den >= MIN_POSITION_UNITS
            by_pos = (pos_num[own] / pos_den[own]).to_dict()
            norm = F.position.map(by_pos).fillna(overall).to_numpy(dtype=float)
            num_before, num_now = leaning_sum(num, F.player_id, HALF_LIFE_RATE)
            den_before, den_now = leaning_sum(den, F.player_id, HALF_LIFE_RATE)
            x, d = num.to_numpy(dtype=float)[had], den.to_numpy(dtype=float)[had]
            nb, db = num_before.to_numpy()[had], den_before.to_numpy()[had]
            miss = {k: float(((x - d * pulled(nb, db, norm[had], k)) ** 2).sum())
                    for k in TD_SHRINK_GRID}
            fit.rate[rate] = dict(
                k=min(TD_SHRINK_GRID, key=miss.get), miss=miss,
                by_pos=by_pos, overall=overall,
                num_now=num_now.to_dict(), den_now=den_now.to_dict())
        fit.ok = True
        self._last = (hist, fit)
        return fit

    def rates(self, hist: History, slate: pd.DataFrame) -> dict:
        """{rate: each slate player's pulled touchdown rate}. All NaN when
        the history is too thin."""
        fit = self.fit(hist)
        n = len(slate)
        pid = slate["player_id"].to_numpy(dtype=object)
        pos = slate["position"].to_numpy(dtype=object)
        out = {}
        for rate in TD_RATES:
            if not fit.ok:
                out[rate] = np.full(n, np.nan)
                continue
            r = fit.rate[rate]
            norm = np.array([r["by_pos"].get(p, r["overall"]) for p in pos],
                            dtype=float)
            own_num = np.array([r["num_now"].get(p, 0.0) for p in pid], dtype=float)
            own_den = np.array([r["den_now"].get(p, 0.0) for p in pid], dtype=float)
            out[rate] = pulled(own_num, own_den, norm, r["k"])
        return out

    def parts(self, hist: History, slate: pd.DataFrame) -> dict:
        """The efficiency model's parts, with the touchdown stats added to
        "mean", and under "td" what each is built from:
        {stat: [(expected count, negative-binomial size), ...]}, one pair
        for passing touchdowns and two (receiving, rushing) for anytime."""
        p = self.eff.parts(hist, slate)
        rt = self.rates(hist, slate)
        mean, size = dict(p["mean"]), p["size"]
        opp, rate = PASSING
        td = {"passing_tds": [(mean[opp] * rt[rate], size[opp])],
              TD_STAT: [(mean[o] * rt[r], size[o]) for o, r in ANYTIME_PARTS]}
        for stat, pieces in td.items():
            mean[stat] = sum(m for m, _ in pieces)
        return {**p, "mean": mean, "td": td}

    def variances(self, hist: History, slate: pd.DataFrame) -> dict:
        """{stat: the variance the model puts round its expected number}."""
        out = dict(self.eff.variances(hist, slate))
        for stat, pieces in self.parts(hist, slate)["td"].items():
            out[stat] = sum(m + m ** 2 / r for m, r in pieces)
        return out

    def project(self, hist: History, slate: pd.DataFrame) -> Projection:
        return _TdLines(self.eff.project(hist, slate), self.parts(hist, slate))


class _TdLines(Projection):
    """Touchdowns as one negative binomial, or the sum of two."""

    def __init__(self, under: Projection, parts: dict):
        self.under, self.p = under, parts

    def point(self, i, stat):
        if stat not in TD_STATS:
            return self.under.point(i, stat)
        return float(self.p["mean"][stat][i])

    def p_over(self, i, stat, line):
        if stat not in TD_STATS:
            return self.under.p_over(i, stat, line)
        if not math.isfinite(line):
            raise ValueError(f"a {stat} line must be a number; got {line!r}")
        n = math.floor(line) + 1        # the fewest that beat the line
        # Added from the top, so a far line is as exact as a near one and
        # the answer is never below zero: the first part alone gets there,
        # or it makes k (fewer than n) and the second makes at least the
        # rest. A line below zero is beaten by any count: n is 0 or less,
        # the first term is 1 and there is no k. A player with no expected
        # count comes out as no number: every term is NaN.
        (m0, r0), *more = [(float(m[i]), r) for m, r in self.p["td"][stat]]
        p = float(nbinom.sf(n - 1, r0, r0 / (r0 + m0)))
        for m1, r1 in more:
            k = np.arange(n)
            p += float((nbinom.pmf(k, r0, r0 / (r0 + m0))
                        * nbinom.sf(n - 1 - k, r1, r1 / (r1 + m1))).sum())
        return min(p, 1.0)      # can round a hair over 1; keeps a NaN


def parts_vs_actual(model: TouchdownModel, frame: pd.DataFrame,
                    weeks) -> pd.DataFrame:
    """One row per week and active player: what `model` expected (targets,
    carries, attempts, receiving, rushing and passing touchdowns, the
    chance of one touchdown and of two or more) beside what he did that
    week. Actives known. Players the model has no anytime number for are
    left out."""
    out = []
    for t in weeks:
        hist = History(frame[frame.t < t], t)
        slate = slate_active(frame, hist)
        p = model.parts(hist, slate)
        P = model.project(hist, slate)
        did = frame[frame.t == t].set_index(["game_id", "player_id"])
        at = pd.MultiIndex.from_arrays([slate["game_id"], slate["player_id"]])
        ok = ~np.isnan(p["mean"][TD_STAT])
        out.append(pd.DataFrame({
            "t": int(t), "game_id": slate["game_id"].to_numpy(),
            "team": slate["team"].to_numpy(),
            "player_id": slate["player_id"].to_numpy(),
            "position": slate["position"].to_numpy(),
            "starter": slate["starting_qb"].to_numpy(),
            "e_targets": p["mean"]["targets"], "e_carries": p["mean"]["carries"],
            "e_attempts": p["mean"]["attempts"],
            "e_rec_td": p["td"][TD_STAT][0][0], "e_rush_td": p["td"][TD_STAT][1][0],
            "e_pass_td": p["mean"]["passing_tds"],
            "p1": [P.p_over(i, TD_STAT, 0.5) if ok[i] else np.nan
                   for i in range(len(slate))],
            "p2": [P.p_over(i, TD_STAT, 1.5) if ok[i] else np.nan
                   for i in range(len(slate))],
            **{c: did[c].reindex(at).to_numpy(dtype=float) for c in (
                "targets", "carries", "attempts", "receiving_tds", "rushing_tds",
                "passing_tds", TD_STAT)}})[ok])
    return pd.concat(out, ignore_index=True)


def pulls_picked(model: TouchdownModel, frame: pd.DataFrame, weeks) -> pd.DataFrame:
    """One row per week: the pull picked for each rate on the history before
    it. Weeks whose history is too thin to fit are left out."""
    out = []
    for t in weeks:
        fit = model.fit(History(frame[frame.t < t], t))
        if fit.ok:
            out.append({"t": int(t), **{r: v["k"] for r, v in fit.rate.items()}})
    return pd.DataFrame(out, columns=["t", *TD_RATES])
