"""Promo tokens as PARSED INPUT, never as constants.

F11/F16. Dustin typically holds 4-6 tokens of different shapes in a given
week — percentage profit boosts, stake-back / no-sweat bets, odds boosts —
with different minimum odds, maximum stakes, leg counts and SGP-vs-parlay
restrictions. **Those terms change every week**, so nothing here is
hardcoded: he states them in the prompt and this reads them.

The whole design rests on one rule, which is this project's oldest:

    A TERM THAT WAS NOT STATED IS NOT A TERM WITH A DEFAULT.

Every field is None until the text says otherwise, `missing` names what a
decision would need and does not have, and `unparsed` keeps the fragments
this module could not read so a human can see what it ignored rather than
discovering later that it guessed. D16 and B39 are the lessons: the
unchecked state must not look like the checked one. The specific failure
this is written against is B77 — `stake_back_ev`'s docstring says "the
caller must state it" while its signature supplies `bonus_value = 0.65`
and `market_hold = 0.39`, so a caller who states nothing gets a confident
number built on two constants measured on one book, one market, one night.

It does NOT price anything. `ff_boost.enumerate_candidates` takes a Token
and builds to its constraints; `ff_props.stake_back_ev` prices a stake-back.
Keeping the parse separate from the math is deliberate: a parser that can
also price is a parser that can smuggle a default into a number.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Kinds this module will commit to. A token it cannot classify stays None and
# says so, because the three are DIFFERENT MATH and picking wrong is not a
# rounding error:
#   profit_boost — pays more when you WIN, so it rewards a high win
#                  probability. Goes through the boost path.
#   stake_back   — refunds the stake as a BONUS BET when you LOSE, so its
#                  value rises as win probability FALLS. B56: these are NOT
#                  boosts and must not go through the boost path. The right
#                  bet for one is the longest shot that qualifies.
#   odds_boost   — a fixed price improvement on a named selection, not a
#                  percentage of anything.
KINDS = ("profit_boost", "stake_back", "odds_boost")

# Phrases that identify a kind. Ordered: stake-back first, because "no sweat
# bet up to $50" contains neither "boost" nor a percentage, and a token that
# refunds a loss must never be read as one that pays more on a win.
_STAKE_BACK = re.compile(
    # "get $25 back" is the commonest phrasing there is and the first cut
    # missed it: the pattern expected "get back" or "get it back", so a
    # money figure between them defeated it and a textbook stake-back read
    # as KIND UNKNOWN. Anything between "get" and "back" now matches.
    r"\b(stake\s*back|no[\s-]*sweat|bet\s*reset|safety\s*net|"
    r"second\s*chance|risk[\s-]*free|refund"
    r"|get\s+(?:[^.,;]{0,18}?\s*)?back)\b", re.I)
_PROFIT_BOOST = re.compile(r"\b(profit\s*boost|boost(?:ed)?)\b", re.I)
_ODDS_BOOST = re.compile(r"\bodds\s*boost\b", re.I)

_PCT = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")
# "min odds +200", "minimum odds of -200", "+200 or longer", "2.00 or greater"
_MIN_ODDS = re.compile(
    r"(?:min(?:imum)?\.?\s*(?:total\s*)?odds\s*(?:of\s*)?|odds\s*of\s*)"
    r"([+-]?\d{2,5})", re.I)
_MIN_ODDS_TAIL = re.compile(r"([+-]\d{2,5})\s*(?:or\s*(?:longer|greater|higher|better|more))", re.I)
_MAX_STAKE = re.compile(
    r"(?:max(?:imum)?\.?\s*(?:bet|stake|wager)?\s*(?:of\s*)?|"
    r"up\s*to\s*|first\s*)\$\s*([\d,]+(?:\.\d{1,2})?)", re.I)
# "3-leg SGP" is as common as "3+ legs" and the hyphen defeated the first
# pattern, which required whitespace.
_MIN_LEGS = re.compile(r"(\d+)\s*\+?\s*(?:or\s*more\s*)?[\s-]*legs?", re.I)
_SGP_ONLY = re.compile(r"\b(sgp|same[\s-]*game)\b[^.]{0,24}\b(only|required)\b|"
                       r"\bonly\b[^.]{0,24}\b(sgp|same[\s-]*game)\b", re.I)
_SGP_WORD = re.compile(r"\b(sgp|same[\s-]*game\s*parlay)\b", re.I)
_PARLAY_WORD = re.compile(r"\bparlay\b", re.I)
# A money figure that is NOT a max — "bet $25 get $25 back" states the stake.
_STAKE_PAIR = re.compile(r"bet\s*\$\s*([\d,]+(?:\.\d{1,2})?)", re.I)


def _money(t: str) -> float:
    return float(t.replace(",", ""))


@dataclass
class Token:
    """One promo token, exactly as stated and no further."""
    raw: str
    kind: str | None = None
    pct: float | None = None             # 0.30 for a 30% profit boost
    min_odds: float | None = None        # american, as the promo states it
    max_stake: float | None = None
    stake: float | None = None           # a stated stake, e.g. "bet $25"
    min_legs: int | None = None
    sgp_only: bool | None = None         # True / False / None = not stated
    label: str = ""
    unparsed: list[str] = field(default_factory=list)

    # ---- what a decision would need and does not have -------------------
    @property
    def missing(self) -> list[str]:
        """Fields whose absence changes what can be concluded.

        Not a validation list — a disclosure list. `enumerate_candidates`
        reports it so a shortlist built without a minimum says so instead of
        quietly using this project's own FLOOR, which answers a different
        question (B55: FLOOR asks "is this worth betting", the token minimum
        asks "will the book apply the token at all").
        """
        out = []
        if self.kind is None:
            out.append("kind (profit boost vs stake-back vs odds boost — "
                       "these are different math, see B56)")
        if self.kind == "profit_boost" and self.pct is None:
            out.append("boost percentage")
        if self.min_odds is None:
            out.append("minimum odds")
        if self.max_stake is None and self.stake is None:
            out.append("maximum stake")
        if self.sgp_only is None:
            # Not guessed, and not silent either. Left unstated, the
            # enumerator does not filter by structure, so a cross-game slip
            # could be offered for a token that cannot take one — which is
            # the wrong direction for silence.
            out.append("whether it is SGP-only or allows a cross-game parlay")
        return out

    @property
    def usable(self) -> bool:
        """Enough is known to build to this token at all."""
        return self.kind is not None and (
            self.kind != "profit_boost" or self.pct is not None)

    @property
    def effective_stake(self) -> float | None:
        """The stake to price at, or None when the text did not say.

        Deliberately NOT defaulted to 10.0. A dollar EV quoted at a stake
        nobody stated is a number about a bet nobody can place.
        """
        if self.stake is not None:
            return self.stake
        return self.max_stake

    def describe(self) -> str:
        bits = [self.label or "token"]
        bits.append(self.kind or "KIND UNKNOWN")
        if self.pct is not None:
            bits.append(f"{self.pct:.0%}")
        if self.min_odds is not None:
            bits.append(f"min {self.min_odds:+.0f}")
        if self.max_stake is not None:
            bits.append(f"max ${self.max_stake:,.2f}")
        if self.stake is not None:
            bits.append(f"stake ${self.stake:,.2f}")
        if self.min_legs is not None:
            bits.append(f"{self.min_legs}+ legs")
        if self.sgp_only is True:
            bits.append("SGP only")
        elif self.sgp_only is False:
            bits.append("parlay ok")
        s = " · ".join(bits)
        if self.missing:
            s += "\n      NOT STATED: " + "; ".join(self.missing)
        if self.unparsed:
            s += "\n      COULD NOT READ: " + "; ".join(self.unparsed)
        return s


def parse_token(text: str, *, label: str = "") -> Token:
    """Read one token's terms from the line Dustin wrote.

    Conservative by construction: a term it cannot read lands in `unparsed`
    rather than being approximated, and nothing is inferred from the absence
    of a term. The one inference it DOES make is the kind, because the three
    kinds are different math and a token whose kind is unknown cannot be
    used at all — so getting that wrong is louder than getting it missing.
    """
    t = Token(raw=text.strip(), label=label)
    s = text

    # --- kind. Stake-back is tested FIRST: "no sweat bet up to $50" has no
    # percentage and no "boost" in it, and reading it as a profit boost
    # would reverse which bet is right for it (B56).
    sb, pb, ob = (_STAKE_BACK.search(s), _PROFIT_BOOST.search(s),
                  _ODDS_BOOST.search(s))
    if sb and not ob:
        t.kind = "stake_back"
        if pb:
            # Both vocabularies present. Refusing to pick is the point.
            t.kind = None
            # Both matches are read defensively. The branch above guarantees
            # them today, but a `.group(0)` on a None match raises
            # AttributeError out of a PARSER, which would take a whole
            # session's intake down over a phrasing — and lesson 14 says a
            # fault should fail loudly in one place, not crash everything
            # downstream of it.
            _sbt = sb.group(0) if sb else "a refund phrase"
            _pbt = pb.group(0) if pb else "a boost phrase"
            t.unparsed.append(
                f"names both a refund ({_sbt!r}) and a boost "
                f"({_pbt!r}) — these are opposite math (a boost pays "
                f"more on a WIN, a stake-back pays on a LOSS), so the kind "
                f"is left unset rather than guessed")
    elif ob:
        t.kind = "odds_boost"
    elif pb:
        t.kind = "profit_boost"

    # --- percentage
    m = _PCT.search(s)
    if m:
        v = float(m.group(1))
        if 0 < v <= 100:
            t.pct = v / 100.0
        else:
            t.unparsed.append(f"percentage {m.group(0)!r} is outside 0-100%")

    # --- minimum odds
    m = _MIN_ODDS.search(s) or _MIN_ODDS_TAIL.search(s)
    if m:
        raw = m.group(1)
        v = float(raw)
        # A bare "200" with no sign is ambiguous: +200 and -200 are different
        # tokens and the difference is large. Refuse rather than assume.
        if raw[0] not in "+-":
            t.unparsed.append(
                f"minimum odds {raw!r} has no sign — +{raw} and -{raw} are "
                f"different terms, so it is not read")
        elif abs(v) < 100:
            t.unparsed.append(
                f"minimum odds {raw!r} is not a valid american price")
        else:
            t.min_odds = v

    # --- stake and maximum stake. Order matters: "bet $25 get $25 back"
    # states a STAKE, and "up to $25" states a CAP; the same number means
    # different things and the EV differs.
    m = _MAX_STAKE.search(s)
    if m:
        t.max_stake = _money(m.group(1))
    m = _STAKE_PAIR.search(s)
    if m:
        v = _money(m.group(1))
        # "bet $25 ... max $25" is consistent; a conflict is reported.
        if t.max_stake is not None and abs(v - t.max_stake) > 1e-9:
            t.unparsed.append(
                f"states a stake of ${v:,.2f} and a maximum of "
                f"${t.max_stake:,.2f}; both kept, priced at the stake")
        t.stake = v

    # --- legs
    m = _MIN_LEGS.search(s)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 12:
            t.min_legs = n
        else:
            t.unparsed.append(f"leg count {m.group(0)!r} is implausible")

    # --- structure
    if _SGP_ONLY.search(s):
        t.sgp_only = True
    elif _SGP_WORD.search(s) and _PARLAY_WORD.search(s):
        # Both named without an "only": the token allows either, which is a
        # STATED fact and not the same as silence.
        t.sgp_only = False
    elif _PARLAY_WORD.search(s) and not _SGP_WORD.search(s):
        t.sgp_only = False
    return t


def parse_tokens(text: str) -> list[Token]:
    """Read a block of token lines — one per line, or separated by ';'.

    Blank lines and obvious headers ("Tokens:", "This week:") are skipped.
    Everything else becomes a Token even when little could be read from it,
    because a line silently dropped is a token Dustin thinks he gave us.
    """
    out: list[Token] = []
    for raw in re.split(r"[\n;]+", text or ""):
        line = raw.strip().lstrip("-*•").strip()
        if not line:
            continue
        if re.fullmatch(r"(tokens?|promos?|this week'?s? (tokens?|promos?))\s*:?",
                        line, re.I):
            continue
        out.append(parse_token(line, label=f"token {len(out) + 1}"))
    return out


def describe_tokens(tokens: list[Token]) -> str:
    """Report a parsed set, including what could not be read."""
    if not tokens:
        return ("no tokens parsed — if you pasted some, the parse found "
                "nothing it recognised, which is a defect to report rather "
                "than a reason to proceed without them")
    L = [f"{len(tokens)} token(s) parsed:"]
    for t in tokens:
        L.append(f"  {t.describe()}")
    unusable = [t for t in tokens if not t.usable]
    if unusable:
        L.append("")
        L.append(f"  *** {len(unusable)} of {len(tokens)} cannot be built to "
                 f"at all until the missing terms are supplied. Ask rather "
                 f"than assume: a boost percentage or a kind guessed wrong "
                 f"changes which bet is right, not just how good it is.")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# F16. Allocating a slate's slips across the tokens on hand.
# ---------------------------------------------------------------------------

def _best_for(token: Token, legs, meta, *, mode: str,
              event_id: str | None = None, limit: int = 8):
    """Shortlist built to ONE token's terms. Import is local to keep
    ff_boost free of any dependency on this module — it reads a Token
    through getattr, so the arrow points one way only."""
    import ff_boost
    return ff_boost.enumerate_candidates(
        legs, meta, mode=mode, event_id=event_id, token=token, limit=limit)


def allocate(tokens: list[Token], legs, meta=None, *, mode: str,
             event_id: str | None = None) -> dict:
    """Which token goes on which slip, and what cannot be compared.

    F16. The hard part is not the assignment, it is the UNIT. Ranking a 30%
    profit boost against a no-sweat token requires a common quantity, and
    the only honest one is dollar EV at the stake each token actually
    allows — which needs `max_stake` stated for both, and for a stake-back
    also needs `bonus_value`, the cash worth of $1 of bonus-bet face.

    B77 is exactly this: `stake_back_ev`'s docstring says the caller must
    state `bonus_value` and its signature supplies 0.65 — a figure measured
    on one book, one market, one night. So a stake-back whose bonus value
    was not stated is **not ranked against anything**; it is listed apart
    with the reason. Returning an order built on that default would be a
    recommendation about which promo to spend, resting on a constant nobody
    chose.

    Returns {assigned, unranked, conflicts, notes}. Nothing here places a
    bet or picks for you; it narrows and names what it could not decide.
    """
    boosts = [t for t in tokens if t.kind == "profit_boost"]
    others = [t for t in tokens if t.kind != "profit_boost"]
    notes: list[str] = []
    unranked: list[tuple[str, str]] = []

    for t in others:
        if t.kind == "stake_back":
            unranked.append((t.label or "token", (
                "stake-back: its value rises as win probability FALLS "
                "(B56), so it does not compete for the same slips as a "
                "boost. Price it with ff_props.stake_back_band on the "
                "LONGEST qualifying price, and note that the dollar answer "
                "needs the bonus value stated — the default 0.65 is one "
                "book, one market, one night (B77).")))
        elif t.kind == "odds_boost":
            unranked.append((t.label or "token", (
                "odds boost: a fixed price improvement on a named "
                "selection, not a percentage of a slip, so there is no "
                "shortlist to build for it here.")))
        else:
            unranked.append((t.label or "token", (
                "kind not stated, so nothing can be built: "
                + "; ".join(t.missing))))

    # Profit boosts are mutually comparable ONLY where both state a stake.
    # Without one, EV percentages still compare but dollar EV does not, and
    # a token capped at $10 against one capped at $25 is a dollar question.
    no_stake = [t.label or "token" for t in boosts
                if t.effective_stake is None]
    if no_stake and len(boosts) > 1:
        notes.append(
            f"{', '.join(no_stake)} did not state a maximum stake, so these "
            f"boosts are ranked on EV PERCENTAGE only. A $10 cap against a "
            f"$25 cap is a dollar question and cannot be settled without "
            f"the caps.")

    assigned: list[dict] = []
    for t in boosts:
        if not t.usable:
            unranked.append((t.label or "token",
                             "missing terms: " + "; ".join(t.missing)))
            continue
        try:
            sl = _best_for(t, legs, meta, mode=mode, event_id=event_id)
        except ValueError as e:
            unranked.append((t.label or "token", str(e)))
            continue
        assigned.append({"token": t, "shortlist": sl,
                         "candidates": sl.candidates,
                         "best": sl.candidates[0] if sl.candidates else None})

    # A slip that is the top pick for two tokens is a CONFLICT, not a
    # ranking problem: each token can be used once and a slip takes one
    # token, so the second-best for one of them has to be found by hand.
    conflicts: list[str] = []
    seen: dict[tuple, str] = {}
    for a in assigned:
        b = a["best"]
        if b is None:
            continue
        key = tuple(sorted(l.player for l in b.legs))
        owner = seen.get(key)
        if owner:
            conflicts.append(
                f"{owner} and {a['token'].label} both rank "
                f"{' + '.join(key)} first. One slip takes one token, so "
                f"pick which token it is worth more on and take the next "
                f"candidate for the other — this does not choose for you.")
        else:
            seen[key] = a["token"].label or "token"
    return {"assigned": assigned, "unranked": unranked,
            "conflicts": conflicts, "notes": notes}


def describe_allocation(alloc: dict) -> str:
    L = []
    for a in alloc["assigned"]:
        t, b = a["token"], a["best"]
        L.append(f"{t.label}: {t.kind} {t.pct:.0%}"
                 + (f", min {t.min_odds:+.0f}" if t.min_odds is not None
                    else "")
                 + (f", stake ${t.effective_stake:,.2f}"
                    if t.effective_stake is not None else ""))
        if b is None:
            L.append("   no candidate clears this token's terms")
        else:
            L.append(f"   best: {' + '.join(l.player for l in b.legs)}  "
                     f"{b.independent_odds:+.0f} product  "
                     f"({len(a['candidates'])} candidates)")
        for n in a["shortlist"].token_notes:
            L.append(f"   - {n}")
    if alloc["conflicts"]:
        L.append("")
        L.append("  *** CONFLICTS")
        for c in alloc["conflicts"]:
            L.append(f"     {c}")
    if alloc["unranked"]:
        L.append("")
        L.append("  NOT RANKED — these are not comparable to the above:")
        for name, why in alloc["unranked"]:
            L.append(f"     {name}: {why}")
    for n in alloc["notes"]:
        L.append("")
        L.append(f"  note: {n}")
    return "\n".join(L)
