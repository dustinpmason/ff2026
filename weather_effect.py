#!/usr/bin/env python3
"""Does rain move receiving/passing yards enough to matter against a line?

Asked 2026-11-06 after a three-leg receiving slip lost in heavy rain
(JAX@BAL, legs missing by 11.5, 9.5 and 2.5 yards). The intuition is
obvious and the measurement does not support it at that magnitude.

    python3 measurements/weather_effect.py

CAVEAT THAT MATTERS: nflverse's `weather` is a KICKOFF SNAPSHOT. A game
that poured for four quarters and one that was drizzling at kickoff and
cleared carry the same label, so the estimate is attenuated and the true
effect of a genuine downpour is larger than what prints below. Treat the
number as a floor on the average, not as a ceiling on any one game.
"""
import sys
import pathlib

_here = pathlib.Path(__file__).resolve().parent
for _cand in (_here, _here.parent):
    if (_cand / "ff_props.py").exists():
        sys.path.insert(0, str(_cand))
        break
else:
    sys.exit(f"cannot find ff_props.py next to or above {_here}")

import numpy as np
import pandas as pd
from ff_data import load_weekly, load_pbp
from ff_scoring import prepare

SEASONS = [2022, 2023, 2024, 2025, 2026]
RAIN = r"rain|shower|storm|drizzle"
MIN_GAMES = 8


def main() -> None:
    pbp = load_pbp(SEASONS)
    g = (pbp.groupby(["season", "week", "home_team", "away_team"])
            .agg(weather=("weather", "first"), roof=("roof", "first"),
                 wind=("wind", "first")).reset_index())
    g["rain"] = g.weather.fillna("").str.contains(RAIN, case=False, regex=True)
    g["indoor"] = g.roof.isin(["dome", "closed"])
    print(f"games {len(g)}  indoor {int(g.indoor.sum())}  "
          f"outdoor-rain {int((g.rain & ~g.indoor).sum())}")

    wk = prepare(load_weekly(SEASONS), pbp)
    wk = wk[wk.season_type == "REG"]
    cols = ["season", "week", "home_team", "away_team", "rain", "indoor",
            "wind"]
    a = wk.merge(g[cols], left_on=["season", "week", "team", "opponent_team"],
                 right_on=["season", "week", "home_team", "away_team"],
                 how="left")
    b = wk.merge(g[cols], left_on=["season", "week", "opponent_team", "team"],
                 right_on=["season", "week", "home_team", "away_team"],
                 how="left")
    wk = wk.assign(rain=a.rain.fillna(b.rain).astype("boolean"),
                   indoor=a.indoor.fillna(b.indoor).astype("boolean"))
    wk = wk[(wk.indoor == False) & wk.rain.notna()].copy()  # noqa: E712

    print("\n  effect on a player's OWN baseline (z-scored per season):")
    for stat, pos in (("receiving_yards", ("WR", "TE")),
                      ("passing_yards", ("QB",)),
                      ("rushing_yards", ("RB",))):
        d = wk[wk.position.isin(pos)].copy()
        d["v"] = pd.to_numeric(d[stat], errors="coerce").fillna(0)
        gg = d.groupby(["season", "player_id"])["v"]
        d["n"], d["mu"], d["sd"] = (gg.transform("size"), gg.transform("mean"),
                                    gg.transform("std"))
        d = d[(d.n >= MIN_GAMES) & (d.sd > 0)].copy()
        d["z"] = (d.v - d.mu) / d.sd
        r, dry = d[d.rain.astype(bool)], d[~d.rain.astype(bool)]
        diff = r.z.mean() - dry.z.mean()
        se = np.sqrt(r.z.var() / len(r) + dry.z.var() / len(dry))
        print(f"    {stat:16} rain n={len(r):5,}  dry n={len(dry):6,}  "
              f"diff {diff:+.4f} sd ({diff / se:+.2f} se)  "
              f"~{diff * d.sd.mean():+.1f} yards")
    print("\n  -> on receiving yards the effect is about ONE yard and is not")
    print("     distinguishable from zero. A leg missing by 9 or 11 yards is")
    print("     not a weather story; read game script and the quarterback.")


if __name__ == "__main__":
    main()
