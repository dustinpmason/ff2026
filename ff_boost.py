"""P0 — the boost-slip optimiser.

Built against test_boost.py, which was written first. Read that file for the
criteria; this docstring covers only what the design commits to and why.

WHAT THIS MODULE IS FOR
-----------------------
The betting objective is exploiting profit boosts: 3+ legs, +300 or better,
$10 max, maximising P(cash) subject to the odds floor. The boost IS the edge
— leg selection is not. So this module does not pick legs on merit. It
enumerates slips that clear the floor, vetoes legs that are broken, and
reports what each slip is actually worth against the measured hold.

IT DOES NOT FETCH ANYTHING. The sandbox has no network access to PropLine
and the MCP tools belong to the session, not to Python. Every function here
takes payloads that the session has already pulled — the same shape as
flatten_odds(). The documented call sequence is at the bottom of this
docstring.

THE THREE STRUCTURES, AND WHY THEY ARE NOT INTERCHANGEABLE
----------------------------------------------------------
Measured 2026-11-02:

  cross-game (SGPx)            hold 17.7-20.9%   needs ~28% boost at +300
  same-game, independent legs  hold 23.1-37.2%   needs ~50% boost at +300
  same-game, correlated        NOT MEASURABLE

Structure is worth roughly 22 points of boost, so it is the primary lever.
Cross-game is the default for that reason, and because its fair joint is the
product of the de-vigged legs — the measured correlation table puts
cross-game pairs at ~0.00 — which makes P(cash) a real number rather than an
estimate.

A correlated same-game slip gets no EV and no P(cash). The book's price
implies a true joint of 1.8-1.95x the independent product, and whether
QB-WR at +0.31 delivers that on a ~12.6% three-way tail needs a joint model
this project does not have. It is returned with its price, its payout and
the book's factor against the measured table, and nothing else. Unpriceable
is not the same as bad: the 30.2% same-game figure was measured on
INDEPENDENT legs and is not a verdict on a stack.

STRUCTURE IS DERIVED, NEVER DECLARED
------------------------------------
`classify()` reads the structure off the legs. A caller asking for
"cross-game" does not make a slip cross-game. This is B36's failure — the
audit quoting the same-game band on cross-game slips reported -8.5% to +2.0%
where the right band was +1.3% to +4.1%, the wrong SIGN from a default meant
to be cautious. The same mistake in the other direction, quoting the
cross-game band on a slip with two legs in one event, is the one this module
is most exposed to, so `mixed` exists as its own kind and takes the
pessimistic band.

WHAT THE CORRELATION TABLE IS FOR HERE
--------------------------------------
Not for seeking correlation. The books price it: their factors tracked this
project's measured table closely (0.61-0.65 on QB stacks, 0.87-0.96 on
receiver-only slips, above 1.0 on opposing RBs). Buying a real lift at its
real price is not an edge, and it costs you the ability to state an EV.

It is for detecting a haircut that is NOT justified — a book charging 0.87
on legs the table puts at +0.00 is charging for correlation that does not
exist. That comparison is qualitative and stays that way. Backing the joint
out of `correlation_factor` is circular: since sgp_decimal = independent
_decimal x factor, dividing the independent probability by the factor and
multiplying gives the independent number back with extra steps.

One thing this module can do that ff_guillotine cannot: it knows the event,
so two RBs inside one event are genuinely facing each other and the measured
-0.14 applies. correlation_matrix() has to treat every different-team pair
as independent because it does not model the schedule.

CALL SEQUENCE FOR A SESSION
---------------------------
    # 1. legs — EV endpoint where it covers your books
    #    get_event_ev(..., devig="shin")        -> fair_prob, fair_source
    #    get_odds(markets=..., bookmakers=...)  -> the price you would bet
    #    For player_anytime_td the EV endpoint prices none of DK/FD/BetMGM,
    #    so take the price from get_odds and the anchor from an UNFILTERED
    #    get_event_ev call.
    quotes = flatten_odds(resp, line_type="main")
    screen = screen_quotes(quotes, game_started=False)

    # 2. veto pass — boost_verdict() per leg, then build BoostLegs
    # 3. shortlist locally; this costs no tool calls
    sl = enumerate_candidates(legs, meta, boost_pct=0.30, mode="cross-game")

    # 4. price ONLY the shortlist with price_sgp — one call per slip per
    #    book. A Sunday slate enumerates hundreds of combinations and you
    #    cannot price them all; the local ranking is a shortlisting
    #    heuristic, the book price is the answer.
    cand = price_candidate(cand, book_odds=..., correlation_factor=...)
    print(report([cand]))

WHAT P(cash) IS NOT
-------------------
It is the product of de-vigged market probabilities and it will look
precise. It inherits whatever error is in the anchor — and the anchor is
per-LINE, not per-book, so read fair_source off the line you are pricing.
It is absent entirely on a correlated slip. The report says all of this on
its face rather than leaving a clean-looking number to be quoted elsewhere.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from itertools import combinations, product

from ff_backtest import (to_decimal, implied, breakeven_p, boosted_return,
                         expected_roi, roi_band, SGP_HOLD_CROSS_GAME,
                         SGP_HOLD_SAME_GAME)
from ff_guillotine import normalize_name

# +300 is the boost's own requirement and does not move.
#
# CEILING was 450, chosen on the theory that EV stops improving materially
# above it while the hit rate halves. Raised to 600 on 2026-11-03 because
# MEASUREMENT contradicted the leg shape the old band assumed.
#
# The band was calibrated to "three legs near -150 each", which multiply to
# +363. A -150 prop main line is rare to nonexistent: the book moves the
# POINT until the price is near even money, so main lines cluster at -110
# to -115 and three of them multiply to roughly +575. Two live events were
# tested and BOTH produced zero candidates in +300..+450 — on event 87238,
# all 1,248 distinct combinations priced above the ceiling (min +558.8,
# median +569.8, max +592.8) and not one below the floor.
#
# So the real comparison is not +575 against +363. The +363 slip does not
# exist on a main-line board; the comparison is +575 against no bet.
#
# And the ceiling was never protecting EV. Minimum boost for +EV barely
# moves with price — 25% cross-game at +575 against 26% at +450. What it
# protects is HIT RATE: ~12.5% at +575 against ~21.6% at +363, i.e. about
# 2 cashes a season instead of 3.5, with each worth $84.75 rather than
# $57.19 on $10 at a 30% boost. That is a preference, not a finding, and
# Dustin's stated preference is regular hits — hence 600 rather than 700+,
# which buys almost no extra EV for a materially worse hit rate.
#
# The better fix is alternate lines and milestone rungs, which let you PICK
# a 60% leg instead of taking whatever the main line offers. Blocked twice
# over: B49 (flatten_odds raises on rungs) and anchor quality — Pinnacle
# offers NO alternates on props at all, so alternates would anchor off
# Kalshi contracts carrying a dollar or two, which is the exact input B46
# exists to reject. Revisit if either changes.
FLOOR = 300
CEILING = 600

# Re-exported, NOT redefined. The Sunday re-measurement updates ff_backtest
# and this module follows it; a second copy here would drift silently.
HOLD_CROSS = SGP_HOLD_CROSS_GAME
HOLD_SAME = SGP_HOLD_SAME_GAME

MODES = ("cross-game", "single-game")

# Pinnacle's minimum limit tier, measured 2026-11-03 on live get_odds:
# every yardage line on an opening board ~68 hours out carried
# `liquidity: 250`, and 18 of 20 were priced -114/-114 flat.
#
# That flatness is NOT corruption — an isolation run confirmed PropLine is
# not degrading Pinnacle on this tier (its player_receptions lines vary
# richly in the SAME response). It is the half-yard grid: on a continuous
# stat the book moves the POINT until -114/-114 is fair, so the price stays
# flat and only tilts when the grid cannot absorb the value.
#
# But a fair_prob of exactly 0.5000 at minimum limits is the book's PRIOR,
# not its posterior — "I set the point at my estimate and have taken no
# money yet". Measured: at the final pre-kickoff snapshot only 2 of 22
# lines are exactly 0.5000, and on a second event inside the last six hours
# it is 0 of 16. An EV built on an opening anchor is an EV against an
# opening number, and that has to be said out loud rather than printed to a
# decimal place it has not earned.
# B54. This was 250 because that was Pinnacle's minimum tier the day it was
# written. **A tier is not a constant.** Measured on one event: liquidity
# 250 on every outcome 2026-11-03, and 500 on every outcome 2026-11-05,
# about a day out — Pinnacle raises the limit as an event approaches, so a
# threshold pinned to the old tier tests a line the board has already walked
# past. The flag then cannot fire on the case it exists for: on that
# 2026-11-05 pull, 7 of 14 receiving lines were priced -112/-112 — exactly
# 0.5000 — every one at liquidity 500, and none flagged. A 2026-11-04 run
# priced 31 of 60 Pinnacle anchors at exactly 0.5000 in silence.
#
# Raised to 500 rather than removed. The gate is NOT wrong in principle: an
# exact 0.5000 backed by genuinely deep money is a real coin flip, not a
# prior, which is what the 10,000-liquidity check in section 35b pins down.
# What was wrong is reading one book's current minimum as a universal line.
#
# This will go stale again. If Pinnacle moves to 1,000 the same silent
# failure returns, and nothing in the suite would catch it, because a flag
# that never fires breaks no test. The durable fix is to derive the tier
# from the board — the modal liquidity across a book's own lines in the
# pull — instead of hardcoding it. Filed as B59; this is the stopgap.
OPENING_LIQUIDITY = 500

# Every correlation factor (sgp_price_decimal / independent_decimal) yet
# observed, all BetMGM on event 87238 across three sittings. Kept as the
# raw list so the range below is DERIVED from measurements rather than
# remembered — narrowing it now fails a test instead of silently shipping.
SGP_FACTORS_OBSERVED = (
    # 2026-11-05 early, 3-leg receiving YARDS
    0.8114, 0.8300, 0.8405, 0.8583,
    # 2026-11-05 later, receptions and Over/Under mixes
    0.8654, 0.9093, 0.9766, 0.9900,
    # 2026-11-05 controlled: SAME three BAL players, market varied
    0.8355,   # 3-leg yards,       product +528 -> quote +425
    0.7933,   # 3-leg receptions,  product +562 -> quote +425
    0.7705,   # 3-leg mixed O/U,   product +614 -> quote +450
    0.9821,   # 3-leg receptions on favourites, product +236 -> quote +230
    0.9044,   # 2-leg yards,       product +243 -> quote +210
)

# **The factor is not a property of a slip. It is quote / product, and the
# quote snaps to a coarse grid.** Observed grid points: +210, +230, +400,
# +425, +450, +475 — roughly 0.25 apart in decimal. Hold the quote near
# fixed and lengthen the product and this ratio falls mechanically, which
# is all the "factor" is measuring.
#
# That kills the explanation this constant originally shipped with. The
# first pass said the factor depends on what the legs ARE — yardage haircut
# hard, receptions barely at all. A controlled run disproved it: the SAME
# three Baltimore players, same event, same side, switching yards ->
# receptions -> mixed gave 0.8355 -> 0.7933 -> 0.7705, the opposite order,
# while products ran +528 -> +562 -> +614. Across those slips factor vs
# log(product) is r = -0.989. The within-market spread (0.189 between two
# receptions slips) is 4.5x the between-market spread (0.042 at matched
# product).
#
# Why the earlier sitting looked like composition: **main-line yards cannot
# produce a short product.** The book moves the POINT until yards sit near
# -110/-120, so three yards legs are always ~+520 or longer, while
# receptions carry real price spread (+170 to -235) and can be either.
# Composition and product length were perfectly confounded.
#
# So this stays wide ON PURPOSE and the right fix is not a tighter range —
# it is to predict the quote from the product against the grid, which needs
# more than thirteen points at one book on one event. B61.
OBSERVED_SGP_FACTORS = (0.77, 0.99)

# A SEPARATE problem from an opening line, and the first version of this
# module could not see it. `anchor_immature` tested fair_prob == 0.5 FIRST
# and returned False otherwise, so it never reached the liquidity check —
# which meant a Kalshi anchor at $0.98 with fair_prob 0.5052 read as a
# settled price while a Pinnacle line at 250 read as immature. That is the
# exact input these instructions call "noise wearing a precise-looking
# number", and the flag written to catch it was structurally blind to it.
#
# 25 is CRUDE and deliberately so. Book liquidity is not one unit:
# Pinnacle's 250 is a bet limit on an opening board, Kalshi's 0.98 is the
# money actually resting on a contract. They are not comparable, and a
# principled cross-book threshold would need a measurement nobody has
# made. 25 sits far below every Pinnacle value observed (250 minimum,
# rising to 10,000 by kickoff) and far above every thin Kalshi contract
# observed (0.94, 0.98, 1.00, 1.06), so it separates the two populations
# that exist today and errs toward flagging.
THIN_ANCHOR_LIQUIDITY = 25

# Measured over 43,228 same-game pairs, 2025-26. Everything absent is ~0.00,
# INCLUDING WR x WR on the same team (+0.00 over 2,970 pairs) — target
# competition cancels out team volume. Do not limit slips to stack shapes.
SAME_TEAM_CORR = {("QB", "WR"): 0.31, ("QB", "TE"): 0.27, ("QB", "RB"): -0.10}
OPPOSING_CORR = {("RB", "RB"): -0.14}

# The measured table was built on YARDS — QB passing, RB rushing, WR/TE
# receiving. So the side of a pair is decided by the MARKET being bet, not
# by the player's roster label.
#
# Found live 2026-11-02: build_meta() returns Travis Hunter as CB (his
# nflverse primary position) while he carries a receiving-yards prop on
# Trevor Lawrence's team. Position-keyed classification scored a genuine
# QB x receiver pair as INDEPENDENT, which hands it the cheaper hold band
# AND an ev_pct and p_cash it must never receive. Two failure modes at
# once, arriving through the data rather than the code — and he was in the
# shortlisted candidate that got priced.
MARKET_SIDE = {
    "player_pass_yds": "PASS",
    "player_rush_yds": "RUSH",
    "player_reception_yds": "RECV",
}

# Markets NOT in MARKET_SIDE are outside what the correlation table
# measured. player_anytime_td is the one that matters: it is a boost-parlay
# staple, and two same-team receivers both scoring correlates through team
# TD volume in a way nobody here has measured. Asserting +0.00 for them
# would be claiming a measurement that does not exist, so a same-event pair
# involving an unmeasured market is treated as UNMEASURED and makes the
# slip unpriceable. Different-event pairs stay independent regardless of
# market — that one IS measured, and it is what makes cross-game exact.

VERDICTS = {
    "PLAY": "Clears the floor and is +EV at the pessimistic end of the "
            "measured hold band.",
    "NEGATIVE": "Clears the floor but is -EV at the measured hold. The "
                "boost does not cover the structure.",
    "UNPRICEABLE": "Correlated legs. Real price, real payout, no EV — the "
                   "joint is not the product and this project has no joint "
                   "model. Not a verdict either way.",
}


_PAREN = re.compile(r"\s*\([^)]*\)\s*$")


def norm_player(name: str) -> str:
    """Canonical key for joining a book's quote to its anchor line.

    USE THIS FOR THE ODDS -> ANCHOR JOIN. It is the one join in the live
    intake path that has to happen on a name, and it has already cost a
    player his whole board.

    D13 recorded that the HISTORICAL endpoints carry no player_id and said
    "just live get_odds has the id". Measured 2026-11-02: live
    get_event_ev has no player_id either — only `description` — while
    get_odds does. So the anchor join is name-keyed on the live path too,
    and the never-join-on-a-name rule has a second and larger hole than
    D13 describes, at exactly the point boost intake needs it.

    It bites inside one response. On event 87238 the EV payload carried
    BOTH spellings at once:

        Brian Thomas Jr.  reception_yds  9.5   anchor kalshi
        Brian Thomas      reception_yds  10.5  anchor pinnacle

    DraftKings and FanDuel both priced him at 10.5, so a raw-name join
    found only the kalshi 9.5 rows and his entire DK/FD board went
    unanchored. normalize_name() — built for B1, the phantom-player bug —
    already collapses both to "brian thomas". The intake path simply was
    not using it.

    Also strips a trailing parenthetical: Bovada writes
    "Garrett Wilson (NYJ)" where DraftKings writes "Garrett Wilson".

    What it does NOT fix, and must not be trusted to: first-name variants
    such as Josh/Joshua Palmer, which are different strings all the way
    down. Resolve those through propline_search_players on an exact
    known_names match, as the instructions require.
    """
    return normalize_name(_PAREN.sub("", str(name).strip()))


def american(decimal: float) -> float:
    """Decimal -> American. Inverse of ff_backtest.to_decimal."""
    return (decimal - 1.0) * 100.0 if decimal >= 2.0 else -100.0 / (decimal - 1.0)


# ---------------------------------------------------------------------------
# Legs
# ---------------------------------------------------------------------------

@dataclass
class BoostLeg:
    """One candidate leg: the price you would take, and a fair line from a
    source that is not the book you are betting.

    `fair_prob` is validated here rather than at pricing time. B4 was the
    same bug one layer out: prop_edge accepted fair_over=0.0 and returned a
    meaningless infinite edge instead of refusing.
    """
    event_id: str
    book: str
    market: str
    player: str
    side: str
    odds: float
    fair_prob: float
    fair_source: str
    devig_method: str
    line: float | None = None
    player_id: str | None = None
    # Default is UNSCREENED, not CLEAR. "Nothing was found against this
    # leg" must not be the state you get when nothing was checked — that is
    # the shape of the 6.0 phantom-player mean (B1), which outranked 1,058
    # real players by being the fallback. A live run built 32 legs that all
    # read CLEAR without boost_verdict() ever being called.
    verdict: str = "UNSCREENED"                  # from ff_props.boost_verdict
    verdict_reasons: tuple[str, ...] = ()
    team: str | None = None
    pos: str | None = None
    # Liquidity on the ANCHOR's line, not on the book you are betting. It
    # is what says whether fair_prob is a settled number or an opening one.
    # Present on live get_odds (Pinnacle 250 on an opening board, rising to
    # 5,000-10,000 by kickoff); absent on Bovada, which returns null.
    anchor_liquidity: float | None = None

    def __post_init__(self):
        if not (0.0 < float(self.fair_prob) < 1.0):
            raise ValueError(
                f"fair_prob must be strictly between 0 and 1, got "
                f"{self.fair_prob!r} for {self.player}. A 0 or 1 makes the "
                f"EV infinite rather than wrong, which is harder to notice.")
        # Refused at construction, not just at intake. A leg whose fair line
        # came from the book being bet is that book's opinion of itself, and
        # a live test noted that such a leg "built and inspected directly
        # looks valid" when the only rejection was downstream. Intake checks
        # it again, because fair_source can be reassigned afterwards.
        if self.circular:
            raise ValueError(
                f"fair_source {self.fair_source!r} names {self.book!r}, the "
                f"book being bet. De-vigging a book against itself measures "
                f"it against its own no-vig opinion, which is circular — "
                f"take the fair line from a sharp anchor instead.")
        if self.verdict not in ("CLEAR", "CAUTION", "VETO", "UNSCREENED"):
            raise ValueError(f"unknown leg verdict {self.verdict!r}")
        self.verdict_reasons = tuple(self.verdict_reasons)

    @property
    def anchor_opening(self) -> bool:
        """The anchor has set a point but taken no money against it.

        An exact 0.5000 is the signal on its own — by kickoff only ~9% of
        lines sit there — and low liquidity confirms it where the book
        reports any.

        B54 moved OPENING_LIQUIDITY from 250 to 500 — see the note there.
        The structure of this test is unchanged and deliberately so: an
        exact 0.5000 behind genuinely deep money is a real coin flip rather
        than a prior, so the liquidity condition stays.
        """
        if abs(float(self.fair_prob) - 0.5) > 1e-9:
            return False
        return (self.anchor_liquidity is None
                or self.anchor_liquidity <= OPENING_LIQUIDITY)

    @property
    def anchor_thin(self) -> bool:
        """Barely any money is resting on the anchor, whatever it says.

        Independent of anchor_opening: a precise-looking 0.5052 off a $0.98
        Kalshi contract is worse input than a flat 0.5000 off Pinnacle, and
        testing fair_prob first hid exactly that case.
        """
        return (self.anchor_liquidity is not None
                and self.anchor_liquidity <= THIN_ANCHOR_LIQUIDITY)

    @property
    def anchor_immature(self) -> bool:
        """Either way the anchor cannot carry the weight of an EV."""
        return self.anchor_opening or self.anchor_thin

    @property
    def anchor_note(self) -> str | None:
        if self.anchor_thin:
            return (f"{self.player}: anchor liquidity is "
                    f"{self.anchor_liquidity:g} — almost no money is resting "
                    f"on this line, so its fair_prob of "
                    f"{self.fair_prob:.4f} is noise wearing a precise-looking "
                    f"number however far from 0.5000 it sits. This is the "
                    f"worst input you can hand fair_over.")
        if self.anchor_opening:
            lq = (f"liquidity {self.anchor_liquidity:g}"
                  if self.anchor_liquidity is not None
                  else "liquidity not reported by this book")
            return (f"{self.player}: fair_prob is exactly 0.5000 at {lq} — "
                    f"this is the anchor's OPENING number, its prior rather "
                    f"than its posterior. Re-pull closer to kickoff; by then "
                    f"only ~9% of lines still sit at exactly 0.5000.")
        return None

    @property
    def circular(self) -> bool:
        """True when the fair line came from the book being bet.

        A book de-vigged against itself is that book's opinion of itself.
        The instructions forbid it on a single prop; it is no more valid
        inside a slip.
        """
        return self.book.lower() in str(self.fair_source).lower()

    def describe(self) -> str:
        ln = f" {self.line}" if self.line is not None else ""
        return (f"{self.player} {self.market}{ln} {self.side} "
                f"{self.odds:+.0f} @{self.book}")


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------

@dataclass
class Structure:
    kind: str                       # cross-game | same-game-independent
                                    # | same-game-correlated | mixed
    pairs: list[tuple]              # (player_a, player_b, r, why) — measured
    priceable: bool
    reason: str
    # Pairs the measured table says NOTHING about. Kept apart from `pairs`
    # on purpose: a measured +0.31 and an unmeasured unknown both block an
    # EV, but only one of them is a number.
    unmeasured: list[tuple] = field(default_factory=list)

    @property
    def cross_game(self) -> bool:
        return self.kind == "cross-game"

    @property
    def hold_band(self) -> tuple[float, float]:
        return HOLD_CROSS if self.cross_game else HOLD_SAME

    @property
    def hold_band_reason(self) -> str:
        if self.cross_game:
            return ("cross-game band 17.7-20.9% — legs are in different "
                    "events, which the measured table puts at ~0.00, so the "
                    "fair joint is exactly the product")
        if self.kind == "mixed":
            return ("same-game band 23.1-37.2% — this slip has two legs in "
                    "one event, so it is NOT cross-game and does not get "
                    "the cheaper band")
        return "same-game band 23.1-37.2% — all legs in one event"


def _pair_r(a: BoostLeg, b: BoostLeg) -> tuple[float | None, str]:
    """Measured correlation for one pair, and why.

    Returns (0.0, "") for an established-independent pair, a non-zero r for
    a measured correlation, and (None, why) for a pair the table never
    measured — which is NOT the same as zero and must not be treated as it.
    """
    # Different games. This is the one the measurement is emphatic about,
    # and it holds whatever the markets are.
    if a.event_id != b.event_id:
        return 0.0, ""

    # Same event: team decides same-side vs opposing, so an unknown team
    # makes the pair unmeasurable rather than independent.
    if not a.team or not b.team:
        missing = a.player if not a.team else b.player
        return None, (f"no team known for {missing}, and these legs share "
                      f"an event — cannot tell a teammate from an opponent")

    sa, sb = MARKET_SIDE.get(a.market), MARKET_SIDE.get(b.market)
    if sa is None or sb is None:
        bad = a.market if sa is None else b.market
        return None, (f"{bad} is outside the measured correlation table "
                      f"(which was built on passing/rushing/receiving "
                      f"YARDS), and these legs share an event")

    if a.team == b.team:
        # WR vs TE only refines the magnitude; default to the larger one.
        if {sa, sb} == {"PASS", "RECV"}:
            pos = (a.pos if sa == "RECV" else b.pos) or ""
            r = SAME_TEAM_CORR[("QB", "TE")] if pos.upper() == "TE" \
                else SAME_TEAM_CORR[("QB", "WR")]
            return r, f"same team passing x receiving ({pos or 'receiver'})"
        if {sa, sb} == {"PASS", "RUSH"}:
            return SAME_TEAM_CORR[("QB", "RB")], "same team passing x rushing"
        return 0.0, ""

    if sa == "RUSH" and sb == "RUSH":
        return OPPOSING_CORR[("RB", "RB")], "opposing rushing in one event"
    return 0.0, ""


def classify(legs, meta=None) -> Structure:
    """Derive the structure FROM THE LEGS. Never takes a caller's word."""
    legs = list(legs)
    names = [l.player for l in legs]
    if len(set(names)) != len(names):
        dupe = next(n for n in names if names.count(n) > 1)
        raise ValueError(
            f"{dupe!r} appears twice in one slip. Two legs on one player are "
            f"not independent and most books will not combine them.")

    if meta:
        for l in legs:
            if l.team is None or l.pos is None:
                l.team, l.pos = meta.get(l.player, (None, None))

    pairs, unmeasured = [], []
    for a, b in combinations(legs, 2):
        r, why = _pair_r(a, b)
        if r is None:
            unmeasured.append((a.player, b.player, why))
        elif r:
            pairs.append((a.player, b.player, r, why))

    events = {l.event_id for l in legs}
    if len(events) == len(legs):
        kind = "cross-game"
    elif len(events) == 1:
        kind = ("same-game-correlated" if (pairs or unmeasured)
                else "same-game-independent")
    else:
        kind = "mixed"

    priceable = not pairs and not unmeasured
    if priceable:
        reason = ("fair joint is the product of the de-vigged legs — every "
                  "pair in this slip is established-independent by the "
                  "measured table")
    elif pairs:
        detail = "; ".join(f"{a} x {b} r={r:+.2f} ({why})"
                           for a, b, r, why in pairs)
        reason = (f"NOT priceable: {detail}. The true joint is not the "
                  f"product and this project has no joint model, so no EV "
                  f"is reported. That is not a verdict against the slip — "
                  f"the measured same-game hold was measured on INDEPENDENT "
                  f"legs and does not apply here.")
    else:
        detail = "; ".join(f"{a} x {b}: {why}" for a, b, why in unmeasured)
        reason = (f"NOT priceable: {detail}. Independence here would be an "
                  f"assumption, not a measurement, and assuming it is what "
                  f"hands a correlated slip an EV it should never get.")
    return Structure(kind=kind, pairs=pairs, priceable=priceable,
                     reason=reason, unmeasured=unmeasured)


def independent_odds(legs) -> float:
    """American price of these legs multiplied, ignoring correlation.

    A SHORTLISTING ESTIMATE ONLY. The book's SGP price is the real one, and
    it is routinely far shorter: three legs at -150 are +363 here and +225
    at a 0.62 factor. Scoring a slip at the product both invents EV and
    smuggles a below-floor slip past the floor.
    """
    d = 1.0
    for l in legs:
        d *= to_decimal(l.odds)
    return american(d)


def fair_joint(legs) -> float:
    """Product of the de-vigged leg probabilities.

    Only meaningful when no pair correlates. Callers must check
    Structure.priceable first; this function cannot.
    """
    p = 1.0
    for l in legs:
        p *= float(l.fair_prob)
    return p


def factor_note(structure: Structure, factor: float | None) -> str:
    """Compare the book's correlation_factor against the measured table.

    Qualitative on purpose. The factor informs the report; it never informs
    the math.
    """
    if factor is None:
        return "no correlation_factor supplied (price_sgp returns it)"
    if structure.pairs:
        return (f"book factor {factor:.3f} against measured "
                f"{', '.join(f'{r:+.2f}' for *_, r, _ in structure.pairs)} — "
                f"the books' factors have tracked this table closely "
                f"(0.61-0.65 on QB stacks), so expect to be charged roughly "
                f"what the correlation is worth. Whether it is worth MORE "
                f"than that is the joint this project cannot compute.")
    if factor < 0.97:
        return (f"book factor {factor:.3f} on legs the measured table puts "
                f"at ~0.00 — this haircut is NOT justified. You are paying "
                f"for correlation that does not exist, which is the bad "
                f"deal the table exists to catch.")
    if factor > 1.03:
        return (f"book factor {factor:.3f} — the book is PAYING for "
                f"anti-correlation. Measured opposing RBs sit at -0.14, so "
                f"this can be real.")
    return f"book factor {factor:.3f} — about 1.0, consistent with independence"


# ---------------------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------------------

@dataclass
class Candidate:
    legs: list[BoostLeg]
    structure: Structure
    boost_pct: float
    independent_odds: float
    stake: float = 10.0
    book_odds: float | None = None
    correlation_factor: float | None = None
    notes: list[str] = field(default_factory=list)
    # B55. The minimum TOTAL ODDS a boost token requires, as the promo
    # states it. Kept separate from FLOOR, which is this project's own band
    # and is a different question: FLOOR asks "is this slip worth betting",
    # the token minimum asks "will the book let me apply the token at all".
    token_min_odds: float | None = None

    # --- the price actually under consideration -----------------------
    @property
    def odds(self) -> float:
        """The book's SGP price once known, the product estimate before."""
        return self.book_odds if self.book_odds is not None else self.independent_odds

    @property
    def priced(self) -> bool:
        return self.book_odds is not None

    @property
    def clears_floor(self) -> bool:
        return self.odds >= FLOOR

    # --- B55: the token's minimum applies to the PRICE, not the product ---
    @property
    def token_minimum(self) -> bool | None:
        """Does the real quote clear the token's minimum total odds?

        `None` means UNKNOWN, and unknown is the dangerous state rather than
        a neutral one. A boost token's "minimum total odds" is checked by
        the book against the correlated SGP price it actually offers, which
        is always below the product of the legs. Measured at BetMGM: a +516
        product quoted +400, +554 quoted +450, +593 quoted +475 — factors
        0.81 to 0.86. So a +450 product prices to roughly +346 to +372, and
        a slip that clears a +400 token on the product VOIDS it on the
        price. Clearing the floor says nothing about this: FLOOR is checked
        against `odds`, which is the product until the slip is priced.

        Returns None when no token minimum was supplied, and None when one
        was but the slip is unpriced — because the product cannot answer the
        question and guessing from it is the bug this exists to stop.
        """
        if self.token_min_odds is None or not self.priced:
            return None
        return float(self.book_odds) >= float(self.token_min_odds)

    @property
    def token_note(self) -> str | None:
        """Say the quiet part: unpriced is not 'probably fine'."""
        if self.token_min_odds is None:
            return None
        if not self.priced:
            lo, hi = OBSERVED_SGP_FACTORS
            est_lo = american(to_decimal(self.independent_odds) * lo)
            est_hi = american(to_decimal(self.independent_odds) * hi)
            return (f"token needs {self.token_min_odds:+.0f} and this slip "
                    f"is UNPRICED. Its product is "
                    f"{self.independent_odds:+.0f}; across every correlation "
                    f"factor yet observed ({lo:.2f}-{hi:.2f}) that quotes "
                    f"anywhere from {est_lo:+.0f} to {est_hi:+.0f}. That "
                    f"range is too wide to decide a token on, deliberately: "
                    f"the quote snaps to a coarse grid, so the factor falls "
                    f"as the product lengthens and is not a property of the "
                    f"slip. Call price_sgp.")
        if self.token_minimum:
            return (f"token minimum {self.token_min_odds:+.0f} cleared by "
                    f"the real quote {self.book_odds:+.0f} "
                    f"(product was {self.independent_odds:+.0f}).")
        return (f"TOKEN VOIDS. It needs {self.token_min_odds:+.0f} and the "
                f"book quotes {self.book_odds:+.0f}. The product "
                f"{self.independent_odds:+.0f} clears it; the price does "
                f"not, and the price is what the book checks.")

    # --- EV, where it is legal ----------------------------------------
    @property
    def p_cash(self) -> float | None:
        return fair_joint(self.legs) if self.structure.priceable else None

    @property
    def breakeven(self) -> float | None:
        if not self.structure.priceable:
            return None
        return breakeven_p(self.odds, self.boost_pct)

    @property
    def ev_pct(self) -> float | None:
        """EV from OUR de-vigged joint against the price ACTUALLY QUOTED.

        None until the slip is priced, and that is the point. Before
        pricing, the only number available is the product of the legs, and
        that is not a price anybody will lay — the book's SGP quote is
        routinely far shorter. Computing a direct EV against an unobtainable
        price produces exactly the plausible-looking wrong number this
        project keeps shipping: an early version of this module reported
        "+15.7%" beside a NEGATIVE verdict, because the verdict used the
        measured hold while the EV assumed the product was purchasable.
        Use `ev_band` before pricing.

        Depends on p_cash, the quoted price and the boost. It does NOT
        depend on correlation_factor — if it did, the factor would be being
        backed into the joint, which cancels.
        """
        if not (self.structure.priceable and self.priced):
            return None
        p = self.p_cash
        d = to_decimal(self.book_odds)
        return p * (d - 1.0) * (1.0 + self.boost_pct) - (1.0 - p)

    @property
    def ev_band(self) -> tuple[float, float] | None:
        """(pessimistic, optimistic) ROI anticipated across the measured
        hold band. This is the pre-pricing estimate: it assumes the book
        will take its usual cut out of the product, which is the whole
        reason the product is not a price."""
        if not self.structure.priceable:
            return None
        return roi_band(self.odds, self.boost_pct,
                        cross_game=self.structure.cross_game)

    @property
    def slip_hold(self) -> float | None:
        """This slip's own hold, from its price against our fair joint.

        For a cross-game slip this is exact and is a better number than the
        measured band — the band is a population figure, this is the slip in
        front of you.
        """
        if not self.structure.priceable or not self.priced:
            return None
        return 1.0 - self.p_cash * to_decimal(self.book_odds)

    @property
    def hold_band(self) -> tuple[float, float]:
        return self.structure.hold_band

    @property
    def hold_band_reason(self) -> str:
        return self.structure.hold_band_reason

    @property
    def payout(self) -> float:
        return boosted_return(self.stake, self.odds, self.boost_pct)

    @property
    def factor_note(self) -> str:
        return factor_note(self.structure, self.correlation_factor)

    @property
    def verdict(self) -> str:
        if not self.structure.priceable:
            return "UNPRICEABLE"
        if not self.clears_floor:
            return "NEGATIVE"
        if self.priced:
            # A real quote beats a population figure: the hold on this slip
            # is now directly observable rather than assumed.
            return "PLAY" if self.ev_pct > 0 else "NEGATIVE"
        # Pessimistic end of the measured band. Assuming the cheaper product
        # when you do not know which you have is the error that loses money.
        return "PLAY" if self.ev_band[0] > 0 else "NEGATIVE"

    @property
    def rank(self) -> float:
        """What to sort on: the real EV once priced, the anticipated
        pessimistic ROI before."""
        if self.ev_pct is not None:
            return self.ev_pct
        return self.ev_band[0] if self.ev_band is not None else -9e9

    @property
    def key(self) -> tuple:
        """Deterministic sort key. A recommendation you cannot reproduce
        cannot be audited against the bet log later."""
        return (-self.rank, tuple(sorted(l.player for l in self.legs)))


def make_candidate(legs, meta=None, *, boost_pct: float,
                   stake: float = 10.0) -> Candidate:
    """One candidate from one set of legs, structure derived."""
    legs = list(legs)
    st = classify(legs, meta)
    notes = []
    for l in legs:
        if l.verdict == "CAUTION":
            notes.append(f"CAUTION on {l.player}: "
                         f"{'; '.join(l.verdict_reasons) or 'unspecified'}")
    if not st.priceable:
        notes.append(st.reason)
    return Candidate(legs=legs, structure=st, boost_pct=float(boost_pct),
                     independent_odds=independent_odds(legs), stake=stake,
                     notes=notes)


# ---------------------------------------------------------------------------
# Enumeration
# ---------------------------------------------------------------------------

@dataclass
class Shortlist:
    candidates: list[Candidate]
    mode: str
    boost_pct: float
    reason: str = ""
    dropped: list[tuple[str, str]] = field(default_factory=list)

    @property
    def playable(self) -> bool:
        """Is there anything here to price at all?

        This is now a structural question — are there legs, do any
        combinations land in the floor band — NOT a judgement on EV.

        It used to be the hard verdict, refusing whenever the boost failed
        to cover the pessimistic end of the measured hold band. Measured
        2026-11-02: that band said 23.1-37.2% and the slip it refused
        actually held 19.2% and priced at **+1.4%**. The pessimistic end of
        a 14-point band is too harsh a gate when the shortlist caps at 8
        and pricing all of them costs 8 calls. The hard verdict now comes
        from Candidate.verdict AFTER a real quote, where the number is real.
        """
        return bool(self.candidates)

    @property
    def outlook(self) -> str:
        """What to expect BEFORE pricing. Advisory, not a verdict."""
        if not self.candidates:
            return "NONE"
        v = {c.verdict for c in self.candidates}
        if "PLAY" in v:
            return "LIKELY PLAYABLE"
        if "UNPRICEABLE" in v:
            return "UNPRICEABLE ONLY"
        return "LIKELY NEGATIVE"

    @property
    def immature_anchors(self) -> list[str]:
        return sorted({l.player for c in self.candidates for l in c.legs
                       if l.anchor_immature})

    def describe(self) -> str:
        if not self.candidates:
            return f"NOTHING TO PRICE — {self.reason}"
        L = [f"{len(self.candidates)} candidate(s) — outlook {self.outlook}",
             f"  {self.reason}"]
        if self.immature_anchors:
            L.append(f"  opening anchors (fair_prob exactly 0.5000) on: "
                     f"{', '.join(self.immature_anchors)} — re-pull closer "
                     f"to kickoff before trusting any EV built on them")
        return "\n".join(L)


def _intake(legs, mode: str, event_id: str | None) -> tuple[list, list]:
    """Drop legs that must never reach a slip. Returns (kept, dropped)."""
    kept, dropped = [], []
    for l in legs:
        if l.verdict == "VETO":
            dropped.append((l.player, "VETO: " +
                            ("; ".join(l.verdict_reasons) or "unspecified")))
            continue
        if l.verdict == "UNSCREENED":
            dropped.append((l.player,
                            "never passed through boost_verdict() — run the "
                            "screen; an unchecked leg is not a clear one"))
            continue
        if l.circular:
            dropped.append((l.player,
                            f"fair line sourced from {l.book}, the book being "
                            f"bet — a book de-vigged against itself is its "
                            f"own opinion, not a reference"))
            continue
        if mode == "single-game" and event_id is not None \
                and l.event_id != event_id:
            dropped.append((l.player, f"not in event {event_id}"))
            continue
        kept.append(l)
    return kept, dropped


def enumerate_candidates(legs, meta=None, *, boost_pct: float,
                         mode: str, event_id: str | None = None,
                         floor: float = FLOOR, ceiling: float = CEILING,
                         legs_per_slip: int = 3, limit: int = 8,
                         stake: float = 10.0) -> Shortlist:
    """Shortlist slips that clear the floor, ranked deterministically.

    Costs no tool calls. Price the survivors with price_sgp — the local
    ranking is a heuristic and the book's price is the answer.
    """
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}. It is "
                         f"not inferred: this module cannot read a boost's "
                         f"terms, and guessing the cheaper structure is the "
                         f"error that loses money.")
    legs = list(legs)
    if mode == "single-game" and event_id is None:
        events = {l.event_id for l in legs}
        if len(events) != 1:
            raise ValueError(
                f"single-game mode needs event_id when the pool spans "
                f"{len(events)} events")
        event_id = events.pop()

    kept, dropped = _intake(legs, mode, event_id)

    combos = []
    if mode == "cross-game":
        by_event: dict[str, list] = {}
        for l in kept:
            by_event.setdefault(l.event_id, []).append(l)
        if len(by_event) >= legs_per_slip:
            for evs in combinations(sorted(by_event), legs_per_slip):
                for pick in product(*(by_event[e] for e in evs)):
                    combos.append(list(pick))
    else:
        combos = [list(c) for c in combinations(kept, legs_per_slip)]

    seen, cands = set(), []
    n_short, n_long = 0, 0        # measured, not guessed — see the reason below
    for c in combos:
        names = tuple(sorted(l.player for l in c))
        if len(set(names)) != len(names) or names in seen:
            continue
        seen.add(names)
        cand = make_candidate(c, meta, boost_pct=boost_pct, stake=stake)
        if cand.independent_odds < floor:
            n_short += 1
            continue
        if cand.independent_odds > ceiling:
            n_long += 1
            continue
        cands.append(cand)

    cands.sort(key=lambda c: c.key)
    cands = cands[:limit]

    reason = ""
    if cands and any(c.verdict == "PLAY" for c in cands):
        best = max(cands, key=lambda c: c.rank)
        reason = (f"best anticipated ROI {best.ev_band[0]:+.1%} to "
                  f"{best.ev_band[1]:+.1%} across the measured hold band — "
                  f"ADVISORY. Price the shortlist with price_sgp; the real "
                  f"quote decides.")
    elif cands:
        band = cands[0].hold_band
        best = max((c for c in cands if c.ev_band is not None),
                   key=lambda c: c.rank, default=None)
        got = (f"Best anticipated is {best.ev_band[0]:+.1%} at the "
               f"pessimistic end. " if best is not None else
               "No candidate here can be priced at all. ")
        reason = (f"a {boost_pct:.0%} boost is unlikely to cover the "
                  f"measured hold for this structure "
                  f"({band[0]:.1%}-{band[1]:.1%}). {got}Measured minimum is "
                  f"~28% cross-game and ~50% same-game at +300. This is an "
                  f"ADVISORY read on an unpriced product price — the band "
                  f"is 14 points wide and a real quote has come in better "
                  f"than its pessimistic end before, so price the shortlist "
                  f"before writing the slip off.")
    else:
        if not kept:
            reason = "every leg was dropped at intake"
        elif not cands:
            # The direction is MEASURED per combination, never assumed. The
            # first version hardcoded "legs are too short"; on a live board
            # all 4,144 combinations were ABOVE the ceiling and none below
            # the floor, so it sent the reader hunting the wrong way. A
            # plausible sentence instead of an error, which is this
            # project's recurring signature.
            if not n_short and not n_long:
                reason = (f"not enough legs to build a "
                          f"{legs_per_slip}-leg slip")
            elif n_long and not n_short:
                reason = (f"all {n_long} combination(s) price ABOVE the "
                          f"+{ceiling:.0f} ceiling — the legs are too LONG "
                          f"for this band. Either raise `ceiling`, or "
                          f"pick legs at lower prices.")
            elif n_short and not n_long:
                reason = (f"all {n_short} combination(s) price BELOW the "
                          f"+{floor:.0f} floor — the legs are too short to "
                          f"reach the boost's minimum price.")
            else:
                reason = (f"no combination lands in the +{floor:.0f} to "
                          f"+{ceiling:.0f} band: {n_short} below the floor, "
                          f"{n_long} above the ceiling.")
        else:
            band = cands[0].hold_band
            reason = (f"a {boost_pct:.0%} boost does not cover the measured "
                      f"hold for this structure ({band[0]:.1%}-{band[1]:.1%}). "
                      f"Best candidate is {cands[0].ev_band[0]:+.1%} at the "
                      f"pessimistic end. Measured minimum is ~28% cross-game "
                      f"and ~50% same-game at +300.")
    return Shortlist(candidates=cands, mode=mode, boost_pct=boost_pct,
                     reason=reason, dropped=dropped)


def price_candidate(cand: Candidate, *, book_odds: float,
                    correlation_factor: float | None = None) -> Candidate:
    """Attach the real price_sgp quote. Returns a NEW Candidate.

    Returning a copy rather than mutating is deliberate: B19 shipped because
    add_replacement_level() mutated a shared pool in place, so a later run
    inherited an earlier one's state and the A/B comparison the flag existed
    for silently stopped working.
    """
    return Candidate(legs=list(cand.legs), structure=cand.structure,
                     boost_pct=cand.boost_pct,
                     independent_odds=cand.independent_odds,
                     stake=cand.stake, book_odds=float(book_odds),
                     correlation_factor=correlation_factor,
                     notes=list(cand.notes),
                     token_min_odds=cand.token_min_odds)


def stake_back_ev(odds: float, *, stake: float = 10.0,
                  bonus_value: float = 0.65,
                  market_hold: float = 0.39) -> dict:
    """EV of a STAKE-BACK token (bet reset / safety net / second chance).

    B56. These are not boosts and must not go through the boost path. A
    boost pays more when you WIN, so it rewards a high win probability. A
    stake-back refunds the stake as a BONUS BET when you LOSE, so its value
    rises as win probability FALLS. **The right bet for one is the longest
    shot that qualifies**, which is why these belong on First TD Scorer and
    not on a -110 single.

        EV = p*(d-1)*S  -  (1-p)*S*(1-v)

    `bonus_value` (v) is the cash worth of $1 of bonus-bet FACE and it
    decides the answer, so it is an argument rather than a constant and the
    caller must state it. A bonus bet returns profit only, never the stake,
    so at fair odds it is worth `1 - 1/d`: 0.50 at even money, 0.80 at +400,
    0.90 at +900. Haircut for the vig of whatever market the refund is spent
    in. A long First TD lands near 0.70; a -110 single near 0.46 — so where
    the REFUND goes matters nearly as much as where the bet goes.

    `market_hold` backs out the true probability from the offered price the
    same way `expected_roi` does.

    **Both defaults were wrong on first release and are now measured.** The
    first pass used hold 0.22 and v 0.70, both guessed. Measured 2026-11-05
    on BetMGM's First TD board for event 87238: booksum across its 23
    selections was **1.3935, a 39.4% overround**, and that is a LOWER bound
    — DraftKings listed 32 selections including No Touchdown Scorer at
    54.9%. So 0.22 was roughly half the real number.

    `v` was worse, because it was not just imprecise but unreachable.
    Deriving it from that same board as `p_true * (d-1)` for a refund spent
    back into it gives 0.65 at +900, 0.69 at +2800 and 0.71 at +6600 under
    a 39.4% hold, falling to 0.58-0.64 at 55%. **v = 0.80 is not attainable
    in this market at all**, so the original 0.60/0.70/0.80 band bracketed
    the truth only at its bottom edge. Honest EV on a $10 token is **$2-4**,
    not the $4-5 first quoted.

    **The raw bet's EV does not depend on the odds at all.** Substituting
    p = 1/(d*(1+h)) into the first term collapses it:

        base = S * (1/(1 + h) - 1)

    — no `d` anywhere. Verified across every price from -200 to +20000:
    -$2.8058 at all of them, for S=10, h=0.39. So **all** odds-dependence
    lives in the refund, `(1-p)*S*v`, and the most EV still available by
    lengthening past any price is exactly `S*v*p_true` there: $0.94 at
    +400, $0.47 at +900, $0.16 at +2800, $0.07 at +6600.

    That bounds the question permanently rather than measuring it once, and
    it sharpens the advice in both directions:

    - **Do not put a stake-back on a short price.** +400 to +900 alone is
      worth $0.47 — more than the whole +900 to +6600 stretch above it.
    - **Reaching past a sensible longshot is worth almost nothing.** Past
      +2800 there is under a dime left on a $10 token.
    - Across prices actually on a First TD board (+400 to +6600) the odds
      choice is worth ~$0.86, against ~$1.2 for the `v` band and ~$1.35
      across the plausible hold range. So odds choice is about two-thirds
      of `v`, not the one-fifth first recorded here — that figure measured
      +900 upward and missed the steepest part of the board.

    Both the hold and v are one book, one market, one night. Re-measure the
    booksum rather than inheriting 0.39 — D16.

    Returns the components rather than one number, because the headline is
    almost entirely the refund and that should be visible, not buried.
    """
    d = to_decimal(odds)
    p = implied(odds) / (1.0 + float(market_hold))
    base = p * (d - 1.0) * stake - (1.0 - p) * stake
    refund = (1.0 - p) * stake * float(bonus_value)
    return {"odds": float(odds), "p_true": p, "stake": float(stake),
            "bonus_value": float(bonus_value), "market_hold": float(market_hold),
            "base_ev": base, "refund_ev": refund, "ev": base + refund,
            "roi": (base + refund) / stake}


def stake_back_band(odds: float, *, stake: float = 10.0,
                    market_hold: float = 0.39) -> dict:
    """`stake_back_ev` across a pessimistic/central/optimistic bonus value.

    Never quote a stake-back token as one number. `bonus_value` is an
    assumption, not a measurement, and it moves the answer about three times
    as much as picking a longer leg does.

    The 0.58/0.65/0.71 band is derived from a real First TD board rather
    than guessed — see `stake_back_ev`. The first version used
    0.60/0.70/0.80, whose top end this market cannot reach.
    """
    return {lab: stake_back_ev(odds, stake=stake, bonus_value=v,
                               market_hold=market_hold)
            for lab, v in (("pessimistic", 0.58), ("central", 0.65),
                           ("optimistic", 0.71))}


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def report(cands, boost_label: str = "") -> str:
    """Human-readable, and deliberately loud about what it does not know."""
    out = []
    for i, c in enumerate(cands, 1):
        out.append(f"--- candidate {i}: {c.structure.kind}  "
                   f"[{c.verdict}] {boost_label}".rstrip())
        for l in c.legs:
            out.append(f"    {l.describe()}   fair {l.fair_prob:.3f} "
                       f"({l.fair_source}, de-vig: {l.devig_method})")
        out.append(f"  product of legs : {c.independent_odds:+.0f} "
                   f"(shortlisting estimate, not a price)")
        if c.priced:
            out.append(f"  BOOK SGP price  : {c.book_odds:+.0f}"
                       + ("" if c.clears_floor
                          else f"   ** BELOW THE +{FLOOR:.0f} FLOOR **"))
        out.append(f"  ${c.stake:.0f} returns  : ${c.payout:.2f} "
                   f"at a {c.boost_pct:.0%} boost")
        out.append(f"  {c.factor_note}")

        if c.structure.priceable:
            out.append(f"  P(cash)         : {c.p_cash:.1%}  "
                       f"(product of the de-vigged legs)")
            out.append(f"  boosted breakeven: {c.breakeven:.1%}")
            if c.priced:
                out.append(f"  EV              : {c.ev_pct:+.1%}  "
                           f"(against the quoted price)")
                out.append(f"  this slip's hold: {c.slip_hold:.1%}  "
                           f"(observed, not assumed — reference band "
                           f"{c.hold_band[0]:.1%}-{c.hold_band[1]:.1%})")
            else:
                out.append(f"  anticipated ROI : {c.ev_band[0]:+.1%} to "
                           f"{c.ev_band[1]:+.1%} across the measured hold "
                           f"band — NOT priced yet, run price_sgp")
                out.append(f"  reference band  : {c.hold_band[0]:.1%}-"
                           f"{c.hold_band[1]:.1%} — {c.hold_band_reason}")
            out.append("  P(cash) is a product of de-vigged market "
                       "probabilities. It inherits whatever error is in the "
                       "anchor, which is per-LINE, not per-book.")
        else:
            out.append("  NO EV, NO P(cash) — the joint is not the product "
                       "and this project cannot compute it.")
            out.append(f"  reference band  : not applicable. "
                       f"{c.hold_band_reason}")
        for l in c.legs:
            if l.anchor_note:
                out.append(f"  ** OPENING ANCHOR ** {l.anchor_note}")
        for n in c.notes:
            out.append(f"  note: {n}")
        out.append("  The model's number is a GAP against a de-vigged line, "
                   "not a finding. A clear leg means nothing was found "
                   "against it.")
        out.append("")
    return "\n".join(out)
