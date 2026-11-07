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
from collections import Counter
from itertools import combinations, product

from ff_backtest import (to_decimal, implied, breakeven_p, boosted_return,
                         expected_roi, roi_band, SGP_HOLD_CROSS_GAME,
                         SGP_HOLD_SAME_GAME)
# B82. norm_player moved to ff_props, which is where the odds intake that
# needs it lives; re-exported here so existing callers and the instructions
# keep working. One home, per lesson 7.
try:
    from ff_props import norm_player  # noqa: F401  (re-export)
    # B78. One definition of "which book is this", shared with the dropout
    # detector. A second copy here is how B68's duplicate table happened.
    from ff_props import book_key  # noqa: F401  (re-export)
except ImportError as _e:               # pragma: no cover - torn repo only
    # B99. `norm_player` moved from here to ff_props on 2026-11-06 (B82),
    # which made this module depend on a NEW ff_props. The repo is updated
    # by uploading files one at a time, so a half-updated clone is the
    # NORMAL case rather than an edge case — and a live session hit exactly
    # this, got a bare "cannot import name 'norm_player' from 'ff_props'",
    # concluded the repo was missing three functions, and built a shim.
    # Two of those three claims were wrong. A cryptic import error at module
    # load costs more than the refactor saved, so it says what to do.
    raise ImportError(
        "ff_boost needs norm_player AND book_key from ff_props, and this "
        "ff_props does "
        "not have it.\n\n"
        "This is a HALF-UPDATED REPO, not a missing feature. norm_player "
        "moved from ff_boost to ff_props on 2026-11-06 (B82), so the two "
        "files must be committed TOGETHER:\n"
        "    ff_props.py  and  ff_boost.py\n\n"
        "Commit the matching ff_props.py and this import works. Do NOT "
        "shim norm_player — ff_props is also where field_from_odds and "
        "two_sided_field live, so an ff_props without norm_player is "
        "missing those too, and anything built on this clone will be "
        "working around absences that a correct commit removes."
    ) from _e

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

# B74. `stake_back_band` carried these three as inline literals, and the
# check guarding them compared a retyped 0.71 against 0.71 — it would have
# caught a regression to the unreachable v=0.80 the first version shipped,
# but its NAME claimed to test reachability, which it never measured. Named
# here for the same reason SGP_FACTORS_OBSERVED is: the numbers are a
# measurement off a real First TD board (see `stake_back_ev`), so they get
# provenance and one home rather than being retyped at each use. The top
# end is what a leg can actually realise; the first version's 0.80 could
# not be reached on that board at any price.
STAKE_BACK_V_OBSERVED = (0.58, 0.65, 0.71)
STAKE_BACK_V_LABELS = ("pessimistic", "central", "optimistic")

# B59. Below this many liquidity readings, a derived tier is not a
# measurement and the module constant is used instead. A "modal" value
# from one or two lines is just that line.
TIER_MIN_SAMPLE = 3


TIER_MIN_SHARE = 0.5

# `modal_liquidity` derives the MOST COMMON limit and asserts it is the
# book's MINIMUM tier. Those coincide on an OPENING board, which is uniform
# at the floor — Pinnacle was 28/28 at exactly 500 tonight. They come apart
# on a MATURE board, which is uniform at depth: `anchor_liquidity`'s own
# docstring records Pinnacle rising to 5,000-10,000 by kickoff. Derived
# naively, that board yields a tier of 10,000 and then EVERY exact-0.5000
# line flags as "opening" regardless of how much money is behind it —
# turning the flag uninformative exactly on the pull you bet from.
#
# So a derived tier above this ceiling is not a floor; it is a mature
# board, and on a mature board the hardcoded floor is the right test.
#
# This is a BOUND, not a threshold, and that is why it does not reintroduce
# the B54 problem it looks like. OPENING_LIQUIDITY had to track a moving
# tier and went silent the moment the tier moved. This only has to sit
# somewhere in the gap between an opening floor (250-1,000 observed) and a
# mature board (5,000-10,000 observed). That gap is wide and the mechanism
# making it wide — books raise limits as confidence grows — is not going to
# invert.
TIER_MAX_TRUSTED = 2000.0


def modal_liquidity(values, *, min_sample: int = TIER_MIN_SAMPLE,
                    min_share: float = TIER_MIN_SHARE):
    """A book's own minimum limit tier, from its board in ONE pull.

    B59. `OPENING_LIQUIDITY` is a hardcoded number and hardcoding it has
    already failed once: 250 was Pinnacle's tier the day it was written,
    Pinnacle moved to 500, and `anchor_opening` went silent on exactly the
    lines it exists to catch. Raising it to 500 postponed that; deriving it
    retires it. The tier is observable in every pull — on two consecutive
    readings Pinnacle was 42 of 42 and then 70 of 70 outcomes at exactly
    500, uniform, no spread.

    Returns None when there are fewer than `min_sample` readings, so the
    caller falls back to the constant rather than trusting a "mode" taken
    from one line.

    **It also returns None unless the mode covers `min_share` of the
    readings, because not every book reports a TIER.** The first version of
    this function missed that and a live pull caught it: Pinnacle came back
    10 of 10 at exactly 500 — a bet limit, discrete, obviously a tier —
    while Kalshi came back with **95 distinct values across 100 readings**
    and a "mode" of 0.97 appearing twice. Kalshi reports resting money in
    dollars, which is continuous; its mode is noise, and feeding it in as a
    threshold would be inventing a number. A book with no dominant value is
    a book with no tier, and the right answer is to say so and fall back.
    Kalshi's shallow anchors are `anchor_thin`'s job, not this one — the
    separation B46 established.

    **Ties break HIGH, on purpose.** A tier that is too high flags some
    settled anchors — noise, and safe. A tier that is too low misses an
    opening anchor, which is silently using a book's prior as its price:
    the exact failure this flag exists to prevent, and the one that has
    actually happened. When the two errors are not symmetric, break toward
    the survivable one.
    """
    vals = [float(v) for v in values if v is not None]
    if len(vals) < min_sample:
        return None
    counts = Counter(vals)
    top = max(counts.values())
    if top < min_share * len(vals):
        return None
    tier = max(v for v, n in counts.items() if n == top)
    # A uniformly DEEP board is not an opening board. See TIER_MAX_TRUSTED.
    return None if tier > TIER_MAX_TRUSTED else tier


def book_liquidity_tiers(odds_response: dict,
                         *, min_sample: int = TIER_MIN_SAMPLE) -> dict:
    """{book: its own minimum tier} from a `get_odds` event response.

    Pass the result to each BoostLeg as `opening_liquidity_tier`, keyed by
    the leg's ANCHOR book — not the book being bet. The anchor is what
    `fair_prob` came from, so it is the board whose tier decides whether
    that number is a price or a prior.

    Books that report no liquidity at all (DraftKings 0/276, FanDuel 0/204,
    Bovada) are absent from the result rather than present with None, so a
    missing key means "never reported" and `anchor_opening` keeps its
    existing behaviour of flagging a null-liquidity 0.5000 regardless.
    """
    out = {}
    for bk in odds_response.get("bookmakers") or []:
        # B78. A manufactured display-name key cannot match ANCHOR_CHAIN, so
        # a tier derived under it was unreachable by every caller that looks
        # a book up by chain key — which is how B75's "no caller anywhere"
        # and this fallback compound each other.
        key = book_key(bk)
        if key is None:
            continue
        vals = [oc.get("liquidity")
                for mk in bk.get("markets") or []
                for oc in mk.get("outcomes") or []]
        tier = modal_liquidity(vals, min_sample=min_sample)
        if tier is not None:
            out[key] = tier
    return out

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

# ("QB","RB") above is QB PASSING x RB RUSHING. A back catching passes is a
# different pair and the code used to miss it: `_pair_r` asked only whether
# the receiving player was a TE, so **an RB with a receiving prop was scored
# at the WR value of +0.31**. Derrick Henry receiving yards beside Lawrence
# passing got double its real correlation.
#
# Measured 2026-11-05 on nflverse 2025-26, games>=4 and no volume gate:
# QB passing x RB receiving is **+0.157 (n=2,154)**, against +0.243 for WR
# receiving and +0.230 for TE on that same filter. RB receiving is about
# **0.65x** the WR figure.
#
# The value below is that RATIO applied to the documented +0.31, not the
# raw +0.157, and that choice needs stating. The documented table was built
# on a filter nobody recorded and which this sweep could not recover (E3),
# so a raw number from a different filter would sit on a different scale
# from its neighbours — the inconsistency E3 exists to fix. A ratio
# measured WITHIN one filter transfers across scales far better than a
# level does. It is still a derived number, so it is marked provisional and
# E3 should overwrite it with a directly measured value on one documented
# filter.
#
# Low stakes either way, and worth knowing why: magnitude does not decide
# priceability. `classify()` marks a slip unpriceable if ANY pair is
# non-zero, so +0.31 and +0.20 both refuse an EV. This number only reaches
# the explanation text and the comparison against the book's own
# correlation_factor, which the instructions tell a session to make.
SAME_TEAM_CORR_PROVISIONAL = {("QB", "RB_RECV"): 0.20}

# Every {PASS, RUSH, RECV} x {same team, opposing} pair, measured in one pass
# so that the gate below rests on numbers rather than on which branch a pair
# happened to fall through. Keyed (relation, side_a, side_b) with sides
# sorted, value = (joint-crossing LIFT, continuous r, n).
#
#   nflverse 2023-2026 REG, the stat behind each market (QB passing yards,
#   RB rushing yards, WR/TE receiving yards), z-scored per player-season,
#   min 6 games, pairs within one game, deduped.
#   Re-derive: python3 measurements/e6_full_pair_sweep.py
#
# CONTROL, same script and method: same-team PASS x RECV recovered r=+0.2462
# against the canonical table's +0.31 — inside band, so the method
# reproduces a pair the table claims to know and the rest is admissible. The
# script VOIDS its own run if that control fails.
#
# LIFT, not r, is what a parlay needs: it is P(both cross) over the product
# of the singles, which is exactly what multiplying two de-vigged legs
# assumes. Two findings worth knowing because they contradict the mechanism
# stories told about them:
#   * SAME-TEAM RB x RB is POSITIVE (+9.92%). The carry-pool argument — two
#     backs splitting fixed carries should be negative, more so than the
#     -0.14 given OPPOSING backs — is wrong. Game script dominates: a team
#     that runs 35 times feeds both, a team that runs 18 feeds neither.
#   * SAME-TEAM RUSH x RECV, the commonest same-game shape there is, is
#     -1.22% over 28,499 pairs — effectively independent. Gating it on the
#     assumption that same-team means correlated would have refused an EV on
#     a large share of real slips for no measured reason.
MEASURED_PAIR_LIFT = {
    ("same", "PASS", "RECV"): (1.1993, +0.2462, 11556),
    ("same", "RUSH", "RUSH"): (1.0992, +0.0902, 3815),
    ("same", "PASS", "RUSH"): (0.9344, -0.0765, 4666),
    ("same", "RECV", "RUSH"): (0.9878, -0.0228, 28499),
    ("same", "RECV", "RECV"): (0.9983, +0.0125, 30764),
    ("opp", "RUSH", "RUSH"): (0.9163, -0.0804, 5744),
    ("opp", "PASS", "PASS"): (1.0722, +0.0622, 952),
    ("opp", "PASS", "RUSH"): (0.9540, -0.0223, 4671),
    ("opp", "PASS", "RECV"): (1.0175, +0.0161, 11543),
    ("opp", "RECV", "RUSH"): (0.9950, -0.0044, 28463),
    ("opp", "RECV", "RECV"): (0.9993, +0.0107, 35147),
}
# ("same","PASS","PASS") is deliberately absent: n=140, below the script's
# 200-pair floor, so it is NOT MEASURABLE and must refuse rather than
# default. Two quarterbacks on one team is barely a real slip anyway.

# Above this deviation from independence, multiplying the de-vigged legs is
# not an approximation and no EV is reported. Set at 3% because that is
# where the EMPIRICAL GAP is: the eleven measured pairs split into five
# between 4.60% and 19.93% and six at or below 1.75%, with nothing in
# between. A round 5% would have sat inside no gap and put opposing
# PASS x RUSH (-4.60%) on the permissive side by coincidence of rounding.
# This is a threshold on measured magnitude, not a claim about any pair.
CORR_GATE_LIFT_DEV = 0.03

# The sweep's own floor, named here so the refusal text can cite it.
MIN_SWEEP_PAIRS = 200


# A pair is unordered, so the lookup sorts the two sides — which means every
# KEY must already be sorted or it is unreachable. Two were not: RECV sorts
# before RUSH, so ("same","RUSH","RECV") could never be found and the
# commonest same-game shape in this project, a back's rushing yards with a
# teammate receiver's, fell to "never measured" and refused an EV. A
# lookup-order bug reads exactly like an honest refusal, which is why this
# asserts at import rather than waiting to be noticed on a Sunday.
_unsorted = [k for k in MEASURED_PAIR_LIFT if list(k[1:]) != sorted(k[1:])]
if _unsorted:
    raise AssertionError(
        f"MEASURED_PAIR_LIFT keys must have their two sides in sorted order "
        f"or pair_lift() cannot find them: {_unsorted}")
del _unsorted


def pair_lift(relation: str, side_a: str, side_b: str):
    """(lift, r, n) for a market-side pair, or None if never measured."""
    lo, hi = sorted((side_a, side_b))
    return MEASURED_PAIR_LIFT.get((relation, lo, hi))


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
    # B59. The anchor book's OWN minimum tier in THIS pull, derived from its
    # board by `modal_liquidity()`. When set it replaces the module-level
    # OPENING_LIQUIDITY for this leg, so "at the book's minimum limits" is
    # measured per pull rather than remembered from a previous one. None
    # falls back to the constant, which is the stale-by-design path.
    opening_liquidity_tier: float | None = None
    # B75. `opening_liquidity_tier is None` was doing two jobs: "the anchor
    # book quotes no tier" and "nobody ever called `book_liquidity_tiers`".
    # `describe()` printed the FIRST as fact — and the second is what is
    # actually true on every run today, because that function has no caller
    # anywhere in the repo or the instructions, so the wrong explanation was
    # the output every time, naming Pinnacle as quoting no tier when the
    # project's own notes say it quotes a uniform one. Set this to
    # "measured" or "book quotes none" when a lookup has actually run; ""
    # means it never did. D16 aimed at one field: the unchecked state must
    # not look like the checked one.
    tier_source: str = ""

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

        B59: the threshold is now the book's OWN tier in this pull when
        `opening_liquidity_tier` is set, and only falls back to the module
        constant when it is not. That retires the stale-constant failure
        rather than postponing it — a hardcoded tier has already gone
        silent once (250 -> 500) and would again at 1,000.
        """
        if abs(float(self.fair_prob) - 0.5) > 1e-9:
            return False
        tier = (self.opening_liquidity_tier
                if self.opening_liquidity_tier is not None
                else OPENING_LIQUIDITY)
        return (self.anchor_liquidity is None
                or self.anchor_liquidity <= tier)

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
    def anchor_untested(self) -> bool:
        """At the book's opening limit, but the price HAS moved off 0.5000.

        B86. The gap between the other two flags, and the one a slip gets
        built from. `anchor_thin` fires at liquidity <= 25 and
        `anchor_opening` needs an exact 0.5000, so a line at the book's
        opening limit whose price has moved got NOTHING — and that is
        precisely the set a session selects, because moving off the prior is
        what makes a line look informative.

        Measured on a real board three days out: Pinnacle had 62 two-sided
        lines, **54 at exactly 0.5000 and all 62 at liquidity 250 against a
        derived tier of 250.** The 8 that had moved were the only ones that
        looked like prices, and a slip was built from them. The session's
        own verdict: *"I picked these three as the most favourable of 62
        lines, which is the procedure that manufactures edge from anchor
        noise."* Its sensitivity table put the whole EV there — +15.3%
        treating the anchors as accurate, **+0.2% treating them as carrying
        no information**, which lands on the measured hold band.

        RESIDUAL by construction: it excludes what the other two already
        catch. The broad version — liquidity <= tier, full stop — fires on
        **100%** of that board and is noise by B93b's standard; this fires
        on the 8, which is 13%. Both go to 0% near kickoff, when Pinnacle's
        tier is up at 1,000 with 1,000-3,000 resting. A flag that fires on
        everything gets ignored, and the point is to be readable on the one
        board where it matters.
        """
        if self.anchor_opening or self.anchor_thin:
            return False
        if self.anchor_liquidity is None:
            return False          # never reported is not the same as low
        tier = (self.opening_liquidity_tier
                if self.opening_liquidity_tier is not None
                else OPENING_LIQUIDITY)
        return self.anchor_liquidity <= tier

    @property
    def anchor_immature(self) -> bool:
        """Any way you cut it, the anchor cannot carry the weight of an EV.

        B86 added `anchor_untested`. Safe to widen here because this feeds
        `Shortlist.immature_anchors`, a REPORT, and gates no leg — and at
        slip level it names three players rather than sixty-two.
        """
        return self.anchor_opening or self.anchor_thin or self.anchor_untested

    @property
    def anchor_note(self) -> str | None:
        if self.anchor_thin:
            return (f"{self.player}: anchor liquidity is "
                    f"{self.anchor_liquidity:g} — almost no money is resting "
                    f"on this line, so its fair_prob of "
                    f"{self.fair_prob:.4f} is noise wearing a precise-looking "
                    f"number however far from 0.5000 it sits. This is the "
                    f"worst input you can hand fair_over.")
        if self.anchor_untested:
            tier = (self.opening_liquidity_tier
                    if self.opening_liquidity_tier is not None
                    else OPENING_LIQUIDITY)
            derived = ("the book's own derived tier"
                       if self.opening_liquidity_tier is not None
                       else f"the hardcoded {OPENING_LIQUIDITY:g} fallback")
            # Defensive on None even though anchor_untested guarantees it
            # is not — anchor_opening's branch already formats this way, and
            # a note that can raise turns a flag into an outage.
            lqs = ("not reported" if self.anchor_liquidity is None
                   else f"{self.anchor_liquidity:g}")
            return (f"{self.player}: fair_prob {self.fair_prob:.4f} has moved "
                    f"off 0.5000, but it sits on liquidity "
                    f"{lqs} against a tier of {tier:g} "
                    f"({derived}) — the book is still at its OPENING limit, "
                    f"so the move is a few hundred dollars of price "
                    f"discovery, not a market-tested number. This is the "
                    f"line a slip gets built from, because moving off the "
                    f"prior is exactly what makes one look informative. "
                    f"Re-pull closer to kickoff and re-price.")
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
    # B81. Pairs the table measured and found independent to within the
    # gate. A third list, because `_pair_r` now returns three different
    # answers and a MEASURED zero used to be indistinguishable from an
    # unexamined fall-through — same 0.0, same empty label. Keeping the
    # provenance here is what lets `reason` name which measurement cleared
    # each pair, instead of asserting independence in general terms.
    zeros: list[tuple] = field(default_factory=list)

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


def _clean(v) -> str:
    """Normalise a meta field to a string, treating NaN and blanks as absent.

    B73. `team` and `pos` both come from `build_meta()`, which aggregates a
    pandas frame with agg("last"), so an absent field arrives as
    float('nan') rather than None. NaN is TRUTHY, so `if not a.team` passed
    it, and `(recv.pos or "")` passed it too and then raised on `.upper()`.
    Whitespace-only values from the same join behaved the same way. Both
    fields are checked against "is this known" in `_pair_r`, and that
    question has to mean the same thing for both of them.
    """
    if v is None:
        return ""
    if isinstance(v, float) and v != v:          # NaN
        return ""
    return str(v).strip()


def _pair_r(a: BoostLeg, b: BoostLeg) -> tuple[float | None, str]:
    """Measured correlation for one pair, and why.

    Returns (0.0, "") for an established-independent pair, a non-zero r for
    a measured correlation, and (None, why) for a pair the table never
    measured — which is NOT the same as zero and must not be treated as it.
    """
    # Different games. This is the one the measurement is emphatic about,
    # and it holds whatever the markets are.
    if a.event_id != b.event_id:
        return 0.0, ("different games — measured independent, and the "
                     "measurement is emphatic about this one whatever the "
                     "markets are")

    # Same event: team decides same-side vs opposing, so an unknown team
    # makes the pair unmeasurable rather than independent.
    #
    # B73. `if not a.team` tested truthiness, which NaN defeats: `build_meta`
    # aggregates with agg("last") over a pandas frame, so an absent field
    # arrives as float('nan'), and NaN is truthy. A NaN team therefore
    # passed this guard, then failed `a.team == b.team`, and the pair was
    # routed to the OPPOSING branch — two same-team rushing legs came back
    # at -0.14 labelled "opposing rushing in one event". Not just a missed
    # refusal: a confident wrong SIGN on a pair whose team is simply
    # unknown. Whitespace did the same thing. `_clean` normalises both this
    # field and `pos` below, since they come from the same join.
    ta, tb = _clean(a.team), _clean(b.team)
    if not ta or not tb:
        missing = a.player if not ta else b.player
        return None, (f"no team known for {missing}, and these legs share "
                      f"an event — cannot tell a teammate from an opponent")

    sa, sb = MARKET_SIDE.get(a.market), MARKET_SIDE.get(b.market)
    if sa is None or sb is None:
        bad = a.market if sa is None else b.market
        return None, (f"{bad} is outside the measured correlation table "
                      f"(which was built on passing/rushing/receiving "
                      f"YARDS), and these legs share an event")

    if ta == tb:
        if {sa, sb} == {"PASS", "RECV"}:
            recv = a if sa == "RECV" else b
            # B73: `(recv.pos or "")` let a whitespace-only position through
            # to the `elif pos:` branch, which returned +0.31 labelled
            # "(   with a receiving prop, scored as WR)" — a blank where the
            # category should be, on the largest of the three coefficients.
            # Worse than the "(receiver)" label B69 removed. A NaN position
            # raised AttributeError out of classify() instead.
            pos = _clean(recv.pos).upper()
            # Three receiving pairs, not two. Asking only "is it a TE?" sent
            # every RB catching passes to the WR value — see the note on
            # SAME_TEAM_CORR_PROVISIONAL.
            #
            # B69: a MISSING position must not land on one of them. This used
            # to be `else: SAME_TEAM_CORR[("QB","WR")]` with the label
            # `pos or "receiver"`, so an empty position took the LARGEST of
            # the three values and printed "(receiver)" — which reads like a
            # category rather than like a miss. `pos` comes from
            # build_meta()'s name join, and B44 established that join is the
            # fragile link: one live payload carried both "Brian Thomas Jr."
            # and "Brian Thomas". An unmatched name therefore arrived here as
            # a confident +0.31, which is B39's shape — unchecked state
            # looking exactly like checked state.
            #
            # Eight lines above, an unknown TEAM already returns None for
            # this reasoning, and position now follows it. Note what is NOT
            # being changed: an odd but PRESENT position still resolves off
            # the MARKET. Section 30b of the suite pins that deliberately —
            # build_meta reports Travis Hunter as CB because that is his
            # nflverse primary position, while he carries a receiving prop on
            # his QB's team, and a receiving prop is evidence of a receiving
            # role whatever the roster label says. A first pass at this fix
            # refused every non-WR/TE/RB position and that check failed by
            # name, correctly: "missing" and "unmeasured but present" are
            # different states and only the first one is a miss.
            if pos == "TE":
                r, lbl = SAME_TEAM_CORR[("QB", "TE")], "TE"
            elif pos == "RB":
                r, lbl = (SAME_TEAM_CORR_PROVISIONAL[("QB", "RB_RECV")],
                          "RB receiving — PROVISIONAL, see E3")
            elif pos:
                # WR, or any other position carrying a receiving prop. The
                # label names the position so a CB or FB reading +0.31 is
                # visible rather than hidden behind the word "receiver".
                r, lbl = SAME_TEAM_CORR[("QB", "WR")], (
                    "WR" if pos == "WR" else
                    f"{pos} with a receiving prop, scored as WR")
            else:
                return None, (
                    f"no position known for {recv.player}, and these legs "
                    f"share a team — the passing x receiving correlation is "
                    f"+0.31 for a WR, +0.27 for a TE and about +0.20 for a "
                    f"back, so the pair cannot be scored without it. An "
                    f"empty position usually means the name did not join to "
                    f"nflverse; check the spelling against search_players "
                    f"before reading anything into this slip")
            return r, f"same team passing x receiving ({lbl})"
        if {sa, sb} == {"PASS", "RUSH"}:
            return SAME_TEAM_CORR[("QB", "RB")], "same team passing x rushing"
        return _from_measured("same", sa, sb, a, b)

    if sa == "RUSH" and sb == "RUSH":
        return OPPOSING_CORR[("RB", "RB")], "opposing rushing in one event"
    return _from_measured("opp", sa, sb, a, b)


def _from_measured(relation: str, sa: str, sb: str,
                   a: BoostLeg, b: BoostLeg) -> tuple[float | None, str]:
    """Resolve a pair the canonical table does not cover, off MEASURED_PAIR_LIFT.

    B81. Every non-zero branch of `_pair_r` named itself and every
    `return 0.0, ""` did not, so a MEASURED zero and an unexamined
    fall-through were the same value with the same empty label — B53's
    family, and the caller could not tell them apart. Three distinct
    answers now, each of which says which:

      * a non-zero r, when the measured deviation clears the gate
      * a LABELLED 0.0, when it is measured and inside the gate
      * None, when the pair was never measured at all

    The canonical `SAME_TEAM_CORR`/`OPPOSING_CORR` entries keep priority
    upstream of this: B68 is explicit that pasting one filter's levels over
    them is how that table became unreproducible, and E3 owns re-deriving
    it. This function only answers for the pairs they never covered.
    """
    rel_word = "same team" if relation == "same" else "opposing"
    m = pair_lift(relation, sa, sb)
    if m is None:
        return None, (
            f"{rel_word} {sa.lower()} x {sb.lower()} is not a pair this "
            f"project has measured — the full sweep could not reach "
            f"{MIN_SWEEP_PAIRS} pairs for it, so there is no number, and "
            f"independence here would be an assumption rather than a "
            f"finding ({a.player} x {b.player})")
    lift, r, n = m
    dev = abs(lift - 1.0)
    extra = (" — note E6 measured WR x WR alone at 0.9817x over 12,622 "
             "pairs; this cell is WR/TE x WR/TE, a wider population, so "
             "the two are different measurements rather than a revision"
             if (sa, sb) == ("RECV", "RECV") or (sb, sa) == ("RECV", "RECV")
             else "")
    if dev > CORR_GATE_LIFT_DEV:
        return r, (f"{rel_word} {sa.lower()} x {sb.lower()} — MEASURED "
                   f"lift {lift:.4f}x ({(lift-1)*100:+.2f}% from "
                   f"independence) over {n:,} pairs, r={r:+.4f}. Past the "
                   f"{CORR_GATE_LIFT_DEV:.0%} gate, so the product of the "
                   f"de-vigged legs is not the joint and no EV is reported")
    return 0.0, (f"{rel_word} {sa.lower()} x {sb.lower()} — MEASURED "
                 f"independent to within {dev*100:.2f}% (lift {lift:.4f}x "
                 f"over {n:,} pairs, r={r:+.4f}), inside the "
                 f"{CORR_GATE_LIFT_DEV:.0%} gate{extra}")


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

    pairs, unmeasured, zeros = [], [], []
    for a, b in combinations(legs, 2):
        r, why = _pair_r(a, b)
        if r is None:
            unmeasured.append((a.player, b.player, why))
        elif r:
            pairs.append((a.player, b.player, r, why))
        else:
            zeros.append((a.player, b.player, why))

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
        # B81. "established-independent by the measured table" was true and
        # useless: it named no measurement, so a pair cleared by a 35,147-
        # pair sweep and a pair cleared by falling through a branch read
        # identically. Each one now cites what cleared it.
        detail = "; ".join(f"{a} x {b}: {why}" for a, b, why in zeros)
        reason = (("fair joint is the product of the de-vigged legs. Every "
                   "pair is independent to within the "
                   f"{CORR_GATE_LIFT_DEV:.0%} gate, and this is the "
                   f"measurement that says so for each — {detail}")
                  if zeros else
                  "fair joint is the product of the de-vigged legs — a "
                  "one-leg slip has no pair to correlate")
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
                     reason=reason, unmeasured=unmeasured, zeros=zeros)


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
        # B119. This used to cite "0.61-0.65 on QB stacks" and claim the
        # books' factors "have tracked this table closely" on EVERY
        # correlated slip, whatever its shape. Two faults. The range is a
        # QB-stack observation and means nothing beside a backfield pair —
        # printed against a 0.921 factor on two same-team backs it invites
        # the reader to think 0.921 is generous, when the comparison is to a
        # different kind of slip. And the claim was contradicted by the slip
        # in front of it in a live round: DraftKings charged 0.686 on an
        # opposing-QB pair measured at +7.22%, against 0.672 on a true QB
        # stack measured at +31% — the same haircut for four times the
        # correlation. So the range is cited only where it was observed, and
        # the general claim is gone.
        #
        # The r values and the factor are also not the same KIND of number —
        # one is a correlation, the other a price ratio — so they are placed
        # side by side as context, never subtracted.
        _is_stack = ["passing x receiving" in why or "passing x rushing" in why
                     for *_, why in structure.pairs]
        qb_stack = all(_is_stack)
        mixed = any(_is_stack) and not qb_stack
        rs = ", ".join(f"{r:+.2f}" for *_, r, _ in structure.pairs)
        if qb_stack:
            return (f"book factor {factor:.3f}, against measured pair "
                    f"correlations of {rs}. On QB stacks specifically the "
                    f"books' factors have sat at 0.61-0.65, so this is "
                    f"roughly the going rate. Whether the correlation is "
                    f"worth MORE than that is the joint this project cannot "
                    f"compute.")
        if mixed:
            return (f"book factor {factor:.3f}, against measured pair "
                    f"correlations of {rs}. This slip mixes a QB stack with "
                    f"a pair of another shape, and the 0.61-0.65 factor "
                    f"range is a QB-stack observation only — it describes "
                    f"PART of what you are being charged for here, so do "
                    f"not read the whole factor against it.")
        return (f"book factor {factor:.3f}, against measured pair "
                f"correlations of {rs}. No factor range has been recorded "
                f"for this SHAPE — the 0.61-0.65 observation is QB stacks "
                f"only — so there is nothing here to call the price cheap or "
                f"dear against, and the joint this project cannot compute is "
                f"what would settle it.")
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
    def hold_vs_band(self) -> str | None:
        """Which side of its own band this slip's hold falls on.

        B93. `report()` printed `this slip's hold: 18.8% (reference band
        23.1%-37.2%)` — both numbers, one line apart, and no verdict. A live
        slip holding 18.79% against the same-game band was read as a +1.83%
        edge and placed. Both numbers were already on this object; what was
        missing was the sentence.
        """
        if self.slip_hold is None:
            return None
        lo, hi = self.hold_band
        if self.slip_hold < lo:
            return "below"
        if self.slip_hold > hi:
            return "above"
        return "within"

    @property
    def hold_band_note(self) -> str | None:
        """The sentence, for the cases that need one — and only those.

        B93b killed the first cut, which noted every direction including
        cross-game: a soft "this beats the population" line fired on NEARLY
        EVERY well-shopped slip, and all three cross-game slips measured in
        the 2026-11-05 session (15.1%, 14.5%, 4.9%) sat below a 17.7% floor.
        CROSS-GAME still gets no note: the measured table puts different
        events at ~0.00, so the product IS the joint there, `slip_hold` is
        exact and the band adds nothing.

        B118. The second cut was worse in a quieter way. Its loud text read
        "p_cash here is the PRODUCT of the de-vigged legs and that is not the
        joint for CORRELATED legs" — and `slip_hold` returns None unless
        `structure.priceable`, which is true only when every pair is
        MEASURED INDEPENDENT. So the note could fire only on slips where its
        own stated reason was false: wrong in 100% of reachable cases, on a
        `***` line, on the one slip in a live round of four that got an EV.
        B93b's firing-rate check missed it because it compared cross-game
        against same-game and never independent against correlated.

        What actually makes a below-band hold worth a line is the ANCHOR, not
        correlation. The band is a population figure for same-game slips; a
        priceable slip holding well under it is either a genuinely better
        price or — far more often — resting on soft fair numbers. In the live
        case all three legs were exactly 0.5000 opening priors with no
        liquidity behind them, so `p_cash` and therefore the hold were nearly
        meaningless. That is measurable, so the note says which it is instead
        of warning about correlation that the structure has already ruled out.
        """
        d = self.hold_vs_band
        if d is None or d == "within" or self.structure.cross_game:
            return None
        immature = [l.player for l in self.legs
                    if getattr(l, "anchor_immature", False)]
        if d == "below":
            if immature:
                return ("*** this slip's hold is BELOW its own same-game "
                        "band, and it rests on immature anchors — "
                        f"{', '.join(immature)}. Every pair here is measured "
                        "independent, so the product IS the joint and the "
                        "hold is arithmetically right; what is soft is the "
                        "fair numbers underneath it. A cheap-looking hold "
                        "off an opening or thin anchor is not evidence of a "
                        "good price. Re-pull closer to kickoff before "
                        "quoting the EV.")
            return ("this slip's hold is BELOW its own same-game band on "
                    "anchors that are not flagged immature. Every pair is "
                    "measured independent, so the product is the joint and "
                    "this is what a better-than-population price looks like "
                    "— the band is a population figure, this is the slip in "
                    "front of you.")
        return ("this slip's hold is ABOVE its own same-game band, which "
                "understates rather than flatters the EV — the product of "
                "the de-vigged legs is giving away edge here, so the real "
                "number is no worse than the one reported.")

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

    @property
    def tier_fallbacks(self) -> tuple[int, int]:
        """(legs on the hardcoded tier, legs total) across the shortlist.

        B59's remaining gap, made visible. `opening_liquidity_tier=None`
        silently means "use the hardcoded OPENING_LIQUIDITY", and on a live
        run that was 48 of 48 legs — every anchor was Bovada or Kalshi, and
        neither quotes a tier. "The tier was derived and agreed with the
        constant" and "no tier was available so we fell back" produce
        byte-identical output and mean entirely different things.

        That is B39's UNSCREENED lesson aimed at this field: the default
        state must not be indistinguishable from the checked one. Report
        this number whenever an EV rests on `anchor_opening`.
        """
        legs = [l for c in self.candidates for l in c.legs]
        return (sum(1 for l in legs if l.opening_liquidity_tier is None),
                len(legs))

    @property
    def tier_never_looked_up(self) -> int:
        """Legs whose tier was never looked up at all. B75."""
        return sum(1 for c in self.candidates for l in c.legs
                   if not l.tier_source)

    def describe(self) -> str:
        if not self.candidates:
            return f"NOTHING TO PRICE — {self.reason}"
        L = [f"{len(self.candidates)} candidate(s) — outlook {self.outlook}",
             f"  {self.reason}"]
        if self.immature_anchors:
            L.append(f"  opening anchors (fair_prob exactly 0.5000) on: "
                     f"{', '.join(self.immature_anchors)} — re-pull closer "
                     f"to kickoff before trusting any EV built on them")
        fb, tot = self.tier_fallbacks
        # Count the two causes rather than inferring one from the other.
        # The first cut compared `never >= fb` and then described ALL the
        # fallbacks by whichever cause won, which over-claimed on a mixed
        # shortlist — the same fault B75 is about, one level up.
        _fbl = [l for c in self.candidates for l in c.legs
                if l.opening_liquidity_tier is None]
        never = sum(1 for l in _fbl if not l.tier_source)
        asked = len(_fbl) - never
        if fb:
            # B75. Say which of the two it is. The old text asserted the
            # book quotes no tier, which was a claim about data nobody had
            # fetched, on every run.
            bits = []
            if asked:
                bits.append(f"{asked} because the anchor book quoted no "
                            f"tier when asked")
            if never:
                bits.append(f"{never} NEVER LOOKED UP — nothing called "
                            f"book_liquidity_tiers(), so that part is not a "
                            f"finding about any book")
            L.append(f"  anchor tier: {fb} of {tot} leg-slots are on the "
                     f"hardcoded {OPENING_LIQUIDITY:g} — "
                     + "; ".join(bits)
                     + ". `anchor_opening` on those is only as current as "
                       "that constant.")
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
                  market_hold: float = 0.39,
                  fair_prob: float | None = None) -> dict:
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
    # B95. `implied(odds)/(1+hold)` assumes this leg carries the FIELD'S
    # AVERAGE margin. Measured on a live First TD board, per-leg margins ran
    # +0.01pp to -3.52pp inside ONE game: Chase Brown's BetMGM +525 carried
    # almost none, so the uniform derivation put him 24% low and his $10
    # token at $3.29 instead of $5.47. The error has a direction — the
    # better you shopped a leg, the more it understates you — so a measured
    # per-leg fair probability must override the derivation when there is
    # one.
    d = to_decimal(odds)
    if fair_prob is None:
        p = implied(odds) / (1.0 + float(market_hold))
        p_source = (f"derived from a uniform {float(market_hold):.1%} hold, "
                    f"so it assumes this leg carries the field's average "
                    f"margin — measured per-leg margins varied by 3.5pp "
                    f"inside one board, see B95")
    else:
        p = float(fair_prob)
        if not 0.0 < p < 1.0:
            raise ValueError(
                f"fair_prob={fair_prob} is not a probability in (0,1). This "
                f"is a de-vigged per-leg number, not a price and not a "
                f"percentage — refused rather than clamped, because a "
                f"clamped 1.0 would silently report the EV of a certainty.")
        # B99b. `market_hold` is INERT once fair_prob is given, and it used
        # to be silently inert: a session headlined "measured hold, not the
        # default" and then found the figure identical at every hold from
        # 0.10 to 0.542. Say so in the result.
        p_source = (f"measured (fair_prob given, so market_hold "
                    f"{float(market_hold):.1%} was NOT used)")
    base = p * (d - 1.0) * stake - (1.0 - p) * stake
    refund = (1.0 - p) * stake * float(bonus_value)
    return {"odds": float(odds), "p_true": p, "stake": float(stake),
            "bonus_value": float(bonus_value), "market_hold": float(market_hold),
            "p_source": p_source, "fair_prob": fair_prob,
            "base_ev": base, "refund_ev": refund, "ev": base + refund,
            "roi": (base + refund) / stake}


def stake_back_band(odds: float, *, stake: float = 10.0,
                    market_hold: float = 0.39,
                    fair_prob: float | None = None) -> dict:
    """`stake_back_ev` across a pessimistic/central/optimistic bonus value.

    Never quote a stake-back token as one number. `bonus_value` is an
    assumption, not a measurement, and it moves the answer about three times
    as much as picking a longer leg does.

    The 0.58/0.65/0.71 band is derived from a real First TD board rather
    than guessed — see `stake_back_ev`. The first version used
    0.60/0.70/0.80, whose top end this market cannot reach.
    """
    # B95. Must pass fair_prob through, or the band silently reverts to the
    # uniform-hold derivation the caller just overrode — three numbers that
    # look like the measured ones and are not.
    return {lab: stake_back_ev(odds, stake=stake, bonus_value=v,
                               market_hold=market_hold, fair_prob=fair_prob)
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
                # B93. Both numbers were already printed, one line apart,
                # with no verdict — and a slip holding 18.79% against the
                # same-game band got read as a +1.83% edge and placed. A
                # note that stays on the object is a note nobody reads.
                if c.hold_band_note:
                    out.append(f"  {c.hold_band_note}")
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
