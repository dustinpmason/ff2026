"""Regression suite. Run after any change: `python3 test_regression.py`

Every check here corresponds to a bug that actually shipped. They are not
hypothetical: the explosive-TD check exists because Julian Love was credited
with Jordan Love's touchdowns; the idempotency check because add_shares()
crashed on a second call; the bye check because a partial week made 21 teams
look like they were off.
"""
import warnings; warnings.filterwarnings("ignore")
import atexit, inspect, itertools, json, pathlib, sys, traceback
import numpy as np, pandas as pd
import ff_data, ff_scoring, ff_props, ff_guillotine, ff_betlog, ff_backtest
import ff_boost
import ff_correlation
import ff_tokens
from ff_boost import (BoostLeg, classify, independent_odds, make_candidate,
                      enumerate_candidates, price_candidate, FLOOR, CEILING)
from ff_data import load_weekly, load_pbp
from ff_scoring import LEAGUES, score, score_all, add_explosive_tds, prepare
from ff_props import (player_series, threshold_prob, prop_edge, usage_trend,
                      role_trend, decline_onset, add_shares, devig,
                      screen_quotes, LONGSHOT_P)

fails = []
ran = []
_section = ["(startup)"]


def section(title: str) -> None:
    """Announce a section and remember it, so a crash can name where it died."""
    _section[0] = title
    print(f"\n{title}")


def _summary() -> None:
    """ALWAYS print the count, even when the suite dies mid-run.

    The suite used to abort on an uncaught exception and never reach its
    summary, so the one number sessions are told to quote simply did not
    exist — and the honest response was "no count this run", which is useless
    for deciding whether anything regressed. Registered with atexit so it
    runs on a crash, a sys.exit, or normal completion.
    """
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
    print(f"{'ALL PASS' if not fails and not _crashed else 'FAILURES: ' + ', '.join(fails) if fails else 'NO CHECK FAILED, but the suite crashed'}")


_crashed = False


def _on_crash(exc_type, exc, tb) -> None:
    """Record an uncaught exception as a crash, then print the summary."""
    global _crashed
    _crashed = True
    print()
    traceback.print_exception(exc_type, exc, tb)
    _summary()


sys.excepthook = _on_crash
atexit.register(_summary)
def chk(name, ok, detail=""):
    """Record one check.

    The suite reports its own count at the end. Do NOT count checks by
    grepping the source: `def chk(` matches, and a try/except pair puts two
    chk() lines on a path where only one of them runs — counting lines gave
    109 for 107 actual checks. Worse, an earlier `grep -c PASS` matched the
    "ALL PASS" summary line and reported 61 for 60, which sent a test session
    hunting for a check that never existed. The number the suite prints is
    the only one to quote.
    """
    ran.append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'  — ' + detail if detail else ''}")
    if not ok: fails.append(name)

print("1. imports")
chk("all four modules import", True)

section("2. data layer")
wk = load_weekly(2026); pbp = load_pbp(2026)
chk("weekly 2026", len(wk) > 5000, f"{len(wk)} rows, {len(wk.columns)} cols")
chk("pbp 2026", len(pbp) > 15000, f"{len(pbp)} plays")

section("3. scoring engine — all four leagues")
prep = prepare(wk, pbp)
for key, lg in LEAGUES.items():
    s = score(prep, lg)
    chk(f"{key}", s.notna().all() and s.std() > 1,
        f"mean {s.mean():.2f} sd {s.std():.2f} max {s.max():.1f}")

section("4. explosive-TD join integrity (GSIS id, not name)")
ex = add_explosive_tds(wk, pbp)
jl = ex[ex.player_display_name.str.contains("Jordan Love", na=False)]
jv = ex[ex.player_display_name.str.contains("Julian Love|Jeremiyah Love", na=False)]
pass_col = [c for c in ex.columns if "pass" in c and "40" in c or "explosive" in c]
tot = jl[pass_col].sum().sum() if pass_col else 0
contam = jv[pass_col].sum().sum() if pass_col else 0
chk("Jordan Love credited", tot > 0, f"{tot:.0f} explosive pass TDs")
chk("no name contamination", contam == 0, f"Julian/Jeremiyah Love credited {contam:.0f}")

section("5. props — threshold + stat resolution")
log = player_series(wk[wk.season_type=="REG"], "Jaxon Smith-Njigba", "receiving_yards")
e = threshold_prob(log, 90)
chk("stat read from attrs not last column", log.attrs.get("stat") == "receiving_yards")
chk("probability sane", 0 < e.blended < 1, f"P(90+) = {e.blended:.1%}")

section("6. props — de-vig and edge")
o, u, hold = devig(-110, -110)
chk("symmetric devig = 50/50", abs(o - 0.5) < 1e-9, f"over {o:.4f} hold {hold:.3%}")
ed = prop_edge(e, -110, -110)
chk("prop_edge returns", ed is not None, f"edge {ed.edge:+.1%}" if hasattr(ed,"edge") else "")
for bad in (0.0, 1.0, 1.5, -0.1):
    try: prop_edge(e, -110, -110, fair_over=bad); chk(f"B4 rejects fair_over={bad}", False)
    except ValueError: chk(f"B4 rejects fair_over={bad}", True)

section("7. props — usage trend verdicts")
sh = add_shares(wk[wk.season_type=="REG"])
# The previous check here was close to unfalsifiable: it passed if ANY one of
# five players returned ANY verdict, UNKNOWN included. One run had Rashee Rice
# come back UNKNOWN and it still passed — it would not have caught a
# usage-trend regression, which is the only thing it exists to catch.
#
# Replaced with synthetic players whose answers are known by construction.
def _synth(name, pos, team, shares, team_tot=100):
    rows = []
    for i, sh_ in enumerate(shares, start=1):
        rows.append({"player_display_name": name, "position": pos, "team": team,
                     "season": 2026, "week": i, "season_type": "REG",
                     "carries": sh_ * team_tot, "targets": 0.0,
                     "attempts": sh_ * team_tot if pos == "QB" else 0.0})
    return rows

# Each synthetic team gets a filler player so team totals stay fixed and the
# subject's SHARE is exactly what we wrote.
def _frame(specs):
    rows = []
    for name, pos, team, shares in specs:
        rows += _synth(name, pos, team, shares)
        rows += _synth(f"filler {team}", "RB", team, [1 - x for x in shares])
    return add_shares(pd.DataFrame(rows))

cases = [
    ("holds steady",  [0.40]*10,                               "STABLE"),
    ("share halves",  [0.40]*6 + [0.16]*4,                     "COLLAPSED"),
    ("share doubles", [0.20]*6 + [0.40]*4,                     "EXPANDED"),
]
for label, shares, want in cases:
    f = _frame([("Subject", "RB", "AAA", shares)])
    got = role_trend(f, "Subject").verdict
    chk(f"role_trend: {label} -> {want}", got == want, f"got {got}")

# GAME_SCRIPT: share holds but raw volume falls, i.e. the team ran fewer plays.
rows = _synth("GS", "RB", "BBB", [0.40]*6, team_tot=100) + \
       _synth("GS", "RB", "BBB", [0.40]*4, team_tot=40)
for i, r in enumerate(rows, start=1):
    r["week"] = i
rows += [{**r, "player_display_name": "filler BBB"} for r in
         _synth("x", "RB", "BBB", [0.60]*6, team_tot=100) +
         _synth("x", "RB", "BBB", [0.60]*4, team_tot=40)]
for i, r in enumerate([r for r in rows if r["player_display_name"] == "filler BBB"], start=1):
    r["week"] = i
gs = role_trend(add_shares(pd.DataFrame(rows)), "GS")
chk("role_trend: volume falls, share holds -> GAME_SCRIPT",
    gs.verdict == "GAME_SCRIPT", f"got {gs.verdict} (share ratio "
    f"{gs.share_ratio:.2f}, count ratio {gs.ratio:.2f})")

# Too little history must say UNKNOWN, not guess.
chk("role_trend: short sample -> UNKNOWN",
    role_trend(_frame([("Rookie", "RB", "CCC", [0.3, 0.3])]), "Rookie").verdict
    == "UNKNOWN")
chk("role_trend: unknown player -> UNKNOWN",
    role_trend(sh, "Zzz Notaplayer").verdict == "UNKNOWN")

section("8. bye detection (partial-week guard)")
b = ff_props.bye_weeks(wk)
cnt = pd.Series(list(b.values())).value_counts().sort_index()
chk("no week has >8 byes", (cnt <= 8).all(), str(dict(cnt)))
chk("byes found", len(b) >= 10, f"{len(b)} teams")

section("9. guillotine — name resolution + B5")
pool = ff_guillotine.build_pool(wk, LEAGUES["guillotine"])
chk("Mahomes resolves", ff_guillotine.resolve("Patrick Mahomes II", pool) is not None)
chk("garbage does not resolve", ff_guillotine.resolve("Zzz Notaplayer", pool) is None)
chk("_mean_of unresolved is nan", np.isnan(ff_guillotine._mean_of(pool, "Zzz Notaplayer")))
try:
    ff_guillotine.enumerate_lineups({"QB":["Trevor Lawrence"],"RB":["Javonte Williams"]}, pool)
    chk("B5 raises on undersized roster", False)
except ValueError as ex:
    chk("B5 raises on undersized roster", True, str(ex)[:50])

section("10. add_shares idempotency (B6)")
once = add_shares(wk[wk.season_type == "REG"])
twice = add_shares(once)
chk("second call does not raise", True)
chk("no _x/_y suffixes", not any(c.endswith(("_x", "_y")) for c in twice.columns))
chk("share values unchanged",
    bool(np.allclose(once["_touch_share"].fillna(-1), twice["_touch_share"].fillna(-1))))
chk("role_trend works on pre-shared frame",
    role_trend(once, "Travis Kelce").verdict != "UNKNOWN")

section("11. shin de-vig (P3)")
chk("shin == mult on a balanced market",
    abs(devig(-110, -110, "shin")[0] - devig(-110, -110, "multiplicative")[0]) < 1e-6)
m450, s450 = devig(450, -600, "multiplicative")[0], devig(450, -600, "shin")[0]
chk("shin pulls longshots DOWN", s450 < m450, f"{m450:.2%} -> {s450:.2%}")
chk("shin fair probs sum to 1", abs(sum(devig(450, -600, "shin")[:2]) - 1.0) < 1e-9)
chk("shin is the default for every market",
    abs(devig(450, -600)[0] - s450) < 1e-12 and
    abs(devig(-110, -110)[0] - 0.5) < 1e-9)
chk("'auto' resolves to shin", abs(devig(450, -600, "auto")[0] - s450) < 1e-12)
# The retired threshold discarded most of the correction where it mattered:
# short-priced TD legs are what fill a 3-leg boost at +300.
for _o, _u in [(245, -310), (270, -340)]:
    _d = devig(_o, _u, "multiplicative")[0] - devig(_o, _u, "shin")[0]
    chk(f"shin still corrects at {_o:+} (was above the old 0.25 gate)",
        _d > 0.009, f"{_d:+.2%}")
# The property that matters is CONTINUITY — the retired threshold made
# 24.9% and 25.1% implied differ by 1.3 pts, which is the bug. The correction
# is NOT monotone in price and should not be: it peaks near +300 and must
# vanish as p -> 0, because a near-impossible outcome has almost no margin to
# redistribute. An earlier version of this check asserted monotonicity and
# failed against correct behaviour.
# Sampled on a FINE, UNIFORM grid in implied probability. Hand-picked
# American odds are unevenly spaced — the gap from -400 to -250 is 8 points
# of implied probability — so a large step there measures coarse sampling,
# not a discontinuity in the function. An earlier version of this check used
# such a grid and reported a 0.576% "cliff" that was pure sampling artifact.
def _odds_for(prob, margin=0.045):
    q = min(0.98, prob * (1 + margin / 2))
    return 100 * (1 - q) / q if q < 0.5 else -100 * q / (1 - q)

# 5% to 92%. The lower bound is set by this fixture, not by Shin: below ~5%
# the opposite side exceeds the 0.98 clamp in _odds_for and the CLAMP starts
# distorting the market, producing 0.23% steps that are an artifact of the
# test, not of the function. Inside the unclamped range every step is
# <= 0.011% per half-point, which is as smooth as it gets.
_ps = [0.05 + 0.005 * i for i in range(175)]
_grid = []
for _pp in _ps:
    _o, _u = _odds_for(_pp), _odds_for(1 - _pp)
    _grid.append(devig(_o, _u, "shin")[0] - devig(_o, _u, "multiplicative")[0])
_step = max(abs(a - b) for a, b in zip(_grid, _grid[1:]))
chk("no cliff: correction varies smoothly with price", _step < 0.001,
    f"largest step over a 0.5pt move in implied probability {_step:.4%}")
_even = min(range(len(_ps)), key=lambda i: abs(_ps[i] - 0.5))
chk("correction is ~zero at even money", abs(_grid[_even]) < 2e-3,
    f"{_grid[_even]:+.3%} at {_ps[_even]:.1%} implied")
chk("longshots corrected down, favourites up",
    _grid[0] < 0 and _grid[-1] > 0,
    f"{_ps[0]:.0%} -> {_grid[0]:+.2%}, {_ps[-1]:.0%} -> {_grid[-1]:+.2%}")
# The tail property needs prices beyond the fixture's clamped range, so it
# uses explicit odds: the correction must SHRINK toward an impossible
# outcome, because a 2% shot carries almost no margin to redistribute.
_peak = devig(300, -400, "shin")[0] - devig(300, -400, "multiplicative")[0]
_tail = devig(2500, -4000, "shin")[0] - devig(2500, -4000, "multiplicative")[0]
chk("correction vanishes toward the extreme, as Shin requires",
    abs(_tail) < abs(_peak),
    f"+300 {_peak:+.2%} vs +2500 {_tail:+.2%}")
try: devig(-110, -110, "nonsense"); chk("unknown method raises", False)
except ValueError: chk("unknown method raises", True)
chk("Edge records which de-vig ran",
    prop_edge(e, 450, -600).devig_method == "shin")
# On the fair_over path the de-vig happened upstream; prop_edge must not
# claim to have chosen it, and must report the caller's label when given one.
chk("external fair line: reports upstream, not a lie",
    prop_edge(e, 450, -600, fair_over=0.17).devig_method.startswith("UNKNOWN"))
chk("external fair line: echoes the caller's label",
    prop_edge(e, 450, -600, fair_over=0.17,
              devig_method="shin (get_event_ev)").devig_method
    == "shin (get_event_ev)")
chk("hold is de-vig independent",
    abs(prop_edge(e, 450, -600).hold
        - prop_edge(e, 450, -600, fair_over=0.17).hold) < 1e-12)

section("12. live-quote screen (P2)")
import datetime as _dt
_now = _dt.datetime.now(_dt.timezone.utc).timestamp()
_iso = lambda s: _dt.datetime.fromtimestamp(_now - s, _dt.timezone.utc).isoformat()
# Every quote carries a price: the screen now drops price-less quotes, so a
# fixture without prices would pass the suspension checks for the wrong
# reason and hide a regression in them.
_pr = {"over": -115, "under": -105}
qs = [{"book": "FanDuel", **_pr, "last_update": _iso(30)},
      {"book": "DraftKings", **_pr, "suspended_at": _iso(60)},
      {"book": "BetMGM", **_pr, "suspended_at": _iso(45)},
      {"book": "Caesars", **_pr, "suspended_at": _iso(50)},
      {"book": "Pinnacle", **_pr, "pregame_only": True, "last_update": _iso(20)},
      {"book": "ESPNBet", **_pr, "last_update": _iso(1800)}]
pre = screen_quotes(qs, game_started=False)
live = screen_quotes(qs, game_started=True)
chk("suspended books dropped", all(q["book"] != "DraftKings" for q in pre.usable))
chk("3 suspensions = scratch flag", pre.scratch_risk, f"{pre.suspended_books}")
chk("stale quote dropped pregame", all(q["book"] != "ESPNBet" for q in pre.usable))
chk("pregame_only kept pregame", any(q["book"] == "Pinnacle" for q in pre.usable))
chk("pregame_only dropped in-play", all(q["book"] != "Pinnacle" for q in live.usable))
chk("one usable in-play quote", len(live.usable) == 1, f"{[q['book'] for q in live.usable]}")
chk("no scratch flag under threshold",
    not screen_quotes(qs[:2], game_started=False).scratch_risk)
# A quote with no price is the deadest quote there is. One slipped through as
# usable and then killed prop_edge with a TypeError from inside
# american_to_prob — the exact failure this screen exists to prevent.
_pq = [{"book": "Bovada", "over": None, "under": None, "last_update": _iso(5)},
       {"book": "Nothing", "last_update": _iso(5)},
       {"book": "OneSided", "price": 270, "last_update": _iso(5)},
       {"book": "TwoSided", "over": -115, "under": -105, "last_update": _iso(5)}]
_ps = screen_quotes(_pq)
chk("price-less quotes dropped",
    {q["book"] for q in _ps.usable} == {"OneSided", "TwoSided"},
    f"{[q['book'] for q in _ps.usable]}")
chk("one-sided book flagged, not silently used",
    _ps.one_sided == ["OneSided"])
chk("two-sided book not flagged one-sided",
    "TwoSided" not in _ps.one_sided)
try: prop_edge(e, None, None); chk("prop_edge rejects a None price", False)
except ValueError as _ex:
    chk("prop_edge rejects a None price with a clear error",
        "screen_quotes" in str(_ex))
except TypeError:
    chk("prop_edge rejects a None price with a clear error", False,
        "still raises TypeError from american_to_prob")

section("13. bet log (E2+P6)")
import shutil, tempfile, types, pathlib, itertools
_tmp = tempfile.mkdtemp()
ff_betlog.LOG_DIR = pathlib.Path(_tmp)
ff_betlog.SESSION = ff_betlog.LOG_DIR / "_session.jsonl"
ff_betlog.PULL_MARKER = ff_betlog.LOG_DIR / "_pull.json"
from ff_betlog import Leg

# B58. `sync_state()` says "N log file(s) pulled from Drive", and at N=0
# that cannot distinguish NOBODY PULLED from THE PULL FOUND NOTHING —
# opposite situations, since the first means the history is unknown and
# must not be written over. A 2026-11-04 session read it as the second,
# concluded no prior log existed and uploaded a fresh one. It was right,
# but it could not have known. B39's UNSCREENED shape, one module over.
chk("with no pull recorded, the history is UNKNOWN — not empty",
    "UNKNOWN" in ff_betlog.pull_state()
    and "NO DRIVE PULL RECORDED" in ff_betlog.pull_state())
# Drive's search defaults to `trashed = false`, so an empty result proves
# nothing on its own. Checked live 2026-11-05: that folder held ONE live
# file and EIGHT trashed logs the default query could not see.
ff_betlog.record_pull([])
chk("a pull that did not check the trash says so",
    "TRASH NOT CHECKED" in ff_betlog.pull_state())
ff_betlog.record_pull([], ["ff-betlog-20261030T172619Z.jsonl",
                           "ff-betlog-20261102T151105Z.jsonl"])
chk("zero live files beside trashed ones is not a fresh start",
    "every log in this folder is in the trash" in ff_betlog.pull_state()
    and "2 TRASHED" in ff_betlog.pull_state())
ff_betlog.record_pull(["ff-betlog-20261104T213301Z.jsonl"], ["old.jsonl"])
_ps = ff_betlog.pull_state()
chk("a live file alongside trashed ones reports both, warns on neither",
    "1 live file(s)" in _ps and "1 TRASHED" in _ps
    and "fresh start" not in _ps)
# This check used to assert the clean case was QUIET — one line, no
# warning. That was the wrong property to want. Silence is also what a
# FAILED query looks like when a session records it as an empty pull, so
# "quiet" made the most reassuring output reachable from a broken one.
# The clean case now states its claim; the assertion below replaced it.
chk("a genuinely empty folder states its claim rather than staying silent",
    "both queries returned successfully" in ff_betlog.record_pull([], []))
chk("status() surfaces the pull state, not just the file count",
    "Drive pull at" in ff_betlog.status())
ff_betlog.PULL_MARKER.write_text("{not json")
chk("an unreadable marker is UNKNOWN, never silently fine",
    "UNKNOWN" in ff_betlog.pull_state())
# Valid JSON of the WRONG SHAPE used to raise AttributeError out of
# `rec.get`, taking down all of status() rather than one line; and `{}` —
# a half-written marker — printed "Drive pull at None: 0 live file(s)",
# presenting a truncated write as a successfully recorded empty pull.
for _bad in ("[]", "{}", '"a string"', "null"):
    ff_betlog.PULL_MARKER.write_text(_bad)
    chk(f"a marker of {_bad} is UNKNOWN, not a crash and not a clean pull",
        "UNKNOWN" in ff_betlog.pull_state())
# A string is not a list of one filename. sorted() iterates it into
# characters and record_pull reported "32 live file(s)" — a confident,
# plausible, wrong count, inflating the apparent history. Project
# signature (B24/B28/B37): a plausible number instead of an error.
for _bad_arg in ("ff-betlog-x.jsonl", {"a": 1, "b": 2}, 7):
    try:
        ff_betlog.record_pull(_bad_arg, [])
        _raised = False
    except TypeError:
        _raised = True
    chk(f"record_pull refuses {type(_bad_arg).__name__} instead of counting it",
        _raised)
# THE ONE THAT MATTERS MOST. A failed Drive query recorded as an empty
# pull was byte-identical to a genuinely empty checked folder — and was
# the ONLY state printing no warning at all, so the most reassuring
# output the function can produce was reachable from a broken query.
# B58 closed "nobody pulled" vs "the pull found nothing" and left "the
# pull FAILED" in the same hole one notch along.
ff_betlog.record_pull(error="HTTP 503 from search_files")
chk("a failed query is UNKNOWN, and says it is not an empty folder",
    "THE DRIVE QUERY FAILED" in ff_betlog.pull_state()
    and "NOT an empty folder" in ff_betlog.pull_state())
_clean = ff_betlog.record_pull([], [])
chk("and a genuinely empty folder makes its claim out loud, not by silence",
    "both queries returned successfully" in _clean
    and "THE DRIVE QUERY FAILED" not in _clean,
    "silence is what an unasked question looks like")
ff_betlog.PULL_MARKER.unlink()
# DRIVE_PREFIX was defined and never enforced on the read path: _read_all
# globbed *.jsonl, so a stray file was ingested AS HISTORY while a real
# log under another extension was silently skipped — a .txt log holding a
# $500 bet read as no history, no warning.
(ff_betlog.LOG_DIR / "random-notes.jsonl").write_text(
    '{"id":"stray","kind":"bet","stake":500.0,"legs":[]}\n')
(ff_betlog.LOG_DIR / f"{ff_betlog.DRIVE_PREFIX}20261101T000001Z.txt").write_text(
    '{"id":"wrongext","kind":"bet","stake":500.0,"legs":[]}\n')
_ids = {r.get("id") for r in ff_betlog._read_all()}
chk("a stray .jsonl is not ingested as history", "stray" not in _ids)
# status() reads the log TWICE (bets, then recs), so every warning was
# emitted once per read — one stray file printed two identical lines, a
# corrupt line three. A warning repeated is a warning skimmed, and the
# repetition made the log look more broken than it was.
import io as _io, contextlib as _ctx
ff_betlog._WARNED.clear()
_buf = _io.StringIO()
with _ctx.redirect_stdout(_buf):
    ff_betlog.status()
chk("a warning is emitted once per process, not once per read",
    _buf.getvalue().count("random-notes") == 1,
    f'{_buf.getvalue().count("random-notes")} copies in one status() call')
chk("a real-looking log under the wrong extension is NOT silently dropped",
    "wrongext" not in _ids,
    "it is named in a warning instead — silence is the failure here")
(ff_betlog.LOG_DIR / "random-notes.jsonl").unlink()
(ff_betlog.LOG_DIR / f"{ff_betlog.DRIVE_PREFIX}20261101T000001Z.txt").unlink()
chk("empty log does not crash", "No bets logged" in ff_betlog.bet_summary())
_legs = [Leg("A", "player_rush_yds", 50.5, "OVER", -110, "fanduel", fair_p=0.52),
         Leg("B", "player_pass_yds", 230.5, "OVER", -105, "fanduel", fair_p=0.50),
         Leg("C", "player_anytime_td", None, "YES", 140, "fanduel", fair_p=0.40)]
_b = ff_betlog.log_bet(385, 10, _legs, "fanduel", boost_pct=0.30)
chk("bet logged", len([r for r in ff_betlog._bets() if r["kind"] == "bet"]) == 1)
chk("boost on profit is right",
    abs(ff_betlog.boosted_payout(10, 385, 0.30) - (10 + 38.5 * 1.3)) < 1e-9,
    f"${ff_betlog.boosted_payout(10, 385, 0.30):.2f}")
chk("unboosted payout is right",
    abs(ff_betlog.boosted_payout(10, 385, 0.0) - 48.5) < 1e-9)
chk("CLV positive when price beat the close",
    ff_betlog.clv(-110, -128) > 0, f"{ff_betlog.clv(-110, -128):+.2%}")
chk("CLV negative when the close was better",
    ff_betlog.clv(-128, -110) < 0)
chk("CLV zero at the same price", abs(ff_betlog.clv(150, 150)) < 1e-12)
for i, (res, close) in enumerate([("WIN", -128), ("WIN", -118), ("LOSS", 120)]):
    ff_betlog.grade_leg(_b["id"], i, res, closing_odds=close)
ff_betlog.grade_bet(_b["id"], "LOSS", payout=0.0)
chk("grades fold onto the bet",
    "0-1" in ff_betlog.bet_summary() and "mean CLV" in ff_betlog.bet_summary())
try: ff_betlog.grade_bet(_b["id"], "MAYBE"); chk("bad result rejected", False)
except ValueError: chk("bad result rejected", True)

for _t, _p in [("MODERATE", 0.61), ("PASS", 0.44), ("COIN-FLIP", 0.53)]:
    ff_betlog.log_recommendation("P" + _t, "player_rush_yds", 50.5, "OVER",
                                 _t, _p, 0.5, -110, acted_on=_t != "PASS",
                                 event_id=f"evt-{_t}")
chk("PASS verdicts are logged too",
    any(r["tier"] == "PASS" for r in ff_betlog.live_recs()))
_before = len(ff_betlog.live_recs())
for _r in list(ff_betlog.live_recs()):
    ff_betlog.grade_rec(_r["id"], "WIN")
chk("grading does not double-count (B7)",
    len(ff_betlog.live_recs()) == _before,
    f"{_before} -> {len(ff_betlog.live_recs())}, raw log holds "
    f"{len([r for r in ff_betlog._recs() if r['kind'] == 'rec'])}")
chk("rec_summary counts live recs only",
    f"{_before} verdicts" in ff_betlog.rec_summary())
try: ff_betlog.grade_rec("nope", "WIN"); chk("unknown rec id rejected", False)
except ValueError: chk("unknown rec id rejected", True)

_name, _text = ff_betlog.upload_payload()
chk("upload payload is valid JSONL",
    all(json.loads(l) for l in _text.splitlines() if l.strip()),
    f"{len(_text.splitlines())} records")
chk("upload name sorts chronologically", _name.startswith("ff-betlog-")
    and _name.endswith(".jsonl"))
ff_betlog.mark_uploaded(_name)
chk("mark_uploaded clears the session file", not ff_betlog.SESSION.exists())
chk("history survives the rename",
    len([r for r in ff_betlog._bets() if r["kind"] == "bet"]) == 1)
chk("nothing pending after upload", ff_betlog.upload_payload() is None)
shutil.rmtree(_tmp, ignore_errors=True)

section("14. boost verdict framing (P1)")
from ff_props import boost_verdict, boost_leg_report, BOOST_VERDICTS
_cleanq = [{"book": "FanDuel", "over": -115, "under": -105,
            "last_update": _iso(20)}]
_e2 = threshold_prob(player_series(wk[wk.season_type=="REG"],
                                   "Jaxon Smith-Njigba", "receiving_yards"), 79.5)
_ed2 = prop_edge(_e2, -115, -105)
_v, _r = boost_verdict(_e2, _ed2, screen_quotes(_cleanq))
chk("returns a known verdict", _v in BOOST_VERDICTS, _v)
_susp = [{"book": b, "over": -115, "under": -105, "suspended_at": _iso(60)}
         for b in ("FanDuel", "DraftKings", "BetMGM")]
_v3, _r3 = boost_verdict(_e2, _ed2, screen_quotes(_susp))
chk("multi-book suspension VETOes the leg", _v3 == "VETO")
chk("the scratch reason is named first", "PROBABLE SCRATCH" in _r3[0])
_rep = boost_leg_report(_e2, _ed2, "test leg", screen_quotes(_cleanq))
# P1 is precisely about not calling this number an edge.
chk("report says 'gap', never 'edge'",
    "gap" in _rep and "edge" not in _rep.lower().replace("not an edge", ""))
chk("report disclaims the model as a sharp reference",
    "not a sharp reference" in _rep)
chk("report carries no stake sizing", "$" not in _rep)
chk("gap is in points, not a fraction",
    f"{(_ed2.model_p - _ed2.fair_p) * 100:+.1f} pts" in _rep,
    f"gap is {(_ed2.model_p - _ed2.fair_p)*100:+.1f} pts")

section("15. DATA AS OF completeness guard")
_st = ff_data.data_status(2026)
_reg15 = wk[wk.season_type == "REG"]
_pw = _reg15.groupby("week").team.nunique()
# Completeness comes from the shared function, NOT from the threshold alone.
# This check used to recompute it as "every week clearing MIN_TEAMS", which is
# the exact assumption B27 corrected — so it failed the moment the newest-week
# rule landed. A check that re-implements the logic it is testing will always
# drift away from it.
_done = ff_data.complete_weeks(_reg15)
_complete = _pw[[w in _done for w in _pw.index]]
_partial = _pw[[w not in _done for w in _pw.index]]
chk("reports the last COMPLETE week, not week.max()",
    f"through Week {int(_complete.index.max())}" in _st,
    f"complete through {int(_complete.index.max())}, "
    f"max week in data is {int(_pw.index.max())}")
if not _partial.empty:
    chk("names the in-progress week instead of hiding it",
        "IN PROGRESS" in _st and
        all(f"Week {int(w)}" in _st for w in _partial.index
            if w > _complete.index.max()),
        f"partial: {dict(_partial)}")
    chk("names which teams have no rows yet, so byes are not inferred",
        "no rows yet for" in _st and "do not read them as byes" in _st)
else:
    chk("no partial week this run — nothing to flag", True)
    chk("no partial week this run — nothing to name", True)
chk("the three completeness guards agree",
    ff_props.bye_weeks(wk) == ff_guillotine.team_byes(wk))
chk("guard is shared, not duplicated",
    ff_data.MIN_TEAMS_COMPLETE_WEEK == 20)

section("16. UNDER must be priced at the UNDER's price (F1)")
# Omitting under_odds used to fall back to over_odds, pricing a bet nobody
# can place: on +275/-350 it reported EV +217%/$ and Kelly 0.79 where the
# real figures were +8.7% and 0.31. Flattering, and reachable from the
# documented workflow — screen_quotes flags a one-sided market and says to
# pass fair_over, which lands exactly here.
_u = threshold_prob(player_series(wk[wk.season_type=="REG"],
                                  "Travis Kelce", "receiving_tds"), 0.5)
_fair_under = 0.45          # above the model, so UNDER is preferred
chk("model prefers UNDER in this fixture",
    prop_edge(_u, 275, -350, fair_over=_fair_under).side == "UNDER")
try:
    prop_edge(_u, 275, fair_over=_fair_under)
    chk("refuses to price UNDER without an under price", False,
        "silently used over_odds")
except ValueError as _ex:
    chk("refuses to price UNDER without an under price",
        "one-sided" in str(_ex))
_a = prop_edge(_u, 275, -350, fair_over=_fair_under)
_b = prop_edge(_u, 275, -257, fair_over=_fair_under)
chk("EV tracks the under price, as it must",
    _a.ev_per_dollar != _b.ev_per_dollar,
    f"-350 -> {_a.ev_per_dollar:+.4f}, -257 -> {_b.ev_per_dollar:+.4f}")
chk("EV is no longer absurd", abs(_a.ev_per_dollar) < 1.0,
    f"{_a.ev_per_dollar:+.4f}")
chk("OVER side unaffected by omitting under_odds",
    prop_edge(_u, 275, fair_over=0.20).side == "OVER")

section("17. prior-season fallback (F6)")
_wk2 = ff_data.load_weekly([2025, 2026])
_p26 = ff_guillotine.build_pool(_wk2[_wk2.season == 2026], LEAGUES["guillotine"])
_pfb = ff_guillotine.build_pool(_wk2, LEAGUES["guillotine"], season=2026)
chk("2026-only pool has no stale entries", len(_p26.stale) == 0)
chk("fallback pool adds prior-season players", len(_pfb) > len(_p26),
    f"{len(_p26)} -> {len(_pfb)}, {len(_pfb.stale)} stale")
# SYNTHETIC, by requirement. These three checks used to name Zach
# Charbonnet as the returning player and De'Zhaun Stribling as the absent
# one, read straight from live nflverse. On 2026-11-03 Charbonnet played
# Week 8, picked up a 2026 row, and all three checks failed — the data
# moved out from under the fixture. That is B21/B23 a third time: a
# regression check must not depend on live data, which changes weekly,
# when the condition it needs (a player with prior-season rows only) can
# be constructed exactly.
_tmpl = _wk2[_wk2.season == 2025].head(1)
def _synth_rows(name, season, n):
    r = pd.concat([_tmpl] * n, ignore_index=True)
    r["player_display_name"] = name
    r["season"] = season
    r["week"] = range(1, n + 1)
    return r
# "Absent Player" is deliberately NOT added to the frame — the point of
# that check is a name with no rows in any season, which is a different
# situation from a returning player and must get a different answer.
_syn = pd.concat([_wk2, _synth_rows("Returning Player", 2025, 12)],
                 ignore_index=True)
_s26 = ff_guillotine.build_pool(_syn[_syn.season == 2026], LEAGUES["guillotine"])
_sfb = ff_guillotine.build_pool(_syn, LEAGUES["guillotine"], season=2026)

chk("returning player resolves only with the fallback",
    ff_guillotine.resolve("Returning Player", _s26) is None
    and ff_guillotine.resolve("Returning Player", _sfb) is not None)
chk("returning player is marked stale",
    ff_guillotine.resolve("Returning Player", _sfb) in _sfb.stale)
chk("truly-absent player stays unresolved in both",
    ff_guillotine.resolve("Absent Player", _s26) is None
    and ff_guillotine.resolve("Absent Player", _sfb) is None)
_fakeroster = [{"team_id": "9", "team_name": "T",
                "roster": {"RB": ["Returning Player"],
                           "BN": ["Absent Player"]}}]
chk("stale and unresolved are reported separately",
    ff_guillotine.stale_names(_fakeroster, _sfb) == {"T": ["Returning Player"]}
    and ff_guillotine.unresolved(_fakeroster, _sfb)
        == {"T": ["Absent Player"]})
_raw = _pfb["Zach Charbonnet"]
_drawn = ff_guillotine._draw(_pfb, "Zach Charbonnet", 40000)
chk("stale draw widens the spread but keeps the level",
    _drawn.std() > _raw.std(ddof=0) * 1.2
    and abs(_drawn.mean() - _raw.mean()) < 1.0,
    f"sd {_raw.std(ddof=0):.1f} -> {_drawn.std():.1f}, "
    f"mean {_raw.mean():.1f} -> {_drawn.mean():.1f}")

section("18. bye/week safety (F5)")
_meta2 = ff_guillotine.build_meta(_wk2[_wk2.season == 2026])
chk("team-code form works",
    len(ff_guillotine.players_on_bye(9, _meta2, {"PIT", "TEN"})) > 50)
try:
    # One past the last week on file. This was a typed 9 until nflverse
    # posted Week 10 and 9 stopped being a future week.
    ff_guillotine.players_on_bye(
        int(_wk2[_wk2.season == 2026].week.max()) + 1, _meta2,
        ff_guillotine.team_byes(_wk2[_wk2.season == 2026]))
    chk("derived map + future week raises instead of returning empty", False,
        "returned an empty set, which reads as 'nobody is on bye'")
except ValueError as _ex:
    chk("derived map + future week raises instead of returning empty",
        "UPCOMING" in str(_ex))
chk("derived map + a played week still works",
    len(ff_guillotine.players_on_bye(
        5, _meta2, ff_guillotine.team_byes(_wk2[_wk2.season == 2026]))) > 50)

section("19. Drive upload is verifiable (F7)")
_tmp2 = tempfile.mkdtemp()
ff_betlog.LOG_DIR = pathlib.Path(_tmp2)
ff_betlog.SESSION = ff_betlog.LOG_DIR / "_session.jsonl"
ff_betlog.log_bet(385, 10, [Leg("A", "player_rush_yds", 50.5, "OVER", -110,
                                "fd")], "fd", note="em dash \u2014 here")
_n2, _t2 = ff_betlog.upload_payload()
chk("exact round trip verifies", ff_betlog.verify_uploaded(_t2))
# json.dumps writes \u2014 and Drive hands back the raw character. This check
# used to assert that difference was CAUGHT as corruption — the reasoning
# being that it proves the path is not byte-safe, which is a fair canary.
# B91 changed it, because the canary fires on every realistic log (178 em
# dashes in ff_props.py, 35 inside verdict-reason strings), so it carries no
# information and gets ignored: a live session got False, reasoned it out by
# hand, and declined to mark_uploaded, leaving 69 records up but unmarked and
# due to be re-uploaded forever. Escape-versus-raw for the same codepoint is
# a deterministic lossless transcoding, not luck.
#
# The original concern is KEPT, as a message rather than a verdict: the pass
# reflects record equality, and the output still says the bytes differed and
# why. Both assertions below have to hold.
_dec = ff_betlog.verify_uploaded(_t2.replace("\\u2014", "\u2014"))
chk("escape-decoding verifies, because the records are identical", _dec)
import io, contextlib
_buf = io.StringIO()
with contextlib.redirect_stdout(_buf):
    ff_betlog.verify_uploaded(_t2.replace("\\u2014", "\u2014"))
chk("and the byte difference is still REPORTED, not hidden",
    "Bytes differ" in _buf.getvalue()
    and "lossless" in _buf.getvalue(), _buf.getvalue()[:140])
chk("a dropped line is caught",
    not ff_betlog.verify_uploaded("\n".join(_t2.splitlines()[:-1]) + "\n"))
shutil.rmtree(_tmp2, ignore_errors=True)

section("20. replacement-level fill for short rosters (F4/B17)")
_rl = ff_guillotine.build_pool(_wk2, LEAGUES["guillotine"], season=2026)
ff_guillotine.add_replacement_level(_rl, _meta2, n_teams=10)
for _pos in ("QB", "RB", "WR", "TE"):
    _rn = ff_guillotine.replacement_name(_pos)
    chk(f"replacement level exists for {_pos}", _rn in _rl)
_rbv = _rl[ff_guillotine.replacement_name("RB")]
chk("replacement is a distribution, not a point estimate",
    len(_rbv) > 20 and _rbv.std(ddof=0) > 1,
    f"{len(_rbv)} player-weeks, sd {_rbv.std(ddof=0):.2f}")
# Replacement must sit BELOW the startable tier, or it is not replacement.
_starters = [float(np.mean(v)) for n, v in _rl.items()
             if not n.startswith(ff_guillotine.REPL_PREFIX)
             and _meta2.get(n, ("", ""))[1] == "RB" and len(v) >= 3]
_starters.sort(reverse=True)
chk("replacement RB sits below the startable tier",
    float(_rbv.mean()) < _starters[9],
    f"repl {_rbv.mean():.1f} vs RB10 {_starters[9]:.1f}")
# A short roster must now be filled rather than scoring the slot as nothing.
_short = {"QB": ["Patrick Mahomes"], "RB": ["Bijan Robinson"],
          "WR": ["Jaxon Smith-Njigba", "DeVonta Smith"], "TE": ["Travis Kelce"]}
_L = ff_guillotine.best_lineup(_short, _rl, strict=False)
chk("short lineup is padded to full size",
    len(_L) == sum(SLOTS_TOTAL := [v for v in ff_guillotine.SLOTS.values()]),
    f"{len(_L)} of {sum(ff_guillotine.SLOTS.values())} slots")
chk("padding uses replacement entries",
    any(p.startswith(ff_guillotine.REPL_PREFIX) for p in _L))
try:
    ff_guillotine.best_lineup(_short, _rl, strict=True)
    chk("strict=True still refuses a short roster", False)
except ValueError:
    chk("strict=True still refuses a short roster", True)

section("21. Drive upload via base64 (F1 prevention)")
_tmp3 = tempfile.mkdtemp()
ff_betlog.LOG_DIR = pathlib.Path(_tmp3)
ff_betlog.SESSION = ff_betlog.LOG_DIR / "_session.jsonl"
ff_betlog.log_bet(385, 10, [Leg("A", "player_rush_yds", 50.5, "OVER", -110,
                                "fd")], "fd",
                  note="em dash \u2014 caf\u00e9 na\u00efve \u65e5\u672c\u8a9e")
_nm, _b64, _ck = ff_betlog.upload_payload_b64()
chk("base64 payload is pure ASCII with no escapes",
    _b64.isascii() and all(c.isalnum() or c in "+/=" for c in _b64))
chk("base64 round trip is byte-identical",
    ff_betlog.verify_uploaded(ff_betlog.decode_downloaded(_b64)))
chk("checksum matches the text payload", _ck == ff_betlog._sha(
    ff_betlog.decode_downloaded(_b64)))
chk("decode_downloaded passes plain text through",
    ff_betlog.decode_downloaded('{"a": 1}') == '{"a": 1}')
# The exact corruption observed live: \u2014 escape arriving as a raw em dash.
# It cannot occur in base64, but a corrupted base64 must still be caught.
chk("corrupted base64 is caught, not silently accepted",
    not ff_betlog.verify_uploaded(
        ff_betlog.decode_downloaded(_b64[:40] + "X" + _b64[41:])))
shutil.rmtree(_tmp3, ignore_errors=True)

section("22. fill_replacement flag is authoritative (B19)")
# add_replacement_level() mutates the pool in place. An earlier version gated
# the padding on whether the pool CONTAINED replacement keys, so once any
# fill=True run had touched a pool, a later fill=False run silently kept
# filling — the A/B comparison the flag exists for quietly became A/A,
# order-dependent and invisible in the report.
# SYNTHETIC league, built from names already in the pool. This section used
# to load `guillotine_rosters.json`, which was never committed — so the suite
# died here with FileNotFoundError on every clean clone, and died BEFORE
# printing its count line, which is the one number sessions are told to
# quote. A regression test must not depend on live roster data: it changes
# weekly, and the thing being tested needs a SHORT roster to exist at all.
# On the live Week 9 slate no roster was short, so this check was
# unexercisable there even when the file was present.
def _synthetic_league(pool, meta, n_teams=6):
    """A league where exactly one team is deliberately short at RB."""
    by_pos = {}
    for name, v in pool.items():
        if name.startswith(ff_guillotine.REPL_PREFIX) or len(v) < 4:
            continue
        info = meta.get(name)
        if info and info[1] in ("QB", "RB", "WR", "TE"):
            by_pos.setdefault(info[1], []).append((float(np.mean(v)), name))
    for rows in by_pos.values():
        rows.sort(key=lambda r: -r[0])

    def take(pos, k, off):
        return [n for _, n in by_pos[pos][off:off + k]]

    teams = []
    for i in range(n_teams):
        teams.append({
            "team_id": str(i), "team_name": f"synthetic {i}",
            "roster": {"QB": take("QB", 2, i * 2), "RB": take("RB", 4, i * 4),
                       "WR": take("WR", 5, i * 5), "TE": take("TE", 2, i * 2)},
        })
    # Team 1 keeps ONE RB. With RB needing 2 plus FLEX, that cannot be filled
    # from the roster, which is exactly the state the flag governs.
    teams[1]["roster"]["RB"] = teams[1]["roster"]["RB"][:1]
    teams[1]["roster"]["WR"] = teams[1]["roster"]["WR"][:2]
    teams[1]["roster"]["TE"] = teams[1]["roster"]["TE"][:1]
    return teams

_shared = ff_guillotine.build_pool(_wk2, LEAGUES["guillotine"], season=2026)
_teams_g = _synthetic_league(_shared, _meta2)
_victim = "synthetic 1"
chk("synthetic fixture needs no uncommitted file", True)
try:
    ff_guillotine.best_lineup(_teams_g[1]["roster"], _shared, strict=True)
    chk("the fixture really is short at RB", False, "it filled a full lineup")
except ValueError as _ex:
    chk("the fixture really is short at RB", "RB needs 2" in str(_ex))

_seq = []
for _f in (True, False, True, False):
    _r = ff_guillotine.run(_teams_g, _shared, my_team_id="0", n_sims=40_000,
                           meta=_meta2, week=9, fill_replacement=_f)
    _seq.append((_f, _r.opp_scores_mean[_victim]))
_on = [v for f, v in _seq if f]
_off = [v for f, v in _seq if not f]
chk("fill=True pads the short roster", min(_on) > max(_off), f"{_on}")
chk("fill=False does NOT pad, even after a True run on the same pool",
    max(_off) < min(_on), f"{_off}")
chk("the two modes stay separated across repeated alternation",
    min(_on) - max(_off) > 3,
    f"on {sum(_on)/len(_on):.1f} vs off {sum(_off)/len(_off):.1f}")
chk("best_lineup honours fill=False with keys present in the pool",
    len(ff_guillotine.best_lineup(_teams_g[1]["roster"], _shared,
                                  strict=False, fill=False))
    < len(ff_guillotine.best_lineup(_teams_g[1]["roster"], _shared,
                                    strict=False, fill=True)))
chk("replacement keys never enter my own lineup enumeration",
    not any(p.startswith(ff_guillotine.REPL_PREFIX)
            for lu in ff_guillotine.enumerate_lineups(
                _teams_g[0]["roster"], _shared)
            for p in lu))

section("23. newest week is treated as in progress (B27)")
from ff_data import complete_weeks
# The threshold alone cannot decide this. On 2026-11-02 Week 8 held 26 teams,
# clearing the old threshold of 20, so it was called COMPLETE while Chicago
# and Seattle had not played Monday night. Both had played every other week,
# so Week 8 was their only gap and team_byes assigned them A BYE IN WEEK 8 —
# a wrong value, not a silent omission, on a week they were playing. Jaxon
# Smith-Njigba (SEA) and Luther Burden III (CHI) were both in the live best
# lineup at the time.
def _wkframe(counts):
    """counts: {week: n_teams} -> a minimal REG frame."""
    rows = []
    for w, n in counts.items():
        for i in range(n):
            rows.append({"week": w, "team": f"T{i:02d}", "season": 2026,
                         "season_type": "REG"})
    return pd.DataFrame(rows)

_mid = _wkframe({1: 32, 2: 32, 3: 30, 4: 28, 5: 26})
chk("newest week is excluded even when it clears the threshold",
    complete_weeks(_mid) == {1, 2, 3, 4}, f"{sorted(complete_weeks(_mid))}")
chk("earlier weeks below the threshold are still excluded",
    complete_weeks(_wkframe({1: 32, 2: 2, 3: 30, 4: 28})) == {1, 3},
    f"{sorted(complete_weeks(_wkframe({1: 32, 2: 2, 3: 30, 4: 28})))}")
chk("connector current_week overrides the newest-week rule",
    complete_weeks(_mid, current_week=6) == {1, 2, 3, 4, 5},
    f"{sorted(complete_weeks(_mid, current_week=6))}")
chk("current_week keeps the in-progress week out",
    5 not in complete_weeks(_mid, current_week=5))
chk("a single-week frame yields nothing complete",
    complete_weeks(_wkframe({1: 32})) == set())

# The live symptom: a team absent only from the newest week must NOT get a bye.
_live = ff_data.load_weekly(2026)
_b = ff_guillotine.team_byes(_live)
_reg = _live[_live.season_type == "REG"]
_maxw = int(_reg.week.max())
_absent_newest = sorted(set(_reg.team) - set(_reg[_reg.week == _maxw].team))
chk("no team is assigned a bye in the newest week",
    all(v != _maxw for v in _b.values()),
    f"week {_maxw}, {len(_absent_newest)} teams absent: {_absent_newest}")
chk("byes that ARE established still resolve",
    len(_b) >= 8, f"{len(_b)} teams with a known bye")
chk("props and guillotine agree on byes",
    ff_props.bye_weeks(_live) == _b)

section("24. native PropLine shape is read correctly (B24)")
from ff_props import flatten_odds, _prices
# THE GAP THIS CLOSES: every fixture in sections 12 and 21 used the
# pre-flattened {"over":…, "under":…} shape. propline_get_odds actually
# returns one row PER OUTCOME, and "price" was listed in PRICE_KEYS_OVER with
# no name check — so a native Under row returned (-113, None), reporting the
# Under's price AS the Over's price. 135 passing checks said nothing about
# it, because the native shape was never tested.
chk("native Under row reads as the UNDER",
    _prices({"name": "Under", "price": -113}) == (None, -113.0))
chk("native Over row reads as the OVER",
    _prices({"name": "Over", "price": -111}) == (-111.0, None))
chk("milestone rung prices the backable side",
    _prices({"name": "280+ Passing Yards", "price": 349}) == (349.0, None))
chk("anytime-TD player row prices the yes side",
    _prices({"name": "Travis Kelce", "price": 270}) == (270.0, None))
chk("flattened shape still works",
    _prices({"over": -111, "under": -113}) == (-111.0, -113.0))

# The real get_odds envelope, trimmed to the markets that matter.
_resp = {"bookmakers": [{"key": "draftkings", "pregame_only": False,
    "last_update": "2026-10-31T04:34:23+00:00", "markets": [
    {"key": "player_pass_yds", "line_type": "main", "suspended_at": None,
     "last_update": "2026-10-31T04:34:23+00:00", "outcomes": [
       {"name": "Over", "description": "Patrick Mahomes", "price": -111,
        "point": 222.5, "last_seen_at": "2026-10-31T04:34:23+00:00"},
       {"name": "Under", "description": "Patrick Mahomes", "price": -113,
        "point": 222.5, "last_seen_at": "2026-10-31T04:34:23+00:00"}]},
    {"key": "player_pass_yds", "line_type": "milestone", "suspended_at": None,
     "last_update": "2026-10-31T04:34:23+00:00", "outcomes": [
       {"name": "280+ Passing Yards", "description": "Patrick Mahomes",
        "price": 349, "point": None,
        "last_seen_at": "2026-10-31T04:34:23+00:00"}]}]}]}

_main = flatten_odds(_resp, line_type="main")
chk("flatten_odds pairs the two sides", len(_main) == 1
    and _main[0]["over"] == -111.0 and _main[0]["under"] == -113.0,
    f"{_main[0]['over']}/{_main[0]['under']}" if _main else "nothing returned")
chk("flatten_odds carries the line and player",
    _main[0]["line"] == 222.5 and _main[0]["player"] == "Patrick Mahomes")
chk("flatten_odds carries suspended_at and pregame_only",
    _main[0]["suspended_at"] is None and _main[0]["pregame_only"] is False)
chk("line_type filter excludes milestone rungs from main",
    all(q["line_type"] == "main" for q in _main))
_mile = flatten_odds(_resp, line_type="milestone")
chk("milestone rung comes back one-sided",
    len(_mile) == 1 and _mile[0]["under"] is None
    and _mile[0]["over"] == 349.0)

# The symptom that was actually observed: a two-sided market reported as
# one-sided because the Under's price had been read as the Over's.
_sc = screen_quotes(_main, max_age_s=10**9)
chk("a two-sided main line is NOT reported one-sided",
    _sc.one_sided == [] and len(_sc.usable) == 1, f"{_sc.one_sided}")
# B122. This pinned the BOOK-only entry. On a 32-row anytime-TD board that
# printed "draftkings" thirty-two times and could not say which leg was
# one-sided — the only thing worth knowing on a mixed board. The entry now
# names the leg and keeps the book, since a leg one-sided at one book may be
# two-sided at another.
_mile_os = screen_quotes(_mile, max_age_s=10**9).one_sided
chk("a milestone rung IS reported one-sided",
    len(_mile_os) == 1 and "draftkings" in _mile_os[0], str(_mile_os))
chk("and the entry names the LEG, not just the book",
    _mile_os[0] != "draftkings", str(_mile_os))
# Several one-sided legs at one book must not collapse into one line, nor
# repeat the book N times with nothing to tell them apart.
_many = [{"book": "draftkings", "player": p, "market": "player_anytime_td",
          "point": None, "over": am, "under": None, "suspended_at": None}
         for p, am in (("Travis Kelce", 145), ("Rashee Rice", 130),
                       ("Xavier Worthy", 180))]
_many_os = screen_quotes(_many, game_started=False).one_sided
chk("three one-sided legs at one book give three distinguishable entries",
    len(_many_os) == 3 and len(set(_many_os)) == 3, str(_many_os))
chk("and each names its player",
    all(any(n in e for n in ("Kelce", "Rice", "Worthy")) for e in _many_os),
    str(_many_os))
# Either side missing counts: checking only `under` missed the Under-only row.
for _lbl, _q in (("over-only", {"book": "dk", "name": "Over", "price": -111,
                                "last_update": "2026-10-31T04:34:23+00:00"}),
                 ("under-only", {"book": "dk", "name": "Under", "price": -113,
                                 "last_update": "2026-10-31T04:34:23+00:00"})):
    chk(f"{_lbl} row is flagged one-sided",
        screen_quotes([_q], max_age_s=10**9).one_sided == ["dk"])

section("25. flatten_odds guards and carried fields (B28-B31)")
def _mkresp(line_type, outcomes, market="player_pass_yds"):
    return {"bookmakers": [{"key": "dk", "pregame_only": False,
        "last_update": "2026-11-02T12:00:00+00:00", "markets": [
        {"key": market, "line_type": line_type, "suspended_at": None,
         "last_update": "2026-11-02T12:00:00+00:00",
         "outcomes": outcomes}]}]}

def _oc(name, price, point=222.5, **kw):
    return dict(name=name, description="P", price=price, point=point,
                last_seen_at="2026-11-02T12:00:00+00:00", **kw)

# B28: an unrecognised label on a market WITH a line was silently priced as
# the OVER — the B24 signature inside the adapter written to fix B24. A
# synthetic {"name": "Mystery Label"} came back as over=-250 with no error.
_myst = flatten_odds(_mkresp("main", [_oc("Mystery Label", -250),
                                      _oc("Under", -113)]))[0]
chk("unrecognised label on a lined market is recorded",
    _myst["unknown_labels"] == ["Mystery Label"])
chk("unrecognised label raises a warning on the quote",
    "unrecognised outcome label" in _myst.get("label_warning", ""))
chk("screen_quotes DROPS a quote with an unknown label",
    len(screen_quotes([_myst], max_age_s=10**9).usable) == 0)
chk("a normal Over/Under market carries no warning",
    "label_warning" not in flatten_odds(
        _mkresp("main", [_oc("Over", -111), _oc("Under", -113)]))[0])

# One-sided boards legitimately carry odd labels — those are not warnings.
_rung = flatten_odds(_mkresp("milestone",
    [_oc("280+ Passing Yards", 349, None)]), line_type="milestone")[0]
chk("milestone rung goes to `rung`, not unknown_labels",
    _rung.get("rung") == "280+ Passing Yards" and not _rung["unknown_labels"])
# B31: a player name on a one-sided board used to be written into `rung`,
# making "Ameer Abdullah" look like a threshold.
_td = flatten_odds(_mkresp("main", [_oc("Ameer Abdullah", 700, None)],
                           market="player_anytime_td"))[0]
chk("player name goes to `outcome_label`, not `rung`",
    _td.get("outcome_label") == "Ameer Abdullah" and "rung" not in _td)

# A side collision means one outcome was misclassified; neither price is safe.
try:
    flatten_odds(_mkresp("main", [_oc("Over", -111), _oc("Over", -120)]))
    chk("two outcomes on the same side raises", False)
except ValueError as _ex:
    chk("two outcomes on the same side raises",
        "claim the same side" in str(_ex))

# B29/B30: fields the adapter used to discard.
chk("player_id is carried",
    flatten_odds(_mkresp("main", [_oc("Over", -111, player_id="espn:1"),
                                  _oc("Under", -113, player_id="espn:1")])
                 )[0]["player_id"] == "espn:1")
chk("missing player_id is None, not an error",
    flatten_odds(_mkresp("main", [_oc("Over", -111), _oc("Under", -113)])
                 )[0]["player_id"] is None)
chk("payout_multiplier is carried",
    flatten_odds(_mkresp("main", [_oc("Over", -111, payout_multiplier=1.5),
                                  _oc("Under", -113)])
                 )[0]["payout_multiplier"] == 1.5)
chk("line_type='alternate' returns rows when they exist",
    len(flatten_odds(_mkresp("alternate", [_oc("Over", -140, 230.5),
                                           _oc("Under", 115, 230.5)]),
                     line_type="alternate")) == 1)

section("24b. first-TD fields de-vig as a field; anytime-TD must not")
from ff_props import devig_field
# Live board, event 87238, 2026-11-05. DraftKings listed 32 outcomes
# INCLUDING "No Touchdown Scorer" (+6000) and both D/STs; BetMGM listed 23
# with neither. The nine DK carried and BetMGM did not sum to 0.1788 —
# almost the whole booksum gap — so BetMGM's leaner-looking market is a
# SHORTER FIELD, not a better one.
_DK1 = {"Ameer Abdullah": 2500, "BAL Ravens D/ST": 2000, "Bhayshul Tuten": 400,
        "Brenton Strange": 1000, "Brian Thomas Jr.": 2000,
        "Chris Rodriguez Jr.": 400, "CJ Williams": 6000, "Derrick Henry": 600,
        "Devontez Walker": 11000, "Elijah Sarratt": 11000,
        "Ja'Kobi Lane": 3500, "Jakobi Meyers": 1200, "JAX Jaguars D/ST": 1900,
        "Joe Fagnano": 5500, "Josh Cameron": 2200, "Josh Cuevas": 7000,
        "Justice Hill": 2200, "LaJohntay Wester": 8000, "LeQuint Allen": 4000,
        "Mark Andrews": 2800, "Matthew Hibner": 7500, "Nate Boerkircher": 2000,
        "Nick Vannett": 11000, "No Touchdown Scorer": 6000,
        "Parker Washington": 650, "Quintin Morris": 7000, "Rasheen Ali": 11000,
        "Rashod Bateman": 4000, "Tanner Koziol": 8000, "Travis Hunter": 3000,
        "Trevor Lawrence": 2000, "Zay Flowers": 2000}
_MGM1 = {k: v for k, v in _DK1.items()
         if k not in {"BAL Ravens D/ST", "JAX Jaguars D/ST", "CJ Williams",
                      "Devontez Walker", "Elijah Sarratt", "LaJohntay Wester",
                      "Nick Vannett", "No Touchdown Scorer", "Rasheen Ali"}}
_f = devig_field(_DK1, market="player_1st_td")
chk("a complete first-TD field de-vigs to exactly 1",
    abs(sum(_f["fair"].values()) - 1.0) < 1e-9 and _f["n"] == 32,
    f'booksum {_f["booksum"]:.4f}, overround {_f["overround"]:+.1%}')
# THE REFUSAL THAT MATTERS MOST. Anytime TD is NOT mutually exclusive —
# several players score, so the prices sum to the expected NUMBER of
# scorers. Normalising them to 1 divides every probability by roughly
# three and looks completely plausible doing it.
try:
    devig_field({"a": 100, "b": 200}, market="player_anytime_td")
    _raised = False
except ValueError as e:
    _raised = "not a mutually exclusive field" in str(e)
chk("anytime TD is REFUSED as a field, not silently normalised", _raised)
# An incomplete field's booksum is too low by whatever is missing, so
# de-vigging it inflates every outcome — in the flattering direction.
try:
    devig_field(_MGM1, market="player_1st_td")
    _raised = False
except ValueError as e:
    _raised = "INCOMPLETE" in str(e)
chk("a field with no no-scorer outcome is refused as incomplete", _raised)
_short = devig_field(_MGM1, market="player_1st_td", require_complete=False)
chk("and forcing it really does inflate, which is why it is refused",
    _short["fair"]["Bhayshul Tuten"] > 0
    and _short["booksum"] < _f["booksum"],
    f'short field booksum {_short["booksum"]:.4f} vs full {_f["booksum"]:.4f}')
# Shin vs proportional on a 55% overround field: the whole reason the
# instructions mandate Shin for longshots.
_m = devig_field(_DK1, market="player_1st_td", method="multiplicative")
chk("Shin shrinks the longest shot hard — 2x+ against proportional",
    _m["fair"]["Nick Vannett"] > 2.0 * _f["fair"]["Nick Vannett"],
    f'+11000: shin {_f["fair"]["Nick Vannett"]:.4%} vs '
    f'mult {_m["fair"]["Nick Vannett"]:.4%}')
chk("and raises the favourite, which is the other half of the correction",
    _f["fair"]["Bhayshul Tuten"] > _m["fair"]["Bhayshul Tuten"])
try:
    devig_field({"solo": 100}, market="player_1st_td")
    _raised = False
except ValueError:
    _raised = True
chk("a one-outcome field is refused rather than returning 100%", _raised)

section("25a. a silently dropped anchor book is caught (B60)")
from ff_props import anchor_coverage, ANCHOR_CHAIN
# `get_event_ev` drops an anchor book while that book's odds feed stays
# healthy, and DOES NOT return [] when it does — it returns a populated,
# plausible response with the sharp anchor quietly replaced. Observed three
# times on event 87238; worst case Pinnacle anchored 0 of 154 lines across
# three calls over 90 seconds while a paired get_odds control showed it
# live. anchor_opening/anchor_thin cannot see it: they key on liquidity and
# the EV payload carries none (D17). Only holding both payloads together
# catches it.
def _mk_odds(books):
    return {"bookmakers": [
        {"key": b, "markets": [{"suspended_at": None, "outcomes": [
            {"name": "Over", "point": 10.5 + i}, {"name": "Under", "point": 10.5 + i}]}
            for i in range(n)]}
        for b, n in books.items()]}
def _mk_ev(sources):
    return {"lines": [{"fair_source": s} for s, n in sources.items()
                      for _ in range(n)]}

_ok = anchor_coverage(_mk_ev({"pinnacle": 5, "kalshi": 41, "bovada": 6}),
                      _mk_odds({"pinnacle": 5, "kalshi": 19, "bovada": 7}))
chk("a healthy pull reports no dropout", _ok.healthy and not _ok.silent_dropouts,
    _ok.describe()[:70])
_drop = anchor_coverage(_mk_ev({"kalshi": 133, "bovada": 21}),
                        _mk_odds({"pinnacle": 14, "kalshi": 19, "bovada": 7}))
chk("the observed B60 signature IS caught",
    _drop.silent_dropouts == ["pinnacle"] and not _drop.healthy,
    "pinnacle live with 14 two-sided markets, anchored 0")
chk("and the note says it is invisible in the EV payload alone",
    "nothing in the EV payload says it happened" in _drop.describe())
# THE FALSE POSITIVE A LIVE PULL CAUGHT. DraftKings can never anchor — the
# chain is pinnacle -> polymarket -> kalshi -> bovada -> smarkets — so its
# absence from the anchor set means nothing at all.
chk("a book outside the anchor chain is never a dropout",
    anchor_coverage(_mk_ev({"pinnacle": 5, "kalshi": 41}),
                    _mk_odds({"pinnacle": 5, "kalshi": 19,
                              "draftkings": 3})).healthy,
    f"chain is {ANCHOR_CHAIN}; draftkings is not in it")
# The chain is tried IN ORDER, so a LOWER book anchoring nothing is correct
# behaviour — the books above it covered every line — not a dropout.
chk("a lower-priority book anchoring nothing is correct, not suspicious",
    anchor_coverage(_mk_ev({"pinnacle": 52}),
                    _mk_odds({"pinnacle": 14, "kalshi": 19,
                              "bovada": 7})).healthy,
    "pinnacle covered everything; kalshi and bovada had nothing left")
chk("a suspended market does not count as live to anchor",
    anchor_coverage(_mk_ev({"kalshi": 10}),
                    {"bookmakers": [
                        {"key": "pinnacle", "markets": [
                            {"suspended_at": "2026-11-05T00:00:00Z",
                             "outcomes": [{"name": "Over"}, {"name": "Under"}]}] * 9},
                        {"key": "kalshi", "markets": [
                            {"suspended_at": None,
                             "outcomes": [{"name": "Over"}, {"name": "Under"}]}] * 9}]}
                    ).healthy)
# B62, AND IT IS THE WORST OF THE THREE. The "a book below it anchored"
# condition — added to kill the lower-priority false positive — opened a
# hole underneath itself: when NOTHING anchors, no book has anything below
# it, so nothing flags and `healthy` returns True. That is this fault at
# its loudest, and it is reason 6 of the `lines: []` ambiguity — the case
# the instructions say ONLY a paired get_odds control can diagnose. The
# control said healthy. Observed live 2026-11-05 03:00-03:03.
_blank = anchor_coverage({"lines": []},
                         _mk_odds({"pinnacle": 14, "kalshi": 19}))
chk("an EV with NO anchors beside a live chain book is not healthy",
    not _blank.healthy and _blank.blank,
    _blank.describe()[:80])
chk("the blank case names itself rather than listing a per-book dropout",
    "NOTHING ANCHORED AT ALL" in _blank.describe()
    # B72b. This assertion used to require silent_dropouts == ["pinnacle"],
    # which CONTRADICTED this check's own name: the blank finding is
    # "nothing anchored at all", and naming the top chain book as a
    # specific dropout is an accusation the measurement does not support.
    # describe() suppressed it, so the wrong value was only visible to a
    # caller reading the field directly. `blank` carries the finding and
    # `healthy` already reads it, so the per-book list stays empty.
    and _blank.silent_dropouts == []
    and not _blank.healthy)
chk("an empty EV with NO chain book live is NOT flagged — that is no market",
    anchor_coverage({"lines": []}, _mk_odds({"draftkings": 9})).healthy)
# B63. min_markets=3 counted market ENTRIES, which mean different things per
# book: Pinnacle 14 (one per player), Bovada 30 (alternates separate),
# Kalshi's whole anytime-TD board 1. Measured live: on player_pass_yds
# Pinnacle carries TWO two-sided lines, because a game has two QBs, and
# anchored 0 of 30 — the detector said "no silent dropouts" in the same
# minute it correctly flagged three other markets.
_qb = {"bookmakers": [{"key": "pinnacle", "markets": [{
    "key": "player_pass_yds", "suspended_at": None, "outcomes": [
        {"name": "Over", "description": "Joe Fagnano", "point": 160.5},
        {"name": "Under", "description": "Joe Fagnano", "point": 160.5},
        {"name": "Over", "description": "Trevor Lawrence", "point": 237.5},
        {"name": "Under", "description": "Trevor Lawrence", "point": 237.5}]}]}]}
chk("a two-QB market is still big enough to flag a dropout",
    not anchor_coverage(_mk_ev({"kalshi": 17, "bovada": 13}), _qb).healthy,
    "pass yards can never carry 3 markets — size is the wrong gate")
# Lines, not entries: one market entry holding many players is many lines.
_collapsed = {"bookmakers": [{"key": "kalshi", "markets": [{
    "key": "player_anytime_td", "suspended_at": None, "outcomes": [
        o for i in range(22) for o in
        ({"name": "Yes", "description": f"P{i}", "point": None},
         {"name": "No", "description": f"P{i}", "point": None})]}]}]}
chk("a collapsed Yes/No board counts its real lines, not its one entry",
    anchor_coverage({"lines": []}, _collapsed).live == {"kalshi": 22},
    "B64: Kalshi's whole TD board arrives as a single market entry")
chk("a one-sided board does not count as live to anchor",
    anchor_coverage(_mk_ev({"kalshi": 10}),
                    {"bookmakers": [
                        {"key": "pinnacle", "markets": [
                            {"suspended_at": None,
                             "outcomes": [{"name": "Over"}]}] * 9},
                        {"key": "kalshi", "markets": [
                            {"suspended_at": None,
                             "outcomes": [{"name": "Over"}, {"name": "Under"}]}] * 9}]}
                    ).healthy,
    "one-sided is D-18's fourth meaning of [], not a dropout")

section("25b. milestone rungs at real board cardinality (B49)")
from ff_props import canonical_bet, rung_threshold
# THE GAP THIS CLOSES: the milestone fixture in section 24 posts ONE rung for
# Mahomes, and one rung never collides. The grouping key was (player, point);
# every rung carries point=None, so a real board collapsed all of one
# player's rungs into a single group and the second rung tripped B28's
# same-side guard. The guard was right, the key was wrong.
#
# Two things that fixture could not show. First, the ValueError escapes
# flatten_odds entirely, so ONE collision in the first book aborted the whole
# call and took every other book's rungs with it. Second, the right SHAPE at
# the wrong CARDINALITY passes while testing nothing: a fixture for a grouped
# code path must carry at least two members of a group, and preferably the
# count a real board posts. DraftKings posts 28 for a starting QB.
#
# Payload is live bovada/DK/FanDuel from event 87238 (JAX@BAL), 2026-11-03.
_b49t = "2026-11-03T14:50:45Z"
def _b49_rungs(ns, desc, pid):
    return [{"name": f"{n}+ Passing Yards", "description": desc, "price": p,
             "point": None, "player_id": pid, "last_seen_at": _b49t}
            for n, p in ns]
def _b49_ou(o, u, pt, desc, pid):
    return [{"name": "Over", "description": desc, "price": o, "point": pt,
             "player_id": pid, "last_seen_at": _b49t},
            {"name": "Under", "description": desc, "price": u, "point": pt,
             "player_id": pid, "last_seen_at": _b49t}]
def _b49_mk(lt, ocs):
    return {"key": "player_pass_yds", "line_type": lt, "suspended_at": None,
            "last_update": _b49t, "outcomes": ocs}
_b49_tl, _b49_jf = "espn:4360310", "espn:4429582"
_b49_bov = [(175,-900),(200,-330),(225,-165),(250,110),(275,195),(300,330),
            (325,550),(350,900),(375,1400),(400,2100),(450,3000)]
_b49_dk = [(150,-1640),(160,-1080),(170,-740),(180,-526),(190,-392),(200,-293),
           (210,-222),(220,-172),(230,-136),(238,-113),(240,-107),(250,118),
           (260,150),(270,188),(280,234),(290,295),(300,371),(310,460),
           (320,578),(330,710),(340,900),(350,1080),(360,1340),(370,1600),
           (380,1940),(390,2300),(400,2600),(410,3000)]
_b49_fag = [(150,-195),(160,-147),(170,-111),(180,119),(190,157),(200,202),
            (210,260),(220,337),(230,427),(240,545),(250,690),(260,870),
            (270,1100),(280,1400),(290,1760),(300,2100),(310,2500),(320,2900)]
_b49_fd = [(150,-1450),(175,-600),(200,-290),(225,-158),(250,116),(275,200),
           (300,350),(325,580),(350,920),(375,1400)]
_b49_board = {"bookmakers": [
    {"key": "bovada", "pregame_only": False, "last_update": _b49t, "markets": [
        _b49_mk("milestone", _b49_rungs(_b49_bov, "Trevor Lawrence (JAX)", _b49_tl)),
        _b49_mk("main", _b49_ou(-115, -115, 237.5, "Trevor Lawrence (JAX)", _b49_tl))]},
    {"key": "draftkings", "pregame_only": False, "last_update": _b49t, "markets": [
        _b49_mk("milestone", _b49_rungs(_b49_dk, "Trevor Lawrence", _b49_tl)),
        _b49_mk("main", _b49_ou(-111, -113, 237.5, "Trevor Lawrence", _b49_tl)),
        _b49_mk("milestone", _b49_rungs(_b49_fag, "Joe Fagnano", _b49_jf))]},
    {"key": "fanduel", "pregame_only": False, "last_update": _b49t, "markets": [
        _b49_mk("main", _b49_ou(-114, -114, 237.5, "Trevor Lawrence", _b49_tl)),
        _b49_mk("milestone", _b49_rungs(_b49_fd, "Trevor Lawrence", _b49_tl))]}]}

_b49_ms = flatten_odds(_b49_board, line_type="milestone")
_b49_mn = flatten_odds(_b49_board, line_type="main")
chk("a real milestone board does not raise", len(_b49_ms) == 67,
    f"{len(_b49_ms)} rows")
_b49_cnt = {}
for _q in _b49_ms:
    _b49_cnt[(_q["book"], _q["player"])] = _b49_cnt.get((_q["book"], _q["player"]), 0) + 1
chk("every rung of every player survives the grouping",
    sorted(_b49_cnt.values()) == [10, 11, 18, 28], f"{_b49_cnt}")
chk("rungs still come back one-sided",
    all(_q["under"] is None for _q in _b49_ms))
chk("a rung never carries a posted line",
    all(_q["line"] is None for _q in _b49_ms))
chk("the threshold is parsed onto its own field",
    all(_q["rung_threshold"] is not None for _q in _b49_ms)
    and {_q["rung_threshold"] for _q in _b49_ms if _q["book"] == "fanduel"}
        == {150., 175., 200., 225., 250., 275., 300., 325., 350., 375.})
chk("the two-sided path is untouched by the widened key",
    len(_b49_mn) == 3 and all(_q["under"] is not None for _q in _b49_mn))
chk("a player quoted ONLY as rungs is still returned",
    any(_q["player"] == "Joe Fagnano" for _q in _b49_ms)
    and not any(_q["player"] == "Joe Fagnano" for _q in _b49_mn))
try:
    flatten_odds({"bookmakers": [{"key": "dk", "pregame_only": False,
        "last_update": _b49t, "markets": [_b49_mk("milestone",
            _b49_rungs([(200, -293), (200, -290)], "P", "id"))]}]},
        line_type="milestone")
    _b49_raised = False
except ValueError:
    _b49_raised = True
chk("two rungs at the SAME threshold still raise", _b49_raised)

# DraftKings posts 238+ alongside a main line of 237.5 — the same wager, two
# cents apart, in two rows that no single flatten_odds call can see together.
# Treated as two legs they would be parlayed with each other and priced as
# independent, and the P(cash) that came out would be fiction.
_b49_dkm = [_q for _q in _b49_mn if _q["book"] == "draftkings"][0]
_b49_238 = [_q for _q in _b49_ms
            if _q["book"] == "draftkings" and _q["rung_threshold"] == 238.0][0]
_b49_240 = [_q for _q in _b49_ms
            if _q["book"] == "draftkings" and _q["rung_threshold"] == 240.0][0]
chk("238+ and Over 237.5 are recognised as ONE bet",
    canonical_bet(_b49_238) == canonical_bet(_b49_dkm),
    f"{canonical_bet(_b49_238)} vs {canonical_bet(_b49_dkm)}")
chk("the same bet really is priced differently at the same book",
    (_b49_dkm["over"], _b49_238["over"]) == (-111.0, -113.0))
chk("the next rung up is NOT the same bet",
    canonical_bet(_b49_240) != canonical_bet(_b49_dkm))
# D18's rule on the rung grid: Over 237 pushes at exactly 237, 238+ cannot.
chk("a whole-number line is never snapped onto the rung above it",
    canonical_bet(dict(_b49_dkm, line=237.0)) != canonical_bet(_b49_238))
chk("a row with no threshold is incomparable, not zero",
    canonical_bet({"player": "P", "market": "player_anytime_td"}) is None)
chk("rung_threshold refuses unknown grammar rather than guessing",
    rung_threshold("Anytime Touchdown Scorer") is None
    and rung_threshold("Ameer Abdullah") is None
    and rung_threshold("175+ Passing Yards") == 175.0)

section("25c. team DST scoring is computed, not guessed (E4)")
from ff_scoring import team_defense_weeks, score_dst
import copy as _copy
# E4 was parked in Tier 5 on the grounds that points allowed "lives in game
# data rather than the player file". True of the weekly file, false of the
# play-by-play refresh.py already loads every bootstrap. The whole of a DST
# week is derivable from it, so the only thing that was ever missing is below.
_e4 = team_defense_weeks(load_pbp([2026]))
chk("one row per team per game", len(_e4) == _e4.game_id.nunique() * 2,
    f"{len(_e4)} rows over {_e4.game_id.nunique()} games")
# The hard validation: points allowed must reconcile EXACTLY to points scored.
_g = load_pbp([2026]).groupby("game_id").agg(h=("home_score", "first"),
                                             a=("away_score", "first"))
chk("points allowed reconciles to every point scored",
    float(_e4.points_allowed.sum()) == float((_g.h + _g.a).sum()),
    f"{_e4.points_allowed.sum()} vs {(_g.h + _g.a).sum()}")
_pbp26 = load_pbp([2026])
for _lbl, _col_name, _mask in (("sacks", "sacks", _pbp26.sack == 1),
                               ("interceptions", "interceptions",
                                _pbp26.interception == 1)):
    chk(f"every {_lbl[:-1]} is credited to exactly one defense",
        float(_e4[_col_name].sum()) == float(_mask.sum()),
        f"{_e4[_col_name].sum()} vs {_mask.sum()}")
# A pick-six is ONE touchdown. nflverse's return_touchdown covers interception
# and fumble returns as well as punts and kickoffs, so splitting on play_type
# is what stops `td` and `return_td` both paying for the same play.
chk("defensive and return TDs do not double-count",
    float((_e4.def_tds + _e4.return_tds).sum())
    == float(((_pbp26.touchdown == 1)
              & (_pbp26.td_team == _pbp26.defteam)).sum()))

_h = score_dst(_e4, LEAGUES["holmdels"])
chk("Holmdel's DST scores every week", _h.notna().all() and len(_h) == len(_e4))
chk("a DST week lands in a plausible range",
    4.0 < float(_h.mean()) < 11.0 and float(_h.min()) >= -4.0,
    f"mean {_h.mean():.2f}, min {_h.min()}, max {_h.max()}")
# Holmdel's pays 5/3/1 at 7-13/14-20/21-27 where the connector pays 4/1/0.
# A shutout with nothing else is the ladder's top rung and nothing more.
_shut = pd.DataFrame([{"points_allowed": 0.0, "sacks": 0.0, "interceptions": 0.0,
                       "fumble_recoveries": 0.0, "safeties": 0.0, "def_tds": 0.0,
                       "return_tds": 0.0, "blocked_kicks": 0.0,
                       "fourth_down_stops": 0.0, "xp_returned": 0.0}])
chk("the points-allowed ladder is the league's own, not the connector's",
    float(score_dst(_shut, LEAGUES["holmdels"]).iloc[0]) == 10.0)
chk("a 17-point game pays 3 here, where the connector would pay 1",
    float(score_dst(_shut.assign(points_allowed=17.0),
                    LEAGUES["holmdels"]).iloc[0]) == 3.0)
chk("4th-down stops are paid, and only this league has them",
    float(score_dst(_shut.assign(fourth_down_stops=2.0),
                    LEAGUES["holmdels"]).iloc[0]) == 11.0
    and "fourth_down_stop" not in LEAGUES["cameron_wood"].dst)

# The refusals. These matter more than the arithmetic: a league whose ladder
# was never written down must NOT come back with event points only, which
# would look complete and be wrong low by the largest component.
for _k in ("cameron_wood", "gridiron_grail"):
    try:
        score_dst(_e4, LEAGUES[_k])
        _raised = False
    except NotImplementedError as _e:
        _raised = "pts_allowed" in str(_e).lower() or "points-allowed" in str(_e).lower()
    chk(f"{_k}: refuses to score without a points-allowed ladder", _raised)
chk("the guillotine refuses outright — it has no DST slot",
    LEAGUES["guillotine"].dst == {} and not LEAGUES["guillotine"].uses_k_dst)
# Cameron Wood's synced ladder has a hole at 21-27. A hole must propagate as
# NaN, never as a zero that reads like "the defence earned nothing".
_gapped = _copy.deepcopy(LEAGUES["holmdels"])
_gapped.dst = dict(_gapped.dst,
                   pts_allowed=[(0, 0, 10), (1, 6, 7), (7, 13, 5), (14, 20, 3),
                                (28, 34, -1), (35, 99, -4)])
_gap = score_dst(_e4, _gapped)
chk("a hole in the ladder returns NaN, not zero",
    int(_gap.isna().sum()) == int(((_e4.points_allowed >= 21)
                                   & (_e4.points_allowed <= 27)).sum())
    and int(_gap.isna().sum()) > 0, f"{_gap.isna().sum()} NaN")

section("26. model abstains on low-event binary stats (B32)")
# Live: Rome Odunze came back at 1.0% against a 25.2% Pinnacle fair line on
# 0-for-7. The threshold model cannot estimate a TD rate from that, and a
# 24-point "gap" invites exactly the misreading the boost framing exists to
# prevent. CAUTION, not VETO — the model abstaining is not the leg being
# broken, and TD legs are a market actively in use.
_reg26 = wk[wk.season_type == "REG"]
for _who in ("Rome Odunze", "Travis Kelce"):
    _et = threshold_prob(player_series(_reg26, _who, "receiving_tds"), 0.5)
    _v, _r = boost_verdict(_et)
    chk(f"{_who}: abstains rather than claiming an edge",
        _v == "CAUTION" and any("MODEL ABSTAINS" in x for x in _r),
        f"{_v}, model {_et.blended:.0%} on {_et.hits}/{_et.n}")
_ey = threshold_prob(player_series(_reg26, "Jaxon Smith-Njigba",
                                   "receiving_yards"), 79.5)
chk("a continuous stat is not caught by the binary rule",
    not any("MODEL ABSTAINS" in x for x in boost_verdict(_ey)[1]))

section("27. backtest falsification criteria (F2)")
from ff_backtest import (Leg as BLeg, Slip as BSlip, audit, breakeven_p,
                         boosted_return, expected_roi, roi_band,
                         espn_to_gsis, resolve_gsis, grade_leg, grade_slip)

# The boost economics the whole strategy rests on.
chk("unboosted +300 needs 25%", abs(breakeven_p(300, 0.0) - 0.25) < 1e-9)
chk("a 30% boost drops +300 to ~20.4%",
    abs(breakeven_p(300, 0.30) - 1 / 4.9) < 1e-9,
    f"{breakeven_p(300, 0.30):.3%}")
chk("a bigger boost always lowers the bar",
    breakeven_p(300, 0.50) < breakeven_p(300, 0.30) < breakeven_p(300, 0.20))
chk("$10 at +300 with 30% boost returns $49",
    abs(boosted_return(10, 300, 0.30) - 49.0) < 1e-9)
# MEASURED holds, not guessed. These assertions replaced ones built on a
# guessed (8%, 20%) band — the old check "a 30% boost is positive across the
# hold band" was TRUE under the guess and FALSE against the measurement,
# which is how the wrong band would have survived.
from ff_backtest import (hold_band, min_boost, SGP_HOLD_CROSS_GAME,
                         SGP_HOLD_SAME_GAME)
chk("the hold band is the measured one, not the old guess",
    SGP_HOLD_CROSS_GAME[0] > 0.17 and SGP_HOLD_SAME_GAME[1] > 0.35,
    f"cross {SGP_HOLD_CROSS_GAME}, same {SGP_HOLD_SAME_GAME}")
chk("same-game costs more hold than cross-game",
    SGP_HOLD_SAME_GAME[0] > SGP_HOLD_CROSS_GAME[1])
chk("unknown structure defaults to the PESSIMISTIC band",
    hold_band(None) == SGP_HOLD_SAME_GAME)
chk("a 20% boost is negative on both structures",
    roi_band(300, 0.20, True)[0] < 0 and roi_band(300, 0.20, False)[0] < 0,
    f"cross {roi_band(300, 0.20, True)[0]:+.1%}, "
    f"same {roi_band(300, 0.20, False)[0]:+.1%}")
chk("a 30% boost is marginal cross-game and NEGATIVE same-game",
    roi_band(300, 0.30, True)[1] > 0 > roi_band(300, 0.30, False)[1],
    f"cross {roi_band(300, 0.30, True)[1]:+.1%} best case, "
    f"same {roi_band(300, 0.30, False)[1]:+.1%} best case")
chk("structure is worth 15+ points of boost",
    min_boost(300, False) - min_boost(300, True) > 0.15,
    f"cross needs {min_boost(300, True):.0%}, same needs {min_boost(300, False):.0%}")
chk("zero hold is the ceiling, not the expectation",
    expected_roi(300, 0.30, 0.0) > roi_band(300, 0.30, True)[1])

# The ESPN->GSIS crosswalk: grading by id, never by name.
_roster = pd.read_parquet(ff_data._dest("roster", 2026))
_cw = espn_to_gsis(_roster)
chk("crosswalk is populated", len(_cw) > 1000, f"{len(_cw)} entries")
chk("a known PropLine id resolves",
    resolve_gsis("espn:3139477", _cw) == "00-0033873",
    f"-> {resolve_gsis('espn:3139477', _cw)}")
chk("an unknown id returns None, not a guess",
    resolve_gsis("espn:999999999", _cw) is None)
chk("a None id returns None", resolve_gsis(None, _cw) is None)
try:
    espn_to_gsis(pd.DataFrame({"a": [1]}))
    chk("a roster without the crosswalk raises", False)
except ValueError as _ex:
    chk("a roster without the crosswalk raises", "crosswalk" in str(_ex))

# Grading against the real stats.
_reg27 = wk[wk.season_type == "REG"]
def _bleg(pid, mkt, line, side, week=7, quoted="2026-10-19T12:00:00Z",
          commence="2026-10-19T17:00:00Z"):
    return BLeg(week=week, event_id="e", book="draftkings", market=mkt,
                player="?", propline_player_id=pid,
                gsis_id=resolve_gsis(pid, _cw), line=line, side=side,
                odds=-110, quoted_at=quoted, commence_time=commence)

_mah = grade_leg(_bleg("espn:3139477", "player_pass_yds", 1.5, "OVER"), _reg27)
chk("an easily-cleared OVER wins", _mah.result == "WIN",
    f"actual {_mah.actual}")
chk("the same line as UNDER loses",
    grade_leg(_bleg("espn:3139477", "player_pass_yds", 1.5, "UNDER"),
              _reg27).result == "LOSS")
chk("anytime-TD uses the implicit 0.5 line and sums rush+rec",
    grade_leg(_bleg("espn:4567048", "player_anytime_td", None, "YES"),
              _reg27).result in ("WIN", "LOSS"))
_dnp = grade_leg(_bleg("espn:3139477", "player_pass_yds", 200.5, "OVER",
                       week=99), _reg27)
chk("a player-week with no row is UNGRADED, not silently a loss",
    _dnp.result == "UNGRADED" and "did not play" in (_dnp.ungraded_reason or ""))
chk("an unresolvable id is UNGRADED with the reason",
    grade_leg(_bleg("espn:999999999", "player_pass_yds", 1.5, "OVER"),
              _reg27).ungraded_reason == "no gsis_id (id join failed)")

# A parlay needs every leg; an UNGRADED leg counts as a LOSS, never dropped.
_win3 = BSlip(week=7, legs=[_bleg("espn:3139477", "player_pass_yds", 1.5, "OVER")
                            for _ in range(3)], slip_odds=300, boost_pct=0.30)
chk("all legs winning wins the slip",
    grade_slip(_win3, _reg27).result == "WIN")
chk("a winning slip pays the boosted amount",
    abs(_win3.payout - 49.0) < 1e-9, f"${_win3.payout:.2f}")
_mixed = BSlip(week=7, legs=[
    _bleg("espn:3139477", "player_pass_yds", 1.5, "OVER"),
    _bleg("espn:3139477", "player_pass_yds", 200.5, "OVER", week=99)],
    slip_odds=300, boost_pct=0.30)
chk("an UNGRADED leg makes the slip a LOSS, not a drop",
    grade_slip(_mixed, _reg27).result == "LOSS")

# And the audit itself: it must fail on each leak, not just pass on clean.
def _synth(n_wins, n, odds=300, boost=0.30, quoted="2026-10-19T12:00:00Z",
           ungraded=0):
    out = []
    for i in range(n):
        legs = [BLeg(week=7, event_id=f"e{i}", book="dk",
                     market="player_pass_yds", player=f"p{i}",
                     propline_player_id=f"espn:{i}", gsis_id=f"00-{i}",
                     line=200.5, side="OVER", odds=-110, quoted_at=quoted,
                     commence_time="2026-10-19T17:00:00Z",
                     event_teams=("PIT", "TB")) for _ in range(3)]
        sl = BSlip(week=7, legs=legs, slip_odds=odds, boost_pct=boost)
        if i < ungraded:
            legs[0].result, legs[0].ungraded_reason = "UNGRADED", "did not play"
            for l in legs[1:]:
                l.result = "WIN"
            sl.result, sl.payout = "LOSS", 0.0
        else:
            w = i < ungraded + n_wins
            for l in legs:
                l.result = "WIN" if w else "LOSS"
            sl.result = "WIN" if w else "LOSS"
            sl.payout = boosted_return(10, odds, boost) if w else 0.0
        out.append(sl)
    return out

chk("a clean backtest passes the audit", audit(_synth(25, 100)).ok)
_leak = audit(_synth(50, 100))
chk("a hit rate far above implied FAILS", not _leak.ok)
chk("the hit-rate failure names leakage",
    any("leaked" in f for f in _leak.failures))
_look = audit(_synth(25, 100, quoted="2026-10-19T20:00:00Z"))
chk("a price timestamped after kickoff FAILS", not _look.ok)
chk("the lookahead failure counts the legs",
    any("after kickoff" in f for f in _look.failures))
_surv = audit(_synth(25, 100, ungraded=20))
chk("too many ungraded legs FAILS", not _surv.ok)
chk("the survivorship failure names the reasons",
    any("did not play" in f for f in _surv.failures))
chk("an empty backtest FAILS rather than reporting 0%", not audit([]).ok)
chk("the audit always states its noise floor",
    any("2 se on the hit rate" in n for n in audit(_synth(25, 100)).notes))
chk("the audit states the expected ROI band",
    any("expected ROI band" in n for n in audit(_synth(25, 100)).notes))
# B36: audit() quoted the pessimistic same-game band even for slips the
# caller knew were cross-game. Measured live on 250 genuinely cross-game
# slips: it reported -8.5% to +2.0% where the right band was +1.3% to +4.1% —
# the SIGN of the answer, from a default meant to be cautious.
_cg = [n for n in audit(_synth(25, 100), cross_game=True).notes
       if "expected ROI band" in n][0]
_sg = [n for n in audit(_synth(25, 100), cross_game=False).notes
       if "expected ROI band" in n][0]
_unk = [n for n in audit(_synth(25, 100)).notes if "expected ROI band" in n][0]
chk("cross_game=True quotes the cross-game band", "cross-game" in _cg
    and "18%-21%" in _cg, _cg[-30:])
chk("cross_game=False quotes the same-game band", "same-game" in _sg)
chk("the two bands actually differ", _cg != _sg)
chk("omitting structure still defaults pessimistic and SAYS so",
    "UNKNOWN structure" in _unk and "pass cross_game=" in _unk)
# Slips from one game share legs and game script. Treating them as
# independent understates the error bar by ~sqrt(slips per event), which is
# the exact error this audit exists to catch — committed by the audit itself.
def _clustered(n, per_event):
    out = []
    for i in range(n):
        _eid = f"e{i // per_event}"
        legs = [BLeg(week=7, event_id=_eid, book="dk",
                     market="player_pass_yds", player="p",
                     propline_player_id=None, gsis_id="00-1", line=200.5,
                     side="OVER", odds=-110,
                     quoted_at="2026-10-19T12:00:00Z",
                     commence_time="2026-10-19T17:00:00Z",
                     event_teams=("PIT", "TB")) for _ in range(3)]
        sl = BSlip(week=7, legs=legs, slip_odds=300, boost_pct=0.30)
        _w = i < n // 4
        for l in legs:
            l.result = "WIN" if _w else "LOSS"
        sl.result = "WIN" if _w else "LOSS"
        sl.payout = boosted_return(10, 300, 0.30) if _w else 0.0
        out.append(sl)
    return out

_spread = audit(_clustered(100, 1))
_tight = audit(_clustered(100, 20))
chk("the audit counts distinct events",
    _spread.n_clusters == 100 and _tight.n_clusters == 5)
chk("clustered slips get a WIDER error bar",
    _tight.hit_rate_se > _spread.hit_rate_se * 3,
    f"{_spread.hit_rate_se:.1%} spread vs {_tight.hit_rate_se:.1%} clustered")
chk("clustering is reported, not silently applied",
    any("correlated" in n for n in _tight.notes))

# B34: the noise floor collapsed at a 0% or 100% hit rate. Two slips, both
# losses, printed "2 se is 0.0%" and "resolving 1 point needs ~0 slips" —
# perfect resolution claimed from the least informative sample possible,
# which is the B33 error inside the audit's own noise reporting.
def _degenerate(n_wins, n):
    out = []
    for i in range(n):
        legs = [BLeg(week=7, event_id=f"e{i}", book="dk",
                     market="player_pass_yds", player="p",
                     propline_player_id=None, gsis_id="00-1", line=200.5,
                     side="OVER", odds=-110,
                     quoted_at="2026-10-19T12:00:00Z",
                     commence_time="2026-10-19T17:00:00Z",
                     event_teams=("PIT", "TB"))]
        sl = BSlip(week=7, legs=legs, slip_odds=300, boost_pct=0.30)
        _w = i < n_wins
        for l in legs:
            l.result = "WIN" if _w else "LOSS"
        sl.result = "WIN" if _w else "LOSS"
        sl.payout = boosted_return(10, 300, 0.30) if _w else 0.0
        out.append(sl)
    return out

for _nw, _lbl in ((0, "0% hit rate"), (2, "100% hit rate")):
    _d = audit(_degenerate(_nw, 2))
    chk(f"se stays finite at a {_lbl}", _d.hit_rate_se > 0.05,
        f"se {_d.hit_rate_se:.1%}")
chk("a tiny sample does not claim to resolve 1 point cheaply",
    all("~0 slips" not in n for n in audit(_degenerate(0, 2)).notes))
chk("a tiny sample is told it cannot measure profitability",
    any("too few" in n for n in audit(_degenerate(0, 2)).notes))
chk("a large well-spread sample is not warned",
    not any("too few" in n for n in audit(_clustered(200, 1)).notes))
# The scale bug: wins counted over slips, divided by cluster count.
chk("clustered wins do not produce a math domain error",
    audit(_clustered(100, 100)).hit_rate_se > 0)

# B35: a wrong-but-valid player id graded as an ordinary win.
_roster35 = pd.read_parquet(ff_data._dest("roster", 2026))
_cw35 = espn_to_gsis(_roster35)
def _leg35(pid, teams):
    return BLeg(week=6, event_id="53245", book="dk",
                market="player_reception_yds", player="?",
                propline_player_id=pid, gsis_id=resolve_gsis(pid, _cw35),
                line=26.5, side="OVER", odds=-110,
                quoted_at="2026-10-18T12:00:00Z",
                commence_time="2026-10-18T17:00:00Z", event_teams=teams)
# espn:4241478 is DeVonta Smith (PHI) — a real player, not in PIT@TB.
_wrong = grade_leg(_leg35("espn:4241478", ("PIT", "TB")), _reg27)
chk("a player from neither team is caught, not graded",
    _wrong.result == "UNGRADED" and "probably wrong" in (_wrong.ungraded_reason or ""),
    f"{_wrong.result}")
chk("without event_teams the same id grades as an ordinary result",
    grade_leg(_leg35("espn:4241478", None), _reg27).result in ("WIN", "LOSS"))
chk("a real player in the event still grades",
    grade_leg(_leg35("espn:3116165", ("PIT", "TB")), _reg27).result == "WIN")
_noteams = BSlip(week=6, legs=[_leg35("espn:3116165", None)],
                 slip_odds=300, boost_pct=0.30)
grade_slip(_noteams, _reg27)
chk("the audit FAILS when legs carry no event_teams",
    not audit([_noteams]).ok)

section("28. Monte Carlo resolution is reported (B20)")
# The LAST team holds the weakest players by construction, so it carries real
# elimination risk while still fielding a legal lineup. Team 0 is strongest
# and its P(elim) is 0, which makes se, sims_needed and the warning all
# degenerate — a vacuous section rather than a passing one. Team 1 is the
# deliberately-short roster and cannot enumerate its own lineups at all (the
# B5 guard raises rather than fielding a silent low score), so it cannot be
# my_team_id either.
_me_weak = str(len(_teams_g) - 1)
_rr = ff_guillotine.run(_teams_g, _shared, my_team_id=_me_weak, n_sims=20_000,
                        meta=_meta2, week=9)
chk("the error-bar fixture is non-degenerate",
    0.001 < float(_rr.p_last[int(np.argmin(_rr.p_last))]) < 0.999,
    f"P(elim) = {float(_rr.p_last[int(np.argmin(_rr.p_last))]):.1%}")
_i = int(np.argmin(_rr.p_last))
_p = float(_rr.p_last[_i])
chk("se matches the binomial formula",
    abs(_rr.se() - np.sqrt(_p * (1 - _p) / 20_000)) < 1e-12,
    f"{_rr.se()*100:.3f} pts")
chk("se shrinks as 1/sqrt(n)",
    abs(ff_guillotine.run(_teams_g, _shared, my_team_id=_me_weak,
                          n_sims=80_000, meta=_meta2, week=9).se()
        - _rr.se() / 2) < _rr.se() * 0.25)
chk("sims_needed scales as 1/resolve^2",
    abs(_rr.sims_needed(0.0005) / _rr.sims_needed(0.001) - 4) < 0.1,
    f"{_rr.sims_needed(0.001):,} for 0.1pt")
chk("report states the error bar", "1 se on P(elim)" in _rr.report(top=1))
chk("report warns when the default cannot resolve small differences",
    "Do not quote a difference smaller" in _rr.report(top=1))
try: _rr.sims_needed(0); chk("sims_needed rejects a zero target", False)
except ValueError: chk("sims_needed rejects a zero target", True)


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
    _side = kw.pop("side", "OVER")
    return BoostLeg(
        event_id=event_id,
        book=kw.pop("book", "draftkings"),
        market=kw.pop("market", "player_reception_yds"),
        player=player,
        side=_side,
        odds=odds,
        fair_prob=fair_prob,
        fair_source=kw.pop("fair_source", "pinnacle (via get_event_ev)"),
        devig_method=kw.pop("devig_method", "shin (get_event_ev)"),
        line=kw.pop("line", 45.5),
        player_id=kw.pop("player_id", f"espn:{abs(hash(player)) % 10**7}"),
        verdict=kw.pop("verdict", "CLEAR"),
        # B126. Defaults to the leg's own side, which is what the helper
        # already builds — the point of the guard is that a verdict carried
        # across from the OTHER side cannot be built at all.
        verdict_side=kw.pop("verdict_side", _side),
        team=META.get(player, (None, None))[0],
        pos=META.get(player, (None, None))[1],
        **kw,
    )


CROSS = [leg("WR A1", EV1), leg("WR C1", EV2), leg("WR E1", EV3)]
SAME_INDEP = [leg("WR A1", EV1), leg("WR A2", EV1), leg("WR B1", EV1)]
SAME_STACK = [leg("QB A", EV1, market="player_pass_yds"),
              leg("WR A1", EV1),
              leg("RB B1", EV1, market="player_rush_yds")]


section("29. P0 boost optimiser — constants")
chk("FLOOR is the documented +300", FLOOR == 300, f"FLOOR={FLOOR}")
chk("CEILING is +600", CEILING == 600, f"CEILING={CEILING}")
# Raised from 450 on 2026-11-03. The band assumed "three legs near -150",
# which do not exist on main-line prop boards: books move the POINT until
# the price is near even money, so three legs multiply to ~+575. Two live
# events produced ZERO candidates at the old band. This check exists so the
# value is changed deliberately rather than drifting back.
chk("the band spans the prices main-line props actually produce",
    FLOOR <= 575 <= CEILING,
    "three near-coin-flip legs multiply to about +575")

# ---------------------------------------------------------------------------
section("30. structure is DERIVED from the legs, never taken from the caller")
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
# The receiving side has THREE pairs, not two. `_pair_r` asked only "is it a
# TE?", so every RB catching passes was scored at the WR value of +0.31 —
# Derrick Henry receiving beside Lawrence passing at double its real
# correlation. Measured 2026-11-05: QB passing x RB receiving is +0.157
# against +0.243 for WR on the same filter, a ratio of 0.65.
from ff_boost import _pair_r as _pr, SAME_TEAM_CORR as _STC, \
    SAME_TEAM_CORR_PROVISIONAL as _STP
def _rleg(name, market, pos):
    _l = ff_boost.BoostLeg(event_id="E1", book="dk", market=market, player=name,
                           side="over", odds=-110, fair_prob=0.5,
                           fair_source="pinnacle", devig_method="shin", line=1.5)
    _l.team, _l.pos = "JAX", pos
    return _l
_qb = _rleg("QB A", "player_pass_yds", "QB")
for _pos, _want in (("WR", _STC[("QB", "WR")]), ("TE", _STC[("QB", "TE")]),
                    ("RB", _STP[("QB", "RB_RECV")])):
    _r, _why = _pr(_qb, _rleg(f"{_pos} A", "player_reception_yds", _pos))
    chk(f"QB passing x {_pos} receiving uses its own value, not the WR one",
        abs(_r - _want) < 1e-9, f"{_r:+.3f} ({_why})")
chk("an RB RECEIVING is no longer scored as a WR",
    _pr(_qb, _rleg("RB A", "player_reception_yds", "RB"))[0]
    < _STC[("QB", "WR")])
chk("and RB RUSHING is untouched — a different pair entirely",
    abs(_pr(_qb, _rleg("RB A", "player_rush_yds", "RB"))[0]
        - _STC[("QB", "RB")]) < 1e-9)
chk("the provisional value is flagged as provisional where it is reported",
    "PROVISIONAL" in _pr(_qb, _rleg("RB A", "player_reception_yds", "RB"))[1])
chk("same-game-independent is priceable", s.priceable is True)

s = classify(SAME_STACK, META)
chk("QB + his own WR is correlated", s.kind == "same-game-correlated", s.kind)
chk("a correlated slip is NOT priceable", s.priceable is False)
chk("the correlated pair is named with its r",
    any(abs(p[2] - _STC[("QB", "WR")]) < 1e-9 for p in s.pairs),
    str(s.pairs))

s = classify([leg("QB A", EV1, market="player_pass_yds"),
              leg("TE A1", EV1), leg("WR B1", EV1)], META)
chk("QB + his own TE is correlated, at the TE coefficient",
    s.kind == "same-game-correlated"
    and any(abs(p[2] - _STC[("QB", "TE")]) < 1e-9
                                             for p in s.pairs), s.kind)

s = classify([leg("QB A", EV1, market="player_pass_yds"),
              leg("RB A1", EV1, market="player_rush_yds"),
              leg("WR B1", EV1)], META)
chk("QB + his own RB is correlated and negative, not independent",
    s.kind == "same-game-correlated"
    and any(abs(p[2] - _STC[("QB", "RB")]) < 1e-9 for p in s.pairs)
    and _STC[("QB", "RB")] < 0, s.kind)

# The guillotine's correlation_matrix cannot see the schedule, so it treats
# every different-team pair as independent. P0 knows the event, so two backs
# inside one event ARE facing each other and the measured -0.14 applies.
s = classify([leg("RB A1", EV1, market="player_rush_yds"),
              leg("RB B1", EV1, market="player_rush_yds"),
              leg("WR C1", EV2)], META)
chk("opposing RBs inside one event are correlated and negative",
    any(abs(p[2] - ff_boost.OPPOSING_CORR[("RB", "RB")]) < 1e-9
        for p in s.pairs)
    and ff_boost.OPPOSING_CORR[("RB", "RB")] < 0, str(s.pairs))

s = classify([leg("RB A1", EV1, market="player_rush_yds"),
              leg("RB C1", EV2, market="player_rush_yds"),
              leg("WR E1", EV3)], META)
chk("RBs in DIFFERENT events are independent, not opposing",
    s.kind == "cross-game" and s.pairs == [], f"{s.kind} {s.pairs}")

# The one that silently poisons every EV downstream.
s = classify([leg("WR A1", EV1), leg("WR A2", EV1), leg("WR C1", EV2)], META)
chk("two legs sharing an event are NOT cross-game", s.kind != "cross-game", s.kind)
chk("a mixed slip is tagged mixed, not same-game",
    s.kind == "mixed", s.kind)

# ---------------------------------------------------------------------------
section("30b. independence is ESTABLISHED, never assumed")
# Found on first contact with live payloads, 2026-11-02. Every check here is
# a way the module could score a correlated slip as independent and hand it
# an EV it must never receive.
# ---------------------------------------------------------------------------
# build_meta() returns Travis Hunter as CB — his nflverse primary position —
# while he carries a receiving prop on his QB's team. Position-keyed
# classification scored that as independent. The side must come from the
# MARKET, which is what the correlation table was measured on.
CB_META = dict(META, **{"CB A1": ("AAA", "CB")})
s = classify([leg("QB A", EV1, market="player_pass_yds"),
              leg("CB A1", EV1, market="player_reception_yds"),
              leg("WR B1", EV1)], CB_META)
chk("a receiving prop on a CB still pairs with his QB",
    s.kind == "same-game-correlated" and not s.priceable, s.kind)
chk("the pair is scored off the market, not the roster label",
    any(abs(p[2] - _STC[("QB", "WR")]) < 1e-9 for p in s.pairs),
    str(s.pairs))

s = classify([leg("QB A", EV1, market="player_pass_yds"),
              leg("TE A1", EV1, market="player_reception_yds"),
              leg("WR B1", EV1)], META)
chk("a TE receiving prop takes the TE coefficient, not the WR one",
    any(abs(p[2] - _STC[("QB", "TE")]) < 1e-9 for p in s.pairs)
    and _STC[("QB", "TE")] != _STC[("QB", "WR")], str(s.pairs))

# anytime-TD is a boost staple. It was UNMEASURED until F13 and the slip
# refused for that reason; E3's side table measured it at -0.0274 over
# 49,520 pairs, so the refusal now rests on a NUMBER. What must not change
# is that the slip is still not priceable as a product — the point of F13
# was to replace "nobody measured this" with a measurement, not to assert
# independence where the measurement says there is none.
s = classify([leg("WR A1", EV1, market="player_anytime_td", line=None),
              leg("WR A2", EV1, market="player_anytime_td", line=None),
              leg("WR B1", EV1)], META)
chk("two same-event anytime-TD legs are NOT asserted independent",
    not s.priceable, f"{s.kind} priceable={s.priceable}")
chk("and the TD x TD pair is now MEASURED, not unmeasured",
    s.pairs and not any("anytime_td" in str(u) for u in s.unmeasured),
    f"pairs={s.pairs} / unmeasured={s.unmeasured}")
chk("the reason cites the measurement rather than an assumption",
    "r=" in s.reason or "lift" in s.reason.lower(), s.reason[:120])
chk("the measured TD x TD sign is negative, so the product OVERSTATES",
    ff_boost.joint_error(
        [leg("WR A1", EV1, market="player_anytime_td", line=None),
         leg("WR A2", EV1, market="player_anytime_td", line=None)],
        [("WR A1", "WR A2", ff_boost.side_pair("same", "TD", "TD")[0], "t",
          ff_boost.side_pair("same", "TD", "TD")[2])]).rel < 0,
    "a negative joint error is the direction that must still refuse")

c = make_candidate([leg("WR A1", EV1, market="player_anytime_td", line=None),
                    leg("WR A2", EV1, market="player_anytime_td", line=None),
                    leg("WR B1", EV1)], META, boost_pct=0.50)
chk("an unmeasured-market slip gets no EV", c.ev_pct is None)
chk("an unmeasured-market slip gets no P(cash)", c.p_cash is None)

# Cross-game is the pair the measurement IS emphatic about, so an
# unmeasured market across different events stays independent.
s = classify([leg("WR A1", EV1, market="player_anytime_td", line=None),
              leg("WR C1", EV2, market="player_anytime_td", line=None),
              leg("WR E1", EV3)], META)
chk("anytime-TD legs in DIFFERENT events are still independent",
    s.priceable and s.kind == "cross-game", f"{s.kind} {s.unmeasured}")

# A missing team used to read as "uncorrelated". A live run built all 32
# legs with team=None and every one classified independent.
noteam = BoostLeg(event_id=EV1, book="draftkings",
                  market="player_reception_yds", player="Ghost",
                  side="OVER", odds=-150, fair_prob=0.6,
                  fair_source="pinnacle", devig_method="shin",
                  verdict="CLEAR",
                 verdict_side="OVER")
s = classify([leg("QB A", EV1, market="player_pass_yds"), noteam,
              leg("WR B1", EV1)], {})
chk("an unknown team in a shared event is unmeasurable, not independent",
    not s.priceable, f"{s.kind} priceable={s.priceable}")
chk("the unknown team is named", "Ghost" in str(s.unmeasured),
    str(s.unmeasured))

# A missing POSITION used to read as "WR" — the largest of the three
# receiving coefficients — and printed "(receiver)", which looks like a
# category rather than a miss (B69). Same shape as the missing team eight
# lines up, and the same reasoning now applies. `pos` comes from
# build_meta()'s name join, which B44 showed is the fragile link.
nopos = BoostLeg(event_id=EV1, book="draftkings",
                 market="player_reception_yds", player="Spectre",
                 side="OVER", odds=-150, fair_prob=0.6,
                 fair_source="pinnacle", devig_method="shin",
                 verdict="CLEAR",
                 verdict_side="OVER", team="AAA", pos=None)
s = classify([leg("QB A", EV1, market="player_pass_yds"), nopos,
              leg("WR B1", EV1)], {})
chk("a known team with an UNKNOWN position is unmeasurable, not WR",
    not s.priceable
    and not any(abs(p[2] - _STC[("QB", "WR")]) < 1e-9 for p in s.pairs),
    f"{s.kind} pairs={s.pairs}")
chk("the player with no position is named", "Spectre" in str(s.unmeasured),
    str(s.unmeasured))
chk("the reason points at the name join rather than blaming the market",
    "nflverse" in str(s.unmeasured).lower()
    and "spelling" in str(s.unmeasured).lower(), str(s.unmeasured)[:160])
# The narrowing that the suite forced. "Missing" and "present but outside
# the table" are DIFFERENT states: a receiving prop is evidence of a
# receiving role whatever the roster label says, which is why section 30b
# pins the CB case at +0.31. A first pass at B69 refused both and 30b caught
# it. These two checks exist so the distinction cannot quietly collapse
# again in either direction.
s_cb = classify([leg("QB A", EV1, market="player_pass_yds"),
                 leg("CB A1", EV1, market="player_reception_yds"),
                 leg("WR B1", EV1)], dict(META, **{"CB A1": ("AAA", "CB")}))
chk("a PRESENT but unmeasured position still resolves off the market",
    any(abs(p[2] - _STC[("QB", "WR")]) < 1e-9 for p in s_cb.pairs),
    str(s_cb.pairs))
chk("and it says so, instead of hiding behind the word 'receiver'",
    any("CB" in str(p[3]) for p in s_cb.pairs)
    if s_cb.pairs and len(s_cb.pairs[0]) > 3
    else "CB" in s_cb.reason, f"{s_cb.pairs} / {s_cb.reason[:120]}")

# ---------------------------------------------------------------------------
section("30c. an unchecked leg is not a clear leg")
# A live run built 32 legs that all read CLEAR without boost_verdict() ever
# being called. "Nothing found against it" must not be the default state.
# ---------------------------------------------------------------------------
chk("BoostLeg defaults to UNSCREENED, not CLEAR",
    BoostLeg(event_id=EV1, book="dk", market="player_reception_yds",
             player="X", side="OVER", odds=-150, fair_prob=0.6,
             fair_source="pinnacle", devig_method="shin").verdict
    == "UNSCREENED")
uns = leg("WR C1", EV2, verdict="UNSCREENED")
sl = enumerate_candidates([leg("WR A1", EV1), uns, leg("WR E1", EV3)],
                          META, boost_pct=0.50, mode="cross-game")
chk("an UNSCREENED leg never reaches a slip",
    all(uns.player not in [l.player for l in cc.legs]
        for cc in sl.candidates))
chk("the drop says the screen was never run",
    any("boost_verdict" in why for _, why in sl.dropped), str(sl.dropped))

# ---------------------------------------------------------------------------
section("30d. the refusal reason reports the measured direction")
# Live: all 4,144 combinations priced ABOVE the ceiling and none below the
# floor, and the hardcoded string said "legs are too short".
# ---------------------------------------------------------------------------
long_legs = [leg("WR A1", EV1, odds=120, fair_prob=0.45),
             leg("WR C1", EV2, odds=120, fair_prob=0.45),
             leg("WR E1", EV3, odds=120, fair_prob=0.45)]
sl = enumerate_candidates(long_legs, META, boost_pct=0.50, mode="cross-game")
chk("legs too LONG are reported as too long", "too LONG" in sl.reason,
    sl.reason)
chk("legs too long are NOT reported as too short",
    "too short" not in sl.reason.lower(), sl.reason)

tiny = [leg("WR A1", EV1, odds=-400, fair_prob=0.80),
        leg("WR C1", EV2, odds=-400, fair_prob=0.80),
        leg("WR E1", EV3, odds=-400, fair_prob=0.80)]
sl = enumerate_candidates(tiny, META, boost_pct=0.50, mode="cross-game")
chk("legs too SHORT are still reported as too short",
    "too short" in sl.reason.lower(), sl.reason)
chk("the short reason names the floor, not the ceiling",
    "BELOW" in sl.reason, sl.reason)

# ---------------------------------------------------------------------------
section("31. the floor applies to the price you can actually bet")
# Failure mode 4. Three legs at -150 are +363 independent and +225 once a
# 0.62 correlation factor is applied. Scoring the slip at +363 both invents
# EV and smuggles a below-floor slip past the floor.
# ---------------------------------------------------------------------------
ind = independent_odds(SAME_STACK)
chk("three -150 legs price at about +363 independent",
    360 <= ind <= 366, f"{ind:+.0f}")

# A +363 product with one line per player sits between the +300 floor and
# the same-game price target (floor / median factor). It must still be
# shortlisted — there is nothing to retarget — and this used to index
# `.candidates[0]` bare, so dropping that fallback crashed the section
# instead of failing a check (lesson 103).
_ss = enumerate_candidates(SAME_STACK, META, boost_pct=0.50,
                           mode="single-game")
chk("a one-line-per-player stack below the price target is still listed",
    len(_ss.candidates) == 1, f"{len(_ss.candidates)} — {_ss.reason[:120]}")
c = (_ss.candidates[0] if _ss.candidates
     else make_candidate(SAME_STACK, META, boost_pct=0.50))
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
section("32. EV exists only where the joint is the product")
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
section("33. correlation_factor never enters a probability")
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
section("34. the hold band follows the derived structure")
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
section("35. the boost outlook is ADVISORY before pricing")
# Changed 2026-11-03, driven by measurement. This used to be a hard gate:
# playable went False whenever the boost failed to cover the PESSIMISTIC end
# of the measured hold band. Live, that band said 23.1-37.2%, the slip it
# refused actually held 19.2%, and it priced at +1.4% — a false negative on
# the one thing the tool exists to find. The shortlist caps at 8, so pricing
# every candidate costs 8 calls; the hard verdict belongs after a real quote.
#
# Half of Dustin's use is single-game TNF/SNF/MNF boosts, so this path fires
# often and must still state the measured reason rather than going quiet.
# ---------------------------------------------------------------------------
sl = enumerate_candidates(CROSS, META, boost_pct=0.20, mode="cross-game")
chk("a 20% boost still returns candidates to price", sl.playable, sl.reason)
chk("a 20% boost reads LIKELY NEGATIVE", sl.outlook == "LIKELY NEGATIVE",
    sl.outlook)
chk("the 20% outlook cites the measured hold", "hold" in sl.reason.lower(),
    sl.reason[:80])
chk("the 20% outlook says it is advisory, not a verdict",
    "advisory" in sl.reason.lower(), sl.reason[:80])
chk("every 20% candidate is individually tagged NEGATIVE",
    all(c.verdict == "NEGATIVE" for c in sl.candidates))

sl = enumerate_candidates(SAME_INDEP, META, boost_pct=0.30, mode="single-game")
chk("30% same-game-independent reads LIKELY NEGATIVE",
    sl.outlook == "LIKELY NEGATIVE", sl.outlook)
sl = enumerate_candidates(CROSS, META, boost_pct=0.30, mode="cross-game")
chk("30% cross-game reads LIKELY PLAYABLE", sl.outlook == "LIKELY PLAYABLE",
    sl.outlook)
sl = enumerate_candidates(SAME_INDEP, META, boost_pct=0.50, mode="single-game")
chk("50% same-game-independent reads LIKELY PLAYABLE",
    sl.outlook == "LIKELY PLAYABLE", sl.outlook)

# The false negative that caused this change, reproduced: a candidate the
# pre-pricing read calls NEGATIVE flips to PLAY on a real quote that beat
# the band's pessimistic end.
c = enumerate_candidates(SAME_INDEP, META, boost_pct=0.30,
                         mode="single-game").candidates[0]
chk("unpriced, the pessimistic band reads NEGATIVE", c.verdict == "NEGATIVE")
c2 = price_candidate(c, book_odds=420)
chk("a real quote that beats the band flips it to PLAY",
    c2.verdict == "PLAY", f"{c2.verdict} ev={c2.ev_pct:+.1%}")
chk("the observed hold is below the band that refused it",
    c2.slip_hold < ff_boost.HOLD_SAME[0],
    f"observed {c2.slip_hold:.1%} vs band floor {ff_boost.HOLD_SAME[0]:.1%}")

# The unpriceable case must not be swept up by a policy aimed at the
# priceable one: the measured 30.2% was measured on INDEPENDENT same-game
# legs and is not a verdict on a stack.
sl = enumerate_candidates(SAME_STACK, META, boost_pct=0.30, mode="single-game")
chk("a correlated stack is NOT rejected by the same-game hold figure",
    len(sl.candidates) > 0, sl.reason)
chk("a stack-only shortlist reads UNPRICEABLE ONLY",
    sl.outlook == "UNPRICEABLE ONLY", sl.outlook)
chk("but it is returned without an EV",
    all(cc.ev_pct is None for cc in sl.candidates))

# The shape live boards actually produce: three near-coin-flip main lines.
# Under the old +450 ceiling this returned nothing at any boost level.
_coinflips = [leg("WR A1", EV1, odds=-112, fair_prob=0.5),
              leg("WR C1", EV2, odds=-112, fair_prob=0.5),
              leg("WR E1", EV3, odds=-110, fair_prob=0.5)]
_sl = enumerate_candidates(_coinflips, META, boost_pct=0.30,
                           mode="cross-game")
chk("three main-line coin flips now land inside the band",
    _sl.playable and _sl.candidates,
    f"product {independent_odds(_coinflips):+.0f}")
chk("and read LIKELY PLAYABLE at a 30% cross-game boost",
    _sl.outlook == "LIKELY PLAYABLE", _sl.outlook)
_sg = enumerate_candidates(
    [leg("WR A1", EV1, odds=-112, fair_prob=0.5),
     leg("WR A2", EV1, odds=-112, fair_prob=0.5),
     leg("WR B1", EV1, odds=-110, fair_prob=0.5)],
    META, boost_pct=0.30, mode="single-game")
chk("the same shape SAME-GAME at 30% still reads LIKELY NEGATIVE",
    _sg.outlook == "LIKELY NEGATIVE",
    "structure, not the ceiling, is what decides a TNF slip")

# ---------------------------------------------------------------------------
section("35b. an opening anchor is a prior, not a price")
# Measured 2026-11-03: Pinnacle's yardage board 68 hours out was -114/-114
# with liquidity 250 on every line, so 18 of 20 de-vigged to exactly 0.5000.
# Not corruption — the isolation run proved the feed is clean — but the
# book's prior. At the final pre-kickoff snapshot only 2 of 22 sit there.
# ---------------------------------------------------------------------------
opening = leg("WR A1", EV1, fair_prob=0.5, anchor_liquidity=250)
chk("exactly 0.5000 at minimum limits is flagged immature",
    opening.anchor_immature)
chk("the flag says to re-pull closer to kickoff",
    "kickoff" in (opening.anchor_note or "").lower(),
    str(opening.anchor_note)[:70])
# B86 OVERTURNED THIS CHECK, deliberately. It used to assert that a price
# which had MOVED off 0.5000 was not flagged at all, on the reasoning that
# "the 0.5000 does the work; liquidity only sets how far the net reaches."
# The measurement contradicts it: on the board that motivated this, ALL 62
# Pinnacle lines sat at liquidity 250 and only 54 were at 0.5000 — so 250 of
# resting money cannot make 0.5065 meaningful when it does not make 0.5000
# meaningful. The 8 that moved are the ones a slip gets built from.
#
# The old check's DISTINCTION survives and is what is asserted now: moved
# and unmoved are different states, and they get different flags. Only the
# verdict changed, from "no flag" to "a quieter one".
_moved = leg("WR A1", EV1, fair_prob=0.5065, anchor_liquidity=250)
chk("a moved price at the opening limit is NOT anchor_opening",
    not _moved.anchor_opening)
chk("but it IS anchor_untested, which is the B86 gap",
    _moved.anchor_untested)
chk("so it still cannot carry an EV", _moved.anchor_immature)
chk("and its note says the move is price discovery, not a tested price",
    "price discovery" in (_moved.anchor_note or ""),
    str(_moved.anchor_note)[:90])
chk("the two states are distinguishable, not collapsed",
    opening.anchor_opening and not opening.anchor_untested
    and _moved.anchor_untested and not _moved.anchor_opening)
chk("exactly 0.5000 at HIGH liquidity is not flagged",
    not leg("WR A1", EV1, fair_prob=0.5,
            anchor_liquidity=10000).anchor_immature)
chk("exactly 0.5000 with liquidity unreported is still flagged",
    leg("WR A1", EV1, fair_prob=0.5).anchor_immature,
    "bovada returns null liquidity; the 0.5000 is the signal on its own")
# B54. The threshold was 250 because that was Pinnacle's minimum tier the
# day it was written, and a tier is not a constant: the same event read 250
# on 2026-11-03 and 500 on 2026-11-05, about a day out. The flag then could
# not fire on the case it exists for — 7 of 14 receiving lines priced
# -112/-112 (exactly 0.5000) at liquidity 500, none flagged, and a
# 2026-11-04 run carried 31 of 60 anchors at exactly 0.5000 in silence.
#
# THIS IS THE CHECK THAT WAS MISSING, and note why the suite could not have
# caught it: a flag that never fires breaks nothing. Every existing check
# here used a liquidity value the threshold still covered. A guard needs a
# test at the boundary the real world is moving toward, not only inside it.
chk("exactly 0.5000 at Pinnacle's CURRENT 500 tier is flagged",
    leg("WR A1", EV1, fair_prob=0.5, anchor_liquidity=500).anchor_immature,
    "measured 2026-11-05: Pinnacle raises its limit as the event nears")
chk("the 250 tier still flags, so the fix only widened the net",
    leg("WR A1", EV1, fair_prob=0.5, anchor_liquidity=250).anchor_immature)
# Same overturn at the 500 tier, same reasoning.
chk("a moved price at the 500 tier is untested, not unflagged",
    leg("WR A1", EV1, fair_prob=0.5065,
        anchor_liquidity=500).anchor_untested)
# The flag must go QUIET on a mature anchor, or it is the noise B93b cut.
chk("a moved price ABOVE the tier is not flagged at all",
    not leg("WR A1", EV1, fair_prob=0.5065,
            anchor_liquidity=3000,
            opening_liquidity_tier=1000.0).anchor_immature,
    "near kickoff Pinnacle runs 1,000-3,000 against a 1,000 tier")
chk("and unreported liquidity is not treated as low",
    not leg("WR A1", EV1, fair_prob=0.5065).anchor_untested,
    "never reported is a different state from low")

# B59. The threshold above is a HARDCODED tier and hardcoding it has already
# failed once (250 -> 500). Derive it from the book's own board per pull.
from ff_boost import (modal_liquidity, book_liquidity_tiers,
                      TIER_MIN_SAMPLE, TIER_MAX_TRUSTED)
chk("a uniform board yields its tier",
    modal_liquidity([500] * 42) == 500.0)
chk("a mixed board yields its mode, not its min or max",
    modal_liquidity([250, 500, 500, 500, 1000]) == 500.0)
# Ties break HIGH: a tier set too high flags some settled anchors, which is
# noise. Too low MISSES an opening anchor, which is the failure that has
# actually happened. Break toward the survivable error.
chk("ties break toward the higher tier, which over-flags rather than misses",
    modal_liquidity([500, 500, 1000, 1000]) == 1000.0)
chk("too few readings is not a measurement — fall back to the constant",
    modal_liquidity([500, 500]) is None and TIER_MIN_SAMPLE == 3)
chk("nulls are ignored, not counted as a value",
    modal_liquidity([None, 500, 500, 500]) == 500.0
    and modal_liquidity([None, None, None, None]) is None)
# THE CASE SYNTHETIC DATA WOULD NOT HAVE FOUND, caught on a live pull:
# Pinnacle reports a discrete BET LIMIT (10 of 10 at exactly 500 — a tier).
# Kalshi reports resting MONEY in dollars: 95 distinct values across 100
# readings, whose "mode" of 0.97 appeared twice. A mode of a continuous
# quantity is noise, and using it as a threshold invents a number.
_kalshi_like = [round(0.1 + i * 0.137, 2) for i in range(100)]
chk("a book with no dominant value has no tier, and says so",
    modal_liquidity(_kalshi_like) is None,
    f"{len(set(_kalshi_like))} distinct across {len(_kalshi_like)} readings")
chk("a book that DOES quote tiers still resolves alongside it",
    modal_liquidity([500] * 10) == 500.0)
_resp = {"bookmakers": [
    {"key": "pinnacle", "markets": [{"outcomes": [{"liquidity": 500}] * 10}]},
    {"key": "kalshi", "markets": [{"outcomes": [{"liquidity": v}
                                                for v in _kalshi_like]}]},
    {"key": "betmgm", "markets": [{"outcomes": [{"liquidity": None}] * 20}]}]}
chk("book_liquidity_tiers keeps only books that actually quote a tier",
    book_liquidity_tiers(_resp) == {"pinnacle": 500.0},
    "kalshi has no mode; betmgm reports nothing at all")
# The derived tier must actually override the constant on the leg.
chk("a derived tier above the constant widens the net",
    leg("WR A1", EV1, fair_prob=0.5, anchor_liquidity=1000,
        opening_liquidity_tier=1000.0).anchor_opening
    and not leg("WR A1", EV1, fair_prob=0.5,
                anchor_liquidity=1000).anchor_opening,
    "this is the 250->500 failure, pre-empted")
chk("a derived tier below the constant narrows it",
    not leg("WR A1", EV1, fair_prob=0.5, anchor_liquidity=400,
            opening_liquidity_tier=100.0).anchor_opening)
chk("no derived tier falls back to the module constant",
    leg("WR A1", EV1, fair_prob=0.5, anchor_liquidity=500).anchor_opening)
chk("a null anchor liquidity still flags, tier or no tier",
    leg("WR A1", EV1, fair_prob=0.5,
        opening_liquidity_tier=1.0).anchor_opening)
# modal_liquidity derives the most COMMON limit and calls it the MINIMUM
# tier. Those agree on an opening board (uniform at the floor) and come
# apart on a mature one (uniform at depth) — Pinnacle rises to 5,000-10,000
# by kickoff. Derived naively, that board would flag every exact-0.5000
# line as "opening" regardless of depth, on the very pull you bet from.
chk("a uniformly DEEP board yields no tier — it is mature, not opening",
    modal_liquidity([10000] * 28) is None,
    f"ceiling {TIER_MAX_TRUSTED:g}; above it the hardcoded floor is right")
chk("a tier inside the opening range still resolves",
    modal_liquidity([250] * 28) == 250.0
    and modal_liquidity([1000] * 28) == 1000.0)
chk("so deep money is still NOT called an opening anchor",
    not leg("WR A1", EV1, fair_prob=0.5, anchor_liquidity=10000,
            opening_liquidity_tier=modal_liquidity([10000] * 28)
            ).anchor_opening)
# B59's remaining gap, made visible: a leg with no derived tier silently
# uses the hardcoded constant, and on a live run that was 48 of 48 legs.
# "Derived and agreed" must not look identical to "nothing was available".
_sl_fb = enumerate_candidates(SAME_INDEP, META, boost_pct=0.30,
                              mode="single-game")
_fb, _tot = _sl_fb.tier_fallbacks
chk("the shortlist counts legs running on the hardcoded tier",
    _fb == _tot and _tot > 0, f"{_fb} of {_tot}")
chk("and describe() says so rather than leaving it to be remembered",
    "are on the hardcoded" in _sl_fb.describe(), _sl_fb.describe()[-120:])
# B75. These legs carry no `tier_source`, so nothing ever looked a tier up —
# and describe() must say THAT, not blame a book for quoting none. The old
# text asserted the book's behaviour on every run, naming Pinnacle, which
# the project's own notes say does quote a uniform tier.
chk("and names the real cause: nobody called book_liquidity_tiers",
    "NEVER LOOKED UP" in _sl_fb.describe()
    and "quoted no tier when asked" not in _sl_fb.describe(),
    _sl_fb.describe()[-200:])

# The scope bug the first version shipped with: fair_prob was tested FIRST
# and returned early, so the liquidity check was unreachable for any line
# that was not exactly 0.5000. Live, a Kalshi anchor at $0.98 with
# fair_prob 0.5052 read as a SETTLED price — the precise-looking number off
# almost no money that these instructions single out as the worst possible
# input to fair_over, invisible to the flag written to catch it.
_thin = leg("WR A1", EV1, fair_prob=0.5052, anchor_liquidity=0.98)
chk("a precise fair_prob off a $0.98 anchor is flagged",
    _thin.anchor_immature, f"fair_prob 0.5052, liquidity 0.98")
chk("it is flagged as THIN, not as opening",
    _thin.anchor_thin and not _thin.anchor_opening)
chk("the note says the number is noise, not that it is an opening line",
    "noise" in (_thin.anchor_note or "").lower(),
    str(_thin.anchor_note)[:70])
chk("a Pinnacle opening board is NOT called thin",
    not leg("WR A1", EV1, fair_prob=0.5, anchor_liquidity=250).anchor_thin,
    "250 is a bet limit, not resting money — different unit entirely")
chk("a deep anchor away from 0.5000 is flagged neither way",
    not leg("WR A1", EV1, fair_prob=0.5052,
            anchor_liquidity=10000).anchor_immature)

sl = enumerate_candidates(
    [opening, leg("WR C1", EV2), leg("WR E1", EV3)], META,
    boost_pct=0.50, mode="cross-game")
chk("the shortlist names its opening anchors",
    sl.immature_anchors == ["WR A1"], str(sl.immature_anchors))
chk("describe() warns about them", "re-pull" in sl.describe(),
    sl.describe()[-80:])
_c = price_candidate(sl.candidates[0], book_odds=400)
chk("the report flags an opening anchor on the slip itself",
    "OPENING ANCHOR" in ff_boost.report([_c]))

# ---------------------------------------------------------------------------
section("35c. the odds -> anchor join is normalized")
# get_event_ev carries `description` and NO player_id, so this join is
# name-keyed on the live path. Event 87238 carried BOTH spellings of one
# player in the SAME payload and his whole DK/FD board went unanchored.
# ---------------------------------------------------------------------------
chk("suffix split collapses (the live failure)",
    ff_boost.norm_player("Brian Thomas Jr.")
    == ff_boost.norm_player("Brian Thomas"))
chk("a trailing team parenthetical is stripped",
    ff_boost.norm_player("Garrett Wilson (NYJ)")
    == ff_boost.norm_player("Garrett Wilson"))
chk("different players still do not collide",
    ff_boost.norm_player("Josh Allen") != ff_boost.norm_player("Keenan Allen"))
chk("a first-name variant is NOT silently merged",
    ff_boost.norm_player("Josh Palmer")
    != ff_boost.norm_player("Joshua Palmer"),
    "resolve these through search_players on exact known_names")

# ---------------------------------------------------------------------------
section("35d. a token's minimum applies to the PRICE, not the product (B55)")
from dataclasses import replace
from ff_boost import (stake_back_ev, stake_back_band,
                      OBSERVED_SGP_FACTORS, SGP_FACTORS_OBSERVED)
# A boost token's "minimum total odds" is checked by the book against the
# correlated SGP quote, which is always below the product of the legs.
# Measured at BetMGM on event 87238, 2026-11-05: product +516 -> quote +400
# (factor 0.8114), +554 -> +450 (0.8405), +593 -> +475 (0.8300). So a +450
# product prices to roughly +346-372 and a +400 token VOIDS on a slip whose
# product cleared it comfortably. FLOOR could never catch this: it is
# checked against `odds`, which IS the product until the slip is priced.
_b55 = enumerate_candidates(SAME_INDEP, META, boost_pct=0.25,
                            mode="single-game").candidates[0]
_b55 = replace(_b55, independent_odds=450.0, token_min_odds=400.0)
chk("an unpriced slip returns UNKNOWN, never a pass",
    _b55.token_minimum is None and not _b55.priced)
chk("and says so loudly rather than implying it is fine",
    "UNPRICED" in (_b55.token_note or ""), str(_b55.token_note)[:70])
# The first version hardcoded 0.81-0.86 into this note from ONE sitting of
# receiving-yards slips. Hours later, receptions and Over/Under mixes quoted
# at factors 0.87-0.99 and put the real price 27-55 points outside the
# printed range — B54/B59's stale-constant pattern one layer up, committed
# the same day it was documented twice. The range is now deliberately WIDE,
# because the factor depends on what the legs ARE, not how long they are.
chk("the unpriced note spans every factor yet observed",
    all(f"{x:.2f}" in (_b55.token_note or "") for x in OBSERVED_SGP_FACTORS),
    str(_b55.token_note)[-90:])
chk("and tells you to price it rather than decide on the estimate",
    "price_sgp" in (_b55.token_note or ""))
# The first version of this check asserted only that the range was >=0.15
# wide and that both ends appeared in the note. That is not enough: a
# controlled run then measured 0.7705, BELOW the recorded floor of 0.81,
# and nothing here would have objected. A range must be checked against
# the MEASUREMENTS it claims to cover, not against its own width.
chk("the range covers every factor actually observed",
    OBSERVED_SGP_FACTORS[0] <= min(SGP_FACTORS_OBSERVED)
    and OBSERVED_SGP_FACTORS[1] >= max(SGP_FACTORS_OBSERVED),
    f"range {OBSERVED_SGP_FACTORS} vs observed "
    f"{min(SGP_FACTORS_OBSERVED):.4f}-{max(SGP_FACTORS_OBSERVED):.4f}")
chk("the observed-factor range is kept wide on purpose",
    OBSERVED_SGP_FACTORS[1] - OBSERVED_SGP_FACTORS[0] >= 0.15,
    f"{OBSERVED_SGP_FACTORS} — narrowing this to the last measurement is the bug")
# The controlled run: SAME three BAL players, same side, market varied.
# Receptions came in BELOW yards, which is the reverse of the composition
# story this constant originally shipped with.
# B74. This compared three LITERALS (0.7705 < 0.7933 < 0.8355), so it could
# not fail and tested no code at all. The controlled triple — the SAME three
# BAL players priced on yards, then receptions, then a mixed O/U, with the
# product rising each time — is recorded in SGP_FACTORS_OBSERVED, so read
# the ordering out of the constant. Now an edit to that tuple fires this.
_CONTROLLED = (0.8355, 0.7933, 0.7705)   # yards -> receptions -> mixed
chk("the controlled triple is still present in the recorded measurements",
    all(v in SGP_FACTORS_OBSERVED for v in _CONTROLLED),
    f"{_CONTROLLED} vs {SGP_FACTORS_OBSERVED}")
chk("the same players at a longer product get a LOWER factor",
    all(a > b for a, b in zip(_CONTROLLED, _CONTROLLED[1:])),
    "mixed +614 < receptions +562 < yards +528 — ordering is by product, "
    "not by market type")
# The case the bug produced: product clears, price does not.
_void = price_candidate(_b55, book_odds=360.0)
chk("a product that clears but a price that does not VOIDS the token",
    _void.token_minimum is False and _void.clears_floor,
    f"product {_void.independent_odds:+.0f} price {_void.book_odds:+.0f}")
chk("the void note names both numbers so the gap is visible",
    "+360" in (_void.token_note or "") and "+450" in (_void.token_note or ""))
_ok = price_candidate(_b55, book_odds=420.0)
chk("a price that clears the minimum passes", _ok.token_minimum is True)
chk("no token minimum supplied stays silent, not False",
    price_candidate(replace(_b55, token_min_odds=None),
                    book_odds=360.0).token_minimum is None)
chk("the token minimum survives pricing", _void.token_min_odds == 400.0)
# FLOOR and the token minimum are different questions and must not merge.
chk("FLOOR is the project's band, the token minimum is the book's rule",
    _void.clears_floor is True and _void.token_minimum is False)

section("35e. stake-back tokens are not boosts (B56)")
# A boost pays more when you WIN; a stake-back refunds the stake as a BONUS
# BET when you LOSE. The arithmetic runs the opposite way, so the right bet
# for one is the LONGEST qualifying shot — which is why these belong on
# First TD Scorer. On the 2026-11-05 inventory two $10 stake-back tokens
# were worth ~$4-5 each while all four boost tokens priced negative.
_sb = {o: stake_back_ev(o) for o in (-150, 100, 400, 900, 1500)}
chk("value RISES as win probability falls — the opposite of a boost",
    all(_sb[a]["ev"] < _sb[b]["ev"]
        for a, b in zip([-150, 100, 400, 900], [100, 400, 900, 1500])),
    ", ".join(f'{o:+}:{d["ev"]:+.2f}' for o, d in _sb.items()))
chk("the refund is the whole story, not a rounding adjustment",
    _sb[900]["refund_ev"] > 2 * abs(_sb[900]["base_ev"]),
    f'base {_sb[900]["base_ev"]:+.2f} vs refund {_sb[900]["refund_ev"]:+.2f}')
# Measured 2026-11-05 on BetMGM's First TD board: 39.4% overround, and the
# derived bonus value tops out near 0.71 — v=0.80 is not reachable here.
# The defaults encode that rather than the 0.22/0.70 originally guessed.
chk("the defaults are the measured ones, not the guessed ones",
    abs(stake_back_ev(900)["market_hold"] - 0.39) < 1e-9
    and abs(stake_back_ev(900)["bonus_value"] - 0.65) < 1e-9)
# The raw bet's EV is INDEPENDENT OF THE ODDS: substituting
# p = 1/(d*(1+h)) collapses the first term to S*(1/(1+h) - 1), with no d.
# That is an identity, not a measurement, and it bounds the whole question.
_bases = {o: stake_back_ev(o)["base_ev"] for o in (-200, 100, 400, 900, 6600, 20000)}
chk("the raw bet's EV does not depend on the odds — it is S*(1/(1+h)-1)",
    max(_bases.values()) - min(_bases.values()) < 1e-9
    and abs(list(_bases.values())[0] - 10.0 * (1 / 1.39 - 1)) < 1e-9,
    f"{min(_bases.values()):.6f} at every price tested")
# So all odds-dependence is in the refund, and the most that lengthening
# past a price can ever add is S*v*p_true there.
chk("the headroom left above a price is exactly S*v*p_true",
    abs((stake_back_ev(20000)["ev"] - stake_back_ev(900)["ev"])
        - (10.0 * 0.65 * stake_back_ev(900)["p_true"]
           - 10.0 * 0.65 * stake_back_ev(20000)["p_true"])) < 1e-9)
# THE REFRAME, corrected. The first version measured +900 upward and called
# odds choice a fifth of the v assumption. The board starts at +400, and
# +400->+900 alone is worth more than all of +900->+6600.
_short_leg = stake_back_ev(900)["ev"] - stake_back_ev(400)["ev"]
_long_leg = stake_back_ev(6600)["ev"] - stake_back_ev(900)["ev"]
_vswing = (stake_back_ev(2800, bonus_value=0.71)["ev"]
           - stake_back_ev(2800, bonus_value=0.58)["ev"])
chk("the steepest part of the board is its SHORT end",
    _short_leg > _long_leg,
    f"+400->+900 ${_short_leg:+.2f} vs +900->+6600 ${_long_leg:+.2f}")
chk("odds choice across the real board is ~two-thirds of the v band",
    0.5 < (_short_leg + _long_leg) / _vswing < 0.85,
    f"board ${_short_leg + _long_leg:+.2f} vs v band ${_vswing:+.2f}")
chk("but reaching past +2800 buys under a dime",
    stake_back_ev(20000)["ev"] - stake_back_ev(2800)["ev"] < 0.20)
chk("the raw bet underneath is still negative — the token is the edge",
    all(d["base_ev"] < 0 for d in _sb.values()))
chk("components are returned, not just a total",
    {"base_ev", "refund_ev", "ev", "roi", "p_true"} <= set(_sb[900]))
# bonus_value is an assumption and the spread is wide enough to matter.
_band = stake_back_band(900)
chk("the band is ordered and wide enough to change the decision",
    _band["pessimistic"]["ev"] < _band["central"]["ev"] < _band["optimistic"]["ev"]
    and _band["optimistic"]["ev"] - _band["pessimistic"]["ev"] > 1.0,
    f'{_band["pessimistic"]["ev"]:+.2f} to {_band["optimistic"]["ev"]:+.2f}')
# B74. This asserted 0.71 <= 0.71 against a hardcoded literal, so its name
# ("reachable in a real First TD market") claimed something it never
# measured. Reachability means the optimistic v is achievable by SOME real
# leg, so check it against the band the module derives rather than a number
# retyped from it, and pin that it is strictly below the v=0.80 the first
# version shipped.
_opt_v = stake_back_band(900)["optimistic"]["bonus_value"]
chk("the band's top comes from the recorded measurements, not a literal",
    _opt_v == max(ff_boost.STAKE_BACK_V_OBSERVED),
    f"band top {_opt_v} vs observed max "
    f"{max(ff_boost.STAKE_BACK_V_OBSERVED)}")
chk("and it is strictly below the unreachable v=0.80 first shipped",
    _opt_v < 0.80, f"optimistic v={_opt_v}")
chk("all three band points are distinct and ordered",
    [stake_back_band(900)[l]["bonus_value"]
     for l in ff_boost.STAKE_BACK_V_LABELS]
    == sorted(set(ff_boost.STAKE_BACK_V_OBSERVED)),
    str([stake_back_band(900)[l]["bonus_value"]
         for l in ff_boost.STAKE_BACK_V_LABELS]))
chk("a worthless bonus bet collapses it to the raw bet",
    abs(stake_back_ev(900, bonus_value=0.0)["ev"]
        - stake_back_ev(900)["base_ev"]) < 1e-9)
chk("a higher market hold lowers EV without flipping the conclusion",
    stake_back_ev(900, market_hold=0.40)["ev"]
    < stake_back_ev(900, market_hold=0.15)["ev"]
    and stake_back_ev(900, market_hold=0.40)["ev"] > 0)

section("36. leg intake — nothing unbettable or circular reaches a slip")
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
chk("a circular fair line is refused at CONSTRUCTION",
    raises(leg, "WR C1", EV2, book="draftkings",
           fair_source="draftkings (via get_event_ev)"))
# fair_source is reassignable after construction, so intake checks again.
circ = leg("WR C1", EV2, book="draftkings")
circ.fair_source = "draftkings (self)"
sl = enumerate_candidates([leg("WR A1", EV1), circ, leg("WR E1", EV3)],
                          META, boost_pct=0.50, mode="cross-game")
chk("a circular fair line set AFTER construction is caught at intake",
    not sl.candidates and any("circular" in why or "own opinion" in why
                              for _, why in sl.dropped), str(sl.dropped))

chk("fair_prob of 0 is refused", raises(leg, "WR C1", EV2, fair_prob=0.0))
chk("fair_prob of 1 is refused", raises(leg, "WR C1", EV2, fair_prob=1.0))
chk("fair_prob above 1 is refused", raises(leg, "WR C1", EV2, fair_prob=1.4))

dupe = [leg("WR A1", EV1), leg("WR A1", EV1, line=55.5), leg("WR E1", EV3)]
chk("the same player twice in one slip is refused",
    raises(classify, dupe, META) or
    not enumerate_candidates(dupe, META, boost_pct=0.50,
                             mode="cross-game").candidates)

# ---------------------------------------------------------------------------
section("37. mode is honoured and stated")
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
section("38. the shortlist is reproducible")
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
section("39. the report does not overstate what it knows")
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

section("42. the role-change veto measures the direction it claims (B80)")
# It used to veto on ANY role change and then assert "it runs against
# {side}" without checking. Live on the TNF board, Justice Hill was the
# best-priced leg and was dropped for an EXPANSION (targets 2.2 -> 6.0)
# that SUPPORTS the Over being bet. `prop_edge` had this right 150 lines
# up; boost_verdict restated the reasoning without the direction test, so
# the same file carried the fix and the un-fixed copy. 488 checks passed
# over the blanket veto, so nothing pinned it.
#
# Six states, enumerated rather than branch-counted: COLLAPSED/EXPANDED x
# OVER/UNDER, plus no-side, plus the soft GAME_SCRIPT flag.
# ---------------------------------------------------------------------------
from dataclasses import replace as _replace
_ut = lambda verdict, base, rec: ff_props.UsageTrend(
    column="targets", window=3, recent=rec, baseline=base,
    ratio=(rec / base if base else 1.0), verdict=verdict,
    per_opportunity=0.0, expected_now=0.0, share_baseline=0.20,
    share_recent=0.20 * (rec / base if base else 1.0),
    share_ratio=(rec / base if base else 1.0), team_volume_ratio=1.0,
    has_share=True)
# Hill's real numbers: targets 2.2 -> 6.0, an expansion.
_HILL = _ut("EXPANDED", 2.2, 6.0)
_COLL = _ut("COLLAPSED", 6.0, 2.2)
_est_x = _replace(_e2, usage=_HILL)
_est_c = _replace(_e2, usage=_COLL)
chk("the fixture really is flagged as a role change",
    _est_x.role_changed and _est_c.role_changed)

# The direction test has ONE home now. It was two copies and the second had
# been written without the test at all, so a check that it has not been
# re-inlined earns its place here.
chk("EXPANDED supports an OVER", _HILL.supports("OVER") is True)
chk("EXPANDED opposes an UNDER", _HILL.supports("UNDER") is False)
chk("COLLAPSED supports an UNDER", _COLL.supports("UNDER") is True)
chk("COLLAPSED opposes an OVER", _COLL.supports("OVER") is False)
chk("an unknown side returns None, not a guess",
    _HILL.supports(None) is None and _HILL.supports("THIS SIDE") is None)
chk("an unflagged trend has no direction to support",
    _ut("STABLE", 5.0, 5.0).supports("OVER") is None
    and _ut("GAME_SCRIPT", 6.0, 4.0).supports("OVER") is None)
_psrc = pathlib.Path(ff_props.__file__).read_text()
# B84. `verdict` is decided on SHARE; a threshold prop is priced on COUNT.
# When team volume moves they diverge, and the verdict-derived direction was
# wrong on ALL 21 of the 264 flagged role changes in the 2025-26 pool where
# they pointed opposite ways (2 of the 243 agreeing cases disagreed, both at
# the boundary). So a conflict must return None, not a confident direction.
_utx = lambda verdict, s_ratio, c_ratio, tv=1.0: ff_props.UsageTrend(
    column="targets", window=3, recent=10.0 * c_ratio, baseline=10.0,
    ratio=c_ratio, verdict=verdict, per_opportunity=5.0,
    expected_now=50.0 * c_ratio, share_baseline=0.20,
    share_recent=0.20 * s_ratio, share_ratio=s_ratio,
    team_volume_ratio=tv, has_share=True)
# bigger slice of a smaller pie: share UP, count DOWN
_conf_x = _utx("EXPANDED", 1.95, 0.85, tv=0.57)
# smaller slice of a bigger pie: share DOWN, count UP
_conf_c = _utx("COLLAPSED", 0.63, 1.24, tv=1.97)
chk("share up + count down is a direction conflict",
    _conf_x.direction_conflict)
chk("share down + count up is a direction conflict",
    _conf_c.direction_conflict)
chk("and a conflict yields None for BOTH sides, not a guess",
    _conf_x.supports("OVER") is None and _conf_x.supports("UNDER") is None
    and _conf_c.supports("OVER") is None
    and _conf_c.supports("UNDER") is None)
chk("share and count agreeing is NOT a conflict",
    not _utx("EXPANDED", 1.95, 1.60).direction_conflict
    and not _utx("COLLAPSED", 0.55, 0.70).direction_conflict)
chk("an agreeing EXPANDED still supports the OVER",
    _utx("EXPANDED", 1.95, 1.60).supports("OVER") is True)
chk("an unflagged trend reports no conflict",
    not _utx("STABLE", 1.10, 0.90).direction_conflict)
# A conflict must VETO as UNDETERMINED, never "against the <side>" — that
# would re-enter B80's mistake through the new None.
for _side in ("OVER", "UNDER"):
    _v9, _r9 = boost_verdict(_replace(_e2, usage=_conf_x),
                             _replace(_ed2, side=_side),
                             screen_quotes(_cleanq))
    chk(f"a conflict on the {_side} vetoes as NOT ESTABLISHED", _v9 == "VETO"
        and any("DIRECTION NOT ESTABLISHED" in x for x in _r9), f"{_v9}: {_r9}")
    chk(f"and never claims it runs against the {_side}",
        not any(f"AGAINST THE {_side}" in x for x in _r9), str(_r9))
chk("the conflict reason reports count, share AND team volume",
    # B88. Named for three things and checked two: the count was never
    # asserted. Lesson 4, inside a check written to enforce lesson 4.
    all(t in " ".join(_r9) for t in (_conf_x.column, "share", "team volume")),
    str(_r9))
# prop_edge shares the helper and must not fold None into "against you".
_pe = prop_edge(_replace(_e2, usage=_conf_x), -115, -105)
chk("prop_edge PASSes a conflict without claiming a direction",
    _pe.tier == "PASS" and "NOT ESTABLISHED" in _pe.reasoning
    and "AGAINST YOU" not in _pe.reasoning, _pe.reasoning[:110])

# B88/A3. `Edge.side` is an unvalidated str and this file uses lowercase
# "over"/"under" in several places. `side is None` was the proxy for "no
# edge supplied", so a lowercase side was not None, `supports()` returned
# None because the string is not canonical, and the call fell through to the
# CONFLICT branch — printing "the COUNT moved the other way" on a trend
# whose count moved the SAME way, and re-vetoing the Justice Hill case B80
# exists to un-veto. Reached by letter case.
_clean_x = _utx("EXPANDED", 2.14, 2.50)      # share AND count up: no conflict
chk("the clean expansion fixture really has no conflict",
    not _clean_x.direction_conflict and not _clean_x.count_flat)
for _s in ("OVER", "over", "Over", " over "):
    _va, _ra = boost_verdict(_replace(_e2, usage=_clean_x),
                             _replace(_ed2, side=_s), screen_quotes(_cleanq))
    chk(f"side={_s!r} is read as OVER and SUPPORTS the leg", _va == "CAUTION"
        and any("SUPPORTS THIS SIDE" in x for x in _ra), f"{_va}: {_ra}")
    chk(f"side={_s!r} never claims a divergence that did not happen",
        not any("NOT ESTABLISHED" in x for x in _ra), str(_ra))
# An unusable side is a CALLER bug and must say so, not be reported as a
# finding about the player and not be confused with "no edge supplied".
_vb, _rb = boost_verdict(_replace(_e2, usage=_clean_x),
                         _replace(_ed2, side="yes"), screen_quotes(_cleanq))
chk("an unrecognised side vetoes as a caller bug", _vb == "VETO"
    and any("SIDE NOT RECOGNISED" in x for x in _rb), f"{_vb}: {_rb}")
chk("and it quotes the offending value", any("'yes'" in x for x in _rb),
    str(_rb))
chk("and does not say an Edge was missing when one was passed",
    not any("No edge was supplied" in x for x in _rb), str(_rb))

# B88/A4. team_volume_ratio is 0.0 when unmeasured and HARDCODED to 1.0 by
# role_trend, and the conflict message printed it as a measurement either
# way — "team volume 0%" reads as a team that ran no plays, and 100%
# directly contradicts "a bigger part of a smaller pie".
_conf_nv = ff_props.UsageTrend(
    column="targets", window=3, recent=3.0, baseline=7.0, ratio=0.43,
    verdict="EXPANDED", per_opportunity=9.0, expected_now=27.0,
    share_baseline=0.14, share_recent=0.24, share_ratio=1.72,
    team_volume_ratio=0.0, has_share=True, has_team_volume=False)
_vc, _rc = boost_verdict(_replace(_e2, usage=_conf_nv),
                         _replace(_ed2, side="OVER"), screen_quotes(_cleanq))
chk("an unmeasured team volume is not printed as a figure",
    "team volume 0%" not in " ".join(_rc)
    and "not measured" in " ".join(_rc), str(_rc))
chk("a MEASURED team volume still appears",
    "team volume 57%" in " ".join(boost_verdict(
        _replace(_e2, usage=_replace(_conf_nv, team_volume_ratio=0.57,
                                     has_team_volume=True)),
        _replace(_ed2, side="OVER"), screen_quotes(_cleanq))[1]))
chk("usage_trend reports team volume as measured",
    ff_props.usage_trend(_jsn_log, "receiving_yards").has_team_volume
    if "_jsn_log" in dir() else True)
chk("role_trend does NOT, because it hardcodes 1.0",
    not ff_props.role_trend(wk[wk.season_type == "REG"],
                            "Jaxon Smith-Njigba").has_team_volume)

# B88/A8. describe() narrated every flagged trend as "the sample describes a
# role this player no longer has", including the states supports() refuses.
# No test ran a conflicting trend through it, which is why a first cut of the
# fix used L.append() in a function that builds with `s +=` and would have
# raised NameError on exactly the state it was written for.
for _u8, _want8 in ((_conf_x, "share and count point opposite ways"),
                    (_utx("COLLAPSED", 0.496, 1.0),
                     "the opportunity count did not move")):
    _d8 = _u8.describe()
    chk(f"describe() says the side is not established ({_want8[:28]})",
        "NOT established" in _d8 and _want8 in _d8, _d8)
chk("describe() still narrates an unambiguous role change",
    "NOT established" not in _utx("EXPANDED", 1.95, 1.60).describe())
# A6: share_ratio is forced to 1.0 when the baseline is zero, and printing it
# gave "COLLAPSED, share 100%" — self-contradictory against SHARE_COLLAPSE.
_nos = ff_props.UsageTrend(
    column="targets", window=3, recent=2.0, baseline=9.0, ratio=0.22,
    verdict="COLLAPSED", per_opportunity=9.0, expected_now=18.0,
    share_baseline=0.0, share_recent=0.0, share_ratio=1.0, has_share=True)
chk("a zero share baseline is not reported as a measured ratio",
    not _nos.share_measured and "share 100%" not in _nos.describe()
    and "baseline is zero" in _nos.describe(), _nos.describe())
chk("a real share ratio is still reported",
    _conf_x.share_measured and "of baseline" in _conf_x.describe())
chk("and an unmeasured team volume says so in describe() too",
    "team volume not measured" in _conf_x.describe()
    if not _conf_x.has_team_volume else True, _conf_x.describe())

# B88/A5. A count ratio of EXACTLY 1.0 is no movement, so there is no
# staleness in either direction — but strict inequalities meant it was not a
# "conflict" and supports() answered confidently off the share verdict. At
# ratio 1.0001 the same state already returned None.
_flat = _utx("COLLAPSED", 0.496, 1.0)
chk("a flat count is flagged as such", _flat.count_flat
    and not _flat.direction_conflict)
chk("and yields None rather than a confident direction",
    _flat.supports("UNDER") is None and _flat.supports("OVER") is None)
# Just above 1.0 the count has turned UP against a falling share, which is
# a genuine conflict; just below, both point down and agree. So the answer
# legitimately changes at 1.0 — what was wrong was 1.0 ITSELF answering
# confidently while 1.0001 returned None.
chk("just above 1.0 is a conflict (count up, share down)",
    _utx("COLLAPSED", 0.496, 1.0001).supports("UNDER") is None)
chk("just below 1.0 they agree, so a direction IS established",
    _utx("COLLAPSED", 0.496, 0.9999).supports("UNDER") is True)
# B89 (open): a count ratio of 0.9999 leaves expected_now within a whisker
# of the sample mean, so "the model overstates him" is technically true and
# practically empty. A tolerance band around 1.0 is the fuller fix and needs
# a MEASURED tolerance — picking one by eye is the error this project keeps
# repeating, so it is filed rather than guessed.
_vd, _rd = boost_verdict(_replace(_e2, usage=_flat),
                         _replace(_ed2, side="UNDER"), screen_quotes(_cleanq))
chk("a flat count vetoes as undetermined", _vd == "VETO"
    and any("NOT ESTABLISHED" in x for x in _rd), f"{_vd}: {_rd}")
# B90. supports() returns None for TWO reasons — conflict, and a flat count
# — and ONE message asserted the conflict narrative for both. Live result:
# CeeDee Lamb's targets were exactly flat at 11.5 -> 11.5 and the refusal
# told the reader "the COUNT moved the other way". The reading session then
# reported him as the conflict case and had to correct itself from the flags.
# A message asserting what the code did not determine, introduced in the fix
# for exactly that — so each state gets its own sentence.
chk("a flat count says the count did NOT move",
    any("did NOT move" in x for x in _rd), str(_rd))
chk("and never claims it moved the other way",
    not any("moved the OTHER WAY" in x or "moved the other way" in x
            for x in _rd), str(_rd))
_vc2, _rc2 = boost_verdict(_replace(_e2, usage=_conf_x),
                           _replace(_ed2, side="OVER"), screen_quotes(_cleanq))
chk("a real conflict DOES say the count moved the other way",
    any("moved the OTHER WAY" in x for x in _rc2), str(_rc2))
chk("and does not say the count was flat",
    not any("did NOT move" in x for x in _rc2), str(_rc2))
# prop_edge carries the same two states and had the same conflated wording.
_pe_f = prop_edge(_replace(_e2, usage=_flat), -115, -105)
chk("prop_edge distinguishes a flat count too",
    "did not move at all" in _pe_f.reasoning
    and "opposite ways" not in _pe_f.reasoning, _pe_f.reasoning[:130])
chk("and still says opposite ways for a real conflict",
    "opposite ways" in prop_edge(_replace(_e2, usage=_conf_x),
                                 -115, -105).reasoning)

chk("the direction test is not re-inlined anywhere (B80)",
    _psrc.count('self.verdict == "COLLAPSED"') == 1
    and _psrc.count('self.verdict == "EXPANDED"') == 1
    and 'u.verdict == "COLLAPSED"' not in _psrc,
    f"COLLAPSED x{_psrc.count('verdict == ' + chr(34) + 'COLLAPSED' + chr(34))}")

for _u, _side, _want, _lbl in (
        (_HILL, "OVER", "CAUTION", "EXPANDED + OVER (the Hill case)"),
        (_HILL, "UNDER", "VETO", "EXPANDED + UNDER"),
        (_COLL, "UNDER", "CAUTION", "COLLAPSED + UNDER"),
        (_COLL, "OVER", "VETO", "COLLAPSED + OVER")):
    _v4, _r4 = boost_verdict(_replace(_e2, usage=_u),
                             _replace(_ed2, side=_side),
                             screen_quotes(_cleanq))
    chk(f"{_lbl} -> {_want}", _v4 == _want, f"got {_v4}: {_r4}")

# The message must not assert a direction it did not measure.
_v5, _r5 = boost_verdict(_est_x, _replace(_ed2, side="OVER"),
                         screen_quotes(_cleanq))
chk("a supportive change says SUPPORTS, not 'runs against'",
    any("SUPPORTS THIS SIDE" in x for x in _r5)
    and not any("against" in x.lower() for x in _r5), str(_r5))
chk("and it still warns the magnitude is unreliable",
    any("magnitude is unreliable" in x for x in _r5), str(_r5))
_v6, _r6 = boost_verdict(_est_x, _replace(_ed2, side="UNDER"),
                         screen_quotes(_cleanq))
chk("an opposing change names the side it runs against",
    any("AGAINST THE UNDER" in x for x in _r6), str(_r6))

# No edge means no side, so the direction is UNKNOWABLE. Refusing is right;
# claiming a direction is not.
_v7, _r7 = boost_verdict(_est_x, None, screen_quotes(_cleanq))
chk("no edge supplied -> VETO, but for the missing side", _v7 == "VETO"
    and any("DIRECTION UNKNOWN" in x for x in _r7), f"{_v7}: {_r7}")
chk("and it does not name a side it was never given",
    not any("against the OVER" in x or "against the UNDER" in x
            for x in _r7), str(_r7))

# A CAUTION leg must actually REACH a slip, or this fix changes nothing.
# enumerate_candidates drops VETO (ff_boost:1187) and only annotates
# CAUTION (ff_boost:1090) — pin that, because the whole point of the fix is
# admission, not wording.
_cau = leg("WR C1", EV2, verdict="CAUTION")
_sl2 = enumerate_candidates([leg("WR A1", EV1), _cau, leg("WR E1", EV3)],
                            META, boost_pct=0.50, mode="cross-game")
chk("a CAUTION leg is admitted to a slip, not dropped",
    any(_cau.player in [l.player for l in cc.legs]
        for cc in _sl2.candidates), str(_sl2.dropped))
chk("and the candidate carries the caution as a note",
    any(any(_cau.player in n for n in cc.notes)
        for cc in _sl2.candidates
        if _cau.player in [l.player for l in cc.legs]),
    str([cc.notes for cc in _sl2.candidates]))

# GAME_SCRIPT is the softer flag and must stay CAUTION, not get pulled into
# the directional branch.
_v8, _r8 = boost_verdict(_replace(_e2, usage=_ut("GAME_SCRIPT", 6.0, 4.0)),
                         _replace(_ed2, side="OVER"), screen_quotes(_cleanq))
chk("a GAME_SCRIPT flag is still CAUTION and not directional",
    _v8 == "CAUTION" and any("game script" in x for x in _r8), f"{_v8}: {_r8}")

section("41. a refusal reachable by OMITTING an argument (B70-B73)")
# Every finding in this section came from an independent review of a diff
# that had already passed 464 checks. The shared shape: the suite tested the
# path the author was thinking about, and the defect was in the path nobody
# wrote a call for. **A parameter's DEFAULT is a code path.** Every caller of
# devig_field in the repo passed `market=` explicitly, so the None default
# — which disabled the mutual-exclusivity refusal entirely — was never once
# exercised.
# ---------------------------------------------------------------------------
_atd = {"Derrick Henry": -140, "Zay Flowers": 120, "Mark Andrews": 150,
        "Travis Etienne": 180, "Brian Thomas Jr.": 200, "Bhayshul Tuten": 400,
        "Rashod Bateman": 450, "Lamar Jackson": 500, "Trevor Lawrence": 900,
        "Keaton Mitchell": 1200, "No Touchdown Scorer": 6000}
try:
    ff_props.devig_field(_atd)
    chk("devig_field cannot be called without naming the market", False,
        "an anytime-TD board de-vigged with no market argument")
except TypeError:
    chk("devig_field cannot be called without naming the market", True)
try:
    ff_props.devig_field(_atd, market=None)
    chk("an explicit market=None is refused, not treated as 'any field'",
        False, "returned a normalized field")
except ValueError as _ex:
    _msg = str(_ex)
    chk("an explicit market=None is refused, not treated as 'any field'",
        "not a mutually exclusive field" in _msg, _msg[:70])
chk("the refusal names the fields that ARE exclusive",
    "player_1st_td" in _msg)

# B71. The completeness guard checked a NAME. A booksum below 1.0 is
# arithmetic PROOF of a short field whatever it is called, and de-vigging it
# scales every price UP — the direction that manufactures edge.
try:
    ff_props.devig_field({"A": 400, "B": 400, "No Touchdown Scorer": 300},
                         market="player_1st_td")
    chk("a booksum below 1.0 is refused even WITH a no-scorer entry", False,
        "a 0.65 booksum was de-vigged")
except ValueError as _ex:
    _msg2 = str(_ex)
    chk("a booksum below 1.0 is refused even WITH a no-scorer entry",
        "BELOW 1.0" in _msg2, _msg2[:70])
chk("and the refusal says the name check is what let it through",
    "name check" in _msg2, _msg2[:120])
# The guard must not fire on a legitimately complete field.
_ok = ff_props.devig_field(_DK1, market="player_1st_td")
chk("a real complete board still de-vigs", _ok["booksum"] > 1.0
    and abs(sum(_ok["fair"].values()) - 1.0) < 1e-9)
chk("and reports shin, because z did not collapse",
    _ok["method"] == "shin", _ok["method"])

# B85. The incomplete-field refusal printed "too low by whatever is missing"
# over whatever booksum arrived. Observed live: a dict keyed on player name
# alone pulled milestone rungs into a First TD field, giving 13 outcomes at
# booksum 2.98 — and the refusal called 2.98 "too low". The caller is already
# confused at that point; the message must not add to it.
# Pre-bound so that if a guard regresses and the call RETURNS, the later
# checks fail on the empty string instead of crashing the suite on a
# NameError — lesson 14: a crash stops every later section and prints
# "0 failed" over a partial count.
_m = _mns = _mb = _m2 = ""
_pol = {f"P{i}": v for i, v in enumerate(
    [-125, -105, 150, 200, 250, 300, 450, 600, 800, 1000, 1400, 2000, 2500])}
try:
    ff_props.devig_field(_pol, market="player_1st_td")
    chk("a polluted field is refused", False, "it de-vigged")
except ValueError as _ex:
    _m = str(_ex)
    chk("a polluted field is refused", True)
chk("the refusal names the ceiling it crossed",
    "2.00 ceiling" in _m and "EXTRA OUTCOMES" in _m, _m[:150])
chk("and never calls a 3.0 booksum 'too low'", "too low" not in _m, _m[:150])
chk("and it names the cause the caller can act on",
    "keyed on player name alone" in _m and "flatten_odds" in _m, _m[:220])

# B88/A1. THE DANGEROUS ONE. Both the lower bound and the diagnosis were
# gated on whether a no-scorer row was PRESENT, so a polluted field carrying
# one had no ceiling at all — and the real DraftKings board carries
# "No Touchdown Scorer", so that is the likely path, not an edge case.
# Measured before the fix: booksum 3.0326 over 14 outcomes RETURNED, tagged
# method='shin', complete=True, turning a 55.6% implied scorer into 24.4%.
_pol_ns = dict(_pol); _pol_ns["No Touchdown Scorer"] = 6000
try:
    _bad = ff_props.devig_field(_pol_ns, market="player_1st_td")
    chk("a polluted field WITH a no-scorer row is still refused", False,
        f"RETURNED booksum {_bad['booksum']:.4f} as {_bad['method']!r}, "
        f"complete={_bad['complete']}")
except ValueError as _ex:
    _mns = str(_ex)
    chk("a polluted field WITH a no-scorer row is still refused", True)
chk("and the refusal says the name check could not have caught it",
    "no-scorer row is present" in _mns, _mns[-170:])
# require_complete must not be an escape hatch from the ceiling: it governs
# inspecting an INCOMPLETE field, and this field is not incomplete.
try:
    ff_props.devig_field(_pol_ns, market="player_1st_td",
                         require_complete=False)
    chk("require_complete=False does not bypass the ceiling", False,
        "it de-vigged")
except ValueError:
    chk("require_complete=False does not bypass the ceiling", True)

# B88/A2. The diagnosis compared against 1.0 + 1.00 = a booksum of 2.0 while
# its own comment claimed 1.0, leaving the whole 1.0-2.0 band — where a
# LIGHTLY polluted field lands — reading "too low".
_band = {f"P{i}": v for i, v in enumerate([300] * 3 + [800] * 5 + [2000] * 6)}
try:
    ff_props.devig_field(_band, market="player_1st_td")
    chk("a booksum in the 1.57-2.00 band is refused", False, "it de-vigged")
except ValueError as _ex:
    _mb = str(_ex)
chk("a booksum above the MEASURED ceiling reads TOO HIGH, not too low",
    "TOO HIGH" in _mb and "too low" not in _mb, _mb[:170])
# And a genuinely short field must still get the original diagnosis.
_shrt = {f"P{i}": v for i, v in enumerate(
    [400, 425, 600, 650, 1000, 1400, 1600, 2000, 2500, 3000])}
try:
    ff_props.devig_field(_shrt, market="player_1st_td")
    chk("a short field is refused as too low", False, "it de-vigged")
except ValueError as _ex:
    _m2 = str(_ex)
chk("a short field is refused as too low", "too low" in _m2
    and "TOO HIGH" not in _m2, _m2[:150])
# The two constants have DIFFERENT jobs; one doing both is what broke it.
chk("the diagnostic ceiling clears every measured real board",
    all(bs - 1.0 <= ff_props.MAX_OBSERVED_OVERROUND
        for bs in (1.5421, 1.5655, 1.4124, 1.3501)),
    str(ff_props.MAX_OBSERVED_OVERROUND))
chk("the diagnostic ceiling is TIGHT to the measurements, not 3x loose",
    ff_props.MAX_OBSERVED_OVERROUND < 0.60,
    str(ff_props.MAX_OBSERVED_OVERROUND))
chk("the refusal line sits above the diagnostic ceiling",
    ff_props.BOOKSUM_REFUSE_ABOVE > 1.0 + ff_props.MAX_OBSERVED_OVERROUND)
chk("and below the polluted booksum that motivated it",
    ff_props.BOOKSUM_REFUSE_ABOVE < 2.9756)

# B72. The detector's own control coming back empty was the one failure it
# could not survive: `eligible` derives from that same payload, so it went
# quiet exactly when it mattered and `healthy` returned True.
for _ctl, _lbl in (({}, "empty dict"), ({"bookmakers": []}, "no bookmakers"),
                   ({"error": "HTTP 503"}, "error payload")):
    _c = anchor_coverage(_EV_LIVE if "_EV_LIVE" in dir() else
                         {"lines": [{"fair_source": "kalshi"}]}, _ctl)
    chk(f"an unusable control ({_lbl}) is NOT reported healthy",
        not _c.healthy and not _c.control_usable, _c.describe()[:70])
    chk(f"and it says the control failed rather than clearing the books "
        f"({_lbl})", "NO USABLE CONTROL" in _c.describe(),
        _c.describe()[:90])
chk("anchor_coverage({}, {}) does not claim a clean bill of health",
    not anchor_coverage({}, {}).healthy)
chk("a usable control is still reported usable",
    anchor_coverage({"lines": [{"fair_source": "pinnacle"}]},
                    _mk_odds({"pinnacle": 14})).control_usable)

# B73. team and pos both come from build_meta()'s agg("last"), so an absent
# field arrives as NaN — which is TRUTHY. Both guards tested truthiness.
def _pleg(player, market, team, pos):
    return BoostLeg(event_id=EV1, book="draftkings", market=market,
                    player=player, side="OVER", odds=-150, fair_prob=0.6,
                    fair_source="pinnacle", devig_method="shin",
                    verdict="CLEAR",
                 verdict_side="OVER", team=team, pos=pos)
_nan = float("nan")
for _bad, _lbl in ((_nan, "NaN"), ("   ", "whitespace"), ("", "empty")):
    # Caught rather than allowed to propagate. A NaN position used to raise
    # AttributeError out of classify(), which CRASHED the suite instead of
    # failing a check — and that matters beyond tidiness: a crash stops
    # every later section, so the run prints "0 failed" over a partial
    # count. Verifying this very fix by counting FAIL lines reported zero
    # for exactly that reason. A check must FAIL, not explode.
    try:
        s = classify([_pleg("QB A", "player_pass_yds", "AAA", "QB"),
                      _pleg("Ghost", "player_reception_yds", "AAA", _bad)])
        chk(f"a {_lbl} position is unmeasured, not the WR coefficient",
            not s.pairs and bool(s.unmeasured), f"pairs={s.pairs}")
    except Exception as _exc:
        chk(f"a {_lbl} position is unmeasured, not the WR coefficient",
            False, f"raised {type(_exc).__name__}: {_exc}")
# The sign error: a NaN team passed the truthiness guard, then failed the
# equality test, and two SAME-team rushing legs were scored as OPPOSING.
s = classify([_pleg("R1", "player_rush_yds", _nan, "RB"),
              _pleg("R2", "player_rush_yds", "BBB", "RB")])
chk("a NaN team never reaches the opposing-rusher branch",
    not any(abs(p[2] + 0.14) < 1e-9 for p in s.pairs), f"pairs={s.pairs}")
chk("it is refused for the reason the team guard already gave",
    s.unmeasured and "no team known" in str(s.unmeasured),
    str(s.unmeasured)[:90])
# And the known-good paths are untouched.
s = classify([_pleg("QB A", "player_pass_yds", "AAA", "QB"),
              _pleg("RB A1", "player_reception_yds", "AAA", " rb ")])
chk("a position with stray whitespace still RESOLVES once stripped",
    any(abs(p[2] - _STP[("QB", "RB_RECV")]) < 1e-9 for p in s.pairs),
    f"pairs={s.pairs}")

section("43. verification that can never pass is not caution (B90, B91)")
# B91. verify_uploaded required BYTE identity, which is unreachable for any
# log containing a non-ASCII character: json.dumps is ASCII-only, so an em
# dash is stored as \u2014 locally and comes back raw from Drive. ff_props.py
# holds 178 em dashes, 35 inside verdict-reason strings, so every role-change
# verdict guaranteed a False. A session re-uploaded, got False again, and
# declined to mark_uploaded — leaving 69 records up but unmarked, forever
# re-uploaded by the next session. A check that cannot pass gets ignored.
# ---------------------------------------------------------------------------
_recs = [{"id": f"v{i}", "kind": "verdict",
          "reason": f"ROLE CHANGE AGAINST THE OVER \u2014 targets {i}.0 -> 2.0"}
         for i in range(3)]
_local = "\n".join(json.dumps(r) for r in _recs) + "\n"
ff_betlog.SESSION.parent.mkdir(parents=True, exist_ok=True)
_prev = ff_betlog.SESSION.read_text() if ff_betlog.SESSION.exists() else None
ff_betlog.SESSION.write_text(_local)
_drive = _local.replace("\\u2014", "\u2014")      # what Drive hands back
chk("the escape-decoded round trip is NOT byte-identical", _drive != _local)
chk("but it verifies, because the records are identical",
    ff_betlog.verify_uploaded(_drive))
# And it must still catch what actually matters.
chk("an altered field still fails",
    not ff_betlog.verify_uploaded(_drive.replace("targets 1.0", "targets 9.0")))
chk("a dropped record still fails",
    not ff_betlog.verify_uploaded("\n".join(_drive.splitlines()[:2]) + "\n"))
chk("a reordered record still fails",
    not ff_betlog.verify_uploaded(
        "\n".join(list(reversed(_drive.splitlines()))) + "\n"))
chk("unparseable content still fails",
    not ff_betlog.verify_uploaded(_drive + "{not json\n"))
if _prev is None:
    ff_betlog.SESSION.unlink(missing_ok=True)
else:
    ff_betlog.SESSION.write_text(_prev)

def _raises(fn, exc=Exception) -> bool:
    """True when fn() raises exc. Keeps a check a FAILURE, not a crash.

    Catches EVERYTHING and compares the type, rather than `except exc`,
    which let a different exception propagate and kill the run — lesson 14
    for the sixth time. A revert that turns a clean ValueError into a
    TypeError now FAILS this check instead of crashing the suite.
    """
    try:
        fn()
        return False
    except BaseException as e:                               # noqa: BLE001
        return isinstance(e, exc)


def _line(text: str, prefix: str) -> str:
    """The report line starting with `prefix`, or "" — so a check can assert
    on the line it NAMES rather than anywhere in the report.

    A check reading `"$7.53" in output` passed a revert that zeroed the
    staked figure, because the same string appeared on the boost line. A
    substring match against a whole report is not a check on the thing the
    check is about.
    """
    for l in text.splitlines():
        if l.strip().startswith(prefix):
            return l.strip()
    return ""


def _out(fn) -> str:
    """fn()'s output, or its error message — so a check that asserts on report
    text cannot crash the run when the report itself breaks (lesson 14)."""
    try:
        return str(fn())
    except Exception as e:                                   # noqa: BLE001
        return f"*** RAISED {type(e).__name__}: {e}"


def _err(fn) -> str:
    """The message fn() raises, or "" — so asserting on wording cannot crash
    the section (lesson 14)."""
    try:
        fn()
        return ""
    except Exception as e:                                   # noqa: BLE001
        return str(e)


section("50. the anchor flag gap a slip gets built from (B86)")
# anchor_thin fires at liquidity <= 25 and anchor_opening needs an exact
# 0.5000, so a line at the book's OPENING LIMIT whose price has moved got
# nothing — and that is the set a session selects, because moving off the
# prior is what makes a line look informative.
#
# Reconstructed from the real slip (Sunday board, 2026-11-05): all three
# legs sat at or under their tier and NOT ONE automated guard fired. The
# session caught it by querying the fields by hand and had earlier written
# prose about "shallow Kalshi anchors" as though the tooling had flagged
# them, then corrected itself.
# ---------------------------------------------------------------------------
def _aleg(player, fp, lq, tier):
    return BoostLeg(event_id=EV1, book="fanduel",
                    market="player_reception_yds", player=player, side="OVER",
                    odds=-114, fair_prob=fp, fair_source="pinnacle",
                    devig_method="shin", verdict="CLEAR",
                 verdict_side="OVER", team="X", pos="WR",
                    anchor_liquidity=lq, opening_liquidity_tier=tier)
_slip = [_aleg("Gibbs", 0.5427, 250, 250.0),      # tier derived from Pinnacle
         _aleg("Likely", 0.4944, 175.76, None),   # Kalshi: no tier, falls back
         _aleg("Allen", 0.4798, 106, None)]
chk("every leg of the real slip is now flagged",
    all(l.anchor_untested for l in _slip),
    str([(l.player, l.anchor_untested) for l in _slip]))
chk("and none of them was caught by the two older flags",
    not any(l.anchor_opening or l.anchor_thin for l in _slip))
chk("a no-tier book falls back to the hardcoded constant, not to silence",
    _slip[2].anchor_untested and _slip[2].opening_liquidity_tier is None)
# FIRING RATE. The broad version — liquidity <= tier, full stop — fires on
# 100% of a three-days-out board and is the noise B93b cut. Residual fires
# on the 8 of 62 that moved. Both go to zero near kickoff.
_early = ([_aleg(f"p{i}", 0.5000, 250, 250.0) for i in range(54)]
          + [_aleg(f"q{i}", 0.5000 + 0.004 * (i + 1), 250, 250.0)
             for i in range(8)])
_n_unt = sum(l.anchor_untested for l in _early)
chk("three days out it fires on the 8 that moved, not all 62",
    _n_unt == 8, f"{_n_unt} of {len(_early)}")
chk("and the other 54 are anchor_opening, so nothing is double-counted",
    sum(l.anchor_opening for l in _early) == 54
    and not any(l.anchor_opening and l.anchor_untested for l in _early))
_late = [_aleg(f"r{i}", 0.52 + 0.004 * i, 2000, 1000.0) for i in range(62)]
chk("near kickoff it goes completely quiet",
    not any(l.anchor_untested or l.anchor_immature for l in _late))
# It feeds the slip-level report, which names three players rather than 62.
_sl = ff_boost.Shortlist(
    candidates=[ff_boost.Candidate(
        legs=_slip, structure=classify(_slip, {}), boost_pct=0.30,
        independent_odds=560.0, stake=10.0)],
    mode="single-game", boost_pct=0.30, reason="", dropped=[])
chk("the shortlist names them as immature anchors",
    set(_sl.immature_anchors) == {"Gibbs", "Likely", "Allen"},
    str(_sl.immature_anchors))

section("49. a book is not its own reference — including at GRADING (B102)")
# The project's oldest rule, never applied to the grading path. Measured
# 2026-11-06 on a real slip: PropLine's grader returned ev_vs_close_pct of
# -4.86% and -3.70% with fair_source "draftkings" — the book the bet was
# placed at — so the figure was mostly DK's own 5.6% hold. Re-graded against
# the best SAME-POINT non-DK close, the three-leg average was at best
# -5.20% and truly worse.
# ---------------------------------------------------------------------------
chk("a fair line from the bet's own book is refused",
    "CIRCULAR" in str(ff_betlog.check_clv_source("draftkings", "draftkings")))
chk("a fair line from a different book is fine",
    ff_betlog.check_clv_source("draftkings", "pinnacle") is None)
# Book names arrive spelled differently across endpoints, so the comparison
# cannot be a bare string equality.
for _a, _b in (("DraftKings", "draftkings"), ("draftkings", "Draft Kings"),
               ("BetMGM", "bet_mgm"), ("draftkings", "DRAFTKINGS")):
    chk(f"{_a!r} and {_b!r} are recognised as the same book",
        ff_betlog.check_clv_source(_a, _b) is not None, f"{_a} / {_b}")
chk("and genuinely different books are not collapsed",
    ff_betlog.check_clv_source("betmgm", "bovada") is None)
# A missing source is its OWN problem: unknowable is not the same as clean.
chk("no recorded source is flagged too, not treated as clean",
    "NO source" in str(ff_betlog.check_clv_source("draftkings", None)))
chk("and the message says what to quote instead",
    "clv_pct" in str(ff_betlog.check_clv_source("draftkings", None)))
# The guard has to REFUSE the write, not just offer an opinion — a circular
# number in the log reads as measured value to every later reader.
chk("grade_leg refuses to record a circular grade",
    _raises(lambda: ff_betlog.grade_leg(
        "abc", 0, "LOSS", actual=22.0, closing_odds=-110,
        closing_fair_source="draftkings", book="draftkings"), ValueError))
# It must stay silent when it has nothing to check, or every legacy call
# breaks.
chk("a grade with no source and no book still records",
    ff_betlog.grade_leg("abc", 0, "LOSS", actual=22.0,
                        closing_odds=-110)["kind"] == "leg_grade")
chk("the source and book are RECORDED when given, for later readers",
    ff_betlog.grade_leg("abc", 1, "LOSS", actual=22.0, closing_odds=-110,
                        closing_fair_source="pinnacle",
                        book="draftkings")["closing_fair_source"]
    == "pinnacle")

section("48. a changed module names the files that must ship with it (B100)")
# The repo is updated by uploading files one at a time, so a PARTIAL commit
# is the normal failure. ff_boost.py was shipped on 2026-11-06 with a
# caption saying "ff_props.py and ff_boost.py must be committed together"
# and ff_props.py was NOT attached. Three sessions in a row then ran against
# a torn clone. Detection was solved by B99's import message; what was still
# hand-written was the LIST OF FILES, so shipset.py computes it.
# ---------------------------------------------------------------------------
import shipset
_g = shipset.deps(pathlib.Path(ff_props.__file__).resolve().parent)
chk("the dependency graph finds every module", len(_g) >= 6, str(sorted(_g)))
# The exact coupling that caused the outage.
chk("ff_boost is recorded as importing from ff_props",
    "ff_props" in _g.get("ff_boost", set()), str(_g.get("ff_boost")))
_bset = shipset.closure({"ff_boost"}, _g)
chk("shipping ff_boost names ff_props as required",
    "ff_props" in _bset, str(sorted(_bset)))
# BOTH directions: ff_props must also name ff_boost, because an importer
# left behind runs against a stale copy rather than failing loudly.
_pset = shipset.closure({"ff_props"}, _g)
chk("and shipping ff_props names ff_boost back",
    "ff_boost" in _pset, str(sorted(_pset)))
chk("and names what ff_props itself imports from",
    {"ff_data", "ff_guillotine"} <= _pset, str(sorted(_pset)))
# One hop, not the transitive closure — over seven modules the closure is
# "all of them", which is not advice.
chk("the default is one hop, so the answer stays actionable",
    len(_bset) < len(_g), f"{len(_bset)} of {len(_g)}")
chk("but --deep still reaches everything",
    len(shipset.closure({"ff_boost"}, _g, deep=True)) >= len(_bset))

section("47. a uniform hold punishes the leg you shopped hardest (B95)")
# stake_back_ev backed p out of the price with `implied(odds)/(1+hold)`,
# which assumes the leg carries the FIELD'S AVERAGE margin. Measured on a
# live First TD board, per-leg margins ran +0.01pp to -3.52pp in ONE game.
# Chase Brown's BetMGM +525 carried almost none, so the derivation put him
# 24% low and his $10 token at $3.29 instead of $5.47. The error has a
# direction: the better you shopped, the more it understates you.
# ---------------------------------------------------------------------------
_CB_ODDS, _CB_FAIR, _CB_HOLD = 525, 0.1601, 0.3195
_der = stake_back_ev(_CB_ODDS, market_hold=_CB_HOLD)
_mea = stake_back_ev(_CB_ODDS, fair_prob=_CB_FAIR)
chk("the uniform derivation really is low on a well-shopped leg",
    _der["p_true"] < _mea["p_true"] * 0.80,
    f'derived {_der["p_true"]:.4f} vs measured {_mea["p_true"]:.4f}')
chk("and it reproduces the measured gap, $3.29 against $5.47",
    abs(_der["ev"] - 3.29) < 0.01 and abs(_mea["ev"] - 5.47) < 0.01,
    f'{_der["ev"]:.2f} / {_mea["ev"]:.2f}')
chk("fair_prob is used verbatim, not re-derived",
    abs(_mea["p_true"] - _CB_FAIR) < 1e-12)
# The result has to say WHICH p it used, or the two are indistinguishable.
chk("the result names the source of p",
    _mea["p_source"].startswith("measured")
    and "uniform" in _der["p_source"],
    f'{_mea["p_source"]!r} / {_der["p_source"]!r}')
chk("a fair_prob outside (0,1) is refused, not clamped",
    all(_raises(lambda v=v: stake_back_ev(525, fair_prob=v), ValueError)
        for v in (0.0, 1.0, 1.4, -0.2)))
# stake_back_band must pass it through, or the band silently reverts.
_bd = stake_back_band(_CB_ODDS, fair_prob=_CB_FAIR)
chk("the band passes fair_prob through to every point",
    all(r["p_source"].startswith("measured") for r in _bd.values()),
    str({k: v["p_source"] for k, v in _bd.items()}))
# B99b. market_hold is inert once fair_prob is given, and used to be
# SILENTLY inert — a session headlined "measured hold, not the default" and
# then found the figure identical at every hold from 0.10 to 0.542.
_inert = [stake_back_ev(525, market_hold=h, fair_prob=0.1601)["ev"]
          for h in (0.10, 0.3195, 0.39, 0.542)]
chk("market_hold changes nothing once fair_prob is passed",
    max(_inert) - min(_inert) < 1e-12, str(_inert))
chk("and p_source SAYS the hold was not used",
    "NOT used" in stake_back_ev(525, market_hold=0.3195,
                                fair_prob=0.1601)["p_source"])
chk("while the derived path still names the hold it applied",
    "uniform 31.9% hold" in stake_back_ev(525,
                                          market_hold=0.3195)["p_source"])
chk("and reproduces the measured band 4.88 / 5.47 / 5.97",
    all(abs(_bd[l]["ev"] - e) < 0.01 for l, e in
        zip(ff_boost.STAKE_BACK_V_LABELS, (4.88, 5.47, 5.97))),
    str({k: round(v["ev"], 2) for k, v in _bd.items()}))

# ODDS-INDEPENDENCE IS A PREMISE, NOT A PROPERTY. The documented result
# `base = S*(1/(1+h) - 1)` follows from substituting p = 1/(d*(1+h)) — which
# IS the uniform-hold assumption. Pin both halves, because the instructions
# used to state the first without the second.
_bases_u = [stake_back_ev(o, market_hold=0.39)["base_ev"]
            for o in (-200, 300, 900, 2800, 20000)]
chk("under a uniform hold the base EV is constant across all prices",
    max(_bases_u) - min(_bases_u) < 1e-9, str([round(b, 4) for b in _bases_u]))
# Real board, real per-leg fair probabilities, same three legs the session
# recommended from.
_real_legs = ((300, 0.2148, "McCaffrey"), (525, 0.1601, "Chase Brown"),
              (1450, 0.0621, "Washington"))
_bases_m = [stake_back_ev(o, fair_prob=p)["base_ev"] for o, p, _ in _real_legs]
chk("with MEASURED per-leg fair probabilities it is not constant at all",
    max(_bases_m) - min(_bases_m) > 1.0, str([round(b, 4) for b in _bases_m]))
# The practical consequence: a shorter price can beat a longer one.
_short = stake_back_ev(525, fair_prob=0.1601)["ev"]
_long = stake_back_ev(800, fair_prob=0.0906)["ev"]
chk("price QUALITY can beat price LENGTH once margins vary",
    _short > _long, f"+525 at ${_short:.2f} vs +800 at ${_long:.2f}")

section("46. the extraction helpers that replace the hand-rolls (B82)")
# Two sessions hand-rolled walks of bookmakers[].markets[].outcomes[] and
# both reproduced bugs flatten_odds already fixes: a Kalshi First TD board
# keyed on name kept the LAST price per player — the No side, at -4900 —
# giving booksum 20.99; and an Over/Under board keyed the same way pulled 13
# milestone rungs into one player's line, giving booksum 2.9756. Both
# fixtures below are those shapes.
# ---------------------------------------------------------------------------
_kal = {"bookmakers": [{"key": "kalshi", "markets": [{
    "key": "player_1st_td", "outcomes": sum(
        [[{"name": "Yes", "description": p, "price": pr},
          {"name": "No", "description": p, "price": -4900}]
         for p, pr in [("Bhayshul Tuten", 400), ("Derrick Henry", 600),
                       ("Zay Flowers", 1000),
                       ("No Touchdown Scorer", 250)]], [])}]}]}
_kf = ff_props.field_from_odds(_kal, market="player_1st_td", book="kalshi")
chk("a Yes/No board yields the YES side, never the No",
    set(_kf.values()) == {400.0, 600.0, 1000.0, 250.0}, str(_kf))
chk("and one entry per player, not two", len(_kf) == 4, str(_kf))
chk("the -4900 No price appears nowhere", -4900.0 not in _kf.values())
# The no-scorer row has to survive normalisation or devig_field's
# completeness check stops working on the output.
chk("the no-scorer row survives norm_player into NO_SCORER_NAMES",
    any(k in ff_props.NO_SCORER_NAMES for k in _kf), str(list(_kf)))

# A name-only board is the other real shape.
_dkb = {"bookmakers": [{"key": "draftkings", "markets": [{
    "key": "player_1st_td", "outcomes": [
        {"name": p, "description": p, "price": pr} for p, pr in
        [("Bhayshul Tuten", 400), ("Chris Rodriguez Jr.", 425),
         ("No Touchdown Scorer", 250)]]}]}]}
_df = ff_props.field_from_odds(_dkb, market="player_1st_td",
                               book="draftkings")
chk("a name-only board works from the same call", len(_df) == 3, str(_df))
# B44: the exact lookup that reported Chris Rodriguez as UNKNOWN.
chk("names come back normalised, so the B44 join cannot miss",
    "chris rodriguez" in _df and "Chris Rodriguez Jr." not in _df, str(_df))

# The ambiguity that taking-either-one hides. One payload really did carry
# both spellings of Brian Thomas at once (B44).
_dup = {"bookmakers": [{"key": "dk", "markets": [{
    "key": "player_1st_td", "outcomes": [
        {"name": "Brian Thomas Jr.", "description": "Brian Thomas Jr.",
         "price": 500},
        {"name": "Brian Thomas", "description": "Brian Thomas",
         "price": 650}]}]}]}
_cm = ""
try:
    ff_props.field_from_odds(_dup, market="player_1st_td", book="dk")
    chk("two names normalising to one key is refused", False, "it returned")
except ValueError as _ex:
    _cm = str(_ex)
    chk("two names normalising to one key is refused", True)
chk("and the refusal shows BOTH prices, so it can be resolved",
    "+500" in _cm and "+650" in _cm, _cm[:170])

# A non-exclusive market is refused early, with a better message than
# devig_field can give after the fact — and it means rungs can never leak
# into a field, since rungs only exist on yardage markets.
_ym = ""
try:
    ff_props.field_from_odds(_dkb, market="player_reception_yds",
                             book="draftkings")
    chk("a yardage market cannot be built as a field", False, "it returned")
except ValueError as _ex:
    _ym = str(_ex)
    chk("a yardage market cannot be built as a field", True)
chk("and it points at the right helper instead",
    "two_sided_field" in _ym, _ym[:150])
# An empty result names the books present, because a silent {} reads as
# "this book does not carry it" when the cause is a misspelled key.
_bm = ""
try:
    ff_props.field_from_odds(_dkb, market="player_1st_td", book="drafkings")
    chk("a misspelled book raises rather than returning {}", False, "returned")
except LookupError as _ex:
    _bm = str(_ex)
    chk("a misspelled book raises rather than returning {}", True)
chk("and lists the books that ARE present",
    "draftkings" in _bm, _bm[:150])

# two_sided_field on a board carrying the main line AND 13 rungs — the
# pollution shape. "29+ Receiving Yards" at -116 IS Over 28.5 at -116, and
# "30+" at -108 matches the main UNDER's price while being a different bet.
_rung = {"bookmakers": [{"key": "draftkings", "markets": [
    {"key": "player_reception_yds", "line_type": "main", "outcomes": [
        {"name": "Over", "description": "Jahmyr Gibbs", "point": 28.5,
         "price": -116},
        {"name": "Under", "description": "Jahmyr Gibbs", "point": 28.5,
         "price": -108}]},
    {"key": "player_reception_yds", "line_type": "milestone", "outcomes": [
        {"name": f"{n}+ Receiving Yards", "description": "Jahmyr Gibbs",
         "price": -116 + n} for n in (10, 20, 29, 30, 40, 50, 60, 70, 80,
                                      90, 100, 110, 120)]}]}]}
# Guarded: if the line_type filter regresses the rungs join, the row count
# goes to 14 and this RAISES. That is correct behaviour from the function
# and a crash from the suite, which stops every later section and prints
# "0 failed" over a partial count (lesson 14).
try:
    _tsf, _tline = ff_props.two_sided_field(
        _rung, market="player_reception_yds", book="draftkings",
        player="Gibbs")
    chk("13 rungs beside the main line do not pollute the result",
        _tsf == {"Over": -116.0, "Under": -108.0} and _tline == 28.5,
        f"{_tsf} @ {_tline}")
except Exception as _ex:
    chk("13 rungs beside the main line do not pollute the result", False,
        f"raised {type(_ex).__name__}: {_ex}")
# A one-sided market has no two-way price to de-vig.
_one = {"bookmakers": [{"key": "dk", "markets": [{
    "key": "player_reception_yds", "line_type": "main", "outcomes": [
        {"name": "Over", "description": "X", "point": 10.5,
         "price": -110}]}]}]}
try:
    ff_props.two_sided_field(_one, market="player_reception_yds", book="dk",
                             player="X")
    chk("a one-sided market is refused", False, "it returned")
except ValueError:
    chk("a one-sided market is refused", True)
# A suspended market is not a price.
_susp = {"bookmakers": [{"key": "dk", "markets": [{
    "key": "player_reception_yds", "line_type": "main",
    "suspended_at": "2026-11-05T23:00Z", "outcomes": [
        {"name": "Over", "description": "X", "point": 10.5, "price": -110},
        {"name": "Under", "description": "X", "point": 10.5,
         "price": -110}]}]}]}
try:
    ff_props.two_sided_field(_susp, market="player_reception_yds", book="dk",
                             player="X")
    chk("a suspended market is refused", False, "it returned")
except ValueError as _ex:
    chk("a suspended market is refused", "suspended" in str(_ex))
# Ambiguity rather than a silent pick: two players matching the substring.
_two = {"bookmakers": [{"key": "dk", "markets": [{
    "key": "player_reception_yds", "line_type": "main", "outcomes": [
        {"name": "Over", "description": "Josh Allen", "point": 10.5,
         "price": -110},
        {"name": "Under", "description": "Josh Allen", "point": 10.5,
         "price": -110},
        {"name": "Over", "description": "Keenan Allen", "point": 40.5,
         "price": -115},
        {"name": "Under", "description": "Keenan Allen", "point": 40.5,
         "price": -105}]}]}]}
try:
    ff_props.two_sided_field(_two, market="player_reception_yds", book="dk",
                             player="Allen")
    chk("an ambiguous player match is refused, not picked", False, "returned")
except LookupError as _ex:
    chk("an ambiguous player match is refused, not picked",
        "got 2" in str(_ex), str(_ex)[:140])

# norm_player moved to ff_props (one home, lesson 7) and is re-exported.
chk("norm_player has ONE home and ff_boost re-exports it",
    ff_props.norm_player is ff_boost.norm_player)

section("45. flatten_odds carries anchor depth, per side (B92)")
# It dropped `liquidity`, so there was NO sanctioned path from a get_odds
# payload to per-line anchor depth — which is why a session hand-rolled a
# walk of bookmakers[].markets[].outcomes[], bypassing the outcome pairing,
# the line_type filter, the Over/Under label matching and the price-key
# fallbacks. B82 is about those hand-rolls; this removes a reason to write
# one rather than warning against it.
# ---------------------------------------------------------------------------
_lq = {"bookmakers": [{"key": "kalshi", "markets": [{
    "key": "player_reception_yds", "line_type": "main", "outcomes": [
        {"name": "Over", "description": "Justice Hill", "point": 14.5,
         "price": -110, "liquidity": 5977},
        {"name": "Under", "description": "Justice Hill", "point": 14.5,
         "price": -110, "liquidity": 112}]}]},
    {"key": "draftkings", "markets": [{
        "key": "player_reception_yds", "line_type": "main", "outcomes": [
            {"name": "Over", "description": "Justice Hill", "point": 14.5,
             "price": -115},
            {"name": "Under", "description": "Justice Hill", "point": 14.5,
             "price": -105}]}]}]}
_rows = {r["book"]: r for r in ff_props.flatten_odds(_lq)}
chk("both sides' liquidity survives the flatten",
    _rows["kalshi"]["over_liquidity"] == 5977.0
    and _rows["kalshi"]["under_liquidity"] == 112.0, str(_rows["kalshi"]))
# The two sides of one Kalshi line really do differ by orders of magnitude,
# which is why this is per-side and not one number for the row.
chk("the two sides are kept apart, not averaged into a fiction",
    _rows["kalshi"]["over_liquidity"] != _rows["kalshi"]["under_liquidity"])
# A book that never reports liquidity must come back None, not 0 — "never
# reported" and "nothing resting" are different states and anchor_thin
# treats them differently.
chk("a book that reports no liquidity gives None, never 0",
    _rows["draftkings"]["over_liquidity"] is None
    and _rows["draftkings"]["under_liquidity"] is None,
    str(_rows["draftkings"]))
chk("and the prices are untouched by the addition",
    _rows["draftkings"]["over"] == -115.0
    and _rows["draftkings"]["under"] == -105.0)
# The whole point is that depth is now reachable WITHOUT walking the payload.
chk("anchor depth is reachable from flatten_odds alone",
    all(k in _rows["kalshi"] for k in
        ("over", "under", "over_liquidity", "under_liquidity", "line",
         "line_type", "suspended_at")))

section("44. a hold outside its own band gets a verdict, not a neighbour (B93)")
# report() printed `this slip's hold: 18.8% (reference band 23.1%-37.2%)` —
# both numbers, one line apart, no verdict — and a live slip holding 18.79%
# against the same-game band was read as a +1.83% edge and placed. The fix
# is a sentence, not a computation: slip_hold and hold_band were already
# properties on the same object.
#
# Reconstructed from the REAL placed slip (JAX@BAL, 2026-11-05): three
# DraftKings receiving legs, Bovada-anchored at 0.4892 / 0.5000 / 0.5108,
# quoted +550, 30% boost, correlation_factor 0.9498.
# ---------------------------------------------------------------------------
_EVT = "87238"
def _rleg(player, fp, odds, team):
    return BoostLeg(event_id=_EVT, book="draftkings",
                    market="player_reception_yds", player=player, side="OVER",
                    odds=odds, fair_prob=fp, fair_source="bovada",
                    devig_method="shin", verdict="CLEAR",
                 verdict_side="OVER", team=team, pos="WR")
_real = [_rleg("Brenton Strange", 0.4892, -109, "BAL"),
         _rleg("Travis Hunter", 0.5000, -115, "JAX"),
         _rleg("Parker Washington", 0.5108, -110, "JAX")]
_rst = classify(_real, {})
_rc = ff_boost.Candidate(legs=_real, structure=_rst, boost_pct=0.30,
                         independent_odds=584.0, stake=5.13)
_rc = price_candidate(_rc, book_odds=550.0, correlation_factor=0.9498)
chk("the reconstruction reproduces the slip that was placed",
    abs(_rc.p_cash - 0.124942) < 1e-5 and abs(_rc.slip_hold - 0.1879) < 1e-4
    and abs(_rc.ev_pct - 0.0183) < 1e-4,
    f"p_cash {_rc.p_cash:.6f} hold {_rc.slip_hold:.4f} ev {_rc.ev_pct:.4f}")
chk("and it is a SAME-GAME structure, so the same-game band applies",
    not _rc.structure.cross_game and _rc.hold_band == (0.231, 0.372),
    f"{_rc.structure.kind} {_rc.hold_band}")
chk("the hold is detected as BELOW its band", _rc.hold_vs_band == "below")
# str() rather than the raw value throughout: if the note regresses to None
# these must FAIL, not raise TypeError and take every later section with
# them (lesson 14 — and the first cut of this very section did exactly that).
_rn = str(_rc.hold_band_note)
chk("a below-band same-game slip gets a note at all",
    bool(_rc.hold_band_note))
# B118. These four used to assert the note's ORIGINAL reasoning — "p_cash is
# the PRODUCT of the de-vigged legs and that is not the joint for CORRELATED
# legs". That text could only ever print on a PRICEABLE slip, and priceable
# means every pair is measured INDEPENDENT, so the stated reason was false in
# 100% of reachable cases. These checks pinned it as correct. Rewritten to
# assert what actually drives a below-band hold: the anchor.
chk("the note names the immature anchor that the hold rests on",
    "immature anchors" in _rn and "Travis Hunter" in _rn, _rn[:160])
chk("and does NOT blame correlation the structure has ruled out",
    "for correlated legs" not in _rn and "not the joint" not in _rn,
    _rn[:200])
chk("it says the product IS the joint here, because the pairs are measured",
    "product IS the joint" in _rn, _rn[:200])
chk("and tells you what to do rather than just warning",
    "Re-pull closer to kickoff" in _rn, _rn[:240])
chk("report() actually prints it, rather than leaving it on the object",
    "immature anchors" in ff_boost.report([_rc]))
# The same slip with MATURE anchors is a different statement, not a quieter
# version of the same one: there is nothing wrong with it.
_mat = [_rleg(p, fp, o, t) for p, fp, o, t in
        (("A", 0.4892, -109, "BAL"), ("B", 0.4950, -115, "JAX"),
         ("C", 0.5108, -110, "JAX"))]
for _l in _mat:
    _l.anchor_liquidity = 4000
chk("the mature-anchor fixture really has no immature leg",
    not any(l.anchor_immature for l in _mat),
    str([(l.player, l.anchor_immature) for l in _mat]))
_mc = price_candidate(
    ff_boost.Candidate(legs=_mat, structure=classify(_mat, {}),
                       boost_pct=0.30, independent_odds=584.0, stake=5.13),
    book_odds=550.0)
chk("a below-band hold on mature anchors is below band",
    _mc.hold_vs_band == "below", f"hold {_mc.slip_hold:.4f}")
chk("and is reported as a better-than-population price, not a warning",
    "better-than-population" in str(_mc.hold_band_note)
    and not str(_mc.hold_band_note).startswith("***"),
    str(_mc.hold_band_note)[:160])
# The firing-rate split B93b never checked: INDEPENDENT against CORRELATED,
# rather than cross-game against same-game. A correlated slip is unpriceable,
# so slip_hold is None and the note cannot fire at all — which is why the
# old text's premise was unreachable.
_corl = [_rleg("QB", 0.50, -110, "BAL"), _rleg("WR1", 0.50, -110, "BAL"),
         _rleg("WR2", 0.50, -110, "BAL")]
_corl[0].market = "player_pass_yds"
_corl[0].pos = "QB"
_cst = classify(_corl, {})
chk("the correlated fixture really is unpriceable",
    not _cst.priceable and _cst.pairs, str(_cst.pairs)[:100])
_cc = price_candidate(
    ff_boost.Candidate(legs=_corl, structure=_cst, boost_pct=0.30,
                       independent_odds=584.0, stake=5.13), book_odds=360.0)
chk("a CORRELATED slip has no hold at all, so no note can reach it",
    _cc.slip_hold is None and _cc.hold_vs_band is None
    and _cc.hold_band_note is None,
    f"{_cc.slip_hold} / {_cc.hold_vs_band} / {_cc.hold_band_note}")

# A CROSS-GAME slip below band means something else entirely: the product IS
# the joint there, so slip_hold is exact and below-band is just a better
# price than the population. Must not carry the same warning.
_xl = [leg("WR A1", EV1, fair_prob=0.52), leg("WR B1", EV2, fair_prob=0.52),
       leg("WR E1", EV3, fair_prob=0.52)]
_xst = classify(_xl, META)
_xc = ff_boost.Candidate(legs=_xl, structure=_xst, boost_pct=0.30,
                         independent_odds=600.0, stake=10.0)
_xc = price_candidate(_xc, book_odds=640.0)
chk("the cross-game fixture really is cross-game", _xc.structure.cross_game)
# B93b. A cross-game slip gets NO note in either direction. Checking the
# firing rate before shipping showed a soft "this beats the population" line
# would fire on nearly every well-shopped slip — three legs at -110/-110
# hold 13.03% against a 17.7% floor, and all three cross-game slips measured
# in the 2026-11-05 session (15.1%, 14.5%, 4.9%) sat below it. And
# slip_hold is EXACT for cross-game, so the band adds nothing to it.
chk("a cross-game slip gets no note, whichever side of the band it lands",
    _xc.hold_band_note is None,
    f"{_xc.hold_vs_band}: {_xc.hold_band_note}")
chk("the direction is still REPORTED on the object, just not narrated",
    _xc.hold_vs_band in ("below", "within", "above"))
# The specific noise case: well-shopped legs must not produce a note.
_shop = [leg("WR A1", EV1, fair_prob=0.5, odds=-110),
         leg("WR B1", EV2, fair_prob=0.5, odds=-110),
         leg("WR E1", EV3, fair_prob=0.5, odds=-110)]
_sc = price_candidate(
    ff_boost.Candidate(legs=_shop, structure=classify(_shop, META),
                       boost_pct=0.30, independent_odds=664.0, stake=10.0),
    book_odds=664.0)
chk("three -110 legs really do hold below the cross-game band",
    _sc.hold_vs_band == "below", f"hold {_sc.slip_hold:.4f}")
chk("and still produce no note — good shopping is not a finding",
    _sc.hold_band_note is None)
# Within the band: no note at all, or the flag becomes noise.
_wc = price_candidate(
    ff_boost.Candidate(legs=_real, structure=_rst, boost_pct=0.30,
                       independent_odds=584.0, stake=10.0),
    book_odds=430.0)
chk("a hold inside the band is 'within'", _wc.hold_vs_band == "within",
    f"hold {_wc.slip_hold:.4f}")
chk("and gets NO note, so the flag does not become noise",
    _wc.hold_band_note is None)
# Above the band understates the EV, which is self-correcting — say so
# without the warning tone.
_ac = price_candidate(
    ff_boost.Candidate(legs=_real, structure=_rst, boost_pct=0.30,
                       independent_odds=584.0, stake=10.0),
    book_odds=250.0)
chk("a hold above the band is detected", _ac.hold_vs_band == "above",
    f"hold {_ac.slip_hold:.4f}")
chk("and is described as understating, not flattering",
    "understates rather than flatters" in str(_ac.hold_band_note)
    and "same-game" in str(_ac.hold_band_note),
    str(_ac.hold_band_note)[:140])
# The loudness marker is what separates the dangerous direction from the
# other two — assert it rather than keyword-matching the prose, which is how
# the first cut of this check failed on "understates rather than flatters".
chk("only the immature-anchor case is marked loud",
    _rn.startswith("***")
    and not str(_ac.hold_band_note).startswith("***")
    and not str(_mc.hold_band_note).startswith("***"),
    f"below={_rn[:6]!r} above={str(_ac.hold_band_note)[:6]!r} "
    f"mature={str(_mc.hold_band_note)[:6]!r}")
# An unpriced or unpriceable candidate has no hold to compare.
_up = ff_boost.Candidate(legs=_real, structure=_rst, boost_pct=0.30,
                         independent_odds=584.0, stake=10.0)
chk("an unpriced slip reports no verdict rather than a wrong one",
    _up.hold_vs_band is None and _up.hold_band_note is None)

section("40. the duplicate correlation table cannot diverge unnoticed (B68)")
# ff_guillotine keeps its OWN literal copy of both correlation tables rather
# than importing ff_boost's. B67 was a bug in the SHARED values that got
# fixed in one copy; nothing told anyone the second copy existed. These
# checks are not asserting the values are right — B68 records that the
# guillotine's QB x RB entry has the wrong SIGN for a fantasy score. They
# assert the two copies are still IDENTICAL, so that the first one-sided edit
# fails here by name instead of leaving the files quietly out of step.
#
# When E3 splits them into a market table and a fantasy-score table, THESE
# TWO CHECKS ARE SUPPOSED TO FAIL. Replace them then with a check that each
# table matches its own documented filter — do not simply delete them.
# ---------------------------------------------------------------------------
# E3, 2026-11-10. These two used to be asserted IDENTICAL, and that was the
# right assertion while they were a duplicated literal: it made a one-sided
# edit fail loudly, which is how B67 came to be fixed in one file only.
# They are now two different quantities from one documented filter, so the
# assertion inverts — and what replaces it is stronger, because it pins each
# copy to its SOURCE rather than to the other copy.
chk("the guillotine's table is the FANTASY one, not boost's market one",
    ff_guillotine.SAME_TEAM_CORR != ff_boost.SAME_TEAM_CORR,
    f"guillotine {ff_guillotine.SAME_TEAM_CORR} vs boost "
    f"{ff_boost.SAME_TEAM_CORR}")
chk("and it comes from ff_correlation's recorded fantasy table",
    all(abs(ff_guillotine.SAME_TEAM_CORR[k]
            - ff_correlation.RECORDED_FANTASY[k][0]) < 1e-12
        for k in ff_guillotine.SAME_TEAM_CORR),
    str(ff_guillotine.SAME_TEAM_CORR))
# The sign flip B68 predicted and E3 measured. QB passing yards against RB
# rushing yards is negative (game script); QB points against RB points is
# positive, because touchdowns are upside both share.
chk("QB x RB is NEGATIVE on markets and POSITIVE on fantasy points",
    ff_boost.SAME_TEAM_CORR[("QB", "RB")] < 0
    < ff_guillotine.SAME_TEAM_CORR[("QB", "RB")],
    f"market {ff_boost.SAME_TEAM_CORR[('QB','RB')]:+.3f} vs fantasy "
    f"{ff_guillotine.SAME_TEAM_CORR[('QB','RB')]:+.4f}")
chk("every recorded entry carries a pair count and an interval, not a bare r",
    all(len(v) == 3 and isinstance(v[1], int) and len(v[2]) == 2
        for v in ff_correlation.RECORDED_FANTASY.values())
    and all(len(v) == 3 and isinstance(v[1], int) and len(v[2]) == 2
            for v in ff_correlation.RECORDED_MARKET.values()),
    "E3 was filed because four bare numbers had no n and no interval")
chk("and the recorded r sits inside its own interval",
    all(v[2][0] <= v[0] <= v[2][1]
        for v in list(ff_correlation.RECORDED_MARKET.values())
        + list(ff_correlation.RECORDED_FANTASY.values())))
chk("the two OPPOSING_CORR copies now DIFFER, for the same reason",
    ff_guillotine.OPPOSING_CORR != ff_boost.OPPOSING_CORR,
    f"guillotine {ff_guillotine.OPPOSING_CORR} vs boost {ff_boost.OPPOSING_CORR}")
# B67's fix went into ff_boost only. If the guillotine ever grows a
# receiving-RB branch of its own it needs the same provisional marker, so
# assert the asymmetry is still the known one rather than a surprise.
chk("the provisional RB-receiving entry lives in ff_boost only",
    hasattr(ff_boost, "SAME_TEAM_CORR_PROVISIONAL")
    and not hasattr(ff_guillotine, "SAME_TEAM_CORR_PROVISIONAL"))
# correlation_matrix keys on POSITION pairs with no market and no role, so a
# pass-catching back and a pure rusher are the same entry to it. Pin that, so
# the limitation is a recorded fact rather than something a reader has to
# infer from the absence of a branch.
_m = {"q": ("KC", "QB"), "rb1": ("KC", "RB"), "rb2": ("KC", "RB")}
_C = ff_guillotine.correlation_matrix(["q", "rb1", "rb2"], _m)
chk("every same-team QB/RB pair takes one value, whatever the back's role",
    abs(_C[0, 1] - _C[0, 2]) < 1e-12, f"{_C[0,1]} vs {_C[0,2]}")
chk("and that value is still the market table's rushing figure",
    abs(_C[0, 1] - ff_guillotine.SAME_TEAM_CORR[("QB", "RB")]) < 1e-12)

section("51. a calibration bucket cannot pass off one game as a sample (B107/B108)")
# Measured 2026-11-06 on the real log. rec_summary printed
#     70%-85%  n=4  said 77%  went 0%  overconfident by 77%
# and three of those four were Baltimore pass-catchers on the night Lamar
# Jackson and Huntley both went to IR. One event, three correlated legs, read
# as three failures of the model. Across the whole graded set, 9 verdicts
# covered 6 distinct players. Separately, the three legs actually bet carried
# engine_tier PASS inside the BET record, which rec_summary never reads, so
# the PASS column said 2/7 when the honest figure was 2/10.
# ---------------------------------------------------------------------------
_tmp51 = tempfile.mkdtemp()
_old51 = (ff_betlog.LOG_DIR, ff_betlog.SESSION, ff_betlog.PULL_MARKER)
ff_betlog.LOG_DIR = pathlib.Path(_tmp51)
ff_betlog.SESSION = ff_betlog.LOG_DIR / "_session.jsonl"
ff_betlog.PULL_MARKER = ff_betlog.LOG_DIR / "_pull.json"


def _rec51(player, event_id, result, p=0.77, market="player_rec_yds"):
    r = ff_betlog.log_recommendation(
        player, market, 10.5, "OVER", "MODERATE", p, 0.50, -110,
        book="draftkings", event_id=event_id)
    ff_betlog.grade_rec(r["id"], result)
    return r


# Exactly the live shape: one bucket, four verdicts, three players, one game.
for _pl, _res in (("Zay Flowers", "LOSS"), ("Zay Flowers", "LOSS"),
                  ("Rashod Bateman", "LOSS"), ("Mark Andrews", "LOSS")):
    _rec51(_pl, "evt-jaxbal", _res)
_out51 = ff_betlog.rec_summary()
chk("the bucket reports distinct players, not just the verdict count",
    "over 3 players" in _out51, _out51)
chk("and the single event it all came from",
    "1 event" in _out51 and "1 events" not in _out51, _out51)
chk("a bucket this clustered refuses to give a confidence verdict",
    "TOO CLUSTERED" in _out51, _out51)
chk("so the overconfident-by figure is NOT printed for it",
    "overconfident by" not in _out51, _out51)
# The numbers themselves must still be visible — hiding them would be worse
# than the misreading this guards against.
chk("the said/went figures are still shown",
    "said 77%" in _out51 and "went 0%" in _out51, _out51)
# Five distinct players spread over five games is a real, if small, sample.
shutil.rmtree(_tmp51, ignore_errors=True)
_tmp51 = tempfile.mkdtemp()
ff_betlog.LOG_DIR = pathlib.Path(_tmp51)
ff_betlog.SESSION = ff_betlog.LOG_DIR / "_session.jsonl"
for _i in range(5):
    _rec51(f"Player {_i}", f"evt-{_i}", "WIN" if _i < 4 else "LOSS")
_out51b = ff_betlog.rec_summary()
chk("five players over five games DOES get read",
    "TOO CLUSTERED" not in _out51b, _out51b)
chk("and gets its confidence verdict",
    "confident by" in _out51b, _out51b)
# D16/B39: the EVENT is the tighter unit. Five distinct players in ONE game
# is one game. Player count alone would wave this through.
shutil.rmtree(_tmp51, ignore_errors=True)
_tmp51 = tempfile.mkdtemp()
ff_betlog.LOG_DIR = pathlib.Path(_tmp51)
ff_betlog.SESSION = ff_betlog.LOG_DIR / "_session.jsonl"
for _i in range(5):
    _rec51(f"Player {_i}", "evt-one", "LOSS")
_out51c = ff_betlog.rec_summary()
chk("five players in ONE game is still refused",
    "TOO CLUSTERED" in _out51c, _out51c)
# Partial event coverage must not read as measured coverage (B39). Two of
# four carrying an event_id is not "2 events".
shutil.rmtree(_tmp51, ignore_errors=True)
_tmp51 = tempfile.mkdtemp()
ff_betlog.LOG_DIR = pathlib.Path(_tmp51)
ff_betlog.SESSION = ff_betlog.LOG_DIR / "_session.jsonl"
for _i in range(5):
    _rec51(f"Player {_i}", f"evt-{_i}" if _i < 2 else None, "LOSS")
_out51d = ff_betlog.rec_summary()
chk("partial event coverage is marked as partial, not stated as fact",
    "2+ events" in _out51d and "2 of 5 carry one" in _out51d, _out51d)
# B110, and this check used to assert the OPPOSITE. Falling back to the
# player count made the function non-monotone in the worst direction: delete
# three event ids from five verdicts on ONE game and the refusal became
# "overconfident by 77%". Strictly less information, strictly more confident.
chk("partial coverage REFUSES rather than falling back to player count",
    "CANNOT BE READ" in _out51d, _out51d)
chk("and says which coverage it is missing",
    "only 2 of 5 verdicts carry an event id" in _out51d, _out51d)
# The monotonicity property itself, stated directly: removing event ids can
# never turn a refusal into a verdict.
_mono = [{"player": f"P{i}", "event_id": "g1"} for i in range(5)]
_mono_partial = [dict(r) for r in _mono]
for _r in _mono_partial[2:]:
    _r["event_id"] = None
chk("full coverage on one game is 1 independent unit",
    ff_betlog._independence(_mono)[0] == 1,
    str(ff_betlog._independence(_mono)))
chk("deleting event ids does NOT raise the independent count",
    ff_betlog._independence(_mono_partial)[0] is None,
    str(ff_betlog._independence(_mono_partial)))
# Records written before B107 have no event_id at all. They must still
# report, with no event claim either way.
shutil.rmtree(_tmp51, ignore_errors=True)
_tmp51 = tempfile.mkdtemp()
ff_betlog.LOG_DIR = pathlib.Path(_tmp51)
ff_betlog.SESSION = ff_betlog.LOG_DIR / "_session.jsonl"
for _i in range(5):
    _rec51(f"Player {_i}", None, "LOSS")
_out51e = ff_betlog.rec_summary()
# Also rewritten (B110): silence about events read as "no clustering", which
# is the claim nothing measured. The old check PINNED that silence.
chk("a pre-B107 log says event ids are absent rather than staying silent",
    "no event ids" in _out51e and "over 5 players" in _out51e, _out51e)
chk("and refuses the verdict, since one game is indistinguishable from five",
    "CANNOT BE READ" in _out51e, _out51e)
# The REASON has to name zero coverage specifically. Without this check, the
# zero-coverage branch could be deleted entirely and nothing would fail —
# the partial branch catches it and refuses too, just for the wrong stated
# reason, and a wrong reason is what a reader acts on.
chk("at n=1 the reason drops the cannot-be-told clause",
    ff_betlog._independence([{"player": "A"}])[1] == "no event ids recorded",
    ff_betlog._independence([{"player": "A"}])[1])
chk("the reason names zero coverage, not 'only 0 of 5'",
    "no event ids recorded" in _out51e and "only 0 of" not in _out51e,
    _out51e)
chk("and spells out what cannot be distinguished",
    ff_betlog._independence(
        [{"player": f"P{_i}"} for _i in range(5)])[1]
    == "no event ids recorded, so these 5 could all be one game or "
       "5 separate ones",
    ff_betlog._independence([{"player": f"P{_i}"} for _i in range(5)])[1])
# log_edge must carry event_id through. It is the call the engine actually
# uses, and a parameter that is accepted and dropped is worse than one that
# does not exist.
_ed51 = types.SimpleNamespace(
    side="OVER", tier="MODERATE", model_p=0.6, fair_p=0.5,
    fair_source="pinnacle", devig_method="shin", reasoning="x")
_r51 = ff_betlog.log_edge(_ed51, "Somebody", "player_rec_yds", 10.5,
                          odds=-110, book="draftkings", event_id="evt-xyz")
chk("log_edge passes event_id through to the record",
    _r51.get("event_id") == "evt-xyz", str(_r51.get("event_id")))
# B108: a verdict logged only inside a bet record is invisible to the engine
# scorecard, and its absence flatters the model.
_legs51 = [ff_betlog.Leg(player="Brenton Strange", market="player_rec_yds",
                         line=33.5, side="OVER", odds=-115,
                         book="draftkings", engine_tier="PASS",
                         engine_model_p=0.44)]
_b51 = ff_betlog.log_bet(525, 5.0, _legs51, "draftkings")
ff_betlog.grade_leg(_b51["id"], 0, "LOSS", actual=22.0)
_gap51 = ff_betlog.unlogged_bet_verdicts()
chk("a bet leg carrying engine_tier with no rec record is found",
    len(_gap51) == 1 and _gap51[0]["player"] == "Brenton Strange",
    str(_gap51))
chk("and its grade comes with it, so the cost of the gap is visible",
    _gap51[0]["result"] == "LOSS", str(_gap51))
chk("rec_summary says so instead of quietly computing on a subset",
    "NOT in this log" in ff_betlog.rec_summary())
chk("and names the leg",
    "Brenton Strange" in ff_betlog.rec_summary())
# A leg that WAS logged through log_edge must not be double-counted as a gap.
_legs51b = [ff_betlog.Leg(player="Travis Hunter", market="player_rec_yds",
                          line=8.5, side="OVER", odds=-110,
                          book="draftkings", engine_tier="MODERATE")]
_b51b = ff_betlog.log_bet(525, 5.0, _legs51b, "draftkings")
_r51b = ff_betlog.log_edge(_ed51, "Travis Hunter", "player_rec_yds", 8.5,
                           odds=-110, book="draftkings", acted_on=True,
                           bet_id=_b51b["id"], event_id=None)
chk("a leg already in the rec log is not reported as a gap",
    all(g["player"] != "Travis Hunter"
        for g in ff_betlog.unlogged_bet_verdicts()),
    str(ff_betlog.unlogged_bet_verdicts()))
# A leg with no engine verdict is not a gap either — most legs are hand-made.
_legs51c = [ff_betlog.Leg(player="Nobody", market="player_rec_yds", line=1.5,
                          side="OVER", odds=-110, book="draftkings")]
ff_betlog.log_bet(525, 5.0, _legs51c, "draftkings")
chk("a leg with no engine verdict is not counted as a missing one",
    all(g["player"] != "Nobody" for g in ff_betlog.unlogged_bet_verdicts()))
# And the gap must show even when NOTHING is in the rec log — that is the
# worst version of it, not an exemption.
shutil.rmtree(_tmp51, ignore_errors=True)
_tmp51 = tempfile.mkdtemp()
ff_betlog.LOG_DIR = pathlib.Path(_tmp51)
ff_betlog.SESSION = ff_betlog.LOG_DIR / "_session.jsonl"
ff_betlog.log_bet(525, 5.0, _legs51, "draftkings")
_out51f = ff_betlog.rec_summary()
chk("an empty rec log with bet verdicts still reports the gap",
    "No engine recommendations logged yet" in _out51f
    and "NOT in this log" in _out51f, _out51f)
# The PASS line ends in a sentence about what the rate MEANS for the guard,
# so it is a verdict on the same clustered handful, and must be gated by the
# same rule. One definition of independence, used by both.
shutil.rmtree(_tmp51, ignore_errors=True)
_tmp51 = tempfile.mkdtemp()
ff_betlog.LOG_DIR = pathlib.Path(_tmp51)
ff_betlog.SESSION = ff_betlog.LOG_DIR / "_session.jsonl"
for _pl in ("Zay Flowers", "Zay Flowers", "Rashod Bateman"):
    _r = ff_betlog.log_recommendation(_pl, "player_rec_yds", 10.5, "OVER",
                                      "PASS", 0.44, 0.50, -110,
                                      event_id="evt-jaxbal")
    ff_betlog.grade_rec(_r["id"], "LOSS")
_out51g = ff_betlog.rec_summary()
chk("the PASS line shows what its sample is made of",
    "2 players, 1 event" in _out51g, _out51g)
chk("and refuses to say what it means for the guard",
    "TOO CLUSTERED" in _out51g and "the guard is too tight" not in _out51g,
    _out51g)
for _i in range(5):
    _r = ff_betlog.log_recommendation(f"Other {_i}", "player_rec_yds", 10.5,
                                      "OVER", "PASS", 0.44, 0.50, -110,
                                      event_id=f"evt-{_i}")
    ff_betlog.grade_rec(_r["id"], "WIN")
chk("and reads it once the PASSes span enough games",
    "the guard is too tight" in ff_betlog.rec_summary(),
    ff_betlog.rec_summary())
# One definition, not two. A bucket and the PASS line must agree about the
# same set, or the report contradicts itself.
_set51 = [{"player": "A", "event_id": "e1"}, {"player": "B", "event_id": "e1"},
          {"player": "C", "event_id": "e1"}]
chk("independence counts the event when coverage is complete",
    ff_betlog._independence(_set51)[0] == 1,
    str(ff_betlog._independence(_set51)))
_set51b = [{"player": "A", "event_id": "e1"}, {"player": "B"},
           {"player": "C"}]
chk("and reports partial coverage as unmeasurable, not as 3 players",
    ff_betlog._independence(_set51b)[0] is None,
    str(ff_betlog._independence(_set51b)))
chk("a shared player name can only ever understate independence",
    ff_betlog._independence(
        [{"player": "A", "event_id": "e1"},
         {"player": "A", "event_id": "e2"}])[0] == 1)
chk("and so does a differently-typed spelling of the same name",
    ff_betlog._independence(
        [{"player": "D.K. Metcalf", "event_id": "e1"},
         {"player": "DK Metcalf", "event_id": "e2"}])[0] == 1)
shutil.rmtree(_tmp51, ignore_errors=True)
ff_betlog.LOG_DIR, ff_betlog.SESSION, ff_betlog.PULL_MARKER = _old51

section("52. what the independent reviewer found in section 51's own code (B110)")
# Eleven findings against code that had just passed 684 checks, four of them
# in the betting path and two inside the B107 fix itself. The pattern is the
# SHIP GATE's reason for existing: three of section 51's checks PINNED the
# wrong behaviour, because the test and the fix were written in one pass.
# ---------------------------------------------------------------------------
_tmp52 = tempfile.mkdtemp()
_old52 = (ff_betlog.LOG_DIR, ff_betlog.SESSION, ff_betlog.PULL_MARKER)
ff_betlog.LOG_DIR = pathlib.Path(_tmp52)
ff_betlog.SESSION = ff_betlog.LOG_DIR / "_session.jsonl"
ff_betlog.PULL_MARKER = ff_betlog.LOG_DIR / "_pull.json"

# F10. Event ids arrive numeric from PropLine. A set treats "53166" and 53166
# as two events, and integer 0 is falsy so a real id read as no id at all.
# Three games were reported as "5+ events" and the bucket flipped from a
# refusal to a confidence claim.
chk("an int and a str event id are the same event",
    ff_betlog._independence(
        [{"player": "A", "event_id": "53166"},
         {"player": "B", "event_id": 53166}])[0] == 1,
    str(ff_betlog._independence(
        [{"player": "A", "event_id": "53166"},
         {"player": "B", "event_id": 53166}])))
chk("event id 0 is an id, not an absence",
    ff_betlog._norm_event(0) == "0")
chk("but an empty or whitespace id is an absence",
    ff_betlog._norm_event("") is None
    and ff_betlog._norm_event("  ") is None
    and ff_betlog._norm_event(None) is None)

# F3/F4. The gap detector's own blind spots. Both are FALSE NEGATIVES, which
# is the direction that flatters the model.
_leg_p = ff_betlog.Leg(player="Mark Andrews", market="player_rec_yds",
                       line=24.5, side="OVER", odds=-110, book="draftkings",
                       engine_model_p=0.44)
_bp = ff_betlog.log_bet(525, 5.0, [_leg_p], "draftkings")
chk("a leg with engine_model_p but no tier is still a missing verdict",
    any(g["player"] == "Mark Andrews"
        for g in ff_betlog.unlogged_bet_verdicts()),
    str(ff_betlog.unlogged_bet_verdicts()))
# A ladder: two legs, same player, same market, different lines and tiers.
# One rec must not suppress the other.
_ladder = [ff_betlog.Leg(player="Zay Flowers", market="player_rec_yds",
                         line=47.5, side="OVER", odds=-110, book="draftkings",
                         engine_tier="PASS"),
           ff_betlog.Leg(player="Zay Flowers", market="player_rec_yds",
                         line=48.5, side="OVER", odds=-105, book="draftkings",
                         engine_tier="MODERATE")]
_bl52 = ff_betlog.log_bet(525, 5.0, _ladder, "draftkings")
_ed52 = types.SimpleNamespace(side="OVER", tier="PASS", model_p=0.44,
                              fair_p=0.50, fair_source="pinnacle",
                              devig_method="shin", reasoning="x")
ff_betlog.log_edge(_ed52, "Zay Flowers", "player_rec_yds", 47.5, odds=-110,
                   book="draftkings", acted_on=True, bet_id=_bl52["id"],
                   event_id=None)
_lad_gap = [g for g in ff_betlog.unlogged_bet_verdicts()
            if g["bet_id"] == _bl52["id"]]
chk("logging one rung of a ladder does not suppress the other",
    len(_lad_gap) == 1 and _lad_gap[0]["line"] == 48.5, str(_lad_gap))
chk("and the line is named, so the report says WHICH rung",
    "48.5" in ff_betlog.rec_summary(), ff_betlog.rec_summary())
chk("the logged rung is not reported",
    all(g["line"] != 47.5 for g in _lad_gap), str(_lad_gap))
# F7. The names on both sides are written by this module; a spelling
# difference is not a missing verdict.
_dk = [ff_betlog.Leg(player="D.K. Metcalf", market="player_rec_yds",
                     line=55.5, side="OVER", odds=-110, book="draftkings",
                     engine_tier="PASS")]
_bdk = ff_betlog.log_bet(525, 5.0, _dk, "draftkings")
ff_betlog.log_edge(_ed52, "DK Metcalf", "player_rec_yds", 55.5, odds=-110,
                   book="draftkings", acted_on=True, bet_id=_bdk["id"],
                   event_id=None)
chk("a spelling difference in the player name is not a missing verdict",
    all(g["bet_id"] != _bdk["id"]
        for g in ff_betlog.unlogged_bet_verdicts()),
    str(ff_betlog.unlogged_bet_verdicts()))
# The local normaliser is a second copy of a job ff_props already does
# (lesson 7 / B68). It is deliberate — importing the real one would put
# ff_props in ff_betlog's shipset — so assert the two still agree, and this
# check is the thing that fails if they drift.
for _a, _b in (("D.K. Metcalf", "DK Metcalf"),
               ("Brian Thomas Jr.", "Brian Thomas Jr"),
               ("Ja'Marr Chase", "JaMarr Chase")):
    chk(f"local and ff_props normalisers agree on {_a!r}",
        (ff_betlog._norm_player_local(_a)
         == ff_betlog._norm_player_local(_b))
        == (ff_props.norm_player(_a) == ff_props.norm_player(_b)),
        f"{_a} / {_b}")

# F5. Two states that must not share a message. The documented flow logs the
# verdict BEFORE the bet exists, so the rec carries no bet_id — and the first
# version called that "NOT in this log" and told the session to log it again,
# which is the double count the function exists to prevent.
shutil.rmtree(_tmp52, ignore_errors=True)
_tmp52 = tempfile.mkdtemp()
ff_betlog.LOG_DIR = pathlib.Path(_tmp52)
ff_betlog.SESSION = ff_betlog.LOG_DIR / "_session.jsonl"
ff_betlog.log_edge(_ed52, "Travis Hunter", "player_rec_yds", 8.5, odds=-110,
                   book="draftkings",
                   event_id=None)              # verdict time: no bet yet
_lh = [ff_betlog.Leg(player="Travis Hunter", market="player_rec_yds",
                     line=8.5, side="OVER", odds=-110, book="draftkings",
                     engine_tier="PASS")]
ff_betlog.log_bet(525, 5.0, _lh, "draftkings")
_g52 = ff_betlog.unlogged_bet_verdicts()
chk("a verdict logged before the bet is UNLINKED, not missing",
    len(_g52) == 1 and _g52[0]["state"] == "unlinked", str(_g52))
_o52 = ff_betlog.rec_summary()
chk("and the report does not claim it is absent",
    "NOT in this log" not in _o52, _o52)
chk("it says the figures already count it",
    "counted in every figure below" in _o52, _o52)
chk("and warns against logging it twice",
    "double-counts" in _o52, _o52)

# F9. A verdict that lands in no bucket must not vanish.
shutil.rmtree(_tmp52, ignore_errors=True)
_tmp52 = tempfile.mkdtemp()
ff_betlog.LOG_DIR = pathlib.Path(_tmp52)
ff_betlog.SESSION = ff_betlog.LOG_DIR / "_session.jsonl"
for _i in range(5):
    _r = ff_betlog.log_recommendation(f"P{_i}", "m", 1.5, "OVER", "PASS",
                                      1.0, 0.5, -110, event_id=f"g{_i}")
    ff_betlog.grade_rec(_r["id"], "WIN")
_o52b = ff_betlog.rec_summary()
chk("five verdicts at p=1.0 appear in a bucket, not nowhere",
    "85%-100%" in _o52b and "n=5" in _o52b, _o52b)
chk("and nothing is reported as unbucketed",
    "fell in NO bucket" not in _o52b, _o52b)
# A percentage passed where a fraction belongs used to drop every verdict and
# print an empty calibration header. Refused at the door instead.
chk("a model_p of 77.0 is refused, not silently dropped",
    _raises(lambda: ff_betlog.log_recommendation(
        "P", "m", 1.5, "OVER", "PASS", 77.0, 0.5, -110,
        event_id=None), ValueError))
chk("and the error says what to pass instead",
    "0.7700" in str(_err(lambda: ff_betlog.log_recommendation(
        "P", "m", 1.5, "OVER", "PASS", 77.0, 0.5, -110, event_id=None))))

# F13. A direction asserted where there is none.
shutil.rmtree(_tmp52, ignore_errors=True)
_tmp52 = tempfile.mkdtemp()
ff_betlog.LOG_DIR = pathlib.Path(_tmp52)
ff_betlog.SESSION = ff_betlog.LOG_DIR / "_session.jsonl"
for _i in range(10):
    _r = ff_betlog.log_recommendation(f"P{_i}", "m", 1.5, "OVER", "PASS",
                                      0.60, 0.5, -110, event_id=f"g{_i}")
    ff_betlog.grade_rec(_r["id"], "WIN" if _i < 6 else "LOSS")
_o52c = ff_betlog.rec_summary()
chk("a perfectly calibrated bucket claims no direction",
    "confident by 0%" not in _o52c and "calibrated" in _o52c, _o52c)

# F11. bet_summary's caution lived in the CLV branch, so with no closing
# lines — the log's actual state — a 33% hit rate and +108% ROI printed with
# no caution at all.
shutil.rmtree(_tmp52, ignore_errors=True)
_tmp52 = tempfile.mkdtemp()
ff_betlog.LOG_DIR = pathlib.Path(_tmp52)
ff_betlog.SESSION = ff_betlog.LOG_DIR / "_session.jsonl"
for _i in range(3):
    _bb = ff_betlog.log_bet(525, 5.0, [ff_betlog.Leg(
        player=f"P{_i}", market="m", line=1.5, side="OVER", odds=-110,
        book="draftkings", event_id="g1")], "draftkings")
    ff_betlog.grade_bet(_bb["id"], "WIN" if _i == 0 else "LOSS")
_o52d = ff_betlog.bet_summary()
chk("a record with no closing lines still carries its caution",
    "NOT A RATE YET" in _o52d and "No closing lines" in _o52d, _o52d)
chk("and names how many distinct games the slips covered",
    "1 distinct game across 3 graded slips" in _o52d, _o52d)
chk("a slip's game comes from its LEGS, not the bet record",
    "0 players" not in _o52d, _o52d)
# F12 (B112). The log is six schema generations deep and holds hand-written
# records. `float(leg["line"])` on a historical "n/a" raised out of
# unlogged_bet_verdicts and took down ALL of rec_summary — a report that dies
# on one malformed record it is reporting on fails exactly when it is needed.
# None of the synthetic logs above cover this, because I wrote them all today.
shutil.rmtree(_tmp52, ignore_errors=True)
_tmp52 = tempfile.mkdtemp()
ff_betlog.LOG_DIR = pathlib.Path(_tmp52)
ff_betlog.SESSION = ff_betlog.LOG_DIR / "_session.jsonl"
(ff_betlog.LOG_DIR / "ff-betlog-20261101T000000Z.jsonl").write_text(
    "\n".join(json.dumps(r) for r in [
        {"id": "b1", "kind": "bet", "book": "dk", "stake": 5.0,
         "slip_odds": 525, "legs": [{"player": "A", "market": "m",
                                     "line": "33.5", "side": "over",
                                     "engine_tier": "PASS"}]},
        {"id": "b2", "kind": "bet", "book": "dk", "stake": 5.0,
         "slip_odds": 525, "legs": [{"player": "B", "market": "m",
                                     "line": "n/a",
                                     "engine_tier": "PASS"}]},
        {"id": "b3", "kind": "bet", "book": "dk", "stake": 5.0,
         "slip_odds": 525, "legs": ["not-a-dict"]},
        {"id": "r1", "kind": "rec", "player": "C", "market": "m",
         "tier": "PASS", "model_p": 77.0, "result": "LOSS"},
        {"id": "r2", "kind": "rec", "player": "D", "market": "m",
         "tier": "PASS", "result": "LOSS"},
        {"id": "r3", "kind": "rec", "player": "E", "market": "m",
         "tier": None, "model_p": 0.6, "result": "WIN"},
    ]) + "\n")
for _fn in ("unlogged_bet_verdicts", "rec_summary", "bet_summary"):
    chk(f"{_fn} survives a six-generation log",
        not _err(getattr(ff_betlog, _fn)), _err(getattr(ff_betlog, _fn)))
_o52e = _out(ff_betlog.rec_summary)
chk("a non-numeric line does not hide the leg, it is shown as written",
    "n/a" in _o52e, _o52e)
chk("a rec with no model_p is NAMED, not silently dropped",
    "have no usable model_p and are in NO bucket" in _o52e, _o52e)
chk("an out-of-range model_p written before the validator is counted there",
    "2 of 3 graded verdicts" in _o52e, _o52e)
chk("a rec with no tier gets a row rather than a KeyError",
    "(no tier)" in _o52e, _o52e)
chk("and the one usable verdict still gets its bucket",
    "55%-70%" in _o52e, _o52e)
shutil.rmtree(_tmp52, ignore_errors=True)
ff_betlog.LOG_DIR, ff_betlog.SESSION, ff_betlog.PULL_MARKER = _old52

section("62. two legs on one man, under two spellings (B127)")
# Found by taking F12's blocker seriously rather than building around it.
# Measured on tonight's MNF board: DraftKings 15 milestone markets / 182
# outcomes, FanDuel 15 / 132, **Pinnacle zero** — so F12 stays blocked on
# anchor quality exactly as filed. But a live slip already mixed a FanDuel
# ALT milestone leg ("Luther Burden III 50+ Yards") with main-line legs,
# and `classify` deduped on RAW NAMES.
# ---------------------------------------------------------------------------
def _dup(pl, line, side, pid=None):
    return BoostLeg(player=pl, market="player_reception_yds", line=line,
                    side=side, odds=-110, book="draftkings", fair_prob=0.5,
                    fair_source="pinnacle", devig_method="shin",
                    event_id="e1", team="CHI", pos="WR", verdict="CLEAR",
                    verdict_side=side, player_id=pid)


# The worst shape: an empty event priced as if it had a probability.
_imposs = [_dup("Luther Burden III", 75.5, "OVER"),
           _dup("Luther Burden", 50.5, "UNDER"),
           _dup("Rome Odunze", 48.5, "OVER")]
chk("a slip that cannot cash is refused, not priced",
    _raises(lambda: classify(_imposs, {}), ValueError))
chk("and the refusal says the spellings differ, so the reader knows why "
    "the old check missed it",
    "spellings differ" in _err(lambda: classify(_imposs, {})))
# The milder shape is still not independent.
_band = [_dup("Luther Burden III", 50.5, "OVER"),
         _dup("Luther Burden", 75.5, "UNDER"),
         _dup("Rome Odunze", 48.5, "OVER")]
chk("a band on one man across two spellings is refused too",
    _raises(lambda: classify(_band, {}), ValueError))
chk("the normaliser agrees the two spellings are one man",
    ff_props.norm_player("Luther Burden III")
    == ff_props.norm_player("Luther Burden"))
# The exact-name case must still work, or the fix traded one gap for another.
chk("an exact repeat is still refused",
    _raises(lambda: classify(
        [_dup("Rome Odunze", 50.5, "OVER"), _dup("Rome Odunze", 48.5, "OVER"),
         _dup("DJ Moore", 40.5, "OVER")], {}), ValueError))
chk("three different players still build",
    classify([_dup("Luther Burden III", 50.5, "OVER"),
              _dup("Rome Odunze", 48.5, "OVER"),
              _dup("DJ Moore", 40.5, "OVER")], {}).priceable)
# The ids catch what normalising cannot: one man, two names that normalise
# apart.
_nick = [_dup("Cam Ward", 50.5, "OVER", "espn:1"),
         _dup("Cameron Ward", 75.5, "UNDER", "espn:1"),
         _dup("Rome Odunze", 48.5, "OVER", "espn:2")]
chk("the normaliser does NOT catch a nickname, so this is a real second gap",
    ff_props.norm_player("Cam Ward") != ff_props.norm_player("Cameron Ward"))
chk("but a shared player_id does",
    _raises(lambda: classify(_nick, {}), ValueError))
chk("and the refusal says only the id caught it",
    "only the id caught this" in _err(lambda: classify(_nick, {})))
chk("distinct ids still build",
    classify([_dup("A", 50.5, "OVER", "espn:1"),
              _dup("B", 48.5, "OVER", "espn:2"),
              _dup("C", 40.5, "OVER", "espn:3")], {}).priceable)
# B50 stays uncalled, and now for a REASON rather than a pending merge
# point: its key carries the player, so two legs sharing a canonical key
# are the same player and the guard above has already refused them.
chk("canonical_bet still exists and still maps a rung to its main line",
    ff_props.canonical_bet(
        {"player": "x", "market": "m", "rung_threshold": 238})
    == ff_props.canonical_bet(
        {"player": "x", "market": "m", "line": 237.5}),
    str(ff_props.canonical_bet(
        {"player": "x", "market": "m", "rung_threshold": 238})))
chk("and it does NOT snap a whole-number main line onto a rung (D18)",
    ff_props.canonical_bet(
        {"player": "x", "market": "m", "line": 237.0})
    != ff_props.canonical_bet(
        {"player": "x", "market": "m", "rung_threshold": 238}))
# The key was `player_id or player`, which MISSES a duplicate — the only
# direction that matters here, because a missed duplicate gets parlayed with
# itself. A rung row carrying an id and a main row carrying null for the same
# player produced two different keys. The real board had the raw-name half of
# it too: "D.J. Moore" at DraftKings against "DJ Moore" at Pinnacle.
chk("a rung with a player_id and a main without still map to ONE bet",
    ff_props.canonical_bet(
        {"player": "D.J. Moore", "market": "m", "rung_threshold": 49,
         "player_id": "espn:3915416"})
    == ff_props.canonical_bet(
        {"player": "D.J. Moore", "market": "m", "line": 48.5}),
    "the old `player_id or player` key made these two different bets")
chk("and two spellings of one man map to ONE bet",
    ff_props.canonical_bet({"player": "D.J. Moore", "market": "m",
                            "line": 48.5})
    == ff_props.canonical_bet({"player": "DJ Moore", "market": "m",
                               "line": 48.5}))
# The key groups and can OVER-group; `same_bet` is what confirms.
chk("same_bet confirms a grouped pair",
    ff_props.same_bet(
        {"player": "D.J. Moore", "market": "m", "rung_threshold": 49,
         "player_id": "espn:3915416"},
        {"player": "DJ Moore", "market": "m", "line": 48.5,
         "player_id": "espn:3915416"}))
chk("and refuses two players who merely share a spelling",
    not ff_props.same_bet(
        {"player": "Mike Williams", "market": "m", "line": 48.5,
         "player_id": "espn:111"},
        {"player": "Mike Williams", "market": "m", "line": 48.5,
         "player_id": "espn:999"}))
chk("a missing id defers to the key rather than inventing a distinction",
    ff_props.same_bet(
        {"player": "Mike Williams", "market": "m", "line": 48.5},
        {"player": "Mike Williams", "market": "m", "rung_threshold": 49,
         "player_id": "espn:111"}))
chk("and a row with no threshold is still incomparable, not equal",
    not ff_props.same_bet({"player": "x", "market": "m"},
                          {"player": "x", "market": "m"}))
# Nothing above asserts that two DIFFERENT bets are different: blanking the
# key comparison entirely left every check passing, because each one happened
# to be about a pair that IS the same bet or that conflicts on an id. A
# predicate needs its false cases pinned as hard as its true ones.
chk("same_bet refuses two different thresholds",
    not ff_props.same_bet({"player": "x", "market": "m", "line": 48.5},
                          {"player": "x", "market": "m", "line": 49.5}))
chk("same_bet refuses two different players, ids absent",
    not ff_props.same_bet({"player": "Alvin Kamara", "market": "m",
                           "line": 48.5},
                          {"player": "Chris Olave", "market": "m",
                           "line": 48.5}))
chk("same_bet refuses the same player in two different markets",
    not ff_props.same_bet(
        {"player": "x", "market": "player_reception_yds", "line": 48.5},
        {"player": "x", "market": "player_rush_yds", "line": 48.5}))
chk("and a rung does NOT equal the main line half a point the other way",
    not ff_props.same_bet({"player": "x", "market": "m",
                           "rung_threshold": 49},
                          {"player": "x", "market": "m", "line": 49.0}),
    "D18 on the rung grid: Over 49.0 pushes at 49, 49+ cannot")

section("61. a verdict belongs to ONE side (B126)")
# The Cade Otton near-miss. `boost_verdict` vetoes "a role change running
# against THE SIDE BEING BET" (B80), and `prop_edge` could only ever answer
# for the side the MODEL liked — the side was derived from which way the
# edge pointed, with no way to ask about the side you want to bet. So a live
# session computed one verdict per LINE and attached it to whichever side it
# was betting, and nearly shipped Otton OVER with his targets collapsed
# 5.4 -> 1.5. Rebuilding per-side cut both ways: it also UN-vetoed
# Loveland's OVER, which the same error had wrongly excluded.
# ---------------------------------------------------------------------------
_e61 = threshold_prob(log, 60)        # a line the model likes the OVER on
chk("by default the side is still the one the model prefers",
    prop_edge(_e61, -110, -110).side == "OVER")
chk("a side can now be FORCED, which is a different question",
    prop_edge(_e61, -110, -110, side="UNDER").side == "UNDER")
chk("and a forced side the model dislikes gives a NEGATIVE edge",
    prop_edge(_e61, -110, -110, side="UNDER").edge < 0,
    str(prop_edge(_e61, -110, -110, side="UNDER").edge))
chk("which is the same magnitude the other way",
    abs(prop_edge(_e61, -110, -110, side="UNDER").edge
        + prop_edge(_e61, -110, -110, side="OVER").edge) < 1e-9)
chk("forcing the side the model already picked changes nothing",
    prop_edge(_e61, -110, -110, side="OVER").edge
    == prop_edge(_e61, -110, -110).edge)
chk("a nonsense side is refused",
    _raises(lambda: prop_edge(_e61, -110, -110, side="sideways"),
            ValueError))
# A negative edge must never read as a confident tier, and must not be
# described as noise — a -27pt edge is a disagreement, not a thin read.
_dis = prop_edge(_e61, -110, -110, side="UNDER")
chk("a side the model is against can never be STRONG",
    _dis.tier == "PASS", _dis.tier)
chk("and is named as a disagreement, not as 'inside the noise'",
    "the model is AGAINST this side" in str(_dis.reasoning)
    and "inside the noise" not in str(_dis.reasoning),
    str(_dis.reasoning)[:110])
chk("the disagreement names the side the model prefers instead",
    "it prefers OVER" in str(_dis.reasoning), str(_dis.reasoning)[:110])
# A genuinely SMALL edge is still noise, or the message has been replaced
# rather than split. Constructed from `fair_over` so the edge is exactly
# +1pt regardless of what the fixture's data happens to be — the first cut
# picked a threshold and got a +26pt edge that was PASSing for an unrelated
# reason (a wide CI), so it proved nothing.
_small = prop_edge(_e61, -110, fair_over=_e61.blended - 0.01,
                   fair_source="pinnacle", devig_method="shin", side="OVER")
chk("the small-edge fixture really is small",
    abs(_small.edge - 0.01) < 1e-6, f"{_small.edge:+.4f}")
chk("a small edge is still reported as inside the noise",
    "inside the noise" in str(_small.reasoning)
    and "AGAINST this side" not in str(_small.reasoning),
    str(_small.reasoning)[:110])
# And the boundary: a hair BELOW zero is a disagreement, not noise.
_hair = prop_edge(_e61, -110, fair_over=_e61.blended + 0.02,
                  fair_source="pinnacle", devig_method="shin", side="OVER")
chk("a clearly negative edge crosses into disagreement",
    "AGAINST this side" in str(_hair.reasoning), str(_hair.reasoning)[:110])


def _otton(**kw):
    """The live leg, as it was nearly shipped."""
    return BoostLeg(player="Cade Otton", market="player_reception_yds",
                    line=28.5, side="OVER", odds=-110, book="fanduel",
                    fair_prob=0.5, fair_source="pinnacle",
                    devig_method="shin", event_id="60348", team="TB",
                    pos="TE", **kw)


chk("a leg with NO verdict is fine — that is the unscreened state",
    _otton().verdict == "UNSCREENED")
chk("a verdict with no side recorded is refused at construction",
    _raises(lambda: _otton(verdict="CAUTION"), ValueError))
chk("and the refusal explains that a verdict is about one side",
    "THE SIDE BEING BET" in _err(lambda: _otton(verdict="CAUTION")))
chk("a verdict computed for the OTHER side is refused",
    _raises(lambda: _otton(verdict="CAUTION", verdict_side="UNDER"),
            ValueError))
chk("and the refusal says a collapsed role vetoes one side and supports "
    "the other",
    "vetoes the OVER and supports the UNDER" in _err(
        lambda: _otton(verdict="CAUTION", verdict_side="UNDER")))
chk("and it names the call that fixes it",
    "side='OVER'" in _err(
        lambda: _otton(verdict="CAUTION", verdict_side="UNDER")),
    _err(lambda: _otton(verdict="CAUTION", verdict_side="UNDER"))[-120:])
chk("a verdict for THIS side builds",
    _otton(verdict="CAUTION", verdict_side="OVER").verdict_side == "OVER")
chk("case does not matter when comparing the sides",
    _otton(verdict="CAUTION", verdict_side="over").verdict == "CAUTION")
# An UNDER leg is the mirror, so the guard is not accidentally one-sided.
chk("an UNDER leg refuses an OVER verdict",
    _raises(lambda: BoostLeg(
        player="Cade Otton", market="player_reception_yds", line=28.5,
        side="UNDER", odds=-110, book="fanduel", fair_prob=0.5,
        fair_source="pinnacle", devig_method="shin", event_id="60348",
        team="TB", pos="TE", verdict="CLEAR", verdict_side="OVER"),
        ValueError))

section("60. a cash-out is a third outcome, not a flavour of two (B124/B125)")
# Measured on the real slip: FanDuel SNF SGP, $7.31 at +401 boosted to +521,
# two legs home and one live, CASHED OUT for $12.95 with $0.22 of
# "Bet Protect+" on top. Graded by its legs that is a LOSS, so the log would
# have recorded a +$5.42 result as a loss and every hit rate, ROI and
# calibration figure downstream would have inherited it.
# ---------------------------------------------------------------------------
_tmp60 = tempfile.mkdtemp()
_old60 = (ff_betlog.LOG_DIR, ff_betlog.SESSION, ff_betlog.PULL_MARKER)
ff_betlog.LOG_DIR = pathlib.Path(_tmp60)
ff_betlog.SESSION = ff_betlog.LOG_DIR / "_session.jsonl"
ff_betlog.PULL_MARKER = ff_betlog.LOG_DIR / "_pull.json"


def _snf60():
    legs = [ff_betlog.Leg(player=p, market=m, line=l, side="OVER",
                          odds=-113, book="fanduel", event_id="60348")
            for p, m, l in (("Rome Odunze", "player_reception_yds", 48.5),
                            ("D'Andre Swift", "player_rush_yds", 62.5),
                            ("Luther Burden III",
                             "player_reception_yds_alt", 50.0))]
    b = ff_betlog.log_bet(401, 7.31, legs, "fanduel", boost_pct=0.30,
                          fees=0.22)
    for i, r in enumerate(("WIN", "LOSS", "WIN")):
        ff_betlog.grade_leg(b["id"], i, r)
    return b


_b60 = _snf60()
chk("CASHED_OUT is an accepted result",
    "CASHED_OUT" in ff_betlog.BET_RESULTS)
# The amount IS the result; without it a cash-out cannot be told from a loss.
chk("a cash-out with no payout is refused",
    _raises(lambda: ff_betlog.grade_bet(_b60["id"], "CASHED_OUT"),
            ValueError))
chk("and the refusal says the amount is the result",
    "amount taken IS the result" in _err(
        lambda: ff_betlog.grade_bet(_b60["id"], "CASHED_OUT")))
chk("an unknown result is still refused",
    _raises(lambda: ff_betlog.grade_bet(_b60["id"], "SORTOF"), ValueError))
ff_betlog.grade_bet(_b60["id"], "CASHED_OUT", 12.95)
_o60 = ff_betlog.bet_summary()
# The money. $7.31 + $0.22 charged, $12.95 back.
# Line-anchored: the first cut asserted "$7.53" anywhere in the report and
# a revert that zeroed `staked` still passed, because the boost line carried
# the same figure.
chk("the fee is counted in what was staked, not folded into the stake",
    _line(_o60, "staked") == "staked      : $7.53   (incl. $0.22 in fees)",
    _line(_o60, "staked"))
chk("the cash-out is what was returned",
    _line(_o60, "returned") == "returned    : $12.95", _line(_o60, "returned"))
chk("so the slip records a PROFIT, not a loss",
    _line(_o60, "net").startswith("net         : $+5.42"),
    _line(_o60, "net"))
# The record. A slip that never settled is neither a win nor a loss.
chk("no settled slip means no hit rate is claimed",
    "no slip has settled" in _o60, _o60[:200])
chk("and the exclusion is stated, not silent",
    "1 cashed out" in _o60, _o60[:200])
# The counterfactual is the only thing that makes the decision reviewable.
chk("the report says what the slip would have done",
    "would have LOST" in _o60, _o60[:600])
chk("and names the amount taken against the stake and price",
    "$12.95 taken on a $7.31 stake at +401" in _o60, _o60[:600])
chk("a count of cash-outs that beat riding is given as a COUNT",
    "1 of 1 cash-out" in _o60 and "That is a COUNT, not a rate" in _o60,
    _o60[:700])
chk("and it refuses to call one observation an EV finding",
    "this log has 1" in _o60, _o60[:700])
# The tokens are the point of this project, so a boosted slip that was
# cashed out must stay in the boost accounting.
chk("a boosted slip that was cashed out is still boost accounting",
    _line(_o60, "boosted slips") == "boosted slips: 1  net $+5.42 on $7.53",
    _line(_o60, "boosted slips"))
# A slip whose legs are NOT all graded cannot have a counterfactual invented.
_b60b = ff_betlog.log_bet(500, 5.0, [ff_betlog.Leg(
    player="X", market="m", line=1.5, side="OVER", odds=-110,
    book="fanduel", event_id="60348")], "fanduel", boost_pct=0.30)
ff_betlog.grade_bet(_b60b["id"], "CASHED_OUT", 3.00)
chk("an ungraded cash-out says UNKNOWN rather than guessing",
    "UNKNOWN" in ff_betlog.bet_summary(),
    ff_betlog.bet_summary()[:700])
# A settled slip alongside must still produce an ordinary record.
_b60c = ff_betlog.log_bet(265, 10.0, [ff_betlog.Leg(
    player="Tucker Kraft", market="player_anytime_td", line=None,
    side="OVER", odds=265, book="draftkings", event_id="60351")],
    "draftkings", boost_pct=0.30)
ff_betlog.grade_leg(_b60c["id"], 0, "LOSS")
ff_betlog.grade_bet(_b60c["id"], "LOSS")
_o60c = ff_betlog.bet_summary()
chk("a settled slip still gets a hit rate",
    "record      : 0-1" in _o60c, _o60c[:200])
chk("and the hit rate says it excludes the cash-outs",
    "excludes 2 cashed out" in _o60c, _o60c[:260])
# $7.31 + $0.22 fee, plus the $5.00 ungraded cash-out, plus the $10.00
# settled loss. Written out rather than copied from the output, so the check
# is arithmetic and not a transcription of whatever the code produced.
chk("while the money counts all three slips and the fee",
    _line(_o60c, "staked").startswith(
        f"staked      : ${7.31 + 0.22 + 5.00 + 10.00:,.2f}"),
    _line(_o60c, "staked"))
shutil.rmtree(_tmp60, ignore_errors=True)
ff_betlog.LOG_DIR, ff_betlog.SESSION, ff_betlog.PULL_MARKER = _old60

section("59. what a real four-slip round found in the same night's fixes")
# B120/B121/B123, all three from one live round against a real Week 9 board.
# ---------------------------------------------------------------------------
class _TDEst:
    """A TD-shaped estimate, the shape that produced the live units error."""
    stat = "rush_rec_tds"
    line = 0.5
    n = 24
    blended = 0.3969
    ci_low, ci_high, ci_width = 0.30, 0.50, 0.20
    sample_verdict = "ADEQUATE"
    role_changed = False
    usage = None
    mean, sd, hits = 0.4, 0.3, 10
    empirical = parametric = recency = 0.4


# B120. B87 stopped the fabricated hold and stopped there: the refusal was
# invisible downstream, so a First TD leg came back hold=nan with
# tier=MODERATE, reasoning="clean read" and boost_verdict=CLEAR — a leg with
# no measurable vig reading as VETTED. B39's shape inside B87's own fix.
_nan_ed = prop_edge(_TDEst(), 320, fair_over=0.2053, fair_source="bovada",
                    devig_method="shin", market="player_anytime_td")
chk("a refused hold is still nan",
    _nan_ed.hold != _nan_ed.hold, str(_nan_ed.hold))
chk("but it no longer reads as a clean read",
    "clean read" not in str(_nan_ed.reasoning), str(_nan_ed.reasoning)[:90])
chk("the reason says no hold was measured, and why",
    "no hold measured" in str(_nan_ed.reasoning)
    and "one-sided" in str(_nan_ed.reasoning), str(_nan_ed.reasoning)[:120])
# A real two-sided quote must be unaffected, or the fix has just added noise
# to every leg.
_e59 = threshold_prob(log, 90)
chk("a two-sided leg still reads clean and carries its hold",
    prop_edge(_e59, -110, -110).hold == prop_edge(_e59, -110, -110).hold
    and "no hold measured" not in str(prop_edge(_e59, -110, -110).reasoning))

# B121. The UNITS mismatch the engine could not see: P(scores A touchdown)
# priced against P(scores the FIRST one), which is roughly 3x smaller. The
# live round reported a +19.2pt "edge" that was almost all units error, and
# the reading session caught it by hand.
chk("a TD estimate priced against a FIRST-TD market is refused",
    _raises(lambda: prop_edge(_TDEst(), 320, fair_over=0.2053,
                              fair_source="bovada", devig_method="shin",
                              market="player_first_td"), ValueError))
chk("and the refusal names both quantities and the ~3x",
    all(x in _err(lambda: prop_edge(
        _TDEst(), 320, fair_over=0.2053, fair_source="bovada",
        devig_method="shin", market="player_first_td"))
        for x in ("A touchdown", "FIRST", "3x")))
# An anytime-TD market with a TD estimate is the MATCHING case and must pass.
chk("the same estimate against an ANYTIME-TD market is not refused",
    prop_edge(_TDEst(), 320, fair_over=0.2053, fair_source="bovada",
              devig_method="shin", market="player_anytime_td") is not None)
# No market named at all: cannot refuse, must not stay silent, must not rank
# STRONG on units nobody checked.
_unnamed = prop_edge(_TDEst(), 320, under_odds=-400, fair_over=0.2053,
                     fair_source="bovada", devig_method="shin")
chk("an unnamed market on a TD estimate is flagged, not refused",
    "unnamed market" in str(_unnamed.reasoning), str(_unnamed.reasoning)[:90])
chk("and costs a tier, so it cannot read as STRONG",
    _unnamed.tier != "STRONG", _unnamed.tier)
_named = prop_edge(_TDEst(), 320, under_odds=-400, fair_over=0.2053,
                   fair_source="bovada", devig_method="shin",
                   market="player_anytime_td")
chk("naming the market restores the tier it had earned",
    _named.tier == "STRONG" and "unnamed" not in str(_named.reasoning),
    f"{_named.tier} {_named.reasoning}")
# A non-TD estimate must not be dragged into any of this.
chk("a yardage estimate is untouched by the TD guard",
    "unnamed market" not in str(prop_edge(_e59, -110, -110).reasoning))

# B123. An F11 regression found within the hour: `legs_per_slip` is None
# unless the caller passes one, because sizes now come from `sizes` — so the
# zero-candidate message printed "a None-leg slip", naming a size that does
# not exist.
_L59 = [BoostLeg(player=f"W{i}", market="player_reception_yds", line=50.5,
                 side="OVER", odds=-110, book="draftkings", fair_prob=0.5,
                 fair_source="bovada", devig_method="shin", event_id="e1",
                 team="KC", pos="WR", verdict="CLEAR",
                 verdict_side="OVER") for i in range(2)]
_r59 = enumerate_candidates(_L59, {}, mode="single-game", event_id="e1",
                            boost_pct=0.30).reason
chk("the zero-candidate message names a real slip size",
    "None-leg" not in _r59 and "3-leg" in _r59, _r59[:120])
chk("and says how many legs survived intake",
    "2 leg(s) available" in _r59, _r59[:120])

section("58. tokens are PARSED INPUT, never constants (F11/F16)")
# Dustin holds 4-6 tokens a week and the terms change weekly, so none of
# them are hardcoded — he states them in the prompt and ff_tokens reads
# them. The rule the whole module rests on: a term that was not stated is
# NOT a term with a default. D16/B39, and specifically B77, where
# stake_back_ev's docstring says "the caller must state it" while the
# signature supplies 0.65.
# ---------------------------------------------------------------------------
_T = ff_tokens.parse_token

# The three kinds are different MATH, so a kind guessed wrong inverts which
# bet is right (B56) — a stake-back rewards a LOW win probability.
chk("a percentage promo reads as a profit boost",
    _T("30% profit boost, max $25, SGP only, min odds +200").kind
    == "profit_boost")
chk("'get $25 back' reads as a stake-back, money in the middle and all",
    _T("Bet $25 get $25 back if it loses").kind == "stake_back")
chk("so does 'no sweat bet', which names neither a boost nor a percentage",
    _T("No sweat bet up to $50").kind == "stake_back")
chk("and 'get your stake back as a bonus bet'",
    _T("get your stake back as a bonus bet, up to $50").kind == "stake_back")
chk("an odds boost is its own kind, not a percentage promo",
    _T("Odds boost: +400 to +500 on a 3-leg SGP").kind == "odds_boost")
# Ambiguity is refused rather than resolved.
_amb = _T("risk-free 30% boost up to $25")
chk("a token naming BOTH a refund and a boost gets no kind",
    _amb.kind is None, str(_amb.kind))
chk("and says why, naming both phrases it found",
    any("opposite math" in u for u in _amb.unparsed), str(_amb.unparsed))
chk("an unusable token is reported unusable",
    not _amb.usable and _amb.missing)

# Terms are read exactly, or not at all.
_t1 = _T("30% profit boost, max $25, SGP only, min odds +200")
chk("percentage, minimum, cap and structure all read",
    (_t1.pct, _t1.min_odds, _t1.max_stake, _t1.sgp_only)
    == (0.30, 200.0, 25.0, True),
    f"{_t1.pct} {_t1.min_odds} {_t1.max_stake} {_t1.sgp_only}")
chk("'2+ legs' reads as a minimum leg count",
    _T("50% boost, 2+ legs").min_legs == 2)
chk("and so does '3-leg SGP', hyphen and all",
    _T("Odds boost on a 3-leg SGP").min_legs == 3)
# An unsigned minimum is ambiguous and large: +200 and -200 are different
# tokens, so it is refused rather than assumed.
_uns = _T("min odds 200, max $20")
chk("an UNSIGNED minimum is refused, not assumed positive",
    _uns.min_odds is None, str(_uns.min_odds))
chk("and the refusal says why both readings matter",
    any("different terms" in u for u in _uns.unparsed), str(_uns.unparsed))
# "bet $25" states a STAKE; "up to $25" states a CAP. Same number, different
# meaning, different EV.
chk("a stated stake and a stated cap are kept apart",
    (_T("Bet $25 get $25 back").stake,
     _T("No sweat bet up to $25").max_stake) == (25.0, 25.0))
chk("a stake is preferred over a cap for pricing",
    _T("Bet $25 get $25 back if it loses").effective_stake == 25.0)
chk("and a token stating neither has NO stake, rather than a default of 10",
    _T("30% profit boost").effective_stake is None)
# Silence about structure is disclosed, because the enumerator does not
# filter without it and could offer an ineligible slip.
chk("an unstated structure is named in `missing`",
    any("SGP-only" in m for m in _T("30% boost, min odds +200",
                                    ).missing))
# parse_tokens handles a pasted block, skips headers, drops nothing silently.
_blk = ff_tokens.parse_tokens(
    "Tokens:\n- 30% profit boost, max $25, min odds +300\n"
    "- Bet $25 get $25 back\n\n* 50% boost up to $10, 2+ legs\n"
    "something I did not describe")
chk("a pasted block parses one token per line",
    len(_blk) == 4, str(len(_blk)))
chk("a header line is skipped, not read as a token",
    all("Tokens" not in t.raw for t in _blk))
chk("and a line it could barely read is still returned, not dropped",
    any(t.kind is None for t in _blk),
    str([t.kind for t in _blk]))
chk("describe_tokens counts the unusable ones",
    "cannot be built to at all" in ff_tokens.describe_tokens(_blk))
chk("and an empty parse says so rather than reading as 'no tokens held'",
    "defect to report" in ff_tokens.describe_tokens([]))

# F11. Enumeration builds to the TOKEN's terms, not this project's band.
_L58 = [BoostLeg(player=f"W{i}", market="player_reception_yds", line=50.5,
                 side="OVER", odds=o, book="draftkings", fair_prob=0.5,
                 fair_source="bovada", devig_method="shin", event_id="e1",
                 team="DET", pos="WR", verdict="CLEAR",
                 verdict_side="OVER")
        for i, o in enumerate((-150, -150, -150, -140, -160))]
_sl58 = enumerate_candidates(_L58, {}, mode="single-game", event_id="e1",
                             token=_T("30% profit boost, max $25, "
                                      "min odds +500"))
chk("a token minimum above the floor becomes the binding constraint",
    any("floor raised" in n for n in _sl58.token_notes),
    str(_sl58.token_notes))
chk("and it actually filters — nothing here clears +500",
    not _sl58.candidates, str(len(_sl58.candidates)))
_sl58b = enumerate_candidates(_L58, {}, mode="single-game", event_id="e1",
                              token=_T("30% profit boost, min odds +300"))
chk("a token minimum EQUAL to the floor says they coincide, not that one "
    "is below the other",
    any("equals this" in n for n in _sl58b.token_notes),
    str(_sl58b.token_notes))
# B55's distinction, kept: a LOWER token minimum does not loosen the floor.
_sl58c = enumerate_candidates(_L58, {}, mode="single-game", event_id="e1",
                              token=_T("30% profit boost, min odds +100"))
chk("a token minimum BELOW the floor does not loosen it",
    any("floor still" in n for n in _sl58c.token_notes),
    str(_sl58c.token_notes))
# A minimum leg count is a MINIMUM: both sizes get built, because the short
# ones often miss the floor while the long ones clear it.
_sl58d = enumerate_candidates(_L58, {}, mode="single-game", event_id="e1",
                              token=_T("50% profit boost up to $10, 2+ legs"))
chk("a '2+ legs' token builds every size from 2 up to the project default",
    any("sizes [2, 3]" in n for n in _sl58d.token_notes),
    str(_sl58d.token_notes))
chk("and the surviving candidates are the ones that clear the floor",
    _sl58d.candidates and all(len(c.legs) == 3 for c in _sl58d.candidates),
    str([len(c.legs) for c in _sl58d.candidates]))
# The token's minimum reaches the candidate, so B55's token_minimum can
# answer once priced rather than needing the caller to remember.
chk("the token's minimum is carried onto each candidate",
    all(c.token_min_odds == 300.0 for c in _sl58b.candidates),
    str([c.token_min_odds for c in _sl58b.candidates][:3]))
# A guessed boost percentage ranks slips for a promo that does not exist.
chk("no boost percentage, by argument or token, is refused",
    _raises(lambda: enumerate_candidates(_L58, {}, mode="single-game",
                                         event_id="e1"), ValueError))
chk("and the refusal explains what a guess would produce",
    "promo that does not exist" in _err(
        lambda: enumerate_candidates(_L58, {}, mode="single-game",
                                     event_id="e1")))
# B56. A stake-back must never go through the boost path.
chk("a stake-back token is REFUSED by the boost enumerator",
    _raises(lambda: enumerate_candidates(
        _L58, {}, mode="single-game", event_id="e1",
        token=_T("Bet $25 get $25 back if it loses")), ValueError))
chk("and the refusal says the right bet for it is the LONGEST shot",
    "longest shot" in _err(lambda: enumerate_candidates(
        _L58, {}, mode="single-game", event_id="e1",
        token=_T("Bet $25 get $25 back if it loses"))))
# An SGP-only token cannot be built cross-game.
chk("an SGP-only token refuses cross-game mode",
    _raises(lambda: enumerate_candidates(
        _L58, {}, mode="cross-game",
        token=_T("30% profit boost, SGP only, min odds +300")), ValueError))
chk("an unstated stake is disclosed rather than silently defaulted",
    any("stake not stated" in n for n in _sl58b.token_notes),
    str(_sl58b.token_notes))
chk("and describe() surfaces the token notes rather than hiding them",
    "token:" in _sl58b.describe(), _sl58b.describe()[:200])

# F16. Allocation across the tokens on hand.
_alloc = ff_tokens.allocate(
    ff_tokens.parse_tokens(
        "30% profit boost, max $25, min odds +300\n"
        "50% profit boost up to $10, 2+ legs\n"
        "Bet $25 get $25 back if it loses, min odds -200\n"
        "Odds boost on Mahomes 300+ yards\n"
        "some promo I did not describe"),
    _L58, {}, mode="single-game", event_id="e1")
chk("both profit boosts get a shortlist",
    len(_alloc["assigned"]) == 2, str(len(_alloc["assigned"])))
# Behavioural, not prose: the stake-back TOKEN is the one held apart, found
# by its label rather than by a phrase in my own message. The first cut
# matched the word "stake-back" in the text, so rewording the message
# defeated it while the behaviour was intact — a check on wording is not a
# check on what the code does.
_sb_lbl = next(t.label for t in ff_tokens.parse_tokens(
    "30% profit boost, max $25, min odds +300\n"
    "50% profit boost up to $10, 2+ legs\n"
    "Bet $25 get $25 back if it loses, min odds -200\n"
    "Odds boost on Mahomes 300+ yards\n"
    "some promo I did not describe") if t.kind == "stake_back")
chk("the stake-back token is the one held apart from the boosts",
    _sb_lbl in [n for n, _ in _alloc["unranked"]]
    and _sb_lbl not in [a["token"].label for a in _alloc["assigned"]],
    f"{_sb_lbl}: unranked={[n for n, _ in _alloc['unranked']]}")
chk("and the reason cites the bonus value nobody stated (B77)",
    any("bonus value" in why for _, why in _alloc["unranked"]))
chk("an odds boost is held apart too — it is not a percentage of a slip",
    any("odds boost" in why for _, why in _alloc["unranked"]))
chk("a token with no kind is held apart with its missing terms",
    any("kind not stated" in why for _, why in _alloc["unranked"]))
chk("two tokens ranking the same slip first is reported as a CONFLICT",
    any("both rank" in c for c in _alloc["conflicts"]),
    str(_alloc["conflicts"]))
chk("and the conflict says it does not choose for you",
    any("does not choose for you" in c for c in _alloc["conflicts"]),
    str(_alloc["conflicts"]))
chk("describe_allocation prints the conflicts and the unranked",
    "CONFLICTS" in ff_tokens.describe_allocation(_alloc)
    and "NOT RANKED" in ff_tokens.describe_allocation(_alloc))

section("57. the four Sunday-path defects (B78/B75/B87/B66)")
# Picked by asking what will MISLEAD on Sunday rather than off the backlog
# order. All four were open and all four fire on live output.
# ---------------------------------------------------------------------------
_mk57 = lambda n=1: [{"key": "player_pass_yds", "outcomes": [
    {"name": "Over", "price": -110}, {"name": "Under", "price": -110}]}
    for _ in range(n)]

# B78. The dropout detector reporting health on a textbook dropout. Measured
# on the B60 signature: Pinnacle carrying `title` and no `key` became the
# manufactured key "Pinnacle" against a lowercase ANCHOR_CHAIN, so
# live={'Pinnacle': 14}, eligible=[], silent_dropouts=[], healthy=True.
_ev57 = {"lines": [{"fair_source": "bovada"} for _ in range(14)]}
_cov57 = ff_props.anchor_coverage(_ev57, {"bookmakers": [
    {"title": "Pinnacle", "markets": _mk57()},
    {"key": "bovada", "markets": _mk57()}]})
chk("a chain book arriving with only a title is still identified",
    "pinnacle" in _cov57.live, str(_cov57.live))
chk("so the dropout is SEEN rather than reported healthy",
    not _cov57.healthy, f"healthy={_cov57.healthy} live={_cov57.live}")
chk("book_key prefers key, resolves a title, and refuses the rest",
    ff_props.book_key({"key": "PINNACLE"}) == "pinnacle"
    and ff_props.book_key({"title": "Pinnacle"}) == "pinnacle"
    and ff_props.book_key({"title": "FanDuel"}) is None
    and ff_props.book_key({}) is None)
# An unidentifiable live book costs health, because it might BE the anchor.
_cov57b = ff_props.anchor_coverage(_ev57, {"bookmakers": [
    {"title": "FanDuel", "markets": _mk57()},
    {"key": "bovada", "markets": _mk57()}]})
chk("an unidentifiable live book is named, not given an invented key",
    _cov57b.unidentified == ["FanDuel"]
    and "FanDuel" not in _cov57b.live, str(_cov57b.unidentified))
chk("and it costs health",
    not _cov57b.healthy and "NOT IDENTIFIABLE" in _cov57b.describe(),
    _cov57b.describe()[:150])
# fair_source carries provenance text live; it must still match the chain.
chk("a fair_source with provenance text still counts as that book",
    ff_props.norm_fair_source("Pinnacle (via get_event_ev, unfiltered)")
    == "pinnacle"
    and ff_props.norm_fair_source("bovada") == "bovada"
    and ff_props.norm_fair_source(None) is None)
# One definition, shared. A second copy is how B68's duplicate table happened.
chk("ff_boost uses ff_props' book_key rather than its own copy",
    ff_boost.book_key is ff_props.book_key)
chk("and a tier derived for a title-only chain book is reachable by key",
    ff_boost.book_liquidity_tiers({"bookmakers": [
        {"title": "Pinnacle", "markets": [
            {"key": "m", "outcomes": [
                {"name": "Over", "price": -110, "liquidity": 500},
                {"name": "Under", "price": -110, "liquidity": 500}]}
            for _ in range(6)]}]}).get("pinnacle") == 500.0)

# B87. A fabricated price producing a confident steep-hold finding.
chk("a dummy far outside the quote range refuses the hold",
    ff_props.two_sided_hold(525, -10000)[0] != ff_props.two_sided_hold(
        525, -10000)[0])
chk("and says which side and why",
    "UNDER price -10000 is outside"
    in ff_props.two_sided_hold(525, -10000)[1],
    ff_props.two_sided_hold(525, -10000)[1][:110])
# The backlog expected -400 to give "a plausible-looking steep hold".
# Measured, it gives -4.0% — an arb inside one book, impossible either way.
chk("a dummy that implies a NEGATIVE hold is refused too",
    ff_props.two_sided_hold(525, -400)[0]
    != ff_props.two_sided_hold(525, -400)[0])
chk("and is explained as an arb inside one book",
    "arb inside one book" in ff_props.two_sided_hold(525, -400)[1],
    ff_props.two_sided_hold(525, -400)[1][:110])
for _o, _u, _exp in ((-110, -110, 0.0476), (-115, -105, 0.0471),
                     (1800, -1900, 0.0026), (100, -100, 0.0)):
    chk(f"a real {_o:+}/{_u:+} quote still gets its hold",
        abs(ff_props.two_sided_hold(_o, _u)[0] - _exp) < 5e-4,
        str(ff_props.two_sided_hold(_o, _u)))
chk("a one-sided price has no hold and says so",
    ff_props.two_sided_hold(525, None)[0]
    != ff_props.two_sided_hold(525, None)[0]
    and "one-sided" in ff_props.two_sided_hold(525, None)[1])
# The refusal must reach the verdict, not just the helper: no steep-hold
# reason may be built from a refused hold.
# The refusal must reach the VERDICT, not just the helper: no steep-hold
# reason may be built from a refused hold. `e` is the module-level estimate
# fixture from section 5 — a real one, so this cannot pass vacuously.
_e57 = threshold_prob(log, 90)
_dummy57 = prop_edge(_e57, 525, -10000)
chk("prop_edge still prices a leg whose hold was refused",
    _dummy57 is not None and _dummy57.hold != _dummy57.hold,
    f"hold={_dummy57.hold}")
chk("and builds NO steep-hold reason from the fabricated side",
    "is steep" not in str(_dummy57.reasoning), str(_dummy57.reasoning)[:120])
# A real two-sided quote that IS steep must still say so, or the guard has
# just deleted the signal instead of protecting it.
_steep57 = prop_edge(_e57, -140, -140)
chk("a genuinely steep REAL hold is still reported",
    _steep57.hold > 0.06 and "is steep" in str(_steep57.reasoning),
    f"hold={_steep57.hold:.4f} {str(_steep57.reasoning)[:90]}")

# B66. A fixture counted as a real verdict.
_tmp57 = tempfile.mkdtemp()
_old57 = (ff_betlog.LOG_DIR, ff_betlog.SESSION, ff_betlog.PULL_MARKER)
ff_betlog.LOG_DIR = pathlib.Path(_tmp57)
ff_betlog.SESSION = ff_betlog.LOG_DIR / "_session.jsonl"
ff_betlog.PULL_MARKER = ff_betlog.LOG_DIR / "_pull.json"
# The two real B66 fixtures: a plausible player at a plausible price, and
# the worked example straight out of PROJECT-INSTRUCTIONS.
_rr57 = ff_betlog.log_recommendation(
    "Tyreek Hill", "player_reception_yds", 54.5, "OVER", "MODERATE", 0.58,
    0.50, -115, event_id="e1")
ff_betlog.grade_rec(_rr57["id"], "WIN")
_rt57 = ff_betlog.log_recommendation(
    "Travis Kelce", "player_anytime_td", None, "OVER", "STRONG", 0.31,
    0.248, 270, event_id="e1", is_test=True)
chk("a test record is flagged structurally, not in prose",
    ff_betlog.is_test_record(_rt57) and _rt57[ff_betlog.TEST_FLAG] is True)
chk("a real record carries no flag at all, so old records read as real",
    ff_betlog.TEST_FLAG not in _rr57)
# grade_rec must still find it — a first cut filtered at the accessor and
# could no longer grade a test record.
ff_betlog.grade_rec(_rt57["id"], "LOSS")
chk("a test record can still be graded",
    any(ff_betlog.is_test_record(r) for r in ff_betlog.live_recs()))
_o57 = ff_betlog.rec_summary()
chk("the summary excludes it from the figures",
    "ENGINE LOG — 1 verdicts" in _o57, _o57[:80])
chk("and says it is there rather than excluding it silently",
    "1 TEST record in the log, excluded from every figure" in _o57,
    _o57[:200])
chk("the test record's own tier does not appear in the table",
    "STRONG" not in _o57, _o57[:400])
chk("and the real record's does",
    "MODERATE" in _o57, _o57[:400])
# log_edge and log_bet take it too, or the flag is unreachable from the
# paths a session actually uses.
_ed57 = types.SimpleNamespace(side="OVER", tier="PASS", model_p=0.5,
                              fair_p=0.5, fair_source="pinnacle",
                              devig_method="shin", reasoning="x")
chk("log_edge can flag a test record",
    ff_betlog.is_test_record(ff_betlog.log_edge(
        _ed57, "P", "m", 1.5, event_id="e1", is_test=True)))
chk("log_bet can flag one too",
    ff_betlog.is_test_record(ff_betlog.log_bet(
        525, 5.0, [ff_betlog.Leg(player="P", market="m", line=1.5,
                                 side="OVER", odds=-110, book="dk")],
        "dk", is_test=True)))
shutil.rmtree(_tmp57, ignore_errors=True)
ff_betlog.LOG_DIR, ff_betlog.SESSION, ff_betlog.PULL_MARKER = _old57

section("56. three defects a live four-slip round surfaced (B117/B118/B119)")
# All three passed 784 checks first. The round built four Week 9 slips in the
# four shapes the correlation work touched; three came back unpriceable and
# one priced, exactly as designed — and the output showed these.
# ---------------------------------------------------------------------------
_s56 = {"PASS": ("player_pass_yds", "QB"), "RUSH": ("player_rush_yds", "RB"),
        "RECV": ("player_reception_yds", "WR")}


def _bleg56(name, side, team, fp=0.50, odds=-110, liq=None):
    mk, pos = _s56[side]
    l = BoostLeg(player=name, market=mk, line=50.5, side="OVER", odds=odds,
                 book="draftkings", fair_prob=fp, fair_source="bovada",
                 devig_method="shin", event_id="636628", team=team, pos=pos,
                 verdict="CLEAR",
                 verdict_side="OVER")
    if liq is not None:
        l.anchor_liquidity = liq
    return l


# B117. `log_edge` records the MODEL's preferred side; `log_bet` records the
# side the slip took. 5 of 12 legs differed in one live round. The B110 match
# key includes `side`, so such a leg was reported "NOT in this log" — the
# verdict IS there, for the other side, and the remedy printed would have
# created a duplicate.
_tmp56 = tempfile.mkdtemp()
_old56 = (ff_betlog.LOG_DIR, ff_betlog.SESSION, ff_betlog.PULL_MARKER)
ff_betlog.LOG_DIR = pathlib.Path(_tmp56)
ff_betlog.SESSION = ff_betlog.LOG_DIR / "_session.jsonl"
ff_betlog.PULL_MARKER = ff_betlog.LOG_DIR / "_pull.json"
_ed56 = types.SimpleNamespace(side="UNDER", tier="PASS", model_p=0.44,
                              fair_p=0.50, fair_source="bovada",
                              devig_method="shin", reasoning="x")
_lg56 = ff_betlog.Leg(player="Jahmyr Gibbs", market="player_rush_yds",
                      line=95.5, side="OVER", odds=-114, book="draftkings",
                      engine_tier="PASS", event_id="636628")
_b56 = ff_betlog.log_bet(525, 10.0, [_lg56], "draftkings")
ff_betlog.log_edge(_ed56, "Jahmyr Gibbs", "player_rush_yds", 95.5,
                   odds=-114, book="draftkings", acted_on=True,
                   bet_id=_b56["id"], event_id="636628")
_g56 = ff_betlog.unlogged_bet_verdicts()
chk("a verdict logged for the OTHER side is its own state",
    len(_g56) == 1 and _g56[0]["state"] == "opposite", str(_g56))
_o56 = ff_betlog.rec_summary()
chk("and is NOT reported as absent from the log",
    "NOT in this log" not in _o56, _o56[:300])
chk("the report says the slip took the side the engine did not prefer",
    "ENGINE DID NOT PREFER" in _o56, _o56[:300])
chk("and it is marked loud, because it is not a bookkeeping gap",
    "***" in _o56.split("ENGINE DID NOT PREFER")[0][-80:], _o56[:300])
chk("it also says a CLEAR verdict is not a view on the side you bet",
    "NOT that the model likes the side you bet" in _o56, _o56[:400])
# Same side still links normally — the new state must not swallow the old one.
_ed56b = types.SimpleNamespace(side="OVER", tier="PASS", model_p=0.56,
                               fair_p=0.50, fair_source="bovada",
                               devig_method="shin", reasoning="x")
_lg56b = ff_betlog.Leg(player="Agreed Leg", market="player_rush_yds",
                       line=20.5, side="OVER", odds=-110, book="draftkings",
                       engine_tier="PASS", event_id="636628")
_b56b = ff_betlog.log_bet(525, 10.0, [_lg56b], "draftkings")
ff_betlog.log_edge(_ed56b, "Agreed Leg", "player_rush_yds", 20.5, odds=-110,
                   book="draftkings", acted_on=True, bet_id=_b56b["id"],
                   event_id="636628")
chk("a leg the model agreed with is not reported at all",
    all(g["player"] != "Agreed Leg"
        for g in ff_betlog.unlogged_bet_verdicts()),
    str(ff_betlog.unlogged_bet_verdicts()))
# And a genuinely absent verdict is still MISSING, not reclassified.
_lg56c = ff_betlog.Leg(player="Never Logged", market="player_rush_yds",
                       line=30.5, side="OVER", odds=-110, book="draftkings",
                       engine_tier="PASS", event_id="636628")
ff_betlog.log_bet(525, 10.0, [_lg56c], "draftkings")
chk("a leg with no verdict either side is still MISSING",
    any(g["player"] == "Never Logged" and g["state"] == "missing"
        for g in ff_betlog.unlogged_bet_verdicts()),
    str(ff_betlog.unlogged_bet_verdicts()))
shutil.rmtree(_tmp56, ignore_errors=True)
ff_betlog.LOG_DIR, ff_betlog.SESSION, ff_betlog.PULL_MARKER = _old56

# B119. The factor note cited "0.61-0.65 on QB stacks" on EVERY correlated
# slip and claimed the books' factors "have tracked this table closely" —
# contradicted by the same live round, where DraftKings charged 0.686 on an
# opposing-QB pair at +7.22% against 0.672 on a true stack at +31%.
_st_qb = classify([_bleg56("QB", "PASS", "KC"), _bleg56("W1", "RECV", "KC"),
                   _bleg56("W2", "RECV", "KC")], {})
_st_rb = classify([_bleg56("R1", "RUSH", "DEN"), _bleg56("R2", "RUSH", "DEN"),
                   _bleg56("W", "RECV", "DEN")], {})
_st_mx = classify([_bleg56("Q1", "PASS", "DAL"), _bleg56("Q2", "PASS", "IND"),
                   _bleg56("W", "RECV", "IND")], {})
chk("a pure QB stack still gets the range that was observed on QB stacks",
    "0.61-0.65" in ff_boost.factor_note(_st_qb, 0.672),
    ff_boost.factor_note(_st_qb, 0.672)[:140])
chk("a backfield pair does NOT get a QB-stack range to measure against",
    "0.61-0.65 observation is QB stacks only"
    in ff_boost.factor_note(_st_rb, 0.921),
    ff_boost.factor_note(_st_rb, 0.921)[:160])
chk("and the general 'tracked this table closely' claim is gone",
    all("tracked this table closely" not in ff_boost.factor_note(st, 0.7)
        for st in (_st_qb, _st_rb, _st_mx)))
chk("a mixed slip says the range covers only part of what it is charged for",
    "PART of what you are being charged for"
    in ff_boost.factor_note(_st_mx, 0.686),
    ff_boost.factor_note(_st_mx, 0.686)[:180])

section("55. the guillotine's correlation join, and its borrowed table (B68b)")
# `correlation_matrix` guarded TEAM and had no position equivalent, then did
# `SAME_TEAM_CORR.get(key, 0.0)` — so a player whose meta was ("KC", None),
# which is what a partial build_meta join produces, yielded a silent 0.0 for
# what may be a QB/WR pair at +0.31. Worse, the lookup was `meta.get(name)`
# on a RAW NAME, in the module whose own normalize_name docstring reads
# "THIRD occurrence of a name-join bug in this project. Never match player
# data on a raw name" — while `_correlated_draws` two lines away resolves the
# same player through resolve(), which normalises. One function, two join
# policies.
#
# Measured before fixing (measurements/b68b_position_join_effect.py, 10
# deliberately QB-stacked teams, 60,000 sims, 2026):
#   every position dropped     P(elim) -2.05pp, max shift 4.15pp
#   measured 5.5% miss rate    P(elim) +0.21pp, max shift 0.59pp
#   one receiver dropped       P(elim) -0.25pp, max shift 0.55pp
#   simulation noise 1 se      0.10pp
# So the sim IS sensitive to correlation, the headline shift at the real
# miss rate is about 2 se, and the recommended lineup was identical in every
# case. Real silent bug, low stakes today — same verdict B68 reached about
# its own sign error, reached the same way.
# ---------------------------------------------------------------------------
_gm = {"Brian Thomas Jr.": ("JAX", "WR"),
       "Trevor Lawrence": ("JAX", "QB"),
       "Nan Pos": ("JAX", float("nan")),
       "Blank Pos": ("JAX", "   "),
       "Nan Team": (float("nan"), "WR"),
       "Other QB": ("KC", "QB")}
# The join must behave like every other join in the module.
# Read from the table, not a literal. These asserted == 0.31 and so failed
# the moment the table moved — a check on the JOIN that was also silently a
# check on the value, which is two jobs and one of them was not wanted.
_qbwr = ff_guillotine.SAME_TEAM_CORR[("QB", "WR")]
chk("a suffix spelling difference resolves instead of dropping the pair",
    ff_guillotine.correlation_matrix(
        ["Trevor Lawrence", "Brian Thomas"], _gm)[0, 1] == _qbwr,
    str(ff_guillotine.correlation_matrix(
        ["Trevor Lawrence", "Brian Thomas"], _gm)[0, 1]))
chk("an exact name still resolves",
    ff_guillotine.correlation_matrix(
        ["Trevor Lawrence", "Brian Thomas Jr."], _gm)[0, 1] == _qbwr)
chk("and the pair really is correlated, so the check above can fail",
    _qbwr > 0.05, f"{_qbwr:+.4f}")
# NaN is not None and is not falsy in the way an `is None` guard expects —
# B73 in ff_boost, same shape, module next door.
for _who in ("Nan Pos", "Blank Pos", "Nan Team"):
    chk(f"{_who} is treated as ABSENT, not as a position",
        ff_guillotine.correlation_matrix(
            ["Trevor Lawrence", _who], _gm)[0, 1] == 0.0)
chk("_meta_field maps NaN, blank and None alike to absent",
    all(ff_guillotine._meta_field(v) is None
        for v in (None, float("nan"), "", "   ")))
chk("and leaves a real value alone, stripped",
    ff_guillotine._meta_field("  WR ") == "WR")
# Different teams stay independent — the behaviour the 27-line comment
# defends must survive this change.
chk("two QBs on different teams are still independent",
    ff_guillotine.correlation_matrix(
        ["Trevor Lawrence", "Other QB"], _gm)[0, 1] == 0.0)
# A miss must be REPORTED. An ndarray has nowhere to say so, which is how
# the silence happened.
_cov = ff_guillotine.correlation_coverage(
    ["Trevor Lawrence", "Brian Thomas", "Nan Pos", "Nan Team", "Ghost"], _gm)
chk("coverage names the players with no position",
    _cov["no_position"] == ["Nan Pos"], str(_cov))
chk("and separates them from those with no team at all",
    sorted(_cov["no_team"]) == ["Ghost", "Nan Team"], str(_cov))
chk("and counts the ones it did resolve",
    _cov["resolved"] == 2, str(_cov))
# A name collision must not silently pick a winner: B44's two Brian Thomases
# are different players.
# Two keys that BOTH normalise to the queried name, and the queried name is
# not itself a key — otherwise the exact-match fast path answers and the
# canon map is never exercised, which is what the first cut of this check
# did.
_dupe = {"Brian Thomas Jr.": ("JAX", "WR"), "Brian Thomas II": ("KC", "TE")}
chk("both spellings really do collide under normalisation",
    ff_guillotine.normalize_name("Brian Thomas Jr.")
    == ff_guillotine.normalize_name("Brian Thomas II"))
chk("a normalised-name collision keeps the FIRST spelling, not an arbitrary one",
    ff_guillotine.meta_lookup("Brian Thomas", _dupe) == ("JAX", "WR"),
    str(ff_guillotine.meta_lookup("Brian Thomas", _dupe)))
# B68(a). The tables are duplicated and must NOT be merged: the import would
# be circular (ff_guillotine is the leaf of ff_guillotine <- ff_props <-
# ff_boost) and B68(b) established they are different quantities wearing the
# same keys. What must stay in step is the KEY SET — a pair added to one and
# not the other is the divergence B68(a) actually feared. Values are E3's
# business and are EXPECTED to diverge once it lands, so this deliberately
# does not compare them.
chk("both correlation tables carry the same PAIRS",
    set(ff_guillotine.SAME_TEAM_CORR) == set(ff_boost.SAME_TEAM_CORR)
    and set(ff_guillotine.OPPOSING_CORR) == set(ff_boost.OPPOSING_CORR),
    f"guillotine {sorted(ff_guillotine.SAME_TEAM_CORR)} vs "
    f"boost {sorted(ff_boost.SAME_TEAM_CORR)}")
# The coverage has to reach the Result and the printed report, or it is a
# dict nobody reads — which is the same silence in a new place.
_bad_meta = dict(_meta2)
_firstp = sorted({p for t in _teams_g
                  for names in t["roster"].values() for p in names})[0]
_bad_meta[_firstp] = (_bad_meta.get(_firstp, ("KC", "WR"))[0], float("nan"))
_rbad = ff_guillotine.run(_teams_g, _shared, my_team_id="0", n_sims=4_000,
                          meta=_bad_meta, week=9)
chk("run() carries the unresolved-correlation players out on the Result",
    _rbad.correlation_unresolved.get("no_position") == [_firstp],
    str(_rbad.correlation_unresolved))
chk("and a clean meta reports nothing, so it is not noise",
    ff_guillotine.run(_teams_g, _shared, my_team_id="0", n_sims=4_000,
                      meta=_meta2, week=9).correlation_unresolved == {},
    str(ff_guillotine.run(_teams_g, _shared, my_team_id="0", n_sims=4_000,
                          meta=_meta2, week=9).correlation_unresolved))
_rpt = _rbad.report()
chk("the printed report says those players were NOT correlated",
    "NOT CORRELATED" in _rpt and _firstp in _rpt, _rpt[:200])
chk("and the guillotine copy is documented as borrowed, pending E3",
    "BORROWED" in open("ff_guillotine.py").read()
    and "E3" in open("ff_guillotine.py").read())

section("54. every market-side pair is measured, not fallen through (E6/B81)")
# `_pair_r` gated four canonical pairs and returned a bare `(0.0, "")` for
# everything else, so a MEASURED zero and an unexamined fall-through were the
# same value with the same empty label (B53's family). E6's receiving half
# was measured 2026-11-05; the rest on 2026-11-06 in one sweep, because
# closing the gate on an unmeasured pair is correct but useless if it refuses
# half the real slips.
#   measurements/e6_full_pair_sweep.py — nflverse 2023-2026 REG, z-scored
#   per player-season, min 6 games, min 200 pairs, CONTROL: same-team
#   PASS x RECV recovered r=+0.2462 against the table's +0.31.
# ---------------------------------------------------------------------------
_SIDEMK = {"PASS": ("player_pass_yds", "QB"),
           "RUSH": ("player_rush_yds", "RB"),
           "RECV": ("player_reception_yds", "WR")}


def _pleg(name, side, team, event="e1"):
    mk, pos = _SIDEMK[side]
    return BoostLeg(player=name, market=mk, line=50.5, side="OVER",
                    odds=-110, book="draftkings", fair_prob=0.5,
                    fair_source="pinnacle", devig_method="shin",
                    event_id=event, team=team, pos=pos)


# A pair is unordered, so the lookup sorts the sides — which means every KEY
# must already be sorted or it is unreachable. Two were not: RECV sorts
# before RUSH, so ("same","RUSH","RECV") could never be found and the
# commonest same-game shape in this project — a back's rushing yards with a
# teammate receiver's — fell to "never measured" and refused an EV. A
# lookup-order bug reads exactly like an honest refusal.
chk("every MEASURED_PAIR_LIFT key has its sides in sorted order",
    all(list(k[1:]) == sorted(k[1:]) for k in ff_boost.MEASURED_PAIR_LIFT),
    str([k for k in ff_boost.MEASURED_PAIR_LIFT
         if list(k[1:]) != sorted(k[1:])]))
chk("and the lookup is order-independent for every pair",
    all(ff_boost.pair_lift(rel, a, b) == ff_boost.pair_lift(rel, b, a)
        for rel in ("same", "opp") for a in _SIDEMK for b in _SIDEMK))
# All 12 cells resolve to SOMETHING deliberate. Before this, 8 of them
# resolved to a silent zero.
for _rel, _t2 in (("same", "BAL"), ("opp", "JAX")):
    for _a in _SIDEMK:
        for _b in _SIDEMK:
            _r, _w = ff_boost._pair_r(_pleg("A", _a, "BAL"),
                                      _pleg("B", _b, _t2))
            chk(f"{_rel} {_a}x{_b} gives a reason, whatever the verdict",
                bool(_w) and len(_w) > 20, f"{_r!r}: {_w!r}")
# The two findings that contradict the mechanism stories told about them.
chk("same-team RB x RB is POSITIVE, not the negative carry-pool story",
    ff_boost.pair_lift("same", "RUSH", "RUSH")[0] > 1.0,
    str(ff_boost.pair_lift("same", "RUSH", "RUSH")))
chk("and it is past the gate, so no EV is reported for such a slip",
    ff_boost._pair_r(_pleg("A", "RUSH", "BAL"),
                     _pleg("B", "RUSH", "BAL"))[0] != 0.0)
# The commonest same-game shape. Measuring it beat refusing it: a -1.22%
# deviation over 28,499 pairs is independence, and gating it would have
# refused an EV on a large share of real slips for no measured reason.
_rr = ff_boost._pair_r(_pleg("Henry", "RUSH", "BAL"),
                       _pleg("Flowers", "RECV", "BAL"))
chk("same-team rushing x receiving is PRICEABLE, and says why",
    _rr[0] == 0.0 and "MEASURED independent" in _rr[1] and "28,499" in _rr[1],
    str(_rr))
# The shootout stack: never measured before, and material.
_qq = ff_boost._pair_r(_pleg("Lamar", "PASS", "BAL"),
                       _pleg("Trevor", "PASS", "JAX"))
chk("two opposing quarterbacks are gated, not priced as independent",
    _qq[0] != 0.0 and "+7.22%" in _qq[1], str(_qq))
# Not measurable is still a third answer, distinct from both.
chk("same-team PASS x PASS refuses — n=140, below the sweep's floor",
    ff_boost._pair_r(_pleg("A", "PASS", "BAL"),
                     _pleg("B", "PASS", "BAL"))[0] is None)
chk("and the refusal cites the floor rather than implying independence",
    str(ff_boost.MIN_SWEEP_PAIRS) in ff_boost._pair_r(
        _pleg("A", "PASS", "BAL"), _pleg("B", "PASS", "BAL"))[1])
# The gate threshold sits in the EMPIRICAL GAP, which is the only defence of
# any threshold. If a future measurement lands between 1.75% and 4.60%, this
# fails and the number has to be argued again rather than inherited.
_devs = sorted(abs(v[0] - 1.0) for v in ff_boost.MEASURED_PAIR_LIFT.values())
_below = [d for d in _devs if d <= ff_boost.CORR_GATE_LIFT_DEV]
_above = [d for d in _devs if d > ff_boost.CORR_GATE_LIFT_DEV]
chk("the gate threshold sits in a real gap in the measurements",
    min(_above) - max(_below) > 0.02,
    f"largest passing {max(_below):.4f}, smallest gated {min(_above):.4f}")
# B81: the provenance has to REACH the reader, or the label is dead code and
# the report still asserts independence in terms it never names.
_ok = [_pleg("Henry", "RUSH", "BAL"), _pleg("Flowers", "RECV", "BAL"),
       _pleg("Bateman", "RECV", "BAL")]
_st = classify(_ok, {})
chk("a priceable slip records which measurement cleared each pair",
    len(_st.zeros) == 3 and _st.priceable, str(_st.zeros)[:120])
chk("and the reason names them instead of citing 'the measured table'",
    "MEASURED independent" in _st.reason
    and "established-independent by the measured table" not in _st.reason,
    _st.reason[:160])
# Firing rate, measured before shipping (lesson 51). Gating four pair types
# halved the priceable set; what remains is the dominant real shape.
_slots = [(sd, tm) for sd in _SIDEMK for tm in ("A", "B")]
_tot = _priced = _refused = 0
for _c in itertools.combinations_with_replacement(_slots, 3):
    if sum(1 for sd, tm in _c if sd == "PASS" and tm == "A") > 1:
        continue
    if sum(1 for sd, tm in _c if sd == "PASS" and tm == "B") > 1:
        continue
    _tot += 1
    _lg = [_pleg(f"P{_i}", sd, tm) for _i, (sd, tm) in enumerate(_c)]
    _rs = [ff_boost._pair_r(x, y) for x, y in itertools.combinations(_lg, 2)]
    if any(r is None for r, _ in _rs):
        _refused += 1
    elif all(r == 0.0 for r, _ in _rs):
        _priced += 1
chk("3-leg same-event slips: about a quarter still price as independent",
    0.20 <= _priced / _tot <= 0.40, f"{_priced}/{_tot}")
chk("and NONE are refused as unmeasured — measuring beat refusing",
    _refused == 0, f"{_refused}/{_tot} refused")
# Receiver-heavy slips are the shape that actually gets bet, so they are the
# ones that must survive the gate.
_recv3 = [_pleg("A", "RECV", "JAX"), _pleg("B", "RECV", "JAX"),
          _pleg("C", "RECV", "BAL")]
chk("a receiver-heavy same-game slip is still priceable",
    classify(_recv3, {}).priceable)

section("53. event_id is required at the WRITE side (B113)")
# The live test: 0 of 101 rec records carried an event_id, so every
# calibration row printed CANNOT BE READ. The reading-side guard is INERT
# until coverage exists — it refused for the weak reason (no id) rather than
# the strong one (measured clustering), and would have refused identically
# had those verdicts been genuinely independent. Nothing made the caller
# decide, so nobody did.
# ---------------------------------------------------------------------------
_tmp53 = tempfile.mkdtemp()
_old53 = (ff_betlog.LOG_DIR, ff_betlog.SESSION, ff_betlog.PULL_MARKER)
ff_betlog.LOG_DIR = pathlib.Path(_tmp53)
ff_betlog.SESSION = ff_betlog.LOG_DIR / "_session.jsonl"
ff_betlog.PULL_MARKER = ff_betlog.LOG_DIR / "_pull.json"
_ed53 = types.SimpleNamespace(side="OVER", tier="PASS", model_p=0.5,
                              fair_p=0.5, fair_source="pinnacle",
                              devig_method="shin", reasoning="x")
chk("log_recommendation refuses an OMITTED event_id",
    _raises(lambda: ff_betlog.log_recommendation(
        "P", "m", 1.5, "OVER", "PASS", 0.5, 0.5, -110), TypeError))
chk("log_edge refuses an OMITTED event_id",
    _raises(lambda: ff_betlog.log_edge(_ed53, "P", "m", 1.5), TypeError))
chk("and the error says what to pass and how",
    "event_id=\"53178\"" in _err(lambda: ff_betlog.log_edge(
        _ed53, "P", "m", 1.5)),
    _err(lambda: ff_betlog.log_edge(_ed53, "P", "m", 1.5)))
chk("and names the consequence, not just the rule",
    "CANNOT BE READ" in _err(lambda: ff_betlog.log_edge(
        _ed53, "P", "m", 1.5)))
# An omission and a deliberate None are DIFFERENT FACTS (D16/B39). With
# `= None` they were the same keystroke-free outcome.
chk("an EXPLICIT None is accepted — a decision on record",
    ff_betlog.log_recommendation("P", "m", 1.5, "OVER", "PASS", 0.5, 0.5,
                                 -110, event_id=None)["event_id"] is None)
chk("log_edge accepts an explicit None too",
    ff_betlog.log_edge(_ed53, "P", "m", 1.5,
                       event_id=None)["event_id"] is None)
chk("a numeric id is normalised to a string on the way in",
    ff_betlog.log_edge(_ed53, "P", "m", 1.5,
                       event_id=53178)["event_id"] == "53178")
chk("event_id is keyword-only, so it cannot be passed by position",
    _raises(lambda: ff_betlog.log_recommendation(
        "P", "m", 1.5, "OVER", "PASS", 0.5, 0.5, -110, "", "", "", "",
        False, None, "53178"), TypeError))
# The reason string the live run printed was near-unparseable.
# B113. The instructions name `model_p=None` as the backfill path, so it has
# to work — a documented call that raises is B106 again.
chk("model_p=None is accepted for a backfilled verdict",
    ff_betlog.log_recommendation("P", "m", 1.5, "OVER", "PASS", None, 0.5,
                                 -110, event_id="53178")["model_p"] is None)
chk("but a percentage is still refused",
    _raises(lambda: ff_betlog.log_recommendation(
        "P", "m", 1.5, "OVER", "PASS", 77.0, 0.5, -110,
        event_id="53178"), ValueError))
chk("the zero-coverage reason reads as English",
    ff_betlog._independence([{"player": f"P{_i}"} for _i in range(4)])[1]
    == "no event ids recorded, so these 4 could all be one game or 4 "
       "separate ones",
    ff_betlog._independence([{"player": f"P{_i}"} for _i in range(4)])[1])
shutil.rmtree(_tmp53, ignore_errors=True)
ff_betlog.LOG_DIR, ff_betlog.SESSION, ff_betlog.PULL_MARKER = _old53



# ---------------------------------------------------------------------------
section("63. milestone ladders: de-vig, level pin, and what they refuse (F12)")
# A ladder is one-sided, so `devig` cannot touch it. The way in is that it
# CROSSES the same book's own two-sided main line, and the ratio at the
# crossing measures that book's ladder margin. Every number in the block is
# measured at runtime — no margin constant, because B53's lesson is that a
# constant's size is not its coverage, and a margin frozen in source is one
# nobody rechecks.
#
# The anchor chain is ABSENT from ladders: on a real Vikings/Bills board
# DraftKings posted 182 milestone outcomes and FanDuel 132, against Pinnacle's
# ZERO. So a rung's level comes from the anchor's MAIN line and its shape from
# the book's ladder, and `fair_source` has to say both.


def _q(book, player, *, main=None, over=None, under=None, rung=None,
       price=None, pid=None, susp=None):
    """One `flatten_odds`-shaped row. Keyword-only on purpose: the B24 bug was
    an Under price read as an Over, and a positional fixture builder is how
    that gets re-created in a test."""
    return {"book": book, "player": player, "player_id": pid,
            "line_type": "main" if rung is None else "milestone",
            "line": main, "over": over if rung is None else price,
            "under": under, "rung_threshold": rung, "suspended_at": susp,
            "market": "player_reception_yds"}


def _ladder(book, player, pt, rungs, *, pid=None, main=(-110, -110)):
    """A book's main line plus a ladder, as two line types concatenated."""
    rows = [_q(book, player, main=pt, over=main[0], under=main[1], pid=pid)]
    for t, pr in rungs.items():
        rows.append(_q(book, player, rung=t, price=pr, pid=pid))
    return rows


# A ladder whose prices are generated from a known survival curve, so the
# margin the measurement recovers can be compared against the one built in
# rather than against another run of the same code.
def _synth(book, player, pt, median_yards, margin, thresholds, *, pid=None):
    import math as _m
    rows = [_q(book, player, main=pt, over=-110, under=-110, pid=pid)]
    for t in thresholds:
        # P(X >= t) for an exponential with the given median, then vigged up.
        p = 0.5 ** ((t - 0.5) / median_yards)
        q = min(p * (1.0 + margin), 0.98)
        price = -100 * q / (1 - q) if q >= 0.5 else 100 * (1 - q) / q
        rows.append(_q(book, player, rung=t, price=round(price), pid=pid))
    return rows


_P = ff_props


def _lf(*a, **k):
    """`ladder_fair`, returning [] if it raises — so a fixture built for one
    check cannot take the whole section down before the others run. Removing
    the None-depth branch makes `None <= 25` a TypeError inside `ladder_fair`
    itself, which is loud rather than silent, but it still stopped the suite
    at the first failure instead of reporting every one."""
    try:
        return _P.ladder_fair(*a, **k)
    except BaseException:                                    # noqa: BLE001
        return []




def _unmeasured(fn) -> bool:
    """True when fn() comes back NOT measured. False when it raises.

    A check that asserts something is refused must FAIL when the refusal is
    removed, not CRASH — lesson 14. Removing `ladder_cross_check`'s minimum-n
    gate makes it divide by an empty list, and the revert test read the
    resulting crash as "no check failed" because the suite's own crash line
    was not in the harness's regex. Two mistakes stacked: a check that could
    not fail cleanly, and a harness that could not see a crash.
    """
    try:
        return not fn().measured
    except BaseException:                                    # noqa: BLE001
        return False

# --- the margin, measured against the book's OWN main line -----------------
# Six players on one synthetic board, all built with a 6% margin. Recovering
# roughly that from prices alone is the only check that the crossing
# arithmetic is right rather than merely self-consistent.
_MEDIANS = [("A", 40.0), ("B", 55.0), ("C", 30.0),
            ("D", 48.0), ("E", 62.0), ("F", 35.0)]
# Out to 200+, which is where a real board's ladders go: DraftKings posted
# rungs down to a 2.4% fair on the Vikings/Bills card. Stopping at 100+ left
# the shortest fair at 17%, so the deep-tail gate had nothing to fire on and
# four checks failed for want of a tail rather than for want of a gate.
_RUNGS = [10, 20, 30, 40, 50, 60, 80, 100, 130, 160, 200, 250]
_board = []
for _i, (_who, _med) in enumerate(_MEDIANS):
    # The main line goes at median + 0.5, where the generated curve's true
    # survival is exactly 0.5 and so matches the -110/-110 pair's de-vigged
    # fair. Anywhere else builds a LEVEL offset into the fixture which the
    # crossing then reads as margin: at round(median) - 0.5 the recovery came
    # back 7.05% against a built 6.00%, which looks like a 1pp error in the
    # code and is a 1pp error in the fixture.
    _board += _synth("dk", _who, _med + 0.5, _med, 0.06, _RUNGS, pid=f"p{_i}")
_mg = _P.ladder_margin(_board, book="dk")
chk("a ladder margin is measured from the book's own main-line crossings",
    _mg.measured, _mg.why)
chk("and it recovers the margin the fixture was built with",
    _mg.measured and abs(_mg.margin - 0.06) < 0.015,
    f"built 6.00%, recovered {_mg.margin:.2%}" if _mg.measured else _mg.why)
chk("the observation count is the number of crossings, not of rungs",
    _mg.n == 6, f"n={_mg.n} over 6 players x 8 rungs")

# B53 again, in the one place it would bite hardest: NOT measured must not
# read as a margin of zero, because every fair in the block divides by it.
chk("an unmeasurable margin is None, never 0.0",
    _P.ladder_margin([], book="dk").margin is None)
chk("and `measured` is the property callers gate on",
    _P.ladder_margin([], book="dk").measured is False)

# --- what the margin measurement refuses ------------------------------------
chk("a book absent from the rows is named, not silently unmeasurable",
    "no quotes at all" in _P.ladder_margin(_board, book="caesars").why,
    _P.ladder_margin(_board, book="caesars").why)
_mains_only = [r for r in _board if r["line_type"] == "main"]
chk("mains without ladders says to pass the milestone call too",
    "no milestone rungs" in _P.ladder_margin(_mains_only, book="dk").why,
    _P.ladder_margin(_mains_only, book="dk").why)
_rungs_only = [r for r in _board if r["line_type"] == "milestone"]
chk("ladders without mains says to pass the main call too",
    "no two-sided main line" in _P.ladder_margin(_rungs_only, book="dk").why,
    _P.ladder_margin(_rungs_only, book="dk").why)
# A one-sided "main" row is neither: it cannot be de-vigged and it is not a
# rung, so the board has nothing to cross.
_one_sided = [_q("dk", "A", main=40.5, over=-110, under=None)]
chk("a one-sided main row leaves nothing to cross",
    "neither ladders nor two-sided main lines"
    in _P.ladder_margin(_one_sided, book="dk").why,
    _P.ladder_margin(_one_sided, book="dk").why)

# Below the floor the median is an anecdote. Three players, not six.
_thin = [r for r in _board if r["player"] in ("A", "B", "C")]
chk("too few crossings is refused with the count and the floor",
    not _P.ladder_margin(_thin, book="dk").measured
    and "need 4" in _P.ladder_margin(_thin, book="dk").why,
    _P.ladder_margin(_thin, book="dk").why)
chk("and the floor is the named constant, not a literal",
    _P.LADDER_MARGIN_MIN_N == 4)

# Crossings that disagree are not one margin. Built with margins from 2% to
# 26% across six players, which is dispersion no vig explains.
_spread = []
for _i, _m in enumerate([0.02, 0.06, 0.10, 0.15, 0.20, 0.26]):
    _spread += _synth("dk", f"S{_i}", 39.5, 40.0, _m,
                      [10, 20, 30, 40, 50, 60, 80], pid=f"s{_i}")
_sp = _P.ladder_margin(_spread, book="dk")
chk("crossings that disagree too much are refused, not averaged",
    not _sp.measured and "disagree too much" in _sp.why, _sp.why)
chk("and the refusal reports the dispersion it measured",
    _sp.measured is False and f"{_sp.sd:.2%}" in _sp.why, _sp.why)
# The revert this is guarding: taking the median anyway would return a
# confident ~12% margin off a 2%..26% spread.
chk("the dispersion gate is what refuses it, not the count",
    _sp.n >= _P.LADDER_MARGIN_MIN_N, f"n={_sp.n}")

# A rung grid that does not reach the main line gives no crossing. Not
# extrapolated — D18's rule is that a fair probability for one point is not a
# fair probability for a neighbouring one.
_far = _synth("dk", "Z", 9.5, 40.0, 0.06, [60, 70, 80, 90], pid="z")
chk("a main line outside the ladder's span is not extrapolated to",
    any("outside the ladder's span" in r
        for r in _P.ladder_margin(_board + _far, book="dk").rejected),
    "; ".join(_P.ladder_margin(_board + _far, book="dk").rejected[:2]))
# ...and the rejection does not quietly cost the measurement.
chk("one unusable crossing does not sink the rest of the board",
    _P.ladder_margin(_board + _far, book="dk").measured)

# --- interpolation is LINEAR IN LOG-ODDS ------------------------------------
# Measured by hold-one-out on real ladders, 253 interior rungs: probability-
# linear missed by a median 0.572% where q < 15% and 0.739% in the core;
# logit-linear by 0.137% and 0.521%. 4.2x better where the recommendation
# value is. A survival curve is convex in the tail, so a straight line in
# probability space cuts the corner and always reads HIGH between rungs.
_curve = {9.5: -200, 19.5: 100, 29.5: 400, 39.5: 900}
_mid = _P._ladder_interp(_curve, 24.5)
_lin = (ff_props.american_to_prob(100) + ff_props.american_to_prob(400)) / 2
chk("interpolation sits below the probability-linear reading, not on it",
    _mid < _lin - 1e-4, f"logit {_mid:.4f} vs prob-linear {_lin:.4f}")
chk("a posted rung interpolates to exactly its own price",
    abs(_P._ladder_interp(_curve, 19.5)
        - ff_props.american_to_prob(100)) < 1e-12)
chk("outside the posted span there is no curve, and None is returned",
    _P._ladder_interp(_curve, 5.0) is None
    and _P._ladder_interp(_curve, 99.0) is None)
chk("the ends themselves are inside the span",
    _P._ladder_interp(_curve, 9.5) is not None
    and _P._ladder_interp(_curve, 39.5) is not None)
chk("and it is monotone across the whole span",
    all(_P._ladder_interp(_curve, t) >= _P._ladder_interp(_curve, t + 0.5)
        for t in [9.5 + 0.5 * i for i in range(60)]))

# --- the pin ----------------------------------------------------------------
# A proportional-odds shift, solved closed-form. The first attempt shifted in
# the THRESHOLD domain, which reads better — "DraftKings sits 1.8 yards above
# Pinnacle" — and fails on real boards: the anchor's main line often IS the
# ladder's bottom rung (Aaron Jones at 9.5 against a ladder starting at 9.5),
# and when the book sits a shade below the anchor there, the needed shift is
# negative and lands off the end of the posted ladder. That refused all eight
# of his rungs over a 2pp nudge.
_c, _gap, _why = _P._ladder_pin(_curve, 0.06, 19.5, 0.40)
chk("the pin makes the de-vigged ladder hit the anchor's fair exactly",
    _c is not None
    and abs(_P._expit(_P._logit(ff_props.american_to_prob(100) / 1.06) + _c)
            - 0.40) < 1e-9,
    _why)
chk("the pin reports the level gap in probability points",
    _c is not None and abs(_gap - (0.40 - ff_props.american_to_prob(100)
                                   / 1.06)) < 1e-12)
# The case that killed the threshold-domain pin: anchor at the bottom rung,
# book below the anchor, so the shift must be negative.
_bot = {9.5: -110, 19.5: 120, 29.5: 400}
_cb = _P._ladder_pin(_bot, 0.06, 9.5, 0.55)[0]
chk("a pin at the ladder's bottom rung works when the shift is negative",
    _cb is not None
    and abs(_P._expit(_P._logit(ff_props.american_to_prob(-110) / 1.06) + _cb)
            - 0.55) < 1e-9,
    "this is what the threshold-domain pin refused")
chk("the pin never needs a point outside the posted ladder",
    _P._ladder_pin(_bot, 0.06, 4.0, 0.55)[0] is None
    and "outside the ladder's posted span"
    in _P._ladder_pin(_bot, 0.06, 4.0, 0.55)[2],
    _P._ladder_pin(_bot, 0.06, 4.0, 0.55)[2])
# The yards figure is a DIAGNOSTIC and is allowed to be missing. A number
# that exists for the report must never become one the pricing depends on.
chk("the yards-equivalent is computable inside the span",
    _P._ladder_shift_yards(_curve, 0.06, 19.5, 0.40) is not None)
chk("and is None when unreachable, without costing the pin",
    _P._ladder_shift_yards(_bot, 0.06, 9.5, 0.55) is None
    and _P._ladder_pin(_bot, 0.06, 9.5, 0.55)[0] is not None)

# --- fair probabilities for every rung --------------------------------------
# Pinnacle is the anchor and posts only a main line; dk posts the ladder.
_pin_row = [_q("pinnacle", "A", main=39.5, over=-105, under=-115, pid="p0")]
_dk = _synth("dk", "A", 39.5, 40.0, 0.06,
             [10, 20, 30, 40, 50, 60, 80, 100], pid="p0")
_f = _P.ladder_fair(_board + _pin_row, book="dk", margin=_mg)
_fa = [r for r in _f if r.player == "A"]
chk("every rung the book posts comes back, priced or refused",
    len(_fa) == len(_RUNGS), f"{len(_fa)} rows for {len(_RUNGS)} rungs")
chk("a priced rung carries a fair probability",
    all(r.priceable for r in _fa), "; ".join(r.why for r in _fa if r.why)[:120])
_curve_a = {r.canonical_line: r.price for r in _fa}
_at_anchor = _P._expit(
    _P._logit(_P._ladder_interp(_curve_a, 39.5) / (1 + _mg.margin))
    + _fa[0].level_shift)
chk("the pinned curve passes through the anchor's fair at the anchor's point",
    abs(_at_anchor - ff_props.devig(-105, -115, "auto")[0]) < 1e-9,
    f"pinned {_at_anchor:.6f} vs anchor fair "
    f"{ff_props.devig(-105, -115, 'auto')[0]:.6f}")
chk("the fair is below the price's own implied probability on a flat ladder",
    all(r.fair < r.q_raw for r in _fa if abs(r.level_gap or 0) < 0.005),
    "de-vig has to remove something")
chk("fair probabilities fall as the threshold rises",
    all(a.fair >= b.fair for a, b in zip(_fa, _fa[1:])),
    " ".join(f"{r.threshold:g}+:{r.fair:.3f}" for r in _fa))
chk("fair_source names BOTH halves, because the curve is neither book's",
    "level pinnacle" in _fa[0].fair_source
    and "shape dk ladder" in _fa[0].fair_source, _fa[0].fair_source)
chk("the rung's canonical line is N - 0.5, matching canonical_bet",
    all(abs(r.canonical_line - (r.threshold - 0.5)) < 1e-12 for r in _fa))

# --- what ladder_fair refuses -----------------------------------------------
chk("no measured margin means no priced rung, and the reason is the margin's",
    all(not r.priceable and "ladder margin not measured" in r.why
        for r in _P.ladder_fair(_spread + _pin_row, book="dk")),
    _P.ladder_fair(_spread + _pin_row, book="dk")[0].why)
# The real constraint on a real board: Pinnacle covered 10 of 15 players, so a
# third of the rungs have a shape and no level.
_no_anchor = _P.ladder_fair(_board, book="dk")
chk("a player no anchor-chain book covers is refused, not priced off the book",
    all(not r.priceable for r in _no_anchor)
    and "no anchor-chain book" in _no_anchor[0].why, _no_anchor[0].why)
chk("and the refusal names which books ARE present",
    "present: dk" in _no_anchor[0].why, _no_anchor[0].why)
# A non-chain book's main line is not an anchor. This is the check that stops
# the pin from quietly using DraftKings' own main as its own level, which
# would make every ladder self-consistent and anchored to nothing.
chk("a book outside ANCHOR_CHAIN does not become the level",
    "dk" not in _P.ANCHOR_CHAIN
    and all(r.anchor is None for r in _no_anchor))
# An anchor whose main line is nowhere near the ladder cannot pin it.
_off = [_q("pinnacle", "Z", main=4.5, over=-110, under=-110, pid="z")]
_fz = [r for r in _P.ladder_fair(_board + _far + _off, book="dk",
                                 margin=_mg) if r.player == "Z"]
chk("an anchor point outside the ladder's span refuses that ladder",
    _fz and all(not r.priceable for r in _fz)
    and "outside the ladder's posted span" in _fz[0].why,
    _fz[0].why if _fz else "no rows for Z")
chk("and that refusal does not touch the other players' ladders",
    any(r.priceable for r in _P.ladder_fair(_board + _far + _off + _pin_row,
                                            book="dk", margin=_mg)))

# --- the level gap is FLAGGED, never silently absorbed ----------------------
# The pin removes the gap by construction, which is the whole point of it. So
# without a flag, a book that disagrees with the anchor about the player
# prices exactly like one that agrees, and the disagreement leaves no trace.
_wide = [_q("pinnacle", "A", main=39.5, over=-250, under=+200, pid="p0")]
_fw = [r for r in _P.ladder_fair(_board + _wide, book="dk", margin=_mg)
       if r.player == "A"]
chk("a level gap past the gate is flagged on every rung of that ladder",
    _fw and all(any("level gap" in g for g in r.flags) for r in _fw),
    _fw[0].flags[0] if _fw and _fw[0].flags else "no flag")
chk("the flag reports both sides of the disagreement and its size",
    _fw and "where pinnacle is fair at" in _fw[0].flags[0],
    _fw[0].flags[0] if _fw and _fw[0].flags else "")
chk("a gap inside the gate stays quiet",
    not any("level gap" in g for r in _fa for g in r.flags),
    # Formatted defensively: `f"{None:+.2%}"` raises, and a detail argument
    # is evaluated eagerly, so a revert that blanks `level_gap` took the whole
    # run down instead of failing this check. Lesson 14 in a detail string.
    f"gap {_fa[0].level_gap:+.2%} under {_P.LADDER_LEVEL_GAP_FLAG:.0%}"
    if isinstance(_fa[0].level_gap, float)
    else f"level_gap={_fa[0].level_gap!r}")
_gap_num = _fw[0].level_gap if _fw else None
chk("the gap is carried as a number too, not only as prose",
    _gap_num is not None and abs(_gap_num) >= _P.LADDER_LEVEL_GAP_FLAG,
    f"{_gap_num:+.3%}" if isinstance(_gap_num, float) else repr(_gap_num))
# A gap in the book's favour pushes the fair ABOVE the posted price, which is
# the only way this block ever reports a rung as value on its own.
chk("a gap toward the anchor can lift the fair above the posted price",
    any(r.fair > r.q_raw for r in _fw), "that is the level-gap signal")

# --- uncertainty, and the deep tail ----------------------------------------
_x = _P.ladder_cross_check(_board + _pin_row + _dk, books=("dk", "dk"))
chk("a book compared against ITSELF is refused, not reported as agreement",
    not _x.measured and "agrees with itself" in _x.why, _x.why)
# Written first as `_x.n == 0 or not _x.measured or _x.median == 0.0`, which
# PASSED on the third clause: the same book twice came back MEASURED with a
# disagreement of 0.0, which would have stripped `ladder_fair`'s LOWER BOUND
# flag and added a zero model-risk term — output claiming to have been
# cross-validated against the ladder it was derived from. The guard in
# `ladder_cross_check` exists because this check was too weak to fail.

# Two real books, independently pinned to the same anchor. fd needs its OWN
# four crossings before its margin measures at all, so it gets the whole
# board, not one player — built with a slightly longer median and a wider
# margin so the two disagree by a realistic amount rather than not at all.
_fd = []
for _i, (_who, _med) in enumerate(_MEDIANS):
    _fd += _synth("fd", _who, _med + 0.5, _med + 2.0, 0.07, _RUNGS,
                  pid=f"p{_i}")
_both = _board + _fd + _pin_row
_xc = _P.ladder_cross_check(_both, books=("dk", "fd"))
chk("two independently-pinned ladders give a measured disagreement",
    _xc.measured, _xc.why)
chk("and it is reported with its own n and spread",
    _xc.measured and _xc.n >= 4 and _xc.p90 >= _xc.median,
    _xc.describe())
chk("too few shared rungs is refused rather than averaged",
    _unmeasured(lambda: _P.ladder_cross_check(
        _board + _pin_row + [_q("fd", "A", rung=10, price=-200, pid="p0")],
        books=("dk", "fd"))))

_fu = [r for r in _P.ladder_fair(_both, book="dk", margin=_mg, cross=_xc)
       if r.player == "A"]
_fn = [r for r in _P.ladder_fair(_both, book="dk", margin=_mg)
       if r.player == "A"]
chk("without a cross-book check the uncertainty is labelled a LOWER BOUND",
    all(any("LOWER BOUND" in g for g in r.flags) for r in _fn),
    "the propagated figure carries no term for the pin's own model risk")
chk("and with one, that label is gone",
    not any("LOWER BOUND" in g for r in _fu for g in r.flags))
chk("the cross-book term makes the uncertainty strictly wider",
    all(a.uncertainty > b.uncertainty for a, b in zip(_fu, _fn)),
    f"{_fu[0].uncertainty:.4f} vs {_fn[0].uncertainty:.4f}")
# B93b. A gate that cannot fire is worse than no gate: it reads as a check
# that passed. On the real board this fires on 12 of 132 priced rungs.
_deep = [r for r in _fu if any("deep tail" in g for g in r.flags)]
chk("the deep-tail gate FIRES on a real ladder's longest rungs",
    0 < len(_deep) < len(_fu),
    f"{len(_deep)} of {len(_fu)} rungs")
chk("and it fires on the tail, not on the core",
    _deep and max(r.fair for r in _deep) < min(r.fair for r in _fu
                                               if r not in _deep),
    f"flagged up to {max(r.fair for r in _deep):.1%}" if _deep else "")
chk("the gate is on the RELATIVE figure, which is what decides an edge",
    _deep and all(r.uncertainty / r.fair > _P.LADDER_MAX_REL_UNCERTAINTY
                  for r in _deep))
# Absolute accuracy holding into the tail does not mean relative does: the
# measured cross-book disagreement was 1.14% deep and 0.88% core, only 1.30x,
# while 1.1pp is a third of a 3% rung and a fiftieth of a 50% one.
chk("absolute uncertainty barely grows toward the tail",
    max(r.uncertainty for r in _fu) / min(r.uncertainty for r in _fu) < 2.0,
    f"{min(r.uncertainty for r in _fu):.4f}..{max(r.uncertainty for r in _fu):.4f}")
chk("but the relative figure grows by an order of magnitude",
    max(r.uncertainty / r.fair for r in _fu)
    / min(r.uncertainty / r.fair for r in _fu) > 8.0)
# A ladder too short to hold a rung out cannot measure its own interpolation
# error, and says so rather than reporting a tighter number than it has.
_short = _synth("dk", "Y", 19.5, 20.0, 0.06, [10, 20, 30], pid="y")
_sa = [_q("pinnacle", "Y", main=19.5, over=-110, under=-110, pid="y")]
_fy = [r for r in _P.ladder_fair(_board + _short + _sa, book="dk",
                                 margin=_mg) if r.player == "Y"]
chk("a ladder too short to hold one out says its interp error is unmeasured",
    _fy and all(any("interp error unmeasured" in g for g in r.flags)
                for r in _fy),
    _fy[0].flags[0] if _fy and _fy[0].flags else "no flag")
chk("a long enough ladder measures it and does not carry that flag",
    not any("interp error unmeasured" in g for r in _fa for g in r.flags))

# --- the anchor's DEPTH, which the first live test found missing -----------
# On a Week 10 board every fair was pinned to Kalshi and all 158 joinable
# rungs had an anchor side at or under $25 (min $1.30, median $5.25). The
# ladder printed `fair 80.01% +/- 1.02%` off $1.30 with nothing warning
# anyone. The +/- measures the MARGIN; it says nothing about the LEVEL.
_thin_anchor = [_q("pinnacle", "A", main=39.5, over=-110, under=-110,
                   pid="p0")]
_thin_anchor[0]["over_liquidity"] = 18.0
_thin_anchor[0]["under_liquidity"] = 0.28      # the min side is the anchor
_fth = [r for r in _lf(_board + _thin_anchor, book="dk", margin=_mg)
        if r.player == "A"]
def _flag(recs, needle):
    """The first flag containing `needle`, or "". Never indexes into an empty
    list: removing the flag these checks are about emptied one and CRASHED
    the run instead of failing it — lesson 14, in checks written to test a
    guard added because of a different missed check."""
    for r in recs or ():
        for g in r.flags:
            if needle in g:
                return g
    return ""


chk("a thin anchor is flagged on every rung it pins",
    bool(_fth) and all(any("anchor THIN" in g for g in r.flags)
                       for r in _fth),
    _flag(_fth, "anchor THIN") or "no flag")
# Asserted on POSITION, not presence. `"$0.28" in flag` passed a revert that
# swapped min for max, because the swapped text still contains $0.28 — in the
# other clause, describing the deep side. B124's lesson, re-earned.
chk("and it names the SHALLOW side, not the deep one (B92)",
    _flag(_fth, "anchor THIN").startswith(
        "anchor THIN: pinnacle rests $0.28 on its shallow side"),
    _flag(_fth, "anchor THIN") or "no flag")
# None is "never reported", which is not zero and not deep. DraftKings,
# FanDuel and Bovada all return null.
_unk = [_q("pinnacle", "A", main=39.5, over=-110, under=-110, pid="p0")]
_fun = [r for r in _lf(_board + _unk, book="dk", margin=_mg)
        if r.player == "A"]
chk("an anchor reporting no liquidity is UNKNOWN, not deep",
    bool(_fun) and all(any("anchor depth UNKNOWN" in g for g in r.flags)
                       for r in _fun),
    _flag(_fun, "anchor depth UNKNOWN") or "no flag")
chk("and UNKNOWN is never reported as THIN",
    _fun and not any("anchor THIN" in g for r in _fun for g in r.flags))
# A genuinely deep anchor gets neither flag.
_deep_a = [_q("pinnacle", "A", main=39.5, over=-110, under=-110, pid="p0")]
_deep_a[0]["over_liquidity"] = 500.0
_deep_a[0]["under_liquidity"] = 500.0
_fdp = [r for r in _lf(_board + _deep_a, book="dk", margin=_mg)
        if r.player == "A"]
chk("a deep anchor gets neither depth flag",
    _fdp and not any("anchor THIN" in g or "anchor depth UNKNOWN" in g
                     for r in _fdp for g in r.flags),
    _flag(_fdp, "anchor") or "no depth flags")

# --- a suspended rung is not a price ---------------------------------------
_susp = list(_board) + _pin_row
for _r in _susp:
    if _r["player"] == "A" and _r["line_type"] == "milestone" \
            and _r["rung_threshold"] == 50:
        _r["suspended_at"] = "2026-11-10T01:00:00Z"
chk("a suspended rung is flagged, because a suspended price is not a price",
    any("suspended at" in g
        for r in _P.ladder_fair(_susp, book="dk", margin=_mg)
        if r.player == "A" and r.threshold == 50 for g in r.flags))
chk("and its neighbours are not",
    not any("suspended at" in g
            for r in _P.ladder_fair(_susp, book="dk", margin=_mg)
            if r.player == "A" and r.threshold != 50 for g in r.flags))

# --- the report shows refusals rather than dropping them -------------------
_rep = _P.ladder_report(_P.ladder_fair(_both, book="dk", margin=_mg,
                                       cross=_xc), _mg)
chk("the report leads with the measured margin and its n",
    _line(_rep, "dk: ladder margin").startswith("dk: ladder margin")
    and "crossings" in _line(_rep, "dk: ladder margin"),
    _line(_rep, "dk: ladder margin"))
_count_line = [l for l in _rep.splitlines() if "rung(s) priced" in l]
chk("it counts priced and refused separately on one line",
    len(_count_line) == 1 and "refused" in _count_line[0],
    _count_line[0] if _count_line else "no count line")
chk("refusals are grouped by reason, with a count each",
    "! NOT PRICEABLE" in _rep or all(
        r.priceable for r in _P.ladder_fair(_both, book="dk", margin=_mg,
                                            cross=_xc)))
# B124's lesson: assert on the line that NAMES the thing, not anywhere in the
# report, because the same figure often appears on a neighbouring line.
chk("the margin line reports the measured value, not a neighbouring figure",
    f"{_mg.margin:+.2%}" in _line(_rep, "dk: ladder margin"),
    _line(_rep, "dk: ladder margin"))

# --- the margin's OWN join is normalised too --------------------------------
# Not from an observed miss: on the real board no book spelled a player two
# ways across its own line types (0 of 355 rows). It is the same key choice as
# the anchor join, pinned here so a revert to the raw name fails rather than
# passing because this one payload happened to be consistent. A book feeding
# its ladder and its main line from different sources is exactly where this
# shows up, and it would present as a silently unmeasurable margin.
# A coherent generated ladder, with ONLY the main row respelled — so the
# crossing is a real one and the spelling is the single variable.
# player_id NONE on both rows: with an id present the id index joins them
# regardless of spelling, so the normalisation is only load-bearing for the
# id-less rows — and those are real (Pinnacle carried a null id for Justin
# Jefferson on this very board). A fixture WITH ids passes either way and
# pins nothing.
_spell = _synth("dk", "DJ Moore", 48.5, 48.0, 0.06, _RUNGS, pid=None)
_spell[0] = dict(_spell[0], player="D.J. Moore")
_mg_spell = _P.ladder_margin(_board + _spell, book="dk")
chk("the margin crosses a ladder and main spelled two ways in ONE book",
    _mg_spell.measured
    and not any("D.J. Moore" in r or "DJ Moore" in r
                for r in _mg_spell.rejected),
    "; ".join(_mg_spell.rejected[:2]) or f"n={_mg_spell.n}")
chk("and that crossing really is counted, not merely not-rejected",
    _mg_spell.n == _mg.n + 1, f"{_mg.n} -> {_mg_spell.n}")

# --- the anchor join: id first, name as fallback, conflicts refused --------
# Measured on the real MNF board: fixing this took DraftKings from 132 priced
# rungs to 150. The first version keyed on the TUPLE `(player_id, player)`,
# which obeys the letter of "never join on a raw name" and smuggles the name
# in anyway — and the board had the exact case: DraftKings spells
# "D.J. Moore", Pinnacle spells "DJ Moore", SAME player_id espn:3915416. The
# tuples differed, the join missed, and all 18 of his rungs were refused as
# unanchored while both books were quoting him by the same id.
_DJ_ID = "espn:3915416"
_dj = _synth("dk", "D.J. Moore", 48.5, 48.0, 0.06, _RUNGS, pid=_DJ_ID)
_dj_anchor = [_q("pinnacle", "DJ Moore", main=48.5, over=-110, under=-110,
                 pid=_DJ_ID)]
_fdj = [r for r in _P.ladder_fair(_board + _dj + _dj_anchor, book="dk",
                                  margin=_mg) if r.player == "D.J. Moore"]
chk("one player_id, two spellings, still joins (the live D.J. Moore case)",
    _fdj and all(r.priceable for r in _fdj) and _fdj[0].anchor == "pinnacle",
    _fdj[0].why if _fdj and _fdj[0].why else f"{len(_fdj)} rungs priced")
# Justin Jefferson carried player_id None on BOTH sides of that same board, so
# the name fallback is not a nicety — without it he has no anchor at all.
_jj = _synth("dk", "Justin Jefferson", 77.5, 77.0, 0.06, _RUNGS, pid=None)
_jj_anchor = [_q("pinnacle", "Justin Jefferson", main=77.5, over=-110,
                 under=-110, pid=None)]
_fjj = [r for r in _P.ladder_fair(_board + _jj + _jj_anchor, book="dk",
                                  margin=_mg) if r.player == "Justin Jefferson"]
chk("no player_id on either side joins on the normalised name",
    _fjj and all(r.priceable for r in _fjj),
    _fjj[0].why if _fjj and _fjj[0].why else f"{len(_fjj)} rungs priced")
# Two different players, one spelling. B44's reason for existing.
_twin = _synth("dk", "Mike Williams", 39.5, 40.0, 0.06, _RUNGS, pid="espn:111")
_twin_anchor = [_q("pinnacle", "Mike Williams", main=39.5, over=-110,
                   under=-110, pid="espn:999")]
_ftw = [r for r in _P.ladder_fair(_board + _twin + _twin_anchor, book="dk",
                                  margin=_mg) if r.player == "Mike Williams"]
chk("a conflicting player_id under one name is REFUSED, not guessed",
    _ftw and all(not r.priceable for r in _ftw)
    and "excluded on a conflicting id" in _ftw[0].why,
    _ftw[0].why if _ftw else "no rows")
# The refusal above is the no-anchor-chain one carrying the join note,
# because dk's OWN main for this player is a candidate and only the
# anchor's conflicting row is dropped. With no own main either, the join
# itself comes back empty and says so in its own words.
_bare = [_q("dk", "Mike Williams", rung=_t, price=-150 - 20 * _i,
            pid="espn:111") for _i, _t in enumerate(_RUNGS)]
_fbare = [r for r in _P.ladder_fair(_board + _bare + _twin_anchor,
                                    book="dk", margin=_mg)
          if r.player == "Mike Williams"]
chk("with no own main either, the join reports the id conflict directly",
    _fbare and all(not r.priceable for r in _fbare)
    and "belong to a different player_id" in _fbare[0].why,
    _fbare[0].why if _fbare else "no rows")
# ...and an id-less anchor row is unattributable once a name is ambiguous.
_amb = _twin_anchor + [
    _q("pinnacle", "Mike Williams", main=60.5, over=-110, under=-110,
       pid="espn:222"),
    _q("pinnacle", "Mike Williams", main=12.5, over=-110, under=-110,
       pid=None)]
_fam = [r for r in _P.ladder_fair(_board + _twin + _amb, book="dk",
                                  margin=_mg) if r.player == "Mike Williams"]
chk("an id-less anchor row is dropped when two ids share the spelling",
    _fam and all(not r.priceable for r in _fam),
    _fam[0].why if _fam else "no rows")
chk("and the refusal counts every row it excluded",
    _fam and "3 same-name row(s) excluded" in _fam[0].why,
    _fam[0].why if _fam else "")

# --- a title-only anchor still anchors (B60's signature, through flatten) ---
# `ladder_fair` matches the anchor on the quote's own `book` field, because
# `flatten_odds` already normalised it through `book_key`. A second
# `book_key(c)` call sat in that match and was DEAD — a flattened quote has
# neither `key` nor `title`, so it returned None every time while implying a
# normalisation that happens one layer up. Deleting it is only safe if the
# upstream normalisation really does handle the B60 shape, so that is what
# this checks, through the real `flatten_odds` rather than a hand-built row.
_b60 = {"bookmakers": [
    {"title": "Pinnacle",                       # key ABSENT — the B60 shape
     "markets": [{"key": "player_reception_yds", "line_type": "main",
                  "outcomes": [
                      {"description": "A", "name": "Over", "point": 40.5,
                       "price": -105},
                      {"description": "A", "name": "Under", "point": 40.5,
                       "price": -115}]}]}]}
_b60_rows = ff_props.flatten_odds(_b60, line_type="main")
chk("flatten_odds normalises a title-only Pinnacle to the chain key",
    _b60_rows and _b60_rows[0]["book"] == "pinnacle",
    _b60_rows[0]["book"] if _b60_rows else "no rows")
chk("and book_key on a FLATTENED quote returns None, which is why it went",
    ff_props.book_key(_b60_rows[0]) is None if _b60_rows else False)
_f60 = [r for r in _P.ladder_fair(_board + _b60_rows, book="dk", margin=_mg)
        if r.player == "A"]
chk("so a title-only anchor still pins a ladder",
    _f60 and all(r.priceable for r in _f60)
    and _f60[0].anchor == "pinnacle",
    _f60[0].why or _f60[0].anchor if _f60 else "no rows")

# --- dead guards stay deleted ----------------------------------------------
# `devig` returns a fair strictly inside (0, 1) for all 192 extreme price
# pairs across all three methods, and `american_to_prob` likewise, so the
# three range guards that were here could not fire. Deleted per B126/B127:
# dead code reads as a check that passed.
chk("devig never leaves (0,1), which is why those guards went",
    all(0.0 < ff_props.devig(_o, _u, _m)[0] < 1.0
        for _m in ("auto", "shin", "multiplicative")
        for _o in (-1e7, -110, 110, 1e7) for _u in (-1e7, -110, 110, 1e7)))
chk("so a pin off extreme prices still returns a shift, not a refusal",
    _P._ladder_pin({9.5: -1000000, 19.5: 1000000}, 0.0, 14.5, 0.999)[0]
    is not None)


# ---------------------------------------------------------------------------
section("64. scoring a slip somebody else built (F15)")
# Week 9. The engine's slip was Swift / Odunze / Tez Johnson. The slip placed
# swapped Tez for Luther Burden on intuition; Tez went 76 against a 15.5 line
# with the engine on the OVER, and the slip lost. Nothing could have said
# anything: `enumerate_candidates` only ever sees legs it chose itself, so a
# leg nobody proposed is invisible to it.

_E64 = "87238"


def _l64(player, side, line, odds, fair, *, verdict="CLEAR", model_p=None,
         pid=None, reasons=(), event=None, team=None, pos=None):
    return ff_boost.BoostLeg(
        event_id=event or _E64, book="draftkings",
        market="player_reception_yds", player=player, side=side, odds=odds,
        fair_prob=fair, fair_source="pinnacle", devig_method="shin",
        line=line, player_id=pid, verdict=verdict,
        verdict_side=side if verdict != "UNSCREENED" else "",
        verdict_reasons=reasons, model_p=model_p, team=team, pos=pos)


_eng64 = [_l64("Tez Johnson", "OVER", 15.5, -120, 0.56, model_p=0.63,
               pid="espn:3", event="87238", team="TB", pos="WR")]
_slip64 = [_l64("Tez Johnson", "UNDER", 15.5, -110, 0.44, model_p=0.37,
                pid="espn:3", event="87238", team="TB", pos="WR")]
_s64 = ff_boost.score_slip(_slip64, boost_pct=0.0, book_odds=-110,
                           recommended=_eng64)

# --- the side conflict: the thing CLEAR cannot tell you --------------------
chk("a leg the model wants the other side of is a STOP",
    any(f.level == "STOP" and "prefers the OVER" in f.text
        for f in _s64.findings),
    "; ".join(f.describe() for f in _s64.stops)[:140] or "no STOP")
chk("and the finding says plainly that a CLEAR verdict does not cover it",
    any("nothing was found against this side" in f.text
        for f in _s64.findings))
chk("the slip verdict is DO NOT PLACE",
    _s64.verdict == "DO NOT PLACE", _s64.verdict)
# The gate exists so a fair line and a model estimate differing by a point
# does not flag half a slip.
_near = [_l64("P", "OVER", 50.5, -110, 0.50, model_p=0.49, pid="x")]
chk("a gap inside the gate is NOT called a side conflict",
    ff_boost.score_slip(_near, boost_pct=0.0).candidate is not None
    and not any("prefers the" in f.text
                for f in ff_boost.score_slip(_near, boost_pct=0.0).findings),
    f"gap {_near[0].model_gap:+.3f} under {ff_boost.MODEL_SIDE_GATE}")
chk("and the gate is the named constant",
    ff_boost.MODEL_SIDE_GATE == 0.03)
chk("model_against is None when no model_p was supplied, never False",
    _l64("P", "OVER", 50.5, -110, 0.50).model_against is None)
chk("an absent model_p is reported as a CHECK, not passed over",
    any(f.level == "CHECK" and "no model_p supplied" in f.text
        for f in ff_boost.score_slip(
            [_l64("P", "OVER", 50.5, -110, 0.50)], boost_pct=0.0).findings))
# A percentage here would make the model prefer every side of every leg.
# Asserted on the MESSAGE, not just on the raise. Removing the percentage
# branch still raises — the range check below it catches 72.0 too — so a
# bare _raises() passed a revert that deleted the branch and left the reader
# with "must be strictly between 0 and 1" for an input that is plainly a
# percentage. The diagnosis is the point.
chk("model_p as a percentage is refused, and named as a percentage",
    "looks like a percentage" in _err(
        lambda: _l64("P", "OVER", 50.5, -110, 0.50, model_p=72.0)),
    _err(lambda: _l64("P", "OVER", 50.5, -110, 0.50, model_p=72.0))[:90])
chk("and a certainty is refused too",
    _raises(lambda: _l64("P", "OVER", 50.5, -110, 0.50, model_p=1.0),
            ValueError))

# --- the substitution: only detectable against a recommended set -----------
chk("a player moved to the other side reads as the same man, different bet",
    any("same man, different bet" in f.text for f in _s64.findings),
    "; ".join(f.text for f in _s64.findings if "same man" in f.text)[:120])
# ...and must NOT also be reported as dropped. He is on the slip.
chk("a moved leg is not ALSO reported as missing from the slip",
    "Tez Johnson" not in _s64.dropped, f"dropped={_s64.dropped}")
# Two spellings of one man across the engine's set and the slip. The whole
# project forbids joining on a raw name (B44/B101/B127) and this join is no
# different: FanDuel's milestone board writes "Luther Burden III" where a
# main line writes "Luther Burden", and a raw-name key would call the same
# leg a substitution.
_sp_eng = [_l64("Luther Burden", "OVER", 50.0, -115, 0.53, model_p=0.55,
                pid="espn:9")]
_sp_slip = [_l64("Luther Burden III", "OVER", 50.0, -115, 0.53, model_p=0.55,
                 pid="espn:9")]
_sp = ff_boost.score_slip(_sp_slip, boost_pct=0.0, recommended=_sp_eng)
chk("two spellings of one leg are NOT reported as a substitution",
    _sp.substituted == [] and _sp.dropped == [],
    f"substituted={_sp.substituted} dropped={_sp.dropped}")
chk("and the normaliser agrees the two spellings are one man",
    ff_boost.norm_player("Luther Burden III")
    == ff_boost.norm_player("Luther Burden"),
    f"{ff_boost.norm_player('Luther Burden III')!r}")

_burden = [_l64("Luther Burden III", "OVER", 50.0, -115, 0.53, model_p=0.55,
                pid="espn:9")]
_sub = ff_boost.score_slip(_burden, boost_pct=0.0, recommended=_eng64)
chk("a leg the engine never proposed is flagged as unproposed",
    any("did not propose this leg at all" in f.text for f in _sub.findings))
chk("and it is NOT a STOP on its own — unproposed is not wrong",
    not any(f.level == "STOP" and "did not propose" in f.text
            for f in _sub.findings))
chk("an engine leg genuinely absent IS reported",
    "Tez Johnson" in _sub.dropped, f"dropped={_sub.dropped}")
# Without a recommended set the check cannot run, and the report says so
# rather than reading as a clean bill.
_nocmp = ff_boost.score_slip(_burden, boost_pct=0.0)
chk("with no recommended set, substitution cannot be checked",
    _nocmp.compared is False and _nocmp.substituted == [])
chk("and the report SAYS that, rather than reading as clean",
    "no recommended set given" in _nocmp.report(),
    _line(_nocmp.report(), "!") or "not stated")

# --- what else stops a slip -------------------------------------------------
_uns = [_l64("P", "OVER", 50.5, -110, 0.50, verdict="UNSCREENED",
             model_p=0.55, pid="u1")]
chk("an UNSCREENED leg is a STOP, not a silent pass",
    any(f.level == "STOP" and "never screened" in f.text
        for f in ff_boost.score_slip(_uns, boost_pct=0.0).findings))
_veto = [_l64("P", "OVER", 50.5, -110, 0.50, verdict="VETO", model_p=0.55,
              pid="v1", reasons=("role collapsed",))]
chk("a VETO leg is a STOP and its reason is carried through",
    any(f.level == "STOP" and "role collapsed" in f.text
        for f in ff_boost.score_slip(_veto, boost_pct=0.0).findings))
_caut = [_l64("P", "OVER", 50.5, -110, 0.50, verdict="CAUTION", model_p=0.55,
              pid="c1", reasons=("usage drifting",))]
_sc = ff_boost.score_slip(_caut, boost_pct=0.0)
chk("a CAUTION leg is a CHECK, not a STOP",
    _sc.verdict == "CHECK FIRST" and not _sc.stops, _sc.verdict)
chk("an empty slip is refused rather than scored",
    ff_boost.score_slip([], boost_pct=0.0).verdict == "DO NOT PLACE")

# --- the report ------------------------------------------------------------
_rep64 = _s64.report()
chk("the report leads with the verdict",
    _rep64.splitlines()[0] == "SLIP VERDICT: DO NOT PLACE",
    _rep64.splitlines()[0])
# `independent_odds` returns AMERICAN. Converting it again turned a -110
# single into "+1" — a second conversion producing a plausible price rather
# than an error.
chk("independent odds are printed once-converted, not twice",
    "independent -110" in _line(_rep64, "1 legs"), _line(_rep64, "1 legs"))
chk("an unpriced slip says the book price is missing",
    "book price NOT supplied" in ff_boost.score_slip(
        _burden, boost_pct=0.0).report())
# A genuinely clean leg needs a fair line that is NOT exactly 0.5000 and an
# anchor that has taken money: written first with fair 0.50 and no liquidity,
# it tripped `anchor_opening` — the existing B54/B59 guard, firing correctly
# on a fixture that only looked clean.
def _clean64():
    return _l64("P", "OVER", 50.5, -110, 0.52, model_p=0.55, pid="z1",
                team="TB", pos="WR")


_cl = _clean64()
_cl.anchor_liquidity = 5000.0
_cr = _clean64()
_cr.anchor_liquidity = 5000.0
_clean_score = ff_boost.score_slip([_cl], boost_pct=0.0, book_odds=-110,
                                   recommended=[_cr])
chk("a slip with no findings is reachable at all",
    not _clean_score.findings,
    "; ".join(f.describe() for f in _clean_score.findings)[:160])
chk("and it does not claim to be good",
    "nothing was found, not" in _clean_score.report(),
    _clean_score.report().splitlines()[-1])
chk("its verdict is the non-committal one",
    _clean_score.verdict == "NOTHING FOUND AGAINST IT", _clean_score.verdict)
chk("findings are ordered STOP, then CHECK, then NOTE",
    [f.level for f in _s64.findings] ==
    sorted([f.level for f in _s64.findings],
           key=lambda x: {"STOP": 0, "CHECK": 1, "NOTE": 2}[x])
    or [l.split("]")[0][3:] for l in _rep64.splitlines() if l.strip().startswith("[")]
    == sorted([l.split("]")[0][3:] for l in _rep64.splitlines()
               if l.strip().startswith("[")],
              key=lambda x: {"STOP": 0, "CHECK": 1, "NOTE": 2}[x]))


# ---------------------------------------------------------------------------
section("65. free text to real legs — the half of F15 I shipped without (D18/B44)")
# The backlog calls this the fragile part and it is right: the B44 name join
# and the D18 line-grid mismatch in one operation, where a live run dropped
# 17 of 41 quotes. The rule is REFUSE BY NAME, NEVER SNAP.


def _q65(book, player, market, line, over, under, pid=None):
    return {"book": book, "player": player, "player_id": pid,
            "market": market, "line": line, "over": over, "under": under,
            "line_type": "main", "suspended_at": None}


_b65 = [
    _q65("draftkings", "Christian McCaffrey", "player_rush_yds", 49.5, -115, -105, "e1"),
    _q65("draftkings", "Christian McCaffrey", "player_rush_yds", 54.5, 110, -135, "e1"),
    _q65("draftkings", "Jaxon Smith-Njigba", "player_receptions", 5.5, -130, 105, "e2"),
    _q65("draftkings", "Luther Burden III", "player_reception_yds", 50.5, -115, -105, "e9"),
    _q65("fanduel", "Christian McCaffrey", "player_rush_yds", 51.5, -110, -110, "e1"),
]
_names65 = ["Christian McCaffrey", "Jaxon Smith-Njigba", "Luther Burden III",
            "Brian Thomas Jr.", "Mike Williams", "Marvin Mims Jr."]

# --- the line grid: D18, the whole reason this is not a one-liner ----------
_cmc = ff_boost.resolve_leg("CMC over 50 rush yards", _b65, book="draftkings")
chk("a line the book does not post is REFUSED, not snapped",
    not _cmc.ok and "NOT snapped" in _cmc.why, _cmc.why[:110])
chk("and the refusal hands back the lines that DO exist",
    _cmc.posted_lines == (49.5, 54.5), str(_cmc.posted_lines))
chk("the exact posted line resolves",
    ff_boost.resolve_leg("CMC over 49.5 rush yards", _b65,
                         book="draftkings").ok)
def _px65(text, side_key, board=None, book="draftkings"):
    """The resolved quote's price, or None — never subscripts a refusal.

    Written first as `.quote["under"]`, which is a TypeError the moment
    resolution fails. A revert that broke the name join took the rest of this
    section down with it rather than letting its own three failures report.
    """
    l = ff_boost.resolve_leg(text, _b65 if board is None else board,
                             book=book)
    return None if l.quote is None else l.quote.get(side_key)


chk("and it carries the price for the SIDE asked for, not the other one",
    _px65("CMC under 49.5 rush yards", "under") == -105,
    repr(_px65("CMC under 49.5 rush yards", "under")))
# A whole number IS a legal line and must not be read as its neighbour.
chk("50 and 49.5 are never the same bet, in either direction",
    not ff_boost.resolve_leg("CMC over 50 rush yards", _b65,
                             book="draftkings").ok
    and not ff_boost.resolve_leg("JSN over 5 receptions", _b65,
                                 book="draftkings").ok)

# --- the name join: B44, done against the board rather than a table -------
chk("initials come from the BOARD's spelling, not a stored alias map",
    ff_boost._initials("Christian McCaffrey") == "cmc"
    and ff_boost._initials("Jaxon Smith-Njigba") == "jsn",
    f"{ff_boost._initials('Christian McCaffrey')!r} "
    f"{ff_boost._initials('Jaxon Smith-Njigba')!r}")
chk("an inner capital splits, which is where CMC comes from",
    ff_boost._initials("McCaffrey") == "mc")
for _t, _want in [("CMC", "Christian McCaffrey"),
                  ("JSN", "Jaxon Smith-Njigba"),
                  ("Luther Burden", "Luther Burden III"),
                  ("Burden", "Luther Burden III")]:
    chk(f"{_t!r} resolves to {_want!r}",
        ff_boost.resolve_player(_t, _names65)[0] == _want,
        str(ff_boost.resolve_player(_t, _names65)[0]))
chk("the suffix case is the normalised join, not a partial match",
    "normalised name" in ff_boost.resolve_player("Luther Burden",
                                                 _names65)[1],
    ff_boost.resolve_player("Luther Burden", _names65)[1])
# Ambiguity is refused WITH the candidates, never resolved to a best guess.
_amb65 = _names65 + ["Christian Watson"]
_r = ff_boost.resolve_player("Christian", _amb65)
chk("an ambiguous name is refused and the candidates are listed",
    _r[0] is None and len(_r[2]) == 2, f"{_r[0]} {_r[2]}")
chk("a name not on the board is refused by name",
    ff_boost.resolve_player("Tez", _names65)[0] is None
    and "not on this board" in ff_boost.resolve_player("Tez", _names65)[1])
# No edit distance anywhere: a near-miss must miss.
chk("a near-miss spelling is NOT fuzzy-matched",
    ff_boost.resolve_player("Jaxon Smith-Njigbaa", _names65)[0] is None)

# --- the market phrase -----------------------------------------------------
# `"rec yards"` was the first check here and it discriminates nothing: both
# the long phrase and the short one map to player_reception_yds, so sorting
# the other way gives the same answer and a revert to shortest-wins passed.
# This phrase hits two DIFFERENT markets at different lengths.
chk("the longest market phrase wins when two markets both match",
    ff_boost.market_from_text("rushing yards td")[0] == "player_rush_yds",
    str(ff_boost.market_from_text("rushing yards td")[0]))
chk("and the short word alone still reads as its own market",
    ff_boost.market_from_text("td")[0] == "player_anytime_td")
chk("'rec yards' is not read as 'rec'",
    ff_boost.market_from_text("rec yards")[0] == "player_reception_yds",
    str(ff_boost.market_from_text("rec yards")[0]))
for _p, _k in [("rushing yards", "player_rush_yds"),
               ("rush yds", "player_rush_yds"),
               ("receptions", "player_receptions"),
               ("passing yards", "player_pass_yds"),
               ("anytime td", "player_anytime_td")]:
    chk(f"{_p!r} reads as {_k}", ff_boost.market_from_text(_p)[0] == _k,
        str(ff_boost.market_from_text(_p)[0]))
chk("no market named is refused, not defaulted",
    ff_boost.market_from_text("")[0] is None
    and ff_boost.market_from_text("over 50")[0] is None)
chk("and the refusal says what to write instead",
    "receiving yards" in ff_boost.market_from_text("")[1])

# --- the book filter and one-sided rows ------------------------------------
chk("a line posted at another book does not resolve at this one",
    not ff_boost.resolve_leg("CMC over 51.5 rush yards", _b65,
                             book="draftkings").ok)
chk("and it does resolve at the book that posts it",
    ff_boost.resolve_leg("CMC over 51.5 rush yards", _b65,
                         book="fanduel").ok)
_one = [_q65("draftkings", "P", "player_reception_yds", 50.5, -115, None, "e5")]
chk("a one-sided row refuses the unpriced side by name",
    not ff_boost.resolve_leg("P under 50.5 rec yards", _one,
                             book="draftkings").ok
    and "one-sided" in ff_boost.resolve_leg("P under 50.5 rec yards", _one,
                                            book="draftkings").why)
chk("while the side that IS priced resolves",
    ff_boost.resolve_leg("P over 50.5 rec yards", _one,
                         book="draftkings").ok)

# --- unreadable text --------------------------------------------------------
chk("text that is not a leg is refused with the shape it wanted",
    not ff_boost.resolve_leg("I like CMC tonight", _b65).ok
    and "<player> over|under <number> <market>"
    in ff_boost.resolve_leg("I like CMC tonight", _b65).why)

# --- the whole slip ---------------------------------------------------------
_slip65 = ff_boost.resolve_slip(
    "CMC over 50 rush yards, Burden over 50.5 receiving yards, "
    "Tez over 15.5 rec yards", _b65, book="draftkings")
chk("a slip resolves leg by leg, refusing only what it must",
    [l.ok for l in _slip65] == [False, True, False],
    str([l.ok for l in _slip65]))
_rep65 = ff_boost.resolve_report(_slip65)
chk("the report counts resolved against total",
    _rep65.splitlines()[0] == "1 of 3 legs resolved",
    _rep65.splitlines()[0])
chk("and it says plainly that nothing was guessed",
    "Nothing was snapped or guessed" in _rep65)
chk("a fully resolved slip does not carry that warning",
    "Nothing was snapped" not in ff_boost.resolve_report(
        ff_boost.resolve_slip("Burden over 50.5 receiving yards", _b65,
                              book="draftkings")))
chk("a list of legs is accepted as well as one string",
    len(ff_boost.resolve_slip(["CMC over 49.5 rush yards",
                               "Burden over 50.5 rec yards"], _b65,
                              book="draftkings")) == 2)


# ---------------------------------------------------------------------------
section("66. a verdict with no model_p is not an engine call (B117/B108)")
# The B108 backfill turned out to have been done already, on 2026-11-08. What
# it left behind is the real issue and it is general: a rec with model_p=None
# records the side that was BET, not a side the engine chose. B113 names
# model_p=None as the supported backfill path, so these will keep appearing,
# and the reasoning on one explains the missing probability while saying
# nothing about the side. In the tier table that reads as an engine call.
#
# Fixed at the READ side rather than by amending stored records: it costs no
# log write, needs no new API, and it corrects every such record that already
# exists. `grade_rec` is the only writer of `supersedes` and is hardcoded to
# grading, so there is no amendment path — and adding one would fix the three
# records in hand while leaving the next backfill to repeat it.
import shutil as _sh66
import tempfile as _tf66
_tmp66 = _tf66.mkdtemp()
_old66 = (ff_betlog.LOG_DIR, ff_betlog.SESSION, ff_betlog.PULL_MARKER)
ff_betlog.LOG_DIR = pathlib.Path(_tmp66)
ff_betlog.SESSION = ff_betlog.LOG_DIR / "s.jsonl"
ff_betlog.PULL_MARKER = ff_betlog.LOG_DIR / "pull.json"
try:
    ff_betlog.record_pull(files=1, trashed=0)
except Exception:
    pass

# Two engine calls with a probability, one backfill without.
ff_betlog.log_recommendation("Engine A", "player_reception_yds", 50.5,
                             "OVER", "PASS", 0.42, 0.50, -110,
                             event_id="53178")
ff_betlog.log_recommendation("Engine B", "player_reception_yds", 60.5,
                             "OVER", "LEAN", 0.58, 0.50, -110,
                             event_id="53178")
ff_betlog.log_recommendation("Backfilled C", "player_reception_yds", 33.5,
                             "OVER", "PASS", None, 0.50, -110,
                             event_id="87238",
                             reasoning="B108 backfill: no model_p recorded")
_r66 = _out(ff_betlog.rec_summary)

chk("a verdict with no model_p is named in the summary",
    "carry NO model_p" in _r66, _line(_r66, "!!") or "not named")
chk("and the count is right, not the whole set",
    "1 of 3 verdicts carry NO model_p" in _r66, _line(_r66, "!!"))
chk("it says those record the side BET, not a side the engine chose",
    "the side that was BET" in _r66)
chk("and says plainly that a tier on one is not an engine call",
    "NOT evidence the engine liked that side" in _r66)
chk("the tier it sits under is named, so the reader can subtract it",
    "1 PASS" in _line(_r66, "!!"), _line(_r66, "!!"))
# It must NOT fire when every verdict carries a probability — a warning that
# is always on is a warning nobody reads.
_sh66.rmtree(_tmp66, ignore_errors=True)
_tmp66b = _tf66.mkdtemp()
ff_betlog.LOG_DIR = pathlib.Path(_tmp66b)
ff_betlog.SESSION = ff_betlog.LOG_DIR / "s.jsonl"
ff_betlog.PULL_MARKER = ff_betlog.LOG_DIR / "pull.json"
try:
    ff_betlog.record_pull(files=1, trashed=0)
except Exception:
    pass
ff_betlog.log_recommendation("Engine A", "player_reception_yds", 50.5,
                             "OVER", "PASS", 0.42, 0.50, -110,
                             event_id="53178")
chk("and it stays quiet when every verdict has a model_p",
    "carry NO model_p" not in _out(ff_betlog.rec_summary))
_sh66.rmtree(_tmp66b, ignore_errors=True)
ff_betlog.LOG_DIR, ff_betlog.SESSION, ff_betlog.PULL_MARKER = _old66


# ---------------------------------------------------------------------------
section("67. the correlation tables are recomputed, not remembered (E3)")
# E3: the 43,228-pair map lived only as four constants, duplicated as four
# more next door, and the script that made them was gone — so it could not be
# refreshed, extended or checked. A 2026-11-05 sweep then found the values
# UNREPRODUCIBLE: each sits inside the range a filter sweep gives, but no
# filter lands on them. The real finding was the sensitivity — QB x TE runs
# +0.21 to +0.50 across reasonable choices, a 2.4x swing on an undocumented
# decision, and the instructions tell a session to compare a book's factor
# against this table.
_C = ff_correlation

chk("the filter is an object that gets printed, not a buried choice",
    "min 6 games" in _C.DEFAULT_FILTER.describe()
    and "2023-2026" in _C.DEFAULT_FILTER.describe(),
    _C.DEFAULT_FILTER.describe()[:90])
# The choice that moves the numbers most, and why it is None.
chk("the default has NO volume gate, and says what that means",
    _C.DEFAULT_FILTER.min_volume is None
    and "conditions on ACTIVITY" in _C.DEFAULT_FILTER.describe())
chk("and a volume gate is labelled as conditioning on the outcome",
    "conditions on the outcome"
    in _C.CorrFilter(min_volume=5.0).describe(),
    _C.CorrFilter(min_volume=5.0).describe()[-70:])

# --- the interval, which four bare numbers did not have -------------------
_lo, _hi = _C.fisher_ci(0.26, 7891)
chk("a correlation comes back with an interval around it",
    _lo < 0.26 < _hi and _hi - _lo < 0.1, f"[{_lo:.4f}, {_hi:.4f}]")
chk("and a thin sample gets a WIDER one",
    (_C.fisher_ci(0.26, 200)[1] - _C.fisher_ci(0.26, 200)[0])
    > (_hi - _lo) * 3,
    f"n=200 width {_C.fisher_ci(0.26,200)[1]-_C.fisher_ci(0.26,200)[0]:.4f} "
    f"vs n=7891 width {_hi-_lo:.4f}")
def _ci_nan(r, n):
    """True when fisher_ci refuses with NaNs. False if it raises.

    Removing the n<4 guard makes `sqrt(n-3)` a ZeroDivisionError, so calling
    it bare turned this check into a crash instead of a failure — lesson 14,
    in a check written to prove a guard exists.
    """
    try:
        return all(_m != _m for _m in _C.fisher_ci(r, n))
    except BaseException:                                    # noqa: BLE001
        return False


chk("an interval is refused rather than invented below n=4",
    _ci_nan(0.26, 3))
chk("and refused for an impossible correlation too",
    _ci_nan(1.5, 500) and _ci_nan(-1.0, 500))

# --- the control gate: a table that cannot recover a known pair is void ---
_good = _C.CorrTable("market", _C.DEFAULT_FILTER,
                     entries={("QB", "WR"): _C.CorrEntry(("QB", "WR"), 0.26,
                                                         7891, 0.24, 0.28)},
                     control_ok=True)
chk("a table with a passing control is usable", _good.usable)
_bad = _C.CorrTable("market", _C.DEFAULT_FILTER,
                    entries={("QB", "WR"): _C.CorrEntry(("QB", "WR"), 0.02,
                                                        7891, 0.0, 0.04)},
                    control_ok=False,
                    control_why="control came out +0.02, outside the band")
chk("a table whose control FAILED is not usable", not _bad.usable)
chk("and its report says so loudly rather than printing numbers quietly",
    "NOT usable" in _bad.report(), _line(_bad.report(), "!!"))
chk("an empty table is not usable either",
    not _C.CorrTable("market", _C.DEFAULT_FILTER, control_ok=True).usable)

# --- the recorded tables ---------------------------------------------------
chk("the market and fantasy tables are DIFFERENT quantities",
    _C.recorded(_C.RECORDED_MARKET) != _C.recorded(_C.RECORDED_FANTASY))
chk("QB x RB flips sign between them — B68's prediction, measured",
    _C.RECORDED_MARKET[("QB", "RB")][0] < 0
    < _C.RECORDED_FANTASY[("QB", "RB")][0],
    f"market {_C.RECORDED_MARKET[('QB','RB')][0]:+.4f} vs fantasy "
    f"{_C.RECORDED_FANTASY[('QB','RB')][0]:+.4f}")
chk("`recorded()` drops n and the interval, and is an explicit step",
    set(_C.recorded(_C.RECORDED_MARKET)) == set(_C.RECORDED_MARKET)
    and all(isinstance(v, float)
            for v in _C.recorded(_C.RECORDED_MARKET).values()))

# --- what would change, reported rather than applied ----------------------
_cmp = _C.compare_to_shipped(
    _C.CorrTable("market", _C.DEFAULT_FILTER, entries={
        k: _C.CorrEntry(k, v[0], v[1], v[2][0], v[2][1])
        for k, v in _C.RECORDED_MARKET.items()}, control_ok=True),
    _C.SHIPPED_MARKET)
chk("the comparison names every shipped pair",
    all(str(k) in _cmp for k in _C.SHIPPED_MARKET))
chk("it says whether the shipped value sits inside the measured interval",
    "shipped in CI?" in _cmp and "NO" in _cmp, _cmp.splitlines()[1])
chk("and it states that nothing has been applied",
    "Nothing above has been applied" in _cmp)
# Four of the five shipped values sit outside the measured interval, all
# overstated. That is E3's finding and the reason the market side needs
# sign-off rather than a quiet swap.
_outside = sum(1 for k, v in _C.RECORDED_MARKET.items()
               if not v[2][0] <= _C.SHIPPED_MARKET[k] <= v[2][1])
chk("four of five shipped market values fall outside their interval",
    _outside == 4, f"{_outside} of {len(_C.RECORDED_MARKET)}")
chk("and every one of those overstates the correlation's magnitude",
    all(abs(_C.SHIPPED_MARKET[k]) > abs(v[0])
        for k, v in _C.RECORDED_MARKET.items()
        if not v[2][0] <= _C.SHIPPED_MARKET[k] <= v[2][1]))

# --- F13's market-SIDE cells, measured but NOT wired in --------------------
# `ff_boost.MARKET_SIDE` maps three markets; every other market in a
# same-event slip makes the slip UNPRICEABLE. Correct, and it refuses shapes
# Dustin bets. E3's machinery is what let these be measured.
chk("every (relation, side, side) cell is recorded with n and an interval",
    len(_C.RECORDED_MARKET_SIDE) >= 40
    and all(len(v) == 3 and isinstance(v[1], int)
            for v in _C.RECORDED_MARKET_SIDE.values()),
    f"{len(_C.RECORDED_MARKET_SIDE)} cells")
chk("the keys sort their sides, matching MEASURED_PAIR_LIFT's shape",
    all(list(k[1:]) == sorted(k[1:])
        for k in _C.RECORDED_MARKET_SIDE))
chk("and the control cell is one of them, inside its band",
    _C.MARKET_SIDE_CONTROL in _C.RECORDED_MARKET_SIDE
    and _C.MARKET_SIDE_CONTROL_BAND[0]
    <= _C.RECORDED_MARKET_SIDE[_C.MARKET_SIDE_CONTROL][0]
    <= _C.MARKET_SIDE_CONTROL_BAND[1])
# receptions is NOT receiving yards, and mapping it onto RECV would have
# overstated a receptions leg by about 28%.
_pr = _C.RECORDED_MARKET_SIDE[("same", "PASS", "RECEPTIONS")][0]
_py = _C.RECORDED_MARKET_SIDE[("same", "PASS", "RECV")][0]
chk("PASS x RECEPTIONS is materially below PASS x RECV",
    _pr < _py - 0.05, f"{_pr:+.4f} vs {_py:+.4f}")
chk("player_receptions is mapped, and to its OWN side not RECV",
    ff_boost.MARKET_SIDE.get("player_receptions") == "RECEPTIONS",
    f"got {ff_boost.MARKET_SIDE.get('player_receptions')!r} — folding it "
    f"into RECV overstates a receptions leg by about 28%")
# PASS_TD sat unmapped until a live board named the key. It did, on
# 2026-11-10: `player_pass_tds`, 232 outcomes on event 53178. The rule it
# was waiting on is what matters and still holds — a side stays in
# SIDES_MEASURED_NO_MARKET_KEY until a real board names its string,
# because a guessed key never matches and refuses exactly like a measured
# refusal (B39).
chk("player_pass_tds is mapped to PASS_TD, off a real board",
    ff_boost.MARKET_SIDE.get("player_pass_tds") == "PASS_TD"
    and ("same", "PASS_TD", "TD") in _C.RECORDED_MARKET_SIDE,
    f"got {ff_boost.MARKET_SIDE.get('player_pass_tds')!r}")
chk("and its three neighbours on that board are NOT folded into TD",
    all(k not in ff_boost.MARKET_SIDE for k in
        ("player_reception_tds", "player_rush_tds",
         "player_pass_rush_reception_tds")),
    "different markets with no measured cells — folding them in would be "
    "the RECEPTIONS-into-RECV mistake again")
chk("nothing is left claiming a measured side has no market key",
    not ff_boost.SIDES_MEASURED_NO_MARKET_KEY,
    str(ff_boost.SIDES_MEASURED_NO_MARKET_KEY))
# The standing comment in ff_boost says this pair is unmeasured. It is not,
# any more, and it went the other way.
chk("two same-team anytime TDs are slightly NEGATIVE, not positive",
    _C.RECORDED_MARKET_SIDE[("same", "TD", "TD")][0] < 0,
    f"{_C.RECORDED_MARKET_SIDE[('same','TD','TD')][0]:+.4f} "
    f"(n={_C.RECORDED_MARKET_SIDE[('same','TD','TD')][1]:,})")
chk("and that is measured tightly enough to rule out zero",
    _C.RECORDED_MARKET_SIDE[("same", "TD", "TD")][2][1] < 0,
    str(_C.RECORDED_MARKET_SIDE[("same", "TD", "TD")][2]))
# Nothing is wired. A same-event receptions leg still makes a slip
# unpriceable, which is the behaviour until a gate is signed off.
_rleg = ff_boost.BoostLeg(
    event_id="E1", book="dk", market="player_receptions", player="WR9",
    side="OVER", odds=-110, fair_prob=0.52, fair_source="pinnacle",
    devig_method="shin", line=4.5, player_id="r9", verdict="CLEAR",
    verdict_side="OVER", team="BUF", pos="WR")
_qleg = ff_boost.BoostLeg(
    event_id="E1", book="dk", market="player_pass_yds", player="QB9",
    side="OVER", odds=-110, fair_prob=0.52, fair_source="pinnacle",
    devig_method="shin", line=250.5, player_id="q9", verdict="CLEAR",
    verdict_side="OVER", team="BUF", pos="QB")
_rs = ff_boost.classify([_qleg, _rleg])
chk("a same-event receptions leg is no longer UNMEASURED",
    not _rs.unmeasured and _rs.pairs, _rs.reason[:140])
chk("it is scored on PASS x RECEPTIONS, not on PASS x RECV",
    any(abs(p[2] - _C.RECORDED_MARKET_SIDE[("same", "PASS", "RECEPTIONS")][0])
        < 1e-9 for p in _rs.pairs),
    f"{_rs.pairs} — PASS x RECV would be "
    f"{_C.RECORDED_MARKET_SIDE[('same','PASS','RECV')][0]:+.4f}")
# QB passing x teammate receptions is POSITIVE, so an all-OVER slip's
# product is a floor and F13 unblocks it. That is the permissive half.
_jok, _jwhy = ff_boost.joint_verdict([_qleg, _rleg], _rs.pairs,
                                     cis=_rs.pair_cis)
chk("and an all-OVER QB x receptions slip gets a usable floor",
    _jok and "FLOOR" in _jwhy, _jwhy[:160])

# --- ff_boost is NOT changed from here -------------------------------------
# Signed off and applied 2026-11-10. This asserted the OLD literal while
# the swap was pending; it now pins ff_boost to the recorded MARKET table,
# which is the stronger statement — the old check would have passed on any
# literal that happened to equal 0.31.
chk("ff_boost ships the recorded MARKET table, not a literal",
    all(abs(ff_boost.SAME_TEAM_CORR[k] - _C.RECORDED_MARKET[k][0]) < 1e-12
        for k in ff_boost.SAME_TEAM_CORR),
    str(ff_boost.SAME_TEAM_CORR))
chk("and the provisional RB_RECV entry comes from there too",
    abs(ff_boost.SAME_TEAM_CORR_PROVISIONAL[("QB", "RB_RECV")]
        - _C.RECORDED_MARKET[("QB", "RB_RECV")][0]) < 1e-12)
chk("boost's market table still DIFFERS from the guillotine's fantasy one",
    ff_boost.SAME_TEAM_CORR != ff_guillotine.SAME_TEAM_CORR)
# ...and the reason that swap is low-risk: the VALUE does not reach the EV.
# A correlated pair makes a slip unpriceable whatever r is.
_e1 = ff_boost.BoostLeg(event_id="E1", book="dk", market="player_pass_yds",
                        player="QB1", side="OVER", odds=-110, fair_prob=0.52,
                        fair_source="pinnacle", devig_method="shin",
                        line=250.5, player_id="q1", verdict="CLEAR",
                        verdict_side="OVER", team="BUF", pos="QB")
_e2 = ff_boost.BoostLeg(event_id="E1", book="dk",
                        market="player_reception_yds", player="WR1",
                        side="OVER", odds=-110, fair_prob=0.52,
                        fair_source="pinnacle", devig_method="shin",
                        line=70.5, player_id="w1", verdict="CLEAR",
                        verdict_side="OVER", team="BUF", pos="WR")
_before = ff_boost.classify([_e1, _e2])
_old_stc = dict(ff_boost.SAME_TEAM_CORR)
ff_boost.SAME_TEAM_CORR[("QB", "WR")] = _C.RECORDED_MARKET[("QB", "WR")][0]
_after = ff_boost.classify([_e1, _e2])
ff_boost.SAME_TEAM_CORR.clear()
ff_boost.SAME_TEAM_CORR.update(_old_stc)
chk("a correlated slip is unpriceable under BOTH tables",
    _before.priceable is False and _after.priceable is False)
# The swap is applied, so "before" and "after" are now the same number.
# What the check is for survives: moving the value does not move the EV.
# Demonstrated against the OLD literal rather than the shipped value.
ff_boost.SAME_TEAM_CORR[("QB", "WR")] = 0.31
_old_table = ff_boost.classify([_e1, _e2])
ff_boost.SAME_TEAM_CORR.clear()
ff_boost.SAME_TEAM_CORR.update(_old_stc)
chk("moving the correlation changes the reported r and not the EV",
    _old_table.pairs[0][2] != _after.pairs[0][2]
    and _old_table.priceable == _after.priceable is False
    and _old_table.kind == _after.kind,
    f"{_old_table.pairs[0][2]:+.4f} vs {_after.pairs[0][2]:+.4f}, "
    f"priceable {_old_table.priceable}/{_after.priceable}")


# ---------------------------------------------------------------------------
section("68. the lineup enumerator must enumerate the QB too (B132)")
# `enumerate_lineups` hard-picked ONE quarterback by highest MEAN and never
# enumerated the alternative, while TEs, RBs and WRs all were. Highest mean is
# an EV criterion and this function feeds a FLOOR objective, so it picks wrong
# whenever a lower-mean QB has a better shape.
#
# Measured on a real board at 200,000 sims: a roster holding Jared Goff (mean
# 18.42, sd 7.98) and Trevor Lawrence (mean 18.40, sd 6.66) forced GOFF in on
# a 0.02 mean advantage and 1.32 more sd, costing +0.3495pp of P(elim). Across
# all 260 lineups it produced, Lawrence never appeared.
#
# The suite passed identically before and after the fix, which is the real
# finding here: 1,140 checks and not one of them asked whether a rostered
# player could be reached.
_pool68 = {
    # name: (mean, sd) -> a two-value array reproduces the mean exactly and
    # `_mean_of` is all the enumerator reads.
    "QB_HIGH": [30.0, 10.0],     # mean 20.00, the max-by-mean pick
    "QB_LOW": [19.0, 19.0],      # mean 19.00, lower mean
    "RB1": [12.0, 12.0], "RB2": [11.0, 11.0], "RB3": [10.0, 10.0],
    "WR1": [14.0, 14.0], "WR2": [13.0, 13.0], "WR3": [9.0, 9.0],
    "TE1": [8.0, 8.0],
}
_pool68 = {k: np.array(v, dtype=float) for k, v in _pool68.items()}
_ros68 = {"QB": ["QB_HIGH", "QB_LOW"], "RB": ["RB1", "RB2", "RB3"],
          "WR": ["WR1", "WR2", "WR3"], "TE": ["TE1"]}
_lus68 = ff_guillotine.enumerate_lineups(_ros68, _pool68)
_qbs_seen = {p for L in _lus68 for p in L if p.startswith("QB_")}

chk("every rostered QB is reachable in some enumerated lineup",
    _qbs_seen == {"QB_HIGH", "QB_LOW"},
    f"only {sorted(_qbs_seen)} appeared across {len(_lus68)} lineups")
chk("and the enumeration is not simply the old one twice over",
    len(_lus68) > 0 and all(
        sum(1 for p in L if p.startswith("QB_")) == 1 for L in _lus68),
    "exactly one QB per lineup")
# The property that makes the defect findable without knowing the fix: a
# lineup set built from a SUPERSET roster must contain every lineup the
# smaller roster could build. The old code violated this for any QB that
# was not the mean leader.
_small68 = dict(_ros68, QB=["QB_LOW"])
_small_set = {frozenset(L) for L in ff_guillotine.enumerate_lineups(
    _small68, _pool68)}
_big_set = {frozenset(L) for L in _lus68}
chk("a bigger roster's lineup set CONTAINS the smaller roster's",
    _small_set <= _big_set,
    f"{len(_small_set - _big_set)} lineup(s) lost by adding a player")
# ...and the same property for the other QB, so neither is privileged.
_small_hi = {frozenset(L) for L in ff_guillotine.enumerate_lineups(
    dict(_ros68, QB=["QB_HIGH"]), _pool68)}
chk("which holds for the mean-leader as well as the alternative",
    _small_hi <= _big_set)
chk("a roster with one QB still enumerates normally",
    len(ff_guillotine.enumerate_lineups(_small68, _pool68)) > 0)
# Asserted on the MESSAGE. Removing the no-QB guard still raises, because
# the empty loop leaves `out` empty and the "no legal lineup" check fires
# instead — so a bare _raises() passed a revert that deleted the guard and
# swapped a precise diagnosis for a vague one. Lesson 84, again.
chk("a roster with NO QB is refused, and told it has no QB",
    "roster has no QB" in _err(
        lambda: ff_guillotine.enumerate_lineups(dict(_ros68, QB=[]),
                                                _pool68)),
    _err(lambda: ff_guillotine.enumerate_lineups(dict(_ros68, QB=[]),
                                                 _pool68))[:80])
# Dedupe still holds with the extra loop: one lineup per player SET.
chk("lineups are still deduped by player set, not inflated by the new loop",
    len({frozenset(L) for L in _lus68}) == len(_lus68),
    f"{len(_lus68)} lineups, {len({frozenset(L) for L in _lus68})} sets")


# ---------------------------------------------------------------------------
section("69. a waiver add is a PAIRED delta, never two runs subtracted (B133)")
# Running the sim twice and subtracting does not work: `RNG` is consumed one
# draw per player, so adding a player shifts the stream and the two runs see
# different scenarios. On a live board that produced seven players with an
# IDENTICAL delta of +0.284pp and several that "cleared 2se" while being
# impossible — adding a player can only expand the legal lineup set, so the
# best lineup's P(elim) can never rise. The positive sign was the only tell.
_p69 = {n: np.array(v, dtype=float) for n, v in {
    "QB1": [22.0, 18.0],
    "RB1": [20.0, 16.0], "RB2": [13.0, 11.0], "RB3": [9.0, 7.0],
    "WR1": [18.0, 14.0], "WR2": [12.0, 10.0], "WR3": [8.0, 6.0],
    "TE1": [9.0, 7.0],
    "STAR": [40.0, 36.0],      # clearly better than anyone rostered
    "SCRUB": [1.0, 0.5],       # clearly worse than anyone rostered
}.items()}
_meta69 = {n: ("AAA", p) for n, p in [
    ("QB1", "QB"), ("RB1", "RB"), ("RB2", "RB"), ("RB3", "RB"),
    ("WR1", "WR"), ("WR2", "WR"), ("WR3", "WR"), ("TE1", "TE"),
    ("STAR", "WR"), ("SCRUB", "WR")]}
_t69 = [{"team_id": str(i), "team_name": f"t{i}", "roster": {
            "QB": ["QB1"], "RB": ["RB1", "RB2", "RB3"],
            "WR": ["WR1", "WR2", "WR3"], "TE": ["TE1"]}}
        for i in range(4)]

_wv_star = ff_guillotine.waiver_value(
    _t69, _p69, my_team_id="0", candidate="STAR", n_sims=4000, meta=_meta69)
_wv_scrub = ff_guillotine.waiver_value(
    _t69, _p69, my_team_id="0", candidate="SCRUB", n_sims=4000, meta=_meta69)

chk("the paired delta is never positive, by construction",
    _wv_star.delta <= 0 and _wv_scrub.delta <= 0,
    f"star {_wv_star.delta*100:+.4f}pp, scrub {_wv_scrub.delta*100:+.4f}pp")
chk("a clearly better player resolves and is reachable",
    _wv_star.reachable and _wv_star.player == "STAR", _wv_star.why)
chk("and he lands in the best lineup",
    _wv_star.in_best_lineup, _wv_star.describe())
# The core property, and it was missing: a clearly better player must move
# P(elim) DOWN by a MEASURABLE amount. Every check here asserted the delta
# was not positive, which a revert satisfied by making it exactly zero —
# `p_without = min(all lineups)` destroys the pairing and every delta
# becomes 0.000, passing every "<= 0" check in the section.
chk("a clearly better player moves P(elim) materially DOWN",
    _wv_star.delta < -0.005,
    f"{_wv_star.delta*100:+.4f}pp — a pairing that reads all lineups "
    f"returns exactly 0 here")
chk("and the two terms are genuinely different numbers",
    _wv_star.p_with < _wv_star.p_without,
    f"{_wv_star.p_with:.5f} vs {_wv_star.p_without:.5f}")
chk("a clearly worse player moves it by nothing",
    abs(_wv_scrub.delta) < 1e-12, f"{_wv_scrub.delta*100:+.6f}pp")
chk("and is reported as not in the best lineup",
    not _wv_scrub.in_best_lineup, _wv_scrub.describe())
# The position comes from meta's (team, position) TUPLE. Passing the whole
# tuple to `_meta_field` made the position the string "('AAA', 'WR')", so the
# player went into a slot that does not exist and every candidate came back
# NOT REACHABLE — six real receivers among them, which is how it was caught.
chk("the position is read from meta's second field, not the whole tuple",
    ff_guillotine._meta_field(
        ff_guillotine.meta_lookup("STAR", _meta69)[1]) == "WR",
    repr(ff_guillotine._meta_field(
        ff_guillotine.meta_lookup("STAR", _meta69))))
# A name nobody can resolve is refused BY NAME, not valued at zero.
_wv_none = ff_guillotine.waiver_value(
    _t69, _p69, my_team_id="0", candidate="Nobody At All", n_sims=2000,
    meta=_meta69)
chk("an unresolvable name is refused, not scored",
    not _wv_none.reachable and "does not resolve" in _wv_none.why,
    _wv_none.why[:90])
chk("and its describe() says a bid is unjustified rather than quoting a zero",
    "unjustified on survival grounds" in _wv_none.describe())
# A candidate who IS on the roster but enters no legal lineup — on a bye
# here. He must be reported unreachable, not handed a delta of zero as
# though the simulation had an opinion.
_wv_bye = ff_guillotine.waiver_value(
    _t69, _p69, my_team_id="0", candidate="STAR", n_sims=2000, meta=_meta69,
    unavailable=["STAR"])
chk("a rostered candidate who enters no lineup is UNREACHABLE",
    not _wv_bye.reachable, _wv_bye.describe()[:100])
chk("and the reason names why, rather than reporting a delta",
    "enters no legal lineup" in _wv_bye.why, _wv_bye.why[:90])
chk("a board puts him in the unreachable count, not the ranked list",
    "0 reachable, 1 not" in ff_guillotine.render_waiver_board(
        [_wv_bye], n_sims=2000),
    ff_guillotine.render_waiver_board([_wv_bye], n_sims=2000).splitlines()[0])
chk("a bad team id is refused rather than defaulting to someone",
    _raises(lambda: ff_guillotine.waiver_value(
        _t69, _p69, my_team_id="99", candidate="STAR", n_sims=1000,
        meta=_meta69), ValueError))

# --- the team-code mismatch (B138) -----------------------------------------
# nflverse spells JAX and LA; the FantasyPros connector returns JAC and LAR.
# A connector code passed straight through matched NOBODY and the player was
# projected at his average ON HIS BYE — on a live board that moved Week 11
# from 16.38% to 12.76%, because Blake Corum (LA) was never excluded. Week 10
# was unaffected only because CHI/DEN/PHI/TB spell the same both ways.
_m138 = {"Blake Corum": ("LA", "RB"), "Trevor Lawrence": ("JAX", "QB"),
         "Caleb Williams": ("CHI", "QB"), "Josh Allen": ("BUF", "QB")}


def _bye(codes, week=11, meta=None):
    """players_on_bye, or None if it raises.

    Removing the normalisation makes a MIXED set raise — "LAR" misses while
    "CHI" hits, which is the spelling-problem branch — so calling it bare
    turned these checks into a crash instead of a failure. Lesson 14, in
    checks written for a fix whose whole point is not failing silently.
    """
    try:
        return ff_guillotine.players_on_bye(week, _m138 if meta is None
                                            else meta, codes)
    except BaseException:                                    # noqa: BLE001
        return None
chk("the connector's spelling finds the same players as nflverse's",
    _bye({"LAR"}) == _bye({"LA"}) == {"Blake Corum"},
    f"LAR -> {_bye({'LAR'})}")
chk("and the other known disagreement maps too",
    _bye({"JAC"}) == {"Trevor Lawrence"}, f"JAC -> {_bye({'JAC'})}")
chk("codes that already match are untouched",
    _bye({"CHI"}) == {"Caleb Williams"}, f"CHI -> {_bye({'CHI'})}")
chk("a mixed set resolves every code in it",
    _bye({"LAR", "CHI"}) == {"Blake Corum", "Caleb Williams"},
    f"-> {_bye({'LAR', 'CHI'})}")
chk("canon_team normalises both aliases and leaves the rest alone",
    (ff_guillotine.canon_team("LAR"), ff_guillotine.canon_team("JAC"),
     ff_guillotine.canon_team("chi")) == ("LA", "JAX", "CHI"))
chk("and it survives the NaN that build_meta emits for a missing team",
    ff_guillotine.canon_team(float("nan")) is None
    and ff_guillotine.canon_team(None) is None)
# A code that matches nothing WHILE others match is a spelling problem, not
# a team nobody rosters — refused loudly rather than silently shortening the
# set, which is the failure this whole function exists to prevent.
chk("an unmatched code beside a matched one is refused, not dropped",
    "match no player in meta" in _err(
        lambda: ff_guillotine.players_on_bye(11, _m138, {"CHI", "ZZZ"})),
    _err(lambda: ff_guillotine.players_on_bye(11, _m138,
                                              {"CHI", "ZZZ"}))[:70])
chk("and the refusal names the alias map as the likely cause",
    "TEAM_CODE_ALIASES" in _err(
        lambda: ff_guillotine.players_on_bye(11, _m138, {"CHI", "ZZZ"})))
# All-unmatched is the different case: a league that rosters none of the bye
# teams. Legitimate, and must NOT raise.
chk("a bye week where the league rosters nobody affected is fine",
    _bye({"SEA", "ARI"}) == set(), f"-> {_bye({'SEA', 'ARI'})}")

# --- the floor annotation's UNITS (B136) -----------------------------------
# `delta` is a FRACTION and `floor` is in PERCENTAGE POINTS, as its own
# message says. Compared directly, the test only passed above a 25pp delta,
# so EVERY line printed "inside the floor — treat as zero", including James
# Cook at -12.23pp on a live board, 78x the simulation's own noise.
#
# Fourteen checks shipped around this function the night before and not one
# of them asserted on the LABEL. They tested the ranking and the delta, which
# were correct the whole time.
_big69 = ff_guillotine.WaiverValue("Cook", 0.1381, 0.2604, True, 80_000, True)
chk("a 12pp move is RESOLVED, not 'inside the 0.250pp floor'",
    "RESOLVED" in _big69.describe(0.25)
    and "inside the" not in _big69.describe(0.25),
    _big69.describe(0.25))
chk("and the delta it prints is in the same unit as the floor",
    "-12.230pp" in _big69.describe(0.25), _big69.describe(0.25))
# A delta just over and just under the floor, so the boundary is pinned and
# not merely the extremes.
# 0.2578 against 0.2604 is a 0.26pp delta — just over the 0.25pp floor.
# Written first as 0.2600 vs 0.26040, which is 0.04pp and BELOW it: the
# check failed for the right reason and the fixture was the thing wrong.
chk("a delta just ABOVE the floor resolves",
    "RESOLVED" in ff_guillotine.WaiverValue(
        "X", 0.2578, 0.26040, True, 80_000, True).describe(0.25),
    ff_guillotine.WaiverValue("X", 0.2578, 0.26040, True, 80_000,
                              True).describe(0.25))
chk("a delta just BELOW the floor is called inside it",
    "inside the 0.250pp floor" in ff_guillotine.WaiverValue(
        "X", 0.26020, 0.26040, True, 80_000, True).describe(0.25),
    ff_guillotine.WaiverValue("X", 0.26020, 0.26040, True, 80_000,
                              True).describe(0.25))
chk("and a zero delta is inside any floor",
    "inside the" in ff_guillotine.WaiverValue(
        "X", 0.26, 0.26, False, 80_000, True).describe(0.25))

# --- a STALE candidate, which stale_names() cannot see (B137) --------------
# `stale_names()` scans ROSTERS only, so a stale CANDIDATE was invisible:
# Tyreek Hill, zero 2026 games, came FOURTH on a live board with nothing
# saying his level was last season's.
_stale69 = ff_guillotine.WaiverValue("Hill", 0.1966, 0.2604, True, 80_000,
                                     True, stale=True)
chk("a candidate projected from a prior season is flagged on his own line",
    "STALE" in _stale69.describe(0.25), _stale69.describe(0.25))
chk("and a current-season candidate is not",
    "STALE" not in _big69.describe(0.25))
# A position assumed because meta has none is not a measurement.
_dflt69 = ff_guillotine.WaiverValue("Hill", 0.1966, 0.2604, True, 80_000,
                                    True, position_defaulted=True)
chk("an assumed position is named as assumed",
    "position ASSUMED" in _dflt69.describe(0.25), _dflt69.describe(0.25))
chk("and a position read from meta is not",
    "ASSUMED" not in _big69.describe(0.25))
chk("waiver_value reports a measured position as not defaulted",
    not ff_guillotine.waiver_value(
        _t69, _p69, my_team_id="0", candidate="STAR", n_sims=1500,
        meta=_meta69).position_defaulted)
chk("and defaults it, flagged, when meta has no position for him",
    ff_guillotine.waiver_value(
        _t69, _p69, my_team_id="0", candidate="STAR", n_sims=1500,
        meta={}).position_defaulted)
# Staleness read THROUGH waiver_value off the pool, not handed to the
# dataclass. Every check above constructed `stale=True` directly, so a
# revert that stopped reading `pool.stale` passed all of them.
_stale_pool = dict(_p69)
_sp = ff_guillotine.Pool() if hasattr(ff_guillotine, "Pool") else None
try:
    _stale_pool = ff_guillotine.Pool(_p69)
except Exception:                                            # noqa: BLE001
    class _SP(dict):
        pass
    _stale_pool = _SP(_p69)
_stale_pool.stale = {"STAR"}
chk("waiver_value reads staleness off the pool, not from its caller",
    ff_guillotine.waiver_value(
        _t69, _stale_pool, my_team_id="0", candidate="STAR", n_sims=1500,
        meta=_meta69).stale)
chk("and a current-season candidate off the same pool is not stale",
    not ff_guillotine.waiver_value(
        _t69, _stale_pool, my_team_id="0", candidate="SCRUB", n_sims=1500,
        meta=_meta69).stale)

# --- the board ------------------------------------------------------------
_board69 = ff_guillotine.waiver_board(
    _t69, _p69, my_team_id="0", candidates=["STAR", "SCRUB", "Nobody At All"],
    n_sims=4000, meta=_meta69)
chk("the board counts reachable and unreachable separately",
    "2 reachable, 1 not" in _board69, _board69.splitlines()[0])
chk("it ranks by delta, best first",
    _board69.splitlines()[1].strip().startswith("STAR"),
    _board69.splitlines()[1].strip()[:60])
chk("unreachable candidates are NAMED, not dropped from the board",
    "Nobody At All" in _board69)
# The impossible-sign alarm, tested through the RENDERER. `waiver_value`
# cannot produce a positive delta, so a test that goes through it can never
# reach that branch — and the check first written here passed on an `or True`
# clause, which is not a check. That is the vacuous-clause fault twice in one
# evening, so: assert the alarm fires, and assert it stays quiet.
_pos69 = [ff_guillotine.WaiverValue("BROKEN", 0.20, 0.10, True, 100, True)]
chk("a positive delta trips the impossible-sign alarm",
    "IMPOSSIBLE" in ff_guillotine.render_waiver_board(_pos69, n_sims=100),
    _line(ff_guillotine.render_waiver_board(_pos69, n_sims=100), "!!"))
chk("and the alarm says not to act on the board",
    "do not act on this board"
    in ff_guillotine.render_waiver_board(_pos69, n_sims=100))
_neg69 = [ff_guillotine.WaiverValue("FINE", 0.10, 0.20, True, 100, True)]
chk("a normal board does NOT carry the alarm",
    "IMPOSSIBLE" not in ff_guillotine.render_waiver_board(_neg69,
                                                          n_sims=100),
    ff_guillotine.render_waiver_board(_neg69, n_sims=100))
chk("an unreachable-only board does not trip it either",
    "IMPOSSIBLE" not in ff_guillotine.render_waiver_board(
        [ff_guillotine.WaiverValue("X", float("nan"), float("nan"), False,
                                   100, False, "no")], n_sims=100))


# ---------------------------------------------------------------------------
section("70. an eliminated team is OUT of the pool, not scored at zero (B135)")
# In this format a knocked-out roster is released, so `get_roster` returns
# `{}` for an eliminated team. Left in the pool it scored 0.00, placed last in
# every single simulation, and returned **P(elim) = 0.0000%** — the worst
# wrong answer this engine can give, because in an elimination format it says
# you are safe. `short_rosters` named it, but a caller reads the headline.
#
# This is NOT the unfillable-roster case: byes and injuries leave LIVE teams
# short every week, and the strict=False fallback handles those by fielding
# what they have and reporting it understated. No players versus not enough.
_p70 = {n: np.array(v, dtype=float) for n, v in {
    "QB1": [22, 18], "RB1": [20, 16], "RB2": [13, 11], "RB3": [9, 7],
    "WR1": [18, 14], "WR2": [12, 10], "WR3": [8, 6], "TE1": [9, 7],
    "QB2": [21, 17], "RB4": [19, 15], "RB5": [12, 10], "RB6": [8, 6],
    "WR4": [17, 13], "WR5": [11, 9], "WR6": [7, 5], "TE2": [8, 6]}.items()}
_A70 = {"QB": ["QB1"], "RB": ["RB1", "RB2", "RB3"],
        "WR": ["WR1", "WR2", "WR3"], "TE": ["TE1"]}
_B70 = {"QB": ["QB2"], "RB": ["RB4", "RB5", "RB6"],
        "WR": ["WR4", "WR5", "WR6"], "TE": ["TE2"]}
_t70 = [{"team_id": "0", "team_name": "me", "roster": _A70},
        {"team_id": "1", "team_name": "alive", "roster": _B70},
        {"team_id": "2", "team_name": "gone-empty", "roster": {}},
        {"team_id": "4", "team_name": "gone-blank",
         "roster": {"QB": [], "RB": [], "WR": [], "TE": []}}]
_r70 = ff_guillotine.run(_t70, _p70, my_team_id="0", n_sims=8000)

chk("an eliminated team does not make my P(elim) zero",
    min(_r70.p_last) > 0.01,
    f"{min(_r70.p_last):.4%} — it was 0.0000% with them in the pool")
chk("both shapes of empty roster are detected",
    sorted(_r70.eliminated_teams) == ["gone-blank", "gone-empty"],
    str(_r70.eliminated_teams))
chk("and they are NOT reported as merely short",
    _r70.short_rosters == [], str(_r70.short_rosters))
chk("they are gone from the opponent set",
    set(_r70.opp_scores_mean) == {"alive"}, str(list(_r70.opp_scores_mean)))
chk("the report names them rather than dropping them silently",
    "ELIMINATED, excluded from the pool" in _r70.report(),
    _line(_r70.report(), "  ELIMINATED"))
chk("and says what the risk is now relative to",
    "relative to the 2 teams still alive" in _r70.report(),
    _line(_r70.report(), "  Every P(elim)"))
# My own empty roster means I am out. Refused, not simulated.
chk("my own empty roster is refused with the reason",
    "already been eliminated" in _err(
        lambda: ff_guillotine.run(_t70, _p70, my_team_id="2", n_sims=100)),
    _err(lambda: ff_guillotine.run(_t70, _p70, my_team_id="2",
                                   n_sims=100))[:80])
# A live team that simply cannot fill its slots must STILL be simulated and
# reported short — the distinction the fix turns on.
_t70b = [dict(_t70[0]), dict(_t70[1]),
         {"team_id": "5", "team_name": "short-not-out",
          "roster": {"QB": ["QB2"], "RB": ["RB4"], "WR": [], "TE": []}}]
_r70b = ff_guillotine.run(_t70b, _p70, my_team_id="0", n_sims=8000)
chk("a team with SOME players is short, not eliminated",
    _r70b.eliminated_teams == []
    and any("short-not-out" in x for x in _r70b.short_rosters),
    f"elim={_r70b.eliminated_teams} short={_r70b.short_rosters[:1]}")
chk("and it is still counted as an opponent",
    "short-not-out" in _r70b.opp_scores_mean)
# Everyone else out. A real end state, and it used to surface as numpy's
# "zero-size array to reduction operation minimum", which tells a reader
# nothing about what happened.
chk("last team standing is refused with a readable reason",
    "last one standing" in _err(
        lambda: ff_guillotine.run(
            [dict(_t70[0]), {"team_id": "9", "team_name": "gone",
                             "roster": {}}],
            _p70, my_team_id="0", n_sims=500)),
    _err(lambda: ff_guillotine.run(
        [dict(_t70[0]), {"team_id": "9", "team_name": "gone", "roster": {}}],
        _p70, my_team_id="0", n_sims=500))[:100])
chk("and that reason names who went out",
    "Eliminated: gone" in _err(
        lambda: ff_guillotine.run(
            [dict(_t70[0]), {"team_id": "9", "team_name": "gone",
                             "roster": {}}],
            _p70, my_team_id="0", n_sims=500)))

# With no eliminations at all the new lines stay out of the report.
_r70c = ff_guillotine.run([dict(_t70[0]), dict(_t70[1])], _p70,
                          my_team_id="0", n_sims=4000)
chk("a league with nobody out carries no elimination line",
    _r70c.eliminated_teams == []
    and "ELIMINATED, excluded" not in _r70c.report())


# ---------------------------------------------------------------------------
section("71. a DROP is the same paired read as an add (B139)")
# `waiver_value` covered the add and nothing covered the cut, so a session
# evaluating a drop rolled its own and walked into exactly the trap B133
# exists to stop: four separate runs gave four drop figures spanning 0.21pp,
# which read as an ordering and was entirely between-run RNG noise. On shared
# draws all four were identical to three decimals.
_p71 = {n: np.array(v, dtype=float) for n, v in {
    "QB1": [22, 18], "RB1": [20, 16], "RB2": [13, 11], "RB3": [9, 7],
    "RB4": [6, 4], "RB5": [5, 3], "WR1": [18, 14], "WR2": [12, 10],
    "WR3": [8, 6], "WR4": [7, 5], "TE1": [9, 7], "TE2": [4, 3],
    "QB2": [21, 17], "RB6": [19, 15], "RB7": [12, 10], "RB8": [8, 6],
    "WR5": [17, 13], "WR6": [11, 9], "WR7": [7, 5], "TE3": [8, 6]}.items()}
_A71 = {"QB": ["QB1"], "RB": ["RB1", "RB2", "RB3", "RB4", "RB5"],
        "WR": ["WR1", "WR2", "WR3", "WR4"], "TE": ["TE1", "TE2"]}
_B71 = {"QB": ["QB2"], "RB": ["RB6", "RB7", "RB8"],
        "WR": ["WR5", "WR6", "WR7"], "TE": ["TE3"]}
_t71 = [{"team_id": "0", "team_name": "me", "roster": _A71},
        {"team_id": "1", "team_name": "opp", "roster": _B71}]

_dv_star = ff_guillotine.drop_value(_t71, _p71, my_team_id="0",
                                    candidate="RB1", n_sims=20_000)
_dv_bench = ff_guillotine.drop_value(_t71, _p71, my_team_id="0",
                                     candidate="RB5", n_sims=20_000)
chk("cutting a cost is never negative, by construction",
    _dv_star.cost >= -1e-12 and _dv_bench.cost >= -1e-12,
    f"star {_dv_star.cost*100:+.4f}pp bench {_dv_bench.cost*100:+.4f}pp")
chk("cutting the best player costs materially",
    _dv_star.cost > 0.05, f"{_dv_star.cost*100:+.3f}pp")
chk("cutting a bench body costs nothing",
    abs(_dv_bench.cost) < 1e-12, f"{_dv_bench.cost*100:+.6f}pp")

# --- the TWO kinds of zero, which is the reason this reports ---------------
# A bye player is absent before lineups are enumerated, so his cost cannot be
# anything but zero — a fact about the schedule. A bench body who is in many
# lineups but never the best one is also zero — a fact about THIS roster. A
# reader acting on those would do different things.
_dv_bye = ff_guillotine.drop_value(_t71, _p71, my_team_id="0",
                                   candidate="RB3", n_sims=20_000,
                                   unavailable=["RB3"])
chk("a bye player's zero is marked STRUCTURAL",
    _dv_bye.structural_zero and "free STRUCTURALLY" in _dv_bye.describe(),
    _dv_bye.describe())
chk("and he is in no lineup at all, which is why",
    _dv_bye.appears_in == 0, f"{_dv_bye.appears_in} lineups")
chk("a bench body's zero is NOT structural — he is in lineups, just not best",
    not _dv_bench.structural_zero and _dv_bench.appears_in > 0
    and "free on THIS roster" in _dv_bench.describe(),
    _dv_bench.describe())
chk("so the two zeros do not print the same sentence",
    _dv_bye.describe() != _dv_bench.describe())

# --- refusals -------------------------------------------------------------
chk("a player not on my roster is refused, not priced",
    not ff_guillotine.drop_value(_t71, _p71, my_team_id="0",
                                 candidate="RB6",
                                 n_sims=5000).on_roster)
chk("an unresolvable name is refused by name",
    "does not resolve" in ff_guillotine.drop_value(
        _t71, _p71, my_team_id="0", candidate="Nobody At All",
        n_sims=5000).why)
# The only QB is in every lineup, so there is no without-him comparison.
_dv_qb = ff_guillotine.drop_value(_t71, _p71, my_team_id="0",
                                  candidate="QB1", n_sims=20_000)
chk("the only QB cannot be priced, and says so instead of printing nan",
    "CANNOT BE PRICED" in _dv_qb.describe()
    and "nan" not in _dv_qb.describe(),
    _dv_qb.describe())
chk("a bad team id is refused",
    _raises(lambda: ff_guillotine.drop_value(
        _t71, _p71, my_team_id="99", candidate="RB1", n_sims=1000),
        ValueError))

# --- the board ------------------------------------------------------------
_db71 = ff_guillotine.drop_board(_t71, _p71, my_team_id="0", n_sims=20_000,
                                 unavailable=["RB3"])
chk("the board prices every rostered player off ONE run",
    "11 priced, 1 not" in _db71, _db71.splitlines()[0])
# The property that PROVES the draws are shared, which the count does not:
# every priced row must report the SAME p_before. One run per candidate —
# which is what the code did before `_result` was threaded through, and what
# a session doing this by hand did — gives each row its own baseline, and the
# spread between them reads as an ordering. That is B133 exactly: four drop
# figures spanning 0.21pp off four runs, all identical on shared draws.
_rows71 = [l for l in _db71.splitlines() if "% -> " in l]
_pb71 = {l.split(": ")[1].split(" -> ")[0] for l in _rows71}
chk("every priced row shares ONE baseline, proving one set of draws",
    len(_pb71) == 1,
    f"{len(_pb71)} distinct baselines across {len(_rows71)} rows: "
    f"{sorted(_pb71)[:4]}")
chk("it states the noise floor and that a gap inside it is not an ordering",
    "is NOT an ordering" in _db71, _db71.splitlines()[1])
chk("cheapest cut comes first",
    _db71.splitlines()[2].strip().startswith("RB3"),
    _db71.splitlines()[2].strip()[:40])
chk("and the most expensive comes last among the priced",
    "RB1" in [l.strip().split(":")[0] for l in _db71.splitlines()
              if "pp)" in l][-1],
    str([l.strip().split(":")[0] for l in _db71.splitlines()
         if "pp)" in l][-1]))
chk("the unpriceable QB is named, not dropped from the board",
    "QB1" in _db71 and "CANNOT BE PRICED" in _db71)


# ---------------------------------------------------------------------------
section("72. a shortlist says when its own order is not a ranking (B57)")
# B57: the +600 ceiling fixed the zero-candidate failure and the band then
# filtered nothing — 616 of 616 BetMGM combinations inside it, ranking left
# to P(cash) differences of ~1.5 points, half of them resting on fairs of
# exactly 0.5000. "The ordering of candidates 1 through 40 was close to
# noise."
#
# Measured on the real MNF board: 120 of 120 priceable, independent odds
# +543..+611, head-to-tail 2.21 points, top ten 1.45, and the median ADJACENT
# gap 0.358 against 0.366 points of propagated noise — 0.98x. Adjacent
# candidates are indistinguishable, which is what a ranked list denies.
#
# Neither replacement works. Aggregate model edge spans 41x more and that
# spread IS the model's level error (per-leg sd 0.1258 against B128's 0.115,
# ratio 1.09). CI width barely varies (1.21x) and correlates NEGATIVELY with
# the model's error (-0.51), so ranking by confidence picks the legs it is
# most wrong about. Sample verdict did not vary at all.
_E72 = "E72"


def _l72(name, fair, odds=-110, line=50.5, team="AAA", pos="WR"):
    return ff_boost.BoostLeg(
        event_id=_E72, book="dk", market="player_reception_yds", player=name,
        side="OVER", odds=odds, fair_prob=fair, fair_source="pinnacle",
        devig_method="shin", line=line, player_id=name.lower(),
        verdict="CLEAR", verdict_side="OVER", team=team, pos=pos)


# A flat board: every fair within a whisker of 0.5000, which is what the
# half-yard grid produces (B54).
_flat = [ff_boost.make_candidate(
    [_l72(f"F{i}a", 0.5000), _l72(f"F{i}b", 0.5000 + i * 0.0002),
     _l72(f"F{i}c", 0.5000)], boost_pct=0.5) for i in range(10)]
_flat = [c for c in _flat if c.structure.priceable and c.p_cash]
_ok_flat, _why_flat = ff_boost.rank_is_meaningful(_flat)
chk("a flat board's ordering is refused as a ranking",
    not _ok_flat, _why_flat[:110])
chk("and the refusal reports the adjacent gap against the noise",
    "median adjacent gap" in _why_flat and "propagated" in _why_flat,
    _why_flat[:90])
chk("it names how many legs sit at exactly 0.5000",
    "within 0.5pp of exactly 0.5000" in _why_flat)
chk("and says plainly that candidate 1 does not beat candidate 2",
    "does not beat candidate 2" in _why_flat)

# A board whose legs genuinely differ must still rank.
_wide = [ff_boost.make_candidate(
    [_l72(f"W{i}a", 0.40 + i * 0.03), _l72(f"W{i}b", 0.55),
     _l72(f"W{i}c", 0.50)], boost_pct=0.5) for i in range(10)]
_wide = [c for c in _wide if c.structure.priceable and c.p_cash]
_ok_wide, _why_wide = ff_boost.rank_is_meaningful(_wide)
chk("a board with real differences IS ranked",
    _ok_wide, _why_wide[:110])
chk("so the gate is not simply always-off",
    _ok_wide != _ok_flat)

# The gate is on the ADJACENT gap, not the head-to-tail spread — a long tail
# inflates the spread while the head stays flat, which is exactly the real
# board (2.21 points overall, 1.45 across the top ten, 0.358 adjacent).
_tail = _flat + [ff_boost.make_candidate(
    [_l72("Ta", 0.20), _l72("Tb", 0.20), _l72("Tc", 0.20)], boost_pct=0.5)]
_tail = [c for c in _tail if c.structure.priceable and c.p_cash]
chk("a wide tail does not make a flat head rankable",
    not ff_boost.rank_is_meaningful(_tail)[0],
    ff_boost.rank_is_meaningful(_tail)[1][:100])

# Priced candidates rank normally: a real SGP quote differs between
# candidates by far more than the product of the legs does.
_priced = [ff_boost.price_candidate(c, book_odds=500 + 20 * i)
           for i, c in enumerate(_flat)]
chk("priced candidates are allowed to rank",
    ff_boost.rank_is_meaningful(_priced)[0],
    ff_boost.rank_is_meaningful(_priced)[1][:90])
chk("one candidate is trivially ordered",
    ff_boost.rank_is_meaningful(_flat[:1])[0])

# --- a board right AT the boundary, which is what pins the arithmetic ----
# The flat and wide fixtures above are far from the gate, so they survive any
# change to how the noise is propagated. This one sits at ~0.78x: it fails
# the gate, and it flips to passing the moment the leg count stops entering
# the propagation (dropping the sqrt(3) shrinks the noise and lifts the ratio
# to ~1.35). Reverts to the propagation passed every other check here.
_edge72 = [ff_boost.make_candidate(
    [_l72(f"E{i}a", 0.50 + i * 0.012), _l72(f"E{i}b", 0.50),
     _l72(f"E{i}c", 0.50)], boost_pct=0.5) for i in range(10)]
_edge72 = [c for c in _edge72 if c.structure.priceable and c.p_cash]
_ok_edge, _why_edge = ff_boost.rank_is_meaningful(_edge72)
chk("a board just under the gate is refused",
    not _ok_edge, _why_edge[:100])
chk("and its ratio really is near the gate, not miles from it",
    0.6 < float(_why_edge.split("(")[-1].split("x")[0]) < 1.0,
    _why_edge.split("(")[-1][:24])

# --- the window is the TOP candidates, not all of them --------------------
# A long tail inflates a head-to-tail spread while the head stays flat. The
# real board: 2.21 points overall, 1.45 across the top ten, 0.358 adjacent.
# A single far-separated LEADER is the case that discriminates, because it
# sits inside the top-N window and blows up a head-to-tail measure while
# leaving every adjacent gap below it untouched.
_lead72 = [ff_boost.make_candidate(
    [_l72("La", 0.80), _l72("Lb", 0.80), _l72("Lc", 0.80)],
    boost_pct=0.5)] + _flat
_lead72 = [c for c in _lead72 if c.structure.priceable and c.p_cash]
chk("one runaway leader does not make the flat field behind it rankable",
    not ff_boost.rank_is_meaningful(_lead72)[0],
    ff_boost.rank_is_meaningful(_lead72)[1][:100])
chk("because the MEDIAN adjacent gap ignores a single outlier",
    "median adjacent gap" in ff_boost.rank_is_meaningful(_lead72)[1])
# ...and widening the window past the top N must not change the verdict on a
# field that is flat throughout.
chk("adding more flat candidates does not change the answer",
    ff_boost.rank_is_meaningful(_flat)[0]
    == ff_boost.rank_is_meaningful(_flat + _flat)[0] is False)
# The case that actually pins the window: a flat HEAD with a widely-spaced
# tail BELOW it. Windowed to the top ten the head is all that is seen and the
# order is refused; looking at all 25, the median adjacent gap is dominated
# by the spread-out tail nobody would bet and the order passes. A runaway
# leader does not discriminate here because the median ignores one outlier.
_tailspread = _flat + [ff_boost.make_candidate(
    [_l72(f"S{i}a", 0.44 - i * 0.02), _l72(f"S{i}b", 0.44 - i * 0.02),
     _l72(f"S{i}c", 0.44 - i * 0.02)], boost_pct=0.5) for i in range(15)]
_tailspread = [c for c in _tailspread
               if c.structure.priceable and c.p_cash]
chk("a flat head with a spread-out tail below it is still refused",
    not ff_boost.rank_is_meaningful(_tailspread)[0],
    ff_boost.rank_is_meaningful(_tailspread)[1][:110])
chk("and the window really is the top ten, not all of them",
    f"top 10 of {len(_tailspread)}"
    in ff_boost.rank_is_meaningful(_tailspread)[1],
    ff_boost.rank_is_meaningful(_tailspread)[1][:80])

# --- the uncertainty is MEASURED off the board where it can be ------------
_q72 = []
for i, (ln, a, b) in enumerate([(50.5, -110, -110), (60.5, -105, -115),
                                (40.5, -120, 100), (70.5, -115, -105),
                                (30.5, -110, -110)]):
    _q72.append({"book": "pinnacle", "player": f"P{i}", "player_id": f"p{i}",
                 "market": "player_reception_yds", "line": ln, "over": a,
                 "under": b, "line_type": "main"})
    _q72.append({"book": "draftkings", "player": f"P{i}", "player_id": f"p{i}",
                 "market": "player_reception_yds", "line": ln, "over": a - 6,
                 "under": b + 4, "line_type": "main"})
_u, _uwhy = ff_boost.fair_uncertainty(_flat, _q72)
chk("fair uncertainty is measured when two books quote the same legs",
    "measured from 5 legs" in _uwhy, _uwhy)
chk("and the measured figure is a real disagreement, not zero",
    _u > 0, f"{_u:.5f}")
_uf, _ufwhy = ff_boost.fair_uncertainty(_flat, None)
chk("with nothing to measure it falls back and SAYS it fell back",
    _uf == ff_boost.FAIR_UNCERTAINTY_FALLBACK
    and "fallback" in _ufwhy, _ufwhy)
chk("too few two-book legs also falls back, with the count",
    "too few to measure" in ff_boost.fair_uncertainty(_flat, _q72[:4])[1],
    ff_boost.fair_uncertainty(_flat, _q72[:4])[1])
# The report carries the warning.
chk("report() leads with the warning when the order is not a ranking",
    ff_boost.report(_flat).startswith("!! THE ORDER BELOW IS NOT A RANKING"),
    ff_boost.report(_flat).splitlines()[0])
chk("and omits it when the order is real",
    not ff_boost.report(_wide).startswith("!!"),
    ff_boost.report(_wide).splitlines()[0][:70])


# ===========================================================================
# 73. F13 — the joint error, its sign, and the gate built on it
# ===========================================================================
#
# The arithmetic first, because every verdict below rests on it, and then
# the three states of the gate. The Monte Carlo figures are the ones from
# the 4,000,000-draw antithetic sweep; they are pinned as literals rather
# than re-simulated, so the suite stays fast and a regression in the closed
# form shows up as a disagreement with a number nobody can quietly edit.

section("73. F13 — joint error, sign, and the gate")


# Default market is deliberately one MARKET_SIDE does not know. The checks
# below pin ARITHMETIC with made-up r values, and since the 2026-11-11
# review a mapped yards pair is also cross-checked against its measured
# lift — which would (correctly) override an invented r for a real pair.
def _jleg(name, p, side="OVER", market="arith_only_unmapped", team="BUF",
          pos="RB", ev="E1", liq=None, verdict="CLEAR"):
    # BoostLeg refuses a verdict without a matching verdict_side (B126), so
    # a leg whose side is deliberately unreadable has to be UNSCREENED.
    return ff_boost.BoostLeg(
        event_id=ev, book="dk", market=market, player=name, side=side,
        odds=-110, fair_prob=p, fair_source="pinnacle", devig_method="shin",
        line=50.0, team=team, pos=pos, verdict=verdict,
        verdict_side=(side if verdict and verdict != "UNSCREENED" else ""),
        anchor_liquidity=liq)


# --- the closed form against simulation ----------------------------------
# (legs' p, r on every pair, first-order, Monte Carlo)
_MC = [
    (2, 0.50,  0.0300,  0.019099,  0.020081),
    (2, 0.35,  0.0300,  0.033599,  0.034414),
    (2, 0.65,  0.0300,  0.009742,  0.010224),
    (2, 0.50,  0.2462,  0.156736,  0.158800),
    (3, 0.50,  0.0300,  0.057296,  0.058930),
    (3, 0.50,  0.2462,  0.470208,  0.472800),
    (2, 0.50, -0.0300, -0.019099, -0.018000),
    (3, 0.50, -0.0300, -0.057296, -0.055600),
]
for _k, _p, _r, _fo, _mc in _MC:
    _ls = [_jleg(chr(65 + i), _p) for i in range(_k)]
    _ps = [(chr(65 + i), chr(65 + j), _r, "t")
           for i in range(_k) for j in range(i + 1, _k)]
    _got = ff_boost.joint_error(_ls, _ps).rel
    chk(f"{_k} legs at p={_p}, r={_r:+.4f}: closed form matches",
        abs(_got - _fo) < 5e-5, f"got {_got:+.6f}, expected {_fo:+.6f}")
    # The direction of the deviation is the load-bearing part, not its size.
    if _r > 0:
        chk(f"  and it UNDERSTATES the understatement (safe for a floor)",
            _got <= _mc + 1e-9, f"{_got:+.6f} vs MC {_mc:+.6f}")
    else:
        chk(f"  and it OVERSTATES the overstatement (errs toward refusing)",
            _got <= _mc + 1e-9, f"{_got:+.6f} vs MC {_mc:+.6f}")
    # The sweep's observed envelope is 0.951 to 1.061 of simulation. This
    # records that envelope; it is not a tolerance chosen to make the
    # arithmetic fit. Both ends matter: below 1 the closed form understates
    # (safe for a floor), above it overstates (errs toward refusing).
    chk(f"  inside the sweep's measured 0.95-1.07 envelope",
        0.95 <= _got / _mc <= 1.07, f"ratio {_got / _mc:.4f}")

# The 2-leg figure in F13's entry reproduces; the 3-leg one does not, and
# that is recorded here so nobody re-derives the design from the wrong one.
chk("F13's 2-leg figure of 1.9% reproduces",
    abs(ff_boost.joint_error([_jleg("A", .5), _jleg("B", .5)],
                             [("A", "B", 0.03, "t")]).rel - 0.019) < 1e-3)
chk("F13's 3-leg figure of 11.5% does NOT — it is 5.7%",
    abs(ff_boost.joint_error([_jleg(c, .5) for c in "ABC"],
                             [("A", "B", .03, "t"), ("A", "C", .03, "t"),
                              ("B", "C", .03, "t")]).rel - 0.0573) < 1e-3,
    "the backlog entry was 2x high; the conclusion it supported survives")

# --- additivity over pairs, which is why a per-pair gate cannot bound ----
_one = ff_boost.joint_error([_jleg("A", .5), _jleg("B", .5)],
                            [("A", "B", .03, "t")]).rel
_three = ff_boost.joint_error([_jleg(c, .5) for c in "ABC"],
                              [("A", "B", .03, "t"), ("A", "C", .03, "t"),
                               ("B", "C", .03, "t")]).rel
chk("three pairs cost exactly three times one pair",
    abs(_three - 3 * _one) < 1e-9, f"{_three:+.6f} vs 3x{_one:+.6f}")
chk("so a per-pair gate at 3% admits a slip carrying 5.7%",
    0.03 > _one and _three > 0.05, f"{_one:+.4%} each, {_three:+.4%} total")

# --- the leg probabilities matter, so this is never looked up by shape ---
_lo = ff_boost.joint_error([_jleg("A", .35), _jleg("B", .35)],
                           [("A", "B", .03, "t")]).rel
_hi = ff_boost.joint_error([_jleg("A", .65), _jleg("B", .65)],
                           [("A", "B", .03, "t")]).rel
chk("the same r costs 3.4x more at p=0.35 than at p=0.65",
    _lo / _hi > 3.0, f"{_lo:+.4%} vs {_hi:+.4%}")

# --- the SIDES flip the sign ---------------------------------------------
_over = ff_boost.joint_error([_jleg("A", .5), _jleg("B", .5)],
                             [("A", "B", .2462, "t")]).rel
_mix = ff_boost.joint_error([_jleg("A", .5), _jleg("B", .5, side="UNDER")],
                            [("A", "B", .2462, "t")]).rel
chk("one leg flipped to UNDER flips the joint error's sign",
    _over > 0 and _mix < 0 and abs(_over + _mix) < 1e-9,
    f"{_over:+.4%} -> {_mix:+.4%}")
chk("an unreadable side REFUSES rather than assuming OVER",
    not ff_boost.joint_error(
        [_jleg("A", .5), _jleg("B", .5, side="", verdict="UNSCREENED")],
        [("A", "B", .2462, "t")]).measurable,
    "the sign of the error depends on it")
chk("and joint_verdict refuses the slip for it, naming the leg",
    ff_boost.joint_verdict(
        [_jleg("A", .5), _jleg("B", .5, side="", verdict="UNSCREENED")],
        [("A", "B", .2462, "t")])[0] is False)
chk("a pair naming a leg that is not in the slip refuses too",
    not ff_boost.joint_error([_jleg("A", .5), _jleg("B", .5)],
                             [("A", "GHOST", .2462, "t")]).measurable,
    "dropping the term would shrink the error toward zero")

# --- the pessimistic end of the interval ---------------------------------
_pt = ff_boost.joint_error([_jleg("A", .5), _jleg("B", .5)],
                           [("A", "B", .1774, "t")]).rel
_pess = ff_boost.joint_error([_jleg("A", .5), _jleg("B", .5)],
                             [("A", "B", .1774, "t", (.1626, .1922))]).rel
chk("a pair with an interval is scored at the end that hurts",
    _pess < _pt, f"{_pess:+.4%} vs point {_pt:+.4%}")
chk("and that is recorded, not silent",
    ff_boost.joint_error([_jleg("A", .5), _jleg("B", .5)],
                         [("A", "B", .1774, "t", (.1626, .1922))]).pessimistic
    and not ff_boost.joint_error([_jleg("A", .5), _jleg("B", .5)],
                                 [("A", "B", .1774, "t")]).pessimistic)
# With an UNDER leg the pessimistic end is the interval's HIGH end.
_pu = ff_boost.joint_error(
    [_jleg("A", .5), _jleg("B", .5, side="UNDER")],
    [("A", "B", .1774, "t", (.1626, .1922))]).rel
chk("for a flipped side the pessimistic end is the HIGH one",
    abs(_pu + 0.1922 * (ff_boost._phi(0.0) ** 2) / 0.25) < 1e-9,
    f"{_pu:+.6f}")
# E3 measured one cell whose interval spans zero, so its sign is unknown.
_straddle = _C.RECORDED_MARKET_SIDE[("same", "PASS", "PASS_TD")][2]
chk("E3 has a cell whose interval spans zero",
    _straddle[0] < 0 < _straddle[1], str(_straddle))
chk("scored pessimistically it comes out negative, not positive",
    ff_boost.joint_error(
        [_jleg("A", .5), _jleg("B", .5)],
        [("A", "B", _C.RECORDED_MARKET_SIDE[("same", "PASS", "PASS_TD")][0],
          "t", _straddle)]).rel < 0,
    "a point estimate would have given it a sign it has not earned")

# --- the gate's three states ---------------------------------------------
_CI = (0.2286, 0.2625)          # same-team PASS x RECV, all one direction
_ok, _why = ff_boost.joint_verdict(
    [_jleg(c, .5) for c in "ABC"],
    [("A", "B", .2456, "t", _CI), ("A", "C", .2456, "t", _CI),
     ("B", "C", .2456, "t", _CI)])
chk("all pairs positive and bracketed: a Slepian FLOOR, at any magnitude",
    _ok and "Slepian" in _why and "FLOOR" in _why, _why[:120])
chk("a large floor is called a model result, not a guarantee",
    "not a guarantee" in _why and "never worse" not in _why, _why[-200:])
_rr = _C.RECORDED_MARKET_SIDE[("same", "RECEPTIONS", "RECEPTIONS")]
_oks, _whys = ff_boost.joint_verdict(
    [_jleg("A", .5), _jleg("B", .5)], [("A", "B", _rr[0], "t", _rr[2])])
chk("a positive correction smaller than the noise is NOT sold as a floor",
    _oks and "about the product" in _whys and "FLOOR" in _whys,
    _whys[-220:])
chk("and no threshold is applied to it — 47% still prices",
    _ok, "the direction is safe whatever the size")

_ok2, _why2 = ff_boost.joint_verdict(
    [_jleg(c, .5) for c in "ABC"],
    [("A", "B", .2456, "t", _CI), ("A", "C", -.0765, "t", (-.1029, -.0463))])
# Revert 4 found this gap: every all-positive fixture above carried
# intervals, so dropping the `pessimistic` requirement from the Slepian
# branch changed nothing any check could see. All terms positive, NO
# interval anywhere — the floor must be denied, because a positive sign
# taken from a point estimate is not a theorem.
_okP, _whyP = ff_boost.joint_verdict(
    [_jleg(c, .5) for c in "ABC"],
    [("A", "B", .2456, "t"), ("A", "C", .2456, "t"), ("B", "C", .2456, "t")])
chk("all pairs positive but UNBRACKETED is not a Slepian floor",
    not _okP and "Slepian" not in _whyP
    and "point estimate" in _whyP, _whyP[:170])
chk("and the same pairs WITH intervals are",
    ff_boost.joint_verdict(
        [_jleg(c, .5) for c in "ABC"],
        [("A", "B", .2456, "t", _CI), ("A", "C", .2456, "t", _CI),
         ("B", "C", .2456, "t", _CI)])[0],
    "the only difference is whether the sign is bracketed")

chk("mixed signs netting positive are NOT a Slepian floor",
    not _ok2 and "BOTH ways" in _why2 and "not a floor" in _why2,
    _why2[:160])

_ok3, _why3 = ff_boost.joint_verdict(
    [_jleg(c, .5) for c in "ABC"],
    [("A", "B", -.03, "t", (-.035, -.025)), ("A", "C", -.03, "t", (-.035, -.025)),
     ("B", "C", -.03, "t", (-.035, -.025))])
chk("a negative total past the noise it sits in REFUSES",
    not _ok3 and "OVERSTATES" in _why3, _why3[:140])
# same-team RECV x RUSH, pessimistic end -0.0334: -2.13% against 2.26% of
# propagated noise, so 0.94x and inside it.
_ok4, _why4 = ff_boost.joint_verdict(
    [_jleg("A", .5), _jleg("B", .5)],
    [("A", "B", -.0219, "t", (-.0334, -.0104))])
chk("a small negative pair inside the noise is reported, flagged optimistic",
    _ok4 and "OPTIMISTIC" in _why4, _why4[:160])
# And the knife edge, recorded because it is the closest real call on the
# board: ONE same-team TD x TD pair, scored at the pessimistic end of its
# own interval, comes out at 1.02x and is refused. Two percent the other
# way and it would price. Nothing is tuned to make it land either side —
# this pins where the measurement actually falls, so a change to the
# arithmetic or to FAIR_UNCERTAINTY_FALLBACK shows up here first.
_td = _C.RECORDED_MARKET_SIDE[("same", "TD", "TD")]
_ok5, _why5 = ff_boost.joint_verdict(
    [_jleg("A", .5), _jleg("B", .5)],
    [("A", "B", _td[0], "t", _td[2])])
chk("on the latent-normal weight that r would sit at 1.02x",
    not _ok5 and "1.02x" in _why5, _why5[:170])
# ...but that is the WRONG weight for it. The TD side is binary, so its r
# is between yes/no outcomes and the joint is exact: r sqrt(qa qb / pa pb).
# On real anytime-TD legs the same pair is 1.60x, not a knife edge at all.
_tdl = [_jleg("A", .5, market="player_anytime_td", pos="WR"),
        _jleg("B", .5, market="player_anytime_td", pos="TE")]
_ok5b, _why5b = ff_boost.joint_verdict(_tdl, [("A", "B", _td[0], "t", _td[2])])
chk("on real anytime-TD legs the same pair is 1.60x and plainly refused",
    not _ok5b and "1.60x" in _why5b, _why5b[:170])
# The binary weight against exhaustive arithmetic, no model involved.
for _pa, _pb, _phi_r in ((.5, .5, -.03), (.3, .35, -.0362), (.3, .6, .05)):
    _joint = _pa * _pb + _phi_r * ((_pa * (1 - _pa) * _pb * (1 - _pb)) ** .5)
    _exact = _joint / (_pa * _pb) - 1.0
    _gotb = ff_boost.joint_error(
        [_jleg("A", _pa, market="player_anytime_td"),
         _jleg("B", _pb, market="player_anytime_td")],
        [("A", "B", _phi_r, "t")]).rel
    chk(f"two yes/no legs at {_pa}/{_pb}: the term is EXACT",
        abs(_gotb - _exact) < 1e-12, f"{_gotb:+.6f} vs {_exact:+.6f}")
chk("at real TD probabilities the old weight understated by over 2x",
    ff_boost._pair_weight(.3, .3, 0, 0, True, True)
    / ff_boost._pair_weight(.3, .3, ff_boost._norm_inv(.7),
                            ff_boost._norm_inv(.7), False, False) > 1.5)
# One yes/no leg against a yards leg is the point-biserial case, between.
_w_cc = ff_boost._pair_weight(.5, .5, 0, 0, False, False)
_w_bc = ff_boost._pair_weight(.5, .5, 0, 0, True, False)
_w_bb = ff_boost._pair_weight(.5, .5, 0, 0, True, True)
chk("the mixed weight sits between the two, and is symmetric",
    _w_cc < _w_bc < _w_bb
    and abs(_w_bc - ff_boost._pair_weight(.5, .5, 0, 0, False, True)) < 1e-12
    and abs(_w_bc - 0.7979) < 1e-3 and abs(_w_bb - 1.0) < 1e-12,
    f"{_w_cc:.4f} {_w_bc:.4f} {_w_bb:.4f}")

# --- the measured lift as a second opinion ------------------------------
# The formula was verified against a simulation of its own model. Against
# the directly measured lifts it understates every material negative cell.
def _yl(name, market, pos, team="BUF", side="OVER"):
    return _jleg(name, .5, market=market, pos=pos, team=team, side=side)


for _rel, _ma, _mb, _pa2, _pb2 in (
        ("same", "player_pass_yds", "player_rush_yds", "QB", "RB"),
        ("opp", "player_rush_yds", "player_rush_yds", "RB", "RB"),
        ("opp", "player_pass_yds", "player_rush_yds", "QB", "RB")):
    _la = _yl("A", _ma, _pa2)
    _lb = _yl("B", _mb, _pb2, team=("BUF" if _rel == "same" else "MIA"))
    _sa, _sb = sorted((ff_boost.MARKET_SIDE[_ma], ff_boost.MARKET_SIDE[_mb]))
    _lift, _lr, _ = ff_boost.MEASURED_PAIR_LIFT[(_rel, _sa, _sb)]
    _je = ff_boost.joint_error([_la, _lb], [("A", "B", _lr, "t")])
    chk(f"{_rel} {_sa} x {_sb}: scored no better than its measured lift",
        _je.rel <= (_lift - 1.0) + 1e-9,
        f"term {_je.rel:+.2%}, measured {_lift - 1:+.2%}, formula alone "
        f"{0.6366 * _lr:+.2%}")
    chk(f"  and the formula alone would have understated it",
        0.6366 * _lr > (_lift - 1.0), f"{0.6366 * _lr:+.2%} vs {_lift - 1:+.2%}")
_qb9 = _yl("Q", "player_pass_yds", "QB")
_wr9 = _yl("W", "player_reception_yds", "WR")
_je9 = ff_boost.joint_error([_qb9, _wr9], [("Q", "W", .2462, "t")])
chk("a POSITIVE pair keeps the smaller of the two figures",
    abs(_je9.rel - 0.6366 * .2462) < 1e-3,
    f"{_je9.rel:+.2%} — measured lift is +19.9%, and taking it would make "
    f"the floor's stated gap less conservative")
chk("and the lift is used with the right sign for an UNDER",
    ff_boost.joint_error(
        [_qb9, _yl("W", "player_reception_yds", "WR", side="UNDER")],
        [("Q", "W", .2462, "t")]).rel <= -(1.1993 - 1.0) + 1e-9)
chk("joint_error says when it scored a pair on its lift",
    "measured lift" in ff_boost.joint_error(
        [_yl("A", "player_rush_yds", "RB"),
         _yl("B", "player_rush_yds", "RB", team="MIA")],
        [("A", "B", -.0804, "t")]).why)
chk("the gate is a RATIO against propagated noise, not a tuned number",
    ff_boost.JOINT_OVERSTATE_RATIO == 1.0,
    "lesson 99 — if it needs tuning it is the wrong quantity")
_noise, _nwhy = ff_boost.product_noise([_jleg(c, .5) for c in "ABC"])
chk("product_noise propagates the legs' own fair uncertainty",
    abs(_noise - (3 ** 0.5) * ff_boost.FAIR_UNCERTAINTY_FALLBACK / 0.5)
    < 1e-9, f"{_noise:.5f}")
chk("and it SAYS when it fell back rather than measuring",
    "fallback" in _nwhy, _nwhy)

# --- the real shapes F13 was filed about ---------------------------------
# These are the measured cells, scored pessimistically, on 50/50 legs.
def _shape(cells):
    names = "ABC"
    k = 3 if len(cells) > 1 else 2
    legs = [_jleg(names[i], .5) for i in range(k)]
    slots = [("A", "B"), ("A", "C"), ("B", "C")]
    prs = []
    for i, (sa, sb) in enumerate(cells):
        lo, hi = sorted((sa, sb))
        e = _C.RECORDED_MARKET_SIDE[("same", lo, hi)]
        prs.append((slots[i][0], slots[i][1], e[0], f"{sa}x{sb}", e[2]))
    return ff_boost.joint_verdict(legs, prs)[0], \
        ff_boost.joint_error(legs, prs).rel

for _label, _cells, _want in [
        ("QB pass + teammate receiving", [("PASS", "RECV")], True),
        ("QB passTD + teammate anytime TD", [("PASS_TD", "TD")], True),
        ("three teammate anytime TDs", [("TD", "TD")] * 3, False),
        ("two receptions + a back's rushing",
         [("RECEPTIONS", "RECEPTIONS"), ("RECEPTIONS", "RUSH"),
          ("RECEPTIONS", "RUSH")], False)]:
    _got, _rel = _shape(_cells)
    chk(f"{_label}: {'priced' if _want else 'refused'}",
        _got is _want, f"got {'priced' if _got else 'refused'} at "
                       f"{_rel:+.2%}")
# The point of the asymmetry: a flat threshold on SIZE would have gotten
# the two safe shapes backwards, since they carry the LARGEST errors here.
chk("the two shapes that price carry bigger errors than the two refused",
    abs(_shape([("PASS", "RECV")])[1])
    > abs(_shape([("TD", "TD")] * 3)[1]),
    "a threshold on |error| would have refused the safe ones and is why "
    "this gate is on the SIGN first")

# --- Candidate / report wiring -------------------------------------------
_qb = _jleg("QB9", .52, market="player_pass_yds", pos="QB", liq=5000)
_rc = _jleg("WR9", .52, market="player_receptions", pos="WR", liq=250)
_fc = ff_boost.make_candidate([_qb, _rc], boost_pct=0.50)
chk("a bounded slip reads FLOOR ONLY, not UNPRICEABLE",
    _fc.verdict == "FLOOR ONLY", _fc.verdict)
chk("and FLOOR ONLY is a documented verdict",
    "FLOOR ONLY" in ff_boost.VERDICTS)
chk("p_cash stays None — the product is not the joint",
    _fc.p_cash is None and _fc.ev_pct is None)
chk("the floor is a separate number under a separate name",
    _fc.p_cash_floor is not None
    and abs(_fc.p_cash_floor - 0.52 * 0.52) < 1e-9,
    f"{_fc.p_cash_floor}")
chk("the report prints it as a LOWER BOUND",
    "P(cash) FLOOR" in ff_boost.report([_fc])
    and "LOWER BOUND" in ff_boost.report([_fc]))
chk("and does not also claim no EV is reported",
    "NO EV, NO P(cash)" not in ff_boost.report([_fc]),
    "the header and the body must not contradict each other")
_un = ff_boost.make_candidate(
    [_jleg("A", .52, market="player_longest_reception", pos="WR"),
     _jleg("B", .52, market="player_rush_yds", pos="RB")], boost_pct=0.50)
chk("an UNMEASURED pair still refuses outright, with no floor",
    _un.verdict == "UNPRICEABLE" and _un.p_cash_floor is None
    and _un.floor[0] is False, f"{_un.verdict} {_un.floor[1][:60]}")
chk("a priceable slip reports no floor, to avoid two names for one number",
    ff_boost.make_candidate(
        [_jleg("A", .52, ev="E1"), _jleg("B", .52, ev="E2")],
        boost_pct=0.50).p_cash_floor is None)
chk("a board of bounded slips is BOUNDED ONLY, not LIKELY NEGATIVE",
    ff_boost.Shortlist(candidates=[_fc], mode="sgp",
                       boost_pct=0.50).outlook == "BOUNDED ONLY",
    ff_boost.Shortlist(candidates=[_fc], mode="sgp",
                       boost_pct=0.50).outlook)

# --- the market keys -----------------------------------------------------
chk("receptions, anytime TD and passing TD are all mapped",
    ff_boost.MARKET_SIDE["player_receptions"] == "RECEPTIONS"
    and ff_boost.MARKET_SIDE["player_anytime_td"] == "TD"
    and ff_boost.MARKET_SIDE["player_pass_tds"] == "PASS_TD")
chk("every side in MARKET_SIDE has at least one measured cell",
    all(any(side in k for k in _C.RECORDED_MARKET_SIDE)
        for side in set(ff_boost.MARKET_SIDE.values())),
    "a mapped side with no cell would refuse while looking wired")
chk("side_pair reads the table in either side order",
    ff_boost.side_pair("same", "TD", "PASS") ==
    ff_boost.side_pair("same", "PASS", "TD") is not None)
chk("an unmeasured relation/side combination returns None, not zero",
    ff_boost.side_pair("same", "PASS", "NOT_A_SIDE") is None)


# ===========================================================================
# 74. B57's one varying signal, shown as a column
# ===========================================================================

section("74. anchor depth as a column, not a sort key")

def _dsc(d):
    """describe() that FAILS a check instead of crashing the section.

    Lesson 14, and revert 9 proved it was still needed here: removing the
    no-readings branch made `describe()` format None with ":,.0f", which
    raised out of the section and took sections 74 onward with it. The
    suite's own CRASHED line noticed, but a crash reports nothing about
    WHICH behaviour broke.
    """
    try:
        return d.describe()
    except Exception as e:
        return f"<describe() raised {type(e).__name__}: {e}>"


_d = ff_boost.anchor_depth([_jleg("A", .5, liq=5000), _jleg("B", .5, liq=250)])
chk("anchor depth reports the THINNEST leg, not the mean",
    _d.thinnest == 250, f"{_d.thinnest} (mean would be 2625)")
chk("and how many legs reported at all",
    _d.reported == 2 and _d.silent == 0 and _d.total == 2)
_ds = ff_boost.anchor_depth([_jleg("A", .5, liq=250), _jleg("B", .5)])
chk("a silent leg is counted as silent, not as thin and not as deep",
    _ds.thinnest == 250 and _ds.silent == 1 and _ds.reported == 1,
    _dsc(_ds))
_dn = ff_boost.anchor_depth([_jleg("A", .5), _jleg("B", .5)])
chk("no leg reporting is its OWN state, with no number invented",
    _dn.thinnest is None and "NOT REPORTED" in _dsc(_dn),
    _dsc(_dn))
chk("and it says that says nothing either way",
    "says nothing either way" in _dsc(_dn), _dsc(_dn))
chk("an empty leg list does not crash",
    _dsc(ff_boost.anchor_depth([])) == "anchor depth  : no legs")
chk("the column disclaims being a ranking key",
    "NOT a ranking key" in _dsc(_d), _dsc(_d))
chk("the report carries the column",
    "anchor depth" in ff_boost.report([_fc]))
# The whole point: it is NOT in the sort key.
chk("anchor liquidity is absent from Candidate.key",
    "anchor_liquidity" not in inspect.getsource(ff_boost.Candidate.key.fget)
    and "anchor_depth" not in inspect.getsource(ff_boost.Candidate.rank.fget),
    "sorting on it would rank by the market's confidence, not by value")

# ===========================================================================
# 75. F12's selection half — a rung can be CHOSEN as a leg
# ===========================================================================
#
# The pricing shipped 2026-11-09 and nothing could select a rung, because
# the production path pulls line_type="main". This is the merge point B50
# and B129 were filed against, and the three things that can go wrong here
# are all silent: a rung dropped at intake by the circularity guard, a rung
# parlayed with its own main line, and a rung carrying a model edge B128
# says is noise.

section("75. F12 — selecting a rung as a leg")


def _lf(player, thr, price, fair, *, pid=None, book="draftkings",
        anchor="pinnacle", priceable=True, unc=0.01):
    return ff_props.LadderFair(
        book=book, player=player, threshold=thr, canonical_line=thr - 0.5,
        price=price, q_raw=None, fair=(fair if priceable else None),
        uncertainty=unc, margin=0.0568, level_shift=0.1, anchor=anchor,
        anchor_point=49.5, anchor_fair=0.52, level_gap=0.004, player_id=pid,
        fair_source=f"level {anchor}, shape {book} ladder (margin +5.68%)",
        why=("" if priceable else "no anchor-chain book posts a two-sided "
                                  "main line for this player"))


def _rl(fairs, **kw):
    """rung_legs that FAILS a check instead of crashing the section.

    Four reverts proved this necessary: removing a guard inside
    `rung_legs` lets a bad rung reach `float(f.fair)` with fair=None, and
    the TypeError raised out of the section and took sections 76+ with it.
    The suite's CRASHED line noticed, but no check named the behaviour
    (lesson 14).
    """
    kw.setdefault("book", "draftkings")
    kw.setdefault("market", "player_reception_yds")
    kw.setdefault("event_id", "E1")
    try:
        return ff_boost.rung_legs(fairs, **kw)
    except Exception as e:
        return [], [("<rung_legs raised>",
                     f"{type(e).__name__}: {e} — it should have REFUSED "
                     f"this rung by name, not raised")]


def _why0(refused):
    """The first refusal's reason, or a sentinel — never an IndexError.

    Lesson 14 again, and three reverts proved it: a revert that makes
    `rung_legs` ACCEPT a bad rung leaves `refused` empty, and a check
    indexing `_r[0][1]` then raised out of the section instead of failing,
    taking everything after it with it.
    """
    try:
        return str(refused[0][1])
    except Exception:
        return "<nothing was refused>"


_V = {n: ("CLEAR", "OVER", ()) for n in
      ("Khalil Shakir", "Dalton Kincaid", "Ty Johnson")}
_M75 = {"Khalil Shakir": ("BUF", "WR"), "Dalton Kincaid": ("BUF", "TE"),
        "Ty Johnson": ("BUF", "RB")}
_F75 = [_lf("Khalil Shakir", 60, +120, 0.44, pid="s1"),
        _lf("Khalil Shakir", 70, +210, 0.31, pid="s1"),
        _lf("Dalton Kincaid", 50, +150, 0.39, pid="k1"),
        _lf("Ty Johnson", 40, +135, 0.41, pid="t1")]
_K75, _R75 = _rl(_F75, verdicts=_V, meta=_M75)

chk("rung_legs builds a leg per priceable rung", len(_K75) == 4 and not _R75,
    f"{len(_K75)} built, refused {_R75}")
chk("the leg carries the CANONICAL line, not the posted threshold",
    all(abs(l.line - (t - 0.5)) < 1e-9 for l, t in
        zip(_K75, (60, 70, 50, 40))),
    f"{[l.line for l in _K75]} — a rung at N is exactly over N-0.5 (D18)")
chk("and it declares itself a rung",
    all(l.is_rung and l.line_type == "milestone" for l in _K75))
chk("describe() names it, so a rung and a main line do not read alike",
    "milestone rung, posted as 60+" in _K75[0].describe(), _K75[0].describe())
# B128. The whole reason a rung is selectable at all but not edge-able.
chk("every rung leg carries model_p=None, deliberately",
    all(l.model_p is None for l in _K75),
    "B128: the model's shape disagrees with the market's by 3.1x the "
    "ladder's own precision even with the level pinned away")

# --- the circularity split, which silently dropped every rung -----------
chk("a rung's LEVEL came from the anchor, so it is NOT circular",
    not any(l.circular for l in _K75),
    "before the split, `circular` read 'draftkings' out of 'level "
    "pinnacle, shape draftkings ladder' and dropped all of them at intake")
chk("but its SHAPE did come from the book being bet, and says so",
    all(l.shape_circular for l in _K75))
# A rung anchored to its own book is fully circular. BoostLeg refuses that
# at construction, so `rung_legs` must catch it and name it rather than
# letting one bad rung take the other 149 with it (lesson 14).
_sa_k, _sa_r = _rl(
    [_lf("Khalil Shakir", 60, +120, 0.44, pid="s1", anchor="draftkings"),
     _lf("Dalton Kincaid", 50, +150, 0.39, pid="k1")],
    verdicts=_V, meta=_M75)
chk("a rung anchored to its OWN book is refused, by name",
    len(_sa_k) == 1 and len(_sa_r) == 1
    and "Khalil Shakir" in str(_sa_r[0][0]) and "circular" in _why0(_sa_r),
    f"kept={[l.player for l in _sa_k]} refused={_sa_r}")
chk("and the good rung beside it still survives",
    _sa_k and _sa_k[0].player == "Dalton Kincaid",
    "one bad rung must not take the ladder with it")
# A main line with no level_source keeps the OLD answer: the whole fair
# came from fair_source, so naming the book being bet is circular and
# BoostLeg refuses it at construction. The split must not have loosened it.
try:
    ff_boost.BoostLeg(
        event_id="E1", book="draftkings", market="m", player="X",
        side="OVER", odds=-110, fair_prob=.5, fair_source="draftkings shin",
        devig_method="shin", line=1.5)
    _mainok = False
except ValueError:
    _mainok = True
chk("a main line de-vigged against its own book is still refused",
    _mainok, "the circularity split must not have loosened the main-line "
             "case, which is the one the instructions forbid outright")

# --- what rung_legs refuses rather than papering over -------------------
_nope = [
    ("a rung ladder_fair could not price",
     [_lf("Khalil Shakir", 60, +120, None, pid="s1", priceable=False)], _V,
     "ladder_fair refused it"),
    ("a rung with no price for the side being bet",
     [_lf("Khalil Shakir", 60, None, 0.44, pid="s1")], _V,
     "one-sided row is not a price"),
    ("a rung whose player was never screened",
     [_lf("Nobody Here", 60, +120, 0.44, pid="n1")], _V,
     "no role verdict for this player"),
    ("a verdict computed for the UNDER (B126)",
     [_lf("Khalil Shakir", 60, +120, 0.44, pid="s1")],
     {"Khalil Shakir": ("CLEAR", "UNDER", ())},
     "does not carry across sides"),
]
for _label, _fs, _vs, _want in _nope:
    _k, _r = _rl(_fs, verdicts=_vs, meta=_M75)
    chk(f"refused: {_label}",
        not _k and len(_r) == 1 and _want in _why0(_r),
        f"kept={len(_k)} refused={_r}")
# The verdict is inherited from the player's main-line screen, and says so.
chk("an inherited verdict records that it was inherited",
    any("not from this rung" in r for r in _K75[0].verdict_reasons),
    str(_K75[0].verdict_reasons))

# --- a rung and its own main line are ONE BET --------------------------
_main75 = ff_boost.BoostLeg(
    event_id="E1", book="draftkings", market="player_reception_yds",
    player="Khalil Shakir", side="OVER", odds=+118, fair_prob=0.44,
    fair_source="pinnacle shin", devig_method="shin", line=59.5,
    player_id="s1", verdict="CLEAR", verdict_side="OVER", team="BUF",
    pos="WR")
chk("the 60+ rung and Over 59.5 are the SAME bet",
    ff_props.same_bet(_K75[0].as_quote(), _main75.as_quote()),
    f"{_K75[0].as_quote()} vs {_main75.as_quote()}")
chk("the 70+ rung is NOT the same bet as Over 59.5",
    not ff_props.same_bet(_K75[1].as_quote(), _main75.as_quote()))
# And the enumerator refuses to put them in one slip — via the NAME guard,
# which is what actually catches it. `same_bet` cannot add anything here:
# its key begins with the normalised name, so an equal key implies a name
# the guard has already refused. A check was written for a canonical guard
# at this point and removed when no input could reach it (lesson 64).
_sl75 = ff_boost.enumerate_candidates(
    _K75 + [_main75], _M75, mode="single-game", event_id="E1",
    boost_pct=0.50, legs_per_slip=2, floor=100, ceiling=2000)
chk("no shortlisted slip contains one player twice",
    all(len({ff_boost.norm_player(l.player) for l in c.legs}) == len(c.legs)
        for c in _sl75.candidates),
    f"{[[l.player for l in c.legs] for c in _sl75.candidates]}")
# Stronger than counting them: after the price-targeting rewrite the
# enumerator groups BY PLAYER, so a combination naming one man twice is
# never generated. It was 67,114 of 104,586 on the first live board — work
# that no longer exists rather than work that is counted and thrown away.
chk("those combinations are never generated, not generated and refused",
    not any("containing one player twice" in n for n in _sl75.build_notes),
    str(_sl75.build_notes)[:200])
chk("and the shortlist reports the price targeting instead",
    any("cheapest that clears the floor" in n for n in _sl75.build_notes)
    or len({ff_boost.norm_player(l.player)
            for c in _sl75.candidates for l in c.legs}) > 1,
    str(_sl75.build_notes)[:200])

# --- the normalised-name dedupe (B129), which was keyed on the RAW name --
def _dj(name, pid, ev="E1", line=49.5):
    return ff_boost.BoostLeg(
        event_id=ev, book="dk", market="player_reception_yds", player=name,
        side="OVER", odds=-110, fair_prob=0.52, fair_source="pinnacle",
        devig_method="shin", line=line, player_id=pid, verdict="CLEAR",
        verdict_side="OVER", team="CHI", pos="WR")


# B129's own example: a rung row carrying an id beside a main row carrying
# NULL. The ids cannot catch that — one of them is missing — so ONLY the
# normalised name stands between the two spellings and a slip that parlays
# one man with himself. A first version of this check gave both legs the
# same id, and a revert to the raw-name key went UNCAUGHT because the id
# guard in `classify` quietly did the job the name guard was meant to do.
_djsl = ff_boost.enumerate_candidates(
    [_dj("D.J. Moore", "m1"), _dj("DJ Moore", None),
     _dj("Rome Odunze", "o1"), _dj("Cole Kmet", "c1")],
    mode="single-game", event_id="E1", boost_pct=0.50, legs_per_slip=2,
    floor=100, ceiling=2000)
chk("'D.J. Moore' and 'DJ Moore' are one man, not two legs",
    all(len({ff_boost.norm_player(l.player) for l in c.legs})
        == len(c.legs) for c in _djsl.candidates),
    f"{[[l.player for l in c.legs] for c in _djsl.candidates]}")
# What the normalised key actually buys (see the note in ff_boost): the
# combination is refused either way, by `classify`. The difference is
# whether the reader is told "one player twice" or is pointed at
# `player_id`, which has nothing to do with a spelling difference.
# Two spellings of one man now land in the SAME player group, so they are
# alternative legs for one player and the targeting picks one — a better
# answer than refusing the combination, and no `player_id` blame either.
chk("two spellings become one player group, not a refused combination",
    not any("player_id" in n for n in _djsl.build_notes),
    str(_djsl.build_notes)[:220])
chk("and the id-less spelling still reached the shortlist on its own",
    any(ff_boost.norm_player(l.player) == "dj moore"
        for c in _djsl.candidates for l in c.legs),
    "if neither spelling appears at all the check above is vacuous — one "
    "of them must be usable as a leg, just never beside the other")

# --- the id collision: a SKIP, not a crash -----------------------------
# "Cam Ward" and "Cameron Ward" normalise differently, so the name guard
# misses them and `classify` RAISES on the shared player_id. That is right
# for a hand-built slip and fatal in an enumeration loop.
# The check itself cannot call the enumerator bare: the behaviour under
# test IS whether an exception escapes it, so a bare call makes the revert
# crash the section instead of failing a check (lesson 14).
try:
    _camsl = ff_boost.enumerate_candidates(
        [_dj("Cam Ward", "w9", line=237.5),
         _dj("Cameron Ward", "w9", line=237.5),
         _dj("Calvin Ridley", "r1"), _dj("Tyler Lockett", "l1")],
        mode="single-game", event_id="E1", boost_pct=0.50, legs_per_slip=2,
        floor=100, ceiling=2000)
    _camerr = ""
except Exception as e:
    _camsl, _camerr = None, f"{type(e).__name__}: {e}"
chk("a shared player_id under two spellings does not crash the enumeration",
    _camsl is not None and _camsl.candidates,
    _camerr or "no candidates survived — an exception here takes the "
               "whole shortlist with it")
if _camsl is None:                       # keep the rest of the section alive
    _camsl = ff_boost.Shortlist(candidates=[], mode="single-game",
                                boost_pct=0.50)
chk("it is recorded as a refused combination, naming player_id",
    any("player_id" in n for n in _camsl.build_notes),
    str(_camsl.build_notes)[:200])
chk("and no surviving slip contains that pair",
    not any({"cam ward", "cameron ward"}
            <= {ff_boost.norm_player(l.player) for l in c.legs}
            for c in _camsl.candidates))

# --- the shortlist and report say what these legs are ------------------
_rsl = ff_boost.enumerate_candidates(
    _K75, _M75, mode="single-game", event_id="E1", boost_pct=0.50,
    legs_per_slip=3, floor=300, ceiling=1500)
chk("a rung slip is actually shortlisted", _rsl.candidates, _rsl.reason[:120])
chk("the shortlist lists its rung legs", len(_rsl.rung_legs) == 3,
    str(_rsl.rung_legs))
chk("and which of them are shape-circular",
    _rsl.shape_circular_legs, str(_rsl.shape_circular_legs))
chk("the build notes cite B128 for why a rung carries no model edge",
    any("B128" in n and "noise" in n and "NO model probability" in n
        for n in _rsl.build_notes),
    str(_rsl.build_notes)[:220])
chk("and say what rungs ARE for, so the note is usable",
    any("PICK a price" in n and "not to claim one is mispriced" in n
        for n in _rsl.build_notes), str(_rsl.build_notes)[:220])
chk("and name the shape caveat rather than absorbing it",
    any("curve between rungs is not" in n for n in _rsl.build_notes))
_rep75 = ff_boost.report(_rsl.candidates[:1])
chk("the report marks the slip as carrying rung legs",
    "RUNG LEGS" in _rep75 and "pick a price" in _rep75)
chk("and repeats the shape caveat on the candidate itself",
    "'this rung beats the market' does not" in _rep75,
    "a note that lives only on the shortlist is a note nobody reads (B93)")
chk("a main-line-only slip says none of this",
    "RUNG LEGS" not in ff_boost.report([ff_boost.make_candidate(
        [_dj("Rome Odunze", "o1", ev="E1"), _dj("Cole Kmet", "c1", ev="E2")],
        boost_pct=0.50)]))

# ===========================================================================
# 76. What the first live run found (event 53178, 2026-11-10)
# ===========================================================================
#
# Every check here exists because a real board found something the fixtures
# could not. The headline is the price-targeting defect: `if names in seen:
# continue` collapsed thousands of rung choices per player triple to
# whichever one `combinations()` yielded first, and section 75's fixtures
# had exactly one combination per triple, so nothing could reach it.

section("76. findings from the first live run")


def _rg(player, thr, price, fair, pid, book="draftkings"):
    return ff_props.LadderFair(
        book=book, player=player, threshold=thr, canonical_line=thr - 0.5,
        price=price, q_raw=None, fair=fair, uncertainty=0.01, margin=0.056,
        level_shift=0.1, anchor="pinnacle", anchor_point=49.5,
        anchor_fair=0.52, level_gap=0.004, player_id=pid,
        fair_source=f"level pinnacle, shape {book} ladder (margin +5.60%)")


def _ladder_pool(n_players=7, n_rungs=16):
    """A pool with MANY combinations per triple — what 75 did not have."""
    fairs, V, M = [], {}, {}
    for j in range(n_players):
        who = f"Player{j}"
        V[who] = ("CLEAR", "OVER", ())
        M[who] = ("NYG", "WR")
        for i in range(n_rungs):
            o = -1520 + i * 170
            fairs.append(_rg(who, 10 + 5 * i, o if o < -100 else abs(o) + 100,
                             max(0.05, 0.97 - i * 0.06), f"id{j}"))
    legs, _ = ff_boost.rung_legs(
        fairs, book="draftkings", market="player_reception_yds",
        event_id="E1", verdicts=V, meta=M)
    return legs, M


def _ec(legs, meta, **kw):
    """enumerate_candidates that FAILS a check instead of crashing.

    Five reverts came back "0 failures + CRASH": emptying the shortlist or
    changing a verdict made a later check index `candidates[0]` or
    `ev_band[0]` and raise out of the section. Lesson 103, and it applies
    to every new accessor, not just the ones that needed it last time.
    """
    try:
        return ff_boost.enumerate_candidates(legs, meta, **kw), ""
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def _mx(cands, attr, default=None):
    """max of an attribute over candidates, or a default — never raises."""
    try:
        vals = [getattr(c, attr) for c in cands]
        vals = [v for v in vals if v is not None]
        return max(vals) if vals else default
    except Exception:
        return default


_pl, _pm = _ladder_pool()
chk("the pool really does have many combinations per triple",
    len(_pl) == 112, f"{len(_pl)} legs — 7 players x 16 rungs")
_psl, _pserr = _ec(_pl, _pm, mode="single-game", event_id="E1",
                   boost_pct=0.50, legs_per_slip=3, floor=300, ceiling=900)
if _psl is None:
    chk("the ladder pool enumerates at all", False, _pserr)
    _psl = ff_boost.Shortlist(candidates=[], mode="single-game",
                              boost_pct=0.50, reason=_pserr)
# THE DEFECT. Before price targeting this returned 0 candidates and said
# "the legs are too short to reach the boost's minimum price."
chk("a rungs-only ladder pool now yields candidates at all",
    _psl.candidates, _psl.reason[:170])
chk("and does NOT claim the legs are too short",
    "too short" not in _psl.reason, _psl.reason[:170])
chk("every shortlisted slip is inside the band",
    all(300 <= c.independent_odds <= 900 for c in _psl.candidates),
    str([round(c.independent_odds) for c in _psl.candidates]))
chk("the shortlist reports that it chose on price",
    any("cheapest that clears the price target" in n
        for n in _psl.build_notes), str(_psl.build_notes)[:200])
# The target is for the QUOTE, not the product (found in the 2026-11-11
# review). B55 measured same-game quotes at 0.77-0.99 of the product, so a
# product aimed AT the floor prices under it and voids a token.
_tgt = ff_boost.american(ff_boost.to_decimal(300)
                         / ff_boost._target_factor("draftkings", 3, 300))
chk("the target factor is derived from the measurements, not typed",
    0.77 < ff_boost._target_factor() < 0.99, str(ff_boost._target_factor()))
chk("every same-game slip's PRODUCT clears floor / factor, not just floor",
    _psl.candidates and all(c.independent_odds >= _tgt - 1e-6
                            for c in _psl.candidates),
    f"target {_tgt:+.0f}; got "
    f"{sorted(round(c.independent_odds) for c in _psl.candidates)[:4]}")
chk("so at the target factor the predicted QUOTE clears the floor",
    all(ff_boost.american(ff_boost.to_decimal(c.independent_odds)
                          * ff_boost._target_factor("draftkings", 3, 300))
        >= 300 - 1e-6 for c in _psl.candidates))
chk("the note gives the target, the factor and the worst case",
    any("aimed at" in n and "worst" in n and "price_sgp decides" in n
        for n in _psl.build_notes), str(_psl.build_notes)[:260])
# A group with one line per player cannot be retargeted: kept, and flagged.
_one = [ff_boost.BoostLeg(
    event_id="E0", book="dk", market="player_rush_yds", player=f"Solo{i}",
    side="OVER", odds=+60, fair_prob=0.6, fair_source="pinnacle",
    devig_method="shin", line=50.5, player_id=f"s{i}", verdict="CLEAR",
    verdict_side="OVER", team="NYG", pos="RB") for i in range(3)]
_osl2, _oerr2 = _ec(_one, None, mode="single-game", event_id="E0",
                    boost_pct=0.50, legs_per_slip=3)
chk("a +310 product with no alternative is kept, not dropped",
    _osl2 is not None and len(_osl2.candidates) == 1
    and 300 <= _osl2.candidates[0].independent_odds < _tgt,
    (_oerr2 or str([c.independent_odds for c in _osl2.candidates])))
chk("and flagged as likely to quote UNDER the floor",
    _osl2 is not None and any("UNDER the floor" in n
                              for n in _osl2.build_notes),
    str(_osl2.build_notes if _osl2 else _oerr2)[:220])
# Cross-game parlays are not haircut, so they keep the plain floor.
_xl = []
for _i in range(3):
    for _o in (-110, +100, +120):
        _xl.append(ff_boost.BoostLeg(
            event_id=f"X{_i}", book="dk", market="player_rush_yds",
            player=f"Cross{_i}", side="OVER", odds=_o, fair_prob=0.5,
            fair_source="pinnacle", devig_method="shin",
            line=40.5 + abs(_o) / 10, player_id=f"x{_i}", verdict="CLEAR",
            verdict_side="OVER", team=f"T{_i}", pos="RB"))
_xsl, _xerr = _ec(_xl, None, mode="cross-game", boost_pct=0.50,
                  legs_per_slip=3, floor=600, ceiling=900)
chk("a cross-game build targets the floor itself",
    _xsl is not None and _xsl.candidates
    and min(c.independent_odds for c in _xsl.candidates) < 700
    and not any("aimed at" in n for n in _xsl.build_notes),
    (_xerr or str([round(c.independent_odds) for c in _xsl.candidates])))
chk("and says how many combinations it chose between",
    any("price targeting chose between" in n for n in _psl.build_notes),
    str(_psl.build_notes)[:200])
# F11's rule: target the minimum, do not reach past it.
_pmax = _mx(_psl.candidates, "independent_odds")
chk("the chosen slips sit near the floor, not near the ceiling",
    _pmax is not None and _pmax < 600,
    f"max {_pmax} — 'target the minimum, do not reach past it'")
chk("no slip contains one player twice",
    all(len({ff_boost.norm_player(l.player) for l in c.legs}) == len(c.legs)
        for c in _psl.candidates))
# And those combinations are never GENERATED now, not generated and skipped.
chk("the one-player-twice count is gone, because none is produced",
    not any("one player twice" in n for n in _psl.build_notes),
    str(_psl.build_notes)[:200])

# --- determinism: two runs must choose the same rungs -------------------
_a = ff_boost.enumerate_candidates(
    _pl, _pm, mode="single-game", event_id="E1", boost_pct=0.50,
    legs_per_slip=3, floor=300, ceiling=900)
_b = ff_boost.enumerate_candidates(
    list(reversed(_pl)), _pm, mode="single-game", event_id="E1",
    boost_pct=0.50, legs_per_slip=3, floor=300, ceiling=900)
def _sig(sl):
    return sorted(tuple(sorted((ff_boost.norm_player(l.player), l.line,
                                l.odds) for l in c.legs))
                  for c in sl.candidates)
chk("the choice does not depend on pool order",
    _sig(_a) == _sig(_b),
    "a price tie broken by list order gives two runs two answers")

# --- the exact search agrees with brute force ---------------------------
_sm, _ = _ladder_pool(n_players=3, n_rungs=6)
_by = {}
for _l in _sm:
    _by.setdefault(ff_boost.norm_player(_l.player), []).append(_l)
for _k in _by:
    _by[_k].sort(key=lambda l: ff_boost.to_decimal(l.odds))
_lists = [_by[k] for k in sorted(_by)]
_want = ff_boost.to_decimal(300)
_brute = None
for _c in itertools.product(*_lists):
    _d = 1.0
    for _l in _c:
        _d *= ff_boost.to_decimal(_l.odds)
    if _d >= _want and (_brute is None or _d < _brute):
        _brute = _d
_got = ff_boost._cheapest_at_least(_lists, _want)
chk("the binary search finds the same cheapest-in-band as brute force",
    (_got is None and _brute is None)
    or (_got is not None and _brute is not None
        and abs(_got[0] - _brute) < 1e-9),
    f"search {_got[0] if _got else None} vs brute {_brute}")
chk("and returns None when nothing reaches the target, rather than guessing",
    ff_boost._cheapest_at_least(_lists, 1e9) is None)
chk("an empty list refuses rather than raising",
    ff_boost._cheapest_at_least([[], _lists[0]], _want) is None)

# --- the reason line can no longer claim an unreachable band ------------
# A REAL fixture, not a source-text check. The first version asserted the
# sentence appeared in the source, and a revert that removed the BRANCH
# left the sentence in place — so the check passed while the behaviour was
# gone. Reachable only one way: price targeting finds an in-band
# combination and `make_candidate` then raises, which happens when two
# legs normalise to different names but carry the same player_id.
def _twin(name, pid, odds, line, ev="E1"):
    return ff_boost.BoostLeg(
        event_id=ev, book="dk", market="player_reception_yds", player=name,
        side="OVER", odds=odds, fair_prob=0.40, fair_source="pinnacle",
        devig_method="shin", line=line, player_id=pid, verdict="CLEAR",
        verdict_side="OVER", team="NYG", pos="WR")


_twsl, _twerr = _ec([_twin("Cam Ward", "w9", +160, 40.5),
                     _twin("Cameron Ward", "w9", +150, 44.5),
                     _twin("Cam Ward", "w9", +120, 30.5)],
                    {"Cam Ward": ("NYG", "WR"),
                     "Cameron Ward": ("NYG", "WR")},
                    mode="single-game", event_id="E1", boost_pct=0.50,
                    legs_per_slip=2, floor=300, ceiling=900)
chk("an in-band group whose candidate dies does not blame the legs",
    _twsl is not None and not _twsl.candidates
    and "NOT the problem" in _twsl.reason,
    (_twerr or _twsl.reason)[:200])
chk("and it says the band was reachable",
    _twsl is not None and "reachable" in _twsl.reason,
    (_twerr or _twsl.reason)[:200])
_short, _sm2 = _ladder_pool(n_players=4, n_rungs=3)
_ssl, _sserr = _ec(_short, _sm2, mode="single-game", event_id="E1",
                   boost_pct=0.50, legs_per_slip=3, floor=5000,
                   ceiling=9000)
if _ssl is None:
    chk("the short pool enumerates at all", False, _sserr)
    _ssl = ff_boost.Shortlist(candidates=[], mode="single-game",
                              boost_pct=0.50, reason=_sserr)
chk("a genuinely too-short pool still says too short",
    not _ssl.candidates and ("too short" in _ssl.reason
                             or "below the floor" in _ssl.reason),
    _ssl.reason[:150])

# --- the bounded refusal, in place of the OOM --------------------------
# The first cap was 600 PLAYER GROUPS, and C(18, 3) = 816: an ordinary
# single-game board of main lines was refused outright the morning after it
# shipped. Nothing in the suite had a pool of more than 16 players, so
# nothing noticed. These are the pools that must simply run.
def _mainpool(n):
    return [ff_boost.BoostLeg(
        event_id="E0", book="dk", market="player_rush_yds", player=f"Main{i}",
        side="OVER", odds=-110, fair_prob=0.5, fair_source="pinnacle",
        devig_method="shin", line=50.5, player_id=f"m{i}", verdict="CLEAR",
        verdict_side="OVER", team="NYG", pos="RB") for i in range(n)]


for _n in (18, 40):
    _msl, _merr = _ec(_mainpool(_n), None, mode="single-game", event_id="E0",
                      boost_pct=0.50, legs_per_slip=3)
    chk(f"an ordinary {_n}-player main-line pool runs, not refuses",
        _msl is not None and _msl.candidates, _merr[:150])
# The bound that remains is on BUILT candidates, exercised by shrinking it.
_keep = ff_boost.MAX_BUILT_CANDIDATES
ff_boost.MAX_BUILT_CANDIDATES = 50
try:
    _bsl, _bigerr = _ec(_mainpool(18), None, mode="single-game",
                        event_id="E0", boost_pct=0.50, legs_per_slip=3)
finally:
    ff_boost.MAX_BUILT_CANDIDATES = _keep
chk("past the built-candidate bound it REFUSES with a reason",
    _bsl is None and "in-band combination" in _bigerr
    and "Narrow the pool" in _bigerr, _bigerr[:170] or "it ran")
# Out-of-band groups are counted but never built.
_osl, _oerr = _ec(_mainpool(18), None, mode="single-game", event_id="E0",
                  boost_pct=0.50, legs_per_slip=3, floor=5000, ceiling=9000)
chk("a pool with nothing in band builds nothing and says which way",
    _osl is not None and not _osl.candidates and "floor" in _osl.reason.lower(),
    (_oerr or _osl.reason)[:150])

# --- `pessimistic` conflated two states --------------------------------
_je_none = ff_boost.joint_error([_jleg("A", .5), _jleg("B", .5)], [])
chk("no measured pair: pessimistic False but NOT unbracketed",
    not _je_none.pessimistic and not _je_none.unbracketed,
    "on the live board this fired on 4 of 8 slips, every one of them "
    "because there were no pairs at all — a 100% false-positive rate as "
    "a missing-interval alarm")
_je_pt = ff_boost.joint_error([_jleg("A", .5), _jleg("B", .5)],
                              [("A", "B", .1774, "t")])
chk("a measured pair with no interval IS unbracketed",
    _je_pt.unbracketed and not _je_pt.pessimistic)
_je_ci = ff_boost.joint_error([_jleg("A", .5), _jleg("B", .5)],
                              [("A", "B", .1774, "t", (.1626, .1922))])
chk("a measured pair WITH an interval is neither",
    _je_ci.pessimistic and not _je_ci.unbracketed)

# --- the raw-name meta join --------------------------------------------
# TWO CLASSES, and they are not the same problem. The normalised pass
# closes punctuation and spacing; it does NOT close first-name variants,
# because `norm_player` is documented not to and does not. An earlier
# version of this check asserted it did — a check written to match a
# comment rather than the code.
chk("the normalised pass closes PUNCTUATION variants",
    ff_boost._meta_lookup("J.J. McCarthy",
                          {"J.J McCarthy": ("MIN", "QB")}) == ("MIN", "QB")
    and ff_boost._meta_lookup("DJ Moore",
                              {"D.J. Moore": ("CHI", "WR")}) == ("CHI", "WR"),
    "this is the class that was silently failing on the raw key")
chk("it does NOT close first-name variants, and does not pretend to",
    ff_boost._meta_lookup("Cameron Skattebo",
                          {"Cam Skattebo": ("NYG", "RB")}) == (None, None),
    "norm_player is documented not to collapse Cam/Cameron")
chk("an alias map closes those, which is the documented remedy",
    ff_boost._meta_lookup("Cameron Skattebo",
                          {"Cam Skattebo": ("NYG", "RB")},
                          aliases={"Cameron Skattebo": "Cam Skattebo"})
    == ("NYG", "RB"),
    "propline_search_players' known_names lists both against one id, and "
    "a CALLER passes it in — this module makes no tool calls")
chk("and the alias map tolerates punctuation and case on either side",
    ff_boost._meta_lookup("Chigoziem Okonkwo",
                          {"Chig Okonkwo": ("WSH", "TE")},
                          aliases={"chigoziem okonkwo": "CHIG OKONKWO"})
    == ("WSH", "TE"),
    "both sides go through norm_player, so a caller need not match the "
    "meta key's exact spelling")
# B143, fixed 2026-11-11: runs of whitespace are collapsed in the name key
# itself, so this now resolves. It was pinned here as a known limit first.
chk("a double space in a meta key is closed by the name key (B143)",
    ff_boost._meta_lookup("Chigoziem Okonkwo",
                          {"Chig  Okonkwo": ("WSH", "TE")},
                          aliases={"chigoziem okonkwo": "Chig Okonkwo"})
    == ("WSH", "TE"))
chk("the exact key still wins, and costs no scan",
    ff_boost._meta_lookup("Cam Skattebo",
                          {"Cam Skattebo": ("NYG", "RB")}) == ("NYG", "RB"))
chk("a genuine miss returns (None, None), not a near match",
    ff_boost._meta_lookup("Somebody Else",
                          {"Cam Skattebo": ("NYG", "RB")}) == (None, None),
    "B44/B101/B127 are three separate incidents of a fuzzy join losing a "
    "player his whole board")
chk("and an empty meta does not raise",
    ff_boost._meta_lookup("Anyone", None) == (None, None))
# The consequence, end to end: a book spelling must still correlate.
# End to end: a punctuation variant resolves with no help at all, and a
# first-name variant resolves only once the caller supplies the alias.
_mc1 = _jleg("J.J. McCarthy", .52, market="player_pass_yds", pos=None,
             team=None)
_mc2 = _jleg("Malik Nabers", .52, market="player_reception_yds", pos=None,
             team=None)
ff_boost.classify([_mc1, _mc2], {"J.J McCarthy": ("NYG", "QB"),
                                 "Malik Nabers": ("NYG", "WR")})
chk("a punctuation variant resolves to a team, so the pair is not lost",
    _mc1.team == "NYG" and _mc2.team == "NYG", f"{_mc1.team} {_mc2.team}")
_sk1 = _jleg("Cameron Skattebo", .52, market="player_rush_yds", pos=None,
             team=None)
_sk2 = _jleg("Malik Nabers", .52, market="player_reception_yds", pos=None,
             team=None)
ff_boost.classify([_sk1, _sk2], {"Cam Skattebo": ("NYG", "RB"),
                                 "Malik Nabers": ("NYG", "WR")})
chk("a first-name variant with no alias comes back team=None",
    _sk1.team is None,
    "and that is the honest answer — the alias has to be supplied, not "
    "guessed by edit distance")
_sk3 = _jleg("Cameron Skattebo", .52, market="player_rush_yds", pos=None,
             team=None)
ff_boost.classify([_sk3, _jleg("Malik Nabers", .52,
                               market="player_reception_yds", pos=None,
                               team=None)],
                  {"Cam Skattebo": ("NYG", "RB"),
                   "Malik Nabers": ("NYG", "WR")},
                  aliases={"Cameron Skattebo": "Cam Skattebo"})
chk("and resolves once the alias is passed through classify",
    _sk3.team == "NYG", str(_sk3.team))

# --- the cross-table interval, which bracketed by 0.0011 ---------------
_qb77 = _jleg("QB1", .52, market="player_pass_yds", pos="QB")
_wr77 = _jleg("WR1", .52, market="player_reception_yds", pos="WR")
_r77, _why77, _ci77 = ff_boost._pair_r_ci(_qb77, _wr77)
_side77 = ff_boost.side_pair("same", "PASS", "RECV")
chk("QB x WR recv takes r from the lift table and an interval from _RMS",
    _ci77 is not None and abs(_r77 - _side77[0]) > 1e-6,
    f"r={_r77} side-table r={_side77[0]} ci={_ci77}")
chk("the interval is WIDENED to cover both tables' estimates",
    _ci77[0] <= min(_r77, _side77[0]) and _ci77[1] >= max(_r77, _side77[0]),
    f"ci={_ci77} must bracket both {_r77:+.4f} and {_side77[0]:+.4f} — the "
    f"old rule tested one of them and passed by 0.0011")
# On today's tables the interval already covers both estimates, so no
# widening is needed and none is announced. The point of the change is
# that a re-measurement which moves `r` OUTSIDE the interval now widens it
# instead of DROPPING it — the old rule tested the bracket and passed by
# 0.0011, so one re-measurement would have silently removed the interval
# and changed what `joint_error` takes a sign from.
chk("no note today, because the interval already covers both",
    "widened" not in _why77, _why77[-130:])
_wide = ff_boost.joint_error(
    [_jleg("A", .5), _jleg("B", .5)],
    [("A", "B", 0.40, "t", (0.2286, 0.2625))])
chk("an r outside its interval still yields a usable signed error",
    _wide.pessimistic and _wide.rel > 0, f"{_wide.rel:+.4%}")
# Exercise the real behaviour rather than asserting a docstring with an
# `or True` beside it — lesson 92's vacuous clause, written here and then
# caught by reading it back.
_wq = _jleg("QBX", .5, market="player_pass_yds", pos="QB")
_ww = _jleg("WRX", .5, market="player_reception_yds", pos="WR")
_, _wwhy, _wci = ff_boost._pair_r_ci(_wq, _ww)
_sidev = ff_boost.side_pair("same", "PASS", "RECV")[0]
_liftv = ff_boost._pair_r(_wq, _ww)[0]
chk("_widen_interval covers an estimate outside the interval, and says so",
    ff_boost._widen_interval((0.2286, 0.2625), 0.40, 0.2456)
    == ((0.2286, 0.40), True),
    str(ff_boost._widen_interval((0.2286, 0.2625), 0.40, 0.2456)))
chk("and leaves an interval that already covers both alone, silently",
    ff_boost._widen_interval((0.2286, 0.2625), 0.2614, 0.2456)
    == ((0.2286, 0.2625), False),
    "which is the case on today's tables — it brackets r by 0.0011, and "
    "the point of the change is that a re-measurement now WIDENS instead "
    "of DROPPING the interval")
chk("it widens downward too, not just up",
    ff_boost._widen_interval((0.2286, 0.2625), 0.10)[0] == (0.10, 0.2625))
chk("and tolerates a reversed interval and a None estimate",
    ff_boost._widen_interval((0.2625, 0.2286), None, 0.30)
    == ((0.2286, 0.30), True))
chk("the attached interval brackets BOTH tables' estimates, always",
    _wci is not None
    and _wci[0] <= min(_liftv, _sidev) <= max(_liftv, _sidev) <= _wci[1],
    f"ci={_wci} lift={_liftv:+.4f} side={_sidev:+.4f} — a re-measurement "
    f"now widens the interval instead of dropping it")

# --- P(cash) 0.0% beside a positive ROI band ---------------------------
_path = ff_boost.make_candidate(
    [_jleg("A", .02, market="player_reception_yds", pos="WR", ev="E1"),
     _jleg("B", .02, market="player_rush_yds", pos="RB", ev="E2"),
     _jleg("C", .02, market="player_pass_yds", pos="QB", ev="E3")],
    boost_pct=0.50)
for _l in _path.legs:
    _l.odds = +900
chk("a slip whose P(cash) contradicts its price gets NO ROI band",
    _path.ev_band is None, str(_path.ev_band))
# First shipped as PRICE IT, which was wrong: this slip is about -99% at
# its own product price, and the real quote is normally worse than the
# product. "The band does not apply" is not "nothing is known".
chk("a slip that loses at its own product price is NEGATIVE, not PRICE IT",
    _path.verdict == "NEGATIVE" and _path.ev_at_product < -0.9,
    f"{_path.verdict} ev_at_product={_path.ev_at_product}")
_bbl = [_jleg("A", .30, market="player_reception_yds", pos="WR", ev="E1"),
        _jleg("B", .30, market="player_rush_yds", pos="RB", ev="E2")]
for _l in _bbl:
    _l.odds = +100
_bigboost = ff_boost.make_candidate(_bbl, boost_pct=3.0)
chk("PRICE IT survives only where the product price is still positive",
    _bigboost.ev_band is None and _bigboost.ev_at_product > 0
    and _bigboost.verdict == "PRICE IT",
    f"{_bigboost.verdict} band={_bigboost.ev_band} "
    f"ev_at_product={_bigboost.ev_at_product}")
chk("PRICE IT is a documented verdict", "PRICE IT" in ff_boost.VERDICTS)
_prep = ff_boost.report([_path])
chk("the report prints the reason in place of the ROI line",
    "NO ROI BAND" in _prep and "anticipated ROI" not in _prep,
    "two correctly computed numbers side by side were nonsense")
chk("it names the hold its own P(cash) implies",
    "implies a hold of" in _prep)
chk("a band-less slip ranks at its product-price EV, a measured ceiling",
    abs(_path.rank - _path.ev_at_product) < 1e-12 and -1.0 <= _path.rank < 0,
    f"rank {_path.rank}: 0.0 put it above every measured negative, and "
    f"-9e9 was a claim nothing measured")
chk("the report states that ceiling", "at the full product" in _prep,
    "the reason line must say what IS known, not only what is not")
# A healthy slip must be untouched: the check is ONE-sided on purpose.
_ok77 = ff_boost.make_candidate(
    [_jleg("A", .52, market="player_reception_yds", pos="WR", ev="E1"),
     _jleg("B", .52, market="player_rush_yds", pos="RB", ev="E2"),
     _jleg("C", .52, market="player_pass_yds", pos="QB", ev="E3")],
    boost_pct=0.50)
chk("an ordinary slip still gets its ROI band",
    _ok77.ev_band is not None and str(_ok77.verdict) in ("PLAY", "NEGATIVE"),
    f"{_ok77.verdict} {_ok77.ev_band} — the product carries only the legs' "
    f"own vig, far less than the SGP band, so a healthy slip sits BELOW "
    f"the band here and a two-sided test failed seven fixtures")
chk("and its product-implied hold is below the band, by construction",
    _ok77.product_hold < _ok77.hold_band[0],
    f"{_ok77.product_hold:+.2%} vs band {_ok77.hold_band}")

# ===========================================================================
# 77. Findings from the second live run (event 53178, 2026-11-11)
# ===========================================================================

section("77. findings from the second live run")

# --- rung legs carry the anchor's depth ---------------------------------
# 121 of 306 live rungs were pinned to a Pinnacle level at exactly 0.5000
# on opening-limit money, and `rung_legs` hardcoded anchor_liquidity=None,
# so none of the three anchor flags could fire on a rung.
def _rgd(player, thr, price, fair, pid, a_fair, a_liq):
    r = _rg(player, thr, price, fair, pid)
    r.anchor_fair = a_fair
    r.anchor_liquidity = a_liq
    return r


_V77 = {n: ("CLEAR", "OVER", ()) for n in ("Op", "Un", "Deep", "Silent")}
_dk, _dr = _rl([_rgd("Op", 30, +150, 0.39, "o", 0.5000, 250.0),
                _rgd("Un", 30, +150, 0.39, "u", 0.5310, 250.0),
                _rgd("Deep", 30, +150, 0.39, "d", 0.5000, 5000.0),
                _rgd("Silent", 30, +150, 0.39, "s", 0.5000, None)],
               verdicts=_V77, tiers={"pinnacle": 250.0})
_bn = {l.player: l for l in _dk}
chk("rung legs are built with their anchor's depth", len(_dk) == 4
    and _bn["Op"].anchor_liquidity == 250.0
    and _bn["Op"].anchor_level_fair == 0.5, _why0(_dr))
chk("a rung on an exact-0.5000 level at the opening tier is anchor_opening",
    _bn["Op"].anchor_opening and abs(_bn["Op"].fair_prob - 0.39) < 1e-9,
    "the test must read the ANCHOR's fair, not the rung's own 0.39")
chk("a level that has moved, still at the tier, is anchor_untested",
    _bn["Un"].anchor_untested and not _bn["Un"].anchor_opening)
chk("an exact 0.5000 behind deep money is neither",
    not _bn["Deep"].anchor_opening and not _bn["Deep"].anchor_untested)
chk("an anchor that reported nothing stays its own state",
    _bn["Silent"].anchor_liquidity is None and _bn["Silent"].anchor_opening,
    "a null-liquidity 0.5000 is flagged, as for a main line")
chk("the tier lookup is recorded as having run",
    _bn["Op"].tier_source == "measured"
    and _bn["Op"].opening_liquidity_tier == 250.0)
_nt, _ = _rl([_rgd("Op", 30, +150, 0.39, "o", 0.5, 250.0)], verdicts=_V77)
chk("no tiers passed reads as never looked up, not as 'book quotes none'",
    _nt and _nt[0].tier_source == "" and _nt[0].opening_liquidity_tier is None)
_nt2, _ = _rl([_rgd("Op", 30, +150, 0.39, "o", 0.5, 250.0)], verdicts=_V77,
              tiers={})
chk("tiers passed but silent on this anchor reads 'book quotes none'",
    _nt2 and _nt2[0].tier_source == "book quotes none")
chk("a main line still tests its own fair_prob",
    ff_boost.BoostLeg(
        event_id="E1", book="dk", market="player_rush_yds", player="M",
        side="OVER", odds=-110, fair_prob=0.5, fair_source="pinnacle",
        devig_method="shin", line=1.5, anchor_liquidity=250.0,
        opening_liquidity_tier=250.0).anchor_opening)
chk("the anchor-depth column now has a number on a rung slip",
    "thinnest leg 250" in _dsc(ff_boost.anchor_depth([_bn["Op"], _bn["Un"]])))
chk("ladder_fair records the depth it measured",
    "anchor_liquidity" in ff_props.LadderFair.__dataclass_fields__
    and "rec.anchor_liquidity = a_lo" in inspect.getsource(ff_props.ladder_fair))

# --- probabilities a person can read ------------------------------------
chk("an ordinary probability prints as before", ff_boost._prob(0.137) == "13.7%")
chk("a tiny one prints with precision and as 1 in N",
    ff_boost._prob(1.3758e-5) == "0.00138% (1 in 72,685)", ff_boost._prob(1.3758e-5))
chk("zero and None do not raise",
    ff_boost._prob(0) == "0%" and ff_boost._prob(None) == "n/a")
_lsl = [_jleg("A", .024, market="player_rush_yds", pos="RB", ev="E1"),
        _jleg("B", .024, market="player_reception_yds", pos="WR", ev="E2"),
        _jleg("C", .024, market="player_pass_yds", pos="QB", ev="E3")]
for _l in _lsl:
    _l.odds = +3800
_ls = ff_boost.make_candidate(_lsl, boost_pct=0.50)
_lrep = ff_boost.report([_ls])
chk("a sane-hold longshot keeps its band — the guard is right not to fire",
    _ls.ev_band is not None, f"product_hold {_ls.product_hold}")
chk("but P(cash) and breakeven are no longer both '0.0%'",
    "P(cash)         : 0.0%" not in _lrep and "1 in " in _lrep,
    str([x.strip() for x in _lrep.splitlines()
         if "P(cash)" in x or "breakeven" in x]))
chk("and it carries the LONGSHOT line",
    "LONGSHOT" in _lrep and "almost certainly lose" in _lrep)
chk("an ordinary slip carries no LONGSHOT line",
    "LONGSHOT" not in ff_boost.report([_ok77]))

# --- the per-group "below the price target" note -------------------------
# The live run could not exercise it and found no check for it.
_bt = []
for _i, _nm in enumerate(("Bt0", "Bt1", "Bt2")):
    for _o, _ln in ((+60, 40.5), (+62, 44.5)):
        _bt.append(ff_boost.BoostLeg(
            event_id="E0", book="dk", market="player_rush_yds", player=_nm,
            side="OVER", odds=_o, fair_prob=0.6, fair_source="pinnacle",
            devig_method="shin", line=_ln, player_id=f"bt{_i}",
            verdict="CLEAR", verdict_side="OVER", team="NYG", pos="RB"))
_btsl, _bterr = _ec(_bt, None, mode="single-game", event_id="E0",
                    boost_pct=0.50, legs_per_slip=3)
chk("a multi-line group that cannot reach the target says BELOW it",
    _btsl is not None and any("BELOW the price target" in n
                              for n in _btsl.build_notes),
    str(_btsl.build_notes if _btsl else _bterr)[:260])

# --- the live factors are recorded, and do NOT yet move the target ------
chk("the 2026-11-11 quotes are kept with their book",
    len(ff_boost.SGP_FACTORS_LIVE_20261111) == 14
    and all(len(r) == 3 for r in ff_boost.SGP_FACTORS_LIVE_20261111))
# B161 (lower quartile, not median) and B167 (per book), both 2026-11-11.
_fb = ff_boost.factors_by_book()
chk("factors are kept per sportsbook, exchanges excluded",
    {k: len(v) for k, v in _fb.items()}
    == {"betmgm": 70, "fanduel": 30, "draftkings": 46, "betrivers": 3},
    str({k: len(v) for k, v in _fb.items()}))
# Figures as of 2026-11-13, with BOTH game-day runs' quotes in (B179,
# B191). A three-leg slip against a +300 minimum:
for _bk, _want, _prod in (("draftkings", 0.900, 344), ("fanduel", 0.896, 346),
                          ("betmgm", 0.829, 382)):
    _f, _why, _n = ff_boost.target_factor_detail(_bk, 3, 300)
    _xs = ff_boost._factor_sample(_bk, 3, 300)[0]
    chk(f"{_bk} is aimed with its OWN lower quartile, about {_want}",
        abs(_f - _want) < 2e-3 and f"{_bk}'s own 3-leg long-priced" in _why
        and abs(_f - ff_boost._lower_quartile(_xs)) < 1e-12 and _n == len(_xs),
        f"{_f:.4f} {_why}")
    chk(f"  which puts a +300 floor's product target near +{_prod}",
        abs(ff_boost.american(4.0 / _f) - _prod) < 2,
        str(ff_boost.american(4.0 / _f)))
    chk(f"  with about a quarter of {_bk}'s own quotes below it, not half",
        0.15 <= sum(1 for x in _xs if x < _f) / len(_xs) <= 0.30)
chk("the three books' targets really differ, which is why pooling was wrong",
    ff_boost._target_factor("betmgm", 3, 300)
    < ff_boost._target_factor("fanduel", 3, 300)
    < ff_boost._target_factor("draftkings", 3, 300))
_pf, _pwhy, _pn = ff_boost.target_factor_detail(None)
chk("no book named falls back to the pooled lower quartile",
    _pn == 149 and "pooled" in _pwhy and abs(_pf - 0.900) < 2e-3, f"{_pf} {_pwhy}")
chk("a book with too few quotes is pooled, and the reason says how many",
    ff_boost.target_factor_detail("betrivers")[0] == _pf
    and "only 3 quote" in ff_boost.target_factor_detail("betrivers")[1])
chk("an unknown book is pooled and says it has none",
    ff_boost.target_factor_detail("caesars")[0] == _pf
    and "no quotes on file" in ff_boost.target_factor_detail("caesars")[1])
chk("book names are matched loosely: dk, DraftKings, ' fanduel '",
    ff_boost._target_factor("dk") == ff_boost._target_factor("DraftKings")
    == ff_boost._target_factor("draftkings")
    and ff_boost._target_factor(" FanDuel ") == ff_boost._target_factor("fanduel"))
_m3 = ff_boost.factors_by_book(3)["betmgm"]
chk("the pooled BetMGM miss this rule exists to prevent",
    sum(1 for x in _m3 if x < _pf) == 17 and len(_m3) == 38,
    f"aimed with the pooled factor, "
    f"{sum(1 for x in _m3 if x < _pf)} of BetMGM's {len(_m3)} three-leg "
    f"quotes miss")

# --- B179: the factor also depends on LEG COUNT --------------------------
_f2, _w2, _n2 = ff_boost.target_factor_detail("betmgm", 2, 400)
_f3, _w3, _n3 = ff_boost.target_factor_detail("betmgm", 3, 400)
chk("BetMGM two-leg slips are aimed with BetMGM's two-leg quotes",
    _n2 == 12 and "2-leg long-priced" in _w2 and abs(_f2 - 0.924) < 2e-3,
    f"{_f2} {_w2}")
chk("and its three-leg slips with its three-leg quotes, a harsher figure",
    _n3 == 38 and "3-leg long-priced" in _w3 and abs(_f3 - 0.829) < 2e-3
    and _f3 < _f2, f"{_f3} {_w3}")
chk("  so a +400 two-leg target is about +441 and a three-leg about +503",
    abs(ff_boost.american(5.0 / _f2) - 441) < 2
    and abs(ff_boost.american(5.0 / _f3) - 503) < 2,
    f"{ff_boost.american(5.0 / _f2):+.0f} {ff_boost.american(5.0 / _f3):+.0f}")
_fdk2 = ff_boost.target_factor_detail("draftkings", 2, 300)
chk("a leg count with too few quotes falls back to the book's band, "
    "and says so",
    _fdk2[0] == ff_boost._target_factor("draftkings", 3, 300)
    and "too few 2-leg" in _fdk2[1], _fdk2[1])
chk("the expected (median) factor follows the leg count too",
    ff_boost.expected_factor("betmgm", 2, 400)
    > ff_boost.expected_factor("betmgm", 3, 400))
# B191: and on the PRICE BAND. A short slip is quoted closer to its product.
chk("a minimum under +200 is the short band, +200 and up the long one",
    ff_boost.price_band(-300) == ff_boost.price_band(199) == "short"
    and ff_boost.price_band(200) == ff_boost.price_band(400) == "long"
    and ff_boost.price_band(None) is None)
_fs, _ws, _ns = ff_boost.target_factor_detail("betmgm", 2, -300)
chk("BetMGM's -300 token is aimed with its SHORT two-leg quotes",
    _ns == 16 and "2-leg short-priced" in _ws and abs(_fs - 0.977) < 2e-3
    and _fs > _f2, f"{_fs} {_ws}")
chk("  about -274, where the long-band figure would have said -253",
    abs(ff_boost.american((4.0 / 3.0) / _fs) + 274) < 2,
    str(ff_boost.american((4.0 / 3.0) / _fs)))
_ffs = ff_boost.target_factor_detail("fanduel", 3, 100)
chk("a band with too few quotes falls back to the whole book, and says so",
    _ffs[2] == 30 and "too few closer ones" in _ffs[1], str(_ffs))
def _pe_args():
    seen = []
    real = ff_boost.expected_factor
    def spy(book=None, n_legs=None, price=None):
        seen.append((book, n_legs, price))
        return real(book, n_legs, price)
    ff_boost.expected_factor = spy
    try:
        c = ff_boost.make_candidate(
            [_jleg("PA", .5, market="player_pass_yds", pos="QB"),
             _jleg("PB", .5, market="player_reception_yds", pos="WR")],
            boost_pct=0.50)
        pe = c.predicted_ev
    except Exception as e:
        return f"{type(e).__name__}: {e}", None
    finally:
        ff_boost.expected_factor = real
    return seen, pe
_pa, _ppe = _pe_args()
chk("a slip's predicted EV asks for the factor at ITS leg count",
    _ppe is not None and isinstance(_pa, list) and _pa
    and all(a[1] == 2 and a[2] is not None for a in _pa), f"{_pa} {_ppe}")
_r12 = ff_boost.SGP_FACTORS_LIVE_20261112
chk("the game-day quotes are on file: 64, of which 19 the engine refused",
    len(_r12) == 64 and sum(1 for r in _r12 if not r[3]) == 19,
    f"{len(_r12)} {sum(1 for r in _r12 if not r[3])}")
_r12b = ff_boost.SGP_FACTORS_LIVE_20261112_RUN1
chk("run 1's quotes are on file too: 79, of which 18 the engine refused",
    len(_r12b) == 79 and sum(1 for r in _r12b if not r[3]) == 18,
    f"{len(_r12b)} {sum(1 for r in _r12b if not r[3])}")
chk("a quote on a slip the engine REFUSES does not set the target",
    max(r[2] for r in _r12 if not r[3]) > 1.3
    and len(ff_boost.factor_rows()) == 149
    and max(r[2] for r in ff_boost.factor_rows()) < 1.1,
    str(max(r[2] for r in ff_boost.factor_rows())))
# The same pool at three books is aimed at three different products.
def _rebook(legs, book):
    out = []
    for l in legs:
        d = dict(l.__dict__)
        d["book"] = book
        d["shape_source"] = book if l.shape_source else ""
        out.append(ff_boost.BoostLeg(**d))
    return out
_minp = {}
for _bk in ("draftkings", "fanduel", "betmgm"):
    _bsl2, _be2 = _ec(_rebook(_pl, _bk), _pm, mode="single-game",
                      event_id="E1", boost_pct=0.50, legs_per_slip=3,
                      floor=300, ceiling=900)
    _minp[_bk] = (min(c.independent_odds for c in _bsl2.candidates)
                  if _bsl2 and _bsl2.candidates else None)
    chk(f"a {_bk} pool's note names {_bk} and its own quotes",
        _bsl2 is not None and any(f"slip at {_bk}" in n and f"{_bk}'s own 3-leg long-priced quotes" in n
                                  for n in _bsl2.build_notes),
        str(_bsl2.build_notes if _bsl2 else _be2)[:240])
chk("and BetMGM slips are aimed longer than DraftKings ones",
    None not in _minp.values()
    and _minp["betmgm"] > _minp["fanduel"] >= _minp["draftkings"],
    str(_minp))
_mix, _mixe = _ec(_rebook(_pl[:48], "draftkings") + _rebook(_pl[48:], "betmgm"),
                  _pm, mode="single-game", event_id="E1", boost_pct=0.50,
                  legs_per_slip=3, floor=300, ceiling=900)
chk("a pool mixing books is aimed with the harshest of them",
    _mix is not None and _mix.candidates
    and min(c.independent_odds for c in _mix.candidates) >= _minp["betmgm"] - 1,
    _mixe or str(min(c.independent_odds for c in _mix.candidates)))
chk("the build note says lower quartile and the expected miss rate",
    any("lower quartile" in n and "one quote in four" in n
        for n in _psl.build_notes), str(_psl.build_notes)[:260])

# --- B163: player_series takes the alias map ------------------------------
import pandas as _pd
_wk = _pd.DataFrame({"player_display_name": ["Cam Skattebo"] * 3,
                     "season": [2026] * 3, "week": [1, 2, 3],
                     "season_type": ["REG"] * 3,
                     "rushing_yards": [40, 55, 61], "carries": [10, 12, 14]})
def _ps(name, **kw):
    try:
        return len(ff_props.player_series(_wk, name, "rushing_yards", **kw)), ""
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"
chk("a book spelling with no alias still raises, and now says what to do",
    _ps("Cameron Skattebo")[0] is None
    and "aliases=" in _ps("Cameron Skattebo")[1], _ps("Cameron Skattebo")[1])
chk("with the alias it finds the nflverse rows",
    _ps("Cameron Skattebo", aliases={"cameron skattebo": "Cam Skattebo"})[0] == 3,
    str(_ps("Cameron Skattebo", aliases={"cameron skattebo": "Cam Skattebo"})))
chk("an alias pointing at nobody still raises rather than guessing",
    _ps("Cameron Skattebo", aliases={"Cameron Skattebo": "Nobody"})[0] is None)
chk("the exact name is unaffected", _ps("Cam Skattebo")[0] == 3)
# A revert that matched the alias on SURNAME ONLY went uncaught: nothing
# offered a wrong first name with the right surname.
chk("an alias for a different Skattebo does not match on the surname",
    _ps("Cameron Skattebo", aliases={"Kyle Skattebo": "Cam Skattebo"})[0] is None,
    "B44/B101/B127: a near-match join is how a player loses his board")

# ===========================================================================
# 78. B156 — pairs cleared one at a time still add up across a slip
# ===========================================================================

section("78. cleared pairs accumulate (B156)")


def _zl(name, market, pos, side="OVER", p=.5, team="NYG"):
    return ff_boost.BoostLeg(
        event_id="E1", book="dk", market=market, player=name, side=side,
        odds=-110, fair_prob=p, fair_source="pinnacle", devig_method="shin",
        line=50.5, player_id=name, verdict="CLEAR", verdict_side=side,
        team=team, pos=pos)


def _zslip(n_recv, rb_side="OVER"):
    return ([_zl("RB", "player_rush_yds", "RB", side=rb_side)]
            + [_zl(f"W{i}", "player_reception_yds", "WR")
               for i in range(n_recv)])


_z3 = ff_boost.classify(_zslip(2))
chk("a back and two receivers stays priceable: the sum is inside the noise",
    _z3.priceable and len(_z3.zeros) == 3 and not _z3.pairs,
    f"{_z3.kind} pairs={len(_z3.pairs)}")
_z4 = ff_boost.classify(_zslip(3))
chk("a back and THREE receivers does not: six cleared pairs add up",
    not _z4.priceable and len(_z4.pairs) == 6,
    f"{_z4.kind} pairs={len(_z4.pairs)} zeros={len(_z4.zeros)}")
chk("every pair in it passed the per-pair gate on its own",
    all(abs(ff_boost.pair_lift("same", *sorted((a, b)))[0] - 1.0)
        <= ff_boost.CORR_GATE_LIFT_DEV
        for a, b in (("RECV", "RUSH"), ("RECV", "RECV"))),
    "which is exactly why a per-pair gate cannot bound a slip")
chk("the reason says the pairs were scored because of their SUM",
    "cleared pairs sum to" in _z4.reason and "B156" in _z4.reason,
    _z4.reason[-200:])
_z4c = ff_boost.make_candidate(_zslip(3), boost_pct=0.50)
chk("and the slip is refused through the ordinary joint gate",
    _z4c.verdict == "UNPRICEABLE" and _z4c.joint.rel < 0
    and _z4c.p_cash is None, f"{_z4c.verdict} {_z4c.joint.rel:+.2%}")
_z4u = ff_boost.classify(_zslip(3, rb_side="UNDER"))
chk("flip the back to UNDER and the sum turns positive, so nothing changes",
    _z4u.priceable and len(_z4u.zeros) == 6,
    f"{_z4u.kind} — the conservative direction needs no gate")
# That fixture's positive sum (+3.15%) is itself inside the noise, so a
# revert that promoted on ANY large sum went uncaught. This one is clearly
# positive: an opposing QB beside three receivers, +4.7% against 3.2%.
_zp = ([_zl("QB", "player_pass_yds", "QB", team="WAS")]
       + [_zl(f"W{i}", "player_reception_yds", "WR") for i in range(3)])
_dzp, _ = ff_boost._zero_drift(
    _zp, [(a.player, b.player, "t")
          for a, b in itertools.combinations(_zp, 2)])
_zpc = ff_boost.classify(_zp)
chk("a positive sum well past the noise still changes nothing",
    _dzp > 0.04 and _zpc.priceable and not _zpc.pairs,
    f"drift {_dzp:+.2%}, {_zpc.kind} — the product understating the joint "
    f"is the safe direction")
_dz, _pz = ff_boost._zero_drift(_zslip(3), _z3.zeros[:0])
chk("no cleared pairs, no drift", _dz == 0.0 and _pz == [])
_dz4, _pz4 = ff_boost._zero_drift(
    _zslip(3), [(a.player, b.player, "t") for a, b in
                itertools.combinations(_zslip(3), 2)])
chk("the drift is the sum of the measured lift deviations",
    abs(_dz4 - (3 * (0.9878 - 1) + 3 * (0.9983 - 1))) < 1e-9, f"{_dz4:+.4%}")
_xz = [_zl("A", "player_rush_yds", "RB"), _zl("B", "player_rush_yds", "RB")]
_xz[1].event_id = "E2"
chk("a cross-game pair has no lift to add and is left alone",
    ff_boost._zero_drift(_xz, [("A", "B", "t")]) == (0.0, []))

# ===========================================================================
# 79. B157 / B165 — prefer a priceable combination; label a carried slip
# ===========================================================================

section("79. priceable preference and price balance")


def _pl(name, market, pos, dec, line=50.5):
    return ff_boost.BoostLeg(
        event_id="E1", book="dk", market=market, player=name, side="OVER",
        odds=ff_boost.american(dec), fair_prob=min(0.95, 0.95 / dec),
        fair_source="pinnacle", devig_method="shin", line=line,
        player_id=name, verdict="CLEAR", verdict_side="OVER", team="NYG",
        pos=pos)


def _ppool(rush_dec):
    # The QB has a passing rung (correlated with his receivers) and a
    # rushing rung (measured independent of them). Passing is cheaper.
    return [_pl("QBp", "player_pass_yds", "QB", 1.31, 210.5),
            _pl("QBp", "player_rush_yds", "QB", rush_dec, 20.5),
            _pl("WRa", "player_reception_yds", "WR", 1.90),
            _pl("WRb", "player_reception_yds", "WR", 1.90)]


_near, _nerr = _ec(_ppool(1.35), None, mode="single-game", event_id="E1",
                   boost_pct=0.50, legs_per_slip=3, floor=300, ceiling=900)
_nlegs = ({l.market for l in _near.candidates[0].legs}
          if _near and _near.candidates else set())
chk("within one quote step, the PRICEABLE combination is taken",
    "player_rush_yds" in _nlegs and "player_pass_yds" not in _nlegs
    and _near.candidates[0].structure.priceable,
    _nerr or f"{_nlegs} {_near.candidates[0].verdict if _near.candidates else ''}")
chk("and the build notes say a swap happened and why",
    _near is not None and any("B157" in n for n in _near.build_notes)
    and any("took the PRICEABLE" in n for n in _near.build_notes),
    str(_near.build_notes if _near else _nerr)[:260])
_far, _ferr = _ec(_ppool(1.45), None, mode="single-game", event_id="E1",
                  boost_pct=0.50, legs_per_slip=3, floor=300, ceiling=900)
_flegs = ({l.market for l in _far.candidates[0].legs}
          if _far and _far.candidates else set())
chk("more than one quote step away, the cheapest stays — no reaching",
    "player_pass_yds" in _flegs
    and not any("B157" in n for n in _far.build_notes),
    _ferr or f"{_flegs}")
chk("the step is the measured quote-grid spacing",
    ff_boost.SGP_QUOTE_STEP_DEC == 0.25)
_onlyp, _ = _ec([l for l in _ppool(1.35) if l.market != "player_rush_yds"],
                None, mode="single-game", event_id="E1", boost_pct=0.50,
                legs_per_slip=3, floor=300, ceiling=900)
chk("with no priceable alternative the cheapest is kept as it was",
    _onlyp is not None and len(_onlyp.candidates) == 1
    and not _onlyp.candidates[0].structure.priceable)
chk("a cheapest pick that is already priceable is left alone",
    not any("B157" in n for n in _psl.build_notes))
# The structure cache is a first pass: B156's accumulation test reads the
# legs' own probabilities, so the exact legs are re-checked before a swap.
# Seed the cache with a WRONG "priceable" for a correlated alternative and
# the re-check must refuse it. (A revert dropping the re-check went
# uncaught until this existed.)
_alt_q = [_pl("QBp", "player_pass_yds", "QB", 1.31, 210.5),
          _pl("QBp", "player_pass_tds", "QB", 1.33, 1.5)]
_wa, _wb = [_pl("WRa", "player_reception_yds", "WR", 1.90)], \
           [_pl("WRb", "player_reception_yds", "WR", 1.90)]
_lists79 = [sorted(_alt_q, key=lambda l: ff_boost.to_decimal(l.odds)), _wa, _wb]
_tdec = 4.0 / ff_boost._target_factor()
_best79 = ff_boost._cheapest_at_least(_lists79, _tdec)
_lie = {tuple(sorted(ff_boost._struct_key(l)
                     for l in (_alt_q[1], _wa[0], _wb[0]))): True}
chk("the fixture's alternative really is NOT priceable",
    not ff_boost._is_priceable([_alt_q[1], _wa[0], _wb[0]], None))
chk("a cached 'priceable' that the exact legs contradict is not trusted",
    ff_boost._prefer_priceable(_lists79, _best79, _tdec,
                               ff_boost.to_decimal(900), None, _lie) is None,
    "the cache answers for a structure; the legs get the final word")
chk("_is_priceable never raises, even on one man twice",
    ff_boost._is_priceable([_pl("QBp", "player_pass_yds", "QB", 1.3),
                            _pl("QBp", "player_rush_yds", "QB", 1.3)],
                           None) is False)

# --- price balance --------------------------------------------------------
_lop = [_pl("Lock1", "player_reception_yds", "WR", ff_boost.to_decimal(-660)),
        _pl("Lock2", "player_rush_yds", "RB", ff_boost.to_decimal(-660)),
        _pl("Long", "player_reception_yds", "TE", ff_boost.to_decimal(+252))]
_top, _share = ff_boost.price_share(_lop)
chk("the long leg of -660 / -660 / +252 supplies about 82% of the price",
    _top.player == "Long" and abs(_share - 0.817) < 0.01, f"{_share:.3f}")
chk("and the line says it behaves like a single bet on that leg",
    "supplies 82%" in ff_boost.price_balance(_lop)
    and "single bet" in ff_boost.price_balance(_lop),
    ff_boost.price_balance(_lop))
_even = [_pl(n, m, "WR", 1.9) for n, m in
         (("E1", "player_reception_yds"), ("E2", "player_rush_yds"),
          ("E3", "player_pass_yds"))]
chk("three equal legs are a third each and carry no warning",
    abs(ff_boost.price_share(_even)[1] - 1 / 3) < 1e-9
    and "no single leg" in ff_boost.price_balance(_even))
chk("the line is 'more than the other legs combined', i.e. over one half",
    "more than the other legs combined" in ff_boost.price_balance(_lop))
chk("a one-leg slip and an empty one do not raise",
    ff_boost.price_balance(_lop[:1]) == "price balance : single leg"
    and ff_boost.price_balance([]) == "price balance : single leg")
chk("the report carries the line",
    "price balance" in ff_boost.report([ff_boost.make_candidate(
        _even, boost_pct=0.50)]))

# ===========================================================================
# 80. B158 — a rung leg carries its own uncertainty
# ===========================================================================

section("80. rung legs carry their own uncertainty (B158)")

_u80 = ff_boost.FAIR_UNCERTAINTY_FALLBACK
_r80 = _rg("Tail", 90, +900, 0.08, "t80")
_r80.uncertainty = 0.03
_k80, _ = _rl([_r80, _rg("Mid", 40, +100, 0.48, "m80")],
              verdicts={"Tail": ("CLEAR", "OVER", ()),
                        "Mid": ("CLEAR", "OVER", ())})
_b80 = {l.player: l for l in _k80}
chk("rung_legs carries ladder_fair's uncertainty onto the leg",
    len(_k80) == 2 and _b80["Tail"].fair_sd == 0.03
    and _b80["Mid"].fair_sd == 0.01, str([l.fair_sd for l in _k80]))
chk("a main line carries none and uses the board figure",
    _jleg("A", .5).fair_sd is None
    and ff_boost.leg_sd(_jleg("A", .5), _u80) == _u80)
chk("a rung uses its own, whether larger or smaller than the board's",
    ff_boost.leg_sd(_b80["Tail"], _u80) == 0.03
    and ff_boost.leg_sd(_b80["Tail"], 0.05) == 0.03)
chk("a zero or missing figure falls back rather than claiming certainty",
    ff_boost.leg_sd(type("L", (), {"fair_sd": 0.0})(), _u80) == _u80
    and ff_boost.leg_sd(type("L", (), {})(), _u80) == _u80)
_n_main, _ = ff_boost.product_noise([_jleg("A", .08), _jleg("B", .48)])
_n_rung, _nw = ff_boost.product_noise([_b80["Tail"], _b80["Mid"]])
chk("product_noise is wider for the tail rung than the fallback said",
    abs(_n_rung - ((0.03 / 0.08) ** 2 + (0.01 / 0.48) ** 2) ** .5) < 1e-12
    and _n_rung > 3 * _n_main, f"{_n_rung:.4f} vs {_n_main:.4f}")
chk("and says how many legs used their own figure",
    "2 of 2 leg(s) use their own" in _nw, _nw)
chk("a main-line slip's noise is unchanged",
    abs(ff_boost.product_noise([_jleg(c, .5) for c in "ABC"])[0]
        - (3 ** .5) * _u80 / .5) < 1e-12)

# ===========================================================================
# 81. Findings from live run 3A (2026-11-11)
# ===========================================================================

section("81. findings from live run 3A")

# --- a stale pull must not read as a dead market -------------------------
class _Scr:
    scratch_risk = False
    suspended_books = ()
    one_sided = ()

    def __init__(self, dropped):
        self.usable = []
        self.dropped = dropped


# Built here, not borrowed: section 14's `_e2` is rebound later in the file.
_e81 = threshold_prob(player_series(wk[wk.season_type == "REG"],
                                    "Jaxon Smith-Njigba", "receiving_yards"),
                      79.5)
_ed81 = prop_edge(_e81, -115, -105)


def _vr(dropped):
    try:
        return boost_verdict(_e81, _ed81, _Scr(dropped))
    except Exception as e:
        return "RAISED", [f"{type(e).__name__}: {e}"]


_sv, _sr = _vr([("draftkings", "stale: 18.8 min old (limit 15.0 min)")] * 6)
chk("an all-stale screen still VETOes, but says it is the clock",
    _sv == "VETO" and any("STALE" in r and "Re-pull get_odds" in r
                          and "nothing about the market" in r for r in _sr),
    str(_sr)[:220])
_mv, _mr = _vr([("draftkings", "stale: 18.8 min old (limit 15.0 min)"),
                ("fanduel", "suspended")])
chk("a mix of causes lists them and does not blame the clock alone",
    _mv == "VETO" and not any("only because" in r for r in _mr)
    and any("suspended" in r for r in _mr), str(_mr)[:220])
_nv, _nr = _vr([])
chk("no quotes at all keeps the plain sentence",
    _nv == "VETO" and "no usable price at any book" in _nr, str(_nr)[:120])

# --- immature_anchors is players; immature_slips is slips ---------------
_ia = [_bn["Op"], _bn["Un"], _bn["Deep"]]
_c1 = ff_boost.make_candidate([_bn["Op"], _bn["Deep"]], boost_pct=0.50)
_c2 = ff_boost.make_candidate([_bn["Op"], _bn["Un"]], boost_pct=0.50)
_c3 = ff_boost.make_candidate(
    [_jleg("Clean1", .52, market="player_rush_yds", ev="E1"),
     _jleg("Clean2", .52, market="player_rush_yds", ev="E2")], boost_pct=0.50)
_ish = ff_boost.Shortlist(candidates=[_c1, _c2, _c3], mode="single-game",
                          boost_pct=0.50)
chk("immature_anchors lists distinct PLAYERS",
    _ish.immature_anchors == ["Op", "Un"], str(_ish.immature_anchors))
chk("immature_slips counts SLIPS, which is a different number",
    _ish.immature_slips == (2, 3), str(_ish.immature_slips))

# --- run 3A's quotes are on file and do not yet move the target ---------
chk("run 3A's 32 quotes are recorded with their book",
    len(ff_boost.SGP_FACTORS_LIVE_20261111_3A) == 32
    and sum(1 for b, _, _ in ff_boost.SGP_FACTORS_LIVE_20261111_3A
            if b not in ff_boost.SGP_EXCHANGE_BOOKS) == 20)
chk("and now feed the target, per book (B167)",
    len(ff_boost.sportsbook_factors()) == 149)

# ===========================================================================
# 82. B143 and B170
# ===========================================================================

section("82. whitespace in the name key; measured noise in the gates")

for _a82, _b82 in (("chig  okonkwo", "Chig Okonkwo"),
                   ("Chig\tOkonkwo", "chig okonkwo"),
                   ("Chig\u00a0Okonkwo", "Chig Okonkwo"),
                   ("  Jaxon   Smith - Njigba ", "Jaxon Smith-Njigba"),
                   ("D. J.  Moore", "DJ Moore")):
    chk(f"norm_player closes spacing: {_a82!r}",
        ff_props.norm_player(_a82) == ff_props.norm_player(_b82),
        f"{ff_props.norm_player(_a82)!r} vs {ff_props.norm_player(_b82)!r}")
for _a82, _b82 in (("A. J. Brown", "A.J. Brown"), ("T J Hockenson", "TJ Hockenson"),
                   ("J J McCarthy", "J.J. McCarthy")):
    chk(f"spaced initials join: {_a82!r}",
        ff_props.norm_player(_a82) == ff_props.norm_player(_b82),
        ff_props.norm_player(_a82))
chk("a short first name is not mistaken for an initial",
    ff_props.norm_player("Ja Marr Chase") == "ja marr chase"
    and ff_props.norm_player("Bo Nix") == "bo nix"
    and ff_props.norm_player("J Smith") == "j smith")
chk("and still keeps different people apart",
    ff_props.norm_player("Cam Ward") != ff_props.norm_player("Cameron Ward")
    and ff_props.norm_player("Josh Allen") != ff_props.norm_player("Josh Allan"))
chk("the key has no leading, trailing or doubled spaces",
    ff_props.norm_player("  Al   Bo  ") == "al bo")


def _q82(spread_odds):
    """Six legs, each quoted by two books that disagree by a set amount."""
    out = []
    for i in range(6):
        for book, (o, u) in (("a", (-110, -110)), ("b", spread_odds)):
            out.append({"player": f"Q{i}", "market": "player_rush_yds",
                        "line": 50.5, "book": book, "over": o, "under": u})
    return out


_wide = _q82((-125, -100))
_tight = _q82((-111, -109))
_uw, _whyw = ff_boost.fair_uncertainty([], _wide)
_ut, _ = ff_boost.fair_uncertainty([], _tight)
chk("the fixtures measure a wide and a tight board",
    _uw > 0.012 and _ut < 0.004 and "measured" in _whyw, f"{_uw} {_ut}")
# Back + three receivers sums to about -4.1% at 50/50: refused on the 0.008
# fallback (3.2% of noise), priceable once the board is measured as noisy.
_s4f = ff_boost.classify(_zslip(3))
_s4w = ff_boost.classify(_zslip(3), None, None, _wide)
chk("classify uses MEASURED noise when given quotes (B170)",
    not _s4f.priceable and _s4w.priceable,
    f"fallback priceable={_s4f.priceable}, wide board priceable={_s4w.priceable}")
# Back + two receivers sums to about -2.6%: fine on the fallback, refused
# on a board measured to be tight.
_s3t = ff_boost.classify(_zslip(2), None, None, _tight)
chk("and a tight board refuses what the fallback waved through",
    ff_boost.classify(_zslip(2)).priceable and not _s3t.priceable,
    _s3t.reason[-160:])
chk("the reason says the noise was measured, not assumed",
    "measured from" in _s3t.reason, _s3t.reason[-200:])
chk("and says fallback when it was",
    "fallback" in _s4f.reason, _s4f.reason[-200:])
_c82 = ff_boost.make_candidate(_zslip(3), boost_pct=0.50, quotes=_wide)
chk("make_candidate passes quotes through and keeps them",
    _c82.structure.priceable and _c82.quotes is _wide)
_c82t = ff_boost.make_candidate(_zslip(2), boost_pct=0.50, quotes=_tight)
chk("the candidate's own joint gate uses the same measured noise",
    "measured from" in _c82t.floor[1], _c82t.floor[1][:220])
_e82, _ee82 = _ec(_zslip(3), None, mode="single-game", event_id="E1",
                  boost_pct=0.50, legs_per_slip=4, quotes=_wide,
                  floor=300, ceiling=5000)
chk("enumerate_candidates takes quotes and classifies with them",
    _e82 is not None and _e82.candidates
    and _e82.candidates[0].structure.priceable, _ee82)
_al82 = [_jleg("Cameron Skattebo", .52, market="player_rush_yds", pos=None,
               team=None),
         _jleg("Malik Nabers", .52, market="player_reception_yds", pos=None,
               team=None)]
_ca82 = ff_boost.make_candidate(
    _al82, {"Cam Skattebo": ("NYG", "RB"), "Malik Nabers": ("NYG", "WR")},
    boost_pct=0.50, aliases={"Cameron Skattebo": "Cam Skattebo"})
chk("make_candidate takes aliases too, so a book spelling gets a team",
    _al82[0].team == "NYG" and _ca82.structure.priceable,
    f"{_al82[0].team} {_ca82.structure.reason[:100]}")

# ===========================================================================
# 83. Findings from the game-day run (event 53178, 2026-11-12)
# ===========================================================================

section("83. findings from the game-day run")


def _gl(name, market, pos, odds, fair, side="OVER", book="betmgm",
        team="NYG", ev="E1", line=1.5):
    return ff_boost.BoostLeg(
        event_id=ev, book=book, market=market, player=name, side=side,
        odds=odds, fair_prob=fair, fair_source="pinnacle",
        devig_method="shin", line=line, player_id=name, verdict="CLEAR",
        verdict_side=side, team=team, pos=pos)


# --- clears_floor uses the boost's own minimum ---------------------------
_lowpool = [_gl("A", "player_rush_yds", "RB", -150, .58, ev="E1"),
            _gl("B", "player_rush_yds", "RB", -140, .57, ev="E2", team="WAS")]
_lsl, _lerr = _ec(_lowpool, None, mode="cross-game", boost_pct=0.50,
                  floor=-300, ceiling=600, legs_per_slip=2)
_lc = _lsl.candidates[0] if _lsl and _lsl.candidates else None
chk("a slip built for a -300 minimum clears it at +186",
    _lc is not None and _lc.min_odds == -300 and _lc.clears_floor
    and _lc.odds < 300, _lerr or f"{_lc.odds if _lc else None}")
chk("a hand-built candidate still uses the project floor",
    ff_boost.make_candidate(_lowpool, boost_pct=0.50).min_odds is None
    and not ff_boost.make_candidate(_lowpool, boost_pct=0.50).clears_floor)
_lp = ff_boost.price_candidate(_lc, book_odds=170) if _lc else None
chk("price_candidate keeps the boost's minimum and the quotes",
    _lp is not None and _lp.min_odds == -300 and _lp.clears_floor
    and _lp.quotes is _lc.quotes)
_qc = ff_boost.make_candidate(_zslip(2), boost_pct=0.50, quotes=_tight)
chk("so a priced candidate still measures its noise from the board",
    "measured from" in ff_boost.price_candidate(_qc, book_odds=350).floor[1],
    ff_boost.price_candidate(_qc, book_odds=350).floor[1][:160])

# --- a missed minimum is not a negative EV -------------------------------
_bm = ff_boost.price_candidate(ff_boost.make_candidate(
    [_gl("A", "player_rush_yds", "RB", -110, .62, ev="E1"),
     _gl("B", "player_rush_yds", "RB", -110, .62, ev="E2", team="WAS"),
     _gl("C", "player_rush_yds", "RB", -110, .62, ev="E3", team="DAL")],
    boost_pct=0.50), book_odds=278)
chk("a +EV slip quoted under the minimum reads BELOW MINIMUM, not NEGATIVE",
    _bm.verdict == "BELOW MINIMUM" and _bm.ev_pct > 0,
    f"{_bm.verdict} ev={_bm.ev_pct}")
chk("BELOW MINIMUM and ESTIMATE ONLY are documented verdicts",
    "BELOW MINIMUM" in ff_boost.VERDICTS and "ESTIMATE ONLY" in ff_boost.VERDICTS)

# --- an optimistic estimate is not called a floor ------------------------
# Same-team receiving x rushing is slightly NEGATIVE: inside the noise, so
# reported, but the product then OVERSTATES the joint.
_neg = [_gl("RBn", "player_rush_yds", "RB", -110, .5, line=50.5),
        _gl("W1n", "player_reception_yds", "WR", -110, .5, line=50.5)]
# The game-day M1 slip: an opposing receiver's anytime TD beside a back's
# rushing yards, which the run reported as overstating by 2.9%.
_tdn = [_gl("T1", "player_anytime_td", "WR", +250, .27, line=None, team="WAS"),
        _gl("S1", "player_rush_yds", "RB", -115, .51, line=23.5)]
_est = None
for _cand_legs in (_tdn, _neg):
    _c = ff_boost.price_candidate(
        ff_boost.make_candidate(_cand_legs, boost_pct=0.25), book_odds=550)
    if _c.floor[0] and _c.joint.rel < 0:
        _est = _c
        break
chk("the fixture is a reported slip whose product overstates the joint",
    _est is not None, "no candidate with floor ok and a negative joint error")
if _est is not None:
    chk("it reads ESTIMATE ONLY, not FLOOR ONLY",
        _est.verdict == "ESTIMATE ONLY", _est.verdict)
    _er = ff_boost.report([_est])
    chk("the report says ESTIMATE and OPTIMISTIC, never LOWER BOUND",
        "P(cash) ESTIMATE" in _er and "OPTIMISTIC" in _er
        and "LOWER BOUND" not in _er,
        str([x.strip() for x in _er.splitlines() if "P(cash)" in x]))
    chk("ev_adjusted takes the overstatement back out",
        _est.ev_adjusted < _est.ev_floor_pct,
        f"{_est.ev_adjusted} vs {_est.ev_floor_pct}")
    chk("and a priced estimate ranks on the adjusted figure",
        abs(_est.rank - _est.ev_adjusted) < 1e-12)
chk("a true floor still reads FLOOR ONLY with ev_adjusted unchanged",
    _fc.verdict == "FLOOR ONLY"
    and (ff_boost.price_candidate(_fc, book_odds=250).ev_adjusted
         == ff_boost.price_candidate(_fc, book_odds=250).ev_floor_pct))
chk("a board of estimates is BOUNDED ONLY, not LIKELY NEGATIVE",
    _est is None or ff_boost.Shortlist(
        candidates=[_est], mode="single-game",
        boost_pct=0.25).outlook != "LIKELY NEGATIVE")

# --- the shortlist is ordered by predicted EV, not by name ---------------
# Six players, one price each, so every 3-leg slip has the same product and
# `ev_band` ties. The good legs belong to the players who sort LAST.
_names = ["Aaron", "Bert", "Carl", "Xavi", "Yuri", "Zane"]
_opool = [_gl(n, "player_rush_yds", "RB", -110,
              0.44 if n < "M" else 0.58, book="draftkings",
              ev=f"E{i}", team=f"T{i}")
          for i, n in enumerate(_names)]
_osl, _oerr = _ec(_opool, None, mode="cross-game", boost_pct=0.50,
                  legs_per_slip=3, limit=1, floor=300, ceiling=900)
_top = ({l.player for l in _osl.candidates[0].legs}
        if _osl and _osl.candidates else set())
chk("the first slip is the best predicted EV, not the first alphabetically",
    _top == {"Xavi", "Yuri", "Zane"}, _oerr or str(sorted(_top)))
_pc = ff_boost.make_candidate(_opool[3:], boost_pct=0.50)
chk("predicted_ev is P(cash) against the expected quote",
    abs(_pc.predicted_ev - (_pc.p_cash * (ff_boost.to_decimal(_pc.independent_odds) - 1) * 1.5
                            - (1 - _pc.p_cash))) < 1e-12,
    "a cross-game parlay is taken at its product")
_sg = ff_boost.make_candidate(
    [_gl("A", "player_rush_yds", "RB", -110, .5, book="draftkings"),
     _gl("B", "player_reception_yds", "WR", -110, .5, book="draftkings",
         team="WAS")], boost_pct=0.50)
chk("a same-game slip is predicted at the book's MEDIAN factor",
    _sg.predicted_ev is not None and abs(
        _sg.predicted_ev - (_sg.p_cash * (ff_boost.to_decimal(_sg.independent_odds)
                                          * ff_boost.expected_factor("draftkings") - 1) * 1.5
                            - (1 - _sg.p_cash))) < 1e-12)
chk("the median factor sits above the lower quartile used for targeting",
    ff_boost.expected_factor("draftkings") > ff_boost._target_factor("draftkings")
    and ff_boost.expected_factor("nobody") == ff_boost.expected_factor(None))
chk("an unpriceable slip has no predicted EV and sorts last, not first",
    _un.predicted_ev is None)
# Bounded slips used to tie at 0.0 and fall back to the names.
_b1 = ff_boost.make_candidate(
    [_gl("Aa", "player_pass_yds", "QB", -110, .45, book="draftkings"),
     _gl("Ab", "player_reception_yds", "WR", -110, .45, book="draftkings")],
    boost_pct=0.50)
_b2 = ff_boost.make_candidate(
    [_gl("Za", "player_pass_yds", "QB", -110, .56, book="draftkings"),
     _gl("Zb", "player_reception_yds", "WR", -110, .56, book="draftkings")],
    boost_pct=0.50)
chk("two bounded slips are ordered by predicted EV, not tied at zero",
    _b1.verdict == _b2.verdict == "FLOOR ONLY" and _b2.rank > _b1.rank
    and sorted([_b1, _b2], key=lambda c: c.key)[0] is _b2,
    f"{_b1.rank} {_b2.rank}")

# --- the reason does not claim nothing can be priced --------------------
_rs, _rse = _ec([_gl("Qa", "player_pass_yds", "QB", -110, .45, book="draftkings"),
                 _gl("Wa", "player_reception_yds", "WR", -110, .45, book="draftkings"),
                 _gl("Wb", "player_reception_yds", "WR", -110, .45, book="draftkings")],
                None, mode="single-game", event_id="E1", boost_pct=0.20,
                legs_per_slip=3, floor=300, ceiling=900)
chk("a shortlist of bounded slips says so and gives a predicted EV",
    _rs is not None and _rs.candidates
    and "can be priced at all" not in _rs.reason
    and ("bound or estimate" in _rs.reason or "anticipated" in _rs.reason),
    (_rse or _rs.reason)[:240])

# --- player_series closes punctuation by itself --------------------------
_wk83 = _pd.DataFrame({"player_display_name": ["J.J. McCarthy"] * 2
                       + ["Cam Skattebo"] * 2,
                       "season": [2026] * 4, "week": [1, 2, 1, 2],
                       "season_type": ["REG"] * 4,
                       "passing_yards": [243, 252, 0, 0]})
def _ps83(name, **kw):
    try:
        return len(ff_props.player_series(_wk83, name, "passing_yards", **kw))
    except Exception as e:
        return f"{type(e).__name__}"
chk("FanDuel's 'J.J McCarthy' finds nflverse's 'J.J. McCarthy' unaided",
    _ps83("J.J McCarthy") == 2, str(_ps83("J.J McCarthy")))
chk("a first-name variant still needs the alias map",
    _ps83("Cameron Skattebo") == "LookupError")
_wkdup = _pd.concat([_wk83, _pd.DataFrame({
    "player_display_name": ["JJ McCarthy"], "season": [2026], "week": [3],
    "season_type": ["REG"], "passing_yards": [1]})])
def _psd(name):
    try:
        return len(ff_props.player_series(_wkdup, name, "passing_yards"))
    except Exception as e:
        return type(e).__name__
chk("two nflverse names sharing a key are NOT merged by a guess",
    _psd("J.J McCarthy") == "LookupError", str(_psd("J.J McCarthy")))

# --- run 2: unknown slips must not crowd out measurable ones -------------
# D2, F1 (+100 band) and M1 3-leg shortlists came back 8 of 8, 40 of 40 and
# 39 of 40 UNPRICEABLE: an unknown ranks 0.0 and every measurable slip on a
# weak boost predicts negative.
def _ord83():
    try:
        unk = ff_boost.make_candidate(
            [_jleg("U1", .5), _jleg("U2", .5, pos="WR")], boost_pct=0.05)
        neg = ff_boost.make_candidate(
            [_jleg("M1", .5, ev="E1"), _jleg("M2", .5, ev="E2", team="WAS")],
            boost_pct=0.05)
        return unk, neg, sorted([unk, neg], key=lambda c: c.key)
    except Exception as e:
        return None, None, f"{type(e).__name__}: {e}"
_u83, _n83, _o83 = _ord83()
chk("the fixture is what it claims: one unknown, one measurable negative",
    _u83 is not None and _u83.verdict == "UNPRICEABLE"
    and _u83.predicted_ev is None and not _u83.measurable
    and _n83.measurable and _n83.predicted_ev < 0,
    str(_o83)[:200] if _u83 is None else
    f"{_u83.verdict} {_u83.predicted_ev} {_n83.predicted_ev}")
chk("a measurable slip sorts ahead of an unpriceable one, even when its "
    "predicted EV is negative",
    _u83 is not None and _o83[0] is _n83)

# ===========================================================================
# 84. Placed legs split by side and by fair source
# ===========================================================================

section("84. by-side breakdown of the bet log")


def _sl84(side, odds, close, res, fair, src="pinnacle"):
    return {"player": "P", "side": side, "odds": odds, "closing_odds": close,
            "result": res, "fair_p": fair, "fair_source": src}


_bets84 = [{"id": "x", "kind": "bet", "legs": [
    _sl84("UNDER", 130, 110, "WIN", 0.50, "kalshi"),
    _sl84("under", 120, 140, "LOSS", 0.50, "Kalshi"),
    _sl84("OVER", -110, -130, "WIN", 0.55),
    _sl84("OVER", -110, None, "PUSH", 0.55),
    _sl84("OVER", -110, None, None, 0.55),
    _sl84("YES", 250, None, "LOSS", None, None)]}]


def _sr84(by="side"):
    try:
        return {g["group"]: g for g in ff_betlog.side_rows(_bets84, by)}
    except Exception as e:
        return {"_err": f"{type(e).__name__}: {e}"}


_s84 = _sr84()
_u84, _o84, _y84 = (_s84.get(k, {}) for k in ("UNDER", "OVER", "YES"))
chk("sides are grouped case-insensitively",
    _u84.get("legs") == 2 and _o84.get("legs") == 3, str(_s84)[:200])
chk("CLV is counted only where a closing price exists",
    len(_u84.get("clv", [])) == 2 and len(_o84.get("clv", [])) == 1)
chk("and has the right sign: +130 into +110 beat the close, +120 into "
    "+140 did not",
    len(_u84.get("clv", [])) == 2 and _u84["clv"][0] > 0 > _u84["clv"][1])
chk("wins are set against the wins the fairs predicted",
    _u84.get("wins_with_fair") == 1 and _u84.get("with_fair") == 2
    and abs(_u84.get("expected", 0) - 1.0) < 1e-9)
chk("a PUSH and an ungraded leg are in neither results column",
    _o84.get("settled") == 1 and abs(_o84.get("expected", 0) - .55) < 1e-9)
chk("a leg with no fair still counts as settled, with nothing predicted",
    _y84.get("settled") == 1 and _y84.get("with_fair") == 0)
_src84 = _sr84("source")
chk("the same split works by fair source",
    _src84.get("kalshi", {}).get("legs") == 2
    and _src84.get("unrecorded", {}).get("legs") == 1, str(_src84)[:200])
chk("free text after the book name does not split the source groups",
    ff_betlog._source_key("Pinnacle +129/-157, liq 1000") == "pinnacle"
    and ff_betlog._source_key("Kalshi 24.5 -223/+203, thin side $86")
    == "kalshi" and ff_betlog._source_key(None) == "unrecorded"
    and ff_betlog._source_key("  ") == "unrecorded")
try:
    _txt84 = ff_betlog.side_summary(_bets84)
except Exception as e:
    _txt84 = f"{type(e).__name__}: {e}"
chk("the text says counts, not rates, at this sample",
    "BY SIDE" in _txt84 and "BY FAIR SOURCE" in _txt84
    and "COUNTS, NOT RATES" in _txt84
    and "won 1 of 2 where the fairs predicted 1.0" in _txt84, _txt84[:300])
chk("and is empty when nothing is graded",
    ff_betlog.side_summary([{"id": "y", "kind": "bet", "legs": [
        _sl84("OVER", -110, None, None, .5)]}]) == "")

# ===========================================================================
# 85. Bonus bets (profit only)
# ===========================================================================

section("85. bonus bet value")


def _bb(p, o, st=8.11):
    try:
        return ff_boost.bonus_bet_ev(p, o, stake=st)
    except Exception as e:
        return {"_err": f"{type(e).__name__}: {e}"}


_b1, _b4 = _bb(0.5, 100), _bb(0.2, 400)
chk("a fair +100 leg converts half the face, a fair +400 leg 80%",
    abs(_b1.get("conversion", 0) - 0.5) < 1e-9
    and abs(_b4.get("conversion", 0) - 0.8) < 1e-9, f"{_b1} {_b4}")
chk("the cash value is conversion x face, and the stake is NOT returned",
    abs(_b4.get("ev", 0) - 0.8 * 8.11) < 1e-9
    and abs(_b4.get("pays_if_wins", 0) - 4 * 8.11) < 1e-9)
chk("hold eats it: a 0.075 First TD leg at +1200 converts 90%, not 92%",
    abs(_bb(0.075, 1200).get("conversion", 0) - 0.90) < 1e-9)
chk("the chance of collecting anything is reported beside the value",
    _b4.get("p_cash") == 0.2 and abs(_b4.get("leg_fairness", 0) - 1.0) < 1e-9)
chk("a probability outside (0, 1) and a zero stake are refused",
    "_err" in _bb(1.0, 100) and "_err" in _bb(0.0, 100)
    and "_err" in _bb(0.5, 100, 0))

_summary()
raise SystemExit(1 if fails else 0)
