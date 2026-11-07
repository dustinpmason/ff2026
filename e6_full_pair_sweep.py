#!/usr/bin/env python3
"""Every {PASS, RUSH, RECV} x {same team, opposing} pair, measured once.

`_pair_r` resolves a pair from the market side (MARKET_SIDE) and the team.
With three sides and two team relations there are 12 ordered combinations and
9 that can actually occur in a slip. The measured table covers four of them;
E6 measured three more on 2026-11-05/06. That left FIVE unmeasured, and
several are common slip shapes — a back's rushing yards with a teammate
receiver's, two opposing quarterbacks in a shootout, two opposing receivers.

Closing the gate on an unmeasured pair is correct but useless if it refuses
half the real slips, so this measures all of them in one pass rather than
converting a silent wrong answer into a loud refusal.

Reports, for each pair:
  * continuous r of the z-scored stat
  * joint threshold crossing LIFT, which is what an SGP actually prices
  * n

The CONTROL is the admissibility gate: this method must recover something
near the table's +0.31 on same-team QB x WR/TE, or none of the other numbers
mean anything. A failed control voids the run.

    python3 measurements/e6_full_pair_sweep.py
"""
import sys, pathlib
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
MIN_PAIRS = 200

# side -> (positions carrying that market, the nflverse stat column)
SIDE = {"PASS": (["QB"], "passing_yards"),
        "RUSH": (["RB"], "rushing_yards"),
        "RECV": (["WR", "TE"], "receiving_yards")}


def _z(wk, positions, col):
    """Per-season z-score of `col` for the given positions."""
    out = wk[wk.position.isin(positions)].copy()
    out["v"] = pd.to_numeric(out[col], errors="coerce").fillna(0)
    g = out.groupby(["season", "player_id"])["v"]
    out["n"], out["mu"], out["sd"] = (g.transform("size"), g.transform("mean"),
                                      g.transform("std"))
    out = out[(out.n >= MIN_GAMES) & (out.sd > 0)].copy()
    out["z"] = (out.v - out.mu) / out.sd
    return out[["game", "team", "opponent_team", "player_id", "z", "v", "mu"]]


def _pairs(a, b, same_team, same_side):
    """Join two side-frames into pairs within one game."""
    if same_team:
        m = a.merge(b, on=["game", "team"], suffixes=("", "_2"))
    else:
        m = a.merge(b, left_on=["game", "team"],
                    right_on=["game", "opponent_team"], suffixes=("", "_2"))
    # A player is never his own pair. When both sides draw from the same
    # position pool, the unordered pair would otherwise appear twice.
    m = m[m.player_id != m.player_id_2]
    if same_side:
        m = m[m.player_id < m.player_id_2]
    return m


def _stats(m):
    if len(m) < MIN_PAIRS:
        return None
    r = np.corrcoef(m.z, m.z_2)[0, 1]
    A = (m.v > m.mu).values
    B = (m.v_2 > m.mu_2).values
    pa, pb, joint = A.mean(), B.mean(), (A & B).mean()
    return {"n": len(m), "r": r, "lift": joint / (pa * pb),
            "phi": np.corrcoef(A.astype(float), B.astype(float))[0, 1]}


def main() -> None:
    wk = prepare(load_weekly(SEASONS), load_pbp(SEASONS))
    wk = wk[wk.season_type == "REG"].copy()
    wk["game"] = (wk.season.astype(str) + "-" + wk.week.astype(str) + "-"
                  + np.where(wk.team < wk.opponent_team,
                             wk.team + wk.opponent_team,
                             wk.opponent_team + wk.team))
    frames = {k: _z(wk, pos, col) for k, (pos, col) in SIDE.items()}
    print(f"seasons {SEASONS}, min {MIN_GAMES} games per player-season, "
          f"min {MIN_PAIRS} pairs to report\n")

    # Control first. If it fails, nothing else is admissible, so say so and
    # stop rather than printing numbers that cannot be used.
    ctl = _stats(_pairs(frames["PASS"], frames["RECV"], True, False))
    if ctl is None or not 0.15 <= ctl["r"] <= 0.50:
        print("CONTROL FAILED or not measurable — same-team QB x WR/TE "
              f"recovered {ctl and round(ctl['r'], 4)} against the table's "
              f"+0.31.")
        print("The method does not reproduce a pair the table claims to "
              "know. VOID: change nothing on this run.")
        return
    print(f"CONTROL PASSED: same-team PASS x RECV r={ctl['r']:+.4f} "
          f"(table +0.31), lift {ctl['lift']:.4f}x, n={ctl['n']:,}\n")

    sides = ["PASS", "RUSH", "RECV"]
    rows = []
    for rel, same_team in (("same team", True), ("opposing", False)):
        print(f"{rel.upper()}")
        for i, sa in enumerate(sides):
            for sb in sides[i:] if same_team else sides:
                if not same_team and sides.index(sb) < i:
                    continue
                m = _pairs(frames[sa], frames[sb], same_team, sa == sb)
                st = _stats(m)
                label = f"  {sa:<5} x {sb:<5}"
                if st is None:
                    print(f"{label}  n={len(m):,} — BELOW {MIN_PAIRS}, "
                          f"NOT MEASURABLE, reporting nothing")
                    rows.append((rel, sa, sb, None))
                    continue
                print(f"{label}  r={st['r']:+.4f}  LIFT {st['lift']:.4f}x  "
                      f"phi={st['phi']:+.4f}  n={st['n']:,}")
                rows.append((rel, sa, sb, st))
        print()

    print("=" * 70)
    print("LIFT is what an SGP prices. Deviation from 1.0 is what matters,")
    print("and the sign of (r) is not always the sign the mechanism suggests.")
    print()
    for rel, sa, sb, st in sorted(
            (r for r in rows if r[3]),
            key=lambda r: -abs(r[3]["lift"] - 1.0)):
        dev = (st["lift"] - 1.0) * 100
        print(f"  {rel:<10} {sa:<5} x {sb:<5}  lift {st['lift']:.4f}x "
              f"({dev:+.2f}%)  r={st['r']:+.4f}  n={st['n']:,}")


if __name__ == "__main__":
    main()
