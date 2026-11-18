#!/usr/bin/env python3
"""B206. Does an unstable snap count predict a vanished role next game?

    python3 snap_volatility.py

Why this exists. On 2026-11-16 KeAndre Lambert-Smith was bet OVER 17.5
receiving yards and played ONE offensive snap. His offensive snap share over
his previous games read 87%, 3%, 56% — a role that had already vanished once
in the last three games. The role check (`usage_trend`) is built on targets
and carries, so it could not see it, and no veto fired.

What is measured. Every WR / TE / RB player-game, regular season, in which
the player had at least three earlier games with a snap that season. The
"window" is his last four such games (an inactive game leaves no row, so
these are appearances, not team games). Players are split three ways on the
window, and the outcome is his offensive snap share in the NEXT game he
appears in:

    STABLE    last game at or above ROLE, no game in the window at or below LOW
    UNSTABLE  last game at or above ROLE, but a game in the window at or
              below LOW          <- the Lambert-Smith pattern
    LOW       last game below ROLE (he did not have a real role last time out)

It prints the share of next games at or below 15% and 25% of snaps for each
group, by season and by position, so the split can be checked for stability
rather than taken from one pooled number.

Limits, stated because the figures get quoted:
  - It conditions on the player APPEARING next game. A scratch has no row and
    is not in the denominator, so these are not injury rates.
  - It says nothing about a line or a price. A book may already shade the
    line of a player like this; whether it does is not measured here.
  - ROLE and LOW are the two thresholds in `ff_props` (SNAP_ROLE_SHARE,
    SNAP_LOW_SHARE). The table at the end shows the result is not an artefact
    of where LOW was put.
"""
from __future__ import annotations

import sys

import pandas as pd

import ff_data

SEASONS = (2024, 2025, 2026)
POSITIONS = ("WR", "TE", "RB")
WINDOW = 4
MIN_PRIOR = 3
ROLE = 0.40
LOW = 0.25


def build(snaps: pd.DataFrame) -> pd.DataFrame:
    s = snaps[(snaps.game_type == "REG") & snaps.position.isin(POSITIONS)]
    s = s.sort_values(["pfr_player_id", "season", "week"])
    rows = []
    for (_pid, season), g in s.groupby(["pfr_player_id", "season"]):
        sh = g.offense_pct.to_numpy()
        pos = g.position.iloc[0]
        for i in range(MIN_PRIOR, len(g)):
            prev = sh[max(0, i - WINDOW):i]
            rows.append((season, pos, float(prev[-1]), float(prev.min()),
                         float(prev.max()), float(sh[i])))
    return pd.DataFrame(rows, columns=["season", "pos", "last", "low", "hi",
                                       "next"])


def group(d: pd.DataFrame, low: float = LOW) -> pd.Series:
    out = pd.Series("STABLE", index=d.index)
    out[(d["last"] >= ROLE) & (d["low"] <= low)] = "UNSTABLE"
    out[d["last"] < ROLE] = "LOW"
    return out


def line(tag: str, x: pd.DataFrame) -> str:
    if x.empty:
        return f"  {tag:<28} n=    0"
    return (f"  {tag:<28} n={len(x):5d}   next game at or under 15% of snaps: "
            f"{(x.next <= 0.15).mean():5.1%}   at or under 25%: "
            f"{(x.next <= 0.25).mean():5.1%}   median next share "
            f"{x.next.median():.2f}")


def main() -> int:
    snaps = ff_data.load_snaps(list(SEASONS))
    d = build(snaps)
    d["grp"] = group(d)
    print(f"{len(d)} player-games, seasons {SEASONS}, positions {POSITIONS}")
    print(f"ROLE = {ROLE:.0%} of offensive snaps, LOW = {LOW:.0%}, "
          f"window = last {WINDOW} games with a snap\n")

    print("ALL")
    for gname in ("STABLE", "UNSTABLE", "LOW"):
        print(line(gname, d[d.grp == gname]))

    print("\nBY SEASON")
    for y in SEASONS:
        for gname in ("STABLE", "UNSTABLE"):
            print(line(f"{y} {gname}", d[(d.season == y) & (d.grp == gname)]))

    print("\nBY POSITION")
    for p in POSITIONS:
        for gname in ("STABLE", "UNSTABLE"):
            print(line(f"{p} {gname}", d[(d.pos == p) & (d.grp == gname)]))

    print("\nSENSITIVITY TO THE LOW THRESHOLD (players with a role last game)")
    role = d[d["last"] >= ROLE]
    for lo in (0.10, 0.15, 0.25, 0.35):
        g = group(role, lo)
        print(line(f"UNSTABLE at {lo:.0%}", role[g == "UNSTABLE"]))
        print(line(f"STABLE   at {lo:.0%}", role[g == "STABLE"]))

    # LOW is two different players, and only one of them has lost anything.
    # `hi` is the highest share in the window: under ROLE means he never had
    # a role in it (a steady part-timer); at or over ROLE means he had one
    # and was under ROLE last game.
    lowg = d[d.grp == "LOW"]
    print("\nLOW, SPLIT BY WHETHER HE HAD A ROLE IN THE WINDOW")
    print(line("LOW, no role in window", lowg[lowg.hi < ROLE]))
    print(line("LOW, a role earlier in it", lowg[lowg.hi >= ROLE]))
    for y in SEASONS:
        print(line(f"{y} LOW, role earlier",
                   lowg[(lowg.hi >= ROLE) & (lowg.season == y)]))
    print(f"  LOW is {len(lowg) / len(d):.1%} of all player-games; "
          f"{(lowg.hi < ROLE).mean():.1%} of LOW never had a role in the window.")

    st, un = d[d.grp == "STABLE"], d[d.grp == "UNSTABLE"]
    a, b = (st.next <= 0.15).mean(), (un.next <= 0.15).mean()
    print(f"\nHEADLINE: after an UNSTABLE window the next game is at or under "
          f"15% of snaps {b:.1%} of the time, against {a:.1%} after a STABLE "
          f"one ({b / a:.1f}x). UNSTABLE is {len(un) / (len(un) + len(st)):.1%} "
          f"of players who had a role last game.")

    # Control. The split has to hold in EVERY season on its own, or the pooled
    # figure is one season's accident. A run that fails this is void.
    ok = True
    for y in SEASONS:
        s_, u_ = (d[(d.season == y) & (d.grp == g_)] for g_ in ("STABLE", "UNSTABLE"))
        if len(u_) < 100 or (u_.next <= 0.15).mean() < 3 * (s_.next <= 0.15).mean():
            ok = False
            print(f"CONTROL FAILED for {y}: UNSTABLE n={len(u_)}, "
                  f"{(u_.next <= 0.15).mean():.1%} vs STABLE "
                  f"{(s_.next <= 0.15).mean():.1%}")
    print("control: the split holds at 3x or more in every season"
          if ok else "THIS RUN IS VOID — do not quote it")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
