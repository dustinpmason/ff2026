"""The simulator's own suite. Run after any change: `python3 test_sim.py`

Separate from `test_regression.py`, which belongs to the betting engine and
keeps its own count. Quote the count THIS file prints, and nothing else.

The behaviours here are broken on purpose by `sim_reverts.py`: it removes
each one from a copy of `ff_sim.py` and confirms this suite then fails.
`SIM-BACKLOG.md` gives the count from its last run. A section that raises
is recorded as a FAILED check named for the section, and the sections after
it still run.

Expectations on real data are derived from the data on file, and from weeks
BEFORE the newest one on file, which may be half-played. No check names a
player or types a week.
"""
import warnings; warnings.filterwarnings("ignore")
import atexit, math, sys, traceback
import numpy as np, pandas as pd

import ff_sim as fs
from ff_sim import (History, LeakError, MAIN, TD_STAT, Projection, Projector,
                    Run, tkey)

fails, ran = [], []
_crashed = []


def chk(name, ok, detail=""):
    ran.append(name)
    ok = bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'  — ' + str(detail) if detail else ''}")
    if not ok:
        fails.append(name)


def _summary():
    if getattr(_summary, "done", False):
        return
    _summary.done = True
    print("\n" + "=" * 60)
    print(f"{len(ran)} checks run, {len(ran) - len(fails)} passed, "
          f"{len(fails)} failed")
    if _crashed:
        print(f"{len(_crashed)} SECTION(S) RAISED and did not finish: "
              f"{', '.join(_crashed)}. Each is counted above as one failed "
              f"check; the checks it did not reach were NOT run.")
    print("ALL PASS" if not fails else "FAILURES: " + "; ".join(fails))


atexit.register(_summary)


def section(title):
    """Run one section; a raise is a named failure, not the end of the run."""
    def deco(fn):
        print(f"\n{title}")
        try:
            fn()
        except Exception as e:                      # noqa: BLE001
            traceback.print_exc()
            _crashed.append(title)
            chk(f"SECTION RAISED: {title}", False, f"{type(e).__name__}: {e}")
        return fn
    return deco


def raises(fn, exc, text=None):
    """True when fn() raises `exc` (and its message contains `text`)."""
    try:
        fn()
    except exc as e:
        return text is None or text in str(e)
    except Exception:                               # noqa: BLE001
        return False
    return False


def near(a, b, tol=1e-9):
    return (isinstance(a, (int, float, np.floating)) and math.isfinite(a)
            and abs(float(a) - float(b)) <= tol)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def gid(season, week, a, b):
    lo, hi = sorted((a, b))
    return f"{season}_{week:02d}_{lo}_{hi}"


def row(season, week, team, opp, pid, pos, **kw):
    r = dict(season=season, week=week, game_id=gid(season, week, team, opp),
             team=team, opponent=opp, player_id=pid, name=kw.pop("name", pid),
             has_stats=True, has_snaps=True, offense_snaps=30.0,
             offense_pct=0.5, st_snaps=0.0, position=pos,
             snap_position=kw.pop("snap_position", pos),
             qb_start=kw.pop("qb_start", False))
    for c in fs.RAW_STATS:
        r[c] = 0.0
    r.update(kw)
    return r


def mkframe(rows):
    f = pd.DataFrame(rows)
    f["t"] = f.season * 100 + f.week
    for c in fs.RAW_STATS:
        f[c] = f[c].astype(float)
    f[TD_STAT] = f.rushing_tds + f.receiving_tds
    f["qb_start"] = f["qb_start"].astype(bool)
    for c in ("game_id", "team", "opponent", "player_id", "name", "position",
              "snap_position"):
        f[c] = f[c].astype(object)
    return f.sort_values(["player_id", "t"], kind="stable").reset_index(drop=True)


# One receiver whose numbers are worked by hand in section 7.
#                  2023 wk 1..6            2024 wk 1..4 (wk 4 is graded)
HAND_TARGETS = {2023: [6, 8, 4, 10, 6, 8], 2024: [5, 7, 9, 3]}
SEASON_WEEKS = {2023: 6, 2024: 4}
MATCHUPS = (("AAA", "BBB"), ("CCC", "DDD"))


def league(extra=(), drop=()):
    """Two games a week, two seasons, five players a side. `extra` rows are
    added; `drop` is a set of (season, week, player_id) to leave out."""
    rows = []
    for season, nweeks in SEASON_WEEKS.items():
        for week in range(1, nweeks + 1):
            for a, b in MATCHUPS:
                for ti, (team, opp) in enumerate(((a, b), (b, a))):
                    k = (season + week * 3 + ti + len(team) + ord(team[0])) % 5
                    att = 30 + k
                    rows.append(row(season, week, team, opp, f"{team}_QB", "QB",
                                    qb_start=True,
                                    attempts=att, completions=att - 10,
                                    passing_yards=7.0 * att, passing_tds=k % 3,
                                    carries=2, rushing_yards=5 + k))
                    rows.append(row(season, week, team, opp, f"{team}_RB", "RB",
                                    carries=14 + k, rushing_yards=4.0 * (14 + k),
                                    rushing_tds=(k + week) % 2, targets=2,
                                    receptions=1, receiving_yards=6 + k))
                    t1 = (HAND_TARGETS[season][week - 1] if team == "AAA"
                          else 5 + (k + week) % 4)
                    rows.append(row(season, week, team, opp, f"{team}_WR1", "WR",
                                    targets=t1, receptions=max(t1 - 2, 0),
                                    receiving_yards=10.0 * max(t1 - 2, 0),
                                    receiving_tds=(week + ti) % 2))
                    t2 = 4 + (k + 2 * week) % 3
                    rows.append(row(season, week, team, opp, f"{team}_WR2", "WR",
                                    targets=t2, receptions=t2 - 1,
                                    receiving_yards=8.0 * (t2 - 1)))
                    rows.append(row(season, week, team, opp, f"{team}_TE", "TE",
                                    targets=1 + k % 2, receptions=k % 2,
                                    receiving_yards=5.0 * (k % 2)))
    rows = [r for r in rows
            if (r["season"], r["week"], r["player_id"]) not in set(drop)]
    return mkframe(rows + list(extra))


class Const(Projector):
    """Says the same thing about everyone."""
    def __init__(self, name="const", point=1.0, p=0.6, uses_actives=False):
        self.name, self._pt, self._p = name, point, p
        self.uses_actives = uses_actives

    def project(self, hist, slate):
        o = self

        class P(Projection):
            def point(self, i, stat): return o._pt
            def p_over(self, i, stat, line): return o._p
        return P()


class SlateSize(Projector):
    """Its answer depends on who is on the slate."""
    name = "slate_size"

    def __init__(self, uses_actives):
        self.uses_actives = uses_actives

    def project(self, hist, slate):
        n = float(len(slate))

        class P(Projection):
            def point(self, i, stat): return n
            def p_over(self, i, stat, line): return 0.5
        return P()


PT_COLS = [*fs._BASE_COLS, "stat", "role", "actual"]
LEG_COLS = [*fs._BASE_COLS, "stat", "rung", "line", "main_line", "actual",
            "over"]


def mkrun(points=(), legs=(), names=("m",)):
    """A Run built by hand, for the report functions."""
    def base(d):
        g = d.get("game_id", "g1")
        return dict(version=d.get("version", "A"), season=2024, week=1,
                    game_id=g, team=d.get("team", "AAA"), opponent="BBB",
                    player_id=d.get("player_id", "p1"),
                    name=d.get("player_id", "p1"),
                    position=d.get("position", "WR"),
                    played=d.get("played", True), newest_input=202323,
                    team_games_missed=0)
    prow, lrow = [], []
    for d in points:
        r = base(d)
        r.update(stat=d.get("stat", "receptions"), role=d.get("role", True),
                 actual=d.get("actual", float("nan")))
        for n in names:
            r[f"pt_{n}"] = d.get(n, float("nan"))
        prow.append(r)
    for d in legs:
        r = base(d)
        r.update(stat=d.get("stat", "receptions"), rung=d.get("rung", MAIN),
                 line=d.get("line", 4.5),
                 main_line=d.get("main_line", d.get("line", 4.5)),
                 actual=d.get("actual", 0.0), over=d.get("over", False))
        for n in names:
            r[f"p_{n}"] = d.get(n, float("nan"))
        lrow.append(r)
    return Run(points=pd.DataFrame(prow, columns=[*PT_COLS, *(f"pt_{n}" for n in names)]),
               legs=pd.DataFrame(lrow, columns=[*LEG_COLS, *(f"p_{n}" for n in names)]),
               names=list(names), weeks=[202401])


# ---------------------------------------------------------------------------
@section("1. the frame — who counts as having played")
def _():
    def wrow(game, pid, name, pos, team="AAA", opp="BBB", stype="REG", **kw):
        r = dict(season=2024, week=int(game.split("_")[1]), season_type=stype,
                 game_id=game, team=team, opponent_team=opp, player_id=pid,
                 player_display_name=name, position=pos)
        for c in fs.RAW_STATS:
            r[c] = 0
        r.update(kw)
        return r

    def srow(game, pfr, name, pos, off, st=0, team="AAA", opp="BBB",
             gtype="REG"):
        return dict(season=2024, week=int(game.split("_")[1]), game_type=gtype,
                    game_id=game, team=team, opponent=opp, player=name,
                    pfr_player_id=pfr, position=pos, offense_snaps=off,
                    offense_pct=off / 60.0, st_snaps=st)

    g1, g2, g3 = "2024_01_AAA_BBB", "2024_02_AAA_BBB", "2024_03_AAA_BBB"
    weekly = pd.DataFrame([
        wrow(g1, "G1", "Rec One", "WR", targets=5, receptions=3,
             receiving_yards=40, receiving_tds=1, rushing_tds=1,
             passing_tds=2),
        wrow(g1, "G2", "Rec Two", "TE", targets=2),
        wrow(g2, "G1", "Rec One", "WR", targets=4),
        wrow(g1, "G9", "Corner", "CB", targets=1),          # a defender thrown to
        wrow(g2, "G9", "Corner", "CB"),                      # ...and a game he was not
        wrow(g1, "G7", "Punter", "P", attempts=1),           # a punter who threw once
        wrow(g1, "G8", "Late", "LB"),                        # a linebacker...
        wrow(g2, "G8", "Late", "LB", targets=1),             # ...thrown to in week 2
        wrow("2024_19_AAA_BBB", "G1", "Rec One", "WR", stype="POST", targets=9),
    ])
    snaps = pd.DataFrame([
        srow(g1, "P1", "Rec One", "WR", 50),
        srow(g1, "P2", "Rec Two", "TE", 20),
        srow(g2, "P1", "Rec One", "WR", 48),
        srow(g2, "P2", "Rec Two", "FB", 12),                 # active, no stat row
        srow(g3, "P2", "Rec Two", "TE", 9),                  # again
        srow(g1, "P3", "Snap Only", "FB", 7),                # never has a stat row
        srow(g1, "P7", "Punter", "P", 1),
        srow(g2, "P7", "Punter", "P", 1),                    # on the field, no stat row
        srow(g1, "PX", "No Id", "WR", 11),                   # no id to join on
        srow(g1, "PAMB", "Two Men", "RB", 30),               # one PFR id, two players
        srow("2024_19_AAA_BBB", "P1", "Rec One", "WR", 60, gtype="POST"),
    ])
    rosters = pd.DataFrame({"gsis_id": ["G1", "G2", "G3", "GA", "GB", "G9", "G7"],
                            "pfr_id": ["P1", "P2", "P3", "PAMB", "PAMB", None,
                                       "P7"]})

    def play(game, order, team, passer, stype="REG"):
        return dict(game_id=game, season_type=stype, posteam=team,
                    order_sequence=order, passer_player_id=passer)

    weekly = pd.concat([weekly, pd.DataFrame([
        wrow(g1, "Q1", "Starter", "QB", attempts=20),
        wrow(g1, "Q2", "Backup", "QB", attempts=9),
        wrow(g2, "Q1", "Starter", "QB", attempts=3),
        wrow(g2, "Q2", "Backup", "QB", attempts=25),
        wrow(g3, "Q2", "Backup", "QB", attempts=30),
        wrow(g1, "Q3", "Other Side", "QB", team="BBB", opp="AAA", attempts=30),
        wrow("2024_19_AAA_BBB", "Q2", "Backup", "QB", stype="POST", attempts=30),
    ])], ignore_index=True)
    pbp = pd.DataFrame([
        play(g1, 5, "AAA", "G1"),          # a receiver throws the first pass
        play(g1, 9, "AAA", "Q1"),          # ...the quarterback the second
        play(g1, 30, "AAA", "Q2"),
        play(g1, 2, "BBB", "Q3"),
        play(g1, 1, "AAA", None),          # a run: no passer
        play(g2, 40, "AAA", "Q2"),         # listed out of order
        play(g2, 7, "AAA", "Q1"),          # he started, and left
        play(g3, 3, None, "Q2"),           # no team on the play
        play("2024_19_AAA_BBB", 1, "AAA", "Q2", stype="POST"),
    ])
    f = fs.build_frame(weekly, snaps, rosters, pbp)
    starts = {(r.game_id, r.player_id) for r in f.itertuples() if r.qb_start}
    chk("the starting quarterback is the one behind the team's first pass",
        (g1, "Q1") in starts and (g1, "Q3") in starts and (g1, "Q2") not in starts,
        sorted(starts))
    chk("...by the order of play, not the order of the rows",
        (g2, "Q1") in starts and (g2, "Q2") not in starts)
    chk("...and a receiver who threw first is not the starting quarterback",
        (g1, "G1") not in starts)
    chk("a team-game with no usable pass play has no starter, not a guess",
        not any(g == g3 for g, _ in starts) and len(starts) == 3)
    chk("the report counts team-games and those with a starter",
        f.attrs["report"]["team_games"] == 4
        and f.attrs["report"]["team_games_with_a_starting_qb"] == 3,
        f.attrs["report"])
    chk("a missing play-by-play column is named",
        raises(lambda: fs.build_frame(weekly, snaps, rosters,
                                      pbp.drop(columns=["order_sequence"])),
               ValueError, "order_sequence"))
    f = f[~f.player_id.isin(["Q1", "Q2", "Q3"])].reset_index(drop=True)
    key = {(r.game_id, r.player_id): r for r in f.itertuples()}

    z = key.get((g2, "G2"))
    chk("active with no stat row is in the frame", z is not None)
    chk("...as a zero, and marked as having no stat row",
        z is not None and z.targets == 0 and not z.has_stats and z.has_snaps)
    chk("a player with neither a snap row nor a stat row is absent",
        (g3, "G1") not in key)
    chk("a stat row with no snap row still counts as played",
        (g1, "G9") in key and not key[(g1, "G9")].has_snaps)
    # two rows have no usable id: "No Id", and the one whose id names two men
    chk("a snap row with no usable id is left out and counted",
        "No Id" not in set(f.name)
        and f.attrs["report"]["skill_snap_rows_unplaced"] == 2
        and f.attrs["report"]["skill_snap_rows"] == 8,
        f.attrs["report"])
    chk("a PFR id naming two players is dropped, not guessed",
        not ({"GA", "GB"} & set(f.player_id))
        and f.attrs["report"]["ambiguous_pfr_ids"] == 1)
    chk("postseason is not in the frame", f.week.max() == 3 and len(f) == 11,
        f"{len(f)} rows, newest week {f.week.max()}")
    a = key[(g1, "G1")]
    chk("anytime TD is rushing plus receiving", a.anytime_tds == 2)
    chk("...and a passing TD is not one", a.passing_tds == 2 and a.anytime_tds == 2)
    chk("position is the weekly label when the game has one",
        key[(g1, "G2")].position == "TE")
    chk("a snap-only game takes his EARLIER weekly label, not the snap table's",
        key[(g2, "G2")].position == "TE", key[(g2, "G2")].position)
    chk("with no earlier weekly label it is the snap table's",
        key[(g1, "G3")].position == "FB")
    order = list(zip(f.player_id, f.t))
    chk("the frame is sorted by player, then week, across the whole frame",
        order == sorted(order) and f.player_id.nunique() > 3
        and list(f[f.player_id == "G2"].t) == [202401, 202402, 202403])
    chk("a defender who was thrown to is carried from then on", (g2, "G9") in key)
    chk("...but not for the games BEFORE his first target",
        (g2, "G8") in key and (g1, "G8") not in key)
    chk("the snap table's own label is kept beside the position",
        key[(g2, "G2")].snap_position == "FB" and key[(g2, "G2")].position == "TE")

    dup = pd.concat([weekly, weekly.iloc[[0]]], ignore_index=True)
    chk("two weekly rows for one player-game are refused",
        raises(lambda: fs.build_frame(dup, snaps, rosters, pbp), ValueError,
               "two rows"))
    chk("a missing column is named",
        raises(lambda: fs.build_frame(weekly.drop(columns=["targets"]), snaps,
                                      rosters, pbp), ValueError, "targets"))
    chk("...in the snap table too",
        raises(lambda: fs.build_frame(weekly, snaps.drop(columns=["st_snaps"]),
                                      rosters, pbp), ValueError, "st_snaps"))
    full = fs.build_frame(weekly[~weekly.player_id.isin(["Q1", "Q2", "Q3"])],
                          snaps, rosters, pbp)
    rep = full.attrs["report"]
    f = full
    # skill rows with an offensive snap: G1 x2, G2 x3, G3 x1 = 6; no stat row
    # among them: G2 wk2, G2 wk3, G3 wk1 = 3. The punter would make it 4 of 8.
    chk("the share on the field with no stat row is counted over skill "
        "positions", near(rep["share_on_field_no_stat_row"], 3 / 6)
        and rep["skill_player_games"] == 6 and rep["player_games"] == 11, rep)
    text = fs.describe_frame(f)
    chk("describe_frame states the share, and that they are graded as zeros",
        "50.0% have no stat row" in text and "graded as zeros" in text
        and "6 active player-games" in text
        and "3 of them have no stat row" in text
        and "starting quarterback was found for 0 of 3 team-games" in text, text)
    bp = rep["share_on_field_no_stat_row_by_position"]
    # on the field: WR G1 x2 (both with stats); TE G2 x3 (2 without); FB G3 x1
    chk("...and the share by position",
        near(bp["WR"], 0.0) and near(bp["TE"], 2 / 3) and near(bp["FB"], 1.0)
        and "P" not in bp, bp)


# ---------------------------------------------------------------------------
@section("2. History — the only thing a projector may read")
def _():
    f = league()
    T = tkey(2024, 4)
    h = History(f[f.t < T], T)
    chk("a row from the week being projected is refused",
        raises(lambda: History(f[f.t <= T], T), LeakError, "that week or later"))
    chk("...and so is a later one",
        raises(lambda: History(f, tkey(2024, 2)), LeakError))
    chk("the refusal says how many rows",
        raises(lambda: History(f[f.t <= T], T), LeakError,
               f"{int((f.t == T).sum())} row(s)"))
    v = h.values("AAA_WR1", "targets")
    chk("a log is oldest first", list(v) == [6, 8, 4, 10, 6, 8, 5, 7, 9], list(v))
    chk("min_season keeps that season on",
        list(h.values("AAA_WR1", "targets", min_season=2024)) == [5, 7, 9])
    chk("an unknown player has an empty log, not an error",
        len(h.values("NOBODY", "targets")) == 0 and h.last_week("NOBODY") is None)
    chk("his newest game is named", h.last_week("AAA_WR1") == tkey(2024, 3))
    fa = f.copy()
    fa.attrs["report"] = {"player_games": 123}
    chk("nothing rides along on the history's frame",
        History(fa[fa.t < T], T).frame.attrs == {})
    chk("the team's last starting quarterback is named",
        h.last_starting_qb("AAA") == "AAA_QB" and h.last_starting_qb("ZZZ") is None)
    sw = league(drop={(2024, 3, "AAA_QB")},
                extra=[row(2024, 3, "AAA", "BBB", "AAA_FILL", "QB", qb_start=True,
                           attempts=30)])
    chk("...from its NEWEST game, whoever started the ones before",
        History(sw[sw.t < T], T).last_starting_qb("AAA") == "AAA_FILL")
    nost = league(drop={(2024, 3, "AAA_QB")})
    chk("...and nobody if that game has no starter on file",
        History(nost[nost.t < T], T).last_starting_qb("AAA") is None)

    # A team that sat out a week, and a player who left it.
    g = league(drop={(2024, 3, "AAA_WR2"), (2024, 2, "AAA_WR2"),
                     (2024, 1, "AAA_WR2"), (2023, 6, "AAA_WR2"),
                     (2024, 3, "CCC_TE")},
               extra=[row(2024, 5, "AAA", "CCC", "AAA_QB", "QB", attempts=30)])
    h2 = History(g[g.t < T], T)
    recent = h2.team_recent_players("AAA", 4)
    chk("a player active in the team's last four games is recent",
        "AAA_WR1" in recent)
    chk("one whose last game for it was five games back is not",
        "AAA_WR2" not in recent, recent)
    chk("...but is with a longer look-back",
        "AAA_WR2" in h2.team_recent_players("AAA", 5))
    chk("games missed counts the team's games since his newest",
        h2.team_games_missed("AAA_WR2", "AAA") == 4
        and h2.team_games_missed("CCC_TE", "CCC") == 1
        and h2.team_games_missed("AAA_WR1", "AAA") == 0)
    chk("a player with no earlier game has no count, not a zero",
        h2.team_games_missed("NOBODY", "AAA") is None)
    chk("the team's weeks are its own",
        list(h2.team_weeks("AAA")) == [202301, 202302, 202303, 202304, 202305,
                                       202306, 202401, 202402, 202403])
    # A bye: BBB has no week-2 game in 2024; its player missed nothing.
    bye = f[~((f.t == 202402) & f.team.isin(["AAA", "BBB"]))]
    hb = History(bye[bye.t < T], T)
    chk("a bye is not a missed game",
        hb.team_games_missed("BBB_WR1", "BBB") == 0
        and 202402 not in set(hb.team_weeks("BBB")))


# ---------------------------------------------------------------------------
@section("3. slates — identity, and nothing that happened")
def _():
    f = league(extra=[row(2024, 4, "AAA", "BBB", "NEWMAN", "WR", targets=9,
                          snap_position="TE"),
                      row(2024, 1, "AAA", "BBB", "SWITCH", "RB", carries=3),
                      row(2024, 2, "AAA", "BBB", "SWITCH", "WR", targets=3),
                      row(2024, 3, "AAA", "BBB", "SWITCH", "WR", targets=3),
                      row(2024, 4, "AAA", "BBB", "SWITCH", "TE", targets=3),
                      row(2024, 4, "AAA", "BBB", "STATONLY", "WR", targets=1,
                          snap_position=float("nan")),
                      row(2024, 4, "AAA", "BBB", "HALFBACK", "RB", carries=2,
                          snap_position="HB"),
                      row(2024, 4, "AAA", "BBB", "NOLABEL", "QB", attempts=21,
                          snap_position=""),
                      # a lineman's first touch: in the frame, not on the slate
                      row(2024, 4, "AAA", "BBB", "TACKLE", "OT", targets=1,
                          snap_position="T"),
                      # a cornerback who has been thrown to before
                      row(2024, 3, "AAA", "BBB", "CORNER", "CB", targets=2),
                      row(2024, 4, "AAA", "BBB", "CORNER", "CB", targets=2),
                      # a quarterback who starts today in place of the regular
                      row(2024, 4, "BBB", "AAA", "BBB_SUB", "QB", qb_start=True,
                          attempts=28),
                      # last played for AAA five of its games back
                      row(2023, 5, "AAA", "BBB", "LONGAGO", "WR", targets=5)],
               drop={(2024, 4, "AAA_WR2"), (2024, 4, "BBB_QB")})
    f.attrs["report"] = {"player_games": 123}
    T = tkey(2024, 4)
    h = History(f[f.t < T], T)
    a = fs.slate_active(f, h)
    b = fs.slate_candidates(f, h)
    chk("slate A carries identity columns only, with no active flag",
        list(a.columns) == list(fs.SLATE_COLS), list(a.columns))
    chk("...and nothing rides along on it", a.attrs == {} and b.attrs == {})
    riding = a.copy()
    riding.attrs["report"] = {"player_games": 123}
    chk("a slate with something riding along is refused",
        raises(lambda: fs.check_slate(riding), LeakError, "attrs"))
    pa = dict(zip(a.player_id, a.position))
    chk("on A his position is the one he had going in, not today's label",
        pa["SWITCH"] == "WR", pa["SWITCH"])
    chk("a first-game player takes the snap table's label",
        pa["NEWMAN"] == "TE", pa["NEWMAN"])
    chk("...and the weekly one only when he has no snap row",
        pa["STATONLY"] == "WR", pa["STATONLY"])
    chk("the snap table's 'HB' is a running back, and an empty label is none",
        pa.get("HALFBACK") == "RB" and pa.get("NOLABEL") == "QB",
        (pa.get("HALFBACK"), pa.get("NOLABEL")))
    chk("a player at no skill position in his first game here is not on A",
        "TACKLE" not in pa and "TACKLE" in set(f[f.t == T].player_id))
    chk("...but one who has been here before is, whatever his label",
        pa.get("CORNER") == "CB")
    sa = dict(zip(a.player_id, a.starting_qb))
    sb = dict(zip(b.player_id, b.starting_qb))
    chk("on A the starting quarterback is who starts TODAY",
        bool(sa["BBB_SUB"]) and bool(sa["AAA_QB"]) and not bool(sa["AAA_WR1"]),
        (sa["BBB_SUB"], sa["AAA_QB"]))
    chk("...and exactly one a team", sum(sa.values()) == 4, sum(sa.values()))
    chk("on B it is who started the team's LAST game, since today's is not "
        "known", bool(sb["BBB_QB"]) and "BBB_SUB" not in sb
        and sum(sb.values()) == 4, sum(sb.values()))
    chk("by default B looks back four of the team's games, not five",
        "LONGAGO" not in set(b.player_id)
        and "LONGAGO" in set(fs.slate_candidates(f, h, lookback=5).player_id))
    chk("slate B carries identity columns only",
        list(b.columns) == list(fs.SLATE_COLS))
    chk("a slate with a result on it is refused",
        raises(lambda: fs.check_slate(a.assign(receptions=1)), LeakError,
               "receptions"))
    chk("a clean slate passes", not raises(lambda: fs.check_slate(a), Exception))
    on_a, on_b = set(a.player_id), set(b.player_id)
    chk("A is who was active that week", "NEWMAN" in on_a and "AAA_WR2" not in on_a)
    chk("B does not know a first-game player", "NEWMAN" not in on_b)
    chk("B still lists a regular who sat out", "AAA_WR2" in on_b)
    chk("B has every team that plays that week",
        set(b.team) == {"AAA", "BBB", "CCC", "DDD"})
    chk("B gives each player his team's game",
        set(b[b.team == "CCC"].game_id) == {gid(2024, 4, "CCC", "DDD")}
        and set(b[b.team == "CCC"].opponent) == {"DDD"})
    # B must be the same slate whatever happens in the week itself.
    f2 = f.copy()
    f2.loc[f2.t == T, ["targets", "carries", "attempts"]] = 77.0
    f2 = f2[~((f2.t == T) & (f2.player_id == "CCC_WR1"))]
    b2 = fs.slate_candidates(f2, History(f2[f2.t < T], T))
    chk("B is unchanged by who turns out to play, and by what they do",
        b.reset_index(drop=True).equals(b2.reset_index(drop=True)))
    # A team with no game that week is on neither slate.
    f3 = f[~((f.t == T) & f.team.isin(["CCC", "DDD"]))]
    b3 = fs.slate_candidates(f3, History(f3[f3.t < T], T))
    chk("a team on a bye is on neither slate",
        "CCC" not in set(b3.team)
        and "CCC" not in set(fs.slate_active(f3, History(f3[f3.t < T], T)).team))
    chk("B gives a player the position of his newest game, not his first",
        b[b.player_id == "SWITCH"].position.iloc[0] == "WR"
        and h.last_position("SWITCH") == "WR")


# ---------------------------------------------------------------------------
@section("4. stand-in lines and roles")
def _():
    r4 = fs.rungs(4.0)
    chk("a median of 4 makes five half-point rungs",
        [l for _, l in r4] == [2.5, 3.5, 4.5, 5.5, 6.5], r4)
    chk("...the middle one called main", dict(r4)[MAIN] == 4.5)
    r2 = fs.rungs(2.0)
    chk("rungs that land on one line are one rung",
        [l for _, l in r2] == [1.5, 2.5, 3.5], r2)
    chk("...and the main line survives the merge", dict(r2).get(MAIN) == 2.5, r2)
    chk("a median of zero is one line at 0.5", fs.rungs(0.0) == [(MAIN, 0.5)])
    chk("every line ends in .5", all(l % 1 == 0.5 for _, l in fs.rungs(47.3)))
    chk("a median below zero is one line, not an upside-down ladder",
        fs.rungs(-3.0) == [(MAIN, -2.5)] and fs.rungs(-0.5) == [(MAIN, -0.5)])
    chk("rungs come lowest first",
        [l for _, l in fs.rungs(50.0)] == sorted(l for _, l in fs.rungs(50.0))
        and [l for _, l in fs.rungs(50.0)] == [30.5, 40.5, 50.5, 62.5, 80.5])

    f = league(extra=[
        # three games only: no role and no line
        *[row(2024, w, "AAA", "BBB", "THREE", "WR", targets=9) for w in (1, 2, 3)],
        # median targets exactly on the floor, and just under it
        *[row(2024, w, "AAA", "BBB", "ONFLOOR", "WR", targets=t)
          for w, t in zip((1, 2, 3), (3, 3, 9))],
        row(2023, 6, "AAA", "BBB", "ONFLOOR", "WR", targets=1),
        *[row(2024, w, "AAA", "BBB", "UNDER", "WR", targets=t)
          for w, t in zip((1, 2, 3), (2, 3, 9))],
        row(2023, 6, "AAA", "BBB", "UNDER", "WR", targets=2),
        # a cornerback who is thrown to
        *[row(s, w, "AAA", "BBB", "CORNER", "CB", targets=6, receptions=4,
              receiving_yards=50)
          for s, w in ((2023, 5), (2023, 6), (2024, 1), (2024, 2), (2024, 3))],
        # a long history: only the last eight games of this season and last count
        *[row(2022, w, "AAA", "BBB", "AAA_WR1", "WR", targets=40)
          for w in (1, 2, 3)],
    ])
    T = tkey(2024, 4)
    h = History(f[f.t < T], T)
    win = fs.line_window(h, "AAA_WR1")
    chk("the line window is his last eight games",
        list(h.col["targets"][win]) == [8, 4, 10, 6, 8, 5, 7, 9],
        list(h.col["targets"][win]))
    f_old = f[~((f.player_id == "AAA_WR1") & (f.season == 2023))]
    h_old = History(f_old[f_old.t < T], T)
    chk("...from this season and last only",
        list(h_old.col["targets"][fs.line_window(h_old, "AAA_WR1")]) == [5, 7, 9])
    chk("the main line is the half point above that median",
        dict(fs.standin_lines(h, win, "targets"))[MAIN] == 7.5)
    chk("the ladder follows the median",
        [l for _, l in fs.standin_lines(h, win, "targets")]
        == [4.5, 6.5, 7.5, 9.5, 12.5])
    chk("a touchdown has one line, 0.5",
        fs.standin_lines(h, win, TD_STAT) == [(MAIN, 0.5)])
    w3 = fs.line_window(h, "THREE")
    chk("fewer than four games: no line", fs.standin_lines(h, w3, "targets") == [])
    chk("...and no role", not any(fs.roles(h, w3).values()))
    chk("a median exactly on the floor is a role",
        fs.roles(h, fs.line_window(h, "ONFLOOR"))["recv"] is True)
    chk("a median just under it is not",
        fs.roles(h, fs.line_window(h, "UNDER"))["recv"] is False)
    rc = fs.roles(h, fs.line_window(h, "CORNER"))
    chk("a role is read from targets, not from the position label",
        rc["recv"] and not rc["rush"] and not rc["pass"])
    chk("a receiving or rushing role is a touchdown role",
        rc["td"] and fs.roles(h, fs.line_window(h, "AAA_RB"))["td"]
        and not fs.roles(h, fs.line_window(h, "AAA_TE"))["td"])
    for fam, stat, floor in (("rush", "carries", 5), ("pass", "attempts", 20)):
        g2 = league(extra=[
            *[row(2024, w, "AAA", "BBB", "ON", "RB", **{stat: v})
              for w, v in zip((1, 2, 3), (floor, floor, floor + 9))],
            row(2023, 6, "AAA", "BBB", "ON", "RB", **{stat: 1}),
            *[row(2024, w, "AAA", "BBB", "BELOW", "RB", **{stat: v})
              for w, v in zip((1, 2, 3), (floor - 1, floor, floor + 9))],
            row(2023, 6, "AAA", "BBB", "BELOW", "RB", **{stat: 1})])
        hh = History(g2[g2.t < T], T)
        chk(f"the {fam} floor is {floor}: a median on it is a role, half a "
            f"unit under is not",
            fs.roles(hh, fs.line_window(hh, "ON"))[fam] is True
            and fs.roles(hh, fs.line_window(hh, "BELOW"))[fam] is False)
    rq = fs.roles(h, fs.line_window(h, "AAA_QB"))
    chk("a quarterback has a passing role and, at two carries, no rushing one",
        rq["pass"] and not rq["rush"] and not rq["td"])


# ---------------------------------------------------------------------------
@section("5. the yardsticks, by hand")
def _():
    f = league(extra=[
        # active with no stat row in week 2 (a true zero), nothing in week 3
        row(2024, 1, "AAA", "BBB", "ZERO", "WR", targets=6, receptions=4,
            receiving_yards=44),
        row(2024, 2, "AAA", "BBB", "ZERO", "WR", has_stats=False),
        row(2023, 5, "AAA", "BBB", "ZERO", "WR", targets=2, receptions=2,
            receiving_yards=20),
        row(2023, 6, "AAA", "BBB", "ZERO", "WR", targets=0, receptions=0,
            receiving_yards=0),          # a stat row with no target
        row(2023, 4, "AAA", "BBB", "ZERO", "WR", targets=4, receptions=3,
            receiving_yards=30),
        row(2023, 3, "AAA", "BBB", "ZERO", "WR", targets=5, receptions=5,
            receiving_yards=60),
        row(2024, 1, "AAA", "BBB", "TWO", "WR", targets=3, receptions=2,
            receiving_yards=30),
        row(2024, 2, "AAA", "BBB", "TWO", "WR", targets=4, receptions=3,
            receiving_yards=50),
    ])
    T = tkey(2024, 4)
    h = History(f[f.t < T], T)
    one = pd.DataFrame([dict(season=2024, week=4, game_id="g", team="AAA",
                             opponent="BBB", player_id=p, name=p, position="WR")
                        for p in ("AAA_WR1", "ZERO", "NOBODY", "TWO")])
    s = fs.SeasonAverage().project(h, one)
    l4 = fs.LastFour().project(h, one)
    gm = fs.GameLogModel().project(h, one)
    chk("season average is this season only", near(s.point(0, "targets"), 7.0),
        s.point(0, "targets"))
    chk("...and counts an active game with no stat row as a zero",
        near(s.point(1, "receiving_yards"), 22.0), s.point(1, "receiving_yards"))
    chk("its probability is the share over the line, half a game toward 50%",
        near(s.p_over(0, "targets", 7.5), 1.5 / 4), s.p_over(0, "targets", 7.5))
    chk("no game this season: no projection, not a zero",
        math.isnan(s.point(2, "targets")) and math.isnan(s.p_over(2, "targets", 1.5)))
    chk("last four reaches back into last season",
        near(l4.point(0, "targets"), (8 + 5 + 7 + 9) / 4), l4.point(0, "targets"))
    chk("...and its probability is over those four",
        near(l4.p_over(0, "targets", 7.5), 2.5 / 5))
    chk("hit_share never says 0% or 100%",
        near(fs.hit_share(np.array([9.0]), 4.5), 0.75)
        and near(fs.hit_share(np.array([1.0]), 4.5), 0.25))
    chk("hit_share of no games is no answer, not a coin flip",
        math.isnan(fs.hit_share(np.array([]), 4.5)))
    chk("the blend drops a missing game, as the engine does",
        near(fs.gamelog_blend(np.array([2.0, float("nan"), 8.0, 5.0, 9.0]), 4.5),
             fs.gamelog_blend(np.array([2.0, 8.0, 5.0, 9.0]), 4.5), 1e-12)
        and math.isnan(fs.gamelog_blend(np.array([5.0, float("nan"), 6.0]), 4.5)))
    chk("hit_share counts strictly over the line: landing on it is not over",
        near(fs.hit_share(np.array([4.0, 5.0, 5.0]), 5.0), 0.5 / 4)
        and near(fs.hit_share(np.array([4.0, 5.0, 5.0]), 4.5), 2.5 / 4))
    lg = fs.GameLogModel().log(h, "ZERO", "receiving_yards")
    chk("the game-log model drops a game with no stat row and one with no "
        "target", list(lg) == [60, 30, 20, 44], list(lg))
    chk("...its single number is the median of that log",
        near(gm.point(1, "receiving_yards"), 37.0))
    chk("...and it needs three games",
        math.isnan(fs.gamelog_blend(np.array([5.0, 6.0]), 4.5))
        and not math.isnan(fs.gamelog_blend(np.array([5.0, 6.0, 7.0]), 4.5)))
    # TWO has two qualifying games: a median exists, and must not be given.
    chk("...for its single number too, not only its probability",
        list(fs.GameLogModel().log(h, "TWO", "receiving_yards")) == [30, 50]
        and math.isnan(gm.point(3, "receiving_yards"))
        and math.isnan(gm.p_over(3, "receiving_yards", 20.5))
        and near(s.point(3, "receiving_yards"), 40.0))
    x = np.array([2.0, 8.0, 5.0, 9.0])
    w = 0.5 ** (np.array([3.0, 2.0, 1.0, 0.0]) / 6.0)
    emp, rec = 0.75, float((w * (x >= 4.5)).sum() / w.sum())
    para = 1 - fs._NORM.cdf((4.5 - x.mean()) / x.std(ddof=1))
    chk("the blend is 45% empirical, 25% normal fit, 30% recency-weighted",
        near(fs.gamelog_blend(x, 4.5), 0.45 * emp + 0.25 * para + 0.30 * rec, 1e-12),
        fs.gamelog_blend(x, 4.5))
    chk("a flat log does not divide by zero",
        near(fs.gamelog_blend(np.array([5.0, 5.0, 5.0]), 4.5), 0.99)
        and near(fs.gamelog_blend(np.array([5.0, 5.0, 5.0]), 5.5), 0.01))
    chk("the three yardsticks have three names",
        [p.name for p in fs.yardsticks()] == ["season_avg", "last4_avg",
                                               "gamelog_model"])
    chk("none of them claims to use the active list",
        not any(p.uses_actives for p in fs.yardsticks()))


# ---------------------------------------------------------------------------
REAL = {}


@section("6. the copied model matches the engine's, on real logs")
def _():
    import ff_data, ff_props
    years = [2023, 2024, 2025, 2026]
    frame = fs.load_frame(years)
    REAL["frame"] = frame
    # The newest week on file may be half-played; the one before it is not.
    T = sorted(int(t) for t in frame.t.unique())[-2]
    S = T // 100
    h = History(frame[frame.t < T], T)
    wk = ff_data.load_weekly([S - 1, S])
    wk = wk[(wk.season_type == "REG") & (wk.season * 100 + wk.week < T)]
    wk = ff_props.add_shares(wk)
    names = wk.groupby("player_display_name").player_id.nunique()
    unique = set(names[names == 1].index)
    cur = frame[(frame.t == T) & frame.position.isin(["QB", "RB", "WR", "TE"])
                & frame.has_stats & frame.name.isin(unique)]
    cur = cur.sort_values("player_id").iloc[::6]          # every sixth, fixed
    model = fs.GameLogModel()
    logs = probs = 0
    bad_log, bad_p = [], []
    for r in cur.itertuples():
        for stat in [s_ for s_ in fs.STATS if s_ != TD_STAT]:
            mine = model.log(h, r.player_id, stat)
            try:
                theirs = ff_props.player_series(wk, r.name, stat)
            except LookupError:
                theirs = None
            ref = (np.array([]) if theirs is None
                   else theirs[stat].to_numpy(dtype=float))
            logs += 1
            if len(mine) != len(ref) or not np.array_equal(mine, ref):
                bad_log.append((r.name, stat, len(mine), len(ref)))
                continue
            if len(mine) < 3:
                continue
            for line in sorted({math.floor(np.median(mine) * k) + 0.5
                                for k in (0.6, 1.0, 1.6)}):
                probs += 1
                want = ff_props.threshold_prob(theirs, line, n_boot=1).blended
                got = fs.gamelog_blend(mine, line)
                if not abs(want - got) < 1e-9:
                    bad_p.append((r.name, stat, line, want, got))
    chk("enough real logs were compared to mean something",
        logs >= 300 and probs >= 400, f"{logs} logs, {probs} probabilities")
    import ff_props as _fp
    no_td = _fp.player_series(wk, cur.name.iloc[0], TD_STAT)
    chk("the engine builds no touchdown log, so that stat is not compared",
        TD_STAT not in no_td.columns
        and raises(lambda: _fp.threshold_prob(no_td, 0.5, TD_STAT, n_boot=1),
                   KeyError))
    chk("my game log is ff_props.player_series' game log", not bad_log,
        f"{len(bad_log)} differ: {bad_log[:3]}")
    chk("gamelog_blend is ff_props.threshold_prob(...).blended", not bad_p,
        f"{len(bad_p)} differ: {bad_p[:3]}")


# ---------------------------------------------------------------------------
@section("7. the walk-forward, on a league worked by hand")
def _():
    f = league(extra=[row(2024, 4, "AAA", "BBB", "NEWMAN", "WR", targets=9),
                      # with AAA for three weeks, then against it for BBB
                      *[row(2024, w, "AAA", "BBB", "MOVED", "WR", targets=7,
                            receptions=5, receiving_yards=60) for w in (1, 2, 3)],
                      row(2023, 6, "AAA", "BBB", "MOVED", "WR", targets=7,
                          receptions=5, receiving_yards=60),
                      row(2024, 4, "BBB", "AAA", "MOVED", "WR", targets=8,
                          receptions=6, receiving_yards=70)],
               drop={(2024, 4, "CCC_WR1")})
    weeks = fs.test_weeks(f, through=202404)
    chk("2023 is warm-up and is not graded",
        weeks == [202401, 202402, 202403, 202404], weeks)
    chk("`through` stops at the week given",
        fs.test_weeks(f, through=202402) == [202401, 202402])
    chk("with no `through`, the newest week on file is left out",
        fs.test_weeks(f) == [202401, 202402, 202403])
    r_thru = fs.walk_forward(f, [Const()], through=202402)
    r_none = fs.walk_forward(f, [Const()])
    chk("walk_forward passes `through` on, and leaves the newest week out "
        "without it",
        r_thru.weeks == [202401, 202402]
        and r_none.weeks == [202401, 202402, 202403])
    chk("a week with no game on file is refused, not run empty",
        raises(lambda: fs.walk_forward(f, [Const()], weeks=[202404, 202409]),
               ValueError, "202409"))
    twice = pd.concat([f, f[f.t == 202404].iloc[[0]]], ignore_index=True)
    chk("a repeated player-game row is refused, not graded twice",
        raises(lambda: fs.walk_forward(twice, [Const()], weeks=[202404]),
               ValueError, "repeated"))
    chk("a frame missing a column is refused by name",
        raises(lambda: fs.walk_forward(f.drop(columns=["snap_position"]),
                                       [Const()], weeks=[202404]),
               ValueError, "snap_position"))
    hole = f.copy()
    hole.loc[hole.index[3], "receiving_yards"] = float("nan")
    chk("a missing stat is refused, not graded as a miss",
        raises(lambda: fs.walk_forward(hole, [Const()], weeks=[202404]),
               ValueError, "receiving_yards"))
    bad_t = f.copy()
    bad_t.loc[bad_t.index[0], "t"] += 1
    chk("a week key that disagrees with season and week is refused",
        raises(lambda: fs.walk_forward(bad_t, [Const()], weeks=[202404]),
               ValueError, "week key"))
    run = fs.walk_forward(f, fs.yardsticks(), weeks=[202404], keep_slates=True)
    L, P = run.legs, run.points
    me = L[(L.version == "A") & (L.player_id == "AAA_WR1") & (L.stat == "targets")]
    chk("the hand-worked receiver has his five rungs",
        list(me.line) == [4.5, 6.5, 7.5, 9.5, 12.5], list(me.line))
    m = me[me.rung == MAIN].iloc[0]
    chk("every rung carries his main line",
        (me.main_line == 7.5).all()
        and (L[L.stat == TD_STAT].main_line == 0.5).all()
        and len(L[L.stat == TD_STAT]) > 0)
    chk("his result is the graded week's, and went under 7.5",
        m.actual == 3.0 and not bool(m.over), (m.actual, m.over))
    chk("season average said 37.5% over", near(m.p_season_avg, 0.375), m.p_season_avg)
    chk("last four said 50% over", near(m.p_last4_avg, 0.5), m.p_last4_avg)
    chk("the game-log model's number is the copied blend on his log",
        near(m.p_gamelog_model,
             fs.gamelog_blend(np.array([6, 8, 4, 10, 6, 8, 5, 7, 9.0]), 7.5)),
        m.p_gamelog_model)
    rc = L[(L.version == "A") & (L.player_id == "AAA_WR1") & (L.stat == "receptions")]
    # receptions are targets less two: window 6 2 8 4 6 3 5 7, median 5.5
    chk("each stat's ladder is built on that stat",
        list(rc.line) == [3.5, 4.5, 5.5, 6.5, 8.5]
        and rc[rc.rung == MAIN].line.iloc[0] == 5.5, list(rc.line))
    la = L[L.version == "A"]
    chk("the result is the actual against the line, both ways round",
        (la.over.astype(bool) == (la.actual > la.line)).all()
        and la.over.astype(bool).any() and not la.over.astype(bool).all())
    pm = P[(P.version == "A") & (P.player_id == "AAA_WR1") & (P.stat == "targets")].iloc[0]
    chk("the point projections are the hand values",
        near(pm.pt_season_avg, 7.0) and near(pm.pt_last4_avg, 7.25)
        and near(pm.pt_gamelog_model, 7.0), pm.to_dict())
    chk("the row says when its newest input is",
        pm.newest_input == 202403 and pm.team_games_missed == 0)
    te = "AAA_TE"
    chk("a player with no role has a projection but no line",
        len(P[(P.player_id == te) & (P.version == "A")]) > 0
        and len(L[L.player_id == te]) == 0)
    chk("...and is marked as having no role",
        not P[(P.player_id == te) & (P.stat == "targets")].role.any())
    chk("a quarterback is given no receiving line",
        "receptions" not in set(P[P.player_id == "AAA_QB"].stat)
        and "passing_yards" in set(P[P.player_id == "AAA_QB"].stat))
    pa = P[P.version == "A"]
    qr = pa[(pa.player_id == "AAA_QB") & (pa.stat == "rushing_yards")]
    chk("a quarterback with no rushing role still gets a rushing projection",
        len(qr) == 1 and not bool(qr.role.iloc[0])
        and TD_STAT not in set(pa[pa.player_id == "AAA_QB"].stat))
    chk("a tight end with no role gets a touchdown projection and no "
        "rushing one",
        TD_STAT in set(pa[pa.player_id == te].stat)
        and "carries" not in set(pa[pa.player_id == te].stat))
    chk("a back gets rushing and receiving projections and no passing one",
        {"carries", "receptions", TD_STAT} <= set(pa[pa.player_id == "AAA_RB"].stat)
        and "attempts" not in set(pa[pa.player_id == "AAA_RB"].stat))
    nm = P[(P.player_id == "NEWMAN") & (P.version == "A") & (P.stat == "targets")]
    chk("a first-game player is on A with no projection, not a zero",
        len(nm) == 1 and math.isnan(nm.iloc[0].pt_season_avg)
        and nm.iloc[0].actual == 9.0)
    chk("...and is not on B", len(P[(P.player_id == "NEWMAN") & (P.version == "B")]) == 0)
    out = P[(P.player_id == "CCC_WR1")]
    chk("a regular who sat out is on B only", set(out.version) == {"B"})
    chk("...marked not played, with no result invented",
        not out.played.any() and out.actual.isna().all())
    ol = L[L.player_id == "CCC_WR1"]
    chk("...and his legs have no over/under result",
        len(ol) > 0 and all(v is None for v in ol.over))
    mv = P[(P.player_id == "MOVED") & (P.stat == "targets")]
    old = mv[(mv.version == "B") & (mv.team == "AAA")]
    chk("a player now on the other side did not play for the team he left",
        len(old) == 1 and not bool(old.played.iloc[0])
        and math.isnan(old.actual.iloc[0]), mv[["version", "team", "played"]].values.tolist())
    chk("...and did play for the one he joined",
        list(mv[mv.version == "A"].team) == ["BBB"]
        and mv[mv.version == "A"].actual.iloc[0] == 8.0)
    chk("everyone on A played", P[P.version == "A"].played.all())
    chk("one row per version, player-game and stat",
        not P.duplicated(["version", "game_id", "team", "player_id", "stat"]).any())
    chk("the slates are kept when asked for",
        set(run.slates[202404]) == {"A", "B"})
    chk("describe counts the games", "2 games" in run.describe(), run.describe())

    chk("a probability above 1 is refused, and names the projector",
        raises(lambda: fs.walk_forward(f, [Const("bad", p=1.2)], weeks=[202404]),
               ValueError, "bad"))
    chk("...so is a negative one",
        raises(lambda: fs.walk_forward(f, [Const("bad", p=-0.1)], weeks=[202404]),
               ValueError, "probability"))
    chk("an infinite projection is refused",
        raises(lambda: fs.walk_forward(f, [Const("bad", point=float("inf"))],
                                       weeks=[202404]), ValueError, "bad"))
    chk("NaN is allowed: it means no projection",
        not raises(lambda: fs.walk_forward(
            f, [Const("ok", point=float("nan"), p=float("nan"))],
            weeks=[202404]), Exception))
    chk("two projectors with one name are refused",
        raises(lambda: fs.walk_forward(f, [Const("x"), Const("x")],
                                       weeks=[202404]), ValueError, "share a name"))
    # One more player active than had been playing, so the two slates differ
    # in size and a projector that counts them gives two answers.
    f21 = league(extra=[row(2024, 4, "AAA", "BBB", "NEWMAN", "WR", targets=9)])
    chk("a projector that reads the slate without saying so is refused",
        raises(lambda: fs.walk_forward(f21, [SlateSize(False)], weeks=[202404]),
               LeakError, "slate_size"))
    ok = fs.walk_forward(f21, [SlateSize(True)], weeks=[202404], keep_slates=True)
    chk("...and allowed once it says so",
        fs.version_gap(ok, "slate_size") > 0
        and len(ok.slates[202404]["A"]) == len(ok.slates[202404]["B"]) + 1)
    seen = []

    class Spy(Projector):
        name = "spy"

        def project(self, hist, slate):
            seen.append((list(slate.columns), dict(slate.attrs),
                         int(hist.frame.t.max()), dict(hist.frame.attrs)))
            slate["position"] = "XX"            # a projector may scribble
            return Const().project(hist, slate)

    fa = f.copy()
    fa.attrs["report"] = {"player_games": 123}
    spied = fs.walk_forward(fa, [Spy()], weeks=[202404], keep_slates=True)
    chk("a projector is handed identity columns and nothing else, twice a "
        "week", len(seen) == 2
        and all(c == list(fs.SLATE_COLS) and a == {} and ha == {}
                for c, a, _, ha in seen), seen)
    chk("...and a history that stops before the week", all(t < 202404 for _, _, t, _ in seen))
    chk("...and its own copy of the slate: scribbling on it changes nothing",
        "XX" not in set(spied.slates[202404]["A"].position)
        and "XX" not in set(spied.points.position))

    class PSize(Projector):
        """Its single number is fixed; only its PROBABILITY reads the slate."""
        name = "psize"

        def project(self, hist, slate):
            p = 0.5 + len(slate) / 1000.0

            class Q(Projection):
                def point(self, i, stat): return 1.0
                def p_over(self, i, stat, line): return p
            return Q()

    chk("reading the slate in a probability alone is caught too",
        raises(lambda: fs.walk_forward(f21, [PSize()], weeks=[202404]),
               LeakError, "psize"))
    first = fs.walk_forward(f, [SlateSize(False)], weeks=[202301])
    chk("where nothing could be compared the claim is NOT CHECKED, and says so",
        first.unverified == ["slate_size"]
        and "NOT CHECKED" in first.describe() and "slate_size" in first.describe()
        and fs.version_gap(first, "slate_size", counts=True) == (0, 0))
    blank = fs.walk_forward(f, [Const("blank", point=float("nan"),
                                      p=float("nan"))], weeks=[202404])
    chk("a blank beside a blank is not a comparison either",
        blank.unverified == ["blank"]
        and fs.version_gap(blank, "blank", counts=True) == (0, 0))
    chk("...and a checked run lists nobody",
        run.unverified == [] and "NOT CHECKED" not in run.describe()
        and fs.version_gap(run, "last4_avg", counts=True)[1] > 0)

    def bad_slate(frame, hist):
        out = real_slate(frame, hist)
        out["receptions"] = 1.0
        return out

    real_slate = fs.slate_active
    try:
        fs.slate_active = bad_slate
        refused = raises(lambda: fs.run_week(f, 202404, [Const()]), LeakError,
                         "receptions")
    finally:
        fs.slate_active = real_slate
    chk("every slate is checked before a projector sees it", refused)


# ---------------------------------------------------------------------------
def old_starter(team, opp, pid, starts_today=False):
    """A quarterback who started all of 2023 and has mopped up since: he has
    a starter's median and a rushing role, and has not started in 2024."""
    rows = [row(2023, w, team, opp, pid, "QB", attempts=35, completions=22,
                passing_yards=250, carries=6, rushing_yards=30)
            for w in range(1, 7)]
    rows += [row(2024, w, team, opp, pid, "QB", attempts=2, completions=1,
                 passing_yards=9, carries=6, rushing_yards=30)
             for w in (1, 2, 3)]
    rows.append(row(2024, 4, team, opp, pid, "QB", qb_start=starts_today,
                    attempts=30 if starts_today else 2, carries=6,
                    rushing_yards=30))
    return rows


@section("7b. one lined quarterback a team")
def _():
    T = 202404
    f = league(
        extra=[*old_starter("CCC", "DDD", "CCC_OLD"),
               # DDD: the regular is inactive and the old starter starts
               *old_starter("DDD", "CCC", "DDD_OLD", starts_today=True),
               # AAA: the regular missed week 3, a fill-in started it, and
               # the regular is back and starting today
               row(2024, 3, "AAA", "BBB", "AAA_FILL", "QB", qb_start=True,
                   attempts=30),
               row(2024, 4, "AAA", "BBB", "AAA_FILL", "QB", attempts=1),
               # BBB: a newcomer starts today; the regular mops up
               row(2024, 4, "BBB", "AAA", "BBB_ROOK", "QB", qb_start=True,
                   attempts=30),
               row(2024, 4, "BBB", "AAA", "BBB_QB", "QB", attempts=2)],
        drop={(2024, 4, "DDD_QB"), (2024, 3, "AAA_QB"), (2024, 4, "BBB_QB")})
    h = History(f[f.t < T], T)
    chk("the old starter still has a starter's median, and a rushing one",
        fs.roles(h, fs.line_window(h, "CCC_OLD"))["pass"]
        and fs.roles(h, fs.line_window(h, "CCC_OLD"))["rush"])
    run = fs.walk_forward(f, [Const()], weeks=[T])
    L, P = run.legs, run.points

    def lined(legs, version):
        v = legs[(legs.version == version) & (legs.stat == "attempts")]
        return {t: set(v[v.team == t].player_id)
                for t in ("AAA", "BBB", "CCC", "DDD")}

    la = lined(L, "A")
    chk("the man who starts today is the lined quarterback",
        la["CCC"] == {"CCC_QB"}, la)
    old = P[(P.version == "A") & (P.player_id == "CCC_OLD")]
    chk("a backup with a starter's median is given no line of any kind",
        len(L[(L.version == "A") & (L.player_id == "CCC_OLD")]) == 0
        and len(old) > 0 and not old.role.any()
        and "rushing_yards" in set(old.stat))
    chk("when the regular is inactive, whoever starts is lined",
        la["DDD"] == {"DDD_OLD"}, la["DDD"])
    chk("...and keeps his rushing line with it",
        "rushing_yards" in set(L[(L.version == "A")
                                 & (L.player_id == "DDD_OLD")].stat))
    chk("a starter back from a week out is lined, though another man "
        "started last week", la["AAA"] == {"AAA_QB"}, la["AAA"])
    no_snap = f[~((f.t == T) & (f.player_id == "AAA_FILL"))]
    chk("...and that does not turn on whether the fill-in took a snap today",
        lined(fs.walk_forward(no_snap, [Const()], weeks=[T]).legs, "A")["AAA"]
        == {"AAA_QB"})
    chk("a newcomer starting today has no line yet, and the man he "
        "replaced has none either", la["BBB"] == set(), la["BBB"])
    lb = lined(L, "B")
    db = L[(L.version == "B") & (L.team == "DDD") & (L.stat == "attempts")]
    chk("with the active list hidden, the line goes to whoever started the "
        "team's LAST game, played or not",
        lb["DDD"] == {"DDD_QB"} and not db.played.any()
        and lb["BBB"] == {"BBB_QB"} and lb["CCC"] == {"CCC_QB"}, lb)
    chk("...even where that was a fill-in with no line to give",
        lb["AAA"] == set(), lb["AAA"])
    chk("no team has two lined quarterbacks, in either version",
        (L[(L.stat == "attempts") & (L.rung == MAIN)]
         .groupby(["version", "game_id", "team"]).size() <= 1).all())
    wr = P[(P.version == "A") & (P.player_id == "AAA_WR1") & (P.stat == "targets")]
    chk("a receiver's role is untouched by any of it", bool(wr.role.iloc[0]))


# ---------------------------------------------------------------------------
class JointConst(Projector):
    """States its own chance that two legs both happen."""
    def __init__(self, name="sim", j=0.2):
        self.name, self._j = name, j
        self.asked = 0

    def project(self, hist, slate):
        o = self

        class P(Projection):
            def point(self, i, stat): return 1.0
            def p_over(self, i, stat, line): return 0.5

            def p_both(self, i, si, li, j, sj, lj):
                o.asked += 1
                return o._j
        return P()


class Echo(Projector):
    """Its joint is a record of exactly what it was asked."""
    name = "echo"

    def __init__(self):
        self.asked = []

    def project(self, hist, slate):
        o = self

        class P(Projection):
            def point(self, i, stat): return 1.0
            def p_over(self, i, stat, line): return 0.5

            def p_both(self, i, si, li, j, sj, lj):
                o.asked.append((i, si, li, j, sj, lj))
                # None for one pair in three: a blank, not the end of asking
                return None if len(o.asked) % 3 == 0 else len(o.asked) * 1e-5
        return P()


@section("7c. a projector's own chance that two legs both happen")
def _():
    # CORNER has a receiving role and a label no market side carries.
    f = league(extra=[row(s_, w, "AAA", "BBB", "CORNER", "CB", targets=6,
                          receptions=4, receiving_yards=50, receiving_tds=1)
                      for s_, w in ((2023, 5), (2023, 6), (2024, 1), (2024, 2),
                                    (2024, 3), (2024, 4))])
    T = 202404
    sim, plain = JointConst("sim", 0.2), Const("plain", p=0.5)
    run = fs.walk_forward(f, [plain, sim], weeks=[T])
    J = run.joints
    chk("a projector that states its own joint has it recorded",
        len(J) > 0 and (J.j_sim == 0.2).all())
    chk("...and one that does not is left blank, not guessed",
        J.j_plain.isna().all())
    sl = fs.side_legs(run, "sim")
    pr = fs.build_pairs(sl, run.joints)
    chk("every pair the report builds has that projector's joint",
        len(pr) == len(J) and pr.j_sim.notna().all() and len(pr) > 50,
        (len(pr), len(J)))
    chk("...and the pair is still priced by the product beside it",
        near(pr["product"].iloc[0], 0.25) and "j_sim" in pr.columns)
    chk("build_pairs without joints adds no column",
        "j_sim" not in fs.build_pairs(sl).columns)
    sc = fs.pair_score(pr, ["product", "j_sim"]).set_index("method")
    chk("its joint is scored on the same pairs as the product",
        sc.loc["j_sim", "n"] == len(pr)
        and near(sc.loc["j_sim", "brier"],
                 float(((0.2 - pr.both.astype(float)) ** 2).mean())))
    quiet = Const("quiet")
    only = fs.walk_forward(f, [quiet], weeks=[T])
    chk("with no such projector there are no joint rows at all",
        len(only.joints) == 0 and list(only.joints.columns)[-1] == "j_quiet")
    chk("a player whose label no side carries has a line and is in no pair",
        len(run.legs[(run.legs.player_id == "CORNER")
                     & (run.legs.stat == "receiving_yards")]) > 0
        and "CORNER" not in set(J.player_id_a) | set(J.player_id_b))
    echo = Echo()
    er = fs.walk_forward(f, [echo], weeks=[T], keep_slates=True)
    EJ = er.joints
    chk("a projector that states joints is asked about EVERY pair",
        len(echo.asked) == len(EJ) == len(J), (len(echo.asked), len(EJ)))
    chk("...and a None for one pair is a blank for that pair only",
        int(EJ.j_echo.isna().sum()) == len(EJ) // 3
        and EJ.j_echo.notna().sum() > 0)
    sl_a = er.slates[T]["A"]
    row_of = {p: i for i, p in enumerate(sl_a.player_id)}
    stat_of = {m[0]: m[2] for m in fs.market_sides()}
    la = er.legs[(er.legs.version == "A") & (er.legs.rung == MAIN)]
    main = {(r.player_id, r.stat): r.line for r in la.itertuples()}
    want = [(row_of[r.player_id_a], stat_of[r.side_a],
             main[(r.player_id_a, stat_of[r.side_a])],
             row_of[r.player_id_b], stat_of[r.side_b],
             main[(r.player_id_b, stat_of[r.side_b])])
            for r in EJ.itertuples()]
    chk("it is asked about exactly the two legs the row names: slate row, "
        "stat and main line of each", echo.asked == want,
        (echo.asked[:1], want[:1]))
    answered = [k + 1 for k in range(len(want)) if (k + 1) % 3]
    chk("...and each answer lands on the pair it was given for",
        np.allclose(EJ.j_echo.dropna().to_numpy(), np.array(answered) * 1e-5))
    pe = fs.build_pairs(fs.side_legs(er, "echo"), er.joints)
    se = fs.pair_score(pe, ["product", "j_echo"])
    chk("pair_score says how many pairs it could score",
        set(se.n) == {int(EJ.j_echo.notna().sum())} and len(pe) == len(EJ))
    chk("...and pair calibration leaves the blanks out",
        fs.pair_calibration(pe, "j_echo").n.sum() == int(EJ.j_echo.notna().sum()))
    chk("a joint outside 0 to 1 is refused, and names the projector",
        raises(lambda: fs.walk_forward(f, [JointConst("wild", 1.5)], weeks=[T]),
               ValueError, "wild"))
    chk("the sides are the correlation table's own",
        [m[0] for m in fs.market_sides()]
        == list(__import__("ff_correlation").SIDE_SPEC)
        and (("TD", ("QB", "RB", "WR", "TE"), TD_STAT, True) in fs.market_sides()))
    class Only(Projector):
        """Returns one kind of number and blanks for the other two."""
        def __init__(self, kind):
            self.name, self.kind = f"only_{kind}", kind

        def project(self, hist, slate):
            kind = self.kind
            nan = float("nan")

            class P(Projection):
                def point(self, i, stat): return 1.0 if kind == "point" else nan
                def p_over(self, i, stat, line): return 0.5 if kind == "prob" else nan

                def p_both(self, *a):
                    return 0.2 if kind == "joint" else None
            return P()

    class OnObject(Projector):
        name = "onobj"

        def project(self, hist, slate):
            inner = Const().project(hist, slate)
            inner.p_both = lambda *a: 0.3          # set on the object
            return inner

    oo = fs.walk_forward(f, [OnObject()], weeks=[T])
    chk("a joint method set on the object itself is asked too",
        len(oo.joints) == len(J) and (oo.joints.j_onobj == 0.3).all())
    for kind in ("point", "prob", "joint"):
        pk = fs.leak_probe(f, [Only(kind)], [T])
        chk(f"the leak probe compares a projector's {kind}s",
            pk.clean and pk.outputs[f"only_{kind}"] > 20, pk.outputs)


# ---------------------------------------------------------------------------
@section("8. the leak probe")
def _():
    f = league()
    weeks = [202403, 202404]
    clean = fs.leak_probe(f, fs.yardsticks(), weeks)
    chk("the honest harness is clean", clean.clean, clean.describe())
    chk("...on a real number of outputs from EACH projector",
        set(clean.outputs) == {"season_avg", "last4_avg", "gamelog_model"}
        and min(clean.outputs.values()) > 300, (clean.outputs, clean.fields))
    chk("...and says what it did not see",
        "no leak through the harness" in clean.describe()
        and "cannot see a projector that carries its own data" in clean.describe()
        and "2 week(s), 202403 to 202404" in clean.describe())

    s = fs.scramble_from(f, 202404)
    ident = ["season", "week", "game_id", "team", "opponent", "player_id",
             "position", "t"]
    chk("the scramble leaves who played, and where, alone",
        s[ident].equals(f[ident]))
    chk("...and every earlier week untouched",
        s[s.t < 202404].equals(f[f.t < 202404]))
    late = s.t >= 202404
    chk("...and overwrites every stat from that week on",
        all((s.loc[late, c] != f.loc[late, c]).all() for c in fs.RAW_STATS))
    gap = f.copy()
    gap.loc[gap.t >= 202404, ["offense_snaps", "st_snaps"]] = float("nan")
    gap.loc[gap.t >= 202404, "has_stats"] = False
    sg = fs.scramble_from(gap, 202404)
    lg = sg.t >= 202404
    chk("...a missing snap count included",
        sg.loc[lg, "offense_snaps"].notna().all()
        and (sg.loc[lg, "offense_snaps"] > 900).all()
        and (sg.loc[lg, "st_snaps"] > 900).all()
        and (sg.loc[lg, "offense_pct"] == 0.99).all())
    chk("...marks each such row as having a stat row",
        sg.loc[lg, "has_stats"].all() and not gap.loc[lg, "has_stats"].any())
    chk("...and rebuilds the touchdown column from the overwritten parts",
        (sg[TD_STAT] == sg.rushing_tds + sg.receiving_tds).all()
        and (sg.loc[lg, TD_STAT] > 1800).all())

    # Now let the week being projected into the history, the way a broken
    # filter would, with the guard that catches it switched off.
    real_rows, real_hist = fs._history_rows, fs.History

    class Unguarded(History):
        def __init__(self, rows, before):
            super().__init__(rows, before + 100)       # the guard looks later
            self.before, self.season, self.week = before, before // 100, before % 100

    try:
        fs._history_rows = lambda frame, before: frame[frame["t"] <= before]
        chk("a history that includes the week itself is refused by the guard",
            raises(lambda: fs.run_week(f, 202404, fs.yardsticks()), LeakError))
        fs.History = Unguarded
        leaky = fs.leak_probe(f, fs.yardsticks(), weeks)
    finally:
        fs._history_rows, fs.History = real_rows, real_hist
    chk("with the guard off, the probe finds the leak",
        leaky.measured and leaky.changed > 0 and not leaky.clean,
        leaky.describe()[:160])
    chk("...and says LEAK", "LEAK —" in leaky.describe())

    # The same leak, with a scramble too gentle to change who has a role or
    # how many rungs he has: only a number-by-number comparison can see it.
    real_scr = fs.scramble_from

    def gentle(frame, before):
        out = frame.copy()
        late = (out["t"] >= before).to_numpy()
        out.loc[late, "receiving_yards"] += 0.001
        return out

    try:
        fs._history_rows = lambda frame, before: frame[frame["t"] <= before]
        fs.History, fs.scramble_from = Unguarded, gentle
        quiet = fs.leak_probe(f, fs.yardsticks(), weeks)
    finally:
        fs._history_rows, fs.History = real_rows, real_hist
        fs.scramble_from = real_scr
    chk("a leak that moves numbers without moving the row count is found",
        quiet.changed > 0 and not quiet.clean
        and not any("row count" in e for e in quiet.examples),
        quiet.describe()[:160])
    chk("the harness is back to normal afterwards",
        fs.leak_probe(f, fs.yardsticks(), [202404]).clean)

    silent = fs.leak_probe(f, [Const("nan", point=float("nan"),
                                       p=float("nan"))], weeks)
    chk("a projector that returns nothing has not been shown clean",
        not silent.measured and not silent.clean and silent.fields > 0
        and "NOT MEASURED" in silent.describe(), silent.describe())
    mixed = fs.leak_probe(f, [Const("talks"), Const("nan", point=float("nan"),
                                                    p=float("nan"))], weeks)
    chk("...nor one that says nothing beside one that talks, and it is named",
        not mixed.measured and not mixed.clean and mixed.silent == ["nan"]
        and mixed.outputs["talks"] > 0
        and "NOT MEASURED — nan produced no number" in mixed.describe(),
        mixed.describe())
    pr = fs.LeakProbe(weeks=[202404])
    fs._diff_rows([("a", 1.0)], [("a", 1.0), ("b", 2.0)], frozenset(), 1,
                  ["m"], pr, 202404)
    chk("a different NUMBER of rows is a change, though every pair matches",
        pr.changed == 1 and pr.examples[0][1] == "row count", pr.examples)
    pr = fs.LeakProbe(weeks=[202404])
    fs._diff_rows([("a", 1.0, 5.0, 0.3, float("nan"))],
                  [("a", 1.0, 9.0, 0.3, float("nan"))],
                  frozenset({2}), 3, ["m", "y"], pr, 202404)
    chk("the graded result is skipped; outputs are counted per projector and "
        "apart from other fields; a blank output is not counted",
        pr.changed == 0 and pr.fields == 2 and pr.outputs == {"m": 1, "y": 0},
        (pr.changed, pr.fields, pr.outputs))
    fs._diff_rows([("a", 1.0, 5.0, 0.3, 0.1)], [("a", 1.0, 5.0, 0.3, 0.2)],
                  frozenset({2}), 3, ["m", "y"], pr, 202404)
    chk("...and one output that moved is a change",
        pr.changed == 1 and pr.outputs == {"m": 2, "y": 1})
    nothing = fs.leak_probe(f, fs.yardsticks(), [])
    chk("with nothing to look at it is NOT MEASURED, and not clean",
        not nothing.measured and not nothing.clean
        and "NOT MEASURED" in nothing.describe())
    empty = fs.leak_probe(f[f.season == 2023], fs.yardsticks(), [202404])
    chk("...the same when the week has no games", not empty.clean)
    one = fs.LeakProbe(outputs={"m": 10}, changed=1, weeks=[202404],
                       examples=[("x",)])
    chk("one changed number is a leak",
        not one.clean and one.describe().startswith("LEAK PROBE: LEAK"))


# ---------------------------------------------------------------------------
@section("9. error bars clustered by game")
def _():
    x = [1.0, 0.0, 1.0, 1.0, 0.0, 0.0]
    g = ["a", "a", "b", "b", "c", "c"]
    m, se, n, k = fs.cluster_mean(x, g)
    # mean 0.5; cluster sums of (x - m): a 0, b +1, c -1 -> sum sq 2
    chk("the mean and counts", near(m, 0.5) and n == 6 and k == 3)
    chk("the clustered standard error, by hand",
        near(se, math.sqrt(3 / 2 * 2) / 6), se)
    naive = math.sqrt(0.25 / 6)
    chk("...is wider than the naive one when a game moves together", se > naive,
        f"{se:.4f} vs {naive:.4f}")
    m2, se2, n2, k2 = fs.cluster_mean(x + x, g + g)
    chk("counting every leg twice inside its game does not shrink it",
        near(se2, se) and n2 == 12 and k2 == 3, se2)
    m1, se1, n1, k1 = fs.cluster_mean([1.0, 0.0], ["a", "a"])
    chk("one game: a mean but no error bar", near(m1, 0.5) and math.isnan(se1)
        and k1 == 1)
    m0, se0, n0, k0 = fs.cluster_mean([], [])
    chk("nothing: NaN, not zero", math.isnan(m0) and n0 == 0 and k0 == 0)
    spread = fs.cluster_mean([1, 0, 1, 0, 1, 0], ["a", "a", "b", "b", "c", "c"])
    chk("games that each split evenly have a zero clustered error",
        near(spread[1], 0.0, 1e-12))

    # 24 hits in 40 one-leg games. The clustered error is the naive one times
    # sqrt(40/39), so 39 effective observations; Wilson's range on those.
    hits = [1.0] * 24 + [0.0] * 16
    r = fs.rate_range(hits, [f"g{i}" for i in range(40)])
    z2 = 1.96 ** 2
    mid = (0.6 + z2 / 78) / (1 + z2 / 39)
    half = 1.96 * math.sqrt(0.24 / 39 + z2 / (4 * 39 ** 2)) / (1 + z2 / 39)
    chk("a rate's 95% range is Wilson's on the effective sample, by hand",
        near(r["n_eff"], 39.0, 1e-9) and near(r["lo"], mid - half, 1e-12)
        and near(r["hi"], mid + half, 1e-12) and r["games"] == 40, r)
    chk("...and is not 'the rate plus or minus two errors'",
        not near(r["hi"] - r["rate"], 1.96 * r["se"], 1e-3))
    chk("the multiplier is 1.96 everywhere", fs.Z95 == 1.96)
    one = fs.rate_range(hits, ["g"] * 40)
    chk("one game counts once: a wide range, and no verdict",
        math.isnan(one["se"]) and near(one["n_eff"], 1.0)
        and one["hi"] - one["lo"] > 0.7
        and fs.read_rate(0.6, one) == "too few games to say", one)
    # the same 40 legs packed two to a game, each game all-or-nothing
    packed = fs.rate_range(hits, [f"g{i // 2}" for i in range(40)])
    chk("legs that move together in a game count for fewer, and widen it",
        packed["n_eff"] < 25 and packed["hi"] - packed["lo"] > r["hi"] - r["lo"],
        packed)
    alt = fs.rate_range([1.0, 0.0] * 20, [f"g{i // 2}" for i in range(40)])
    chk("...but never for MORE than there are", near(alt["n_eff"], 40.0), alt)
    full = fs.rate_range([1.0] * 40, [f"g{i}" for i in range(40)])
    chk("40 hits in 40 does not have a range of exactly 100%",
        full["lo"] < 0.92 and full["hi"] == 1.0, full)
    chk("...so a stated 97% that always hit reads as stated",
        fs.read_rate(0.97, full) == "as stated")
    heavy = fs.rate_range([1.0] * 600, [f"g{i % 30}" for i in range(600)])
    chk("600 legs that all hit, in 30 games, count as 30 and not 600",
        near(heavy["n_eff"], 30.0) and heavy["lo"] < 0.90
        and fs.read_rate(0.99, heavy) == "as stated", heavy)
    for misses in (1, 2, 4):
        near_top = fs.rate_range([0.0] * misses + [1.0] * (600 - misses),
                                 [f"g{i % 30}" for i in range(600)])
        chk(f"...and so do 600 with {misses} miss(es): too few to measure how "
            f"a game's legs move together",
            near(near_top["n_eff"], 30.0)
            and fs.read_rate(0.99, near_top) == "as stated", near_top)
    five = fs.rate_range([0.0] * 5 + [1.0] * 595, [f"g{i % 30}" for i in range(600)])
    chk("with five misses the clustering is measured from the legs",
        five["n_eff"] > 100 and fs.RARE_FOR_CLUSTERING == 5, five["n_eff"])
    for n in (31, 44, 57):
        top = fs.rate_range([1.0] * n, [f"g{i}" for i in range(n)])
        bot = fs.rate_range([0.0] * n, [f"g{i}" for i in range(n)])
        chk(f"{n} of {n} reaches exactly 100%, and 0 of {n} exactly 0%",
            top["hi"] == 1.0 and bot["lo"] == 0.0
            and fs.read_rate(1.0, top) == "as stated"
            and fs.read_rate(0.0, bot) == "as stated", (top["hi"], bot["lo"]))
    chk("a stated figure just inside the range is as stated",
        fs.read_rate(r["hi"] - 0.001, r) == "as stated"
        and fs.read_rate(r["lo"] + 0.001, r) == "as stated")
    chk("...and just outside it is not, in the right direction",
        fs.read_rate(r["hi"] + 0.001, r) == "happens LESS than stated"
        and fs.read_rate(r["lo"] - 0.001, r) == "happens MORE than stated")
    g30 = fs.rate_range(hits[:30], [f"g{i}" for i in range(30)])
    g29 = fs.rate_range(hits[:29], [f"g{i}" for i in range(29)])
    chk("30 games gets a verdict and 29 does not",
        fs.read_rate(0.99, g30) == "happens LESS than stated"
        and fs.read_rate(0.99, g29) == "too few games to say"
        and fs.MIN_GAMES_FOR_VERDICT == 30)
    chk("nothing at all is NaN, not 0%", math.isnan(fs.rate_range([], [])["rate"]))
    # A difference: 30 games, c + 1 and c - 1 alternating. se = sqrt(30/29*30)/30
    se30 = math.sqrt(30 / 29 * 30) / 30
    chk("a difference just inside 1.96 errors is noise, just outside is not",
        fs._verdict(1.96 * se30 - 0.001, se30, 30)
        == "no difference that can be told from noise"
        and fs._verdict(1.96 * se30 + 0.001, se30, 30) == "higher"
        and fs._verdict(-1.96 * se30 - 0.001, se30, 30) == "lower"
        and fs._verdict(5.0, se30, 29) == "too few games to say")


# ---------------------------------------------------------------------------
def games(n, **kw):
    """n one-leg games, for anything that needs 30 clusters."""
    return [dict(game_id=f"g{i}", player_id=f"p{i}", **kw) for i in range(n)]


@section("10. the stat-line miss")
def _():
    pts = [dict(game_id="g1", player_id="a", actual=5, m=4.0, y=8.0),
           dict(game_id="g1", player_id="b", actual=2, m=3.0, y=2.0),
           dict(game_id="g4", player_id="h", actual=10, m=4.0, y=10.0),
           dict(game_id="g2", player_id="c", actual=10, m=6.0, y=float("nan")),
           dict(game_id="g2", player_id="d", actual=0, m=0.0, y=1.0, role=False),
           dict(game_id="g3", player_id="e", version="B", played=False,
                m=4.0, y=4.0),
           dict(game_id="g3", player_id="f", version="B", actual=6, m=4.0, y=7.0)]
    run = mkrun(points=pts, names=("m", "y"))
    e = fs.stat_error(run).set_index("projector")
    # common rows a, b, h. m misses by 1, 1, 6; y by 3, 0, 0.
    chk("on the common player-games: typical miss is the MEDIAN miss",
        near(e.loc["m", "typical_miss"], 1.0) and e.loc["m", "n"] == 3
        and near(e.loc["y", "typical_miss"], 0.0), e.loc["m"].to_dict())
    chk("mean miss by hand", near(e.loc["m", "mean_miss"], 8 / 3)
        and near(e.loc["y", "mean_miss"], 1.0))
    chk("bias is projected minus actual", near(e.loc["m", "bias"], -2.0)
        and near(e.loc["y", "bias"], 1.0))
    chk("coverage is the share it could project at all",
        near(e.loc["y", "coverage"], 3 / 4) and near(e.loc["m", "coverage"], 1.0))
    own = fs.stat_error(run, common=False).set_index("projector")
    chk("common=False grades each on its own player-games",
        own.loc["m", "n"] == 4 and near(own.loc["m", "mean_miss"], 3.0)
        and own.loc["y", "n"] == 3)
    allp = fs.stat_error(run, role_only=False).set_index("projector")
    chk("role_only=False adds the player with no role", allp.loc["m", "n"] == 4)
    b = fs.stat_error(run, version="B").set_index("projector")
    chk("version B drops a player who did not play",
        b.loc["m", "n"] == 1 and near(b.loc["m", "mean_miss"], 2.0))
    bz = fs.stat_error(run, version="B", dnp_as_zero=True).set_index("projector")
    chk("...or scores him as a zero when asked",
        bz.loc["m", "n"] == 2 and near(bz.loc["m", "mean_miss"], 3.0))
    chk("an unknown version is refused",
        raises(lambda: fs.stat_error(run, version="C"), ValueError))
    chk("games are counted", e.loc["m", "games"] == 2 and own.loc["m", "games"] == 3)
    # a, b in g1 miss by 1 and 1; h in g4 misses by 6. Mean 8/3. Game sums of
    # (miss - mean): g1 -10/3, g4 +10/3.
    chk("the mean miss's error is clustered by game, by hand",
        near(e.loc["m", "mean_miss_se"],
             math.sqrt(2 / 1 * 2 * (10 / 3) ** 2) / 3, 1e-9),
        e.loc["m", "mean_miss_se"])
    bver = fs.stat_error(run, version="B", common=False).set_index("projector")
    chk("version A and version B are graded apart",
        bver.loc["m", "n"] == 1 and own.loc["m", "n"] == 4)
    cmp_rows = [dict(game_id="g1", player_id="a", actual=0, m=3.0, y=0.0),
                dict(game_id="g2", player_id="b", actual=0, m=9.0, y=0.0, role=False),
                dict(game_id="g3", player_id="c", played=False, m=9.0, y=0.0),
                dict(game_id="g4", player_id="d", actual=0, m=9.0, y=0.0, version="B")]
    crun = mkrun(points=cmp_rows, names=("m", "y"))
    ce = fs.compare_error(crun, "m", "y").iloc[0]
    chk("compare_error leaves out a player with no role, one who did not "
        "play, and the other version", ce["n"] == 1 and near(ce["diff"], 3.0),
        ce.to_dict())
    chk("...and takes the no-role player when asked",
        fs.compare_error(crun, "m", "y", role_only=False).iloc[0]["n"] == 2)
    chk("...or the other version",
        near(fs.compare_error(crun, "m", "y", version="B").iloc[0]["diff"], 9.0))

    big = mkrun(points=games(40, actual=5, m=5.0, y=7.0), names=("m", "y"))
    c = fs.compare_error(big, "m", "y").iloc[0]
    chk("the better projector's difference is negative and read as lower",
        near(c["diff"], -2.0) and c["read"] == "lower", c.to_dict())
    c2 = fs.compare_error(big, "y", "m").iloc[0]
    chk("...and the other way round, higher", c2["read"] == "higher")
    few = mkrun(points=games(29, actual=5, m=5.0, y=7.0), names=("m", "y"))
    chk("under 30 games no verdict is given",
        fs.compare_error(few, "m", "y").iloc[0]["read"] == "too few games to say")
    thirty = mkrun(points=games(30, actual=5, m=5.0, y=7.0), names=("m", "y"))
    chk("...and at 30 one is",
        fs.compare_error(thirty, "m", "y").iloc[0]["read"] == "lower")
    empty = mkrun(names=("m", "y"))
    chk("an empty run gives empty tables, not an error",
        len(fs.stat_error(empty)) == 0 and len(fs.compare_error(empty, "m", "y")) == 0
        and fs.score_legs(empty).n.sum() == 0
        and fs.availability(empty, "m")["n"] == 0
        and math.isnan(fs.reference_brier(empty)["brier"])
        and len(fs.graded_legs(empty, "m")) == 0)
    none = fs.walk_forward(league(), fs.yardsticks(), weeks=[])
    chk("...nor does a walk-forward over no weeks",
        none.describe() == "no weeks were run" and len(fs.stat_error(none)) == 0
        and fs.score_legs(none).n.sum() == 0 and none.unverified == []
        and fs.availability(none, "last4_avg")["n"] == 0
        and len(fs.calibration(fs.graded_legs(none, "last4_avg"))) == 10)
    mixed = [dict(game_id=f"g{i}", player_id=f"p{i}", actual=5,
                  m=5.0 + (1 if i % 2 else -1) * 2, y=5.0 + (2 if i % 2 else -2))
             for i in range(40)]
    chk("equal misses read as no difference",
        fs.compare_error(mkrun(points=mixed, names=("m", "y")), "m", "y")
        .iloc[0]["read"] == "no difference that can be told from noise")


# ---------------------------------------------------------------------------
@section("11. calibration of single lines")
def _():
    legs = [dict(game_id="g1", player_id="a", m=0.30, over=False),   # UNDER .70 hit
            dict(game_id="g1", player_id="b", m=0.72, over=False),   # OVER .72 miss
            dict(game_id="g2", player_id="c", m=0.50, over=True),    # OVER .50 hit
            dict(game_id="g2", player_id="d", m=float(np.nextafter(0.6, 0)),
                 over=True),                 # a rounding hair under 60%
            dict(game_id="g3", player_id="e", m=1.0, over=True),
            dict(game_id="g3", player_id="f", m=float("nan"), over=True),
            dict(game_id="g3", player_id="g", m=0.9, over=True, played=False)]
    run = mkrun(legs=legs)
    g = fs.graded_legs(run, "m").set_index("player_id")
    chk("a leg under 50% is read on the UNDER side",
        g.loc["a", "side"] == "UNDER" and near(g.loc["a", "p_side"], 0.70)
        and bool(g.loc["a", "hit"]))
    chk("an OVER that missed is a miss",
        g.loc["b", "side"] == "OVER" and not bool(g.loc["b", "hit"]))
    chk("exactly 50% is put on OVER", g.loc["c", "side"] == "OVER")
    chk("a leg with no probability or no result is not graded",
        "f" not in g.index and "g" not in g.index and len(g) == 5)
    c = fs.calibration(g.reset_index()).set_index("band")
    chk("0.70 and 0.72 share the 70-75% band", c.loc["70%-75%", "n"] == 2)
    chk("...where one of two happened", near(c.loc["70%-75%", "happened"], 0.5)
        and near(c.loc["70%-75%", "stated"], 0.71))
    chk("a probability a rounding hair under 60% is in 60-65%, not 55-60%",
        c.loc["60%-65%", "n"] == 1 and c.loc["55%-60%", "n"] == 0)
    chk("100% is in the top band", c.loc["95%-100%", "n"] == 1)
    chk("an empty band says so", c.loc["55%-60%", "read"] == "no legs")
    chk("a band on one game gives no verdict",
        c.loc["70%-75%", "read"] == "too few games to say")
    chk("the ten bands run 50% to 100%",
        list(c.index)[0] == "50%-55%" and list(c.index)[-1] == "95%-100%"
        and len(c) == 10)

    # One player's ladder inside one band counts once.
    lad = [dict(game_id="g1", player_id="a", m=0.73, line=2.5, main_line=4.5,
                rung="x0.6", over=True),               # farther, listed first
           dict(game_id="g1", player_id="a", m=0.71, line=3.5, main_line=4.5,
                rung="x0.8", over=True),
           dict(game_id="g1", player_id="a", m=0.28, line=6.5, main_line=4.5,
                rung="x1.6", over=False),              # UNDER side: separate
           dict(game_id="g1", player_id="b", m=0.74, line=2.5, main_line=4.5,
                rung="x0.6", over=False),              # another player
           dict(game_id="g1", player_id="a", stat="targets", m=0.74, line=5.5,
                main_line=6.5, rung="x0.8", over=True)]   # another stat
    cl = fs.calibration(fs.graded_legs(mkrun(legs=lad), "m")).set_index("band")
    r = cl.loc["70%-75%"]
    chk("two rungs of one player, stat and side in a band count once",
        r.n == 4 and r.legs_before_dedupe == 5, r.to_dict())
    chk("...keeping the rung nearer his main line",
        near(r.stated, (0.71 + 0.72 + 0.74 + 0.74) / 4), r.stated)

    def band(n, p, hits):
        return [dict(game_id=f"g{i}", player_id=f"p{i}", m=p, over=i < hits)
                for i in range(n)]
    for label, hits, want in (("as stated", 24, "as stated"),
                              ("less", 10, "happens LESS than stated"),
                              ("more", 39, "happens MORE than stated")):
        cc = fs.calibration(fs.graded_legs(mkrun(legs=band(40, 0.62, hits)), "m"))
        got = cc.set_index("band").loc["60%-65%", "read"]
        chk(f"40 games, {hits} of 40 at a stated 62%: {want}", got == want, got)
    c29 = fs.calibration(fs.graded_legs(mkrun(legs=band(29, 0.62, 5)), "m"))
    chk("29 games gives no verdict however far off",
        c29.set_index("band").loc["60%-65%", "read"] == "too few games to say")
    c30 = fs.calibration(fs.graded_legs(mkrun(legs=band(30, 0.62, 5)), "m"))
    chk("...and 30 does",
        c30.set_index("band").loc["60%-65%", "read"] == "happens LESS than stated")
    c40 = fs.calibration(fs.graded_legs(mkrun(legs=band(40, 0.62, 24)), "m")
                         ).set_index("band").loc["60%-65%"]
    want = fs.rate_range([1.0] * 24 + [0.0] * 16, [f"g{i}" for i in range(40)])
    chk("the band's range is rate_range's, clustered by game",
        near(c40.lo, want["lo"], 1e-12) and near(c40.hi, want["hi"], 1e-12)
        and near(c40.happened, 0.6) and c40.games == 40
        and 0.43 < c40.lo < 0.46 and 0.72 < c40.hi < 0.75, c40.to_dict())
    # 24 of 40 has a range of 44.4% to 73.8%. A stated 73% is inside it and
    # a stated 74.5% is not. (Rate plus or minus two errors would reach 75.4%.)
    for p_, want_ in ((0.73, "as stated"), (0.745, "happens LESS than stated")):
        got = fs.calibration(fs.graded_legs(mkrun(legs=band(40, p_, 24)), "m")
                             ).set_index("band").loc["70%-75%", "read"]
        chk(f"24 of 40 at a stated {p_:.1%}: {want_}", got == want_, got)
    top = fs.calibration(fs.graded_legs(mkrun(legs=band(40, 0.97, 40)), "m")
                         ).set_index("band").loc["95%-100%"]
    chk("40 of 40 at a stated 97% reads as stated, not as MORE",
        top["read"] == "as stated" and top.lo < 0.97, top.to_dict())
    two = [dict(game_id=f"g{i // 2}", player_id=f"p{i}", m=0.62, over=i < 24)
           for i in range(40)]
    c2 = fs.calibration(fs.graded_legs(mkrun(legs=two), "m")
                        ).set_index("band").loc["60%-65%"]
    chk("the same legs two to a game, each game all or nothing, have a "
        "wider range", c2.games == 20 and c2.n == 40
        and c2.hi - c2.lo > c40.hi - c40.lo + 0.05, (c2.lo, c2.hi))
    vb = [dict(game_id="g1", player_id="a", m=0.7, over=True),
          dict(game_id="g1", player_id="b", m=0.7, over=True, version="B")]
    chk("graded_legs takes one version at a time",
        list(fs.graded_legs(mkrun(legs=vb), "m").player_id) == ["a"]
        and list(fs.graded_legs(mkrun(legs=vb), "m", version="B").player_id) == ["b"])

    td = [dict(game_id=f"g{i}", player_id=f"p{i}", stat=TD_STAT, line=0.5,
               m=0.25, over=i < 12) for i in range(40)]
    u = fs.calibration(fs.graded_legs(mkrun(legs=td), "m"), folded=False)
    u = u.set_index("band")
    chk("unfolded reads the chance of OVER as stated",
        u.loc["20%-30%", "n"] == 40 and near(u.loc["20%-30%", "happened"], 0.30)
        and len(u) == 10)
    gl = fs.graded_legs(mkrun(legs=legs + td), "m", stats=[TD_STAT])
    chk("graded_legs can be limited to some stats",
        set(gl.stat) == {TD_STAT} and len(gl) == 40)
    gr = fs.graded_legs(mkrun(legs=lad), "m", rung="x0.6")
    chk("...or to one rung", len(gr) == 2 and set(gr.rung) == {"x0.6"})


# ---------------------------------------------------------------------------
@section("12. scores")
def _():
    legs = [dict(game_id="g1", player_id="a", m=0.8, y=0.5, over=True),
            dict(game_id="g2", player_id="b", m=0.3, y=0.5, over=False),
            dict(game_id="g2", player_id="c", m=0.9, y=float("nan"), over=False)]
    run = mkrun(legs=legs, names=("m", "y"))
    s = fs.score_legs(run).set_index("projector")
    chk("Brier score by hand, on the legs both priced",
        near(s.loc["m", "brier"], (0.04 + 0.09) / 2) and s.loc["m", "n"] == 2,
        s.loc["m"].to_dict())
    chk("a coin flip scores 0.250", near(s.loc["y", "brier"], 0.25))
    chk("log loss by hand",
        near(s.loc["m", "log_loss"], -(math.log(0.8) + math.log(0.7)) / 2, 1e-9))
    big = mkrun(legs=[dict(game_id=f"g{i}", player_id=f"p{i}", m=0.8, y=0.5,
                           over=i % 5 != 0) for i in range(40)],
                names=("m", "y"))
    c = fs.compare_brier(big, "m", "y")
    chk("the sharper, calibrated projector has the lower Brier",
        c["diff"] < 0 and c["read"] == "lower" and c["n"] == 40, c)
    chk("...and the comparison flips with the order",
        fs.compare_brier(big, "y", "m")["read"] == "higher")
    # Filters: one leg of each kind, each scoring differently.
    mix = [dict(game_id="g1", player_id="a", m=0.9, y=0.5, over=True),
           dict(game_id="g2", player_id="b", m=0.9, y=0.5, over=False,
                stat="targets"),
           dict(game_id="g3", player_id="c", m=0.9, y=0.5, over=False,
                rung="x0.6", line=2.5),
           dict(game_id="g4", player_id="d", m=0.9, y=0.5, over=False,
                version="B"),
           dict(game_id="g5", player_id="e", m=0.9, y=0.5, over=False,
                played=False)]
    mr = mkrun(legs=mix, names=("m", "y"))

    def brier_m(**kw):
        return fs.score_legs(mr, **kw).set_index("projector").loc["m", ["n", "brier"]]

    chk("score_legs: version A, played legs only",
        brier_m().n == 3 and near(brier_m().brier, (0.01 + 0.81 + 0.81) / 3))
    chk("...limited to some stats",
        brier_m(stats=["receptions"]).n == 2
        and near(brier_m(stats=["targets"]).brier, 0.81))
    chk("...or one rung", brier_m(rung=MAIN).n == 2
        and near(brier_m(rung="x0.6").brier, 0.81) and brier_m(rung="x0.6").n == 1)
    chk("...or the other version",
        brier_m(version="B").n == 1 and near(brier_m(version="B").brier, 0.81))
    cb = fs.compare_brier(mr, "m", "y")
    chk("compare_brier uses the same legs",
        cb["n"] == 3 and near(cb["diff"], (0.01 + 0.81 + 0.81) / 3 - 0.25))
    chk("...and the same filters",
        fs.compare_brier(mr, "m", "y", stats=["targets"])["n"] == 1
        and fs.compare_brier(mr, "m", "y", rung="x0.6")["n"] == 1
        and fs.compare_brier(mr, "m", "y", version="B")["n"] == 1
        and near(fs.compare_brier(mr, "m", "y", stats=["receptions"],
                                  rung=MAIN)["diff"], 0.01 - 0.25))
    one_blank = [dict(game_id="g1", player_id="a", m=0.9, y=0.5, over=True),
                 dict(game_id="g2", player_id="b", m=0.9, y=float("nan"),
                      over=True)]
    cbl = fs.compare_brier(mkrun(legs=one_blank, names=("m", "y")), "m", "y")
    chk("compare_brier leaves out a leg either one did not price",
        cbl["n"] == 1 and near(cbl["diff"], 0.01 - 0.25), cbl)
    sure = [dict(game_id="g1", player_id="a", m=0.0, y=0.5, over=True),
            dict(game_id="g2", player_id="b", m=1.0, y=0.5, over=False)]
    ll = fs.score_legs(mkrun(legs=sure, names=("m", "y"))).set_index("projector")
    chk("a wrong 0% or 100% has a large log loss, not an infinite one",
        math.isfinite(ll.loc["m", "log_loss"])
        and near(ll.loc["m", "log_loss"], -math.log(1e-6), 1e-9))
    # Knowing nothing: 3 of 4 main receptions legs went over, 1 of 2 at x0.6,
    # and 1 of 4 main TARGETS legs.
    ref = [*[dict(game_id=f"g{i}", player_id=f"p{i}", m=0.9, y=0.5, over=i < 3)
             for i in range(4)],
           *[dict(game_id=f"h{i}", player_id=f"q{i}", m=0.9, y=0.5, over=i < 1,
                  rung="x0.6", line=2.5) for i in range(2)],
           *[dict(game_id=f"t{i}", player_id=f"r{i}", m=0.9, y=0.5, over=i < 1,
                  stat="targets") for i in range(4)],
           dict(game_id="z", player_id="z", m=float("nan"), y=0.5, over=True)]
    rrun = mkrun(legs=ref, names=("m", "y"))
    rr = fs.reference_brier(rrun)
    chk("the know-nothing reference says each stat-and-rung's own rate",
        rr["n"] == 10
        and near(rr["brier"], (4 * 0.1875 + 2 * 0.25 + 4 * 0.1875) / 10), rr)
    # m says 0.9 everywhere: 5 overs (0.01 each) and 5 unders (0.81 each)
    cr = fs.compare_reference(rrun, "m")
    chk("a projector's gap to it is taken leg by leg, on the same legs",
        cr["n"] == 10 and near(cr["diff"], 0.41 - rr["brier"])
        and cr["read"] == "too few games to say", cr)
    wide = mkrun(legs=[dict(game_id=f"g{i}", player_id=f"p{i}", m=0.9, y=0.5,
                            over=i % 2 == 0) for i in range(40)],
                 names=("m", "y"))
    pack = mkrun(legs=[dict(game_id=f"g{i // 2}", player_id=f"p{i}", m=0.9,
                            y=0.5, over=(i // 2) % 2 == 0) for i in range(40)],
                 names=("m", "y"))
    chk("...with its error clustered by game",
        fs.compare_reference(pack, "m")["games"] == 20
        and fs.compare_reference(pack, "m")["se"]
        > fs.compare_reference(wide, "m")["se"] * 1.2)
    chk("...and read as higher when it is worse than knowing nothing",
        fs.compare_reference(wide, "m")["read"] == "higher"
        and near(fs.compare_reference(wide, "m")["diff"], 0.41 - 0.25)
        and fs.compare_reference(wide, "y")["read"]
        == "no difference that can be told from noise")
    chk("...on the legs every projector priced, and with the same filters",
        fs.reference_brier(rrun, rung="x0.6")["n"] == 2
        and near(fs.reference_brier(rrun, rung=MAIN)["brier"], 0.1875)
        and near(fs.reference_brier(rrun, stats=["targets"])["brier"], 0.1875)
        and fs.compare_reference(rrun, "m", stats=["targets"])["n"] == 4)


# ---------------------------------------------------------------------------
@section("13. pairs")
def _():
    import ff_boost, ff_correlation

    def leg(g, team, pid, pos, stat, p, over):
        return dict(game_id=g, team=team, player_id=pid, position=pos,
                    stat=stat, m=p, over=over, line=0.5 if stat == TD_STAT else 4.5)
    legs = [leg("g1", "AAA", "qb", "QB", "passing_yards", 0.6, True),
            leg("g1", "AAA", "wr", "WR", "receiving_yards", 0.5, True),
            leg("g1", "AAA", "wr", "WR", "receptions", 0.4, False),
            leg("g1", "AAA", "rb", "RB", "receiving_yards", 0.5, True),
            leg("g1", "AAA", "rb", "RB", "receptions", 0.5, True),
            leg("g1", "BBB", "wr2", "WR", "receiving_yards", 0.3, False),
            leg("g1", "AAA", "wr", "WR", TD_STAT, 0.2, True),
            leg("g2", "CCC", "wr3", "WR", "receiving_yards", 0.7, True),
            dict(game_id="g1", team="AAA", player_id="wr", position="WR",
                 stat="receiving_yards", m=0.9, over=True, rung="x0.6",
                 line=2.5, main_line=4.5)]
    run = mkrun(legs=legs)
    sl = fs.side_legs(run, "m")
    sides = {(r.player_id, r.side) for r in sl.itertuples()}
    chk("a receiver's yards are RECV and his catches RECEPTIONS",
        ("wr", "RECV") in sides and ("wr", "RECEPTIONS") in sides)
    chk("a back's receiving yards are not RECV, as the engine measured it",
        ("rb", "RECV") not in sides and ("rb", "RECEPTIONS") in sides)
    chk("anytime TD is the TD side, and marked yes/no",
        ("wr", "TD") in sides and bool(sl[sl.side == "TD"].binary.all())
        and not sl[sl.side == "RECV"].binary.any())
    chk("only the main line makes a side leg",
        len(sl[(sl.player_id == "wr") & (sl.side == "RECV")]) == 1
        and near(sl[(sl.player_id == "wr") & (sl.side == "RECV")].p.iloc[0], 0.5))
    chk("the sides are the engine's own list",
        set(sl.side) <= set(ff_correlation.SIDE_SPEC))
    extra = legs + [
        dict(game_id="g1", team="BBB", player_id="out", position="WR",
             stat="receiving_yards", m=0.5, over=False, played=False),
        dict(game_id="g1", team="BBB", player_id="blank", position="WR",
             stat="receiving_yards", m=float("nan"), over=True),
        dict(game_id="g1", team="BBB", player_id="vb", position="WR",
             stat="receiving_yards", m=0.5, over=True, version="B")]
    sx = fs.side_legs(mkrun(legs=extra), "m")
    chk("a leg he did not play, one with no probability, and the other "
        "version make no side leg",
        not ({"out", "blank", "vb"} & set(sx.player_id)) and len(sx) == len(sl))
    chk("...and the other version's are there when asked for",
        set(fs.side_legs(mkrun(legs=extra), "m", version="B").player_id) == {"vb"})
    pr = fs.build_pairs(sl)
    keyset = [tuple(sorted(((a.player_id_a, a.side_a), (a.player_id_b, a.side_b))))
              for a in pr.itertuples()]
    chk("each pair appears once", len(keyset) == len(set(keyset)), len(keyset))
    # g1 legs: qb PASS, wr RECV, wr RECEPTIONS, wr TD, rb RECEPTIONS, wr2 RECV
    # = 6 legs, 15 pairs, less the 3 that are wr with himself = 12
    chk("the count is every two legs on two different players", len(pr) == 12,
        len(pr))
    chk("a player is never paired with himself",
        (pr.player_id_a != pr.player_id_b).all())
    chk("a pair is inside one game", "wr3" not in set(pr.player_id_a) | set(pr.player_id_b))
    one = pr[(pr.side_a == "PASS") & (pr.player_id_b == "wr") & (pr.side_b == "RECV")].iloc[0]
    chk("same team is 'same', and both is both",
        one.relation == "same" and bool(one.both) and near(one["product"], 0.30))
    opp = pr[(pr.side_a == "PASS") & (pr.player_id_b == "wr2")].iloc[0]
    chk("the other team is 'opp', and one miss is not both",
        opp.relation == "opp" and not bool(opp.both))

    chk("no correlation: the joint is the product",
        near(fs.corr_joint(0.6, 0.5, 0.0, False, False), 0.30))
    za, zb = fs._NORM.inv_cdf(0.4), fs._NORM.inv_cdf(0.5)
    want = 0.30 + 0.25 * fs._NORM.pdf(za) * fs._NORM.pdf(zb)
    chk("two yardage legs: the engine's first-order joint, by hand",
        near(fs.corr_joint(0.6, 0.5, 0.25, False, False), want, 1e-12))
    chk("...and it is ff_boost's own weight, not a copy",
        near(fs.corr_joint(0.6, 0.5, 0.25, False, False),
             0.30 * (1 + 0.25 * ff_boost._pair_weight(0.6, 0.5, za, zb, False, False)),
             1e-12))
    chk("two yes/no legs: the exact joint",
        near(fs.corr_joint(0.3, 0.2, 0.2, True, True),
             0.06 + 0.2 * math.sqrt(0.3 * 0.7 * 0.2 * 0.8), 1e-12))
    chk("a mixed pair differs from both",
        not near(fs.corr_joint(0.3, 0.5, 0.2, True, False),
                 fs.corr_joint(0.3, 0.5, 0.2, False, False), 1e-6))
    chk("a leg at exactly 0 or 1 leaves no room: the product, exactly",
        fs.corr_joint(1.0, 0.6, 0.3, False, False) == 0.6
        and fs.corr_joint(0.0, 0.6, 0.3, False, False) == 0.0
        and fs.corr_joint(0.4, 1.0, 0.3, True, True) == 0.4)
    chk("the joint never exceeds the smaller leg",
        near(fs.corr_joint(0.05, 0.9, 5.0, False, False), 0.05))
    chk("...nor falls below what two legs must share",
        near(fs.corr_joint(0.9, 0.9, -50.0, False, False), 0.8))

    tab = {("same", "PASS", "RECV"): 0.25}
    pa = fs.add_corr(pr, tab, "c")
    hit = pa[(pa.side_a == "PASS") & (pa.player_id_b == "wr") & (pa.side_b == "RECV")].iloc[0]
    chk("a measured cell is adjusted", near(hit.c, want, 1e-12) and bool(hit.c_measured))
    miss = pa[(pa.side_a == "PASS") & (pa.player_id_b == "wr2")].iloc[0]
    chk("an unmeasured cell keeps the product and is flagged",
        near(miss.c, miss["product"]) and not bool(miss.c_measured))
    chk("the flag counts the cells that had a number",
        int(pa.c_measured.sum()) == 1)
    flipped = fs.add_corr(pr, {("same", "RECEPTIONS", "PASS"): 0.25}, "c")
    chk("a key with its sides unsorted is never found",
        int(flipped.c_measured.sum()) == 0)
    sorted_key = fs.add_corr(pr, {("same", "PASS", "RECEPTIONS"): 0.25}, "c")
    chk("...and the sorted one is, for every pair in the cell",
        int(sorted_key.c_measured.sum()) == 2)
    hand = pd.DataFrame({"season": [2024, 2024], "relation": ["same", "same"],
                         "side_a": ["RECV", "RECV"], "side_b": ["PASS", "PASS"],
                         "p_a": [0.5, 1.0], "p_b": [0.6, 0.6],
                         "binary_a": [False, False], "binary_b": [False, False]})
    hc = fs.add_corr(hand, tab, "c")
    chk("a pair listed with its sides the other way round still finds its cell",
        bool(hc.c_measured.iloc[0]) and near(hc.c.iloc[0], want, 1e-12))
    chk("a leg stated at exactly 100% keeps the product instead of raising",
        not bool(hc.c_measured.iloc[1]) and near(hc.c.iloc[1], 0.6))
    by = fs.add_corr(pr, {2024: tab, 2025: {}}, "c")
    chk("a table per season is used for that season",
        int(by.c_measured.sum()) == 1)
    chk("...and a season with no table keeps the product",
        int(fs.add_corr(pr, {2023: tab}, "c").c_measured.sum()) == 0)

    cells = fs.pair_cells(pa, ("product", "c")).set_index(
        ["relation", "side_a", "side_b"])
    c = cells.loc[("same", "PASS", "RECV")]
    chk("a cell reports how often both happened, and each method's mean",
        c.n == 1 and near(c.both, 1.0) and near(c["product"], 0.30)
        and near(c.c, want, 1e-12))
    rr = cells.loc[("opp", "RECV", "RECV")]
    chk("measured lift is both over the two actual hit rates multiplied",
        near(rr.singles_product, 0.0) and math.isnan(rr.measured_lift))

    many = pd.DataFrame({
        "game_id": [f"g{i}" for i in range(80)], "relation": "same",
        "side_a": "PASS", "side_b": "RECV",
        "hit_a": [i < 40 for i in range(80)],
        "hit_b": [i < 32 or i >= 72 for i in range(80)],
        "both": [i < 32 for i in range(80)],
        "product": 0.25, "good": 0.40, "bad": 0.05})
    cc = fs.pair_cells(many, ("product", "good")).iloc[0]
    chk("lift by hand: 0.40 both over 0.5 x 0.5",
        near(cc.singles_product, 0.25) and near(cc.measured_lift, 1.6))
    # 80 one-pair games, 32 both: se = sqrt(80/79 * 80 * 0.24) / 80
    chk("the error of 'both', by hand",
        near(cc.se, math.sqrt(80 / 79 * 80 * 0.24) / 80, 1e-12), cc.se)
    # The lift's own error: each game's pull on both / (a x b), linearised.
    bo = many.both.to_numpy(dtype=float)
    ha, hb = many.hit_a.to_numpy(dtype=float), many.hit_b.to_numpy(dtype=float)
    lin = bo / 0.25 - 1.6 * (ha / 0.5 + hb / 0.5)
    by_hand = math.sqrt(80 / 79 * float(((lin - lin.mean()) ** 2).sum())) / 80
    chk("the lift's error carries the two single rates with it, by hand",
        near(cc.lift_se, by_hand, 1e-12) and cc.lift_se < cc.se / 0.25,
        (cc.lift_se, by_hand, cc.se / 0.25))
    packed = many.assign(game_id=[f"g{i // 2}" for i in range(80)])
    pk = fs.pair_cells(packed, ("product",)).iloc[0]
    chk("...and both errors are clustered by game",
        pk.se > cc.se * 1.2 and pk.lift_se > cc.lift_se * 1.2)
    # Against resampling whole games: 300 games of five pairs each, where a
    # good day lifts every leg at once.
    rng = np.random.RandomState(7)
    day = rng.rand(300) < 0.5
    gid = np.repeat(np.arange(300), 5)
    pa_ = np.where(day[gid], 0.75, 0.25)
    xa, xb = rng.rand(1500) < pa_, rng.rand(1500) < pa_
    sim = pd.DataFrame({"game_id": gid, "relation": "same", "side_a": "PASS",
                        "side_b": "RECV", "hit_a": xa, "hit_b": xb,
                        "both": xa & xb, "product": 0.25})
    cell = fs.pair_cells(sim, ("product",)).iloc[0]
    boots = []
    groups = [g_ for _, g_ in sim.groupby("game_id")]
    for _ in range(400):
        pick = rng.randint(0, 300, 300)
        bs = pd.concat([groups[k] for k in pick])
        boots.append(bs.both.mean() / (bs.hit_a.mean() * bs.hit_b.mean()))
    boot = float(np.std(boots, ddof=1))
    chk("the lift's error agrees with resampling whole games",
        0.8 < cell.lift_se / boot < 1.25, (cell.lift_se, boot))
    import ff_boost as _fb
    kept, real_w = list(fs._PAIR_WEIGHT), _fb._pair_weight
    try:
        fs._PAIR_WEIGHT.clear()
        del _fb._pair_weight
        named = raises(lambda: fs.corr_joint(0.5, 0.5, 0.2, False, False),
                       ImportError, "tell the engine thread")
    finally:
        _fb._pair_weight = real_w
        fs._PAIR_WEIGHT[:] = kept
    chk("if the engine's weight has moved, the failure names the coupling",
        named and near(fs.corr_joint(0.5, 0.5, 0.0, False, False), 0.25))
    sc = fs.pair_score(many, ["bad", "good"]).set_index("method")
    chk("the first method is the reference",
        sc.loc["bad", "read"] == "(the reference)"
        and near(sc.loc["bad", "diff_vs_first"], 0.0))
    # Brier: good 0.4*0.36 + 0.6*0.16 = 0.24; bad 0.4*0.9025 + 0.6*0.0025
    chk("a joint nearer the truth scores lower, by the hand figure",
        near(sc.loc["good", "brier"], 0.24)
        and near(sc.loc["good", "diff_vs_first"], 0.24 - 0.3625)
        and sc.loc["good", "read"] == "lower", sc.loc["good"].to_dict())
    back = fs.pair_score(many, ["good", "bad"]).set_index("method")
    chk("...and the worse one, against it, scores higher",
        back.loc["bad", "read"] == "higher")
    holes = many.assign(sim=[0.4 if i % 2 else float("nan") for i in range(80)])
    sh = fs.pair_score(holes, ["bad", "good", "sim"]).set_index("method")
    chk("methods are scored on the pairs ALL of them have a number for",
        set(sh.n) == {40} and near(sh.loc["sim", "brier"], sh.loc["good", "brier"]))
    p2 = many.assign(game_id=[f"g{i // 2}" for i in range(80)])
    chk("the score's error is clustered by game",
        fs.pair_score(p2, ["bad", "good"]).set_index("method").loc["good", "se"]
        > sc.loc["good", "se"] * 1.2)
    pc = fs.pair_calibration(many, "good").set_index("band")
    chk("pair calibration bands the stated joint",
        pc.loc["40%-50%", "n"] == 80 and near(pc.loc["40%-50%", "happened"], 0.40)
        and pc.loc["40%-50%", "read"] == "as stated")
    pp = fs.pair_calibration(many, "product").set_index("band")
    chk("...and reports what HAPPENED beside what was stated",
        near(pp.loc["20%-30%", "stated"], 0.25)
        and near(pp.loc["20%-30%", "happened"], 0.40)
        and pp.loc["20%-30%", "read"] == "happens MORE than stated",
        pp.loc["20%-30%"].to_dict())
    chk("...and can be limited to one relation",
        len(fs.pair_calibration(many, "good", "opp")) == 0)
    chk("it lists only bands that hold a pair, and counts pairs",
        list(pc.index) == ["40%-50%"] and "legs_before_dedupe" not in pc.columns
        and pc.loc["40%-50%", "games"] == 80)
    chk("a pair with no stated joint is left out, not put at 0%",
        fs.pair_calibration(holes, "sim").n.sum() == 40)


# ---------------------------------------------------------------------------
@section("14. what the active list is worth")
def _():
    pts = [dict(game_id="g1", player_id="a", actual=5, m=4.0),
           dict(game_id="g1", player_id="b", actual=5, m=4.0),
           dict(game_id="g1", player_id="e", actual=5, m=4.0),
           dict(game_id="g1", player_id="x", version="B", actual=1, m=1.0),
           # a role on A; on B's slate, but with no role there (a
           # quarterback B lists and does not line). He WAS on B's list.
           dict(game_id="g1", player_id="q", actual=5, m=4.0),
           dict(game_id="g1", player_id="q", version="B", actual=5,
                m=float("nan"), role=False),
           # no role in A: on both versions, and must not be compared
           dict(game_id="g1", player_id="n", actual=5, m=0.0, role=False),
           dict(game_id="g1", player_id="n", version="B", actual=5, m=5.0,
                role=False),
           dict(game_id="g1", player_id="a", version="B", actual=5, m=2.0),
           # on both, with a role on both, and the same number on both
           dict(game_id="g1", player_id="r", actual=5, m=4.0),
           dict(game_id="g1", player_id="r", version="B", actual=5, m=4.0),
           dict(game_id="g1", player_id="c", version="B", played=False, m=3.0),
           dict(game_id="g1", player_id="d", version="B", played=False, m=3.0,
                role=False)]
    av = fs.availability(mkrun(points=pts), "m")
    # compared: a (misses 1 on A, 3 on B) and r (1 and 1)
    chk("the difference is A's miss minus B's on the players both projected",
        av["n"] == 2 and near(av["miss_diff"], ((1 - 3) + (1 - 1)) / 2), av)
    # B's role players: x, a, r, c; only c did not play
    chk("the share of B's role players who did not play",
        av["b_role_players"] == 4 and near(av["b_did_not_play"], 1 / 4), av)
    # A's role players: a, b, e, q, r; b and e are on no B slate
    chk("the share of A's role players B never listed, role there or not",
        av["a_role_players"] == 5 and near(av["a_not_on_b"], 2 / 5), av)
    f = league(drop={(2024, 4, "CCC_WR1")})
    run = fs.walk_forward(f, fs.yardsticks(), weeks=[202403, 202404])
    chk("a yardstick that ignores the active list gains exactly nothing from it",
        all(fs.availability(run, n)["miss_diff"] == 0.0 for n in run.names)
        and fs.availability(run, "last4_avg")["n"] > 0)
    chk("...and its two versions agree number for number",
        all(fs.version_gap(run, n) == 0 for n in run.names))


# ---------------------------------------------------------------------------
@section("15. end to end on the newest weeks on file")
def _():
    frame = REAL.get("frame")
    if frame is None:
        frame = fs.load_frame()
    rep = frame.attrs["report"]
    chk("the real frame builds, four seasons of it",
        rep["seasons"] == sorted(set(rep["seasons"])) and len(rep["seasons"]) >= 4
        and rep["skill_player_games"] > 20000, rep)
    chk("active players with no stat row exist in real data, and are a "
        "minority", 0.03 < rep["share_on_field_no_stat_row"] < 0.30,
        f"{rep['share_on_field_no_stat_row']:.1%}")
    chk("nearly every skill snap row found its player",
        rep["skill_snap_rows_unplaced"] < 0.03 * rep["skill_snap_rows"],
        f"{rep['skill_snap_rows_unplaced']} of {rep['skill_snap_rows']}")
    chk("no player has two rows in one game",
        not frame.duplicated(["game_id", "player_id"]).any())
    chk("a starting quarterback was found for nearly every team-game, and "
        "never two", rep["team_games_with_a_starting_qb"] >= 0.99 * rep["team_games"]
        and frame[frame.qb_start].groupby(["game_id", "team"]).size().max() == 1
        and (frame[frame.qb_start].position == "QB").all(),
        (rep["team_games_with_a_starting_qb"], rep["team_games"]))
    chk("every row has a team, an opponent and a position",
        frame[["team", "opponent", "position"]].notna().all().all())
    # test_weeks leaves the newest week on file out: it may be half-played.
    weeks = fs.test_weeks(frame)[-3:]
    chk("the weeks graded here stop before the newest on file",
        len(weeks) == 3 and max(weeks) < int(frame.t.max()))
    run = fs.walk_forward(frame, fs.yardsticks(), weeks=weeks)
    REAL["run"] = run
    a = run.legs[run.legs.version == "A"]
    chk("three weeks ran", run.weeks == weeks and a.week.nunique() == 3)
    chk("every stat line named in the handoff has legs",
        set(a.stat) == set(fs.STATS), sorted(set(fs.STATS) - set(a.stat)))
    cols = [f"p_{n}" for n in run.names]
    v = a[cols].to_numpy(dtype=float)
    chk("every probability is between 0 and 1",
        np.nanmin(v) >= 0 and np.nanmax(v) <= 1)
    chk("the game-log model priced most legs",
        a.p_gamelog_model.notna().mean() > 0.9,
        f"{a.p_gamelog_model.notna().mean():.1%}")
    chk("every A leg has a result", a.played.all()
        and a.over.map(lambda x: isinstance(x, (bool, np.bool_))).all())
    chk("the result is the actual against the line",
        (a.over == (a.actual > a.line)).all())
    chk("no team has two lined quarterbacks",
        (a[(a.stat == "attempts") & (a.rung == MAIN)]
         .groupby(["game_id", "team"]).size() <= 1).all()
        and len(a[a.stat == "attempts"]) > 0)
    lq = a[(a.stat == "attempts") & (a.rung == MAIN)]
    started = set(zip(frame[frame.qb_start].game_id, frame[frame.qb_start].player_id))
    chk("every lined quarterback is the one who started that game",
        len(lq) > 60 and all(k in started for k in zip(lq.game_id, lq.player_id)),
        len(lq))
    chk("the yardsticks state no joint of their own", len(run.joints) == 0)
    chk("nothing was left unchecked", run.unverified == [])
    chk("every ladder has its main line",
        a.groupby(["game_id", "team", "player_id", "stat"]).rung
        .apply(lambda s: MAIN in set(s)).all())
    chk("lines are half points", ((a.line % 1).round(6) == 0.5).all())
    chk("a touchdown line is always 0.5", (a[a.stat == TD_STAT].line == 0.5).all())
    hist_ids = set(frame[frame.t < weeks[0]].player_id)
    b0 = run.points[(run.points.version == "B") & (run.points.week == weeks[0] % 100)]
    chk("everyone on B's first slate had played before it",
        len(b0) > 0 and set(b0.player_id) <= hist_ids)
    chk("no yardstick's numbers move when the active list is hidden",
        all(fs.version_gap(run, n) == 0 for n in run.names))
    probe = fs.leak_probe(frame, fs.yardsticks(), weeks[-1:])
    chk("the leak probe is clean on real data", probe.clean, probe.describe())
    e = fs.stat_error(run)
    chk("the stat-line report covers every stat for every yardstick",
        len(e) == len(fs.STATS) * len(run.names) and (e.n > 0).all())
    chk("typical misses are positive and finite",
        np.isfinite(e.typical_miss).all() and (e.mean_miss > 0).all())
    c = fs.calibration(fs.graded_legs(run, "gamelog_model"))
    chk("calibration puts every graded leg in exactly one band",
        int(c.legs_before_dedupe.sum())
        == len(fs.graded_legs(run, "gamelog_model")))
    sl = fs.side_legs(run, "gamelog_model")
    pr = fs.build_pairs(sl)
    import ff_correlation
    pr = fs.add_corr(pr, ff_correlation.recorded(
        ff_correlation.RECORDED_MARKET_SIDE), "corr")
    chk("real pairs come in both relations",
        set(pr.relation) == {"same", "opp"} and len(pr) > 1000, len(pr))
    chk("most real pairs sit in a cell the engine has measured",
        pr.corr_measured.mean() > 0.95, f"{pr.corr_measured.mean():.1%}")
    chk("an adjusted joint is still a probability",
        pr["corr"].between(0, 1).all()
        and (pr["corr"] <= pr[["p_a", "p_b"]].min(axis=1) + 1e-12).all())
    chk("the run describes itself", str(len(weeks)) + " weeks" in run.describe(),
        run.describe())


# ===========================================================================
# S4 — the opportunity model (ff_sim_opp.py)
# ===========================================================================
fo = OpportunityModel = None


@section("16. the opportunity model — it loads")
def _():
    global fo, OpportunityModel
    import ff_sim_opp
    fo, OpportunityModel = ff_sim_opp, ff_sim_opp.OpportunityModel
    chk("it projects targets, carries and pass attempts, and shares out the "
        "first two", fo.OPP_STATS == ("targets", "carries", "attempts")
        and fo.SHARED == ("targets", "carries"))


# The test's OWN copy of every number the model sets by hand. Typed here, not
# read from the module, so a changed constant shows up as a failed by-hand
# check and not as two things changing together.
HL_TEAM, HL_SHORT, HL_LONG = 4.0, 3.0, 10.0
FIT_ROWS, CUT, SIZE_LO, SIZE_HI, FLOOR = 16, 1.0, 1.0, 500.0, 1.0


def lean(vals, h):
    """A leaning average worked the long way: [(before, including), ...]."""
    w, out = 0.5 ** (1.0 / h), []
    for k in range(len(vals)):
        num = sum(w ** (k - j) * vals[j] for j in range(k + 1))
        den = sum(w ** (k - j) for j in range(k + 1))
        out.append((out[-1][1] if out else None, num / den))
    return out


def nb_tail(k, mean, size):
    """P(X > k) for a negative binomial with that mean and size, summed term
    by term from its formula."""
    if mean == 0:
        return 0.0
    p = size / (size + mean)
    below = sum(math.exp(math.lgamma(j + size) - math.lgamma(j + 1)
                         - math.lgamma(size) + size * math.log(p)
                         + j * math.log1p(-p)) for j in range(int(k) + 1))
    return 1.0 - below


def hand_size(x, m):
    excess = sum((a - b) ** 2 - b for a, b in zip(x, m))
    if not len(x) or excess <= 0:
        return SIZE_HI
    return min(max(sum(b * b for b in m) / excess, SIZE_LO), SIZE_HI)


def spread_for(lines, game, team):
    home, away, spread, total = lines[game]
    return [spread if team == home else -spread, total]


def by_hand_fit(F, lines=None):
    """Everything the model learns from a history, re-derived with plain
    loops from the description in its docstring."""
    tg = {}
    for r in F.itertuples():
        d = tg.setdefault((r.game_id, r.team), dict(
            t=r.t, opp=r.opponent, targets=0.0, carries=0.0, attempts=0.0))
        for s_ in ("targets", "carries", "attempts"):
            d[s_] += getattr(r, s_)
    keys = sorted(tg, key=lambda k: (tg[k]["t"], k))
    out = dict(keys=keys, tg=tg)
    for stat in ("targets", "carries", "attempts"):
        league = sum(tg[k][stat] for k in keys) / len(keys)
        off, dfn = {}, {}
        for k in keys:
            off.setdefault(k[1], []).append(k)
            dfn.setdefault(tg[k]["opp"], []).append(k)
        before = ({}, {})
        now = ({}, {})
        for which, grp in enumerate((off, dfn)):
            for name, ks in grp.items():
                for k, (b, inc) in zip(ks, lean([tg[k][stat] for k in ks],
                                                HL_TEAM)):
                    before[which][k] = league if b is None else b
                now[which][name] = inc
        X = np.array([[1.0, before[0][k], before[1][k]]
                      + (spread_for(lines, k[0], k[1]) if lines else [])
                      for k in keys])
        beta = np.linalg.lstsq(X, np.array([tg[k][stat] for k in keys]),
                               rcond=None)[0]
        out[stat] = dict(beta=beta, off_now=now[0], def_now=now[1],
                         league=league,
                         pred={k: float(X[i] @ beta) for i, k in enumerate(keys)})
    rows = F.sort_values(["player_id", "t"], kind="stable")
    for stat in ("targets", "carries"):
        o = out[stat]
        share = [getattr(r, stat) / tg[(r.game_id, r.team)][stat]
                 if tg[(r.game_id, r.team)][stat] > 0 else 0.0
                 for r in rows.itertuples()]
        pos = list(rows.position)
        overall = sum(share) / len(share)
        by_pos = {q: float(np.mean([s_ for s_, q2 in zip(share, pos) if q2 == q]))
                  for q in set(pos) if q is not None}
        feats, ys, ms, xs, short_now, long_now = [], [], [], [], {}, {}
        i = 0
        for pid, grp in rows.groupby("player_id", sort=False):
            sh = share[i:i + len(grp)]
            s3, s10 = lean(sh, HL_SHORT), lean(sh, HL_LONG)
            short_now[pid], long_now[pid] = s3[-1][1], s10[-1][1]
            for j, r in enumerate(grp.itertuples()):
                if j:
                    feats.append([1.0, s3[j][0], s10[j][0],
                                  by_pos.get(r.position, overall)])
                    ys.append(sh[j])
                    ms.append(o["pred"][(r.game_id, r.team)])
                    xs.append(getattr(r, stat))
            i += len(grp)
        A = np.array(feats)
        sbeta = np.linalg.lstsq(A, np.array(ys), rcond=None)[0]
        m = [max(float(a @ sbeta), 0.0) * v for a, v in zip(A, ms)]
        kept = [(x, v) for x, v in zip(xs, m) if v > CUT]
        o.update(sbeta=sbeta, short_now=short_now, long_now=long_now,
                 by_pos=by_pos, overall=overall, rows=len(feats),
                 small=len(m) - len(kept),
                 size=hand_size([a for a, _ in kept], [b for _, b in kept]))
    st = [r for r in F.itertuples() if r.qb_start]
    ss = (sum(r.attempts / tg[(r.game_id, r.team)]["attempts"] for r in st)
          / len(st)) if st else 1.0
    out["starter_share"] = ss
    out["attempts"]["size"] = hand_size(
        [r.attempts for r in st],
        [ss * out["attempts"]["pred"][(r.game_id, r.team)] for r in st])
    return out


def by_hand_means(ref, slate, lines=None):
    """The expected counts for a slate, from `by_hand_fit`'s numbers."""
    rows = list(slate.itertuples())

    def volume(stat, r):
        o = ref[stat]
        x = ([1.0, o["off_now"].get(r.team, o["league"]),
              o["def_now"].get(r.opponent, o["league"])]
             + (spread_for(lines, r.game_id, r.team) if lines else []))
        return max(float(np.array(x) @ o["beta"]), FLOOR)

    out = {}
    for stat in ("targets", "carries"):
        o = ref[stat]
        raw = []
        for r in rows:
            norm = o["by_pos"].get(r.position, o["overall"])
            raw.append(max(float(np.array(
                [1.0, o["short_now"][r.player_id], o["long_now"][r.player_id],
                 norm]) @ o["sbeta"]), 0.0)
                if r.player_id in o["short_now"] else norm)
        tot = {}
        for r, v in zip(rows, raw):
            tot[(r.game_id, r.team)] = tot.get((r.game_id, r.team), 0.0) + v
        out[stat] = [v / tot[(r.game_id, r.team)] * volume(stat, r)
                     if tot[(r.game_id, r.team)] > 0 else float("nan")
                     for r, v in zip(rows, raw)]
    out["attempts"] = [ref["starter_share"] * volume("attempts", r)
                       if r.starting_qb else float("nan") for r in rows]
    return out


ROUNDS = ((("AAA", "BBB"), ("CCC", "DDD")), (("AAA", "CCC"), ("BBB", "DDD")),
          (("AAA", "DDD"), ("BBB", "CCC")))
TEAM_LEAN = dict(AAA=1.25, BBB=0.9, CCC=1.0, DDD=0.8)


def rotating_league():
    """(frame, lines). A league whose schedule ROTATES, so a team's own
    average and what its opponent allows are different numbers. Counts are
    DRAWN and widely spread; a tight end is rarely thrown to and a receiver
    rarely runs; a second quarterback relieves one starter in two games;
    one team-game has no carry at all and another exactly one; home and
    away alternate."""
    rng = np.random.default_rng(7)

    def draw(mean, n=3):
        return float(rng.negative_binomial(n, n / (n + mean))) if mean > 0 else 0.0

    rows, lines, k = [], {}, 0
    for season, nweeks in SEASON_WEEKS.items():
        for week in range(1, nweeks + 1):
            for a, b in ROUNDS[k % 3]:
                home, away = (a, b) if week % 2 else (b, a)
                lines[gid(season, week, a, b)] = (
                    home, away, round(14 * (TEAM_LEAN[home] - TEAM_LEAN[away]), 1)
                    + (k % 4) - 1.5, 38.0 + 2 * (k % 5) + 6 * TEAM_LEAN[a])
                for team, opp in ((a, b), (b, a)):
                    up, soft = TEAM_LEAN[team], 2.0 - TEAM_LEAN[opp]
                    att = 12.0 + draw(20 * up * soft, 6)
                    relief = team == "AAA" and (season, week) in ((2023, 3), (2023, 5))
                    mk = lambda who, pos, **kw: rows.append(  # noqa: E731
                        row(season, week, team, opp, f"{team}_{who}", pos, **kw))
                    mk("QB", "QB", qb_start=True, carries=draw(2.5),
                       attempts=att - (9 if relief else 0))
                    if relief:
                        mk("QB2", "QB", attempts=9)
                    mk("RB", "RB", carries=draw(15 * soft), targets=draw(2.5))
                    mk("WR1", "WR", targets=draw(8 * up * soft), carries=draw(0.4))
                    mk("WR2", "WR", targets=draw(5 * up))
                    mk("TE", "TE", targets=draw(0.7))
            k += 1
    f = mkframe(rows)
    f.loc[(f.t == 202302) & (f.team == "CCC"), "carries"] = 0.0
    f.loc[(f.t == 202303) & (f.team == "DDD"), "carries"] = 0.0
    f.loc[(f.t == 202303) & (f.player_id == "DDD_RB"), "carries"] = 1.0
    return f, lines


def same_fit(a, b):
    """Two fits agree on everything that reaches a projection."""
    return (all(np.allclose(a.team[s_][0], b.team[s_][0])
                and near(a.team[s_][3], b.team[s_][3], 1e-9)
                and all(near(a.team[s_][j][k], b.team[s_][j][k], 1e-9)
                        for j in (1, 2) for k in a.team[s_][j])
                for s_ in fo.OPP_STATS)
            and all(np.allclose(a.share[s_][0], b.share[s_][0])
                    and all(near(a.share[s_][j][k], b.share[s_][j][k], 1e-9)
                            for j in (1, 2) for k in a.share[s_][j])
                    for s_ in fo.SHARED)
            and all(near(a.size[s_], b.size[s_], 1e-6) for s_ in fo.OPP_STATS)
            and near(a.starter_share, b.starter_share, 1e-12))


def fit_matches(fit, ref):
    """{what: ok} — a model's fit against the long-hand one, part by part."""
    ok = {}
    for stat in ("targets", "carries", "attempts"):
        beta, off_now, def_now, lg = fit.team[stat]
        o = ref[stat]
        ok[f"{stat}: team fit"] = (
            len(beta) == len(o["beta"]) and np.allclose(beta, o["beta"])
            and near(lg, o["league"], 1e-9)
            and set(off_now) == set(o["off_now"]) and set(def_now) == set(o["def_now"])
            and all(near(off_now[k], o["off_now"][k], 1e-9) for k in off_now)
            and all(near(def_now[k], o["def_now"][k], 1e-9) for k in def_now))
        ok[f"{stat}: spread"] = near(fit.size[stat], o["size"], 1e-6)
    for stat in ("targets", "carries"):
        sbeta, short_now, long_now, by_pos, overall = fit.share[stat]
        o = ref[stat]
        ok[f"{stat}: share fit"] = (
            np.allclose(sbeta, o["sbeta"]) and near(overall, o["overall"], 1e-12)
            and set(short_now) == set(o["short_now"])
            and all(near(short_now[k], o["short_now"][k], 1e-9) for k in short_now)
            and all(near(long_now[k], o["long_now"][k], 1e-9) for k in long_now)
            and set(by_pos) == set(o["by_pos"])
            and all(near(by_pos[k], o["by_pos"][k], 1e-9) for k in by_pos))
    ok["starter share"] = near(fit.starter_share, ref["starter_share"], 1e-12)
    return ok


def means_match(got, want):
    return {s_: bool(np.allclose(np.asarray(got[s_], dtype=float),
                                 np.asarray(want[s_], dtype=float),
                                 rtol=1e-9, atol=1e-9, equal_nan=True))
            for s_ in ("targets", "carries", "attempts")}


@section("17. the opportunity model — what it learns, by hand")
def _():
    v = pd.Series([4.0, 10.0, 8.0, 2.0, 6.0])
    g = pd.Series(["a", "b", "a", "b", "a"])
    before, now = fo.leaning_average(v, g, 2.0)
    w = 0.5 ** 0.5          # one game back, at a half-life of two games
    a2 = (w * 4.0 + 8.0) / (w + 1.0)
    a3 = (w * w * 4.0 + w * 8.0 + 6.0) / (w * w + w + 1.0)
    chk("a leaning average 'before' a game uses only that group's earlier games",
        math.isnan(before[0]) and math.isnan(before[1])
        and near(before[2], 4.0) and near(before[3], 10.0)
        and near(before[4], a2, 1e-12), list(before))
    chk("...and 'now' is the average over all of them, newest weighted most",
        near(now["a"], a3, 1e-12)
        and near(now["b"], (w * 10.0 + 2.0) / (w + 1.0), 1e-12)
        and a3 > 6.0 > now["b"])
    v2 = v.copy()
    v2[2] = 99.0
    b2, _ = fo.leaning_average(v2, g, 2.0)
    chk("a game's own number does not reach its own 'before', and does reach "
        "the next one's", near(b2[2], before[2]) and not near(b2[4], before[4]))
    chk("the fit recovers a straight line exactly",
        np.allclose(fo.ols(np.array([[0, 0], [1, 0], [0, 1], [2, 3.0]]),
                           np.array([1, 3, 4, 14.0])), [1, 2, 3])
        and np.allclose(fo.predict(np.array([1, 2, 3.0]), np.array([[2, 3.0]])), [14]))
    chk("...and predicting for nobody gives nothing, not an error",
        len(fo.predict(np.array([1, 2, 3.0]), np.zeros((0, 2)))) == 0)
    chk("a count's spread, by hand: size = sum m^2 / sum((x-m)^2 - m)",
        near(fo.size_from(np.array([0.0, 4.0]), np.array([2.0, 2.0])), 2.0))
    chk("counts no wider than a Poisson, or none at all, get the top of the "
        "range; a very wide one the bottom",
        fo.size_from(np.array([2.0, 2.0]), np.array([2.0, 2.0])) == SIZE_HI
        and fo.size_from(np.array([]), np.array([])) == SIZE_HI
        and fo.size_from(np.array([0.0, 40.0]), np.array([2.0, 2.0])) == SIZE_LO)

    f, lines = rotating_league()
    T = 202404
    h = History(f[f.t < T], T)
    fit = OpportunityModel().fit(h)
    ref = by_hand_fit(h.frame)
    for what, ok in fit_matches(fit, ref).items():
        chk(f"{what} matches a long-hand re-derivation", ok)
    chk("the fixture is worth the comparison: every spread is a measured one "
        "and not an end of the range, some expected counts fall under the "
        "cut, and starters do not throw every pass",
        all(SIZE_LO < ref[s_]["size"] < SIZE_HI
            for s_ in ("targets", "carries", "attempts"))
        and all(ref[s_]["small"] > 0 for s_ in ("targets", "carries"))
        and 0.9 < ref["starter_share"] < 1.0,
        ([ref[s_]["size"] for s_ in ("targets", "carries", "attempts")],
         ref["starter_share"]))
    chk("...and a team's own average is not its opponent's 'allowed'",
        not near(ref["targets"]["off_now"]["AAA"], ref["targets"]["def_now"]["BBB"],
                 1e-6))

    mfit = OpportunityModel("opp_market", lines=lines).fit(h)
    mref = by_hand_fit(h.frame, lines)
    for what, ok in fit_matches(mfit, mref).items():
        chk(f"with the spread and total — {what} matches too", ok)
    chk("...where the team fit has two more inputs, and they move it",
        len(mfit.team["targets"][0]) == 5 and len(fit.team["targets"][0]) == 3
        and not np.allclose(mfit.team["targets"][0][:3], fit.team["targets"][0]))

    nostart = h.frame.copy()
    nostart["qb_start"] = False
    chk("with no starter on record he is taken to throw them all",
        OpportunityModel().fit(History(nostart, T)).starter_share == 1.0)
    shuffled = History(h.frame.sample(frac=1.0, random_state=3), T)
    chk("rows handed over in any order give the same fit",
        same_fit(OpportunityModel().fit(shuffled), fit))
    ren = h.frame.copy()
    ren["game_id"] = [f"g{999999 - t_}_{'_'.join(sorted((a_, b_)))}"
                      for t_, a_, b_ in zip(ren.t, ren.team, ren.opponent)]
    by_name = ren.drop_duplicates("game_id").sort_values("game_id").t.to_numpy()
    chk("...and so do game ids whose names run backwards in time",
        (np.diff(by_name) <= 0).all() and by_name[0] > by_name[-1]
        and same_fit(OpportunityModel().fit(History(ren, T)), fit))
    nopos = h.frame.copy()
    nopos["position"] = nopos.position.where(nopos.player_id != "DDD_TE", None)
    hn = History(nopos, T)
    for what, ok in fit_matches(OpportunityModel().fit(hn),
                                by_hand_fit(hn.frame)).items():
        if "share" in what:
            chk(f"a player with no position on file is given the all-player "
                f"norm — {what} still matches", ok)

    lg = league()
    four = History(lg[lg.t <= 202304], 202305)
    three = History(lg[lg.t <= 202303], 202304)
    m3 = OpportunityModel()
    chk("sixteen team-games is enough to fit, twelve is not, and it says why",
        len(four.frame.groupby(["game_id", "team"])) == FIT_ROWS
        and OpportunityModel().fit(four).ok
        and not m3.fit(three).ok and "12 team-games" in m3.fit(three).why,
        m3.fit(three).why)

    def strangers(keep):
        """Six weeks in which nobody has an earlier game, bar `keep`
        players who have exactly one."""
        d = lg[lg.season == 2023].copy()
        regulars = sorted(set(d.player_id))[:keep]
        d["player_id"] = [p_ if p_ in regulars and w_ <= 2 else f"{p_}@{w_}"
                          for p_, w_ in zip(d.player_id, d.week)]
        return History(d, 202401)

    ms = OpportunityModel()
    chk("...and so is a history where too few players have an earlier game: "
        "sixteen such player-games fit, fifteen do not",
        OpportunityModel().fit(strangers(FIT_ROWS)).ok
        and not ms.fit(strangers(FIT_ROWS - 1)).ok
        and "15 player-games" in ms.fit(strangers(FIT_ROWS - 1)).why,
        ms.fit(strangers(FIT_ROWS - 1)).why)
    sl = fs.slate_active(lg, History(lg[lg.t < 202401], 202401))
    chk("...which then projects nothing, rather than zeros or an error",
        all(np.isnan(v_).all() for v_ in ms.means(strangers(0), sl).values())
        and math.isnan(ms.project(strangers(0), sl).point(0, "targets"))
        and math.isnan(ms.project(strangers(0), sl).p_over(0, "targets", 2.5)))


@section("18. the opportunity model — projecting a slate")
def _():
    f, lines = rotating_league()
    T = 202404
    h = History(f[f.t < T], T)
    a = fs.slate_active(f, h)
    extra = a[a.player_id == "AAA_QB"].assign(player_id="AAA_QB2", name="AAA_QB2",
                                              starting_qb=False)
    new = a[a.player_id == "AAA_WR2"].assign(player_id="NEWMAN", name="NEWMAN")
    odd = a[a.player_id == "BBB_TE"].assign(player_id="KICKER", name="KICKER",
                                            position="K")
    nopos = a[a.player_id == "DDD_TE"].assign(player_id="NOPOS", name="NOPOS",
                                              position=None)
    full = pd.concat([a, extra, new, odd, nopos], ignore_index=True)
    ref = by_hand_fit(h.frame)
    m = OpportunityModel()
    for label, slate in (("the active slate", a),
                         ("a slate with a spare quarterback, a first-game "
                          "player, a position never seen and a player with "
                          "none", full)):
        for stat, ok in means_match(m.means(h, slate),
                                    by_hand_means(ref, slate)).items():
            chk(f"{label}: expected {stat} match the long-hand ones", ok)
    mm = OpportunityModel("opp_market", lines=lines)
    for stat, ok in means_match(mm.means(h, full),
                                by_hand_means(by_hand_fit(h.frame, lines), full,
                                              lines)).items():
        chk(f"with the spread and total: expected {stat} match the long-hand "
            f"ones", ok)
    mean = m.means(h, full)
    fit = m.fit(h)
    idx = {p_: i for i, p_ in enumerate(full.player_id)}
    key = list(zip(full.game_id, full.team))
    chk("(the long-hand slate exercises what it should: a first-game player "
        "with his position's share, an unseen position and a missing one "
        "with the all-player share, a spare quarterback with no attempts)",
        mean["targets"][idx["NEWMAN"]] > 0 and "K" not in fit.share["targets"][3]
        and mean["targets"][idx["KICKER"]] > 0
        and near(mean["targets"][idx["NOPOS"]] / mean["targets"][idx["DDD_TE"]]
                 * max(float(np.array([1.0, fit.share["targets"][1]["DDD_TE"],
                                       fit.share["targets"][2]["DDD_TE"],
                                       fit.share["targets"][3]["TE"]])
                             @ fit.share["targets"][0]), 0.0),
                 fit.share["targets"][4], 1e-9)
        and math.isnan(mean["attempts"][idx["AAA_QB2"]])
        and mean["attempts"][idx["AAA_QB"]] > 15)
    for stat in fo.SHARED:
        beta, off_now, def_now, lg = fit.team[stat]
        sums = pd.Series(mean[stat]).groupby(pd.Series(key)).sum()
        opp_of = dict(zip(key, full.opponent))
        chk(f"the {stat} handed out on a team add up to the team's projected "
            f"{stat}",
            all(near(sums[k], beta[0] + beta[1] * off_now[k[1]]
                     + beta[2] * def_now[opp_of[k]], 1e-9) for k in sums.index)
            and len(set(round(v_, 6) for v_ in sums)) == len(sums))
    out = full[full.player_id != "AAA_WR1"].reset_index(drop=True)
    i2 = {p_: i for i, p_ in enumerate(out.player_id)}
    mean2 = m.means(h, out)
    chk("with a teammate off the slate, his share is handed round: the rest "
        "go up, the team total does not move, and another team is untouched",
        mean2["targets"][i2["AAA_WR2"]] > mean["targets"][idx["AAA_WR2"]] + 0.1
        and near(pd.Series(mean2["targets"]).groupby(out.team.to_numpy()).sum()["AAA"],
                 pd.Series(mean["targets"]).groupby(full.team.to_numpy()).sum()["AAA"],
                 1e-9)
        and near(mean2["targets"][i2["CCC_WR1"]], mean["targets"][idx["CCC_WR1"]]))
    chk("nobody but the named starter is given a pass attempt: no other "
        "quarterback, no receiver, nobody with no position",
        all(math.isnan(mean["attempts"][i]) != bool(full.starting_qb[i])
            for i in range(len(full)))
        and int(full.starting_qb.sum()) == 4
        and (full.position[~full.starting_qb.to_numpy()] == "QB").sum() == 1)
    wild = full.copy()
    wild.loc[wild.player_id == "CCC_QB", "starting_qb"] = False
    wild.loc[wild.player_id == "CCC_RB", "starting_qb"] = True
    wa = m.means(h, wild)["attempts"]
    chk("whoever is named the starter gets the starter's share, whatever "
        "his position; the quarterback beside him gets none",
        near(wa[idx["CCC_RB"]], mean["attempts"][idx["CCC_QB"]], 1e-9)
        and math.isnan(wa[idx["CCC_QB"]]))
    none = full.copy()
    none.loc[none.team == "AAA", "starting_qb"] = False
    na = m.means(h, none)["attempts"]
    chk("a team with no starter named: it says nothing about its "
        "quarterbacks' attempts, and other teams are untouched",
        math.isnan(na[idx["AAA_QB"]]) and math.isnan(na[idx["AAA_QB2"]])
        and near(na[idx["CCC_QB"]], mean["attempts"][idx["CCC_QB"]], 1e-12))
    twice = pd.concat([full, full[full.player_id == "BBB_WR1"]], ignore_index=True)
    chk("a player on the slate twice for one team is refused by name, not "
        "given two shares",
        raises(lambda: m.means(h, twice), ValueError, "BBB_WR1")
        and raises(lambda: m.means(h, pd.concat(
            [full, full[full.player_id == "CCC_QB"]], ignore_index=True)),
            ValueError, "twice"))
    two = full.copy()
    two.loc[two.player_id == "AAA_QB2", "starting_qb"] = True
    chk("two starters named for one team is refused, and names the team",
        raises(lambda: m.means(h, two), ValueError, "AAA"))
    blank = full.copy()
    blank["starting_qb"] = blank.starting_qb.astype(object)
    blank.loc[blank.player_id == "AAA_RB", "starting_qb"] = None
    chk("a starter flag that is neither yes nor no is refused, not read as yes",
        raises(lambda: m.means(h, blank), ValueError, "starting_qb"))
    chk("a slate missing a column is refused by name, thin history or not",
        raises(lambda: m.means(h, full.drop(columns=["starting_qb"])),
               ValueError, "starting_qb")
        and raises(lambda: m.means(History(f[f.t < 202302], 202302),
                                   full.drop(columns=["opponent"])),
                   ValueError, "opponent"))
    empty = m.means(h, a.iloc[:0])
    chk("an empty slate gets an empty answer",
        set(empty) == set(fo.OPP_STATS) and all(len(v_) == 0 for v_ in empty.values()))
    alone = full[full.player_id == "NEWMAN"].reset_index(drop=True)
    beta, off_now, def_now, lg = fit.team["targets"]
    chk("a slate of nobody but a new player gives him the whole team",
        near(m.means(h, alone)["targets"][0],
             beta[0] + beta[1] * off_now["AAA"]
             + beta[2] * def_now[alone.opponent[0]], 1e-9))

    z = full.copy()
    z.loc[z.team == "CCC", "team"] = "ZZZ"
    z.loc[z.opponent == "CCC", "opponent"] = "ZZZ"
    zt = pd.Series(m.means(h, z)["targets"]).groupby(z.team.to_numpy()).sum()
    other = z[z.opponent == "ZZZ"].team.iloc[0]
    chk("a team with no earlier game is given the league's average volume",
        near(zt["ZZZ"], beta[0] + beta[1] * lg + beta[2] * def_now[other], 1e-9),
        zt.to_dict())
    chk("...and its opponent the league's average allowed",
        near(zt[other], beta[0] + beta[1] * off_now[other] + beta[2] * lg, 1e-9))

    low = OpportunityModel()
    lf = low.fit(h)
    lf.team["carries"] = (np.array([-50.0, 0.0, 0.0]),) + lf.team["carries"][1:]
    chk("a team's projected volume never falls below one play",
        np.allclose(pd.Series(low.means(h, full)["carries"])
                    .groupby(full.team.to_numpy()).sum(), FLOOR))
    neg = OpportunityModel()
    nf = neg.fit(h)
    nf.share["targets"] = (np.array([-0.2, 1.0, 0.0, 0.0]),) + nf.share["targets"][1:]
    nm = neg.means(h, full)["targets"]
    chk("a share the fit puts below zero is zero, and the rest still add up",
        nm[idx["AAA_TE"]] == 0.0 and (nm >= 0).all() and nm[idx["AAA_WR1"]] > 0
        and np.allclose(pd.Series(nm).groupby(pd.Series(key)).sum().sort_index(),
                        pd.Series(mean["targets"]).groupby(pd.Series(key)).sum()
                        .sort_index()), nm[:6].tolist())
    NP = neg.project(h, full)
    chk("...and a player expected to get none is priced at none",
        NP.point(idx["AAA_TE"], "targets") == 0.0
        and NP.p_over(idx["AAA_TE"], "targets", 0.5) == 0.0)
    zero = OpportunityModel()
    zf = zero.fit(h)
    zf.share["targets"] = (np.array([-1.0, 0.0, 0.0, 0.0]),) + zf.share["targets"][1:]
    zm = zero.means(h, full)["targets"]
    chk("a team none of whose players is given any share gets no projection, "
        "not zeros; a team with one new player gives him everything",
        all(math.isnan(zm[i]) for i in range(len(full)) if full.team[i] == "CCC")
        and near(zm[idx["NEWMAN"]],
                 float(np.nansum(mean["targets"][full.team.to_numpy() == "AAA"])),
                 1e-9)
        and zm[idx["AAA_WR1"]] == 0.0, zm[idx["NEWMAN"]])

    # ---- the count round the mean
    P = m.project(h, full)
    size = fit.size
    priced = [(idx["AAA_WR1"], "targets", 6.5), (idx["AAA_WR1"], "targets", 2.5),
              (idx["CCC_RB"], "carries", 14.5), (idx["CCC_RB"], "carries", 6.5),
              (idx["BBB_QB"], "attempts", 30.5), (idx["BBB_QB"], "attempts", 22.5)]
    chk("the chance of a line is the count's chance of MORE than it, each "
        "stat with its own spread — summed from the formula",
        all(near(P.p_over(i, s_, ln), nb_tail(ln, mean[s_][i], size[s_]), 1e-9)
            for i, s_, ln in priced)
        and len({round(size[s_], 6) for s_ in fo.OPP_STATS}) == 3,
        [(P.p_over(i, s_, ln), nb_tail(ln, mean[s_][i], size[s_]))
         for i, s_, ln in priced][:2])
    i = idx["AAA_WR1"]
    chk("landing exactly on a whole-number line is not over it",
        near(P.p_over(i, "targets", 6.0), nb_tail(6, mean["targets"][i],
                                                  size["targets"]), 1e-9)
        and P.p_over(i, "targets", 6.0) == P.p_over(i, "targets", 6.5)
        and P.p_over(i, "targets", 6.0) < P.p_over(i, "targets", 5.5)
        and P.p_over(i, "targets", -0.5) == 1.0)
    chk("its single number is the expected count",
        all(P.point(j, s_) == mean[s_][j] for j, s_, _ in priced))
    PM = OpportunityModel("opp_median", single="median").project(h, full)
    med = [PM.point(j, s_) for j, s_, _ in priced]
    chk("...or, when asked, the count's median: the smallest whole number he "
        "is at least as likely to stay at or under as to beat",
        all(v_ == int(v_)
            and nb_tail(v_, mean[s_][j], size[s_]) <= 0.5
            < nb_tail(v_ - 1, mean[s_][j], size[s_])
            for v_, (j, s_, _) in zip(med, priced))
        and all(PM.p_over(j, s_, ln) == P.p_over(j, s_, ln) for j, s_, ln in priced)
        and any(v_ != mean[s_][j] for v_, (j, s_, _) in zip(med, priced)), med)
    chk("...and no third thing",
        raises(lambda: OpportunityModel(single="mode"), ValueError, "single"))
    chk("it says nothing about catches, yards or touchdowns",
        all(math.isnan(P.point(i, s_)) and math.isnan(P.p_over(i, s_, 0.5))
            for s_ in ("receptions", "receiving_yards", "rushing_yards",
                       "passing_yards", TD_STAT, "completions", "passing_tds")))
    chk("...nor a pass-attempt line for a receiver",
        math.isnan(P.p_over(i, "attempts", 20.5)) and math.isnan(P.point(i, "attempts")))
    top = int(mean["targets"][i] * 60) + 200
    chk("the chances it states add up to the count it expects: the sum over "
        "every whole number of 'more than that' is the mean",
        all(near(sum(P.p_over(j, s_, k_ + 0.5) for k_ in range(top)),
                 mean[s_][j], 1e-6) for j, s_, _ in priced[::2]),
        [sum(P.p_over(j, s_, k_ + 0.5) for k_ in range(top)) - mean[s_][j]
         for j, s_, _ in priced[::2]])

    # ---- one fit per history, and never another history's
    first = m.means(h, a)["targets"].copy()
    h3 = History(f[f.t < 202403], 202403)
    s3 = fs.slate_active(f, h3)
    fresh3 = OpportunityModel().means(h3, s3)["targets"]
    chk("a model that has fitted one history answers another exactly as a "
        "fresh model does", np.array_equal(m.means(h3, s3)["targets"], fresh3,
                                           equal_nan=True))
    chk("...and the first again exactly as before",
        np.array_equal(first, m.means(History(f[f.t < T], T), a)["targets"],
                       equal_nan=True))
    changed = f[f.t < T].copy()
    changed.loc[changed.player_id == "AAA_WR1", "targets"] *= 0.5
    hc = History(changed, T)
    used = OpportunityModel()
    used.means(h, a)
    chk("...and two histories that stop at the SAME week are still two "
        "histories",
        np.array_equal(used.means(hc, a)["targets"],
                       OpportunityModel().means(hc, a)["targets"], equal_nan=True)
        and not np.allclose(used.means(hc, a)["targets"], first, equal_nan=True))

    # ---- through the harness
    lgf = league(extra=[row(2024, 4, "AAA", "BBB", "NEWMAN", "WR", targets=9)])
    run = fs.walk_forward(lgf, [OpportunityModel(), fs.LastFour()],
                          weeks=[202403, T])
    chk("through the harness its numbers differ between the two slates",
        fs.version_gap(run, "opportunity") > 0)
    L = run.legs[(run.legs.version == "A")]
    chk("it prices targets, carries and pass attempts, and leaves the rest blank",
        L[L.stat.isin(fo.OPP_STATS)].p_opportunity.notna().all()
        and L[~L.stat.isin(fo.OPP_STATS)].p_opportunity.isna().all()
        and L.stat.isin(fo.OPP_STATS).sum() > 20)
    hw = run.points[(run.points.version == "A") & (run.points.player_id == "AAA_WR1")
                    & (run.points.stat == "targets") & (run.points.week == 4)]
    hh = History(lgf[lgf.t < T], T)
    want = by_hand_means(by_hand_fit(hh.frame), fs.slate_active(lgf, hh))
    at = list(fs.slate_active(lgf, hh).player_id).index("AAA_WR1")
    chk("...and the number the harness records for the hand-worked receiver "
        "is the long-hand one", len(hw) == 1
        and near(float(hw.pt_opportunity.iloc[0]), want["targets"][at], 1e-9),
        (hw.pt_opportunity.tolist(), want["targets"][at]))
    probe = fs.leak_probe(lgf, [OpportunityModel()], [202403, T])
    chk("the leak probe finds nothing reaching it through the harness",
        probe.clean and probe.outputs["opportunity"] > 100,
        probe.describe()[:120])


@section("19. the opportunity model — the closing spread and total")
def _():
    f, lines = rotating_league()
    T = 202404
    h = History(f[f.t < T], T)
    a = fs.slate_active(f, h)
    lines = dict(lines)
    lines["2031_01_AAA_BBB"] = ("AAA", "BBB", 7.0, 50.0)    # not yet played
    m = OpportunityModel("opp_market", lines=lines)
    g1 = a.game_id[0]
    home, away, spread, total = lines[g1]
    mk = m._market([g1, g1], [home, away], {g1})
    chk("the spread is in the HOME team's favour for it and against the "
        "visitor; the total is the same for both",
        mk.shape == (2, 2) and spread != 0 and mk[0, 0] == spread
        and mk[1, 0] == -spread and mk[0, 1] == mk[1, 1] == total, mk.tolist())
    chk("a team that did not play in the game is refused, not signed as "
        "the visitor", raises(lambda: m._market([g1], ["QQQ"], {g1}), ValueError,
                              "QQQ"))
    chk("with no lines it adds no column",
        OpportunityModel()._market([g1], [home], {g1}).shape == (1, 0))
    chk("a game neither in the history nor on the slate is refused",
        raises(lambda: m._market(["2031_01_AAA_BBB"], ["AAA"], {g1}), LeakError,
               "2031_01_AAA_BBB"))
    chk("a game with no line on file is an error that names it, not a zero",
        raises(lambda: m._market(["2024_09_AAA_BBB"], ["AAA"],
                                 {"2024_09_AAA_BBB"}), KeyError, "2024_09_AAA_BBB"))
    chk("...and an EMPTY table of lines is not the same as no lines",
        raises(lambda: OpportunityModel("x", lines={}).means(h, a), KeyError))
    for what, bad in (("spread", (home, away, float("nan"), total)),
                      ("total", (home, away, spread, float("nan")))):
        holed = dict(lines)
        holed[g1] = bad
        chk(f"a line whose {what} is not a number stops it, on the slate's "
            f"game", raises(lambda: OpportunityModel("x", lines=holed).means(h, a),
                            ValueError, g1))
    asked = []
    real = m._market

    def spy(game_ids, teams, allowed):
        asked.append((set(game_ids), set(allowed)))
        return real(game_ids, teams, allowed)

    m2 = OpportunityModel("opp_market", lines=lines)
    m2._market = spy
    mean = m2.means(h, a)
    hist_games, slate_games = set(h.frame.game_id), set(a.game_id)
    chk("fitting looks up the history's games and nothing else",
        asked[0][0] == hist_games and asked[0][1] == hist_games)
    chk("...and projecting the slate's games, with the history's allowed",
        asked[1][0] == slate_games and asked[1][1] == hist_games | slate_games
        and len(asked) == 2)
    moved = dict(lines)
    for g_ in slate_games:
        hm, aw, sp, tt = moved[g_]
        moved[g_] = (hm, aw, sp + 7.0, tt)
    later = dict(lines)
    later["2031_01_AAA_BBB"] = ("AAA", "BBB", -20.0, 70.0)
    chk("this week's line moves this week's projection; a later game's "
        "line does not",
        not np.allclose(OpportunityModel("x", lines=moved).means(h, a)["targets"],
                        mean["targets"])
        and np.array_equal(OpportunityModel("x", lines=later).means(h, a)["targets"],
                           mean["targets"]))
    run = fs.walk_forward(f, [m], weeks=[202403, T])
    chk("it runs through the harness with them",
        run.legs.p_opp_market.notna().sum() > 20)

    def loaded(spread_g2=-2.0, total_g2=41.0, spread_g3=1.0):
        """`closing_lines` on a made-up play-by-play, or the error it raised."""
        def load(years, columns=None):
            return pd.DataFrame(dict(
                game_id=["g1", "g1", "g2", "g3"],
                season_type=["REG", "REG", "REG", "POST"],
                home_team=["H1", "H1", "H2", "H3"],
                away_team=["A1", "A1", "A2", "A3"],
                spread_line=[3.5, 3.5, spread_g2, spread_g3],
                total_line=[44.5, 44.5, total_g2, 50.0]))
        real_load = fo.ff_data.load_pbp
        fo.ff_data.load_pbp = load
        try:
            return fo.closing_lines([2024])
        except Exception as e:                      # noqa: BLE001
            return e
        finally:
            fo.ff_data.load_pbp = real_load

    got = loaded()
    chk("the lines table is one entry per regular-season game: home, "
        "visitor, spread, total",
        got == {"g1": ("H1", "A1", 3.5, 44.5), "g2": ("H2", "A2", -2.0, 41.0)}, got)
    chk("a regular-season game with no spread stops the load",
        isinstance(loaded(spread_g2=float("nan")), ValueError))
    chk("...and so does one with no total",
        isinstance(loaded(total_g2=float("nan")), ValueError))
    chk("...a postseason one, which is never graded, does not",
        loaded(spread_g3=float("nan")) == got)

    frame = REAL.get("frame")
    if frame is None:
        frame = fs.load_frame()
    cl = fo.closing_lines(sorted(int(y) for y in frame.season.unique()))
    games = set(frame.game_id)
    chk("on real data every game in the frame has a closing line",
        games <= set(cl) and len(games) > 900, len(games - set(cl)))
    pairs = frame.drop_duplicates(["game_id", "team"])
    chk("...whose two sides are the two teams the frame has playing it, in "
        "EVERY game",
        all(tm in cl[g_][:2] for g_, tm in zip(pairs.game_id, pairs.team))
        and all(cl[g_][0] != cl[g_][1] for g_ in games))
    chk("...with plausible numbers",
        all(-25 < cl[g_][2] < 25 and 25 < cl[g_][3] < 70 for g_ in games))
    pbp = fo.ff_data.load_pbp(sorted(int(y) for y in frame.season.unique()),
                              columns=["game_id", "home_score", "away_score"])
    fin = pbp.drop_duplicates("game_id").set_index("game_id")
    fav = [(cl[g_][2], fin.home_score[g_] - fin.away_score[g_]) for g_ in games
           if abs(cl[g_][2]) >= 3]
    won = float(np.mean([(s_ > 0) == (d_ > 0) for s_, d_ in fav if d_ != 0]))
    chk("...and a positive spread does mean the HOME team is favoured: "
        "sides favoured by a field goal or more win well over half",
        len(fav) > 400 and 0.6 < won < 0.9, (len(fav), won))
    weeks = fs.test_weeks(frame)[-2:]
    rr = fs.walk_forward(frame, [OpportunityModel(),
                                 OpportunityModel("opp_market", lines=cl)],
                         weeks=weeks)
    ra = rr.legs[(rr.legs.version == "A") & rr.legs.stat.isin(fo.OPP_STATS)]
    v = ra[["p_opportunity", "p_opp_market"]].to_numpy(dtype=float)
    chk("on real weeks both versions price every opportunity leg, between "
        "0 and 1", not np.isnan(v).any() and v.min() >= 0 and v.max() <= 1
        and len(ra) > 1000, len(ra))
    h_real = History(frame[frame.t < weeks[-1]], weeks[-1])
    sa = fs.slate_active(frame, h_real)
    mm = OpportunityModel().means(h_real, sa)
    tt = pd.Series(mm["targets"]).groupby(sa.team.to_numpy()).sum()
    chk("a real team's projected targets are a real team's targets",
        tt.between(18, 48).all() and 26 < tt.mean() < 38, tt.describe().to_dict())
    qa = mm["attempts"][sa.starting_qb.to_numpy()]
    chk("...and a real starter's projected pass attempts likewise",
        len(qa) >= 20 and (qa > 18).all() and (qa < 48).all(), (qa.min(), qa.max()))
    sizes = OpportunityModel().fit(h_real).size
    chk("...and on real history every spread is a measured one",
        all(SIZE_LO < sizes[s_] < SIZE_HI for s_ in fo.OPP_STATS), sizes)
    pr = fs.leak_probe(frame, [OpportunityModel(),
                               OpportunityModel("opp_market", lines=cl)], weeks[-1:])
    chk("the leak probe finds nothing reaching either through the harness, "
        "on real data (it cannot see the lines)", pr.clean, pr.describe()[:120])


@section("20. the opportunity model — its expected counts beside what happened")
def _():
    f, _ = rotating_league()
    T = 202404
    weeks = [202403, T]
    m = OpportunityModel()
    ea = fo.expected_vs_actual(m, f, weeks)
    h = History(f[f.t < T], T)
    a = fs.slate_active(f, h)
    mean = m.means(h, a)
    size = m.fit(h).size
    e4 = ea[ea.t == T]
    chk("one row per slate player and stat he is given a number for, each "
        "week asked",
        set(ea.t) == set(weeks)
        and all(len(e4[e4.stat == s_]) == int(np.isfinite(mean[s_]).sum())
                for s_ in fo.OPP_STATS)
        and (e4.stat == "attempts").sum() == int((a.position == "QB").sum()),
        e4.stat.value_counts().to_dict())
    ok_e = ok_a = ok_v = ok_g = True
    for s_ in fo.OPP_STATS:
        d = e4[e4.stat == s_].set_index("player_id")
        for i, r in enumerate(a.itertuples()):
            if not np.isfinite(mean[s_][i]):
                continue
            x = float(f[(f.t == T) & (f.player_id == r.player_id)][s_].iloc[0])
            ok_e &= near(d.expected[r.player_id], mean[s_][i], 1e-12)
            ok_a &= d.actual[r.player_id] == x
            ok_v &= near(d.variance[r.player_id],
                         mean[s_][i] + mean[s_][i] ** 2 / size[s_], 1e-9)
            ok_g &= d.game_id[r.player_id] == r.game_id
    chk("...the expected count is the model's mean for that week", ok_e)
    chk("...the actual is what he did THAT week, in that stat", ok_a
        and len({tuple(e4[e4.stat == s_].actual.round(3)) for s_ in fo.SHARED}) == 2)
    chk("...the variance is the count's own: mean + mean^2 / size, with "
        "that stat's size", ok_v)
    chk("...and the game is his game", ok_g and e4.game_id.nunique() == 2)
    e3 = ea[(ea.t == 202403) & (ea.stat == "targets")].set_index("player_id")
    x3 = float(f[(f.t == 202403) & (f.player_id == "AAA_WR1")].targets.iloc[0])
    h3 = History(f[f.t < 202403], 202403)
    s3 = fs.slate_active(f, h3)
    chk("...and the earlier week is fitted on ITS history and graded on ITS "
        "result",
        e3.actual["AAA_WR1"] == x3
        and near(e3.expected["AAA_WR1"],
                 OpportunityModel().means(h3, s3)["targets"]
                 [list(s3.player_id).index("AAA_WR1")], 1e-12))

    sat = f[~((f.t == T) & (f.player_id == "AAA_WR2"))]
    hs = History(sat[sat.t < T], T)
    on_a, on_b = fs.slate_active(sat, hs), fs.slate_candidates(sat, hs)
    es = fo.expected_vs_actual(OpportunityModel(), sat, [T])
    et = es[es.stat == "targets"].set_index("player_id")
    chk("it is graded on the slate of who was ACTIVE: a regular who sat out "
        "is not in it, and his share has gone to the others",
        "AAA_WR2" in set(on_b.player_id) and "AAA_WR2" not in set(on_a.player_id)
        and "AAA_WR2" not in set(es.player_id) and es.actual.notna().all()
        and near(et.expected["AAA_WR1"],
                 OpportunityModel().means(hs, on_a)["targets"]
                 [list(on_a.player_id).index("AAA_WR1")], 1e-12)
        and et.expected["AAA_WR1"] > e4[e4.stat == "targets"]
        .set_index("player_id").expected["AAA_WR1"] + 0.1)

    run = fs.walk_forward(f, [OpportunityModel(), fs.LastFour()], weeks=weeks)
    wl = fo.with_main_line(run, ea, "opportunity")
    L = run.legs[(run.legs.version == "A") & (run.legs.rung == fs.MAIN)
                 & run.legs.stat.isin(fo.OPP_STATS)]
    chk("players with a main line: one row for each such leg, actives known",
        len(wl) == len(L) > 10 and set(wl.stat) == set(fo.OPP_STATS),
        (len(wl), len(L)))
    k = L.set_index(["game_id", "player_id", "stat"])
    e = ea.set_index(["game_id", "player_id", "stat"])
    chk("...carrying that leg's line, result and stated chance, and that "
        "player's expected count",
        all(k.line[(r.game_id, r.player_id, r.stat)] == r.line
            and k.actual[(r.game_id, r.player_id, r.stat)] == r.actual
            and bool(k["over"][(r.game_id, r.player_id, r.stat)]) == r.over
            and (r.actual > r.line) == r.over
            and near(k.p_opportunity[(r.game_id, r.player_id, r.stat)], r.said, 1e-12)
            and near(e.expected[(r.game_id, r.player_id, r.stat)], r.expected, 1e-12)
            for r in wl.itertuples()))
    bad = ea.copy()
    bad.loc[(bad.stat == wl.stat[0]) & (bad.player_id == wl.player_id[0])
            & (bad.game_id == wl.game_id[0]), "actual"] += 1.0
    chk("...and it stops if a result does not agree between the two",
        raises(lambda: fo.with_main_line(run, bad, "opportunity"), RuntimeError,
               "line up"))
    who = wl.player_id[0]
    part = fs.Run(points=run.points, names=run.names, weeks=run.weeks,
                  legs=run.legs.assign(p_opportunity=run.legs.p_opportunity.where(
                      run.legs.player_id != who)))
    wp = fo.with_main_line(part, ea, "opportunity")
    chk("...a leg the projector did not price is left out, not carried blank",
        len(wp) == len(wl) - int((wl.player_id == who).sum()) < len(wl)
        and who not in set(wp.player_id) and wp.said.notna().all())
    chk("...the same player twice in the expected counts is refused, not "
        "counted twice",
        raises(lambda: fo.with_main_line(run, pd.concat([ea, ea]), "opportunity"),
               Exception, "one-to-one"))
    w4 = fo.with_main_line(run, ea, "last4_avg")
    chk("...and for another projector it is still only targets, carries and "
        "pass attempts, with that projector's stated chance",
        len(w4) == len(wl) and set(w4.stat) == set(fo.OPP_STATS)
        and not np.allclose(w4.said, wl.said)
        and np.array_equal(w4.expected, wl.expected))
    chk("a week too thin to fit gives no rows, not an error",
        len(fo.expected_vs_actual(OpportunityModel(), f, [202302])) == 0)
    chk("...or if a lined player has no expected count",
        raises(lambda: fo.with_main_line(
            run, ea[ea.player_id != wl.player_id[0]], "opportunity"),
            RuntimeError, "line up"))


# ===========================================================================
# S17 — efficiency (ff_sim_eff.py)
# ===========================================================================
fe = EfficiencyModel = None


@section("21. efficiency — it loads")
def _():
    global fe, EfficiencyModel
    import ff_sim_eff
    fe, EfficiencyModel = ff_sim_eff, ff_sim_eff.EfficiencyModel
    chk("it gives a number for the three opportunities, two counts and three "
        "yardages, and nothing else",
        fe.EFF_STATS == ("targets", "carries", "attempts", "receptions",
                         "completions", "receiving_yards", "rushing_yards",
                         "passing_yards"))


# The test's OWN typed copy of what the model sets by hand and of which
# column is divided by which.
HL_RATE, RATE_ROWS, SPREAD_UNITS, YFLOOR = 16.0, 16, 200.0, 0.1
GRID = (2.0, 5.0, 10.0, 20.0, 40.0, 80.0, 160.0, 320.0, 640.0, 1280.0)
RATE_COLS = {"catch": ("receptions", "targets"),
             "yards_per_catch": ("receiving_yards", "receptions"),
             "yards_per_carry": ("rushing_yards", "carries"),
             "completion": ("completions", "attempts"),
             "yards_per_attempt": ("passing_yards", "attempts")}
YARD_RATES = ("yards_per_catch", "yards_per_carry", "yards_per_attempt")


def eff_league():
    """(frame, lines): the rotating league with catches, completions and
    yards DRAWN on top of its targets, carries and attempts. Receivers and
    teams differ in how well they catch and how far they go; a few rushing
    totals are negative."""
    f, lines = rotating_league()
    rng = np.random.default_rng(11)
    catch = dict(WR1=0.68, WR2=0.55, TE=0.72, RB=0.80, QB=0.5, QB2=0.5)
    far = dict(WR1=14.0, WR2=10.0, TE=8.0, RB=6.5, QB=5.0, QB2=5.0)
    run_ = dict(RB=4.4, QB=5.5, WR1=7.0, WR2=7.0, TE=3.0, QB2=4.0)

    def yards(n, each, shape):
        return float(np.round(rng.gamma(shape, each / shape, int(n)).sum()))

    for i in f.index:
        role = f.at[i, "player_id"].split("_")[1]
        up = TEAM_LEAN[f.at[i, "team"]]
        rec = float(rng.binomial(int(f.at[i, "targets"]),
                                 min(catch[role] * (0.8 + 0.2 * up), 0.95)))
        f.at[i, "receptions"] = rec
        f.at[i, "receiving_yards"] = yards(rec, far[role] * up, 1.3)
        f.at[i, "rushing_yards"] = (yards(f.at[i, "carries"],
                                          run_[role] * (2.4 * up - 1.4), 0.7)
                                    - (3.0 if i % 7 == 0 and f.at[i, "carries"] else 0.0))
        comp = float(rng.binomial(int(f.at[i, "attempts"]), 0.56 + 0.08 * up))
        f.at[i, "completions"] = comp
        f.at[i, "passing_yards"] = yards(comp, 10.0 + 2.0 * up, 1.1)
    # yards with no catch and no carry behind them: a lateral, a fumble
    lat = (f.t == 202303) & (f.player_id == "BBB_RB")
    f.loc[lat, ["receptions", "receiving_yards"]] = [0.0, 7.0]
    f.loc[(f.t == 202305) & (f.player_id == "CCC_WR2"), ["carries", "rushing_yards"]] = [0.0, 4.0]
    return f, lines


def by_hand_eff(F):
    """Everything the efficiency model learns from a history, with plain
    loops, from the description in its docstring."""
    w = 0.5 ** (1.0 / HL_RATE)
    rows = list(F.sort_values(["player_id", "t"], kind="stable").itertuples())
    out = {}
    for rate, (nc, dc) in RATE_COLS.items():
        overall = (sum(getattr(r, nc) for r in rows)
                   / sum(getattr(r, dc) for r in rows))
        pn, pd_ = {}, {}
        for r in rows:
            if r.position is not None:
                pn[r.position] = pn.get(r.position, 0.0) + getattr(r, nc)
                pd_[r.position] = pd_.get(r.position, 0.0) + getattr(r, dc)
        by_pos = {q: pn[q] / pd_[q] for q in pn if pd_[q] > 0}
        before, num_now, den_now, cur = [], {}, {}, object()
        for r in rows:
            if r.player_id != cur:
                cur, sn, sd = r.player_id, 0.0, 0.0
            before.append((sn, sd))
            sn, sd = w * sn + getattr(r, nc), w * sd + getattr(r, dc)
            num_now[cur], den_now[cur] = sn, sd
        used = [(getattr(r, nc), getattr(r, dc), b, by_pos.get(r.position, overall),
                 r.position) for r, b in zip(rows, before) if getattr(r, dc) > 0]
        miss = {k: sum((x - d * ((bn + k * nm) / (bd + k))) ** 2
                       for x, d, (bn, bd), nm, _ in used) for k in GRID}
        k = min(GRID, key=lambda v: (miss[v], v))
        o = dict(k=k, overall=overall, by_pos=by_pos, num_now=num_now,
                 den_now=den_now, rows=len(used), miss=miss)
        if rate in YARD_RATES:
            sq, un = {}, {}
            for x, d, (bn, bd), nm, q in used:
                sq[q] = sq.get(q, 0.0) + (x - d * ((bn + k * nm) / (bd + k))) ** 2
                un[q] = un.get(q, 0.0) + d
            o["spread"] = {q: sq[q] / un[q] for q in sq
                           if q is not None and un[q] >= SPREAD_UNITS}
            o["spread_all"] = sum(sq.values()) / sum(un.values())
            o["units"] = un
        out[rate] = o
    return out


def by_hand_parts(F, slate, lines=None):
    """Expected numbers, the spread underneath and the variance for a slate,
    from the two by-hand fits."""
    opp = by_hand_fit(F, lines)
    eff = by_hand_eff(F)
    om = by_hand_means(opp, slate, lines)
    rows = list(slate.itertuples())

    def rate(name, r):
        o = eff[name]
        v = ((o["num_now"].get(r.player_id, 0.0)
              + o["k"] * o["by_pos"].get(r.position, o["overall"]))
             / (o["den_now"].get(r.player_id, 0.0) + o["k"]))
        return max(v, YFLOOR) if name in YARD_RATES else v

    def spread(name, r):
        return eff[name]["spread"].get(r.position, eff[name]["spread_all"])

    mean = {s_: list(om[s_]) for s_ in ("targets", "carries", "attempts")}
    mean["receptions"] = [m * rate("catch", r) for m, r in zip(om["targets"], rows)]
    mean["completions"] = [m * rate("completion", r)
                           for m, r in zip(om["attempts"], rows)]
    size = {s_: opp[s_]["size"] for s_ in ("targets", "carries", "attempts")}
    size.update(receptions=size["targets"], completions=size["attempts"],
                receiving_yards=size["targets"], rushing_yards=size["carries"],
                passing_yards=size["attempts"])
    unit, var = {}, {}
    for stat, count, name in (("receiving_yards", "receptions", "yards_per_catch"),
                              ("rushing_yards", "carries", "yards_per_carry"),
                              ("passing_yards", "attempts", "yards_per_attempt")):
        unit[stat] = [(rate(name, r), spread(name, r)) for r in rows]
        mean[stat] = [c * u[0] for c, u in zip(mean[count], unit[stat])]
        var[stat] = [c * u[1] + u[0] ** 2 * (c + c * c / size[stat])
                     for c, u in zip(mean[count], unit[stat])]
    for stat in ("targets", "carries", "attempts", "receptions", "completions"):
        var[stat] = [m + m * m / size[stat] for m in mean[stat]]
    return dict(mean=mean, size=size, unit=unit, var=var, eff=eff)


def same(a, b, tol=1e-9):
    return bool(np.allclose(np.asarray(a, dtype=float), np.asarray(b, dtype=float),
                            rtol=tol, atol=tol, equal_nan=True))


def erlang_tail(x, k):
    """P(a sum of k unit exponentials > x), from its formula."""
    term, total = 1.0, 0.0
    for j in range(k):
        total += term
        term *= x / (j + 1)
    return math.exp(-x) * total


def nb_pmf(j, mean, size):
    p = size / (size + mean)
    return math.exp(math.lgamma(j + size) - math.lgamma(j + 1) - math.lgamma(size)
                    + size * math.log(p) + j * math.log1p(-p))


@section("22. efficiency — what it learns, by hand")
def _():
    v = pd.Series([4.0, 10.0, 8.0, 2.0, 6.0])
    g = pd.Series(["a", "b", "a", "b", "a"])
    before, now = fe.leaning_sum(v, g, 2.0)
    w = 0.5 ** 0.5
    chk("a leaning total 'before' a game is that group's earlier games, the "
        "newest at full weight; nothing before his first",
        before[0] == 0.0 and before[1] == 0.0 and near(before[2], 4.0)
        and near(before[3], 10.0) and near(before[4], w * 4.0 + 8.0, 1e-12),
        list(before))
    chk("...and 'now' takes in every game he has",
        near(now["a"], w * w * 4.0 + w * 8.0 + 6.0, 1e-12)
        and near(now["b"], w * 10.0 + 2.0, 1e-12))
    chk("a rate pulled toward the position, by hand: 3 of 5 with a pull of 10 "
        "toward 0.9 is 12 of 15",
        near(fe.pulled(3.0, 5.0, 0.9, 10.0), 0.8, 1e-12)
        and near(fe.pulled(0.0, 0.0, 0.9, 10.0), 0.9, 1e-12))

    f, lines = eff_league()
    T = 202404
    h = History(f[f.t < T], T)
    fit = EfficiencyModel().fit(h)
    ref = by_hand_eff(h.frame)
    for rate in RATE_COLS:
        r, o = fit.rate[rate], ref[rate]
        chk(f"{rate}: the pull it picks, the position rates and the all-player "
            f"rate match a long-hand re-derivation",
            r["k"] == o["k"] and near(r["overall"], o["overall"], 1e-12)
            and tuple(r["miss"]) == GRID
            and all(near(r["miss"][k_] / o["miss"][k_], 1.0, 1e-9) for k_ in GRID)
            and set(r["by_pos"]) == set(o["by_pos"])
            and all(near(r["by_pos"][q], o["by_pos"][q], 1e-12) for q in o["by_pos"]),
            (r["k"], o["k"]))
        chk(f"{rate}: every player's leaning totals match it",
            set(r["num_now"]) == set(o["num_now"])
            and all(near(r["num_now"][q], o["num_now"][q], 1e-9)
                    and near(r["den_now"][q], o["den_now"][q], 1e-9)
                    for q in o["num_now"]))
        if rate in YARD_RATES:
            chk(f"{rate}: the spread of one catch, carry or attempt matches "
                f"it, by position and over all",
                set(r["spread"]) == set(o["spread"])
                and all(near(r["spread"][q], o["spread"][q], 1e-6)
                        for q in o["spread"])
                and near(r["spread_all"], o["spread_all"], 1e-6),
                (r["spread"], o["spread"]))
        else:
            chk(f"{rate}: a rate that is not yards has no spread of its own",
                "spread" not in r and "spread_all" not in r)
    ks = [ref[r_]["k"] for r_ in RATE_COLS]
    chk("the fixture is worth the comparison: the pulls picked differ and "
        "none sits at an end of the list; the list's two ends would each "
        "have been a worse pick; one position has its own spread and "
        "another is too thin to",
        len(set(ks)) > 1 and all(GRID[0] < k_ < GRID[-1] for k_ in ks)
        and all(ref[r_]["miss"][ref[r_]["k"]] < min(ref[r_]["miss"][GRID[0]],
                                                    ref[r_]["miss"][GRID[-1]])
                for r_ in RATE_COLS)
        and "WR" in ref["yards_per_catch"]["spread"]
        and "TE" not in ref["yards_per_catch"]["spread"]
        and 0 < ref["yards_per_catch"]["units"]["TE"] < SPREAD_UNITS, ks)

    nopos = h.frame.copy()
    nopos["position"] = nopos.position.where(nopos.player_id != "DDD_TE", None)
    hn = History(nopos, T)
    fn, rn = EfficiencyModel().fit(hn), by_hand_eff(hn.frame)
    chk("a player with no position on file is judged against the all-player "
        "rate: the pull, every position's rate and every spread still match "
        "the long-hand ones",
        all(fn.rate[r_]["k"] == rn[r_]["k"]
            and set(fn.rate[r_]["by_pos"]) == set(rn[r_]["by_pos"])
            and all(near(fn.rate[r_]["by_pos"][q], rn[r_]["by_pos"][q], 1e-12)
                    for q in rn[r_]["by_pos"])
            and all(near(fn.rate[r_]["miss"][k_] / rn[r_]["miss"][k_], 1.0, 1e-9)
                    for k_ in GRID)
            and set(fn.rate[r_].get("spread", {})) == set(rn[r_].get("spread", {}))
            and near(fn.rate[r_].get("spread_all", 0.0),
                     rn[r_].get("spread_all", 0.0), 1e-6) for r_ in RATE_COLS)
        and fn.rate["catch"]["miss"] != fit.rate["catch"]["miss"])

    def te_catches(total):
        """The history with the tight ends' catches set to add up to exactly
        `total`."""
        d = h.frame.copy()
        te = d.index[d.position == "TE"]
        d.loc[te, "receptions"] = 5.0
        d.loc[te[0], "receptions"] = total - 5.0 * (len(te) - 1)
        return History(d, T)

    at_200 = EfficiencyModel().fit(te_catches(SPREAD_UNITS))
    chk("a position with exactly 200 catches has its own spread of yards; "
        "with 199 it takes the all-position one",
        float(te_catches(SPREAD_UNITS).frame.query("position == 'TE'").receptions.sum())
        == SPREAD_UNITS
        and "TE" in at_200.rate["yards_per_catch"]["spread"]
        and "TE" not in EfficiencyModel().fit(te_catches(SPREAD_UNITS - 1.0))
        .rate["yards_per_catch"]["spread"])

    def only(n, col, *more):
        """The history with `col` (and what is counted from it) zeroed in
        all but `n` of the player-games that had any."""
        d = h.frame.copy()
        keep = d.index[d[col] > 0][:n]
        for c in (col, *more):
            d[c] = d[c].where(d.index.isin(keep), 0.0)
        return History(d, T)

    def with_attempts(n):
        return only(n, "attempts", "completions", "passing_yards")

    for col, more, word in (("targets", ("receptions", "receiving_yards"), "target"),
                            ("receptions", ("receiving_yards",), "catch"),
                            ("carries", ("rushing_yards",), "carry")):
        tm = EfficiencyModel()
        chk(f"too few games with a {word}: it does not fit, and says which "
            f"opportunity was short",
            not tm.fit(only(RATE_ROWS - 1, col, *more)).ok
            and f"15 player-games with a {word} " in tm.fit(
                only(RATE_ROWS - 1, col, *more)).why,
            tm.fit(only(RATE_ROWS - 1, col, *more)).why)

    thin = EfficiencyModel()
    chk("sixteen games with a pass attempt is enough to learn a passer's "
        "rates from, fifteen is not, and it says which",
        EfficiencyModel().fit(with_attempts(RATE_ROWS)).ok
        and not thin.fit(with_attempts(RATE_ROWS - 1)).ok
        and "15 player-games with a pass attempt" in thin.fit(
            with_attempts(RATE_ROWS - 1)).why, thin.fit(with_attempts(15)).why)
    a = fs.slate_active(f, h)
    tp = thin.parts(with_attempts(RATE_ROWS - 1), a)
    tr = thin.rates(with_attempts(RATE_ROWS - 1), a)
    chk("...and then every rate and spread is blank, not zero",
        len(tr) == len(RATE_COLS) + len(YARD_RATES)
        and all(len(v_) == len(a) and np.isnan(v_).all() for v_ in tr.values()))
    chk("...and it says nothing at all, not even the opportunities",
        all(np.isnan(tp["mean"][s_]).all() for s_ in fe.EFF_STATS)
        and math.isnan(thin.project(with_attempts(RATE_ROWS - 1), a)
                       .p_over(0, "receptions", 2.5)))
    changed = f[f.t < T].copy()
    changed.loc[changed.player_id == "AAA_WR1", "receptions"] *= 0.5
    hc = History(changed, T)
    used = EfficiencyModel()
    used.fit(h)
    chk("a model that has fitted one history fits another afresh, even one "
        "that stops at the same week",
        used.fit(hc) is not used.fit(h)
        and near(used.fit(hc).rate["catch"]["num_now"]["AAA_WR1"],
                 0.5 * fit.rate["catch"]["num_now"]["AAA_WR1"], 1e-9)
        and used.fit(h) is used.fit(h))


@section("23. efficiency — projecting a slate")
def _():
    f, lines = eff_league()
    T = 202404
    h = History(f[f.t < T], T)
    a = fs.slate_active(f, h)
    new = a[a.player_id == "AAA_WR2"].assign(player_id="NEWMAN", name="NEWMAN")
    odd = a[a.player_id == "BBB_TE"].assign(player_id="KICKER", name="KICKER",
                                            position="K")
    nopos = a[a.player_id == "DDD_TE"].assign(player_id="NOPOS", name="NOPOS",
                                              position=None)
    full = pd.concat([a, new, odd, nopos], ignore_index=True)
    m = EfficiencyModel()
    got, want = m.parts(h, full), by_hand_parts(h.frame, full)
    var = m.variances(h, full)
    for stat in fe.EFF_STATS:
        chk(f"expected {stat} match the long-hand ones",
            same(got["mean"][stat], want["mean"][stat]))
        chk(f"...and so does the variance put round them",
            same(var[stat], want["var"][stat], 1e-7)
            and near(got["size"][stat], want["size"][stat], 1e-6))
    for stat in fe.YARDS:
        chk(f"{stat}: the yards each one is worth, and how much one varies, "
            f"match too",
            same(got["unit"][stat][0], [u[0] for u in want["unit"][stat]])
            and same(got["unit"][stat][1], [u[1] for u in want["unit"][stat]], 1e-7))
    idx = {p_: i for i, p_ in enumerate(full.player_id)}
    eff = want["eff"]
    chk("(the long-hand slate exercises what it should: a first-game player "
        "is his position's rate, an unseen or missing position the "
        "all-player one, and a receiver's own rate sits between his raw "
        "rate and his position's)",
        near(m.rates(h, full)["catch"][idx["NEWMAN"]], eff["catch"]["by_pos"]["WR"], 1e-12)
        and near(m.rates(h, full)["catch"][idx["KICKER"]], eff["catch"]["overall"], 1e-12)
        and near(m.rates(h, full)["catch"][idx["NOPOS"]], eff["catch"]["overall"], 1e-12)
        and min(eff["catch"]["by_pos"]["WR"],
                eff["catch"]["num_now"]["AAA_WR1"] / eff["catch"]["den_now"]["AAA_WR1"])
        < m.rates(h, full)["catch"][idx["AAA_WR1"]]
        < max(eff["catch"]["by_pos"]["WR"],
              eff["catch"]["num_now"]["AAA_WR1"] / eff["catch"]["den_now"]["AAA_WR1"]))
    P = m.project(h, full)
    O = OpportunityModel().project(h, full)
    chk("targets, carries and pass attempts pass through from the "
        "opportunity model unchanged, number and chance",
        all(P.point(i, s_) == O.point(i, s_)
            or (math.isnan(P.point(i, s_)) and math.isnan(O.point(i, s_)))
            for i in range(len(full)) for s_ in fo.OPP_STATS)
        and all(P.p_over(idx[p_], s_, ln) == O.p_over(idx[p_], s_, ln)
                for p_, s_, ln in (("AAA_WR1", "targets", 6.5),
                                   ("CCC_RB", "carries", 12.5),
                                   ("BBB_QB", "attempts", 30.5))))
    chk("its single number is the expected number, for every stat",
        all(P.point(idx["AAA_WR1"], s_) == got["mean"][s_][idx["AAA_WR1"]]
            for s_ in ("receptions", "receiving_yards", "rushing_yards"))
        and P.point(idx["BBB_QB"], "passing_yards")
        == got["mean"]["passing_yards"][idx["BBB_QB"]] > 100)
    i, q = idx["AAA_WR1"], idx["BBB_QB"]
    mr, mc_ = want["mean"]["receptions"][i], want["mean"]["completions"][q]
    chk("the chance of a catches line is the count's chance of MORE than it, "
        "spread as his targets are; completions as his attempts are",
        near(P.p_over(i, "receptions", 4.5), nb_tail(4, mr, want["size"]["targets"]), 1e-9)
        and near(P.p_over(q, "completions", 19.5),
                 nb_tail(19, mc_, want["size"]["attempts"]), 1e-9)
        and not near(want["size"]["targets"], want["size"]["attempts"], 1e-3))
    chk("...and landing exactly on a whole-number line is not over it",
        P.p_over(i, "receptions", 4.0) == P.p_over(i, "receptions", 4.5)
        < P.p_over(i, "receptions", 3.5))
    chk("it says nothing about touchdowns, and nothing about a receiver's "
        "passing",
        all(math.isnan(P.point(i, s_)) and math.isnan(P.p_over(i, s_, 0.5))
            for s_ in ("passing_tds", TD_STAT, "passing_yards", "completions")))

    # ---- yards: a sum over the count, checked three independent ways
    toy = fe._Lines(dict(
        mean={"receptions": np.array([2.0]), "receiving_yards": np.array([14.0])},
        size={"receptions": 3.0, "receiving_yards": 3.0},
        unit={"receiving_yards": (np.array([7.0]), np.array([49.0]))},
        count={"receiving_yards": "receptions"}))
    by_formula = sum(nb_pmf(k_, 2.0, 3.0) * erlang_tail(20.5 / 7.0, k_)
                     for k_ in range(1, 200))
    chk("yards: when one catch is worth an exponential 7 yards, the chance "
        "of a line is the catches' chances times the closed-form tail of "
        "that many exponentials",
        near(toy.p_over(0, "receiving_yards", 20.5), by_formula, 1e-9),
        (toy.p_over(0, "receiving_yards", 20.5), by_formula))
    two = fe._Lines(dict(
        mean={"receptions": np.array([2.5]), "receiving_yards": np.array([20.0])},
        size={"receptions": 4.0, "receiving_yards": 4.0},
        unit={"receiving_yards": (np.array([8.0]), np.array([32.0]))},
        count={"receiving_yards": "receptions"}))
    by_formula2 = sum(nb_pmf(k_, 2.5, 4.0) * erlang_tail(30.5 / 4.0, 2 * k_)
                      for k_ in range(1, 200))
    chk("...and when one catch is worth 8 yards with a variance of 32 (two "
        "exponentials of 4), that many pairs of exponentials",
        near(two.p_over(0, "receiving_yards", 30.5), by_formula2, 1e-9),
        (two.p_over(0, "receiving_yards", 30.5), by_formula2))
    chk("...a player with no catches is not over any line; everyone is over "
        "a line below zero; the chance falls as the line rises",
        near(toy.p_over(0, "receiving_yards", 0.0), 1.0 - nb_pmf(0, 2.0, 3.0), 1e-9)
        and toy.p_over(0, "receiving_yards", -0.5) == 1.0
        and toy.p_over(0, "receiving_yards", 5.5) > toy.p_over(0, "receiving_yards", 40.5))
    none = fe._Lines(dict(
        mean={"carries": np.array([0.0]), "rushing_yards": np.array([0.0])},
        size={"carries": 3.0, "rushing_yards": 3.0},
        unit={"rushing_yards": (np.array([4.0]), np.array([30.0]))},
        count={"rushing_yards": "carries"}))
    chk("...and a player expected no carries at all is priced at none",
        none.p_over(0, "rushing_yards", 0.5) == 0.0
        and none.point(0, "rushing_yards") == 0.0)
    for who, stat in (("AAA_WR1", "receiving_yards"), ("CCC_RB", "rushing_yards"),
                      ("BBB_QB", "passing_yards")):
        j = idx[who]
        mu, vv = got["mean"][stat][j], var[stat][j]
        step = max(mu / 400.0, 0.02)
        ys = np.arange(0.0, mu + 14 * math.sqrt(vv), step)
        tail = np.array([P.p_over(j, stat, y_) for y_ in ys])
        first = float(np.trapezoid(tail, ys))
        second = float(2.0 * np.trapezoid(tail * ys, ys))
        chk(f"{stat}: the chances it states add up to the expected number "
            f"and the variance it reports",
            abs(first - mu) < 2e-3 * mu and abs(second - (vv + mu * mu))
            < 4e-3 * (vv + mu * mu), (first, mu, second, vv + mu * mu))

    low = EfficiencyModel()
    lf = low.fit(h)
    lf.rate["yards_per_carry"]["by_pos"]["WR"] = -3.0
    chk("yards per carry are never taken below a tenth of a yard",
        near(low.rates(h, full)["yards_per_carry"][idx["NEWMAN"]], YFLOOR, 1e-12)
        and low.parts(h, full)["mean"]["rushing_yards"][idx["NEWMAN"]] >= 0
        and math.isfinite(low.project(h, full).p_over(idx["NEWMAN"],
                                                      "rushing_yards", 2.5)))
    cf = EfficiencyModel()
    cfit = cf.fit(h)
    cfit.rate["catch"]["by_pos"]["WR"] = -0.5
    chk("...but the floor is for yards only: a catch rate is left as fitted",
        cf.rates(h, full)["catch"][idx["NEWMAN"]] == -0.5)

    mkt = OpportunityModel("o", lines=lines)
    em = EfficiencyModel("with_lines", opportunity=mkt)
    chk("it sits on the opportunity model it is given",
        em.opp is mkt and same(em.parts(h, full)["mean"]["receptions"],
                               by_hand_parts(h.frame, full, lines)["mean"]["receptions"])
        and not same(em.parts(h, full)["mean"]["receptions"],
                     got["mean"]["receptions"]))
    chk("...which must report its expected count, not its median",
        raises(lambda: EfficiencyModel(opportunity=OpportunityModel(single="median")),
               ValueError, "median"))
    chk("with none given it makes its own, named after itself",
        EfficiencyModel("abc").opp.name == "abc_opportunity"
        and EfficiencyModel("abc").opp.lines is None)

    run = fs.walk_forward(f, [EfficiencyModel(), fs.LastFour()], weeks=[202403, T])
    L = run.legs[run.legs.version == "A"]
    chk("through the harness it prices its eight stats and leaves "
        "touchdowns blank",
        L[L.stat.isin(fe.EFF_STATS)].p_efficiency.notna().all()
        and L[~L.stat.isin(fe.EFF_STATS)].p_efficiency.isna().all()
        and set(L[L.p_efficiency.notna()].stat) == set(fe.EFF_STATS)
        and (~L.stat.isin(fe.EFF_STATS)).sum() > 0)
    hw = run.points[(run.points.version == "A") & (run.points.player_id == "AAA_WR1")
                    & (run.points.stat == "receiving_yards") & (run.points.week == 4)]
    at = list(a.player_id).index("AAA_WR1")
    chk("...and the number the harness records is the long-hand one",
        len(hw) == 1 and near(float(hw.pt_efficiency.iloc[0]),
                              by_hand_parts(h.frame, a)["mean"]["receiving_yards"][at],
                              1e-9))
    sat = f[~((f.t == T) & (f.player_id == "AAA_WR2"))]
    rs = fs.walk_forward(sat, [EfficiencyModel()], weeks=[T])
    chk("its numbers differ between the two slates when a regular sits out",
        fs.version_gap(rs, "efficiency") > 0)
    probe = fs.leak_probe(f, [EfficiencyModel()], [202403, T])
    chk("the leak probe finds nothing reaching it through the harness",
        probe.clean and probe.outputs["efficiency"] > 200, probe.describe()[:120])


@section("24. efficiency — its expected numbers beside what happened, and real data")
def _():
    f, _ = eff_league()
    T = 202404
    weeks = [202403, T]
    m = EfficiencyModel()
    ea = fe.expected_vs_actual(m, f, weeks)
    h = History(f[f.t < T], T)
    a = fs.slate_active(f, h)
    parts, var = m.parts(h, a), m.variances(h, a)
    e4 = ea[ea.t == T]
    ok_e = ok_a = ok_v = ok_g = True
    for s_ in fe.EFF_STATS:
        d = e4[e4.stat == s_].set_index("player_id")
        ok_e &= len(d) == int(np.isfinite(parts["mean"][s_]).sum())
        for i, r in enumerate(a.itertuples()):
            if not np.isfinite(parts["mean"][s_][i]):
                continue
            x = float(f[(f.t == T) & (f.player_id == r.player_id)][s_].iloc[0])
            ok_e &= near(d.expected[r.player_id], parts["mean"][s_][i], 1e-12)
            ok_a &= d.actual[r.player_id] == x
            ok_v &= near(d.variance[r.player_id], var[s_][i], 1e-9)
            ok_g &= d.game_id[r.player_id] == r.game_id
    chk("one row per slate player and stat he is given a number for, each "
        "week asked, carrying the model's expected number",
        ok_e and set(ea.t) == set(weeks) and set(ea.stat) == set(fe.EFF_STATS))
    chk("...what he did THAT week in that stat",
        ok_a and len({tuple(e4[e4.stat == s_].actual.round(3))
                      for s_ in fe.EFF_STATS}) == len(fe.EFF_STATS))
    chk("...the model's own variance, and his game", ok_v and ok_g)
    P4 = m.project(h, a)
    ok_s = True
    for s_ in fe.EFF_STATS:
        d = e4[e4.stat == s_].set_index("player_id")
        for i, r in enumerate(a.itertuples()):
            if np.isfinite(parts["mean"][s_][i]):
                ok_s &= near(d.said_above[r.player_id],
                             P4.p_over(i, s_, parts["mean"][s_][i]), 1e-12)
    wr = e4[(e4.player_id == "AAA_WR1")].set_index("stat")
    chk("...and the chance the model itself gives of finishing above its "
        "expected number: under a half for a count, which leans right",
        ok_s and e4.said_above.between(0, 1).all()
        and near(wr.said_above["receptions"],
                 nb_tail(math.floor(wr.expected["receptions"]),
                         wr.expected["receptions"],
                         parts["size"]["receptions"]), 1e-9)
        and 0.2 < wr.said_above["receptions"] < 0.5)
    e3 = ea[(ea.t == 202403) & (ea.stat == "receptions")].set_index("player_id")
    h3 = History(f[f.t < 202403], 202403)
    s3 = fs.slate_active(f, h3)
    chk("...and the earlier week is fitted on ITS history and graded on ITS "
        "result",
        e3.actual["AAA_WR1"] == float(f[(f.t == 202403)
                                        & (f.player_id == "AAA_WR1")].receptions.iloc[0])
        and near(e3.expected["AAA_WR1"],
                 EfficiencyModel().parts(h3, s3)["mean"]["receptions"]
                 [list(s3.player_id).index("AAA_WR1")], 1e-12))
    only = fe.expected_vs_actual(m, f, [T], stats=("receptions", "rushing_yards"))
    chk("it can be asked for some stats only",
        set(only.stat) == {"receptions", "rushing_yards"}
        and len(only) == len(e4[e4.stat.isin(["receptions", "rushing_yards"])]))
    sat = f[~((f.t == T) & (f.player_id == "AAA_WR2"))]
    es = fe.expected_vs_actual(EfficiencyModel(), sat, [T])
    chk("it is graded on the slate of who was ACTIVE: a regular who sat out "
        "is not in it",
        "AAA_WR2" not in set(es.player_id) and es.actual.notna().all()
        and "AAA_WR2" in set(fs.slate_candidates(
            sat, History(sat[sat.t < T], T)).player_id))
    chk("a week too thin to fit gives no rows, not an error",
        len(fe.expected_vs_actual(EfficiencyModel(), f, [202302])) == 0)

    run = fs.walk_forward(f, [EfficiencyModel(), fs.LastFour()], weeks=weeks)
    wl = fe.with_main_line(run, ea, "efficiency")
    L = run.legs[(run.legs.version == "A") & (run.legs.rung == fs.MAIN)
                 & run.legs.stat.isin(fe.EFF_STATS)]
    k = L.set_index(["game_id", "player_id", "stat"])
    e = ea.set_index(["game_id", "player_id", "stat"])
    chk("players with a main line: one row for each such leg, actives known, "
        "carrying that leg's line, result and stated chance and that "
        "player's expected number",
        len(wl) == len(L) > 20 and set(wl.stat) == set(fe.EFF_STATS)
        and all(k.line[(r.game_id, r.player_id, r.stat)] == r.line
                and k.actual[(r.game_id, r.player_id, r.stat)] == r.actual
                and bool(k["over"][(r.game_id, r.player_id, r.stat)]) == r.over
                and near(k.p_efficiency[(r.game_id, r.player_id, r.stat)], r.said, 1e-12)
                and near(e.said_above[(r.game_id, r.player_id, r.stat)],
                         r.said_above, 1e-12)
                and near(e.expected[(r.game_id, r.player_id, r.stat)], r.expected, 1e-12)
                for r in wl.itertuples()), (len(wl), len(L)))
    few = fe.with_main_line(run, ea, "efficiency", stats=("receptions",))
    chk("...for some stats only when asked",
        set(few.stat) == {"receptions"} and len(few) == int((wl.stat == "receptions").sum()))
    w4 = fe.with_main_line(run, ea, "last4_avg")
    chk("...with another projector's stated chance when asked for his",
        len(w4) == len(wl) and not same(w4.said, wl.said)
        and same(w4.expected, wl.expected))
    bad = ea.copy()
    bad.loc[(bad.stat == wl.stat[0]) & (bad.player_id == wl.player_id[0])
            & (bad.game_id == wl.game_id[0]), "actual"] += 1.0
    chk("...and it stops if a result disagrees, a lined player has no "
        "expected number, or a player is there twice",
        raises(lambda: fe.with_main_line(run, bad, "efficiency"), RuntimeError,
               "line up")
        and raises(lambda: fe.with_main_line(
            run, ea[ea.player_id != wl.player_id[0]], "efficiency"),
            RuntimeError, "line up")
        and raises(lambda: fe.with_main_line(run, pd.concat([ea, ea]), "efficiency"),
                   Exception, "one-to-one"))
    who = wl.player_id[0]
    part = fs.Run(points=run.points, names=run.names, weeks=run.weeks,
                  legs=run.legs.assign(p_efficiency=run.legs.p_efficiency.where(
                      run.legs.player_id != who)))
    wp = fe.with_main_line(part, ea, "efficiency")
    chk("...a leg the projector did not price is left out, not carried blank",
        len(wp) == len(wl) - int((wl.player_id == who).sum()) < len(wl)
        and who not in set(wp.player_id))

    frame = REAL.get("frame")
    if frame is None:
        frame = fs.load_frame()
    wk = fs.test_weeks(frame)[-2:]
    rr = fs.walk_forward(frame, [EfficiencyModel()], weeks=wk)
    ra = rr.legs[(rr.legs.version == "A") & rr.legs.stat.isin(fe.EFF_STATS)]
    pv = ra.p_efficiency.to_numpy(dtype=float)
    chk("on real weeks it prices every leg of its eight stats, between 0 and 1",
        not np.isnan(pv).any() and pv.min() >= 0 and pv.max() <= 1 and len(ra) > 3000,
        len(ra))
    hr = History(frame[frame.t < wk[-1]], wk[-1])
    sa = fs.slate_active(frame, hr)
    rm = EfficiencyModel()
    rfit, rt = rm.fit(hr), rm.rates(hr, sa)
    chk("on real history the pull picked for each rate is inside the list, "
        "not at an end of it",
        all(GRID[0] < rfit.rate[r_]["k"] < GRID[-1] for r_ in RATE_COLS),
        {r_: rfit.rate[r_]["k"] for r_ in RATE_COLS})
    recv = sa.position.isin(["WR", "TE", "RB"]).to_numpy()
    qb = sa.starting_qb.to_numpy()
    chk("...and the rates are football: catch rates, yards a catch, yards a "
        "carry, completion rates and yards an attempt",
        0.45 < rt["catch"][recv].min() and rt["catch"][recv].max() < 0.95
        and 5 < rt["yards_per_catch"][recv].min() and rt["yards_per_catch"][recv].max() < 20
        and 2.5 < np.median(rt["yards_per_carry"][sa.position.to_numpy() == "RB"]) < 5.5
        and 0.55 < rt["completion"][qb].min() and rt["completion"][qb].max() < 0.75
        and 5.5 < rt["yards_per_attempt"][qb].min() and rt["yards_per_attempt"][qb].max() < 9,
        (rt["catch"][recv].min(), rt["catch"][recv].max(),
         rt["yards_per_attempt"][qb].min(), rt["yards_per_attempt"][qb].max()))
    pm = rm.parts(hr, sa)["mean"]
    chk("...a real starter is expected a real day's passing yards",
        len(pm["passing_yards"][qb]) >= 20 and 140 < pm["passing_yards"][qb].min()
        and pm["passing_yards"][qb].max() < 330,
        (pm["passing_yards"][qb].min(), pm["passing_yards"][qb].max()))
    pr = fs.leak_probe(frame, [EfficiencyModel()], wk[-1:])
    chk("the leak probe finds nothing reaching it through the harness, on "
        "real data", pr.clean, pr.describe()[:120])


_summary()
sys.exit(1 if fails else 0)
