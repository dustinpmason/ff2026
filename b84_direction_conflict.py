#!/usr/bin/env python3
"""Reproduce B84's measurement: how often does the SHARE-derived role-change
verdict point the opposite way from the production-relevant COUNT direction?

B88(c). The reviewer of the B84 diff noted that its figures — 264 flagged
changes, 21 conflicts wrong on all 21, 243 agreeing with 2 wrong,
team_volume_ratio 0.42 to 1.98 — appeared in a docstring as a PROSE
ASSERTION with nothing in the repo able to reproduce them. That is D16's
shape: a measurement recorded as a standing claim with no way to re-check
it. This script is the missing artefact. Run it to re-derive the numbers.

    python3 measurements/b84_direction_conflict.py
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
import pandas as pd
from ff_data import load_weekly, load_pbp
from ff_scoring import prepare
import ff_props as P

SEASONS = [2025, 2026]
GROUPS = (("receiving_yards", ("WR", "TE", "RB")),
          ("rushing_yards", ("RB", "QB")),
          ("passing_yards", ("QB",)))


def main() -> None:
    wk = prepare(load_weekly(SEASONS), load_pbp(SEASONS))
    wk = wk[wk.season_type == "REG"]
    rows = []
    for stat, pos in GROUPS:
        for name in wk[wk.position.isin(pos)].player_display_name.unique():
            try:
                log = P.player_series(wk, name, stat)
            except Exception:
                continue
            if log is None or len(log) < 6:
                continue
            u = P.usage_trend(log, stat)
            if not u.flagged:
                continue
            mean = float(pd.to_numeric(log[stat], errors="coerce").mean())
            if mean <= 0 or u.expected_now <= 0:
                continue
            rows.append({
                "player": name, "stat": stat, "verdict": u.verdict,
                "share_ratio": u.share_ratio, "count_ratio": u.ratio,
                "team_volume_ratio": u.team_volume_ratio,
                "has_team_volume": u.has_team_volume,
                "conflict": u.direction_conflict, "flat": u.count_flat,
                # which side the staleness actually helps, by production
                "by_production": "OVER" if u.expected_now > mean else "UNDER",
                # which side the SHARE-derived verdict claims it helps
                "by_verdict": "OVER" if u.verdict == "EXPANDED" else "UNDER"})
    df = pd.DataFrame(rows)
    df["disagrees"] = df.by_production != df.by_verdict
    print(f"seasons {SEASONS}, flagged role changes: {len(df)}")
    print(f"  share and count point OPPOSITE ways : {int(df.conflict.sum())}")
    print(f"    of those, direction disagreed     : "
          f"{int(df[df.conflict].disagrees.sum())}")
    print(f"    of those, direction AGREED        : "
          f"{int((~df[df.conflict].disagrees).sum())}")
    print(f"  share and count AGREE               : {int((~df.conflict).sum())}")
    print(f"    of those, direction disagreed     : "
          f"{int(df[~df.conflict].disagrees.sum())}")
    tv = df[df.conflict & df.has_team_volume].team_volume_ratio
    if len(tv):
        print(f"  team_volume_ratio on the conflicting set (measured only): "
              f"{tv.min():.2f} to {tv.max():.2f}, n={len(tv)}")
    print()
    print("A conflict is refused as DIRECTION NOT ESTABLISHED, so the figure")
    print("that matters is: disagreements inside the conflicting set (all of")
    print("them, historically) against correct calls lost (none).")
    out = pathlib.Path(__file__).with_suffix(".csv")
    df.to_csv(out, index=False)
    print(f"\nfull rows -> {out}")


if __name__ == "__main__":
    main()
