#!/usr/bin/env python3
"""
ff_news.py — role and usage news, and whether the books have priced it (B258).

WHY THIS EXISTS. Three tests on 41 games (Weeks 9 to 11 of 2026, DraftKings,
FanDuel and BetMGM closing lines; REPLAY-RESULT.md and REPLAY-RESULT-2.md)
said the same thing: a projection built from public stats does not beat the
book's line. Two trends were then tested against the price, and they came out
differently:

  ROLE NEWS IS WORTH SOMETHING ONLY BEFORE THE LINE MOVES. With a same-position
  teammate who had a real role ruled out, 38% of main lines moved up 10% or
  more between the first posting and the close (12% of all lines do). At the
  CLOSING number those overs came in 47.9% against 48.8% priced: fair, nothing
  left. At the OPENING number they came in 54.5% (101 lines, 14 games).

  A HOT RUN IS NOT A REASON FOR THE OVER. Over today's line in 4 or 5 of his
  last 5: the over came in 43.6% against 50.8% priced (287 lines). Over in 0
  or 1 of his last 5: 48.1% against 48.1% (378 lines).

So this module does three things and no more:
  1. holds each piece of role news as a FLAG with its source and its time;
  2. sets each affected player's line NOW beside where it OPENED, book by
     book, so the run can say whether the news is already in the price;
  3. marks a line that sits on a hot run, as a caution.
It makes no projection and gives no probability. Every flag it prints is
written to a log so that the flags themselves can be graded against the price,
week by week, and dropped if they do not hold.

WHAT IT READS. Saved tool responses, never retyped ones:
  propline_get_event_movement   each book's opening and latest line
  propline_get_injuries         status and the time that status began
  FantasyPros injury_status     practice report and dated news
A finding from a web search is entered by hand with `manual_flag`, which
refuses one with no source or no time: undated news cannot be set against a
line's history.

HOW TO RUN IT. One saved movement response a game:

    python3 ff_news.py --week 12 --injuries <injuries file> \\
        --flags flags_wk12.json <movement file> [<movement file> ...]

(`--no-save` prints without saving a log: for a first pass made to see what
needs looking up.)

It prints, for all games together and then game by game: (0) lines where the
news has a direction and a book has not moved 10%; (1) every flag, who it
bears on, and what each book has done since its opener; (1b) players with a
role who sat the team's last game and carry no flag; (2) main lines on a hot
run; (3) each team's roles. It saves a log, one row a line and book.

"OPENER" MEANS the first line PropLine recorded for that book, which can be
later than the book's true first posting.

NOT BUILT, AND SAID SO. `propline_get_lineups` (starters and inactives from
six hours before kickoff) had no game to return when this was written, so its
shape is not known and nothing here guesses it; enter an inactive with
`manual_flag`. The teammate rule is by position group only (receivers and
tight ends together, backs together): it does not know who lines up where.

The game log (`load_games`) is the simulator's frame, `ff_sim.load_frame`,
because it counts a game a player was on the field for and recorded nothing
in, which the weekly stat table leaves out (one game in eight).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from ff_props import norm_player

#: market key -> the stat column it settles on. Over/under markets only.
MARKET_STAT = {
    "player_pass_yds": "passing_yards",
    "player_pass_attempts": "attempts",
    "player_pass_completions": "completions",
    "player_pass_tds": "passing_tds",
    "player_rush_yds": "rushing_yards",
    "player_rush_attempts": "carries",
    "player_reception_yds": "receiving_yards",
    "player_receptions": "receptions",
}
SWEEP_MARKETS = ",".join(MARKET_STAT)
PLAIN = {"passing_yards": "pass yds", "attempts": "pass att", "completions": "comp",
         "passing_tds": "pass TD", "rushing_yards": "rush yds", "carries": "carries",
         "receiving_yards": "rec yds", "receptions": "catches"}
#: Which stats a change in a position group's volume bears on.
GROUP = {"WR": "REC", "TE": "REC", "RB": "RB", "FB": "RB", "QB": "QB"}
GROUP_STATS = {"REC": ("receiving_yards", "receptions"),
               "RB": ("rushing_yards", "carries", "receiving_yards", "receptions"),
               "QB": ("passing_yards", "attempts", "completions", "passing_tds")}
TEAM_CODE = {
    "Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL", "Baltimore Ravens": "BAL",
    "Buffalo Bills": "BUF", "Carolina Panthers": "CAR", "Chicago Bears": "CHI",
    "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE", "Dallas Cowboys": "DAL",
    "Denver Broncos": "DEN", "Detroit Lions": "DET", "Green Bay Packers": "GB",
    "Houston Texans": "HOU", "Indianapolis Colts": "IND", "Jacksonville Jaguars": "JAX",
    "Kansas City Chiefs": "KC", "Los Angeles Rams": "LA", "Los Angeles Chargers": "LAC",
    "Las Vegas Raiders": "LV", "Miami Dolphins": "MIA", "Minnesota Vikings": "MIN",
    "New England Patriots": "NE", "New Orleans Saints": "NO", "New York Giants": "NYG",
    "New York Jets": "NYJ", "Philadelphia Eagles": "PHI", "Pittsburgh Steelers": "PIT",
    "Seattle Seahawks": "SEA", "San Francisco 49ers": "SF", "Tampa Bay Buccaneers": "TB",
    "Tennessee Titans": "TEN", "Washington Commanders": "WAS",
}
#: Other spellings of a team code (FantasyPros, ESPN) -> the data's.
CODE_ALIAS = {"LAR": "LA", "JAC": "JAX", "WSH": "WAS"}

# MEASURED 2026-11-23, 41 games. Not tuned; these are where the tables were cut.
MOVED = 0.10          # a main line this far from its opener has moved
FLAT = 0.03           # and this near it has not
ROLE_TARGETS = 4.0    # a "real role": this many targets a game over his last four
ROLE_CARRIES = 8.0    # or this many carries
ROLE_GAMES = 4
RECENT_TEAM_GAMES = 4   # who counts as on a team: active in one of its last four games
MAX_NEWS_HOURS = 72.0   # a hand-entered finding older than this is refused
SAMPLE = "41 games, Weeks 9 to 11 of 2026"
EVIDENCE = {
    "UP": ("a same-position teammate with a role is out: 38% of such lines moved up "
           "10%+ by the close (12% of all lines). At the close the over was fair "
           "(47.9% against 48.8% priced); at the opener it came in 54.5%. 101 lines "
           "from 14 of the 41 games, Weeks 9 to 11 of 2026: a lead, too few to act "
           "on alone."),
    "DOWN": ("a same-position teammate is back: nothing measured either way at the "
             "close (155 lines, " + SAMPLE + "). Shown as context."),
    "QB": ("a new starting quarterback: his receivers' overs came in 42.3% against "
           "49.4% priced, with an error of 7 points, so not established (168 lines, "
           + SAMPLE + "). Shown as context."),
    "WATCH": "status not settled: no direction until it is.",
}
#: The short form, for a second flag of the same kind in one game.
WHAT = {"UP": "a same-position teammate with a role is out",
        "DOWN": "a same-position teammate is back",
        "QB": "a new starting quarterback",
        "WATCH": "status not settled"}
HOT_TEXT = ("overs on lines like this came in 43.6% against 50.8% priced (287 lines, "
            + SAMPLE + "): a hot run is not a reason for the over")
COLD_TEXT = ("lines like this were priced fair, 48.1% against 48.1% (378 lines, "
             + SAMPLE + ")")

#: Verdicts that leave something to look at: the news has a direction and
#: at least one book has not moved 10% with it.
OPEN_VERDICTS = ("NOT MOVED", "SMALL MOVE", "PARTLY")
SEVERITY = {"OUT": 4, "DOUBTFUL": 3, "QUESTIONABLE": 2, "BACK": 2, "NEW_QB": 2, "NOTE": 1}
KINDS = tuple(SEVERITY)
#: propline_get_injuries status_code -> kind. Anything else is not a flag.
INJURY_KIND = {"out": "OUT", "injured_list": "OUT", "suspended": "OUT",
               "doubtful": "DOUBTFUL", "questionable": "QUESTIONABLE"}
#: FantasyPros status -> kind.
FP_KIND = {"out": "OUT", "ir": "OUT", "pup": "OUT", "suspended": "OUT",
           "doubtful": "DOUBTFUL", "questionable": "QUESTIONABLE"}


# ---------------------------------------------------------------------------
# Reading what the thread saved
# ---------------------------------------------------------------------------

def read_saved(source):
    """A saved tool response, however it was kept: the object, its JSON text,
    a path to either, or the harness's [{"text": ...}] wrapper round it."""
    if isinstance(source, (str, Path)):
        s = str(source)
        if not s.lstrip().startswith(("{", "[")):
            s = Path(s).read_text()
        source = json.loads(s)
    if isinstance(source, list) and source and isinstance(source[0], dict) \
            and set(source[0]) >= {"text"} and "type" in source[0]:
        source = json.loads(source[0]["text"])
    return source


def team_code(team) -> str | None:
    """The data's code for a team given as a name or as any book's code."""
    if team in TEAM_CODE:
        return TEAM_CODE[team]
    team = CODE_ALIAS.get(team, team)
    return team if team in TEAM_CODE.values() else None


def _utc(value):
    """A time as UTC, or None when there is none or it does not parse."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    try:
        t = pd.Timestamp(value)
    except (ValueError, TypeError):
        return None
    if pd.isna(t):
        return None
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


# ---------------------------------------------------------------------------
# 1. Where each line opened and where it is now
# ---------------------------------------------------------------------------

MOVE_COLS = ["game", "book", "market", "stat", "player", "key", "open", "latest",
             "move", "open_at", "latest_at", "snapshots"]


def line_moves(response, books=None) -> pd.DataFrame:
    """Each book's MAIN line for each player and stat in one saved
    `propline_get_event_movement` response: where it opened, where it is,
    and when each was seen.

        [game, book, market, stat, player, key, open, latest, move, open_at,
         latest_at, snapshots]

    `move` is (latest - open) / open. A main line is a market of exactly an
    Over and an Under on one number; rungs ("100+ Receiving Yards") are not
    read. `.attrs["kickoff"]` is the game's start. Raises ValueError on a
    response that is not one, or that the free tier has redacted."""
    r = read_saved(response)
    if not isinstance(r, dict) or not isinstance(r.get("bookmakers"), list) \
            or "commence_time" not in r:
        raise ValueError("not a propline_get_event_movement response: it needs "
                         "'bookmakers' and 'commence_time'. Pull one game with "
                         "its event_id.")
    if r.get("redacted"):
        raise ValueError("this movement response is redacted (free tier): it "
                         "holds no opening lines to read")
    away, home = team_code(r.get("away_team")), team_code(r.get("home_team"))
    if not away or not home:
        raise ValueError(f"the response's teams are {r.get('away_team')!r} and "
                         f"{r.get('home_team')!r}, which are not NFL team names "
                         f"this file knows")
    game, rows = f"{away} at {home}", []
    for bk in r["bookmakers"]:
        if books and bk.get("key") not in books:
            continue
        for mk in bk.get("markets") or []:
            stat = MARKET_STAT.get(mk.get("key"))
            oc = mk.get("outcomes") or []
            if stat is None or len(oc) != 2 or {o.get("name") for o in oc} != {"Over", "Under"}:
                continue
            o = next(x for x in oc if x["name"] == "Over")
            who = o.get("description")
            if not isinstance(who, str) or o.get("redacted"):
                continue
            op, la = o.get("open_point"), o.get("latest_point")
            if not isinstance(op, (int, float)) or not isinstance(la, (int, float)) or op <= 0:
                continue
            rows.append((game, bk["key"], mk["key"], stat, who, norm_player(who),
                         float(op), float(la), (la - op) / op, _utc(o.get("open_at")),
                         _utc(o.get("latest_at")), o.get("num_snapshots")))
    out = pd.DataFrame(rows, columns=MOVE_COLS)
    out.attrs.update(kickoff=_utc(r["commence_time"]), away=away, home=home, game=game)
    return out


# ---------------------------------------------------------------------------
# 2. Flags
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RoleFlag:
    """One piece of role news about one player.

    `kind` is OUT, DOUBTFUL, QUESTIONABLE, BACK, NEW_QB or NOTE. `at` is when
    it became true or was published, UTC; None only when the source gives no
    time, and then nothing can say whether a line moved after it."""
    player: str
    team: str
    position: str
    kind: str
    source: str
    at: object = None
    detail: str = ""
    url: str = ""

    @property
    def key(self) -> str:
        return norm_player(self.player)

    def describe(self) -> str:
        when = f"{self.at:%a %m-%d %H:%M} UTC" if self.at is not None else "NO TIME GIVEN"
        return (f"{self.player} ({self.team} {self.position}): {self.kind}"
                + (f", {self.detail}" if self.detail else "")
                + f"  [{self.source}, {when}]")


def flags_from_injuries(response, positions=("QB", "RB", "FB", "WR", "TE")) -> list:
    """Flags from one saved `propline_get_injuries` response. `at` is
    `status_since`: when the current status began. Players at other
    positions, and statuses that are not out, doubtful or questionable, are
    left out."""
    r = read_saved(response)
    if not isinstance(r, dict) or not isinstance(r.get("players"), list):
        raise ValueError("not a propline_get_injuries response: it has no "
                         "'players' list")
    out = []
    for p in r["players"]:
        kind = INJURY_KIND.get(str(p.get("status_code") or "").lower())
        team = team_code(p.get("team_abbr")) or team_code(p.get("team"))
        if kind is None or team is None or p.get("position") not in positions:
            continue
        detail = " ".join(str(x) for x in (p.get("status"), p.get("injury_type")) if x)
        out.append(RoleFlag(p["player_name"], team, p["position"], kind,
                            "PropLine injuries (ESPN)", _utc(p.get("status_since")),
                            detail))
    return out


def flags_from_fantasypros(response) -> list:
    """Flags from one saved FantasyPros `injury_status` response: one for
    each player in `practice_details` who is out, doubtful or questionable.
    The practice line and his chance of playing go in `detail`. `at` is the
    newest dated news item about him when there is one, else None:
    FantasyPros' own update time carries no time zone and is not used."""
    r = read_saved(response)
    if not isinstance(r, dict) or not isinstance(r.get("practice_details"), list):
        raise ValueError("not a FantasyPros injury_status response: it has no "
                         "'practice_details' list")
    newest = {}
    for n in r.get("player_news") or []:
        t = _utc(str(n.get("published") or "").replace(" UTC", "+00:00"))
        k = norm_player(str(n.get("player_name") or ""))
        if t is not None and (k not in newest or t > newest[k][0]):
            newest[k] = (t, n.get("url") or "")
    out = []
    for p in r["practice_details"]:
        kind = FP_KIND.get(str(p.get("status") or "").lower())
        team, pos = team_code(p.get("team_id")), p.get("position_id")
        if kind is None or team is None or pos not in GROUP:
            continue
        bits = [str(p.get("status")), str(p.get("injury_type") or "").strip()]
        practice = [p.get(f"practice_{i}") for i in (1, 2, 3)]
        if any(practice):
            bits.append("practice " + "/".join(str(x or "-") for x in practice))
        prob = p.get("probability_of_playing")
        try:
            bits.append(f"{float(prob):.0%} to play")
        except (TypeError, ValueError):
            pass
        t, url = newest.get(norm_player(p["name"]), (None, ""))
        out.append(RoleFlag(p["name"], team, pos, kind, "FantasyPros", t,
                            ", ".join(b for b in bits if b), url))
    return out


def _zoned(value) -> bool:
    try:
        return pd.Timestamp(value).tzinfo is not None
    except (ValueError, TypeError):
        return False


def manual_flag(player: str, team: str, position: str, kind: str, source: str,
                at, detail: str = "", url: str = "", now=None, confirmed=None) -> RoleFlag:
    """A finding entered by hand, from a web search or a lineup report.

    Refused without a source and a time, with a time that carries no time
    zone, with a time in the future, or with one more than 72 hours before
    `now`: undated or stale news cannot be set
    against a line's history, and last season's article reads like this
    week's.

    One way past the 72 hours, for an absence that began long ago and that
    the injury report does not carry (a player on injured reserve for a
    month, or released): kind OUT, `at` when it began, and `confirmed` the
    time a CURRENT listing was read that still has him out. `confirmed`
    must itself be inside 72 hours."""
    if kind not in KINDS:
        raise ValueError(f"kind is {kind!r}; it must be one of {KINDS}")
    code = team_code(team)
    if code is None:
        raise ValueError(f"{team!r} is not an NFL team name or code")
    if position not in GROUP:
        raise ValueError(f"position is {position!r}; it must be one of {tuple(GROUP)}")
    if not str(source or "").strip():
        raise ValueError(f"no source given for the flag on {player}: say where "
                         f"it was reported")
    t = _utc(at)
    if t is None:
        raise ValueError(f"no time given for the flag on {player} ({source}): "
                         f"give when it was published, with its time zone. News "
                         f"with no time cannot be set against the line.")
    if not _zoned(at):
        raise ValueError(f"the time on the flag on {player} ({at!r}) has no time zone: "
                         f"write it as 2026-11-25 14:10-05:00 (Eastern in November is "
                         f"-05:00) or 2026-11-25 19:10 UTC. Read as the wrong zone it "
                         f"would be hours out against the line.")
    now = _utc(now) or pd.Timestamp.now(tz="UTC")
    if t > now + pd.Timedelta(minutes=5):
        raise ValueError(f"the flag on {player} is timed {t:%Y-%m-%d %H:%M} UTC, "
                         f"which is in the future")
    old = (now - t).total_seconds() / 3600 > MAX_NEWS_HOURS
    c = _utc(confirmed)
    if confirmed is not None and str(confirmed).strip():
        if c is None or not _zoned(confirmed):
            raise ValueError(f"the confirmed time on the flag on {player} ({confirmed!r}) "
                             f"is not a time with a time zone")
        if kind != "OUT":
            raise ValueError(f"the flag on {player} gives a confirmed time, which is only "
                             f"for a standing absence (kind OUT), not {kind}")
        if c > now + pd.Timedelta(minutes=5) or c < t \
                or (now - c).total_seconds() / 3600 > MAX_NEWS_HOURS:
            raise ValueError(f"the confirmed time on the flag on {player} "
                             f"({c:%Y-%m-%d %H:%M} UTC) must be after the absence began "
                             f"and inside the last {MAX_NEWS_HOURS:.0f} hours")
        detail = (detail + "; " if detail else "") + f"still out when read {c:%a %m-%d %H:%M} UTC"
    elif old:
        raise ValueError(f"the flag on {player} is from {t:%Y-%m-%d %H:%M} UTC, "
                         f"more than {MAX_NEWS_HOURS:.0f} hours ago: too old to "
                         f"act on. If it still holds, a current report will say so. "
                         f"(For an absence that began long ago, kind OUT, also give "
                         f"\"confirmed\": when a current listing was read.)")
    return RoleFlag(player, code, position, kind, source.strip(), t, detail, url)


def merge_flags(*lists) -> list:
    """One flag a player and team: the most severe kind, and among flags of
    that kind the EARLIEST time, since that is when the books could first
    have known. Sources are joined so nothing is lost.

    One exception: a BACK timed after every other timed flag on him wins.
    An injury list is slow to drop a player who has been activated, and a
    dated report that he is back is newer than the listing it contradicts."""
    best = {}
    for f in (f for lst in lists for f in lst):
        best.setdefault((f.team, f.key), []).append(f)
    out = []
    for fl in best.values():
        top = max(SEVERITY[f.kind] for f in fl)
        same = [f for f in fl if SEVERITY[f.kind] == top]
        backs = [f for f in fl if f.kind == "BACK" and f.at is not None]
        rest = [f.at for f in fl if f.kind != "BACK" and f.at is not None]
        if backs and all(max(b.at for b in backs) > t for t in rest):
            same = [f for f in fl if f.kind == "BACK"]
        timed = sorted((f for f in same if f.at is not None), key=lambda f: f.at)
        lead = timed[0] if timed else same[0]
        others = sorted({f.source for f in fl} - {lead.source})
        detail = "; ".join(dict.fromkeys(f.detail for f in [lead, *same, *fl] if f.detail))
        out.append(RoleFlag(lead.player, lead.team, lead.position, lead.kind,
                            lead.source + ("".join(f" + {s}" for s in others)),
                            lead.at, detail, lead.url or next((f.url for f in fl if f.url), "")))
    return sorted(out, key=lambda f: (f.team, -SEVERITY[f.kind], f.player))


# ---------------------------------------------------------------------------
# 3. Who a flag bears on
# ---------------------------------------------------------------------------

def load_games(years=None) -> pd.DataFrame:
    """One row a player and game, zeros included, oldest first. See the top
    for why this is the simulator's frame and not the weekly stat table."""
    import ff_data
    import ff_sim
    years = years or (ff_data.CURRENT_SEASON - 1, ff_data.CURRENT_SEASON)
    return ff_sim.load_frame(tuple(years)).sort_values("t").reset_index(drop=True)


def team_roles(games: pd.DataFrame, team: str, season: int, week: int) -> pd.DataFrame:
    """The team's skill players going into `week`: everyone active for it in
    one of its last four games, with his averages over his own last four
    games played for it.

        [player_id, name, key, position, group, games, targets, carries,
         snap_share, role, missed]

    `role` is True at 4 targets or 8 carries a game, or for a quarterback
    who started its last game. `missed` is how many of the team's most
    recent games he has sat since he last played for it (0 = he played its
    last game)."""
    t = season * 100 + week
    g = games[(games.team == team) & (games.t < t)]
    recent = sorted(g.t.unique())[-RECENT_TEAM_GAMES:]
    if not recent:
        return pd.DataFrame(columns=["player_id", "name", "key", "position", "group",
                                     "games", "targets", "carries", "snap_share", "role",
                                     "missed"])
    last_start = set(g[(g.t == recent[-1]) & g.qb_start.fillna(False).astype(bool)].player_id)
    rows = []
    for pid in g[g.t.isin(recent)].player_id.unique():
        h = g[g.player_id == pid].tail(ROLE_GAMES)
        pos = h.position.iloc[-1]
        if pos not in GROUP:
            continue
        tg, ca = float(h.targets.mean()), float(h.carries.mean())
        role = (pid in last_start) if pos == "QB" else (tg >= ROLE_TARGETS or ca >= ROLE_CARRIES)
        rows.append((pid, h.name.iloc[-1], norm_player(h.name.iloc[-1]), pos, GROUP[pos],
                     len(h), tg, ca, float(h.offense_pct.mean()), bool(role),
                     sum(1 for x in recent if x > h.t.iloc[-1])))
    out = pd.DataFrame(rows, columns=["player_id", "name", "key", "position", "group",
                                      "games", "targets", "carries", "snap_share", "role",
                                      "missed"])
    return out.sort_values(["group", "targets", "carries"], ascending=[True, False, False]) \
              .reset_index(drop=True)


@dataclass(frozen=True)
class Bearing:
    """One flag's bearing on one player: which way it pushes his volume."""
    flag: RoleFlag
    player: str          # the affected player, as the data names him
    key: str
    team: str
    position: str
    direction: str       # UP, DOWN, QB or WATCH
    stats: tuple


def bearings(flag: RoleFlag, roles: pd.DataFrame) -> list:
    """Who `flag` bears on, among `roles` (his team's, from `team_roles`).

    OUT or DOUBTFUL, and he had a real role: his position group's other
    players are UP. BACK: they are DOWN. A quarterback out, or NEW_QB: the
    receivers, tight ends and backs who catch are QB. QUESTIONABLE with a
    real role: his group is WATCH. A flag on a player with no real role
    bears on nobody: a fourth receiver sitting moves no one's line."""
    grp = GROUP.get(flag.position)
    me = roles[roles.key == flag.key]
    had_role = bool(len(me) and me.role.iloc[0])
    others = roles[roles.key != flag.key]
    if flag.kind == "NEW_QB" or (grp == "QB" and flag.kind in ("OUT", "DOUBTFUL") and had_role):
        hit, direction = others[others.group.isin(["REC", "RB"])], "QB"
        stats = {"REC": ("receiving_yards", "receptions"),
                 "RB": ("receiving_yards", "receptions")}
    elif flag.kind == "BACK" and grp in ("REC", "RB"):
        hit, direction, stats = others[others.group == grp], "DOWN", {grp: GROUP_STATS[grp]}
    elif flag.kind in ("OUT", "DOUBTFUL") and had_role and grp in ("REC", "RB"):
        hit, direction, stats = others[others.group == grp], "UP", {grp: GROUP_STATS[grp]}
    elif flag.kind == "QUESTIONABLE" and had_role and grp in ("REC", "RB"):
        hit, direction, stats = others[others.group == grp], "WATCH", {grp: GROUP_STATS[grp]}
    else:
        return []
    return [Bearing(flag, r["name"], r.key, flag.team, r.position, direction, stats[r.group])
            for _, r in hit.iterrows()]


# ---------------------------------------------------------------------------
# 4. Is it in the price yet
# ---------------------------------------------------------------------------

def priced(direction: str, lines: pd.DataFrame, flag_at=None) -> tuple:
    """(verdict, why) for one player and stat, from his rows of `line_moves`
    (one a book). Verdicts:

      NO LINE         no book has a main line up for him
      POSTED AFTER    every line was first posted after the news: it was
                      priced from the start, and "has it moved" means nothing
      PRICED          every book has moved 10%+ the way the news points
      PARTLY          some have and some have not: the ones that have not
                      are named
      NOT MOVED       no book is 3% from its opener
      SMALL MOVE      something between
      MOVED AGAINST   a book has moved 10%+ the other way
      SHOWN           the news has no direction (QB, WATCH): moves are listed

    `flag_at` is when the news broke; without it POSTED AFTER cannot be told
    and the why says so."""
    if not len(lines):
        return "NO LINE", "no book has a main line posted"
    sign = {"UP": 1.0, "DOWN": -1.0}.get(direction)
    listed = ", ".join(f"{r.book} {r.open:g} -> {r.latest:g} ({r.move:+.0%})"
                       for r in lines.sort_values("book").itertuples())
    note = "" if flag_at is not None else " The news has no time, so it is not known whether these lines were posted before it."
    if flag_at is not None and lines.open_at.notna().all() and (lines.open_at > flag_at).all():
        return "POSTED AFTER", f"{listed}. Every line was first posted after the news."
    if sign is None:
        return "SHOWN", listed + note
    with_ = lines.move * sign
    if (with_ <= -MOVED).any():
        return "MOVED AGAINST", listed + note
    if (with_ >= MOVED).all():
        return "PRICED", listed + note
    if (with_ >= MOVED).any():
        stale = ", ".join(sorted(lines.book[with_ < MOVED]))
        return "PARTLY", f"{listed}. Not moved: {stale}." + note
    if (lines.move.abs() < FLAT).all():
        return "NOT MOVED", listed + note
    return "SMALL MOVE", listed + note


# ---------------------------------------------------------------------------
# 5. A hot run is a caution
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Form:
    """A player's last games against one line."""
    values: tuple        # his last five games played, oldest first
    over5: int | None    # how many of the last five beat the line; None under five
    over3: int | None
    avg3: float
    read: str            # HOT, COLD or ""
    text: str            # what was counted; what a HOT or COLD line has been
                         # worth is HOT_TEXT and COLD_TEXT


def form(games: pd.DataFrame, player_id, stat: str, line: float,
         season: int, week: int) -> Form:
    """His last five games going into `week` (any team, zeros counted) set
    against `line`. HOT at 4 or 5 of the last five over it, COLD at 0 or 1:
    the two cuts that were measured. Fewer than five games reads nothing.
    `player_id` is the data's id for him (`team_roles` has it)."""
    t = season * 100 + week
    v = games.loc[(games.t < t) & (games.player_id == player_id), stat] \
             .to_numpy(dtype=float)[-5:]
    if not len(v):
        return Form((), None, None, float("nan"), "", "no game log")
    if len(v) < 3:
        return Form(tuple(v), None, None, float("nan"), "", f"only {len(v)} games on file")
    o3 = int((v[-3:] > line).sum())
    if len(v) < 5:
        return Form(tuple(v), None, o3, float(v[-3:].mean()), "",
                    f"only {len(v)} games on file: over in {o3} of his last 3")
    o5 = int((v > line).sum())
    shown = ", ".join(f"{x:g}" for x in v)
    if o5 >= 4:
        return Form(tuple(v), o5, o3, float(v[-3:].mean()), "HOT",
                    f"HOT: over {line:g} in {o5} of his last 5 ({shown})")
    if o5 <= 1:
        return Form(tuple(v), o5, o3, float(v[-3:].mean()), "COLD",
                    f"COLD: over {line:g} in {o5} of his last 5 ({shown})")
    return Form(tuple(v), o5, o3, float(v[-3:].mean()), "",
                f"over {line:g} in {o5} of his last 5 ({shown})")


# ---------------------------------------------------------------------------
# 6. One game's sweep
# ---------------------------------------------------------------------------

LOG_COLS = ["run_at", "season", "week", "game", "kickoff", "team", "player", "stat",
            "why", "direction", "flag_player", "flag_kind", "flag_source", "flag_at",
            "verdict", "book", "open", "latest", "move", "open_at", "latest_at",
            "form", "over5"]


@dataclass
class Sweep:
    """One game's sweep. `rows` is the log (one row a player, stat and book
    for everything flagged or hot; `why` is "flag" for a teammate a flag
    bears on, "own" for the flagged player's own line, "hot" for a hot run
    nothing else had listed); `text` is what to print."""
    game: str
    rows: pd.DataFrame
    text: str
    flags: list = field(default_factory=list)
    look: list = field(default_factory=list)     # section 0's lines
    returns: list = field(default_factory=list)  # section 1b's players
    unplaced: list = field(default_factory=list)  # posted, on neither team's recent games
    clashes: list = field(default_factory=list)   # flagged OUT with a main line posted
    kickoff: object = None


def sweep_game(movement, flags, games: pd.DataFrame, *, season: int, week: int,
               now=None, books=None) -> Sweep:
    """Everything this module says about one game.

    `movement` is its saved `propline_get_event_movement` response, `flags`
    every flag for its two teams (others are ignored), `games` from
    `load_games`. Prints, in order: the lines where news has a direction and
    a book has not moved; the flags, each with its bearing on each teammate
    with a posted line and whether that line has moved; players with a role
    who sat the team's last game and carry no flag; every main line sitting
    on a hot run; and the two teams' roles, for reading."""
    now = _utc(now) or pd.Timestamp.now(tz="UTC")
    M = line_moves(movement, books)
    game, kick = M.attrs["game"], M.attrs["kickoff"]
    teams = (M.attrs["away"], M.attrs["home"])
    roles = {tm: team_roles(games, tm, season, week) for tm in teams}
    where = {}                      # normalised name -> team, when he is on one of them only
    for tm in teams:
        for k in roles[tm].key:
            where[k] = None if k in where else tm
    pid_of = {(tm, k): pid for tm in teams for k, pid in zip(roles[tm].key, roles[tm].player_id)}
    M = M.assign(team=[where.get(k) for k in M.key])
    flags = merge_flags([f for f in flags if f.team in teams])
    hours = (kick - now).total_seconds() / 3600 if kick is not None else float("nan")
    out = [f"=== NEWS SWEEP: {game}, kickoff {kick:%a %m-%d %H:%M} UTC "
           f"({hours:.0f} hours away) ===" if kick is not None else f"=== NEWS SWEEP: {game} ===",
           f"Main lines read: {len(M)} across {M.book.nunique()} books "
           f"({', '.join(sorted(M.book.unique())) or 'none'}), {M.key.nunique()} players. "
           f"No projection is made here, and nothing below is a probability."]
    unplaced = sorted(set(M.player[M.team.isna()]))
    if unplaced:
        out.append(f"Posted, and not placed on either team from its last four games: "
                   f"{', '.join(unplaced)}. A player back from a long absence or new "
                   f"to the team is news in itself: check him.")
    rows, look = [], []

    def log(team, player, stat, why, direction, f, verdict, lines, fm):
        for r in (lines.itertuples() if len(lines) else [None]):
            rows.append((now, season, week, game, kick, team, player, stat, why, direction,
                         f.player if f else "", f.kind if f else "", f.source if f else "",
                         f.at if f else None, verdict,
                         r.book if r else "", r.open if r else np.nan,
                         r.latest if r else np.nan, r.move if r else np.nan,
                         r.open_at if r else None, r.latest_at if r else None,
                         fm.read if fm else "", fm.over5 if fm else None))

    out.append("")
    out.append(f"1. FLAGS ({len(flags)})")
    if not flags:
        out.append("   none for these two teams. That is a finding only if the "
                   "injury and news pulls were made.")
    seen, owned, clash, told = set(), [], [], set()
    gone = {(f.team, f.key) for f in flags if f.kind == "OUT"}
    for f in flags:
        out.append("   " + f.describe())
        # a teammate who is out himself gains nothing, and his line is dead
        bs = [b for b in bearings(f, roles[f.team]) if (b.team, b.key) not in gone]
        own = M[(M.key == f.key) & (M.team == f.team)]
        up = M[(M.key == f.key) & (M.team.isna() | (M.team == f.team))]
        if f.kind == "OUT" and len(up):
            clash.append(f"{f.player} ({f.team} {f.position})")
            out.append(f"      ! FLAGGED OUT, YET {up.book.nunique()} book"
                       f"{'s have' if up.book.nunique() != 1 else ' has'} a main line up for "
                       f"him ({', '.join(PLAIN[x] for x in dict.fromkeys(up.stat))}): the "
                       f"listing is stale or the line is dead. Settle which before "
                       f"reading this team.")
        if f.kind != "OUT" and len(own):
            # his own lines, for reading: what the books have done with him
            bits = []
            for stat, lines in own.groupby("stat", sort=False):
                bits.append(f"{PLAIN[stat]} " + ", ".join(
                    f"{r.book} {r.open:g} -> {r.latest:g} ({r.move:+.0%})"
                    for r in lines.sort_values("book").itertuples()))
                fm = form(games, pid_of[(f.team, f.key)], stat,
                          float(lines.latest.median()), season, week)
                owned.append((f, stat, lines, fm))
            out.append("      his own lines: " + "; ".join(bits))
        if not bs:
            me = roles[f.team][roles[f.team].key == f.key]
            out.append("      bears on nobody: " + (
                "he is not among this team's players of its last four games" if not len(me)
                else "he did not start the team's last game"
                if not me.role.iloc[0] and me.group.iloc[0] == "QB"
                else "he had no real role (under 4 targets and 8 carries a game)"
                if not me.role.iloc[0]
                else "a note is shown for reading; no bearing is drawn from it"
                if f.kind == "NOTE"
                else "no bearing is drawn from this kind of news at his position, or "
                     "he has no teammate at it"))
            continue
        # what this kind of news has been worth is said once a game, not once a flag
        out.append(f"      {EVIDENCE[bs[0].direction]}" if bs[0].direction not in told
                   else f"      {WHAT[bs[0].direction]} (what that has been worth: above)")
        told.add(bs[0].direction)
        bare, after, quiet = [], [], 0
        arrow = {"UP": "volume UP", "DOWN": "volume DOWN", "QB": "QB change",
                 "WATCH": "watch"}[bs[0].direction]
        for b in bs:
            mine = M[(M.key == b.key) & (M.team == b.team)]
            if not mine.stat.isin(b.stats).any():
                bare.append(b.player)
            for stat in b.stats:
                lines = mine[mine.stat == stat]
                if not len(lines):
                    continue
                verdict, why = priced(b.direction, lines, f.at)
                fm = form(games, pid_of[(b.team, b.key)], stat,
                          float(lines.latest.median()), season, week)
                log(b.team, b.player, stat, "flag", b.direction, f, verdict, lines, fm)
                seen.add((b.key, stat))
                if verdict == "POSTED AFTER":
                    after.append(b.player)
                    continue
                if verdict == "SHOWN" and (lines.move.abs() < FLAT).all():
                    quiet += 1
                    continue
                out.append(f"      {b.player} {PLAIN[stat]} ({arrow}): {verdict}. {why}")
                if fm.read == "HOT":
                    out.append(f"         ! {fm.text}: a caution on the over (section 2)")
                if b.direction in ("UP", "DOWN") and verdict in OPEN_VERDICTS:
                    look.append(f"   {b.player} ({b.team}) {PLAIN[stat]}: {f.player} "
                                f"{f.kind}, {arrow}. {verdict}. {why.rstrip('.')}."
                                + (" BUT he is on a hot run, which has gone against "
                                   "the over (section 2)."
                                   if fm.read == "HOT" and b.direction == "UP" else ""))
        if after:
            out.append(f"      {len(after)} line{'s' if len(after) != 1 else ''} first posted "
                       f"AFTER this news, so priced with it from the start: "
                       f"{', '.join(dict.fromkeys(after))}")
        if quiet:
            out.append(f"      {quiet} other line{'s' if quiet != 1 else ''} within 3% of "
                       f"the opener at every book")
        if bare:
            out.append(f"      no main line posted yet for: {', '.join(bare)}")
    for f, stat, lines, fm in owned:
        # a line a flag bears on is logged as that; his own line only otherwise
        if (f.key, stat) not in seen:
            log(f.team, f.player, stat, "own", "", f, "SHOWN", lines, fm)
            seen.add((f.key, stat))
    out.append("")
    listed = {(f.team, f.key) for f in flags if f.kind in ("OUT", "DOUBTFUL", "BACK")}
    back = [(tm, x) for tm in teams for x in roles[tm].itertuples()
            if x.role and x.group != "QB" and x.missed >= 1 and (tm, x.key) not in listed]
    out.append(f"1b. RETURNS TO CHECK ({len(back)}): had a real role, sat the team's last "
               f"game or more, and no flag has him out or back")
    for tm, x in back:
        out.append(f"   {x.name} ({tm} {x.position}): missed its last "
                   f"{x.missed} game{'s' if x.missed > 1 else ''}; "
                   f"{x.targets:.1f} tgt {x.carries:.1f} car a game before. If he is back, "
                   f"flag him BACK with the time it was reported; if he is still out or "
                   f"gone, flag him OUT (an absence older than 72 hours needs "
                   f"\"confirmed\").")
    if back:
        out.append("   Either way his teammates' lines depend on it, and nothing above "
                   "has counted him.")
    out.append("")
    hot = []
    for (key, stat), lines in M[M.team.notna()].groupby(["key", "stat"], sort=False):
        fm = form(games, pid_of[(lines.team.iloc[0], key)], stat,
                  float(lines.latest.median()), season, week)
        if fm.read == "HOT":
            hot.append((lines.player.iloc[0], lines.team.iloc[0], stat, fm, lines))
    out.append(f"2. LINES SITTING ON A HOT RUN ({len(hot)}): a caution on the OVER, "
               f"not a lean to the under.")
    if hot:
        out.append(f"   What it has been worth: {HOT_TEXT}.")
    for player, team, stat, fm, lines in hot:
        out.append(f"   {player} ({team}) {PLAIN[stat]}: {fm.text}")
        if (norm_player(player), stat) not in seen:
            log(team, player, stat, "hot", "", None, "", lines, fm)
    out.append("")
    out.append("3. ROLES going in (his last four games played for the team; "
               "* = a real role)")
    for tm in teams:
        r = roles[tm]
        out.append(f"   {tm}: " + "; ".join(
            f"{'*' if x.role else ''}{x.name} {x.position}"
            + (f" {x.targets:.1f} tgt" if x.group != "QB" else "")
            + (f" {x.carries:.1f} car" if x.carries >= 1 else "")
            + (f" {x.snap_share:.0%} snaps" if x.snap_share == x.snap_share else "")
            for x in r[(r.targets >= 1) | (r.carries >= 1) | r.role].itertuples()))
    head = [f"0. NEWS THE LINE MAY NOT HAVE CAUGHT UP WITH ({len(look)}): the news points "
            f"one way and at least one book has not moved 10%"] + (look or [
            "   none. Every flagged line was posted after its news, has moved, or has "
            "no direction."]) + [""]
    at = 3 if unplaced else 2
    out[at:at] = [""] + head[:-1]
    return Sweep(game, pd.DataFrame(rows, columns=LOG_COLS), "\n".join(out), flags,
                 [x.strip() for x in look], [f"{x.name} ({tm} {x.position})" for tm, x in back],
                 unplaced, clash, kick)


def save_log(sweeps, path) -> pd.DataFrame:
    """Every sweep's rows in one table, saved as CSV for grading later."""
    d = pd.concat([s.rows for s in sweeps], ignore_index=True) if sweeps \
        else pd.DataFrame(columns=LOG_COLS)
    d.to_csv(path, index=False)
    return d


# ---------------------------------------------------------------------------
# 7. The command line
# ---------------------------------------------------------------------------

FLAG_KEYS = ("player", "team", "position", "kind", "source", "at")


def read_flag_file(path, now=None) -> list:
    """The hand-entered findings in a JSON file, each through `manual_flag`:

        {"flags": [{"player": "...", "team": "DET", "position": "WR",
                    "kind": "OUT", "source": "...", "at": "2026-11-25 14:10-05:00",
                    "detail": "...", "url": "..."}]}

    `detail`, `url` and `confirmed` (see `manual_flag`) are optional.

    One bad entry stops the read, and the error names it: a finding dropped
    without a word is worse than a run that has to be started again."""
    r = json.loads(Path(path).read_text())
    rows = r.get("flags") if isinstance(r, dict) else None
    if not isinstance(rows, list):
        raise ValueError(f"{path}: it needs a top-level \"flags\" list")
    out = []
    for i, x in enumerate(rows, 1):
        if not isinstance(x, dict):
            raise ValueError(f"{path}, entry {i}: not an object")
        gone = [k for k in FLAG_KEYS if not str(x.get(k) or "").strip()]
        if gone:
            raise ValueError(f"{path}, entry {i} ({x.get('player', '?')}): missing "
                             f"{', '.join(gone)}")
        extra = sorted(set(x) - set(FLAG_KEYS) - {"detail", "url", "confirmed"})
        if extra:
            raise ValueError(f"{path}, entry {i} ({x['player']}): unknown "
                             f"field{'s' if len(extra) > 1 else ''} {', '.join(extra)}")
        try:
            out.append(manual_flag(x["player"], x["team"], x["position"], x["kind"],
                                   x["source"], x["at"], str(x.get("detail") or ""),
                                   str(x.get("url") or ""), now=now,
                                   confirmed=x.get("confirmed")))
        except ValueError as e:
            raise ValueError(f"{path}, entry {i}: {e}") from None
    return out


def main(argv=None, games=None) -> int:
    """`python3 ff_news.py --week N [--injuries F] [--flags F] <movement files>`.
    `games` is for tests: the game log to use in place of `load_games()`."""
    import argparse
    ap = argparse.ArgumentParser(
        description="Role news against the line, one game a saved movement response.")
    ap.add_argument("movement", nargs="+",
                    help="saved propline_get_event_movement responses, one a game")
    ap.add_argument("--week", type=int, required=True, help="the NFL week being played")
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--injuries", help="the saved propline_get_injuries response (all teams)")
    ap.add_argument("--fantasypros", nargs="*", default=[],
                    help="saved FantasyPros injury_status responses")
    ap.add_argument("--flags", help="JSON file of findings entered by hand")
    ap.add_argument("--books", help="comma-separated books to read (default: all in the files)")
    ap.add_argument("--out", help="where to save the log (default: news_<season>_wk<NN>_<time>.csv)")
    ap.add_argument("--no-save", action="store_true",
                    help="print only: for a first pass made to see what to look up")
    ap.add_argument("--now", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    now = _utc(a.now) or pd.Timestamp.now(tz="UTC")
    try:
        lists, pulled = [], []
        if a.injuries:
            got = flags_from_injuries(a.injuries)
            lists.append(got)
            pulled.append(f"{len(got)} from the injury report")
        for f in a.fantasypros:
            got = flags_from_fantasypros(f)
            lists.append(got)
            pulled.append(f"{len(got)} from FantasyPros ({Path(f).name})")
        if a.flags:
            got = read_flag_file(a.flags, now=now)
            lists.append(got)
            pulled.append(f"{len(got)} entered by hand")
        flags = merge_flags(*lists)
        games = load_games() if games is None else games
        books = set(a.books.split(",")) if a.books else None
        sweeps = [sweep_game(f, flags, games, season=a.season, week=a.week, now=now, books=books)
                  for f in a.movement]
        sweeps.sort(key=lambda s: (s.kickoff is None, s.kickoff))
    except (ValueError, OSError, json.JSONDecodeError) as e:
        print(f"STOPPED: {e}")
        return 2
    have = games[(games.season == a.season) & (games.week < a.week)]
    print(f"NEWS SWEEP, {a.season} Week {a.week}, run {now:%a %m-%d %H:%M} UTC. "
          f"Flags read: {'; '.join(pulled) or 'NONE'}.")
    print(f"Game log runs through Week {int(have.week.max()) if len(have) else 0} "
          f"({have[have.week == have.week.max()].team.nunique() if len(have) else 0} teams "
          f"have a game in that week).")
    if not a.injuries:
        print("NOTE: no injury report was given, so \"no flags\" below means nothing.")
    look = [(s.game, x) for s in sweeps for x in s.look]
    print(f"\nACROSS {len(sweeps)} GAME{'S' if len(sweeps) != 1 else ''}: {len(look)} "
          f"line{'s' if len(look) != 1 else ''} where news points one way and a book has "
          f"not moved 10%; {sum(len(s.returns) for s in sweeps)} possible "
          f"return{'s' if sum(len(s.returns) for s in sweeps) != 1 else ''} to check.")
    for g, x in look:
        print(f"   [{g}] {x}")
    for s in sweeps:
        if s.returns:
            print(f"   [{s.game}] possible return: {', '.join(s.returns)}")
        if s.unplaced:
            print(f"   [{s.game}] posted but not on either team's last four games: "
                  f"{', '.join(s.unplaced)}")
        if s.clashes:
            print(f"   [{s.game}] flagged OUT yet a line is posted: {', '.join(s.clashes)}")
    for s in sweeps:
        print("\n" + s.text)
    if a.no_save:
        print("\nFirst pass: nothing saved. Run again without --no-save once the "
              "findings are entered.")
        return 0
    out = a.out or f"news_{a.season}_wk{a.week:02d}_{now:%m%d-%H%M}.csv"
    d = save_log(sweeps, out)
    print(f"\nSaved {len(d):,} rows ({d[['game', 'player', 'stat']].drop_duplicates().shape[0]:,} "
          f"lines flagged or hot) to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
