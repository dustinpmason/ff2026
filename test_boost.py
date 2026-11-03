"""P0 falsification criteria — written BEFORE ff_boost.py exists, on purpose.

This file is the specification. It is the same discipline F2 used: the
criteria that would catch a broken optimiser are written first, so the
implementation is built to satisfy checks it did not get to choose.

Until ff_boost.py exists this file fails at import. That is correct and
expected. It lives outside test_regression.py so the committed suite stays
green — project threads bootstrap from GitHub and run that suite, and a red
suite in the repo breaks all of them. Fold these sections in once they pass.

--------------------------------------------------------------------------
WHAT A BROKEN BOOST OPTIMISER LOOKS LIKE
--------------------------------------------------------------------------

Every standing lesson in HANDOFF.md says the dangerous bug returns a
plausible number rather than an error. For this module the plausible numbers
are a P(cash) and an EV, and there are four distinct ways to produce a wrong
one that looks right:

  1. Quoting the CROSS-GAME hold band on a slip that is not cross-game.
     Measured bands are 17.7-20.9% cross-game against 23.1-37.2% same-game.
     A "cross-game" slip containing two legs from one event gets scored
     against a band ~12 points too favourable. This is B36 exactly — the
     audit quoting the wrong band and producing the wrong SIGN — so the
     structure tag MUST be derived from the legs and MUST NOT be taken from
     what the caller asked for.

  2. Attaching an EV to a correlated same-game slip. The true joint is not
     the product of the legs and this project has no joint model. Any
     P(cash) on a QB stack is invented.

  3. Backing the joint out of correlation_factor. PROJECT-INSTRUCTIONS is
     explicit that this is circular: the factor cancels and you get the
     independent number dressed up as a correlation adjustment.

  4. Pricing off the independent product when the book's real SGP price is
     available. The product is a shortlisting estimate only. Three legs at
     -150 are +363 independent and +225 at a 0.62 factor; scoring the slip
     at +363 both invents EV and smuggles a below-floor slip past the floor.

The checks below are organised around those four, plus leg intake and
output honesty.

--------------------------------------------------------------------------
API CONTRACT these checks assume
--------------------------------------------------------------------------

    BoostLeg(event_id, book, market, player, side, odds, fair_prob,
             fair_source, devig_method, line=None, player_id=None,
             verdict="CLEAR", verdict_reasons=(), team=None, pos=None)

    classify(legs, meta) -> Structure
        .kind         "cross-game" | "same-game-independent"
                      | "same-game-correlated" | "mixed"
        .pairs        [(player_a, player_b, r, why)] for every non-zero pair
        .priceable    bool — False iff the joint is not the product
        .reason       one line, for the report

    independent_odds(legs) -> float        American, product of de-vigged legs
    enumerate_candidates(legs, meta, *, boost_pct, mode, floor=FLOOR,
                         ceiling=CEILING, limit=8) -> Shortlist
        mode: "cross-game" | "single-game"
        .candidates   list[Candidate], deterministic order
        .playable     bool
        .reason       why nothing is playable, when nothing is

    price_candidate(cand, *, book_odds, correlation_factor=None) -> Candidate
        attaches the real SGP price and recomputes everything legal

    Candidate
        .legs .structure .independent_odds .book_odds .correlation_factor
        .boost_pct .p_cash .breakeven .ev_pct .hold_band .hold_band_reason
        .factor_note .notes
        p_cash / breakeven / ev_pct are None when .structure.priceable is False

Teams and positions come from build_meta(), never from recall — the standing
rule after a session asserted two players' teams backwards and built a
conclusion on it.
"""
import warnings; warnings.filterwarnings("ignore")
import atexit, sys, traceback

import ff_boost
from ff_boost import (BoostLeg, classify, independent_odds,
                      enumerate_candidates, price_candidate, FLOOR, CEILING)

fails, ran = [], []
_section = ["(startup)"]
_crashed = False


def section(title: str) -> None:
    _section[0] = title
    print(f"\n{title}")


def _summary() -> None:
    if getattr(_summary, "done", False):
        return
    _summary.done = True
    print("\n" + ("=" * 60))
    print(f"{len(ran)} checks run, {len(ran) - len(fails)} passed, "
          f"{len(fails)} failed")
    if _crashed:
        print(f"CRASHED in section {_section[0]!r} — sections after it did "
              f"NOT run, so the count above is partial and anything later is "
              f"UNVERIFIED.")
    print("ALL PASS" if not fails and not _crashed
          else ("FAILURES: " + ", ".join(fails)) if fails
          else "NO CHECK FAILED, but the suite crashed")


def _on_crash(exc_type, exc, tb) -> None:
    global _crashed
    _crashed = True
    print()
    traceback.print_exception(exc_type, exc, tb)
    _summary()


sys.excepthook = _on_crash
atexit.register(_summary)


def chk(name, ok, detail=""):
    ran.append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'  — ' + detail if detail else ''}")
    if not ok:
        fails.append(name)


def raises(fn, *a, **kw) -> bool:
    """True if fn raised. Used where the right answer is a refusal."""
    try:
        fn(*a, **kw)
    except Exception:
        return True
    return False


# ---------------------------------------------------------------------------
# Synthetic fixtures.
#
# Synthetic by requirement, not convenience: B21 shipped a check that loaded
# an uncommitted roster file and broke every clean bootstrap, and B23 shipped
# one that could not be exercised because no live roster happened to be short.
# A fixture whose answer is known by construction is the only kind that can
# both confirm a fix and catch its regression.
#
# Three events. AAA@BBB, CCC@DDD, EEE@FFF.
# ---------------------------------------------------------------------------
META = {
    "QB A":  ("AAA", "QB"),  "WR A1": ("AAA", "WR"), "WR A2": ("AAA", "WR"),
    "TE A1": ("AAA", "TE"),  "RB A1": ("AAA", "RB"),
    "RB B1": ("BBB", "RB"),  "WR B1": ("BBB", "WR"),
    "QB C":  ("CCC", "QB"),  "WR C1": ("CCC", "WR"), "RB C1": ("CCC", "RB"),
    "WR D1": ("DDD", "WR"),
    "WR E1": ("EEE", "WR"),  "RB F1": ("FFF", "RB"),
}
EV1, EV2, EV3 = "ev-aaa-bbb", "ev-ccc-ddd", "ev-eee-fff"


def leg(player, event_id, odds=-150, fair_prob=0.60, **kw):
    """A leg that passes intake unless a kwarg says otherwise.

    -150 / 0.60 is the documented target shape: three such legs price at
    +363, which clears the +300 floor with the shortest legs available.
    """
    return BoostLeg(
        event_id=event_id,
        book=kw.pop("book", "draftkings"),
        market=kw.pop("market", "player_reception_yds"),
        player=player,
        side=kw.pop("side", "OVER"),
        odds=odds,
        fair_prob=fair_prob,
        fair_source=kw.pop("fair_source", "pinnacle (via get_event_ev)"),
        devig_method=kw.pop("devig_method", "shin (get_event_ev)"),
        line=kw.pop("line", 45.5),
        player_id=kw.pop("player_id", f"espn:{abs(hash(player)) % 10**7}"),
        team=META.get(player, (None, None))[0],
        pos=META.get(player, (None, None))[1],
        **kw,
    )


CROSS = [leg("WR A1", EV1), leg("WR C1", EV2), leg("WR E1", EV3)]
SAME_INDEP = [leg("WR A1", EV1), leg("WR A2", EV1), leg("WR B1", EV1)]
SAME_STACK = [leg("QB A", EV1), leg("WR A1", EV1), leg("RB B1", EV1)]


print("1. module imports")
chk("ff_boost imports", True)
chk("FLOOR is the documented +300", FLOOR == 300, f"FLOOR={FLOOR}")
chk("CEILING is the documented +450", CEILING == 450, f"CEILING={CEILING}")

# ---------------------------------------------------------------------------
section("2. structure is DERIVED from the legs, never taken from the caller")
# Failure mode 1. This is B36's signature: the wrong hold band produces the
# wrong sign, from a default that was meant to be cautious.
# ---------------------------------------------------------------------------
s = classify(CROSS, META)
chk("three legs in three events are cross-game", s.kind == "cross-game", s.kind)
chk("cross-game is priceable", s.priceable is True)
chk("cross-game has no correlated pairs", s.pairs == [], str(s.pairs))

s = classify(SAME_INDEP, META)
chk("same-team WR x WR is NOT correlated (measured +0.00)",
    s.kind == "same-game-independent", s.kind)
chk("same-game-independent is priceable", s.priceable is True)

s = classify(SAME_STACK, META)
chk("QB + his own WR is correlated", s.kind == "same-game-correlated", s.kind)
chk("a correlated slip is NOT priceable", s.priceable is False)
chk("the correlated pair is named with its r",
    any(abs(p[2] - 0.31) < 1e-9 for p in s.pairs), str(s.pairs))

s = classify([leg("QB A", EV1), leg("TE A1", EV1), leg("WR B1", EV1)], META)
chk("QB + his own TE is correlated (+0.27)",
    s.kind == "same-game-correlated" and any(abs(p[2] - 0.27) < 1e-9
                                             for p in s.pairs), s.kind)

s = classify([leg("QB A", EV1), leg("RB A1", EV1), leg("WR B1", EV1)], META)
chk("QB + his own RB is correlated (-0.10), not independent",
    s.kind == "same-game-correlated" and any(abs(p[2] + 0.10) < 1e-9
                                             for p in s.pairs), s.kind)

# The guillotine's correlation_matrix cannot see the schedule, so it treats
# every different-team pair as independent. P0 knows the event, so two backs
# inside one event ARE facing each other and the measured -0.14 applies.
s = classify([leg("RB A1", EV1), leg("RB B1", EV1), leg("WR C1", EV2)], META)
chk("opposing RBs inside one event are correlated (-0.14)",
    any(abs(p[2] + 0.14) < 1e-9 for p in s.pairs), str(s.pairs))

s = classify([leg("RB A1", EV1), leg("RB C1", EV2), leg("WR E1", EV3)], META)
chk("RBs in DIFFERENT events are independent, not opposing",
    s.kind == "cross-game" and s.pairs == [], f"{s.kind} {s.pairs}")

# The one that silently poisons every EV downstream.
s = classify([leg("WR A1", EV1), leg("WR A2", EV1), leg("WR C1", EV2)], META)
chk("two legs sharing an event are NOT cross-game", s.kind != "cross-game", s.kind)
chk("a mixed slip is tagged mixed, not same-game",
    s.kind == "mixed", s.kind)

# ---------------------------------------------------------------------------
section("3. the floor applies to the price you can actually bet")
# Failure mode 4. Three legs at -150 are +363 independent and +225 once a
# 0.62 correlation factor is applied. Scoring the slip at +363 both invents
# EV and smuggles a below-floor slip past the floor.
# ---------------------------------------------------------------------------
ind = independent_odds(SAME_STACK)
chk("three -150 legs price at about +363 independent",
    360 <= ind <= 366, f"{ind:+.0f}")

c = enumerate_candidates(SAME_STACK, META, boost_pct=0.50,
                         mode="single-game").candidates[0]
c = price_candidate(c, book_odds=225, correlation_factor=0.62)
chk("a below-floor BOOK price is rejected even when the product clears",
    c.book_odds == 225 and not c.clears_floor,
    f"independent {c.independent_odds:+.0f}, book {c.book_odds:+.0f}")

sl = enumerate_candidates(CROSS, META, boost_pct=0.50, mode="cross-game")
chk("every returned candidate clears the floor",
    all(cc.independent_odds >= FLOOR for cc in sl.candidates))
chk("no returned candidate exceeds the ceiling by default",
    all(cc.independent_odds <= CEILING for cc in sl.candidates))

short = [leg("WR A1", EV1, odds=-400, fair_prob=0.80),
         leg("WR C1", EV2, odds=-400, fair_prob=0.80),
         leg("WR E1", EV3, odds=-400, fair_prob=0.80)]
sl = enumerate_candidates(short, META, boost_pct=0.50, mode="cross-game")
chk("legs too short to reach the floor yield nothing playable",
    not sl.playable and bool(sl.reason), sl.reason)
chk("nothing playable is EXPLICIT, never a bare empty list",
    "floor" in sl.reason.lower() or "+300" in sl.reason, sl.reason)

# ---------------------------------------------------------------------------
section("4. EV exists only where the joint is the product")
# Failure mode 2.
# ---------------------------------------------------------------------------
c = enumerate_candidates(CROSS, META, boost_pct=0.30,
                         mode="cross-game").candidates[0]
c = price_candidate(c, book_odds=330, correlation_factor=0.98)
chk("a cross-game slip carries P(cash)", c.p_cash is not None, str(c.p_cash))
chk("a cross-game slip carries a breakeven", c.breakeven is not None)
chk("a cross-game slip carries an EV", c.ev_pct is not None)
chk("P(cash) is the product of the de-vigged legs",
    abs(c.p_cash - 0.6 ** 3) < 1e-6, f"{c.p_cash:.4f}")

c = enumerate_candidates(SAME_STACK, META, boost_pct=0.30,
                         mode="single-game").candidates[0]
c = price_candidate(c, book_odds=225, correlation_factor=0.62)
chk("a correlated slip carries NO P(cash)", c.p_cash is None)
chk("a correlated slip carries NO breakeven", c.breakeven is None)
chk("a correlated slip carries NO EV", c.ev_pct is None)
chk("a correlated slip still carries its real book price", c.book_odds == 225)
chk("a correlated slip says WHY it has no EV",
    any("joint" in n.lower() for n in c.notes), str(c.notes))

# ---------------------------------------------------------------------------
section("5. correlation_factor never enters a probability")
# Failure mode 3. If the factor is being backed into the joint, perturbing it
# moves the EV. The factor may inform the report; it may not inform the math.
# ---------------------------------------------------------------------------
base = enumerate_candidates(CROSS, META, boost_pct=0.30,
                            mode="cross-game").candidates[0]
a = price_candidate(base, book_odds=330, correlation_factor=0.62)
b = price_candidate(base, book_odds=330, correlation_factor=1.05)
chk("EV is unchanged when correlation_factor changes",
    a.ev_pct == b.ev_pct, f"{a.ev_pct} vs {b.ev_pct}")
chk("P(cash) is unchanged when correlation_factor changes",
    a.p_cash == b.p_cash)
chk("the factor IS reported against the measured table",
    bool(a.factor_note) and bool(b.factor_note))
chk("a haircut on independent legs is called out as the bad deal",
    "not justified" in a.factor_note.lower()
    or "does not exist" in a.factor_note.lower(), a.factor_note)

# ---------------------------------------------------------------------------
section("6. the hold band follows the derived structure")
# ---------------------------------------------------------------------------
c = price_candidate(enumerate_candidates(CROSS, META, boost_pct=0.30,
                                         mode="cross-game").candidates[0],
                    book_odds=330)
chk("a cross-game slip uses the cross-game band",
    c.hold_band == ff_boost.HOLD_CROSS, str(c.hold_band))
chk("the slip states which band it used and why", bool(c.hold_band_reason))

c = price_candidate(enumerate_candidates(SAME_INDEP, META, boost_pct=0.50,
                                         mode="single-game").candidates[0],
                    book_odds=330)
chk("a same-game independent slip uses the same-game band",
    c.hold_band == ff_boost.HOLD_SAME, str(c.hold_band))

# Built directly, not via enumerate: cross-game mode correctly refuses to
# put two legs from one event in a slip (section 9), so a mixed slip can
# only arise from legs handed in deliberately. The band logic still has to
# be right for it — that is the whole point of the `mixed` kind.
mixed = [leg("WR A1", EV1), leg("WR A2", EV1), leg("WR C1", EV2)]
c = price_candidate(ff_boost.make_candidate(mixed, META, boost_pct=0.50),
                    book_odds=330)
chk("a MIXED slip gets the pessimistic same-game band, not cross-game",
    c.hold_band == ff_boost.HOLD_SAME, str(c.hold_band))

# ---------------------------------------------------------------------------
section("7. the measured boost policy is enforced, not advisory")
# A 20% boost is negative everywhere measured; same-game needs ~50%.
# Half of Dustin's use is single-game TNF/SNF/MNF boosts, so this path will
# fire often and must state the measured reason rather than going quiet.
# ---------------------------------------------------------------------------
sl = enumerate_candidates(CROSS, META, boost_pct=0.20, mode="cross-game")
chk("a 20% boost returns nothing playable", not sl.playable, sl.reason)
chk("the 20% refusal cites the measured hold", "hold" in sl.reason.lower()
    or "%" in sl.reason, sl.reason)

sl = enumerate_candidates(SAME_INDEP, META, boost_pct=0.30, mode="single-game")
chk("30% same-game-independent returns nothing playable", not sl.playable,
    sl.reason)
sl = enumerate_candidates(CROSS, META, boost_pct=0.30, mode="cross-game")
chk("30% cross-game IS playable", sl.playable, sl.reason)
sl = enumerate_candidates(SAME_INDEP, META, boost_pct=0.50, mode="single-game")
chk("50% same-game-independent is playable", sl.playable, sl.reason)

# The unpriceable case must not be silently dropped by the same policy that
# rejects the priceable one: the measured 30.2% was measured on INDEPENDENT
# same-game legs, and the instructions forbid reading it as a verdict on a
# correlated stack.
sl = enumerate_candidates(SAME_STACK, META, boost_pct=0.30, mode="single-game")
chk("a correlated stack is NOT rejected by the same-game hold figure",
    len(sl.candidates) > 0, sl.reason)
chk("but it is returned without an EV",
    all(cc.ev_pct is None for cc in sl.candidates))

# ---------------------------------------------------------------------------
section("8. leg intake — nothing unbettable or circular reaches a slip")
# ---------------------------------------------------------------------------
vetoed = leg("WR C1", EV2, verdict="VETO",
             verdict_reasons=["suspended at 3 books — probable scratch"])
sl = enumerate_candidates([leg("WR A1", EV1), vetoed, leg("WR E1", EV3)],
                          META, boost_pct=0.50, mode="cross-game")
chk("a VETOed leg never appears in any slip",
    all(vetoed.player not in [l.player for l in cc.legs]
        for cc in sl.candidates))

abst = leg("WR C1", EV2, verdict="CAUTION",
           verdict_reasons=["MODEL ABSTAINS — 0 of 7"])
sl = enumerate_candidates([leg("WR A1", EV1), abst, leg("WR E1", EV3)],
                          META, boost_pct=0.50, mode="cross-game")
chk("a CAUTION leg may still be used", len(sl.candidates) > 0, sl.reason)
chk("a CAUTION leg is surfaced on the slip, not silently treated as CLEAR",
    any("ABSTAIN" in n.upper() or "CAUTION" in n.upper()
        for cc in sl.candidates for n in cc.notes))

# Circularity: a fair line de-vigged from the same book you are betting is
# that book's opinion of itself. The instructions forbid it on single props;
# it is no more valid inside a slip.
circ = leg("WR C1", EV2, book="draftkings", fair_source="draftkings (self)")
chk("a fair line sourced from the book being bet is refused",
    raises(classify, [circ], META) or
    not enumerate_candidates([leg("WR A1", EV1), circ, leg("WR E1", EV3)],
                             META, boost_pct=0.50,
                             mode="cross-game").candidates)

chk("fair_prob of 0 is refused", raises(leg, "WR C1", EV2, fair_prob=0.0))
chk("fair_prob of 1 is refused", raises(leg, "WR C1", EV2, fair_prob=1.0))
chk("fair_prob above 1 is refused", raises(leg, "WR C1", EV2, fair_prob=1.4))

dupe = [leg("WR A1", EV1), leg("WR A1", EV1, line=55.5), leg("WR E1", EV3)]
chk("the same player twice in one slip is refused",
    raises(classify, dupe, META) or
    not enumerate_candidates(dupe, META, boost_pct=0.50,
                             mode="cross-game").candidates)

# ---------------------------------------------------------------------------
section("9. mode is honoured and stated")
# ---------------------------------------------------------------------------
pool = CROSS + SAME_INDEP
sl = enumerate_candidates(pool, META, boost_pct=0.50, mode="single-game",
                          event_id=EV1)
chk("single-game mode returns only legs from the requested event",
    all(l.event_id == EV1 for cc in sl.candidates for l in cc.legs))
sl = enumerate_candidates(pool, META, boost_pct=0.50, mode="cross-game")
chk("cross-game mode returns no slip with two legs in one event",
    all(len({l.event_id for l in cc.legs}) == len(cc.legs)
        for cc in sl.candidates))
chk("an unknown mode is refused, not silently defaulted",
    raises(enumerate_candidates, pool, META, boost_pct=0.50, mode="whatever"))

# ---------------------------------------------------------------------------
section("10. the shortlist is reproducible")
# A recommendation you cannot reproduce cannot be audited later against the
# bet log.
# ---------------------------------------------------------------------------
big = ([leg(p, EV1) for p in ("WR A1", "WR A2", "WR B1")]
       + [leg(p, EV2) for p in ("WR C1", "RB C1", "WR D1")]
       + [leg(p, EV3) for p in ("WR E1", "RB F1")])
one = enumerate_candidates(big, META, boost_pct=0.50, mode="cross-game")
two = enumerate_candidates(big, META, boost_pct=0.50, mode="cross-game")
chk("the same inputs give the same shortlist, in the same order",
    [[l.player for l in c.legs] for c in one.candidates] ==
    [[l.player for l in c.legs] for c in two.candidates])
chk("the shortlist is capped", len(one.candidates) <= 8,
    f"{len(one.candidates)} candidates")

# ---------------------------------------------------------------------------
section("11. the report does not overstate what it knows")
# P(cash) is a product of de-vigged market probabilities. It will look
# precise. It inherits whatever error is in the anchor, and on a correlated
# slip it is absent entirely — the report has to say so on its face rather
# than leave a clean-looking number to be quoted in a project thread.
# ---------------------------------------------------------------------------
c = price_candidate(enumerate_candidates(CROSS, META, boost_pct=0.30,
                                         mode="cross-game").candidates[0],
                    book_odds=330, correlation_factor=0.98)
txt = ff_boost.report([c])
chk("the report names the fair source", "pinnacle" in txt.lower(), txt[:80])
chk("the report names the de-vig method", "shin" in txt.lower())
chk("the report states the hold band it used", "17.7" in txt or "18.6" in txt)
chk("the report calls the model's number a gap, never an edge",
    "edge" not in txt.lower() or "gap" in txt.lower())

c = price_candidate(enumerate_candidates(SAME_STACK, META, boost_pct=0.50,
                                         mode="single-game").candidates[0],
                    book_odds=320, correlation_factor=0.62)
txt = ff_boost.report([c])
chk("an unpriceable slip says so in the report",
    "no ev" in txt.lower() or "cannot" in txt.lower(), txt[:120])
chk("the report never prints a P(cash) for a correlated slip",
    "P(cash)" not in txt or "—" in txt)
