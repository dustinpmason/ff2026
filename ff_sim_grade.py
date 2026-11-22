"""S29. Grade saved shadow runs against what happened.

A shadow run (`sim_live.py --out`) saves one row for each posted line it
priced: the player, the stat, the line, and the chance it gave the over,
a push and the under, IF HE PLAYS. This reads those files once the games
are on file and says what happened.

WHAT COUNTS AS WHAT.
- A game is on file when the data has BOTH the stats and the snap counts
  for the team that week, against the opponent the file was saved with. The
  two arrive separately, and with only one of them a man who played and
  did nothing cannot be told from a man who sat out. Until both are in,
  its lines are "not on file" or "half on file" and are left out, by name.
  A file whose week the data has against another opponent, or has no
  game for though it has later ones, is refused.
- A player with no row in his team's game did not play. His lines are
  void, as a book voids them, and are counted and named, not graded. Two
  cases the data's own table misses are put right when the raw tables
  are handed in: a man listed under his name in a snap-count row that
  the data could not tie to any player (`unplaced_snaps`) played, and is
  graded on no stats; and a
  touchdown on a return or a recovery counts toward "anytime", as a book
  counts it, though the simulator's own touchdown stat is rushing and
  receiving only.
- A line is OVER when he did more than the line, UNDER when less, and a
  PUSH when the same. A push is counted and not graded.
- The chance graded is the over's share of over plus under, so a
  whole-number line is read as "if it does not push".

ONE LINE PER PLAYER AND STAT. A player's rungs win and lose together, so
the headline tables read one line for each player and stat: the book's
main line (where books differ, the one more of them post, as a main line
or as a rung), or, where no main line was posted, the line the run put
nearest 50%. The anytime touchdown is the line at 0.5. That choice is
made from the saved file alone, before any result is looked at. Tables of
every line use the harness's own rule: one rung per player, stat and side
inside a band.

NOTHING HERE IS A VERDICT BEFORE 30 GAMES, the harness's rule
(`ff_sim.MIN_GAMES_FOR_VERDICT`). Under that it gives the figures and
says "too few games to say".

THE YARDSTICK IS A COIN FLIP, AND IT IS A LOW ONE. A book's main line is
its own middle, so calling every main line 50/50 scores 0.250. The run's
chances on main lines are scored beside that. Scoring under 0.250 says
its leans on main lines carried something; it does not say a bet would
have paid, and it is not a comparison with the market's price, which the
saved files do not hold. No price is read.

What it cannot know: when a file was made. It takes the file's word that
it was saved before kickoff; the commit time in the repository is the
evidence.
"""
from __future__ import annotations

import math
import re
from pathlib import Path

import numpy as np
import pandas as pd

import ff_sim as fs
import ff_sim_live as fl
from ff_sim import TD_STAT
from ff_sim_live import Missing
from ff_sim_td import ALL_STATS

#: What `ff_sim_live.to_csv` saves, in its order.
SHADOW_COLS = ["season", "week", *fl.LINE_COLS, "record", "cautions"]
NUMBERS = ("line", "chance", "expected", "over", "push", "under")
#: What one saved line is: a second row with the same is a mistake. A team
#: plays once a week, so the game id, a label, is not part of it.
LINE_KEY = ["season", "week", "team", "player_id", "stat", "line"]
#: One player and stat.
ONE = ["season", "week", "team", "player_id", "stat"]
GRADED = ("over", "under")
NOT_ON_FILE, HALF_ON_FILE, DID_NOT_PLAY, OTHER_TEAM, PUSH = (
    "not on file", "half on file", "did not play", "other team", "push")
#: Left out because the game is not all in the data yet.
WAITING = (NOT_ON_FILE, HALF_ON_FILE)
#: Touchdowns a book pays that the simulator's own stat leaves out.
OTHER_TDS = ("special_teams_tds", "def_tds", "fumble_recovery_tds")
TEXT = ("game_id", "team", "opponent", "player_id", "name", "position", "source", "stat",
        "kind", "rung", "no_record", "books", "suspended", "matched", "record", "cautions")
#: A main line taken as a coin flip.
COIN = 0.25
#: The record's own figure, as `ff_sim_live.record_text` writes it.
RECORD_RATE = re.compile(r"happened (\d+(?:\.\d+)?)% of ")


def read_shadow(paths) -> pd.DataFrame:
    """The saved runs as one table, with `file`. Refuses a file that is not
    one, has a line twice, gives one game two ids, or holds a team's game
    that another file holds: a game graded twice would count twice."""
    paths = [str(p) for p in ([paths] if isinstance(paths, (str, Path)) else paths)]
    if not paths:
        raise Missing("no shadow file was given")
    out, held = [], {}
    for path in paths:
        name = Path(path).name
        try:
            d = pd.read_csv(path, dtype=str, keep_default_na=False)
        except (OSError, UnicodeDecodeError, pd.errors.ParserError,
                pd.errors.EmptyDataError) as e:
            raise Missing(f"cannot read the shadow file {name}: {e}") from e
        lacking = [c for c in SHADOW_COLS if c not in d.columns]
        if lacking:
            raise Missing(f"{name} is not a saved shadow run: it has no "
                          f"{lacking}")
        if not len(d):
            raise Missing(f"{name} has no lines in it")
        d = d[SHADOW_COLS].copy()
        for c in TEXT:
            d[c] = d[c].str.strip()
        for c in ("season", "week", *NUMBERS):
            v = pd.to_numeric(d[c], errors="coerce")
            if not np.isfinite(v).all():
                raise Missing(f"{name}: \"{c}\" is not a number on row "
                              f"{int(np.flatnonzero(~np.isfinite(v))[0]) + 2}")
            d[c] = v
        for c in ("season", "week"):
            if (d[c] != d[c].round()).any():
                raise Missing(f"{name}: \"{c}\" is not a whole number")
            d[c] = d[c].astype(int)
        if len(d[["season", "week"]].drop_duplicates()) != 1:
            raise Missing(f"{name} holds more than one week")
        odd = sorted(set(d.stat) - set(ALL_STATS))
        if odd:
            raise Missing(f"{name} has a stat this cannot grade: {odd}")
        P = d[["over", "push", "under"]]
        if ((P < 0) | (P > 1)).any().any() or (abs(P.sum(axis=1) - 1) > 1e-6).any():
            raise Missing(f"{name}: over, push and under do not add up to "
                          f"one on every row; the file is not as it was saved")
        if ((d.chance < 0) | (d.chance > 1)).any():
            raise Missing(f"{name}: a chance of playing is not between 0 and 1")
        if (P.over + P.under <= 0).any():
            raise Missing(f"{name}: a line is saved as a certain push, with no "
                          f"chance of over or under")
        twice = d[d.duplicated(LINE_KEY, keep=False)]
        if len(twice):
            r = twice.iloc[0]
            raise Missing(f"{name} has {r['name']} {r.stat} {r.line:g} more "
                          f"than once")
        teams = d.assign(_m=[" and ".join(sorted(x)) for x in zip(d.team, d.opponent)])
        for a, b, what in (("_m", "game_id", "more than one game id for"),
                           ("game_id", "_m", "more than one game under the id")):
            n_ = teams.groupby(a)[b].nunique()
            if (n_ > 1).any():
                raise Missing(f"{name} has {what} {n_[n_ > 1].index[0]}")
        for g in sorted(set(zip(d.season, d.week, d.team))):
            if g in held:
                raise Missing(f"{held[g]} and {name} both hold {g[2]}'s game of "
                              f"{g[0]} Week {g[1]}: grade one run of a game, "
                              f"not two")
            held[g] = name
        out.append(d.assign(file=name))
    return pd.concat(out, ignore_index=True)


def unplaced_snaps(snaps: pd.DataFrame, rosters: pd.DataFrame) -> pd.DataFrame:
    """The snap-count rows `ff_sim.build_frame` cannot tie to a player:
    their PFR id is in no roster, or a roster gives it to two players.
    Only these are read by name, so a namesake the data does know is not
    taken for a man it does not."""
    x = (rosters[rosters.pfr_id.notna() & rosters.gsis_id.notna()]
         [["pfr_id", "gsis_id"]].astype(str).drop_duplicates())
    per = x.groupby("pfr_id").gsis_id.nunique()
    return snaps[~snaps.pfr_player_id.astype(str).isin(set(per[per == 1].index))]


def books_on(row) -> int:
    """How many books posted this line."""
    return len(str(row.books).split())


def headline(shadow: pd.DataFrame) -> pd.Series:
    """True on the one line read for each player and stat (see the top).
    Chosen from the saved rows alone."""
    p = shadow.over / (shadow.over + shadow.under)
    d = shadow.assign(_p=(p - 0.5).abs(), _books=[books_on(r) for r in shadow.itertuples()])
    pick = pd.Series(False, index=shadow.index)
    for _, g in d.groupby(ONE, sort=False):
        if g.stat.iloc[0] == TD_STAT:
            g = g[g.line == 0.5]
        elif (g.kind == "main").any():
            g = g[g.kind == "main"].sort_values(["_books", "_p", "line"],
                                                ascending=[False, True, True], kind="stable")
        else:
            g = g.sort_values(["_p", "line"], kind="stable")
        if len(g):
            pick[g.index[0]] = True
    return pick


def grade(shadow: pd.DataFrame, frame: pd.DataFrame, weekly=None, snaps=None) -> pd.DataFrame:
    """Each saved line with what happened: `actual`, `result` (over, under,
    push, did not play, other team, not on file, half on file), `how` (""
    or what was put right from the raw tables), and for a line that is
    over or under: `p` (the over's chance if it does not push), the `side`
    the run favoured, that side's chance `p_side`, and whether it `hit`.
    Also `headline` and `main_line`, the headline line of his stat.

    `weekly` is the raw stats table (`ff_data.load_weekly`) and `snaps`
    the snap rows the data could not place (`unplaced_snaps`). Either may
    be left out: see the top."""
    lacking = sorted(c for c in {"t", "team", "opponent", "player_id", *shadow.stat}
                     if c not in frame.columns)
    if lacking:
        raise Missing(f"the data has no column for {lacking}")
    t = shadow.season * 100 + shadow.week
    F = frame[frame.t.isin(set(t))]
    if F.duplicated(["t", "player_id"]).any():
        raise Missing("the data has a player twice in one week")
    both = {}
    for k, g in F.groupby(["t", "team"], sort=False):
        both[k] = (set(g.opponent),
                   bool(g.has_stats.any()) if "has_stats" in g else True,
                   bool(g.has_snaps.any()) if "has_snaps" in g else True)
    newest = frame.groupby("team").t.max().to_dict()
    state = {}
    for tt, team, opp, gid in sorted(set(zip(t, shadow.team, shadow.opponent, shadow.game_id))):
        where = f"{team} in {tt // 100} Week {tt % 100}"
        if (tt, team) not in both:
            if newest.get(team, -1) > tt:
                raise Missing(f"the data has no game for {where}, though it "
                              f"has later weeks of {team}: the saved file's "
                              f"week is not the data's")
            state[(tt, team, gid)] = NOT_ON_FILE
            continue
        against, stats_in, snaps_in = both[(tt, team)]
        if against != {opp}:
            raise Missing(f"the saved file has {where} against {opp}, and the "
                          f"data has it against {sorted(against)}: the file's "
                          f"week or game is not the data's")
        state[(tt, team, gid)] = "" if stats_in and snaps_in else HALF_ON_FILE
    at = {(a, b): i for i, (a, b) in enumerate(zip(F.t, F.player_id))}
    team = F.team.to_numpy()
    more = {}
    if weekly is not None:
        w = weekly[weekly.season_type == "REG"]
        extra = sum(pd.to_numeric(w[c], errors="coerce").fillna(0.0) for c in OTHER_TDS)
        more = {(int(a) * 100 + int(b), c): float(x)
                for a, b, c, x in zip(w.season, w.week, w.player_id, extra) if x > 0}
    seen = set()
    if snaps is not None:
        sn = snaps[snaps.game_type == "REG"]
        on = sn[["offense_snaps", "defense_snaps", "st_snaps"]].fillna(0).sum(axis=1) > 0
        seen = {(int(a) * 100 + int(b), c, fl.norm_player(str(n)))
                for a, b, c, n in zip(sn.season[on], sn.week[on], sn.team[on], sn.player[on])}
    actual, result, how = [], [], []
    for tt, r in zip(t, shadow.itertuples(index=False)):
        i = at.get((tt, r.player_id))
        a, res, note = float("nan"), state[(tt, r.team, r.game_id)], ""
        if res:
            pass
        elif i is None and (tt, r.team, fl.norm_player(r.name)) in seen:
            a, note = 0.0, "played by the snap count, under his name"
        elif i is None:
            res = DID_NOT_PLAY
        elif team[i] != r.team:
            res = OTHER_TEAM
        else:
            a = float(F[r.stat].iloc[i])
            if r.stat == TD_STAT and more.get((tt, r.player_id)):
                a += more[(tt, r.player_id)]
                note = "a touchdown on a return or a recovery"
        if not res:
            res = "over" if a > r.line else "under" if a < r.line else PUSH
        actual.append(a)
        result.append(res)
        how.append(note)
    G = shadow.assign(actual=actual, result=result, how=how)
    G["p"] = G.over / (G.over + G.under)
    fav = G.p >= 0.5
    G["side"] = np.where(fav, "OVER", "UNDER")
    G["p_side"] = np.where(fav, G.p, 1.0 - G.p)
    done = G.result.isin(GRADED)
    G["hit"] = np.where(done, (G.result == "over") == fav, np.nan)
    G["headline"] = headline(shadow)
    main = G[G.headline].set_index(ONE).line
    G["main_line"] = [main.get(k, float("nan")) for k in zip(*(G[c] for c in ONE))]
    return G


def legs(G: pd.DataFrame) -> pd.DataFrame:
    """The graded lines in the shape `ff_sim.calibration` reads."""
    d = G[G.result.isin(GRADED)].copy()
    d["over"] = d.result == "over"
    d["hit"] = d.hit.astype(bool)
    d["main_line"] = d.main_line.fillna(d.line)
    return d


def rate(d: pd.DataFrame, p_col: str = "p_side", hit_col: str = "hit") -> dict:
    """What a set of graded lines said and what happened: n, games, stated,
    happened, the 95% range and the harness's reading of it."""
    if not len(d):
        return {"n": 0, "games": 0, "stated": float("nan"), "happened": float("nan"),
                "lo": float("nan"), "hi": float("nan"), "read": "nothing here"}
    r = fs.rate_range(d[hit_col].astype(float), d.game_id)
    stated = float(d[p_col].mean())
    return {"n": r["n"], "games": r["games"], "stated": stated, "happened": r["rate"],
            "lo": r["lo"], "hi": r["hi"], "read": fs.read_rate(stated, r)}


def brier(d: pd.DataFrame) -> dict:
    """The run's chances scored on these lines, beside the 0.250 of
    calling every one 50/50: the score, the gap to that (negative is
    better), the gap's clustered error, and a reading, refused under 30
    games."""
    if not len(d):
        return {"n": 0, "games": 0, "brier": float("nan"), "gap": float("nan"),
                "se": float("nan"), "read": "nothing here"}
    sq = (d.p - d["over"].astype(float)) ** 2
    gap, se, n, games = fs.cluster_mean(sq - COIN, d.game_id)
    read = ("too few games to say" if games < fs.MIN_GAMES_FOR_VERDICT else
            "no better or worse than calling them 50/50" if not abs(gap) > 2 * se else
            "better than calling them 50/50" if gap < 0 else "WORSE than calling them 50/50")
    return {"n": n, "games": games, "brier": float(sq.mean()), "gap": gap, "se": se,
            "read": read}


def record_rate(text) -> float:
    """What the record said happens in this line's band, or NaN."""
    m = RECORD_RATE.search(str(text))
    return float(m.group(1)) / 100.0 if m else float("nan")


def splits(H: pd.DataFrame) -> list:
    """The splits of the headline lines: (label, which rows)."""
    c = H.cautions.astype(str)
    return [
        ("with a record", H.no_record.astype(str) == ""),
        ("no record: off his ladder", H.no_record == fl.OFF_LADDER),
        ("no record: no role", H.no_record == fl.NO_ROLE),
        ("S21 main-line caution", c.str.contains("S21 main-line caution", regex=False)),
        ("passing-touchdown unders", (H.stat == "passing_tds") & (H.side == "UNDER")),
        ("a posted teammate off the slate", c.str.contains("too high if", regex=False)),
        ("matched by name or alias", H.matched.isin(["name", "alias"])),
        ("line suspended when saved", H.suspended.astype(str) != ""),
        ("it favoured the OVER", H.side == "OVER"),
        ("it favoured the UNDER", H.side == "UNDER"),
    ]


def stat_error(G: pd.DataFrame) -> pd.DataFrame:
    """For players who played, one row a stat: what the run expected, what
    happened, its typical miss and the typical miss of the book's line.
    One line per player and stat; the anytime touchdown is left out."""
    d = G[G.headline & G.actual.notna() & (G.stat != TD_STAT)]
    rows = []
    for stat in [s for s in ALL_STATS if s in set(d.stat)]:
        x = d[d.stat == stat]
        rows.append((stat, len(x), x.game_id.nunique(), float(x.expected.mean()),
                     float(x.actual.mean()), float((x.expected - x.actual).abs().mean()),
                     float((x.line - x.actual).abs().mean())))
    return pd.DataFrame(rows, columns=["stat", "n", "games", "expected", "actual",
                                       "miss", "line_miss"])


def _pct(x) -> str:
    return "  n/a" if x != x else f"{100 * x:5.1f}%"


def _line(label: str, r: dict) -> str:
    if not r["n"]:
        return f"  {label:<34} nothing here"
    return (f"  {label:<34} {r['n']:>5} lines, {r['games']:>3} games: said "
            f"{_pct(r['stated'])}, happened {_pct(r['happened'])} "
            f"({_pct(r['lo']).strip()} to {_pct(r['hi']).strip()}; {r['read']})")


def render(G: pd.DataFrame) -> str:
    """The report."""
    out = []
    weeks = sorted(set(zip(G.season, G.week)))
    out.append("SHADOW RUNS GRADED: " + ", ".join(f"{s} Week {w}" for s, w in weeks)
               + f" ({', '.join(sorted(set(G.file)))})")
    n = G.result.value_counts()
    games_done = G[G.result.isin(GRADED)].game_id.nunique()
    out.append(f"{len(G):,} saved lines in {G.game_id.nunique()} games. "
               f"Graded {int(n.get('over', 0) + n.get('under', 0)):,} "
               f"(over {int(n.get('over', 0)):,}, under {int(n.get('under', 0)):,}) "
               f"in {games_done} games; pushes {int(n.get(PUSH, 0)):,}; did not play "
               f"{int(n.get(DID_NOT_PLAY, 0)):,}; other team {int(n.get(OTHER_TEAM, 0)):,}; "
               f"not on file {int(n.get(NOT_ON_FILE, 0)):,}; half on file "
               f"{int(n.get(HALF_ON_FILE, 0)):,}.")
    for label, res in (("NOT ON FILE YET, left out", NOT_ON_FILE),
                       ("HALF ON FILE (the stats or the snap counts, not both yet), left out",
                        HALF_ON_FILE)):
        waiting = sorted(set(G.game_id[G.result == res]))
        if waiting:
            out.append(f"{label}: {', '.join(waiting)}.")
    for label, res in (("DID NOT PLAY, lines void", DID_NOT_PLAY),
                       ("PLAYED FOR ANOTHER TEAM, lines void", OTHER_TEAM)):
        who = G[G.result == res].drop_duplicates(["game_id", "team", "player_id"])
        if len(who):
            out.append(f"{label}: " + ", ".join(
                f"{r['name']} ({r.team}, it said {r.chance:.0%} to play)"
                for _, r in who.iterrows()) + ".")
    for label, note in (("GRADED ON NO STATS, the snap counts list him by name and the data "
                         "could not tie him to an id", "played by the snap count, under his name"),
                        ("SCORED ON A RETURN OR A RECOVERY, counted as a book counts it",
                         "a touchdown on a return or a recovery")):
        who = G[G.how == note].drop_duplicates(["game_id", "team", "player_id"])
        if len(who):
            out.append(f"{label}: " + ", ".join(f"{r['name']} ({r.team})"
                                                for _, r in who.iterrows()) + ".")
    P = G[~G.result.isin(WAITING)].drop_duplicates(["game_id", "team", "player_id"])
    if len(P):
        played = ~P.result.isin([DID_NOT_PLAY, OTHER_TEAM])
        out.append(f"Chance of playing, posted players: it said {_pct(P.chance.mean()).strip()} "
                   f"on average; {int(played.sum())} of {len(P)} played "
                   f"({_pct(played.mean()).strip()}).")
    L = legs(G)
    if not len(L):
        out.append("")
        out.append("Nothing to grade yet.")
        return "\n".join(out)
    H = L[L.headline]
    if games_done < fs.MIN_GAMES_FOR_VERDICT:
        out.append(f"READ THIS FIRST: {games_done} games. Nothing below is a verdict "
                   f"before {fs.MIN_GAMES_FOR_VERDICT} games; the figures are given, "
                   f"and the reading is refused.")
    out.append("")
    S = H[H.stat != TD_STAT]
    mains = S[S.kind == "main"]
    out.append(f"1. ONE LINE PER PLAYER AND STAT, on the side the run favoured: "
               f"{len(mains):,} the book's main line, {len(S) - len(mains):,} the line "
               f"nearest 50% where it posted no main line")
    out.append(_line("all stats but the anytime touchdown", rate(S)))
    b = brier(mains)
    if b["n"]:
        out.append(f"  main lines scored (Brier, lower is better): {b['brier']:.3f} beside "
                   f"{COIN:.3f} for calling every one 50/50; gap {b['gap']:+.3f} (error "
                   f"{b['se']:.3f}; {b['read']}). This is not the market's price.")
    for stat in [s for s in ALL_STATS if s in set(S.stat)]:
        out.append(_line("  " + stat.replace("_", " "), rate(S[S.stat == stat])))
    cal = fs.calibration(S)
    out.append("  by what it said:")
    for r in cal.itertuples():
        if r.n:
            out.append(f"    {r.band:<9} {r.n:>5} lines, {r.games:>3} games: said "
                       f"{_pct(r.stated)}, happened {_pct(r.happened)} ({r.read})")
    T = H[H.stat == TD_STAT]
    out.append(_line("anytime touchdown, chance to score", rate(T, "p", "over")))
    out.append("")
    out.append("2. THE SAME LINES, SPLIT")
    for label, which in splits(S):
        out.append(_line(label, rate(S[which])))
    R = S.assign(_rec=[record_rate(x) for x in S.record])
    R = R[R._rec.notna()]
    if len(R):
        out.append(f"  where the record gave a figure ({len(R)} lines): it said "
                   f"{_pct(R.p_side.mean()).strip()}, the record said "
                   f"{_pct(R._rec.mean()).strip()}, and {_pct(R.hit.mean()).strip()} happened")
    out.append("")
    out.append("3. THE STAT LINES, for players who played: expected, actual, typical miss, "
               "and the book line's typical miss")
    for r in stat_error(G).itertuples():
        out.append(f"  {r.stat.replace('_', ' '):<18} {r.n:>4} players: expected "
                   f"{r.expected:7.1f}, actual {r.actual:7.1f}, miss {r.miss:6.1f}, "
                   f"line's miss {r.line_miss:6.1f}")
    out.append("  (not like for like: the run's number is an average, and a line is a "
               "half-point near the middle, which on a small count cannot miss by under a half)")
    out.append("")
    out.append("4. EVERY POSTED LINE, ladders included (one rung per player, stat and "
               "side inside a band)")
    A = L[L.stat != TD_STAT]
    out.append(_line("all lines, each counted", rate(A)))
    for r in fs.calibration(A).itertuples():
        if r.n:
            out.append(f"    {r.band:<9} {r.n:>5} lines ({r.legs_before_dedupe:,} before a "
                       f"ladder is counted once), {r.games:>3} games: said {_pct(r.stated)}, "
                       f"happened {_pct(r.happened)} ({r.read})")
    for ln in sorted(set(L.line[(L.stat == TD_STAT) & (L.line > 0.5)])) or [1.5]:
        out.append(_line(f"{math.ceil(ln)} or more touchdowns, chance",
                         rate(L[(L.stat == TD_STAT) & (L.line == ln)], "p", "over")))
    return "\n".join(out)


def to_csv(G: pd.DataFrame) -> pd.DataFrame:
    """The graded table to save: the saved columns, then what happened."""
    return G[[*SHADOW_COLS, "file", "actual", "result", "how", "headline", "p", "side",
              "p_side", "hit"]]


def grade_files(frame: pd.DataFrame, paths, out=None, weekly=None, snaps=None) -> tuple:
    """Everything `sim_grade.py` does once the data is loaded: (what to
    print, exit code). 2 with "STOPPED." when something is missing, 3 on a
    fault it did not foresee."""
    try:
        G = grade(read_shadow(paths), frame, weekly, snaps)
        text = render(G)
        if out:
            try:
                to_csv(G).to_csv(out, index=False)
            except OSError as e:
                raise Missing(f"cannot save the graded table to {out}: {e}") from e
            text += f"\nsaved {len(G):,} graded lines to {out}"
        return text, 0
    except Missing as e:
        return f"STOPPED. {e}", 2
    except Exception as e:       # noqa: BLE001 - say so, do not dump a traceback
        return (f"STOPPED. Something it did not foresee: {type(e).__name__}: {e}", 3)


__all__ = ["read_shadow", "headline", "grade", "legs", "rate", "brier", "splits",
           "stat_error", "render", "to_csv", "grade_files", "record_rate"]
