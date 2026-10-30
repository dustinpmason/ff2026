"""Regression suite. Run after any change: `python3 test_regression.py`

Every check here corresponds to a bug that actually shipped. They are not
hypothetical: the explosive-TD check exists because Julian Love was credited
with Jordan Love's touchdowns; the idempotency check because add_shares()
crashed on a second call; the bye check because a partial week made 21 teams
look like they were off.
"""
import warnings; warnings.filterwarnings("ignore")
import json, pathlib
import numpy as np, pandas as pd
import ff_data, ff_scoring, ff_props, ff_guillotine, ff_betlog
from ff_data import load_weekly, load_pbp
from ff_scoring import LEAGUES, score, score_all, add_explosive_tds, prepare
from ff_props import (player_series, threshold_prob, prop_edge, usage_trend,
                      role_trend, decline_onset, add_shares, devig,
                      screen_quotes, LONGSHOT_P)

fails = []
def chk(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'  — ' + detail if detail else ''}")
    if not ok: fails.append(name)

print("1. imports")
chk("all four modules import", True)

print("\n2. data layer")
wk = load_weekly(2026); pbp = load_pbp(2026)
chk("weekly 2026", len(wk) > 5000, f"{len(wk)} rows, {len(wk.columns)} cols")
chk("pbp 2026", len(pbp) > 15000, f"{len(pbp)} plays")

print("\n3. scoring engine — all four leagues")
prep = prepare(wk, pbp)
for key, lg in LEAGUES.items():
    s = score(prep, lg)
    chk(f"{key}", s.notna().all() and s.std() > 1,
        f"mean {s.mean():.2f} sd {s.std():.2f} max {s.max():.1f}")

print("\n4. explosive-TD join integrity (GSIS id, not name)")
ex = add_explosive_tds(wk, pbp)
jl = ex[ex.player_display_name.str.contains("Jordan Love", na=False)]
jv = ex[ex.player_display_name.str.contains("Julian Love|Jeremiyah Love", na=False)]
pass_col = [c for c in ex.columns if "pass" in c and "40" in c or "explosive" in c]
tot = jl[pass_col].sum().sum() if pass_col else 0
contam = jv[pass_col].sum().sum() if pass_col else 0
chk("Jordan Love credited", tot > 0, f"{tot:.0f} explosive pass TDs")
chk("no name contamination", contam == 0, f"Julian/Jeremiyah Love credited {contam:.0f}")

print("\n5. props — threshold + stat resolution")
log = player_series(wk[wk.season_type=="REG"], "Jaxon Smith-Njigba", "receiving_yards")
e = threshold_prob(log, 90)
chk("stat read from attrs not last column", log.attrs.get("stat") == "receiving_yards")
chk("probability sane", 0 < e.blended < 1, f"P(90+) = {e.blended:.1%}")

print("\n6. props — de-vig and edge")
o, u, hold = devig(-110, -110)
chk("symmetric devig = 50/50", abs(o - 0.5) < 1e-9, f"over {o:.4f} hold {hold:.3%}")
ed = prop_edge(e, -110, -110)
chk("prop_edge returns", ed is not None, f"edge {ed.edge:+.1%}" if hasattr(ed,"edge") else "")
for bad in (0.0, 1.0, 1.5, -0.1):
    try: prop_edge(e, -110, -110, fair_over=bad); chk(f"B4 rejects fair_over={bad}", False)
    except ValueError: chk(f"B4 rejects fair_over={bad}", True)

print("\n7. props — usage trend verdicts")
sh = add_shares(wk[wk.season_type=="REG"])
seen = set()
for p in ["Jaxon Smith-Njigba","Rhamondre Stevenson","Tony Pollard","Rashee Rice","Travis Kelce"]:
    try:
        t = role_trend(sh, p)
        seen.add(t.verdict); print(f"       {p:24s} {t.verdict}")
    except Exception as ex: print(f"       {p:24s} ERR {ex}")
chk("verdicts produced", len(seen) >= 1, "/".join(sorted(seen)))

print("\n8. bye detection (partial-week guard)")
b = ff_props.bye_weeks(wk)
cnt = pd.Series(list(b.values())).value_counts().sort_index()
chk("no week has >8 byes", (cnt <= 8).all(), str(dict(cnt)))
chk("byes found", len(b) >= 10, f"{len(b)} teams")

print("\n9. guillotine — name resolution + B5")
pool = ff_guillotine.build_pool(wk, LEAGUES["guillotine"])
chk("Mahomes resolves", ff_guillotine.resolve("Patrick Mahomes II", pool) is not None)
chk("garbage does not resolve", ff_guillotine.resolve("Zzz Notaplayer", pool) is None)
chk("_mean_of unresolved is nan", np.isnan(ff_guillotine._mean_of(pool, "Zzz Notaplayer")))
try:
    ff_guillotine.enumerate_lineups({"QB":["Trevor Lawrence"],"RB":["Javonte Williams"]}, pool)
    chk("B5 raises on undersized roster", False)
except ValueError as ex:
    chk("B5 raises on undersized roster", True, str(ex)[:50])

print("\n10. add_shares idempotency (B6)")
once = add_shares(wk[wk.season_type == "REG"])
twice = add_shares(once)
chk("second call does not raise", True)
chk("no _x/_y suffixes", not any(c.endswith(("_x", "_y")) for c in twice.columns))
chk("share values unchanged",
    bool(np.allclose(once["_touch_share"].fillna(-1), twice["_touch_share"].fillna(-1))))
chk("role_trend works on pre-shared frame",
    role_trend(once, "Travis Kelce").verdict != "UNKNOWN")

print("\n11. shin de-vig (P3)")
chk("shin == mult on a balanced market",
    abs(devig(-110, -110, "shin")[0] - devig(-110, -110, "multiplicative")[0]) < 1e-6)
m450, s450 = devig(450, -600, "multiplicative")[0], devig(450, -600, "shin")[0]
chk("shin pulls longshots DOWN", s450 < m450, f"{m450:.2%} -> {s450:.2%}")
chk("shin fair probs sum to 1", abs(sum(devig(450, -600, "shin")[:2]) - 1.0) < 1e-9)
chk("auto picks shin on a longshot",
    abs(devig(450, -600, "auto")[0] - s450) < 1e-12)
chk("auto picks multiplicative near even",
    abs(devig(-110, -110, "auto")[0] - 0.5) < 1e-9)
try: devig(-110, -110, "nonsense"); chk("unknown method raises", False)
except ValueError: chk("unknown method raises", True)
chk("Edge records which de-vig ran",
    prop_edge(e, 450, -600).devig_method == "shin")

print("\n12. live-quote screen (P2)")
import datetime as _dt
_now = _dt.datetime.now(_dt.timezone.utc).timestamp()
_iso = lambda s: _dt.datetime.fromtimestamp(_now - s, _dt.timezone.utc).isoformat()
qs = [{"book": "FanDuel", "last_update": _iso(30)},
      {"book": "DraftKings", "suspended_at": _iso(60)},
      {"book": "BetMGM", "suspended_at": _iso(45)},
      {"book": "Caesars", "suspended_at": _iso(50)},
      {"book": "Pinnacle", "pregame_only": True, "last_update": _iso(20)},
      {"book": "ESPNBet", "last_update": _iso(1800)}]
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

print("\n13. bet log (E2+P6)")
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

print("\n" + ("="*60))
print(f"{'ALL PASS' if not fails else str(len(fails)) + ' FAILURES: ' + ', '.join(fails)}")
raise SystemExit(1 if fails else 0)
