#!/usr/bin/env python3
"""
ff_sim_live.py — S28. A shadow run: the simulator on a slate not yet played.

It reads what a project thread saves to files, builds this week's slate from
the history, runs the simulator as it was measured (touchdowns on efficiency
on opportunity, with a chance of playing), and sets each player's projected
stat line and the chance of clearing each posted line beside the record of
the band that chance falls in.

WHAT IT NEEDS, AND IT STOPS IF ANY IS MISSING (`Missing`)
  1. One saved `propline_get_odds` EVENT response per game: the dict, its
     JSON text, or the file the harness saved it to. Only the lines are
     read. Prices are not used, printed or saved: a posted line is a
     benchmark here, not a lean.
  2. The week, and the STARTING QUARTERBACK of every team in those games.
     The model gives pass attempts to the named starter and to nobody else.
  3. This week's injury report on file (nflverse) for at least one player
     in those games, unless the run says it may go without. That file can
     be days behind the league's own report, so the inputs may hand in a
     player's STATUS (out, doubtful, questionable, listed, none), which
     replaces the file's for him, or his CHANCE of playing outright, which
     overrides both.
  4. The record (`sim_record.py`), built from the same model code.

THE SLATE is the harness's "list not known" slate, which is what the record
was measured on: everyone active for a team in one of its last four games,
plus anyone the inputs add, plus the named starter. A player back after
longer out, or new to the team, is not on it until he is added.

WHICH TEAM A POSTED PLAYER IS PRICED FOR. The team the odds file puts him
on, when it says, and he must be on that team's slate. If the file puts
him on more than one team (two books, or one with his id and one
without), or on a team that is not in the game, he is not priced. A
name with no id is never enough when two players on these teams share it. When
it does not say: the one slate he is on, unless the roster has him on the
other team in this game; a player on both slates is not priced. Whatever
is not priced is listed with the reason, never dropped and never guessed.

IS IT THIS WEEK'S GAME. A game in progress or already started is refused.
So is one outside the season, and one outside the Wednesday-to-Tuesday
week that follows last week's Sunday. With no dates to go by (Week 1, or
last week's are not on file) it refuses only a game more than eight days
off, and says that is all it could do.

EVERY NUMBER IS "IF HE PLAYS". A player's expected line and his chances are
worked out with him playing and each teammate playing with his own chance.

WHAT THE RECORD IS AND IS NOT. The walk-forward record of this set-up (list
not known, with the report), on stand-in lines made from each player's own
recent games. Three things it is not:
  - It has not been graded against a book's line (S3).
  - It covers only players the harness gives a stand-in line: four recent
    games and a role in them (a median of 3 targets, 5 carries or 20 pass
    attempts; a passing role only for the starter). A line for anyone else
    is printed with no record.
  - It was graded with each team's LAST game's starter, the injury file as
    it stood, and nothing handed in.
A posted line is read on the record of HIS OWN stand-in rung nearest to it
(his stand-in main line is the half point above his eight-game median,
and the others are multiples of that median), because the record differs
by rung (S21); a line off his ladder has no record. That holds for every
stat, passing touchdowns included. An anytime touchdown is read on the
chance of scoring as stated.

    python3 sim_live.py --week 11 --inputs week11.json odds/*.json

Owned by the simulator thread. It imports the engine and edits none of it.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path

import pandas as pd

import ff_sim as fs
from ff_props import flatten_odds, norm_player
from ff_sim import (CANDIDATE_LOOKBACK, FAMILY, FOLDED_BANDS, MAIN, RAW_BANDS,
                    RUNG_FACTORS, TD_STAT, History, tkey)
from ff_sim_eff import EfficiencyModel
from ff_sim_play import STATUSES, ChanceOpportunity, PlayChance
from ff_sim_td import ALL_STATS, TouchdownModel

#: PropLine's team names -> the codes the history uses.
TEAM_CODE = {
    "Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL",
    "Baltimore Ravens": "BAL", "Buffalo Bills": "BUF",
    "Carolina Panthers": "CAR", "Chicago Bears": "CHI",
    "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE",
    "Dallas Cowboys": "DAL", "Denver Broncos": "DEN", "Detroit Lions": "DET",
    "Green Bay Packers": "GB", "Houston Texans": "HOU",
    "Indianapolis Colts": "IND", "Jacksonville Jaguars": "JAX",
    "Kansas City Chiefs": "KC", "Los Angeles Rams": "LA",
    "Los Angeles Chargers": "LAC", "Las Vegas Raiders": "LV",
    "Miami Dolphins": "MIA", "Minnesota Vikings": "MIN",
    "New England Patriots": "NE", "New Orleans Saints": "NO",
    "New York Giants": "NYG", "New York Jets": "NYJ",
    "Philadelphia Eagles": "PHI", "Pittsburgh Steelers": "PIT",
    "Seattle Seahawks": "SEA", "San Francisco 49ers": "SF",
    "Tampa Bay Buccaneers": "TB", "Tennessee Titans": "TEN",
    "Washington Commanders": "WAS",
}
#: market key -> (the stat it settles on, the line when the outcome has none)
MARKETS = {
    "player_pass_yds": ("passing_yards", None),
    "player_pass_attempts": ("attempts", None),
    "player_pass_completions": ("completions", None),
    "player_pass_tds": ("passing_tds", None),
    "player_rush_yds": ("rushing_yards", None),
    "player_rush_attempts": ("carries", None),
    "player_reception_yds": ("receiving_yards", None),
    "player_receptions": ("receptions", None),
    "player_reception_targets": ("targets", None),
    "player_anytime_td": (TD_STAT, 0.5),
    "player_2plus_td": (TD_STAT, 1.5),
    "player_3plus_td": (TD_STAT, 2.5),
}
#: The files the record depends on. A record built from other code is refused.
MODEL_FILES = ("ff_sim.py", "ff_sim_opp.py", "ff_sim_eff.py", "ff_sim_play.py",
               "ff_sim_td.py")
#: A leg on a player's stand-in main line at or above this carries the S21
#: caution. Kept in the record too, which is refused if they differ.
S21_FROM = 0.65
#: The record's layout. A record with another number is refused.
LAYOUT = 3
RECORD_KEYS = ("layout", "code", "s21_from", "first", "through", "weeks",
               "bands", "s21")
RUNG_LABELS = ("x0.6", "x0.8", MAIN, "x1.25", "x1.6")
#: A game further off than this is not this week's. Used only when last
#: week's dates are not to hand (`week_window`).
MAX_DAYS_AHEAD = 8
#: An NFL week runs Wednesday to Tuesday. In UTC it starts this long after
#: 00:00 on the Sunday before it (a Tuesday night game is over by 09:00 UTC
#: on Wednesday, and no Wednesday game starts that early), and lasts seven
#: days.
WEEK_STARTS = pd.Timedelta(days=3, hours=9)
#: Positions a player may be added at.
ADD_AT = ("QB", "RB", "FB", "WR", "TE")
INPUT_KEYS = {"season", "week", "starters", "statuses", "chances", "add"}
ROW_KEYS = {"statuses": {"team", "player", "status"},
            "chances": {"team", "player", "chance"},
            "add": {"team", "player", "position"}}
#: Not players: left out without comment.
NOT_A_PLAYER = re.compile(r"d/st$|^no (touchdown|td) scorer$|^no scorer$", re.I)
GSIS = re.compile(r"^\d\d-\d{7}$")
PASS_TD_UNDER = ("the UNDER is unreliable: passing-touchdown unders are "
                 "overstated by about 5 points (S24)")
NO_ROLE = ("he has no stand-in line for this stat (it takes four recent "
           "games and a role in them), so the record does not cover him")
OFF_LADDER = "the line is outside his stand-in ladder"
TWO_PLUS = "nothing grades two or more"


class Missing(Exception):
    """Something the run needs is not there. The message says what."""


# ---------------------------------------------------------------------------
# What the thread saved
# ---------------------------------------------------------------------------

def read_odds(source) -> dict:
    """One `propline_get_odds` event response, however it was saved: the
    dict, its JSON text, a path to either, or the harness's text-block
    wrapper round it."""
    where = "the response"
    if isinstance(source, (str, Path)):
        s = str(source)
        if not s.lstrip().startswith(("{", "[")):
            where = s
            try:
                s = Path(s).read_text()
            except (OSError, UnicodeDecodeError) as e:
                raise Missing(f"cannot read the odds file {where}: {e}") from e
        try:
            source = json.loads(s)
        except ValueError as e:
            raise Missing(f"{where} is not JSON: {e}") from e
    if isinstance(source, list) and source and isinstance(source[0], dict) \
            and "text" in source[0]:
        try:
            source = json.loads(source[0]["text"])
        except ValueError as e:
            raise Missing(f"{where} is a saved tool result whose text is not "
                          f"JSON: {e}") from e
    if not isinstance(source, dict) or not isinstance(source.get("bookmakers"), list):
        raise Missing(f"{where} is not a get_odds EVENT response: it has no "
                      f"'bookmakers' list. Pull each game with its event_id.")
    for side in ("home_team", "away_team"):
        if source.get(side) not in TEAM_CODE:
            raise Missing(f"{where}: {side} is {source.get(side)!r}, which is "
                          f"not an NFL team name this file knows")
    return source


def game_of(event: dict) -> str:
    """"LV at DEN" for an event response."""
    return f"{TEAM_CODE[event['away_team']]} at {TEAM_CODE[event['home_team']]}"


def week_window(dates, week: int):
    """(start, end), UTC, of the Wednesday-to-Tuesday week that `week`'s
    games are played in, going by the Sunday of the week before it.
    `dates` is one season's regular-season games, [week, game_date]. None
    when that Sunday is not in it (Week 1, or no dates to hand)."""
    if dates is None or week <= 1:
        return None
    prev = pd.to_datetime(dates.loc[dates["week"] == week - 1, "game_date"])
    sundays = prev[prev.dt.dayofweek == 6]
    if not len(sundays):
        return None
    start = sundays.max().tz_localize("UTC") + WEEK_STARTS
    return start, start + pd.Timedelta(days=7)


NO_WINDOW = ("this week's dates could not be worked out from last week's "
             "games (Week 1, or they are not on file): a game was refused "
             "only if more than eight days off, which next week's Thursday "
             "game can pass from Wednesday on")


def check_kickoffs(events, now, window=None, season=None) -> list:
    """Refuse a game that is in progress, has started, is not in `season`
    (August to February), or is not this week's: outside `window` (from
    `week_window`), or, with no window, more than eight days off. `now` is
    a UTC time. Returns notes: one when there was no window, and one for
    each file with no kickoff time to check."""
    notes = [] if window is not None else [NO_WINDOW]
    for e in events:
        if e.get("live"):
            raise Missing(f"{game_of(e)} is in progress: its odds are not "
                          f"pregame lines")
        try:
            kick = pd.Timestamp(e.get("commence_time"))
            kick = kick.tz_localize("UTC") if kick.tzinfo is None else kick.tz_convert("UTC")
        except (ValueError, TypeError):
            kick = pd.NaT
        if pd.isna(kick):
            notes.append(f"{game_of(e)}: no kickoff time in the odds file, "
                         f"so it was not checked to be this week's game")
        elif kick <= now:
            raise Missing(f"{game_of(e)} kicked off {kick:%Y-%m-%d %H:%M} UTC: "
                          f"the game has started")
        elif season is not None and not (
                pd.Timestamp(f"{season}-08-01", tz="UTC") <= kick
                < pd.Timestamp(f"{season + 1}-03-01", tz="UTC")):
            raise Missing(f"{game_of(e)} kicks off {kick:%Y-%m-%d}, which is "
                          f"not in the {season} season")
        elif window is not None and not window[0] <= kick < window[1]:
            raise Missing(f"{game_of(e)} kicks off {kick:%Y-%m-%d %H:%M} UTC, "
                          f"which is not in this week (Wednesday "
                          f"{window[0]:%Y-%m-%d} to Tuesday "
                          f"{window[1] - pd.Timedelta(days=1):%Y-%m-%d}, going "
                          f"by last week's games): it is another week's game")
        elif window is None and kick > now + pd.Timedelta(days=MAX_DAYS_AHEAD):
            raise Missing(f"{game_of(e)} kicks off {kick:%Y-%m-%d}, more than "
                          f"{MAX_DAYS_AHEAD} days from now: that is not this "
                          f"week's game")
    return notes


def posted_lines(event: dict, books=None) -> pd.DataFrame:
    """Every line in one event response that the simulator has a stat for:
    one row per book, market, player and line.

        [book, market, stat, player, player_key, line, kind, suspended]

    `line` is the point of an over/under, half a point under an "N+" rung,
    or the market's own (0.5 for an anytime touchdown). `kind` is "main"
    for a book's main line and for the anytime touchdown, else "ladder".
    The pairing of outcomes is `ff_props.flatten_odds`'s; prices are
    dropped here. `.attrs["passed_over"]` counts what was left out and
    why: {"no stat for <market>": n, "label not read in <market>": n}."""
    try:
        quotes = flatten_odds(event, line_type="")
    except ValueError as e:
        raise Missing(f"{game_of(event)}: the odds file does not pair up: {e}") from e
    except (AttributeError, TypeError) as e:
        raise Missing(f"{game_of(event)}: the odds file is not in the shape "
                      f"of a get_odds response ({type(e).__name__}: {e})") from e
    rec, passed = [], Counter()
    for q in quotes:
        if NOT_A_PLAYER.search(str(q["player"]).strip()):
            continue
        if books and q["book"] not in books:
            continue
        if q["market"] not in MARKETS:
            passed[f"no stat for {q['market']}"] += 1
            continue
        stat, own = MARKETS[q["market"]]
        if q["line"] is not None:
            try:
                line = float(q["line"])
            except (TypeError, ValueError):
                line = float("nan")
        elif q.get("rung_threshold") is not None:
            line = float(q["rung_threshold"]) - 0.5
        elif own is not None:
            line = own
        else:
            line = float("nan")     # a label that is neither a line nor a rung
        if not math.isfinite(line):
            passed[f"label not read in {q['market']}"] += 1
            continue
        main = (q["line_type"] == "main" and q["line"] is not None) \
            or q["market"] == "player_anytime_td"
        rec.append((q["book"], q["market"], stat, q["player"], q["player_id"],
                    line, "main" if main else "ladder",
                    q["suspended_at"] is not None))
    out = pd.DataFrame(rec, columns=["book", "market", "stat", "player",
                                     "player_key", "line", "kind", "suspended"])
    out.attrs["passed_over"] = dict(passed)
    return out


def book_players(event: dict) -> list:
    """Every player outcome in the response, once each: [(player as the
    book has him, the book's id for him or None, the team it puts him on
    or None)]. The team is a code, or the name as given when it is not a
    team this knows."""
    seen = {}
    for bk in event.get("bookmakers") or []:
        for mk in bk.get("markets") or []:
            for oc in mk.get("outcomes") or []:
                who = oc.get("description") or oc.get("name")
                if not isinstance(who, str) or NOT_A_PLAYER.search(who.strip()):
                    continue
                key = oc.get("player_id")
                team = oc.get("player_team")
                team = TEAM_CODE.get(team, team) if isinstance(team, str) and team else None
                seen[(who, key if isinstance(key, str) and key else None, team)] = None
    return list(seen)


def read_inputs(source) -> dict:
    """The inputs file: {"season", "week", "starters": {team: player},
    "statuses": [{"team", "player", "status"}], "chances": [{"team",
    "player", "chance"}], "add": [{"team", "player", "position"}]}.
    `statuses`, `chances` and `add` may be left out. A team is its code or
    its full name; a player is his name, his nflverse id, or "espn:<id>";
    a status is one of `ff_sim_play.STATUSES`. Anything else in it is
    refused: a misspelt key would otherwise be a hand-in silently lost."""
    if isinstance(source, (str, Path)):
        try:
            source = json.loads(Path(source).read_text())
        except OSError as e:
            raise Missing(f"cannot read the inputs file {source}: {e}") from e
        except ValueError as e:
            raise Missing(f"the inputs file is not JSON: {e}") from e
    if not isinstance(source, dict) or not isinstance(source.get("starters"), dict):
        raise Missing('the inputs have no "starters": the starting '
                      'quarterback of each team, {"DEN": "Bo Nix", ...}')
    odd = sorted(set(source) - INPUT_KEYS)
    if odd:
        raise Missing(f"the inputs have {odd}, which is not one of "
                      f"{sorted(INPUT_KEYS)}")
    out = {"statuses": [], "chances": [], "add": [], "starters": {}}
    for k in ("season", "week"):
        v = source.get(k)
        if v is not None and (isinstance(v, bool) or not isinstance(v, int)):
            raise Missing(f'the inputs give "{k}" as {v!r}; it must be a '
                          f"whole number")
        out[k] = v
    if out["week"] is not None and not 1 <= out["week"] <= 22:
        raise Missing(f'the inputs give "week" as {out["week"]}; it must be '
                      f"from 1 to 22")
    for team, who in source["starters"].items():
        if team_code(team) in out["starters"]:
            raise Missing(f"{team_code(team)} has two starters named in the inputs")
        out["starters"][team_code(team)] = who
    for kind, keys in ROW_KEYS.items():
        rows = source.get(kind) or []
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            raise Missing(f'"{kind}" in the inputs must be a list of '
                          f"{{{', '.join(sorted(keys))}}} rows")
        for row in rows:
            if set(row) - keys or not {"team", "player"} <= set(row):
                raise Missing(f'a "{kind}" row in the inputs is {row}; it '
                              f"takes {sorted(keys)}")
            team, who = team_code(row["team"]), row["player"]
            if kind == "statuses":
                if row.get("status") not in STATUSES:
                    raise Missing(f"the status handed in for {who!r} is "
                                  f"{row.get('status')!r}; it must be one of "
                                  f"{STATUSES}")
                out[kind].append((team, who, row["status"]))
            elif kind == "chances":
                p = row.get("chance")
                if not isinstance(p, (int, float)) or isinstance(p, bool) \
                        or not 0.0 <= p <= 1.0:
                    raise Missing(f"the chance handed in for {who!r} is "
                                  f"{p!r}; it must be a number from 0 to 1")
                out[kind].append((team, who, float(p)))
            else:
                if row.get("position") is not None and row["position"] not in ADD_AT:
                    raise Missing(f"the position handed in for {who!r} is "
                                  f"{row['position']!r}; it must be one of "
                                  f"{ADD_AT}, or left out")
                out[kind].append((team, who, row.get("position")))
    return out


def team_code(team) -> str:
    """A team's code, from its code or its full name."""
    if team in TEAM_CODE:
        return TEAM_CODE[team]
    if team in TEAM_CODE.values():
        return team
    raise Missing(f"{team!r} is not an NFL team code or name")


# ---------------------------------------------------------------------------
# Who is who
# ---------------------------------------------------------------------------

class Names:
    """Finds a player's nflverse id from what a book or the inputs call him.

    `roster` is `ff_data.load_roster(season)`. An ESPN id is looked up in
    it. A player counts as on a team when the roster has him there or he
    has played for it in `season`; a name must match exactly one player on
    the team named, and an id given outright must be someone on it. So a
    man who left in an earlier season is not found there, unless he is
    being added (`find(..., anywhere=True)`)."""

    def __init__(self, roster: pd.DataFrame, hist: History, season: int):
        r = roster[roster["gsis_id"].notna()]
        has = r[r["espn_id"].notna()]
        self.espn = {str(e).split(".")[0]: g for e, g in zip(has.espn_id, has.gsis_id)}
        self.position = dict(zip(r.gsis_id, r.position))
        self.full = dict(zip(r.gsis_id, r.full_name))
        self.team = dict(zip(r.gsis_id, r.team))
        self.by_name, self.on, self.any_name, self.known = {}, set(), {}, set()
        F = hist.frame[hist.frame["season"] == season]
        F = F.drop_duplicates(["team", "player_id"], keep="last")
        for ids, names, teams in ((r.gsis_id, r.full_name, r.team),
                                  (F.player_id, F.name, F.team)):
            for g, name, team in zip(ids, names, teams):
                self.by_name.setdefault((team, norm_player(name)), set()).add(g)
                self.any_name.setdefault(norm_player(name), set()).add(g)
                self.on.add((team, g))
                self.known.add(g)

    def from_key(self, key):
        """The nflverse id for a book's "espn:<id>", or None."""
        if isinstance(key, str) and key.startswith("espn:"):
            return self.espn.get(key[5:])
        return None

    def find(self, team: str, who, anywhere: bool = False) -> str:
        """The one player `who` names on `team`, or `Missing`. With
        `anywhere` (a player being added), an id may be anyone the roster
        or this season has, and a name nobody on the team has may be the
        one player of that name in the league."""
        who = str(who or "").strip()
        got = who if GSIS.match(who) else self.from_key(who)
        if got is not None:
            if (team, got) not in self.on and not (anywhere and got in self.known):
                raise Missing(f"{self.full.get(got, got)} ({who}) is not on "
                              f"{team}: the roster does not have him there "
                              f"and he has not played for it this season")
            return got
        found = self.by_name.get((team, norm_player(who)), set())
        if anywhere and not found:
            found = self.any_name.get(norm_player(who), set())
        if len(found) != 1:
            raise Missing(
                f"{'no player' if not found else 'more than one player'} "
                f"called {who!r} on {team} this season"
                + (f" ({sorted(found)})" if found else "")
                + ". Give his nflverse id (like 00-0039732) instead.")
        return next(iter(found))


# ---------------------------------------------------------------------------
# The slate
# ---------------------------------------------------------------------------

def build_slate(hist: History, season: int, week: int, games, starters: dict,
                names: Names, add=()) -> pd.DataFrame:
    """This week's slate, in the harness's columns.

    `games` is [(away code, home code), ...]. A team's rows are everyone
    active for it in one of its last four games, anyone in `add` ([(team,
    player id, position or None)]) and its named starter, who alone is
    marked `starting_qb`. Refuses a team with no starter named, a team in
    two games, a team with no history, and a starter not listed at
    quarterback (add him with that position if he really is starting)."""
    t = tkey(season, week)
    if t != hist.before:
        raise ValueError(f"the slate is for {t} and the history stops before "
                         f"{hist.before}")
    teams = [tm for g in games for tm in g]
    twice = sorted({tm for tm in teams if teams.count(tm) > 1})
    if twice:
        raise Missing(f"{twice} appear in more than one game: the same odds "
                      f"file was given twice, or two weeks are mixed")
    unnamed = sorted(set(teams) - set(starters))
    if unnamed:
        raise Missing(f"no starting quarterback named for {unnamed}. Add them "
                      f'to "starters" in the inputs.')
    rec = []
    for away, home in games:
        for team, opp in ((away, home), (home, away)):
            recent = hist.team_recent_players(team, CANDIDATE_LOOKBACK)
            if not len(recent):
                raise Missing(f"{team} has no game in the history")
            qb = starters[team]
            extra = [(pid, pos) for tm, pid, pos in add if tm == team] + [(qb, None)]
            pos_of = {pid: pos for pid, pos in extra if pos}
            order = list(recent) + [pid for pid, _ in extra if pid not in set(recent)]
            for pid in dict.fromkeys(order):
                seen = hist.last_week(pid) is not None
                name = hist.last_name(pid) if seen else names.full.get(pid, pid)
                pos = pos_of.get(pid) or (hist.last_position(pid) if seen
                                          else names.position.get(pid))
                if pid == qb and pos != "QB":
                    raise Missing(
                        f"{name} is named as {team}'s starting quarterback "
                        f"and is listed at {pos}. If he really is starting, "
                        f'add him under "add" with position QB.')
                rec.append((season, week, f"{season}_{week:02d}_{away}_{home}",
                            team, opp, pid, name, pos, pid == qb))
    return pd.DataFrame(rec, columns=list(fs.SLATE_COLS))


def live_model(reports, given=None, name: str = "live") -> TouchdownModel:
    """The simulator as the record measures it: touchdowns on efficiency on
    opportunity, with a chance of playing from the report and from what is
    handed in."""
    return TouchdownModel(name, efficiency=EfficiencyModel(
        f"{name}_eff", opportunity=ChanceOpportunity(
            f"{name}_opp", chance=PlayChance(reports, given=given))))


# ---------------------------------------------------------------------------
# One run
# ---------------------------------------------------------------------------

def sides(P, i: int, stat: str, line: float) -> tuple:
    """(over, push, under) for one line. A half-point line cannot push. A
    whole-number line pushes on exactly that number: over is the chance of
    more than it, under of less."""
    if float(line) != math.floor(line):
        over = P.p_over(i, stat, line)
        return over, 0.0, 1.0 - over
    over, at_least = P.p_over(i, stat, line + 0.5), P.p_over(i, stat, line - 0.5)
    return over, at_least - over, 1.0 - at_least


def nearest_rung(line: float, ladder) -> str:
    """Which rung of a player's own stand-in ladder ([(label, line)] from
    `ff_sim.standin_lines`, lowest first) a posted line is nearest; of two
    equally near, the one nearer his main line. "" when the line is off
    the ladder, where the record has nothing: further below his lowest
    rung, or above his highest, than half the gap to the next rung in (or
    half a point, if the ladder is one rung)."""
    if not ladder:
        return ""
    below = (ladder[1][1] - ladder[0][1]) / 2 if len(ladder) > 1 else 0.5
    above = (ladder[-1][1] - ladder[-2][1]) / 2 if len(ladder) > 1 else 0.5
    if not ladder[0][1] - below <= line <= ladder[-1][1] + above:
        return ""
    far = {lab: abs(math.log(f)) for lab, f in zip(RUNG_LABELS, RUNG_FACTORS)}
    return min(ladder, key=lambda r: (abs(r[1] - line), far[r[0]]))[0]


def read_on(stat: str, line: float, role: dict, ladder) -> tuple:
    """(what the record is read on, why there is none) for one line; one of
    the two is "". `role` and `ladder` are the harness's for this player:
    `ff_sim.roles` (with a passing role kept only by the starter) and
    `ff_sim.standin_lines`."""
    if stat == TD_STAT and line != 0.5:
        return "", TWO_PLUS
    if not role[FAMILY[stat]]:
        return "", NO_ROLE
    if stat == TD_STAT:
        return MAIN, ""
    rung = nearest_rung(line, ladder)
    return rung, "" if rung else OFF_LADDER


class Board:
    """One shadow run. `slate` (with `chance`, `status`, `source`), `lines`
    (one row per player, stat and posted line), `unmatched` (posted lines
    with no projection, and why), and `notes`."""

    def __init__(self, slate, lines, unmatched, notes, P):
        self.slate, self.lines, self.unmatched = slate, lines, unmatched
        self.notes, self.P = notes, P


LINE_COLS = ["game_id", "team", "opponent", "player_id", "name", "position",
             "chance", "source", "stat", "line", "kind", "rung", "no_record",
             "books", "suspended", "matched", "expected", "over", "push", "under"]


def run_live(frame: pd.DataFrame, reports, roster: pd.DataFrame, events,
             inputs: dict, *, week: int | None = None, books=None,
             allow_no_report: bool = False) -> Board:
    """Project the games in `events` (read with `read_odds`) for the week in
    `inputs` (from `read_inputs`), and price every posted line. Raises
    `Missing`, saying what, when something it needs is not there."""
    newest_season = int(frame["season"].max())
    season = int(inputs.get("season") or newest_season)
    week = week if week is not None else inputs.get("week")
    if week is None:
        raise Missing('no week: pass --week or put "week" in the inputs')
    if isinstance(week, bool) or not isinstance(week, int) or not 1 <= week <= 22:
        raise Missing(f"the week is {week!r}; it must be a whole number from "
                      f"1 to 22")
    if inputs.get("week") is not None and inputs["week"] != week:
        raise Missing(f"the inputs are for week {inputs['week']} and the run "
                      f"is for week {week}")
    if season != newest_season and not (season == newest_season + 1 and week == 1):
        raise Missing(f"the season is {season}; the newest on file is "
                      f"{newest_season}, and only Week 1 of the next can be run "
                      f"from it")
    t = tkey(season, week)
    if not len(events):
        raise Missing("no odds files: nothing to price")
    hist = History(frame[frame["t"] < t], t)
    newest = int(hist.frame["t"].max()) if len(hist.frame) else None
    if week > 1 and newest != tkey(season, week - 1):
        raise Missing(f"the newest week in the history is {newest}, not "
                      f"{tkey(season, week - 1)}: run refresh.py, or the data "
                      f"for last week is not published yet")
    if week > 1:
        this_season = hist.frame[hist.frame["season"] == season]
        had = this_season.loc[this_season["t"] == newest, "team"].nunique()
        of = this_season["team"].nunique()
        if 2 * had < of:
            raise Missing(f"only {had} of {of} teams have last week's game on "
                          f"file: week {week - 1} is not finished or not "
                          f"published yet")
    games = [(TEAM_CODE[e["away_team"]], TEAM_CODE[e["home_team"]]) for e in events]
    playing = {tm for g in games for tm in g}
    played = sorted(set(frame.loc[frame["t"] == t, "team"]) & playing)
    if played:
        raise Missing(f"{played} already have a game on file for week {week}: "
                      f"that game has been played")
    notes = []
    names = Names(roster, hist, season)
    add = [(tm, names.find(tm, who, anywhere=True), pos)
           for tm, who, pos in inputs["add"] if tm in playing]
    added = {(tm, pid) for tm, pid, _ in add}
    if len(added) != len(add):
        raise Missing('a player is listed twice under "add" in the inputs')

    def placed(tm, who):
        """A player on the team, or one just added to it."""
        try:
            return names.find(tm, who)
        except Missing:
            if (tm, names.find(tm, who, anywhere=True)) in added:
                return names.find(tm, who, anywhere=True)
            raise

    starters = {tm: placed(tm, who) for tm, who in inputs["starters"].items()
                if tm in playing}
    given, said = {}, {}
    for kind, into in (("chances", given), ("statuses", said)):
        for tm, who, value in inputs[kind]:
            if tm in playing:
                key = (tm, placed(tm, who))
                if key in into:
                    raise Missing(f"{who!r} ({tm}) is listed twice under "
                                  f'"{kind}" in the inputs')
                into[key] = value
    slate = build_slate(hist, season, week, games, starters, names, add)
    on_slate = set(zip(slate.team, slate.player_id))
    stray = sorted(f"{names.full.get(pid, pid)} ({tm})" for tm, pid in {*given, *said}
                   if (tm, pid) not in on_slate)
    if stray:
        raise Missing(f"a chance or a status was handed in for {stray}, who "
                      f'are not on the slate. Add them under "add" if they '
                      f"are playing.")
    for tm, pid in said:
        also = sorted(set(slate.team[slate.player_id == pid]) - {tm})
        if also:
            raise Missing(
                f"a status was handed in for {names.full.get(pid, pid)} on "
                f"{tm}, and he is on {also}'s slate too. A status goes with "
                f"the player, so it would count for both teams: hand in his "
                f"chance of playing for each team instead.")

    # The injury file, for these teams. It carries no team, so "on file" is
    # read as "has a row for somebody on this slate".
    filed = (reports[(reports["t"] == t) & reports["player_id"].isin(set(slate.player_id))]
             if reports is not None else pd.DataFrame(columns=["t", "player_id", "status"]))
    if not len(filed):
        if not allow_no_report:
            raise Missing(f"no injury report on file for week {week} for "
                          f"anyone in these games. Wait for it, or run with "
                          f"--allow-no-report and hand in each listed "
                          f"player's status.")
        notes.append(f"NO INJURY REPORT ON FILE for week {week} for anyone in "
                     f"these games: every player with no status or chance "
                     f"handed in is priced from games missed alone. The "
                     f"record below was measured WITH reports and does not "
                     f"describe this run.")
    else:
        n = filed.status.value_counts()
        notes.append(
            f"Injury file for these teams: {len(filed)} listed, "
            f"{int(n.get('out', 0))} out, {int(n.get('doubtful', 0))} doubtful, "
            f"{int(n.get('questionable', 0))} questionable. It can be days "
            f"behind the league's report; {len(said)} status"
            f"{'' if len(said) == 1 else 'es'} and {len(given)} chance"
            f"{'' if len(given) == 1 else 's'} were handed in.")
        bare = sorted(tm for tm in playing if not (
            set(slate.player_id[slate.team == tm]) & set(filed.player_id)))
        if bare:
            notes.append(f"{bare}: nobody on the injury file this week. A "
                         f"clean report is rare; the file may be missing them.")
    if said:
        # A status handed in IS this week's report for that player.
        ids = {pid for _, pid in said}
        old = reports if reports is not None else pd.DataFrame(
            columns=["t", "player_id", "status"])
        reports = pd.concat([
            old[~((old["t"] == t) & old["player_id"].isin(ids))],
            pd.DataFrame([(t, pid, st) for (_, pid), st in said.items() if st != "none"],
                         columns=["t", "player_id", "status"])], ignore_index=True)

    model = live_model(reports, given)
    P = model.project(hist, slate)
    if all(math.isnan(P.point(i, s_)) for i in range(len(slate)) for s_ in ALL_STATS):
        raise Missing("the history is too thin to fit the model: it has a "
                      "number for nobody")
    ch = model.eff.opp.chance.describe(hist, slate)
    slate = slate.assign(chance=ch["chance"].to_numpy(), status=ch["status"].to_numpy(),
                         source=ch["source"].to_numpy())
    told = [(tm, pid) in said and src != "given"
            for tm, pid, src in zip(slate.team, slate.player_id, slate.source)]
    slate.loc[told, "source"] = "counted from the status handed in"
    for tm in sorted(playing):
        last = int(hist.team_weeks(tm)[-1])
        if week > 1 and last != tkey(season, week - 1):
            notes.append(f"{tm}: newest game on file is {last} (a bye, or a "
                         f"game not yet published)")
        gone = sorted(f"{nm} (roster: {names.team[pid]})" for pid, nm in zip(
            slate.player_id[slate.team == tm], slate.name[slate.team == tm])
            if names.team.get(pid) not in (None, tm)
            and (tm, pid) not in given and (tm, pid) not in said)
        if gone:
            notes.append(f"{tm}'s slate has players the roster has on "
                         f"another team: {', '.join(gone)}. Each is still "
                         f"counted as someone who may play for {tm}; hand in "
                         f"chance 0 for any who is not with {tm}.")

    meta = fs._row_meta(hist, slate)       # the harness's own (window, role)
    at = {(tm, pid): i for i, (tm, pid) in enumerate(zip(slate.team, slate.player_id))}
    by_name = {}
    for i, (tm, nm) in enumerate(zip(slate.team, slate.name)):
        by_name.setdefault((tm, norm_player(nm)), []).append(i)
    rows, unmatched = [], []
    for e, (away, home) in zip(events, games):
        game = f"{away} at {home}"
        L = posted_lines(e, books)
        for why, n in sorted(L.attrs["passed_over"].items()):
            notes.append(f"{game}: {n} posted outcome{'s' if n != 1 else ''} "
                         f"passed over: {why}")
        absent = sorted(set(books or ()) - set(L.book))
        if absent:
            notes.append(f"{game}: the odds file has nothing the simulator "
                         f"reads from {absent}")
        if not len(L):
            if not books:
                notes.append(f"{game}: the odds file has no line the "
                             f"simulator has a stat for")
            continue
        # Who each outcome is, and every team the file puts him on. An
        # outcome with no id is taken to be the player another outcome in
        # this file gives an id under the same name, but only when nobody
        # else in the league has that name.
        listed = book_players(e)
        same = {}
        for player, key, _ in listed:
            if names.from_key(key):
                same.setdefault(norm_player(player), set()).add(names.from_key(key))

        def person(player, key):
            pid, n = names.from_key(key), norm_player(player)
            if (pid is None and len(same.get(n, ())) == 1
                    and names.any_name.get(n, set()) <= same[n]):
                pid = next(iter(same[n]))
            return pid

        puts = {}
        for player, key, team in listed:
            if team:
                puts.setdefault(person(player, key) or norm_player(player), set()).add(team)
        where, how = [], []
        for player, key in zip(L.player, L.player_key):
            pid = person(player, key)
            teams = puts.get(pid or norm_player(player), set())
            told = next(iter(teams)) if len(teams) == 1 else None
            if len(teams) > 1 or (told and told not in (away, home)):
                hits, told = [], "?"
                why = (f"the odds file puts him on {' and '.join(sorted(teams))}"
                       f": not one team in this game, so he is not priced")
            elif pid is None:
                hits = [j for tm in ((told,) if told else (away, home))
                        for j in by_name.get((tm, norm_player(player)), [])]
                why = ("no id from the book that the roster has, and no one "
                       "player of that name on "
                       + (f"{told}'s slate, where the odds file has him"
                          if told else "either slate"))
                # a namesake on these teams who is not on the slate: a name
                # alone cannot say which of them the book means
                if len(hits) == 1 and {g for tm in ((told,) if told else (away, home))
                                       for g in names.by_name.get((tm, norm_player(player)), ())
                                       } - {slate.player_id.iloc[hits[0]]}:
                    hits, why = [], ("no id from the book that the roster has, "
                                     "and more than one player of that name on "
                                     "these teams")
            else:
                on = [tm for tm in (away, home) if (tm, pid) in at]
                hits = [at[(tm, pid)] for tm in ((told,) if told else on) if tm in on]
                why = (f"the book has him on {told}, and he is not on {told}'s "
                       f"slate: not active for it in its last four games. Add "
                       f"him in the inputs if he is playing." if told else
                       "on both teams' slates, and the book does not say "
                       "which team he is on" if len(on) == 2 else
                       "on a roster but not on the slate: not active for "
                       "either team in its last four games. Add him in the "
                       "inputs if he is playing.")
            if len(hits) == 1 and not told:
                # the book does not say: the roster may know he has moved
                his = slate.team.iloc[hits[0]]
                there = names.team.get(slate.player_id.iloc[hits[0]])
                if there in (away, home) and there != his:
                    hits, why = [], (
                        f"the roster has him on {there}, the book does not say, "
                        f"and he is on {his}'s slate only: not active for "
                        f"{there} in its last four games. Add him to {there} "
                        f"in the inputs if he is playing for it.")
            where.append(hits[0] if len(hits) == 1 else why)
            how.append("id" if names.from_key(key) is not None else "name")
        L = L.assign(where=where, how=how)
        lost = L[[isinstance(w, str) for w in L["where"]]]
        for (player, why), g in lost.groupby(["player", "where"], sort=False):
            unmatched.append((game, player, len(g.drop_duplicates(["stat", "line"])), why))
        found = L[[not isinstance(w, str) for w in L["where"]]]
        for i, g in found.groupby("where", sort=False):
            s = slate.iloc[i]
            win, role = meta[i][0], meta[i][1]
            blank = []
            for (stat, line), h in g.groupby(["stat", "line"], sort=True):
                expected = P.point(i, stat)
                if math.isnan(expected):
                    blank.append(stat)
                    continue
                rung, no_record = read_on(stat, line, role,
                                          fs.standin_lines(hist, win, stat))
                over, push, under = sides(P, i, stat, line)
                rows.append((s.game_id, s.team, s.opponent, s.player_id, s["name"],
                             s.position, s.chance, s.source, stat, float(line),
                             "main" if (h.kind == "main").any() else "ladder",
                             rung, no_record, " ".join(sorted(set(h.book))),
                             " ".join(sorted(set(h.book[h.suspended]))),
                             "id" if (h.how == "id").any() else "name",
                             expected, over, push, under))
            for stat, n in sorted(Counter(blank).items()):
                unmatched.append((game, s["name"], n, f"no {stat} projection" + (
                    ": he is not the named starter" if FAMILY[stat] == "pass" else "")))
    lines = pd.DataFrame(rows, columns=LINE_COLS)
    return Board(slate, lines, unmatched, notes, P)


# ---------------------------------------------------------------------------
# The record
# ---------------------------------------------------------------------------

def code_stamp(folder=None) -> str:
    """A fingerprint of the model's source files."""
    folder = Path(folder) if folder else Path(__file__).resolve().parent
    h = hashlib.md5()
    for f in MODEL_FILES:
        h.update((folder / f).read_bytes())
    return h.hexdigest()


def build_record(frame: pd.DataFrame, reports, through: int) -> dict:
    """Walk the live set-up forward over every graded week and keep, for the
    list-not-known slate: each stat's bands by stand-in rung on the side
    favoured; the anytime touchdown's bands as stated; and the main-line
    legs put at 65% or better, by side (S21). Raises if the leak probe
    finds anything."""
    run = fs.walk_forward(frame, [live_model(reports)], through=through)
    probe = fs.leak_probe(frame, [live_model(reports)], run.weeks)
    if not probe.clean or run.unverified:
        raise RuntimeError("the leak probe did not pass: " + probe.describe())
    rec = {"layout": LAYOUT, "code": code_stamp(), "s21_from": S21_FROM,
           "first": int(run.weeks[0]), "through": int(run.weeks[-1]),
           "weeks": len(run.weeks), "bands": {}, "s21": {}}

    def table(legs, folded):
        bands = FOLDED_BANDS if folded else RAW_BANDS
        cal = fs.calibration(legs, folded=folded, bands=bands)
        return [[float(lo), float(hi), int(r.n), int(r.games),
                 None if not r.n else round(float(r.stated), 4),
                 None if not r.n else round(float(r.happened), 4), r.read]
                for (lo, hi), r in zip(bands, cal.itertuples())]

    def s21(g):
        out = {}
        for side in ("OVER", "UNDER"):
            d = g[(g.side == side) & (g.p_side >= S21_FROM)]
            out[side] = [int(len(d)), None if not len(d) else round(float(d.p_side.mean()), 4),
                         None if not len(d) else round(float(d.hit.mean()), 4)]
        return out

    laddered = [s for s in ALL_STATS if s != TD_STAT]
    for stat in laddered:
        rec["bands"][stat] = {
            r: table(fs.graded_legs(run, "live", version="B", stats=[stat],
                                    rung=r), True)
            for r in RUNG_LABELS}
        rec["s21"][stat] = s21(fs.graded_legs(run, "live", version="B",
                                              stats=[stat], rung=MAIN))
    rec["s21"]["all"] = s21(fs.graded_legs(run, "live", version="B",
                                           stats=laddered, rung=MAIN))
    rec["bands"][TD_STAT] = {MAIN: table(
        fs.graded_legs(run, "live", version="B", stats=[TD_STAT]), False)}
    return rec


def check_record(record) -> None:
    """Refuse a record that is missing, is not whole, or was built from
    other model code or another S21 threshold."""
    rebuild = "Rebuild it: python3 sim_live.py --record --current-week N"
    if not record:
        raise Missing(f"there is no record (sim_record.py). {rebuild}")
    if set(RECORD_KEYS) - set(record) or record["layout"] != LAYOUT:
        raise Missing(f"the record (sim_record.py) is not in the layout this "
                      f"script reads. {rebuild}")
    if record["code"] != code_stamp() or record["s21_from"] != S21_FROM:
        raise Missing(f"the record (sim_record.py) was built from different "
                      f"model code than is here now. {rebuild}")


def band_of(record: dict, stat: str, rung, p: float):
    """The record's band for a stated chance: (lo, hi, legs, games, stated,
    happened, read), or None when there is no record for it. `p` is the
    chance of the favoured side, or for an anytime touchdown of scoring.
    `rung` is "main", another stand-in rung, or "" for a line the record
    does not cover."""
    if not rung or not 0.0 <= p <= 1.0:
        return None
    for b in record["bands"].get(stat, {}).get(rung, []):
        if b[0] <= p < b[1] or (p == 1.0 and b[1] >= 1.0):
            return tuple(b)
    return None


def on_main(row) -> bool:
    """Is this a main-line leg in the S21 sense: on the player's own
    stand-in main line. A touchdown is not."""
    return row.rung == MAIN and row.stat != TD_STAT


def flags_for(record: dict, row) -> list:
    """The cautions that belong on one priced line."""
    out = []
    side = "OVER" if row.over >= row.under else "UNDER"
    if row.stat == "passing_tds":
        out.append(PASS_TD_UNDER)
    if on_main(row) and max(row.over, row.under) >= S21_FROM:
        n, stated, happened = record["s21"].get(row.stat, {}).get(side, (0, None, None))
        if n:
            out.append(f"S21 main-line caution: {side.lower()}s it put at "
                       f"{S21_FROM:.0%}+ on this stat: stated {stated:.1%}, "
                       f"happened {happened:.1%} ({n:,} legs)")
        else:
            out.append(f"S21 main-line caution: no {side.lower()}s at "
                       f"{S21_FROM:.0%}+ on this stat in the record")
    if row.matched == "name":
        out.append("matched by NAME, not by id: check it is the right player")
    if row.suspended:
        out.append(f"SUSPENDED at {row.suspended}")
    if row.push > 0:
        out.append(f"whole-number line: pushes {row.push:.1%}")
    return out


# ---------------------------------------------------------------------------
# What is printed
# ---------------------------------------------------------------------------

PLAIN = {"targets": "targets", "receptions": "catches", "receiving_yards": "rec yds",
         "carries": "carries", "rushing_yards": "rush yds", "attempts": "pass att",
         "completions": "comp", "passing_yards": "pass yds",
         "passing_tds": "pass TD", TD_STAT: "TD"}


def stat_line(P, i: int) -> str:
    """One player's expected numbers, the ones that are not nothing."""
    bits = []
    for stat in ("attempts", "completions", "passing_yards", "passing_tds",
                 "carries", "rushing_yards", "targets", "receptions",
                 "receiving_yards"):
        v = P.point(i, stat)
        if not math.isnan(v) and v >= 0.5:
            bits.append(f"{v:.1f} {PLAIN[stat]}")
    td = P.p_over(i, TD_STAT, 0.5)
    if not math.isnan(td):
        bits.append(f"scores {td:.0%}")
    return ", ".join(bits) if bits else "nothing projected"


def record_text(record: dict, row) -> str:
    """The band's record for one priced line, in words."""
    if not row.rung:
        return f"no record: {row.no_record}"
    if row.stat == TD_STAT:
        b, what = band_of(record, TD_STAT, MAIN, row.over), "scored"
    else:
        b = band_of(record, row.stat, row.rung, max(row.over, row.under))
        what = "happened"
    if b is None and row.stat != TD_STAT and max(row.over, row.under) < 0.5:
        return "no record: with the push, neither side reaches 50%"
    if b is None:
        return "no record: the record has no table for this"
    lo, hi, n, games, stated, happened, read = b
    where = ("" if row.stat == TD_STAT else " on his main line" if row.rung == MAIN
             else f" on his {row.rung} rung")
    if not n:
        return f"said {lo:.0%}-{hi:.0%}{where}: never, in the record"
    return (f"said {lo:.0%}-{hi:.0%}{where}: {what} {happened:.1%} of "
            f"{n:,} ({read})")


def week_text(t: int) -> str:
    """"2026 Week 11" for 202611."""
    return f"{t // 100} Week {t % 100}"


POSITION_ORDER = {"QB": 0, "RB": 1, "FB": 1, "WR": 2, "TE": 3}


def render(board: Board, record: dict, *, everyone: bool = False) -> str:
    """The run as text: the standing cautions, then by game, team and
    player the stat line and each posted line; then what was not priced.
    Within a team: the starter, then backs, receivers and tight ends, the
    busiest first."""
    s21 = record["s21"]["all"]
    out = [
        "SHADOW RUN: the simulator's own numbers. Not a lean, no prices; a "
        "posted line is only a benchmark.",
        f"Record: walk-forward, {record['weeks']} weeks, "
        f"{week_text(record['first'])} to {week_text(record['through'])}, list "
        f"not known, with the injury report, on STAND-IN lines. Nothing here "
        f"has been graded against a book's line.",
        "The record covers players with four recent games and a role in "
        "them, graded with last game's starter and nothing handed in. A "
        "line is read on HIS OWN stand-in rung nearest it: \"his main "
        "line\" is the half point above his eight-game median, not the book's.",
        "Every number is IF HE PLAYS.",
        f"S21, the main-line caution. Legs on a player's main line that it "
        f"has put at {S21_FROM:.0%} or better, every stat: overs stated "
        f"{s21['OVER'][1]:.1%}, happened {s21['OVER'][2]:.1%} "
        f"({s21['OVER'][0]:,} legs); unders stated {s21['UNDER'][1]:.1%}, "
        f"happened {s21['UNDER'][2]:.1%} ({s21['UNDER'][0]:,}). Each such "
        f"line below carries its own stat's figures.",
        "S24. Passing-touchdown UNDERS are unreliable: overstated by about 5 "
        "points. S25. A regular's chance of scoring runs about 2 points low.",
    ] + ["NOTE. " + n for n in board.notes] + [""]
    L, S = board.lines, board.slate
    for gid, G in S.groupby("game_id", sort=False):
        away, home = gid.split("_")[2:]
        out.append(f"=== {away} at {home} ===")
        for team, T in G.groupby("team", sort=False):
            out.append(f"--- {team} ---")
            priced = set(L.player_id[(L.game_id == gid) & (L.team == team)])

            def busy(i):
                v = [board.P.point(i, s_) for s_ in ("targets", "carries")]
                return sum(x for x in v if not math.isnan(x))

            for i in sorted(T.index, key=lambda i: (
                    not S.starting_qb[i], POSITION_ORDER.get(S.position[i], 9), -busy(i))):
                r = S.loc[i]
                if not (everyone or r.player_id in priced or r.starting_qb):
                    continue
                out.append(
                    f"{r['name']} ({r.position}{', starting QB' if r.starting_qb else ''})"
                    f"  plays {r.chance:.0%} ({r.source}"
                    f"{'' if r.status == 'none' else ', report: ' + r.status})"
                    f"  |  {stat_line(board.P, i)}")
                mine = L[(L.game_id == gid) & (L.team == team) & (L.player_id == r.player_id)]
                for row in mine.itertuples(index=False):
                    what = ("to score" if row.line == 0.5 else
                            f"{int(row.line + 0.5)}+ TDs") if row.stat == TD_STAT \
                        else f"{PLAIN[row.stat]} {row.line:g}"
                    odds = (f"yes {row.over:.1%}" if row.stat == TD_STAT else
                            f"over {row.over:.1%} / under {row.under:.1%}")
                    out.append(f"    {what:<16} {odds:<30} [{row.books}]  "
                               f"{record_text(record, row)}")
                    out += [f"        ! {f}" for f in flags_for(record, row)]
        out.append("")
    if board.unmatched:
        out.append("POSTED BUT NOT PRICED")
        out += [f"    {game}: {player} ({n} line{'s' if n != 1 else ''}): {why}"
                for game, player, n, why in board.unmatched]
    return "\n".join(out)


def to_csv(board: Board, record: dict, season: int, week: int) -> pd.DataFrame:
    """The priced lines as a table to save and grade later: one row per
    player, stat and line, with the band's record and the cautions."""
    d = board.lines.copy()
    d.insert(0, "week", week)
    d.insert(0, "season", season)
    d["record"] = [record_text(record, r) for r in board.lines.itertuples(index=False)]
    d["cautions"] = [" | ".join(flags_for(record, r))
                     for r in board.lines.itertuples(index=False)]
    return d


def shadow_run(frame: pd.DataFrame, reports, roster: pd.DataFrame, record, odds,
               inputs, *, week: int | None = None, books=None, ladders: bool = False,
               everyone: bool = False, out=None, allow_no_report: bool = False,
               now=None, dates=None) -> tuple:
    """Everything `sim_live.py` does once the data is loaded: (what to
    print, exit code). `odds` is the saved responses, `inputs` the inputs
    file, `now` the UTC time to judge kickoffs by (the clock's, if not
    given), `dates` the season's games as [week, game_date], from which
    this week's dates are worked out (`week_window`). Without `ladders`
    only main lines and the anytime touchdown are shown, and it says how
    many others were priced. `out` also saves the lines shown there as
    CSV. When something is missing the text is "STOPPED." and what, and
    the code is 2; on a fault it did not foresee, 3. Either way nothing is
    printed of the run."""
    try:
        check_record(record)
        if not inputs:
            raise Missing("no --inputs file: it names the week and each "
                          "team's starting quarterback")
        events = [read_odds(f) for f in odds]
        books = {str(b).strip().lower() for b in books} if books else None
        asked = read_inputs(inputs)
        wk = week if week is not None else asked["week"]
        late = check_kickoffs(
            events, pd.Timestamp.now(tz="UTC") if now is None else now,
            week_window(dates, wk) if isinstance(wk, int) else None,
            asked["season"] or int(frame["season"].max()))
        board = run_live(frame, reports, roster, events, asked,
                         week=week, books=books, allow_no_report=allow_no_report)
        board.notes += late
        hidden = int((board.lines.kind != "main").sum())
        if not ladders:
            board.lines = board.lines[board.lines.kind == "main"].reset_index(drop=True)
            if hidden:
                board.notes.append(
                    f"{hidden} ladder line{'s' if hidden != 1 else ''} (rungs, "
                    f"alternates, 2+ and 3+ touchdowns) were priced and are "
                    f"not shown: run with --ladders to see them.")
        text = render(board, record, everyone=everyone)
        if out:
            try:
                to_csv(board, record, int(board.slate.season.iloc[0]),
                       int(board.slate.week.iloc[0])).to_csv(out, index=False)
            except OSError as e:
                raise Missing(f"cannot save to {out}: {e}") from e
            text += f"\n\nsaved {len(board.lines):,} priced lines to {out}"
    except Missing as e:
        return f"STOPPED. {e}", 2
    except Exception as e:      # noqa: BLE001 - the rule is to stop and say what
        return (f"STOPPED. Something it did not foresee: {type(e).__name__}: "
                f"{e}. Nothing was priced. This is a fault in the script or "
                f"a file in a shape it does not know."), 3
    return text, 0
