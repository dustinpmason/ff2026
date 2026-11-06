#!/usr/bin/env python3
"""E6: is a same-team receiver pair really independent for a threshold prop?

`_pair_r` returns `(0.0, "")` — priceable — for two same-team receiving legs,
because SAME_TEAM_CORR only holds QB x WR, QB x TE and QB x RB. E6 recorded
that nobody could establish whether that pair was in B53's 43,228-pair sweep,
so the 0.0 might be a measured zero or an unexamined fall-through. It went
live on a placed bet (2026-11-05, two JAX receivers in one DraftKings SGP),
which is what prompted measuring it.

Answer: effectively independent, very slightly NEGATIVE on crossings.
Run this to re-derive it.

    python3 measurements/e6_same_team_receivers.py
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


def main() -> None:
    wk = prepare(load_weekly(SEASONS), load_pbp(SEASONS))
    wk = wk[wk.season_type == "REG"].copy()
    wk["game"] = (wk.season.astype(str) + "-" + wk.week.astype(str) + "-"
                  + np.where(wk.team < wk.opponent_team,
                             wk.team + wk.opponent_team,
                             wk.opponent_team + wk.team))
    r = wk[wk.position.isin(["WR", "TE"])].copy()
    r["ry"] = pd.to_numeric(r.receiving_yards, errors="coerce").fillna(0)
    g = r.groupby(["season", "player_id"])["ry"]
    r["n"], r["mu"], r["sd"] = (g.transform("size"), g.transform("mean"),
                                g.transform("std"))
    r = r[(r.n >= MIN_GAMES) & (r.sd > 0)].copy()
    r["z"] = (r.ry - r.mu) / r.sd
    a = r[["game", "team", "player_id", "position", "z", "ry", "mu"]]
    m = a.merge(a, on=["game", "team"], suffixes=("", "_2"))
    m = m[m.player_id < m.player_id_2]
    print(f"seasons {SEASONS}, min {MIN_GAMES} games")
    print(f"same-team receiver pairs: {len(m):,}\n")
    print("  continuous correlation of receiving YARDS:")
    for p1, p2 in (("WR", "WR"), ("WR", "TE"), ("TE", "TE")):
        s = m[((m.position == p1) & (m.position_2 == p2))
              | ((m.position == p2) & (m.position_2 == p1))]
        if len(s) < 200:
            continue
        print(f"    {p1} x {p2}: r = {np.corrcoef(s.z, s.z_2)[0, 1]:+.4f}"
              f"  n={len(s):,}")
    # The quantity a parlay actually needs is not the yards correlation but
    # whether BOTH legs cross their line in the same game.
    s = m[(m.position == "WR") & (m.position_2 == "WR")]
    A = (s.ry > s.mu).values
    B = (s.ry_2 > s.mu_2).values
    pa, pb, joint = A.mean(), B.mean(), (A & B).mean()
    print("\n  joint threshold crossing (each vs his own season mean):")
    print(f"    P(A) {pa:.4f}  P(B) {pb:.4f}  independent {pa * pb:.4f}")
    print(f"    observed joint {joint:.4f}  -> LIFT {joint / (pa * pb):.4f}x")
    print(f"    phi = {np.corrcoef(A.astype(float), B.astype(float))[0, 1]:+.4f}")
    print("\n  -> the 0.0 fall-through is a good approximation and very")
    print("     slightly OPTIMISTIC: two same-team receivers cross together")
    print("     a touch less often than independence implies.")


if __name__ == "__main__":
    main()
