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
import ff_data, ff_scoring, ff_props, ff_guillotine, ff_betlog
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
from ff_betlog import Leg
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
_pw = wk[wk.season_type == "REG"].groupby("week").team.nunique()
_complete = _pw[_pw >= ff_data.MIN_TEAMS_COMPLETE_WEEK]
_partial = _pw[_pw < ff_data.MIN_TEAMS_COMPLETE_WEEK]
chk("reports the last COMPLETE week, not week.max()",
    f"through Week {int(_complete.index.max())}" in _st,
    f"complete through {int(_complete.index.max())}, "
    f"max week in data is {int(_pw.index.max())}")
if not _partial.empty:
    chk("names the in-progress week instead of hiding it",
        "IN PROGRESS" in _st and
        all(f"Week {int(w)}" in _st for w in _partial.index if w > _complete.index.max()),
        f"partial: {dict(_partial)}")
else:
    chk("no partial week this run — nothing to flag", True)
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
chk("returning player resolves only with the fallback",
    ff_guillotine.resolve("Zach Charbonnet", _p26) is None
    and ff_guillotine.resolve("Zach Charbonnet", _pfb) is not None)
chk("returning player is marked stale",
    ff_guillotine.resolve("Zach Charbonnet", _pfb) in _pfb.stale)
chk("truly-absent player stays unresolved in both",
    ff_guillotine.resolve("De'Zhaun Stribling", _p26) is None
    and ff_guillotine.resolve("De'Zhaun Stribling", _pfb) is None)
_fakeroster = [{"team_id": "9", "team_name": "T",
                "roster": {"RB": ["Zach Charbonnet"],
                           "BN": ["De'Zhaun Stribling"]}}]
chk("stale and unresolved are reported separately",
    ff_guillotine.stale_names(_fakeroster, _pfb) == {"T": ["Zach Charbonnet"]}
    and ff_guillotine.unresolved(_fakeroster, _pfb)
        == {"T": ["De'Zhaun Stribling"]})
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

section("23. native PropLine shape is read correctly (B24)")
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

section("24. Monte Carlo resolution is reported (B20)")
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

_summary()
raise SystemExit(1 if fails else 0)
