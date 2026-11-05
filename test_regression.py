"""Regression suite. Run after any change: `python3 test_regression.py`

Every check here corresponds to a bug that actually shipped. They are not
hypothetical: the explosive-TD check exists because Julian Love was credited
with Jordan Love's touchdowns; the idempotency check because add_shares()
crashed on a second call; the bye check because a partial week made 21 teams
look like they were off.
"""
import warnings; warnings.filterwarnings("ignore")
import atexit, json, pathlib, sys, traceback
import numpy as np, pandas as pd
import ff_data, ff_scoring, ff_props, ff_guillotine, ff_betlog, ff_backtest
import ff_boost
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
import shutil, tempfile
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
                                 _t, _p, 0.5, -110, acted_on=_t != "PASS")
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
    ff_guillotine.players_on_bye(
        9, _meta2, ff_guillotine.team_byes(_wk2[_wk2.season == 2026]))
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
# The observed corruption: json.dumps writes \u2014, transcription unescaped it.
chk("unescaped-unicode corruption is caught",
    not ff_betlog.verify_uploaded(_t2.replace("\\u2014", "\u2014")))
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
chk("a milestone rung IS reported one-sided",
    screen_quotes(_mile, max_age_s=10**9).one_sided == ["draftkings"])
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
        verdict=kw.pop("verdict", "CLEAR"),
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
    any(abs(p[2] - 0.31) < 1e-9 for p in s.pairs), str(s.pairs))

s = classify([leg("QB A", EV1, market="player_pass_yds"),
              leg("TE A1", EV1), leg("WR B1", EV1)], META)
chk("QB + his own TE is correlated (+0.27)",
    s.kind == "same-game-correlated" and any(abs(p[2] - 0.27) < 1e-9
                                             for p in s.pairs), s.kind)

s = classify([leg("QB A", EV1, market="player_pass_yds"),
              leg("RB A1", EV1, market="player_rush_yds"),
              leg("WR B1", EV1)], META)
chk("QB + his own RB is correlated (-0.10), not independent",
    s.kind == "same-game-correlated" and any(abs(p[2] + 0.10) < 1e-9
                                             for p in s.pairs), s.kind)

# The guillotine's correlation_matrix cannot see the schedule, so it treats
# every different-team pair as independent. P0 knows the event, so two backs
# inside one event ARE facing each other and the measured -0.14 applies.
s = classify([leg("RB A1", EV1, market="player_rush_yds"),
              leg("RB B1", EV1, market="player_rush_yds"),
              leg("WR C1", EV2)], META)
chk("opposing RBs inside one event are correlated (-0.14)",
    any(abs(p[2] + 0.14) < 1e-9 for p in s.pairs), str(s.pairs))

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
    any(abs(p[2] - 0.31) < 1e-9 for p in s.pairs), str(s.pairs))

s = classify([leg("QB A", EV1, market="player_pass_yds"),
              leg("TE A1", EV1, market="player_reception_yds"),
              leg("WR B1", EV1)], META)
chk("a TE receiving prop takes the TE coefficient, not the WR one",
    any(abs(p[2] - 0.27) < 1e-9 for p in s.pairs), str(s.pairs))

# The correlation table was measured on YARDS. anytime-TD is a boost staple
# and nobody here has measured it, so independence would be a claim.
s = classify([leg("WR A1", EV1, market="player_anytime_td", line=None),
              leg("WR A2", EV1, market="player_anytime_td", line=None),
              leg("WR B1", EV1)], META)
chk("two same-event anytime-TD legs are NOT asserted independent",
    not s.priceable, f"{s.kind} priceable={s.priceable}")
chk("the unmeasured pair is kept apart from the measured ones",
    s.unmeasured and not s.pairs, f"{s.unmeasured} / {s.pairs}")
chk("the reason says independence would be an assumption",
    "assumption" in s.reason.lower(), s.reason[:90])

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
                  verdict="CLEAR")
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
                 verdict="CLEAR", team="AAA", pos=None)
s = classify([leg("QB A", EV1, market="player_pass_yds"), nopos,
              leg("WR B1", EV1)], {})
chk("a known team with an UNKNOWN position is unmeasurable, not WR",
    not s.priceable and not any(abs(p[2] - 0.31) < 1e-9 for p in s.pairs),
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
    any(abs(p[2] - 0.31) < 1e-9 for p in s_cb.pairs), str(s_cb.pairs))
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
chk("a settled anchor at the same liquidity is NOT flagged",
    not leg("WR A1", EV1, fair_prob=0.5065,
            anchor_liquidity=250).anchor_immature)
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
chk("a settled anchor at the 500 tier is still NOT flagged",
    not leg("WR A1", EV1, fair_prob=0.5065,
            anchor_liquidity=500).anchor_immature,
    "the 0.5000 does the work; liquidity only sets how far the net reaches")

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
    "fell back to the hardcoded" in _sl_fb.describe(),
    _sl_fb.describe()[-90:])

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
                    verdict="CLEAR", team=team, pos=pos)
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
    any(abs(p[2] - 0.20) < 1e-9 for p in s.pairs), f"pairs={s.pairs}")

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
chk("the two SAME_TEAM_CORR copies are still identical",
    ff_guillotine.SAME_TEAM_CORR == ff_boost.SAME_TEAM_CORR,
    f"guillotine {ff_guillotine.SAME_TEAM_CORR} vs boost {ff_boost.SAME_TEAM_CORR}")
chk("the two OPPOSING_CORR copies are still identical",
    ff_guillotine.OPPOSING_CORR == ff_boost.OPPOSING_CORR,
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

_summary()
raise SystemExit(1 if fails else 0)
