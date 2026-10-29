"""
ff_data.py — nflverse data layer for the Fantasy Football + NFL Props copilot.

Pulls current-season weekly player stats, play-by-play, and rosters straight from
the nflverse GitHub release assets. Everything is cached to a local directory so a
session downloads each file at most once.

The sandbox this runs in is EPHEMERAL — nothing survives between conversations.
That is fine: a full refresh is ~10MB and takes well under a minute. Freshness is
solved by re-pulling at the start of a session, not by maintaining a store.

Usage
-----
    from ff_data import load_weekly, load_pbp, refresh_all, data_status

    refresh_all()                 # pull everything fresh, print what landed
    wk = load_weekly([2025, 2026])
    pbp = load_pbp(2026)
    print(data_status())          # how current is this data?

nflverse updates in-season, typically within a day of games completing.
"""

from __future__ import annotations

import os
import sys
import time
import urllib.request
from pathlib import Path

import pandas as pd

BASE = "https://github.com/nflverse/nflverse-data/releases/download"

# Cache lives in the scratchpad so it never pollutes the project directory.
CACHE = Path(
    os.environ.get(
        "FF_CACHE",
        "/tmp/claude-0/-home-claude/a8825ed4-40ad-5c73-8fab-438a5034b895/scratchpad/nflverse",
    )
)

CURRENT_SEASON = 2026

# Asset paths confirmed live 2026-10-29. nflverse has reorganized these before;
# if a 404 shows up, the release tag is the thing that moved.
ASSETS = {
    "weekly": "{B}/stats_player/stats_player_week_{yr}.parquet",
    "pbp": "{B}/pbp/play_by_play_{yr}.parquet",
    "roster": "{B}/rosters/roster_{yr}.parquet",
}

# Max age before a cached file is considered stale and re-pulled.
STALE_AFTER_SECONDS = 6 * 60 * 60  # 6 hours


def _dest(kind: str, year: int) -> Path:
    return CACHE / f"{kind}_{year}.parquet"


def _is_stale(path: Path) -> bool:
    if not path.exists():
        return True
    return (time.time() - path.stat().st_mtime) > STALE_AFTER_SECONDS


def fetch(kind: str, year: int, force: bool = False) -> Path:
    """Download one nflverse asset if absent or stale. Returns the local path."""
    if kind not in ASSETS:
        raise ValueError(f"unknown asset kind {kind!r}; expected one of {list(ASSETS)}")

    dest = _dest(kind, year)
    if not force and not _is_stale(dest):
        return dest

    CACHE.mkdir(parents=True, exist_ok=True)
    url = ASSETS[kind].format(B=BASE, yr=year)
    tmp = dest.with_suffix(".tmp")

    try:
        with urllib.request.urlopen(url, timeout=180) as r, open(tmp, "wb") as f:
            while chunk := r.read(1 << 16):
                f.write(chunk)
    except Exception as e:
        tmp.unlink(missing_ok=True)
        if dest.exists():
            print(f"  ! {kind} {year} refresh failed ({e}); using cached copy",
                  file=sys.stderr)
            return dest
        raise RuntimeError(f"could not fetch {kind} {year} from {url}: {e}") from e

    tmp.replace(dest)
    return dest


def load_weekly(years: int | list[int] = CURRENT_SEASON,
                force: bool = False) -> pd.DataFrame:
    """Weekly player box-score stats. One row per player per game."""
    years = [years] if isinstance(years, int) else list(years)
    frames = []
    for y in years:
        df = pd.read_parquet(fetch("weekly", y, force))
        if "season" not in df.columns:
            df["season"] = y
        frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    # Numeric stat columns arrive with nulls for players who didn't record that
    # stat type. Zero is the correct fill — scoring math must not propagate NaN.
    skip = {"season", "week"}
    for c in out.select_dtypes(include=["number"]).columns:
        if c not in skip:
            out[c] = out[c].fillna(0)
    return out


def load_pbp(years: int | list[int] = CURRENT_SEASON,
             columns: list[str] | None = None,
             force: bool = False) -> pd.DataFrame:
    """Play-by-play. Needed for anything the weekly box score doesn't carry:
    40+ yard touchdowns, return yardage, down-and-distance splits."""
    years = [years] if isinstance(years, int) else list(years)
    frames = [pd.read_parquet(fetch("pbp", y, force), columns=columns) for y in years]
    return pd.concat(frames, ignore_index=True)


def load_roster(year: int = CURRENT_SEASON, force: bool = False) -> pd.DataFrame:
    """Roster / player metadata — team, position, status, ids for joining."""
    return pd.read_parquet(fetch("roster", year, force))


def refresh_all(years: list[int] | None = None, force: bool = True) -> None:
    """Pull every asset fresh. Call this at the start of a working session."""
    years = years or [CURRENT_SEASON - 1, CURRENT_SEASON]
    print(f"Refreshing nflverse data -> {CACHE}")
    for y in years:
        for kind in ("weekly", "pbp", "roster"):
            try:
                p = fetch(kind, y, force=force)
                mb = p.stat().st_size / 1e6
                print(f"  ok  {kind:<7} {y}  {mb:6.1f} MB")
            except Exception as e:
                print(f"  FAIL {kind:<7} {y}  {e}")
    print()
    print(data_status())


def data_status(year: int = CURRENT_SEASON) -> str:
    """How current is the data? Report the latest completed week on file.

    Always surface this before giving advice — if the latest week on file is
    behind the real NFL week, every projection built on it is stale.
    """
    try:
        wk = pd.read_parquet(_dest("weekly", year), columns=["season", "week", "season_type"])
    except Exception:
        return f"No weekly data cached for {year}. Run refresh_all()."

    reg = wk[wk.season_type == "REG"]
    if reg.empty:
        return f"{year}: no regular-season rows yet."

    last = int(reg.week.max())
    pulled = time.strftime("%Y-%m-%d %H:%M",
                           time.localtime(_dest("weekly", year).stat().st_mtime))
    return (f"DATA AS OF: {year} regular season complete through Week {last}. "
            f"Files pulled {pulled}. Weeks after {last} are not in this data.")


if __name__ == "__main__":
    refresh_all()
