#!/usr/bin/env python3
"""
ff_sim.py — the simulator build. Phase 1, first task: THE HARNESS.

This file grades a projection. It does not make one yet. `SIM-HANDOFF.md`
asks for the grader before the thing it grades, so that the first simulator
number Dustin sees has already been through a test that could have failed it.

WHAT IT DOES

  1. WALKS FORWARD. For every regular-season week from 2024 Week 1 on, each
     projector is handed two things and nothing else:

       * a `History` — every player-game from an EARLIER week (2023 is
         warm-up), and
       * a slate — who is to be projected, as identity columns only.

     A week is the unit, so a Thursday game is not used for that Sunday.
     That is stricter than "before that game" and costs nothing worth
     having.

  2. TWO VERSIONS OF EVERY RESULT.

       version "A" (actives known)   the slate is the players who were
                                     active that day. Inactives are public
                                     about 90 minutes before kickoff, so a
                                     live run is version A.
       version "B" (actives unknown) the slate is everyone who had been
                                     playing for that team (active in one
                                     of its last four games), with nothing
                                     saying who is up today.

     Being on slate A IS the active list; there is no flag beside it. A
     projector that says it does not read who is on the slate must give the
     same number for the same player in both, and the run refuses if it
     does not (`LeakError`).

  3. SETS ITS OWN LINES. Book lines on file start about 2026-11-06, so the
     calibration test uses a STAND-IN line: a ladder of half-point lines
     around the player's median over his last eight games. `standin` in
     every table name means this. It is not a book's line.

  4. REPORTS three things: the stat-line miss, calibration of single lines
     in probability bands with a range clustered by game, and calibration
     of pairs: a projector's own "both happen" beside "multiply the two"
     and beside `ff_correlation`'s table.

WHAT "ACTIVE" MEANS HERE, AND WHY IT IS NOT "HAS A STAT ROW"

  nflverse weekly stats carry a row only for a player who recorded
  something. Measured 2026-11-19 on 2023-2026 (`sim_baseline.py` prints
  it): of skill players who took an offensive snap, 12.6% have no weekly
  row (24.7% of tight ends, 10.7% of receivers). Those are real games with
  zero targets. A test that grades only players with a stat row has thrown
  away the zeros before it starts. So a player-game here is ACTIVE when he
  has a snap-count row OR a weekly row, and an active player with no
  weekly row is graded as a true zero. A player with neither did not play:
  that is a state, not a zero.

  It is still not quite the inactive list. A man who dressed and never
  took a snap has no row, so he is missing rather than a zero; that is
  almost always a backup quarterback. So a quarterback is given a line only
  if he STARTS, which is announced before kickoff and is read from the
  play-by-play, not from who happened to take a snap (`_row_meta`).

THE ONE RULE FOR ANYTHING BUILT ON THIS

  Every number a projector uses must come out of the `History` it was
  handed. A constant worked out over all seasons and typed into a projector
  is a leak the probe below cannot see. Estimate it inside `project()`, or
  from the 2023 warm-up only, and say which.

    python3 sim_baseline.py      # the yardsticks, through this harness
    python3 test_sim.py          # this file's own suite

Owned by the simulator thread. It imports the engine and edits none of it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import NormalDist

import numpy as np
import pandas as pd

import ff_props


# ---------------------------------------------------------------------------
# What is graded
# ---------------------------------------------------------------------------

#: Stats copied straight from nflverse weekly.
RAW_STATS = ("targets", "receptions", "receiving_yards", "receiving_tds",
             "carries", "rushing_yards", "rushing_tds",
             "attempts", "completions", "passing_yards", "passing_tds")

#: Anytime touchdown as the market settles it: rushing or receiving. A
#: quarterback throwing one has not scored.
TD_STAT = "anytime_tds"

#: The stat lines the handoff names, in the order they are reported.
STATS = ("targets", "receptions", "receiving_yards", "carries",
         "rushing_yards", "attempts", "completions", "passing_yards",
         "passing_tds", TD_STAT)

FAMILY = {"targets": "recv", "receptions": "recv", "receiving_yards": "recv",
          "carries": "rush", "rushing_yards": "rush",
          "attempts": "pass", "completions": "pass", "passing_yards": "pass",
          "passing_tds": "pass", TD_STAT: "td"}

#: The volume stat a ROLE is read from, by family.
OPPORTUNITY = {"recv": "targets", "rush": "carries", "pass": "attempts"}

#: Positions given a single-number projection even with no role ("all
#: players", `role_only=False`). Chosen: who ordinarily records the stat.
POSITIONS = {"recv": ("WR", "TE", "RB"), "rush": ("RB", "QB"),
             "pass": ("QB",), "td": ("RB", "WR", "TE")}

SKILL = ("QB", "RB", "WR", "TE", "FB")
#: The snap table's own spellings of a skill position, as found in it.
SNAP_ALIAS = {"HB": "RB"}

# A ROLE is the stand-in for "a book would post a line for him": his median
# over the line window at or above this many targets / carries / attempts.
# THESE THREE ARE JUDGEMENT, NOT MEASUREMENT (S2 in SIM-BACKLOG.md). They
# are to be replaced by what real boards actually post once enough weeks of
# book lines are on file. Read off the opportunity stat, not the position,
# so a cornerback who is thrown to is a receiver here whatever his label.
ROLE_FLOOR = {"recv": 3.0, "rush": 5.0, "pass": 20.0}

# EVERY NUMBER FROM HERE TO `FIRST_TEST_SEASON` WAS CHOSEN, NOT MEASURED (S2).
# They define the TEST, not a projection, and every projector is graded by
# the same test. They do change what it is a test of, and how far apart two
# projectors look (the gaps differ rung by rung). Each is listed in
# SIM-BACKLOG.md.
LINE_WINDOW = 8          # the stand-in line reads his last eight active games
LINE_MIN_GAMES = 4       # ...and says nothing on fewer than four
#: Ladder rungs, as multiples of that median. 1.0 is the main line. Chosen to
#: put legs in every band from 50% to 95%, which a single line cannot.
RUNG_FACTORS = (0.6, 0.8, 1.0, 1.25, 1.6)
MAIN = "main"
# The main line is the half point ABOVE the median (floor + 0.5), so on a
# whole-number stat it sits above half his games. Measured 2026-11-19
# (`sim_baseline.py` prints it): main lines went over 43.1% of the time.

CANDIDATE_LOOKBACK = 4   # version B: active for this team in its last 4 games

#: Fewer games than this in a band and no verdict is printed for it.
MIN_GAMES_FOR_VERDICT = 30

#: Two-sided 95%. One number for every range printed and every verdict given.
Z95 = 1.96

#: Fewer than this many hits, or this many misses, and how much the legs in
#: one game move together is not measured from them: each game counts once.
RARE_FOR_CLUSTERING = 5

FIRST_TEST_SEASON = 2024  # 2023 is warm-up (SIM-HANDOFF.md) and never graded

#: Everything a slate may carry. Identity, and nothing that happened.
#: `starting_qb` is public before kickoff like the rest: on slate A it is who
#: started this game, on slate B who started the team's last one.
SLATE_COLS = ("season", "week", "game_id", "team", "opponent", "player_id",
              "name", "position", "starting_qb")

_NORM = NormalDist()


#: The play-by-play columns `build_frame` reads, and all it reads.
PBP_COLS = ("game_id", "posteam", "order_sequence", "passer_player_id")


class LeakError(RuntimeError):
    """Something from the game being projected, or later, got near a
    projection. Raised rather than reported, because a leaked backtest
    returns a better-looking number, not an error."""


def tkey(season: int, week: int) -> int:
    """One sortable integer per week. 2026 Week 10 -> 202610."""
    return int(season) * 100 + int(week)


# ---------------------------------------------------------------------------
# The player-game frame
# ---------------------------------------------------------------------------

def build_frame(weekly: pd.DataFrame, snaps: pd.DataFrame,
                rosters: pd.DataFrame, pbp: pd.DataFrame) -> pd.DataFrame:
    """One row per ACTIVE player-game, regular season, zeros included.

        frame = build_frame(ff_data.load_weekly(YEARS),
                            ff_data.load_snaps(YEARS),
                            pd.concat(ff_data.load_roster(y) for y in YEARS),
                            ff_data.load_pbp(YEARS, columns=list(PBP_COLS)))

    A row exists when the player has a snap-count row or a weekly stat row
    for that game. Stats are zero where he was active and recorded nothing.
    `rosters` is used ONLY to turn a snap table's PFR id into a GSIS id; a
    roster's team is its latest team and is never read. `pbp` is used ONLY
    to say who STARTED at quarterback: the quarterback behind his team's
    first pass play (`qb_start`). Who starts is announced before kickoff.

    `frame.attrs["report"]` says what could not be placed.
    """
    for label, df, need in (
            ("weekly", weekly, {"season", "week", "season_type", "game_id",
                                "team", "opponent_team", "player_id",
                                "player_display_name", "position",
                                *RAW_STATS}),
            ("snaps", snaps, {"season", "week", "game_type", "game_id",
                              "team", "opponent", "player", "pfr_player_id",
                              "position", "offense_snaps", "offense_pct",
                              "st_snaps"}),
            ("rosters", rosters, {"gsis_id", "pfr_id"}),
            ("pbp", pbp, set(PBP_COLS))):
        missing = need - set(getattr(df, "columns", []))
        if missing:
            raise ValueError(f"{label} is missing {sorted(missing)} — the "
                             f"frame cannot be built without them")

    wk = weekly[weekly.season_type == "REG"].copy()
    if wk.duplicated(["game_id", "player_id"]).any():
        raise ValueError("weekly has two rows for one player in one game; "
                         "refusing to pick one")
    wk["_opp"] = wk[list(OPPORTUNITY.values())].sum(axis=1)
    sn = snaps[snaps.game_type == "REG"].copy()

    # PFR id -> GSIS id. An id that names two players is dropped, not guessed.
    x = (rosters[rosters.pfr_id.notna() & rosters.gsis_id.notna()]
         [["pfr_id", "gsis_id"]].astype(str).drop_duplicates())
    per = x.groupby("pfr_id").gsis_id.nunique()
    ambiguous = set(per[per > 1].index)
    xw = {p: g for p, g in zip(x.pfr_id, x.gsis_id) if p not in ambiguous}
    sn["player_id"] = sn.pfr_player_id.astype(str).map(xw)
    skill_snaps = sn[sn.position.isin(SKILL)]
    unplaced = skill_snaps[skill_snaps.player_id.isna()]
    placed = (sn[sn.player_id.notna()]
              .sort_values("offense_snaps", ascending=False)
              .drop_duplicates(["game_id", "player_id"]))

    # First a superset: anyone EVER listed at a skill position or given a
    # target, carry or pass attempt. Cut down below to the rows from each
    # player's first such game on, so no row is here because of a later one.
    keep = (set(wk.loc[wk.position.isin(SKILL) | (wk._opp > 0), "player_id"])
            | set(placed.loc[placed.position.isin(SKILL), "player_id"]))
    w = wk.loc[wk.player_id.isin(keep),
               ["season", "week", "game_id", "team", "opponent_team",
                "player_id", "player_display_name", "position", *RAW_STATS]]
    s = placed.loc[placed.player_id.isin(keep),
                   ["season", "week", "game_id", "team", "opponent", "player",
                    "player_id", "position", "offense_snaps", "offense_pct",
                    "st_snaps"]]
    m = w.merge(s, on=["game_id", "player_id"], how="outer",
                suffixes=("", "_s"), indicator=True)

    out = pd.DataFrame({
        "season": m.season.fillna(m.season_s).astype(int),
        "week": m.week.fillna(m.week_s).astype(int),
        "game_id": m.game_id.astype(object),
        "team": m.team.fillna(m.team_s).astype(object),
        "opponent": m.opponent_team.fillna(m.opponent).astype(object),
        "player_id": m.player_id.astype(object),
        "name": m.player_display_name.fillna(m.player).astype(object),
        "has_stats": (m._merge != "right_only").to_numpy(),
        "has_snaps": (m._merge != "left_only").to_numpy(),
        "offense_snaps": m.offense_snaps.astype(float),
        "offense_pct": m.offense_pct.astype(float),
        "st_snaps": m.st_snaps.astype(float),
        "_wpos": m.position.astype(object).where(m._merge != "right_only"),
        "_spos": m.position_s.astype(object),
    })
    out["t"] = out.season * 100 + out.week
    for c in RAW_STATS:
        out[c] = pd.to_numeric(m[c], errors="coerce").fillna(0.0).astype(float)
    out[TD_STAT] = out.rushing_tds + out.receiving_tds

    # Position: the weekly label when he has one for this game; otherwise
    # his most recent EARLIER weekly label; otherwise the snap table's.
    out = out.sort_values(["player_id", "t"], kind="stable").reset_index(drop=True)
    carried = out["_wpos"].groupby(out["player_id"]).ffill()
    out["position"] = carried.where(carried.notna(), out["_spos"]).astype(object)
    out = out.rename(columns={"_spos": "snap_position"}).drop(columns=["_wpos"])

    # A player is carried from his first game at a skill position, or with a
    # target, carry or pass attempt, and from then on. A linebacker who
    # catches a pass in 2026 does not put his 2024 games on a 2024 slate.
    opp_row = out[list(OPPORTUNITY.values())].sum(axis=1) > 0
    qualifies = out["position"].isin(SKILL) | opp_row
    since = qualifies.groupby(out["player_id"]).cummax()
    out = out[since.to_numpy()].reset_index(drop=True)

    # Who started at quarterback: the first pass play of each team in each
    # game whose passer is listed at quarterback. (One team's first pass in
    # these four seasons was thrown by a running back.)
    # (Postseason plays need no filter: the frame has no postseason game
    # for them to join to.)
    pb = pbp[pbp.passer_player_id.notna() & pbp.posteam.notna()]
    pb = pb[["game_id", "posteam", "order_sequence", "passer_player_id"]]
    pb = pb.merge(out.loc[out.position == "QB", ["game_id", "team", "player_id"]],
                  left_on=["game_id", "posteam", "passer_player_id"],
                  right_on=["game_id", "team", "player_id"])
    first = (pb.sort_values(["game_id", "team", "order_sequence"], kind="stable")
             .drop_duplicates(["game_id", "team"]))
    started = set(zip(first.game_id, first.team, first.player_id))
    out["qb_start"] = [k in started for k in
                       zip(out.game_id, out.team, out.player_id)]
    team_games = out.drop_duplicates(["game_id", "team"])

    # Counted over the skill positions. The frame also carries every game of
    # a punter who once threw a pass; he is never graded and would only
    # make these figures describe someone else.
    sk = out[out.position.isin(SKILL)]
    on_field = sk[sk.offense_snaps > 0]
    by_pos = {pos: float((~g.has_stats).mean())
              for pos, g in on_field.groupby("position")}
    out.attrs["report"] = {
        "team_games": int(len(team_games)),
        "team_games_with_a_starting_qb": int(out.qb_start.sum()),
        "share_on_field_no_stat_row_by_position": by_pos,
        "player_games": int(len(out)),
        "skill_player_games": int(len(sk)),
        "seasons": sorted(int(y) for y in out.season.unique()),
        "weekly_rows": int(sk.has_stats.sum()),
        "active_no_stat_row": int((~sk.has_stats).sum()),
        "share_on_field_no_stat_row":
            float((~on_field.has_stats).mean()) if len(on_field) else float("nan"),
        "skill_snap_rows": int(len(skill_snaps)),
        "skill_snap_rows_unplaced": int(len(unplaced)),
        "ambiguous_pfr_ids": int(len(ambiguous)),
    }
    return out


def describe_frame(frame: pd.DataFrame) -> str:
    r = frame.attrs.get("report")
    if not r:
        return "frame carries no build report"
    return (f"{r['skill_player_games']:,} active player-games at "
            f"{'/'.join(SKILL)}, seasons {r['seasons']}. "
            f"{r['active_no_stat_row']:,} of them have no stat row and are "
            f"graded as zeros. Of those who took an offensive snap, "
            f"{r['share_on_field_no_stat_row']:.1%} have no stat row. "
            f"{r['skill_snap_rows_unplaced']:,} of "
            f"{r['skill_snap_rows']:,} skill-position snap rows had no id "
            f"to join on and are not in the frame. A starting quarterback "
            f"was found for {r['team_games_with_a_starting_qb']:,} of "
            f"{r['team_games']:,} team-games.")


# ---------------------------------------------------------------------------
# History — the only thing a projector may read
# ---------------------------------------------------------------------------

class History:
    """Every player-game strictly before one week.

        h.values(player_id, "targets")              all his earlier games
        h.values(player_id, "targets", min_season=2025)
        h.rows(player_id)                           row numbers, oldest first
        h.col["offense_pct"][h.rows(player_id)]     any column, same rows
        h.frame                                     the rows as a DataFrame

    Constructing one with a row from `before` or later raises `LeakError`.
    """

    def __init__(self, rows: pd.DataFrame, before: int):
        self.before = int(before)
        self.season = self.before // 100
        self.week = self.before % 100
        rows = rows.sort_values(["player_id", "t"], kind="stable")
        t = rows["t"].to_numpy()
        if len(t) and int(t.max()) >= self.before:
            late = int((t >= self.before).sum())
            raise LeakError(
                f"History for week {self.before} was handed {late} row(s) "
                f"from that week or later (newest {int(t.max())}). A "
                f"projection may only see earlier weeks.")
        self.frame = rows.reset_index(drop=True)
        self.frame.attrs = {}      # the build report counts ALL seasons
        self.t = self.frame["t"].to_numpy()
        self.season_of = self.frame["season"].to_numpy()
        self.player = self.frame["player_id"].to_numpy(dtype=object)
        self.team = self.frame["team"].to_numpy(dtype=object)
        self.position = self.frame["position"].to_numpy(dtype=object)
        self.has_stats = self.frame["has_stats"].to_numpy(dtype=bool)
        self.qb_start = self.frame["qb_start"].to_numpy(dtype=bool)
        self.col = {c: self.frame[c].to_numpy(dtype=float)
                    for c in (*RAW_STATS, TD_STAT, "offense_snaps",
                              "offense_pct", "st_snaps")}
        n = len(self.frame)
        self._span = {}
        if n:
            cut = np.flatnonzero(self.player[1:] != self.player[:-1]) + 1
            starts = np.concatenate(([0], cut))
            stops = np.concatenate((cut, [n]))
            self._span = {self.player[a]: (int(a), int(b))
                          for a, b in zip(starts, stops)}
        self._team_rows = None
        self._team_weeks: dict = {}

    def rows(self, player_id, min_season: int | None = None) -> np.ndarray:
        """Row numbers of a player's earlier active games, oldest first."""
        sp = self._span.get(player_id)
        if sp is None:
            return np.empty(0, dtype=int)
        a, b = sp
        if min_season is not None:
            a += int(np.searchsorted(self.season_of[a:b], min_season, "left"))
        return np.arange(a, b)

    def values(self, player_id, stat: str,
               min_season: int | None = None) -> np.ndarray:
        return self.col[stat][self.rows(player_id, min_season)]

    def _teams(self) -> dict:
        if self._team_rows is None:
            order = np.argsort(self.team, kind="stable")
            tm = self.team[order]
            cut = np.flatnonzero(tm[1:] != tm[:-1]) + 1 if len(tm) else []
            starts = np.concatenate(([0], cut)).astype(int) if len(tm) else []
            stops = np.concatenate((cut, [len(tm)])).astype(int) if len(tm) else []
            self._team_rows = {tm[a]: order[a:b] for a, b in zip(starts, stops)}
        return self._team_rows

    def team_weeks(self, team) -> np.ndarray:
        """The weeks this team has played, oldest first."""
        if team not in self._team_weeks:
            idx = self._teams().get(team)
            self._team_weeks[team] = (np.unique(self.t[idx]) if idx is not None
                                      else np.empty(0, dtype=int))
        return self._team_weeks[team]

    def team_recent_players(self, team, games: int) -> list:
        """Players active for `team` in any of its last `games` games."""
        idx = self._teams().get(team)
        if idx is None:
            return []
        weeks = np.unique(self.t[idx])[-games:]
        return sorted(set(self.player[idx[np.isin(self.t[idx], weeks)]]))

    def last_starting_qb(self, team):
        """Who started at quarterback in this team's newest game. None if it
        has no earlier game, or none with a starter on file."""
        idx = self._teams().get(team)
        if idx is None:
            return None
        newest = idx[self.t[idx] == self.t[idx].max()]
        who = self.player[newest[self.qb_start[newest]]]
        return who[0] if len(who) else None

    def last_week(self, player_id) -> int | None:
        sp = self._span.get(player_id)
        return int(self.t[sp[1] - 1]) if sp else None

    def last_position(self, player_id):
        sp = self._span.get(player_id)
        return self.position[sp[1] - 1] if sp else None

    def last_name(self, player_id):
        sp = self._span.get(player_id)
        return self.frame["name"].iat[sp[1] - 1] if sp else None

    def team_games_missed(self, player_id, team) -> int | None:
        """Games `team` has played since his newest game. None if he has no
        earlier game at all. A bye is not a miss."""
        last = self.last_week(player_id)
        if last is None:
            return None
        return int((self.team_weeks(team) > last).sum())


def _history_rows(frame: pd.DataFrame, before: int) -> pd.DataFrame:
    """The rows a projection for week `before` may see: earlier weeks only."""
    return frame[frame["t"] < before]


# ---------------------------------------------------------------------------
# Slates
# ---------------------------------------------------------------------------

def check_slate(slate: pd.DataFrame) -> None:
    """Refuse a slate carrying anything but identity."""
    extra = set(slate.columns) - set(SLATE_COLS)
    if extra:
        raise LeakError(f"a slate may carry identity only; it has "
                        f"{sorted(extra)}")
    if slate.attrs:
        raise LeakError(f"a slate may carry identity only; it has attrs "
                        f"{sorted(slate.attrs)}")


def slate_active(frame: pd.DataFrame, hist: History) -> pd.DataFrame:
    """Version A: the players active that week. Identity columns only.

    Being ON this slate is the active list; there is no separate flag.
    His position is the one he had going in: his newest earlier game's. A
    player with no earlier game takes the snap table's label ("HB" read as
    RB), and the weekly label only if the snap table gives him none, so the
    label does not turn on whether he recorded a stat today. `starting_qb`
    is who started at
    quarterback today, which is announced before kickoff.

    One kind of row in the frame is NOT on the slate: a player at no skill
    position with no earlier game here. He is in the frame only because he
    got a touch in this game, and nobody knew that going in.
    """
    cur = frame.loc[frame["t"] == hist.before,
                    [*SLATE_COLS[:-1], "snap_position",
                     "qb_start"]].reset_index(drop=True)
    pos, keep = [], []
    for pid, snap, own in zip(cur["player_id"].to_numpy(dtype=object),
                              cur["snap_position"].to_numpy(dtype=object),
                              cur["position"].to_numpy(dtype=object)):
        prior = hist.last_position(pid)
        if isinstance(snap, str):
            snap = SNAP_ALIAS.get(snap, snap)
        label = (prior if prior is not None
                 else snap if isinstance(snap, str) and snap else own)
        pos.append(label)
        keep.append(prior is not None or label in SKILL)
    out = cur[list(SLATE_COLS[:-1])].copy()
    out["position"] = np.array(pos, dtype=object)
    out["starting_qb"] = cur["qb_start"].to_numpy(dtype=bool)
    out = out[np.array(keep, dtype=bool)].reset_index(drop=True)
    out.attrs = {}
    return out


def slate_candidates(frame: pd.DataFrame, hist: History,
                     lookback: int = CANDIDATE_LOOKBACK) -> pd.DataFrame:
    """Version B: who had been playing for each team, not who is up today.

    The week's schedule (which teams play, and whom) is public and is read
    from the frame. Who is on each team is read from HISTORY only: a player
    active for the team in one of its last `lookback` games. So a player
    back after five weeks out, or in his first game for a new team, is not
    on this slate. That is what not knowing the active list costs.
    `starting_qb` is who started the team's LAST game, since today's
    starter is not known here.
    """
    cur = frame.loc[frame["t"] == hist.before,
                    ["season", "week", "game_id", "team", "opponent"]]
    games = cur.drop_duplicates(["game_id", "team"])
    rec = []
    for g in games.itertuples(index=False):
        qb = hist.last_starting_qb(g.team)
        for pid in hist.team_recent_players(g.team, lookback):
            rec.append((g.season, g.week, g.game_id, g.team, g.opponent, pid,
                        hist.last_name(pid), hist.last_position(pid),
                        pid == qb))
    return pd.DataFrame(rec, columns=list(SLATE_COLS))


def check_frame(frame: pd.DataFrame) -> None:
    """Refuse a frame that would be graded wrongly rather than loudly."""
    need = {"t", "season", "week", "game_id", "team", "opponent", "player_id",
            "name", "position", "snap_position", "has_stats", "qb_start",
            *RAW_STATS, TD_STAT, "offense_snaps", "offense_pct", "st_snaps"}
    missing = need - set(frame.columns)
    if missing:
        raise ValueError(f"the frame is missing {sorted(missing)}; build it "
                         f"with build_frame")
    if frame.duplicated(["game_id", "player_id"]).any():
        n = int(frame.duplicated(["game_id", "player_id"]).sum())
        raise ValueError(f"the frame has {n} repeated player-game row(s); "
                         f"each would be graded twice")
    if not (frame["t"] == frame["season"] * 100 + frame["week"]).all():
        raise ValueError("the frame's week key `t` does not match its season "
                         "and week")
    blank = [c for c in (*RAW_STATS, TD_STAT) if frame[c].isna().any()]
    if blank:
        raise ValueError(f"the frame has a missing value in {blank}; a "
                         f"missing stat grades as a miss on every line")


# ---------------------------------------------------------------------------
# Stand-in lines
# ---------------------------------------------------------------------------

def rungs(median: float) -> list[tuple[str, float]]:
    """[(label, line)] around a median, lowest first. Half-point lines.

    Two factors that land on one line are one rung, labelled by the factor
    nearer 1.0, so the main line is always present and always called "main".
    """
    if median < 0:
        # Scaling a negative number turns the ladder upside down (a kneeling
        # quarterback's rushing yards). One line, no ladder.
        return [(MAIN, math.floor(median) + 0.5)]
    by_line: dict[float, float] = {}
    for f in sorted(RUNG_FACTORS, key=lambda f: abs(math.log(f))):
        by_line.setdefault(math.floor(median * f) + 0.5, f)
    return [(MAIN if f == 1.0 else f"x{f:g}", line)
            for line, f in sorted(by_line.items())]


def line_window(hist: History, player_id) -> np.ndarray:
    """Rows of his last `LINE_WINDOW` active games, this season and last."""
    return hist.rows(player_id, min_season=hist.season - 1)[-LINE_WINDOW:]


def roles(hist: History, win: np.ndarray) -> dict:
    """{family: bool} — would a book plausibly post a line for him?"""
    if len(win) < LINE_MIN_GAMES:
        return {"recv": False, "rush": False, "pass": False, "td": False}
    r = {fam: bool(np.median(hist.col[opp][win]) >= ROLE_FLOOR[fam])
         for fam, opp in OPPORTUNITY.items()}
    r["td"] = r["recv"] or r["rush"]
    return r


def standin_lines(hist: History, win: np.ndarray, stat: str) -> list:
    """The stand-in ladder for one player and stat. [] when there is none."""
    if len(win) < LINE_MIN_GAMES:
        return []
    if stat == TD_STAT:
        return [(MAIN, 0.5)]
    return rungs(float(np.median(hist.col[stat][win])))


# ---------------------------------------------------------------------------
# Projectors
# ---------------------------------------------------------------------------

class Projection:
    """What a projector returns for one slate.

    `point` is the projected MEDIAN (or the projector's best single number)
    for slate row `i`; `p_over` is P(stat > line). Either may return NaN for
    "no projection", which is reported as coverage and never as a zero.
    `p_both` is optional: a simulator that draws whole games returns its own
    joint probability; anything else returns None and is priced by product.
    """

    def point(self, i: int, stat: str) -> float:
        raise NotImplementedError

    def p_over(self, i: int, stat: str, line: float) -> float:
        raise NotImplementedError

    def p_both(self, i: int, stat_i: str, line_i: float,
               j: int, stat_j: str, line_j: float):
        return None


class Projector:
    """Subclass, set `name`, implement `project`.

    `uses_actives` must be True for anything whose answer depends on WHO is
    on the slate (a share model, a simulator): on slate A that is the
    active list. The run checks the claim.
    """
    name = "unnamed"
    uses_actives = False

    def project(self, hist: History, slate: pd.DataFrame) -> Projection:
        raise NotImplementedError


def hit_share(x: np.ndarray, line: float) -> float:
    """Share of games over a line, pulled half a game toward 50%.

    (hits + 0.5) / (n + 1). Without the half, one game makes a 0% or a
    100%, which no yardstick should be charged with saying. The half is a
    choice, not a measurement. No games at all is NaN.
    """
    if not len(x):
        return float("nan")        # no games is no answer, not a coin flip
    return float(((x > line).sum() + 0.5) / (len(x) + 1.0))


def gamelog_blend(x: np.ndarray, line: float, half_life: float = 6.0) -> float:
    """`ff_props.threshold_prob(...).blended`, without its bootstrap.

    A COPY, kept because the original costs 4 ms a call and the walk-forward
    makes hundreds of thousands. `test_sim.py` section 6 runs the original
    beside this on real logs and fails by name if they ever differ, so a
    change to the engine's model cannot leave this one behind unnoticed.
    """
    x = x[~np.isnan(x)]            # as the engine does
    n = len(x)
    if n < 3:
        return float("nan")
    over = x >= line
    emp = over.mean()
    mu, sd = float(x.mean()), float(x.std(ddof=1))
    if sd > 0:
        para = 0.5 * math.erfc((line - mu) / (sd * math.sqrt(2.0)))
    else:
        para = float(x[0] >= line)
    w = 0.5 ** (np.arange(n - 1, -1, -1, dtype=float) / half_life)
    rec = float((over * w).sum() / w.sum())
    return float(np.clip(0.45 * emp + 0.25 * para + 0.30 * rec, 0.01, 0.99))


class _LogProjection(Projection):
    def __init__(self, owner, hist: History, slate: pd.DataFrame):
        self.owner, self.hist = owner, hist
        self.pids = slate["player_id"].to_numpy(dtype=object)
        self._cache: dict = {}

    def _log(self, i: int, stat: str) -> np.ndarray:
        k = (i, stat)
        if k not in self._cache:
            self._cache[k] = self.owner.log(self.hist, self.pids[i], stat)
        return self._cache[k]

    def point(self, i, stat):
        x = self._log(i, stat)
        return self.owner.point_of(x) if len(x) >= self.owner.min_games \
            else float("nan")

    def p_over(self, i, stat, line):
        x = self._log(i, stat)
        return self.owner.prob_of(x, line) if len(x) >= self.owner.min_games \
            else float("nan")


class _LogYardstick(Projector):
    """A yardstick that reads one player's own game log and nothing else."""
    min_games = 1

    def project(self, hist, slate):
        return _LogProjection(self, hist, slate)

    def log(self, hist: History, player_id, stat: str) -> np.ndarray:
        raise NotImplementedError

    def point_of(self, x: np.ndarray) -> float:
        return float(x.mean())

    def prob_of(self, x: np.ndarray, line: float) -> float:
        return hit_share(x, line)


class SeasonAverage(_LogYardstick):
    """His average this season, over the games he was active (zeros count).
    The chance of a line is how often he has cleared it this season."""
    name = "season_avg"

    def log(self, hist, player_id, stat):
        return hist.values(player_id, stat, min_season=hist.season)


class LastFour(_LogYardstick):
    """His average over his last four active games, this season or last."""
    name = "last4_avg"

    def log(self, hist, player_id, stat):
        return hist.values(player_id, stat, min_season=hist.season - 1)[-4:]


class GameLogModel(_LogYardstick):
    """The model the engine uses today: `ff_props.threshold_prob` on the log
    `ff_props.player_series` builds from this season and last.

    That log keeps only games with a stat row and, where the engine names an
    opportunity column for the stat, only games with at least one
    opportunity. So it never sees a game he was active and got nothing.
    Its single number is the median of that log.

    Two places it is NOT the engine's:
      * `anytime_tds`. The engine builds no touchdown log: nflverse has no
        such column, `player_series` returns a log without it and
        `threshold_prob` raises. For that stat this is the engine's blend
        applied to a log the harness made, and every table says so.
      * The log is kept by player id. The engine keeps it by display name,
        so a player whose name is spelled two ways across seasons has a
        shorter log there (2 of 1,732 logs on three weeks, 2026-11-19).
    """
    name = "gamelog_model"
    min_games = 3

    def log(self, hist, player_id, stat):
        r = hist.rows(player_id, min_season=hist.season - 1)
        keep = hist.has_stats[r]
        opp = ff_props.opportunity_column(stat)
        if opp:
            keep = keep & (hist.col[opp][r] > 0)
        return hist.col[stat][r[keep]]

    def point_of(self, x):
        return float(np.median(x))

    def prob_of(self, x, line):
        return gamelog_blend(x, line)


def yardsticks() -> list[Projector]:
    return [SeasonAverage(), LastFour(), GameLogModel()]


# ---------------------------------------------------------------------------
# The walk-forward run
# ---------------------------------------------------------------------------

@dataclass
class Run:
    """What a walk-forward produced.

    `points`  one row per version, player-game and stat: the single-number
              projection of each projector (`pt_<name>`) beside what happened.
    `legs`    one row per version, player-game, stat and stand-in line: each
              projector's P(over) (`p_<name>`) beside whether it went over.
              Only players with a ROLE have legs.
    `joints`  version A only: for each pair of main-line legs in one game, the
              P(both) of every projector that states its own (`j_<name>`).
              Empty when none does.
    `unverified`  projectors whose "does not read the slate" claim could not
              be checked, because no player-game was in both versions.
    """
    points: pd.DataFrame
    legs: pd.DataFrame
    names: list
    weeks: list
    slates: dict = field(default_factory=dict)
    joints: pd.DataFrame = field(default_factory=pd.DataFrame)
    unverified: list = field(default_factory=list)

    def describe(self) -> str:
        if not self.weeks:
            return "no weeks were run"
        a = self.legs[self.legs.version == "A"]
        out = (f"{len(self.weeks)} weeks, {self.weeks[0]} to {self.weeks[-1]}; "
               f"{a.game_id.nunique():,} games; "
               f"{len(self.points[self.points.version == 'A']):,} stat lines "
               f"and {len(a):,} stand-in legs with actives known")
        if self.unverified:
            out += (f". NOT CHECKED: whether {', '.join(self.unverified)} "
                    f"read the slate — no player-game was in both versions")
        return out


def test_weeks(frame: pd.DataFrame, first_season: int = FIRST_TEST_SEASON,
               through: int | None = None) -> list[int]:
    """Every week to grade, oldest first.

    `through` is the newest COMPLETE week as a key (202610). Without it the
    newest week on file is LEFT OUT: data arrives through a week, a Thursday
    game alone looks like a week, and nothing in the data can tell a
    finished week from a half-played one. Same rule, and same reason, as
    `ff_data.complete_weeks`.
    """
    ts = sorted(int(t) for t in frame["t"].unique()
                if t // 100 >= first_season)
    if through is None:
        newest = int(frame["t"].max()) if len(frame) else None
        return [t for t in ts if t != newest]
    return [t for t in ts if t <= through]


def market_sides() -> list:
    """[(side, positions, stat, yes/no?)] — `ff_correlation.SIDE_SPEC`, with
    its anytime-TD column named as this module names it."""
    import ff_correlation
    return [(side, tuple(pos), TD_STAT if col == "_anytime_td" else col,
             bool(binary))
            for side, (pos, col, binary) in ff_correlation.SIDE_SPEC.items()]


def _row_meta(hist: History, slate: pd.DataFrame) -> list:
    """Per slate row: (line window, roles, newest input, games missed).
    History and the slate's own columns only.

    ONE LINED QUARTERBACK A TEAM. A backup who used to start still has a
    starter's median, and no book posts a line for him. So a passing role
    is kept only by the slate's `starting_qb`: on slate A the man who
    starts today, on slate B the man who started the team's last game.
    Anyone else whose median earned a passing role is a backup
    quarterback, and is given no role of any kind.
    """
    out = []
    for pid, team, starts in zip(slate["player_id"].to_numpy(dtype=object),
                                 slate["team"].to_numpy(dtype=object),
                                 slate["starting_qb"].to_numpy(dtype=bool)):
        win = line_window(hist, pid)
        role = roles(hist, win)
        if role["pass"] and not starts:
            role = dict.fromkeys(role, False)
        out.append((win, role, hist.last_week(pid),
                    hist.team_games_missed(pid, team)))
    return out


def run_week(frame: pd.DataFrame, before: int,
             projectors: list[Projector]) -> tuple[list, list, dict, list]:
    """Project and grade one week.
    Returns (point rows, leg rows, slates, joint rows)."""
    hist = History(_history_rows(frame, before), before)
    cur = frame[frame["t"] == before]
    # Keyed by team as well: a player who changed sides between two teams
    # that then meet is on B's slate for the team he LEFT, and did not play
    # for it.
    truth = {k: i for i, k in
             enumerate(zip(cur["game_id"].to_numpy(dtype=object),
                           cur["team"].to_numpy(dtype=object),
                           cur["player_id"].to_numpy(dtype=object)))}
    actual = {s: cur[s].to_numpy(dtype=float) for s in STATS}

    pts, legs, slates, joints = [], [], {}, []
    for version, slate in (("A", slate_active(frame, hist)),
                           ("B", slate_candidates(frame, hist))):
        check_slate(slate)
        slates[version] = slate
        meta = _row_meta(hist, slate)
        outs = [pr.project(hist, slate.copy()) for pr in projectors]
        ident = list(zip(*(slate[c].to_numpy(dtype=object)
                           for c in SLATE_COLS)))
        mains = {}
        for i, row in enumerate(ident):
            season, week, game_id, team, opp, pid, name, pos, _starts = row
            win, role, newest, missed = meta[i]
            k = truth.get((game_id, team, pid))
            played = k is not None
            base = (version, int(season), int(week), game_id, team, opp, pid,
                    name, pos, played, newest, missed)
            for stat in STATS:
                fam = FAMILY[stat]
                if not (role[fam] or pos in POSITIONS[fam]):
                    continue
                act = float(actual[stat][k]) if played else float("nan")
                vals = []
                for pr, o in zip(projectors, outs):
                    v = float(o.point(i, stat))
                    if not (math.isnan(v) or math.isfinite(v)):
                        raise ValueError(f"{pr.name} returned {v!r} as a "
                                         f"projection for {stat}")
                    vals.append(v)
                pts.append((*base, stat, bool(role[fam]), act, *vals))
                if not role[fam]:
                    continue
                ladder = standin_lines(hist, win, stat)
                main_line = dict(ladder).get(MAIN, float("nan"))
                if ladder:
                    mains[(i, stat)] = float(main_line)
                for label, line in ladder:
                    ps = []
                    for pr, o in zip(projectors, outs):
                        p = float(o.p_over(i, stat, line))
                        if not (math.isnan(p) or 0.0 <= p <= 1.0):
                            raise ValueError(
                                f"{pr.name} returned {p!r} as a probability "
                                f"for {stat} over {line}")
                        ps.append(p)
                    over = (act > line) if played else None
                    legs.append((*base, stat, label, float(line),
                                 float(main_line), act, over, *ps))
        if version == "A":
            joints.extend(_joint_rows(projectors, outs, ident, mains))
    return pts, legs, slates, joints


def _states_joint(o) -> bool:
    """Does this projection have a `p_both` of its own? On its class, set on
    the object, or reached through a wrapper: anything but the base
    `Projection.p_both`, which answers None."""
    m = getattr(o, "p_both", None)
    return m is not None and getattr(m, "__func__", m) is not Projection.p_both


def _joint_rows(projectors, outs, ident, mains) -> list:
    """Each projector's OWN chance that two main-line legs both go over.

    Asked of every projector whose projection has a `p_both` of its own
    (`_states_joint`), for every pair; one that leaves the base method
    alone is never asked. An
    answer of None for a pair is a blank for that pair, and `pair_score`
    reports how many pairs it scored. The pairs, and their order, are
    exactly `build_pairs`'.
    """
    by_game: dict = {}
    for side, positions, stat, _binary in market_sides():
        for (i, st), line in mains.items():
            if st == stat and ident[i][7] in positions:
                by_game.setdefault(ident[i][2], []).append(
                    (side, ident[i][5], i, stat, line))
    pairs = []
    for game_id, ls in by_game.items():
        ls.sort(key=lambda r: (r[0], str(r[1])))
        for x in range(len(ls)):
            for y in range(x + 1, len(ls)):
                if ls[x][1] != ls[y][1]:
                    pairs.append((game_id, ls[x], ls[y]))
    able = [_states_joint(o) for o in outs]
    if not pairs or not any(able):
        return []
    rows = []
    for game_id, a, b in pairs:
        js = []
        for pr, o, ok in zip(projectors, outs, able):
            j = float("nan")
            if ok:
                got = o.p_both(a[2], a[3], a[4], b[2], b[3], b[4])
                j = float("nan") if got is None else float(got)
                if not (math.isnan(j) or 0.0 <= j <= 1.0):
                    raise ValueError(f"{pr.name} returned {j!r} as the "
                                     f"chance two legs both happen")
            js.append(j)
        rows.append((game_id, a[1], a[0], b[1], b[0], *js))
    return rows


_BASE_COLS = ["version", "season", "week", "game_id", "team", "opponent",
              "player_id", "name", "position", "played", "newest_input",
              "team_games_missed"]
_JOINT_KEYS = ["game_id", "player_id_a", "side_a", "player_id_b", "side_b"]
# Where the RESULT sits in a point row (stat, role, actual, ...) and in a leg
# row (stat, rung, line, main_line, actual, over, ...). The leak probe skips
# exactly these and compares everything else. A joint row holds no result.
_PT_RESULT = frozenset({len(_BASE_COLS) + 2})
_LEG_RESULT = frozenset({len(_BASE_COLS) + 4, len(_BASE_COLS) + 5})
# ...and where the projector's own OUTPUTS start in each kind of row.
_PT_OUT, _LEG_OUT, _JOINT_OUT = (len(_BASE_COLS) + 3, len(_BASE_COLS) + 6,
                                 len(_JOINT_KEYS))


def _eq(x, y) -> bool:
    if isinstance(x, float) and isinstance(y, float):
        return x == y or (math.isnan(x) and math.isnan(y))
    return x == y


def walk_forward(frame: pd.DataFrame, projectors: list[Projector], *,
                 weeks: list[int] | None = None,
                 through: int | None = None,
                 keep_slates: bool = False) -> Run:
    """Run every projector over every test week and grade it.

        run = walk_forward(frame, yardsticks(), through=202610)

    With neither `weeks` nor `through`, the newest week on file is left out
    (see `test_weeks`). A week named in `weeks` with no game on file is
    refused. Raises `LeakError` if a projector that does not declare
    `uses_actives` gives a different answer once the active list is hidden;
    if that could not be checked at all, the projector is named in
    `run.unverified` and in `run.describe()`.
    """
    check_frame(frame)
    names = [p.name for p in projectors]
    if len(set(names)) != len(names):
        raise ValueError(f"two projectors share a name: {names}")
    weeks = list(weeks) if weeks is not None else test_weeks(frame,
                                                             through=through)
    on_file = set(int(t) for t in frame["t"].unique())
    absent = [t for t in weeks if t not in on_file]
    if absent:
        raise ValueError(f"no game on file for week(s) {absent}; a week "
                         f"with nothing in it cannot be graded")
    pts, legs, slates, joints = [], [], {}, []
    for t in weeks:
        a, b, s, j = run_week(frame, t, projectors)
        pts.extend(a)
        legs.extend(b)
        joints.extend(j)
        if keep_slates:
            slates[t] = s
    points = pd.DataFrame(pts, columns=[*_BASE_COLS, "stat", "role", "actual",
                                        *(f"pt_{n}" for n in names)])
    legs_df = pd.DataFrame(legs, columns=[*_BASE_COLS, "stat", "rung", "line",
                                          "main_line", "actual", "over",
                                          *(f"p_{n}" for n in names)])
    joints_df = pd.DataFrame(joints, columns=[*_JOINT_KEYS,
                                              *(f"j_{n}" for n in names)])
    run = Run(points=points, legs=legs_df, names=names, weeks=weeks,
              slates=slates, joints=joints_df)
    for pr in projectors:
        if pr.uses_actives:
            continue
        differ, compared = version_gap(run, pr.name, counts=True)
        if differ:
            raise LeakError(
                f"{pr.name} says it does not use the active list, yet "
                f"{differ} of its numbers changed when the list was hidden. "
                f"Either it reads who is on the slate (set "
                f"uses_actives = True) or something else differs "
                f"between the two versions that should not.")
        if not compared and len(points):
            run.unverified.append(pr.name)
    return run


def _same(a: pd.Series, b: pd.Series) -> np.ndarray:
    x, y = a.to_numpy(dtype=float), b.to_numpy(dtype=float)
    return (x == y) | (np.isnan(x) & np.isnan(y))


def version_gap(run: Run, name: str, counts: bool = False):
    """How many of one projector's numbers differ between versions A and B,
    over the player-games and lines present in both: its single numbers and
    its probabilities alike. With `counts=True`, (differing, compared) — so
    "none differ" can be told from "none could be compared". A blank beside
    a blank is not a comparison and is not counted as one."""
    differ = compared = 0
    for df, col, keys in ((run.points, f"pt_{name}",
                           ["game_id", "team", "player_id", "stat"]),
                          (run.legs, f"p_{name}",
                           ["game_id", "team", "player_id", "stat", "line"])):
        a = df[df.version == "A"]
        b = df[df.version == "B"]
        m = a.merge(b, on=keys, suffixes=("_a", "_b"))
        compared += int((m[f"{col}_a"].notna() | m[f"{col}_b"].notna()).sum())
        differ += int((~_same(m[f"{col}_a"], m[f"{col}_b"])).sum())
    return (differ, compared) if counts else differ


# ---------------------------------------------------------------------------
# The leak probe
# ---------------------------------------------------------------------------

@dataclass
class LeakProbe:
    """Three answers, not two: clean, leaking, or not measured.

    WHAT IT CAN SEE: anything from the week being projected, or later, that
    reaches a projection, a line, a role or a slate THROUGH THE FRAME the
    harness was given. WHAT IT CANNOT: a projector that carries its own copy
    of the data, or a constant typed into one that was worked out over all
    seasons. Nothing automatic sees those.

    `outputs` counts, per projector, the outputs compared that were real
    numbers. A projector that returned nothing has not been shown to be
    clean, whatever the others did, and the probe is not `measured` until
    every one of them has at least one.
    """
    outputs: dict = field(default_factory=dict)
    fields: int = 0
    changed: int = 0
    weeks: list = field(default_factory=list)
    examples: list = field(default_factory=list)

    @property
    def silent(self) -> list:
        return [n for n, k in self.outputs.items() if not k]

    @property
    def measured(self) -> bool:
        return bool(self.outputs) and not self.silent

    @property
    def clean(self) -> bool:
        return self.measured and self.changed == 0

    def describe(self) -> str:
        span = (f"{len(self.weeks)} week(s), {self.weeks[0]} to "
                f"{self.weeks[-1]}" if self.weeks else "no weeks")
        if self.changed:
            return (f"LEAK PROBE: LEAK — {self.changed:,} value(s) changed "
                    f"when the week being projected, and everything after "
                    f"it, was overwritten ({span}). First: "
                    f"{self.examples[:3]}")
        if not self.measured:
            who = ", ".join(self.silent) or "any projector"
            return (f"LEAK PROBE: NOT MEASURED — {who} produced no number "
                    f"over {span}, so there was nothing of its to compare")
        return (f"LEAK PROBE: no leak through the harness — "
                f"{sum(self.outputs.values()):,} projector outputs and "
                f"{self.fields:,} lines, roles and slate fields over {span} "
                f"were identical after the week being projected, and "
                f"everything after it, was overwritten. It cannot see a "
                f"projector that carries its own data.")


def scramble_from(frame: pd.DataFrame, before: int) -> pd.DataFrame:
    """A copy with every outcome from week `before` on replaced by nonsense.

    Who played, for whom and against whom is left alone, and so is each
    player's position, so the slate is the same slate. Every stat and snap
    figure from that week on becomes a large number no real game produces,
    a missing snap count included, and every such row is marked as having a
    stat row. A projection that reads any of it moves.
    """
    out = frame.copy()
    late = (out["t"] >= before).to_numpy()
    for j, c in enumerate((*RAW_STATS, "offense_snaps", "st_snaps")):
        out.loc[late, c] = 900.0 + 37.0 * j + out.loc[late, c].fillna(0.0) * 3.0
    out.loc[late, "offense_pct"] = 0.99
    out.loc[late, "has_stats"] = True
    out[TD_STAT] = out.rushing_tds + out.receiving_tds
    return out


def _diff_rows(real: list, fake: list, skip: frozenset, first_output: int,
               names: list, probe: LeakProbe, week: int) -> None:
    """Compare two lists of harness rows field by field, into `probe`.

    Fields in `skip` are what was graded AGAINST and are expected to move.
    Fields from `first_output` on are the projectors' own numbers, one per
    name in `names`, in order. A different NUMBER of rows is a change in
    its own right: the extra rows are otherwise never looked at.
    """
    for n in names:
        probe.outputs.setdefault(n, 0)
    if len(real) != len(fake):
        probe.changed += 1
        if len(probe.examples) < 20:
            probe.examples.append((week, "row count", len(real), len(fake)))
    for a, b in zip(real, fake):
        for j, (x, y) in enumerate(zip(a, b)):
            if j in skip:
                continue
            if j >= first_output:
                if not (isinstance(x, float) and math.isnan(x)):
                    probe.outputs[names[j - first_output]] += 1
            else:
                probe.fields += 1
            if not _eq(x, y):
                probe.changed += 1
                if len(probe.examples) < 20:
                    probe.examples.append((week, a[:8][-1] if len(a) > 8
                                           else a[0], x, y))


def leak_probe(frame: pd.DataFrame, projectors: list[Projector],
               weeks: list[int]) -> LeakProbe:
    """Does anything from the week being projected, or later, reach a
    projection THROUGH THE FRAME?

    For each week it projects twice: once on the real frame and once on a
    frame where that week and everything after it has been overwritten.
    Lines, roles, single-number projections, probabilities and joint
    probabilities must come back identical. Only what was graded against
    moves. Read `LeakProbe` for what this cannot see.
    """
    names = [p.name for p in projectors]
    probe = LeakProbe(weeks=list(weeks), outputs={n: 0 for n in names})
    for t in weeks:
        real = run_week(frame, t, projectors)
        fake = run_week(scramble_from(frame, t), t, projectors)
        _diff_rows(real[0], fake[0], _PT_RESULT, _PT_OUT, names, probe, t)
        _diff_rows(real[1], fake[1], _LEG_RESULT, _LEG_OUT, names, probe, t)
        _diff_rows(real[3], fake[3], frozenset(), _JOINT_OUT, names, probe, t)
    return probe


# ---------------------------------------------------------------------------
# Error bars — clustered by game
# ---------------------------------------------------------------------------

def cluster_mean(x, cluster) -> tuple[float, float, int, int]:
    """(mean, standard error, n, clusters) with the error clustered.

    Players in one game rise and fall together, and so do one player's
    rungs. The standard error is the cluster-robust one for a mean. With
    fewer than two clusters there is no error to state and it is NaN.
    """
    x = np.asarray(x, dtype=float)
    n = len(x)
    if n == 0:
        return float("nan"), float("nan"), 0, 0
    m = float(x.mean())
    codes = pd.factorize(np.asarray(cluster, dtype=object))[0]
    g = int(codes.max()) + 1
    if g < 2:
        return m, float("nan"), n, g
    sums = np.bincount(codes, weights=x - m, minlength=g)
    se = math.sqrt(g / (g - 1.0) * float((sums ** 2).sum())) / n
    return m, se, n, g


def rate_range(hits, cluster) -> dict:
    """A rate with a 95% range that still means something near 0% and 100%.

    The range is Wilson's, on the EFFECTIVE number of observations: n cut
    down by how much wider the game-clustered error is than the naive one
    (never raised above n). Where that cannot be measured — fewer than five
    hits or five misses, or one game — each game counts once. A plain "rate
    plus or minus two standard errors" gives 40 hits in 40 a range of
    exactly 100% to 100%, and would call a stated 97% wrong.
    """
    rate, se, n, g = cluster_mean(np.asarray(hits, dtype=float), cluster)
    if n == 0:
        return {"rate": float("nan"), "se": float("nan"), "n": 0, "games": 0,
                "n_eff": 0.0, "lo": float("nan"), "hi": float("nan")}
    naive = math.sqrt(rate * (1.0 - rate) / n)
    hits_n = float(np.asarray(hits, dtype=float).sum())
    rare = min(hits_n, n - hits_n)
    if rare >= RARE_FOR_CLUSTERING and math.isfinite(se):
        n_eff = n / max((se / naive) ** 2, 1.0)
    else:
        # Every leg hit, or all but a handful did (or missed), or there is
        # one game: how much the legs in a game move together cannot be
        # measured from these legs. With one miss in 600 the clustered
        # error comes out equal to the naive one whatever the truth is.
        # Take the cautious end and count each game once.
        n_eff = float(g)
    z2 = Z95 ** 2
    mid = (rate + z2 / (2 * n_eff)) / (1 + z2 / n_eff)
    half = (Z95 * math.sqrt(rate * (1 - rate) / n_eff + z2 / (4 * n_eff ** 2))
            / (1 + z2 / n_eff))
    # At a rate of exactly 0 or 1 the range reaches it exactly; left to the
    # arithmetic it lands a rounding hair inside and a stated 100% reads as
    # wrong.
    lo = 0.0 if rate == 0.0 else max(0.0, mid - half)
    hi = 1.0 if rate == 1.0 else min(1.0, mid + half)
    return {"rate": rate, "se": se, "n": n, "games": g, "n_eff": n_eff,
            "lo": lo, "hi": hi}


def read_rate(stated: float, r: dict) -> str:
    """Does what happened agree with what was stated? One rule, used by
    every calibration table: the stated figure is inside the 95% range, or
    it is not. Refused under `MIN_GAMES_FOR_VERDICT` games."""
    if r["n"] == 0:
        return "nothing here"
    if r["games"] < MIN_GAMES_FOR_VERDICT:
        return "too few games to say"
    if r["lo"] <= stated <= r["hi"]:
        return "as stated"
    return ("happens LESS than stated" if r["rate"] < stated
            else "happens MORE than stated")


# ---------------------------------------------------------------------------
# Report 1 — the stat-line miss
# ---------------------------------------------------------------------------

def _select(df: pd.DataFrame, version: str) -> pd.DataFrame:
    if version not in ("A", "B"):
        raise ValueError(f"version must be 'A' or 'B', not {version!r}")
    return df[df.version == version]


_ERROR_COLS = ["stat", "projector", "n", "games", "coverage", "typical_miss",
               "mean_miss", "mean_miss_se", "bias"]


def stat_error(run: Run, *, version: str = "A", role_only: bool = True,
               dnp_as_zero: bool = False, common: bool = True) -> pd.DataFrame:
    """Typical miss of each projector's single number, by stat.

    `typical_miss` is the median absolute miss, `mean_miss` the mean
    absolute miss (its standard error clustered by game), `bias` the mean
    of (projected - actual): positive means it projects too high.
    `common=True` grades every projector on the same player-games, those
    where all of them had a projection; `coverage` is the share of
    player-games each one could project at all.

    `dnp_as_zero` only matters for version B: a player on the slate who did
    not play is dropped by default (a bet on him is void) and scored as a
    zero when this is True (a stat line for him was simply wrong).
    """
    d = _select(run.points, version)
    if role_only:
        d = d[d.role.astype(bool)]
    if dnp_as_zero:
        d = d.assign(actual=d.actual.where(d.played.astype(bool), 0.0))
    else:
        d = d[d.played.astype(bool)]
    cols = [f"pt_{n}" for n in run.names]
    rec = []
    for stat in STATS:
        s = d[d.stat == stat]
        if s.empty:
            continue
        has = s[cols].notna()
        use = s[has.all(axis=1)] if common else s
        for n, c in zip(run.names, cols):
            u = use[use[c].notna()]
            if u.empty:
                rec.append((stat, n, 0, 0, float(has[c].mean()),
                            *(float("nan"),) * 4))
                continue
            err = (u[c] - u.actual).to_numpy(dtype=float)
            mean_abs, se, _, g = cluster_mean(np.abs(err), u.game_id)
            rec.append((stat, n, len(u), g, float(has[c].mean()),
                        float(np.median(np.abs(err))), mean_abs, se,
                        float(err.mean())))
    return pd.DataFrame(rec, columns=_ERROR_COLS)


def compare_error(run: Run, a: str, b: str, *, version: str = "A",
                  role_only: bool = True) -> pd.DataFrame:
    """Mean absolute miss of `a` minus `b`, on the player-games both
    projected and he played, with a clustered error. Negative means `a`
    misses by less."""
    d = _select(run.points, version)
    d = d[d.played.astype(bool)]
    if role_only:
        d = d[d.role.astype(bool)]
    rec = []
    for stat in STATS:
        s = d[(d.stat == stat) & d[f"pt_{a}"].notna() & d[f"pt_{b}"].notna()]
        if s.empty:
            continue
        diff = (np.abs(s[f"pt_{a}"] - s.actual)
                - np.abs(s[f"pt_{b}"] - s.actual))
        m, se, n, g = cluster_mean(diff, s.game_id)
        rec.append((stat, n, g, m, se, _verdict(m, se, g)))
    return pd.DataFrame(rec, columns=["stat", "n", "games", "diff", "se",
                                      "read"])


def _verdict(diff: float, se: float, games: int) -> str:
    """A difference in words: which way, or that it cannot be told."""
    if games < MIN_GAMES_FOR_VERDICT or not math.isfinite(se):
        return "too few games to say"
    if abs(diff) <= Z95 * se:
        return "no difference that can be told from noise"
    return "lower" if diff < 0 else "higher"


# ---------------------------------------------------------------------------
# Report 2 — calibration of single lines
# ---------------------------------------------------------------------------

FOLDED_BANDS = tuple((round(0.50 + 0.05 * i, 2), round(0.55 + 0.05 * i, 2))
                     for i in range(10))
RAW_BANDS = tuple((round(0.1 * i, 1), round(0.1 * (i + 1), 1))
                  for i in range(10))

_EDGE = 1e-9    # 1 - 0.4 is not 0.6 in floating point; an edge belongs above


def _in_band(p: pd.Series, lo: float, hi: float, last: bool) -> pd.Series:
    """lo <= p < hi, or <= hi for the top band, with edges landing upward."""
    q = p + _EDGE
    return (q >= lo) & ((p <= hi + _EDGE) if last else (q < hi))


def _legs(run: Run, version: str, stats, rung) -> pd.DataFrame:
    """Played legs of one version, optionally of some stats or one rung."""
    d = _select(run.legs, version)
    d = d[d.played.astype(bool)]
    if stats is not None:
        d = d[d.stat.isin(list(stats))]
    if rung is not None:
        d = d[d.rung == rung]
    return d


def graded_legs(run: Run, name: str, *, version: str = "A",
                stats=None, rung: str | None = None) -> pd.DataFrame:
    """Legs with a probability from `name` and a result, plus `p`, the side
    it favours, that side's probability, and whether that side won.

    A leg stated at exactly 50% favours neither side and is put on OVER.
    """
    d = _legs(run, version, stats, rung)
    d = d[d[f"p_{name}"].notna()].copy()
    d["p"] = d[f"p_{name}"].astype(float)
    over = d["over"].astype(bool)
    fav_over = d.p >= 0.5
    d["side"] = np.where(fav_over, "OVER", "UNDER")
    d["p_side"] = np.where(fav_over, d.p, 1.0 - d.p)
    d["hit"] = np.where(fav_over, over, ~over)
    d["over"] = over
    return d


_CAL_COLS = ["band", "n", "legs_before_dedupe", "games", "stated", "happened",
             "se", "lo", "hi", "read"]


def _band_table(d: pd.DataFrame, p_col: str, hit_col: str, bands,
                dedupe) -> pd.DataFrame:
    """The one place a calibration table is made, for legs and pairs."""
    rec = []
    for lo, hi in bands:
        b = d[_in_band(d[p_col], lo, hi, hi >= bands[-1][1])]
        raw = len(b)
        if dedupe:
            b = b.sort_values("_near", kind="stable").drop_duplicates(dedupe)
        label = f"{lo:.0%}-{hi:.0%}"
        if b.empty:
            rec.append((label, 0, 0, 0, *(float("nan"),) * 5, "no legs"))
            continue
        stated = float(b[p_col].mean())
        r = rate_range(b[hit_col].astype(float), b.game_id)
        rec.append((label, r["n"], raw, r["games"], stated, r["rate"],
                    r["se"], r["lo"], r["hi"], read_rate(stated, r)))
    return pd.DataFrame(rec, columns=_CAL_COLS)


def calibration(legs: pd.DataFrame, *, folded: bool = True,
                bands=None) -> pd.DataFrame:
    """Stated probability against what happened, by band.

    `legs` comes from `graded_legs`. Folded (the default): each leg is
    read on the side the projector favours, so the bands run 50% to 100%
    and "60 to 65%" means "it said this side was 60 to 65% likely".
    Unfolded reads P(over) as stated, 0% to 100% — for touchdowns, where
    the favoured side is nearly always "no".

    Inside one band a player's ladder counts ONCE per stat and side (the
    rung nearest his main line): rungs win and lose together. `lo` to `hi`
    is the 95% range (`rate_range`), clustered by game. `read` is refused
    under 30 games.
    """
    p_col, hit_col = ("p_side", "hit") if folded else ("p", "over")
    bands = bands or (FOLDED_BANDS if folded else RAW_BANDS)
    d = legs.assign(_near=(legs.line - legs.main_line).abs())
    return _band_table(d, p_col, hit_col, bands,
                       ["game_id", "team", "player_id", "stat", "side"])


_SCORE_COLS = ["projector", "n", "games", "brier", "brier_se", "log_loss"]


def score_legs(run: Run, *, version: str = "A", stats=None,
               rung: str | None = None) -> pd.DataFrame:
    """Brier score and log loss of every projector on the SAME legs (those
    all of them priced). Lower is better. Read it beside `reference_brier`
    on the same legs, not beside a coin flip: on a ladder most rungs are
    easy, and saying 50% for all of them is not the know-nothing answer."""
    d = _legs(run, version, stats, rung)
    cols = [f"p_{n}" for n in run.names]
    d = d[d[cols].notna().all(axis=1)]
    y = d["over"].astype(float).to_numpy()
    rec = []
    for n, c in zip(run.names, cols):
        p = d[c].to_numpy(dtype=float)
        if not len(p):
            rec.append((n, 0, 0, *(float("nan"),) * 3))
            continue
        b, se, k, g = cluster_mean((p - y) ** 2, d.game_id)
        q = np.clip(p, 1e-6, 1 - 1e-6)
        ll = float(-(y * np.log(q) + (1 - y) * np.log(1 - q)).mean())
        rec.append((n, k, g, b, se, ll))
    return pd.DataFrame(rec, columns=_SCORE_COLS)


def _reference(run: Run, version: str, stats, rung):
    """(legs every projector priced, the know-nothing rate for each)."""
    d = _legs(run, version, stats, rung)
    d = d[d[[f"p_{n}" for n in run.names]].notna().all(axis=1)]
    y = d["over"].astype(float)
    base = (y.groupby([d.stat, d.rung]).transform("mean") if len(d)
            else y.copy())
    return d, y, base


def reference_brier(run: Run, *, version: str = "A", stats=None,
                    rung: str | None = None) -> dict:
    """The Brier score of knowing NOTHING about the player: for every leg,
    say the share of all legs of that stat and rung that went over.

    That share is worked out on the very legs it is scored on, which
    flatters it. So it is a hard reference: a projector has to beat a
    number that was allowed to peek. Scored on the legs every projector
    priced, the same legs `score_legs` uses.
    """
    d, y, base = _reference(run, version, stats, rung)
    if d.empty:
        return {"n": 0, "games": 0, "brier": float("nan"),
                "se": float("nan")}
    b, se, n, g = cluster_mean((base - y) ** 2, d.game_id)
    return {"n": n, "games": g, "brier": b, "se": se}


def compare_reference(run: Run, name: str, *, version: str = "A", stats=None,
                      rung: str | None = None) -> dict:
    """Brier of `name` minus the know-nothing reference, leg by leg on the
    same legs, with a clustered error. Negative means `name` knows
    something the reference does not."""
    d, y, base = _reference(run, version, stats, rung)
    diff = (d[f"p_{name}"] - y) ** 2 - (base - y) ** 2
    m, se, n, g = cluster_mean(diff, d.game_id)
    return {"projector": name, "n": n, "games": g, "diff": m, "se": se,
            "read": _verdict(m, se, g)}


def compare_brier(run: Run, a: str, b: str, *, version: str = "A",
                  stats=None, rung: str | None = None) -> dict:
    """Brier of `a` minus Brier of `b` on legs both priced, clustered.
    Negative means `a` has the lower Brier score."""
    d = _legs(run, version, stats, rung)
    d = d[d[f"p_{a}"].notna() & d[f"p_{b}"].notna()]
    y = d["over"].astype(float)
    diff = (d[f"p_{a}"] - y) ** 2 - (d[f"p_{b}"] - y) ** 2
    m, se, n, g = cluster_mean(diff, d.game_id)
    return {"a": a, "b": b, "n": n, "games": g, "diff": m, "se": se,
            "read": _verdict(m, se, g)}


def availability(run: Run, name: str) -> dict:
    """What knowing the active list is worth to one projector, and how much
    of the slate it changes. Players with a role only.

    `miss_diff` is A's mean miss minus B's on the player-games both
    versions projected and he played. For a projector that does not read
    the slate it is zero by construction, and `walk_forward` has already
    refused otherwise.
    """
    a = run.points[(run.points.version == "A")]
    b = run.points[(run.points.version == "B")]
    col = f"pt_{name}"
    keys = ["game_id", "team", "player_id"]
    m = a.merge(b[[*keys, "stat", col]], on=[*keys, "stat"],
                suffixes=("_a", "_b"))
    m = m[m.role.astype(bool) & m[f"{col}_a"].notna() & m[f"{col}_b"].notna()]
    diff = (np.abs(m[f"{col}_a"] - m.actual) - np.abs(m[f"{col}_b"] - m.actual))
    d, se, n, g = cluster_mean(diff, m.game_id)
    br = b[b.role.astype(bool)].drop_duplicates(keys)
    ar = a[a.role.astype(bool)].drop_duplicates(keys)
    # On B's slate at all, with a role there or not: a quarterback B lists
    # but does not line was still on its list.
    on_b = set(zip(b.game_id, b.team, b.player_id))
    seen = sum(1 for k in zip(ar.game_id, ar.team, ar.player_id) if k in on_b)
    return {"projector": name, "n": n, "games": g, "miss_diff": d, "se": se,
            "b_role_players": int(len(br)),
            "b_did_not_play": (float((~br.played.astype(bool)).mean())
                               if len(br) else float("nan")),
            "a_role_players": int(len(ar)),
            "a_not_on_b": float(1.0 - seen / len(ar)) if len(ar) else float("nan")}


# ---------------------------------------------------------------------------
# Report 3 — calibration of pairs
# ---------------------------------------------------------------------------

def side_legs(run: Run, name: str, *, version: str = "A") -> pd.DataFrame:
    """One OVER leg per player and market side, at his main stand-in line.

    The sides and the positions that carry them are `market_sides()`, which
    is `ff_correlation.SIDE_SPEC`, so a pair here is a pair the engine's
    table measured: PASS, RUSH, RECV, RECEPTIONS, PASS_TD and TD. Only legs
    that were played and that `name` priced.
    """
    d = _legs(run, version, None, MAIN)
    d = d[d[f"p_{name}"].notna()]
    out = []
    for side, positions, stat, binary in market_sides():
        s = d[(d.stat == stat) & d.position.isin(list(positions))]
        out.append(pd.DataFrame({
            "season": s.season.to_numpy(), "game_id": s.game_id.to_numpy(),
            "team": s.team.to_numpy(), "player_id": s.player_id.to_numpy(),
            "side": side, "binary": binary,
            "p": s[f"p_{name}"].to_numpy(dtype=float),
            "hit": s["over"].astype(bool).to_numpy()}))
    return pd.concat(out, ignore_index=True)


def build_pairs(sl: pd.DataFrame, joints: pd.DataFrame | None = None
                ) -> pd.DataFrame:
    """Every pair of legs in one game on two different players, once.

    Pass `run.joints` to add each projector's OWN P(both) as `j_<name>`
    (NaN where it stated none), so a simulator's joint can be scored beside
    `product` and beside a correlation table.
    """
    m = sl.merge(sl, on=["season", "game_id"], suffixes=("_a", "_b"))
    m = m[m.player_id_a != m.player_id_b]
    first = (m.side_a < m.side_b) | ((m.side_a == m.side_b)
                                     & (m.player_id_a < m.player_id_b))
    m = m[first].copy()
    m["relation"] = np.where(m.team_a == m.team_b, "same", "opp")
    m["both"] = m.hit_a & m.hit_b
    m["product"] = m.p_a * m.p_b
    m = m.reset_index(drop=True)
    if joints is not None and len(joints):
        m = m.merge(joints, on=_JOINT_KEYS, how="left")
    return m


_PAIR_WEIGHT = []


def _engine_pair_weight():
    """`ff_boost._pair_weight`, imported once and named if it has moved."""
    if not _PAIR_WEIGHT:
        try:
            from ff_boost import _pair_weight
        except ImportError as e:      # name the coupling rather than shim it
            raise ImportError(
                "ff_sim.corr_joint reads ff_boost._pair_weight, which this "
                "ff_boost.py does not have. The engine's joint arithmetic "
                "moved; tell the engine thread rather than copying it."
            ) from e
        _PAIR_WEIGHT.append(_pair_weight)
    return _PAIR_WEIGHT[0]


def corr_joint(pa: float, pb: float, r: float, bin_a: bool,
               bin_b: bool) -> float:
    """P(both) from two single probabilities and a table correlation.

    To first order: the product times (1 + r x weight), with the weight
    `ff_boost._pair_weight` gives for the kind of pair (two yardage legs,
    two yes/no legs, or one of each) — the engine's own function, not a
    copy. Held inside what any joint probability can be.

    THIS IS NOT WHAT THE ENGINE DOES WITH A CORRELATION. `ff_boost
    .joint_error` scores a pair at the pessimistic end of its interval,
    takes the worse of this term and the measured lift, and reports a bound
    on the product's error. It does not price a slip. This is the plain
    point estimate, which is what "the correlation table's adjustment"
    means in every table this module makes.

    A leg at exactly 0 or 1 has no room for a correlation: the product is
    exact and is returned.
    """
    if not (0.0 < pa < 1.0 and 0.0 < pb < 1.0):
        return float(pa * pb)
    za, zb = _NORM.inv_cdf(1.0 - pa), _NORM.inv_cdf(1.0 - pb)
    j = pa * pb * (1.0 + r * _engine_pair_weight()(pa, pb, za, zb,
                                                    bin_a, bin_b))
    return float(min(max(j, max(0.0, pa + pb - 1.0)), min(pa, pb)))


def add_corr(pairs: pd.DataFrame, table, col: str) -> pd.DataFrame:
    """Add `col`: the joint under a correlation table.

    `table` is {(relation, side, side): r} with the sides sorted, the shape
    `ff_correlation.recorded(RECORDED_MARKET_SIDE)` returns — or
    {season: such a table}, to use for each season a table measured only on
    EARLIER seasons. `<col>_measured` says whether a correlation was
    applied: False for a pair whose cell has no number, and for a pair with
    a leg at exactly 0 or 1. Either way the pair keeps the product and is
    counted, not hidden.
    """
    by_season = bool(table) and all(isinstance(k, (int, np.integer))
                                    for k in table)
    vals, had = [], []
    for season, rel, sa, sb, pa, pb, ba, bb in zip(
            pairs.season, pairs.relation, pairs.side_a, pairs.side_b,
            pairs.p_a, pairs.p_b, pairs.binary_a, pairs.binary_b):
        t = table.get(int(season), {}) if by_season else table
        r = t.get((rel, *sorted((sa, sb))))
        if r is None or not 0.0 < pa < 1.0 or not 0.0 < pb < 1.0:
            vals.append(pa * pb)
            had.append(False)
        else:
            vals.append(corr_joint(pa, pb, float(r), bool(ba), bool(bb)))
            had.append(True)
    out = pairs.copy()
    out[col] = vals
    out[f"{col}_measured"] = had
    return out


def pair_cells(pairs: pd.DataFrame, cols=("product",)) -> pd.DataFrame:
    """By (relation, side, side): what each method predicted for "both
    happen" against how often both did.

    `singles_product` is the two legs' ACTUAL hit rates multiplied, and
    `measured_lift` is `both` over that — how far the pair really is from
    independent, with the single-leg miscalibration taken out. `lift_se`
    is the lift's own clustered error: the numerator and the two rates
    under it rise and fall together game by game, and that is carried
    through (the delta method on the three means), not ignored.
    """
    rec = []
    for (rel, sa, sb), g in pairs.groupby(["relation", "side_a", "side_b"]):
        both = g.both.astype(float).to_numpy()
        ha = g.hit_a.astype(float).to_numpy()
        hb = g.hit_b.astype(float).to_numpy()
        rate, se, n, k = cluster_mean(both, g.game_id)
        ma, mb = float(ha.mean()), float(hb.mean())
        sp = ma * mb
        lift = rate / sp if sp > 0 else float("nan")
        lift_se = float("nan")
        if sp > 0:
            # d(lift) = d(both)/sp - lift * (d(a)/a + d(b)/b)
            lin = both / sp - lift * (ha / ma + hb / mb)
            lift_se = cluster_mean(lin, g.game_id)[1]
        row = [rel, sa, sb, n, k, rate, se, sp, lift, lift_se]
        for c in cols:
            row.append(float(g[c].mean()))
        rec.append(tuple(row))
    return pd.DataFrame(rec, columns=["relation", "side_a", "side_b", "n",
                                      "games", "both", "se", "singles_product",
                                      "measured_lift", "lift_se", *cols])


def pair_calibration(pairs: pd.DataFrame, col: str, relation: str | None = None,
                     bands=RAW_BANDS) -> pd.DataFrame:
    """Stated chance both happen, by band, against how often both did.
    Bands with no pair are left out. `n` counts PAIRS."""
    d = pairs if relation is None else pairs[pairs.relation == relation]
    t = _band_table(d, col, "both", bands, None)   # a blank joint is in no band
    return (t[t.n > 0].drop(columns=["legs_before_dedupe"])
            .reset_index(drop=True))


def pair_score(pairs: pd.DataFrame, cols) -> pd.DataFrame:
    """Brier score of each joint method on the same pairs (those every
    method named has a number for), and each method's difference from the
    first, clustered by game."""
    cols = list(cols)
    d = pairs[pairs[cols].notna().all(axis=1)]
    y = d.both.astype(float)
    base = (d[cols[0]] - y) ** 2
    rec = []
    for c in cols:
        loss = (d[c] - y) ** 2
        b, _, n, g = cluster_mean(loss, d.game_id)
        diff, se, _, _ = cluster_mean(loss - base, d.game_id)
        rec.append((c, n, g, b, diff, se,
                    "(the reference)" if c == cols[0] else _verdict(diff, se, g)))
    return pd.DataFrame(rec, columns=["method", "n", "games", "brier",
                                      "diff_vs_first", "se", "read"])


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_frame(years=(2023, 2024, 2025, 2026)) -> pd.DataFrame:
    """The frame for these seasons, from the engine's own loaders."""
    import ff_data
    years = list(years)
    return build_frame(ff_data.load_weekly(years), ff_data.load_snaps(years),
                       pd.concat([ff_data.load_roster(y) for y in years],
                                 ignore_index=True),
                       ff_data.load_pbp(years, columns=list(PBP_COLS)))
