#!/usr/bin/env python3
"""
ff_sim_play.py — S13. Each player's CHANCE OF PLAYING, and an opportunity
model that uses it.

THE PROBLEM IT FIXES. `ff_sim_opp.OpportunityModel` shares a team's targets
and carries among everyone on the slate it is handed. Handed a list that
includes players who will not play, it gives them a fifth of the volume and
everyone who does play too little. Before the inactive lists are out, that
is the list anyone has.

WHAT IT DOES

  1. `PlayChance` puts a chance of playing on every slate player, from two
     things known before kickoff: his status on the team's INJURY REPORT
     that week (out, doubtful, questionable, listed with no status, or not
     on it), and how many of his team's last four games he has missed. How
     often each combination has played is counted on the history, every
     week again, from earlier weeks only.

  2. A chance can also be HANDED IN (`given={player_id: chance}`), which
     overrides the counted one for that player. That is the run-time
     input: what the person running it knows from the report, the depth
     chart and the news. `given` with no report at all works too.

  3. `ChanceOpportunity` is the opportunity model with one change. A
     player's expected targets (or carries) are worked out AS IF HE PLAYS,
     with each teammate counted at his chance of playing:

         his share = his weight / (his weight + sum of chance x weight
                                   over his teammates)

     With every chance at 1 it is the opportunity model, number for
     number. A teammate who is out hands his share round; one who is
     questionable hands round part of it. The numbers no longer add up to
     the team's total, and are not meant to: each is one player's line in
     the games he plays, which is what a prop on him is settled on.
     It is an approximation: teammates are put in at their average
     presence, where really each plays or does not. That understates a
     player's expected share a little, most when one heavy teammate is
     near 50%; and teammates' absences are treated as unrelated.

WHAT THE COUNT GETS WRONG. A team's games are taken as one unbroken run
across seasons, so in Week 1 "played in the team's last game" means last
season's finale, and the count, made mostly on mid-season weeks, puts far
too high a chance on it (`sim_play.py`: said 77%, played 50%). From Week 2
on it is not biased. A status never seen in the history takes the
all-player rate; with the real reports every status has been seen since
2023.

WHAT IT DOES NOT DO. It does not pick the starting quarterback: the slate
names him, and if the named man is out, his backup is given no pass
attempts. At run time the starter has to be named by hand. It does not read
practice participation, only the game status. Players on injured reserve
are not on the weekly report at all; "missed the last three games" is what
catches them. And a status is taken as the report had it. A report stamped
on the day of the game or later is left out, so that nothing learned after
the main run is used; the 2025 and 2026 files carry no time stamps, so for
those seasons that cannot be checked and the rows are taken as published
(in 2023 and 2024, 18 of 11,405 stamped rows were from game day or later).

WHERE THE REPORTS COME FROM. nflverse's `injuries` release, one file a
season, fetched here into the same cache the engine uses. The engine's
loader does not know about it and is not edited (SIM-BACKLOG, "Needs").
The reports reach the model at construction, where the harness's leak
probe cannot see (S8, as with the closing lines). What stands there: a
report is only ever looked up for a game in the history, by that game's own
week, or for the week being projected; `test_sim.py` checks that a later
week's report moves nothing and that this week's does not reach what is
counted on the history; and the week's own report is published before its
games.

SET BY HAND, NOT TUNED (S2): how many earlier team-games are looked back
over (the harness's own four), how many rows a count is pulled toward its
status's rate with, and the fewest rows the counting needs.

    python3 sim_play.py --current-week 11

Owned by the simulator thread. It imports the engine and edits none of it.
"""
from __future__ import annotations

import sys
import urllib.request

import numpy as np
import pandas as pd

import ff_data
from ff_sim import CANDIDATE_LOOKBACK, History, slate_candidates
from ff_sim_opp import SHARED, OpportunityModel

#: A player's standing on the week's report, least worrying first.
STATUSES = ("none", "listed", "questionable", "doubtful", "out")
#: The report's own words for the three game statuses.
REPORT_WORD = {"Questionable": "questionable", "Doubtful": "doubtful",
               "Out": "out"}
REPORT_URL = "{B}/injuries/injuries_{yr}.parquet"

# CHOSEN, NOT TUNED (S2).
#: A cell's count is pulled toward its status's overall rate as if that
#: rate had been seen this many times.
PRIOR_ROWS = 20.0
#: Fewer listed player-games than this in the history and no chance is
#: counted: everyone is taken to play.
MIN_CHANCE_ROWS = 100


def fetch_reports(year: int, force: bool = False):
    """Download one season's injury reports if absent or stale. The engine's
    cache directory and staleness rule; its own file name."""
    dest = ff_data.CACHE / f"injuries_{year}.parquet"
    if not force and not ff_data._is_stale(dest):
        return dest
    ff_data.CACHE.mkdir(parents=True, exist_ok=True)
    url = REPORT_URL.format(B=ff_data.BASE, yr=year)
    tmp = dest.with_suffix(".tmp")
    try:
        with urllib.request.urlopen(url, timeout=180) as r, open(tmp, "wb") as f:
            while chunk := r.read(1 << 16):
                f.write(chunk)
    except Exception as e:                          # noqa: BLE001
        tmp.unlink(missing_ok=True)
        if dest.exists():
            print(f"  ! injuries {year} refresh failed ({e}); using cached copy",
                  file=sys.stderr)
            return dest
        raise RuntimeError(f"could not fetch injuries {year} from {url}: {e}") from e
    tmp.replace(dest)
    return dest


def clean_reports(raw: pd.DataFrame, games: pd.DataFrame) -> pd.DataFrame:
    """One row per player and week: [t, player_id, status].

    `raw` is nflverse's injuries table. `games` is one row per team-game
    already on file: [season, week, team, game_date]. Kept: regular
    season, and a report NOT known to have been changed on the day of the
    game or later. A report for a game that is not on file yet (this
    week's) is kept: that is the one a live run needs. A row with no time
    stamp is kept and counted: where stamps exist, almost every one is
    from before the day of the game. A player reported twice in a week
    keeps the later report. The counts are in `.attrs["report"]`.
    """
    need = {"season", "week", "team", "game_type", "gsis_id", "report_status",
            "date_modified"}
    if need - set(raw.columns):
        raise ValueError(f"the injury table is missing {sorted(need - set(raw.columns))}")
    reg = raw[(raw.game_type == "REG") & raw.gsis_id.notna()]
    m = reg.merge(games[["season", "week", "team", "game_date"]],
                  on=["season", "week", "team"], how="left")
    day = pd.to_datetime(m.game_date).dt.tz_localize("UTC")
    stamp = pd.to_datetime(m.date_modified, utc=True)
    late = (stamp.dt.normalize() >= day).to_numpy()   # False with no stamp or no game yet
    kept = m[~late]
    kept = (kept.assign(_stamp=stamp[~late])
            .sort_values("_stamp", kind="stable", na_position="first")
            .drop_duplicates(["season", "week", "gsis_id"], keep="last"))
    out = pd.DataFrame({
        "t": (kept.season * 100 + kept.week).astype(int).to_numpy(),
        "player_id": kept.gsis_id.to_numpy(dtype=object),
        "status": kept.report_status.map(REPORT_WORD).fillna("listed")
        .to_numpy(dtype=object)})
    out.attrs["report"] = {
        "rows": int(len(raw)), "regular_season": int(len(reg)),
        "game_not_on_file_yet": int(m.game_date.isna().sum()),
        "changed_on_game_day_or_later": int(late.sum()),
        "no_time_stamp": int(stamp.isna().sum()),
        "second_report_same_week": int((~late).sum() - len(kept)),
        "kept": int(len(out))}
    return out


def load_reports(years) -> pd.DataFrame:
    """`clean_reports` on the seasons asked for, from nflverse."""
    years = [int(y) for y in years]
    raw = pd.concat([pd.read_parquet(fetch_reports(y)) for y in years],
                    ignore_index=True)
    pbp = ff_data.load_pbp(years, columns=["game_id", "season", "week",
                                           "home_team", "away_team", "game_date"])
    g = pbp.drop_duplicates("game_id")
    games = pd.concat([
        g[["season", "week", side, "game_date"]].rename(columns={side: "team"})
        for side in ("home_team", "away_team")], ignore_index=True)
    return clean_reports(raw, games)


def listed_history(F: pd.DataFrame, lookback: int = CANDIDATE_LOOKBACK) -> pd.DataFrame:
    """For every team-game in `F`, the players the harness's slate B would
    have listed for it (active for that team in one of its `lookback` games
    before), with whether each then PLAYED and how many of those games he
    had MISSED since he last played for it (0 = he played its last game).
    Columns [team, t, player_id, missed, played]."""
    A = F[["team", "t", "player_id"]].drop_duplicates()
    tw = A[["team", "t"]].drop_duplicates().sort_values(["team", "t"], kind="stable")
    tw["seq"] = tw.groupby("team").cumcount()
    A = A.merge(tw, on=["team", "t"])[["team", "seq", "player_id"]]
    C = (pd.concat([A.assign(seq=A.seq + d, back=d) for d in range(1, lookback + 1)],
                   ignore_index=True)
         .groupby(["team", "seq", "player_id"], as_index=False).back.min())
    C = C.merge(tw, on=["team", "seq"])      # a game the team has not played drops out
    C = C.merge(A.assign(played=True), on=["team", "seq", "player_id"], how="left")
    return pd.DataFrame({
        "team": C.team.to_numpy(dtype=object), "t": C.t.to_numpy(),
        "player_id": C.player_id.to_numpy(dtype=object),
        "missed": (C.back - 1).to_numpy(),
        "played": C.played.notna().to_numpy()})


class ChanceFit:
    def __init__(self):
        self.ok = False
        self.why = ""
        self.rows = 0
        self.by_status = {}     # status -> how often that status played
        self.cell = {}          # (status, missed) -> chance; every cell filled
        self.count = {}         # (status, missed) -> rows it was counted on


class PlayChance:
    """Each slate player's chance of playing. See the module docstring.

        PlayChance()                              games missed lately only
        PlayChance(reports)                       ...and the injury report
        PlayChance(reports, given={pid: 0.25})    ...and what is handed in

    `reports` is `load_reports(...)`: [t, player_id, status]. A key of
    `given` is a player id, or (team, player id) for a player listed under
    two teams; the pair wins.
    """

    def __init__(self, reports: pd.DataFrame | None = None,
                 given: dict | None = None):
        if reports is not None:
            bad = sorted(set(reports["status"]) - set(STATUSES))
            if bad:
                raise ValueError(f"unknown injury status {bad}; expected one "
                                 f"of {STATUSES}")
            if reports.duplicated(["t", "player_id"]).any():
                raise ValueError("a player has two reports in one week")
        for pid, p in (given or {}).items():
            if not 0.0 <= float(p) <= 1.0:
                raise ValueError(f"the chance handed in for {pid} is {p}; it "
                                 f"must be between 0 and 1")
        self.reports = reports
        # {(week, player): status}. It is only ever asked about a game in
        # the history, by that game's own week, or about the week being
        # projected: see `fit` and `describe`.
        self._status = ({} if reports is None else
                        dict(zip(zip(reports.t, reports.player_id), reports.status)))
        self.given = dict(given or {})
        self._last = (None, None)

    def fit(self, hist: History) -> ChanceFit:
        """Count, on the history alone, how often each status and each
        number of games missed went on to play."""
        if self._last[0] is hist:
            return self._last[1]
        fit = ChanceFit()
        L = listed_history(hist.frame)
        fit.rows = len(L)
        if len(L) < MIN_CHANCE_ROWS:
            fit.why = (f"only {len(L)} listed player-games in the history; "
                       f"needs {MIN_CHANCE_ROWS}")
            self._last = (hist, fit)
            return fit
        status = np.array([self._status.get(k, "none")
                           for k in zip(L.t, L.player_id)], dtype=object)
        played = L.played.to_numpy(dtype=float)
        everyone = float(played.mean())
        for s in STATUSES:
            is_s = status == s
            rate = float(played[is_s].mean()) if is_s.any() else everyone
            fit.by_status[s] = rate
            for miss in range(CANDIDATE_LOOKBACK):
                in_cell = is_s & (L.missed.to_numpy() == miss)
                n = int(in_cell.sum())
                fit.count[(s, miss)] = n
                fit.cell[(s, miss)] = float(
                    (played[in_cell].sum() + PRIOR_ROWS * rate) / (n + PRIOR_ROWS))
        fit.ok = True
        self._last = (hist, fit)
        return fit

    def describe(self, hist: History, slate: pd.DataFrame) -> pd.DataFrame:
        """Per slate row: [status, missed, chance, source]. `missed` is how
        many of his team's last four games he has sat out since he last
        played for it; blank if he played in none of them. `source` says
        where the chance came from: "given", "counted", or "taken to play"
        when the history is too thin to count on."""
        fit = self.fit(hist)
        week = set((slate["season"] * 100 + slate["week"]).astype(int))
        if week - {hist.before}:
            raise ValueError(f"the slate is for week {sorted(week)} and the "
                             f"history stops before {hist.before}")
        F = hist.frame
        last = F.groupby(["team", "player_id"]).t.max().to_dict()
        weeks = {tm: np.sort(g.unique())[-CANDIDATE_LOOKBACK:]
                 for tm, g in F.groupby("team").t}
        rec = []
        for tm, pid in zip(slate["team"], slate["player_id"]):
            status = self._status.get((hist.before, pid), "none")
            tw = weeks.get(tm, np.array([]))
            seen = last.get((tm, pid))
            missed = (int((tw > seen).sum())
                      if seen is not None and len(tw) and seen >= tw[0] else None)
            handed = self.given.get((tm, pid), self.given.get(pid))
            if handed is not None:
                rec.append((status, missed, float(handed), "given"))
            elif not fit.ok:
                rec.append((status, missed, 1.0, "taken to play"))
            elif missed is None:
                rec.append((status, missed, fit.by_status[status], "counted"))
            else:
                rec.append((status, missed, fit.cell[(status, missed)], "counted"))
        return pd.DataFrame(rec, columns=["status", "missed", "chance", "source"])

    def chances(self, hist: History, slate: pd.DataFrame) -> np.ndarray:
        """Each slate row's chance of playing."""
        return self.describe(hist, slate)["chance"].to_numpy(dtype=float)


class ChanceOpportunity(OpportunityModel):
    """The opportunity model with each teammate counted at his chance of
    playing. See the module docstring.

        ChanceOpportunity("opp_report", chance=PlayChance(reports))
    """

    def __init__(self, name: str = "opportunity_chance",
                 chance: PlayChance | None = None, lines: dict | None = None,
                 single: str = "mean"):
        super().__init__(name, lines=lines, single=single)
        self.chance = chance if chance is not None else PlayChance()

    def means(self, hist: History, slate: pd.DataFrame) -> dict:
        out = dict(super().means(hist, slate))
        p = self.chance.chances(hist, slate)
        team = pd.Series(list(zip(slate["game_id"], slate["team"])), dtype=object)
        for stat in SHARED:
            m = out[stat]
            whole = pd.Series(m).groupby(team).transform("sum").to_numpy()
            likely = pd.Series(p * m).groupby(team).transform("sum").to_numpy()
            beside = m + (likely - p * m)       # him, and his teammates at their chances
            out[stat] = np.divide(whole * m, beside, out=m.copy(), where=beside > 0)
        return out


def chance_vs_played(chance: PlayChance, frame: pd.DataFrame, weeks) -> pd.DataFrame:
    """One row per week and player the harness's slate B lists: the chance
    of playing he was given beside whether he played. Columns [t, game_id,
    team, player_id, status, missed, chance, source, played]."""
    out = []
    for t in weeks:
        hist = History(frame[frame.t < t], t)
        slate = slate_candidates(frame, hist)
        d = chance.describe(hist, slate)
        was = set(zip(frame.team[frame.t == t], frame.player_id[frame.t == t]))
        out.append(pd.DataFrame({
            "t": int(t), "game_id": slate["game_id"].to_numpy(),
            "team": slate["team"].to_numpy(),
            "player_id": slate["player_id"].to_numpy(),
            "status": d.status.to_numpy(), "missed": d.missed.to_numpy(),
            "chance": d.chance.to_numpy(), "source": d.source.to_numpy(),
            "played": [k in was for k in zip(slate["team"], slate["player_id"])]}))
    return pd.concat(out, ignore_index=True)
