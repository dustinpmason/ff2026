"""Bet log and engine-recommendation log (E2 + P6).

WHY THIS EXISTS, AND WHY IT HAD TO BE BUILT BEFORE THE FIRST BET

Closing line value is the only fast feedback a bettor gets. Results take a
season to say anything — at $10 a slip, variance swamps skill for months. CLV
says within hours whether the price you took was better than where the market
landed, and it is the single best predictor of long-run profit.

But CLV **cannot be reconstructed afterwards.** It needs the price you actually
took, at the book you took it at, at the moment you took it. Once the game
kicks off that number is gone — PropLine keeps closing lines, not your
personal fill. A log started in week 12 can never grade weeks 1 through 11.

Two separate logs, deliberately:

  bets.jsonl   What was actually wagered. Grades the BETTOR.
  recs.jsonl   Every engine verdict, INCLUDING PASS. Grades the ENGINE.

Keeping them apart is the whole point of P6. If only placed bets are logged,
the engine is graded on a sample filtered by the bettor's own agreement — the
PASSes that would have won are invisible, and so is the engine's real hit
rate. A model that is right 80% of the time but only gets logged when Dustin
agrees with it looks exactly like a model that is right 80% of the time
because Dustin filtered it. Logging the PASSes separates those two.

PERSISTENCE — read this before changing anything here

The sandbox is destroyed between conversations. Nothing on local disk survives,
not `~/ff` and not `~/ff-data`. So the log lives in **Google Drive**, and the
local files are a working copy:

  1. START of any betting conversation: `sync_pull()` guidance below — download
     every `ff-betlog-*.jsonl` from Drive into LOG_DIR.
  2. Work normally. New records go to `LOG_DIR/_session.jsonl`.
  3. END of the conversation, or right after logging a bet: upload
     `_session.jsonl` to Drive under the name `upload_name()` returns.

One file per session rather than one file rewritten: Drive's `update_file`
changes metadata only, not content, so there is no append. Writing a new file
each time is append-only by construction and cannot race or truncate history.
`_read_all()` globs every `*.jsonl` in LOG_DIR and concatenates, so the split is
invisible to everything above it.

Append-only within a file too, one JSON object per line. Never rewrite history:
a correction is a new record with `corrects` pointing at the original id.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

# Working copy only. The durable copy is in Google Drive — see PERSISTENCE in
# the module docstring. Local disk does not survive the conversation.
LOG_DIR = Path(os.environ.get("FF_LOG_DIR", Path.home() / "ff-data"))
SESSION = LOG_DIR / "_session.jsonl"

# Everything goes in one stream, tagged by `kind`. Bets and engine
# recommendations are separated when read, not when written: one file per
# session means one upload per session, and two files doubled the chance of
# a half-synced history.
BET_KINDS = {"bet", "bet_grade", "leg_grade"}
REC_KINDS = {"rec", "rec_grade"}

DRIVE_PREFIX = "ff-betlog-"      # every log file in Drive starts with this

# The Drive folder holding the durable log. Created 2026-10-30.
# https://drive.google.com/drive/folders/1d3oQvz5rgHmvv9FTet8Bup65pXlLQgtS
DRIVE_FOLDER_ID = "1d3oQvz5rgHmvv9FTet8Bup65pXlLQgtS"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _append(rec: dict) -> dict:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with SESSION.open("a") as f:
        f.write(json.dumps(rec, default=str) + "\n")
    return rec


def _read_all() -> list[dict]:
    """Every record from every log file in LOG_DIR, oldest file first."""
    if not LOG_DIR.exists():
        return []
    out: list[dict] = []
    # Pulled history first, this session's records last, so a correction
    # logged now lands after the record it corrects.
    paths = sorted(p for p in LOG_DIR.glob("*.jsonl") if p != SESSION)
    if SESSION.exists():
        paths.append(SESSION)
    for path in paths:
        for i, line in enumerate(path.read_text().splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                # A corrupt line must not take the whole log down with it.
                # Report it and keep going — the rest is still gradeable.
                print(f"  WARNING: {path.name} line {i} is not valid JSON, "
                      f"skipped")
    return out


def _bets() -> list[dict]:
    return [r for r in _read_all() if r.get("kind") in BET_KINDS]


def _recs() -> list[dict]:
    return [r for r in _read_all() if r.get("kind") in REC_KINDS]


def live_recs() -> list[dict]:
    """Current state of every engine verdict: superseded versions dropped.

    A grade is logged as a NEW record carrying `supersedes`, so the raw log
    holds both the ungraded original and the graded replacement. Counting the
    raw log double-counts every graded verdict — use this everywhere.
    """
    recs = [r for r in _recs() if r.get("kind") == "rec"]
    dead = {r["supersedes"] for r in recs if r.get("supersedes")}
    return [r for r in recs if r["id"] not in dead]


# ---------------------------------------------------------------------------
# Drive sync — the module cannot call MCP tools, so it packages the work and
# the conversation makes the calls.
# ---------------------------------------------------------------------------

def upload_name() -> str:
    """Filename to create in Drive for this session's records.

    Sorts chronologically as a string, which is what `_read_all()` relies on
    to replay corrections in the right order.
    """
    return (f"{DRIVE_PREFIX}"
            f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.jsonl")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def upload_payload() -> tuple[str, str] | None:
    """(filename, text) to push to Drive, or None if nothing new was logged.

    Call after logging bets. Create it in Drive with:
        create_file(title=<name>, textContent=<text>,
                    contentMimeType="text/plain",
                    disableConversionToGoogleType=True,
                    parentId=DRIVE_FOLDER_ID)

    `disableConversionToGoogleType=True` is required. Without it Drive turns
    the file into a Google Doc and the JSONL comes back reflowed.
    """
    if not SESSION.exists() or not SESSION.read_text().strip():
        return None
    text = SESSION.read_text()
    print(f"  checksum {_sha(text)} over {len(text)} chars — after uploading, "
          f"download the file and run verify_uploaded() on what comes back.")
    return upload_name(), text


def verify_uploaded(downloaded: str) -> bool:
    """Does what landed in Drive match what was meant to go there?

    Call after create_file: download the file back and pass its text. Returns
    True on an exact match, and prints what differs otherwise.

    This exists because the upload path is not byte-safe and cannot be made
    so. The content has to travel through a tool call as text, so it is
    retyped, and a 50-bet payload is thousands of characters of JSON. One
    observed case: the local file holds an em dash as the six-character escape
    `\u2014` (json.dumps is ASCII-only by design) and what reached Drive was
    the raw three-byte character — JSON-equivalent by luck, but proof the
    bytes are not preserved. The fix is not to transcribe more carefully; it
    is to make corruption DETECTABLE. A mismatch means re-upload, not shrug.
    """
    want = SESSION.read_text() if SESSION.exists() else None
    if want is None:
        # Already renamed by mark_uploaded — compare against that file.
        cands = sorted(LOG_DIR.glob(f"{DRIVE_PREFIX}*.jsonl"))
        if not cands:
            print("  nothing local to verify against")
            return False
        want = cands[-1].read_text()
    if downloaded == want:
        print(f"  verified: {_sha(want)} — byte-identical, {len(want)} chars")
        return True

    print(f"  MISMATCH. local {_sha(want)} ({len(want)} chars) vs "
          f"downloaded {_sha(downloaded)} ({len(downloaded)} chars)")
    lw, ld = want.splitlines(), downloaded.splitlines()
    if len(lw) != len(ld):
        print(f"  line count differs: {len(lw)} local vs {len(ld)} downloaded")
    for i, (a, b) in enumerate(zip(lw, ld), 1):
        if a != b:
            j = next((k for k in range(min(len(a), len(b))) if a[k] != b[k]),
                     min(len(a), len(b)))
            print(f"  first difference on line {i} at char {j}:")
            print(f"    local      ...{a[max(0,j-25):j+25]!r}")
            print(f"    downloaded ...{b[max(0,j-25):j+25]!r}")
            break
    # Both sides may still parse to the same records — that is luck, not
    # safety, and it is worth knowing which case this is.
    try:
        same = ([json.loads(x) for x in lw if x.strip()]
                == [json.loads(x) for x in ld if x.strip()])
        print(f"  parsed records identical: {same}"
              + ("  (equivalent by luck — re-upload anyway)" if same else ""))
    except json.JSONDecodeError as e:
        print(f"  downloaded copy does not parse: {e}")
    return False


def upload_payload_b64() -> tuple[str, str, str] | None:
    """(filename, base64 of the exact bytes, checksum) — PREFER THIS.

    Upload with `base64Content`, not `textContent`:

        create_file(title=<name>, base64Content=<b64>,
                    contentMimeType="application/json",
                    disableConversionToGoogleType=True,
                    parentId=DRIVE_FOLDER_ID)

    Why base64 rather than the text: the text path is not byte-safe and the
    corruption fired on the very first real payload. `json.dumps` is
    ASCII-only by design, so an em dash in a note is stored as the six
    characters `\u2014`; what reached Drive was the raw three-byte character.
    727 chars local, 722 in Drive, different checksums, and the records
    happened to parse identically — equivalent by luck, which is the worst
    kind of pass.

    Base64 removes the failure mode rather than detecting it. The payload
    becomes pure `[A-Za-z0-9+/=]` with no escape sequences, so there is
    nothing for an un-escaping step to mangle, and any corruption that does
    occur breaks the decode or the checksum loudly instead of surviving as
    valid-looking JSON.

    Still verify afterwards: download, decode, and pass the text to
    verify_uploaded().
    """
    got = upload_payload()
    if got is None:
        return None
    name, text = got
    b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
    return name, b64, _sha(text)


def decode_downloaded(b64_or_text: str) -> str:
    """Normalise whatever came back from Drive into the original text.

    download_file_content returns base64; a file uploaded as base64Content
    round-trips as base64 of the same bytes. Accepts either form so
    verify_uploaded() can be handed the result directly.
    """
    t = b64_or_text.strip()
    try:
        decoded = base64.b64decode(t, validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return b64_or_text
    # A JSONL payload starts with '{'. If decoding produced that, the input
    # really was base64; otherwise it was already the text.
    return decoded if decoded.lstrip().startswith("{") else b64_or_text


def mark_uploaded(name: str) -> None:
    """Rename the session file to its Drive name once the upload succeeded.

    Do this only AFTER create_file returns an id. Renaming first would make a
    failed upload look like pulled history, and the records would never reach
    Drive — silently losing exactly the data this module exists to protect.
    """
    if SESSION.exists():
        SESSION.rename(LOG_DIR / name)


def write_pulled(name: str, text: str) -> Path:
    """Drop a file downloaded from Drive into LOG_DIR."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    p = LOG_DIR / name
    p.write_text(text)
    return p


def sync_state() -> str:
    pulled = sorted(p.name for p in LOG_DIR.glob("*.jsonl")
                    if p != SESSION) if LOG_DIR.exists() else []
    n_new = len(SESSION.read_text().splitlines()) if SESSION.exists() else 0
    L = [f"{len(pulled)} log file(s) pulled from Drive, "
         f"{n_new} record(s) logged this session and NOT YET UPLOADED"]
    for p in pulled:
        L.append(f"    {p}")
    if n_new:
        L.append("")
        L.append("  UPLOAD BEFORE THIS CONVERSATION ENDS. The sandbox is")
        L.append("  destroyed between conversations — an unuploaded record is")
        L.append("  gone, and CLV cannot be reconstructed.")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# Odds helpers (duplicated from ff_props on purpose: this module must be
# importable and usable with no data layer loaded)
# ---------------------------------------------------------------------------

def to_decimal(american: float) -> float:
    a = float(american)
    return 1.0 + (a / 100.0 if a > 0 else 100.0 / abs(a))


def to_american(decimal: float) -> float:
    d = float(decimal)
    return round((d - 1.0) * 100.0 if d >= 2.0 else -100.0 / (d - 1.0))


def to_prob(american: float) -> float:
    return 1.0 / to_decimal(american)


# ---------------------------------------------------------------------------
# Legs and slips
# ---------------------------------------------------------------------------

@dataclass
class Leg:
    """One leg of a slip, as priced at the moment of the bet."""
    player: str
    market: str                      # player_rush_yds, player_anytime_td, ...
    line: float | None               # None for anytime-TD style markets
    side: str                        # OVER / UNDER / YES
    odds: float                      # American, AS TAKEN
    book: str
    event_id: str | None = None
    # The sharp reference AT THE TIME OF THE BET. Recorded because it is the
    # only way to tell a good process from a lucky result.
    fair_p: float | None = None
    fair_source: str | None = None
    devig_method: str | None = None
    # Engine verdict for this leg, if one was taken.
    engine_tier: str | None = None
    engine_model_p: float | None = None
    # Graded later.
    result: str | None = None        # WIN / LOSS / PUSH / VOID
    actual: float | None = None
    closing_odds: float | None = None
    closing_fair_p: float | None = None


def log_bet(slip_odds: float,
            stake: float,
            legs: list[Leg],
            book: str,
            boost_pct: float = 0.0,
            boost_type: str = "",
            slip_type: str = "sgp",
            note: str = "",
            placed_at: str | None = None) -> dict:
    """Record a placed bet. Call this WHEN THE BET IS PLACED, not afterwards.

    `slip_odds` is the American price on the slip as a whole, AFTER any boost
    is reflected in the odds. If the boost pays as bonus/profit boost on top
    of the stated odds instead, record the stated odds here and set
    `boost_pct` — the payout math reads both.
    """
    rec = {
        "id": uuid.uuid4().hex[:12],
        "kind": "bet",
        "logged_at": _now(),
        "placed_at": placed_at or _now(),
        "book": book,
        "slip_type": slip_type,
        "n_legs": len(legs),
        "slip_odds": float(slip_odds),
        "slip_decimal": to_decimal(slip_odds),
        "stake": float(stake),
        "boost_pct": float(boost_pct),
        "boost_type": boost_type,
        "legs": [asdict(l) for l in legs],
        "note": note,
        "result": None,
        "payout": None,
    }
    return _append(rec)


def log_recommendation(player: str,
                       market: str,
                       line: float | None,
                       side: str,
                       tier: str,
                       model_p: float,
                       fair_p: float | None,
                       odds: float | None,
                       book: str = "",
                       fair_source: str = "",
                       devig_method: str = "",
                       reasoning: str = "",
                       acted_on: bool = False,
                       bet_id: str | None = None) -> dict:
    """Record an engine verdict — INCLUDING PASS and COIN-FLIP.

    This is the half that makes the engine gradeable. Log every verdict the
    engine produces, whether or not it was bet. `acted_on` and `bet_id` link
    a recommendation to the slip it ended up on, so agreement rate and engine
    accuracy can be measured separately.
    """
    rec = {
        "id": uuid.uuid4().hex[:12],
        "kind": "rec",
        "logged_at": _now(),
        "player": player,
        "market": market,
        "line": line,
        "side": side,
        "tier": tier,
        "model_p": float(model_p),
        "fair_p": None if fair_p is None else float(fair_p),
        "odds": None if odds is None else float(odds),
        "book": book,
        "fair_source": fair_source,
        "devig_method": devig_method,
        "reasoning": reasoning,
        "acted_on": bool(acted_on),
        "bet_id": bet_id,
        "result": None,
        "actual": None,
    }
    return _append(rec)


def log_edge(edge, player: str, market: str, line: float | None,
             odds: float | None = None, book: str = "",
             acted_on: bool = False, bet_id: str | None = None) -> dict:
    """Convenience: log an `ff_props.Edge` straight from prop_edge()."""
    return log_recommendation(
        player=player, market=market, line=line, side=edge.side,
        tier=edge.tier, model_p=edge.model_p, fair_p=edge.fair_p,
        odds=odds, book=book, fair_source=edge.fair_source,
        devig_method=getattr(edge, "devig_method", ""),
        reasoning=edge.reasoning, acted_on=acted_on, bet_id=bet_id)


# ---------------------------------------------------------------------------
# Grading
# ---------------------------------------------------------------------------

def grade_leg(bet_id: str, leg_index: int, result: str,
              actual: float | None = None,
              closing_odds: float | None = None) -> dict:
    """Append a grade for one leg. Never edits the original record."""
    if result not in ("WIN", "LOSS", "PUSH", "VOID"):
        raise ValueError(f"result must be WIN/LOSS/PUSH/VOID, got {result!r}")
    return _append({
        "id": uuid.uuid4().hex[:12],
        "kind": "leg_grade",
        "logged_at": _now(),
        "bet_id": bet_id,
        "leg_index": int(leg_index),
        "result": result,
        "actual": actual,
        "closing_odds": None if closing_odds is None else float(closing_odds),
    })


def grade_bet(bet_id: str, result: str, payout: float | None = None) -> dict:
    """Append a slip-level grade."""
    if result not in ("WIN", "LOSS", "PUSH", "VOID"):
        raise ValueError(f"result must be WIN/LOSS/PUSH/VOID, got {result!r}")
    return _append({
        "id": uuid.uuid4().hex[:12],
        "kind": "bet_grade",
        "logged_at": _now(),
        "bet_id": bet_id,
        "result": result,
        "payout": None if payout is None else float(payout),
    })


def clv(taken_odds: float, closing_odds: float) -> float:
    """Closing line value, as a fraction.

    Positive means the price taken was better than the close: the market moved
    toward the bet. This is the number that predicts long-run profit, and it is
    knowable within hours instead of months.

    Computed on decimal odds, which is the only form where the ratio is
    meaningful — American odds are discontinuous across +100/-100 and a
    difference in "cents" is not comparable between a -500 and a +500 leg.
    """
    return to_decimal(taken_odds) / to_decimal(closing_odds) - 1.0


def boosted_payout(stake: float, slip_odds: float,
                   boost_pct: float = 0.0,
                   boost_on: str = "profit") -> float:
    """Return total returned on a win, including the boost.

    `boost_on`:
      "profit" — the usual profit boost: profit is multiplied by (1+pct).
                 Stake comes back on top.
      "odds"   — the odds themselves are boosted before settling.
    """
    d = to_decimal(slip_odds)
    profit = stake * (d - 1.0)
    if boost_on == "profit":
        return stake + profit * (1.0 + boost_pct)
    if boost_on == "odds":
        return stake * (1.0 + (d - 1.0) * (1.0 + boost_pct))
    raise ValueError(f"boost_on must be 'profit' or 'odds', got {boost_on!r}")


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _apply_grades(bets: list[dict]) -> list[dict]:
    """Fold grade records onto their bets. Grades are appended, not edited, so
    the log is replayable; this reconstructs current state."""
    by_id = {b["id"]: dict(b) for b in bets if b.get("kind") == "bet"}
    for r in bets:
        k = r.get("kind")
        if k == "bet_grade" and r["bet_id"] in by_id:
            by_id[r["bet_id"]]["result"] = r["result"]
            if r.get("payout") is not None:
                by_id[r["bet_id"]]["payout"] = r["payout"]
        elif k == "leg_grade" and r["bet_id"] in by_id:
            legs = by_id[r["bet_id"]]["legs"]
            i = r["leg_index"]
            if 0 <= i < len(legs):
                legs[i]["result"] = r["result"]
                if r.get("actual") is not None:
                    legs[i]["actual"] = r["actual"]
                if r.get("closing_odds") is not None:
                    legs[i]["closing_odds"] = r["closing_odds"]
    return list(by_id.values())


def bet_summary() -> str:
    """What the bets actually did. Honest about small samples."""
    bets = _apply_grades(_bets())
    if not bets:
        return ("No bets logged yet.\n"
                "  Log each slip AS IT IS PLACED with log_bet(). CLV cannot be\n"
                "  reconstructed afterwards — your fill price is gone once the\n"
                "  game starts.")

    graded = [b for b in bets if b.get("result") in ("WIN", "LOSS")]
    staked = sum(b["stake"] for b in graded)
    returned = sum(
        b.get("payout") if b.get("payout") is not None
        else (boosted_payout(b["stake"], b["slip_odds"], b.get("boost_pct", 0.0))
              if b["result"] == "WIN" else 0.0)
        for b in graded)

    L = [f"BET LOG — {len(bets)} slips, {len(graded)} graded"]
    if graded:
        wins = sum(1 for b in graded if b["result"] == "WIN")
        L.append(f"  record      : {wins}-{len(graded)-wins}  "
                 f"({wins/len(graded):.0%} hit rate)")
        L.append(f"  staked      : ${staked:,.2f}")
        L.append(f"  returned    : ${returned:,.2f}")
        L.append(f"  net         : ${returned-staked:+,.2f}  "
                 f"(ROI {(returned-staked)/staked:+.1%})" if staked else "")

    # CLV — the number that actually means something at this sample size.
    vals = [clv(l["odds"], l["closing_odds"])
            for b in bets for l in b["legs"]
            if l.get("closing_odds") is not None]
    if vals:
        v = np.array(vals)
        L.append(f"  legs w/ CLV : {len(v)}")
        L.append(f"  mean CLV    : {v.mean():+.2%}   median {np.median(v):+.2%}")
        L.append(f"  beat close  : {(v > 0).mean():.0%} of legs")
        L.append("")
        L.append("  CLV is the signal to trust at this sample size. Record is not:")
        L.append(f"  {len(graded)} graded slips says essentially nothing about skill,")
        L.append("  while positive CLV across 30+ legs does.")
    else:
        L.append("")
        L.append("  No closing lines recorded yet. Grade legs with")
        L.append("  grade_leg(..., closing_odds=...) using propline_get_odds_closing")
        L.append("  or propline_grade_clv after each slate. Without closing odds")
        L.append("  there is no fast feedback — only win/loss, which takes months.")

    if graded:
        boosted = [b for b in graded if b.get("boost_pct", 0)]
        if boosted:
            bs = sum(b["stake"] for b in boosted)
            br = sum(b.get("payout") or
                     (boosted_payout(b["stake"], b["slip_odds"], b["boost_pct"])
                      if b["result"] == "WIN" else 0.0) for b in boosted)
            L.append("")
            L.append(f"  boosted slips: {len(boosted)}  "
                     f"net ${br-bs:+,.2f} on ${bs:,.2f}")
    return "\n".join(x for x in L if x != "")


def rec_summary() -> str:
    """How the ENGINE did — on every verdict, not just the ones that were bet.

    This is the half that answers "is the model adding anything". Agreement
    rate and engine accuracy are reported separately, because a model graded
    only on the calls Dustin agreed with is graded on his filter, not its own.
    """
    recs = live_recs()
    if not recs:
        return ("No engine recommendations logged yet.\n"
                "  Log EVERY verdict with log_edge(), including PASS. Logging\n"
                "  only the ones you bet measures your filter, not the model.")

    L = [f"ENGINE LOG — {len(recs)} verdicts"]
    tiers: dict[str, list[dict]] = {}
    for r in recs:
        tiers.setdefault(r["tier"], []).append(r)

    L.append("")
    L.append(f"  {'tier':<12}{'n':>5}{'acted':>8}{'graded':>8}{'hit':>8}")
    for tier, rs in sorted(tiers.items(), key=lambda kv: -len(kv[1])):
        g = [r for r in rs if r.get("result") in ("WIN", "LOSS")]
        acted = sum(1 for r in rs if r.get("acted_on"))
        hit = (f"{sum(1 for r in g if r['result']=='WIN')/len(g):.0%}"
               if g else "—")
        L.append(f"  {tier:<12}{len(rs):>5}{acted:>8}{len(g):>8}{hit:>8}")

    graded = [r for r in recs if r.get("result") in ("WIN", "LOSS")]
    if graded:
        # Calibration: does a 70% call win 70% of the time? This is the only
        # question that matters about a probability model, and it is the one
        # a bets-only log cannot answer.
        L.append("")
        L.append("  calibration (model probability vs realised)")
        buckets = [(0.0, .4), (.4, .55), (.55, .7), (.7, .85), (.85, 1.0)]
        for lo, hi in buckets:
            b = [r for r in graded if lo <= r["model_p"] < hi]
            if not b:
                continue
            exp = float(np.mean([r["model_p"] for r in b]))
            act = sum(1 for r in b if r["result"] == "WIN") / len(b)
            L.append(f"    {lo:.0%}-{hi:.0%}  n={len(b):<4} "
                     f"said {exp:.0%}  went {act:.0%}  "
                     f"{'over' if exp > act else 'under'}confident by "
                     f"{abs(exp-act):.0%}")
        passes = [r for r in graded if r["tier"] == "PASS"]
        if passes:
            w = sum(1 for r in passes if r["result"] == "WIN") / len(passes)
            L.append("")
            L.append(f"  PASSes that would have won: {w:.0%} of {len(passes)}")
            L.append("  A PASS rate near the market's implied probability means")
            L.append("  the vetoes are not costing anything. Well above it means")
            L.append("  the guard is too tight.")
    else:
        L.append("")
        L.append("  Nothing graded yet. Grade with grade_rec() after each slate.")
    return "\n".join(L)


def grade_rec(rec_id: str, result: str, actual: float | None = None) -> dict:
    """Append a grade for one engine recommendation."""
    if result not in ("WIN", "LOSS", "PUSH", "VOID"):
        raise ValueError(f"result must be WIN/LOSS/PUSH/VOID, got {result!r}")
    hit = next((r for r in live_recs() if r.get("id") == rec_id), None)
    if hit is None:
        raise ValueError(f"no recommendation with id {rec_id!r}")
    # ONE record, not two. An earlier version wrote both a `rec_grade` audit
    # copy and a superseding `rec`, which double-counted every graded verdict
    # in rec_summary — "10 verdicts" for 5 recommendations, and every tier
    # count doubled. The superseding record IS the audit trail: it carries
    # `supersedes`, and the original is still in the log, untouched.
    merged = dict(hit)
    merged.update({"id": uuid.uuid4().hex[:12], "kind": "rec",
                   "logged_at": _now(), "supersedes": rec_id,
                   "result": result, "actual": actual})
    return _append(merged)


def pending() -> str:
    """Everything waiting to be graded. Run this Monday morning."""
    bets = _apply_grades(_bets())
    recs = live_recs()

    ub = [b for b in bets if b.get("result") is None]
    nc = [(b, i, l) for b in bets for i, l in enumerate(b["legs"])
          if l.get("closing_odds") is None]
    ur = [r for r in recs if r.get("result") is None]

    L = ["TO GRADE"]
    L.append(f"  {len(ub)} ungraded slips, {len(nc)} legs without a closing "
             f"line, {len(ur)} ungraded engine verdicts")
    for b in ub[:10]:
        legs = ", ".join(f"{l['player']} {l['side']} {l.get('line','')}"
                         for l in b["legs"])
        L.append(f"    {b['id']}  {b['book']} ${b['stake']:.0f} "
                 f"{b['slip_odds']:+.0f}  {legs}")
    if len(ub) > 10:
        L.append(f"    ... and {len(ub)-10} more")
    if nc:
        L.append("")
        L.append("  Closing lines matter more than results. Pull them with")
        L.append("  propline_get_odds_closing for each event, then")
        L.append("  grade_leg(bet_id, i, result, closing_odds=...).")
    return "\n".join(L)


def status() -> str:
    """Where the log stands. Run this at the start of a betting conversation."""
    bets = [r for r in _bets() if r.get("kind") == "bet"]
    recs = live_recs()
    return "\n".join([
        f"logs in {LOG_DIR} (working copy — durable copy is in Drive)",
        f"  {len(bets)} bets, {len(recs)} engine verdicts",
        f"  {sync_state()}",
    ])
