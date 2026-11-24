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
4. Injuries and byes are applied only as far as they are HANDED IN: every
   name in `unavailable=` is taken off his roster (matched with suffixes and
   punctuation ignored, B268), and nothing else is. A player who is hurt and
   not on that list is projected at his average. `idle_games()` counts how
   long each player has gone without a stat line and the waiver board prints
   it (B269), but that is a prompt to check him, not an injury report.
5. A roster that cannot field a lineup: an OPPONENT's empty slot is filled at
   replacement level and reported under SHORT ROSTERS; a waiver candidate is
   valued against a replacement-level pickup in the empty slot (B267); MY
   roster with no quarterback, back or receiver to start is refused with the
   slot named, and with no tight end is simulated with that slot empty and
   says so.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from itertools import combinations

import numpy as np
import pandas as pd

from ff_data import MIN_TEAMS_COMPLETE_WEEK, complete_weeks
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
# Extra spread applied to a player projected from a PRIOR season, on top of
# any caller-supplied inflation. Last season's level is the only evidence
# available, so the mean is kept and the uncertainty widened instead.
STALE_VARIANCE_INFLATION = 1.35

# B68 — READ THIS BEFORE CHANGING EITHER LINE BELOW.
#
# These are a SECOND, duplicate copy of the tables in ff_boost.py. They are
# deliberately left identical for now so the regression suite can assert the
# two copies match; that assertion is what makes a one-sided edit fail loudly
# instead of silently diverging, which is how B67 came to be fixed in one
# file only.
#
# They are also the WRONG QUANTITY for this module, and knowingly so:
#   * ff_boost measures one MARKET against another — ("QB","RB") = -0.10 is
#     QB passing yards x RB rushing yards, where the negative is game script
#     (team ahead -> run more -> QB throws less).
#   * correlation_matrix() below correlates FANTASY SCORES, which include
#     receptions, receiving yards and TDs. Measured on nflverse with
#     guillotine scoring, QB x RB same-team fantasy score is +0.033 to +0.089
#     across six filter variants and POSITIVE under every one of them. The
#     game-script drag on yards does not survive into points, because TDs are
#     upside both players share. QB x WR and QB x TE land inside their
#     measured ranges; opposing RB x RB has the right sign at about twice the
#     measured magnitude.
#
# Not corrected in place, for two reasons. The effect is small and was
# measured rather than assumed: flipping QB x RB to +0.06 over 200,000 sims
# moved best P(elim) by under 0.01pp, max 0.089pp across all lineups, and
# picked the same lineup both times. And dropping one filter's levels in here
# is precisely how the existing table became unreproducible (E3) — the fix is
# E3 rebuilding BOTH tables on one documented filter, from one home.
# B68(a) recorded this as a duplicate of `ff_boost`'s tables that ought to be
# imported from one place. It should NOT be, for two separate reasons, and
# this comment exists so nobody mechanically merges them.
#
# 1. It CANNOT be imported from ff_boost: the chain runs
#    ff_guillotine <- ff_props <- ff_boost, so this module is the leaf and
#    the import would be circular. That is why the copy exists at all.
# 2. It SHOULD NOT share values anyway. B68(b) established that these are
#    DIFFERENT QUANTITIES wearing the same keys. `ff_boost`'s table is
#    MARKET-level — ("QB","RB") = -0.10 is QB *passing yards* x RB *rushing
#    yards*, where the negative is a game-script effect. This one is applied
#    to FANTASY SCORES, which include receptions, receiving yards and TDs.
#    Measured QB x RB same-team fantasy-score correlation came out POSITIVE
#    under all six filter variants (+0.033 to +0.089), so the sign here is
#    wrong, and merging the tables would make that error permanent and
#    invisible instead of fixing it.
#
# The real fix is E3: give this module its own fantasy-score table measured
# on a documented filter. Until then the values are BORROWED and known
# wrong in at least one entry. The divergence B68(a) actually feared — a
# pair added to one table and not the other — is pinned by a suite check on
# the KEY SETS, which is the part that must stay in step; the values are
# E3's business and are expected to differ once it lands.
# E3, 2026-11-10. These are no longer literals and are no longer a duplicate
# of `ff_boost`'s. They come from `ff_correlation.RECORDED_FANTASY`, which is
# the FANTASY-POINTS table — the quantity this module actually correlates —
# measured on one documented filter with a pair count and an interval per
# entry. `ff_boost` keeps its own MARKET table, which is a different
# quantity, and the two are now allowed to differ because they always should
# have.
#
# The import is safe in this direction: the cycle the old comment warned
# about was ff_guillotine <- ff_props <- ff_boost, and `ff_correlation`
# imports neither at module level.
#
# ("QB","RB") is the entry that changed sign: -0.10 (market: passing yards
# against rushing yards, where the negative is game script) becomes +0.057
# (fantasy points, where touchdowns are upside both players share). Measured
# effect of the whole swap on a real 10-team board at 200,000 sims:
# **best P(elim) 4.5515% -> 4.6140%, +0.0625pp, same recommended lineup** —
# which matches what B68 measured independently and is why this side moves
# without sign-off.
from ff_correlation import RECORDED_FANTASY as _RF

SAME_TEAM_CORR = {k: v[0] for k, v in _RF.items()
                  if k in (("QB", "WR"), ("QB", "TE"), ("QB", "RB"))}
OPPOSING_CORR = {("RB", "RB"): _RF[("RB", "RB")][0]}


def team_byes(weekly: pd.DataFrame,
               current_week: int | None = None) -> dict[str, int]:
    """Each NFL team's bye week, derived from the data: the week in which no
    player on that team recorded a game."""
    df = weekly[weekly.season_type == "REG"] if "season_type" in weekly.columns else weekly

    # Only COMPLETE weeks can reveal a bye. A partially-played week (the data
    # refreshed mid-week, so only Thursday's game is in) makes every team that
    # has not played yet look like it is on bye — this produced "21 teams on
    # bye in Week 8" when only the TNF game had been recorded.
    complete = complete_weeks(df, current_week)
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


# B138. nflverse and FantasyPros disagree on two team codes. `meta` comes
# from nflverse and carries JAX and LA; the connector returns JAC and LAR.
# Passing a connector code straight through matched NOBODY and the player was
# projected at his average ON HIS BYE — on a live board that moved Week 11
# from 16.38% to 12.76%, because Blake Corum (LA) was never excluded.
#
# This is the same silent-empty failure the docstring below already warns
# about for derived byes, in a second guise: the set comes back smaller than
# it should and nothing says so. Week 10 happened to be unaffected, since
# CHI/DEN/PHI/TB spell the same in both.
#
# Kept as a map rather than a fuzzy match: these are two known, stable
# disagreements, and a near-match rule would be a new way to pair the wrong
# team. Add to it when a third shows up.
TEAM_CODE_ALIASES = {
    "JAC": "JAX",      # FantasyPros -> nflverse
    "LAR": "LA",
}


def canon_team(code) -> str | None:
    """A team code in nflverse's spelling, or None."""
    c = _meta_field(code)
    if c is None:
        return None
    c = c.strip().upper()
    return TEAM_CODE_ALIASES.get(c, c) or None


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
        if not off and byes:
            # The silent-empty case this function exists to prevent. A derived
            # byes map only knows weeks already played, so asking it about an
            # upcoming week returns nothing and reads as "nobody is on bye".
            known = sorted(set(byes.values()))
            raise ValueError(
                f"no team has a bye in Week {week} according to this byes map, "
                f"which covers Weeks {known}. If Week {week} is UPCOMING, a "
                f"derived map cannot know its byes — team_byes() reads only "
                f"completed games. Get them from the connector instead: "
                f"get_schedule_and_strength(team_codes=[...]) -> "
                f"schedules[].bye_week, or pass the team codes directly as a "
                f"set: players_on_bye({week}, meta, {{'PIT', 'TEN'}}). "
                f"Returning an empty set here would have read as 'nobody is "
                f"on bye' and projected every bye player at his average.")
    else:
        off = set(byes)

    # B138. Normalise BOTH sides to nflverse's spelling before matching, and
    # refuse a code that matches nobody while other codes do. A connector
    # "LAR" against meta's "LA" matched zero players and the bye silently did
    # not apply.
    off_canon = {c for c in (canon_team(t) for t in off) if c}
    hits = {p: canon_team(team) for p, (team, _) in meta.items()}
    present = {t for t in hits.values() if t}
    missed = sorted(off_canon - present)
    if missed and len(missed) < len(off_canon):
        # Some codes matched and some did not. A team nobody rosters is
        # legitimate, so this is a warning in the exception only when it
        # looks like a spelling problem: the code is absent while its
        # neighbours are present.
        raise ValueError(
            f"bye team code(s) {missed} match no player in meta, while "
            f"{sorted(off_canon & present)} do. meta comes from nflverse and "
            f"spells teams {sorted(present)[:6]}...; the connector spells two "
            f"of them differently (JAC/JAX, LAR/LA), which is why "
            f"TEAM_CODE_ALIASES exists. Either this code is misspelled or "
            f"nobody in the league rosters that team — pass the codes through "
            f"canon_team() and check. Returning a short set here would have "
            f"projected a bye player at his average.")
    return {p for p, t in hits.items() if t in off_canon}


def build_meta(weekly: pd.DataFrame) -> dict[str, tuple[str, str]]:
    """{player: (team, position)} — needed to know which pairs correlate."""
    df = weekly[weekly.season_type == "REG"] if "season_type" in weekly.columns else weekly
    d = df.sort_values("week").groupby("player_display_name").agg(
        team=("team", "last"), pos=("position", "last"))
    return {k: (v.team, v.pos) for k, v in d.iterrows()}


def _meta_field(v) -> str | None:
    """A meta field as a clean string, or None when it is absent.

    B68b. `build_meta` aggregates a pandas frame with `agg("last")`, so a
    missing field arrives as `float('nan')` — and NaN is not None, nor is it
    falsy in the way a guard like `if not v` expects. This is B73 in
    `ff_boost` all over again, in the module next door: there a NaN team
    passed an `is None` check and routed a same-team pair to the OPPOSING
    branch, producing a confident wrong SIGN.
    """
    if v is None:
        return None
    if isinstance(v, float) and v != v:                      # NaN
        return None
    t = str(v).strip()
    return t or None


def meta_lookup(name: str,
                meta: dict[str, tuple[str, str]]) -> tuple[str | None,
                                                           str | None]:
    """(team, position) for a roster name, matched the way every other join
    in this module is.

    B68b. `correlation_matrix` did `meta.get(name, (None, None))` — a RAW
    NAME lookup, in the module whose own `normalize_name` docstring reads
    "THIRD occurrence of a name-join bug in this project. Never match player
    data on a raw name." Two lines away, `_correlated_draws` resolves the
    same player against the pool through `resolve()`, which DOES normalise.
    One function, two join policies.

    Measured 2026 weekly: `build_meta` yields 1,732 players with no missing
    field, so the NaN path does not fire from that source today — but 96 of
    those names carry a suffix whose plain spelling is not a meta key, so any
    roster source spelling "Brian Thomas" for "Brian Thomas Jr." misses, and
    a miss silently dropped a QB x WR pair from +0.31 to 0.00.
    """
    if name in meta:
        t, p = meta[name]
    else:
        t, p = _meta_canon(meta).get(normalize_name(name), (None, None))
    return _meta_field(t), _meta_field(p)


_META_CANON_CACHE: dict[int, dict[str, tuple[str, str]]] = {}


def _meta_canon(meta: dict) -> dict[str, tuple[str, str]]:
    """Normalised-name index over a meta dict, cached by identity like
    `_canon` does for a pool. A collision keeps the FIRST spelling rather
    than letting an arbitrary one win — B44's two Brian Thomases are
    different players, and silently preferring one is how that bug worked."""
    key = id(meta)
    if key not in _META_CANON_CACHE:
        idx: dict[str, tuple[str, str]] = {}
        for k, v in meta.items():
            idx.setdefault(normalize_name(k), v)
        _META_CANON_CACHE[key] = idx
    return _META_CANON_CACHE[key]


def correlation_coverage(players: list[str],
                         meta: dict[str, tuple[str, str]]) -> dict:
    """Which players could not be resolved well enough to correlate.

    B68b. `correlation_matrix` returns a bare ndarray, so an unresolved
    player had nowhere to be reported and became a silent 0.0 — which is
    indistinguishable from a measured independence. Measured effect of that
    silence on the simulation (`measurements/b68b_position_join_effect.py`,
    10 deliberately QB-stacked teams, 60,000 sims): removing the correlation
    signal entirely moves the best lineup's P(elim) by -2.05pp with a 4.15pp
    max shift across lineups, against a 0.10pp simulation-noise se — so the
    sim IS sensitive to this. At the measured 5.5% name-miss rate the shift
    is +0.21pp, roughly 2 se, and the recommended lineup was identical in
    every case tested. Real bug, low stakes today, reported rather than
    assumed harmless.
    """
    no_team, no_pos = [], []
    for p in players:
        t, pos = meta_lookup(p, meta)
        if t is None:
            no_team.append(p)
        elif pos is None:
            no_pos.append(p)
    return {"n": len(players), "no_team": no_team, "no_position": no_pos,
            "resolved": len(players) - len(no_team) - len(no_pos)}


def correlation_matrix(players: list[str],
                       meta: dict[str, tuple[str, str]]) -> np.ndarray:
    """Build the correlation matrix for a set of players from the measured
    table. Nearly all off-diagonal entries are zero — only a QB sharing a real
    NFL team with his own pass-catcher or back is non-zero."""
    n = len(players)
    C = np.eye(n)
    for i in range(n):
        ti, pi = meta_lookup(players[i], meta)
        for j in range(i + 1, n):
            tj, pj = meta_lookup(players[j], meta)
            if ti is None or tj is None:
                continue
            # B68b. The original complaint was that the TEAM guard above
            # had no position equivalent, so a player whose meta was
            # ("KC", None) — team joined, position did not — fell to
            # `SAME_TEAM_CORR.get(key, 0.0)` and got a silent 0.0 for what
            # may be a QB/WR pair at +0.31. An explicit `if pi is None`
            # guard here is REDUNDANT, because `_meta_field` maps NaN,
            # blank and None alike to None and no table key contains None,
            # so the keyed lookup below already misses — and a guard whose
            # removal changes no behaviour cannot be tested, which in this
            # project is worse than no guard because it reads as coverage.
            # The two real fixes are therefore elsewhere: `_meta_field`
            # normalising the absent cases, and `correlation_coverage`
            # making the miss VISIBLE instead of silent. That silence was
            # the actual defect — the 0.0 itself is the right number once
            # the position is genuinely unknown.
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
    n = (n.replace("’", "'").replace(".", "").replace("-", " ")
         .replace("'", "").lower())
    # B143. Collapse runs of whitespace, including tabs and non-breaking
    # spaces. "chig  okonkwo" and "chig okonkwo" were two different keys,
    # and the hyphen replacement above can itself manufacture a double
    # space ("Smith - Njigba"). This can only MERGE keys that differ in
    # spacing, which is the one difference that is never meaningful.
    toks = n.replace("\u00a0", " ").split()
    # Spaced initials: "A. J. Brown" and "A.J. Brown" are one man, and after
    # the dots go they are "a j brown" and "aj brown". Consecutive
    # single-letter tokens are joined. Found by the check written for the
    # whitespace fix, which expected the two to match and they did not.
    out: list[str] = []
    in_run = False                  # is out[-1] a run of single letters?
    for t in toks:
        single = len(t) == 1 and t.isalpha()
        if single and in_run:
            out[-1] += t
        else:
            out.append(t)
        in_run = single
    return " ".join(out)


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
    """Every roster name with no data ANYWHERE in the pool, by team. These
    must be SURFACED, never silently defaulted.

    A name here means the pool has nothing for this player in any season
    loaded. For a player who has prior-season data but none this season, see
    `stale_names()` — that is a different problem with a different answer.
    """
    out: dict[str, list[str]] = {}
    for t in rosters:
        miss = [p for pos in t.get("roster", {}) for p in t["roster"][pos]
                if resolve(p, pool) is None]
        if miss:
            out[t.get("team_name", t.get("team_id", "?"))] = miss
    return out


def stale_names(rosters: list[dict], pool: Pool) -> dict[str, list[str]]:
    """Roster names projected from a PRIOR season, by team.

    These resolve and are simulated, but their distribution describes a role
    they may no longer have — a player returning from a full season out is
    the likeliest case. Report them so the number can be discounted by hand.
    """
    stale = getattr(pool, "stale", set())
    if not stale:
        return {}
    out: dict[str, list[str]] = {}
    for t in rosters:
        hits = []
        for pos in t.get("roster", {}):
            for p in t["roster"][pos]:
                r = resolve(p, pool)
                if r is not None and r in stale:
                    hits.append(p)
        if hits:
            out[t.get("team_name", t.get("team_id", "?"))] = hits
    return out


class Pool(dict):
    """{player_name: array of weekly scores}, plus which entries are stale.

    A plain dict everywhere it is used; `.stale` names the players whose
    distribution came from a PRIOR season because they have no games in the
    current one.
    """
    stale: set[str]

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.stale = set()


def build_pool(weekly: pd.DataFrame, lg: League,
               season: int | None = None) -> Pool:
    """Score every player's game log under the league's real rules.

    The returned array IS the distribution — bootstrapping from it preserves
    the real shape, including bust games, which a fitted normal would smooth
    away. Bust games are the whole subject here.

    PRIOR-SEASON FALLBACK. Pass a multi-season frame and `season` to get it.
    A player with no games this season but games last season is NOT an
    unknown name — he is a player returning from a full-season absence (IR,
    suspension, a year out of the league), and he is exactly the player a
    lineup decision turns on. Zach Charbonnet had 0 rows in 2026 and 17 in
    2025 and was being reported alongside De'Zhaun Stribling, who has 0 rows
    in both: two completely different situations with completely different
    answers.

    Leaving him out is not the safe default. In a survival simulation,
    understating an OPPONENT makes that opponent likelier to post the low
    score, which makes your own elimination risk look SMALLER than it is.
    Falling back to prior-season form, with the variance inflation `run()`
    applies to stale names, errs in the conservative direction instead.
    """
    def _scored(df: pd.DataFrame) -> dict[str, np.ndarray]:
        df = df[df.season_type == "REG"].copy() if "season_type" in df.columns \
            else df.copy()
        if df.empty:
            return {}
        df["_pts"] = score(df, lg)
        out = {}
        for name, g in df.groupby("player_display_name"):
            v = g["_pts"].values.astype(float)
            if len(v):
                out[name] = v
        return out

    if season is None or "season" not in weekly.columns:
        pool = Pool(_scored(weekly))
        return pool

    pool = Pool(_scored(weekly[weekly.season == season]))
    prior = _scored(weekly[weekly.season < season])
    for name, v in prior.items():
        if name not in pool:
            pool[name] = v
            pool.stale.add(name)
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
    # A prior-season distribution describes a role the player may no longer
    # hold, so widen it on top of any caller-supplied inflation. The mean is
    # kept: last season's level is the only evidence there is, and shifting it
    # by guess would be worse than widening it.
    infl = variance_inflation
    if k in getattr(pool, "stale", ()):
        infl *= STALE_VARIANCE_INFLATION
    if infl != 1.0:
        m = out.mean()
        out = m + (out - m) * infl
    return np.clip(out, 0, None)


def _mean_of(pool: dict[str, np.ndarray], name: str) -> float:
    k = resolve(name, pool)
    v = pool.get(k) if k else None
    # NaN, not a number. An unresolved player must never outrank a real one —
    # the old 6.0 default beat 1,058 of 1,687 real players and got started.
    return float(v.mean()) if v is not None and len(v) else float("nan")


REPL_PREFIX = "__replacement_"


def replacement_name(pos: str) -> str:
    return f"{REPL_PREFIX}{pos}__"


def add_replacement_level(pool: Pool, meta: dict[str, tuple[str, str]],
                          n_teams: int = 12) -> Pool:
    """Add a replacement-level distribution per position to the pool.

    WHY. When byes or injuries leave an opponent short at a position, fielding
    an incomplete lineup scores that slot as nothing. That understates the
    opponent, which in a survival simulation makes them likelier to post the
    low score — so YOUR elimination risk reads lower than it is. The bias runs
    in the flattering direction, which is the one worth removing.

    A real manager facing an empty slot makes a waiver add. The waiver wire is
    not in this data, but its LEVEL is knowable: it is roughly the best player
    at that position nobody has rostered. With `n_teams` teams and the slot
    counts in SLOTS, the startable population at a position is about
    n_teams x slots, so replacement is the tier just past that boundary.

    The distribution is the concatenated weekly scores of that tier, not a
    mean, so a replacement add keeps a realistic spread — including the bust
    games that matter here.
    """
    pos_players: dict[str, list[tuple[float, np.ndarray]]] = {}
    for name, v in pool.items():
        if name.startswith(REPL_PREFIX) or len(v) < MIN_GAMES:
            continue
        info = meta.get(name)
        if not info:
            continue
        pos = info[1]
        if pos in ("QB", "RB", "WR", "TE"):
            pos_players.setdefault(pos, []).append((float(np.mean(v)), v))

    # FLEX is filled from RB/WR/TE, so those positions carry more startable
    # bodies than their base slot count implies.
    flex_share = {"RB": 0.4, "WR": 0.4, "TE": 0.2}
    for pos, rows in pos_players.items():
        rows.sort(key=lambda r: -r[0])
        base = SLOTS.get(pos, 1)
        startable = int(round(n_teams * (base + SLOTS["FLEX"] * flex_share.get(pos, 0.0))))
        tier = rows[startable:startable + n_teams]
        if not tier:
            tier = rows[-n_teams:] or rows
        pool[replacement_name(pos)] = np.concatenate([v for _, v in tier])
    return pool


def best_lineup(roster: dict[str, list[str]], pool: dict[str, np.ndarray],
                strict: bool = True, fill: bool = True) -> list[str]:
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

    out = used + flex_pool[:SLOTS["FLEX"]]

    # Fill what is missing at REPLACEMENT level rather than leaving it empty.
    # An empty slot scores nothing and understates the team; a waiver add is
    # what a real manager would do, and its level is knowable even though the
    # wire itself is not in this data.
    #
    # `fill` is passed in, NOT inferred from whether the pool happens to carry
    # replacement keys. Inferring it was a real bug: add_replacement_level()
    # mutates the pool in place, so once any run with fill_replacement=True
    # had touched a pool, a later run with False silently kept filling. The
    # A/B comparison the flag exists for quietly became A/A, order-dependent
    # and with no trace in the report.
    if not strict and fill:
        for pos, count in (("QB", SLOTS["QB"]), ("RB", SLOTS["RB"]),
                           ("WR", SLOTS["WR"]), ("TE", SLOTS["TE"])):
            have = len([p for p in roster.get(pos, []) if p in out])
            rn = replacement_name(pos)
            if have < count and rn in pool:
                out += [rn] * (count - have)
        flex_filled = len(flex_pool[:SLOTS["FLEX"]])
        rn = replacement_name("RB")
        if flex_filled < SLOTS["FLEX"] and rn in pool:
            out += [rn] * (SLOTS["FLEX"] - flex_filled)

    return out


class NoLegalLineup(ValueError):
    """This roster cannot field a legal lineup. A ValueError, so every
    caller that caught one still does; its own type so that a caller can
    tell "this team has a hole" from every other refusal `run()` makes."""


class LineupList(list):
    """The lineups `enumerate_lineups` kept, plus how many were legal.

    `total` is the number of legal lineups before the cap. When it is
    larger than `len(self)` the list is the highest-MEAN ones only, and the
    lowest-risk lineup is not guaranteed to be among them."""
    total: int = 0

    @property
    def capped(self) -> bool:
        return self.total > len(self)


#: B270. The cap was 4,000 and SILENT. A real 12- or 13-man roster has 160
#: to 550 legal lineups, so it never bound on a lineup question; it bound on
#: a hypothetical roster carrying four or more adds at once (16 players:
#: 4,025; 17: 6,860), which is exactly the roster a waiver thread builds to
#: ask "what is my lineup if every claim lands". Raised to where a 17-man
#: roster fits whole, and reported wherever it does bind.
MAX_LINEUPS = 20_000


def enumerate_lineups(roster: dict[str, list[str]],
                      pool: dict[str, np.ndarray],
                      max_lineups: int | None = None) -> LineupList:
    """Every legal starting lineup, as a `LineupList`.

    Capped for tractability at `max_lineups` (default `MAX_LINEUPS`). Over
    the cap, the combinations with the best expected points are kept, and
    the list says so: `.total` is the full count and `.capped` is True.
    Highest mean is an EV rule feeding a floor objective, so a capped list
    can miss the lowest-risk lineup; `Result.report()` prints that.
    """
    if max_lineups is None:
        max_lineups = MAX_LINEUPS
    qbs = roster.get("QB", [])
    tes = roster.get("TE", [])
    rbs = roster.get("RB", [])
    wrs = roster.get("WR", [])
    if not qbs:
        raise NoLegalLineup("roster has no QB")

    # B132. This was `qb = max(qbs, key=lambda p: _mean_of(pool, p))` — a
    # single QB, hard-picked by MEAN, never enumerated, while TEs, RBs and
    # WRs all are. Highest mean is an EV criterion and this function is
    # feeding a FLOOR objective, so it picks wrong whenever a lower-mean QB
    # has a better shape.
    #
    # Measured on a real board at 200,000 sims: a roster holding Jared Goff
    # (mean 18.42, sd 7.98) and Trevor Lawrence (mean 18.40, sd 6.66) forced
    # GOFF in on a 0.02 mean advantage and 1.32 more sd, and cost
    # **+0.3495pp of P(elim)** — larger than the across-seed noise floor and
    # five times the fantasy-table swap. Across all 260 lineups it enumerated,
    # Lawrence never appeared once.
    #
    # It also made a QB waiver add unanalyzable: a candidate QB is either
    # discarded (no effect, delta 0) or forced in as a replacement, so the
    # delta reported for him is a swap he may not want. That is how a session
    # got a POSITIVE delta for Goff, which is logically impossible — adding a
    # player can only expand the legal lineup set.

    # Dedupe by player SET. A WR in the WR slot and the same WR in the FLEX
    # slot score identically, so slot permutations of one set of eight are the
    # same lineup — enumerating them inflates the count and fills the output
    # with duplicate rows.
    seen: set[frozenset[str]] = set()
    out = LineupList()
    for qb in qbs:
        for te in (tes or [None]):
            for rb2 in combinations(rbs, SLOTS["RB"]):
                for wr2 in combinations(wrs, SLOTS["WR"]):
                    core = ([qb] + ([te] if te else []) + list(rb2)
                            + list(wr2))
                    rest = [p for pos in FLEX_ELIGIBLE
                            for p in roster.get(pos, []) if p not in core]
                    for flex in combinations(rest, SLOTS["FLEX"]):
                        full = tuple(core) + flex
                        key = frozenset(full)
                        if len(key) != len(full) or key in seen:
                            continue
                        seen.add(key)
                        out.append(full)

    if not out:
        counts = {k: len(v) for k, v in roster.items()}
        raise NoLegalLineup(
            f"no legal lineup can be built from this roster: {counts}. "
            f"Needs {SLOTS}. Returning an empty list here made run() fail "
            f"later with an opaque error instead of naming the cause.")

    out.total = len(out)
    if len(out) > max_lineups:
        out.sort(key=lambda L: -sum(_mean_of(pool, p) for p in L))
        kept = LineupList(out[:max_lineups])
        kept.total = out.total
        return kept
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
    week: int | None = None
    # Monte Carlo resolution. Every P(elim) here is a binomial proportion over
    # n_sims draws, so it carries sqrt(p(1-p)/n) of simulation noise. Reported
    # because a figure was quoted as a measurement when it sat inside its own
    # error bar: at the 20,000 default, 1 se on a ~3% risk is ~0.12 points,
    # and the replacement-fill correction being measured is ~0.28 points. A
    # single pair of 20k runs resolves that to barely 2 se, and one such pair
    # put the effect at +0.50 points where 80k runs put it at +0.28.
    flagged: list[str] = field(default_factory=list)
    unresolved_names: dict[str, list[str]] = field(default_factory=dict)
    excluded: list[str] = field(default_factory=list)
    short_rosters: list[str] = field(default_factory=list)
    # B135. Teams with NO players — eliminated, and excluded from the pool
    # before anything is simulated. Named rather than silently dropped: the
    # count of who is still alive is what P(elim) is relative to, so a reader
    # needs to know it changed.
    eliminated_teams: list[str] = field(default_factory=list)
    stale_projections: dict[str, list[str]] = field(default_factory=dict)
    # B68b. Players the correlation lookup could not resolve. These were
    # silently dropped to a 0.0 entry, indistinguishable from a measured
    # independence, in a simulation whose output moves 2.05pp when the
    # correlation signal is removed entirely. An ndarray has nowhere to
    # report a miss, so the miss is reported here instead.
    correlation_unresolved: dict[str, list[str]] = field(default_factory=dict)
    # B270. How many lineups were legal before the cap. Larger than
    # len(lineups) means only the highest-mean ones were simulated.
    lineups_total: int | None = None
    # B267. Slots on MY roster that nobody could fill, so they score nothing
    # in every lineup below (today only a missing tight end gets this far;
    # a missing quarterback, back or receiver is refused outright).
    my_empty_slots: list[str] = field(default_factory=list)

    @property
    def capped(self) -> bool:
        return self.lineups_total is not None and self.lineups_total > len(self.lineups)

    def cap_note(self) -> str:
        """One sentence when the lineup cap bound, else ''."""
        if not self.capped:
            return ""
        return (f"only the {len(self.lineups):,} highest-MEAN of "
                f"{self.lineups_total:,} legal lineups were simulated, so the "
                f"lowest-risk lineup may not be among them. Cut the roster to "
                f"the players actually in question, or raise "
                f"ff_guillotine.MAX_LINEUPS")

    def se(self, i: int | None = None) -> float:
        """Standard error on P(eliminated) for lineup `i` (default: the best)."""
        if i is None:
            i = self._idx_min_risk()
        p = float(self.p_last[i])
        return float(np.sqrt(max(p * (1.0 - p), 0.0) / self.n_sims))

    def sims_needed(self, resolve: float, i: int | None = None) -> int:
        """How many sims to resolve a difference of `resolve` (as a fraction,
        e.g. 0.003 for 0.3 points) at roughly 2 standard errors."""
        if i is None:
            i = self._idx_min_risk()
        p = float(self.p_last[i])
        if resolve <= 0:
            raise ValueError("resolve must be positive")
        return int(np.ceil(4.0 * max(p * (1.0 - p), 1e-9) / (resolve ** 2)))

    def _idx_max_ev(self) -> int:
        return int(np.argmax(self.means))

    def _idx_min_risk(self) -> int:
        return int(np.argmin(self.p_last))

    def report(self, top: int = 5) -> str:
        i_ev, i_sr = self._idx_max_ev(), self._idx_min_risk()
        L = []
        wk = f" — WEEK {self.week}" if self.week is not None else ""
        L.append(f"GUILLOTINE SURVIVAL — {self.my_team}{wk}")
        if self.week is None:
            # The connector's current_week and the week being simulated are
            # routinely different: the guillotine's first cut is next week, so
            # the byes that matter are next week's. Leaving the week unstated
            # made it impossible to tell, from the output alone, which week's
            # byes were applied.
            L.append("  ! week not stated — pass week= so the byes applied "
                     "can be checked against the week being simulated")
        _i = self._idx_min_risk()
        L.append(f"  {self.n_sims:,} simulations, {len(self.lineups):,} legal "
                 f"lineups  (1 se on P(elim) = {self.se()*100:.2f} pts)")
        if self.capped:
            L.append(f"  ! LINEUP CAP: {self.cap_note()}.")
        if self.my_empty_slots:
            L.append(f"  ! EMPTY SLOT: this roster has nobody available at "
                     f"{', '.join(self.my_empty_slots)}, so that slot scores "
                     f"NOTHING in every lineup below. A pickup there is worth "
                     f"more than any swap.")
        if self.se() * 100 > 0.10:
            L.append(f"    Do not quote a difference smaller than "
                     f"{self.se()*200:.2f} pts as a measurement at this sim "
                     f"count — that is 2 se. For 0.10 pt resolution use "
                     f"n_sims={self.sims_needed(0.001):,}.")
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
        if self.eliminated_teams:
            L.append("")
            L.append(f"  ELIMINATED, excluded from the pool: "
                     f"{', '.join(self.eliminated_teams)}")
            L.append(f"  Every P(elim) here is relative to the "
                     f"{len(self.opp_scores_mean) + 1} teams still alive.")
        if self.short_rosters:
            L.append("")
            L.append("  ! SHORT ROSTERS after exclusions — these opponents cannot")
            L.append("    fill a lineup and are UNDERSTATED here (a real manager")
            L.append("    would make a waiver add):")
            for x in self.short_rosters:
                L.append(f"     {x}")
        if self.correlation_unresolved:
            L.append("")
            L.append("  ! NOT CORRELATED — these players could not be matched")
            L.append("    to a team and position, so every pair involving them")
            L.append("    was drawn as INDEPENDENT. That is not a measurement:")
            L.append("    a QB and his own receiver sit at +0.31, and removing")
            L.append("    the correlation signal entirely moves P(elim) by about")
            L.append("    2pp, so treat their lineups' spread as understated.")
            for k, names in sorted(self.correlation_unresolved.items()):
                L.append(f"     {k.replace('_', ' ')}: {', '.join(names)}")
        if self.excluded:
            L.append("")
            L.append(f"  excluded as unavailable (bye / out / IR): "
                     f"{', '.join(self.excluded)}")
        if self.stale_projections:
            L.append("  ~ PROJECTED FROM LAST SEASON — no games this year, so "
                     "these describe a role they may no longer have")
            L.append(f"    (spread widened "
                     f"{STALE_VARIANCE_INFLATION:.2f}x; level is last "
                     f"season's, which is the only evidence there is)")
            for tm, ns in self.stale_projections.items():
                L.append(f"    {tm}: {', '.join(ns)}")
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
        unavailable: set[str] | list[str] | None = None,
        week: int | None = None,
        fill_replacement: bool = True) -> Result:
    """Simulate one week and return P(eliminated) for every legal lineup.

    `teams` is the list from get_roster(all_teams=True): each entry needs
    team_id, team_name and roster.

    Common random numbers: each player is drawn ONCE and every lineup is scored
    against the same draws, so lineup-to-lineup differences are real signal
    rather than simulation noise.
    """
    unres = unresolved(teams, pool)
    stale = stale_names(teams, pool)

    # Replacement level, sized to THIS league. A 12-team default would set the
    # waiver boundary in the wrong place for an 18-team guillotine, where the
    # wire is far thinner. Added automatically so a short roster is filled at
    # a realistic level rather than scoring the slot as nothing.
    # Recomputing when the keys are already present is cheap and keeps a
    # reused pool from carrying a level sized to a different league.
    if fill_replacement and meta is not None and isinstance(pool, Pool):
        add_replacement_level(pool, meta, n_teams=len(teams))

    # Remove unavailable players (bye, Out, IR) from every roster BEFORE
    # lineups are built. Zeroing them is not enough: a zeroed player can still
    # be selected, wasting a starting slot — worse than excluding him outright.
    # Only players actually on a roster are worth reporting — `unavailable`
    # is typically every player on a bye team, which is hundreds of names.
    #
    # B268. Matched on the NORMALISED name. `players_on_bye` returns the
    # data's spelling ("KC Concepcion") and the connector's roster carries
    # its own ("KC Concepcion Jr."); an exact match let him through, and on
    # the real league in Week 11 he was projected at his average on his bye.
    # This is the fourth name-join bug in this project and the rule is the
    # same as the first three: never match a player on a raw name.
    rostered = {p for t in teams for names in t["roster"].values() for p in names}
    canon_out = {normalize_name(p) for p in (unavailable or ())}
    out_set = {p for p in rostered if normalize_name(p) in canon_out}
    if out_set:
        teams = [{**t, "roster": {pos: [p for p in names if p not in out_set]
                                  for pos, names in t["roster"].items()}}
                 for t in teams]

    # B135. A team with NO PLAYERS AT ALL has been eliminated — in this
    # format the knocked-out roster is released, so the roster object comes
    # back `{}`. Such a team is no longer competing for last place and must
    # not be in the pool.
    #
    # Left in, it scored 0.00, placed last in every single simulation, and
    # returned **my P(elim) = 0.0000%**. That is the worst wrong answer this
    # engine can give: in an elimination format it says you are safe. The
    # `short_rosters` line did name it, but a caller reads the headline.
    #
    # This is NOT the same as a roster that cannot fill its slots — byes and
    # injuries do that to live teams every week, and the `strict=False`
    # fallback below handles those correctly by fielding what they have and
    # reporting it understated. The distinction is no players versus not
    # enough players.
    def _is_out(t) -> bool:
        return not any(t.get("roster", {}).values())

    eliminated = [str(t.get("team_name") or t.get("team_id"))
                  for t in teams if _is_out(t)]
    if _is_out(next((t for t in teams
                     if str(t["team_id"]) == str(my_team_id)), {})):
        raise ValueError(
            f"team {my_team_id!r} has an empty roster, which in this format "
            f"means it has already been eliminated. There is nothing to "
            f"simulate.")
    teams = [t for t in teams if not _is_out(t)]

    me = next(t for t in teams if str(t["team_id"]) == str(my_team_id))
    opponents = [t for t in teams if str(t["team_id"]) != str(my_team_id)]
    # Everyone else eliminated. A real end state in this format, and it used
    # to surface as `zero-size array to reduction operation minimum`, which
    # tells the reader nothing. There is no last place to come in when nobody
    # else is playing.
    if not opponents:
        raise ValueError(
            f"every other team in this league has an empty roster, so "
            f"{str(me.get('team_name') or my_team_id)!r} is the last one "
            f"standing. There is no elimination risk left to simulate."
            + (f" Eliminated: {', '.join(eliminated)}." if eliminated else ""))

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
            L = best_lineup(t["roster"], pool, strict=False,
                            fill=fill_replacement)
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

    # B68b. Coverage over every player the correlation path touched, not just
    # mine — an opponent's unresolved QB stack understates HIS variance,
    # which moves opp_min and so moves my P(elim) too.
    corr_unres: dict[str, list[str]] = {}
    if use_corr:
        _seen = sorted({p for t in teams
                        for names in t["roster"].values() for p in names
                        if not p.startswith(REPL_PREFIX)})
        _cov = correlation_coverage(_seen, meta)
        if _cov["no_team"]:
            corr_unres["no_team"] = _cov["no_team"]
        if _cov["no_position"]:
            corr_unres["no_position"] = _cov["no_position"]

    # My side: draw each candidate player once, reuse across all lineups.
    lineups = enumerate_lineups(me["roster"], pool)
    my_empty = [pos for pos in ("TE",) if not me["roster"].get(pos)]
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
                  variance_inflation=variance_inflation, week=week,
                  flagged=flagged or [],
                  unresolved_names=unres, excluded=sorted(out_set),
                  short_rosters=short,
        eliminated_teams=eliminated, stale_projections=stale,
                  correlation_unresolved=corr_unres,
                  lineups_total=getattr(lineups, "total", len(lineups)),
                  my_empty_slots=my_empty)


# ---------------------------------------------------------------------------
# Waiver value — what an added player is worth, measured as a PAIRED delta
# ---------------------------------------------------------------------------
#
# B133. The obvious way to value a waiver add is to run the sim twice, once
# with the player and once without, and subtract. It does not work, and the
# way it fails is quiet.
#
# `RNG` is a module-level generator consumed sequentially, one draw per
# player, so adding a player SHIFTS THE STREAM and the two runs see different
# scenarios. The difference you get back is mostly that shift. On a live board
# it produced seven different players with an identical delta of +0.284pp and
# several that "cleared 2se" — while being impossible, because adding a player
# can only EXPAND the set of legal lineups, so the best lineup's P(elim) can
# never rise. A positive delta is the tell, and it is the only reason anyone
# noticed.
#
# The fix is to never run twice. Run ONCE with the candidate on the roster,
# then read two numbers off the same draws:
#
#     p_with    = min P(elim) over ALL lineups
#     p_without = min P(elim) over lineups that do NOT contain the candidate
#
# Same scenarios, same stream, so the delta has no sampling error between the
# two terms at all and is <= 0 by construction. What remains is scenario
# spread across seeds, which is what `WaiverValue.floor` reports.
#
# Credit where due: this method came out of a live project-thread session
# that threw away its own first sweep after noticing the impossible sign.


#: B269. A free agent with no stat line in this many of his team's most
#: recent games is listed apart from the ranked board. Three, not one: the
#: weekly table leaves out a game he played and recorded nothing in.
IDLE_GAMES = 3


def idle_games(weekly: pd.DataFrame, season: int) -> dict[str, int]:
    """{player: how many of his team's most recent games have no stat line
    for him}, for everyone with a game in `season`.

    0 means he was in his team's last game. A player on injured reserve
    since Week 5 keeps his season average in the pool, and a sweep of
    "everyone unrostered averaging 6 or more" ranks him beside players who
    are on the field: on 2026-11-24, 28 of the 146 names such a sweep
    returned had not played in three or more of their team's games (Jalen
    Hurts since Week 5, Lamar Jackson since Week 8).

    Keyed by `normalize_name`, so any source's spelling finds him. A player
    with no game this season is not here at all; the pool marks him stale.
    The table has no row for a game he played and recorded nothing in, so
    a 1 can be a quiet game. That is why `IDLE_GAMES` is 3.
    """
    df = weekly[weekly.season == season] if "season" in weekly.columns else weekly
    if "season_type" in df.columns:
        df = df[df.season_type == "REG"]
    if df.empty:
        return {}
    team_weeks = {t: sorted(set(g.week)) for t, g in df.groupby("team")}
    last = df.sort_values("week").groupby("player_display_name").tail(1)
    out: dict[str, int] = {}
    for name, team, wk_ in zip(last.player_display_name, last.team, last.week):
        out[normalize_name(name)] = sum(1 for w in team_weeks.get(team, ()) if w > wk_)
    return out


def wire_sweep(pool: dict[str, np.ndarray], meta: dict, teams: list[dict], *,
               min_mean: float = 6.0, idle: dict | None = None,
               max_idle: int = IDLE_GAMES - 1) -> tuple[list[str], str]:
    """Every UNROSTERED quarterback, back, receiver and tight end averaging
    `min_mean` or more: (candidates, a printable account of who was left off).

    Left off, and named: players idle more than `max_idle` of their team's
    games (pass `idle=idle_games(weekly, season)`), and players whose only
    games are a prior season's. Both can still be priced by naming them to
    `waiver_board` directly; they are kept out of a blind sweep because a
    sweep has no injury report in it.
    """
    rostered = {normalize_name(p) for t in teams
                for names in t.get("roster", {}).values() for p in names}
    stale = getattr(pool, "stale", set())
    keep, off_idle, off_stale, thin = [], [], [], []
    for name, v in pool.items():
        if name.startswith(REPL_PREFIX) or not len(v):
            continue
        pos = _meta_field(meta_lookup(name, meta)[1]) if meta else None
        if pos not in ("QB", "RB", "WR", "TE") and name not in stale:
            continue
        key = normalize_name(name)
        m = float(np.mean(v))
        if key in rostered or m < min_mean:
            continue
        if name in stale:
            off_stale.append((m, name))
            continue
        n = None if idle is None else idle.get(key)
        if n is not None and n > max_idle:
            off_idle.append((m, f"{name} ({n})"))
            continue
        keep.append((m, name))
        if len(v) < MIN_GAMES:
            thin.append((m, f"{name} ({len(v)})"))
    by = lambda x: (-x[0], x[1])            # best first, ties by name
    keep.sort(key=by); off_idle.sort(key=by); off_stale.sort(key=by)
    thin.sort(key=by)
    L = [f"WIRE SWEEP — {len(keep)} unrostered players averaging "
         f"{min_mean:g} or more"
         + ("" if idle is not None else
            ". NO idle map was passed, so players who have not played in "
            "weeks are IN this list")]
    if off_idle:
        L.append(f"  left off, no stat line in more than {max_idle} of his "
                 f"team's latest games (games missed in brackets): "
                 + ", ".join(n for _, n in off_idle))
    if off_stale:
        L.append("  left off, no game this season (last season's numbers "
                 "only): " + ", ".join(n for _, n in off_stale))
    if thin:
        L.append(f"  KEPT on fewer than {MIN_GAMES} games (games in brackets), "
                 f"so the average is one or two games and not a level: "
                 + ", ".join(n for _, n in thin))
    L.append("  This is a list from the game log, not from an injury report: "
             "check every name you mean to bid on.")
    return [n for _, n in keep], "\n".join(L)


_NEED = (("QB", 1), ("RB", 2), ("WR", 2), ("TE", 1))


def lineup_holes(roster: dict[str, list[str]]) -> dict[str, int]:
    """{position: how many bodies short} for one legal lineup, {} when the
    roster can field one. A flex shortage is counted at RB, which is where
    `best_lineup` fills it."""
    short = {pos: need - len(roster.get(pos, []))
             for pos, need in _NEED if len(roster.get(pos, [])) < need}
    have = sum(len(roster.get(p, [])) for p in FLEX_ELIGIBLE) + sum(
        v for k, v in short.items() if k in FLEX_ELIGIBLE)
    need = sum(SLOTS[p] for p in FLEX_ELIGIBLE) + SLOTS["FLEX"]
    if have < need:
        short["RB"] = short.get("RB", 0) + (need - have)
    return short


def _fill_names(pool: dict, holes: dict[str, int]) -> dict[str, list[str]] | None:
    """Placeholder names for `holes`, each a replacement-level distribution
    already in `pool`, or None when the pool has no replacement level for
    one of the positions. A second body at one position needs its own name
    (a lineup is a SET of players), so it is an alias of the first."""
    out: dict[str, list[str]] = {}
    for pos, n in holes.items():
        base = replacement_name(pos)
        if base not in pool:
            return None
        names = [base]
        for k in range(2, n + 1):
            alias = f"{base}{k}"
            pool[alias] = pool[base]
            names.append(alias)
        out[pos] = names
    return out


@dataclass
class WaiverValue:
    player: str
    p_with: float
    p_without: float
    in_best_lineup: bool
    n_sims: int
    reachable: bool          # does he appear in ANY legal lineup
    why: str = ""
    # His distribution is a PRIOR season's. `stale_names()` cannot see this:
    # it scans rosters only, so a stale CANDIDATE was invisible and Tyreek
    # Hill — zero 2026 games — came fourth on a live board with nothing
    # saying his level was last year's.
    stale: bool = False
    # No position in `meta`, so one was assumed. A player with no 2026 rows
    # has no team and no position, and this used to fall through to "WR"
    # silently, which is a guess wearing a measurement's clothes.
    position_defaulted: bool = False
    # B267. Four ways a team with a HOLE in its lineup used to read as "he
    # does not help", which is the opposite of the truth: the team that
    # cannot field a lineup is the one that needs a pickup most.
    #   fill         the roster had a hole without him, so the without-him
    #                side was simulated with a replacement-level pickup in
    #                that slot. The delta is his worth OVER a waiver body.
    #   required     he is in every legal lineup and no replacement level
    #                was available to compare against. No delta exists.
    #   blocked      the roster has no legal lineup even WITH him.
    #   unavailable  he himself is on a bye or listed out this week.
    fill: str = ""
    required: bool = False
    blocked: str = ""
    unavailable: bool = False
    # B269. How many of his team's most recent games carry no stat line for
    # him. None when no `idle=` map was passed.
    idle: int | None = None
    # B269. Games behind his distribution. Under MIN_GAMES the simulation
    # keeps his mean and widens the spread, so one big game ranks a
    # practice-squad call-up beside a starter: on 2026-11-24 Max Hurleman,
    # one game, came second on the real board.
    games: int | None = None
    # B270. The lineup cap bound in the run this came from.
    capped: bool = False
    # The name matched nobody in the pool, in any season. That is "nothing
    # is known", which is not the same as "he enters no lineup".
    unknown: bool = False

    @property
    def delta(self) -> float:
        """Change in best-lineup P(elim). Never positive, by construction."""
        return self.p_with - self.p_without

    @property
    def is_idle(self) -> bool:
        return self.idle is not None and self.idle >= IDLE_GAMES

    def describe(self, floor: float | None = None) -> str:
        if self.unknown:
            return (f"{self.player}: NOT IN THE DATA — no game log under "
                    f"this name in any season loaded (check the spelling). "
                    f"The simulation has nothing to say about him, so a bid "
                    f"is unjustified on survival grounds and would have to "
                    f"rest on something else.")
        if self.blocked:
            return (f"{self.player}: CANNOT BE VALUED — this roster has no "
                    f"legal lineup this week even with him ({self.blocked}). "
                    f"Fill that hole first. Nothing here says he does not help.")
        if self.unavailable:
            return (f"{self.player}: UNAVAILABLE THIS WEEK — on a bye or "
                    f"listed out, so he is worth nothing this week whoever he "
                    f"is. Price him on next week's board.")
        if self.required:
            return (f"{self.player}: FILLS A HOLE — without him this roster "
                    f"has no legal lineup this week, and there was no "
                    f"replacement level to compare him against (pass meta=). "
                    f"With him: P(elim) {self.p_with:.3%}. That is a level, "
                    f"not a delta, and he is NOT a player who does not help.")
        if not self.reachable:
            return (f"{self.player}: NOT REACHABLE — he enters no legal "
                    f"lineup, so the simulation has nothing to say about him. "
                    f"A bid is unjustified on survival grounds.")
        s = (f"{self.player}: {self.p_without:.3%} -> {self.p_with:.3%}  "
             f"({self.delta * 100:+.3f}pp)")
        if self.fill:
            s += (f"  [HOLE at {self.fill}: without him that slot is a "
                  f"replacement-level pickup, so this is his worth OVER a "
                  f"waiver-wire body]")
        if self.games is not None and self.games < MIN_GAMES:
            s += (f"  [THIN: {self.games} game{'s' if self.games != 1 else ''} "
                  f"on file — this is that game, not a level]")
        if self.idle:
            s += (f"  [IDLE: no stat line in his team's last {self.idle} "
                  f"game{'s' if self.idle != 1 else ''} — confirm he is "
                  f"playing]")
        if self.capped:
            s += "  [lineup cap bound]"
        if self.stale:
            s += "  [STALE: projected from a prior season]"
        if self.position_defaulted:
            s += "  [position ASSUMED, not in meta]"
        if floor is not None:
            # `delta` is a FRACTION; `floor` is in PERCENTAGE POINTS, as its
            # own message says. Comparing them directly meant the test only
            # passed at a delta above 25pp, so EVERY line printed "inside the
            # floor" — including James Cook at -12.23pp, 78x the simulation's
            # own noise. Fourteen checks shipped around this function and not
            # one asserted on the label; they all tested the ranking and the
            # delta, which were right.
            s += ("  RESOLVED" if abs(self.delta * 100.0) > floor
                  else f"  inside the {floor:.3f}pp floor — treat as zero")
        if not self.in_best_lineup:
            s += "  [not in the best lineup]"
        return s


def waiver_value(teams: list[dict], pool: dict[str, np.ndarray],
                 *, my_team_id: str, candidate: str,
                 n_sims: int = 80_000, meta: dict | None = None,
                 week: int | None = None,
                 unavailable=None, idle: dict | None = None,
                 **kw) -> WaiverValue:
    """What `candidate` is worth to `my_team_id`, as a paired delta.

    The candidate is added to the roster and the sim runs ONCE. Both numbers
    come off those same draws, so the comparison carries no between-run noise.
    Never run this twice and subtract — see the note above this function.

    A ROSTER WITH A HOLE (B267). When the roster cannot field a lineup
    without him (its only quarterback is out, say), the without-him side is
    simulated with a replacement-level pickup in the empty slot, in the same
    run, and `.fill` names the slot. That is what a manager would really do,
    and it is how every opponent with a hole is already simulated. It needs
    `meta=`; without it he comes back `required` and no delta is claimed.

    `idle` is `idle_games(weekly, season)`; with it the value carries how
    many of his team's latest games he has no stat line in.
    """
    me = next((t for t in teams if str(t.get("team_id")) == str(my_team_id)),
              None)
    if me is None:
        raise ValueError(f"no team with id {my_team_id!r} in this league")
    who = resolve(candidate, pool)
    if who is None:
        return WaiverValue(candidate, float("nan"), float("nan"), False,
                           n_sims, False,
                           f"{candidate!r} does not resolve to anyone in the "
                           f"pool — check the spelling before reading "
                           f"anything into this", unknown=True)
    pos = None
    if meta:
        # `meta_lookup` returns (team, position); `_meta_field` cleans ONE
        # field. Passing the whole tuple made the position the string
        # "('BUF', 'WR')", so every candidate went into a slot that does not
        # exist and came back NOT REACHABLE — including six real receivers,
        # which is the only reason it was noticed.
        pos = _meta_field(meta_lookup(candidate, meta)[1])
    from_roster = next((p for p in ("RB", "WR", "TE", "QB")
                        if who in me["roster"].get(p, [])), None)
    defaulted = not (pos or from_roster)
    pos = pos or from_roster or "WR"
    is_stale = who in getattr(pool, "stale", ())

    n_idle = None if idle is None else idle.get(normalize_name(who))
    tags = dict(stale=is_stale, position_defaulted=defaulted, idle=n_idle,
                games=len(pool[who]))

    grown = {k: list(v) for k, v in me["roster"].items()}
    grown.setdefault(pos, [])
    if who not in grown[pos]:
        grown[pos].append(who)

    # B267. Can this roster field a lineup WITHOUT him, on the players
    # actually available this week? If not, give the empty slot a
    # replacement-level pickup, so that "without him" is a lineup and not a
    # void. Nothing here draws a random number, so a roster with no hole
    # runs exactly as it always did.
    canon_out = {normalize_name(p) for p in (unavailable or ())}
    is_out = normalize_name(who) in canon_out or normalize_name(candidate) in canon_out
    base = {k: [p for p in v if p != who and normalize_name(p) not in canon_out]
            for k, v in me["roster"].items()}
    holes, filled = lineup_holes(base), ""
    if holes and kw.get("fill_replacement", True) and meta is not None \
            and isinstance(pool, Pool):
        add_replacement_level(pool, meta, n_teams=len(teams))
        names = _fill_names(pool, holes)
        if names is not None:
            for hp, ns in names.items():
                grown.setdefault(hp, []).extend(ns)
            filled = ", ".join(f"{hp}" + (f" x{n}" if n > 1 else "")
                               for hp, n in holes.items())
    patched = [({**t, "roster": grown} if str(t.get("team_id")) ==
                str(my_team_id) else t) for t in teams]

    try:
        r = run(patched, pool, my_team_id=my_team_id, n_sims=n_sims, meta=meta,
                week=week, unavailable=unavailable, **kw)
    except NoLegalLineup as e:
        # No lineup even WITH him: a hole somewhere he does not play, and no
        # replacement level to stand in it. Returned, not raised, so that
        # one such candidate cannot take a whole board down with him.
        return WaiverValue(candidate, float("nan"), float("nan"), False,
                           n_sims, False, str(e), blocked=str(e).split(". ")[0],
                           unavailable=is_out, **tags)
    tags["capped"] = r.capped
    with_him = [i for i, L in enumerate(r.lineups) if who in L]
    without = [i for i, L in enumerate(r.lineups) if who not in L]
    if not with_him:
        return WaiverValue(candidate, float(min(r.p_last)),
                           float(min(r.p_last)), False, n_sims, False,
                           f"{who} is on the roster but enters no legal "
                           f"lineup — on a bye, or crowded out of every "
                           f"slot. The simulation cannot value him.",
                           unavailable=is_out, **tags)
    if not without:
        return WaiverValue(candidate, float(min(r.p_last)), float("nan"),
                           True, n_sims, False,
                           f"{who} appears in EVERY legal lineup, so there is "
                           f"no without-him comparison on this roster",
                           required=True, **tags)
    p_with = float(min(r.p_last))
    p_without = float(min(r.p_last[without]))
    best = r.lineups[int(np.argmin(r.p_last))]
    return WaiverValue(candidate, p_with, p_without, who in best, n_sims,
                       True, "paired within one run", fill=filled, **tags)


def waiver_board(teams: list[dict], pool: dict[str, np.ndarray], *,
                 my_team_id: str, candidates, n_sims: int = 80_000,
                 meta: dict | None = None, week: int | None = None,
                 unavailable=None, floor: float = 0.25,
                 idle: dict | None = None, **kw) -> str:
    """Every candidate, ranked, with the unreachable ones named not hidden.

    Pass `idle=idle_games(weekly, season)` and a free agent who has not had
    a stat line in his team's last three games is listed apart from the
    ranking, with how long it has been."""
    # One row a player. A released roster joined to a sweep names the same
    # man twice, and two runs of him print two slightly different numbers
    # that read as two findings.
    seen: set[str] = set()
    once = [c for c in candidates
            if not (normalize_name(c) in seen or seen.add(normalize_name(c)))]
    vals = [waiver_value(teams, pool, my_team_id=my_team_id, candidate=c,
                         n_sims=n_sims, meta=meta, week=week,
                         unavailable=unavailable, idle=idle, **kw)
            for c in once]
    return render_waiver_board(vals, n_sims=n_sims, floor=floor,
                               idle_checked=idle is not None)


def render_waiver_board(vals, *, n_sims: int, floor: float = 0.25,
                        idle_checked: bool | None = None) -> str:
    """Format a list of `WaiverValue`s.

    Separate from `waiver_board` so the impossible-sign alarm below can be
    TESTED. `waiver_value` cannot produce a positive delta by construction,
    so a test that goes through it can never reach that branch — and a check
    written against the combined function passed on an `or True` clause,
    which is no check at all.
    """
    ok = sorted([v for v in vals if v.reachable and not v.is_idle],
                key=lambda v: v.delta)
    idl = sorted([v for v in vals if v.reachable and v.is_idle],
                 key=lambda v: v.delta)
    # Not-reachable rows, the ones that are NOT "he does not help" first.
    no = sorted([v for v in vals if not v.reachable],
                key=lambda v: (not v.required, not v.blocked, not v.unavailable))
    L = [f"WAIVER BOARD — {len(ok)} reachable, {len(no)} not, "
         + (f"{len(idl)} idle, " if idl else "")
         + f"n_sims={n_sims:,}, floor {floor:.3f}pp"]
    for v in ok:
        L.append("  " + v.describe(floor))
    if idl:
        L.append(f"  IDLE {IDLE_GAMES}+ GAMES — not ranked with the players "
                 f"above. These numbers are his season average from before "
                 f"he stopped playing; they mean something only if he is "
                 f"confirmed back:")
        for v in idl:
            L.append("    " + v.describe(floor))
    for v in no:
        L.append("  " + v.describe())
    if any(v.fill for v in vals):
        L.append("  A HOLE means this roster cannot field a lineup this week "
                 "without a pickup at that slot. Every player marked that way "
                 "is measured against a replacement-level pickup there.")
    if idle_checked is False:
        # At the foot, so the ranked rows stay where every reader of this
        # board already looks for them.
        L.append("  ! no idle= map was passed, so a player who has not "
                 "played in weeks is ranked above on his season average with "
                 "nothing to say so. Pass idle=idle_games(weekly, season).")
    if any(v.capped for v in vals):
        L.append("  ! LINEUP CAP bound on a row marked so: only the highest-"
                 "mean lineups were simulated for it. Value candidates one at "
                 "a time on the real roster, not on a roster carrying "
                 "several adds.")
    if any(v.delta > 0 for v in ok):
        L.append("  !! a POSITIVE delta appeared, which is IMPOSSIBLE — "
                 "adding a player cannot raise the best lineup's P(elim). "
                 "Something has broken the pairing; do not act on this board.")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# Drop value — the same paired read, for a cut instead of an add
# ---------------------------------------------------------------------------
#
# B139. `waiver_value` covers the ADD case and nothing covered the DROP case,
# so a session evaluating a cut rolled its own comparison and walked into
# exactly the trap B133 exists to stop: four separate runs gave four drop
# figures spanning 0.21pp, which looked like an ordering and was entirely
# between-run RNG noise. On shared draws all four were identical to three
# decimals.
#
# The read is the same one: dropping X restricts the legal lineup set to the
# lineups that do NOT contain X, which is already what `p_without` computes.
# One run, both numbers off the same draws, no between-run term at all.
#
# TWO ZEROS THAT MEAN DIFFERENT THINGS, which is the reason this reports
# rather than just subtracts:
#
#   * a player who appears in NO legal lineup costs exactly zero STRUCTURALLY
#     — `run()` strips unavailable players before enumerating, so a bye
#     player is already absent and cutting him cannot move anything;
#   * a player who appears in some lineups but never the BEST one also costs
#     zero, which is a real finding about this roster rather than a fact
#     about the schedule.
#
# Both print 0.000 and they are not the same claim.


@dataclass
class DropValue:
    player: str
    p_before: float
    p_after: float
    appears_in: int          # how many legal lineups contain him
    total_lineups: int
    n_sims: int
    on_roster: bool = True
    why: str = ""

    @property
    def cost(self) -> float:
        """Rise in best-lineup P(elim) from cutting him. Never negative."""
        return self.p_after - self.p_before

    @property
    def structural_zero(self) -> bool:
        """Zero because he was in no lineup to begin with — a bye, usually."""
        return self.appears_in == 0

    def describe(self, floor: float = 0.25) -> str:
        if not self.on_roster:
            return f"{self.player}: NOT ON THIS ROSTER — {self.why}"
        if self.p_after != self.p_after:               # NaN
            # He is in EVERY legal lineup, so there is no without-him set to
            # compare against. Printed as its reason, not as "nan%" — which
            # is what it did, and a row of nans in a board a person reads to
            # make a cut is worse than no row.
            return (f"{self.player}: CANNOT BE PRICED — in all "
                    f"{self.total_lineups} legal lineups. {self.why}")
        s = (f"{self.player}: {self.p_before:.3%} -> {self.p_after:.3%}  "
             f"(+{self.cost * 100:.3f}pp)  in {self.appears_in}/"
             f"{self.total_lineups} lineups")
        if self.structural_zero:
            s += ("  [free STRUCTURALLY — he is in no legal lineup, so this "
                  "number cannot be anything else]")
        elif self.cost * 100 <= floor:
            s += "  [free on THIS roster — never in the best lineup]"
        return s


def drop_value(teams: list[dict], pool: dict[str, np.ndarray], *,
               my_team_id: str, candidate: str, n_sims: int = 80_000,
               meta: dict | None = None, week: int | None = None,
               unavailable=None, _result=None, **kw) -> DropValue:
    """What cutting `candidate` costs, as a paired delta within one run.

    Pass `_result` to reuse a run you already have — every drop from one
    roster reads off the same draws, so `drop_board` does exactly that and
    pays for one simulation rather than one per candidate.
    """
    me = next((t for t in teams if str(t.get("team_id")) == str(my_team_id)),
              None)
    if me is None:
        raise ValueError(f"no team with id {my_team_id!r} in this league")
    who = resolve(candidate, pool)
    mine = {p for v in me["roster"].values() for p in v}
    if who is None or who not in mine:
        return DropValue(candidate, float("nan"), float("nan"), 0, 0, n_sims,
                         False,
                         (f"{candidate!r} does not resolve to anyone in the "
                          f"pool" if who is None else
                          f"{who} is not on team {my_team_id!r}"))
    r = _result if _result is not None else run(
        teams, pool, my_team_id=my_team_id, n_sims=n_sims, meta=meta,
        week=week, unavailable=unavailable, **kw)
    without = [i for i, L in enumerate(r.lineups) if who not in L]
    appears = len(r.lineups) - len(without)
    if not without:
        return DropValue(candidate, float(min(r.p_last)), float("nan"),
                         appears, len(r.lineups), r.n_sims, True,
                         f"{who} is in EVERY legal lineup — cutting him "
                         f"leaves no lineup at all, so there is no "
                         f"comparison to make")
    return DropValue(candidate, float(min(r.p_last)),
                     float(min(r.p_last[without])), appears, len(r.lineups),
                     r.n_sims, True, "paired within one run")


def drop_board(teams: list[dict], pool: dict[str, np.ndarray], *,
               my_team_id: str, candidates=None, n_sims: int = 80_000,
               meta: dict | None = None, week: int | None = None,
               unavailable=None, floor: float = 0.25, **kw) -> str:
    """Every cut, cheapest first, off ONE set of draws.

    `candidates` defaults to the whole roster. The two kinds of zero are
    distinguished in the output, because "free because he is on a bye" and
    "free because this roster never starts him" are different claims and a
    reader acting on them would do different things.
    """
    me = next((t for t in teams if str(t.get("team_id")) == str(my_team_id)),
              None)
    if me is None:
        raise ValueError(f"no team with id {my_team_id!r} in this league")
    if candidates is None:
        candidates = sorted({p for v in me["roster"].values() for p in v})
    r = run(teams, pool, my_team_id=my_team_id, n_sims=n_sims, meta=meta,
            week=week, unavailable=unavailable, **kw)
    vals = [drop_value(teams, pool, my_team_id=my_team_id, candidate=c,
                       meta=meta, week=week, unavailable=unavailable,
                       _result=r, **kw) for c in candidates]
    ok = sorted([v for v in vals if v.on_roster and v.cost == v.cost],
                key=lambda v: v.cost)
    bad = [v for v in vals if not v.on_roster or v.cost != v.cost]
    se = (min(r.p_last) * (1 - min(r.p_last)) / r.n_sims) ** 0.5
    L = [f"DROP BOARD — {len(ok)} priced, {len(bad)} not, "
         f"n_sims={r.n_sims:,}, {len(r.lineups)} legal lineups",
         f"  1 se of simulation noise is {se * 100:.3f}pp, so a gap under "
         f"{2 * se * 100:.3f}pp between two cuts is NOT an ordering"]
    for v in ok:
        L.append("  " + v.describe(floor))
    for v in bad:
        L.append("  " + v.describe(floor))
    if r.capped:
        L.append(f"  ! LINEUP CAP: {r.cap_note()}.")
    if any(v.cost < -1e-12 for v in ok):
        L.append("  !! a NEGATIVE cost appeared, which is impossible — "
                 "removing a player cannot shrink the best lineup's P(elim). "
                 "The pairing has broken; do not act on this board.")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# Who else wants him, and what it takes to outbid them (B221)
# ---------------------------------------------------------------------------
#
# `waiver_value` says what a free agent is worth to ONE team. A FAAB bid is
# a first-price sealed auction against every other team still alive, so the
# price is set by what he is worth to THEM and by what they have left to
# spend, neither of which the board for my own roster can show.
#
# Two things here are facts and are reported as facts:
#   * nobody can bid more than they hold, so (largest opposing budget + 1)
#     wins outright;
#   * a team he does not help this week has no survival reason to pay for
#     him this week.
# What a team WILL bid is not a fact and nothing here pretends to know it.
# This returns bounds and the evidence, and leaves the number to be chosen
# and justified in the open.


@dataclass
class Demand:
    team_id: str
    team_name: str
    value: WaiverValue
    budget: float | None = None
    # Set when this team could not be simulated at all this week, which on
    # a real board means it has NO legal lineup: its only quarterback is on
    # a bye. That team is the one most likely to need a pickup, so it is
    # never read as "he does not help them". Found by running the
    # instructions' own example before shipping it.
    unvalued: str = ""

    @property
    def needs_him(self) -> bool:
        """B267. This team has NO legal lineup without him and nothing to
        compare him against. It is the team likeliest to pay, never a team
        he "does not help"."""
        return bool(self.value.required)

    @property
    def gain_pp(self) -> float:
        """Points of P(elim) he takes off this team this week (>= 0)."""
        d = self.value.delta
        return 0.0 if (not self.value.reachable or d != d) else max(0.0, -d * 100.0)


def waiver_demand(teams: list[dict], pool: dict[str, np.ndarray], *,
                  candidate: str, n_sims: int = 40_000,
                  meta: dict | None = None, week: int | None = None,
                  unavailable=None, budgets: dict | None = None,
                  idle: dict | None = None, **kw) -> list[Demand]:
    """`waiver_value` for `candidate` from EVERY live team's side.

    One paired run per team, so the cost is (live teams) simulations per
    candidate; keep the candidate list to the players actually worth a bid.
    Teams with an empty roster are eliminated and are skipped. A candidate
    already on a roster is refused: he is not on the wire.
    """
    who = resolve(candidate, pool)
    for t in teams:
        if who is not None and who in {p for v in t["roster"].values()
                                       for p in v}:
            raise ValueError(
                f"{who} is on {t.get('team_name')!r}'s roster, so he is not "
                f"a waiver candidate")
    out = []
    for t in teams:
        if not any(t["roster"].values()):
            continue
        tid = str(t.get("team_id"))
        why = ""
        try:
            v = waiver_value(teams, pool, my_team_id=tid,
                             candidate=candidate, n_sims=n_sims, meta=meta,
                             week=week, unavailable=unavailable, idle=idle,
                             **kw)
            # A team with no lineup even with him used to arrive here as an
            # exception; it is now a value marked `blocked`. Same meaning.
            why = v.blocked
        except ValueError as e:
            why = str(e)
            v = WaiverValue(who or candidate, float("nan"), float("nan"),
                            False, n_sims, False, why)
        b = None
        if budgets is not None:
            b = budgets.get(tid, budgets.get(t.get("team_id")))
        out.append(Demand(tid, str(t.get("team_name")), v,
                          None if b is None else float(b), why))
    return out


@dataclass
class FaabRead:
    candidate: str
    my_team: str
    my_budget: float
    my_gain_pp: float
    weeks_left: int
    floor_pp: float
    rivals: list            # every other live team's Demand
    missing_budgets: list   # team names with no budget supplied

    @property
    def contested(self) -> list:
        """Rivals he measurably helps THIS week, biggest gain first, plus
        any rival that could not be valued: unknown is not "no help"."""
        return sorted([d for d in self.rivals
                       if d.gain_pp > self.floor_pp or d.unvalued
                       or d.needs_him],
                      key=lambda d: -d.gain_pp)

    @property
    def can_outbid_me(self) -> list:
        return [d for d in self.rivals
                if d.budget is not None and d.budget >= self.my_budget]

    def _lock(self, ds):
        if any(d.budget is None for d in ds):
            return None
        return (max(d.budget for d in ds) + 1.0) if ds else 1.0

    @property
    def lock_all(self) -> float | None:
        """Beats every rival's whole budget. None when a budget is missing."""
        return self._lock(self.rivals)

    @property
    def lock_contested(self) -> float | None:
        """Beats the whole budget of every rival he helps this week."""
        return self._lock(self.contested)

    @property
    def pace(self) -> float:
        """Budget spread evenly over the weeks left. A reference, not a rule:
        FAAB is worth nothing once the league ends."""
        return self.my_budget / max(1, int(self.weeks_left))

    def report(self) -> str:
        L = [f"FAAB READ — {self.candidate}, for {self.my_team} "
             f"(${self.my_budget:,.0f} left, {self.weeks_left} week(s) to "
             f"play)"]
        L.append(f"  worth to me this week : {self.my_gain_pp:.3f}pp of "
                 f"P(elim)"
                 + ("" if self.my_gain_pp > self.floor_pp else
                    f"  — inside the {self.floor_pp:.3f}pp floor: he does "
                    f"not measurably help me THIS week, so any bid is for "
                    f"later weeks or to keep him from a rival"))
        L.append("  worth to each rival this week, and what they hold:")
        for d in sorted(self.rivals, key=lambda d: -d.gain_pp):
            b = "budget NOT SUPPLIED" if d.budget is None else f"${d.budget:,.0f}"
            tag = ("" if d.gain_pp > self.floor_pp else "  (no measurable help)")
            if d.unvalued:
                tag = (f"  (COULD NOT BE VALUED: {d.unvalued[:50]} — this "
                       f"team has no legal lineup as it stands, so it is "
                       f"counted as contesting)")
            elif d.needs_him:
                tag = ("  (HAS NO LEGAL LINEUP WITHOUT HIM — counted as "
                       "contesting, and the likeliest to pay)")
            elif d.value.unavailable:
                tag = "  (he is unavailable this week)"
            elif not d.value.reachable:
                tag = f"  (not valued: {d.value.why[:60]})"
            elif d.value.fill:
                tag += (f"  (HOLE at {d.value.fill}: measured against a "
                        f"replacement-level pickup)")
            L.append(f"     {d.team_name:<28} {d.gain_pp:6.3f}pp   {b}{tag}")
        if self.missing_budgets:
            L.append(f"  !! no budget for: {', '.join(self.missing_budgets)}. "
                     f"The lock prices below cannot be stated without them.")
        la, lc = self.lock_all, self.lock_contested
        if la is not None:
            L.append(f"  certain to win  : ${la:,.0f}"
                     + ("" if la <= self.my_budget else
                        f"  — MORE THAN I HOLD. "
                        f"{', '.join(d.team_name for d in self.can_outbid_me)} "
                        f"can outbid anything I offer"))
        if lc is not None:
            n = len(self.contested)
            L.append(f"  beats everyone he helps this week ({n} team(s)): "
                     f"${lc:,.0f}"
                     + ("" if lc <= self.my_budget else "  — more than I hold")
                     + ("  — nobody else is measurably helped, so the "
                        "contest is for later weeks" if n == 0 else ""))
        L.append(f"  even pace       : ${self.pace:,.0f} a week. Unspent "
                 f"FAAB is worth nothing at the end, and each week's "
                 f"released roster is stronger than the last.")
        L.append("  These are bounds and evidence, NOT a predicted winning "
                 "bid: a rival may bid for later weeks, to block, or not at "
                 "all. Last week's winning bids in this league are the only "
                 "direct evidence of what teams actually pay.")
        return "\n".join(L)


def faab_read(demand: list[Demand], *, my_team_id: str, my_budget: float,
              weeks_left: int, floor: float = 0.25) -> FaabRead:
    """Bounds on a first-price bid, from `waiver_demand`'s output.

    `my_budget` is passed on its own, never read from `budgets`, so a
    missing or stale entry for my own team cannot quietly set the answer.
    """
    me = next((d for d in demand if d.team_id == str(my_team_id)), None)
    if me is None:
        raise ValueError(f"team {my_team_id!r} is not in this demand list")
    if me.unvalued:
        raise ValueError(
            f"my own roster could not be simulated this week "
            f"({me.unvalued}). Fix the lineup problem first; a bid cannot "
            f"be bounded for a team with no legal lineup")
    if my_budget is None or float(my_budget) < 0:
        raise ValueError(f"my_budget must be a dollar amount, got {my_budget!r}")
    if int(weeks_left) < 1:
        raise ValueError(f"weeks_left must be at least 1, got {weeks_left!r}")
    rivals = [d for d in demand if d.team_id != str(my_team_id)]
    return FaabRead(me.value.player, me.team_name, float(my_budget),
                    me.gain_pp, int(weeks_left), float(floor), rivals,
                    [d.team_name for d in rivals if d.budget is None])
