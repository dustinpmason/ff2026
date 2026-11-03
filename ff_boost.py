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

from dataclasses import dataclass, field
from itertools import combinations, product

from ff_backtest import (to_decimal, implied, breakeven_p, boosted_return,
                         expected_roi, roi_band, SGP_HOLD_CROSS_GAME,
                         SGP_HOLD_SAME_GAME)

# The documented target band. +300 is the boost's own requirement; +450 is
# where EV stops improving materially (~2.5 points up to +700) while the hit
# rate nearly halves — and the stated objective is grinding regular wins.
FLOOR = 300
CEILING = 450

# Re-exported, NOT redefined. The Sunday re-measurement updates ff_backtest
# and this module follows it; a second copy here would drift silently.
HOLD_CROSS = SGP_HOLD_CROSS_GAME
HOLD_SAME = SGP_HOLD_SAME_GAME

MODES = ("cross-game", "single-game")

# Measured over 43,228 same-game pairs, 2025-26. Everything absent is ~0.00,
# INCLUDING WR x WR on the same team (+0.00 over 2,970 pairs) — target
# competition cancels out team volume. Do not limit slips to stack shapes.
SAME_TEAM_CORR = {("QB", "WR"): 0.31, ("QB", "TE"): 0.27, ("QB", "RB"): -0.10}
OPPOSING_CORR = {("RB", "RB"): -0.14}

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
    verdict: str = "CLEAR"                       # from ff_props.boost_verdict
    verdict_reasons: tuple[str, ...] = ()
    team: str | None = None
    pos: str | None = None

    def __post_init__(self):
        if not (0.0 < float(self.fair_prob) < 1.0):
            raise ValueError(
                f"fair_prob must be strictly between 0 and 1, got "
                f"{self.fair_prob!r} for {self.player}. A 0 or 1 makes the "
                f"EV infinite rather than wrong, which is harder to notice.")
        if self.verdict not in ("CLEAR", "CAUTION", "VETO"):
            raise ValueError(f"unknown leg verdict {self.verdict!r}")
        self.verdict_reasons = tuple(self.verdict_reasons)

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
    pairs: list[tuple]              # (player_a, player_b, r, why)
    priceable: bool
    reason: str

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


def _pair_r(a: BoostLeg, b: BoostLeg) -> tuple[float, str]:
    """Measured correlation for one pair, and why. Zero unless they share an
    event — two players in different games are independent."""
    if a.event_id != b.event_id:
        return 0.0, ""
    pa, pb = a.pos, b.pos
    if pa is None or pb is None:
        return 0.0, ""
    if a.team and b.team and a.team == b.team:
        key = (pa, pb) if (pa, pb) in SAME_TEAM_CORR else (pb, pa)
        if key in SAME_TEAM_CORR:
            return SAME_TEAM_CORR[key], f"same team {key[0]}x{key[1]}"
        return 0.0, ""
    key = (pa, pb) if (pa, pb) in OPPOSING_CORR else (pb, pa)
    if key in OPPOSING_CORR:
        return OPPOSING_CORR[key], f"opposing {key[0]}x{key[1]} in one event"
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

    pairs = []
    for a, b in combinations(legs, 2):
        r, why = _pair_r(a, b)
        if r:
            pairs.append((a.player, b.player, r, why))

    events = {l.event_id for l in legs}
    if len(events) == len(legs):
        kind = "cross-game"
    elif len(events) == 1:
        kind = "same-game-correlated" if pairs else "same-game-independent"
    else:
        kind = "mixed"

    priceable = not pairs
    if priceable:
        reason = ("fair joint is the product of the de-vigged legs — no "
                  "correlated pair in this slip")
    else:
        detail = "; ".join(f"{a} x {b} r={r:+.2f} ({why})"
                           for a, b, r, why in pairs)
        reason = (f"NOT priceable: {detail}. The true joint is not the "
                  f"product and this project has no joint model, so no EV "
                  f"is reported. That is not a verdict against the slip — "
                  f"the measured same-game hold was measured on INDEPENDENT "
                  f"legs and does not apply here.")
    return Structure(kind=kind, pairs=pairs, priceable=priceable,
                     reason=reason)


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
        """Something here is worth pricing.

        UNPRICEABLE counts: the measured same-game hold was measured on
        independent legs and does not rule out a stack. NEGATIVE does not.
        """
        return any(c.verdict in ("PLAY", "UNPRICEABLE") for c in self.candidates)

    def describe(self) -> str:
        if not self.playable:
            return f"NOTHING PLAYABLE — {self.reason}"
        return (f"{len(self.candidates)} candidate(s), "
                f"{sum(c.verdict == 'PLAY' for c in self.candidates)} playable")


def _intake(legs, mode: str, event_id: str | None) -> tuple[list, list]:
    """Drop legs that must never reach a slip. Returns (kept, dropped)."""
    kept, dropped = [], []
    for l in legs:
        if l.verdict == "VETO":
            dropped.append((l.player, "VETO: " +
                            ("; ".join(l.verdict_reasons) or "unspecified")))
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
    for c in combos:
        names = tuple(sorted(l.player for l in c))
        if len(set(names)) != len(names) or names in seen:
            continue
        seen.add(names)
        cand = make_candidate(c, meta, boost_pct=boost_pct, stake=stake)
        if not (floor <= cand.independent_odds <= ceiling):
            continue
        cands.append(cand)

    cands.sort(key=lambda c: c.key)
    cands = cands[:limit]

    reason = ""
    if not any(c.verdict in ("PLAY", "UNPRICEABLE") for c in cands):
        if not kept:
            reason = "every leg was dropped at intake"
        elif not cands:
            reason = (f"no combination lands in the +{floor:.0f} to "
                      f"+{ceiling:.0f} floor band — "
                      f"{'legs are too short' if combos else 'not enough legs'}")
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
                     notes=list(cand.notes))


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
        for n in c.notes:
            out.append(f"  note: {n}")
        out.append("  The model's number is a GAP against a de-vigged line, "
                   "not a finding. A clear leg means nothing was found "
                   "against it.")
        out.append("")
    return "\n".join(out)
