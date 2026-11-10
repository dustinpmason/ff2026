#!/usr/bin/env python3
"""
ff_correlation.py — the correlation tables, recomputed rather than remembered.

E3. The 43,228-pair map lived only as four constants in `ff_boost`, duplicated
as four more in `ff_guillotine`, and the ad-hoc script that produced them was
gone. So the table could not be refreshed as the season added data, could not
be extended to a new market, and could not be checked. Worse, a 2026-11-05
sweep found the documented values **unreproducible**: every one sits inside
the range a filter sweep produces, but no filter lands on them, and the
documented pair count sits between two of them. The table is not wrong; its
method was simply unrecoverable.

THE REAL FINDING WAS THE SENSITIVITY. QB x TE ran **+0.21 to +0.50** across
reasonable filter choices — a 2.4x swing on an undocumented decision — and
the instructions tell a session to compare a book's `correlation_factor`
against this table. A factor that looks fair against +0.27 looks like a steal
against +0.50. So the filter is not an implementation detail to be buried; it
is the finding, and it is printed beside every value this module produces.

TWO TABLES, ONE FILTER. The two callers need different quantities and the
single duplicated table was doing both jobs badly:

  * `ff_boost` needs a MARKET table — QB *passing yards* against RB *rushing
    yards*, one market against another. That is what the documented numbers
    measure.
  * `ff_guillotine` needs a FANTASY-SCORE table — total points against total
    points, receptions and touchdowns included. The market numbers are the
    wrong quantity there, and for QB x RB they are the wrong SIGN: the
    game-script drag that makes passing yards trade off against rushing yards
    does not survive into points, because touchdowns are upside both players
    share.

NOTHING HERE OVERWRITES A SHIPPED CONSTANT. This module computes and reports;
swapping `ff_boost.SAME_TEAM_CORR` is a live behaviour change that gates
whether a slip gets an EV at all, and it needs a person's sign-off. The
fantasy side is different — its measured effect was under 0.1pp of P(elim)
with no change to the recommended lineup — but it is still not changed from
here.

    python3 ff_correlation.py            # both tables, with the filter
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# The filter — the whole point of this module
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CorrFilter:
    """Every choice that moves the numbers, in one object that gets printed.

    `min_volume` is None ON PURPOSE and it is the choice that matters most.
    A volume gate (say, 5+ targets to count a game) raises QB x TE from
    +0.26 to +0.50, and it is tempting because it looks like it removes
    noise. It does not: it conditions on the OUTCOME. A receiver who was
    active and saw one target is a real observation of the relationship, and
    for an Over bet it is a real losing one. Dropping those games keeps the
    outcomes where both players produced and discards the ones where they did
    not, which is the selection effect that manufactures the correlation it
    then reports.

    Conditioning on ACTIVITY is the defensible version and is what this does:
    a player appears in a game if nflverse has a row for him. `min_games` is
    a baseline-stability gate on the player, not on the game, so it does not
    have that problem.
    """
    seasons: tuple[int, ...] = (2023, 2024, 2025, 2026)
    min_games: int = 6
    min_volume: float | None = None
    min_pairs: int = 200
    regular_season_only: bool = True

    def describe(self) -> str:
        vol = ("no volume gate (conditions on ACTIVITY, not production)"
               if self.min_volume is None
               else f"min volume {self.min_volume:g} per game "
                    f"— WARNING: conditions on the outcome")
        return (f"seasons {min(self.seasons)}-{max(self.seasons)}"
                f"{' REG only' if self.regular_season_only else ''}, "
                f"z-scored per player-season, min {self.min_games} games, "
                f"{vol}, min {self.min_pairs} pairs to report an entry")


DEFAULT_FILTER = CorrFilter()

# The market each side is measured through, and the positions that carry it.
SIDE_STAT = {
    "PASS": (("QB",), "passing_yards"),
    "RUSH": (("RB",), "rushing_yards"),
    "RECV": (("WR", "TE"), "receiving_yards"),
}

# Position pairs the shipped tables key on. `ff_boost._pair_r` resolves a pair
# from the MARKET first and falls back to these, so both keyings have to come
# out of one run or they drift — which is exactly how B67 came to need fixing
# in two places.
MARKET_POSITION_PAIRS = (
    ("QB", "WR", "passing_yards", "receiving_yards", True),
    ("QB", "TE", "passing_yards", "receiving_yards", True),
    ("QB", "RB", "passing_yards", "rushing_yards", True),
    ("QB", "RB_RECV", "passing_yards", "receiving_yards", True),
    ("RB", "RB", "rushing_yards", "rushing_yards", False),
)

# The control. This method must recover something near the shipped +0.31 on
# same-team QB x WR, or none of the other numbers mean anything. A failed
# control VOIDS the run rather than printing a table nobody should use.
CONTROL_KEY = ("QB", "WR")
CONTROL_BAND = (0.18, 0.40)


# ---------------------------------------------------------------------------
# The recorded tables — what a documented run produced, with its provenance
# ---------------------------------------------------------------------------
#
# E3's complaint was that the shipped constants were four bare numbers whose
# method was gone. These are the same shape of thing with the three missing
# parts attached: the filter that produced them, the pair count, and an
# interval. `python3 ff_correlation.py` re-derives them; `verify()` re-derives
# and compares, so a drift is findable rather than assumed away.
#
# Recorded 2026-11-10 from nflverse, filter DEFAULT_FILTER, control PASS.

#: MARKET quantity — one market against another. `ff_boost`'s table.
RECORDED_MARKET = {
    ("QB", "WR"):       (+0.2614, 7891, (+0.241, +0.282)),
    ("QB", "TE"):       (+0.2149, 3935, (+0.185, +0.245)),
    ("QB", "RB"):       (-0.0755, 4737, (-0.104, -0.047)),
    ("QB", "RB_RECV"):  (+0.1705, 4649, (+0.142, +0.198)),
    ("RB", "RB"):       (-0.0793, 5795, (-0.105, -0.054)),
}

#: FANTASY-POINTS quantity — total score against total score.
#: `ff_guillotine`'s table, and a DIFFERENT quantity from the one above.
#: QB x RB is the entry that matters: the market number is -0.10 and the
#: fantasy number is POSITIVE. The game-script drag that makes passing yards
#: trade against rushing yards does not survive into points, because
#: touchdowns are upside both players share. B68 predicted the sign flip from
#: six filter variants; this is it on the documented one.
RECORDED_FANTASY = {
    ("QB", "WR"):  (+0.2167, 7971, (+0.196, +0.238)),
    ("QB", "TE"):  (+0.1895, 3955, (+0.159, +0.219)),
    ("QB", "RB"):  (+0.0565, 4793, (+0.028, +0.085)),
    ("RB", "RB"):  (-0.0316, 5888, (-0.057, -0.006)),
    ("WR", "WR"):  (+0.0187, 13065, (+0.002, +0.036)),
    ("QB", "QB"):  (+0.1350, 980, (+0.073, +0.196)),
}

#: What `ff_boost` ships today, for the comparison. NOT imported from it —
#: importing would make this module depend on the thing it audits.
SHIPPED_MARKET = {
    ("QB", "WR"): 0.31, ("QB", "TE"): 0.27, ("QB", "RB"): -0.10,
    ("QB", "RB_RECV"): 0.20, ("RB", "RB"): -0.14,
}


#: F13. Every (relation, side, side) cell, sides SORTED — the key shape
#: `ff_boost.MEASURED_PAIR_LIFT` uses, so the two compare without a
#: translation step. Recorded 2026-11-10, DEFAULT_FILTER, control
#: ('same','PASS','RECV') = +0.2456 PASS.
#:
#: RECEPTIONS, PASS_TD and TD are the sides F13 adds. `player_receptions`
#: is deliberately NOT mapped onto RECV: same-team PASS x RECEPTIONS is
#: +0.1774 against PASS x RECV at +0.2456, so treating them as one side
#: would overstate a receptions leg by about 28%.
#:
#: ("same","TD","TD") = -0.0274 contradicts the standing comment in
#: ff_boost that two same-team receivers both scoring "correlates through
#: team TD volume in a way nobody here has measured". Measured, it is
#: slightly NEGATIVE: they compete for the same end-zone looks more than
#: they share team volume.
RECORDED_MARKET_SIDE = {
    ('opp', 'PASS', 'PASS')           : (+0.0698, 974, (+0.0070, +0.1320)),
    ('opp', 'PASS', 'PASS_TD')        : (+0.1142, 1920, (+0.0698, +0.1581)),
    ('opp', 'PASS', 'RECEPTIONS')     : (+0.0027, 16476, (-0.0126, +0.0180)),
    ('opp', 'PASS', 'RECV')           : (+0.0175, 11812, (-0.0005, +0.0356)),
    ('opp', 'PASS', 'RUSH')           : (-0.0238, 4746, (-0.0523, +0.0046)),
    ('opp', 'PASS', 'TD')             : (+0.0348, 14519, (+0.0186, +0.0511)),
    ('opp', 'PASS_TD', 'PASS_TD')     : (+0.0917, 946, (+0.0281, +0.1545)),
    ('opp', 'PASS_TD', 'RECEPTIONS')  : (+0.0421, 16261, (+0.0268, +0.0574)),
    ('opp', 'PASS_TD', 'RECV')        : (+0.0483, 11657, (+0.0302, +0.0664)),
    ('opp', 'PASS_TD', 'RUSH')        : (+0.0008, 4687, (-0.0278, +0.0294)),
    ('opp', 'PASS_TD', 'TD')          : (+0.0295, 14329, (+0.0132, +0.0459)),
    ('opp', 'RECEPTIONS', 'RECEPTIONS'): (-0.0046, 70003, (-0.0120, +0.0029)),
    ('opp', 'RECEPTIONS', 'RECV')     : (+0.0033, 100395, (-0.0029, +0.0095)),
    ('opp', 'RECEPTIONS', 'RUSH')     : (-0.0031, 40370, (-0.0128, +0.0067)),
    ('opp', 'RECEPTIONS', 'TD')       : (+0.0131, 123261, (+0.0075, +0.0187)),
    ('opp', 'RECV', 'RECV')           : (+0.0100, 35986, (-0.0004, +0.0203)),
    ('opp', 'RECV', 'RUSH')           : (-0.0046, 28964, (-0.0161, +0.0070)),
    ('opp', 'RECV', 'TD')             : (+0.0143, 88357, (+0.0077, +0.0209)),
    ('opp', 'RUSH', 'RUSH')           : (-0.0789, 5815, (-0.1044, -0.0533)),
    ('opp', 'RUSH', 'TD')             : (-0.0117, 35587, (-0.0221, -0.0013)),
    ('opp', 'TD', 'TD')               : (+0.0077, 54214, (-0.0007, +0.0161)),
    ('same', 'PASS', 'PASS_TD')       : (-0.0770, 262, (-0.1963, +0.0447)),
    ('same', 'PASS', 'RECEPTIONS')    : (+0.1774, 16510, (+0.1626, +0.1922)),
    ('same', 'PASS', 'RECV')          : (+0.2456, 11843, (+0.2286, +0.2625)),
    ('same', 'PASS', 'RUSH')          : (-0.0746, 4745, (-0.1029, -0.0463)),
    ('same', 'PASS', 'TD')            : (+0.0914, 13306, (+0.0745, +0.1082)),
    ('same', 'PASS_TD', 'RECEPTIONS') : (+0.0757, 16278, (+0.0604, +0.0910)),
    ('same', 'PASS_TD', 'RECV')       : (+0.1203, 11680, (+0.1024, +0.1381)),
    ('same', 'PASS_TD', 'RUSH')       : (+0.0354, 4676, (+0.0068, +0.0640)),
    ('same', 'PASS_TD', 'TD')         : (+0.2173, 13100, (+0.2009, +0.2335)),
    ('same', 'RECEPTIONS', 'RECEPTIONS'): (+0.0308, 63678, (+0.0230, +0.0385)),
    ('same', 'RECEPTIONS', 'RECV')    : (+0.0182, 91517, (+0.0117, +0.0247)),
    ('same', 'RECEPTIONS', 'RUSH')    : (-0.0255, 36526, (-0.0358, -0.0153)),
    ('same', 'RECEPTIONS', 'TD')      : (-0.0006, 112679, (-0.0065, +0.0052)),
    ('same', 'RECV', 'RECV')          : (+0.0111, 31534, (+0.0000, +0.0221)),
    ('same', 'RECV', 'RUSH')          : (-0.0219, 28970, (-0.0334, -0.0104)),
    ('same', 'RECV', 'TD')            : (+0.0105, 81014, (+0.0036, +0.0174)),
    ('same', 'RUSH', 'RUSH')          : (+0.0907, 3866, (+0.0594, +0.1219)),
    ('same', 'RUSH', 'TD')            : (+0.0196, 32334, (+0.0087, +0.0305)),
    ('same', 'TD', 'TD')              : (-0.0274, 49520, (-0.0362, -0.0186)),
}


def recorded(table: dict) -> dict:
    """{key: r} from a recorded table, dropping n and the interval.

    An explicit step, so nothing reads a bare number by default. Both of the
    things this drops are what E3 was filed for the absence of.
    """
    return {k: v[0] for k, v in table.items()}


# ---------------------------------------------------------------------------

@dataclass
class CorrEntry:
    key: tuple
    r: float
    n: int
    lo: float
    hi: float

    @property
    def width(self) -> float:
        return self.hi - self.lo

    def describe(self) -> str:
        return (f"{str(self.key):<22} r={self.r:+.4f}  "
                f"95% CI [{self.lo:+.3f}, {self.hi:+.3f}]  n={self.n:,}")


def fisher_ci(r: float, n: int, conf: float = 0.95) -> tuple[float, float]:
    """Fisher-z interval for a correlation.

    A bare point estimate is what E3 was filed against: the shipped table
    gave four numbers and no way to tell a well-measured one from a thin one.
    """
    if n < 4 or not -1.0 < r < 1.0:
        return (float("nan"), float("nan"))
    z = math.atanh(r)
    se = 1.0 / math.sqrt(n - 3)
    crit = 1.959963985 if abs(conf - 0.95) < 1e-9 else abs(
        _norm_ppf(0.5 + conf / 2.0))
    return math.tanh(z - crit * se), math.tanh(z + crit * se)


def _norm_ppf(p: float) -> float:
    """Inverse normal CDF, Acklam's rational approximation."""
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    pl, pu = 0.02425, 1 - 0.02425
    if p < pl:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > pu:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q, r = p - 0.5, (p - 0.5) ** 2
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
           (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


@dataclass
class CorrTable:
    kind: str                      # "market" | "fantasy"
    filt: CorrFilter
    entries: dict = field(default_factory=dict)
    skipped: list = field(default_factory=list)
    control: CorrEntry | None = None
    control_ok: bool = False
    control_why: str = ""

    @property
    def usable(self) -> bool:
        """A table whose control failed is not a table. Callers gate on this."""
        return self.control_ok and bool(self.entries)

    def report(self) -> str:
        L = [f"{self.kind.upper()} CORRELATION TABLE",
             f"  filter: {self.filt.describe()}"]
        if self.control is not None:
            # The control key is the TABLE's own, not a module-level literal.
            # This printed `CONTROL_KEY` — the position-keyed table's ('QB',
            # 'WR') — above a market-SIDE table whose control is
            # ('same','PASS','RECV'), so the report named a cell it had not
            # tested. A report that misnames its own gate is worse than one
            # that omits it.
            band = (MARKET_SIDE_CONTROL_BAND if self.kind == "market-side"
                    else CONTROL_BAND)
            L.append(f"  control {self.control.key}: r={self.control.r:+.4f} "
                     f"(band {band[0]:+.2f}..{band[1]:+.2f}) "
                     f"-> {'PASS' if self.control_ok else 'FAIL'}")
        if not self.control_ok:
            L.append(f"  !! {self.control_why}")
            L.append("  !! This table is NOT usable. Nothing below should be "
                     "shipped or quoted.")
        L.append("")
        for e in self.entries.values():
            L.append("  " + e.describe())
        for key, why in self.skipped:
            L.append(f"  {str(key):<22} NOT MEASURED — {why}")
        return "\n".join(L)

    def as_dict(self) -> dict:
        """Bare {key: r}, the shape the shipped constants use.

        Deliberately separate from `entries`: anything that takes this loses
        the interval and the n, so it is an explicit step rather than the
        default way to read the table.
        """
        return {k: e.r for k, e in self.entries.items()}


# ---------------------------------------------------------------------------

def _prepared(weekly: pd.DataFrame, filt: CorrFilter) -> pd.DataFrame:
    wk = weekly
    if filt.regular_season_only and "season_type" in wk.columns:
        wk = wk[wk.season_type == "REG"]
    wk = wk[wk.season.isin(filt.seasons)].copy()
    wk["game"] = (wk.season.astype(str) + "-" + wk.week.astype(str) + "-"
                  + wk[["team", "opponent_team"]].min(axis=1).astype(str)
                  + "-"
                  + wk[["team", "opponent_team"]].max(axis=1).astype(str))
    return wk


def _z(wk: pd.DataFrame, positions, col: str,
       filt: CorrFilter) -> pd.DataFrame:
    out = wk[wk.position.isin(list(positions))].copy()
    out["v"] = pd.to_numeric(out[col], errors="coerce").fillna(0)
    if filt.min_volume is not None:
        out = out[out.v >= filt.min_volume]
    g = out.groupby(["season", "player_id"])["v"]
    out["ng"], out["mu"], out["sd"] = (g.transform("size"), g.transform("mean"),
                                       g.transform("std"))
    out = out[(out.ng >= filt.min_games) & (out.sd > 0)].copy()
    out["z"] = (out.v - out.mu) / out.sd
    return out[["game", "team", "opponent_team", "player_id", "z"]]


def _pair_frames(a: pd.DataFrame, b: pd.DataFrame, *, same_team: bool,
                 same_pool: bool) -> pd.DataFrame:
    if same_team:
        m = a.merge(b, on=["game", "team"], suffixes=("", "_2"))
    else:
        m = a.merge(b, left_on=["game", "team"],
                    right_on=["game", "opponent_team"], suffixes=("", "_2"))
    m = m[m.player_id != m.player_id_2]
    if same_pool:
        # An unordered pair drawn from one pool would otherwise appear twice.
        m = m[m.player_id < m.player_id_2]
    return m


def _entry(key, m: pd.DataFrame, filt: CorrFilter):
    if len(m) < filt.min_pairs:
        return None, (f"only {len(m):,} pairs, under the {filt.min_pairs} "
                      f"floor — a correlation off fewer is an anecdote")
    r = float(np.corrcoef(m.z, m.z_2)[0, 1])
    if not np.isfinite(r):
        return None, "correlation is not finite — a side has no variance"
    lo, hi = fisher_ci(r, len(m))
    return CorrEntry(key, r, len(m), lo, hi), ""


def market_table(weekly: pd.DataFrame,
                 filt: CorrFilter = DEFAULT_FILTER) -> CorrTable:
    """Position-pair correlations measured on MARKET stats.

    This is `ff_boost`'s quantity: QB passing yards against RB rushing yards,
    not fantasy points. `("QB","RB_RECV")` is the pair B67 was filed for — a
    back with a RECEIVING prop, which the code scored at the WR value until
    it was split out.
    """
    wk = _prepared(weekly, filt)
    t = CorrTable("market", filt)
    for pa, pb, ca, cb, same_team in MARKET_POSITION_PAIRS:
        posa = ("RB",) if pa == "RB_RECV" else SIDE_STAT.get(
            {"QB": "PASS", "RB": "RUSH"}.get(pa, "RECV"), ((pa,), ""))[0]
        posa = (pa,) if pa in ("QB", "RB", "WR", "TE") else ("RB",)
        posb = (pb,) if pb in ("QB", "RB", "WR", "TE") else ("RB",)
        a = _z(wk, posa, ca, filt)
        b = _z(wk, posb, cb, filt)
        m = _pair_frames(a, b, same_team=same_team,
                         same_pool=(posa == posb and ca == cb))
        e, why = _entry((pa, pb), m, filt)
        if e is None:
            t.skipped.append(((pa, pb), why))
        else:
            t.entries[(pa, pb)] = e
    c = t.entries.get(CONTROL_KEY)
    t.control = c
    if c is None:
        t.control_ok, t.control_why = False, (
            f"the control pair {CONTROL_KEY} did not measure at all")
    elif not CONTROL_BAND[0] <= c.r <= CONTROL_BAND[1]:
        t.control_ok, t.control_why = False, (
            f"control {CONTROL_KEY} came out {c.r:+.4f}, outside "
            f"{CONTROL_BAND[0]:+.2f}..{CONTROL_BAND[1]:+.2f} — this method "
            f"does not reproduce a pair the shipped table claims to know, so "
            f"nothing else it produces is admissible")
    else:
        t.control_ok, t.control_why = True, "control recovered"
    return t


# ---------------------------------------------------------------------------
# F13 — the market SIDES, which is what `_pair_r` actually resolves on
# ---------------------------------------------------------------------------
#
# `ff_boost.MARKET_SIDE` maps exactly three markets to three sides, and every
# other market in a same-event slip returns (None, why) and makes the slip
# UNPRICEABLE. That is the correct answer — independence there would be an
# assumption — but it refuses slip shapes Dustin actually bets, receptions
# legs above all.
#
# Adding a market means either mapping it to a side already measured, or
# adding a side and measuring every pair it forms. Mapping `player_receptions`
# onto RECV would be the former and is NOT done: receptions and receiving
# yards are a different stat, and their correlation with a quarterback's
# passing yards is a different number. Assuming they match is the kind of
# unmeasured equivalence this whole module exists to stop.
#
# TD is BINARY, which the backlog flagged as not transferring. It transfers:
# Pearson on a per-player-season z-scored 0/1 is a base-rate-adjusted phi,
# which is the right statistic and the same arithmetic. What does NOT
# transfer is the joint-crossing LIFT, which needs a threshold.
SIDE_SPEC = {
    "PASS":       (("QB",),             "passing_yards",    False),
    "RUSH":       (("RB",),             "rushing_yards",    False),
    "RECV":       (("WR", "TE"),        "receiving_yards",  False),
    "RECEPTIONS": (("WR", "TE", "RB"),  "receptions",       False),
    "PASS_TD":    (("QB",),             "passing_tds",      False),
    "TD":         (("QB", "RB", "WR", "TE"), "_anytime_td",  True),
}

#: Sides `ff_boost.MARKET_SIDE` already maps. The rest are what F13 adds.
SIDES_SHIPPED = ("PASS", "RUSH", "RECV")

MARKET_SIDE_CONTROL = ("same", "PASS", "RECV")
MARKET_SIDE_CONTROL_BAND = (0.18, 0.40)


def _with_derived(wk: pd.DataFrame) -> pd.DataFrame:
    """Add the columns no single nflverse field provides."""
    out = wk.copy()
    rec = pd.to_numeric(out.get("receiving_tds"), errors="coerce").fillna(0)
    rush = pd.to_numeric(out.get("rushing_tds"), errors="coerce").fillna(0)
    # Anytime TD as the market settles it: receiving OR rushing, not special
    # teams and not a defensive score, neither of which the prop pays.
    out["_anytime_td"] = ((rec + rush) > 0).astype(float)
    return out


def market_side_table(weekly: pd.DataFrame,
                      filt: CorrFilter = DEFAULT_FILTER,
                      sides=None) -> CorrTable:
    """Every (relation, side, side) cell, including the sides F13 needs.

    Keyed `(relation, side_a, side_b)` with the sides SORTED, matching
    `ff_boost.MEASURED_PAIR_LIFT`'s key shape so the two can be compared
    without a translation step.
    """
    wk = _with_derived(_prepared(weekly, filt))
    use = tuple(sides) if sides else tuple(SIDE_SPEC)
    t = CorrTable("market-side", filt)
    frames = {}
    for sd in use:
        pos, col, _binary = SIDE_SPEC[sd]
        if col not in wk.columns:
            t.skipped.append(((sd,), f"no {col!r} column in this frame"))
            continue
        frames[sd] = _z(wk, pos, col, filt)
    names = [sd for sd in use if sd in frames]
    for i, sa in enumerate(names):
        for sb in names[i:]:
            for rel in ("same", "opp"):
                key = (rel, *sorted((sa, sb)))
                if key in t.entries or any(k == key for k, _ in t.skipped):
                    continue
                m = _pair_frames(frames[sa], frames[sb],
                                 same_team=(rel == "same"),
                                 same_pool=(sa == sb))
                e, why = _entry(key, m, filt)
                if e is None:
                    t.skipped.append((key, why))
                else:
                    t.entries[key] = e
    c = t.entries.get(MARKET_SIDE_CONTROL)
    t.control = c
    lo, hi = MARKET_SIDE_CONTROL_BAND
    if c is None:
        t.control_ok, t.control_why = False, (
            f"the control cell {MARKET_SIDE_CONTROL} did not measure")
    elif not lo <= c.r <= hi:
        t.control_ok, t.control_why = False, (
            f"control {MARKET_SIDE_CONTROL} came out {c.r:+.4f}, outside "
            f"{lo:+.2f}..{hi:+.2f} — this method does not reproduce a pair "
            f"the shipped table claims to know")
    else:
        t.control_ok, t.control_why = True, "control recovered"
    return t


FANTASY_PAIRS = (
    ("QB", "WR", True), ("QB", "TE", True), ("QB", "RB", True),
    ("RB", "RB", False), ("WR", "WR", True), ("QB", "QB", False),
)


def fantasy_table(weekly: pd.DataFrame, points_col: str = "fantasy_points",
                  filt: CorrFilter = DEFAULT_FILTER) -> CorrTable:
    """Position-pair correlations measured on FANTASY POINTS.

    `ff_guillotine`'s quantity. It correlates total scores — receptions and
    touchdowns included — and the market table is simply the wrong number
    there. For QB x RB it is the wrong SIGN: the game-script drag that makes
    passing yards trade against rushing yards does not survive into points,
    because touchdowns are upside both players share.

    The control band does not apply to this table — it is calibrated to the
    market quantity — so this one reports its control for reference and does
    not gate on it.
    """
    wk = _prepared(weekly, filt)
    if points_col not in wk.columns:
        t = CorrTable("fantasy", filt)
        t.control_ok, t.control_why = False, (
            f"no {points_col!r} column in this frame — pass the column your "
            f"scoring produced, or score the frame first")
        return t
    t = CorrTable("fantasy", filt)
    for pa, pb, same_team in FANTASY_PAIRS:
        a = _z(wk, (pa,), points_col, filt)
        b = _z(wk, (pb,), points_col, filt)
        m = _pair_frames(a, b, same_team=same_team, same_pool=(pa == pb))
        e, why = _entry((pa, pb), m, filt)
        if e is None:
            t.skipped.append(((pa, pb), why))
        else:
            t.entries[(pa, pb)] = e
    t.control = t.entries.get(CONTROL_KEY)
    t.control_ok = bool(t.entries)
    t.control_why = ("the market control band does not apply to a "
                     "fantasy-points table and is not gated on here")
    return t


def compare_to_shipped(table: CorrTable, shipped: dict) -> str:
    """What would change if this table replaced the shipped constants.

    Printed rather than applied. Swapping `ff_boost.SAME_TEAM_CORR` gates
    whether a slip gets an EV at all, so it is a person's decision.
    """
    L = ["WHAT WOULD CHANGE", f"  {'pair':<14}{'shipped':>9}{'measured':>10}"
                              f"{'delta':>9}{'shipped in CI?':>16}"]
    for key, e in table.entries.items():
        old = shipped.get(key)
        if old is None:
            L.append(f"  {str(key):<14}{'—':>9}{e.r:>+10.3f}{'new':>9}"
                     f"{'—':>16}")
            continue
        inside = e.lo <= old <= e.hi
        L.append(f"  {str(key):<14}{old:>+9.2f}{e.r:>+10.3f}"
                 f"{e.r - old:>+9.3f}{('yes' if inside else 'NO'):>16}")
    missing = [k for k in shipped if k not in table.entries]
    for k in missing:
        L.append(f"  {str(k):<14}{shipped[k]:>+9.2f}{'—':>10}"
                 f"{'NOT MEASURED':>9}{'—':>16}")
    L.append("")
    L.append("  Nothing above has been applied. `ff_boost`'s table gates "
             "whether a slip")
    L.append("  gets an EV at all, so changing it is a live behaviour change "
             "and needs")
    L.append("  a person to sign it off.")
    return "\n".join(L)


def main() -> None:
    from ff_data import load_weekly
    from ff_scoring import LEAGUES, score
    import ff_boost

    wk = load_weekly(list(DEFAULT_FILTER.seasons))
    mt = market_table(wk)
    print(mt.report())
    print()
    shipped = dict(ff_boost.SAME_TEAM_CORR)
    shipped.update({("RB", "RB"): ff_boost.OPPOSING_CORR[("RB", "RB")]})
    shipped.update(getattr(ff_boost, "SAME_TEAM_CORR_PROVISIONAL", {}))
    print(compare_to_shipped(mt, shipped))
    print()
    # `score()` returns a Series for ONE league; the guillotine's own scoring
    # is the one this table is for, so it is the one used. Scored off a
    # `prepare`d frame because the explosive-TD bonuses raise otherwise
    # rather than quietly undercounting.
    try:
        from ff_data import load_pbp
        from ff_scoring import prepare
        full = prepare(wk, load_pbp(list(DEFAULT_FILTER.seasons)))
        full = full.copy()
        full["gpts"] = score(full, LEAGUES["guillotine"])
        ft = fantasy_table(full, "gpts")
    except Exception as exc:                                 # noqa: BLE001
        print(f"FANTASY TABLE NOT BUILT: {type(exc).__name__}: {exc}")
        return
    print(ft.report())
    print()
    print(compare_to_shipped(
        ft, {("QB", "WR"): 0.31, ("QB", "TE"): 0.27, ("QB", "RB"): -0.10,
             ("RB", "RB"): -0.14}))
    print("  (the four above are the MARKET numbers ff_guillotine currently "
          "duplicates;")
    print("   they are the wrong quantity for a fantasy-points table, which "
          "is the point.)")


if __name__ == "__main__":
    main()
