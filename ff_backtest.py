"""Backtest the boost-slip strategy (F2) — falsification first, logic second.

WHY THIS FILE OPENS WITH THE FALSIFICATION CRITERIA

Seven rounds of deployment testing produced a clear pattern: not one defect in
this project was arithmetic. Every one was either a claim nobody verified or a
fixture that did not match reality. A backtest is made entirely of both — it is
historical fixtures plus causal claims about what made money — and the boost
optimiser that comes next will act on its output. So the checks that would
catch a flattering result are written before the code that could produce one.

THE CENTRAL FALSIFICATION

Under boost-chasing the model's job is vetoing broken legs, not selecting
winners. So a HONEST backtest should show:

    realised hit rate  ~=  the no-vig implied probability of the slip

and all the profit coming from the boost. If the realised hit rate runs
materially ABOVE the no-vig implied probability, that is not an edge — it means
information leaked from after the bet was placed. The three usual leaks:

  * closing prices used as if they were available pre-game,
  * legs chosen with any knowledge of the result,
  * ungraded slips dropped, when the ones that fail to grade are systematically
    different from the ones that do (a scratched player is a LOSS, not a
    missing row).

A backtest that reports an edge on leg SELECTION is making a claim this
project has already measured as false: the model is 0-for-2 when it disagreed
with a sharp line, and both of those were role changes.

WHAT GRADES WHAT

  Prices  -> PropLine `get_odds_history`, pre-game snapshots only.
  Results -> nflverse weekly stats, locally. PropLine's graded-results
             endpoint is Pro tier, and the local stats are the ground truth a
             prop settles against anyway: already validated exact across
             25,987 player-weeks.
  Join    -> ESPN id to GSIS id via the roster crosswalk, NEVER on a name.
             Three separate name-matching bugs have shipped in this project.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ff_data import ensure_deps

ensure_deps("pyarrow", "scipy")


# ---------------------------------------------------------------------------
# Market -> stat, and how a leg settles
# ---------------------------------------------------------------------------

# A prop settles against one stat. `player_anytime_td` is the exception: it is
# any TD, so rushing and receiving are summed (passing TDs do not count — a QB
# throwing one has not scored).
MARKET_STAT = {
    "player_pass_yds": ("passing_yards",),
    "player_rush_yds": ("rushing_yards",),
    "player_reception_yds": ("receiving_yards",),
    "player_receptions": ("receptions",),
    "player_pass_tds": ("passing_tds",),
    "player_anytime_td": ("rushing_tds", "receiving_tds"),
}

# Anytime-TD has no line in the feed (`point: null`); it settles at 1+.
IMPLICIT_LINE = {"player_anytime_td": 0.5}


@dataclass
class Leg:
    """One historical leg: the price that was available, and how it settled."""
    week: int
    event_id: str
    book: str
    market: str
    player: str
    propline_player_id: str | None
    gsis_id: str | None
    line: float | None
    side: str                      # OVER / UNDER / YES
    odds: float                    # American, as available PRE-GAME
    quoted_at: str                 # snapshot timestamp of that price
    commence_time: str
    # The two nflverse team codes in this event, e.g. ("PIT", "IND"). Supply
    # it whenever you can: it is the only check that catches a WRONG BUT
    # VALID player id. A fabricated "espn:4241478" resolved to DeVonta Smith
    # (PHI) instead of Jaylen Warren (PIT); Smith had no row that week, so
    # the pipeline returned a plausible "did not play" rather than an error —
    # the B24/B28 signature again. With the event's teams known, a player
    # from neither team is caught immediately.
    event_teams: tuple[str, str] | None = None
    # Filled by grading.
    actual: float | None = None
    result: str | None = None      # WIN / LOSS / PUSH / UNGRADED
    ungraded_reason: str | None = None


@dataclass
class Slip:
    """A candidate boost slip."""
    week: int
    legs: list[Leg]
    slip_odds: float               # American, the correlated SGP price
    boost_pct: float
    stake: float = 10.0
    # Filled by grading.
    result: str | None = None
    payout: float | None = None


# ---------------------------------------------------------------------------
# Odds helpers (local, so this module needs no other import to be testable)
# ---------------------------------------------------------------------------

def to_decimal(american: float) -> float:
    a = float(american)
    return 1.0 + (a / 100.0 if a > 0 else 100.0 / abs(a))


def implied(american: float) -> float:
    return 1.0 / to_decimal(american)


def boosted_return(stake: float, slip_odds: float, boost_pct: float) -> float:
    """Total returned on a win, with the boost applied to PROFIT."""
    d = to_decimal(slip_odds)
    return stake + stake * (d - 1.0) * (1.0 + boost_pct)


def breakeven_p(slip_odds: float, boost_pct: float) -> float:
    """The win probability a boosted slip needs to break even.

    This is the number the whole strategy rests on: a +300 slip needs 25% to
    break even unboosted, but only 20.4% with a 30% profit boost. The gap
    between those two is the entire edge, and it does not depend on picking
    winners.
    """
    d = to_decimal(slip_odds)
    return 1.0 / (1.0 + (d - 1.0) * (1.0 + boost_pct))


# MEASURED 2026-11-02, not guessed. 12 priced 3-leg combinations, 2 events,
# DraftKings and FanDuel. The earlier guess of (8%, 20%) was badly optimistic:
# 8% was not attained by a single slip, and the lowest compounded leg vig
# observed was 17.7%.
#
# And it is not ONE number — structure matters more than price does:
#
#   CROSS-GAME (SGPx): hold 18.6% median, range 17.7-20.9%. This is just the
#     per-leg vig compounded, and it is EXACT for cross-game, because the
#     measured correlation table says cross-game legs are independent, so no
#     correlation model is needed. Confirmed against price_parlay.
#
#   SAME-GAME, independent legs (three receivers, say): hold 30.2% median,
#     range 23.1-37.2%. The extra ~12 points is the book haircutting legs
#     that are NOT actually correlated — you pay for correlation that does
#     not exist.
#
#   SAME-GAME, correlated (a QB stack): NOT MEASURABLE this way. The book's
#     price implies the true joint is 1.8-1.95x the independent product, and
#     whether QB-WR at +0.31 delivers that on a ~12.6% three-way tail needs a
#     joint model this project does not have. The apparent "hold" of 80-95%
#     on those slips is mostly real correlation, not margin. Do not quote it.
#
# Corroboration: the books' own correlation_factor tracked the measured
# correlation table closely — 0.61-0.65 on QB stacks, 0.87-0.96 on
# receiver-only slips, and ABOVE 1.0 on opposing RBs, i.e. the book paying
# for the -0.14 anti-correlation.
SGP_HOLD_CROSS_GAME = (0.177, 0.209)
SGP_HOLD_SAME_GAME = (0.231, 0.372)

# Kept for callers that do not know the slip's structure. Deliberately the
# SAME-GAME band, because assuming the cheaper product when you do not know
# which you have is the error that loses money.
SGP_HOLD_BAND = SGP_HOLD_SAME_GAME


def hold_band(cross_game: bool | None = None) -> tuple[float, float]:
    """The measured hold band for a slip of this structure.

    `cross_game=None` means unknown, and returns the same-game band — the
    pessimistic one. Guessing the cheaper product is how you talk yourself
    into a slip that is not +EV.
    """
    return SGP_HOLD_CROSS_GAME if cross_game else SGP_HOLD_SAME_GAME


def expected_roi(slip_odds: float, boost_pct: float,
                 sgp_hold: float) -> float:
    """ROI to expect from a FAIRLY-PLAYED slip, given the book's hold.

    This exists so nobody reads the no-hold number as a target. A +300 slip
    with a 30% boost returns +22.5% **if its true probability equals its
    offered implied probability** — that is, if the book takes nothing. Books
    do take something: the offered price already embeds the hold, so the true
    probability is lower and the real expectation is much smaller.

        p_true = implied(offered) / (1 + hold)
        ROI    = p_true * (d - 1) * (1 + boost) - (1 - p_true)

    Use `roi_band()` for the range to expect across plausible holds. A
    backtest landing above that band is not good news; it is a reason to check
    the grading.
    """
    d = to_decimal(slip_odds)
    p = implied(slip_odds) / (1.0 + sgp_hold)
    return p * (d - 1.0) * (1.0 + boost_pct) - (1.0 - p)


def roi_band(slip_odds: float, boost_pct: float,
             cross_game: bool | None = None) -> tuple[float, float]:
    """(pessimistic, optimistic) ROI across the measured hold band."""
    band = hold_band(cross_game)
    return (expected_roi(slip_odds, boost_pct, band[1]),
            expected_roi(slip_odds, boost_pct, band[0]))


def min_boost(slip_odds: float, cross_game: bool | None = None,
              step: float = 0.005) -> float:
    """The smallest boost that makes this slip +EV at the measured hold.

    Measured answers: a +300 cross-game SGPx needs about 25%; the same slip
    built same-game needs about 40%. Structure is worth ~15 points of boost,
    which makes "prefer SGPx" the main lever rather than a tidiness
    preference.
    """
    b = 0.0
    while b <= 2.0:
        if expected_roi(slip_odds, b, hold_band(cross_game)[1]) > 0:
            return b
        b += step
    return float("nan")


# ---------------------------------------------------------------------------
# FALSIFICATION — written before the backtest logic, on purpose
# ---------------------------------------------------------------------------

# A realised hit rate this many standard errors above the no-vig implied
# probability is treated as leakage, not edge.
LEAK_SIGMA = 2.0

# Hard tripwire. Nothing in this strategy can plausibly return this much; a
# figure above it is a bug being reported as a finding.
IMPLAUSIBLE_ROI = 0.40

# Above this share of ungraded legs the sample is not trustworthy, because what
# fails to grade (scratches, inactives) is not random.
MAX_UNGRADED = 0.05


@dataclass
class Audit:
    """What the falsification checks found. `ok` False means do not report the
    backtest's headline numbers as a result."""
    ok: bool = True
    failures: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    n_slips: int = 0
    n_graded: int = 0
    n_clusters: int = 0
    hit_rate: float = float("nan")
    hit_rate_se: float = float("nan")
    implied_mean: float = float("nan")
    roi: float = float("nan")
    roi_unboosted: float = float("nan")

    def fail(self, why: str) -> None:
        self.ok = False
        self.failures.append(why)

    def describe(self) -> str:
        L = [f"AUDIT — {'PASS' if self.ok else 'DO NOT TRUST THIS BACKTEST'}"]
        L.append(f"  slips {self.n_slips}, graded {self.n_graded}, "
                 f"distinct events {self.n_clusters}")
        if self.n_graded:
            L.append(f"  hit rate   {self.hit_rate:.1%} +/- "
                     f"{self.hit_rate_se:.1%}   (no-vig implied "
                     f"{self.implied_mean:.1%})")
            L.append(f"  ROI        {self.roi:+.1%} boosted, "
                     f"{self.roi_unboosted:+.1%} unboosted")
        for f in self.failures:
            L.append(f"  FAIL  {f}")
        for n in self.notes:
            L.append(f"  note  {n}")
        if self.ok and self.n_graded:
            L.append("  The profit, if any, is attributable to the boost "
                     "rather than to leg selection — which is what this "
                     "strategy claims and all it should ever show.")
        return "\n".join(L)


def audit(slips: list[Slip], fair_implied: list[float] | None = None) -> Audit:
    """Run every falsification check. Call this BEFORE quoting any result.

    `fair_implied` is the no-vig probability of each slip, when available from
    a sharp anchor. Without it the book's own implied probability is used,
    which is conservative in the wrong direction (it includes the hold, so it
    OVERstates the probability and makes leakage harder to see) — so that
    substitution is reported as a note, not passed over.
    """
    a = Audit(n_slips=len(slips))
    if not slips:
        a.fail("no slips — nothing was backtested")
        return a

    graded = [s for s in slips if s.result in ("WIN", "LOSS")]
    a.n_graded = len(graded)

    # 0. The wrong-id guard can only fire when the event's teams are known,
    #    and without it a wrong id grades as a NORMAL WIN OR LOSS. Measured:
    #    a fabricated id resolved to DeVonta Smith, who played and cleared
    #    the line, so the leg graded WIN — a wrong answer with no trace. At
    #    backtest scale that is a systematic hole, not an edge case.
    no_teams = [l for s in slips for l in s.legs if not l.event_teams]
    if no_teams:
        share_nt = len(no_teams) / max(len([l for s in slips for l in s.legs]), 1)
        msg = (f"{len(no_teams)} leg(s) ({share_nt:.0%}) carry no "
               f"`event_teams`, so a wrong player_id cannot be detected — it "
               f"would grade as an ordinary win or loss. Supply the event's "
               f"two nflverse team codes on every leg.")
        if share_nt > 0.10:
            a.fail(msg)
        else:
            a.notes.append(msg)

    # 1. Lookahead. Every price must predate its own kickoff.
    late = [(s.week, l.player, l.quoted_at, l.commence_time)
            for s in slips for l in s.legs
            if l.quoted_at and l.commence_time and l.quoted_at >= l.commence_time]
    if late:
        a.fail(f"{len(late)} leg(s) priced at or after kickoff — that price "
               f"was not available when the bet would have been placed. "
               f"First: {late[0]}")

    # 2. Survivorship. What failed to grade is not random: a scratch is a
    #    LOSS, and silently dropping it inflates the hit rate.
    legs = [l for s in slips for l in s.legs]
    ung = [l for l in legs if l.result not in ("WIN", "LOSS", "PUSH")]
    share = len(ung) / len(legs) if legs else 0.0
    if share > MAX_UNGRADED:
        reasons: dict[str, int] = {}
        for l in ung:
            reasons[l.ungraded_reason or "unknown"] = \
                reasons.get(l.ungraded_reason or "unknown", 0) + 1
        a.fail(f"{share:.1%} of legs could not be graded (limit "
               f"{MAX_UNGRADED:.0%}): {reasons}. A player who did not play is "
               f"a LOSS, not a missing row — dropping these inflates the hit "
               f"rate.")
    elif ung:
        a.notes.append(f"{len(ung)} ungraded leg(s), {share:.1%} — under the "
                       f"limit, but they are counted as losses, not dropped")

    if not graded:
        a.fail("no slip graded WIN or LOSS — there is no result to report")
        return a

    # 3. THE CENTRAL CHECK: profit must come from the boost, not the hit rate.
    wins = sum(1 for s in graded if s.result == "WIN")
    a.hit_rate = wins / len(graded)

    # CLUSTERED, not independent. Slips built from the same game share legs
    # and share game script: if the game goes under, every total-based leg in
    # every slip from that game fails together. Treating them as independent
    # understates the error bar by roughly sqrt(slips per event), which would
    # make a noise result look significant — the exact error this audit exists
    # to catch, committed by the audit itself.
    #
    # The conservative unit is the EVENT. With slips spread over few events,
    # the effective sample size is closer to the event count than the slip
    # count, so the se is computed on whichever is smaller.
    ev = {l.event_id for s in graded for l in s.legs}
    a.n_clusters = len(ev)
    n_eff = min(len(graded), max(a.n_clusters, 1))

    # AGRESTI-COULL, not the raw binomial. At a 0% or 100% hit rate the plain
    # binomial se is exactly zero, so the audit claimed PERFECT resolution
    # from the least informative sample possible: two slips, both losses,
    # printed "2 se on the hit rate is 0.0%" and "resolving 1 point needs ~0
    # slips". That is the B33 error — noise read as signal — committed inside
    # the audit's own noise reporting. Adding two notional successes and two
    # failures keeps the interval finite at the boundaries, which is what the
    # estimator is for.
    # Computed on the FULL sample, then inflated by the design effect
    # sqrt(n / n_eff) for clustering. An earlier version divided `wins` (a
    # count over all slips) by `n_eff` (a count of events), which mixes
    # scales: 25 wins over 1 cluster gave p_adj = 5.4 and a math domain
    # error on sqrt of a negative.
    n_full = len(graded)
    p_adj = (wins + 2.0) / (n_full + 4.0)
    se_full = math.sqrt(p_adj * (1.0 - p_adj) / (n_full + 4.0))
    a.hit_rate_se = se_full * math.sqrt(n_full / max(n_eff, 1))
    if a.n_clusters < len(graded):
        a.notes.append(f"{len(graded)} slips but only {a.n_clusters} distinct "
                       f"event(s) — slips from one game are correlated, so "
                       f"the error bar uses {n_eff} effective observations, "
                       f"not {len(graded)}")
    if fair_implied is None:
        a.implied_mean = float(np.mean([implied(s.slip_odds) for s in graded]))
        a.notes.append("no sharp anchor supplied, so the book's own implied "
                       "probability is the comparison — it includes the hold, "
                       "so it OVERSTATES the true probability and makes "
                       "leakage HARDER to detect, not easier")
    else:
        a.implied_mean = float(np.mean(fair_implied))

    excess = a.hit_rate - a.implied_mean
    if a.hit_rate_se > 0 and excess > LEAK_SIGMA * a.hit_rate_se:
        a.fail(f"hit rate {a.hit_rate:.1%} exceeds the implied probability "
               f"{a.implied_mean:.1%} by {excess/a.hit_rate_se:.1f} se. This "
               f"strategy does not claim an edge on leg SELECTION — the model "
               f"is 0-for-2 against sharp lines. An excess this large means "
               f"information leaked from after the bet: closing prices used "
               f"as pre-game, result-aware leg choice, or dropped losers.")

    # 4. Economics, boosted and not. The unboosted figure is the control: it
    #    should be negative, because the hold is real.
    staked = sum(s.stake for s in graded)
    ret = sum(boosted_return(s.stake, s.slip_odds, s.boost_pct)
              if s.result == "WIN" else 0.0 for s in graded)
    ret_nb = sum(boosted_return(s.stake, s.slip_odds, 0.0)
                 if s.result == "WIN" else 0.0 for s in graded)
    a.roi = (ret - staked) / staked if staked else float("nan")
    a.roi_unboosted = (ret_nb - staked) / staked if staked else float("nan")

    # Compare against what the boost can actually produce once the book's
    # hold is accounted for. Landing above the band is a reason to re-check
    # the grading, not a finding.
    bands = [roi_band(s.slip_odds, s.boost_pct) for s in graded]
    band_lo = float(np.mean([b[0] for b in bands]))
    band_hi = float(np.mean([b[1] for b in bands]))
    a.notes.append(f"expected ROI band for these slips, after SGP hold of "
                   f"{SGP_HOLD_BAND[0]:.0%}-{SGP_HOLD_BAND[1]:.0%}: "
                   f"{band_lo:+.1%} to {band_hi:+.1%}")
    if a.n_graded and a.roi > band_hi + 2 * a.hit_rate_se * 4:
        a.notes.append(f"realised ROI {a.roi:+.1%} is above the top of that "
                       f"band — possible, but check the grading before "
                       f"believing it")

    if a.roi > IMPLAUSIBLE_ROI:
        a.fail(f"ROI {a.roi:+.1%} is above the {IMPLAUSIBLE_ROI:.0%} "
               f"plausibility ceiling on {len(graded)} slips. A boost of this "
               f"size against fairly-priced slips cannot produce that. Treat "
               f"it as a bug until the leg-by-leg grading has been checked by "
               f"hand.")
    if a.roi_unboosted > 0:
        a.notes.append(f"unboosted ROI is {a.roi_unboosted:+.1%}, i.e. "
                       f"POSITIVE without the boost. That implies beating the "
                       f"book's hold on leg selection, which nothing here "
                       f"claims — check for leakage even though the hit-rate "
                       f"test passed")

    # 5. Noise floor. The lesson from quoting a 20k-sim figure as a
    #    measurement: say what the sample can and cannot resolve.
    two_se = 2 * a.hit_rate_se
    # Sized off the ADJUSTED rate, so a degenerate sample cannot claim
    # perfect resolution.
    need = int(math.ceil(4.0 * p_adj * (1.0 - p_adj) / 0.01 ** 2))
    a.notes.append(f"2 se on the hit rate is {two_se:.1%} over {n_eff} "
                   f"effective observation(s); do not read any difference "
                   f"smaller than that as real. Resolving 1 point needs "
                   f"~{need:,} independent slips.")
    if n_eff < 30:
        a.notes.append(f"{n_eff} effective observation(s) is too few to "
                       f"measure anything about profitability — this sample "
                       f"can only catch a pipeline fault, not an edge")
    return a


# ---------------------------------------------------------------------------
# Player resolution — by id, never by name
# ---------------------------------------------------------------------------

def espn_to_gsis(roster: pd.DataFrame) -> dict[str, str]:
    """{espn_id: gsis_id} from the nflverse roster crosswalk.

    PropLine ships `player_id` as "espn:3139477"; nflverse keys everything on
    GSIS. This is the only join between them that does not go through a name.
    Measured on the live feed: 8 of 8 sampled PropLine ids resolved.
    """
    if "espn_id" not in roster.columns or "gsis_id" not in roster.columns:
        raise ValueError("roster is missing espn_id/gsis_id — the crosswalk "
                         "is what makes id-based grading possible, and "
                         "without it grading would fall back to names, which "
                         "this project has already shipped three bugs on")
    r = roster[roster.espn_id.notna() & roster.gsis_id.notna()]
    keys = (r.espn_id.astype(str).str.replace(r"\.0$", "", regex=True))
    return dict(zip(keys, r.gsis_id.astype(str)))


def resolve_gsis(propline_player_id: str | None,
                 crosswalk: dict[str, str]) -> str | None:
    """"espn:3139477" -> GSIS id, or None. Never guesses from a name."""
    if not propline_player_id:
        return None
    raw = str(propline_player_id)
    key = raw.split(":", 1)[1] if ":" in raw else raw
    return crosswalk.get(key)


# ---------------------------------------------------------------------------
# Grading, against local nflverse stats
# ---------------------------------------------------------------------------

def _rows(weekly: pd.DataFrame, gsis_id: str, week: int) -> pd.DataFrame:
    return weekly[(weekly.player_id == gsis_id) & (weekly.week == week)]


def _actual(rows: pd.DataFrame, market: str) -> float | None:
    cols = MARKET_STAT.get(market)
    if not cols or rows.empty:
        return None
    total = 0.0
    for c in cols:
        if c not in rows.columns:
            return None
        total += float(pd.to_numeric(rows[c], errors="coerce").fillna(0).sum())
    return total


def grade_leg(leg: Leg, weekly: pd.DataFrame) -> Leg:
    """Settle one leg against the actual stat. Mutates and returns the leg.

    A leg that cannot be graded is marked UNGRADED with a reason and is
    counted as a LOSS by the slip grader — never dropped. A player who did
    not play did not clear his line.
    """
    if leg.gsis_id is None:
        leg.result, leg.ungraded_reason = "UNGRADED", "no gsis_id (id join failed)"
        return leg
    if leg.market not in MARKET_STAT:
        leg.result, leg.ungraded_reason = "UNGRADED", f"unknown market {leg.market}"
        return leg

    line = leg.line if leg.line is not None else IMPLICIT_LINE.get(leg.market)
    if line is None:
        leg.result, leg.ungraded_reason = "UNGRADED", "no line and no implicit line"
        return leg

    rows = _rows(weekly, leg.gsis_id, leg.week)

    # WRONG-ID GUARD. Checked before the "did not play" branch, because a
    # wrong id usually LOOKS like a player who did not play — which is a
    # plausible answer, and therefore the dangerous one.
    if leg.event_teams and not rows.empty and "team" in rows.columns:
        teams = {str(t) for t in rows.team.unique()}
        if not (teams & set(leg.event_teams)):
            leg.result = "UNGRADED"
            leg.ungraded_reason = (
                f"id resolves to a player on {sorted(teams)}, who is not in "
                f"this event ({' vs '.join(leg.event_teams)}) — "
                f"player_id {leg.propline_player_id!r} is probably wrong")
            return leg

    actual = _actual(rows, leg.market)
    if actual is None:
        leg.result = "UNGRADED"
        reason = "no stat row for that player-week (did not play)"
        if leg.event_teams:
            reason += (" — note a WRONG player_id also looks like this when "
                       "the wrong player also sat; the team check above only "
                       "fires when he played")
        leg.ungraded_reason = reason
        return leg

    leg.actual = actual
    side = leg.side.upper()
    if side in ("OVER", "YES"):
        leg.result = "WIN" if actual > line else ("PUSH" if actual == line else "LOSS")
    elif side in ("UNDER", "NO"):
        leg.result = "WIN" if actual < line else ("PUSH" if actual == line else "LOSS")
    else:
        leg.result, leg.ungraded_reason = "UNGRADED", f"unknown side {leg.side}"
    return leg


def grade_slip(slip: Slip, weekly: pd.DataFrame) -> Slip:
    """Settle every leg, then the slip. A parlay needs every leg to win.

    UNGRADED legs count as losses. That is deliberate: the alternative is
    dropping the slip, and what fails to grade is dominated by players who did
    not play — which is a loss in reality and a silent hit-rate boost if
    excluded.
    """
    for leg in slip.legs:
        grade_leg(leg, weekly)
    results = [l.result for l in slip.legs]
    if all(r == "PUSH" for r in results):
        slip.result, slip.payout = "PUSH", slip.stake
    elif all(r in ("WIN", "PUSH") for r in results):
        slip.result = "WIN"
        slip.payout = boosted_return(slip.stake, slip.slip_odds, slip.boost_pct)
    else:
        slip.result, slip.payout = "LOSS", 0.0
    return slip
