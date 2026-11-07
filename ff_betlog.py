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
import re
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


_WARNED: set = set()


def _warn_once(msg: str) -> None:
    """Say it once per process, not once per read.

    `status()` reads the log twice (bets, then recs) and every read
    re-emitted every warning, so a single stray file produced two
    identical lines and a corrupt log line produced three. A warning
    repeated is a warning skimmed — and worse, the repetition made the
    log look more broken than it is.
    """
    if msg not in _WARNED:
        _WARNED.add(msg)
        print(msg)


def _read_all() -> list[dict]:
    """Every record from every log file in LOG_DIR, oldest file first."""
    if not LOG_DIR.exists():
        return []
    out: list[dict] = []
    # Pulled history first, this session's records last, so a correction
    # logged now lands after the record it corrects.
    paths = sorted(p for p in LOG_DIR.glob(f"{DRIVE_PREFIX}*.jsonl")
                   if p != SESSION)
    # DRIVE_PREFIX was defined and never enforced here: this globbed
    # `*.jsonl`, so any stray .jsonl in LOG_DIR was ingested AS HISTORY,
    # and — the dangerous half — a real log saved under any other
    # extension was silently skipped. A `.txt` log carrying a $500 bet
    # read as no history at all, with no warning, which is the exact
    # shape B58 exists to prevent. Anything in LOG_DIR that looks like a
    # log but will not be read must say so rather than vanish.
    strays = sorted(p.name for p in LOG_DIR.iterdir()
                    if p.is_file() and p != SESSION and p != PULL_MARKER
                    and p not in paths
                    and (p.suffix in {".jsonl", ".json", ".txt"}
                         or p.name.startswith(DRIVE_PREFIX)))
    for name in strays:
        _warn_once(f"  WARNING: {name} is in the log directory but will NOT "
                   f"be read — history is only loaded from "
                   f"{DRIVE_PREFIX}*.jsonl. If this is a real log, rename it.")
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
                _warn_once(f"  WARNING: {path.name} line {i} is not valid "
                           f"JSON, skipped")
    return out


def _bets() -> list[dict]:
    return [r for r in _read_all() if r.get("kind") in BET_KINDS]


def _recs() -> list[dict]:
    return [r for r in _read_all() if r.get("kind") in REC_KINDS]


# B113. A sentinel, not a default. An OMITTED event_id and a deliberate
# `event_id=None` are different facts, and with `= None` they were the same
# keystroke-free outcome — which is D16/B39 exactly: unchecked state must not
# look like checked state. Zero of 101 records in the live log carry one,
# because nothing ever made the caller decide. The reading-side guard
# (`_independence`) is INERT until coverage exists, so it closes nothing on
# its own; this closes it at the cheap end, the way B70 made `market=`
# required on `devig_field` one module over.
_MUST_PASS = object()


def _resolve_event_id(event_id, fn: str):
    if event_id is _MUST_PASS:
        raise TypeError(
            f"{fn}() needs event_id=. Verdicts cluster by game, and without "
            f"it the calibration report cannot tell four verdicts on four "
            f"games from four on one — it prints CANNOT BE READ and the "
            f"whole scorecard says nothing. Pass the PropLine event id as a "
            f"string, e.g. event_id=\"53178\". If you genuinely do not have "
            f"one, pass event_id=None EXPLICITLY: that is a decision on "
            f"record, and leaving it out is not.")
    return _norm_event(event_id)


# B107. Below this many INDEPENDENT UNITS — distinct events where every
# verdict carries an id, and nothing at all otherwise, per `_independence` —
# a calibration bucket is reporting one game rather than a sample, and
# printing "overconfident by 77%" beside it reads as a finding. The name said
# DISTINCT PLAYERS while the code compared something else; one name, two
# meanings (lesson 23), so the comment now points at the one function that
# decides it. Set at 5 because the live case had 4 verdicts over 3 players in
# 1 event — Baltimore pass-catchers on the night both their quarterbacks went
# to IR. This is a READABILITY threshold, not a statistical one: it decides
# whether a VERDICT is printed, never what the numbers are.
#
# Measured firing rate, full event coverage (lesson 51 — and the FIRST set of
# these numbers was wrong, in the permissive direction; see B111). The
# threshold is PER BUCKET, so what matters is how many distinct games land in
# each one, not how many verdicts are in the log:
#   9 verdicts over 1 game  (the real log)  -> every bucket refuses
#   15 verdicts over 5 games                -> 1 of 2 buckets still refuses
#   24 verdicts over 8 games                -> reads
#   46 verdicts over 1 game                 -> every bucket refuses
# So roughly 8 games' worth of logged verdicts clears it, which is one or two
# Sundays, and no amount of volume from a single game ever does. Partial or
# absent coverage does not refuse for clustering — it reports that clustering
# was not measurable, which is a different claim.
MIN_INDEPENDENT_FOR_CALIBRATION = 5


# B66. A structural marker for records that are not real bets or verdicts.
# Verified 2026-11-05: all eight trashed logs were test data and the claim
# held only because a HUMAN had written "delete me" in prose. Two of the
# eight used real players at plausible prices — Tyreek Hill reception yards
# 54.5 OVER at -115 for $10, and the Travis Kelce anytime-TD example straight
# out of PROJECT-INSTRUCTIONS reused as a fixture. On player, market, price,
# stake and boost alone both are indistinguishable from a bet Dustin would
# place. Nothing validated, grepped for, or filtered on the free-text note.
#
# So: a flag on the record, excluded from every summary by default, and a
# loud line when any are present. The flag is the ONLY thing that makes a
# record test data — a note saying "test" does not, which is the whole point.
TEST_FLAG = "is_test"


def is_test_record(r: dict) -> bool:
    return bool(r.get(TEST_FLAG))


def _real(rs: list[dict]) -> list[dict]:
    """Records that are not flagged test data."""
    return [r for r in rs if not is_test_record(r)]




def live_recs() -> list[dict]:
    """Current state of every engine verdict: superseded versions dropped.

    A grade is logged as a NEW record carrying `supersedes`, so the raw log
    holds both the ungraded original and the graded replacement. Counting the
    raw log double-counts every graded verdict — use this everywhere.
    """
    recs = [r for r in _recs() if r.get("kind") == "rec"]
    dead = {r["supersedes"] for r in recs if r.get("supersedes")}
    # B66. Deliberately NOT filtered here. `grade_rec` and the gap detector
    # look records up by id and must see every one of them — a first cut
    # filtered at this accessor and grade_rec could no longer find a test
    # record to grade. The exclusion belongs where the NUMBERS are computed,
    # which is rec_summary, and nowhere else.
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
    r"""Does what landed in Drive match what was meant to go there?

    Call after create_file: download the file back and pass its text. Returns
    True on an exact match, and prints what differs otherwise.

    Verification is at the RECORD level, not the byte level (B91). Byte
    equality is reported when it happens, but a difference caused by Drive
    decoding `\uXXXX` escapes is a lossless JSON transcoding and passes:
    identical records, identical order. Only a real content change fails.
    Requiring byte-identity made this function unable to pass for any log
    containing an em dash, which is all of them.

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

    # B91. Byte-identity was the only way to pass, and it is UNREACHABLE for
    # any log containing a non-ASCII character. `json.dumps` is ASCII-only by
    # design, so an em dash is written locally as the escape `\u2014` and
    # comes back from Drive as the raw character. Measured: `ff_props.py`
    # holds 178 em dashes, 35 of them inside verdict-reason f-strings, so
    # EVERY role-change verdict guarantees a mismatch. The docstring's advice
    # — "a mismatch means re-upload, not shrug" — cannot help, because the
    # transcoding is in the transport, not the attempt: a session re-uploaded
    # and got False again, then declined to call mark_uploaded, leaving 69
    # verdicts up but unmarked.
    #
    # The old code already computed record equality and still returned False,
    # calling it "equivalent by luck". That is the wrong reading of THIS
    # cause. Escape-versus-raw for the same codepoint is a deterministic,
    # lossless JSON transcoding — every conformant reader decodes it the
    # same way — whereas a truncation or a reordering is what luck would
    # look like, and both show up at the record level. So compare CANONICAL
    # serialisations: identical records in identical order is the property
    # that actually matters, and it is checkable.
    #
    # A check that can never pass is not caution, it is noise — and it
    # trains the reader to ignore the one signal meant to be load-bearing,
    # which is B39's lesson arriving from the other side.
    try:
        lw_r = [json.loads(x) for x in want.splitlines() if x.strip()]
        ld_r = [json.loads(x) for x in downloaded.splitlines() if x.strip()]
        canon = lambda rs: [json.dumps(r, sort_keys=True, ensure_ascii=True)
                            for r in rs]
        if canon(lw_r) == canon(ld_r):
            print(f"  verified: {len(lw_r)} records identical field-for-field "
                  f"and in order. Bytes differ ({len(want)} local vs "
                  f"{len(downloaded)} downloaded) because Drive decodes "
                  f"\\uXXXX escapes in transit — a lossless JSON "
                  f"transcoding, not a content change. Safe to "
                  f"mark_uploaded.")
            return True
    except json.JSONDecodeError as e:
        print(f"  downloaded copy does not parse: {e}")
        return False

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


PULL_MARKER = LOG_DIR / "_pull.json"


def record_pull(live: list | None = None, trashed: list | None = None,
                *, error: str | None = None) -> str:
    """Record that a Drive pull HAPPENED, and what it saw. B58.

    Call this once per session, straight after querying Drive, with the
    filenames the search returned — even when it returned none. Pass the
    `trashed = true` query's results as `trashed`.

    **Why this exists.** `sync_state()` reports "N log file(s) pulled from
    Drive", which at N=0 cannot distinguish *nobody pulled* from *the pull
    found nothing*. Those are opposite situations: the first means the
    history is UNKNOWN and must not be written over, the second means
    there is genuinely none. On 2026-11-04 a session read that line as the
    second, concluded no prior log existed, and uploaded a fresh one. It
    happened to be right — but it could not have known, and that is the
    B39 UNSCREENED shape: an unchecked state must not look like a checked
    one.

    **Why `trashed` matters, measured.** Drive's search defaults to
    `trashed = false`, so a `parentId` query returns nothing when every
    file in the folder is in the trash. Checked 2026-11-05: that folder
    held one live file and **eight trashed logs** the default query could
    not see. Those eight were throwaway test records — "VERIFICATION
    TEST", "THROWAWAY verification bet - delete", "ROUND-TRIP TEST" — so
    no real history was lost. Next time it may not be test data, and a
    pull that cannot see the trash reports an empty folder either way.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    live = _namelist(live, "live")
    trashed = None if trashed is None else _namelist(trashed, "trashed")
    rec = {"at": _now(), "live": sorted(live),
           "trashed": sorted(trashed or []),
           "trash_checked": trashed is not None,
           "error": str(error) if error else None}
    PULL_MARKER.write_text(json.dumps(rec, indent=2))
    return pull_state()


def _namelist(v, what: str) -> list:
    """Filenames must arrive as a LIST. A string is not one filename.

    `sorted("ff-betlog-....jsonl")` returns 32 characters and
    `record_pull` happily reported "32 live file(s)" — a confident,
    plausible, WRONG count from a caller who passed one name instead of a
    list of one. A dict reports its key count. Only an int ever raised.
    That is this project's signature failure (B24, B28, B37): a plausible
    number instead of an error. It inflates the apparent history, which
    is the flattering direction — it makes the log look better pulled
    than it was.
    """
    if v is None:
        return []
    if isinstance(v, (str, bytes)) or not isinstance(v, (list, tuple, set)):
        raise TypeError(
            f"record_pull({what}=...) needs a list of filenames, got "
            f"{type(v).__name__}. One filename is ['name.jsonl'], not "
            f"'name.jsonl' — a bare string counts its characters as files.")
    return [str(x) for x in v]


def pull_state() -> str:
    """What the Drive pull found — or that nobody looked. B58."""
    if not PULL_MARKER.exists():
        return ("*** NO DRIVE PULL RECORDED THIS SESSION. The history is "
                "UNKNOWN, not empty. Query the folder and call "
                "record_pull() before logging or uploading anything — an "
                "upload now can orphan records nobody has seen.")
    try:
        rec = json.loads(PULL_MARKER.read_text())
        if not isinstance(rec, dict) or not rec.get("at"):
            raise ValueError("marker is not a completed pull record")
    except (ValueError, TypeError, AttributeError, OSError) as e:
        # Widened from (ValueError, OSError). A marker of `[]` is valid
        # JSON of the wrong shape and raised AttributeError straight out
        # of `rec.get`, taking down the whole of status() rather than one
        # line of it. And a marker of `{}` — a half-written file — used to
        # print "Drive pull at None: 0 live file(s)", presenting a
        # truncated write as a successfully recorded pull of an empty
        # folder. The `at: None` was the only tell and nothing read it.
        return (f"*** pull marker unusable ({e}) — treat history as "
                f"UNKNOWN and pull again before uploading")
    if rec.get("error"):
        return (f"*** THE DRIVE QUERY FAILED at {rec['at']}: "
                f"{rec['error']}. The folder's contents are UNKNOWN. This "
                f"is NOT an empty folder — do not log or upload against "
                f"it, because an upload now can orphan records nobody has "
                f"seen.")
    live, trashed = rec.get("live", []), rec.get("trashed", [])
    L = [f"Drive pull at {rec.get('at')}: {len(live)} live file(s)"]
    if not rec.get("trash_checked"):
        L.append("    TRASH NOT CHECKED — Drive hides trashed files by "
                 "default, so an empty result proves nothing. Re-query "
                 "with `trashed = true`.")
    elif trashed:
        L.append(f"    {len(trashed)} TRASHED file(s) in the same folder: "
                 f"{', '.join(trashed[:4])}"
                 f"{' ...' if len(trashed) > 4 else ''}")
        if not live:
            L.append("    *** every log in this folder is in the trash. Do "
                     "NOT treat this as a fresh start — read them before "
                     "uploading, or the history is orphaned.")
    elif not live:
        # The clean-and-empty case used to print this line ALONE, with no
        # second line at all — the most reassuring output this function
        # can produce, and byte-identical to what a session gets if its
        # query ERRORED and it recorded `record_pull([], [])` anyway. B58
        # closed "nobody pulled" vs "the pull found nothing" and left "the
        # pull failed" sitting in the same hole, one notch along. So the
        # quiet case now states its claim out loud instead of being
        # silent: silence is what an unasked question looks like.
        L.append("    both queries returned successfully and the folder is "
                 "genuinely empty — if either query errored, that is "
                 "record_pull(error=...), not this.")
    return "\n".join(L)


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
            is_test: bool = False,
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
        **({TEST_FLAG: True} if is_test else {}),
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
                       bet_id: str | None = None,
                       *,
                       event_id: str | None = _MUST_PASS,
                       is_test: bool = False) -> dict:
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
        # B110. Unvalidated, a model_p of 77.0 (a percentage, not a
        # fraction) landed in no calibration bucket at all and printed a
        # header with nothing beneath it. Refused at the door instead.
        "model_p": _check_prob(model_p, "model_p"),
        "fair_p": None if fair_p is None else float(fair_p),
        "odds": None if odds is None else float(odds),
        "book": book,
        "fair_source": fair_source,
        "devig_method": devig_method,
        "reasoning": reasoning,
        "acted_on": bool(acted_on),
        "bet_id": bet_id,
        # B107. Without this, nothing can tell four verdicts on four games
        # from four on one. Optional, because older records do not have it
        # and backfilling would be inventing data.
        "event_id": _resolve_event_id(event_id, "log_recommendation"),
        # B66. Structural, not prose. Omitted entirely when False so the
        # 101 existing records are unchanged and still read as real.
        **({TEST_FLAG: True} if is_test else {}),
        "result": None,
        "actual": None,
    }
    return _append(rec)


def log_edge(edge, player: str, market: str, line: float | None,
             odds: float | None = None, book: str = "",
             acted_on: bool = False, bet_id: str | None = None,
             *, event_id: str | None = _MUST_PASS,
             is_test: bool = False) -> dict:
    """Convenience: log an `ff_props.Edge` straight from prop_edge()."""
    return log_recommendation(
        player=player, market=market, line=line, side=edge.side,
        tier=edge.tier, model_p=edge.model_p, fair_p=edge.fair_p,
        odds=odds, book=book, fair_source=edge.fair_source,
        devig_method=getattr(edge, "devig_method", ""),
        reasoning=edge.reasoning, acted_on=acted_on, bet_id=bet_id,
        event_id=_resolve_event_id(event_id, "log_edge"),
        is_test=is_test)


# ---------------------------------------------------------------------------
# Grading
# ---------------------------------------------------------------------------

def check_clv_source(book: str, fair_source: str | None) -> str | None:
    """Is a closing fair line usable, or is it the book you bet at?

    B102. The project's oldest rule is that a book is not its own reference —
    "RIGHT: fair line from a sharp anchor, price from the book you'd bet.
    WRONG: de-vigs DraftKings against itself." It was never applied to the
    GRADING path, where the same circularity is harder to see because the
    number arrives pre-computed from an external grader.

    Measured 2026-11-06 grading a real slip: PropLine's `grade_clv` returned
    `ev_vs_close_pct` of -4.86% and -3.70% with **`fair_source: draftkings`
    on both legs — the book the bet was placed at.** So the figure was
    largely measuring DraftKings' own 5.6% hold rather than whether the
    price taken was good. Re-graded against the best SAME-POINT non-DK
    close, the three-leg average was at best -5.20% and truly worse.

    Returns None when the source is usable, or the sentence to print
    instead of the number. **It never silently corrects anything** — an
    external grader's figure is its own, and the only honest options are to
    quote it with the caveat or to re-grade against a different book.
    """
    if not fair_source:
        return ("closing fair line has NO source recorded, so ev_vs_close "
                "cannot be trusted — quote clv_pct (price vs price) or "
                "re-grade against a named book.")
    if norm_book(fair_source) == norm_book(book):
        return (f"CIRCULAR: the closing fair line is sourced from "
                f"{fair_source!r}, which is the book this was BET at. "
                f"ev_vs_close here is mostly that book's own hold, not "
                f"whether the price was good. Re-grade against a sharp "
                f"book at the SAME POINT, or quote it as a lower bound and "
                f"say so.")
    return None


def norm_book(name: str | None) -> str:
    """Book key for comparison — lowercase, no spaces or punctuation."""
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower())


def grade_leg(bet_id: str, leg_index: int, result: str,
              actual: float | None = None,
              closing_odds: float | None = None,
              closing_fair_source: str | None = None,
              book: str | None = None) -> dict:
    """Append a grade for one leg. Never edits the original record.

    B102. `closing_fair_source` and `book` are recorded so a later reader
    can tell a clean CLV from a circular one. Passing both runs
    `check_clv_source` and REFUSES the circular case rather than writing a
    number that reads as measured value.
    """
    if result not in ("WIN", "LOSS", "PUSH", "VOID"):
        raise ValueError(f"result must be WIN/LOSS/PUSH/VOID, got {result!r}")
    if book and closing_fair_source:
        problem = check_clv_source(book, closing_fair_source)
        if problem:
            raise ValueError(
                f"refusing to grade leg {leg_index} of {bet_id}: {problem}")
    return _append({
        "closing_fair_source": closing_fair_source,
        "book": book,
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
        # B110. The "record is not the signal" caution lived inside the CLV
        # branch below, so with no closing lines recorded — the log's actual
        # state — a 33% hit rate and a +108% ROI printed with no caution of
        # any kind. The caution belongs to the RECORD, which is right here.
        _u, _why = _bet_independence(graded)
        if _u is not None:
            L.append(f"  spread      : {_u} distinct "
                     f"{'game' if _u == 1 else 'games'} across "
                     f"{len(graded)} graded slips")
        if _u is None or _u < MIN_INDEPENDENT_FOR_CALIBRATION:
            L.append(f"  NOT A RATE YET — {_why}. Slips on the same game "
                     "are one observation, not several.")

    # CLV — the number that actually means something at this sample size.
    vals = [clv(l["odds"], l["closing_odds"])
            for b in bets for l in _legs(b)
            if l.get("closing_odds") is not None
            and _num(l.get("odds")) is not None]
    if vals:
        v = np.array(vals)
        L.append(f"  legs w/ CLV : {len(v)}")
        L.append(f"  mean CLV    : {v.mean():+.2%}   median {np.median(v):+.2%}")
        L.append(f"  beat close  : {(v > 0).mean():.0%} of legs")
        L.append("")
        L.append("  CLV is the signal to trust at this sample size. Record is not:")
        L.append(f"  {len(graded)} graded slips says essentially nothing "
                 "about skill,")
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


def _check_prob(p, name: str) -> float | None:
    """A probability, an explicit None, or a refusal. B110/B113.

    None is the honest value for a backfilled verdict whose probability was
    never recorded: the calibration block already separates those out and
    NAMES the count, so they cost nothing, while an invented number would
    enter the figures looking measured. A percentage is a different thing —
    an error — and is still refused.
    """
    if p is None:
        return None
    v = float(p)
    if not 0.0 <= v <= 1.0:
        raise ValueError(
            f"{name}={p} is not a probability in [0,1]. A percentage "
            f"(77.0 for 77%) lands in no calibration bucket and vanishes "
            f"from the report without a word — pass {v/100:.4f} instead.")
    return v


def _num(v):
    """A float, or None when the value is not one. B112.

    The log is six schema generations deep and hand-written records are in
    it. `float(leg["line"])` on a historical `"n/a"` raised ValueError out of
    `unlogged_bet_verdicts` and took down the WHOLE of rec_summary — a report
    that cannot survive one malformed record it is reporting on is worse than
    no report, because it fails at the moment it is needed.
    """
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _legs(b: dict) -> list[dict]:
    """A bet's legs, skipping anything that is not a record. B112."""
    return [l for l in (b.get("legs") or []) if isinstance(l, dict)]


def _norm_event(e) -> str | None:
    """An event id as a comparable string, or None when there isn't one.

    B110. Stored raw, `event_id` broke the count two ways at once: PropLine's
    ids are numeric, so `{"53166", 53166}` is TWO events to a set, and the
    integer `0` is falsy, so a real id read as no id at all. Three games typed
    inconsistently reported as "5+ events" and the bucket flipped from a
    refusal to a confidence claim.
    """
    if e is None:
        return None
    t = str(e).strip()
    return t or None


def _norm_player_local(name) -> str | None:
    """Case- and punctuation-insensitive player key, for comparing two strings
    THIS MODULE WROTE.

    Deliberately not `ff_props.norm_player`. This is not a join across data
    sources — both sides are written by the same session in the same
    conversation, so the only mismatches possible are its own typing
    ("DK Metcalf" vs "D.K. Metcalf"). Importing the real one would put
    `ff_props` — and transitively its own imports — into `ff_betlog`'s
    shipset, which is lesson 41 and the B99/B100 failure, for the file that
    changes most often. A suite check asserts the two still agree on the
    cases that matter, so a divergence fails by name (B68's remedy) rather
    than quietly.
    """
    if not name:
        return None
    return "".join(c for c in str(name).lower() if c.isalnum()) or None


def _bet_independence(bets: list[dict]) -> tuple[int | None, str]:
    """Independent units across SLIPS. B110.

    A slip's game lives on its legs, not on the bet record, so the rec-level
    `_independence` reads the wrong shape here and reported "0 players +
    3 unnamed". The unit for a slip is the set of games it touches: two
    same-game slips on one game are one observation, and a cross-game slip
    is its own set.
    """
    sets, missing = set(), 0
    for b in bets:
        evs = {_norm_event(l.get("event_id")) for l in _legs(b)}
        evs.discard(None)
        if not evs:
            missing += 1
        else:
            sets.add(frozenset(evs))
    if missing == len(bets):
        return None, (f"no event ids recorded, so {len(bets)} slips on one "
                      f"game cannot be told from {len(bets)} on {len(bets)}")
    if missing:
        return None, (f"only {len(bets) - missing} of {len(bets)} slips "
                      f"carry an event id")
    return len(sets), (f"{len(sets)} distinct "
                       f"{'game' if len(sets) == 1 else 'games or game sets'}"
                       f" across {len(bets)} slips")


def _independence(rs: list[dict]) -> tuple[int | None, str]:
    """How many INDEPENDENT observations a set of verdicts holds, or None.

    B107/B110. Verdicts cluster by game: three Baltimore pass-catchers on the
    night both their quarterbacks went to IR are one event, not three samples.

    Returns `(None, why)` when independence CANNOT BE MEASURED, which is a
    third state and not a synonym for "plenty". The first version of this
    returned the player count whenever event coverage was partial or absent,
    and that made the function non-monotone in the worst possible direction:
    five verdicts from ONE game reported `1 independent — TOO CLUSTERED`
    with all five ids present, and `overconfident by 77%` once three of the
    ids were deleted. Strictly less information produced a strictly more
    confident claim. Worse, partial coverage is the NORMAL state for the next
    several weeks, because pre-B107 records have no id and backfilling one
    from a date would be inventing data — so the gate would have been inert
    for exactly the transition it was written for.

    Players are keyed loosely and only ever as a FALLBACK bound: two players
    sharing a name collapse into one, which can only understate independence,
    and unnamed verdicts all collapse together for the same reason. Both
    errors make the gate more cautious, never less.
    """
    evs = [_norm_event(r.get("event_id")) for r in rs]
    carried = sum(1 for e in evs if e)
    keys = [_norm_player_local(r.get("player")) for r in rs]
    # Unnamed verdicts might all be the same player, so they count as one.
    players = len({k for k in keys if k}) + (1 if any(k is None
                                                      for k in keys) else 0)
    if not rs:
        return 0, "no verdicts"
    if carried == 0:
        n = len(rs)
        tail = ("" if n == 1 else
                f", so these {n} could all be one game or {n} separate ones")
        return None, f"no event ids recorded{tail}"
    if carried < len(rs):
        return None, f"only {carried} of {len(rs)} verdicts carry an event id"
    events = len({e for e in evs if e})
    return min(players, events), (
        f"{players} player{'s' if players != 1 else ''} over "
        f"{events} event{'s' if events != 1 else ''}")


def _spread_note(rs: list[dict]) -> str:
    """"N players, M events" — what a count is actually made of."""
    keys = [_norm_player_local(r.get("player")) for r in rs]
    named = len({k for k in keys if k})
    unnamed = sum(1 for k in keys if k is None)
    pl = f"{named} player{'s' if named != 1 else ''}"
    if unnamed:
        pl += f" + {unnamed} unnamed"
    evs = [_norm_event(r.get("event_id")) for r in rs]
    carried = sum(1 for e in evs if e)
    events = len({e for e in evs if e})
    if carried == 0:
        # Say so. Silence here reads as "no clustering", which is the claim
        # nothing measured (B39).
        ev = ", no event ids"
    elif carried == len(evs):
        ev = f", {events} event{'s' if events != 1 else ''}"
    else:
        ev = f", {events}+ events ({carried} of {len(evs)} carry one)"
    return pl + ev


def unlogged_bet_verdicts() -> list[dict]:
    """Bet legs that carry an engine verdict no rec record knows about.

    B108. `log_bet` stores `engine_tier` as a FIELD ON THE LEG, while
    `rec_summary` reads `live_recs()`, which filters `kind == "rec"`. A leg
    bet on the engine's say-so therefore never reaches the engine's own
    scorecard unless `log_edge` was called separately. This is not a cosmetic
    gap: the three legs of slip 7a5f4b8e all carried `engine_tier: PASS` and
    all three lost, so the PASS column read 2/7 (29%) when the honest figure
    was 2/10 (20%) — the omission flattered the model by hiding three
    correct PASSes. Reported rather than silently merged, because a session
    that calls both `log_bet` and `log_edge` for the same leg would otherwise
    be double-counted.
    """
    bets = _apply_grades(_bets())
    recs = live_recs()

    def _key(d, bet_id):
        # B110. `line` and `side` are part of the identity. Without them one
        # rec suppressed EVERY leg for that player and market on the slip —
        # and a ladder (Flowers at 47.5 and 48.5, Bateman at 15.5 and 14.5,
        # which the live log has) is exactly where two legs share both and
        # carry different tiers.
        return (bet_id, _norm_player_local(d.get("player")),
                d.get("market"), _num(d.get("line")),
                (d.get("side") or "").upper())

    # Two separate states, and the message must not merge them (B39): a
    # verdict with no rec at all, and a verdict whose rec exists but was
    # logged before the bet and so carries no bet_id. The documented flow
    # produces the second one, and the first version called it "NOT in this
    # log" and told the session to log it again — which is the double count
    # this function exists to avoid.
    linked = {_key(r, r.get("bet_id")) for r in recs if r.get("bet_id")}
    unlinked = {_key(r, None) for r in recs}
    # B117. `log_edge` records `edge.side` — the side the MODEL prefers — while
    # `log_bet` records the side the slip actually took, and those differ
    # often: 5 of 12 legs in one live round. So a leg can have a verdict in
    # this log for the OPPOSITE side, which is neither missing nor unlinked.
    # It is the engine disagreeing with the bet, and that is the most
    # actionable line on the whole report.
    def _flip(k):
        return k[:4] + ("UNDER" if k[4] == "OVER" else
                        "OVER" if k[4] == "UNDER" else k[4],)
    opposite = {_flip(_key(r, None)) for r in recs}
    out = []
    for b in bets:
        for i, leg in enumerate(_legs(b)):
            # A leg carrying the engine's PROBABILITY is a leg bet on the
            # engine, tier or no tier. Keying only on engine_tier made that
            # leg invisible to the detector built to find invisible legs.
            if not leg.get("engine_tier") \
                    and leg.get("engine_model_p") is None:
                continue
            if _key(leg, b["id"]) in linked:
                continue
            k = _key(leg, None)
            state = ("unlinked" if k in unlinked
                     else "opposite" if k in opposite
                     else "missing")
            out.append({"bet_id": b["id"], "leg_index": i,
                        "state": state,
                        "player": leg.get("player"),
                        "market": leg.get("market"),
                        "line": leg.get("line"),
                        "side": leg.get("side"),
                        "tier": leg.get("engine_tier"),
                        "model_p": leg.get("engine_model_p"),
                        "result": leg.get("result")})
    return out


def _unlogged_note() -> list[str]:
    """The B108 gap, as report lines. Empty when there is no gap.

    Two states, reported separately (B110). MISSING means no rec record
    exists for that leg at all, so every figure in this report is computed on
    an incomplete set and the remedy is to call `log_edge`. UNLINKED means
    the verdict IS here and IS counted — it was logged before the bet
    existed, which is what the documented flow produces — and the only thing
    absent is the `bet_id` tying the two together. Merging them told a
    session to re-log a verdict it had already logged, which is the double
    count this exists to prevent.
    """
    gap = unlogged_bet_verdicts()
    if not gap:
        return []
    missing = [g for g in gap if g["state"] == "missing"]
    unlinked = [g for g in gap if g["state"] == "unlinked"]
    opposite = [g for g in gap if g["state"] == "opposite"]

    def _who(g):
        bits = [x for x in (g["player"], g["market"]) if x]
        if g.get("line") is not None:
            bits.append(f"{g['side'] or ''} {g['line']}".strip())
        return " ".join(bits) or \
            f"(unnamed leg {g['leg_index']} of bet {g['bet_id']})"

    L = []
    if missing:
        graded = [g for g in missing if g["result"] in ("WIN", "LOSS")]
        L += ["",
              f"  !! {len(missing)} bet leg"
              f"{'s' if len(missing) != 1 else ''} "
              f"{'carry' if len(missing) != 1 else 'carries'} an engine "
              f"verdict that is NOT in this log",
              "     (log_bet stores engine_tier on the leg; this scorecard "
              "reads log_edge records)"]
        for g in missing:
            L.append(f"       {g['tier'] or '(no tier)':<10} {_who(g)}"
                     f"  {g['result'] or 'ungraded'}")
        if graded:
            L.append(f"     {len(graded)} of them already graded, so every "
                     "figure in this report is")
            L.append("     computed on an incomplete set. Call log_edge() "
                     "for slip legs too.")
    if opposite:
        # B117. Loud, and first, because this is not a bookkeeping gap — it
        # says the slip took the side the model likes LESS.
        L += ["",
              f"  *** {len(opposite)} bet leg"
              f"{'s' if len(opposite) != 1 else ''} "
              f"{'take' if len(opposite) != 1 else 'takes'} the side the "
              f"ENGINE DID NOT PREFER",
              "     (log_edge records the model's own side; these legs are "
              "the other one. The verdict IS",
              "      in this log and IS counted — a CLEAR verdict means the "
              "veto found nothing wrong",
              "      with the leg, NOT that the model likes the side you "
              "bet.)"]
        for g in opposite:
            L.append(f"       {g['tier'] or '(no tier)':<10} {_who(g)}"
                     f"   model preferred the other side")
    if unlinked:
        L += ["",
              f"  note: {len(unlinked)} bet leg"
              f"{'s' if len(unlinked) != 1 else ''} "
              f"{'have' if len(unlinked) != 1 else 'has'} a verdict in this "
              "log that is not linked to the bet",
              "     (counted in every figure below — pass bet_id= and "
              "acted_on=True to log_edge to link it;",
              "      do NOT log it again, that double-counts)"]
        for g in unlinked:
            L.append(f"       {g['tier'] or '(no tier)':<10} {_who(g)}")
    return L


def rec_summary() -> str:
    """How the ENGINE did — on every verdict, not just the ones that were bet.

    This is the half that answers "is the model adding anything". Agreement
    rate and engine accuracy are reported separately, because a model graded
    only on the calls Dustin agreed with is graded on his filter, not its own.
    """
    recs = _real(live_recs())
    if not recs:
        # The gap still has to show here. No recs at all, with bets carrying
        # engine verdicts, is the worst version of B108, not an exemption.
        return "\n".join(
            ["No engine recommendations logged yet.",
             "  Log EVERY verdict with log_edge(), including PASS. Logging",
             "  only the ones you bet measures your filter, not the model."]
            + _unlogged_note())

    _tests = [r for r in live_recs() if is_test_record(r)]
    _tn = ([f"  note: {len(_tests)} TEST record"
            f"{'s' if len(_tests) != 1 else ''} in the log, excluded from "
            f"every figure below",
            "     (flagged with is_test=True; delete them from Drive when "
            "you are done with them)"] if _tests else [])
    L = ([f"ENGINE LOG — {len(recs)} verdicts"] + _tn
         + _unlogged_note())
    tiers: dict[str, list[dict]] = {}
    for r in recs:
        tiers.setdefault(r.get("tier") or "(no tier)", []).append(r)

    L.append("")
    L.append(f"  {'tier':<12}{'n':>5}{'acted':>8}{'graded':>8}{'hit':>8}")
    for tier, rs in sorted(tiers.items(), key=lambda kv: -len(kv[1])):
        g = [r for r in rs if r.get("result") in ("WIN", "LOSS")]
        acted = sum(1 for r in rs if r.get("acted_on"))
        hit = (f"{sum(1 for r in g if r['result']=='WIN')/len(g):.0%}"
               if g else "—")
        L.append(f"  {tier:<12}{len(rs):>5}{acted:>8}{len(g):>8}{hit:>8}"
                 f"   {_spread_note(g) if g else ''}")

    # The hit column is a raw tally, deliberately ungated — `graded` and the
    # spread of players and events sit beside every figure, so nothing in the
    # table claims to be a rate. Everything below it that says what a number
    # MEANS is gated instead (B107).
    graded = [r for r in recs if r.get("result") in ("WIN", "LOSS")]
    if graded:
        # Calibration: does a 70% call win 70% of the time? This is the only
        # question that matters about a probability model, and it is the one
        # a bets-only log cannot answer.
        L.append("")
        L.append("  calibration (model probability vs realised)")
        buckets = [(0.0, .4), (.4, .55), (.55, .7), (.7, .85), (.85, 1.0)]
        placed = 0
        # B112. `_check_prob` guards the WRITE path only; records already in
        # the log predate it, so the read path has to cope with a missing or
        # out-of-range model_p instead of raising mid-report.
        usable = [r for r in graded
                  if _num(r.get("model_p")) is not None
                  and 0.0 <= _num(r["model_p"]) <= 1.0]
        unusable = len(graded) - len(usable)
        # B107. `n` is a count of VERDICTS, and verdicts cluster hard. A live
        # example: a 0-for-4 bucket read as four failures, and three of the
        # four were Baltimore pass-catchers on the night Lamar Jackson and
        # Huntley both went to IR — one event driving three legs. Across the
        # whole graded set, 9 verdicts covered 6 distinct players, with three
        # players appearing at two lines each. Printing `n=4` next to
        # "overconfident by 77%" invites reading one game as four
        # observations, so the independent counts are printed beside it and
        # a bucket that cannot support a verdict says so instead of giving
        # one.
        for lo, hi in buckets:
            # The top bucket must INCLUDE 1.0, or a verdict at exactly 1.0
            # is counted in the header and the tier table and appears in no
            # bucket, with nothing saying so.
            b = [r for r in usable
                 if lo <= r["model_p"] < hi
                 or (hi == 1.0 and r["model_p"] == 1.0)]
            placed += len(b)
            if not b:
                continue
            exp = float(np.mean([r["model_p"] for r in b]))
            act = sum(1 for r in b if r["result"] == "WIN") / len(b)
            spread = f"n={len(b)} over {_spread_note(b)}"
            units, why = _independence(b)
            if units is None:
                L.append(f"    {lo:.0%}-{hi:.0%}  {spread}  said {exp:.0%}  "
                         f"went {act:.0%}  — CANNOT BE READ: {why}")
            elif units < MIN_INDEPENDENT_FOR_CALIBRATION:
                L.append(f"    {lo:.0%}-{hi:.0%}  {spread}  said {exp:.0%}  "
                         f"went {act:.0%}  — TOO CLUSTERED TO READ "
                         f"({units} independent, "
                         f"need {MIN_INDEPENDENT_FOR_CALIBRATION})")
            else:
                L.append(f"    {lo:.0%}-{hi:.0%}  {spread}  "
                         f"said {exp:.0%}  went {act:.0%}  "
                         + ("calibrated (no gap at this rounding)"
                            if round(abs(exp - act), 2) == 0 else
                            f"{'over' if exp > act else 'under'}confident "
                            f"by {abs(exp-act):.0%}"))
        # Reconcile, so the section can report that it could not measure
        # rather than quietly showing less than it was given (lesson 13).
        if unusable:
            L.append(f"    !! {unusable} of {len(graded)} graded verdicts "
                     f"have no usable model_p and are in NO bucket")
        if placed != len(usable):
            L.append(f"    !! {len(usable) - placed} of {len(usable)} graded "
                     f"verdicts fell in NO bucket — this is a bug, not data")
        passes = [r for r in graded if r.get("tier") == "PASS"]
        if passes:
            w = sum(1 for r in passes if r["result"] == "WIN") / len(passes)
            # B107 applies here too. This line ends in a sentence telling the
            # reader what the rate MEANS for the guard, which is a verdict on
            # the same clustered handful the buckets above refuse to read.
            n_ind, why = _independence(passes)
            L.append("")
            L.append(f"  PASSes that would have won: {w:.0%} of {len(passes)}"
                     f"  ({_spread_note(passes)})")
            if n_ind is None or n_ind < MIN_INDEPENDENT_FOR_CALIBRATION:
                L.append(f"  NOT READABLE YET ({why}) — this does not say "
                         "anything about the guard.")
            else:
                L.append("  A PASS rate near the market's implied probability "
                         "means")
                L.append("  the vetoes are not costing anything. Well above "
                         "it means")
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
        f"  {pull_state()}",
    ])
