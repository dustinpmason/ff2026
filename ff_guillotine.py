"""
ff_guillotine.py — survival simulation for elimination (guillotine) leagues.

WHY THIS IS DIFFERENT FROM EVERY OTHER LINEUP TOOL
--------------------------------------------------
In a normal league you maximize expected points. In an elimination league the
lowest weekly score is removed, so the objective is minimizing P(I am lowest).

No projection site computes this because the question does not exist in redraft.

WHAT THE SIMULATION ACTUALLY SHOWS (measured 2026-10-29, 10-team league)
------------------------------------------------------------------------
The intuition going in was that a team comfortably ahead should minimize
variance and a team near the bottom should maximize it. Measured on this
league, that is only half right and the effect is much smaller than expected:

  Controlled regression over the top quartile of lineups, EV held fixed:
      P(elim) = 0.6925 - 0.00587 * EV + 0.00646 * sd

  * Higher variance DOES raise elimination risk: +1 point of sd costs about
    +0.65 points of elimination probability.
  * EXCHANGE RATE: 1 point of sd is worth about 1.1 points of expected points.
    Trade a point of EV to shed a point of sd and you come out marginally
    ahead.
  * But EV DOMINATES in practice. Lineup-to-lineup EV differences in a real
    roster are far larger than the sd differences, so the max-EV lineup is
    usually also the min-risk lineup. Variance is a TIEBREAKER among lineups
    of similar expected points, not a reason to bench your best players.

A WARNING FROM BUILDING THIS: the first version of this analysis compared the
low-sd half of each EV band against the high-sd half and concluded that MORE
variance was better. That comparison was confounded — the high-sd half also had
2.8 more expected points. Any future test of a variance effect must control for
the mean explicitly, not bucket and hope.

The "need a tail outcome when you are doomed" half of the intuition was NOT
reproducible here at any field size or skill gap tested. Do not assert it.

Usage
-----
    from ff_data import load_weekly
    from ff_scoring import LEAGUES
    from ff_guillotine import build_pool, run

    wk = load_weekly(2026)
    pool = build_pool(wk, LEAGUES["guillotine"])
    result = run(rosters, pool, my_team_id="3")
    print(result.report())

HONEST LIMITATIONS — read before trusting a number
--------------------------------------------------
1. NO CORRELATION. Players are drawn independently. In reality a QB and his WR1
   boom together, and a team blown out early drags its whole offense down.
   Ignoring this UNDERSTATES the variance of any single lineup. Since variance
   is the entire subject here, treat the absolute probabilities as approximate
   and the COMPARISON between lineups as the usable output. `variance_inflation`
   exists as a crude knob for this.
2. Opponents are assumed to start their best eight by mean. Real managers
   misplay lineups, which helps you. The model is therefore pessimistic.
3. Distributions are bootstrapped from 2026 game logs only — 3 to 7 games per
   player. That is a thin sample and it cannot see a role change. Cross-check
   anyone flagged by `ff_props.usage_trend` before relying on their line.
4. Injuries and byes are NOT modeled. Check them separately; a player on bye
   scores zero and this will happily project him at his average.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations

import numpy as np
import pandas as pd

from ff_scoring import League, score

RNG = np.random.default_rng(20261029)

# Starting lineup for the Mid Season Guillotine: 8 starters, no K, no DST.
SLOTS = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 2}
FLEX_ELIGIBLE = ("RB", "WR", "TE")

# Players with fewer than this many games get a widened, pessimistic
# distribution rather than a confident one built on two data points.
MIN_GAMES = 3


def build_pool(weekly: pd.DataFrame, lg: League) -> dict[str, np.ndarray]:
    """Score every player's game log under the league's real rules and return
    {player_name: array of weekly scores}. That array IS the distribution —
    bootstrapping from it preserves the real shape, including bust games, which
    a fitted normal would smooth away. Bust games are the whole subject here.
    """
    df = weekly[weekly.season_type == "REG"].copy() if "season_type" in weekly.columns \
        else weekly.copy()
    df["_pts"] = score(df, lg)
    pool: dict[str, np.ndarray] = {}
    for name, g in df.groupby("player_display_name"):
        v = g["_pts"].values.astype(float)
        if len(v):
            pool[name] = v
    return pool


def _draw(pool: dict[str, np.ndarray], name: str, n: int,
          variance_inflation: float = 1.0) -> np.ndarray:
    """Bootstrap n weekly scores for one player."""
    v = pool.get(name)
    if v is None or len(v) == 0:
        # Unknown player: assume a replacement-level, high-uncertainty line
        # rather than zero, which would make any lineup containing him look
        # catastrophic and distort every comparison.
        return np.clip(RNG.normal(6.0, 5.0, n), 0, None)

    if len(v) < MIN_GAMES:
        # Too few games to trust the shape. Keep the mean, widen the spread.
        return np.clip(RNG.normal(v.mean(), max(v.std(ddof=0), 4.0) * 1.5, n), 0, None)

    out = RNG.choice(v, n, replace=True)
    if variance_inflation != 1.0:
        m = out.mean()
        out = m + (out - m) * variance_inflation
    return np.clip(out, 0, None)


def _mean_of(pool: dict[str, np.ndarray], name: str) -> float:
    v = pool.get(name)
    return float(v.mean()) if v is not None and len(v) else 6.0


def best_lineup(roster: dict[str, list[str]], pool: dict[str, np.ndarray]) -> list[str]:
    """The highest expected-points lineup. This is what a normal league wants,
    and it is the thing the survival simulation is testing against.
    """
    used: list[str] = []
    for pos, count in (("QB", SLOTS["QB"]), ("RB", SLOTS["RB"]),
                       ("WR", SLOTS["WR"]), ("TE", SLOTS["TE"])):
        avail = sorted(roster.get(pos, []), key=lambda p: -_mean_of(pool, p))
        used += avail[:count]
    flex_pool = [p for pos in FLEX_ELIGIBLE for p in roster.get(pos, []) if p not in used]
    flex_pool.sort(key=lambda p: -_mean_of(pool, p))
    return used + flex_pool[:SLOTS["FLEX"]]


def enumerate_lineups(roster: dict[str, list[str]],
                      pool: dict[str, np.ndarray],
                      max_lineups: int = 4000) -> list[tuple[str, ...]]:
    """Every legal starting lineup. Capped for tractability — when the roster
    is large, keep the combinations with the best expected points, since a
    lineup far off the EV frontier is not a serious candidate under either
    objective.
    """
    qbs = roster.get("QB", [])
    tes = roster.get("TE", [])
    rbs = roster.get("RB", [])
    wrs = roster.get("WR", [])
    if not qbs:
        raise ValueError("roster has no QB")

    qb = max(qbs, key=lambda p: _mean_of(pool, p))

    # Dedupe by player SET. A WR in the WR slot and the same WR in the FLEX
    # slot score identically, so slot permutations of one set of eight are the
    # same lineup — enumerating them inflates the count and fills the output
    # with duplicate rows.
    seen: set[frozenset[str]] = set()
    out: list[tuple[str, ...]] = []
    for te in (tes or [None]):
        for rb2 in combinations(rbs, SLOTS["RB"]):
            for wr2 in combinations(wrs, SLOTS["WR"]):
                core = [qb] + ([te] if te else []) + list(rb2) + list(wr2)
                rest = [p for pos in FLEX_ELIGIBLE for p in roster.get(pos, [])
                        if p not in core]
                for flex in combinations(rest, SLOTS["FLEX"]):
                    full = tuple(core) + flex
                    key = frozenset(full)
                    if len(key) != len(full) or key in seen:
                        continue
                    seen.add(key)
                    out.append(full)

    if len(out) > max_lineups:
        out.sort(key=lambda L: -sum(_mean_of(pool, p) for p in L))
        out = out[:max_lineups]
    return out


@dataclass
class Result:
    my_team: str
    n_sims: int
    lineups: list[tuple[str, ...]]
    p_last: np.ndarray
    means: np.ndarray
    sds: np.ndarray
    opp_min_mean: float
    opp_scores_mean: dict[str, float]
    variance_inflation: float
    flagged: list[str] = field(default_factory=list)

    def _idx_max_ev(self) -> int:
        return int(np.argmax(self.means))

    def _idx_min_risk(self) -> int:
        return int(np.argmin(self.p_last))

    def report(self, top: int = 5) -> str:
        i_ev, i_sr = self._idx_max_ev(), self._idx_min_risk()
        L = []
        L.append(f"GUILLOTINE SURVIVAL — {self.my_team}")
        L.append(f"  {self.n_sims:,} simulations, {len(self.lineups):,} legal lineups")
        L.append(f"  opponents' weekly minimum averages {self.opp_min_mean:.1f} pts")
        if self.variance_inflation != 1.0:
            L.append(f"  variance inflation applied: {self.variance_inflation:.2f}x")
        L.append("")
        L.append(f"  MAX EXPECTED POINTS   {self.means[i_ev]:6.1f} pts "
                 f"(sd {self.sds[i_ev]:4.1f})   P(eliminated) = {self.p_last[i_ev]*100:5.2f}%")
        L.append(f"  MIN ELIMINATION RISK  {self.means[i_sr]:6.1f} pts "
                 f"(sd {self.sds[i_sr]:4.1f})   P(eliminated) = {self.p_last[i_sr]*100:5.2f}%")
        L.append("")
        # Quantify the EV/variance trade-off on THIS week's lineup set rather
        # than assuming the coefficient measured on one past week still holds.
        try:
            upper = self.means >= np.quantile(self.means, 0.75)
            X = np.column_stack([np.ones(upper.sum()), self.means[upper], self.sds[upper]])
            b, *_ = np.linalg.lstsq(X, self.p_last[upper], rcond=None)
            if abs(b[1]) > 1e-9:
                rate = abs(b[2] / b[1])
                L.append(f"  trade-off this week: +1 sd costs {b[2]*100:+.2f} pts of "
                         f"elimination risk; 1 sd ~ {rate:.1f} expected points")
                L.append("")
        except Exception:
            pass

        if i_ev == i_sr:
            L.append("  Same lineup wins on both objectives — no trade-off this week.")
            L.append("  (Expected points usually dominate variance; this is the normal result.)")
        else:
            delta = (self.p_last[i_ev] - self.p_last[i_sr]) * 100
            L.append(f"  THEY DIFFER. Switching cuts elimination risk by "
                     f"{delta:.2f} points, costing {self.means[i_ev]-self.means[i_sr]:.1f} "
                     f"expected points.")
            a, b = set(self.lineups[i_ev]), set(self.lineups[i_sr])
            L.append(f"    out: {', '.join(sorted(a - b))}")
            L.append(f"    in : {', '.join(sorted(b - a))}")
        L.append("")
        L.append("  Safest lineups:")
        for r, i in enumerate(np.argsort(self.p_last)[:top], 1):
            L.append(f"   {r}. P(elim) {self.p_last[i]*100:5.2f}%  "
                     f"{self.means[i]:5.1f} pts (sd {self.sds[i]:4.1f})  "
                     f"{', '.join(self.lineups[i])}")
        L.append("")
        L.append("  Projected opponent means:")
        for t, m in sorted(self.opp_scores_mean.items(), key=lambda x: x[1]):
            L.append(f"     {m:6.1f}  {t}")
        if self.flagged:
            L.append("")
            L.append("  ! ROLE-CHANGE FLAGS on your players — distributions may be stale:")
            for f in self.flagged:
                L.append(f"     {f}")
        return "\n".join(L)


def run(teams: list[dict],
        pool: dict[str, np.ndarray],
        my_team_id: str,
        n_sims: int = 20_000,
        variance_inflation: float = 1.0,
        flagged: list[str] | None = None) -> Result:
    """Simulate one week and return P(eliminated) for every legal lineup.

    `teams` is the list from get_roster(all_teams=True): each entry needs
    team_id, team_name and roster.

    Common random numbers: each player is drawn ONCE and every lineup is scored
    against the same draws, so lineup-to-lineup differences are real signal
    rather than simulation noise.
    """
    me = next(t for t in teams if str(t["team_id"]) == str(my_team_id))
    opponents = [t for t in teams if str(t["team_id"]) != str(my_team_id)]

    # Opponent totals: best-eight-by-mean, drawn independently.
    opp_tot = np.zeros((len(opponents), n_sims))
    opp_mean: dict[str, float] = {}
    for i, t in enumerate(opponents):
        L = best_lineup(t["roster"], pool)
        tot = np.zeros(n_sims)
        for p in L:
            tot += _draw(pool, p, n_sims, variance_inflation)
        opp_tot[i] = tot
        opp_mean[t["team_name"]] = float(tot.mean())
    opp_min = opp_tot.min(axis=0)

    # My side: draw each candidate player once, reuse across all lineups.
    lineups = enumerate_lineups(me["roster"], pool)
    players = sorted({p for L in lineups for p in L})
    idx = {p: i for i, p in enumerate(players)}
    draws = np.vstack([_draw(pool, p, n_sims, variance_inflation) for p in players])

    p_last = np.empty(len(lineups))
    means = np.empty(len(lineups))
    sds = np.empty(len(lineups))
    CHUNK = 400
    for s in range(0, len(lineups), CHUNK):
        block = lineups[s:s + CHUNK]
        sel = np.zeros((len(block), len(players)))
        for r, L in enumerate(block):
            for p in L:
                sel[r, idx[p]] += 1.0
        tot = sel @ draws                      # (block, n_sims)
        p_last[s:s + len(block)] = (tot < opp_min).mean(axis=1)
        means[s:s + len(block)] = tot.mean(axis=1)
        sds[s:s + len(block)] = tot.std(axis=1)

    return Result(my_team=me["team_name"], n_sims=n_sims, lineups=lineups,
                  p_last=p_last, means=means, sds=sds,
                  opp_min_mean=float(opp_min.mean()), opp_scores_mean=opp_mean,
                  variance_inflation=variance_inflation, flagged=flagged or [])
