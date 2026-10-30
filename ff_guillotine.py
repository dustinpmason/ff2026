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
1. CORRELATION is now modeled, from measured values rather than assumption.
   Pooled over 43,228 same-game pairs (2025-26), only three relationships are
   non-zero: a QB with his own WR (+0.31), a QB with his own TE (+0.27), and a
   QB with his own RB (-0.10). Same-team WR pairs are +0.00 — target
   competition cancels team volume — and every cross-team combination is ~0.
   So correlation inside a fantasy lineup matters ONLY when a roster stacks a
   QB with his own pass-catcher. Four of the ten rosters in this league do,
   including the user's (Lawrence + Strange, both JAX).
   Imposed via a Gaussian copula so each player's real empirical distribution
   is preserved. Pass correlate=False to reproduce the old independent draws.
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
import re
from itertools import combinations

import numpy as np
import pandas as pd

from ff_data import MIN_TEAMS_COMPLETE_WEEK
from ff_scoring import League, score

RNG = np.random.default_rng(20261029)

# Starting lineup for the Mid Season Guillotine: 8 starters, no K, no DST.
SLOTS = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 2}
FLEX_ELIGIBLE = ("RB", "WR", "TE")

# Players with fewer than this many games get a widened, pessimistic
# distribution rather than a confident one built on two data points.
MIN_GAMES = 3


# Measured over 43,228 same-game player pairs, 2025-26, each player z-scored
# against his own season baseline. Only these three are distinguishable from
# zero; everything else (including same-team WR pairs) came in at ~0.00.
SAME_TEAM_CORR = {("QB", "WR"): 0.31, ("QB", "TE"): 0.27, ("QB", "RB"): -0.10}
OPPOSING_CORR = {("RB", "RB"): -0.14}


def team_byes(weekly: pd.DataFrame) -> dict[str, int]:
    """Each NFL team's bye week, derived from the data: the week in which no
    player on that team recorded a game."""
    df = weekly[weekly.season_type == "REG"] if "season_type" in weekly.columns else weekly

    # Only COMPLETE weeks can reveal a bye. A partially-played week (the data
    # refreshed mid-week, so only Thursday's game is in) makes every team that
    # has not played yet look like it is on bye — this produced "21 teams on
    # bye in Week 8" when only the TNF game had been recorded.
    per_week = df.groupby("week").team.nunique()
    complete = set(per_week[per_week >= MIN_TEAMS_COMPLETE_WEEK].index)
    if not complete:
        return {}
    df = df[df.week.isin(complete)]
    allw = set(complete)
    out: dict[str, int] = {}
    for team, g in df.groupby("team"):
        miss = sorted(allw - set(g.week.unique()))
        if len(miss) == 1:
            out[team] = miss[0]
    return out


def players_on_bye(week: int,
                   meta: dict[str, tuple[str, str]],
                   byes: dict[str, int] | set[str] | list[str]) -> set[str]:
    """Everyone whose NFL team is on bye in `week`.

    `byes` is either a {team: bye_week} map (from team_byes() or the
    connector) or, when you already know which teams are off this week, just
    the collection of team codes — {"PIT", "TEN"}. Accepting both is
    deliberate: the second form is what you actually have in hand when
    reading a bye chart, and passing it to a dict-only signature failed with
    an opaque AttributeError.

    IMPORTANT — `team_byes()` derives byes from COMPLETED games, so it only
    knows about byes that have already happened. For an UPCOMING week the bye
    is not in the data at all: pass `byes` from the connector instead, which
    returns `bye_week` per team:

        get_schedule_and_strength(team_codes=[...])  ->  schedules[].bye_week

    Feeding a derived-byes dict and asking about a future week silently returns
    an empty set, which looks like "nobody is on bye" — the exact failure this
    function exists to prevent.
    """
    if isinstance(byes, dict):
        off = {t for t, w in byes.items() if w == week}
    else:
        off = set(byes)
    return {p for p, (team, _) in meta.items() if team in off}


def build_meta(weekly: pd.DataFrame) -> dict[str, tuple[str, str]]:
    """{player: (team, position)} — needed to know which pairs correlate."""
    df = weekly[weekly.season_type == "REG"] if "season_type" in weekly.columns else weekly
    d = df.sort_values("week").groupby("player_display_name").agg(
        team=("team", "last"), pos=("position", "last"))
    return {k: (v.team, v.pos) for k, v in d.iterrows()}


def correlation_matrix(players: list[str],
                       meta: dict[str, tuple[str, str]]) -> np.ndarray:
    """Build the correlation matrix for a set of players from the measured
    table. Nearly all off-diagonal entries are zero — only a QB sharing a real
    NFL team with his own pass-catcher or back is non-zero."""
    n = len(players)
    C = np.eye(n)
    for i in range(n):
        ti, pi = meta.get(players[i], (None, None))
        for j in range(i + 1, n):
            tj, pj = meta.get(players[j], (None, None))
            if ti is None or tj is None:
                continue
            # ONLY same-NFL-team pairs correlate here. The measured
            # opposing-RB figure (-0.14) applies to backs FACING EACH OTHER in
            # one game; two backs on unrelated teams are independent, and this
            # simulation does not model the schedule so it cannot tell those
            # apart. Treating every different-team pair as "opposing" was wrong
            # and silently suppressed lineup variance.
            if ti != tj:
                continue
            key = (pi, pj) if (pi, pj) in SAME_TEAM_CORR else (pj, pi)
            C[i, j] = C[j, i] = SAME_TEAM_CORR.get(key, 0.0)

    # A matrix assembled from pairwise values need not be positive
    # semi-definite. Clip negative eigenvalues and renormalize rather than
    # letting the Cholesky factorization fail at draw time.
    w, V = np.linalg.eigh(C)
    if w.min() < 1e-8:
        C = V @ np.diag(np.clip(w, 1e-8, None)) @ V.T
        d = np.sqrt(np.diag(C))
        C = C / np.outer(d, d)
    return C


def _correlated_draws(players: list[str],
                      pool: dict[str, np.ndarray],
                      meta: dict[str, tuple[str, str]],
                      n: int,
                      variance_inflation: float = 1.0) -> np.ndarray:
    """Draw correlated weekly scores via a Gaussian copula.

    Correlated normals -> uniforms -> each player's own empirical quantiles.
    This imposes the measured dependence WITHOUT replacing anyone's real
    distribution with a fitted normal, which matters because the bust games in
    the left tail are the whole subject.
    """
    from scipy.stats import norm
    C = correlation_matrix(players, meta)
    L = np.linalg.cholesky(C)
    Z = L @ RNG.standard_normal((len(players), n))
    U = norm.cdf(Z)

    out = np.empty((len(players), n))
    for i, p in enumerate(players):
        k = resolve(p, pool)
        v = pool.get(k) if k else None
        if v is None or len(v) < MIN_GAMES:
            out[i] = _draw(pool, p, n, variance_inflation)
        else:
            # method="inverted_cdf" returns ACTUAL observed game scores rather
            # than interpolating between them. Plain np.quantile smooths the
            # empirical distribution and shrinks its variance, which made the
            # correlated draws look LESS volatile than the bootstrap ones —
            # the opposite of what adding positive correlation should do.
            out[i] = np.quantile(v, np.clip(U[i], 1e-6, 1 - 1e-6),
                                 method="inverted_cdf")
            if variance_inflation != 1.0:
                m = out[i].mean()
                out[i] = m + (out[i] - m) * variance_inflation
    return np.clip(out, 0, None)


_SUFFIX = re.compile(r"\s+(?:Jr\.?|Sr\.?|II|III|IV|V)\s*$", re.I)


def normalize_name(n: str) -> str:
    """Canonical form for matching players across sources.

    Roster names come from FantasyPros, stat names from nflverse, and they
    disagree on suffixes: "Patrick Mahomes II" vs "Patrick Mahomes",
    "James Cook III" vs "James Cook". Unmatched names used to fall through to a
    replacement-level default, which silently STARTED a phantom over most real
    players — Mahomes was being projected at 6.0.

    THIRD occurrence of a name-join bug in this project. Never match player
    data on a raw name.
    """
    n = _SUFFIX.sub("", str(n).strip())
    return (n.replace("’", "'").replace(".", "").replace("-", " ")
            .replace("'", "").lower())


def resolve(name: str, pool: dict[str, np.ndarray]) -> str | None:
    """Pool key for a roster name, or None if genuinely absent."""
    if name in pool:
        return name
    return _canon(pool).get(normalize_name(name))


_CANON_CACHE: dict[int, dict[str, str]] = {}


def _canon(pool: dict[str, np.ndarray]) -> dict[str, str]:
    key = id(pool)
    if key not in _CANON_CACHE:
        _CANON_CACHE[key] = {normalize_name(k): k for k in pool}
    return _CANON_CACHE[key]


def unresolved(rosters: list[dict], pool: dict[str, np.ndarray]) -> dict[str, list[str]]:
    """Every roster name that cannot be matched, by team. These must be
    SURFACED, never silently defaulted."""
    out: dict[str, list[str]] = {}
    for t in rosters:
        miss = [p for pos in t.get("roster", {}) for p in t["roster"][pos]
                if resolve(p, pool) is None]
        if miss:
            out[t.get("team_name", t.get("team_id", "?"))] = miss
    return out


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
    k = resolve(name, pool)
    v = pool.get(k) if k else None
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
    k = resolve(name, pool)
    v = pool.get(k) if k else None
    # NaN, not a number. An unresolved player must never outrank a real one —
    # the old 6.0 default beat 1,058 of 1,687 real players and got started.
    return float(v.mean()) if v is not None and len(v) else float("nan")


def best_lineup(roster: dict[str, list[str]], pool: dict[str, np.ndarray],
                strict: bool = True) -> list[str]:
    """The highest expected-points lineup. This is what a normal league wants,
    and it is the thing the survival simulation is testing against.
    """
    # Unresolved players score NaN. Sort them LAST rather than letting NaN
    # comparisons scramble the order — an unknown player must never be started
    # ahead of a known one.
    def rank(p: str) -> float:
        m = _mean_of(pool, p)
        return float("inf") if np.isnan(m) else -m

    used: list[str] = []
    short: list[str] = []
    for pos, count in (("QB", SLOTS["QB"]), ("RB", SLOTS["RB"]),
                       ("WR", SLOTS["WR"]), ("TE", SLOTS["TE"])):
        avail = sorted(roster.get(pos, []), key=rank)
        if len(avail) < count:
            short.append(f"{pos} needs {count}, roster has {len(avail)}")
        used += avail[:count]
    flex_pool = sorted(
        [p for pos in FLEX_ELIGIBLE for p in roster.get(pos, []) if p not in used],
        key=rank)
    if len(flex_pool) < SLOTS["FLEX"]:
        short.append(f"FLEX needs {SLOTS['FLEX']}, {len(flex_pool)} eligible left")

    if short and strict:
        raise ValueError(
            "roster cannot fill the lineup: " + "; ".join(short) +
            ". A short lineup silently scores LOW, which makes this team look "
            "weak and the user look safe. Pass strict=False only if that is "
            "genuinely intended.")

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

    if not out:
        counts = {k: len(v) for k, v in roster.items()}
        raise ValueError(
            f"no legal lineup can be built from this roster: {counts}. "
            f"Needs {SLOTS}. Returning an empty list here made run() fail "
            f"later with an opaque error instead of naming the cause.")

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
    unresolved_names: dict[str, list[str]] = field(default_factory=dict)
    excluded: list[str] = field(default_factory=list)
    short_rosters: list[str] = field(default_factory=list)

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
        if self.short_rosters:
            L.append("")
            L.append("  ! SHORT ROSTERS after exclusions — these opponents cannot")
            L.append("    fill a lineup and are UNDERSTATED here (a real manager")
            L.append("    would make a waiver add):")
            for x in self.short_rosters:
                L.append(f"     {x}")
        if self.excluded:
            L.append("")
            L.append(f"  excluded as unavailable (bye / out / IR): "
                     f"{', '.join(self.excluded)}")
        if self.unresolved_names:
            L.append("")
            L.append("  ! UNRESOLVED PLAYER NAMES — no stats found, EXCLUDED from")
            L.append("    projections. These teams are understated:")
            for tm, ns in self.unresolved_names.items():
                L.append(f"     {tm}: {', '.join(ns)}")
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
        flagged: list[str] | None = None,
        meta: dict[str, tuple[str, str]] | None = None,
        correlate: bool = True,
        unavailable: set[str] | list[str] | None = None) -> Result:
    """Simulate one week and return P(eliminated) for every legal lineup.

    `teams` is the list from get_roster(all_teams=True): each entry needs
    team_id, team_name and roster.

    Common random numbers: each player is drawn ONCE and every lineup is scored
    against the same draws, so lineup-to-lineup differences are real signal
    rather than simulation noise.
    """
    unres = unresolved(teams, pool)

    # Remove unavailable players (bye, Out, IR) from every roster BEFORE
    # lineups are built. Zeroing them is not enough: a zeroed player can still
    # be selected, wasting a starting slot — worse than excluding him outright.
    # Only players actually on a roster are worth reporting — `unavailable`
    # is typically every player on a bye team, which is hundreds of names.
    rostered = {p for t in teams for names in t["roster"].values() for p in names}
    out_set = set(unavailable or ()) & rostered
    if out_set:
        teams = [{**t, "roster": {pos: [p for p in names if p not in out_set]
                                  for pos, names in t["roster"].items()}}
                 for t in teams]

    me = next(t for t in teams if str(t["team_id"]) == str(my_team_id))
    opponents = [t for t in teams if str(t["team_id"]) != str(my_team_id)]

    # Opponent totals: best-eight-by-mean, drawn independently.
    opp_tot = np.zeros((len(opponents), n_sims))
    opp_mean: dict[str, float] = {}
    short: list[str] = []
    use_corr = correlate and meta is not None
    for i, t in enumerate(opponents):
        # strict=False on the fallback is deliberate: byes and injuries can
        # legitimately leave a roster unable to fill every slot. A real manager
        # would make a waiver add, which this cannot model — so field what they
        # have and REPORT it. Their projection is understated, not wrong.
        try:
            L = best_lineup(t["roster"], pool)
        except ValueError as e:
            L = best_lineup(t["roster"], pool, strict=False)
            short.append(f"{t['team_name']}: "
                         f"{str(e).split('.')[0].replace('roster cannot fill the lineup: ', '')}")
        if use_corr:
            tot = _correlated_draws(L, pool, meta, n_sims, variance_inflation).sum(axis=0)
        else:
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
    if use_corr:
        draws = _correlated_draws(players, pool, meta, n_sims, variance_inflation)
    else:
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
                  variance_inflation=variance_inflation, flagged=flagged or [],
                  unresolved_names=unres, excluded=sorted(out_set),
                  short_rosters=short)
