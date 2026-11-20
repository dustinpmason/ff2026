#!/usr/bin/env python3
"""
ff_sim_eff.py — S17. Efficiency: what a player does with his opportunities.

`ff_sim_opp.OpportunityModel` says how many targets, carries and pass
attempts to expect. This turns those into the things props are written on:
RECEPTIONS, RECEIVING YARDS, RUSHING YARDS, COMPLETIONS and PASSING YARDS.
It passes targets, carries and pass attempts through unchanged, and says
nothing about touchdowns, which come later.

HOW IT WORKS, IN ORDER

  1. Five rates per player, each from his own games, leaning on the newest:
       catch rate            receptions per target
       yards per catch       receiving yards per reception
       yards per carry       rushing yards per carry
       completion rate       completions per pass attempt
       yards per attempt     passing yards per pass attempt

  2. Each rate is PULLED TOWARD WHAT HIS POSITION DOES. A rate is
       (his total + k x the position's rate) / (his opportunities + k)
     so a player with few targets is mostly his position, and one with
     many is mostly himself. How hard to pull (k) is not set by hand: for
     each rate, each week, it is the value from a fixed list that would
     have predicted the history's own games best.

  3. Counts. Receptions are his targets, each caught at his catch rate; so
     are completions from attempts. Thinning a negative binomial leaves a
     negative binomial of the same size, so nothing new is fitted here.

  4. Yards. Each catch (or carry, or pass attempt) is worth a random number
     of yards with his rate as its average; how much those vary is measured
     on the history, per position. Yards for the game are the sum over
     however many catches he turns out to have. The chance of clearing a
     line adds that up over every possible number of catches.

WHAT IT LEAVES OUT, ON PURPOSE. The opponent, the game script and
touchdowns are later stages. A player's rates do not move with his
quarterback, his team, or how his role has changed. Each player is still
drawn on his own: nothing here ties a quarterback's yards to his
receivers'.

THINGS IN THE FITS A READER SHOULD KNOW. A position's rate is taken over
the whole history, so when k is chosen the early games are judged against
a norm that later games helped set (it is still only history, never the
week being projected). The catch rate is treated as fixed within a game,
so receptions are spread exactly as targets are; `sim_efficiency.py`
measures whether that is wide enough. Yards for a game are built from a
gamma distribution per catch or carry, which cannot go below zero: a line
is never set there, but a rusher's real total sometimes is. Yards per
catch or carry are floored at a tenth of a yard when a slate is projected
(not when the pull is picked); that only touches positions that hardly
ever catch or run, such as a quarterback's yards per catch. And every
count here is a negative binomial, which leans right: more of its weight
sits below its own average than above. `sim_efficiency.py` measures that
against what players actually did.

EVERYTHING ELSE IS LEARNED FROM THE HISTORY IT IS HANDED. Set by hand and
not tuned against the test (S2): the half-life of a player's totals, the
list k is chosen from, the fewest rows a rate may be learned from, the
fewest catches or carries a position needs before it gets its own spread,
and the floor under yards per catch or carry.

    python3 sim_efficiency.py --current-week 11

Owned by the simulator thread. It imports the engine and edits none of it.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

import ff_data

ff_data.ensure_deps("scipy")

from scipy.stats import gamma, nbinom  # noqa: E402

from ff_sim import (MAIN, History, Projection, Projector,  # noqa: E402
                    slate_active)
from ff_sim_opp import OPP_STATS, OpportunityModel  # noqa: E402

#: rate -> (what is counted, out of what)
RATES = {
    "catch": ("receptions", "targets"),
    "yards_per_catch": ("receiving_yards", "receptions"),
    "yards_per_carry": ("rushing_yards", "carries"),
    "completion": ("completions", "attempts"),
    "yards_per_attempt": ("passing_yards", "attempts"),
}
#: count stat -> (the opportunity it is thinned from, the rate it is thinned at)
COUNTS = {"receptions": ("targets", "catch"),
          "completions": ("attempts", "completion")}
#: yardage stat -> (the count it is summed over, the yards each one is worth)
YARDS = {"receiving_yards": ("receptions", "yards_per_catch"),
         "rushing_yards": ("carries", "yards_per_carry"),
         "passing_yards": ("attempts", "yards_per_attempt")}
#: What one of each opportunity is called, for messages.
ONE = {"targets": "target", "receptions": "catch", "carries": "carry",
       "attempts": "pass attempt"}
#: Everything this model gives a number for.
EFF_STATS = (*OPP_STATS, *COUNTS, *YARDS)

# CHOSEN, NOT TUNED (S2). Every number in this model that is set by hand.
HALF_LIFE_RATE = 16.0     # games: how fast a player's own totals are forgotten
#: How hard to pull toward the position, in targets / catches / carries /
#: attempts. One of these is picked per rate, per week, on the history.
SHRINK_GRID = (2.0, 5.0, 10.0, 20.0, 40.0, 80.0, 160.0, 320.0, 640.0, 1280.0)
#: A rate is learned from no fewer games-with-an-opportunity than this.
MIN_RATE_ROWS = 16
#: A position with fewer catches / carries / attempts than this in the
#: history takes the all-position spread of yards.
MIN_SPREAD_UNITS = 200.0
#: Yards per catch, carry or attempt are never taken below this.
RATE_FLOOR = 0.1
#: How much of a count's far tail is left out when yards are added up.
TAIL = 1e-10


def leaning_sum(values: pd.Series, groups: pd.Series, half_life: float):
    """(before, now) for a total that leans on the newest games.

    `before` is, for each row, the weighted total of that group's EARLIER
    rows: 0 for a group's first row. `now` is, per group, the total over
    all its rows. A row one half-life back counts half. Rows must already
    be in time order within a group.
    """
    incl = (values.groupby(groups).ewm(halflife=half_life).sum()
            .reset_index(level=0, drop=True).reindex(values.index))
    return incl.groupby(groups).shift(1).fillna(0.0), incl.groupby(groups).last()


def pulled(own_num, own_den, norm, k):
    """A player's rate pulled toward his position's: see the docstring."""
    return (own_num + k * norm) / (own_den + k)


class EffFit:
    """Everything learned from one History. See `EfficiencyModel.fit`."""

    def __init__(self):
        self.ok = False
        self.why = ""
        # rate -> dict(k, miss, by_pos, overall, num_now, den_now, and for
        # the three yardage rates spread, spread_all)
        self.rate = {}


class EfficiencyModel(Projector):
    """Receptions, receiving yards, rushing yards, completions and passing
    yards, on top of an opportunity model. See the module docstring.

        EfficiencyModel()                        its own OpportunityModel()
        EfficiencyModel("eff", opportunity=m)    on top of the one given
    """
    uses_actives = True

    def __init__(self, name: str = "efficiency",
                 opportunity: OpportunityModel | None = None):
        self.name = name
        self.opp = opportunity if opportunity is not None else OpportunityModel(
            f"{name}_opportunity")
        if self.opp.single != "mean":
            raise ValueError("the opportunity model underneath must report "
                             "its expected count, not its median")
        self._last = (None, None)

    # -- learning from the history -----------------------------------------
    def fit(self, hist: History) -> EffFit:
        """Learn the five rates' pull, norms and spreads from `hist` alone."""
        if self._last[0] is hist:
            return self._last[1]
        fit = EffFit()
        F = hist.frame          # each player's games together, oldest first
        for rate, (num_col, den_col) in RATES.items():
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
            by_pos = (pos_num[pos_den > 0] / pos_den[pos_den > 0]).to_dict()
            norm = F.position.map(by_pos).fillna(overall).to_numpy(dtype=float)
            num_before, num_now = leaning_sum(num, F.player_id, HALF_LIFE_RATE)
            den_before, den_now = leaning_sum(den, F.player_id, HALF_LIFE_RATE)
            x, d = num.to_numpy(dtype=float)[had], den.to_numpy(dtype=float)[had]
            nb, db = num_before.to_numpy()[had], den_before.to_numpy()[had]
            miss = {k: float(((x - d * pulled(nb, db, norm[had], k)) ** 2).sum())
                    for k in SHRINK_GRID}
            k = min(SHRINK_GRID, key=lambda v: (miss[v], v))
            out = dict(k=k, miss=miss, by_pos=by_pos, overall=overall,
                       num_now=num_now.to_dict(), den_now=den_now.to_dict())
            if rate in {r for _, r in YARDS.values()}:
                # How much one catch / carry / attempt varies: the squared
                # miss of a game's yards grows with how many he had.
                sq = (x - d * pulled(nb, db, norm[had], k)) ** 2
                pos = F.position.to_numpy(dtype=object)[had]
                units = pd.Series(d).groupby(pos).sum()
                per = pd.Series(sq).groupby(pos).sum() / units
                out["spread"] = per[units >= MIN_SPREAD_UNITS].to_dict()
                out["spread_all"] = float(sq.sum() / d.sum())
            fit.rate[rate] = out
        fit.ok = True
        self._last = (hist, fit)
        return fit

    # -- projecting a slate --------------------------------------------------
    def rates(self, hist: History, slate: pd.DataFrame) -> dict:
        """{rate: each slate player's pulled rate}; and under "spread:<rate>"
        the variance of yards from one catch, carry or attempt at his
        position. All NaN when the history is too thin."""
        fit = self.fit(hist)
        n = len(slate)
        pid = slate["player_id"].to_numpy(dtype=object)
        pos = slate["position"].to_numpy(dtype=object)
        out = {}
        for rate in RATES:
            if not fit.ok:
                out[rate] = np.full(n, np.nan)
                continue
            r = fit.rate[rate]
            norm = np.array([r["by_pos"].get(p, r["overall"]) for p in pos],
                            dtype=float)
            own_num = np.array([r["num_now"].get(p, 0.0) for p in pid], dtype=float)
            own_den = np.array([r["den_now"].get(p, 0.0) for p in pid], dtype=float)
            out[rate] = pulled(own_num, own_den, norm, r["k"])
            if "spread" in r:
                out[rate] = np.clip(out[rate], RATE_FLOOR, None)
                out[f"spread:{rate}"] = np.array(
                    [r["spread"].get(p, r["spread_all"]) for p in pos], dtype=float)
        for rate in {r for _, r in YARDS.values()}:
            out.setdefault(f"spread:{rate}", np.full(n, np.nan))
        return out

    def parts(self, hist: History, slate: pd.DataFrame) -> dict:
        """What a projection is built from, per slate row:
        {"mean": {stat: expected}, "size": {stat: negative-binomial size of
        the count underneath}, "unit": {yardage stat: (yards each, variance
        each)}}. NaN where it says nothing."""
        opp_mean = self.opp.means(hist, slate)
        opp_size = self.opp.fit(hist).size
        rt = self.rates(hist, slate)
        nan = np.full(len(slate), np.nan)
        mean = {s: opp_mean[s] for s in OPP_STATS}
        size = {s: opp_size.get(s, np.nan) for s in OPP_STATS}
        for stat, (frm, rate) in COUNTS.items():
            mean[stat] = mean[frm] * rt[rate]
            size[stat] = size[frm]
        unit = {}
        for stat, (count, rate) in YARDS.items():
            mean[stat] = mean[count] * rt[rate]
            size[stat] = size[count]
            unit[stat] = (rt[rate], rt[f"spread:{rate}"])
        if not self.fit(hist).ok:
            mean = {s: nan for s in EFF_STATS}
        return {"mean": mean, "size": size, "unit": unit,
                "count": {s: YARDS[s][0] for s in YARDS}}

    def variances(self, hist: History, slate: pd.DataFrame) -> dict:
        """{stat: the variance the model puts round its expected number}."""
        p = self.parts(hist, slate)
        out = {}
        for stat in EFF_STATS:
            m = p["mean"][stat]
            if stat in YARDS:
                each, var_each = p["unit"][stat]
                c = p["mean"][p["count"][stat]]
                out[stat] = (c * var_each
                             + each ** 2 * (c + c ** 2 / p["size"][stat]))
            else:
                out[stat] = m + m ** 2 / p["size"][stat]
        return out

    def project(self, hist: History, slate: pd.DataFrame) -> Projection:
        return _Lines(self.parts(hist, slate))


class _Lines(Projection):
    """Counts as negative binomials; yards as a sum over the count."""

    def __init__(self, parts: dict):
        self.p = parts

    def _mean(self, i, stat):
        if stat not in self.p["mean"]:
            return float("nan")
        return float(self.p["mean"][stat][i])

    def point(self, i, stat):
        return self._mean(i, stat)

    def p_over(self, i, stat, line):
        m = self._mean(i, stat)
        if math.isnan(m):
            return float("nan")
        r = self.p["size"][stat]
        if stat not in YARDS:
            return float(nbinom.sf(math.floor(line), r, r / (r + m)))
        if line < 0:
            return 1.0
        c = float(self.p["mean"][self.p["count"][stat]][i])
        each, var_each = (float(v[i]) for v in self.p["unit"][stat])
        p = r / (r + c)
        k = np.arange(1, int(nbinom.ppf(1.0 - TAIL, r, p)) + 2)
        return float((nbinom.pmf(k, r, p)
                      * gamma.sf(line, a=k * each ** 2 / var_each,
                                 scale=var_each / each)).sum())


def expected_vs_actual(model: EfficiencyModel, frame: pd.DataFrame,
                       weeks, stats=EFF_STATS) -> pd.DataFrame:
    """One row per week, slate player and stat: the model's expected number,
    the variance it puts round it, and the chance IT gives of finishing
    above that expected number (`said_above`), beside what he did. Actives
    known. Rows where the model says nothing are left out."""
    out = []
    for t in weeks:
        hist = History(frame[frame.t < t], t)
        slate = slate_active(frame, hist)
        mean = model.parts(hist, slate)["mean"]
        var = model.variances(hist, slate)
        P = model.project(hist, slate)
        played = frame[frame.t == t].set_index(["game_id", "player_id"])
        at = pd.MultiIndex.from_arrays([slate["game_id"], slate["player_id"]])
        for stat in stats:
            out.append(pd.DataFrame({
                "t": int(t), "stat": stat,
                "game_id": slate["game_id"].to_numpy(),
                "player_id": slate["player_id"].to_numpy(),
                "expected": mean[stat], "variance": var[stat],
                "said_above": [P.p_over(i, stat, m) if m == m else np.nan
                               for i, m in enumerate(mean[stat])],
                "actual": played[stat].reindex(at).to_numpy(dtype=float)}))
    rows = pd.concat(out, ignore_index=True)
    return rows[rows.expected.notna()].reset_index(drop=True)


def with_main_line(run, rows: pd.DataFrame, name: str,
                   stats=EFF_STATS) -> pd.DataFrame:
    """Each player with a MAIN stand-in line (actives known) in `stats`, his
    row of `expected_vs_actual` beside the harness's leg for him. `said` is
    `name`'s stated chance of the over and `over` whether it went over.
    Raises if the two do not line up player for player, result for result.
    """
    L = run.legs
    L = L[(L.version == "A") & (L.rung == MAIN) & L.stat.isin(list(stats))
          & L[f"p_{name}"].notna()]
    j = L.merge(rows.rename(columns={"actual": "actual_again"}),
                on=["game_id", "player_id", "stat"], how="left",
                validate="one_to_one")
    if not (j.actual == j.actual_again).all():     # a missing row fails this too
        raise RuntimeError("the harness's legs and the model's expected "
                           "numbers do not line up player for player")
    return pd.DataFrame({
        "stat": j.stat.to_numpy(), "game_id": j.game_id.to_numpy(),
        "player_id": j.player_id.to_numpy(),
        "line": j.line.to_numpy(dtype=float),
        "expected": j.expected.to_numpy(dtype=float),
        "said_above": j.said_above.to_numpy(dtype=float),
        "actual": j.actual.to_numpy(dtype=float),
        "said": j[f"p_{name}"].to_numpy(dtype=float),
        "over": j["over"].astype(bool).to_numpy()})
