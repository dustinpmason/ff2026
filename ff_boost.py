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

import math
import re
from statistics import NormalDist
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

# Leg count of each SGP_FACTORS_OBSERVED row, in order, from the comments
# beside them; None where the sitting did not record it.
SGP_FACTORS_OBSERVED_LEGS = (3, 3, 3, 3, None, None, None, None,
                             3, 3, 3, 3, 2)

# Second live run, event 53178, 2026-11-11 ~14:48Z: (book, quote / ENGINE
# product, quote / that book's own independent price). Five slips, every
# quote returned. Kept as its own tuple because it carries the BOOK and two
# ratios per quote, which the older list does not. The sportsbook rows feed
# the same-game price target through `sportsbook_factors()`; the target is
# the LOWER QUARTILE of those (B161), because a median would have put 11 of
# the 23 sportsbook quotes on record under the floor. Novig is an exchange,
# is the source of most of the >1.0 values, and is excluded.
# Live run 3A, same event, 2026-11-11 ~18:41Z: 13 slips, 32 quotes, same
# three columns. With these in hand the factor is plainly a property of the
# BOOK: lower quartile 0.83 at BetMGM (n=14), 0.93 at DraftKings (n=18),
# 0.91 at FanDuel (n=8). They feed the target PER BOOK through
# `factors_by_book()` (B167); pooling would aim a BetMGM slip too low and a
# DraftKings slip too high.
SGP_FACTORS_LIVE_20261111_3A = (
    ("draftkings", .9341, .9341), ("novig", 1.0381, 1.0013),
    ("fanduel", .9732, .9599), ("draftkings", .9658, .9658),
    ("novig", 1.1209, .9773), ("draftkings", .9449, .9449),
    ("betrivers", .9449, .9957), ("novig", 1.0171, 1.0553),
    ("draftkings", .9260, .9260), ("betrivers", .9681, 1.0004),
    ("novig", 1.0925, 1.1054), ("draftkings", .9268, .9268),
    ("novig", .9848, 1.0193), ("draftkings", .9502, .9502),
    ("fanduel", .9650, .9711), ("draftkings", .9513, .9513),
    ("novig", 1.1550, 1.1227), ("fanduel", .9658, .9385),
    ("draftkings", .9514, .9514), ("novig", 1.0796, 1.0362),
    ("draftkings", .9708, .9708), ("novig", 1.1146, 1.1368),
    ("fanduel", 1.0461, .9294), ("draftkings", .9347, .9347),
    ("novig", 1.1278, 1.0169), ("draftkings", .9352, .9352),
    ("novig", 1.0674, .9887), ("draftkings", .9385, .9385),
    ("novig", 1.0829, 1.0396), ("fanduel", .8955, 1.0123),
    ("draftkings", .9508, .9508), ("novig", 1.1217, 1.2292),
)

# Game-day run 2, event 53178, 2026-11-12 ~17:30Z: 64 quotes at the three
# books Dustin's boosts sit at. (book, LEGS IN THE SLIP, quote / engine
# product, whether the engine could measure the slip). Two things this run
# showed that the earlier tuples could not carry:
#   - LEG COUNT matters (B179). BetMGM's measurable 2-leg slips came in at
#     0.93-1.04 of the product, its 3-leg slips at 0.73-0.99.
#   - Slips the engine REFUSES (anti-correlated pairs) are quoted ABOVE the
#     product (B181): FanDuel 0.95-1.09, BetMGM up to 1.36. They can never
#     be a qualifier, so they must not set the target for slips that can;
#     pooled in, they would aim every product too low.
# DraftKings missed its minimum on 9 of 18 here against a predicted one in
# four: its measurable 3-leg lower quartile was 0.889 against the 0.934 the
# target then used.
SGP_FACTORS_LIVE_20261112 = (
    ("draftkings", 3, 0.909, True), ("draftkings", 3, 0.950, True), ("draftkings", 3, 0.965, True),
    ("draftkings", 3, 0.858, True), ("draftkings", 3, 0.943, True), ("draftkings", 3, 0.891, True),
    ("draftkings", 3, 1.017, False), ("draftkings", 3, 1.008, False), ("draftkings", 3, 0.953, False),
    ("draftkings", 3, 0.906, False), ("fanduel", 3, 1.061, False), ("fanduel", 3, 1.088, False),
    ("fanduel", 3, 1.053, False), ("fanduel", 3, 0.946, False), ("fanduel", 3, 1.066, False),
    ("fanduel", 3, 1.080, False), ("fanduel", 3, 1.021, False), ("fanduel", 3, 1.064, False),
    ("fanduel", 3, 0.977, True), ("fanduel", 3, 0.865, True), ("fanduel", 3, 0.896, True),
    ("fanduel", 3, 0.946, True), ("fanduel", 3, 0.943, True), ("fanduel", 3, 1.004, True),
    ("fanduel", 3, 0.938, True), ("fanduel", 3, 0.961, True), ("betmgm", 2, 1.098, False),
    ("betmgm", 2, 1.012, False), ("betmgm", 2, 1.132, False), ("betmgm", 2, 1.272, False),
    ("betmgm", 2, 0.933, True), ("betmgm", 3, 0.815, True), ("betmgm", 3, 0.734, True),
    ("betmgm", 3, 1.356, False), ("betmgm", 3, 1.207, False), ("betmgm", 3, 0.810, True),
    ("betmgm", 3, 0.885, True), ("betmgm", 3, 0.699, False), ("betmgm", 3, 0.973, True),
    ("betmgm", 2, 0.986, True), ("betmgm", 2, 1.008, True), ("betmgm", 2, 1.022, True),
    ("betmgm", 2, 0.948, True), ("betmgm", 2, 0.934, True), ("betmgm", 2, 1.038, True),
    ("betmgm", 2, 1.001, True), ("betmgm", 2, 0.979, True), ("betmgm", 3, 0.969, True),
    ("betmgm", 3, 0.990, True), ("betmgm", 3, 0.967, True), ("betmgm", 3, 0.916, True),
    ("betmgm", 3, 0.956, True), ("betmgm", 3, 0.896, True), ("betmgm", 3, 0.922, True),
    ("betmgm", 3, 0.969, True), ("draftkings", 3, 0.864, True), ("draftkings", 3, 0.920, True),
    ("draftkings", 3, 0.892, True), ("draftkings", 3, 0.888, True), ("betmgm", 2, 0.971, True),
    ("draftkings", 3, 0.886, True), ("draftkings", 3, 0.910, True), ("draftkings", 3, 0.902, True),
    ("draftkings", 3, 0.908, True),
)

SGP_FACTORS_LIVE_20261111 = (
    ("fanduel", 0.8630, 0.9243), ("draftkings", 0.8994, 0.9211),
    ("fanduel", 0.9251, 0.9730), ("draftkings", 0.9529, 0.9549),
    ("betrivers", 0.9101, 1.0047), ("novig", 1.0364, 0.9938),
    ("fanduel", 0.9186, 0.9684), ("draftkings", 0.9422, 0.9462),
    ("novig", 1.0814, 1.1050), ("draftkings", 0.9413, 0.9413),
    ("novig", 1.1355, 1.0959), ("draftkings", 0.8987, 0.9182),
    ("betmgm", 1.0212, 1.0575), ("novig", 1.1569, 1.0551),
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

# F15. How far the model must sit BELOW the fair line before it counts as
# preferring the other side of a leg. A fair line and a model estimate differ
# by a point or two on almost every leg, so a bare sign test would flag half
# a slip and mean nothing.
#
# 3pp is deliberately well inside what matters: the Week 9 Tez Johnson case,
# the one this exists to catch, ran far wider than that — the engine liked
# the OVER and the slip took the UNDER. The gate is there to silence noise,
# not to be a close call. B128 is the reason it is not set tighter: the
# model's own level error against a sharp anchor measured sd 11.5pp, so
# anything under a few points is not a disagreement worth reporting.
MODEL_SIDE_GATE = 0.03

# Measured over 43,228 same-game pairs, 2025-26. Everything absent is ~0.00,
# INCLUDING WR x WR on the same team (+0.00 over 2,970 pairs) — target
# competition cancels out team volume. Do not limit slips to stack shapes.
# E3, signed off 2026-11-10. These were four literals whose method was gone
# and which a 2026-11-05 sweep found unreproducible. They now come from
# `ff_correlation.RECORDED_MARKET` — the MARKET quantity, one market against
# another, measured on one documented filter with a pair count and a 95%
# interval per entry. `ff_guillotine` keeps the FANTASY-POINTS table, which
# is a different quantity and is allowed to differ.
#
# Four of the five old values sat OUTSIDE the measured interval, every one
# overstating the magnitude:
#
#     ("QB","WR")       +0.31  ->  +0.2614   CI +0.241..+0.282   n=7,891
#     ("QB","TE")       +0.27  ->  +0.2149   CI +0.185..+0.245   n=3,935
#     ("QB","RB")       -0.10  ->  -0.0755   CI -0.104..-0.047   n=4,737
#     ("QB","RB_RECV")  +0.20  ->  +0.1705   CI +0.142..+0.198   n=4,649
#     ("RB","RB") opp   -0.14  ->  -0.0793   CI -0.105..-0.054   n=5,795
#
# The swap changes the reported `r` and `factor_note`, NOT any EV: a
# correlated pair makes a slip unpriceable whatever `r` is, verified by
# classifying one QB-stack slip under both tables and getting identical
# `priceable` and `independent_odds`. Re-derive with
# `python3 ff_correlation.py`.
from ff_correlation import (RECORDED_MARKET as _RM,
                            RECORDED_MARKET_SIDE as _RMS,
                            SIDE_SPEC as _SIDE_SPEC)

SAME_TEAM_CORR = {k: _RM[k][0] for k in (("QB", "WR"), ("QB", "TE"),
                                         ("QB", "RB"))}
OPPOSING_CORR = {("RB", "RB"): _RM[("RB", "RB")][0]}

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
# No longer provisional, and no longer a ratio applied to a literal: E3
# measured QB passing x RB RECEIVING directly at +0.1705 (n=4,649,
# CI +0.142..+0.198), on the same filter as every other entry.
SAME_TEAM_CORR_PROVISIONAL = {("QB", "RB_RECV"): _RM[("QB", "RB_RECV")][0]}

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
    # F13. Added once E3 made the table reproducible and
    # `market_side_table()` measured the cells. RECEPTIONS is deliberately
    # its OWN side and not folded into RECV: same-team PASS x RECEPTIONS is
    # +0.1774 (n=16,510) against PASS x RECV at +0.2456, so mapping a
    # receptions leg to the receiving side overstates it by about 28%.
    "player_receptions": "RECEPTIONS",
    "player_anytime_td": "TD",
    # Added 2026-11-10 from the first live board, which carries
    # `player_pass_tds` with 232 outcomes. It was deliberately absent until
    # a real board named it: a guessed key refuses exactly like a measured
    # refusal (B39), so the string had to come off a board rather than out
    # of a plausible guess. Five cells reach it, including same-team
    # PASS_TD x TD at +0.2173 over 13,100 pairs.
    #
    # NOT the three neighbours on the same board. `player_reception_tds`,
    # `player_rush_tds` and `player_pass_rush_reception_tds` are different
    # markets with no measured cells of their own, and folding any of them
    # into TD would be the RECEPTIONS-into-RECV mistake again.
    "player_pass_tds": "PASS_TD",
}

# Sides that `_RMS` has measured but no market string has been seen for.
# A side belongs here, NOT in MARKET_SIDE, until a live board names its
# key: a guessed key never matches and so refuses exactly like a measured
# refusal, which is B39's shape. PASS_TD sat here until 2026-11-10, when
# the first live run returned `player_pass_tds`.
# Empty as of 2026-11-10: `player_pass_tds` came off a live board and
# PASS_TD is mapped. Kept as the place the next such side goes, and as the
# reason `MARKET_SIDE` is allowed to be narrower than `_RMS`.
SIDES_MEASURED_NO_MARKET_KEY: tuple = ()

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
    "PRICE IT": "Rare. The measured hold band does not describe this slip "
                "(its own P(cash) implies a hold worse than the band's "
                "worst case) AND it is still positive at the full product "
                "price, which takes a large boost. No anticipated ROI is "
                "reported. A real quote from price_sgp decides it. A slip "
                "the band does not describe that LOSES at its product price "
                "is NEGATIVE, not this.",
    "ESTIMATE ONLY": "Correlated legs where the product slightly OVERSTATES "
                     "the joint, by less than the noise the product already "
                     "carries. P(cash) and EV are reported but are "
                     "OPTIMISTIC by about the stated joint error — the "
                     "opposite of a floor. Subtract it before comparing.",
    "BELOW MINIMUM": "The price is under the minimum odds this slip was "
                     "built for, so the boost cannot be applied. Says "
                     "nothing about its EV.",
    "FLOOR ONLY": "Correlated legs whose measured correlation BOUNDS the "
                  "joint instead of destroying it. P(cash) and EV are a "
                  "lower bound, not an estimate; the slip can only be "
                  "better than it reads. Read the joint-error line for "
                  "which direction the bound runs.",
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
    # B126. WHICH SIDE the verdict was computed for. `boost_verdict` vetoes
    # "a role change running against THE SIDE BEING BET" (B80), so a verdict
    # for the UNDER says nothing whatever about the OVER — and until now
    # nothing recorded the difference. A live session computed one verdict
    # per LINE and attached it to whichever side it was betting, which
    # nearly shipped Cade Otton OVER with his targets collapsed 5.4 -> 1.5:
    # COLLAPSED against the OVER is a VETO, and it had been carried across
    # as a CAUTION. Rebuilding per-side cut both ways — it also UN-vetoed
    # Loveland's OVER, which the same error had wrongly excluded.
    verdict_side: str = ""
    # F15. The MODEL's probability FOR THE SIDE ON THIS LEG, so a slip can
    # be told that the engine wants the other side of a leg you are betting.
    # `verdict` does not carry this: boost_verdict answers "does anything
    # argue against this side", and CLEAR means nothing was found against it,
    # not that the model prefers it. On the Week 9 slate the engine preferred
    # the OVER on Tez Johnson while the slip took the UNDER; every leg read
    # CLEAR, because CLEAR was the right answer to the question being asked
    # and nobody was asking this one.
    #
    # None means NOT SUPPLIED, which is a different state from "the model is
    # indifferent" and is reported as such rather than passing silently.
    model_p: float | None = None
    team: str | None = None
    pos: str | None = None
    # Liquidity on the ANCHOR's line, not on the book you are betting. It
    # is what says whether fair_prob is a settled number or an opening one.
    # Present on live get_odds (Pinnacle 250 on an opening board, rising to
    # 5,000-10,000 by kickoff); absent on Bovada, which returns null.
    # F12. Which KIND of line this is: "main", "alternate" or "milestone".
    # Default "main" because that is the only kind the pipeline could build
    # until now, and because a rung has to declare itself — B128 established
    # that a rung's fair is good for price selection and market-vs-market
    # gaps but NOT for a model-vs-market edge, and nothing downstream can
    # honour that distinction if it cannot see which legs are rungs.
    line_type: str = "main"
    # F12. For a rung, the fair is built from TWO books: the LEVEL comes
    # from the anchor's own two-sided main line and the SHAPE comes from the
    # ladder, which is usually the book being bet. Those are different kinds
    # of dependence and the old single `fair_source` string could not tell
    # them apart, so `circular` read "draftkings" out of
    # "level pinnacle, shape draftkings ladder" and dropped every DK rung at
    # intake — silently, and looking exactly like "F12 does not work".
    #
    # Set BOTH for a rung. Leaving them empty means "the whole fair came
    # from fair_source", which is the main-line case and keeps `circular`
    # answering exactly as it did.
    level_source: str = ""
    shape_source: str = ""
    # For a rung: the ANCHOR's de-vigged fair at the point the level was
    # pinned to. `anchor_opening` asks whether the anchor is sitting on an
    # exact 0.5000, and a rung's own `fair_prob` is never that — it is some
    # point out on the ladder — so without this the question was being put
    # to the wrong number and could not come back yes. None for a main
    # line, where `fair_prob` IS the anchor's fair.
    anchor_level_fair: float | None = None
    # B158. One standard deviation on THIS leg's fair, when the machinery
    # that produced it measured one. A rung's comes from `ladder_fair`
    # (margin scatter, interpolation, the cross-book check) and is wider
    # than a main line's, most of all in the tail; None means "not carried",
    # and the board-level figure from `fair_uncertainty` is used instead.
    fair_sd: float | None = None
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
        # B126. A verdict with no side recorded, or recorded for the OTHER
        # side, is refused at construction. Refused rather than flagged
        # because the failure is silent by nature: COLLAPSED + OVER is a
        # VETO and COLLAPSED + UNDER is support, so a carried-across verdict
        # does not look wrong — it looks like a screened leg.
        if self.verdict and self.verdict != "UNSCREENED":
            vs = (self.verdict_side or "").upper()
            if not vs:
                raise ValueError(
                    f"{self.player}: verdict {self.verdict!r} was given with "
                    f"no verdict_side. boost_verdict() judges a role change "
                    f"against THE SIDE BEING BET (B80), so a verdict is "
                    f"about one side and is meaningless without it. Pass "
                    f"verdict_side= the side you evaluated — and if that is "
                    f"not the side on this leg, evaluate the right one with "
                    f"ff_props.prop_edge(..., side=...).")
            if vs != str(self.side).upper():
                raise ValueError(
                    f"{self.player}: this leg is {self.side} but its verdict "
                    f"was computed for {vs}. A verdict does NOT carry across "
                    f"sides — a collapsed role vetoes the OVER and supports "
                    f"the UNDER. Re-evaluate with "
                    f"ff_props.prop_edge(est, ..., side={str(self.side).upper()!r}) "
                    f"and pass that Edge to boost_verdict().")
        if self.model_p is not None:
            mp = float(self.model_p)
            if mp > 1.0:
                raise ValueError(
                    f"{self.player}: model_p={self.model_p!r} looks like a "
                    f"percentage. Pass a probability in (0, 1) — 0.72, not "
                    f"72. A percentage here makes the model prefer every "
                    f"side of every leg.")
            if not 0.0 < mp < 1.0:
                raise ValueError(
                    f"{self.player}: model_p must be strictly between 0 and "
                    f"1, got {self.model_p!r}. Use None for 'not supplied' — "
                    f"a 0 or a 1 is a certainty nobody has.")
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
    def model_gap(self) -> float | None:
        """model_p − fair_prob for the side on this leg, or None.

        Positive means the model likes the side being bet; negative means it
        is AGAINST it. Negative is not the same as the leg being bad — a
        −0.01 gap is inside anybody's noise — so `model_against` applies a
        threshold rather than testing the sign.
        """
        if self.model_p is None:
            return None
        return float(self.model_p) - float(self.fair_prob)

    @property
    def model_against(self) -> bool | None:
        """True when the model prefers the OTHER side of this leg.

        None means no `model_p` was supplied, reported as unknown rather than
        as agreement — D16/B39's rule that an unchecked state must not look
        like a checked one. `verdict == "CLEAR"` is exactly that trap here:
        it means nothing was found AGAINST this side, not that the model
        wants it.
        """
        g = self.model_gap
        if g is None:
            return None
        return g < -MODEL_SIDE_GATE

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
        lvl = (self.anchor_level_fair if self.anchor_level_fair is not None
               else self.fair_prob)
        if abs(float(lvl) - 0.5) > 1e-9:
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
        """True when the fair's LEVEL came from the book being bet.

        A book de-vigged against itself is that book's opinion of itself.
        The instructions forbid it on a single prop; it is no more valid
        inside a slip. This is the disqualifying kind and `_intake` drops
        on it.

        F12: where `level_source` is set the level is the only part that
        counts here, because a rung's level comes from an independent
        anchor while its shape comes from the ladder. `shape_circular`
        below is the weaker kind, which is reported rather than dropped.
        """
        if self.level_source:
            return self.book.lower() in str(self.level_source).lower()
        return self.book.lower() in str(self.fair_source).lower()

    @property
    def shape_circular(self) -> bool:
        """True when the fair's SHAPE came from the book being bet.

        NOT a refusal, and not nothing either. For a rung priced off its own
        book's ladder, the level is pinned to an independent anchor but the
        CURVE between rungs is this book's. So "is this rung cheap" is
        answerable relative to the book's other rungs — F12's actual
        purpose, where the shared shape cancels — while "does this rung beat
        the market" partly assumes the shape it is testing.

        Pinnacle posts no ladders at all, so there is no second opinion on
        the shape to measure this against on most boards; `ladder_fair`
        labels its uncertainty a LOWER BOUND in that case. Reported on the
        leg and in the report, because silently absorbing it is the one
        thing the pinning design is most likely to hide.
        """
        return (bool(self.shape_source)
                and self.book.lower() in str(self.shape_source).lower())

    @property
    def is_rung(self) -> bool:
        return str(self.line_type or "main").lower() in ("alternate",
                                                         "milestone")

    def as_quote(self) -> dict:
        """The leg as a quote dict, for `canonical_bet` / `same_bet`.

        B50/B129's merge point. A rung at N is exactly "over N - 0.5", and
        `canonical_bet` does that subtraction — so a leg carries its line in
        `line` and lets the canonical function do the arithmetic rather than
        doing it here in a second place.
        """
        return {"player": self.player, "market": self.market,
                "line": self.line, "player_id": self.player_id}

    def describe(self) -> str:
        ln = f" {self.line}" if self.line is not None else ""
        s = (f"{self.player} {self.market}{ln} {self.side} "
             f"{self.odds:+.0f} @{self.book}")
        if self.is_rung:
            # Named on the leg, not only in a note. A rung and a main line
            # read identically once the threshold has been canonicalised to
            # N - 0.5, and the two are priced by different machinery with
            # different standing (B128).
            s += f"  [{self.line_type} rung, posted as {self.line + 0.5:g}+]"
        return s


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
    # F13. (player_a, player_b) -> (lo, hi) for each measured pair that
    # carries one. Kept OUT of the `pairs` tuples on purpose: one caller
    # unpacks those as `*_, r, why`, so appending a fifth element would
    # silently shift `r` onto the label. A separate map changes nothing for
    # existing readers and gives `joint_error` the interval it needs to know
    # a pair's SIGN rather than assume it.
    pair_cis: dict = field(default_factory=dict)

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


def side_pair(relation: str, side_a: str, side_b: str):
    """(r, n, ci) from E3's market-side table, or None if never measured.

    This is the F13 table — 40 cells with confidence intervals — and it is
    consulted only for pairs `MEASURED_PAIR_LIFT` does not cover. The
    canonical lift table keeps priority where it has an entry, because B68
    is explicit that pasting one filter's levels over another's is how the
    original table became unreproducible.
    """
    lo, hi = sorted((side_a, side_b))
    e = _RMS.get((relation, lo, hi))
    if e is None:
        return None
    return float(e[0]), int(e[1]), (float(min(e[2])), float(max(e[2])))


def _pair_r_ci(a: BoostLeg, b: BoostLeg) -> tuple[float | None, str, tuple | None]:
    """`_pair_r` plus the pair's confidence interval where one was measured.

    `_pair_r` keeps its two-value signature — it is called directly in the
    suite and the interval is not part of the question it answers. The
    interval matters to `joint_error`, which needs a SIGN it can trust and
    must not take one from a cell whose interval spans zero.
    """
    r, why = _pair_r(a, b)
    if r is None or not r:
        return r, why, None
    ta, tb = _clean(a.team), _clean(b.team)
    sa, sb = MARKET_SIDE.get(a.market), MARKET_SIDE.get(b.market)
    if a.event_id != b.event_id or not ta or not tb or sa is None or sb is None:
        return r, why, None
    m = side_pair("same" if ta == tb else "opp", sa, sb)
    if m is None:
        return r, why, None
    _r, _n, ci = m
    # The canonical lift table and the side table are DIFFERENT
    # measurements of the same pair. The first live run found how fragile
    # the old rule was: QB x WR receiving uses r=+0.2614 from the lift
    # table and the interval (+0.2286, +0.2625) from `_RMS`, whose own
    # point estimate is +0.2456 — so the interval bracketed the r it was
    # being attached to BY 0.0011. One re-measurement of either table and
    # that slip silently loses its interval, which changes what
    # `joint_error` will take a sign from.
    #
    # So the interval is WIDENED to cover both measurements rather than
    # tested against one of them. Two tables disagreeing about a pair IS
    # uncertainty about that pair, and hiding it behind a bracket test that
    # passes by a thousandth was pretending otherwise. Scored at the
    # pessimistic end as always, this can only make the gate more
    # conservative, never less.
    both, widened = _widen_interval(ci, r, _r)
    if widened:
        why += (f" [interval widened to {both[0]:+.4f}..{both[1]:+.4f} to "
                f"cover both tables' estimates: lift r={r:+.4f} vs "
                f"market-side r={_r:+.4f}]")
    return r, why, both


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
        # F13. The lift sweep never reached this pair; the market-side
        # table may still have measured its CORRELATION. A lift is a
        # joint-crossing quantity and does not transfer to a binary market
        # (a TD has no threshold to cross), but r does, and the gate is now
        # computed from r rather than from lift. So an r here is a real
        # answer where a missing lift used to be a refusal.
        sp = side_pair(relation, sa, sb)
        if sp is not None:
            r, n, ci = sp
            return r, (f"{rel_word} {sa.lower()} x {sb.lower()} — MEASURED "
                       f"r={r:+.4f} over {n:,} pairs, 95% CI "
                       f"{ci[0]:+.4f}..{ci[1]:+.4f} (E3's market-side "
                       f"table; no joint-crossing lift for this pair, so "
                       f"the slip's joint error is computed from r)")
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


def classify(legs, meta=None, aliases=None, quotes=None) -> Structure:
    """Derive the structure FROM THE LEGS. Never takes a caller's word."""
    legs = list(legs)
    # B127. This compared RAW NAMES, the join this project forbids
    # everywhere else (B44, B68b, and normalize_name's own docstring). A
    # live slip carried "Luther Burden III" from FanDuel's milestone board;
    # a main line reads "Luther Burden". Two legs on one man, two
    # spellings, and `classify` returned priceable=True with a reason
    # asserting "every pair is independent to within the 3% gate".
    #
    # The worst shape it let through cannot cash at all: OVER 75.5 and
    # UNDER 50.5 on the same receiver is an empty event, priced as if it
    # had a probability. Anything milder — OVER 50.5 with UNDER 75.5 — is
    # a band, where the joint is nothing like the product.
    #
    # `norm_player` already existed and already agreed the two spellings
    # are one man.
    keyed = [(norm_player(l.player) or l.player, l) for l in legs]
    seen: dict[str, BoostLeg] = {}
    for k, l in keyed:
        if k in seen:
            a, b = seen[k], l
            raise ValueError(
                f"{a.player!r} and {b.player!r} are the same player "
                f"({k!r}) and both appear in this slip — "
                f"{a.side} {a.line} and {b.side} {b.line}. Two legs on one "
                f"man are not independent and most books will not combine "
                f"them; opposite sides at different lines may not even be "
                f"possible together. The spellings differ, which is why "
                f"this was reached by normalising rather than by matching "
                f"the names.")
        seen[k] = l

    # B50/B127. `canonical_bet` was wired in here first and then removed:
    # its key is (player, market, "over", threshold), so two legs sharing a
    # canonical key MUST be the same player, which the guard above has
    # already refused. The block could not fire on any input, and a guard
    # whose removal changes nothing reads as coverage (lesson 64). B50's
    # concern — a rung and a main line being the same wager — is real and
    # is covered by that guard, since both legs name one man.
    #
    # What the name guard CAN miss is the same player under names that
    # normalise differently: "Cam Ward" and "Cameron Ward" are one man and
    # two keys. The ids catch that when both legs carry one.
    ids: dict[str, BoostLeg] = {}
    for l in legs:
        pid = getattr(l, "player_id", None)
        if not pid:
            continue
        if pid in ids:
            a = ids[pid]
            raise ValueError(
                f"{a.player!r} and {l.player!r} carry the SAME player_id "
                f"({pid}) and both appear in this slip — {a.side} {a.line} "
                f"and {l.side} {l.line}. Two legs on one man are not "
                f"independent, and opposite sides at different lines may "
                f"not be possible together at all. The names normalise "
                f"differently, so only the id caught this.")
        ids[pid] = l

    if meta:
        for l in legs:
            if l.team is None or l.pos is None:
    # Normalised, not raw, and `aliases` for the rest. A raw
                # lookup misses, team comes back None, and the pair drops
                # to INDEPENDENT with no flag: a correlated slip priced as
                # an uncorrelated one, which is the quietest way this
                # project can be wrong. `_meta_lookup` is explicit about
                # which name differences it can and cannot close.
                l.team, l.pos = _meta_lookup(l.player, meta, aliases)

    pairs, unmeasured, zeros, pair_cis = [], [], [], {}
    for a, b in combinations(legs, 2):
        r, why, ci = _pair_r_ci(a, b)
        if r is None:
            unmeasured.append((a.player, b.player, why))
        elif r:
            pairs.append((a.player, b.player, r, why))
            if ci is not None:
                pair_cis[(a.player, b.player)] = ci
        else:
            zeros.append((a.player, b.player, why))

    # B156. The per-pair gate clears a pair whose measured lift is within
    # 3% of 1, and F13's own finding was that a per-pair gate cannot bound
    # a SLIP: the deviations add. A back beside three same-team receivers
    # is six cleared pairs summing to about -4.2%, against 3.2% of noise —
    # every pair "independent", the slip not. So the cleared pairs' measured
    # lifts are summed, and when the total says the product OVERSTATES the
    # joint by more than the noise it already carries, those pairs stop
    # being zeros and are scored like any other measured pair. Positive or
    # small totals change nothing: the conservative direction needs no
    # gate, and inside the noise there is nothing to act on.
    if zeros and not unmeasured:
        drift, promote = _zero_drift(legs, zeros)
        if drift < 0 and promote:
            # B170. With `quotes` the noise is MEASURED off the board (two
            # books on the same leg); without them it is the fallback, and
            # on real legs this comparison has come within 0.05pp. Pass the
            # flattened get_odds quotes wherever a slip like this is scored.
            try:
                noise, _nwhy = product_noise(legs, quotes)
            except Exception:
                noise, _nwhy = 0.0, ""
            if noise > 0 and abs(drift) > noise:
                keep = []
                names = {(a, b) for a, b, _r in promote}
                for a_name, b_name, why in zeros:
                    if (a_name, b_name) in names:
                        r = next(r for a, b, r in promote
                                 if (a, b) == (a_name, b_name))
                        pairs.append((
                            a_name, b_name, r,
                            why + f" — but this slip's cleared pairs sum to "
                                  f"{drift:+.2%}, past the {noise:.2%} of "
                                  f"noise the product carries ({_nwhy}), "
                                  f"so they are scored rather than waved "
                                  f"through (B156)"))
                    else:
                        keep.append((a_name, b_name, why))
                zeros = keep

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
        # Deliberately says nothing about whether an EV is reported. It
        # used to assert "no EV is reported", and F13 made that false while
        # leaving the sentence in place two lines above a printed EV floor.
        # Whether a floor exists is `Candidate.floor`'s answer, and this
        # text is not the place to pre-empt it.
        reason = (f"The product is NOT the joint: {detail}. Whether that "
                  f"leaves a usable bound is a separate question — see the "
                  f"joint-error line. Either way it is not a verdict "
                  f"against the slip: the measured same-game hold was "
                  f"measured on INDEPENDENT legs and does not apply here.")
    else:
        detail = "; ".join(f"{a} x {b}: {why}" for a, b, why in unmeasured)
        reason = (f"NOT priceable: {detail}. Independence here would be an "
                  f"assumption, not a measurement, and assuming it is what "
                  f"hands a correlated slip an EV it should never get.")
    return Structure(kind=kind, pairs=pairs, priceable=priceable,
                     reason=reason, unmeasured=unmeasured, zeros=zeros,
                     pair_cis=pair_cis)


# ---------------------------------------------------------------------------
# F13 — what a measured correlation COSTS the product, and which way
# ---------------------------------------------------------------------------
#
# `classify` answers "is the product the joint". For a correlated slip the
# answer is no, and until now that was the end of it: no P(cash), no EV,
# whatever the size of the correlation. That refusal is right for an
# UNMEASURED pair and far too blunt for a measured one, which is the whole
# of F13: once a pair has a number, the product's error has a number too,
# and a number can be reported instead of a refusal.
#
# THE ARITHMETIC. Under a Gaussian copula each leg fires when its latent
# Z clears z_i = PHI^-1(1 - p_i). To first order in the correlations, the
# orthant probability is
#
#     P(all) ~ (PROD p_i) * (1 + SUM_{i<j} r_ij * phi(z_i) phi(z_j) / p_i p_j)
#
# so the RELATIVE error of the independent product is the second term, and
# it is ADDITIVE OVER PAIRS. That additivity is the finding: a per-pair gate
# cannot bound a slip, because three pairs each just inside a 3% gate stack.
# Verified against antithetic Monte Carlo over a swept range in section 73,
# and it holds far better than a first-order expansion has any right to:
# across r from 0.03 to 0.50 on 2- and 3-leg slips, closed-form / simulation
# runs 0.95 to 1.00, never worse than 5% out even where the error itself is
# 95%. The deviations point the right way on BOTH gates below. For positive
# correlations it UNDERSTATES the understatement (0.95-1.00), so a floor
# stated from it is a floor. For the small NEGATIVE correlations where the
# refusal gate actually lives it OVERSTATES the overstatement (1.06x at
# r=-0.03, 1.03x on three such pairs), so the gate errs toward refusing.
# Neither direction is corrected by a fudge factor; the sweep is pinned in
# the suite instead, so a regression in this arithmetic is visible.
#
# READ THIS PARAGRAPH FOR WHAT IT IS: agreement between a formula and a
# simulation OF THE SAME MODEL. It shows the algebra is right. It does not
# show the model fits football, and against the measured lifts it partly
# does not — see "What the 2026-11-11 review found" above `joint_error`.
#
# The 2-leg figure in F13's backlog entry reproduces exactly. **The 3-leg
# figure does not.** That entry says r=0.03 across three pairs costs 11.5%
# of a 3-leg joint; it costs 5.73% closed-form and 5.89% by simulation, so
# the entry was 2x high. The conclusion it was used to support — gate the
# TOTAL, not each pair — survives unharmed, since 3 pairs still cost 3x one
# pair. The magnitude of the argument was overstated; its direction was not.
#
# TWO THINGS THE OLD PER-PAIR GATE COULD NOT SEE.
#
# 1. THE SIGN. A positive joint error means the true joint is HIGHER than
#    the product, so the reported P(cash) and EV are too LOW. Being wrong in
#    that direction passes on a good slip; it never places a bad one. A
#    NEGATIVE joint error is the dangerous one: the product OVERSTATES the
#    joint and hands the slip an EV it has not earned, which is the exact
#    failure `classify`'s refusal exists to prevent. Both signs are real in
#    the measured table — same-team PASS x RECV is +0.2462 and same-team
#    PASS x RUSH is -0.0765 — so the asymmetry below discriminates rather
#    than waving slips through.
#
# 2. THE SIDES. Correlation is between the underlying STATS, not between the
#    bets. Two positively-correlated players both bet OVER lift the joint;
#    one OVER and one UNDER depress it. Under the copula that is exactly a
#    sign flip on the latent variable, so the pair's effective r is
#    r * s_a * s_b with s = +1 for an OVER and -1 for an UNDER. Nothing
#    before this read `BoostLeg.side` when scoring a pair, so a mixed-side
#    slip was scored with the sign of an all-OVER one.
#
# AND THE LEG PROBABILITIES MATTER, which is why this is computed on the
# real legs and never looked up by shape. The same r=0.03 pair costs 0.97%
# at p=0.65 each and 3.36% at p=0.35 each — a 3.5x range inside one pair.
# F13's table of "measured totals for real shapes" was computed at 50/50 and
# is a rough guide only.


# The stdlib's own normal, not a hand-rolled rational approximation.
# `ff_correlation._norm_ppf` exists but is an Acklam-style approximation
# carried for a different job; this arithmetic is sensitive in the tail,
# where a 1e-4 approximation error in z moves phi(z) by more than the
# correlations being measured.
_NORM = NormalDist()


def _phi(z: float) -> float:
    """Standard normal density."""
    return _NORM.pdf(z)


def _norm_inv(q: float) -> float:
    """Standard normal quantile, refusing the endpoints.

    A fair probability of exactly 0 or 1 has no finite z and `BoostLeg`
    already refuses those, so reaching here with one is a caller error
    rather than a number to clamp.
    """
    if not (0.0 < q < 1.0):
        raise ValueError(
            f"no finite normal quantile for {q!r} — a fair probability of "
            f"exactly 0 or 1 cannot be placed on the copula's scale")
    return _NORM.inv_cdf(q)


def _side_sign(side) -> int:
    """+1 for an OVER, -1 for an UNDER.

    Anything else raises rather than defaulting. A slip whose side this
    cannot read must not be scored with the sign of an all-OVER slip —
    that is B39's shape, and here it would invert which way the error runs.
    """
    s = str(side or "").strip().upper()
    if s in ("OVER", "O", "YES"):
        return 1
    if s in ("UNDER", "U", "NO"):
        return -1
    raise ValueError(
        f"cannot tell which side {side!r} is, and the joint error's SIGN "
        f"depends on it — an OVER and an UNDER of the same correlated pair "
        f"move the joint in opposite directions")


@dataclass
class JointError:
    """How far the product of the legs is from the joint, and which way."""
    rel: float                              # signed relative error
    terms: tuple[tuple[str, str, float], ...]   # (a, b, contribution)
    why: str = ""
    unreadable: tuple[str, ...] = ()        # legs whose side could not be read
    # True when EVERY pair was scored on the pessimistic end of its own
    # confidence interval rather than on its point estimate. The gate below
    # keys on the SIGN of the error, and E3 measured one cell —
    # same-team PASS x PASS_TD, n=262 — whose interval spans zero, so its
    # sign is not known. A point estimate would have handed that pair a
    # confident sign it has not earned (B39), so a pair carrying an interval
    # is scored at whichever end hurts, and a pair carrying none is scored
    # at its point estimate and forfeits the Slepian floor.
    pessimistic: bool = False

    @property
    def measurable(self) -> bool:
        return not self.unreadable

    @property
    def unbracketed(self) -> bool:
        """True when a MEASURED pair arrived without a confidence interval.

        `pessimistic` alone cannot say this, and the first live run proved
        it: it came back False on 4 of 8 slips, every one of them because
        there were no measured non-zero pairs at all — nothing to be
        pessimistic about. Used as a missing-interval alarm it was a 100%
        false-positive rate on that board. The two states are now separate,
        because only this one is a problem.
        """
        return bool(self.terms) and not self.pessimistic

    @property
    def conservative(self) -> bool:
        """True when the product UNDERSTATES the joint.

        Zero counts as conservative: no error is not an overstatement.
        """
        return self.measurable and self.rel >= 0.0

    def describe(self) -> str:
        if not self.measurable:
            return ("joint error NOT MEASURABLE: could not read the side of "
                    + ", ".join(self.unreadable))
        word = ("the product UNDERSTATES the joint"
                if self.rel > 0 else
                "the product OVERSTATES the joint" if self.rel < 0 else
                "the product is the joint to first order")
        s = f"joint error {self.rel:+.2%} — {word}"
        if self.terms:
            worst = max(self.terms, key=lambda t: abs(t[2]))
            s += (f" (largest pair: {worst[0]} x {worst[1]} at "
                  f"{worst[2]:+.2%})")
        return s


# ---------------------------------------------------------------------------
# What the 2026-11-11 review found in the arithmetic above
# ---------------------------------------------------------------------------
#
# The closed form was "verified" against a Monte Carlo of the SAME Gaussian
# copula. That checks the algebra. It says nothing about whether football
# follows the copula, and two things in this repo say it does not quite:
#
# 1. THE MEASURED LIFTS DISAGREE, IN THE UNSAFE DIRECTION. `MEASURED_PAIR_LIFT`
#    holds the directly measured joint-crossing lift for eleven yard pairs,
#    and at 50/50 the formula predicts lift = 1 + 0.6366 r. Against the data:
#
#        same PASS x RUSH   predicted -4.9%   measured  -6.6%
#        opp  RUSH x RUSH   predicted -5.1%   measured  -8.4%
#        opp  PASS x RUSH   predicted -1.4%   measured  -4.6%
#        same PASS x RECV   predicted +15.7%  measured +19.9%
#
#    Every material NEGATIVE cell is understated, by 1.3x to 3.2x. Each is
#    individually within about 1.5 standard errors (these cells have 4,600
#    to 5,700 pairs), so this is a lean and not a proof — but the header
#    above says the formula "errs toward refusing" on the dangerous side,
#    and that was true only against its own simulation. So where a measured
#    lift exists the term is scored at the WORSE of the two.
#
# 2. THE ANYTIME-TD r IS NOT A LATENT CORRELATION. `SIDE_SPEC` marks TD as
#    binary: its r is a correlation between two yes/no outcomes. For those
#    the joint is EXACT with no copula at all,
#
#        P(A and B) = pa pb + r sqrt(pa qa pb qb)
#
#    so the relative error is r sqrt(qa qb / pa pb). Feeding that r to the
#    latent-normal formula understated every TD x TD term by 1.57x at 50/50
#    and by more at real anytime-TD probabilities (2.9x at p = 0.30). A
#    binary leg against a yards leg is the point-biserial case, between the
#    two. None of the suite's verdicts moved, but the knife edge recorded
#    for one same-team TD x TD pair was 1.02x on the wrong arithmetic and
#    is 1.60x on the right one.


def _binary_market(market) -> bool:
    """True when this market's measured r is between yes/no outcomes."""
    side = MARKET_SIDE.get(market)
    spec = _SIDE_SPEC.get(side) if side else None
    return bool(spec and spec[2])


def _pair_weight(pa, pb, za, zb, bin_a: bool, bin_b: bool) -> float:
    """d(relative joint error)/dr for one pair, by what KIND of r it is."""
    if bin_a and bin_b:
        return math.sqrt((1.0 - pa) * (1.0 - pb) / (pa * pb))      # exact
    if bin_a:
        return (_phi(zb) / pb) * math.sqrt((1.0 - pa) / pa)
    if bin_b:
        return (_phi(za) / pa) * math.sqrt((1.0 - pb) / pb)
    return _phi(za) * _phi(zb) / (pa * pb)


_W50 = _phi(0.0) ** 2 / 0.25          # the yards-pair weight at 50/50


def _lift_term(la, lb, sign, pa, pb, za, zb):
    """This pair's term implied by its MEASURED lift, or None.

    The lift sweep crossed each player's own median, so (lift - 1) is the
    relative joint error at 50/50. It is carried to these legs'
    probabilities with the same weight the formula uses, which is the only
    part of the copula this leans on. None when the pair has no measured
    lift, a market is unmapped, or a team is unknown — never a guess.
    """
    sa, sb = MARKET_SIDE.get(la.market), MARKET_SIDE.get(lb.market)
    ta, tb = _clean(la.team), _clean(lb.team)
    if (sa is None or sb is None or not ta or not tb
            or la.event_id != lb.event_id
            or _binary_market(la.market) or _binary_market(lb.market)):
        return None
    m = pair_lift("same" if ta == tb else "opp", sa, sb)
    if m is None:
        return None
    return sign * (float(m[0]) - 1.0) * (_phi(za) * _phi(zb) / (pa * pb)) / _W50


def _zero_drift(legs, zeros):
    """(sum of the cleared pairs' measured lift terms, [(a, b, r), ...]).

    Only pairs with a measured LIFT contribute; a cross-game pair or one
    cleared some other way has no number to add and is left alone. The r
    returned is the lift table's own, so a promoted pair is scored by
    `joint_error` exactly as a pair that failed the gate would be.
    """
    by = {l.player: l for l in legs}
    tot, out = 0.0, []
    for a_name, b_name, _why in zeros:
        la, lb = by.get(a_name), by.get(b_name)
        if la is None or lb is None:
            continue
        try:
            sign = _side_sign(la.side) * _side_sign(lb.side)
            pa, pb = float(la.fair_prob), float(lb.fair_prob)
            za, zb = _norm_inv(1.0 - pa), _norm_inv(1.0 - pb)
        except ValueError:
            continue
        t = _lift_term(la, lb, sign, pa, pb, za, zb)
        if t is None:
            continue
        sa, sb = MARKET_SIDE.get(la.market), MARKET_SIDE.get(lb.market)
        m = pair_lift("same" if _clean(la.team) == _clean(lb.team) else "opp",
                      sa, sb)
        tot += t
        out.append((a_name, b_name, float(m[1])))
    return tot, out


def joint_error(legs, pairs, cis=None) -> JointError:
    """First-order relative error of the independent product.

    `pairs` is `Structure.pairs` — (player_a, player_b, r, why). Only pairs
    with a measured non-zero r contribute; a pair the table never measured
    does not appear there and is NOT scored here, because `classify` refuses
    the slip outright for it and no error estimate can stand in for a number
    that does not exist.
    """
    by_name: dict[str, list] = {}
    for l in legs:
        by_name.setdefault(l.player, []).append(l)

    unreadable, terms, tot = [], [], 0.0
    all_ci = True
    n_lift = 0
    for pair in pairs:
        a_name, b_name, r = pair[0], pair[1], pair[2]
        ci = pair[4] if len(pair) > 4 else None
        if ci is None and cis:
            ci = (cis.get((pair[0], pair[1]))
                  or cis.get((pair[1], pair[0])))
        la = by_name.get(a_name, [None])[0]
        lb = by_name.get(b_name, [None])[0]
        if la is None or lb is None:
            # A pair naming a player not in `legs` is a caller error, not a
            # datum. Refuse rather than silently dropping the term, which
            # would shrink the error toward zero — the unsafe direction.
            unreadable.append(f"{a_name if la is None else b_name} "
                              f"(named in a pair but not among the legs)")
            continue
        try:
            sign = _side_sign(la.side) * _side_sign(lb.side)
        except ValueError:
            bad = [l.player for l in (la, lb)
                   if str(l.side or "").strip().upper()
                   not in ("OVER", "O", "YES", "UNDER", "U", "NO")]
            unreadable.extend(bad)
            continue
        pa, pb = float(la.fair_prob), float(lb.fair_prob)
        za = _norm_inv(1.0 - pa)
        zb = _norm_inv(1.0 - pb)
        # The pessimistic end is whichever one drives the TERM most
        # negative, which depends on the sides: with sign -1 the term is
        # most negative at the interval's HIGH end.
        if ci is None:
            all_ci = False
            use = float(r)
        else:
            lo, hi = float(min(ci)), float(max(ci))
            use = lo if sign > 0 else hi
        w = _pair_weight(pa, pb, za, zb,
                         _binary_market(la.market), _binary_market(lb.market))
        t = sign * use * w
        # Second opinion, where one exists: the MEASURED joint-crossing
        # lift for this pair. See `_lift_term`. The term is scored at
        # whichever of the two is worse for the slip.
        tl = _lift_term(la, lb, sign, pa, pb, za, zb)
        if tl is not None and tl < t:
            t = tl
            n_lift += 1
        terms.append((a_name, b_name, t))
        tot += t

    if unreadable:
        return JointError(rel=0.0, terms=tuple(terms),
                          unreadable=tuple(dict.fromkeys(unreadable)),
                          why="the sign of the joint error cannot be fixed")
    if not terms:
        return JointError(rel=0.0, terms=(),
                          why="no measured non-zero pair — nothing to correct")
    return JointError(
        rel=tot, terms=tuple(terms), pessimistic=all_ci,
        why=(f"first-order Gaussian-copula expansion over "
             f"{len(terms)} measured pair(s), on these legs' own fair "
             f"probabilities and sides, scored at "
             + ("the pessimistic end of each pair's confidence interval"
                if all_ci else
                "point estimates — at least one pair carried no interval")
             + (f"; {n_lift} pair(s) scored on their measured lift instead, "
                f"because it was worse than the formula's figure"
                if n_lift else "")))


# The gate. NOT a threshold on the joint error's size, which is the thing
# lesson 99 says to stop doing — three tuned thresholds died on B57 before
# the quantity turned out to be wrong. There are two questions here and only
# one of them needs a number at all:
#
#   * rel >= 0 — the product understates the joint. The reported P(cash) and
#     EV are then a conservative FLOOR, and a floor is a usable number. No
#     threshold: the direction is safe at any magnitude.
#
#   * rel < 0 — the product overstates the joint. Now the size matters, and
#     the honest reference is the error the product ALREADY carries from the
#     legs' own fair uncertainty, propagated the same way B57 propagates it.
#     Inside that, the bias is smaller than the noise it sits in and
#     refusing buys nothing; outside it, the bias dominates and the slip
#     goes back to refusing. A RATIO, with nothing to tune.
JOINT_OVERSTATE_RATIO = 1.0


def product_noise(legs, quotes=None) -> tuple[float, str]:
    """Relative error the product already carries from the legs' own fairs.

    sqrt(SUM (u/p_i)^2) — independent per-leg errors through a product. `u`
    is B57's `fair_uncertainty`, measured off the board where two books
    quote the same leg and falling back to FAIR_UNCERTAINTY_FALLBACK with a
    reason when they do not.
    """
    u, why = fair_uncertainty(legs, quotes)
    tot, own = 0.0, 0
    for l in legs:
        p = float(l.fair_prob)
        tot += (leg_sd(l, u) / p) ** 2
        own += l.fair_sd is not None
    if own:
        why += (f"; {own} of {len(list(legs))} leg(s) use their own "
                f"measured uncertainty (rungs) instead of that figure")
    return math.sqrt(tot), why


def leg_sd(leg, board_u: float) -> float:
    """The uncertainty to use for one leg's fair (B158).

    The leg's own when it carries one, else the board-level figure. Not the
    larger of the two and not the smaller: which direction is "safe"
    differs by consumer — more noise makes the ranking gate stricter and
    the correlation gate more lenient — so the honest input is simply the
    best measurement of this leg.
    """
    sd = getattr(leg, "fair_sd", None)
    return float(sd) if sd is not None and sd > 0 else float(board_u)


def joint_verdict(legs, pairs, quotes=None, cis=None) -> tuple[bool, str]:
    """(is the product usable as a floor, why) for a correlated slip.

    THREE states, because "the product understates the joint" rests on two
    quite different things depending on the pairs:

      1. EVERY effective pair correlation >= 0. Then P(all legs) >= the
         product is a THEOREM, not an estimate — Slepian's inequality for a
         Gaussian copula with non-negative correlations. The floor holds at
         any magnitude and does not depend on the expansion at all; the
         expansion only SIZES the gap. Priced.

      2. MIXED signs that happen to total positive. The floor is then only
         as good as the first-order expansion, since a negative pair pulls
         the joint down and nothing guarantees the positives outweigh it
         beyond the arithmetic that said so. Held to the same ratio test as
         an overstatement, against the error the product already carries.

      3. TOTAL negative. The product overstates the joint, which is the one
         direction that places a bad slip rather than passing on a good one.
         Ratio test.
    """
    je = joint_error(legs, pairs, cis)
    if not je.measurable:
        return False, je.describe()
    if not je.terms:
        return True, je.why

    if je.rel >= 0 and all(t[2] >= 0 for t in je.terms) and je.pessimistic:
        # Wording corrected 2026-11-11. This used to say "a theorem" and
        # "can only be better than it reads, never worse". Slepian's
        # inequality is a theorem ABOUT A GAUSSIAN COPULA, and football is
        # not obliged to be one: this repo's own tables hold a pair with a
        # positive r and a measured lift BELOW 1 (same-team receiving,
        # r=+0.0125, lift 0.9983). So the floor is as strong as the
        # evidence for the direction, and a correction smaller than the
        # noise it sits in is reported as that, not as a guarantee.
        noise0, _ = product_noise(legs, quotes)
        if je.rel < noise0:
            return True, (
                f"{je.describe()}. Every pair points the same way, so the "
                f"product is treated as a FLOOR on P(cash) (Slepian's "
                f"inequality, under a Gaussian copula) — but the whole "
                f"correction is smaller than the {noise0:.2%} the product "
                f"already carries from the legs' own fair uncertainty, so "
                f"read this as 'about the product', not as a slip that is "
                f"sure to be better than it looks")
        return True, (
            f"{je.describe()}. Every pair points the same way, so the "
            f"product is a FLOOR on P(cash): under a Gaussian copula that "
            f"is Slepian's inequality and holds at any magnitude, and "
            f"where a joint-crossing lift has been measured directly for "
            f"these pairs it points the same way. A model result backed by "
            f"measurement, not a guarantee. The real joint is about "
            f"{je.rel:+.2%} above the product on this arithmetic, so the EV "
            f"on the floor is conservative by roughly that much")

    noise, nwhy = product_noise(legs, quotes)
    ratio = abs(je.rel) / noise if noise > 0 else float("inf")
    mixed = je.rel >= 0
    lead = (f"{je.describe()}, which is {ratio:.2f}x the {noise:.2%} the "
            f"product already carries from the legs' own fair uncertainty "
            f"({nwhy})")
    if mixed:
        gap = ("the pairs point BOTH ways and only net out positive on "
               "the first-order arithmetic"
               if not all(t[2] >= 0 for t in je.terms) else
               "at least one pair carried no confidence interval, so the "
               "positive sign rests on a point estimate")
        if ratio <= JOINT_OVERSTATE_RATIO:
            return True, (
                f"{lead}. {gap[0].upper()}{gap[1:]}, so this is not a "
                f"Slepian floor — but the whole correction is inside the "
                f"noise it sits in, so it is reported rather than refused")
        return False, (
            f"{lead}. {gap[0].upper()}{gap[1:]}, so nothing guarantees the "
            f"joint clears the product beyond a first-order expansion, and "
            f"the correction is bigger than the noise it sits in. No "
            f"P(cash) and no EV: a floor that rests only on an "
            f"approximation is not a floor")
    if ratio <= JOINT_OVERSTATE_RATIO:
        return True, (
            f"{lead} — the bias is inside the noise it sits in, so it is "
            f"reported rather than refused, but the EV on the floor is "
            f"OPTIMISTIC "
            f"by about {abs(je.rel):.2%} and that is the direction that "
            f"costs money")
    return False, (
        f"{lead} — past {JOINT_OVERSTATE_RATIO:.2f}x the overstatement "
        f"dominates, so no P(cash) and no EV. This is the one direction "
        f"that places a bad slip rather than passing on a good one")


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
    # B170. The flattened board quotes this candidate was classified with,
    # so `floor` measures the product's noise from the same data. None means
    # the fallback figure, and the reason text says which.
    quotes: list | None = field(default=None, repr=False, compare=False)
    # The minimum odds THIS run was built for (the boost's own minimum, as
    # passed to `enumerate_candidates(floor=...)`). None means the project
    # default, FLOOR. Game-day run 2026-11-12: `clears_floor` compared every
    # slip against +300 whatever the boost, so a FanDuel slip at +124 on a
    # +100 boost and a BetMGM slip at +110 on a -300 boost both read False.
    min_odds: float | None = None
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
        return self.odds >= (FLOOR if self.min_odds is None
                             else float(self.min_odds))

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

    # --- F13: the floor, where the product is not the joint -----------
    #
    # Strictly DISJOINT from p_cash / ev_pct above, which stay None for a
    # correlated slip. The same number must never appear under two names
    # with two meanings — that is how "+15.7% beside a NEGATIVE verdict"
    # happened. `p_cash` means "this IS the joint"; `p_cash_floor` means
    # "the joint is at least this".
    @property
    def joint(self) -> JointError:
        return joint_error(self.legs, self.structure.pairs,
                           self.structure.pair_cis)

    @property
    def floor(self) -> tuple[bool, str]:
        """(is the product usable as a floor, why) — None-safe, never raises."""
        if self.structure.priceable:
            return False, ("the product IS the joint here, so there is no "
                           "floor to report — see P(cash)")
        if self.structure.unmeasured:
            return False, ("a pair in this slip was never measured, and no "
                           "floor can be built on a number that does not "
                           "exist")
        return joint_verdict(self.legs, self.structure.pairs,
                             quotes=self.quotes,
                             cis=self.structure.pair_cis)

    @property
    def p_cash_floor(self) -> float | None:
        """A LOWER BOUND on P(cash) for a correlated slip, or None."""
        return fair_joint(self.legs) if self.floor[0] else None

    @property
    def ev_floor_pct(self) -> float | None:
        """EV computed on the floor — itself a lower bound where the joint
        error is positive, and an OPTIMISTIC figure where the gate let a
        small negative through. `floor[1]` says which, and the report
        prints it, because the two read identically as numbers."""
        if not (self.floor[0] and self.priced):
            return None
        p = self.p_cash_floor
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
        if self.product_hold is not None:
            _, hi = self.hold_band
            # ONE-SIDED, and the first version of this was two-sided and
            # wrong. The measured band is the hold on the book's real SGP
            # QUOTE; the product carries only the legs' own compounded vig,
            # which is far smaller — about 14% on three legs against a
            # 23.1-37.2% same-game band. So a healthy slip sits BELOW the
            # band here by construction, and testing the lower side failed
            # seven ordinary fixtures before this was caught.
            #
            # The upper side is the one that means something: if our own
            # P(cash) implies a hold worse than the band's WORST measured
            # case, then the slip is already worse than the band's
            # pessimistic end before the boost is applied, and a ROI drawn
            # from that band is a number about a different slip.
            if self.product_hold > hi:
                # The band assumes the book takes its usual cut out of a
                # product whose legs are priced about right. When OUR OWN
                # P(cash) against this product implies a hold nowhere near
                # the measured band, that assumption is broken and the band
                # does not describe this slip.
                #
                # The first live run printed `P(cash): 0.0%` beside
                # `anticipated ROI +9.3% to +21.9%` on a slip built from
                # three longest rungs. Both numbers were computed
                # correctly; together they were nonsense, because the ROI
                # band never looked at P(cash) and P(cash) said the slip
                # cannot cash. A reader sees one number beside the other,
                # not the two derivations.
                #
                # The 5-point tolerance is deliberate slack: the band is a
                # population figure and a single slip legitimately sits a
                # little outside it. This fires on disagreement, not on
                # noise.
                return None
        return roi_band(self.odds, self.boost_pct,
                        cross_game=self.structure.cross_game)

    @property
    def product_hold(self) -> float | None:
        """The hold implied by our fair joint against the PRODUCT price.

        `slip_hold` is the same quantity against the book's real quote and
        needs the slip priced; this one needs nothing and is what makes
        `ev_band` able to notice that it does not apply.
        """
        if not self.structure.priceable:
            return None
        p = self.p_cash
        if p is None:
            return None
        return 1.0 - p * to_decimal(self.odds)

    @property
    def ev_band_reason(self) -> str:
        """Why there is no ROI band, when there is none."""
        if not self.structure.priceable:
            return ("the joint is not the product, so there is no product "
                    "price to put a band around")
        ph = self.product_hold
        if ph is None:
            return "no P(cash), so the band cannot be checked against it"
        lo, hi = self.hold_band
        if ph > hi:
            return (f"NO ROI BAND: this slip's own P(cash) of "
                    f"{self.p_cash:.1%} against its {self.odds:+.0f} "
                    f"product implies a hold of {ph:+.1%}, worse than the "
                    f"WORST of the measured {lo:.1%}-{hi:.1%} band. The "
                    f"band assumes legs priced about right and these are "
                    f"not, so a ROI from it would be a number about a "
                    f"different slip. What IS known: at the full product "
                    f"price the boosted EV is {self.ev_at_product:+.1%}, and "
                    f"the book's real quote is normally worse than the "
                    f"product, so that is a ceiling")
        return ""

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
            # F13. UNPRICEABLE used to be the only answer here, and it was
            # printed in the header while the body now carries a P(cash)
            # floor and an EV on it. A header that contradicts its own body
            # is worse than either reading alone — the "+15.7% beside a
            # NEGATIVE verdict" failure, one layer out — so a slip whose
            # product bounds its joint says FLOOR ONLY and means it.
            if not self.floor[0]:
                return "UNPRICEABLE"
            # A bound and an optimistic estimate are opposite kinds of
            # number and were both labelled FLOOR ONLY. When the product
            # OVERSTATES the joint (inside the noise, so it is reported),
            # the EV on it is too HIGH, not a lower bound — the game-day
            # run found slips whose "floor" EV was optimistic by up to
            # 2.9% carrying the label that says "can only be better".
            return "FLOOR ONLY" if self.joint.rel >= 0 else "ESTIMATE ONLY"
        if not self.clears_floor:
            # Not NEGATIVE. A slip whose quote missed the minimum printed
            # NEGATIVE beside EV +1.0%: the EV is what it is, the boost
            # simply cannot be applied to it.
            return "BELOW MINIMUM"
        if self.priced:
            # A real quote beats a population figure: the hold on this slip
            # is now directly observable rather than assumed.
            return "PLAY" if self.ev_pct > 0 else "NEGATIVE"
        # Pessimistic end of the measured band. Assuming the cheaper product
        # when you do not know which you have is the error that loses money.
        if self.ev_band is None:
            # Priceable, but the measured hold band does not describe this
            # slip — its own P(cash) against its product implies a hold
            # nowhere near the band, so a ROI from the band would be a
            # number about a different slip. Neither PLAY nor NEGATIVE is
            # knowable here without a real quote, and inventing either is
            # how a pathological slip read `P(cash) 0.0%` beside
            # `anticipated ROI +9.3% to +21.9%`.
            #
            # Corrected 2026-11-11. "Not knowable" was wrong for most of
            # these: the band not applying does not mean nothing is known.
            # P(cash) and the product price give the EV AT THE PRODUCT
            # PRICE exactly, and the book's real same-game quote is
            # normally WORSE than the product (that gap is what the hold
            # band measures). So when even the product price loses, the
            # slip loses, and sending a reader to price a slip that is
            # -98.8% before the book's cut wastes the one scarce thing in
            # this workflow. PRICE IT is kept only for the case it fits:
            # positive at the product price, band not applicable.
            return "PRICE IT" if (self.ev_at_product or 0.0) > 0 else "NEGATIVE"
        return "PLAY" if self.ev_band[0] > 0 else "NEGATIVE"

    @property
    def ev_adjusted(self) -> float | None:
        """`ev_floor_pct` with a known OVERSTATEMENT taken back out.

        For a floor (joint error >= 0) this is `ev_floor_pct` unchanged:
        the understatement is left in, as margin. For an optimistic
        estimate, P(cash) is scaled down by the joint error first.
        """
        if not (self.floor[0] and self.priced):
            return None
        p = self.p_cash_floor * (1.0 + min(0.0, self.joint.rel))
        d = to_decimal(self.book_odds)
        return p * (d - 1.0) * (1.0 + self.boost_pct) - (1.0 - p)

    @property
    def predicted_ev(self) -> float | None:
        """Boosted EV at the quote this slip's book is EXPECTED to give.

        Product times the book's MEDIAN measured quote/product factor (the
        expectation, where price targeting uses the lower quartile for
        safety); a cross-game parlay is taken at its product. P(cash) is
        the joint where the product is the joint, the floor where it is a
        bound, and the estimate with its overstatement removed. None when
        there is no P(cash) of any kind.

        An ORDERING aid for the unpriced shortlist, not a number to quote:
        it rests on anchors that may be soft and a factor that varies by
        slip. `rank_is_meaningful` still says when the order is not a
        ranking, and a real quote replaces this entirely.
        """
        if self.structure.priceable:
            p = self.p_cash
        elif self.floor[0]:
            p = fair_joint(self.legs) * (1.0 + min(0.0, self.joint.rel))
        else:
            p = None
        if p is None:
            return None
        d = to_decimal(self.independent_odds)
        if not self.structure.cross_game:
            books = {_book_key(l.book) for l in self.legs}
            d = d * min(expected_factor(b, len(self.legs)) for b in books)
        return p * (d - 1.0) * (1.0 + self.boost_pct) - (1.0 - p)

    @property
    def ev_at_product(self) -> float | None:
        """Boosted EV if the book paid the full product of the legs.

        A CEILING on the real EV for independent legs, not an estimate of
        it: the book's quote is normally below the product. Needs no quote
        and no band.
        """
        p = self.p_cash
        if p is None:
            return None
        d = to_decimal(self.independent_odds)
        return p * (d - 1.0) * (1.0 + self.boost_pct) - (1.0 - p)

    @property
    def rank(self) -> float:
        """What to sort on: the real EV once priced, the anticipated
        pessimistic ROI before."""
        if self.ev_pct is not None:
            return self.ev_pct
        if self.ev_floor_pct is not None:
            return self.ev_adjusted
        # Unpriced: the EV at the quote this book is EXPECTED to give. Until
        # 2026-11-12 an unpriced slip ranked on `ev_band[0]`, which depends
        # only on the slip's PRICE — so every slip at one price target tied
        # and the tie-break was the players' names. The game-day run's
        # eight-slip shortlists came out alphabetical ("Antonio Williams"
        # in almost every one) and held qualifiers on one boost of five,
        # while a scan of the same pools found them on all five.
        pe = self.predicted_ev
        if pe is not None:
            return pe
        # A slip with no band is UNKNOWN, not bad. -9e9 would bury it below
        # every measured negative, which is a ranking claim about a slip
        # nothing has measured — B57's whole objection. Zero puts it where
        # it belongs: not evidence for, not evidence against.
        if self.ev_band is not None:
            return self.ev_band[0]
        # No band. The EV at the product price is a measured ceiling, so it
        # is the honest rank: 0.0 put a slip that is -98.8% at its own
        # product price above every measured negative on the board.
        e = self.ev_at_product
        return e if e is not None else 0.0

    @property
    def key(self) -> tuple:
        """Deterministic sort key. A recommendation you cannot reproduce
        cannot be audited against the bet log later."""
        return (0 if self.measurable else 1, -self.rank,
                tuple(sorted(l.player for l in self.legs)))

    @property
    def measurable(self) -> bool:
        """Whether ANY probability of cashing exists for this slip: a real
        priced EV, a joint, a floor or an estimate.

        Sorts ahead of `rank`. A slip with none of them ranks at 0.0
        ("unknown, not bad"), and on a weak boost every measurable slip has
        a NEGATIVE predicted EV, so the unknowns took the whole shortlist:
        the second game-day run's D2, F1 (+100 band) and M1 3-leg lists
        were 8 of 8, 40 of 40 and 39 of 40 UNPRICEABLE. An unpriceable slip
        cannot become a qualifier whatever the book quotes; a measurable
        one can, so it is the one worth a price_sgp call.
        """
        return (self.ev_pct is not None or self.ev_floor_pct is not None
                or self.predicted_ev is not None)


def make_candidate(legs, meta=None, *, boost_pct: float,
                   stake: float = 10.0, aliases=None,
                   quotes=None) -> Candidate:
    """One candidate from one set of legs, structure derived.

    `aliases` and `quotes` go straight to `classify`; `quotes` is also kept
    on the candidate so its joint gate measures noise the same way.
    """
    legs = list(legs)
    st = classify(legs, meta, aliases, quotes)
    notes = []
    for l in legs:
        if l.verdict == "CAUTION":
            notes.append(f"CAUTION on {l.player}: "
                         f"{'; '.join(l.verdict_reasons) or 'unspecified'}")
    if not st.priceable:
        notes.append(st.reason)
    return Candidate(legs=legs, structure=st, boost_pct=float(boost_pct),
                     independent_odds=independent_odds(legs), stake=stake,
                     notes=notes, quotes=quotes)


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
    # F11. What the token changed, and what it did not state. Reported
    # rather than applied silently: a shortlist built to a token minimum
    # nobody checked looks identical to one built to this project's band,
    # and the two answer different questions (B55).
    token_notes: list[str] = field(default_factory=list)
    # F12. What the enumeration refused on the way, and what it chose. With
    # rungs in the pool MOST combinations for a player are that player's own
    # rungs against each other, so a silently smaller shortlist is the
    # normal outcome and reads as "the pool was thin" unless it is counted.
    build_notes: list[str] = field(default_factory=list)

    @property
    def rung_legs(self) -> list[str]:
        """Legs in this shortlist that are rungs rather than main lines."""
        return sorted({f"{l.player} {l.line:g}+0.5 @{l.book}"
                       for c in self.candidates for l in c.legs
                       if l.is_rung})

    @property
    def shape_circular_legs(self) -> list[str]:
        """Rung legs whose SHAPE came from the book being bet.

        Not a refusal — see `BoostLeg.shape_circular`. Surfaced here because
        a shortlist built entirely out of one book's own ladder is answering
        "which of this book's rungs is cheapest", which is a real question,
        and NOT "do these rungs beat the market", which it cannot answer.
        """
        return sorted({f"{l.player} @{l.book}"
                       for c in self.candidates for l in c.legs
                       if l.shape_circular})

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
        # F13. A FLOOR ONLY slip has a BOUNDED EV, which is not a negative
        # one — it fell through to "LIKELY NEGATIVE" when this state was
        # added, which is the opposite of what the bound says. It is listed
        # ahead of UNPRICEABLE because a bound is actionable and a refusal
        # is not, so a board holding both should surface the bound.
        if "FLOOR ONLY" in v or "ESTIMATE ONLY" in v:
            return "BOUNDED ONLY"
        if "UNPRICEABLE" in v:
            return "UNPRICEABLE ONLY"
        return "LIKELY NEGATIVE"

    @property
    def immature_anchors(self) -> list[str]:
        """Distinct PLAYER NAMES with an immature anchor — NOT slips.

        Its length matched the candidate count on one live shortlist (8 and
        8) and not the next (7 against 8, because eight slips drew on seven
        players), which is how the difference surfaced. For "how many slips
        are clean" use `immature_slips`.
        """
        return sorted({l.player for c in self.candidates for l in c.legs
                       if l.anchor_immature})

    @property
    def immature_slips(self) -> tuple[int, int]:
        """(slips with at least one immature-anchor leg, slips total)."""
        return (sum(1 for c in self.candidates
                    if any(l.anchor_immature for l in c.legs)),
                len(self.candidates))

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
        if self.token_notes:
            L.append("  token:")
            for n in self.token_notes:
                L.append(f"     {n}")
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


# B50/B129 wanted a `same_bet` check here, at the merge point, and it does
# NOT belong: `same_bet` requires equal canonical keys, a canonical key
# BEGINS with the normalised player name, and the name guard in
# `enumerate_candidates` already refuses any combination naming one man
# twice. A guard that no input can reach reads as coverage (lesson 64), and
# this one was written, tested against a constructed input, and removed when
# the input turned out to be impossible.
#
# What the name guard genuinely misses is the same player under names that
# normalise DIFFERENTLY — "Cam Ward" and "Cameron Ward". `same_bet` misses
# that too, because its key is the normalised name. The `player_id` guard
# inside `classify` is what catches it, and the enumerator now treats that
# as a refused combination instead of letting it raise.


def rung_legs(fairs, *, book: str, market: str, event_id: str,
              verdicts=None, odds=None, meta=None, aliases=None,
              tiers=None,
              line_type: str = "milestone") -> tuple[list, list]:
    """BoostLegs from `ff_props.ladder_fair` records. (kept, refused).

    F12's selection half. The pricing shipped 2026-11-09 and nothing could
    CHOOSE a rung, because the production path pulls `line_type="main"`.
    This is the merge point B50 and B129 were waiting for.

    THREE things this refuses rather than papering over:

      * A rung `ladder_fair` could not price. `fair is None` means refused,
        and a leg built on it would carry a fair nobody computed.
      * A rung with no price for the side being bet. A one-sided row is not
        a price (B101).
      * A rung whose player has no verdict. `_intake` drops an UNSCREENED
        leg and says so, and that is the right behaviour — but a rung
        arriving with no verdict at all would be dropped there for a reason
        that reads like a screening failure rather than like a missing
        input, so it is named here instead.

    `verdicts` maps normalised player name -> (verdict, side, reasons). The
    role screen is about the PLAYER'S ROLE and the SIDE, not the threshold,
    so one screen legitimately covers every rung on that side — a collapsed
    role vetoes a longer OVER at least as hard as a shorter one, so carrying
    it across thresholds errs the safe way. It is still recorded as having
    come from the main-line screen rather than from a screen of this rung.
    """
    vmap = {}
    for k, v in (verdicts or {}).items():
        vmap[norm_player(str(k))] = v
    omap = {}
    for k, v in (odds or {}).items():
        omap[(norm_player(str(k[0])), float(k[1]))] = float(v)

    kept, refused = [], []
    for f in fairs:
        who = getattr(f, "player", None)
        thr = getattr(f, "threshold", None)
        tag = f"{who} {thr:g}+" if thr is not None else str(who)
        if not getattr(f, "priceable", False):
            refused.append((tag, f"ladder_fair refused it: "
                                 f"{getattr(f, 'why', '') or 'no reason given'}"))
            continue
        price = getattr(f, "price", None)
        if price is None:
            price = omap.get((norm_player(str(who)), float(thr)))
        if price is None:
            refused.append((tag, "no price for the side being bet — a "
                                 "one-sided row is not a price (B101)"))
            continue
        v = vmap.get(norm_player(str(who)))
        if not v:
            refused.append((tag, "no role verdict for this player. Run "
                                 "ff_props.boost_verdict on the OVER and "
                                 "pass it in `verdicts` — an unscreened leg "
                                 "is not a clear one, and a rung inherits "
                                 "the player's screen, not a screen of its "
                                 "own threshold"))
            continue
        verdict, vside = str(v[0]), str(v[1]).upper()
        reasons = tuple(v[2]) if len(v) > 2 and v[2] else ()
        if vside != "OVER":
            refused.append((tag, f"the verdict supplied was computed for "
                                 f"{vside}, and a rung is an OVER. A verdict "
                                 f"does not carry across sides (B126)"))
            continue
        team = pos = None
        if meta:
# Normalised, not raw, and `aliases` for the rest — see
            # `_meta_lookup` for which name differences each closes.
            team, pos = _meta_lookup(who, meta, aliases)
        # BoostLeg validates at construction and RAISES — on a circular
        # fair, an out-of-range fair_prob, a verdict with no side. Right for
        # a hand-built leg and wrong for a loop over a whole ladder, where
        # one bad rung would take the other 149 with it. Refused by name
        # instead (lesson 14: a check must fail, not crash), and the
        # message is the validator's own so nothing is paraphrased.
        try:
            kept.append(_rung_leg(
            event_id=event_id, book=book, market=market, player=str(who),
            side="OVER", odds=float(price), fair_prob=float(f.fair),
            fair_source=str(getattr(f, "fair_source", "") or ""),
            devig_method="ladder (own-main crossing)",
            # The canonical line, NOT the posted N. A rung at N is exactly
            # "over N - 0.5" and `canonical_bet` relies on `line` carrying
            # that, which is how a rung collides with its own main line.
            line=float(getattr(f, "canonical_line", float(thr) - 0.5)),
            player_id=getattr(f, "player_id", None),
            verdict=verdict, verdict_side="OVER",
            verdict_reasons=reasons + (
                "role screen taken from this player's MAIN line, not from "
                "this rung — the screen is about the role and the side, not "
                "the threshold",),
            team=team, pos=pos,
            line_type=line_type,
            level_source=str(getattr(f, "anchor", "") or ""),
            shape_source=str(book),
            # The anchor's depth and its fair at the pinned point, so
            # `anchor_opening` / `anchor_thin` / `anchor_untested` can fire
            # on a rung. Until 2026-11-11 this was a hardcoded None: the
            # second live run built +3.6% to +15.9% "PLAY" slips from rungs
            # whose levels sat at Pinnacle's opening limit, 121 of 306 of
            # them on an exact 0.5000, and nothing said so (B86, again, on
            # the legs F12 added).
            anchor_liquidity=getattr(f, "anchor_liquidity", None),
            anchor_level_fair=getattr(f, "anchor_fair", None),
            fair_sd=getattr(f, "uncertainty", None),
            # `tiers` is `book_liquidity_tiers(odds)`, keyed by ANCHOR book.
            # Not passed -> "" (never looked up), which B75 keeps distinct
            # from a book that quotes no tier.
            opening_liquidity_tier=(tiers or {}).get(
                str(getattr(f, "anchor", "") or "")),
            tier_source=("" if tiers is None else
                         "measured" if (tiers or {}).get(
                             str(getattr(f, "anchor", "") or "")) is not None
                         else "book quotes none"),
            # B128. A rung carries NO model probability, deliberately. The
            # model's level error against a sharp anchor is sd 11.5pp and
            # its SHAPE disagrees with the market's by 3.1x the ladder's own
            # precision even after the level is pinned away, so a
            # model-vs-market rung edge is noise. None means NOT SUPPLIED,
            # which is the state ff_betlog already reports as such.
            model_p=None))
        except ValueError as e:
            refused.append((tag, f"refused at construction: {e}"))
    return kept, refused


# How many player groups price targeting will WALK. Walking is a binary
# search per group and cheap; this only stops a runaway. C(150, 3) fits.
MAX_PLAYER_GROUPS = 500_000
# The real cost bound: one `make_candidate` per in-band group. Measured at
# 9,880 builds in 0.4s (40 players of main lines), so 200,000 is seconds,
# not minutes, and a full main-line slate fits with a wide margin.
MAX_BUILT_CANDIDATES = 200_000


def _widen_interval(ci, *estimates) -> tuple[tuple, bool]:
    """(interval covering ci and every estimate, whether it had to widen).

    Extracted so it can be tested directly. The behaviour it replaces was
    a BRACKET TEST — attach the interval only if it already contained the
    `r` being used — and on the live board it contained it by 0.0011, so
    one re-measurement of either table would have silently dropped the
    interval and changed what `joint_error` takes a sign from. Two tables
    disagreeing about a pair IS uncertainty about that pair, so the
    interval covers both rather than being discarded for not already
    doing so.
    """
    lo, hi = min(ci[0], ci[1]), max(ci[0], ci[1])
    vals = [float(e) for e in estimates if e is not None]
    out = (min([lo] + vals), max([hi] + vals))
    return out, out != (lo, hi)


def _meta_lookup(name, meta, aliases=None):
    """(team, pos) for a board spelling. Two mechanisms, two classes.

    BE PRECISE ABOUT WHAT EACH ONE FIXES. The first live board carried
    three name variants at once and they are NOT the same problem:

      * PUNCTUATION AND SPACING — "J.J McCarthy" vs "J.J. McCarthy",
        "D.J. Moore" vs "DJ Moore". `norm_player` collapses these, so the
        normalised pass below resolves them. This is the class that was
        silently failing, because the lookup used the RAW key.

      * FIRST-NAME VARIANTS — "Cam"/"Cameron" Skattebo,
        "Chig"/"Chigoziem" Okonkwo. `norm_player` is documented NOT to
        collapse these and does not, so the normalised pass does NOTHING
        for them. An earlier version of this docstring claimed it did,
        which was a comment asserting a fix the code had not made.
        The documented remedy is `propline_search_players`, whose
        `known_names` lists both spellings against one id — a CALLER
        supplies that as `aliases`, because this module makes no tool
        calls. Without it, these still miss.

    `aliases` maps any spelling -> the meta key, and is normalised on both
    sides so a caller need not match punctuation either.

    Returns (None, None) rather than guessing, and never a near match:
    B44/B101/B127 are three separate incidents of a fuzzy name join losing
    a player his whole board.
    """
    if not meta:
        return (None, None)
    got = meta.get(name)
    if got is not None:
        return got
    want = norm_player(str(name))
    if not want:
        return (None, None)
    if aliases:
        for k, v in aliases.items():
            if norm_player(str(k)) == want:
                hit = meta.get(v)
                if hit is None:
                    for mk, mv in meta.items():
                        if norm_player(str(mk)) == norm_player(str(v)):
                            hit = mv
                            break
                if hit is not None:
                    return hit
    for k, v in meta.items():
        if norm_player(str(k)) == want:
            return v
    return (None, None)


# Below this a probability is shown as "1 in N" as well as a percentage,
# and a priceable slip gets the LONGSHOT line. 1% is where one decimal
# place stops carrying two significant figures; it is a display boundary,
# not a judgement about which slips are worth betting.
LONGSHOT_P = 0.01


def _prob(p) -> str:
    """A probability a person can read at any size."""
    if p is None:
        return "n/a"
    p = float(p)
    if p <= 0:
        return "0%"
    if p >= LONGSHOT_P:
        return f"{p:.1%}"
    return f"{p * 100:.3g}% (1 in {1.0 / p:,.0f})"


# Books whose same-game quotes are NOT used to set the price target. An
# exchange prices a parlay off resting orders rather than a correlated SGP
# model, and it is where most of the >1.0 factors come from; a boost token
# lives at a sportsbook.
SGP_EXCHANGE_BOOKS = ("novig", "prophetx", "sxbet", "matchbook", "smarkets",
                      "kalshi", "polymarket", "polymarket_us")


# A book's own lower quartile is used only when it has at least this many
# quotes on file; below that the pooled figure stands in. Eight puts the
# quartile between the second and third lowest observations, so it is not
# just the single worst quote. FanDuel qualifies with exactly eight, all
# from one event — treat its figure as provisional.
MIN_QUOTES_FOR_BOOK_FACTOR = 8


def factor_rows() -> list[tuple[str, int | None, float]]:
    """Every sportsbook quote / ENGINE-product factor on file, as
    (book, legs in the slip or None when it was not recorded, factor).

    The original list is BetMGM's (B55); its leg counts are in
    SGP_FACTORS_OBSERVED_LEGS, None where a sitting did not record them. The 2026-11-11 live runs priced three-leg shortlists only. The
    2026-11-12 rows carry their leg count, and only the slips the engine
    could MEASURE are used: a slip it refuses is quoted above the product
    (B181) and can never be a qualifier, so it must not set the target.
    Exchanges are left out: see SGP_EXCHANGE_BOOKS.
    """
    out = [("betmgm", n, x) for x, n
           in zip(SGP_FACTORS_OBSERVED, SGP_FACTORS_OBSERVED_LEGS)]
    for rows in (SGP_FACTORS_LIVE_20261111, SGP_FACTORS_LIVE_20261111_3A):
        out += [(book, 3, eng) for book, eng, _own in rows]
    out += [(book, n, x) for book, n, x, measurable
            in SGP_FACTORS_LIVE_20261112 if measurable]
    return [r for r in out if r[0] not in SGP_EXCHANGE_BOOKS]


def factors_by_book(n_legs=None) -> dict[str, list[float]]:
    """Measured factors keyed by sportsbook; with `n_legs`, only the quotes
    on slips of that many legs."""
    out: dict[str, list[float]] = {}
    for book, n, x in factor_rows():
        if n_legs is None or n == int(n_legs):
            out.setdefault(book, []).append(x)
    return out


def sportsbook_factors() -> list[float]:
    """Every measured sportsbook factor, pooled across books."""
    return [x for xs in factors_by_book().values() for x in xs]


def _lower_quartile(xs) -> float:
    """Linear interpolation between order statistics, so one new
    measurement moves the figure smoothly instead of jumping."""
    xs = sorted(xs)
    i = 0.25 * (len(xs) - 1)
    lo = int(i)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (i - lo)


def _target_factor(book=None, n_legs=None) -> float:
    """The quote/product factor a same-game product is aimed with.

    B161 (2026-11-11): the LOWER QUARTILE, not the median — a miss voids a
    token and an overshoot only lengthens the slip a little.

    B167 (same day, after live run 3A): PER BOOK. The factor is a property
    of the book's pricer, so one pooled figure aims one book's slips too
    low and another's too high. Dustin's boosts sit at three books.

    B179 (2026-11-13, after the game-day quotes): PER LEG COUNT as well,
    where that book has enough quotes at that count. A two-leg slip is
    quoted much closer to its product than a three-leg one.

    Falls back in order: the book's quotes at this leg count, the book's
    quotes at any count, every sportsbook pooled. Each step needs
    MIN_QUOTES_FOR_BOOK_FACTOR quotes.
    """
    return target_factor_detail(book, n_legs)[0]


def _factor_sample(book=None, n_legs=None) -> tuple[list[float], str]:
    """(the quotes that describe this book and leg count, what they are)."""
    key = _book_key(book)
    if key and n_legs is not None:
        xs = factors_by_book(n_legs).get(key)
        if xs and len(xs) >= MIN_QUOTES_FOR_BOOK_FACTOR:
            return xs, f"{key}'s own {int(n_legs)}-leg quotes"
    xs = factors_by_book().get(key) if key else None
    if xs and len(xs) >= MIN_QUOTES_FOR_BOOK_FACTOR:
        why = f"{key}'s own quotes"
        if n_legs is not None:
            why += f" at every leg count (too few {int(n_legs)}-leg ones)"
        return xs, why
    pooled = sportsbook_factors()
    return pooled, ("all sportsbooks pooled"
                    + (f" ({key} has only {len(xs)} quote(s) on file)"
                       if xs else
                       f" (no quotes on file for {key})" if key else ""))


def target_factor_detail(book=None, n_legs=None) -> tuple[float, str, int]:
    """(factor, which data it came from, n)."""
    xs, why = _factor_sample(book, n_legs)
    return _lower_quartile(xs), why, len(xs)


def expected_factor(book=None, n_legs=None) -> float:
    """MEDIAN quote/product factor for a book — the expected quote.

    Same data and same fallback as `target_factor_detail`, at the median
    instead of the lower quartile: targeting wants to be safe, an expected
    EV wants to be central.
    """
    xs = sorted(_factor_sample(book, n_legs)[0])
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2.0


_BOOK_ALIASES = {"dk": "draftkings", "fd": "fanduel", "mgm": "betmgm"}


def _book_key(book) -> str:
    k = str(book or "").strip().lower().replace(" ", "")
    return _BOOK_ALIASES.get(k, k)


# B157, decided 2026-11-11. The spacing of the same-game quote grid: the
# quotes observed at BetMGM sat at +400, +425, +450, +475 (and +210, +230),
# roughly 0.25 apart in decimal — see the note under SGP_FACTORS_OBSERVED.
# Two products closer than this are likely quoted at the same grid point,
# so preferring the priceable one inside it costs nothing at the book.
SGP_QUOTE_STEP_DEC = 0.25


def _struct_key(l) -> tuple:
    """What decides a leg's part in the slip's STRUCTURE — not its line."""
    return (norm_player(l.player), l.market, str(l.side).upper(),
            l.event_id, _clean(l.team))


def _is_priceable(legs, meta, cache=None, quotes=None) -> bool:
    """Is this combination's product its joint? Never raises.

    Cached on the structure key when a cache is given. B156's accumulation
    test reads the legs' probabilities, so a cached answer is a first pass;
    `_prefer_priceable` re-checks the exact legs it is about to return.
    """
    key = tuple(sorted(_struct_key(l) for l in legs))
    if cache is not None and key in cache:
        return cache[key]
    try:
        ok = bool(classify(list(legs), meta, None, quotes).priceable)
    except ValueError:
        ok = False
    if cache is not None:
        cache[key] = ok
    return ok


def _prefer_priceable(lists, best, target_dec, cl_dec, meta, cache,
                      quotes=None):
    """A priceable combination within one quote step of `best`, or None.

    Only looks when the cheapest pick is NOT priceable — the common case
    costs one cached lookup. A slip's structure depends on each leg's
    market and side, not its line, so each player's rungs are split by
    market and the cheapest-that-clears search is rerun per market
    combination; the best priceable result wins if it is close enough.
    """
    if _is_priceable(best[1], meta, cache, quotes):
        return None
    per_player = []
    for ls in lists:
        by_mkt: dict = {}
        for l in ls:                       # `ls` is price-sorted; order kept
            by_mkt.setdefault((l.market, str(l.side).upper()), []).append(l)
        per_player.append(list(by_mkt.values()))
    found = None
    for combo in product(*per_player):
        if not _is_priceable([sub[0] for sub in combo], meta, cache, quotes):
            continue
        got = _cheapest_at_least(list(combo), target_dec)
        if got is None or got[0] > cl_dec:
            continue
        if found is None or got[0] < found[0]:
            found = got
    if found is None or found[0] - best[0] > SGP_QUOTE_STEP_DEC:
        return None
    # The cache answered for the structure; confirm these exact legs.
    return found if _is_priceable(found[1], meta, None, quotes) else None


def _leg_key(l) -> tuple:
    """Deterministic ordering for two legs at the same price."""
    return (norm_player(l.player), l.market,
            float(l.line) if l.line is not None else 0.0, str(l.book))


def _cheapest_at_least(lists, want_dec: float):
    """(decimal product, legs) — the CHEAPEST product >= want_dec, or None.

    `lists` are each sorted ascending by decimal price. Every choice of the
    first n-1 legs is walked, and the last leg is found by binary search:
    the smallest rung whose price clears the multiple still needed. Exact,
    and O(k^(n-1) log k) rather than the O(k^n) of enumerating products —
    which measured 63s on a 500-leg pool.

    Returns None when no combination reaches `want_dec` at all, which is a
    real answer and not an error: it means even the longest rung of every
    player together falls short.
    """
    if not lists or any(not ls for ls in lists):
        return None
    head, tail = lists[:-1], lists[-1]
    tail_dec = [to_decimal(l.odds) for l in tail]
    best = None
    for pick in product(*head):
        d = 1.0
        for l in pick:
            d *= to_decimal(l.odds)
        need = want_dec / d
        # bisect on the sorted tail prices: first index with price >= need
        lo, hi = 0, len(tail_dec)
        while lo < hi:
            mid = (lo + hi) // 2
            if tail_dec[mid] < need:
                lo = mid + 1
            else:
                hi = mid
        if lo >= len(tail_dec):
            continue
        tot = d * tail_dec[lo]
        legs = list(pick) + [tail[lo]]
        # Deliberately NOT tie-broken on the combination's own contents.
        # A revert that removed a `_combo_key` tie-break here came back NOT
        # CAUGHT, and the reason is that it was unreachable: the per-player
        # lists are sorted with `_leg_key` before this runs, so
        # `product(*head)` iterates in a fixed order and the strict `<`
        # below keeps the FIRST minimal product. Determinism comes from
        # the list sort, not from a second key here (lesson 64 — a guard
        # no input can reach reads as coverage). Section 76 pins the
        # order-independence instead, by running a reversed pool.
        if best is None or tot < best[0]:
            best = (tot, legs)
    return best


def _combo_key(legs) -> tuple:
    """A deterministic tie-break for two combinations at the same price.

    Two rung choices can product to the same American number, and which
    one a run picks must not depend on dict or set ordering. Keyed on the
    legs' own lines and prices, which are the only things that distinguish
    them.
    """
    return tuple(sorted((norm_player(l.player),
                         float(l.line) if l.line is not None else 0.0,
                         float(l.odds)) for l in legs))


def _rung_leg(*args, **kw) -> BoostLeg:
    """Named so the `try` above wraps exactly one thing and reads clearly."""
    return BoostLeg(*args, **kw)


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


def enumerate_candidates(legs, meta=None, *, boost_pct: float | None = None,
                         mode: str, event_id: str | None = None,
                         floor: float = FLOOR, ceiling: float = CEILING,
                         legs_per_slip: int | None = None, limit: int = 8,
                         stake: float | None = None,
                         token=None, aliases=None,
                         quotes=None) -> Shortlist:
    """Shortlist slips that clear the floor, ranked deterministically.

    Costs no tool calls. Price the survivors with price_sgp — the local
    ranking is a heuristic and the book's price is the answer.

    F11. Pass `token` (an `ff_tokens.Token`) and the slips are built to the
    PROMO's terms instead of this project's own band. The two answer
    different questions and B55 is emphatic about not confusing them: FLOOR
    asks "is this slip worth betting", a token minimum asks "will the book
    let me apply the token at all". Where both apply, the BINDING one wins
    and the shortlist says which it used.

    A token supplies `boost_pct`, `stake` and `legs_per_slip` when the text
    stated them; it never invents them. If the token did not state a
    percentage and the caller did not pass one, this refuses — a shortlist
    built at a guessed boost ranks slips for a promo that does not exist.
    """
    tok_notes: list[str] = []
    if token is not None:
        if getattr(token, "kind", None) == "stake_back":
            raise ValueError(
                "this is a STAKE-BACK token, not a boost (B56). Its value "
                "rises as win probability FALLS, so the right bet for it is "
                "the longest shot that qualifies, not a slip in this "
                "project's band — enumerating boost candidates for it "
                "inverts the whole question. Price it with "
                "ff_props.stake_back_ev / stake_back_band instead.")
        if boost_pct is None:
            boost_pct = getattr(token, "pct", None)
        if stake is None:
            stake = token.effective_stake
        tmin_legs = getattr(token, "min_legs", None)
        tmin = getattr(token, "min_odds", None)
        if tmin is not None:
            # The binding constraint, named. A token minimum below this
            # project's floor does NOT loosen the floor: the floor is a
            # judgement about whether the slip is worth betting at all.
            if float(tmin) > floor:
                tok_notes.append(
                    f"floor raised from {floor:+.0f} to the token's minimum "
                    f"{float(tmin):+.0f} — the binding constraint")
                floor = float(tmin)
            elif float(tmin) == floor:
                tok_notes.append(
                    f"token minimum {float(tmin):+.0f} equals this "
                    f"project's floor, so both bind at the same number — "
                    f"they still answer different questions (B55) and a "
                    f"change to either does not move the other")
            else:
                tok_notes.append(
                    f"token minimum {float(tmin):+.0f} is below this "
                    f"project's floor {floor:+.0f}, so the floor still "
                    f"binds; they answer different questions (B55)")
        if getattr(token, "sgp_only", None) is True and mode == "cross-game":
            raise ValueError(
                "this token is SGP-only and mode is cross-game. Building "
                "cross-game candidates for it produces slips the book will "
                "not let the token apply to.")
        for m in getattr(token, "missing", []) or []:
            tok_notes.append(f"token did not state: {m}")
        for u in getattr(token, "unparsed", []) or []:
            tok_notes.append(f"token text not read: {u}")
    if boost_pct is None:
        raise ValueError(
            "boost_pct is required and was not supplied, by argument or by "
            "token. It is not defaulted: the shortlist ranks and filters on "
            "the boosted return, so a guessed percentage produces a ranking "
            "for a promo that does not exist. State the token's terms.")
    # F11. A token saying "2+ legs" states a MINIMUM, not a size. Building
    # only 2-leg slips misses the 3-leg ones that clear the floor (three
    # -150 legs product to +363 while two product to +256), and building
    # only 3 misses shorter eligible ones. So every size from the token's
    # minimum up to the project default is enumerated, and the shortlist
    # says which sizes it built.
    sizes: list[int]
    if legs_per_slip is not None:
        sizes = [legs_per_slip]
    elif token is not None and getattr(token, "min_legs", None):
        lo = int(token.min_legs)
        sizes = list(range(lo, max(lo, 3) + 1))
        if len(sizes) > 1:
            tok_notes.append(
                f"token allows {lo}+ legs, so sizes {sizes} were all built "
                f"— a minimum is not a size, and the shorter ones often "
                f"miss the floor while the longer ones clear it")
    else:
        sizes = [3]
    if stake is None:
        # A dollar figure nobody stated is a number about a bet nobody can
        # place, so this is recorded rather than silently assumed.
        stake = 10.0
        tok_notes.append(
            "stake not stated — priced at $10.00 so the EV PERCENTAGES are "
            "comparable; every dollar figure here is therefore illustrative")
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

    # The brute-force combination list that used to be built here is GONE.
    # It materialised every leg combination before anything looked at it —
    # C(900, 3) is 121 million lists, which is what actually exhausted
    # memory on a 900-rung pool, not the targeting below. Grouping by
    # player never generates a combination naming one man twice, so the
    # 67,114 of 104,586 that the first live board threw away are no longer
    # produced at all.

    # ------------------------------------------------------------------
    # F12's price targeting. THIS REPLACED `if names in seen: continue`.
    #
    # That dedupe was correct for as long as the pool held one line per
    # player per market: a player triple then had exactly one combination,
    # so keeping the first kept the only one. F12 put a player's whole
    # LADDER in the pool — 16 to 21 legs each on the first live board — and
    # the same line silently collapsed thousands of genuinely different
    # bets per triple down to whichever one `combinations()` yielded first.
    # Pool order is `ladder_fair` order, which is ascending threshold, so
    # the survivor was always the shortest, heaviest-favourite rung of
    # every player.
    #
    # Measured on event 53178: of 104,586 structurally valid combinations,
    # 10,005 were INSIDE the +300..+900 band. The enumerator priced 35 —
    # exactly C(7,3), one per triple — found them all below the floor, and
    # reported "the legs are too short to reach the boost's minimum price."
    # Confident, specific, and the opposite of true. That reason line was
    # the worst part: a reader acting on it hunts longer rungs while the
    # pool already holds hundreds of in-band slips.
    #
    # It survived every fixture in section 75, because those fixtures had
    # one combination per triple. A dedupe cannot be exercised by a pool
    # with nothing to dedupe.
    #
    # WHAT IT DOES NOW: per player group, find the CHEAPEST combination
    # that clears the floor. "Target the minimum, do not reach past it" is
    # Dustin's own scope decision on F11 and is what rungs are FOR. This is
    # a SELECTION rule and B57 applies to it: it does not rank slips by
    # predicted value, which B57 showed cannot be done — it picks the
    # cheapest way to reach a required price, which is arithmetic on posted
    # odds and not a model claim.
    #
    # NOT BY ENUMERATION. Brute force is O(k^n) per group and took 63s on a
    # 500-leg pool, which a full board will exceed. Each player's rungs are
    # sorted by decimal price once, then for every choice of the first n-1
    # legs the last is found by binary search — the smallest rung that
    # clears the remaining multiple. Exact, and O(k^(n-1) log k).
    by_player: dict[str, list] = {}
    for l in kept:
        by_player.setdefault(norm_player(l.player), []).append(l)
    for who in by_player:
        by_player[who].sort(key=lambda l: (to_decimal(l.odds), _leg_key(l)))

    fl_dec = to_decimal(floor)
    cl_dec = to_decimal(ceiling)
    # WHAT THE TARGET IS A TARGET FOR. Found in the 2026-11-11 review: the
    # first version aimed the PRODUCT at the floor, and the floor is a
    # condition on the book's real QUOTE. B55 measured that a same-game
    # quote is the product times 0.77 to 0.99 — a +516 product quoted +400
    # — so a slip targeted to a +300 product quotes around +240 to +290,
    # fails the floor once priced, and voids a token with that minimum.
    # Targeting made this systematic: every shortlisted same-game slip sat
    # just over the line on the wrong number.
    #
    # So in a same-game build the product is aimed at floor / factor, with
    # the factor taken as the LOWER QUARTILE of every measured sportsbook
    # quote (`_target_factor`, B161) rather than a constant typed here. It is still a prediction: the quote snaps to a
    # coarse grid (B61) and the observed range is wide, so the note below
    # gives the worst case too, and only `price_sgp` settles it. Cross-game
    # parlays are not haircut this way and keep the plain floor.
    # The slip is bet at ONE book; if the pool somehow mixes books, aim with
    # the harshest of them rather than guess which one the slip lands at.
    _books = sorted({_book_key(l.book) for l in kept})
    _fd = (min((target_factor_detail(b, legs_per_slip) for b in _books),
               key=lambda t: t[0]) if _books
           else target_factor_detail(None, legs_per_slip))
    sgp_factor = (_fd[0] if mode != "cross-game" else 1.0)
    target_dec = fl_dec / sgp_factor
    n_below_target = 0
    n_swapped = 0
    _struct_cache: dict = {}
    chosen: list[tuple] = []
    n_rung_alts = 0
    n_groups_in_band = 0
    n_groups_short = 0
    n_groups_long = 0
    target_notes: list[str] = []
    cands = []
    n_dupe = 0                    # combinations refused as one man twice
    dupe_reasons: list[str] = []
    # `n_same` is gone, and that is the point: grouping BY PLAYER makes a
    # combination naming one man twice structurally impossible rather than
    # something to count and skip. It was 67,114 of 104,586 on the first
    # live board — work that is now never generated.

    # A bounded refusal rather than an unbounded run — but bounded on what
    # actually costs something. The first version of this capped PLAYER
    # GROUPS at 600, which C(18, 3) = 816 already exceeds: an ordinary
    # single-game board of main lines (a QB, two backs, four receivers and
    # two tight ends a side is 18 players) was refused outright, where the
    # same pool had run fine for weeks. The cap was sized against the
    # 900-rung pool that exhausted memory, and the memory went on the
    # brute-force combination list that no longer exists, not on groups.
    #
    # Walking a group is cheap (a binary search); the expensive step is
    # `make_candidate`, and that now runs ONLY for groups with an in-band
    # combination — out-of-band groups were being built and then thrown
    # away by the band filter. So groups get a generous bound and built
    # candidates get the real one.
    n_groups_total = sum(math.comb(len(by_player), n) for n in sizes
                         if len(by_player) >= n)
    if n_groups_total > MAX_PLAYER_GROUPS:
        raise ValueError(
            f"this pool makes {n_groups_total:,} player group(s) at "
            f"size(s) {sizes}, past the {MAX_PLAYER_GROUPS:,} this will "
            f"walk. The cost is in the number of distinct PLAYERS "
            f"({len(by_player)} here), not the rungs — narrow the pool to "
            f"the players you would actually bet.")

    for n_legs in sizes:
        if len(by_player) < n_legs:
            continue
        for who in combinations(sorted(by_player), n_legs):
            lists = [by_player[w] for w in who]
            if mode == "cross-game":
                # One leg per EVENT. A player plays one game, so distinct
                # players in distinct events is the same constraint — but
                # it is checked rather than assumed.
                evs = {ls[0].event_id for ls in lists}
                if len(evs) != n_legs:
                    continue
            n_combo = 1
            for ls in lists:
                n_combo *= len(ls)
            if n_combo > 1:
                n_rung_alts += n_combo - 1
            best = _cheapest_at_least(lists, target_dec)
            below_target = False
            if (best is None or best[0] > cl_dec) and target_dec > fl_dec:
                # Nothing reaches the price target inside the band. Fall
                # back to the cheapest that clears the floor on the PRODUCT
                # — the old behaviour, and the only option for a group with
                # one line per player — but say the quote will likely miss.
                best = _cheapest_at_least(lists, fl_dec)
                below_target = best is not None and best[0] <= cl_dec
                if below_target:
                    n_below_target += 1
            # Direction, exactly, from the sorted ends — no enumeration.
            lo_dec = 1.0
            hi_dec = 1.0
            for ls in lists:
                lo_dec *= to_decimal(ls[0].odds)
                hi_dec *= to_decimal(ls[-1].odds)
            swapped = ""
            if best is not None and best[0] <= cl_dec and not below_target:
                alt = _prefer_priceable(lists, best, target_dec, cl_dec,
                                        meta, _struct_cache, quotes)
                if alt is not None:
                    swapped = (f" — took the PRICEABLE {american(alt[0]):+.0f} "
                               f"over the cheapest {american(best[0]):+.0f}, "
                               f"which was not priceable; within one quote "
                               f"step, so the book likely quotes both alike")
                    best = alt
                    n_swapped += 1
            if best is not None and best[0] <= cl_dec:
                n_groups_in_band += 1
                pick = best[1]
                if n_combo > 1:
                    (target_notes.insert if swapped else target_notes.append)(
                        *((0,) if swapped else ()),
                        f"{', '.join(who)}: chose {american(best[0]):+.0f} "
                        f"from {n_combo:,} combination(s) spanning "
                        f"{american(lo_dec):+.0f} to {american(hi_dec):+.0f} "
                        f"— cheapest that clears the "
                        + ("floor on the product only, BELOW the price target"
                           if below_target else "price target")
                        + swapped)
            elif hi_dec < fl_dec:
                n_groups_short += 1
                continue                # counted, never built
            else:
                n_groups_long += 1
                continue                # out of band: counted, never built
            chosen.append((who, list(pick), n_combo))
            if len(chosen) > MAX_BUILT_CANDIDATES:
                raise ValueError(
                    f"more than {MAX_BUILT_CANDIDATES:,} player groups have "
                    f"an in-band combination, and each one is a full "
                    f"`make_candidate`. Narrow the pool to the players you "
                    f"would actually bet, or tighten the band.")

    n_short, n_long = n_groups_short, n_groups_long
    for who, c, n_combo in chosen:
        # F12. `classify` RAISES on two legs carrying the same player_id
        # under names that normalise differently — "Cam Ward" and "Cameron
        # Ward" are one man and two keys, and the ids are what catch it.
        # That is the right answer for a hand-built slip and the wrong one
        # here: with rungs in the pool that pair is a NORMAL combination,
        # and an exception out of this loop takes the whole shortlist with
        # it. So it is caught and recorded as a refused combination.
        try:
            cand = make_candidate(c, meta, boost_pct=boost_pct, stake=stake,
                                  aliases=aliases, quotes=quotes)
        except ValueError as e:
            n_dupe += 1
            dupe_reasons.append("; ".join(sorted(
                {norm_player(l.player) for l in c})) + f": {e}")
            continue
        if token is not None and getattr(token, "min_odds", None) is not None:
            # B55. So `token_minimum` can answer once the slip is priced,
            # rather than the caller having to remember to set it.
            cand.token_min_odds = float(token.min_odds)
        cand.min_odds = float(floor)
        # The counters are GROUP counts set above, measured exactly from
        # each group's sorted ends rather than from the one combination
        # that happened to be priced. That is what lets the reason line
        # below tell the truth about direction.
        if cand.independent_odds < floor or cand.independent_odds > ceiling:
            continue
        cands.append(cand)

    cands.sort(key=lambda c: c.key)
    cands = cands[:limit]

    reason = ""
    _banded = [c for c in cands if c.ev_band is not None]
    if cands and any(c.verdict == "PLAY" for c in cands) and _banded:
        best = max(_banded, key=lambda c: c.rank)
        reason = (f"best anticipated ROI {best.ev_band[0]:+.1%} to "
                  f"{best.ev_band[1]:+.1%} across the measured hold band — "
                  f"ADVISORY. Price the shortlist with price_sgp; the real "
                  f"quote decides.")
    elif cands and any(c.verdict == "PRICE IT" for c in cands):
        # Candidates exist and the measured band does not describe them, so
        # there is no anticipated ROI to lead with and inventing one is the
        # `P(cash) 0.0%` beside `+9.3% to +21.9%` failure at shortlist
        # level. `best` is chosen only among candidates that HAVE a band
        # above, because `max(...).ev_band[0]` on a band-less candidate
        # raises — two reverts crashed here rather than failing.
        _n = sum(1 for c in cands if c.verdict == "PRICE IT")
        reason = (f"{_n} of {len(cands)} candidate(s) have a P(cash) that "
                  f"contradicts their own product price, so the measured "
                  f"hold band says nothing about them and no anticipated "
                  f"ROI is reported. Price them with price_sgp — that "
                  f"replaces the band with an observation.")
    elif cands:
        band = cands[0].hold_band
        best = max((c for c in cands if c.ev_band is not None),
                   key=lambda c: c.rank, default=None)
        _pe = [c.predicted_ev for c in cands if c.predicted_ev is not None]
        got = (f"Best anticipated is {best.ev_band[0]:+.1%} at the "
               f"pessimistic end. " if best is not None else
               # "No candidate here can be priced at all" was printed on
               # seven of eight game-day shortlists whose slips were
               # bounded (FLOOR ONLY / ESTIMATE ONLY) and had an EV the
               # moment they were quoted.
               (f"The shortlisted slips are correlated, so none has a "
                f"plain P(cash); {len(_pe)} of {len(cands)} have a bound "
                f"or estimate, best predicted EV {max(_pe):+.1%} at the "
                f"quote this book usually gives. " if _pe else
                "No candidate here can be priced at all. "))
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
            if n_groups_in_band:
                # FIRST, before any count-based branch. An in-band group
                # proves there were enough legs AND that the band was
                # reached, so every sentence below it would be false. The
                # fixture that exercises this came back "not enough legs
                # survived intake — 3 leg(s) available" on a pool with
                # three legs and a valid +450 group: the same
                # confident-and-wrong shape as the defect this whole
                # branch exists to prevent, one sentence over.
                reason = (f"{n_groups_in_band} player group(s) DID have an "
                          f"in-band combination and no candidate survived "
                          f"pricing — so the band is reachable and the legs "
                          f"are NOT the problem. Read build_notes and "
                          f"dropped: something after the price filter "
                          f"removed them. Do not go looking for longer or "
                          f"shorter legs.")
            elif not n_short and not n_long:
                # F11 regression, found live within the hour: `legs_per_slip`
                # is None unless the caller passed one, because the sizes to
                # build now come from `sizes` — so this printed "a None-leg
                # slip", naming a size that does not exist. The message has
                # to name what was actually attempted.
                want = (f"{sizes[0]}-leg" if len(sizes) == 1 else
                        f"{'- or '.join(str(n) for n in sizes)}-leg")
                reason = (f"not enough legs survived intake to build a "
                          f"{want} slip from them — {len(kept)} leg(s) "
                          f"available after drops")
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
    build_notes: list[str] = []
    if n_dupe:
        build_notes.append(
            f"{n_dupe} combination(s) refused as naming one player twice "
            f"under names that normalise differently — caught on player_id, "
            f"which is the only thing that catches it")
        build_notes.extend(f"  {r}" for r in dupe_reasons[:5])
    if sgp_factor < 1.0 and chosen:
        _bk = "/".join(_books) or "unknown book"
        # The SAME sample the factor came from, so the range and the n
        # in this note describe one set of quotes.
        _fx = min((_factor_sample(b, legs_per_slip) for b in _books),
                  key=lambda t: _lower_quartile(t[0]))[0] if _books \
            else _factor_sample(None, legs_per_slip)[0]
        worst = min(_fx)
        build_notes.append(
            f"same-game products are aimed at {american(target_dec):+.0f}, "
            f"not {floor:+.0f}: the floor applies to the book's QUOTE. For a "
            f"slip at {_bk} the measured quote/product factor has a lower "
            f"quartile of {sgp_factor:.2f}, from {_fd[1]} (n={_fd[2]}, range "
            f"{worst:.2f}-{max(_fx):.2f}). Expect roughly one quote in four "
            f"to come in under the floor anyway; at the worst observed "
            f"factor a {american(target_dec):+.0f} product quotes "
            f"{american(target_dec * worst):+.0f}. A prediction — "
            f"price_sgp decides.")
        if n_below_target:
            build_notes.append(
                f"{n_below_target} group(s) clear {floor:+.0f} on the "
                f"product but cannot reach the price target, so their real "
                f"quote will probably come in UNDER the floor. They are "
                f"listed because the factor is a prediction, not because "
                f"they are expected to clear.")
    if n_swapped:
        build_notes.append(
            f"{n_swapped} group(s) took a PRICEABLE combination in place of "
            f"a cheaper one that was not, each within one quote step "
            f"({SGP_QUOTE_STEP_DEC:.2f} decimal) of the cheapest — a real "
            f"EV instead of a bound or a refusal, at effectively the same "
            f"price (B157).")
    if n_rung_alts:
        build_notes.append(
            f"price targeting chose between {n_rung_alts + len(chosen)} "
            f"combination(s) across {len(chosen)} player group(s), taking "
            f"the CHEAPEST that clears the price target in each — "
            f"F11's rule, target the minimum and do not reach past it. "
            f"{n_groups_in_band} group(s) had an in-band option.")
        for t in target_notes[:6]:
            build_notes.append(f"  {t}")
        if len(target_notes) > 6:
            build_notes.append(f"  ... and {len(target_notes) - 6} more")
    n_rung = sum(1 for l in kept if l.is_rung)
    if n_rung:
        build_notes.append(
            f"{n_rung} of {len(kept)} legs in the pool are rungs rather "
            f"than main lines (F12). A rung carries NO model probability by "
            f"design: B128 measured the model's shape disagreement at 3.1x "
            f"the ladder's own precision even with the level pinned away, "
            f"so a model-vs-market rung edge is noise. Rungs are here to "
            f"let you PICK a price, not to claim one is mispriced.")
        sc = sorted({l.book for l in kept if l.shape_circular})
        if sc:
            build_notes.append(
                f"and the SHAPE of those rungs' fairs came from the book "
                f"being bet ({', '.join(sc)}) — the level is pinned to an "
                f"independent anchor, the curve between rungs is not. So "
                f"'which rung is cheapest' is answerable here and 'does "
                f"this rung beat the market' is not.")
    return Shortlist(candidates=cands, mode=mode, boost_pct=boost_pct,
                     reason=reason, dropped=dropped,
                     token_notes=tok_notes, build_notes=build_notes)


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
                     token_min_odds=cand.token_min_odds,
                     # Both were dropped here until 2026-11-12, so a priced
                     # candidate lost its measured noise ("no quotes
                     # supplied, using the measured fallback") and its
                     # boost's minimum the moment it got a real quote.
                     quotes=cand.quotes, min_odds=cand.min_odds)


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

# B57. Below this spread in the ranking quantity, an ordering of candidates
# is not an ordering. Measured on the real MNF board (event 53177, 120
# priceable 3-leg combinations): P(cash) spanned **2.21 points** with sd
# 0.47, five of ten de-vigged fairs sat within 0.5pp of exactly 0.5000, and
# independent odds clustered +543..+611. Every main line on a board sits near
# -112, so three near-coin-flips multiply to the same place whichever three
# they are.
#
# 1 point of P(cash) is the gate because it is already generous: at a ~12.5%
# joint, a 1-point spread is 8% of the quantity, and the differences B57 saw
# were ~1.5 points with half of them resting on fairs pinned at exactly
# 0.5000 by the book's half-yard grid (B54).
#
# This is NOT fixed by ranking on something else. Aggregate model edge spans
# 41x more, and that spread is the model's own level error: per-leg
# `model_p - fair_prob` measured sd 0.1258 against B128's model level error
# of sd 0.115, a ratio of 1.09. Ranking on it would sort candidates by how
# wrong the model is about each player. CI width is worse — it barely varies
# (1.21x) and correlates NEGATIVELY with the model's error (-0.51, n=11), so
# ranking by confidence picks the legs the model is most wrong about. Sample
# verdict did not vary at all: every leg on the board read ADEQUATE.
#
# So the report says the ordering is not meaningful rather than inventing a
# signal to replace it. An UNPRICED shortlist is a set to go and get quotes
# for; `ev_pct` against real SGP quotes is a different number and is allowed
# to rank.
# How many candidates count as "the ones being considered". The full range
# is the wrong window: a board can span 2.21 points across 120 combinations
# while its top two differ by 0.30, and nobody bets candidate 120.
RANK_MEANINGFUL_TOP_N = 10

# How many times the propagated uncertainty an ADJACENT gap must clear before
# one candidate can be said to beat the next. A ranked list asserts exactly
# that, pair by pair, so the adjacent gap is the quantity — not the
# head-to-tail spread, which a long tail inflates while the head stays flat.
#
# 1.0 is deliberately the loosest defensible bar: it asks only that the gap
# exceed the noise, not that it clear it with margin.
RANK_MEANINGFUL_RATIO = 1.0

# Per-leg uncertainty in a de-vigged fair, used when the board cannot supply
# one. Measured as the cross-book disagreement between two independently
# de-vigged ladders, 106 shared rungs: median 0.76%, and the same figure
# appears as ~0.8pp in the ladder work. Only a fallback — `fair_uncertainty`
# measures it off the board in hand whenever two books quote the same leg.
FAIR_UNCERTAINTY_FALLBACK = 0.008


def fair_uncertainty(legs, quotes=None) -> tuple[float, str]:
    """How far a de-vigged fair can be wrong, measured off the board.

    When `quotes` carries two books on the same player and line, their
    de-vigged fairs disagree by a measurable amount and the median of those
    disagreements IS the uncertainty. With nothing to measure it falls back
    to a figure from the ladder work and says so, because a fallback dressed
    as a measurement is the failure this project keeps filing.
    """
    if not quotes:
        return FAIR_UNCERTAINTY_FALLBACK, "no quotes supplied, using the measured fallback"
    from ff_props import devig as _dv, norm_player as _np
    by_leg: dict[tuple, list[float]] = {}
    for q in quotes:
        o, u = q.get("over"), q.get("under")
        if o is None or u is None or q.get("line") is None:
            continue
        key = (_np(str(q.get("player") or "")), q.get("market"),
               float(q["line"]))
        by_leg.setdefault(key, []).append(_dv(float(o), float(u), "auto")[0])
    spreads = [max(v) - min(v) for v in by_leg.values() if len(v) > 1]
    if len(spreads) < 4:
        return FAIR_UNCERTAINTY_FALLBACK, (
            f"only {len(spreads)} leg(s) quoted by two books, too few to "
            f"measure — using the measured fallback")
    spreads.sort()
    med = spreads[len(spreads) // 2] if len(spreads) % 2 else (
        spreads[len(spreads) // 2 - 1] + spreads[len(spreads) // 2]) / 2
    return med, (f"measured from {len(spreads)} legs quoted by two books")


def rank_is_meaningful(cands, quotes=None) -> tuple[bool, str]:
    """Whether an ordering of these candidates asserts anything.

    Returns (meaningful, why). Judged on the candidates IN HAND rather than
    asserted: a board whose legs genuinely differ produces a real spread and
    gets ranked normally.
    """
    cands = list(cands)
    if len(cands) < 2:
        return True, "fewer than two candidates — nothing to order"
    priced = [c for c in cands if c.priced]
    if priced and len(priced) == len(cands):
        return True, ("priced against real SGP quotes, which differ between "
                      "candidates by more than the product of the legs does")
    # Judged on the TOP candidates, not the full range. The full range
    # passes on a board whose ordering is nonetheless noise: the real MNF
    # board spans 2.21 points across 120 candidates and its top two differ
    # by 0.30. B57's own words were "the ordering of candidates 1 through 40
    # was close to noise" — a wide tail does not make the head separable,
    # and nobody bets candidate 120.
    top = sorted([c for c in cands if c.p_cash is not None],
                 key=lambda c: c.key)[:RANK_MEANINGFUL_TOP_N]
    ps = [c.p_cash for c in top]
    if len(ps) < 2:
        return True, "fewer than two priceable candidates"

    # The ADJACENT gap, because that is what a ranked list claims. The
    # head-to-tail spread passes on a board whose head is flat: the real MNF
    # board spans 2.21 points over 120 candidates, 1.45 over its top ten, and
    # its median adjacent gap is 0.358.
    gaps = sorted(abs(a - b) for a, b in zip(ps, ps[1:]))
    gap = (gaps[len(gaps) // 2] if len(gaps) % 2
           else (gaps[len(gaps) // 2 - 1] + gaps[len(gaps) // 2]) / 2)

    # Propagate each leg's fair uncertainty through the product. A product of
    # k legs carries the relative error of each, added in quadrature.
    u, uwhy = fair_uncertainty(top, quotes)
    # B158: rungs carry their own, wider, uncertainty. The RMS over the
    # legs in play, so a main-line-only board gives exactly `u` as before.
    _tl = [l for c in top for l in c.legs]
    if any(l.fair_sd is not None for l in _tl):
        u = math.sqrt(sum(leg_sd(l, u) ** 2 for l in _tl) / len(_tl))
        uwhy += "; rung legs use their own measured uncertainty"
    k = max(len(c.legs) for c in top)
    base = sum(ps) / len(ps)
    noise = base * (u / 0.5) * (k ** 0.5)
    ratio = gap / noise if noise > 0 else float("inf")
    if ratio >= RANK_MEANINGFUL_RATIO:
        return True, (f"the median adjacent gap over the top {len(ps)} is "
                      f"{gap * 100:.3f} points against {noise * 100:.3f} of "
                      f"propagated noise ({ratio:.2f}x) — {uwhy}")
    flat = sum(1 for c in top for l in c.legs
               if abs(l.fair_prob - 0.5) < 0.005)
    tot = sum(len(c.legs) for c in top)
    return False, (
        f"the median adjacent gap over the top {len(ps)} of {len(cands)} is "
        f"{gap * 100:.3f} points, against {noise * 100:.3f} points of noise "
        f"propagated from the legs' own fair uncertainty ({ratio:.2f}x, "
        f"needs {RANK_MEANINGFUL_RATIO:.1f}x) — {uwhy}"
        + (f". {flat} of {tot} of their legs have a fair within 0.5pp of "
           f"exactly 0.5000" if flat else "")
        + ". Candidate 1 does not beat candidate 2. Get real SGP quotes and "
          "rank on those.")


# ---------------------------------------------------------------------------
# B57's one surviving quality signal — SHOWN, never sorted on
# ---------------------------------------------------------------------------
#
# B57 went looking for anything that could order a shortlist and found
# exactly one quantity that genuinely varies across a real board: the
# liquidity resting on the legs' ANCHOR lines, 5x across 120 candidates.
# Everything else was noise, the model's own level error, or flat.
#
# It is still not a sort key, and this deliberately does not make it one.
# Anchor liquidity measures how much money the MARKET has put behind the
# level, which is the market's confidence in its own number — not this
# slip's value. Sorting on it would rank a shortlist by how well-tested its
# legs are and present that as which slip to bet, which is precisely the
# false ordering B57 concluded the report must refuse to imply.
#
# So it is a column. It tells Dustin which legs rest on a number somebody
# has actually taken a position against, and leaves the ordering refused.
#
# D16/B39: a leg whose anchor reported NO liquidity must not read as a thin
# one or as a deep one. Bovada returns null, DraftKings reported none on
# 0/276 lines and FanDuel on 0/204, so "silent" is the common case and it
# is reported as its own state with its own count.


def price_share(legs):
    """(leg supplying the most of the slip's price, its share of log-odds).

    A parlay's price is the product of its legs' decimal odds, so each
    leg's contribution is its LOG decimal odds. Three equal legs are a
    third each; a -660, a -660 and a +252 are 10%, 10% and 80%.
    """
    logs = [(math.log(to_decimal(l.odds)), l) for l in legs]
    tot = sum(x for x, _ in logs)
    if not logs or tot <= 0:
        return None, 0.0
    top = max(logs, key=lambda t: t[0])
    return top[1], top[0] / tot


def price_balance(legs) -> str:
    """One report line on whether a single leg carries the slip (B165).

    Decided 2026-11-11: lopsided slips stay IN and are labelled. Price
    targeting reaches a product cheaply by pairing near-certain rungs with
    one longer leg, and on the one live board that priced any, such a slip
    got the best quote of three. That is one slip, so this reports rather
    than judges. The line of "more than the other legs combined" is a
    share above one half — the definition of carrying it, not a tuned
    cutoff.
    """
    legs = list(legs)
    if len(legs) < 2:
        return "price balance : single leg"
    top, share = price_share(legs)
    if top is None:
        return "price balance : not computable"
    short = min(legs, key=lambda l: to_decimal(l.odds))
    if share > 0.5:
        rest = ", ".join(f"{l.player} {l.odds:+.0f}" for l in legs
                         if l is not top)
        return (f"price balance : {top.player} ({top.odds:+.0f}) supplies "
                f"{share:.0%} of this slip's price — more than the other "
                f"legs combined ({rest}). It behaves like a single bet on "
                f"that leg with passengers; judge it as one.")
    return (f"price balance : no single leg supplies more than half the "
            f"price (largest {share:.0%}, {top.player}); shortest leg "
            f"{short.player} {short.odds:+.0f}")


@dataclass
class AnchorDepth:
    """Depth behind a candidate's legs, summarised without being ranked."""
    thinnest: float | None = None
    reported: int = 0
    silent: int = 0
    total: int = 0

    def describe(self) -> str:
        if self.total == 0:
            return "anchor depth  : no legs"
        if self.reported == 0:
            return (f"anchor depth  : NOT REPORTED on any of "
                    f"{self.total} legs — this says nothing either way "
                    f"about whether these levels have been tested")
        # Defensive on purpose: the number is formatted only when there
        # IS one, independently of the branch above. A revert that removed
        # the no-readings branch made this line format None and raise out
        # of `report()`, taking the whole report down over a column that is
        # the least important line in it (lesson 14 — a check must fail,
        # not crash, and so must a cosmetic column).
        depth = (f"{self.thinnest:,.0f}" if self.thinnest is not None
                 else "UNKNOWN")
        s = (f"anchor depth  : thinnest leg {depth} "
             f"({self.reported} of {self.total} legs reporting)")
        if self.silent:
            s += f", {self.silent} silent"
        return s + "  — market confidence, NOT a ranking key"


def anchor_depth(legs) -> AnchorDepth:
    """The thinnest anchor among these legs, and how many said nothing.

    THINNEST, not mean: a parlay inherits its weakest anchor, and averaging
    a 10,000 against a 25 reports 5,012 and hides the leg that matters.
    """
    vals = [float(l.anchor_liquidity) for l in legs
            if l.anchor_liquidity is not None]
    return AnchorDepth(thinnest=min(vals) if vals else None,
                       reported=len(vals),
                       silent=sum(1 for l in legs
                                  if l.anchor_liquidity is None),
                       total=len(list(legs)))


def report(cands, boost_label: str = "", quotes=None) -> str:
    """Human-readable, and deliberately loud about what it does not know."""
    out = []
    _ok, _why = rank_is_meaningful(cands, quotes)
    if not _ok:
        out.append("!! THE ORDER BELOW IS NOT A RANKING")
        out.append(f"   {_why}")
        out.append("   Treat these as a SET. Nothing here says candidate 1 "
                   "beats candidate 2.")
        out.append("")
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
            out.append(f"  P(cash)         : {_prob(c.p_cash)}  "
                       f"(product of the de-vigged legs)")
            out.append(f"  boosted breakeven: {_prob(c.breakeven)}")
            if c.p_cash is not None and c.p_cash < LONGSHOT_P:
                # The second live run printed `P(cash): 0.0%`, `breakeven:
                # 0.0%` and `anticipated ROI +9.3% to +21.9%` for a slip
                # paying $912,595 on $10. Every number was right — P(cash)
                # 0.00138% against a 0.00110% breakeven — and at one decimal
                # the report was unreadable, and said nothing about what a
                # 1-in-72,685 shot means for a ROI figure.
                out.append(
                    f"  LONGSHOT: this cashes about 1 time in "
                    f"{1.0 / c.p_cash:,.0f}. Any ROI on it is an average "
                    f"over that many slips, the fairs behind it are deep-"
                    f"tail rungs with the widest error in the ladder, and "
                    f"one slip will almost certainly lose its stake.")
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
            elif c.ev_band is None:
                # The ROI line is OMITTED and the reason takes its place.
                # Printing a band here beside a P(cash) that contradicts it
                # is what produced `P(cash) 0.0%` next to `anticipated ROI
                # +9.3% to +21.9%` on the first live run — two correctly
                # computed numbers that are nonsense side by side.
                out.append(f"  {c.ev_band_reason}")
                out.append(f"  reference band  : {c.hold_band[0]:.1%}-"
                           f"{c.hold_band[1]:.1%} — {c.hold_band_reason}")
            elif c.ev_band is None:
                # Belt and braces: the branch above already catches this,
                # and a revert of it crashed the report rather than
                # failing a check. A report must not be able to raise over
                # a missing number (lesson 14).
                out.append("  anticipated ROI : NOT AVAILABLE — see the "
                           "P(cash) line")
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
            _fok, _fwhy = c.floor
            if _fok:
                # F13. The product is not the joint, but it bounds it, and
                # a bound is a usable number where a refusal was not.
                if c.joint.rel >= 0:
                    out.append(f"  P(cash) FLOOR   : {_prob(c.p_cash_floor)}  "
                               f"(a LOWER BOUND, not an estimate — the "
                               f"product of the de-vigged legs)")
                else:
                    out.append(f"  P(cash) ESTIMATE: {_prob(c.p_cash_floor)}  "
                               f"(the product of the de-vigged legs, "
                               f"OPTIMISTIC by about {abs(c.joint.rel):.1%} "
                               f"— NOT a lower bound)")
                if c.ev_floor_pct is not None:
                    out.append(
                        f"  EV on the {'floor' if c.joint.rel >= 0 else 'estimate'} "
                        f": {c.ev_floor_pct:+.1%}  (against the quoted price"
                        + ("" if c.joint.rel >= 0 else
                           f"; optimistic, so nearer "
                           f"{c.ev_adjusted:+.1%}") + ")")
                else:
                    out.append("  EV on the floor : not priced yet — run "
                               "price_sgp")
                out.append(f"  {_fwhy}")
            else:
                out.append("  NO EV, NO P(cash) — the joint is not the "
                           "product and this project cannot compute it.")
                out.append(f"  why: {_fwhy}")
            out.append(f"  reference band  : not applicable. "
                       f"{c.hold_band_reason}")
        if any(l.is_rung for l in c.legs):
            out.append("  RUNG LEGS: priced by the ladder, NOT by a "
                       "model-vs-market edge (B128). They are here to let "
                       "you pick a price.")
            sc = sorted({l.book for l in c.legs if l.shape_circular})
            if sc:
                out.append(f"  and their fairs' SHAPE came from "
                           f"{', '.join(sc)}, the book being bet — the "
                           f"LEVEL is pinned to an independent anchor, the "
                           f"curve between rungs is not. 'Which rung is "
                           f"cheapest' holds; 'this rung beats the market' "
                           f"does not.")
        try:
            out.append(f"  {price_balance(c.legs)}")
        except Exception as e:                       # pragma: no cover
            out.append(f"  price balance : COULD NOT BE RENDERED "
                       f"({type(e).__name__}: {e})")
        try:
            out.append(f"  {anchor_depth(c.legs).describe()}")
        except Exception as e:                       # pragma: no cover
            # A column must not be able to cost the report. Named rather
            # than swallowed, so a silent omission is not what you get.
            out.append(f"  anchor depth  : COULD NOT BE RENDERED "
                       f"({type(e).__name__}: {e})")
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


# ---------------------------------------------------------------------------
# F15 — score a slip somebody else built
# ---------------------------------------------------------------------------
#
# `enumerate_candidates` BUILDS slips from a leg pool. This one takes a slip
# that already exists — the one on the bet slip, with whatever substitutions
# were made on the way — and says what is wrong with it.
#
# WHY IT EXISTS. Week 9: the engine's slip was Swift / Odunze / Tez Johnson.
# The slip actually placed swapped Tez for Luther Burden on intuition. Tez
# went 76 yards against a 15.5 line and the engine had preferred the OVER; the
# slip lost. Nothing in the pipeline could have said anything, because
# `enumerate_candidates` only ever sees legs it chose itself, and a leg nobody
# proposed is invisible to it.
#
# Two failure modes, and they are different:
#
#   SUBSTITUTION  — a leg the engine never recommended. Needs `recommended=`
#                   to detect, because "the engine did not pick this" is only
#                   meaningful against a set the engine actually picked.
#   SIDE CONFLICT — a leg where the model prefers the other side. Needs
#                   `model_p` on the leg. `verdict == "CLEAR"` does NOT cover
#                   this: boost_verdict answers "does anything argue against
#                   this side", and CLEAR means nothing was found against it.
#                   On the Tez leg every verdict read CLEAR and was right to.
#
# Both are reported as findings against the slip, never as a score. The
# project's standing rule is that the output is a confidence tier and a list
# of refusals, not a number that looks precise.


@dataclass
class SlipFinding:
    """One thing wrong with a slip, at one of three levels.

    STOP  — do not place this as it stands.
    CHECK — place only if you can answer the question it raises.
    NOTE  — worth knowing, not worth stopping for.
    """
    level: str
    leg: str                      # the player, or "" for a slip-level finding
    text: str

    def describe(self) -> str:
        where = f"{self.leg}: " if self.leg else ""
        return f"[{self.level}] {where}{self.text}"


@dataclass
class SlipScore:
    # None only for an empty slip, which is refused before anything prices it.
    candidate: Candidate | None
    findings: list[SlipFinding] = field(default_factory=list)
    substituted: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    compared: bool = False        # was a recommended set supplied at all

    @property
    def stops(self) -> list[SlipFinding]:
        return [f for f in self.findings if f.level == "STOP"]

    @property
    def checks(self) -> list[SlipFinding]:
        return [f for f in self.findings if f.level == "CHECK"]

    @property
    def verdict(self) -> str:
        if self.stops:
            return "DO NOT PLACE"
        if self.checks:
            return "CHECK FIRST"
        return "NOTHING FOUND AGAINST IT"

    def report(self) -> str:
        c = self.candidate
        if c is None:
            return (f"SLIP VERDICT: {self.verdict}\n  "
                    + "\n  ".join(f.describe() for f in self.findings))
        out = [f"SLIP VERDICT: {self.verdict}",
               # `independent_odds` returns AMERICAN already. Wrapping it in
               # american() again turned a -110 single into "+1" — a second
               # conversion of an already-converted number, which produces a
               # plausible-looking price rather than an error.
               f"  {len(c.legs)} legs, {c.structure.kind}, "
               f"independent {c.independent_odds:+.0f}"]
        if c.priced:
            out.append(f"  book {c.book_odds:+.0f}")
        else:
            # Not "probably fine". An unpriced slip is one nobody quoted.
            out.append("  book price NOT supplied, so nothing here checks the "
                       "price you are actually being offered")
        if not self.compared:
            out.append("  ! no recommended set given, so NOTHING here can "
                       "tell you a leg was substituted — pass recommended= "
                       "with the engine's own legs to get that")
        for level in ("STOP", "CHECK", "NOTE"):
            group = [f for f in self.findings if f.level == level]
            for f in group:
                out.append("  " + f.describe())
        if not self.findings:
            out.append("  no findings — which means nothing was found, not "
                       "that the slip is good")
        return "\n".join(out)


def _slip_key(leg) -> tuple:
    """Identity of a leg for comparing one slip against another.

    Normalised name, never the raw one (B44/B101/B127), plus market, side and
    line. The line is part of it on purpose: the same player at a different
    number is a different bet, which is exactly what a substitution often is.
    """
    return (norm_player(str(getattr(leg, "player", "") or "")),
            str(getattr(leg, "market", "") or ""),
            str(getattr(leg, "side", "") or "").upper(),
            None if getattr(leg, "line", None) is None
            else float(leg.line))


def score_slip(legs, meta=None, *, boost_pct: float = 0.0,
               book_odds: float | None = None, stake: float = 10.0,
               recommended=None) -> SlipScore:
    """Score a slip that already exists, and say what is wrong with it.

    `legs` are the legs ON THE SLIP, in the sides actually taken.
    `recommended` is the engine's own legs, when there are any — without it
    the substitution check cannot run and the report says so rather than
    reporting a clean bill.

    Every finding names the leg it is about. Nothing is scored; the output is
    a verdict and a list, because a slip with one VETO and four CLEARs does
    not average out to fine.
    """
    legs = list(legs)
    # Checked BEFORE the candidate is built, not after. `independent_odds([])`
    # is a decimal 1.0, and `american(1.0)` divides by zero — so the empty
    # case has to be refused before anything prices it, not flagged once
    # pricing has already raised.
    if not legs:
        return SlipScore(
            candidate=None, compared=recommended is not None,
            findings=[SlipFinding("STOP", "", "the slip has no legs in it")])

    cand = make_candidate(legs, meta, boost_pct=boost_pct, stake=stake)
    if book_odds is not None:
        cand = price_candidate(cand, book_odds=float(book_odds))
    out = SlipScore(candidate=cand, compared=recommended is not None)

    # --- structure ---------------------------------------------------------
    if not cand.structure.priceable:
        out.findings.append(SlipFinding(
            "STOP", "", f"not priceable as a parlay: "
                        f"{cand.structure.reason}"))
    for note in cand.structure.zeros or ():
        out.findings.append(SlipFinding("NOTE", "", note))
    for name in getattr(cand.structure, "correlation_unresolved", ()) or ():
        out.findings.append(SlipFinding(
            "CHECK", str(name),
            "correlation against the other legs could NOT be resolved, so "
            "this slip is priced as if it were independent when it may not "
            "be"))

    # --- per leg -----------------------------------------------------------
    for l in legs:
        who = str(l.player)
        if l.verdict == "VETO":
            out.findings.append(SlipFinding(
                "STOP", who, f"VETO on the {l.side}: "
                             f"{'; '.join(l.verdict_reasons) or 'unspecified'}"))
        elif l.verdict == "UNSCREENED":
            # The default, and deliberately loud. A live run once built 32
            # legs that all read CLEAR without boost_verdict ever being
            # called; UNSCREENED exists so that cannot happen quietly.
            out.findings.append(SlipFinding(
                "STOP", who,
                "never screened — boost_verdict() was not run for this leg, "
                "so nothing has looked at whether anything argues against "
                f"the {l.side}"))
        elif l.verdict == "CAUTION":
            out.findings.append(SlipFinding(
                "CHECK", who, f"CAUTION on the {l.side}: "
                              f"{'; '.join(l.verdict_reasons) or 'unspecified'}"))

        against = l.model_against
        if against is None:
            out.findings.append(SlipFinding(
                "CHECK", who,
                "no model_p supplied, so nothing here can tell you whether "
                f"the engine wants the {l.side} or the other side of it. A "
                f"CLEAR verdict does not answer that question."))
        elif against:
            # The Tez Johnson shape. Loud, because it is the one that reads
            # as a screened leg.
            other = "UNDER" if str(l.side).upper() == "OVER" else "OVER"
            out.findings.append(SlipFinding(
                "STOP", who,
                f"the model prefers the {other}. You are on the {l.side} at "
                f"a fair {l.fair_prob:.1%}, and the model puts that side at "
                f"{l.model_p:.1%} — {abs(l.model_gap):.1%} the wrong way, "
                f"past the {MODEL_SIDE_GATE:.0%} gate. This is NOT what a "
                f"verdict measures: {l.verdict} means nothing was found "
                f"against this side, not that the model wants it."))

        if l.anchor_thin:
            out.findings.append(SlipFinding(
                "CHECK", who, f"the fair line rests on a thin anchor "
                              f"({l.fair_source}), so {l.fair_prob:.1%} is "
                              f"softer than it looks"))
        elif l.anchor_opening:
            out.findings.append(SlipFinding(
                "CHECK", who, f"the anchor has set a point but taken no "
                              f"money against it — re-pull closer to kickoff"))

    # --- what the engine would have picked ---------------------------------
    if recommended is not None:
        rec = list(recommended)
        rec_keys = {_slip_key(r): r for r in rec}
        mine = {_slip_key(l): l for l in legs}
        # A leg on the slip that the engine never proposed.
        for k, l in mine.items():
            if k in rec_keys:
                continue
            same_player = [r for r in rec
                           if _slip_key(r)[0] == k[0]]
            out.substituted.append(str(l.player))
            if same_player:
                r = same_player[0]
                out.findings.append(SlipFinding(
                    "CHECK", str(l.player),
                    f"the engine had this player at {r.side} "
                    f"{r.line if r.line is not None else ''}".rstrip()
                    + f", the slip has {l.side} "
                      f"{l.line if l.line is not None else ''}".rstrip()
                    + " — same man, different bet"))
            else:
                out.findings.append(SlipFinding(
                    "CHECK", str(l.player),
                    "the engine did not propose this leg at all. That is not "
                    "a reason it is wrong, but nothing in this pipeline has "
                    "an opinion on it beyond what is printed above"))
        # An engine leg that did not make the slip. A leg whose PLAYER is on
        # the slip under a different key is not dropped — he was moved, and
        # the "same man, different bet" finding above already says so.
        # Reporting both made Tez Johnson read as absent from a slip he was
        # on, which is worse than silence.
        on_slip = {k[0] for k in mine}
        for k, r in rec_keys.items():
            if k not in mine and k[0] not in on_slip:
                out.dropped.append(str(r.player))
                out.findings.append(SlipFinding(
                    "NOTE", str(r.player),
                    f"the engine proposed this leg ({r.side} "
                    f"{r.line if r.line is not None else ''}".rstrip()
                    + ") and it is not on the slip"))
    return out


# ---------------------------------------------------------------------------
# F15, the other half — free text to real legs
# ---------------------------------------------------------------------------
#
# "JSN over 5 receptions, CMC over 50 rush" has to become legs priced at a
# real book before anything can score it. This is the step the backlog calls
# the fragile part, and it is right: it is the B44 name join (Brian Thomas Jr.
# against Brian Thomas) and the D18 line-grid mismatch (his book at 46.5 where
# the anchor is at 47.5) in a single operation, and a live run dropped 17 of
# 41 quotes at that join.
#
# THE RULE IS REFUSE, NEVER SNAP. A leg that cannot be resolved comes back
# named, with the candidates or the posted lines beside it, so the ambiguity
# goes to a person instead of being guessed. Snapping "over 50" onto a posted
# 49.5 is a different bet with a different probability, and D18 exists because
# a fair probability for one point is not a fair probability for its
# neighbour.
#
# NO STORED ALIAS TABLE. "JSN" and "CMC" are resolved against the BOARD's own
# spellings, by initials computed from them — not from a nickname map, which
# would be a constant that goes stale the moment a rookie arrives (B53's
# lesson, where a constant's size was mistaken for its coverage). The board
# is the authority on who is playing.

_MARKET_WORDS = {
    "player_reception_yds": ("receiving yards", "rec yards", "rec yds",
                             "receiving yds", "rec"),
    "player_rush_yds": ("rushing yards", "rush yards", "rush yds",
                        "rushing yds", "rush"),
    "player_pass_yds": ("passing yards", "pass yards", "pass yds",
                        "passing yds", "pass"),
    "player_receptions": ("receptions", "catches", "recs"),
    "player_anytime_td": ("anytime td", "anytime touchdown", "td", "touchdown"),
}


def market_from_text(text: str) -> tuple[str | None, str]:
    """(market_key, why) from a phrase like "rush yards".

    Longest phrase wins, so "rec yards" is not read as "rec". Returns None
    when nothing matches AND when more than one market matches equally —
    never a best guess, because the market decides which line grid the
    number is read against.
    """
    t = " ".join(str(text or "").lower().split())
    hits = []
    for key, words in _MARKET_WORDS.items():
        for w in words:
            if re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", t):
                hits.append((len(w), key))
    if not hits:
        return None, (f"no market named in {text!r} — say receiving yards, "
                      f"rushing yards, passing yards, receptions or anytime "
                      f"TD")
    hits.sort(reverse=True)
    best = hits[0][0]
    top = {k for n, k in hits if n == best}
    if len(top) > 1:
        return None, (f"{text!r} names more than one market "
                      f"({', '.join(sorted(top))}) — say which")
    return hits[0][1], "named"


def _initials(name: str) -> str:
    """Initials of a board spelling, splitting inner capitals too.

    "Christian McCaffrey" -> c + mc + c -> "cmc", which is what people type.
    "Jaxon Smith-Njigba" -> "jsn". Computed from the board, never stored.
    """
    out = []
    for part in re.split(r"[\s.\-']+", str(name or "")):
        if not part:
            continue
        # McCaffrey -> ["Mc", "Caffrey"]; Smith -> ["Smith"]
        for chunk in re.findall(r"[A-Z][a-z]*|[a-z]+", part):
            out.append(chunk[0].lower())
    return "".join(out)


def resolve_player(text: str, names) -> tuple[str | None, str, list[str]]:
    """(board spelling, why, candidates) for a player named in free text.

    Four passes, each of which must land on EXACTLY ONE board name or it
    refuses with the candidates listed:
      1. normalised equality  — the B44 join, done right
      2. normalised substring — "Burden" for "Luther Burden III"
      3. initials             — "CMC", "JSN", computed from the board
      4. refuse

    No edit distance and no nearest match anywhere. A fuzzy join is how a
    player loses his whole board to a near-miss, which has happened here
    three times.
    """
    raw = " ".join(str(text or "").split())
    if not raw:
        return None, "no player named", []
    names = list(dict.fromkeys(str(n) for n in names if n))
    want = norm_player(raw)

    exact = [n for n in names if norm_player(n) == want]
    if len(exact) == 1:
        return exact[0], "matched on the normalised name", exact
    if len(exact) > 1:
        return None, (f"{raw!r} matches {len(exact)} players on this board "
                      f"under one spelling"), exact

    if want:
        sub = [n for n in names if want in norm_player(n)]
        if len(sub) == 1:
            return sub[0], f"matched {sub[0]!r} on a partial name", sub
        if len(sub) > 1:
            return None, (f"{raw!r} is ambiguous on this board"), sub

    key = re.sub(r"[^a-z]", "", raw.lower())
    ini = [n for n in names if _initials(n) == key]
    if len(ini) == 1:
        return ini[0], f"matched {ini[0]!r} on initials", ini
    if len(ini) > 1:
        return None, f"{raw!r} is the initials of {len(ini)} players", ini

    return None, f"{raw!r} is not on this board", []


@dataclass
class ResolvedLeg:
    """One free-text leg, resolved or refused — never partly either."""
    text: str
    player: str | None = None
    market: str | None = None
    side: str | None = None
    line: float | None = None
    quote: dict | None = None
    why: str = ""
    posted_lines: tuple[float, ...] = ()
    candidates: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.quote is not None

    def describe(self) -> str:
        if self.ok:
            return (f"{self.player} {self.side} {self.line:g} "
                    f"{self.market} @{self.quote['book']} "
                    f"{self.quote['over' if self.side == 'OVER' else 'under']:+.0f}"
                    f"  ({self.why})")
        s = f"REFUSED {self.text!r}: {self.why}"
        if self.candidates:
            s += "\n    candidates: " + ", ".join(self.candidates[:8])
        if self.posted_lines:
            s += ("\n    lines posted here: "
                  + ", ".join(f"{x:g}" for x in self.posted_lines))
        return s


_LEG_RE = re.compile(
    r"^\s*(?P<player>.+?)\s+(?P<side>over|under|o|u)\s+"
    r"(?P<line>\d+(?:\.\d+)?)\s*(?P<market>.*?)\s*$", re.I)


def resolve_leg(text: str, quotes: list[dict], *,
                book: str | None = None) -> ResolvedLeg:
    """One leg of free text against a board, refused rather than guessed."""
    raw = " ".join(str(text or "").split())
    m = _LEG_RE.match(raw)
    if not m:
        return ResolvedLeg(raw, why=(
            "could not read this as a leg — the shape is "
            "'<player> over|under <number> <market>', e.g. "
            "'CMC over 50 rush yards'"))
    side = "OVER" if m.group("side").lower().startswith("o") else "UNDER"
    line = float(m.group("line"))
    market, mwhy = market_from_text(m.group("market"))
    if market is None:
        return ResolvedLeg(raw, side=side, line=line, why=mwhy)

    rows = [q for q in quotes
            if q.get("market") == market
            and (book is None or q.get("book") == book)]
    if not rows:
        at = f" at {book}" if book else ""
        return ResolvedLeg(raw, market=market, side=side, line=line,
                           why=f"no {market} quotes{at} on this board")

    who, pwhy, cands = resolve_player(m.group("player"),
                                      [q.get("player") for q in rows])
    if who is None:
        return ResolvedLeg(raw, market=market, side=side, line=line,
                           why=pwhy, candidates=tuple(cands[:8]))

    his = [q for q in rows if q.get("player") == who]
    posted = tuple(sorted({float(q["line"]) for q in his
                           if q.get("line") is not None}))
    exact = [q for q in his if q.get("line") is not None
             and abs(float(q["line"]) - line) < 1e-9]
    if not exact:
        # D18. NOT snapped. The posted lines come back so a person can pick,
        # which is the useful half of refusing.
        return ResolvedLeg(
            raw, player=who, market=market, side=side, line=line,
            posted_lines=posted,
            why=(f"{who} has no {line:g} posted for {market}"
                 + (f" at {book}" if book else "")
                 + ". NOT snapped to a neighbour: a fair probability for one "
                   "point is not a fair probability for the next, so pick "
                   "one of the lines that exists"))
    q = exact[0]
    price = q.get("over") if side == "OVER" else q.get("under")
    if price is None:
        return ResolvedLeg(
            raw, player=who, market=market, side=side, line=line,
            posted_lines=posted, quote=None,
            why=(f"{who} {line:g} is posted but the {side} side is not "
                 f"priced — this is a one-sided row"))
    return ResolvedLeg(raw, player=who, market=market, side=side, line=line,
                       quote=q, why=pwhy, posted_lines=posted)


def resolve_slip(text, quotes: list[dict], *,
                 book: str | None = None) -> list[ResolvedLeg]:
    """Free text to resolved legs. Accepts one string or a list of them.

    A string is split on commas and newlines — NOT on "and", which appears
    inside nothing useful but would also split a market phrase somebody
    writes as "rush and rec".
    """
    if isinstance(text, str):
        parts = [p for p in re.split(r"[,\n;]+", text) if p.strip()]
    else:
        parts = [str(p) for p in text]
    return [resolve_leg(p, quotes, book=book) for p in parts]


def resolve_report(legs: list[ResolvedLeg]) -> str:
    ok = [l for l in legs if l.ok]
    no = [l for l in legs if not l.ok]
    out = [f"{len(ok)} of {len(legs)} legs resolved"]
    for l in ok:
        out.append("  " + l.describe())
    for l in no:
        out.append("  " + l.describe())
    if no:
        out.append("  Nothing was snapped or guessed. Resolve the refusals "
                   "above before scoring this slip — a slip missing a leg is "
                   "a different slip.")
    return "\n".join(out)
