#!/usr/bin/env python3
"""E6, RB half: are two same-team backs really independent for a prop?

`_pair_r` returns `(0.0, "")` — priceable — for two SAME-TEAM running backs,
while two OPPOSING backs get -0.14 and refuse the slip. Same-team backs share
one carry pool, so the fall-through is the one place the table's own logic
argues against itself: if opposing backs are negatively correlated by game
script, teammates splitting a fixed number of carries should be MORE so, not
zero.

E6 recorded that nobody could establish whether same-team RB pairs were in
B53's 43,228-pair sweep, so the 0.0 might be a measured zero or an unexamined
fall-through. The receiving half of E6 was measured 2026-11-05 (WR x WR
r = +0.0090, joint-crossing lift 0.9817x, which moved a placed slip from
+1.83% to -0.04% EV). This is the other half, plus the cross-team
passing x receiving pair that falls through the same way.

Measures three things, because a parlay needs the third:
  1. continuous correlation of the z-scored stat
  2. joint threshold crossing, which is what an SGP actually prices
  3. the same for cross-team PASS x RECV

    python3 measurements/e6_rb_and_cross_pass_recv.py
"""
import sys, pathlib
# Work whether this sits in measurements/ or flat at the repo root — the
# GitHub web uploader flattens folders, and a repo-root copy adding
# `parent.parent` to sys.path points ABOVE the repo and fails to import
# ff_data at all.
_here = pathlib.Path(__file__).resolve().parent
for _cand in (_here, _here.parent):
    if (_cand / "ff_props.py").exists():
        sys.path.insert(0, str(_cand))
        break
else:
    sys.exit(f"cannot find ff_props.py next to or above {_here} — put this "
             f"script in the repo root or in measurements/ under it")
import pandas as pd, numpy as np
from ff_data import load_weekly, load_pbp
from ff_scoring import prepare

SEASONS = [2023, 2024, 2025, 2026]
MIN_GAMES = 6


def _z(df, col):
    """Per-season z-score of `col`, keeping only players with enough games.

    Z-scoring within season is what makes a pair comparable: a back averaging
    90 yards and one averaging 30 are not correlated just because both are
    above zero every week.
    """
    out = df.copy()
    out["v"] = pd.to_numeric(out[col], errors="coerce").fillna(0)
    g = out.groupby(["season", "player_id"])["v"]
    out["n"], out["mu"], out["sd"] = (g.transform("size"), g.transform("mean"),
                                      g.transform("std"))
    out = out[(out.n >= MIN_GAMES) & (out.sd > 0)].copy()
    out["z"] = (out.v - out.mu) / out.sd
    return out[["game", "team", "opponent_team", "player_id", "position",
                "z", "v", "mu"]]


def _report(pairs, label, note):
    if len(pairs) < 200:
        print(f"  {label}: only {len(pairs)} pairs — NOT MEASURABLE, "
              f"reporting nothing")
        return None
    r = np.corrcoef(pairs.z, pairs.z_2)[0, 1]
    A = (pairs.v > pairs.mu).values
    B = (pairs.v_2 > pairs.mu_2).values
    pa, pb, joint = A.mean(), B.mean(), (A & B).mean()
    lift = joint / (pa * pb)
    phi = np.corrcoef(A.astype(float), B.astype(float))[0, 1]
    print(f"  {label}  n={len(pairs):,}")
    print(f"    continuous r      = {r:+.4f}")
    print(f"    P(A) {pa:.4f}  P(B) {pb:.4f}  independent {pa*pb:.4f}")
    print(f"    observed joint    = {joint:.4f}   LIFT {lift:.4f}x")
    print(f"    phi (crossings)   = {phi:+.4f}")
    print(f"    -> {note}")
    print()
    return {"label": label, "n": len(pairs), "r": r, "lift": lift, "phi": phi}


def main() -> None:
    wk = prepare(load_weekly(SEASONS), load_pbp(SEASONS))
    wk = wk[wk.season_type == "REG"].copy()
    wk["game"] = (wk.season.astype(str) + "-" + wk.week.astype(str) + "-"
                  + np.where(wk.team < wk.opponent_team,
                             wk.team + wk.opponent_team,
                             wk.opponent_team + wk.team))
    print(f"seasons {SEASONS}, min {MIN_GAMES} games per player-season\n")
    rows = []

    # ---- 1. SAME-TEAM RB x RB, rushing yards ----------------------------
    rb = _z(wk[wk.position == "RB"], "rushing_yards")
    m = rb.merge(rb, on=["game", "team"], suffixes=("", "_2"))
    m = m[m.player_id < m.player_id_2]
    print("SAME-TEAM RB x RB — rushing yards (the carry-pool question)")
    rows.append(_report(
        m, "RB x RB same team",
        "this is what _pair_r currently prices as 0.0"))

    # ---- 2. OPPOSING RB x RB, for the comparison the table asserts -----
    # The table gives opposing backs -0.14. Measuring it on the same data
    # with the same method is the only way to know whether the same-team
    # number above is small because teammates really are independent, or
    # small because this method understates everything.
    opp = rb.merge(rb, left_on=["game", "team"],
                   right_on=["game", "opponent_team"], suffixes=("", "_2"))
    opp = opp[opp.player_id < opp.player_id_2]
    print("OPPOSING RB x RB — rushing yards (the table says -0.14)")
    rows.append(_report(
        opp, "RB x RB opposing",
        "compare against the table's -0.14 to calibrate the METHOD"))

    # ---- 3. CROSS-TEAM PASS x RECV -------------------------------------
    qb = _z(wk[wk.position == "QB"], "passing_yards")
    rc = _z(wk[wk.position.isin(["WR", "TE"])], "receiving_yards")
    x = qb.merge(rc, left_on=["game", "team"],
                 right_on=["game", "opponent_team"], suffixes=("", "_2"))
    print("CROSS-TEAM QB passing x opposing receiver (falls through to 0.0)")
    rows.append(_report(
        x, "QB pass x opposing RECV",
        "both rise in a shootout, so a positive lift would mean the 0.0 is "
        "optimistic"))

    # ---- 4. SAME-TEAM QB x WR, the one the table DOES carry ------------
    # A control. SAME_TEAM_CORR gives QB x WR +0.31. If this method cannot
    # recover a number near that on a pair the table claims to know, then
    # none of the three numbers above can be trusted either, and the whole
    # run says nothing. This is the check that makes the rest admissible.
    sw = qb.merge(rc, on=["game", "team"], suffixes=("", "_2"))
    print("CONTROL — SAME-TEAM QB x WR/TE (table carries +0.31)")
    ctl = _report(sw, "QB x WR/TE same team",
                  "the method must recover something near +0.31 here or "
                  "nothing above is admissible")
    print("=" * 68)
    if ctl is None:
        print("CONTROL NOT MEASURABLE — treat every number above as void.")
        return
    if not 0.15 <= ctl["r"] <= 0.50:
        print(f"CONTROL FAILED: recovered r={ctl['r']:+.4f} against a table "
              f"value of +0.31.")
        print("The method does not reproduce a pair the table claims to "
              "know, so the")
        print("three fall-through numbers above are NOT evidence about "
              "_pair_r. Do not")
        print("change the table on this run.")
        return
    print(f"CONTROL PASSED: recovered r={ctl['r']:+.4f} on QB x WR/TE "
          f"against the table's +0.31,")
    print("so the method reproduces a known pair and the fall-through "
          "numbers are admissible.")
    print()
    for r in rows:
        if r is None:
            continue
        print(f"  {r['label']:<26} r={r['r']:+.4f}  lift={r['lift']:.4f}x  "
              f"n={r['n']:,}")


if __name__ == "__main__":
    main()
