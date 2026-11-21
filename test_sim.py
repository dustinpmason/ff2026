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


# ===========================================================================
# S13 — each player's chance of playing (ff_sim_play.py)
# ===========================================================================
fp = None


@section("25. chance of playing — it loads")
def _():
    global fp
    import ff_sim_play
    fp = ff_sim_play
    chk("it knows five standings on the injury report, least worrying first",
        fp.STATUSES == ("none", "listed", "questionable", "doubtful", "out"))


# The test's own typed copy of what the module sets by hand.
PRIOR, CHANCE_ROWS, BACK = 20.0, 100, 4
SAT = {("AAA_WR2", 202304), ("AAA_WR2", 202305), ("BBB_TE", 202306),
       ("BBB_TE", 202401), ("BBB_TE", 202402), ("BBB_TE", 202403),
       ("BBB_TE", 202404), ("CCC_RB", 202402), ("DDD_WR1", 202404),
       ("DDD_WR2", 202303), ("CCC_WR1", 202403), ("AAA_TE", 202302),
       ("BBB_WR2", 202305), ("BBB_WR2", 202306), ("CCC_WR2", 202401),
       ("CCC_WR2", 202402), ("CCC_WR2", 202403)}
REPORTED = [(202304, "AAA_WR2", "out"), (202305, "AAA_WR2", "doubtful"),
            (202306, "AAA_WR2", "questionable"), (202306, "BBB_TE", "out"),
            (202401, "BBB_TE", "out"), (202402, "CCC_RB", "doubtful"),
            (202303, "DDD_WR2", "questionable"), (202403, "CCC_WR1", "questionable"),
            (202302, "AAA_TE", "listed"), (202304, "AAA_TE", "listed"),
            (202305, "BBB_WR2", "out"), (202306, "BBB_WR2", "out"),
            (202403, "AAA_RB", "questionable"), (202305, "CCC_QB", "listed"),
            (202401, "DDD_RB", "questionable"), (202402, "DDD_RB", "questionable"),
            # the graded week, and one that has not happened yet
            (202404, "DDD_WR1", "out"), (202404, "AAA_WR1", "questionable"),
            (202404, "CCC_TE", "listed"), (203101, "AAA_QB", "out")]


def play_league():
    """(frame, reports): the efficiency league with players sitting games
    out, one of them for good, and a made-up injury report."""
    f, _ = eff_league()
    f = f[[(p_, t_) not in SAT for p_, t_ in zip(f.player_id, f.t)]].reset_index(drop=True)
    # a trade: AAA_WR2 plays for CCC from 2024 Week 3 on
    for t_ in (202403, 202404):
        to = f[(f.t == t_) & (f.team == "CCC")].iloc[0]
        moved = (f.t == t_) & (f.player_id == "AAA_WR2")
        f.loc[moved, ["team", "opponent", "game_id"]] = [to.team, to.opponent, to.game_id]
    rep = pd.DataFrame(REPORTED, columns=["t", "player_id", "status"])
    return f, rep


def hand_listed(F):
    """{(team, t, player): (missed, played)} with plain loops: who a team
    would have listed for each of its games, from its four games before."""
    out = {}
    for team, g in F.groupby("team"):
        weeks = sorted(set(g.t))
        on = {w: set(g.player_id[g.t == w]) for w in weeks}
        for i, w in enumerate(weeks):
            before = weeks[max(0, i - BACK):i]
            for p_ in set().union(*[on[b] for b in before]) if before else ():
                last = max(j for j, b in enumerate(before) if p_ in on[b])
                out[(team, w, p_)] = (len(before) - 1 - last, p_ in on[w])
    return out


def hand_chances(F, rep, before):
    """(cell, by_status, count) the long way, from games before `before`."""
    status = ({(t_, p_): s_ for t_, p_, s_ in zip(rep.t, rep.player_id, rep.status)
               if t_ < before} if rep is not None else {})
    rows = [(status.get((t_, p_), "none"), miss, played)
            for (team, t_, p_), (miss, played) in hand_listed(F).items()]
    everyone = sum(r[2] for r in rows) / len(rows)
    by_status, cell, count = {}, {}, {}
    for s_ in ("none", "listed", "questionable", "doubtful", "out"):
        mine = [r for r in rows if r[0] == s_]
        by_status[s_] = sum(r[2] for r in mine) / len(mine) if mine else everyone
        for miss in range(BACK):
            c = [r for r in mine if r[1] == miss]
            count[(s_, miss)] = len(c)
            cell[(s_, miss)] = ((sum(r[2] for r in c) + PRIOR * by_status[s_])
                                / (len(c) + PRIOR))
    return cell, by_status, count


@section("26. chance of playing — counted on the history, by hand")
def _():
    f, rep = play_league()
    T = 202404
    h = History(f[f.t < T], T)
    L = fp.listed_history(h.frame)
    want = hand_listed(h.frame)
    got = {(r.team, r.t, r.player_id): (r.missed, r.played) for r in L.itertuples()}
    chk("who each team would have listed for each game, how many of its "
        "last four he had missed, and whether he then played, match a "
        "long-hand walk through the games",
        got == want and len(L) == len(want) > CHANCE_ROWS, (len(L), len(want)))
    chk("(the fixture has what it should: players who sat, came back, and "
        "one who dropped off the list for good)",
        want[("AAA", 202305, "AAA_WR2")] == (1, False)
        and want[("AAA", 202306, "AAA_WR2")] == (2, True)
        and want[("BBB", 202403, "BBB_TE")] == (3, False)
        and ("BBB", 202404, "BBB_TE") not in hand_listed(f)
        and {m_ for m_, _ in want.values()} == {0, 1, 2, 3}
        and hand_listed(f)[("AAA", 202404, "AAA_WR2")] == (1, False)
        and hand_listed(f)[("CCC", 202404, "AAA_WR2")] == (0, True))
    same_as_harness = True
    for w in sorted(set(f.t))[1:]:
        hw = History(f[f.t < w], w)
        mine = {(r.team, r.player_id) for r in fp.listed_history(f[f.t <= w]).itertuples()
                if r.t == w}
        same_as_harness &= mine == set(zip(*[fs.slate_candidates(f, hw)[c]
                                             for c in ("team", "player_id")]))
    chk("...and for every week it is exactly the list the harness's slate B "
        "gives", same_as_harness)

    pc = fp.PlayChance(rep)
    fit = pc.fit(h)
    cell, by_status, count = hand_chances(h.frame, rep, T)
    chk("how often each status played matches a long-hand count",
        fit.ok and set(fit.by_status) == set(by_status)
        and all(near(fit.by_status[s_], by_status[s_], 1e-12) for s_ in by_status),
        (fit.by_status, by_status))
    chk("the chance for each status and number of games missed matches too: "
        "its own count pulled toward its status's rate as if that rate had "
        "been seen twenty times",
        set(fit.cell) == set(cell) and len(cell) == 20
        and all(near(fit.cell[k_], cell[k_], 1e-12) for k_ in cell)
        and fit.count == count and fit.rows == len(want))
    chk("(the fixture is worth it: every status was seen; out and doubtful "
        "never played, questionable sometimes; a regular who played last "
        "week is likelier than one who has missed three)",
        all(count[(s_, m_)] > 0 for s_, m_ in (("out", 0), ("doubtful", 1),
                                               ("questionable", 0), ("listed", 0)))
        and by_status["out"] == 0.0 and by_status["doubtful"] == 0.0
        and 0.0 < by_status["questionable"] < 1.0
        and cell[("none", 0)] > cell[("none", 3)] + 0.05
        and cell[("out", 0)] == 0.0)
    none_fit = fp.PlayChance().fit(h)
    cell0, by0, _ = hand_chances(h.frame, None, T)
    chk("with no report at all everyone is 'none', and a status never seen "
        "takes the all-player rate",
        all(near(none_fit.cell[k_], cell0[k_], 1e-12) for k_ in cell0)
        and near(none_fit.by_status["out"], by0["none"], 1e-12)
        and not near(none_fit.cell[("none", 0)], fit.cell[("none", 0)], 1e-6))

    later = rep.copy()
    later.loc[later.t >= T, "status"] = "doubtful"
    chk("a report from the week being projected, or later, does not reach "
        "what is counted on the history",
        fp.PlayChance(later).fit(h).cell == fit.cell)
    earlier = rep.copy()
    earlier.loc[earlier.t == 202403, "status"] = "out"
    chk("...and one from before it does",
        fp.PlayChance(earlier).fit(h).cell != fit.cell)
    thin = History(f[f.t < 202305], 202305)
    tf = fp.PlayChance(rep).fit(thin)
    chk("fewer than a hundred listed player-games: nothing is counted, and "
        "it says why",
        not tf.ok and f"only {len(hand_listed(thin.frame))} listed" in tf.why
        and len(hand_listed(thin.frame)) < CHANCE_ROWS, tf.why)
    floor = fp.MIN_CHANCE_ROWS
    try:
        fp.MIN_CHANCE_ROWS = len(want)
        at_it = fp.PlayChance(rep).fit(History(h.frame, T)).ok
        fp.MIN_CHANCE_ROWS = len(want) + 1
        under = fp.PlayChance(rep).fit(History(h.frame, T)).ok
    finally:
        fp.MIN_CHANCE_ROWS = floor
    chk("...the least it will count on is met by exactly that many listed "
        "player-games and not by one fewer; and the least is a hundred",
        at_it and not under and floor == CHANCE_ROWS)
    used = fp.PlayChance(rep)
    used.fit(h)
    h2 = History(f[(f.t < T) & (f.player_id != "CCC_WR2")], T)
    chk("it counts afresh for another history that stops at the same week",
        used.fit(h2) is not fit and used.fit(h2).rows < fit.rows
        and used.fit(h2) is used.fit(h2))
    chk("an unknown status, two reports for one player-week, or a chance "
        "outside 0 to 1 handed in, is refused",
        raises(lambda: fp.PlayChance(rep.assign(status="probable")), ValueError,
               "probable")
        and raises(lambda: fp.PlayChance(pd.concat([rep, rep.iloc[:1]])), ValueError,
                   "two reports")
        and raises(lambda: fp.PlayChance(given={"AAA_QB": 1.2}), ValueError, "AAA_QB")
        and raises(lambda: fp.PlayChance(given={"AAA_QB": -0.1}), ValueError, "AAA_QB"))


@section("27. chance of playing — on a slate, and in the opportunity model")
def _():
    f, rep = play_league()
    T = 202404
    h = History(f[f.t < T], T)
    b = fs.slate_candidates(f, h)
    pc = fp.PlayChance(rep)
    d = pc.describe(h, b)
    cell, by_status, _ = hand_chances(h.frame, rep, T)
    listed = hand_listed(f[f.t <= T])
    now = {p_: s_ for t_, p_, s_ in REPORTED if t_ == T}
    ok = True
    for i, r in enumerate(b.itertuples()):
        miss = listed[(r.team, T, r.player_id)][0]
        s_ = now.get(r.player_id, "none")
        ok &= (d.status[i] == s_ and d.missed[i] == miss
               and near(d.chance[i], cell[(s_, miss)], 1e-12)
               and d.source[i] == "counted")
    idx = {p_: i for i, p_ in enumerate(b.player_id)}
    chk("every listed player gets this week's status, his games missed and "
        "the chance counted for that pair", ok and len(d) == len(b)
        and np.array_equal(pc.chances(h, b), d.chance.to_numpy()))
    traded = {b.team[i]: d.missed[i] for i in range(len(b))
              if b.player_id[i] == "AAA_WR2"}
    chk("a traded player is listed by both teams, and his games missed are "
        "counted for EACH: one for the team he left, none for the one he "
        "joined", traded == {"AAA": 1, "CCC": 0}, traded)
    chk("(the slate has an out player, a questionable one, one listed with "
        "no status, and one who has missed three)",
        d.status[idx["DDD_WR1"]] == "out" and d.status[idx["AAA_WR1"]] == "questionable"
        and d.status[idx["CCC_TE"]] == "listed" and d.missed[idx["CCC_WR2"]] == 3
        and "BBB_TE" not in idx
        and d.chance[idx["DDD_WR1"]] < 0.05 < d.chance[idx["CCC_WR2"]]
        < d.chance[idx["AAA_QB"]]
        and d.chance[idx["AAA_WR1"]] < d.chance[idx["AAA_QB"]])
    later = rep.copy()
    later.loc[later.t > T, "status"] = "questionable"
    moved = rep.copy()
    moved.loc[(moved.t == T) & (moved.player_id == "AAA_WR1"), "status"] = "out"
    chk("a later week's report moves nothing; this week's does",
        np.array_equal(fp.PlayChance(later).chances(h, b), pc.chances(h, b))
        and fp.PlayChance(moved).chances(h, b)[idx["AAA_WR1"]]
        < pc.chances(h, b)[idx["AAA_WR1"]] - 0.3)
    two = fp.PlayChance(rep, given={"AAA_WR2": 0.9, ("AAA", "AAA_WR2"): 0.0}
                        ).describe(h, b)
    chk("a chance can be handed in for one team's listing of a traded "
        "player; the pair wins over the bare id",
        {b.team[i]: two.chance[i] for i in range(len(b))
         if b.player_id[i] == "AAA_WR2"} == {"AAA": 0.0, "CCC": 0.9}
        and raises(lambda: fp.PlayChance(given={("AAA", "AAA_WR2"): 1.5}),
                   ValueError, "AAA_WR2"))
    chk("a slate for another week than the history stops before is refused",
        raises(lambda: pc.describe(History(f[f.t < 202403], 202403), b),
               ValueError, "202404"))
    gv = fp.PlayChance(rep, given={"AAA_WR1": 0.25, "DDD_WR1": 1.0})
    gd = gv.describe(h, b)
    chk("a chance handed in overrides the counted one for that player and "
        "nobody else, and says so",
        gd.chance[idx["AAA_WR1"]] == 0.25 and gd.chance[idx["DDD_WR1"]] == 1.0
        and gd.source[idx["AAA_WR1"]] == "given" and gd.status[idx["DDD_WR1"]] == "out"
        and all(gd.chance[i] == d.chance[i] and gd.source[i] == "counted"
                for i in range(len(b)) if b.player_id[i] not in ("AAA_WR1", "DDD_WR1")))
    a = fs.slate_active(f, h)
    new = a.iloc[[0]].assign(player_id="NEWMAN", name="NEWMAN", position="WR")
    old = b[b.team == "BBB"].iloc[[0]].assign(player_id="BBB_TE", name="BBB_TE")
    wide = pd.concat([a, new, old], ignore_index=True)
    dn = fp.PlayChance(pd.concat([rep, pd.DataFrame(
        [(T, "NEWMAN", "questionable")], columns=rep.columns)])).describe(h, wide)
    chk("a player who has not played for the team in its last four games, "
        "whether he never has or it was longer ago, has no count of games "
        "missed", pd.isna(dn.missed[len(wide) - 2]) and pd.isna(dn.missed[len(wide) - 1])
        and "BBB_TE" in set(h.frame.player_id))
    chk("...and takes his status's overall rate: questionable for the "
        "newcomer, 'none' for the man long gone",
        near(dn.chance[len(wide) - 2], by_status["questionable"], 1e-12)
        and near(dn.chance[len(wide) - 1], by_status["none"], 1e-12)
        and not near(by_status["questionable"], by_status["none"], 1e-3))
    thin = History(f[f.t < 202305], 202305)
    bt = fs.slate_candidates(f, thin)
    td = fp.PlayChance(rep, given={bt.player_id[0]: 0.4}).describe(thin, bt)
    chk("too little history to count on: everyone is taken to play, and "
        "says so; a chance handed in still stands",
        td.chance[0] == 0.4 and td.source[0] == "given"
        and (td.chance[1:] == 1.0).all() and set(td.source[1:]) == {"taken to play"})

    # ---- in the opportunity model
    plain = OpportunityModel()
    base = plain.means(h, b)
    sure = fp.ChanceOpportunity("sure", chance=fp.PlayChance(
        given={p_: 1.0 for p_ in b.player_id}))
    chk("with every chance at 1 it is the opportunity model, number for number",
        all(same(sure.means(h, b)[s_], base[s_], 1e-12) for s_ in fo.OPP_STATS))
    gone = fp.ChanceOpportunity("gone", chance=fp.PlayChance(
        given={**{p_: 1.0 for p_ in b.player_id}, "AAA_WR1": 0.0, "CCC_RB": 0.0}))
    without = b[~b.player_id.isin(["AAA_WR1", "CCC_RB"])].reset_index(drop=True)
    gm, wm = gone.means(h, b), plain.means(h, without)
    keep = np.flatnonzero(~b.player_id.isin(["AAA_WR1", "CCC_RB"]).to_numpy())
    chk("with a teammate's chance at 0 everyone else gets exactly what the "
        "opportunity model gives on a slate without him",
        all(same(gm[s_][keep], wm[s_], 1e-9) for s_ in fo.SHARED)
        and gm["targets"][idx["AAA_TE"]] > base["targets"][idx["AAA_TE"]] * 1.2)
    chk("...and he himself is given what he would get if he did play, "
        "which is what the plain model gives him",
        near(gm["targets"][idx["AAA_WR1"]], base["targets"][idx["AAA_WR1"]], 1e-9))
    co = fp.ChanceOpportunity("opp_report", chance=pc)
    cm = co.means(h, b)
    p = pc.chances(h, b)
    ok = True
    for stat in fo.SHARED:
        for i, r in enumerate(b.itertuples()):
            mates = [j for j in range(len(b))
                     if b.team[j] == r.team and b.game_id[j] == r.game_id]
            whole = sum(base[stat][j] for j in mates)
            beside = base[stat][i] + sum(p[j] * base[stat][j] for j in mates if j != i)
            ok &= near(cm[stat][i], whole * base[stat][i] / beside, 1e-9)
    chk("with counted chances: his share is his weight over his own plus "
        "each teammate's weight times that teammate's chance, by hand", ok)
    chk("...so nobody is given less than the plain model gives him, and the "
        "teammates of an out player are given more",
        all((cm[s_] >= base[s_] - 1e-12).all() for s_ in fo.SHARED)
        and cm["targets"][idx["DDD_WR2"]] > base["targets"][idx["DDD_WR2"]] * 1.15)
    chk("pass attempts are untouched",
        same(cm["attempts"], base["attempts"], 1e-12))
    zero = fp.ChanceOpportunity("z", chance=fp.PlayChance(
        given={p_: 0.0 for p_ in b.player_id}))
    zf = zero.fit(h)
    zf.share["targets"] = (np.array([-0.2, 1.0, 0.0, 0.0]),) + zf.share["targets"][1:]
    zb = OpportunityModel()
    zb.fit(h).share["targets"] = zf.share["targets"]
    zbase = zb.means(h, b)["targets"]
    zm = zero.means(h, b)["targets"]
    chk("a player the model gives nothing stays at nothing, whatever the "
        "chances; with every teammate at 0 a player gets the whole team",
        (zbase == 0.0).sum() >= 4 and all(zm[i] == 0.0 for i in range(len(b))
                                          if zbase[i] == 0.0)
        and zbase[idx["AAA_WR1"]] > 0
        and near(zm[idx["AAA_WR1"]],
                 sum(zbase[j] for j in range(len(b)) if b.team[j] == "AAA"), 1e-9)
        and np.isfinite(zm).all(), zm[:6].tolist())
    chk("left to itself it counts chances from games missed, with no report",
        fp.ChanceOpportunity().chance.reports is None
        and fp.ChanceOpportunity().name == "opportunity_chance"
        and same(fp.ChanceOpportunity().means(h, b)["carries"],
                 fp.ChanceOpportunity("x", chance=fp.PlayChance()).means(h, b)["carries"]))
    lines = eff_league()[1]
    wl = fp.ChanceOpportunity("m", chance=pc, lines=lines)
    chk("it still takes closing lines and the median, as the model under "
        "it does", wl.lines is lines
        and not same(wl.means(h, b)["targets"], cm["targets"])
        and fp.ChanceOpportunity("q", single="median").single == "median")
    em = EfficiencyModel("eff_report", opportunity=co)
    plain_eff = EfficiencyModel()
    chk("efficiency sits on it: expected catches rise with the expected "
        "targets, at the same catch rate",
        same(em.parts(h, b)["mean"]["receptions"] / cm["targets"],
             plain_eff.parts(h, b)["mean"]["receptions"] / base["targets"], 1e-9)
        and em.parts(h, b)["mean"]["receptions"][idx["DDD_WR2"]]
        > plain_eff.parts(h, b)["mean"]["receptions"][idx["DDD_WR2"]])
    run = fs.walk_forward(f, [plain_eff, em], weeks=[202403, T])
    B = run.points[(run.points.version == "B") & (run.points.stat == "targets")
                   & (run.points.week == 4)].set_index("player_id")
    chk("through the harness, on the list of who had been playing, the "
        "number recorded is the long-hand one and is above the plain model's "
        "for an out player's teammate",
        near(float(B.pt_eff_report["DDD_WR2"]), cm["targets"][idx["DDD_WR2"]], 1e-9)
        and B.pt_eff_report["DDD_WR2"] > B.pt_efficiency["DDD_WR2"] * 1.15)
    probe = fs.leak_probe(f, [EfficiencyModel("eff_report", opportunity=fp.ChanceOpportunity(
        "o", chance=fp.PlayChance(rep)))], [202403, T])
    chk("the leak probe finds nothing reaching it through the harness (it "
        "cannot see the reports)", probe.clean and probe.outputs["eff_report"] > 200,
        probe.describe()[:100])

    cv = fp.chance_vs_played(pc, f, [202403, T])
    c4 = cv[cv.t == T].reset_index(drop=True)
    chk("chance beside played: one row for each player slate B lists, each "
        "week asked, with the chance he was given and whether he played "
        "for that team that week",
        set(cv.t) == {202403, T} and len(c4) == len(b)
        and list(c4.player_id) == list(b.player_id)
        and np.array_equal(c4.chance.to_numpy(), d.chance.to_numpy())
        and list(c4.status) == list(d.status)
        and not c4.played[idx["DDD_WR1"]] and c4.played[idx["CCC_WR2"]]
        and c4.played[idx["AAA_WR1"]]
        and {c4.team[i]: bool(c4.played[i]) for i in range(len(b))
             if b.player_id[i] == "AAA_WR2"} == {"AAA": False, "CCC": True}
        and int(c4.played.sum()) == int(((f.t == T) & f.player_id.isin(
            set(b.player_id))).sum()))
    h3 = History(f[f.t < 202403], 202403)
    c3 = cv[cv.t == 202403].reset_index(drop=True)
    chk("...the earlier week counted on ITS history and read from ITS report",
        np.array_equal(c3.chance.to_numpy(),
                       pc.chances(h3, fs.slate_candidates(f, h3)))
        and c3.status[list(c3.player_id).index("CCC_WR1")] == "questionable"
        and not c3.played[list(c3.player_id).index("CCC_WR1")])


@section("28. chance of playing — the injury reports themselves")
def _():
    stamp = lambda s_: pd.Timestamp(s_, tz="UTC")       # noqa: E731
    raw = pd.DataFrame([
        # season, week, team, type, id, status, modified
        (2024, 3, "AAA", "REG", "p1", "Out", stamp("2024-09-20 20:00")),
        (2024, 3, "AAA", "REG", "p2", "Questionable", stamp("2024-09-21 23:00")),
        (2024, 3, "AAA", "REG", "p3", None, stamp("2024-09-20 20:00")),
        (2024, 3, "AAA", "REG", "p4", "Note", stamp("2024-09-20 20:00")),
        (2024, 3, "AAA", "REG", "p5", "Doubtful", stamp("2024-09-22 14:00")),   # game day
        (2024, 3, "AAA", "REG", "p6", "Out", stamp("2024-09-23 02:00")),        # after
        (2024, 3, "AAA", "REG", "p7", "Doubtful", pd.NaT),                      # no stamp
        (2024, 3, "AAA", "REG", "p8", "Out", stamp("2024-09-20 21:00")),        # later report
        (2024, 3, "AAA", "REG", "p8", "Questionable", stamp("2024-09-19 20:00")),
        (2024, 3, "NXT", "REG", "p9", "Out", stamp("2024-09-25 20:00")),        # game not played yet
        (2024, 19, "AAA", "WC", "p1", "Out", stamp("2025-01-10 20:00")),        # postseason
        (2024, 3, "AAA", "REG", None, "Out", stamp("2024-09-20 20:00")),        # no id
        (2024, 4, "AAA", "REG", "p1", "Questionable", stamp("2024-09-27 20:00")),
    ], columns=["season", "week", "team", "game_type", "gsis_id", "report_status",
                "date_modified"])
    games = pd.DataFrame([(2024, 3, "AAA", "2024-09-22"), (2024, 4, "AAA", "2024-09-29"),
                          (2024, 19, "AAA", "2025-01-12")],
                         columns=["season", "week", "team", "game_date"])
    out = fp.clean_reports(raw, games)
    got = {(r.t, r.player_id): r.status for r in out.itertuples()}
    chk("the reports table: one row per player and week, the report's three "
        "game statuses in plain words, anything else on the report 'listed'",
        got == {(202403, "p1"): "out", (202403, "p2"): "questionable",
                (202403, "p3"): "listed", (202403, "p4"): "listed",
                (202403, "p7"): "doubtful", (202403, "p8"): "out",
                (202403, "p9"): "out", (202404, "p1"): "questionable"}, got)
    chk("...a report changed on the day of the game or later is left out; "
        "one with no time stamp is kept; of two for one week the later "
        "stands, whichever row comes first; postseason and a row with no "
        "id go",
        (202403, "p5") not in got and (202403, "p6") not in got
        and got[(202403, "p7")] == "doubtful" and got[(202403, "p8")] == "out"
        and not any(t_ == 202419 for t_, _ in got))
    chk("...and the report for a game that has not been played yet is KEPT: "
        "it is the one a live run needs", got[(202403, "p9")] == "out")
    chk("...and it counts what it dropped",
        out.attrs["report"] == dict(rows=13, regular_season=11, game_not_on_file_yet=1,
                                    changed_on_game_day_or_later=2, no_time_stamp=1,
                                    second_report_same_week=1, kept=8),
        out.attrs["report"])
    chk("...and a table missing a column is refused by name",
        raises(lambda: fp.clean_reports(raw.drop(columns=["date_modified"]), games),
               ValueError, "date_modified"))
    fp.PlayChance(out)          # what it makes is what PlayChance takes

    import pathlib
    import tempfile
    real_cache, real_open = fp.ff_data.CACHE, fp.urllib.request.urlopen
    calls = []

    class _Resp:
        def __init__(self, data): self.data, self.done = data, False
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self, n):
            if self.done:
                return b""
            self.done = True
            return self.data

    def ok_open(url, timeout=0):
        calls.append(url)
        return _Resp(b"season-file")

    def bad_open(url, timeout=0):
        calls.append(url)
        raise OSError("no network")

    class _Dies(_Resp):
        def read(self, n):
            if self.done:
                raise OSError("connection lost")
            self.done = True
            return self.data

    def half_open(url, timeout=0):
        return _Dies(b"half-a-file")

    import contextlib
    import io
    said = io.StringIO()
    try:
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stderr(said):
            fp.ff_data.CACHE = pathlib.Path(tmp) / "cache"
            fp.urllib.request.urlopen = bad_open
            no_file = raises(lambda: fp.fetch_reports(2031), RuntimeError, "2031")
            fp.urllib.request.urlopen = ok_open
            first = fp.fetch_reports(2031)
            n_first = len(calls)
            again = fp.fetch_reports(2031)
            fresh_no_fetch = len(calls) == n_first
            fp.urllib.request.urlopen = bad_open
            forced = fp.fetch_reports(2031, force=True)
            fp.urllib.request.urlopen = half_open
            halved = fp.fetch_reports(2031, force=True)
            chk("a download that dies half way leaves the old copy as it "
                "was and no partial file behind",
                halved == first and first.read_bytes() == b"season-file"
                and [x.name for x in fp.ff_data.CACHE.iterdir()]
                == ["injuries_2031.parquet"])
            chk("a season's reports are fetched from nflverse's injuries "
                "release into the engine's cache under their own name",
                first == fp.ff_data.CACHE / "injuries_2031.parquet"
                and first.read_bytes() == b"season-file"
                and calls[1].endswith("/injuries/injuries_2031.parquet")
                and calls[1].startswith(fp.ff_data.BASE))
            chk("...a fresh copy is not fetched again; a failed refresh falls "
                "back on the copy there is; with no copy it stops and names "
                "the season",
                fresh_no_fetch and again == first and forced == first
                and forced.read_bytes() == b"season-file" and no_file
                and not list(fp.ff_data.CACHE.glob("*.tmp")))
    finally:
        fp.ff_data.CACHE, fp.urllib.request.urlopen = real_cache, real_open
    chk("...and each fall-back says so, naming the season",
        said.getvalue().count("injuries 2031 refresh failed") == 2
        and "using cached copy" in said.getvalue(), said.getvalue()[:80])

    frame = REAL.get("frame")
    if frame is None:
        frame = fs.load_frame()
    years = sorted(int(y) for y in frame.season.unique())
    rep = fp.load_reports(years)
    rr = rep.attrs["report"]
    chk("on real data: reports for every season in the frame, thousands of "
        "them, one per player and week, nearly all of the regular-season "
        "rows kept",
        set(rep.t // 100) == set(years) and len(rep) > 15000
        and not rep.duplicated(["t", "player_id"]).any()
        and set(rep.status) == set(fp.STATUSES) - {"none"}
        and rr["kept"] > 0.99 * rr["regular_season"]
        and rr["changed_on_game_day_or_later"] < 0.01 * rr["regular_season"], rr)
    newest = int(rep.t.max())
    raw_new = pd.read_parquet(fp.fetch_reports(newest // 100))
    raw_new = raw_new[(raw_new.game_type == "REG") & (raw_new.week == newest % 100)]
    chk("...and the newest week's report is there for every team that filed "
        "one, played yet or not",
        (rep.t == newest).sum() == raw_new.gsis_id.nunique() > 100
        and raw_new.team.nunique() >= 20, ((rep.t == newest).sum(), raw_new.team.nunique()))
    wk = fs.test_weeks(frame)[-1]
    hr = History(frame[frame.t < wk], wk)
    rf = fp.PlayChance(rep).fit(hr)
    chk("...and what is counted on it is football: out and doubtful almost "
        "never play, questionable plays more often than not, a player on "
        "the report with no status nearly always, and a regular who has "
        "missed three straight rarely",
        rf.ok and rf.by_status["out"] < 0.03 and rf.by_status["doubtful"] < 0.1
        and 0.5 < rf.by_status["questionable"] < 0.8 and rf.by_status["listed"] > 0.85
        and rf.cell[("none", 0)] > 0.8 and rf.cell[("none", 3)] < 0.25
        and all(rf.count[(s_, 0)] > 100 for s_ in fp.STATUSES),
        {k_: round(v_, 3) for k_, v_ in rf.by_status.items()})
    sb = fs.slate_candidates(frame, hr)
    pr = fp.PlayChance(rep).chances(hr, sb)
    chk("...every listed player gets a chance between 0 and 1, and they are "
        "not all the same", len(pr) == len(sb) > 500 and pr.min() >= 0
        and pr.max() <= 1 and pr.std() > 0.1)


# ===========================================================================
# S24 — touchdowns (ff_sim_td.py)
# ===========================================================================
ft = TouchdownModel = None


@section("29. touchdowns — it loads")
def _():
    global ft, TouchdownModel
    import ff_sim_td
    ft, TouchdownModel = ff_sim_td, ff_sim_td.TouchdownModel
    chk("it adds passing and anytime touchdowns to the efficiency model's "
        "eight stats", ft.TD_STATS == ("passing_tds", "anytime_tds")
        and ft.ALL_STATS == (*fe.EFF_STATS, "passing_tds", "anytime_tds"))


# The test's own typed copy.
TD_GRID = (20.0, 40.0, 80.0, 160.0, 320.0, 640.0, 1280.0, 2560.0, 5120.0, 10240.0)
TD_COLS = {"td_per_target": ("receiving_tds", "targets"),
           "td_per_carry": ("rushing_tds", "carries"),
           "td_per_attempt": ("passing_tds", "attempts")}
TD_MIN_POS = 200.0


def td_league():
    """(frame, lines): the efficiency league with touchdowns DRAWN on its
    catches, carries and completions. Scoring differs by role and by team."""
    f, lines = eff_league()
    rng = np.random.default_rng(23)
    catch_td = dict(WR1=0.16, WR2=0.07, TE=0.20, RB=0.05, QB=0.0, QB2=0.0)
    run_td = dict(RB=0.07, QB=0.12, WR1=0.03, WR2=0.0, TE=0.0, QB2=0.0)
    for i in f.index:
        role = f.at[i, "player_id"].split("_")[1]
        up = TEAM_LEAN[f.at[i, "team"]]
        f.at[i, "receiving_tds"] = float(rng.binomial(
            int(f.at[i, "receptions"]), min(catch_td[role] * (3 * up - 2), 0.9)
            if 3 * up - 2 > 0 else 0.0))
        f.at[i, "rushing_tds"] = float(rng.binomial(
            int(f.at[i, "carries"]), run_td[role] * up))
        f.at[i, "passing_tds"] = float(rng.binomial(
            int(f.at[i, "completions"]), 0.02 + 0.30 * (up - 0.8)))
    f[TD_STAT] = f.rushing_tds + f.receiving_tds
    return f, lines


def hand_rate(F, nc, dc, grid, half_life=16.0):
    """One pulled rate learned from a history, with plain loops."""
    w = 0.5 ** (1.0 / half_life)
    rows = list(F.sort_values(["player_id", "t"], kind="stable").itertuples())
    overall = sum(getattr(r, nc) for r in rows) / sum(getattr(r, dc) for r in rows)
    pn, pd_ = {}, {}
    for r in rows:
        if r.position is not None:
            pn[r.position] = pn.get(r.position, 0.0) + getattr(r, nc)
            pd_[r.position] = pd_.get(r.position, 0.0) + getattr(r, dc)
    by_pos = {q: pn[q] / pd_[q] for q in pn if pd_[q] >= TD_MIN_POS}
    before, num_now, den_now, cur = [], {}, {}, object()
    for r in rows:
        if r.player_id != cur:
            cur, sn, sd = r.player_id, 0.0, 0.0
        before.append((sn, sd))
        sn, sd = w * sn + getattr(r, nc), w * sd + getattr(r, dc)
        num_now[cur], den_now[cur] = sn, sd
    used = [(getattr(r, nc), getattr(r, dc), b, by_pos.get(r.position, overall))
            for r, b in zip(rows, before) if getattr(r, dc) > 0]
    miss = {k: sum((x - d * ((bn + k * nm) / (bd + k))) ** 2
                   for x, d, (bn, bd), nm in used) for k in grid}
    return dict(k=min(grid, key=lambda v: (miss[v], v)), miss=miss, overall=overall,
                by_pos=by_pos, num_now=num_now, den_now=den_now, rows=len(used),
                thin={q: pn[q] / pd_[q] for q in pn if 0 < pd_[q] < TD_MIN_POS})


def hand_td(F, slate):
    """Expected touchdowns for a slate and what they are built from, from
    the by-hand opportunity fit and by-hand touchdown rates."""
    base = by_hand_parts(F, slate)
    rate = {r_: hand_rate(F, nc, dc, TD_GRID) for r_, (nc, dc) in TD_COLS.items()}
    rows = list(slate.itertuples())

    def q(name, r):
        o = rate[name]
        return ((o["num_now"].get(r.player_id, 0.0)
                 + o["k"] * o["by_pos"].get(r.position, o["overall"]))
                / (o["den_now"].get(r.player_id, 0.0) + o["k"]))

    recv = [m * q("td_per_target", r) for m, r in zip(base["mean"]["targets"], rows)]
    rush = [m * q("td_per_carry", r) for m, r in zip(base["mean"]["carries"], rows)]
    thrown = [m * q("td_per_attempt", r) for m, r in zip(base["mean"]["attempts"], rows)]
    return dict(base=base, rate=rate, recv=recv, rush=rush, thrown=thrown,
                anytime=[a + b for a, b in zip(recv, rush)])


@section("30. touchdowns — what it learns and what it projects, by hand")
def _():
    f, lines = td_league()
    T = 202404
    h = History(f[f.t < T], T)
    m = TouchdownModel()
    fit = m.fit(h)
    for rate, (nc, dc) in TD_COLS.items():
        r, o = fit.rate[rate], hand_rate(h.frame, nc, dc, TD_GRID)
        chk(f"{rate}: the pull it picks, how each candidate pull scored, the "
            f"position rates and every player's leaning totals match a "
            f"long-hand re-derivation",
            r["k"] == o["k"] and tuple(r["miss"]) == TD_GRID
            and all(near(r["miss"][k_] / o["miss"][k_], 1.0, 1e-9) for k_ in TD_GRID)
            and near(r["overall"], o["overall"], 1e-12)
            and set(r["by_pos"]) == set(o["by_pos"])
            and all(near(r["by_pos"][q_], o["by_pos"][q_], 1e-12) for q_ in o["by_pos"])
            and set(r["num_now"]) == set(o["num_now"])
            and all(near(r["num_now"][q_], o["num_now"][q_], 1e-9)
                    and near(r["den_now"][q_], o["den_now"][q_], 1e-9)
                    for q_ in o["num_now"]), (r["k"], o["k"]))
    hk = {r_: hand_rate(h.frame, nc, dc, TD_GRID) for r_, (nc, dc) in TD_COLS.items()}
    chk("(the fixture is worth it: no pull sits at an end of the list, and "
        "each end would have been a worse pick)",
        all(TD_GRID[0] < hk[r_]["k"] < TD_GRID[-1]
            and hk[r_]["miss"][hk[r_]["k"]] < min(hk[r_]["miss"][TD_GRID[0]],
                                                  hk[r_]["miss"][TD_GRID[-1]])
            for r_ in TD_COLS), {r_: hk[r_]["k"] for r_ in TD_COLS})
    chk("(...and it has positions on both sides of the 200 a position needs "
        "for a rate of its own: receivers' targets and backs' carries are "
        "over it; tight ends' targets, quarterbacks' carries and receivers' "
        "carries are under it, with raw rates far from the all-player one)",
        set(hk["td_per_target"]["by_pos"]) == {"WR"}
        and set(hk["td_per_carry"]["by_pos"]) == {"RB"}
        and set(hk["td_per_attempt"]["by_pos"]) == {"QB"}
        and {"TE", "RB"} <= set(hk["td_per_target"]["thin"])
        and {"QB", "WR"} <= set(hk["td_per_carry"]["thin"])
        and abs(hk["td_per_target"]["thin"]["TE"] - hk["td_per_target"]["overall"]) > 0.02
        and abs(hk["td_per_carry"]["thin"]["WR"] - hk["td_per_carry"]["overall"]) > 0.02,
        (hk["td_per_target"]["thin"], hk["td_per_carry"]["thin"]))

    def te_targets(total):
        d = h.frame.copy()
        te = d.index[d.position == "TE"]
        d.loc[te, "targets"] = 5.0
        d.loc[te[0], "targets"] = total - 5.0 * (len(te) - 1)
        return History(d, T)

    at200, at199 = te_targets(200.0), te_targets(199.0)
    chk("a position with exactly 200 targets in the history has a rate of "
        "its own, its touchdowns over its targets; with 199 it has none",
        float(at200.frame.targets[at200.frame.position == "TE"].sum()) == 200.0
        and near(TouchdownModel().fit(at200).rate["td_per_target"]["by_pos"]["TE"],
                 float(h.frame.receiving_tds[h.frame.position == "TE"].sum()) / 200.0, 1e-12)
        and "TE" not in TouchdownModel().fit(at199).rate["td_per_target"]["by_pos"]
        and float(at199.frame.targets[at199.frame.position == "TE"].sum()) == 199.0)

    nopos = h.frame.copy()
    nopos["position"] = nopos.position.where(nopos.player_id != "DDD_WR1", None)
    hn = History(nopos, T)
    fn = TouchdownModel().fit(hn)
    chk("a player with no position on file is judged against the all-player "
        "rate: the pull, every position's rate and every candidate's score "
        "still match the long-hand ones",
        all(fn.rate[r_]["k"] == (o := hand_rate(hn.frame, nc, dc, TD_GRID))["k"]
            and set(fn.rate[r_]["by_pos"]) == set(o["by_pos"])
            and all(near(fn.rate[r_]["by_pos"][q_], o["by_pos"][q_], 1e-12)
                    for q_ in o["by_pos"])
            and all(near(fn.rate[r_]["miss"][k_] / o["miss"][k_], 1.0, 1e-9)
                    for k_ in TD_GRID) for r_, (nc, dc) in TD_COLS.items())
        and fn.rate["td_per_target"]["miss"] != fit.rate["td_per_target"]["miss"])

    a = fs.slate_active(f, h)
    new = a[a.player_id == "AAA_WR2"].assign(player_id="NEWMAN", name="NEWMAN")
    odd = a[a.player_id == "BBB_TE"].assign(player_id="KICKER", name="KICKER",
                                            position="K")
    blank = a[a.player_id == "DDD_TE"].assign(player_id="NOPOS", name="NOPOS",
                                              position=None)
    full = pd.concat([a, new, odd, blank], ignore_index=True)
    got, want = m.parts(h, full), hand_td(h.frame, full)
    var = m.variances(h, full)
    idx = {p_: i for i, p_ in enumerate(full.player_id)}
    size = want["base"]["size"]
    rt, tt, tc = m.rates(h, full), hk["td_per_target"], hk["td_per_carry"]
    own = tt["num_now"]["AAA_WR1"] / tt["den_now"]["AAA_WR1"]
    newte = a[a.player_id == "CCC_TE"].assign(player_id="NEWTE", name="NEWTE")
    newrb = a[a.player_id == "CCC_RB"].assign(player_id="NEWRB", name="NEWRB")
    rs = m.rates(h, pd.concat([full, newte, newrb], ignore_index=True))
    chk("(the long-hand slate exercises what it should: a first-game player "
        "is given his position's rate where the position has one, and the "
        "all-player rate where it is too thin to; an unseen or missing "
        "position the all-player one; and a receiver's own rate sits "
        "between his raw rate and his position's)",
        near(rt["td_per_target"][idx["NEWMAN"]], tt["by_pos"]["WR"], 1e-12)
        and near(rt["td_per_carry"][idx["NEWMAN"]], tc["overall"], 1e-12)
        and near(rs["td_per_target"][-2], tt["overall"], 1e-12)
        and near(rs["td_per_carry"][-1], tc["by_pos"]["RB"], 1e-12)
        and near(rt["td_per_target"][idx["KICKER"]], tt["overall"], 1e-12)
        and near(rt["td_per_target"][idx["NOPOS"]], tt["overall"], 1e-12)
        and near(rt["td_per_carry"][idx["NOPOS"]], tc["overall"], 1e-12)
        and abs(tt["by_pos"]["WR"] - tt["overall"]) > 1e-4
        and abs(tc["by_pos"]["RB"] - tc["overall"]) > 1e-4
        and min(tt["by_pos"]["WR"], own) < rt["td_per_target"][idx["AAA_WR1"]]
        < max(tt["by_pos"]["WR"], own) and abs(own - tt["by_pos"]["WR"]) > 0.01
        and set(rt) == set(TD_COLS),
        (rt["td_per_target"][idx["AAA_WR1"]], own, tt["by_pos"]["WR"], tt["overall"]))
    chk("expected passing touchdowns are his expected attempts times his "
        "pulled rate, by hand", same(got["mean"]["passing_tds"], want["thrown"])
        and got["mean"]["passing_tds"][idx["BBB_QB"]] > 0.3
        and math.isnan(got["mean"]["passing_tds"][idx["AAA_WR1"]]))
    chk("expected anytime touchdowns are his targets times one rate plus his "
        "carries times another, by hand", same(got["mean"][TD_STAT], want["anytime"])
        and got["mean"][TD_STAT][idx["NEWMAN"]] > 0
        and got["mean"][TD_STAT][idx["KICKER"]] > 0)
    chk("...built from a receiving part spread as his targets are and a "
        "rushing part spread as his carries are",
        same(got["td"][TD_STAT][0][0], want["recv"])
        and same(got["td"][TD_STAT][1][0], want["rush"])
        and near(got["td"][TD_STAT][0][1], size["targets"], 1e-6)
        and near(got["td"][TD_STAT][1][1], size["carries"], 1e-6)
        and near(got["td"]["passing_tds"][0][1], size["attempts"], 1e-6)
        and len({round(size[s_], 6) for s_ in ("targets", "carries", "attempts")}) == 3)
    chk("the variance it reports is each part's own, added",
        same(var[TD_STAT], [x + x * x / size["targets"] + y + y * y / size["carries"]
                            for x, y in zip(want["recv"], want["rush"])], 1e-7)
        and same(var["passing_tds"], [x + x * x / size["attempts"]
                                      for x in want["thrown"]], 1e-7))
    eff_parts = EfficiencyModel().parts(h, full)
    chk("everything the efficiency model gives passes through unchanged: "
        "expected numbers, variances, and what they are built from",
        all(same(got["mean"][s_], eff_parts["mean"][s_]) for s_ in fe.EFF_STATS)
        and all(same(var[s_], EfficiencyModel().variances(h, full)[s_])
                for s_ in fe.EFF_STATS)
        and set(got) == set(eff_parts) | {"td"})

    P, E = m.project(h, full), EfficiencyModel().project(h, full)
    i, q, b = idx["AAA_WR1"], idx["BBB_QB"], idx["CCC_RB"]
    chk("...and so do their single numbers and chances",
        all(P.point(j, s_) == E.point(j, s_) and P.p_over(j, s_, ln) == E.p_over(j, s_, ln)
            for j, s_, ln in ((i, "receptions", 4.5), (i, "receiving_yards", 55.5),
                              (b, "rushing_yards", 60.5), (b, "carries", 12.5),
                              (q, "passing_yards", 220.5), (q, "completions", 19.5))))
    chk("its single number for a touchdown stat is the expected count",
        P.point(b, TD_STAT) == got["mean"][TD_STAT][b]
        and P.point(q, "passing_tds") == got["mean"]["passing_tds"][q])
    for who, j in (("a back", b), ("a receiver", i)):
        x, y = want["recv"][j], want["rush"][j]
        none = ((size["targets"] / (size["targets"] + x)) ** size["targets"]
                * (size["carries"] / (size["carries"] + y)) ** size["carries"])
        two = sum(nb_pmf(u, x, size["targets"]) * nb_pmf(v, y, size["carries"])
                  for u in range(40) for v in range(40) if u + v >= 2)
        chk(f"the chance {who} scores is one minus the chance of no receiving "
            f"and no rushing touchdown; of two or more, the double sum over "
            f"both counts", near(P.p_over(j, TD_STAT, 0.5), 1.0 - none, 1e-9)
            and near(P.p_over(j, TD_STAT, 1.5), two, 1e-9)
            and 0.02 < P.p_over(j, TD_STAT, 0.5) < 0.98, (P.p_over(j, TD_STAT, 0.5),
                                                         1.0 - none))
    chk("the chance of a passing-touchdown line is the count's chance of "
        "MORE than it, spread as his attempts are",
        near(P.p_over(q, "passing_tds", 1.5),
             nb_tail(1, want["thrown"][q], size["attempts"]), 1e-9)
        and near(P.p_over(q, "passing_tds", 0.5),
                 nb_tail(0, want["thrown"][q], size["attempts"]), 1e-9))
    chk("landing exactly on a whole-number line is not over it; any count "
        "beats a line below zero",
        P.p_over(q, "passing_tds", 1.0) == P.p_over(q, "passing_tds", 1.5)
        < P.p_over(q, "passing_tds", 0.5) < P.p_over(q, "passing_tds", -0.5) == 1.0
        and P.p_over(q, "passing_tds", -1.0) == 1.0
        and P.p_over(q, "passing_tds", 0.0) == P.p_over(q, "passing_tds", 0.5)
        and P.p_over(b, TD_STAT, 1.0) == P.p_over(b, TD_STAT, 1.5)
        and P.p_over(b, TD_STAT, 0.0) == P.p_over(b, TD_STAT, 0.5)
        and P.p_over(b, TD_STAT, -0.5) == 1.0)
    for ln in (6.5, 20.5, 30.5):
        far = sum(nb_pmf(u, want["thrown"][q], size["attempts"])
                  for u in range(int(ln) + 1, 400))
        x, y = want["recv"][b], want["rush"][b]
        both = sum(nb_pmf(u, x, size["targets"])
                   * sum(nb_pmf(v, y, size["carries"])
                         for v in range(max(int(ln) + 1 - u, 0), 300))
                   for u in range(300))
        chk(f"a line as far out as {ln} is priced as exactly as a near one, "
            f"for one count and for the sum of two",
            near(P.p_over(q, "passing_tds", ln) / far, 1.0, 1e-6) and far > 0
            and near(P.p_over(b, TD_STAT, ln) / both, 1.0, 1e-6) and both > 0,
            (P.p_over(q, "passing_tds", ln), far, P.p_over(b, TD_STAT, ln), both))
    ladders = [[P.p_over(j, s_, k_ + 0.5) for k_ in range(60)]
               for j, s_ in ((b, TD_STAT), (i, TD_STAT), (q, "passing_tds"))]
    chk("no chance it states is below zero or above one, however far the "
        "line, and a higher line is never likelier",
        all(0.0 <= v_ <= 1.0 for lad in ladders for v_ in lad)
        and all(lad[n_ + 1] < lad[n_] for lad in ladders for n_ in range(59))
        and all(0.0 <= P.p_over(j, TD_STAT, 500.5) < 1e-100 for j in range(len(full))
                if not math.isnan(got["mean"][TD_STAT][j])))
    grid = [ft._TdLines(None, {"mean": {TD_STAT: np.array([m0 + m1])},
                               "td": {TD_STAT: [(np.array([m0]), r0),
                                                (np.array([m1]), r1)]}}
                        ).p_over(0, TD_STAT, n_ - 0.5)
            for m0 in (0.05, 1.0, 8.0, 60.0) for m1 in (0.05, 1.0, 8.0, 60.0)
            for r0 in (3.0, 8.0, 500.0) for r1 in (3.0, 40.0, 500.0) for n_ in (1, 2, 3, 5)]
    chk("...nor does rounding ever carry a chance over one, even for a "
        "player expected an absurd sixty touchdowns",
        len(grid) == 576 and all(0.0 <= v_ <= 1.0 for v_ in grid) and max(grid) == 1.0
        and min(grid) < 0.01, (min(grid), max(grid)))
    chk("a line that is not a number is refused by name, for a player with "
        "a projection and for one without",
        raises(lambda: P.p_over(q, "passing_tds", float("nan")), ValueError,
               "passing_tds line must be a number")
        and raises(lambda: P.p_over(b, TD_STAT, float("inf")), ValueError,
                   "anytime_tds line must be a number")
        and raises(lambda: P.p_over(i, "passing_tds", float("nan")), ValueError,
                   "must be a number"))
    chk("the chances it states add up to the expected count",
        all(near(sum(P.p_over(j, s_, k_ + 0.5) for k_ in range(12)),
                 got["mean"][s_][j], 1e-6)
            for j, s_ in ((b, TD_STAT), (i, TD_STAT), (q, "passing_tds"))))
    chk("it gives a receiver no passing touchdowns, and has no number for a "
        "stat nobody projects",
        math.isnan(P.p_over(i, "passing_tds", 0.5)) and math.isnan(P.point(i, "passing_tds"))
        and math.isnan(P.p_over(i, "passing_tds", -0.5))
        and math.isnan(P.point(i, "first_td")) and math.isnan(P.p_over(i, "first_td", 0.5)))

    def only(n, col, *more):
        d = h.frame.copy()
        keep = d.index[d[col] > 0][:n]
        for c in (col, *more):
            d[c] = d[c].where(d.index.isin(keep), 0.0)
        return History(d, T)

    for col, more, word in (("targets", ("receiving_tds",), "target"),
                            ("carries", ("rushing_tds",), "carry"),
                            ("attempts", ("passing_tds",), "pass attempt")):
        tm = TouchdownModel()
        chk(f"sixteen games with a {word} are enough to learn its touchdown "
            f"rate from; fifteen are not, and it says which",
            tm.fit(only(16, col, *more)).ok
            and not TouchdownModel().fit(only(15, col, *more)).ok
            and f"15 player-games with a {word} " in TouchdownModel().fit(
                only(15, col, *more)).why)
    thin = TouchdownModel()
    th = only(15, "attempts", "passing_tds")
    chk("...and then it says nothing at all, for any stat, and every rate "
        "is blank",
        all(np.isnan(thin.parts(th, a)["mean"][s_]).all() for s_ in ft.ALL_STATS)
        and all(np.isnan(v_).all() for v_ in thin.rates(th, a).values())
        and math.isnan(thin.project(th, a).p_over(0, TD_STAT, 0.5))
        and math.isnan(thin.project(th, a).p_over(0, "receptions", 2.5)))
    changed = f[f.t < T].copy()
    changed.loc[changed.player_id == "AAA_WR1", "receiving_tds"] = 0.0
    hc = History(changed, T)
    used = TouchdownModel()
    used.fit(h)
    chk("a model that has fitted one history fits another afresh, even one "
        "that stops at the same week",
        used.fit(hc) is not used.fit(h) and used.fit(h) is used.fit(h)
        and used.fit(hc).rate["td_per_target"]["num_now"]["AAA_WR1"] == 0.0
        and fit.rate["td_per_target"]["num_now"]["AAA_WR1"] > 0)

    eff = EfficiencyModel("e", opportunity=OpportunityModel("o", lines=lines))
    on = TouchdownModel("with_lines", efficiency=eff)
    chk("it sits on the efficiency model it is given; with none it makes "
        "its own, named after itself",
        on.eff is eff and on.name == "with_lines" and TouchdownModel().name == "touchdowns"
        and not same(on.parts(h, full)["mean"][TD_STAT], got["mean"][TD_STAT])
        and TouchdownModel("abc").eff.name == "abc_efficiency")


@section("31. touchdowns — through the harness, and real data")
def _():
    f, _ = td_league()
    T = 202404
    h = History(f[f.t < T], T)
    a = fs.slate_active(f, h)
    run = fs.walk_forward(f, [TouchdownModel(), fs.LastFour()], weeks=[202403, T])
    L = run.legs[run.legs.version == "A"]
    chk("through the harness it prices every stat there is, touchdowns "
        "included",
        L.p_touchdowns.notna().all() and set(L.stat) == set(ft.ALL_STATS)
        and (L.stat == TD_STAT).sum() > 5 and (L.stat == "passing_tds").sum() > 2)
    hw = run.points[(run.points.version == "A") & (run.points.player_id == "CCC_RB")
                    & (run.points.stat == TD_STAT) & (run.points.week == 4)]
    at = list(a.player_id).index("CCC_RB")
    chk("...and the number the harness records is the long-hand one",
        len(hw) == 1 and near(float(hw.pt_touchdowns.iloc[0]),
                              hand_td(h.frame, a)["anytime"][at], 1e-9))
    sat = f[~((f.t == T) & (f.player_id == "AAA_WR2"))]
    sp = fs.walk_forward(sat, [TouchdownModel()], weeks=[T]).points
    sp = sp[(sp.stat == TD_STAT) & (sp.team == "AAA")]
    ab = sp[sp.version == "A"].merge(sp[sp.version == "B"], on=["game_id", "player_id"],
                                     suffixes=("_a", "_b"))
    chk("its touchdown numbers differ between the two slates when a regular "
        "sits out: his teammates are expected more with him known to be out",
        len(ab) >= 3 and (ab.pt_touchdowns_a > ab.pt_touchdowns_b + 1e-6).any()
        and not (ab.pt_touchdowns_a < ab.pt_touchdowns_b - 1e-9).any(),
        ab[["player_id", "pt_touchdowns_a", "pt_touchdowns_b"]].to_dict("records")[:3])
    probe = fs.leak_probe(f, [TouchdownModel()], [202403, T])
    chk("the leak probe finds nothing reaching it through the harness",
        probe.clean and probe.outputs["touchdowns"] > 300, probe.describe()[:100])
    ea = fe.expected_vs_actual(TouchdownModel(), f, [T], stats=ft.TD_STATS)
    parts = TouchdownModel().parts(h, a)
    d = ea[ea.stat == TD_STAT].set_index("player_id")
    chk("the efficiency model's expected-beside-actual table works on it: "
        "each player's expected touchdowns, what he scored that week, and "
        "the chance it gives of beating its own number",
        set(ea.stat) == set(ft.TD_STATS)
        and all(near(d.expected[r.player_id], parts["mean"][TD_STAT][i], 1e-12)
                and d.actual[r.player_id] == float(
                    f[(f.t == T) & (f.player_id == r.player_id)][TD_STAT].iloc[0])
                for i, r in enumerate(a.itertuples()))
        and near(d.said_above["CCC_RB"], TouchdownModel().project(h, a).p_over(
            at, TD_STAT, parts["mean"][TD_STAT][at]), 1e-12)
        and (ea.stat == "passing_tds").sum() == int(a.starting_qb.sum()))
    pv = ft.parts_vs_actual(TouchdownModel(), f, [202403, T])
    one = pv[pv.t == T].reset_index(drop=True)
    hw_ = hand_td(h.frame, a)
    Pa = TouchdownModel().project(h, a)
    now = f[f.t == T].set_index("player_id")
    chk("the table of expected beside actual has one row per week and active "
        "player with a number, in slate order, saying who he is",
        list(one.player_id) == list(a.player_id) and list(one.team) == list(a.team)
        and list(one.position) == list(a.position)
        and list(one.starter) == list(a.starting_qb) and set(pv.t) == {202403, T}
        and list(one.game_id) == list(a.game_id) and len(pv) > len(one) > 12)
    chk("...what it expected of him is the long-hand number, column by "
        "column: targets, carries, attempts, and each kind of touchdown",
        same(one.e_targets, hw_["base"]["mean"]["targets"])
        and same(one.e_carries, hw_["base"]["mean"]["carries"])
        and same(one.e_attempts, hw_["base"]["mean"]["attempts"])
        and same(one.e_rec_td, hw_["recv"]) and same(one.e_rush_td, hw_["rush"])
        and same(one.e_pass_td, hw_["thrown"])
        and not same(one.e_rec_td, one.e_rush_td))
    chk("...the chances are of one or more and of two or more",
        same(one.p1, [Pa.p_over(j, TD_STAT, 0.5) for j in range(len(a))])
        and same(one.p2, [Pa.p_over(j, TD_STAT, 1.5) for j in range(len(a))])
        and (one.p1 > one.p2).all())
    chk("...and what he did is that week's, for that player",
        all(list(one[c]) == [float(now.at[q_, c]) for q_ in one.player_id]
            for c in ("targets", "carries", "attempts", "receiving_tds",
                      "rushing_tds", "passing_tds", TD_STAT))
        and one[TD_STAT].sum() > 0 and one.passing_tds.sum() > 0
        and list(pv[pv.t == 202403][TD_STAT]) == [
            float(f[(f.t == 202403) & (f.player_id == q_)][TD_STAT].iloc[0])
            for q_ in pv[pv.t == 202403].player_id])
    thin_week = ft.parts_vs_actual(TouchdownModel(), f, [202302, T])
    h2 = History(f[f.t < 202302], 202302)
    chk("...a player it has no number for is left out, not shown as a blank: "
        "a week whose history is too thin to fit gives no rows at all",
        np.isnan(TouchdownModel().parts(h2, fs.slate_active(f, h2))["mean"][TD_STAT]).all()
        and len(fs.slate_active(f, h2)) > 12
        and set(thin_week.t) == {T} and len(thin_week) == len(one)
        and thin_week.p1.notna().all() and thin_week.e_rec_td.notna().all())
    pk = ft.pulls_picked(TouchdownModel(), f, [202301, 202403, T])
    chk("the pulls picked are listed week by week, each the long-hand pick on "
        "the history before that week; a week with too little history is "
        "left out",
        list(pk.t) == [202403, T] and list(pk.columns) == ["t", *TD_COLS]
        and all(pk[r_].iloc[1] == hand_rate(h.frame, nc, dc, TD_GRID)["k"]
                and pk[r_].iloc[0] == hand_rate(f[f.t < 202403], nc, dc, TD_GRID)["k"]
                for r_, (nc, dc) in TD_COLS.items()), pk.to_dict("records"))
    wl = fe.with_main_line(run, fe.expected_vs_actual(
        TouchdownModel(), f, [202403, T], stats=ft.TD_STATS), "touchdowns",
        stats=ft.TD_STATS)
    chk("...and so does its table of players with a line: an anytime line "
        "is always a half", set(wl.stat) == set(ft.TD_STATS)
        and (wl[wl.stat == TD_STAT].line == 0.5).all() and len(wl) > 8)

    frame = REAL.get("frame")
    if frame is None:
        frame = fs.load_frame()
    wk = fs.test_weeks(frame)[-2:]
    rr = fs.walk_forward(frame, [TouchdownModel()], weeks=wk)
    ra = rr.legs[(rr.legs.version == "A") & rr.legs.stat.isin(ft.TD_STATS)]
    pv = ra.p_touchdowns.to_numpy(dtype=float)
    chk("on real weeks it prices every touchdown leg, between 0 and 1",
        not np.isnan(pv).any() and pv.min() >= 0 and pv.max() <= 1 and len(ra) > 300,
        len(ra))
    hr = History(frame[frame.t < wk[-1]], wk[-1])
    sa = fs.slate_active(frame, hr)
    rm = TouchdownModel()
    rfit, rt = rm.fit(hr), rm.rates(hr, sa)
    pos = sa.position.to_numpy()
    chk("on real history the pull picked for each rate is inside the list",
        all(TD_GRID[0] < rfit.rate[r_]["k"] < TD_GRID[-1] for r_ in TD_COLS),
        {r_: rfit.rate[r_]["k"] for r_ in TD_COLS})
    chk("...and the rates are football: a receiver scores on a few targets "
        "in a hundred, a back on a few carries in a hundred, a starter "
        "throws a touchdown on four or five attempts in a hundred",
        0.02 < np.median(rt["td_per_target"][pos == "WR"]) < 0.08
        and 0.015 < np.median(rt["td_per_carry"][pos == "RB"]) < 0.06
        and 0.03 < rt["td_per_attempt"][sa.starting_qb.to_numpy()].min()
        and rt["td_per_attempt"][sa.starting_qb.to_numpy()].max() < 0.07,
        (np.median(rt["td_per_target"][pos == "WR"]),
         np.median(rt["td_per_carry"][pos == "RB"])))
    starters = sa[sa.starting_qb.to_numpy()]
    odd = pd.concat([starters.iloc[:1].assign(position="RB"),
                     sa[pos == "WR"].iloc[:1].assign(position="CB"),
                     sa[pos == "WR"].iloc[:1].assign(player_id="NOBODY", position="DE")],
                    ignore_index=True)
    ro = rm.rates(hr, odd)
    chk("on real history only a position with 200 of the thing has its own "
        "rate: quarterbacks alone for pass attempts; backs, receivers and "
        "tight ends for targets; no lineman or cornerback for anything",
        set(rfit.rate["td_per_attempt"]["by_pos"]) == {"QB"}
        and {"RB", "WR", "TE"} <= set(rfit.rate["td_per_target"]["by_pos"])
        and {"RB", "QB"} <= set(rfit.rate["td_per_carry"]["by_pos"])
        and not {"CB", "DE", "DT", "OT", "T", "G", "C", "LB", "S", "P", "K"} & set().union(
            *(rfit.rate[r_]["by_pos"] for r_ in TD_COLS)),
        {r_: sorted(rfit.rate[r_]["by_pos"]) for r_ in TD_COLS})
    chk("...so a starter listed at running back is pulled toward the "
        "all-player rate of touchdown passes, which is a quarterback's, and "
        "a cornerback or a new defensive end is given the all-player rate "
        "per target, not one catch's worth",
        0.03 < ro["td_per_attempt"][0] < 0.07
        and near(rfit.rate["td_per_attempt"]["overall"]
                 / rfit.rate["td_per_attempt"]["by_pos"]["QB"], 1.0, 0.02)
        and near(ro["td_per_target"][2], rfit.rate["td_per_target"]["overall"], 1e-12)
        and 0.02 < ro["td_per_target"][1] < 0.12
        and 0.03 < rfit.rate["td_per_target"]["overall"] < 0.07,
        (ro["td_per_attempt"][0], ro["td_per_target"][1], ro["td_per_target"][2]))
    pm = rm.parts(hr, sa)["mean"]
    pr_ = rm.project(hr, sa)
    best = int(np.nanargmax(pm[TD_STAT]))
    chk("...the likeliest scorer on the slate is likely but not certain, "
        "and a real starter is expected one to two and a half touchdown "
        "passes",
        0.4 < pr_.p_over(best, TD_STAT, 0.5) < 0.85
        and 0.8 < pm["passing_tds"][sa.starting_qb.to_numpy()].min()
        and pm["passing_tds"][sa.starting_qb.to_numpy()].max() < 2.6,
        (pr_.p_over(best, TD_STAT, 0.5), pm["passing_tds"][sa.starting_qb.to_numpy()].max()))
    lp = fs.leak_probe(frame, [TouchdownModel()], wk[-1:])
    chk("the leak probe finds nothing reaching it through the harness, on "
        "real data", lp.clean, lp.describe()[:100])


# ===========================================================================
# S28 — the live run (ff_sim_live.py)
# ===========================================================================
fl = None


def _oc(name, desc, point, pid, team=None):
    """One outcome with every key a real one carries (prices are not read)."""
    d = {"name": name, "description": desc, "price": -110, "point": point,
         "book_updated_at": None, "book_version": None, "payout_multiplier": None,
         "dfs_odds_type": None, "last_change_at": "2026-11-21T03:49:42.654510Z",
         "last_seen_at": "2026-11-21T04:38:35.212762Z", "liquidity": None,
         "liquidity_updated_at": None, "line_gap": None, "book_outcome_id": None,
         "outcome_id": None, "player_id": pid, "side": None}
    if team:
        d["player_team"] = team
    return d


def odds_event(home, away, books):
    """An event response in the real shape. `books` is {book: [(market key,
    line type, suspended_at, [(name, description, point, player id)])]}."""
    return {"id": "1", "sport_key": "americanfootball_nfl", "home_team": home,
            "away_team": away, "commence_time": "2024-09-29T17:00:00Z",
            "bookmakers": [{"key": b, "title": b, "pregame_only": False, "markets": [
                {"key": k, "description": k, "period": None, "suspended_at": sus,
                 "team": None, "line_type": lt,
                 "outcomes": [_oc(n, dsc, pt, pid) for n, dsc, pt, pid in ocs]}
                for k, lt, sus, ocs in mkts]} for b, mkts in books.items()]}


def real_event():
    """A trimmed copy of a real `propline_get_odds` response: event 723936,
    Las Vegas at Denver, DraftKings, pulled 2026-11-21. The keys, names,
    ids, lines and line types are the response's own; most outcomes are
    cut."""
    DEN, LV = "Denver Broncos", "Las Vegas Raiders"
    two = [("Adam Trautman", "espn:3911853", DEN), ("Ashton Jeanty", "espn:4890973", LV),
           ("Bo Nix", "espn:4426338", DEN), ("Brock Bowers", "espn:4432665", LV),
           ("Courtland Sutton", "espn:3128429", DEN), ("DEN Broncos D/ST", None, None),
           ("J.K. Dobbins", "espn:4241985", DEN), ("Marvin Mims", "espn:4686472", DEN),
           ("Mike Washington Jr.", "espn:4686658", LV), ("Tre Tucker", "espn:4428718", LV)]

    def mk(key, desc, lt, outcomes):
        return {"key": key, "description": desc, "last_update": "2026-11-21T04:38:35.212762Z",
                "period": None, "suspended_at": None, "team": None, "line_type": lt,
                "outcomes": outcomes}

    def qb(name, pid, team, rungs, point):
        return [mk("player_pass_tds", f"{name} Passing Touchdowns", "milestone",
                   [_oc(f"{k}+ Passing Touchdowns", name, None, pid, team) for k in rungs]),
                mk("player_pass_tds", f"{name} Passing Touchdowns O/U", "main",
                   [_oc("Over", name, point, pid, team), _oc("Under", name, point, pid, team)])]

    return {"home_team_key": "broncos", "away_team_key": "raiders", "id": "723936",
            "sport_key": "americanfootball_nfl", "home_team": DEN, "away_team": LV,
            "commence_time": "2026-11-22T21:25:00Z", "live": False, "is_outright": False,
            "last_update": "2026-11-21T04:38:35.212762Z",
            "bookmakers": [{"key": "draftkings", "title": "DraftKings",
                            "last_update": "2026-11-21T04:38:35.212762Z", "link": None,
                            "app_link": None, "pregame_only": False, "book_event_id": None,
                            "markets": [
                                mk("player_2plus_td", "2+ TDs", "milestone",
                                   [_oc(n, n, None, i, t) for n, i, t in two]),
                                *qb("Fernando Mendoza", "espn:4837248", LV, (1, 2, 3), 0.5),
                                *qb("Bo Nix", "espn:4426338", DEN, (1, 2, 3, 4, 5), 1.5)]}]}


def _json_copy(x):
    import json
    return json.loads(json.dumps(x))


LIVE_TEAMS = {"AAA": "ARI", "BBB": "ATL", "CCC": "BAL", "DDD": "BUF"}
LIVE_NAMES = {"QB": "Passer", "RB": "Back", "WR1": "One", "WR2": "Two", "TE": "End"}
LIVE_FIRST = {"AAA": ("Art", "Rob", "Wes", "Will", "Ted"), "BBB": ("Abe", "Ray", "Walt", "Wade", "Tom"),
              "CCC": ("Cal", "Rex", "Wyn", "Ward", "Tim"), "DDD": ("Dan", "Rod", "Wim", "Webb", "Tad")}


def live_frame():
    """The touchdown league under real team codes and people's names, every
    week of it."""
    return live_league(cut=False)[0]


def live_league(cut=True):
    """(frame, roster, reports): the touchdown league under real team codes
    and people's names, a roster with an ESPN number for most of them, and
    an injury report for 2024 Week 4, which the frame is cut off before."""
    f, _ = td_league()
    f = f.copy()
    name, rost = {}, []
    for tm, firsts in LIVE_FIRST.items():
        for k, (role, first) in enumerate(zip(("QB", "RB", "WR1", "WR2", "TE"), firsts)):
            pid = f"{tm}_{role}"
            name[pid] = f"{first} {LIVE_NAMES[role]}" + (" Jr." if role == "WR2" else "")
            rost.append((pid, None if role == "TE" else float(10 * (1 + list(LIVE_FIRST).index(tm)) + k + 1),
                         name[pid], LIVE_TEAMS[tm], role[:2]))
    f["name"] = f.player_id.map(name).fillna(f["name"])
    for c in ("team", "opponent"):
        f[c] = f[c].map(LIVE_TEAMS)
    rost += [("NEW_WR", 99.0, "Nat Newman", "ATL", "WR"), ("TWIN_1", 71.0, "Sam Twin", "ARI", "WR"),
             ("TWIN_2", 72.0, "Sam Twin", "ARI", "TE"), ("00-0099999", 73.0, "Ivan Dee", "ARI", "QB"),
             (None, 74.0, "No Id", "ARI", "WR")]
    roster = pd.DataFrame(rost, columns=["gsis_id", "espn_id", "full_name", "team", "position"])
    reports = pd.DataFrame([(202404, "AAA_WR2", "questionable"), (202403, "AAA_TE", "out")],
                           columns=["t", "player_id", "status"])
    return (f[f.t < 202404] if cut else f).reset_index(drop=True), roster, reports


LIVE_IN = {"season": 2024, "week": 4, "statuses": [], "chances": [], "add": [],
           "starters": {"ARI": "Art Passer", "ATL": "Abe Passer",
                        "BAL": "Cal Passer", "BUF": "Dan Passer"}}


@section("32. live run — it loads, and reads what the thread saved")
def _():
    global fl
    import ff_sim_live
    fl = ff_sim_live
    chk("it knows all 32 teams, each with a code of its own, and a stat for "
        "twelve markets",
        len(fl.TEAM_CODE) == 32 and len(set(fl.TEAM_CODE.values())) == 32
        and fl.TEAM_CODE["Los Angeles Rams"] == "LA"
        and fl.TEAM_CODE["Washington Commanders"] == "WAS"
        and len(fl.MARKETS) == 12
        and fl.MARKETS["player_anytime_td"] == (TD_STAT, 0.5)
        and fl.MARKETS["player_2plus_td"] == (TD_STAT, 1.5)
        and fl.MARKETS["player_3plus_td"] == (TD_STAT, 2.5)
        and {v[0] for v in fl.MARKETS.values()} == set(ft.ALL_STATS))
    ev = real_event()
    import json as _json
    import pathlib
    import tempfile as _tmp
    d = pathlib.Path(_tmp.mkdtemp())
    (d / "plain.json").write_text(_json.dumps(ev))
    (d / "wrapped.json").write_text(_json.dumps([{"type": "text", "text": _json.dumps(ev)}]))
    (d / "notjson.json").write_text("the tool timed out")
    chk("an odds response is read the same from the dict, its text, a file, "
        "and a file with the harness's wrapper round it",
        fl.read_odds(ev) == ev and fl.read_odds(_json.dumps(ev)) == ev
        and fl.read_odds(str(d / "plain.json")) == ev
        and fl.read_odds(d / "wrapped.json") == ev)
    (d / "bytes.json").write_bytes(b"\xff\xfe\x00\x81")
    chk("a file that is not there, is not text, is not JSON, is not an event "
        "response, or names a team it does not know is refused, saying which",
        raises(lambda: fl.read_odds(str(d / "absent.json")), fl.Missing, "cannot read the odds file")
        and raises(lambda: fl.read_odds(str(d / "bytes.json")), fl.Missing, "cannot read the odds file")
        and raises(lambda: fl.read_odds(str(d / "notjson.json")), fl.Missing, "is not JSON")
        and raises(lambda: fl.read_odds([ev]), fl.Missing, "not a get_odds EVENT response")
        and raises(lambda: fl.read_odds([{"type": "text", "text": "Error: timed out"}]),
                   fl.Missing, "a saved tool result whose text is not JSON")
        and raises(lambda: fl.read_odds({"home_team": "Denver Broncos"}), fl.Missing,
                   "no 'bookmakers' list")
        and raises(lambda: fl.read_odds(dict(ev, away_team="London Monarchs")), fl.Missing,
                   "away_team is 'London Monarchs'")
        and raises(lambda: fl.read_odds(dict(ev, home_team=None)), fl.Missing, "home_team is None"))

    L = fl.posted_lines(ev)
    got = sorted(zip(L.player, L.stat, L.line, L.kind))
    want = sorted(
        [(n, TD_STAT, 1.5, "ladder") for n in (
            "Adam Trautman", "Ashton Jeanty", "Bo Nix", "Brock Bowers",
            "Courtland Sutton", "J.K. Dobbins", "Marvin Mims",
            "Mike Washington Jr.", "Tre Tucker")]
        + [("Fernando Mendoza", "passing_tds", x, "ladder") for x in (0.5, 1.5, 2.5)]
        + [("Fernando Mendoza", "passing_tds", 0.5, "main")]
        + [("Bo Nix", "passing_tds", x, "ladder") for x in (0.5, 1.5, 2.5, 3.5, 4.5)]
        + [("Bo Nix", "passing_tds", 1.5, "main")])
    chk("a real DraftKings response (trimmed) gives the lines by hand: an "
        "over/under pair is ONE main line at its point, an N+ rung is half a "
        "point under N, a 2+ touchdown name is 1.5, and the D/ST is left out",
        got == want and list(L.columns) == ["book", "market", "stat", "player",
                                            "player_key", "line", "kind", "suspended"]
        and set(L.book) == {"draftkings"} and not L.suspended.any()
        and dict(zip(L.player, L.player_key))["Bo Nix"] == "espn:4426338", got[:4])

    made = odds_event("Atlanta Falcons", "Arizona Cardinals", {
        "booka": [
            ("player_receptions", "main", None, [("Over", "Wes One", 4.5, "espn:14"),
                                                 ("Under", "Wes One", 4.5, "espn:14")]),
            ("player_receptions", "alternate", None, [("Over", "Wes One", 6.5, "espn:14")]),
            ("player_receptions", "milestone", None, [("3+ Receptions", "Wes One", None, "espn:14")]),
            ("player_anytime_td", "milestone", None, [("Wes One", "Wes One", None, "espn:14"),
                                                      ("No Touchdown Scorer", "No Touchdown Scorer", None, None),
                                                      ("ARI Cardinals D/ST", "ARI Cardinals D/ST", None, None)]),
            ("player_3plus_td", "milestone", None, [("Wes One", "Wes One", None, "espn:14")]),
            ("player_rush_yds", "main", "2024-01-01T00:00:00Z",
             [("Over", "Rob Back", 61.5, "espn:12"), ("Under", "Rob Back", 61.5, "espn:12")]),
            ("player_pass_longest", "main", None, [("Over", "Art Passer", 35.5, "espn:11"),
                                                   ("Under", "Art Passer", 35.5, "espn:11")]),
            ("player_receptions", "milestone", None, [("Lots of Receptions", "Wes One", None, "espn:14")]),
            ("player_reception_targets", "main", None, [("Over", "Wes One", 7.0, "espn:14"),
                                                        ("Under", "Wes One", 7.0, "espn:14")])],
        "kalshi": [
            ("player_anytime_td", "main", None, [("Yes", "Wes One", None, None),
                                                 ("No", "Wes One", None, None)]),
            ("player_receptions", "main", None, [("Over", "Wes One", 5.5, "espn:14"),
                                                 ("Under", "Wes One", 5.5, "espn:14")])]})
    M = fl.posted_lines(made)
    rowsM = sorted(zip(M.book, M.market, M.stat, M.player, M.line, M.kind, M.suspended))
    chk("made-up boards: a main line, an alternate, a rung, an anytime name "
        "(0.5, main), a 3+ touchdown name (2.5), a Yes/No pair read as one "
        "line, a suspended market marked; the no-scorer row and the D/ST "
        "are left out",
        rowsM == sorted([
            ("booka", "player_receptions", "receptions", "Wes One", 4.5, "main", False),
            ("booka", "player_receptions", "receptions", "Wes One", 6.5, "ladder", False),
            ("booka", "player_receptions", "receptions", "Wes One", 2.5, "ladder", False),
            ("booka", "player_anytime_td", TD_STAT, "Wes One", 0.5, "main", False),
            ("booka", "player_3plus_td", TD_STAT, "Wes One", 2.5, "ladder", False),
            ("booka", "player_rush_yds", "rushing_yards", "Rob Back", 61.5, "main", True),
            ("booka", "player_reception_targets", "targets", "Wes One", 7.0, "main", False),
            ("kalshi", "player_anytime_td", TD_STAT, "Wes One", 0.5, "main", False),
            ("kalshi", "player_receptions", "receptions", "Wes One", 5.5, "main", False)]),
        rowsM)
    chk("...a market it has no stat for and a label it cannot read are left "
        "out too, and counted so the run can say so",
        M.attrs["passed_over"] == {"no stat for player_pass_longest": 1,
                                   "label not read in player_receptions": 1}
        and fl.posted_lines(real_event()).attrs["passed_over"] == {})
    odd = fl.posted_lines(odds_event("Atlanta Falcons", "Arizona Cardinals", {"booka": [
        ("player_anytime_td", "main", None, [("Over", "Wes One", 1.5, "espn:14"),
                                             ("Under", "Wes One", 1.5, "espn:14")]),
        ("player_rush_yds", "main", None, [("70+ Rushing Yards", "Rob Back", None, "espn:12")]),
        ("player_pass_attempts", "main", None, [("Over", "Art Passer", 33.5, "espn:11"),
                                                ("Under", "Art Passer", 33.5, "espn:11")]),
        ("player_pass_completions", "main", None, [("Over", "Art Passer", 21.5, "espn:11"),
                                                   ("Under", "Art Passer", 21.5, "espn:11")]),
        ("player_receptions", "main", None, [("Over", "Wes One", "five", "espn:14")])]}))
    chk("...a point posted on a touchdown market is the line used; an N+ "
        "rung inside a main market is still a ladder line; attempts and "
        "completions are each their own stat; a point that is not a number "
        "is counted as not read",
        sorted(zip(odd.stat, odd.line, odd.kind)) == sorted([
            (TD_STAT, 1.5, "main"), ("rushing_yards", 69.5, "ladder"),
            ("attempts", 33.5, "main"), ("completions", 21.5, "main")])
        and odd.attrs["passed_over"] == {"label not read in player_receptions": 1})
    chk("a response whose books, markets or outcomes are not in the shape "
        "of one is refused by game, not read on a guess",
        all(raises(lambda b=b: fl.posted_lines(dict(ev, bookmakers=b)), fl.Missing,
                   "the odds file is not in the shape of a get_odds response")
            for b in ([5], [{"key": "booka", "markets": "oops"}],
                      [{"key": "booka", "markets": [{"key": "player_receptions", "outcomes": [7]}]}],
                      [{"key": ["booka"], "markets": []}], [{"key": "booka", "markets": 7}],
                      [{"key": "booka", "markets": [{"key": "player_receptions", "outcomes": [
                          {"name": "Over", "description": {"a": 1}, "point": 1.5}]}]}])))
    U = lambda x: pd.Timestamp(x, tz="UTC")   # noqa: E731
    D = pd.DataFrame({"week": [3, 3, 3, 4, 16, 16, 16, 16],
                      "game_date": ["2024-09-19", "2024-09-22", "2024-09-23", "2024-09-26",
                                    "2024-12-19", "2024-12-21", "2024-12-22", "2024-12-23"]})
    W = fl.week_window(D, 4)
    chk("this week is the Wednesday-to-Tuesday week after last week's "
        "Sunday; with no such Sunday to go by (Week 1, no dates, a week "
        "not on file) there is no window",
        W == (U("2024-09-25 09:00"), U("2024-10-02 09:00"))
        and fl.week_window(D, 17) == (U("2024-12-25 09:00"), U("2025-01-01 09:00"))
        and fl.week_window(D, 1) is None and fl.week_window(None, 4) is None
        and fl.week_window(D, 5) is None and fl.week_window(D, 9) is None
        and fl.week_window(D.iloc[::-1], 4) == W)
    at = lambda when, **kw: dict(ev, commence_time=when, **kw)   # noqa: E731
    ok = lambda when, now, win, season=None: fl.check_kickoffs(   # noqa: E731
        [at(when)], U(now), win, season) == ([] if win is not None else [fl.NO_WINDOW])
    no = lambda when, now, win, msg: raises(   # noqa: E731
        lambda: fl.check_kickoffs([at(when)], U(now), win), fl.Missing, msg)
    chk("a game is refused when it is not in this week: next week's Thursday "
        "game, which is inside eight days by Friday, a Wednesday game of "
        "the week after, and last week's Tuesday night",
        ok("2024-09-29T17:00:00Z", "2024-09-27 12:00", W)
        and ok("2024-09-27T00:15:00Z", "2024-09-25 12:00", W)
        and ok("2024-10-01T00:15:00Z", "2024-09-27 12:00", W)
        and ok("2024-10-02T03:15:00Z", "2024-09-27 12:00", W)
        and ok("2024-09-25T09:00:00Z", "2024-09-24 12:00", W)
        and no("2024-10-04T00:15:00Z", "2024-09-27 12:00", W,
               fl.game_of(ev) + " kicks off 2024-10-04 00:15 UTC, which is not in this week "
               "(Wednesday 2024-09-25 to Tuesday 2024-10-01, going by last week's games): it is "
               "another week's game")
        and no("2024-10-02T09:00:00Z", "2024-09-27 12:00", W, "which is not in this week")
        and no("2024-10-02T18:00:00Z", "2024-09-27 12:00", W, "which is not in this week")
        and no("2024-09-25T03:15:00Z", "2024-09-24 12:00", W, "which is not in this week")
        and ok("2024-12-25T18:00:00Z", "2024-12-24 12:00", fl.week_window(D, 17)))
    chk("...with a window the eight-day rule is not used, and without one it "
        "is; a game that has started or is in progress is refused either way",
        ok("2024-09-29T17:00:00Z", "2024-09-10 12:00", W)
        and no("2024-09-29T17:00:00Z", "2024-09-10 12:00", None, "more than 8 days from now")
        and ok("2024-10-04T00:15:00Z", "2024-09-27 12:00", None)
        and no("2024-09-29T17:00:00Z", "2024-09-29 17:00", W, "the game has started")
        and raises(lambda: fl.check_kickoffs([at("2024-09-29T17:00:00Z", live=True)],
                                             U("2024-09-27 12:00"), W), fl.Missing, "is in progress"))
    out_of = lambda when, season: raises(   # noqa: E731
        lambda: fl.check_kickoffs([at(when)], U("2024-01-01"), None, season), fl.Missing,
        f"{fl.game_of(ev)} kicks off {when[:10]}, which is not in the {season} season")
    far_off = lambda when, season: raises(   # noqa: E731
        lambda: fl.check_kickoffs([at(when)], U("2024-01-01"), None, season), fl.Missing,
        "more than 8 days from now")
    chk("a game outside the season named (August to February) is refused "
        "before anything else is asked of its date, and with no window to "
        "go by it says the eight-day rule was all it had",
        out_of("2026-11-22T18:00:00Z", 2027) and far_off("2026-11-22T18:00:00Z", 2026)
        and out_of("2024-07-31T23:59:00Z", 2024) and far_off("2024-08-01T00:00:00Z", 2024)
        and far_off("2025-02-28T23:59:00Z", 2024) and out_of("2025-03-01T00:00:00Z", 2024)
        and ok("2024-09-29T17:00:00Z", "2024-09-27 12:00", W, 2024)
        and fl.check_kickoffs([at("2024-09-29T17:00:00Z")], U("2024-09-27 12:00")) == [fl.NO_WINDOW]
        and "eight days" in fl.NO_WINDOW and "not on file" in fl.NO_WINDOW)
    twice_over = odds_event("Atlanta Falcons", "Arizona Cardinals", {"booka": [
        ("player_receptions", "main", None, [("Over", "Wes One", 4.5, "espn:14"),
                                             ("Over", "Wes One", 4.5, "espn:14")])]})
    chk("a file whose outcomes do not pair up (the same side twice) is "
        "refused by game, not priced on a guess",
        raises(lambda: fl.posted_lines(twice_over), fl.Missing,
               "ARI at ATL: the odds file does not pair up: two outcomes claim the same side"))
    listed = odds_event("Atlanta Falcons", "Arizona Cardinals", {
        "booka": [("player_receptions", "main", None, [("Over", "Wes One", 4.5, "espn:14"),
                                                       ("Under", "Wes One", 4.5, "espn:14"),
                                                       ("Over", "Rob Back", 1.5, None)])],
        "bookb": [("player_anytime_td", "milestone", None, [("Wes One Jr.", "Wes One Jr.", None, "")]),
                  ("player_anytime_td", "milestone", None, [("ARI Cardinals D/ST", "ARI Cardinals D/ST",
                                                             None, None)])]})
    for oc, tm in ((listed["bookmakers"][0]["markets"][0]["outcomes"][0], "Atlanta Falcons"),
                   (listed["bookmakers"][0]["markets"][0]["outcomes"][1], "Atlanta Falcons"),
                   (listed["bookmakers"][0]["markets"][0]["outcomes"][2], "London Monarchs"),
                   (listed["bookmakers"][1]["markets"][0]["outcomes"][0], "")):
        oc["player_team"] = tm
    chk("every player outcome in a response is listed once, with the book's "
        "id for him and the team it puts him on: a code, the name as given "
        "when it is no team it knows, nothing when the book says nothing; a "
        "defence is not a player",
        fl.book_players(listed) == [("Wes One", "espn:14", "ATL"), ("Rob Back", None, "London Monarchs"),
                                    ("Wes One Jr.", None, None)]
        and fl.book_players(made)[0][2] is None
        and ("Bo Nix", "espn:4426338", "DEN") in fl.book_players(real_event())
        and ("Tre Tucker", "espn:4428718", "LV") in fl.book_players(real_event())
        and {t_ for _, _, t_ in fl.book_players(real_event())} == {"DEN", "LV"}
        and fl.game_of(real_event()) == "LV at DEN")
    chk("...and only the books asked for are read",
        set(fl.posted_lines(made, {"kalshi"}).book) == {"kalshi"}
        and len(fl.posted_lines(made, {"kalshi"})) == 2
        and len(fl.posted_lines(made, {"nobody"})) == 0
        and list(fl.posted_lines(made, {"nobody"}).columns) == list(M.columns))

    ok = {"season": 2024, "week": 4, "starters": {"ARI": "Art Passer", "Atlanta Falcons": "Abe Passer"},
          "statuses": [{"team": "Atlanta Falcons", "player": "Tom End", "status": "doubtful"}],
          "chances": [{"team": "Arizona Cardinals", "player": "Wes One", "chance": 0.5}],
          "add": [{"team": "ATL", "player": "espn:99", "position": "WR"}],
          "aliases": [{"team": "Arizona Cardinals", "name": "Wesley One", "player": "Wes One"}]}
    (d / "in.json").write_text(_json.dumps(ok))
    got_in = fl.read_inputs(str(d / "in.json"))
    chk("the inputs are read from a file or a dict, with a team given by code "
        "or by name; chances and additions may be left out",
        got_in == fl.read_inputs(ok) == {
            "season": 2024, "week": 4, "starters": {"ARI": "Art Passer", "ATL": "Abe Passer"},
            "statuses": [("ATL", "Tom End", "doubtful")],
            "chances": [("ARI", "Wes One", 0.5)], "add": [("ATL", "espn:99", "WR")],
            "aliases": [("ARI", "Wesley One", "Wes One")]}
        and fl.read_inputs({"starters": {"ARI": "x"}}) == {
            "season": None, "week": None, "starters": {"ARI": "x"}, "statuses": [],
            "chances": [], "add": [], "aliases": []}
        and [fl.read_inputs({"starters": {}, "statuses": [{"team": "ARI", "player": "a", "status": s_}]})
             ["statuses"][0][2] for s_ in fp.STATUSES] == list(fp.STATUSES)
        and raises(lambda: fl.read_inputs({"starters": {}, "statuses": [
            {"team": "ARI", "player": "Wes One", "status": "Q"}]}), fl.Missing,
            "the status handed in for 'Wes One' is 'Q'")
        and raises(lambda: fl.read_inputs({"starters": {}, "statuses": [
            {"team": "ARI", "player": "Wes One"}]}), fl.Missing, "it must be one of"))
    al = lambda *rows: fl.read_inputs({"starters": {}, "aliases": list(rows)})["aliases"]   # noqa: E731
    al_bad = lambda msg, *rows: raises(lambda: al(*rows), fl.Missing, msg)   # noqa: E731
    chk("an alias is the book's name, the team and the player, all three: a "
        "row short of one, with a key it does not know, with no name, or "
        "the same name twice for a team (however it is spelt) is refused; "
        "the same name for two teams is not",
        al({"team": "ARI", "name": "Kenneth G", "player": "00-0012345"},
           {"team": "ATL", "name": "Kenneth G", "player": "espn:5"}) == [
            ("ARI", "Kenneth G", "00-0012345"), ("ATL", "Kenneth G", "espn:5")]
        and al_bad('a "aliases" row in the inputs is', {"team": "ARI", "name": "K"})
        and al_bad('a "aliases" row in the inputs is', {"name": "K", "player": "a"})
        and al_bad('a "aliases" row in the inputs is',
                   {"team": "ARI", "name": "K", "player": "a", "position": "WR"})
        and al_bad("an alias in the inputs has the name None", {"team": "ARI", "player": "a"})
        and al_bad("an alias in the inputs has the name ''", {"team": "ARI", "name": "", "player": "a"})
        and al_bad("an alias in the inputs has the name ' . '", {"team": "ARI", "name": " . ", "player": "a"})
        and al_bad("an alias in the inputs has the name 7", {"team": "ARI", "name": 7, "player": "a"})
        and al_bad("'ken g jr.' (ARI) has two aliases", {"team": "ARI", "name": "Ken G", "player": "a"},
                   {"team": "Arizona Cardinals", "name": "ken g jr.", "player": "b"})
        and raises(lambda: fl.read_inputs({"starters": {}, "alias": []}), fl.Missing, "which is not one of")
        and raises(lambda: fl.read_inputs({"starters": {}, "aliases": {"a": 1}}), fl.Missing,
                   '"aliases" in the inputs must be a list'))
    chk("inputs with no starters, an unknown team, or a chance that is not a "
        "number from 0 to 1 are refused, saying which",
        raises(lambda: fl.read_inputs({"week": 4}), fl.Missing, 'no "starters"')
        and raises(lambda: fl.read_inputs({"starters": ["Art Passer"]}), fl.Missing, 'no "starters"')
        and raises(lambda: fl.read_inputs({"starters": {"XYZ": "a"}}), fl.Missing, "'XYZ' is not an NFL team")
        and all(raises(lambda v=v: fl.read_inputs(
            {"starters": {}, "chances": [{"team": "ARI", "player": "Wes One", "chance": v}]}),
            fl.Missing, "chance handed in for 'Wes One'") for v in (1.5, -0.1, "0.5", None, True))
        and raises(lambda: fl.read_inputs(str(d / "absent.json")), fl.Missing, "cannot read the inputs file")
        and raises(lambda: fl.read_inputs(str(d / "notjson.json")), fl.Missing, "inputs file is not JSON")
        and fl.read_inputs({"starters": {}, "chances": [
            {"team": "ARI", "player": "a", "chance": 0}, {"team": "ARI", "player": "b", "chance": 1}]}
        )["chances"] == [("ARI", "a", 0.0), ("ARI", "b", 1.0)])
    bad = lambda msg, **kw: raises(lambda: fl.read_inputs(dict({"starters": {}}, **kw)),   # noqa: E731
                                   fl.Missing, msg)
    chk("anything in the inputs it does not know is refused, so a misspelt "
        "key cannot quietly drop a hand-in: a key, a row's key, a row that "
        "is not a row, a week that is not a whole number, a team named twice",
        bad("['chance'], which is not one of", chance=[])
        and bad('a "chances" row in the inputs is', chances=[{"team": "ARI", "player": "a", "chanse": 0.5}])
        and bad('a "statuses" row in the inputs is', statuses=[{"team": "ARI", "status": "out"}])
        and bad('a "add" row in the inputs is', add=[{"player": "a"}])
        and bad('"statuses" in the inputs must be a list of', statuses={"ARI": "out"})
        and bad('"chances" in the inputs must be a list of', chances=["Wes One"])
        and bad('the inputs give "week" as \'eleven\'', week="eleven")
        and bad('the inputs give "week" as 4.5', week=4.5)
        and bad('the inputs give "season" as True', season=True)
        and raises(lambda: fl.read_inputs({"starters": {"ARI": "a", "Arizona Cardinals": "b"}}),
                   fl.Missing, "ARI has two starters named")
        and fl.read_inputs({"starters": {}, "add": [{"team": "ARI", "player": "a"}]})["add"]
        == [("ARI", "a", None)])
    chk("a week outside 1 to 22, or a position to add a player at that is "
        "not one of the five, is refused",
        bad('the inputs give "week" as 0; it must be from 1 to 22', week=0)
        and bad('the inputs give "week" as 23', week=23)
        and fl.read_inputs({"starters": {}, "week": 22})["week"] == 22
        and fl.read_inputs({"starters": {}, "week": 1})["week"] == 1
        and all(bad("the position handed in for 'a' is", add=[{"team": "ARI", "player": "a", "position": v}])
                for v in ("wr", "K", 7, ""))
        and [fl.read_inputs({"starters": {}, "add": [{"team": "ARI", "player": "a", "position": v}]})
             ["add"][0][2] for v in ("QB", "RB", "FB", "WR", "TE")] == ["QB", "RB", "FB", "WR", "TE"])


@section("33. live run — who is who, and the slate")
def _():
    f, roster, reports = live_league()
    T = 202404
    h = History(f, T)
    N = fl.Names(roster, h, 2024)
    chk("a book's ESPN number finds the player through the roster; one the "
        "roster does not have, or a key that is not an ESPN number, finds "
        "nobody",
        N.from_key("espn:11") == "AAA_QB" and N.from_key("espn:24") == "BBB_WR2"
        and N.from_key("espn:99") == "NEW_WR" and N.from_key("espn:15") is None
        and N.from_key("espn:5555") is None and N.from_key(None) is None
        and N.from_key("11") is None and N.from_key(float("nan")) is None
        and N.from_key("espn:nan") is None and "nan" not in N.espn)
    chk("a name finds the one player of that name on that team, whatever "
        "the suffix or the dots, from the roster or from the history",
        N.find("ARI", "Art Passer") == "AAA_QB" and N.find("ARI", "Will Two") == "AAA_WR2"
        and N.find("ARI", "will two jr") == "AAA_WR2" and N.find("ATL", "Nat Newman") == "NEW_WR"
        and N.find("ARI", "Ted End") == "AAA_TE" and N.find("ARI", "espn:11") == "AAA_QB"
        and N.find("BUF", " Dan Passer ") == "DDD_QB")
    chk("a name on the wrong team, a name two players share, a name nobody "
        "has and a key the roster does not have are refused, asking for his id",
        raises(lambda: N.find("ATL", "Art Passer"), fl.Missing, "no player called 'Art Passer' on ATL")
        and raises(lambda: N.find("ARI", "Sam Twin"), fl.Missing, "more than one player called 'Sam Twin' on ARI")
        and raises(lambda: N.find("ARI", "Sam Twin"), fl.Missing, "['TWIN_1', 'TWIN_2']")
        and raises(lambda: N.find("ARI", ""), fl.Missing, "no player called '' on ARI")
        and raises(lambda: N.find("ARI", "espn:5555"), fl.Missing, "nflverse id")
        and raises(lambda: N.find("ATL", "Art Passer"), fl.Missing, "on ATL this season"))
    old = pd.concat([f, f[(f.player_id == "AAA_TE") & (f.season == 2023)].assign(
        player_id="00-0011111", name="Old Timer")], ignore_index=True)
    No = fl.Names(roster, History(old, T), 2024)
    chk("a man who last played for the team in an earlier season, and is "
        "not on its roster, is not found there by name or by id; one who "
        "has played for it this season is",
        raises(lambda: No.find("ARI", "Old Timer"), fl.Missing, "no player called 'Old Timer' on ARI")
        and raises(lambda: No.find("ARI", "00-0011111"), fl.Missing, "is not on ARI")
        and fl.Names(roster, History(old, T), 2023).find("ARI", "Old Timer") == "00-0011111"
        and No.find("ARI", "Ted End") == "AAA_TE"
        and fl.Names(roster[roster.gsis_id != "AAA_TE"], h, 2024).find("ARI", "Ted End") == "AAA_TE"
        and No.team["AAA_WR1"] == "ARI" and "00-0011111" not in No.team)
    chk("a player being added may be anyone the roster or this season has: "
        "by id from any team, by name when nobody on the team has it and "
        "one player in the league does; not a man from an earlier season",
        N.find("ATL", "espn:11", anywhere=True) == "AAA_QB"
        and N.find("ATL", "Art Passer", anywhere=True) == "AAA_QB"
        and N.find("ARI", "Art Passer", anywhere=True) == "AAA_QB"
        and raises(lambda: N.find("ATL", "Sam Twin", anywhere=True), fl.Missing, "more than one player")
        and raises(lambda: N.find("ATL", "Nobody Atall", anywhere=True), fl.Missing, "no player called")
        and raises(lambda: No.find("ARI", "00-0011111", anywhere=True), fl.Missing, "is not on ARI")
        and raises(lambda: No.find("ATL", "Old Timer", anywhere=True), fl.Missing, "no player called")
        and raises(lambda: N.find("ATL", "espn:11"), fl.Missing, "is not on ATL")
        and fl.Names(roster.assign(team=roster.team.where(roster.gsis_id != "TWIN_2", "ATL")), h, 2024)
        .find("ARI", "Sam Twin", anywhere=True) == "TWIN_1")
    chk("an id, his nflverse one or the book's, is taken only for a team the "
        "roster or the history has him on",
        N.find("ARI", "00-0099999") == "00-0099999" and N.find("ATL", "espn:99") == "NEW_WR"
        and N.full["00-0099999"] == "Ivan Dee" and N.position["NEW_WR"] == "WR"
        and raises(lambda: N.find("ATL", "00-0099999"), fl.Missing,
                   "Ivan Dee (00-0099999) is not on ATL: the roster does not have him there")
        and raises(lambda: N.find("ARI", "00-0012345"), fl.Missing,
                   "00-0012345 (00-0012345) is not on ARI")
        and raises(lambda: N.find("ARI", "espn:21"), fl.Missing, "Abe Passer (espn:21) is not on ARI")
        and N.find("ATL", "espn:21") == "BBB_QB")

    starters = {"ARI": "AAA_QB", "ATL": "BBB_QB", "BAL": "CCC_QB", "BUF": "DDD_QB"}
    S = fl.build_slate(h, 2024, 4, [("ARI", "ATL"), ("BAL", "BUF")], starters, N)
    want = []
    for away, home, tag in (("ARI", "ATL", "2024_04_ARI_ATL"), ("BAL", "BUF", "2024_04_BAL_BUF")):
        for tm, opp in ((away, home), (home, away)):
            code = {v: k for k, v in LIVE_TEAMS.items()}[tm]
            last4 = sorted(f[f.team == tm].t.unique())[-4:]
            for pid in sorted(f[(f.team == tm) & f.t.isin(last4)].player_id.unique()):
                want.append((2024, 4, tag, tm, opp, pid, f[f.player_id == pid].name.iloc[-1],
                             f[f.player_id == pid].position.iloc[-1], pid == f"{code}_QB"))
    chk("the slate is, by hand, everyone active for each team in one of its "
        "last four games, in the harness's columns, each game named away at "
        "home, and only the named starter marked",
        list(S.columns) == list(fs.SLATE_COLS)
        and sorted(S.itertuples(index=False, name=None)) == sorted(want)
        and int(S.starting_qb.sum()) == 4 and len(S) == 20, len(S))
    back = f[~((f.player_id == "AAA_WR2") & (f.t >= 202306))]
    hb = History(back, T)
    chk("...so a player out for his team's last four games is not on it "
        "until he is added, and then is, once, with his own name and "
        "position",
        "AAA_WR2" not in set(fl.build_slate(hb, 2024, 4, [("ARI", "ATL")], starters,
                                            fl.Names(roster, hb, 2024)).player_id)
        and (fl.build_slate(hb, 2024, 4, [("ARI", "ATL")], starters, fl.Names(roster, hb, 2024),
                            [("ARI", "AAA_WR2", None), ("ARI", "AAA_WR2", None),
                             ("ATL", "AAA_RB", None)]
                            ).query("player_id == 'AAA_WR2'")[["team", "name", "position"]]
             .values.tolist() == [["ARI", "Will Two Jr.", "WR"]]))
    fourth = sorted(f[f.team == "ARI"].t.unique())[-4]
    on_it = lambda fr: "AAA_WR2" in set(fl.build_slate(   # noqa: E731
        History(fr, T), 2024, 4, [("ARI", "ATL")], starters,
        fl.Names(roster, History(fr, T), 2024)).player_id)
    chk("...four games exactly: a player whose last game for the team was "
        "its fourth back is on the slate, and one whose last was its fifth "
        "back is not",
        on_it(f[~((f.player_id == "AAA_WR2") & (f.t > fourth))])
        and not on_it(f[~((f.player_id == "AAA_WR2") & (f.t >= fourth))]))
    S2 = fl.build_slate(h, 2024, 4, [("ARI", "ATL")],
                        dict(starters, ARI="00-0099999", ATL="NEW_WR"), N,
                        [("ATL", "00-0099999", "TE"), ("ARI", "TWIN_1", None),
                         ("ATL", "NEW_WR", "QB")])
    r2 = S2.set_index(["team", "player_id"])
    chk("a starter other than last week's is the one marked; a starter or an "
        "added player with no history comes from the roster, and a position "
        "handed in is the one used",
        list(S2.player_id[S2.starting_qb]) == ["00-0099999", "NEW_WR"]
        and not r2.starting_qb[("ARI", "AAA_QB")] and not r2.starting_qb[("ATL", "BBB_QB")]
        and r2.loc[("ATL", "NEW_WR"), ["name", "position"]].tolist() == ["Nat Newman", "QB"]
        and r2.loc[("ATL", "00-0099999"), ["name", "position"]].tolist() == ["Ivan Dee", "TE"]
        and r2.loc[("ARI", "00-0099999"), ["name", "position"]].tolist() == ["Ivan Dee", "QB"]
        and r2.loc[("ARI", "TWIN_1"), ["name", "position"]].tolist() == ["Sam Twin", "WR"]
        and len(S2) == 14 and not S2.duplicated(["team", "player_id"]).any())
    chk("a starter who is not listed at quarterback is refused, and taken "
        "when he is added with that position",
        raises(lambda: fl.build_slate(h, 2024, 4, [("ARI", "ATL")], dict(starters, ARI="AAA_WR1"), N),
               fl.Missing, "Wes One is named as ARI's starting quarterback and is listed at WR")
        and raises(lambda: fl.build_slate(h, 2024, 4, [("ARI", "ATL")], dict(starters, ATL="NEW_WR"), N),
                   fl.Missing, 'add him under "add" with position QB')
        and fl.build_slate(h, 2024, 4, [("ARI", "ATL")], dict(starters, ARI="AAA_WR1"), N,
                           [("ARI", "AAA_WR1", "QB")]).query("starting_qb").player_id.tolist()
        == ["AAA_WR1", "BBB_QB"])
    chk("a team with no starter named, a team in two games, a team with no "
        "history and a week the history does not stop at are refused",
        raises(lambda: fl.build_slate(h, 2024, 4, [("ARI", "ATL"), ("BAL", "BUF")],
                                      {"ARI": "AAA_QB", "BAL": "CCC_QB"}, N),
               fl.Missing, "no starting quarterback named for ['ATL', 'BUF']")
        and raises(lambda: fl.build_slate(h, 2024, 4, [("ARI", "ATL"), ("BAL", "ARI")],
                                          dict(starters), N), fl.Missing, "['ARI'] appear in more than one game")
        and raises(lambda: fl.build_slate(h, 2024, 4, [("ARI", "DEN")], dict(starters, DEN="x"), N),
                   fl.Missing, "DEN has no game in the history")
        and raises(lambda: fl.build_slate(h, 2024, 5, [("ARI", "ATL")], starters, N),
                   ValueError, "the slate is for 202405"))


@section("34. live run — one run")
def _():
    f, roster, reports = live_league()
    T = 202404
    h = History(f, T)
    lines_a = [
        ("player_receptions", "main", None, [("Over", "Wes One", 4.5, "espn:13"),
                                             ("Under", "Wes One", 4.5, "espn:13")]),
        ("player_receptions", "alternate", None, [("Over", "Wes One", 7.5, "espn:13"),
                                                  ("Over", "Wes One", 2.5, "espn:13")]),
        ("player_reception_yds", "milestone", None, [("60+ Receiving Yards", "Wes One", None, "espn:13")]),
        ("player_reception_targets", "main", None, [("Over", "Wes One", 7.0, "espn:13"),
                                                    ("Under", "Wes One", 7.0, "espn:13")]),
        ("player_rush_yds", "main", "2024-09-29T00:00:00Z",
         [("Over", "Rob Back", 40.0, "espn:12"), ("Under", "Rob Back", 40.0, "espn:12")]),
        ("player_anytime_td", "milestone", None, [("Rob Back", "Rob Back", None, "espn:12"),
                                                  ("Ted End", "Ted End", None, None),
                                                  ("Tom End", "Tom End", None, "espn:5555")]),
        ("player_2plus_td", "milestone", None, [("Rob Back", "Rob Back", None, "espn:12")]),
        ("player_pass_tds", "main", None, [("Over", "Abe Passer", 1.5, "espn:21"),
                                           ("Under", "Abe Passer", 1.5, "espn:21")]),
        ("player_pass_tds", "milestone", None, [("1+ Passing Touchdowns", "Abe Passer", None, "espn:21")]),
        ("player_pass_yds", "main", None, [("Over", "Ray Back", 0.5, "espn:22"),
                                           ("Under", "Ray Back", 0.5, "espn:22")]),
        ("player_receptions", "main", None, [("Over", "Nat Newman", 2.5, "espn:99"),
                                             ("Under", "Nat Newman", 2.5, "espn:99")]),
        ("player_receptions", "main", None, [("Over", "Sam Stranger", 2.5, None),
                                             ("Under", "Sam Stranger", 2.5, None)])]
    lines_b = [("player_receptions", "main", None, [("Over", "Wes One", 4.5, "espn:13"),
                                                    ("Under", "Wes One", 4.5, "espn:13")]),
               ("player_receptions", "main", None, [("Over", "Nat Newman", 2.5, "espn:99"),
                                                    ("Under", "Nat Newman", 2.5, "espn:99")]),
               ("player_receptions", "main", "2024-09-29T00:00:00Z",
                [("Over", "Wes One", 5.5, "espn:13"), ("Under", "Wes One", 5.5, "espn:13")]),
               ("player_rush_yds", "main", "2024-09-29T00:00:00Z",
                [("Over", "Rob Back", 40.0, "espn:12"), ("Under", "Rob Back", 40.0, "espn:12")])]
    ev = odds_event("Atlanta Falcons", "Arizona Cardinals", {"booka": lines_a, "bookb": lines_b})
    ev2 = odds_event("Buffalo Bills", "Baltimore Ravens", {"booka": [
        ("player_rush_attempts", "main", None, [("Over", "Rex Back", 15.5, "espn:32"),
                                                ("Under", "Rex Back", 15.5, "espn:32")])]})
    B = fl.run_live(f, reports, roster, [ev, ev2], fl.read_inputs(LIVE_IN))
    S, L = B.slate, B.lines
    base = S[list(fs.SLATE_COLS)]
    P = fl.live_model(reports).project(h, base)
    plain = TouchdownModel().project(h, base)
    hand = hand_td(h.frame, base)
    at = {p_: i for i, p_ in enumerate(S.player_id)}
    chk("the slate it ran is the one built by hand above for both games, "
        "with each player's chance of playing beside him",
        base.equals(fl.build_slate(h, 2024, 4, [("ARI", "ATL"), ("BAL", "BUF")],
                                   {"ARI": "AAA_QB", "ATL": "BBB_QB", "BAL": "CCC_QB",
                                    "BUF": "DDD_QB"}, fl.Names(roster, h, 2024)))
        and list(S.columns) == [*fs.SLATE_COLS, "chance", "status", "source"]
        and S.status[at["AAA_WR2"]] == "questionable" and (S.status.drop(at["AAA_WR2"]) == "none").all()
        and set(S.source) == {"counted"})
    key = {(r.player_id, r.stat, r.line): r for r in L.itertuples(index=False)}
    chk("every posted line it has a number for is priced once, whichever "
        "books post it",
        sorted(key) == sorted([
            ("AAA_WR1", "receptions", 4.5), ("AAA_WR1", "receptions", 7.5),
            ("AAA_WR1", "receptions", 2.5), ("AAA_WR1", "receptions", 5.5),
            ("AAA_WR1", "receiving_yards", 59.5), ("AAA_WR1", "targets", 7.0),
            ("AAA_RB", "rushing_yards", 40.0), ("AAA_RB", TD_STAT, 0.5), ("AAA_RB", TD_STAT, 1.5),
            ("AAA_TE", TD_STAT, 0.5), ("BBB_TE", TD_STAT, 0.5),
            ("BBB_QB", "passing_tds", 1.5), ("BBB_QB", "passing_tds", 0.5),
            ("CCC_RB", "carries", 15.5)])
        and len(L) == len(key) and list(L.columns) == fl.LINE_COLS, sorted(key))
    r = key[("AAA_WR1", "receptions", 4.5)]
    i = at["AAA_WR1"]
    chk("a line's numbers are the model's for that slate row: the expected "
        "count, the chance of more than the line, and under as the rest",
        r.expected == P.point(i, "receptions") and r.over == P.p_over(i, "receptions", 4.5)
        and r.push == 0.0 and near(r.under, 1.0 - r.over, 1e-15)
        and 0.05 < r.over < 0.95
        and (r.game_id, r.team, r.opponent, r.name, r.position) == (
            "2024_04_ARI_ATL", "ARI", "ATL", "Wes One", "WR")
        and key[("CCC_RB", "carries", 15.5)].over == P.p_over(at["CCC_RB"], "carries", 15.5)
        and key[("CCC_RB", "carries", 15.5)].game_id == "2024_04_BAL_BUF"
        and key[("AAA_WR1", "receiving_yards", 59.5)].over == P.p_over(i, "receiving_yards", 59.5)
        and key[("BBB_QB", "passing_tds", 1.5)].over == P.p_over(at["BBB_QB"], "passing_tds", 1.5)
        and key[("AAA_RB", TD_STAT, 1.5)].over == P.p_over(at["AAA_RB"], TD_STAT, 1.5))
    chk("...and with nobody's chance far from certain they are the long-hand "
        "numbers of sections 23 and 30",
        (S.chance > 0.95).all()
        and near(key[("AAA_RB", TD_STAT, 0.5)].expected / hand["anytime"][at["AAA_RB"]], 1.0, 0.02)
        and near(r.expected / hand["base"]["mean"]["receptions"][i], 1.0, 0.02)
        and near(key[("BBB_QB", "passing_tds", 1.5)].expected / hand["thrown"][at["BBB_QB"]], 1.0, 1e-9)
        and near(key[("BBB_QB", "passing_tds", 1.5)].over,
                 plain.p_over(at["BBB_QB"], "passing_tds", 1.5), 1e-12),
        (r.expected, hand["base"]["mean"]["receptions"][i]))
    w = key[("AAA_WR1", "targets", 7.0)]
    y = key[("AAA_RB", "rushing_yards", 40.0)]
    chk("a whole-number line pushes on exactly that number: over is the "
        "chance of more, under of fewer, and the three add to one",
        near(w.over, P.p_over(i, "targets", 7.5), 1e-15)
        and near(w.push, P.p_over(i, "targets", 6.5) - P.p_over(i, "targets", 7.5), 1e-15)
        and near(w.under, 1.0 - P.p_over(i, "targets", 6.5), 1e-15)
        and w.push > 0.02 and near(w.over + w.push + w.under, 1.0, 1e-12)
        and near(y.over, P.p_over(at["AAA_RB"], "rushing_yards", 40.5), 1e-15)
        and near(y.under, 1.0 - P.p_over(at["AAA_RB"], "rushing_yards", 39.5), 1e-15)
        and 0 < y.push < 0.05
        and fl.sides(P, i, "targets", 7.0) == (w.over, w.push, w.under)
        and fl.sides(P, i, "targets", 6.5) == (P.p_over(i, "targets", 6.5), 0.0,
                                               1.0 - P.p_over(i, "targets", 6.5)))
    chk("each line says which books post it, where it is suspended, whether "
        "any book has it as its main line, and how the player was found",
        (r.books, r.suspended, r.kind, r.matched) == ("booka bookb", "", "main", "id")
        and (y.books, y.suspended) == ("booka bookb", "booka bookb")
        and (key[("AAA_WR1", "receptions", 5.5)].books,
             key[("AAA_WR1", "receptions", 5.5)].suspended,
             key[("AAA_WR1", "receptions", 5.5)].kind) == ("bookb", "bookb", "main")
        and key[("AAA_WR1", "receptions", 7.5)].kind == "ladder"
        and key[("AAA_RB", TD_STAT, 0.5)].kind == "main"
        and key[("AAA_RB", TD_STAT, 1.5)].kind == "ladder"
        and key[("BBB_QB", "passing_tds", 0.5)].kind == "ladder"
        and key[("AAA_TE", TD_STAT, 0.5)].matched == "name"
        and key[("AAA_TE", TD_STAT, 0.5)].name == "Ted End"
        and key[("BBB_TE", TD_STAT, 0.5)].matched == "name"
        and key[("BBB_TE", TD_STAT, 0.5)].name == "Tom End")
    chk("(a player is found by name only when the book gives no id the "
        "roster has: no id at all, or one the roster does not carry)",
        roster.espn_id[roster.gsis_id == "AAA_TE"].isna().all()
        and fl.Names(roster, h, 2024).from_key("espn:5555") is None)
    last8 = [float(v) for v in f[f.player_id == "AAA_WR1"].sort_values("t").receptions][-8:]
    med = sorted(last8)[3] / 2 + sorted(last8)[4] / 2
    ladder = sorted({math.floor(med * x) + 0.5: lab for x, lab in (
        (0.6, "x0.6"), (1.6, "x1.6"), (0.8, "x0.8"), (1.25, "x1.25"), (1.0, "main"))}.items())
    chk("(his stand-in ladder, by hand: the half point above his eight-game "
        "median of 6 catches, and the multiples of that median round it)",
        ladder == [(3.5, "x0.6"), (4.5, "x0.8"), (6.5, "main"), (7.5, "x1.25"), (9.5, "x1.6")]
        and [(ln, lab) for lab, ln in fs.standin_lines(
            h, fs.line_window(h, "AAA_WR1"), "receptions")] == ladder)
    rung = {k_: (v.rung, v.no_record) for k_, v in key.items()}
    chk("the record each line is read on is HIS OWN stand-in rung nearest "
        "it, whatever the book calls its main line: 4.5 is his x0.8 rung, "
        "5.5 sits between two and goes to the one nearer his main line, 7.5 "
        "is his x1.25, and 2.5 is off his ladder and has no record",
        rung[("AAA_WR1", "receptions", 4.5)] == ("x0.8", "")
        and rung[("AAA_WR1", "receptions", 5.5)] == ("main", "")
        and rung[("AAA_WR1", "receptions", 7.5)] == ("x1.25", "")
        and rung[("AAA_WR1", "receptions", 2.5)] == ("", fl.OFF_LADDER)
        and rung[("AAA_WR1", "receiving_yards", 59.5)] == ("x0.6", "")
        and rung[("AAA_WR1", "targets", 7.0)] == ("main", "")
        and rung[("AAA_RB", "rushing_yards", 40.0)] == ("x0.6", "")
        and rung[("CCC_RB", "carries", 15.5)] == ("main", ""), rung)
    chk("...a passing touchdown is read the same way (his median is one a "
        "game, so 1.5 is his main line and 0.5 his x0.8); an anytime "
        "touchdown on \"main\"; two or more has no record; and a player the "
        "harness gives no stand-in line (no role in his last games) has no "
        "record, and says why",
        rung[("BBB_QB", "passing_tds", 1.5)] == ("main", "")
        and rung[("BBB_QB", "passing_tds", 0.5)] == ("x0.8", "")
        and fs.standin_lines(h, fs.line_window(h, "BBB_QB"), "passing_tds")
        == [("x0.8", 0.5), ("main", 1.5)]
        and rung[("AAA_RB", TD_STAT, 0.5)] == ("main", "")
        and rung[("AAA_RB", TD_STAT, 1.5)] == ("", fl.TWO_PLUS)
        and rung[("AAA_TE", TD_STAT, 0.5)] == ("", fl.NO_ROLE)
        and rung[("BBB_TE", TD_STAT, 0.5)] == ("", fl.NO_ROLE)
        and not fs.roles(h, fs.line_window(h, "AAA_TE"))["td"]
        and fs.roles(h, fs.line_window(h, "AAA_RB"))["td"])
    lad = [("x0.6", 3.5), ("x0.8", 4.5), ("main", 6.5), ("x1.25", 7.5), ("x1.6", 9.5)]
    chk("nearest_rung by hand: the rung nearest the line; of two equally "
        "near, the one nearer his main line; and none for a line further "
        "off either end than half the gap to the next rung in",
        [fl.nearest_rung(x, lad) for x in (3.5, 3.0, 2.9, 4.0, 5.4, 5.5, 5.6, 7.0, 8.5, 8.6,
                                           10.5, 10.6)]
        == ["x0.6", "x0.6", "", "x0.8", "x0.8", "main", "main", "main", "x1.25", "x1.6",
            "x1.6", ""]
        and fl.nearest_rung(4.5, []) == ""
        and [fl.nearest_rung(x, [("x0.6", 40.5), ("x0.8", 54.5), ("main", 68.5),
                                 ("x1.25", 85.5), ("x1.6", 108.5)])
             for x in (33.5, 33.4, 120.0, 120.1, 47.5, 47.6, 97.0, 96.9)]
        == ["x0.6", "", "x1.6", "", "x0.8", "x0.8", "x1.25", "x1.25"]
        and [fl.nearest_rung(x, [("main", -0.5)]) for x in (-0.5, 0.0, -1.0, 0.1, -1.1)]
        == ["main", "main", "main", "", ""])
    role = lambda **kw: dict({"recv": False, "rush": False, "pass": False, "td": False}, **kw)   # noqa: E731
    chk("read_on by hand: no role, no record; a role and a line on the "
        "ladder, its rung; off the ladder, none; passing touchdowns by line; "
        "an anytime touchdown on main; two or more never",
        fl.read_on("receptions", 4.5, role(recv=True), lad) == ("x0.8", "")
        and fl.read_on("receptions", 4.5, role(rush=True, td=True), lad) == ("", fl.NO_ROLE)
        and fl.read_on("receptions", 12.5, role(recv=True), lad) == ("", fl.OFF_LADDER)
        and fl.read_on("carries", 4.5, role(rush=True), lad) == ("x0.8", "")
        and fl.read_on("passing_yards", 4.5, role(recv=True), lad) == ("", fl.NO_ROLE)
        and fl.read_on("passing_tds", 1.5, role(**{"pass": True}), [("x0.8", 0.5), ("main", 1.5)])
        == ("main", "")
        and fl.read_on("passing_tds", 2.5, role(**{"pass": True}), [("x0.8", 0.5), ("main", 1.5)])
        == ("", fl.OFF_LADDER)
        and fl.read_on("passing_tds", 1.5, role(recv=True), [("x0.8", 0.5), ("main", 1.5)])
        == ("", fl.NO_ROLE)
        and fl.read_on(TD_STAT, 0.5, role(td=True), []) == ("main", "")
        and fl.read_on(TD_STAT, 0.5, role(recv=True), []) == ("", fl.NO_ROLE)
        and fl.read_on(TD_STAT, 1.5, role(td=True), []) == ("", fl.TWO_PLUS)
        and fl.read_on(TD_STAT, 2.5, role(), []) == ("", fl.TWO_PLUS))
    why = {p_: (g, n, w_) for g, p_, n, w_ in B.unmatched}
    NOBODY = ("no id from the book that the roster has, and nobody of that name on either team's "
              "roster or slate. If the book spells him differently from the data, name him with an "
              "alias in the inputs. If he is a player not on the slate, add him: until then his "
              "teammates' numbers here are too high.")
    chk("what it cannot price is listed once a player with the reason: a "
        "rostered player not on the slate, a name with no usable id that "
        "nobody on either slate has, and a passer who is not the named "
        "starter",
        [u[1] for u in B.unmatched] == ["Nat Newman", "Sam Stranger", "Ray Back"]
        and why["Ray Back"] == ("ARI at ATL", 1, "no passing_yards projection: he is not the named starter")
        and why["Nat Newman"][1:] == (
            1, "on ATL's roster but not on the slate: not active for ATL in its last four games. "
               "Add him in the inputs if he is playing. " + fl.TOO_HIGH)
        and why["Sam Stranger"][2] == NOBODY)
    chk("a posted player known not to be on a team's slate makes that "
        "team's numbers too high if he plays: the run says so in a note, "
        "and keeps who and for which team; a name it cannot place is on "
        "nobody's account",
        B.off_slate == {"ATL": ["Nat Newman"]}
        and B.notes[-1] == fl.too_high_text("ATL", ["Nat Newman"]) == (
            "ATL'S NUMBERS ARE TOO HIGH if Nat Newman plays: posted, and not on ATL's slate, so "
            "the work that would be his is shared among the others. Add him in the inputs, "
            "unless he is ruled out.")
        and fl.too_high_text("PIT", ["A B", "C D"]) == (
            "PIT'S NUMBERS ARE TOO HIGH if A B, C D play: posted, and not on PIT's slate, so the "
            "work that would be theirs is shared among the others. Add each in the inputs, "
            "unless he is ruled out.")
        and fl.TOO_HIGH == "Until he is added or ruled out, his teammates' numbers here are too high.")
    runner = f.copy()
    runner.loc[runner.player_id == "BBB_QB", "carries"] = 8.0
    his = dict(fs.standin_lines(History(runner, T), fs.line_window(History(runner, T), "BBB_QB"),
                                "rushing_yards"))["main"]
    qb_lines = odds_event("Atlanta Falcons", "Arizona Cardinals", {"booka": [
        ("player_rush_yds", "main", None, [("Over", "Abe Passer", his, "espn:21"),
                                           ("Under", "Abe Passer", his, "espn:21")]),
        ("player_pass_tds", "main", None, [("Over", "Nat Newman", 1.5, "espn:99"),
                                           ("Under", "Nat Newman", 1.5, "espn:99")]),
        ("player_pass_tds", "main", None, [("Over", "Art Passer", 3.5, "espn:11"),
                                           ("Under", "Art Passer", 3.5, "espn:11")])]})
    as_starter = fl.run_live(runner, reports, roster, [qb_lines], fl.read_inputs(LIVE_IN))
    benched = fl.run_live(runner, reports, roster, [qb_lines], dict(
        fl.read_inputs(LIVE_IN), starters=dict(LIVE_IN["starters"], ATL="Nat Newman"),
        add=[("ATL", "Nat Newman", "QB")]))
    rr = lambda b: {(r_.player_id, r_.stat): (r_.rung, r_.no_record) for r_ in b.lines.itertuples()}  # noqa: E731
    chk("who has a stand-in line is the harness's rule on THIS slate, with "
        "the starter named: a quarterback who runs has a rushing record "
        "while he starts and none of any kind once another man is named; "
        "the man named, with no games behind him, has none either",
        rr(as_starter)[("BBB_QB", "rushing_yards")] == ("main", "")
        and rr(benched)[("BBB_QB", "rushing_yards")] == ("", fl.NO_ROLE)
        and rr(benched)[("NEW_WR", "passing_tds")] == ("", fl.NO_ROLE)
        and rr(as_starter)[("AAA_QB", "passing_tds")] == ("main", "")
        and fs.roles(History(runner, T), fs.line_window(History(runner, T), "BBB_QB"))["rush"])
    sat = f[~((f.player_id == "AAA_QB") & (f.t == 202403))]
    back = fl.run_live(sat, reports, roster, [qb_lines], fl.read_inputs(LIVE_IN))
    chk("...and it goes by the starter NAMED, not last game's: a starter who "
        "sat out last week still has his passing record",
        History(sat, T).last_starting_qb("ARI") != "AAA_QB"
        and rr(back)[("AAA_QB", "passing_tds")][0] in fl.RUNG_LABELS
        and rr(back)[("AAA_QB", "passing_tds")][1] == "")
    chk("it says what the injury file has for these teams and which of them "
        "have nobody on it",
        B.notes == [
            "Injury file for these teams: 1 listed, 0 out, 0 doubtful, 1 questionable. It can "
            "be days behind the league's report; 0 statuses and 0 chances were handed in.",
            "['ATL', 'BAL', 'BUF']: nobody on the injury file this week. A clean report is "
            "rare; the file may be missing them.",
            fl.too_high_text("ATL", ["Nat Newman"])])

    moved = f.copy()
    was = (moved.player_id == "AAA_WR2") & (moved.t == 202403)
    moved.loc[was, ["team", "opponent"]] = ["ATL", "BAL"]
    two = odds_event("Atlanta Falcons", "Arizona Cardinals", {
        "booka": [("player_receptions", "main", None, [("Over", "Will Two", 2.5, "espn:14"),
                                                       ("Under", "Will Two", 2.5, "espn:14")])],
        "bookb": [("player_receptions", "main", None, [("Over", "Will Two Jr.", 2.5, "espn:14"),
                                                       ("Under", "Will Two Jr.", 2.5, "espn:14")]),
                  ("player_receptions", "alternate", None, [("Over", "Will Two Jr.", 3.5, "espn:14")])],
        "bookc": [("player_receptions", "main", None, [("Over", "Will Two", 2.5, None),
                                                       ("Under", "Will Two", 2.5, None)])]})

    def says(team):
        e = _json_copy(two)
        for bk in e["bookmakers"]:
            for mk in bk["markets"]:
                for oc in mk["outcomes"]:
                    if team and oc["player_id"]:
                        oc["player_team"] = team
        return fl.run_live(moved, reports, roster, [e], fl.read_inputs(LIVE_IN))

    here = says(None)
    chk("a player on both teams' slates (he changed sides between two teams "
        "that now meet) is priced for the team the book puts him on, and "
        "not at all when the book does not say",
        set(says("Atlanta Falcons").lines.team) == {"ATL"}
        and set(says("Arizona Cardinals").lines.team) == {"ARI"}
        and len(says("Atlanta Falcons").lines) == 2
        and says("Atlanta Falcons").lines.over[0] != says("Arizona Cardinals").lines.over[0]
        and len(here.lines) == 0 and [u[1:3] for u in here.unmatched] == [
            ("Will Two", 1), ("Will Two Jr.", 2)]
        and all("on both teams' slates" in u[3] for u in here.unmatched)
        and {(tm, pid) for tm, pid in zip(here.slate.team, here.slate.player_id)}
        >= {("ARI", "AAA_WR2"), ("ATL", "AAA_WR2")})
    one = fl.run_live(f, reports, roster, [two], fl.read_inputs(LIVE_IN))
    chk("a player one book spells two ways, or gives an id at one book and "
        "none at another, is one player: each line once, with every book on "
        "it, found by id if any book gave one",
        sorted(zip(one.lines.player_id, one.lines.line, one.lines.books, one.lines.matched,
                   one.lines.kind)) == [("AAA_WR2", 2.5, "booka bookb bookc", "id", "main"),
                                        ("AAA_WR2", 3.5, "bookb", "id", "ladder")]
        and one.unmatched == [])

    def told(team_by_book):
        e = _json_copy(two)
        for bk in e["bookmakers"]:
            for mk in bk["markets"]:
                for oc in mk["outcomes"]:
                    if bk["key"] in team_by_book:
                        oc["player_team"] = team_by_book[bk["key"]]
        return fl.run_live(f, reports, roster, [e], fl.read_inputs(LIVE_IN))

    away_ = told({"booka": "Atlanta Falcons", "bookb": "Atlanta Falcons", "bookc": "Atlanta Falcons"})
    chk("a player the book puts on the OTHER team from the only slate he is "
        "on (he has just moved) is not priced as his old team's man: he is "
        "listed with that reason, under an id or under his name alone",
        len(away_.lines) == 0 and [u[1:3] for u in away_.unmatched] == [
            ("Will Two", 1), ("Will Two Jr.", 2)]
        and all(u[3].startswith("the book has him on ATL, and he is not on ATL's slate")
                for u in away_.unmatched)
        and len(told({"booka": "Arizona Cardinals", "bookb": "Arizona Cardinals",
                      "bookc": "Arizona Cardinals"}).lines) == 2)
    lone = odds_event("Atlanta Falcons", "Arizona Cardinals", {"bookc": [
        ("player_receptions", "main", None, [("Over", "Will Two", 2.5, None),
                                             ("Under", "Will Two", 2.5, None)])]})
    for oc in lone["bookmakers"][0]["markets"][0]["outcomes"]:
        oc["player_team"] = "Atlanta Falcons"
    nameless = fl.run_live(f, reports, roster, [lone], fl.read_inputs(LIVE_IN))
    chk("...with no id anywhere in the file he is looked for by name on the "
        "team the file names; when nobody there has the name and one "
        "player on the other team does, he is that player, and the file's "
        "team stands as for a player with an id",
        len(nameless.lines) == 0 and [u[1:] for u in nameless.unmatched] == [
            ("Will Two", 1, "the book has him on ATL, and he is not on ATL's slate: not active for "
                            "it in its last four games. Add him in the inputs if he is playing. "
                            + fl.TOO_HIGH)]
        and nameless.off_slate == {"ATL": ["Will Two Jr."]})
    mixed = ("the odds file puts him on ARI and ATL: not one team in this game, so he is not priced. "
             "He is not on the slate of ATL. " + fl.TOO_HIGH)
    chk("...and when the file puts him on two teams he is not priced at all, "
        "whether two books disagree under two spellings or one gives his "
        "id and the other only his name; the team whose slate he is not on "
        "is cautioned, since one of them says he is its player",
        all(len(b_.lines) == 0 and b_.off_slate == {"ATL": ["Will Two Jr."]}
            and [u[1:] for u in b_.unmatched] == [
            ("Will Two", 1, mixed), ("Will Two Jr.", 2, mixed)]
            for b_ in (told({"booka": "Atlanta Falcons", "bookb": "Arizona Cardinals"}),
                       told({"booka": "Arizona Cardinals", "bookc": "Atlanta Falcons"}),
                       told({"bookb": "Arizona Cardinals", "bookc": "Atlanta Falcons"}))))
    twins = lambda outcomes, add, **kw: fl.run_live(   # noqa: E731
        f, reports, roster, [odds_event("Atlanta Falcons", "Arizona Cardinals", outcomes)],
        dict(fl.read_inputs(LIVE_IN), add=add, **kw))
    with_id = ("player_receptions", "main", None, [("Over", "Sam Twin", 1.5, "espn:71"),
                                                   ("Under", "Sam Twin", 1.5, "espn:71")])
    no_id = ("player_receptions", "main", None, [("Over", "Sam Twin", 2.5, None),
                                                 ("Under", "Sam Twin", 2.5, None)])
    shared = "no id from the book that the roster has, and more than one player of that name on these teams"
    t1 = twins({"booka": [with_id], "bookb": [no_id]}, [("ARI", "espn:71", None)])
    t2 = twins({"bookb": [no_id]}, [("ARI", "espn:71", None)])
    t3 = twins({"booka": [with_id], "bookb": [no_id]}, [("ARI", "espn:71", None), ("ARI", "espn:72", None)])
    chk("a name two players on these teams share is never enough: the line "
        "that comes with an id is priced for that player, and the line "
        "with the name alone is not priced, whether one of the two is on "
        "the slate or both, and though another outcome in the file gives "
        "the name an id",
        [(r_.player_id, r_.line, r_.matched) for r_ in t1.lines.itertuples()] == [("TWIN_1", 1.5, "id")]
        and [u[1:] for u in t1.unmatched] == [("Sam Twin", 1, shared)]
        and len(t2.lines) == 0 and [u[1:] for u in t2.unmatched] == [("Sam Twin", 1, shared)]
        and [(r_.player_id, r_.line) for r_ in t3.lines.itertuples()] == [("TWIN_1", 1.5)]
        and t3.unmatched[0][3] == shared and t1.off_slate == t2.off_slate == t3.off_slate == {}
        and {"TWIN_1", "TWIN_2"} <= set(t3.slate.player_id) and "TWIN_2" not in set(t1.slate.player_id))
    other_id = ("player_receptions", "alternate", None, [("Over", "Sam Twin", 3.5, "espn:72")])
    t4 = twins({"booka": [with_id], "bookb": [no_id], "bookc": [other_id]},
               [("ARI", "espn:71", None), ("ARI", "espn:72", None)])
    across = roster.assign(team=roster.team.where(roster.gsis_id != "TWIN_2", "ATL"))
    t5 = fl.run_live(f, reports, across, [odds_event("Atlanta Falcons", "Arizona Cardinals", {"bookb": [no_id]})],
                     dict(fl.read_inputs(LIVE_IN), add=[("ARI", "espn:71", None)]))
    named = odds_event("Atlanta Falcons", "Arizona Cardinals", {"bookb": [no_id]})
    for oc in named["bookmakers"][0]["markets"][0]["outcomes"]:
        oc["player_team"] = "Arizona Cardinals"
    t6 = fl.run_live(f, reports, across, [named], dict(fl.read_inputs(LIVE_IN), add=[("ARI", "espn:71", None)]))
    chk("...nor when the file gives each of the two an id elsewhere, nor "
        "when the namesake is on the OTHER team's roster and not on any "
        "slate; but when the file names the team, a namesake on the other "
        "team does not stand in the way",
        sorted((r_.player_id, r_.line) for r_ in t4.lines.itertuples()) == [("TWIN_1", 1.5), ("TWIN_2", 3.5)]
        and [u[1:3] for u in t4.unmatched] == [("Sam Twin", 1)]
        and len(t5.lines) == 0 and [u[1:] for u in t5.unmatched] == [("Sam Twin", 1, shared)]
        and "TWIN_2" not in set(t5.slate.player_id)
        and [(r_.player_id, r_.team, r_.line, r_.matched) for r_ in t6.lines.itertuples()]
        == [("TWIN_1", "ARI", 2.5, "name")] and t6.unmatched == [])
    far = told({"booka": "Buffalo Bills", "bookb": "Buffalo Bills", "bookc": "Buffalo Bills"})
    chk("...nor when it puts him on a team that is not in this game",
        len(far.lines) == 0 and far.off_slate == {} and {u[3] for u in far.unmatched} == {
            "the odds file puts him on BUF: not one team in this game, so he is not priced"}
        and len(told({"bookc": "London Monarchs"}).lines) == 0)
    moved_roster = roster.assign(team=roster.team.where(roster.gsis_id != "AAA_WR2", "ATL"))
    left = fl.run_live(f, reports, moved_roster, [ev], fl.read_inputs(LIVE_IN))
    left0 = fl.run_live(f, reports, moved_roster, [ev], dict(
        fl.read_inputs(LIVE_IN), chances=[("ARI", "Will Two Jr.", 0.0)]))
    silent = fl.run_live(f, reports, moved_roster, [two], fl.read_inputs(LIVE_IN))
    spoken = _json_copy(two)
    for bk in spoken["bookmakers"]:
        for mk in bk["markets"]:
            for oc in mk["outcomes"]:
                oc["player_team"] = "Arizona Cardinals"
    elsewhere = roster.assign(team=roster.team.where(roster.gsis_id != "AAA_WR2", "BUF"))
    chk("when the book does not say and the roster has a player on the "
        "OTHER team in this game from the one slate he is on, he is not "
        "priced for his old team, found by id or by name; the book saying "
        "so settles it, and a roster that has him outside this game does not "
        "stop him",
        len(silent.lines) == 0 and [u[1:3] for u in silent.unmatched] == [
            ("Will Two", 1), ("Will Two Jr.", 2)]
        and all(u[3] == "the roster has him on ATL, the book does not say, and he is on ARI's "
                        "slate only: not active for ATL in its last four games. Add him to ATL in "
                        "the inputs if he is playing for it. " + fl.TOO_HIGH for u in silent.unmatched)
        and silent.off_slate == {"ATL": ["Will Two Jr."]}
        and sorted(fl.run_live(f, reports, moved_roster, [spoken], fl.read_inputs(LIVE_IN)).lines.team)
        == ["ARI", "ARI"]
        and fl.run_live(f, reports, moved_roster, [spoken], fl.read_inputs(LIVE_IN)).off_slate == {}
        and sorted(fl.run_live(f, reports, elsewhere, [two], fl.read_inputs(LIVE_IN)).lines.team)
        == ["ARI", "ARI"])
    left_st = fl.run_live(f, reports, moved_roster, [ev], dict(
        fl.read_inputs(LIVE_IN), statuses=[("ARI", "Will Two Jr.", "out")]))
    unlisted = fl.run_live(f, reports, roster[roster.gsis_id != "AAA_TE"], [ev], fl.read_inputs(LIVE_IN))
    chk("a slate player the roster has on another team is named in a note, "
        "since he is still counted as someone who may play; not once his "
        "chance or his status has been handed in, and not a man the roster "
        "does not have at all",
        not any("the roster has on another team" in n for n in left_st.notes + unlisted.notes)
        and "AAA_TE" in set(unlisted.slate.player_id) and
        "ARI's slate has players the roster has on another team: Will Two Jr. (roster: ATL). "
        "Each is still counted as someone who may play for ARI; hand in chance 0 for any who "
        "is not with ARI." in left.notes
        and not any("the roster has on another team" in n for n in left0.notes)
        and not any("the roster has on another team" in n for n in B.notes))
    both = lambda **kw: fl.run_live(moved, reports, roster, [ev], dict(fl.read_inputs(LIVE_IN), **kw))  # noqa: E731
    chk("a status handed in for a player who is on both teams' slates is "
        "refused, because a status goes with the player and would count "
        "for both; a chance for each team is how it is said",
        raises(lambda: both(statuses=[("ARI", "Will Two Jr.", "out")]), fl.Missing,
               "a status was handed in for Will Two Jr. on ARI, and he is on ['ATL']'s slate too")
        and raises(lambda: both(statuses=[("ATL", "espn:14", "questionable")]), fl.Missing,
                   "on ATL, and he is on ['ARI']'s slate too")
        and {(r_.team, r_.chance) for r_ in both(
            chances=[("ARI", "Will Two Jr.", 0.0), ("ATL", "Will Two Jr.", 0.8)]).slate.itertuples()
            if r_.player_id == "AAA_WR2"} == {("ARI", 0.0), ("ATL", 0.8)}
        and len(both(statuses=[("ARI", "Wes One", "out")]).slate) > 0)
    # -- a name the data does not have, and a player not on the slate
    post = lambda name, pid, line_=3.5: ("player_receptions", "main", None, [   # noqa: E731
        ("Over", name, line_, pid), ("Under", name, line_, pid)])
    game = lambda books: odds_event("Atlanta Falcons", "Arizona Cardinals", books)   # noqa: E731
    aka = lambda e, *al, fr=f, ro=roster, **kw: fl.run_live(   # noqa: E731
        fr, reports, ro, [e], dict(fl.read_inputs(LIVE_IN), aliases=list(al), **kw))
    row = lambda b: [(r_.team, r_.player_id, r_.line, r_.books, r_.matched)   # noqa: E731
                     for r_ in b.lines.itertuples(index=False)]
    spelt = game({"booka": [post("Wesley One", None)], "bookb": [post("Wes One", "espn:13")]})
    solo = game({"booka": [post("Wesley One", None)]})
    unnamed, known = aka(spelt), aka(spelt, ("ARI", "Wesley One", "Wes One"))
    alone = aka(solo, ("ARI", "wesley one jr.", "espn:13"))
    chk("a book's spelling the data does not have is not priced, and the "
        "reason says an alias can settle it; with the alias (the book's "
        "name, the team, the player) his line is priced as his own, pooled "
        "with the book that gives his id, and the run says the alias was "
        "used",
        row(unnamed) == [("ARI", "AAA_WR1", 3.5, "bookb", "id")]
        and [u[1:] for u in unnamed.unmatched] == [("Wesley One", 1, NOBODY)]
        and row(known) == [("ARI", "AAA_WR1", 3.5, "booka bookb", "id")] and known.unmatched == []
        and row(alone) == [("ARI", "AAA_WR1", 3.5, "booka", "alias")] and alone.unmatched == []
        and alone.lines.over.iloc[0] == known.lines.over.iloc[0] == unnamed.lines.over.iloc[0]
        and "ARI: the book's 'Wesley One' is read as Wes One, by an alias in the inputs" in known.notes
        and "ARI: the book's 'wesley one jr.' is read as Wes One, by an alias in the inputs" in alone.notes
        and not any("alias" in n for n in unnamed.notes)
        and "matched by an ALIAS from the inputs, not by id" in fl.flags_for(
            {"s21": {}}, next(alone.lines.itertuples(index=False)))
        and not any("ALIAS" in x for x in fl.flags_for({"s21": {}}, next(known.lines.itertuples(index=False)))))
    idle = aka(spelt, ("ARI", "Kenneth Nobody", "Wes One"), ("ARI", "Wes One", "espn:13"),
               ("BUF", "Wesley One", "Nobody Atall"))
    chk("an alias nothing posted answers to is named as not used, one for a "
        "name the book gives an id is not used either (the id decides), and "
        "one for a team that is not playing is not looked at",
        row(idle) == row(unnamed) and [u[1] for u in idle.unmatched] == ["Wesley One"]
        and idle.notes[-2:] == [
            "ARI: the alias for 'Kenneth Nobody' was not used: no line this run reads is posted "
            "under that name without an id",
            "ARI: the alias for 'Wes One' was not used: no line this run reads is posted under "
            "that name without an id"]
        and not any("BUF" in n and "alias" in n for n in idle.notes))
    far_game = aka(solo, ("BAL", "Wesley One", "Wyn One"))
    both_games = fl.run_live(f, reports, roster, [solo, ev2], dict(
        fl.read_inputs(LIVE_IN), aliases=[("BAL", "Wesley One", "Wyn One")]))
    chk("an alias is for its own team's game: the same name posted in "
        "another game of the run is not read by it",
        row(far_game) == [] and [u[1:] for u in far_game.unmatched] == [("Wesley One", 1, NOBODY)]
        and [r_ for r_ in row(both_games) if r_[0] in ("ARI", "ATL")] == []
        and ("ARI at ATL", "Wesley One", 1, NOBODY) in both_games.unmatched
        and "BAL: the alias for 'Wesley One' was not used: no line this run reads is posted "
            "under that name without an id" in both_games.notes
        and not any("alias" in n for n in far_game.notes))
    other_id = game({"booka": [post("Wesley One", None)], "bookb": [post("Wesley One", "espn:14")]})
    chk("an alias must name a player on the team or one added to it; it is "
        "refused when the file gives the same name the id of someone else, "
        "when both teams in a game have one for the same name, and when "
        "the name is another player's on these teams; it may say which of "
        "two namesakes the book means",
        raises(lambda: aka(solo, ("ARI", "Wesley One", "Abe Passer")), fl.Missing,
               "no player called 'Abe Passer' on ARI")
        and raises(lambda: aka(other_id, ("ARI", "Wesley One", "Wes One")), fl.Missing,
                   "ARI at ATL: the alias for 'Wesley One' names Wes One, and the odds file gives "
                   "that name the id of Will Two Jr.")
        and row(aka(other_id, ("ARI", "Wesley One", "espn:14"))) == [
            ("ARI", "AAA_WR2", 3.5, "booka bookb", "id")]
        and raises(lambda: aka(solo, ("ARI", "Wesley One", "Wes One"), ("ATL", "Wesley One", "Walt One")),
                   fl.Missing, "ARI at ATL: an alias for 'Wesley One' is given for both teams")
        and all(raises(lambda nm=nm: aka(game({"booka": [post(nm, None)]}), ("ARI", nm, "Wes One")),
                       fl.Missing, f"ARI at ATL: the alias for {nm!r} names Wes One, and that is the "
                                   f"name of {own} on these teams")
                for nm, own in (("Walt One", "Walt One"), ("rob back jr", "Rob Back"),
                                ("Nat Newman", "Nat Newman")))
        and row(aka(solo, ("ATL", "Wesley One", "Nat Newman"), add=[("ATL", "espn:99", "WR")])) == [
            ("ATL", "NEW_WR", 3.5, "booka", "alias")]
        and row(aka(game({"booka": [post("Sam Twin", None)]}), ("ARI", "Sam Twin", "espn:72"),
                    add=[("ARI", "espn:71", None), ("ARI", "espn:72", None)])) == [
            ("ARI", "TWIN_2", 3.5, "booka", "alias")]
        and row(aka(game({"booka": [post("Sam Twin", None)]}), ("ARI", "Sam Twin", "espn:71"),
                    add=[("ARI", "espn:71", None)])) == [("ARI", "TWIN_1", 3.5, "booka", "alias")])

    def on_team(e, team):
        e = _json_copy(e)
        for oc in e["bookmakers"][0]["markets"][0]["outcomes"]:
            oc["player_team"] = team
        return e

    cross = aka(on_team(solo, "Atlanta Falcons"), ("ARI", "Wesley One", "Wes One"))
    chk("the alias's team stands for the team said when the file says "
        "nothing, so a player on both slates is priced for that team; when "
        "the file names a team, the file decides",
        row(aka(solo, ("ARI", "Wesley One", "Will Two Jr."), fr=moved)) == [("ARI", "AAA_WR2", 3.5, "booka", "alias")]
        and row(aka(solo, ("ATL", "Wesley One", "Will Two Jr."), fr=moved)) == [("ATL", "AAA_WR2", 3.5, "booka", "alias")]
        and row(aka(on_team(solo, "Arizona Cardinals"), ("ARI", "Wesley One", "Wes One")))
        == [("ARI", "AAA_WR1", 3.5, "booka", "alias")]
        and aka(on_team(solo, "Arizona Cardinals"), ("ARI", "Wesley One", "Wes One")).off_slate == {}
        and aka(on_team(game({"booka": [post("Wes One", "espn:13")]}), "Arizona Cardinals")).off_slate == {}
        and row(cross) == [] and [u[1:] for u in cross.unmatched] == [(
            "Wesley One", 1, "the book has him on ATL, and he is not on ATL's slate: not active for "
                             "it in its last four games. Add him in the inputs if he is playing. "
                             + fl.TOO_HIGH)]
        and cross.off_slate == {"ATL": ["Wes One"]})
    newman = game({"booka": [post("Nat Newman", None)]})
    bare, renamed = aka(newman), aka(game({"booka": [post("Nathaniel Newman", None)]}),
                                     ("ATL", "Nathaniel Newman", "Nat Newman"))
    joined_ = aka(newman, add=[("ATL", "Nat Newman", None)])
    chk("a posted name with no id that belongs to one player on a team's "
        "roster, who is not on the slate, is said to be on that roster and "
        "addable, not to be nobody; added by name he is priced, and the "
        "caution on his team goes",
        row(bare) == [] and [u[1:] for u in bare.unmatched] == [(
            "Nat Newman", 1, "on ATL's roster but not on the slate: not active for ATL in its last "
                             "four games. Add him in the inputs if he is playing. " + fl.TOO_HIGH)]
        and bare.off_slate == {"ATL": ["Nat Newman"]}
        and fl.too_high_text("ATL", ["Nat Newman"]) in bare.notes
        and row(joined_) == [("ATL", "NEW_WR", 3.5, "booka", "name")]
        and joined_.off_slate == {} and not any("TOO HIGH" in n for n in joined_.notes)
        and [u[1:] for u in aka(on_team(newman, "Arizona Cardinals")).unmatched] == [(
            "Nat Newman", 1, "the book has him on ARI, and he is not on ARI's slate: not active for "
                             "it in its last four games. Add him in the inputs if he is playing. "
                             + fl.TOO_HIGH)]
        and aka(on_team(newman, "Arizona Cardinals")).off_slate == {
            "ARI": ["Nat Newman"], "ATL": ["Nat Newman"]}
        and [u[1:] for u in aka(on_team(newman, "Buffalo Bills")).unmatched] == [(
            "Nat Newman", 1, "the odds file puts him on BUF: not one team in this game, so he is not "
                             "priced. He is not on the slate of ATL. " + fl.TOO_HIGH)]
        and aka(on_team(newman, "Buffalo Bills")).off_slate == {"ATL": ["Nat Newman"]}
        and [u[1:] for u in aka(on_team(game({"booka": [post("Sam Stranger", None)]}),
                                        "Arizona Cardinals")).unmatched] == [("Sam Stranger", 1, NOBODY)])
    chk("...the same when an alias names him: the reason says it is the "
        "alias that puts him there",
        row(renamed) == [] and [u[1:] for u in renamed.unmatched] == [(
            "Nathaniel Newman", 1, "the alias has him on ATL, and he is not on ATL's slate: not "
                                   "active for it in its last four games. Add him in the inputs if "
                                   "he is playing. " + fl.TOO_HIGH)]
        and renamed.off_slate == {"ATL": ["Nat Newman"]})
    away_roster = roster.assign(team=roster.team.where(roster.gsis_id != "NEW_WR", "BUF"))
    nowhere = aka(game({"booka": [post("Nat Newman", "espn:99")]}), ro=away_roster)
    two_off = aka(game({"booka": [post("Nat Newman", "espn:99"), post("Sam Twin", "espn:72", 1.5),
                                  post("Sam Twin", "espn:71", 2.5)]}))
    chk("a player with an id whom the roster has on neither of these teams "
        "is on nobody's account; two posted players off one team's slate "
        "are both named, each once",
        [u[1:] for u in nowhere.unmatched] == [(
            "Nat Newman", 1, "on a roster but not on the slate: not active for either team in its "
                             "last four games. Add him in the inputs if he is playing.")]
        and nowhere.off_slate == {} and not any("TOO HIGH" in n for n in nowhere.notes)
        and two_off.off_slate == {"ARI": ["Sam Twin"], "ATL": ["Nat Newman"]}
        and [n for n in two_off.notes if "TOO HIGH" in n] == [
            fl.too_high_text("ARI", ["Sam Twin"]), fl.too_high_text("ATL", ["Nat Newman"])])
    def _tag(tm):
        e = game({f"book{i}": [post("Nat Newman", "espn:99")] for i in range(len(tm))})
        for bk, t_ in zip(e["bookmakers"], tm):
            for oc in bk["markets"][0]["outcomes"]:
                oc["player_team"] = t_
        return e

    tagged = lambda *tm: aka(_tag(tm))   # noqa: E731
    stale_tag, split_tag, wrong_tag = (tagged("Buffalo Bills"), tagged("Buffalo Bills", "Atlanta Falcons"),
                                       tagged("Arizona Cardinals"))
    chk("the team at risk is the one the file OR the roster has him on, so "
        "a tag that is stale, split between books, or simply the other "
        "team's does not hide it: the roster's team is cautioned, and the "
        "file's as well when it is in this game",
        [u[1:] for u in stale_tag.unmatched] == [(
            "Nat Newman", 1, "the odds file puts him on BUF: not one team in this game, so he is not "
                             "priced. He is not on the slate of ATL. " + fl.TOO_HIGH)]
        and stale_tag.off_slate == {"ATL": ["Nat Newman"]}
        and [u[1:] for u in split_tag.unmatched] == [(
            "Nat Newman", 1, "the odds file puts him on ATL and BUF: not one team in this game, so "
                             "he is not priced. He is not on the slate of ATL. " + fl.TOO_HIGH)]
        and split_tag.off_slate == {"ATL": ["Nat Newman"]}
        and [u[1:] for u in wrong_tag.unmatched] == [(
            "Nat Newman", 1, "the book has him on ARI, and he is not on ARI's slate: not active for "
                             "it in its last four games. Add him in the inputs if he is playing. "
                             + fl.TOO_HIGH)]
        and wrong_tag.off_slate == {"ARI": ["Nat Newman"], "ATL": ["Nat Newman"]}
        and [n for n in wrong_tag.notes if "TOO HIGH" in n] == [
            fl.too_high_text("ARI", ["Nat Newman"]), fl.too_high_text("ATL", ["Nat Newman"])])
    defender = roster.assign(position=roster.position.where(roster.gsis_id != "NEW_WR", "DB"))
    guard = aka(game({"booka": [post("Nat Newman", "espn:99")]}), ro=defender)
    unknown = aka(on_team(game({"booka": [post("Ted End", None)]}), "Atlanta Falcons"),
                  ro=roster[roster.gsis_id != "AAA_TE"])
    chk("...and only for a position the slate carries: a defender posted "
        "and not on the slate takes no targets from anyone; a slate player "
        "the roster does not have, so of no known position, still counts",
        unknown.off_slate == {"ATL": ["Ted End"]} and len(unknown.lines) == 0
        and guard.off_slate == {} and [u[1:] for u in guard.unmatched] == [(
            "Nat Newman", 1, "on ATL's roster but not on the slate: not active for ATL in its last "
                             "four games. Add him in the inputs if he is playing.")])
    unread = game({"booka": [post("Wes One", "espn:13"),
                             ("player_1st_td", "main", None, [("Nat Newman", "Nat Newman", None, "espn:99"),
                                                              ("Walt One", "Walt One", None, "espn:23"),
                                                              ("Sam Stranger", "Sam Stranger", None, None)])],
                   "bookb": [post("Sam Twin", "espn:71")]})
    quiet = aka(unread)
    chk("a player posted only in a market this run does not read, or only "
        "by a book it was not asked for, has no line to list; if he is off "
        "his team's slate the caution is still given, and not for one who "
        "is on it, a defender, or a name it cannot place",
        row(quiet) == [("ARI", "AAA_WR1", 3.5, "booka", "id")]
        and [u[1] for u in quiet.unmatched] == ["Sam Twin"]
        and quiet.off_slate == {"ARI": ["Sam Twin"], "ATL": ["Nat Newman"]}
        and fl.run_live(f, reports, roster, [unread], fl.read_inputs(LIVE_IN), books={"booka"}).off_slate
        == {"ARI": ["Sam Twin"], "ATL": ["Nat Newman"]}
        and fl.run_live(f, reports, roster, [unread], fl.read_inputs(LIVE_IN), books={"booka"}).unmatched == []
        and aka(unread, ro=defender).off_slate == {"ARI": ["Sam Twin"]}
        and aka(game({"booka": [post("Wes One", "espn:13"), ("player_1st_td", "main", None, [
            ("Nat Newman", "Nat Newman", None, None), ("Sam Twin", "Sam Twin", None, None),
            ("Will Two", "Will Two", None, None)])]})).off_slate == {"ATL": ["Nat Newman"]}
        and aka(on_team(game({"booka": [("player_1st_td", "main", None, [
            ("Will Two", "Will Two", None, "espn:14")])], "bookb": [post("Wes One", "espn:13")]}),
            "Arizona Cardinals"), ro=moved_roster).off_slate == {}
        and aka(unread, add=[("ATL", "espn:99", None), ("ARI", "espn:71", None)]).off_slate == {})
    stale = dict(fl.read_inputs(LIVE_IN), add=[("ATL", "Will Two Jr.", None)])
    joined = fl.run_live(f, reports, roster, [ev], stale)
    chk("a player can be added to a team the roster does not have him on "
        "yet, by name when it is his alone in the league or by id; he is "
        "then on both slates and named in the note; and the same player "
        "twice under add is refused",
        {(r_.team) for r_ in joined.slate.itertuples() if r_.player_id == "AAA_WR2"} == {"ARI", "ATL"}
        and any("ATL's slate has players the roster has on another team: Will Two Jr. (roster: ARI)"
                in n for n in joined.notes)
        and len(fl.run_live(f, reports, roster, [ev], dict(
            fl.read_inputs(LIVE_IN), add=[("ATL", "espn:14", "WR")],
            chances=[("ATL", "Will Two", 0.7)])).slate) == len(joined.slate)
        and raises(lambda: fl.run_live(f, reports, roster, [ev], dict(
            fl.read_inputs(LIVE_IN), add=[("ATL", "Will Two Jr.", None), ("ATL", "espn:14", "WR")])),
            fl.Missing, 'a player is listed twice under "add"')
        and raises(lambda: fl.run_live(f, reports, roster, [ev], dict(
            fl.read_inputs(LIVE_IN), add=[("ATL", "Sam Twin", None)])),
            fl.Missing, "more than one player called 'Sam Twin' on ATL")
        and raises(lambda: fl.run_live(f, reports, roster, [ev], dict(
            fl.read_inputs(LIVE_IN), add=[("ATL", "Nobody Atall", None)])),
            fl.Missing, "no player called 'Nobody Atall' on ATL"))
    chk("...a starter, a chance or a status still has to name a player on "
        "the team or one added to it: another team's quarterback is not "
        "taken as the starter until he is added",
        raises(lambda: fl.run_live(f, reports, roster, [ev], dict(
            fl.read_inputs(LIVE_IN), starters=dict(LIVE_IN["starters"], ATL="Art Passer"))),
            fl.Missing, "no player called 'Art Passer' on ATL")
        and raises(lambda: fl.run_live(f, reports, roster, [ev], dict(
            fl.read_inputs(LIVE_IN), starters=dict(LIVE_IN["starters"], ATL="espn:11"))),
            fl.Missing, "Art Passer (espn:11) is not on ATL")
        and raises(lambda: fl.run_live(f, reports, roster, [ev], dict(
            fl.read_inputs(LIVE_IN), chances=[("ATL", "Will Two Jr.", 0.5)])),
            fl.Missing, "no player called 'Will Two Jr.' on ATL")
        and list(fl.run_live(f, reports, roster, [ev], dict(
            fl.read_inputs(LIVE_IN), starters=dict(LIVE_IN["starters"], ATL="Art Passer"),
            add=[("ATL", "Art Passer", None)])).slate.query("starting_qb and team == 'ATL'").player_id)
        == ["AAA_QB"])

    half = dict(LIVE_IN, chances=[("ATL", "Walt One", 0.5), ("BAL", "CCC_RB", 0.0)],
                add=[("ATL", "Nat Newman", "WR")])
    H = fl.run_live(f, reports, roster, [ev], half)
    hs = H.slate.set_index("player_id")
    m0 = {p_: plain.point(at[p_], "targets") for p_ in S.player_id[S.team == "ATL"]}
    kk = {(r_.player_id, r_.stat, r_.line): r_ for r_ in H.lines.itertuples(index=False)}
    chk("a chance handed in is the one used and says so; one for a team "
        "whose game is not in the files is let pass; a player added is "
        "priced",
        hs.chance["BBB_WR1"] == 0.5 and hs.source["BBB_WR1"] == "given"
        and hs.source["BBB_RB"] == "counted" and "CCC_RB" not in hs.index
        and set(H.slate.team) == {"ARI", "ATL"}
        and ("NEW_WR", "receptions", 2.5) in kk and kk[("NEW_WR", "receptions", 2.5)].over > 0
        and "Nat Newman" not in {u[1] for u in H.unmatched})
    chk("...and every priced line carries its own player's chance of "
        "playing and where it came from, as the slate has them",
        len(H.lines) > 5
        and all(r_.chance == hs.chance[r_.player_id] and r_.source == hs.source[r_.player_id]
                and r_.name == hs.name[r_.player_id] and r_.position == hs.position[r_.player_id]
                for r_ in H.lines.itertuples(index=False))
        and len({r_.chance for r_ in H.lines.itertuples(index=False)}) > 1
        and not any(r_.chance == 1.0 for r_ in H.lines.itertuples(index=False)))
    H0 = fl.run_live(f, reports, roster, [ev], dict(half, chances=[]))
    Hm = fl.live_model(reports, {("ATL", "BBB_WR1"): 0.5}).project(
        h, H.slate[list(fs.SLATE_COLS)])
    ih = {p_: j for j, p_ in enumerate(H.slate.player_id)}
    chk("...and it reaches the model: with a receiver at 50% his teammate is "
        "expected more targets than with him near certain, by the model's "
        "own sum",
        H.P.point(ih["BBB_WR2"], "targets") == Hm.point(ih["BBB_WR2"], "targets")
        and H.P.point(ih["BBB_WR2"], "targets") > 1.02 * H0.P.point(ih["BBB_WR2"], "targets")
        and list(H0.slate.player_id) == list(H.slate.player_id) and m0["BBB_WR2"] > 0,
        (H.P.point(ih["BBB_WR2"], "targets"), H0.P.point(ih["BBB_WR2"], "targets")))

    told = dict(LIVE_IN, statuses=[("ATL", "Walt One", "out"), ("ARI", "Will Two", "none"),
                                   ("ATL", "Wade Two", "doubtful"), ("BUF", "Dan Passer", "out")],
                chances=[("ATL", "Wade Two", 0.4)])
    Tn = fl.run_live(f, reports, roster, [ev], told)
    ts = Tn.slate.set_index("player_id")
    as_if = pd.concat([reports[~((reports.t == T) & (reports.player_id == "AAA_WR2"))],
                       pd.DataFrame([(T, "BBB_WR1", "out"), (T, "BBB_WR2", "doubtful")],
                                    columns=["t", "player_id", "status"])], ignore_index=True)
    want_ch = fl.live_model(as_if, {("ATL", "BBB_WR2"): 0.4}).eff.opp.chance.describe(
        h, Tn.slate[list(fs.SLATE_COLS)]).set_index(Tn.slate.player_id)
    chk("a status handed in is this week's report for that player: it "
        "replaces the file's, 'none' clears it, the chance is counted from "
        "it as from any report, and it says where it came from; a chance "
        "handed in for the same player still wins",
        ts.status["BBB_WR1"] == "out" and ts.status["AAA_WR2"] == "none"
        and ts.status["BBB_WR2"] == "doubtful"
        and list(ts.chance) == list(want_ch.chance) and list(ts.status) == list(want_ch.status)
        and ts.source["BBB_WR1"] == ts.source["AAA_WR2"] == "counted from the status handed in"
        and ts.source["BBB_WR2"] == "given" and ts.chance["BBB_WR2"] == 0.4
        and ts.source["BBB_RB"] == "counted" and ts.chance["BBB_WR1"] != ts.chance["BBB_RB"]
        and ts.chance["AAA_WR2"] == ts.chance["AAA_WR1"] != S.chance[at["AAA_WR2"]]
        and Tn.P.point(list(Tn.slate.player_id).index("BBB_WR2"), "targets")
        == fl.live_model(as_if, {("ATL", "BBB_WR2"): 0.4}).project(
            h, Tn.slate[list(fs.SLATE_COLS)]).point(list(Tn.slate.player_id).index("BBB_WR2"), "targets"),
        (ts.chance["BBB_WR1"], ts.chance["BBB_RB"], ts.source["BBB_WR1"]))
    past = pd.concat([reports, pd.DataFrame(
        [(202403, "BBB_WR1", "questionable"), (202402, "BBB_WR1", "questionable"),
         (T, "AAA_RB", "questionable")], columns=["t", "player_id", "status"])], ignore_index=True)
    Tp = fl.run_live(f, past, roster, [ev], told)
    if_p = pd.concat([past[~((past.t == T) & (past.player_id == "AAA_WR2"))],
                      pd.DataFrame([(T, "BBB_WR1", "out"), (T, "BBB_WR2", "doubtful")],
                                   columns=["t", "player_id", "status"])], ignore_index=True)
    say = lambda rep_: fl.live_model(rep_, {("ATL", "BBB_WR2"): 0.4}).eff.opp.chance.describe(   # noqa: E731
        h, Tp.slate[list(fs.SLATE_COLS)])
    chk("...and it replaces nothing else: the same player's reports from "
        "earlier weeks still count towards how often each status plays, "
        "and another player's report this week still stands",
        list(Tp.slate.chance) == list(say(if_p).chance)
        and list(Tp.slate.status) == list(say(if_p).status)
        and Tp.slate.set_index("player_id").status["AAA_RB"] == "questionable"
        and list(say(if_p).chance) != list(say(if_p[~((if_p.player_id == "BBB_WR1") & (if_p.t < T))]).chance)
        and list(say(if_p).chance) != list(say(if_p[~((if_p.t == T) & (if_p.player_id == "AAA_RB"))]).chance))
    chk("...and with no report file at all a status handed in still counts, "
        "though the run still has to be told it may go without the file",
        raises(lambda: fl.run_live(f, None, roster, [ev], told), fl.Missing, "no injury report on file")
        and fl.run_live(f, None, roster, [ev], told, allow_no_report=True
                        ).slate.set_index("player_id").status["BBB_WR1"] == "out")

    def gone(msg, **kw):
        args = dict(frame=f, reports=reports, roster=roster, events=[ev],
                    inputs=fl.read_inputs(LIVE_IN))
        args.update(kw)
        fr = args.pop("frame"), args.pop("reports"), args.pop("roster"), args.pop("events"), args.pop("inputs")
        return raises(lambda: fl.run_live(*fr, **args), fl.Missing, msg)

    played = pd.concat([f, f[(f.t == 202403) & (f.team == "ARI")].assign(t=202404, week=4)],
                       ignore_index=True)
    chk("it stops, saying what, with no week, a week that disagrees with the "
        "inputs, no odds files, last week not on file, or a game already "
        "played",
        gone("no week", inputs=dict(fl.read_inputs(LIVE_IN), week=None))
        and gone("the week is 4.5; it must be a whole number from 1 to 22", week=4.5)
        and gone("the week is True", week=True)
        and gone("the week is 0", week=0, inputs=dict(fl.read_inputs(LIVE_IN), week=None))
        and gone("the season is 2023; the newest on file is 2024",
                 inputs=dict(fl.read_inputs(LIVE_IN), season=2023))
        and gone("the season is 2025; the newest on file is 2024, and only Week 1",
                 inputs=dict(fl.read_inputs(LIVE_IN), season=2025))
        and gone("the inputs are for week 4 and the run is for week 5", week=5)
        and gone("no odds files", events=[])
        and gone("the newest week in the history is 202402, not 202403", frame=f[f.t < 202403])
        and gone("only 1 of 4 teams have last week's game on file: week 3 is not finished",
                 frame=f[(f.t < 202403) | (f.team == "BUF")])
        and len(fl.run_live(f[(f.t < 202403) | f.team.isin(("ARI", "ATL"))], reports, roster,
                            [ev], fl.read_inputs(LIVE_IN)).lines) > 5
        and gone("['ARI'] already have a game on file for week 4", frame=played))
    chk("a starter named for a team whose game is not in the files is not "
        "looked up, so a name it could not place there does not stop the run",
        len(fl.run_live(f, reports, roster, [ev], dict(
            fl.read_inputs(LIVE_IN), starters=dict(LIVE_IN["starters"], BUF="Nobody Atall"))).lines)
        == len(fl.run_live(f, reports, roster, [ev], fl.read_inputs(LIVE_IN)).lines) > 5
        and gone("no player called 'Nobody Atall' on ATL",
                 inputs=dict(fl.read_inputs(LIVE_IN), starters=dict(LIVE_IN["starters"], ATL="Nobody Atall"))))
    chk("...with no injury report for the week, a starter it cannot place, "
        "no starter for a team in the files, or a chance for someone not on "
        "the slate",
        gone("no injury report on file for week 4 for anyone in these games",
                 reports=reports[reports.t < T])
        and gone("no injury report on file for week 4", reports=None)
        and gone("no injury report on file for week 4", reports=pd.DataFrame(
            [(T, "CCC_RB", "out"), (T, "DDD_WR1", "questionable")],
            columns=["t", "player_id", "status"]))
        and gone("'Wes One' (ARI) is listed twice under \"chances\"",
                 inputs=dict(fl.read_inputs(LIVE_IN), chances=[("ARI", "espn:13", 0.5), ("ARI", "Wes One", 0.6)]))
        and gone("'espn:13' (ARI) is listed twice under \"statuses\"",
                 inputs=dict(fl.read_inputs(LIVE_IN), statuses=[("ARI", "Wes One", "out"), ("ARI", "espn:13", "none")]))
        and gone("Ivan Dee (00-0099999) is not on ATL",
                 inputs=dict(fl.read_inputs(LIVE_IN), starters=dict(LIVE_IN["starters"], ATL="00-0099999")))
        and gone("Wes One is named as ARI's starting quarterback and is listed at WR",
                 inputs=dict(fl.read_inputs(LIVE_IN), starters=dict(LIVE_IN["starters"], ARI="Wes One")))
        and gone("no player called 'Nobody Atall' on ATL",
                 inputs=dict(fl.read_inputs(LIVE_IN), starters=dict(LIVE_IN["starters"], ATL="Nobody Atall")))
        and gone("no starting quarterback named for ['ATL']",
                 inputs=dict(fl.read_inputs(LIVE_IN), starters={"ARI": "Art Passer"}))
        and gone("a chance or a status was handed in for ['Nat Newman (ATL)']",
                 inputs=dict(fl.read_inputs(LIVE_IN), chances=[("ATL", "Nat Newman", 0.2)]))
        and gone("a chance or a status was handed in for ['Nat Newman (ATL)']",
                 inputs=dict(fl.read_inputs(LIVE_IN), statuses=[("ATL", "Nat Newman", "out")]))
        and gone("the history is too thin to fit the model: it has a number for nobody",
                 frame=f[f.t.isin((202402, 202403))]))
    A = fl.run_live(f, reports[reports.t < T], roster, [ev], fl.read_inputs(LIVE_IN),
                    allow_no_report=True)
    old_too = pd.concat([f, f[f.season == 2023].assign(season=2022, t=lambda d: d.t - 100)],
                        ignore_index=True)
    chk("with no season in the inputs it runs for the newest season on file",
        set(fl.run_live(old_too, reports, roster, [ev], dict(fl.read_inputs(LIVE_IN), season=None)
                        ).slate.season) == {2024}
        and int(old_too.season.min()) == 2022)
    wk1 = f.assign(t=f.t + 1, week=f.week + 1)
    chk("told it may, it runs without a report and says so first; and a week "
        "is taken from the run when the inputs name none",
        any(n.startswith("NO INJURY REPORT ON FILE for week 4") for n in A.notes)
        and not any("NO INJURY REPORT" in n for n in B.notes) and len(A.lines) == len(
            fl.run_live(f, reports, roster, [ev], fl.read_inputs(LIVE_IN)).lines)
        and len(fl.run_live(f, reports, roster, [ev],
                            dict(fl.read_inputs(LIVE_IN), week=None), week=4).lines) == len(A.lines))
    bye = f[~((f.team == "ARI") & (f.t == 202403))]
    empty = odds_event("Buffalo Bills", "Baltimore Ravens", {"booka": [
        ("player_sacks", "main", None, [("Over", "Rex Back", 0.5, "espn:32")])]})
    Y = fl.run_live(bye, reports, roster, [ev, empty], fl.read_inputs(LIVE_IN))
    chk("it notes a team whose newest game is not last week's, and a file "
        "with no line it has a stat for, and goes on",
        any(n.startswith("ARI: newest game on file is 202402") for n in Y.notes)
        and not any(n.startswith("ATL:") for n in Y.notes)
        and any(n == "BAL at BUF: the odds file has no line the simulator has a stat for"
                for n in Y.notes)
        and any(n == "BAL at BUF: 1 posted outcome passed over: no stat for player_sacks"
                for n in Y.notes)
        and not any("newest game" in n or "no line" in n for n in B.notes)
        and len(Y.lines) > 5 and set(Y.slate.team) == {"ARI", "ATL", "BAL", "BUF"})
    first = fl.run_live(f[f.season == 2023], pd.DataFrame(
        [(202401, "AAA_WR2", "out")], columns=["t", "player_id", "status"]), roster, [ev],
        dict(fl.read_inputs(LIVE_IN), week=1))
    cut_ = fl.run_live(f[f.season == 2023], pd.DataFrame(
        [(202401, "AAA_WR2", "out")], columns=["t", "player_id", "status"]),
        roster[roster.gsis_id != "AAA_TE"],
        [odds_event("Atlanta Falcons", "Arizona Cardinals", {"booka": [
            ("player_receptions", "main", None, [("Over", "Ted End", 2.5, None),
                                                 ("Under", "Ted End", 2.5, None)])]})],
        dict(fl.read_inputs(LIVE_IN), week=1))
    chk("a name with no id is looked for on the slates as well as the "
        "rosters: a player on the slate from last season's games, whom the "
        "roster no longer has, is still found by his name",
        [(r_.team, r_.player_id, r_.matched) for r_ in cut_.lines.itertuples(index=False)]
        == [("ARI", "AAA_TE", "name")] and cut_.unmatched == [])
    chk("the season after the newest on file can be run for Week 1 only",
        set(first.slate.season) == {2024} and raises(
            lambda: fl.run_live(f[f.season == 2023], reports, roster, [ev],
                                dict(fl.read_inputs(LIVE_IN), week=2)),
            fl.Missing, "only Week 1 of the next can be run"))
    chk("Week 1 runs on last season alone: no last week to be missing, and "
        "no note that every team's newest game is an old one",
        len(first.lines) > 5 and set(first.slate.game_id) == {"2024_01_ARI_ATL"}
        and not any("newest game" in n for n in first.notes) and len(first.notes) == 3
        and first.notes[0].startswith("Injury file for these teams: 1 listed, 1 out, ")
        and first.slate.status[list(first.slate.player_id).index("AAA_WR2")] == "out")
    only = fl.run_live(f, reports, roster, [ev], fl.read_inputs(LIVE_IN), books={"bookb"})
    none = fl.run_live(f, reports, roster, [ev], fl.read_inputs(LIVE_IN), books={"bookz"})
    some = fl.run_live(f, reports, roster, [ev], fl.read_inputs(LIVE_IN), books={"bookb", "bookz"})
    chk("only the books asked for are priced, and a book asked for that the "
        "file has nothing from is named",
        set(only.lines.books) == {"bookb"} and len(only.lines) == 3
        and len(none.lines) == 0
        and "ARI at ATL: the odds file has nothing the simulator reads from ['bookz']" in none.notes
        and not any("has no line" in n for n in none.notes)
        and len(some.lines) == 3
        and "ARI at ATL: the odds file has nothing the simulator reads from ['bookz']" in some.notes
        and not any("nothing the simulator reads" in n for n in only.notes))



@section("35. live run — the record, and what is printed")
def _():
    import hashlib
    import pathlib
    import tempfile
    from types import SimpleNamespace as NS
    f, roster, reports = live_league()
    full = live_frame()
    full = full[~((full.t == 202403) & (full.player_id == "AAA_WR2"))]     # he sits out once
    rec = fl.build_record(full, reports, 202404)
    run = fs.walk_forward(full, [fl.live_model(reports)], through=202404)
    here = pathlib.Path(fl.__file__).resolve().parent
    by_hand = hashlib.md5(b"".join((here / n).read_bytes() for n in (
        "ff_sim.py", "ff_sim_opp.py", "ff_sim_eff.py", "ff_sim_play.py", "ff_sim_td.py"))).hexdigest()
    chk("the record says what it was built from and over which weeks; the "
        "fingerprint is the five model files', by hand",
        rec["code"] == by_hand == fl.code_stamp() and rec["layout"] == 3
        and rec["s21_from"] == 0.65
        and (rec["first"], rec["through"], rec["weeks"]) == (202401, 202404, 4)
        and list(rec) == ["layout", "code", "s21_from", "first", "through", "weeks", "bands",
                          "s21"])
    tmp = pathlib.Path(tempfile.mkdtemp())
    for n in fl.MODEL_FILES:
        (tmp / n).write_bytes((here / n).read_bytes())
    same = fl.code_stamp(tmp)
    (tmp / "ff_sim_td.py").write_bytes((here / "ff_sim_td.py").read_bytes() + b"\n")
    chk("...and one byte more in any of them is another fingerprint",
        same == by_hand and fl.code_stamp(tmp) != by_hand)

    def hand_table(legs, folded):
        cal = fs.calibration(legs, folded=folded)
        bands = fs.FOLDED_BANDS if folded else fs.RAW_BANDS
        return [[lo, hi, int(r.n), int(r.games),
                 None if not r.n else round(float(r.stated), 4),
                 None if not r.n else round(float(r.happened), 4), r.read]
                for (lo, hi), r in zip(bands, cal.itertuples())]

    legs = lambda **kw: fs.graded_legs(run, "live", version="B", **kw)   # noqa: E731
    laddered = [s_ for s_ in ft.ALL_STATS if s_ != TD_STAT]
    chk("each stat's bands are the harness's own, on the list-not-known "
        "slate, by stand-in rung and on the side favoured, passing "
        "touchdowns like the rest",
        set(rec["bands"]) == set(ft.ALL_STATS) and "passing_tds" in laddered
        and all(set(rec["bands"][s_]) == {"x0.6", "x0.8", "main", "x1.25", "x1.6"}
                and all(rec["bands"][s_][r_] == hand_table(legs(stats=[s_], rung=r_), True)
                        for r_ in rec["bands"][s_]) for s_ in laddered)
        and sum(b[2] for s_ in laddered for r_ in rec["bands"][s_]
                for b in rec["bands"][s_][r_]) > 200
        and sum(b[2] for b in rec["bands"]["passing_tds"]["main"]) > 5
        and rec["bands"]["receptions"]["main"] != rec["bands"]["receptions"]["x0.6"]
        and any(rec["bands"][s_]["main"] != hand_table(
            fs.graded_legs(run, "live", version="A", stats=[s_], rung="main"), True)
            for s_ in laddered))
    td = legs(stats=[TD_STAT])
    chk("an anytime touchdown is kept on the chance of scoring as stated, "
        "0 to 100%, not on the side favoured",
        list(rec["bands"][TD_STAT]) == ["main"]
        and rec["bands"][TD_STAT]["main"] == hand_table(td, False)
        and [b[:2] for b in rec["bands"][TD_STAT]["main"]] == [list(b) for b in fs.RAW_BANDS]
        and sum(b[2] for b in rec["bands"][TD_STAT]["main"]) == len(td) > 10)

    def hand_s21(g):
        out = {}
        for side in ("OVER", "UNDER"):
            rows_ = [r for r in g.itertuples() if r.side == side and r.p_side >= 0.65]
            out[side] = [len(rows_),
                         None if not rows_ else round(sum(r.p_side for r in rows_) / len(rows_), 4),
                         None if not rows_ else round(sum(bool(r.hit) for r in rows_) / len(rows_), 4)]
        return out

    every = [s_ for s_ in ft.ALL_STATS if s_ != TD_STAT]
    chk("the S21 figures are, by hand, the main-line legs it put at 65% or "
        "better, overs and unders apart, for each stat and for all of them",
        set(rec["s21"]) == {*every, "all"}
        and all(rec["s21"][s_] == hand_s21(legs(stats=[s_], rung="main")) for s_ in every)
        and rec["s21"]["all"] == hand_s21(legs(stats=every, rung="main"))
        and rec["s21"]["all"]["UNDER"][0] > 10
        and rec["s21"]["all"]["UNDER"][0] == sum(rec["s21"][s_]["UNDER"][0] for s_ in every)
        and rec["s21"]["all"] != hand_s21(legs(stats=every))
        and rec["s21"]["all"] != hand_s21(fs.graded_legs(run, "live", version="A",
                                                         stats=every, rung="main")))
    real_probe = fs.leak_probe
    try:
        fs.leak_probe = lambda *a, **k: NS(clean=False, describe=lambda: "LEAK FOUND")
        chk("no record is made when the leak probe does not pass",
            raises(lambda: fl.build_record(full, reports, 202404), RuntimeError,
                   "the leak probe did not pass: LEAK FOUND"))
    finally:
        fs.leak_probe = real_probe

    chk("a missing record, one from other model code or another S21 "
        "threshold, one in another layout and one with a part missing are "
        "refused, saying how to rebuild; the right one passes",
        raises(lambda: fl.check_record(None), fl.Missing, "there is no record")
        and raises(lambda: fl.check_record({}), fl.Missing, "there is no record")
        and raises(lambda: fl.check_record(dict(rec, code="0" * 32)), fl.Missing, "different model code")
        and raises(lambda: fl.check_record(dict(rec, s21_from=0.7)), fl.Missing, "different model code")
        and raises(lambda: fl.check_record(dict(rec, layout=2)), fl.Missing, "not in the layout")
        and raises(lambda: fl.check_record({k_: v_ for k_, v_ in rec.items() if k_ != "s21"}),
                   fl.Missing, "not in the layout")
        and raises(lambda: fl.check_record(["RECORD"]), fl.Missing, "not in the layout")
        and raises(lambda: fl.check_record(dict(rec, layout=2)), fl.Missing, "sim_live.py --record")
        and fl.check_record(rec) is None and fl.check_record(dict(rec, extra=1)) is None)

    bands = [[round(0.5 + 0.05 * k, 2), round(0.55 + 0.05 * k, 2), 100 + k, 90, 0.52 + 0.05 * k,
              0.5 + 0.05 * k, "as stated"] for k in range(10)]
    bands[3][2] = 0
    raw = [[round(0.1 * k, 1), round(0.1 * (k + 1), 1), 1556, 642, 0.3416, 0.3535, "as stated"]
           for k in range(10)]
    R = {"weeks": 46, "first": 202401, "through": 202610,
         "bands": {"receptions": {"main": bands, "x0.6": bands}, "passing_tds": {"main": bands},
                   TD_STAT: {"main": raw}},
         "s21": {"receptions": {"OVER": [287, 0.7076, 0.6028], "UNDER": [0, None, None]},
                 "passing_tds": {"OVER": [69, 0.7044, 0.7681], "UNDER": [528, 0.7584, 0.7008]},
                 "all": {"OVER": [1823, 0.722, 0.6687], "UNDER": [7790, 0.7315, 0.7074]}}}
    chk("a stated chance is read in the band it falls in: the bottom of a "
        "band belongs to it, the top to the next, and 100% to the last",
        fl.band_of(R, "receptions", "main", 0.55)[:3] == (0.55, 0.6, 101)
        and fl.band_of(R, "receptions", "main", 0.5499)[:3] == (0.5, 0.55, 100)
        and fl.band_of(R, "receptions", "main", 0.5)[:2] == (0.5, 0.55)
        and fl.band_of(R, "receptions", "main", 1.0)[:2] == (0.95, 1.0)
        and fl.band_of(R, "receptions", "main", 0.97)[2] == 109
        and fl.band_of(R, TD_STAT, "main", 0.31)[:2] == (0.3, 0.4)
        and fl.band_of(R, TD_STAT, "main", 0.0)[:2] == (0.0, 0.1))
    chk("...and there is none for a stat, a rung or a chance the record does "
        "not have",
        fl.band_of(R, "carries", "main", 0.6) is None and fl.band_of(R, "receptions", "x1.6", 0.6) is None
        and fl.band_of(R, "receptions", "", 0.6) is None and fl.band_of(R, "receptions", "main", 0.4) is None
        and fl.band_of(R, "receptions", "main", float("nan")) is None
        and fl.band_of(R, "receptions", "main", 1.01) is None)

    def line(**kw):
        d = dict(stat="receptions", line=4.5, kind="main", rung="main", no_record="",
                 books="booka", suspended="", matched="id", over=0.56, push=0.0, under=0.44)
        d.update(kw)
        return NS(**d)

    chk("a line with nothing wrong carries no caution",
        fl.flags_for(R, line()) == [] and fl.flags_for(R, line(over=0.6499, under=0.3501)) == []
        and fl.flags_for(R, line(kind="ladder", rung="x0.6", over=0.9, under=0.1)) == []
        and fl.flags_for(R, line(rung="", no_record=fl.NO_ROLE, over=0.9, under=0.1)) == []
        and fl.flags_for(R, line(stat=TD_STAT, line=0.5, over=0.7, under=0.3)) == [])
    s21_over = ("S21 main-line caution: overs it put at 65%+ on this stat: stated 70.8%, "
                "happened 60.3% (287 legs)")
    chk("a line on HIS main line put at 65% or better carries the S21 "
        "caution with that stat's and that side's own record, and says so "
        "when there is none; it goes by his main line, not the book's",
        fl.flags_for(R, line(over=0.65, under=0.35)) == [s21_over]
        and fl.flags_for(R, line(kind="ladder", over=0.7, under=0.3)) == [s21_over]
        and fl.flags_for(R, line(kind="main", rung="x0.8", over=0.7, under=0.3)) == []
        and fl.flags_for(R, line(over=0.2, under=0.8)) == [
            "S21 main-line caution: no unders at 65%+ on this stat in the record"]
        and fl.on_main(line()) and not fl.on_main(line(rung="x1.25"))
        and not fl.on_main(line(stat=TD_STAT, line=0.5)))
    chk("...a passing touchdown on his main line carries both its own "
        "warning and the S21 one; off his main line, only its own",
        fl.flags_for(R, line(stat="passing_tds", over=0.3, under=0.7)) == [
            fl.PASS_TD_UNDER,
            "S21 main-line caution: unders it put at 65%+ on this stat: stated 75.8%, "
            "happened 70.1% (528 legs)"]
        and fl.flags_for(R, line(stat="passing_tds", rung="x0.8", over=0.3, under=0.7))
        == [fl.PASS_TD_UNDER]
        and fl.flags_for(R, line(stat="passing_tds", rung="", no_record=fl.OFF_LADDER,
                                 over=0.3, under=0.7)) == [fl.PASS_TD_UNDER])
    chk("every passing-touchdown line says its under is unreliable, whichever "
        "side is favoured and main line or not",
        all(fl.flags_for(R, line(stat="passing_tds", rung=r_, kind=k_, over=o_, under=1 - o_))[0]
            == fl.PASS_TD_UNDER for k_ in ("main", "ladder") for o_ in (0.4, 0.6)
            for r_ in ("main", "x1.25", ""))
        and "UNDER is unreliable" in fl.PASS_TD_UNDER and "5 points" in fl.PASS_TD_UNDER
        and fl.PASS_TD_UNDER not in fl.flags_for(R, line(stat="passing_yards")))
    chk("a player found by name, a suspended market and a line that can "
        "push each say so",
        fl.flags_for(R, line(matched="name")) == [
            "matched by NAME, not by id: check it is the right player"]
        and fl.flags_for(R, line(suspended="booka bookb")) == ["SUSPENDED at booka bookb"]
        and fl.flags_for(R, line(line=5.0, over=0.4, push=0.153, under=0.447)) == [
            "whole-number line: pushes 15.3%"]
        and len(fl.flags_for(R, line(matched="name", suspended="booka", over=0.7, under=0.3))) == 3)

    chk("the record beside a line, in words: the band, where it was read, "
        "what happened and of how many",
        fl.record_text(R, line()) == "said 55%-60% on his main line: happened 55.0% of 101 (as stated)"
        and fl.record_text(R, line(over=0.3, under=0.7)) == (
            "said 70%-75% on his main line: happened 70.0% of 104 (as stated)")
        and fl.record_text(R, line(kind="ladder", rung="x0.6", over=0.91, under=0.09)) == (
            "said 90%-95% on his x0.6 rung: happened 90.0% of 108 (as stated)")
        and fl.record_text(R, line(stat="passing_tds", over=0.42, under=0.58)) == (
            "said 55%-60% on his main line: happened 55.0% of 101 (as stated)")
        and fl.record_text(R, line(line=5.0, over=0.52, push=0.1, under=0.38)) == (
            "said 50%-55% on his main line: happened 50.0% of 100 (as stated)")
        and fl.record_text(R, line(stat=TD_STAT, line=0.5, over=0.31, under=0.69)) == (
            "said 30%-40%: scored 35.4% of 1,556 (as stated)"))
    chk("...and when there is none it says why: an empty band, a line off "
        "his ladder, a player with no stand-in line, two or more touchdowns, "
        "a table the record lacks",
        fl.record_text(R, line(over=0.66, under=0.34)) == "said 65%-70% on his main line: never, in the record"
        and fl.record_text(R, line(rung="", no_record=fl.OFF_LADDER)) == (
            "no record: the line is outside his stand-in ladder")
        and fl.record_text(R, line(rung="", no_record=fl.NO_ROLE)) == "no record: " + fl.NO_ROLE
        and fl.record_text(R, line(stat=TD_STAT, line=1.5, rung="", no_record=fl.TWO_PLUS,
                                   over=0.05, under=0.95)) == "no record: nothing grades two or more"
        and fl.record_text(R, line(kind="ladder", rung="x1.6")) == (
            "no record: the record has no table for this")
        and fl.record_text(R, line(stat="passing_yards")) == (
            "no record: the record has no table for this")
        and fl.record_text(R, line(line=4.0, over=0.363, push=0.161, under=0.476)) == (
            "no record: with the push, neither side reaches 50%")
        and fl.record_text(dict(R, bands={}), line(stat=TD_STAT, line=0.5, over=0.3, under=0.7)) == (
            "no record: the record has no table for this")
        and "four recent games" in fl.NO_ROLE)

    class Fake:
        def __init__(self, vals, td):
            self.vals, self.td = vals, td

        def point(self, i, stat):
            return self.vals.get(stat, float("nan"))

        def p_over(self, i, stat, line_):
            return self.td if (stat, line_) == (TD_STAT, 0.5) else 0.999

    chk("a stat line lists what he is expected to do, passing first, leaves "
        "out anything under a half, and ends with his chance of scoring",
        fl.stat_line(Fake({"attempts": 33.34, "completions": 21.4, "passing_yards": 223.06,
                           "passing_tds": 1.31, "carries": 4.1, "rushing_yards": 18.0,
                           "targets": 0.49}, 0.186), 0)
        == "33.3 pass att, 21.4 comp, 223.1 pass yds, 1.3 pass TD, 4.1 carries, 18.0 rush yds, scores 19%"
        and fl.stat_line(Fake({"targets": 7.25, "receptions": 5.0, "receiving_yards": 59.6}, 0.35), 0)
        == "7.2 targets, 5.0 catches, 59.6 rec yds, scores 35%"
        and fl.stat_line(Fake({}, float("nan")), 0) == "nothing projected"
        and fl.week_text(202611) == "2026 Week 11" and fl.week_text(202401) == "2024 Week 1")

    ev = odds_event("Atlanta Falcons", "Arizona Cardinals", {"booka": [
        ("player_receptions", "main", None, [("Over", "Wes One", 4.5, "espn:13"),
                                             ("Under", "Wes One", 4.5, "espn:13")]),
        ("player_reception_targets", "main", None, [("Over", "Wes One", 7.0, "espn:13"),
                                                    ("Under", "Wes One", 7.0, "espn:13")]),
        ("player_anytime_td", "milestone", None, [("Rob Back", "Rob Back", None, "espn:12"),
                                                  ("Ted End", "Ted End", None, None)]),
        ("player_2plus_td", "milestone", None, [("Rob Back", "Rob Back", None, "espn:12")]),
        ("player_pass_tds", "main", "2024-09-29T00:00:00Z",
         [("Over", "Abe Passer", 1.5, "espn:21"), ("Under", "Abe Passer", 1.5, "espn:21")]),
        ("player_receptions", "main", None, [("Over", "Sam Stranger", 2.5, None)])]})
    B = fl.run_live(f[~((f.team == "ATL") & (f.t == 202403))], reports, roster, [ev],
                    dict(fl.read_inputs(LIVE_IN), chances=[("ARI", "Will Two", 0.25)]))
    text = fl.render(B, rec)
    rows = text.split("\n")
    L = {(r.player_id, r.stat, r.line): r for r in B.lines.itertuples(index=False)}
    w = L[("AAA_WR1", "receptions", 4.5)]
    s21 = rec["s21"]["all"]
    chk("the printout opens with what it is, what the record does and does "
        "not cover, and the standing cautions, the S21 figures being the "
        "record's own; then the run's notes",
        rows[0].startswith("SHADOW RUN: the simulator's own numbers. Not a lean, no prices")
        and rows[1].startswith("Record: walk-forward, 4 weeks, 2024 Week 1 to 2024 Week 4, list "
                               "not known, with the injury report, on STAND-IN lines.")
        and rows[2].startswith("The record covers players with four recent games and a role in "
                               "them, graded with last game's starter and nothing handed in.")
        and "HIS OWN stand-in rung" in rows[2] and "not the book's" in rows[2]
        and rows[3] == "Every number is IF HE PLAYS."
        and rows[4] == (f"S21, the main-line caution. Legs on a player's main line that it has "
                        f"put at 65% or better, every stat: overs stated {s21['OVER'][1]:.1%}, "
                        f"happened {s21['OVER'][2]:.1%} ({s21['OVER'][0]:,} legs); unders stated "
                        f"{s21['UNDER'][1]:.1%}, happened {s21['UNDER'][2]:.1%} "
                        f"({s21['UNDER'][0]:,}). Each such line below carries its own "
                        f"stat's figures.")
        and rows[5].startswith("S24. Passing-touchdown UNDERS are unreliable")
        and "S25." in rows[5]
        and rows[6] == ("NOTE. Injury file for these teams: 1 listed, 0 out, 0 doubtful, 1 "
                        "questionable. It can be days behind the league's report; 0 statuses "
                        "and 1 chance were handed in.")
        and rows[7].startswith("NOTE. ['ATL']: nobody on the injury file this week.")
        and rows[8] == "NOTE. ATL: newest game on file is 202402 (a bye, or a game not yet published)"
        and rows[9] == "" and rows[10] == "=== ARI at ATL ===" and rows[11] == "--- ARI ---",
        rows[:12])
    i = list(B.slate.player_id).index("AAA_WR1")
    head = (f"Wes One (WR)  plays {B.slate.chance[i]:.0%} (counted)  |  "
            f"{fl.stat_line(B.P, i)}")
    at_ = rows.index(head) if head in rows else -1
    chk("a player's line gives his chance of playing and where it came from, "
        "then his stat line; under it each posted line with both sides, the "
        "books, the record, and its cautions",
        at_ > 0
        and rows[at_ + 1] == (f"    {'catches 4.5':<16} "
                              f"{f'over {w.over:.1%} / under {w.under:.1%}':<30} [booka]  "
                              f"{fl.record_text(rec, w)}")
        and rows[at_ + 2].startswith("    targets 7 ")
        and rows[at_ + 3].startswith("        ! whole-number line: pushes ")
        and any(r_.startswith("Will Two Jr. (WR)  plays 25% (given, report: questionable)")
                for r_ in rows) is False
        and any(r_.startswith("Rob Back (RB)  plays ") for r_ in rows))
    td_at = next(k for k, r_ in enumerate(rows) if r_.startswith("Rob Back (RB)"))
    qb_at = next(k for k, r_ in enumerate(rows) if r_.startswith("Abe Passer (QB, starting QB)"))
    chk("a touchdown is printed as the chance he scores, two or more as 2+; "
        "a passing touchdown carries its warning; a suspended market says "
        "where",
        rows[td_at + 1].startswith(f"    {'to score':<16} yes {L[('AAA_RB', TD_STAT, 0.5)].over:.1%}")
        and rows[td_at + 2].startswith(f"    {'2+ TDs':<16} yes {L[('AAA_RB', TD_STAT, 1.5)].over:.1%}")
        and "no record: nothing grades two or more" in rows[td_at + 2]
        and rows[qb_at + 1].startswith("    pass TD 1.5 ")
        and rows[qb_at + 2] == "        ! " + fl.PASS_TD_UNDER
        and "        ! SUSPENDED at booka" in rows[qb_at + 2:qb_at + 6]
        and any(r_ == "        ! matched by NAME, not by id: check it is the right player"
                for r_ in rows))
    names_at = [k for k, r_ in enumerate(rows) if "  plays " in r_ and not r_.startswith(" ")]
    ari = [rows[k].split(" (")[0] for k in names_at if k < rows.index("--- ATL ---")]
    chk("within a team the starter comes first, then backs, receivers and "
        "tight ends; a player with no posted line is left out unless "
        "everyone is asked for",
        ari == ["Art Passer", "Rob Back", "Wes One", "Ted End"]
        and "Will Two Jr." not in text
        and all(n_ in fl.render(B, rec, everyone=True) for n_ in B.slate.name)
        and "Will Two Jr. (WR)  plays 25% (given, report: questionable)" in fl.render(
            B, rec, everyone=True))
    order = pd.DataFrame(
        [(2024, 4, "2024_04_ARI_ATL", "ARI", "ATL", pid, nm, pos, qb, 1.0, "none", "counted")
         for pid, nm, pos, qb in (("w_lo", "Quiet Wideout", "WR", False), ("te", "Tight End", "TE", False),
                                  ("k", "Kicker", "K", False), ("q2", "Backup Passer", "QB", False),
                                  ("w_hi", "Busy Wideout", "WR", False), ("rb", "Running Back", "RB", False),
                                  ("fb", "Full Back", "FB", False), ("q1", "Starting Passer", "QB", True))],
        columns=[*fs.SLATE_COLS, "chance", "status", "source"])
    busy_p = Fake({}, 0.1)
    busy_p.point = lambda i, stat: {"targets": [2.0, 3.0, 0.0, 0.0, 9.0, 1.0, 0.5, 0.0][i],
                                    "carries": [0.0, 0.0, 0.0, 6.0, 0.5, 14.0, 20.0, 4.0][i]}.get(
        stat, float("nan"))
    shown = fl.render(fl.Board(order, pd.DataFrame(columns=fl.LINE_COLS), [], [], busy_p), R,
                      everyone=True).split("\n")
    chk("the order within a team, by hand on a slate listed the other way "
        "round: the starter, then the other quarterbacks, backs and "
        "fullbacks busiest first, receivers busiest first, tight ends, "
        "anyone else",
        [r_.split(" (")[0] for r_ in shown if "  plays " in r_] == [
            "Starting Passer", "Backup Passer", "Full Back", "Running Back", "Busy Wideout",
            "Quiet Wideout", "Tight End", "Kicker"])
    chk("...and it ends with what was posted but not priced, and why",
        rows[-2] == "POSTED BUT NOT PRICED"
        and rows[-1].startswith("    ARI at ATL: Sam Stranger (1 line): no id from the book that the "
                                "roster has, and nobody of that name on either team's roster or slate.")
        and rows[-1].endswith("until then his teammates' numbers here are too high.")
        and "POSTED BUT NOT PRICED" not in fl.render(
            fl.Board(B.slate, B.lines, [], [], B.P), rec))
    C = fl.to_csv(B, rec, 2024, 4)
    rec_line = lambda who, pid: ("player_receptions", "main", None, [   # noqa: E731
        ("Over", who, 3.5, pid), ("Under", who, 3.5, pid)])
    Bo = fl.run_live(f, reports, roster, [odds_event("Atlanta Falcons", "Arizona Cardinals", {"booka": [
        rec_line("Wes One", "espn:13"), rec_line("Walt One", "espn:23"), rec_line("Wade Two", "espn:24"),
        rec_line("Nat Newman", "espn:99")]})], fl.read_inputs(LIVE_IN))
    ro, Co = fl.render(Bo, rec).split("\n"), fl.to_csv(Bo, rec, 2024, 4)
    chk("a team with a posted player off its slate carries the caution "
        "under its name in the printout and on every one of its lines in "
        "the table, and the other team carries none",
        Bo.off_slate == {"ATL": ["Nat Newman"]} and B.off_slate == {}
        and ro[ro.index("--- ATL ---") + 1] == "! " + fl.too_high_text("ATL", ["Nat Newman"])
        and not ro[ro.index("--- ARI ---") + 1].startswith("!")
        and sum(r_.startswith("! ATL'S NUMBERS") for r_ in ro) == 1
        and "NOTE. " + fl.too_high_text("ATL", ["Nat Newman"]) in ro
        and not any("TOO HIGH" in r_ for r_ in rows)
        and sorted(Co.team) == ["ARI", "ATL", "ATL"]
        and all((c_ == "too high if Nat Newman plays: posted, and not on the slate") == (t_ == "ATL")
                and ("too high" in c_) == (t_ == "ATL") for c_, t_ in zip(Co.cautions, Co.team))
        and not any("too high" in c_ for c_ in C.cautions)
        and fl.flags_for(R, line(), ["A B", "C D"])[0] == "too high if A B, C D play: posted, and not on the slate"
        and not any("too high" in x for x in fl.flags_for(R, line()))
        and not any("too high" in x for x in fl.flags_for(R, line(), [])),
        (Bo.off_slate, list(zip(Co.team, Co.cautions))))
    chk("the table to save has one row per priced line: the season and week, "
        "everything on the line, its record and its cautions",
        list(C.columns) == ["season", "week", *fl.LINE_COLS, "record", "cautions"]
        and len(C) == len(B.lines) and set(C.season) == {2024} and set(C.week) == {4}
        and list(C.record) == [fl.record_text(rec, r_) for r_ in B.lines.itertuples(index=False)]
        and C.cautions[list(C.stat).index("passing_tds")].startswith(fl.PASS_TD_UNDER + " | ")
        and "over" in C.columns and not any(c in C.columns for c in ("price", "odds")))


@section("36. live run — the whole of it, as the script runs it")
def _():
    import json as _json
    import pathlib
    import tempfile
    f, roster, reports = live_league()
    rec = fl.build_record(live_frame(), reports, 202404)
    d = pathlib.Path(tempfile.mkdtemp())
    ev = odds_event("Atlanta Falcons", "Arizona Cardinals", {"booka": [
        ("player_receptions", "main", None, [("Over", "Wes One", 4.5, "espn:13"),
                                             ("Under", "Wes One", 4.5, "espn:13")]),
        ("player_receptions", "alternate", None, [("Over", "Wes One", 7.5, "espn:13")]),
        ("player_anytime_td", "milestone", None, [("Rob Back", "Rob Back", None, "espn:12")]),
        ("player_2plus_td", "milestone", None, [("Rob Back", "Rob Back", None, "espn:12")])]})
    (d / "game.json").write_text(_json.dumps([{"type": "text", "text": _json.dumps(ev)}]))
    (d / "in.json").write_text(_json.dumps(LIVE_IN))
    NOW = pd.Timestamp("2024-09-27 12:00", tz="UTC")
    DATES = pd.DataFrame({"week": [3, 3, 3], "game_date": ["2024-09-19", "2024-09-22", "2024-09-23"]})
    go = lambda **kw: fl.shadow_run(f, reports, roster, rec, [str(d / "game.json")],   # noqa: E731
                                    str(d / "in.json"), **dict({"now": NOW, "dates": DATES}, **kw))
    text, code = go()
    B = fl.run_live(f, reports, roster, [ev], fl.read_inputs(LIVE_IN))
    hid = ("2 ladder lines (rungs, alternates, 2+ and 3+ touchdowns) were priced and are not "
           "shown: run with --ladders to see them.")
    mains = fl.Board(B.slate, B.lines[B.lines.kind == "main"].reset_index(drop=True),
                     B.unmatched, B.notes + [hid], B.P)
    chk("from the saved files it prints the run and ends clean; unasked, "
        "only main lines and the anytime touchdown, saying how many others "
        "it priced",
        code == 0 and text == fl.render(mains, rec) and "catches 4.5" in text
        and "to score" in text and "catches 7.5" not in text and "2+ TDs" not in text
        and len(mains.lines) == 2 and "NOTE. " + hid in text)
    full_text, _ = go(ladders=True)
    chk("...asked for ladders it prices every line; asked for everyone it "
        "prints players with no line; asked for one book it reads only "
        "that, however the book's name is typed",
        full_text == fl.render(B, rec) and "catches 7.5" in full_text and "2+ TDs" in full_text
        and hid not in full_text
        and go(everyone=True)[0] == fl.render(mains, rec, everyone=True) != text
        and "catches 4.5" not in go(books={"nobody"})[0]
        and go(books={"booka"})[0] == text == go(books={" BookA"})[0])
    saved_text, saved_code = go(out=str(d / "out.csv"), ladders=True)
    C = pd.read_csv(d / "out.csv")
    chk("...asked to save, it writes the priced lines as a table, with the "
        "week it ran for, and says how many",
        saved_code == 0 and saved_text == full_text + f"\n\nsaved 4 priced lines to {d / 'out.csv'}"
        and len(C) == 4 and list(C.columns) == ["season", "week", *fl.LINE_COLS, "record", "cautions"]
        and set(C.season) == {2024} and set(C.week) == {4}
        and near(C.over[0], B.lines.over[0], 1e-12) and list(C.line) == list(B.lines.line))
    live_ev = dict(ev, live=True)
    (d / "live.json").write_text(_json.dumps(live_ev))
    (d / "notime.json").write_text(_json.dumps({k_: v_ for k_, v_ in ev.items() if k_ != "commence_time"}))
    (d / "nozone.json").write_text(_json.dumps(dict(ev, commence_time="2024-09-29T17:00:00")))
    (d / "bytes.json").write_bytes(b"\xff\xfe\x00\x81")
    (d / "shape.json").write_text(_json.dumps(dict(ev, bookmakers=[{"key": "booka", "markets": "oops"}])))
    (d / "next.json").write_text(_json.dumps(dict(ev, commence_time="2024-10-04T00:15:00Z")))
    (d / "season.json").write_text(_json.dumps(dict(LIVE_IN, season=2025, week=1)))
    stops = [
        (dict(), dict(odds=[str(d / "bytes.json")]), "cannot read the odds file"),
        (dict(), dict(odds=[str(d / "shape.json")]), "not in the shape of a get_odds response"),
        (dict(dates=DATES), dict(odds=[str(d / "next.json")]),
         "which is not in this week (Wednesday 2024-09-25 to Tuesday 2024-10-01"),
        (dict(dates=DATES, week=5), dict(), "the inputs are for week 4 and the run is for week 5"),
        (dict(), dict(record=None), "there is no record"),
        (dict(), dict(record=dict(rec, code="x")), "different model code"),
        (dict(), dict(inputs=None), "no --inputs file"),
        (dict(), dict(odds=[str(d / "absent.json")]), "cannot read the odds file"),
        (dict(), dict(odds=[]), "no odds files"),
        (dict(week=5), dict(), "the inputs are for week 4"),
        (dict(), dict(reports=None), "no injury report on file"),
        (dict(now=pd.Timestamp("2024-09-29 17:00", tz="UTC")), dict(),
         "ARI at ATL kicked off 2024-09-29 17:00 UTC: the game has started"),
        (dict(now=pd.Timestamp("2024-09-21 16:59", tz="UTC"), dates=None), dict(),
         "ARI at ATL kicks off 2024-09-29, more than 8 days from now"),
        (dict(), dict(inputs=str(d / "season.json")), "which is not in the 2025 season"),
        (dict(), dict(odds=[str(d / "live.json")]), "ARI at ATL is in progress"),
        (dict(out=str(d / "nowhere" / "out.csv")), dict(), "cannot save to")]
    out = []
    for kw, swap_, _ in stops:
        a = dict(frame=f, reports=reports, roster=roster, record=rec,
                 odds=[str(d / "game.json")], inputs=str(d / "in.json"))
        a.update(swap_)
        out.append(fl.shadow_run(a["frame"], a["reports"], a["roster"], a["record"],
                                 a["odds"], a["inputs"],
                                 **dict({"out": str(d / "no.csv"), "now": NOW, "dates": DATES}, **kw)))
    chk("when something is missing it prints STOPPED and what, ends with "
        "code 2, and saves nothing: no record, a stale one, no inputs, no "
        "odds, an odds file that is not text or not a response, next week's "
        "game, the wrong week, no report, a game that has started, one more "
        "than eight days off, one outside the season, one in progress, "
        "nowhere to save",
        all(t_.startswith("STOPPED. ") and msg in t_ and c_ == 2
            for (t_, c_), (_, _, msg) in zip(out, stops))
        and not (d / "no.csv").exists()
        and fl.shadow_run(f, None, roster, rec, [str(d / "game.json")], str(d / "in.json"),
                          allow_no_report=True, now=NOW)[1] == 0
        and fl.shadow_run(None, reports, roster, rec, [str(d / "game.json")], str(d / "season.json"),
                          now=NOW)[0].startswith("STOPPED. ARI at ATL kicks off 2024-09-29, which is "
                                                 "not in the 2025 season"))
    nxt = lambda **kw: fl.shadow_run(f, reports, roster, rec, [str(d / "next.json")],   # noqa: E731
                                     str(d / "in.json"), now=NOW, **kw)
    (d / "noweek.json").write_text(_json.dumps({k_: v_ for k_, v_ in LIVE_IN.items() if k_ != "week"}))
    bare = go(dates=None)
    chk("the week's dates are worked out from last week's games: next "
        "week's Thursday game is refused though it is inside eight days; "
        "without the dates it runs, and the printout says the eight-day "
        "rule was all it had; the week is the run's when the inputs name "
        "none",
        nxt()[1] == 0 and "NOTE. " + fl.NO_WINDOW in nxt()[0] and nxt(dates=DATES)[1] == 2
        and bare[1] == 0 and "NOTE. " + fl.NO_WINDOW in bare[0] and fl.NO_WINDOW not in text
        and bare[0].replace("NOTE. " + fl.NO_WINDOW + "\n", "") == text
        and go(now=pd.Timestamp("2024-09-10 12:00", tz="UTC"))[1] == 0
        and go(dates=None, now=pd.Timestamp("2024-09-10 12:00", tz="UTC"))[1] == 2
        and fl.shadow_run(f, reports, roster, rec, [str(d / "next.json")], str(d / "noweek.json"),
                          now=NOW, dates=DATES, week=4)[0].startswith(
            "STOPPED. ARI at ATL kicks off 2024-10-04 00:15 UTC, which is not in this week")
        and fl.shadow_run(f, reports, roster, rec, [str(d / "game.json")], str(d / "noweek.json"),
                          now=NOW, dates=DATES, week=4) == (text, 0))
    edge = go(dates=None, now=pd.Timestamp("2024-09-21 17:00", tz="UTC"))
    no_time = fl.shadow_run(f, reports, roster, rec, [str(d / "notime.json")], str(d / "in.json"),
                            now=NOW, dates=DATES)
    chk("with no dates a game exactly eight days off is taken; one whose "
        "file carries no kickoff time is run with a note that it was not "
        "checked; with no time handed in it goes by the clock, and the 2024 "
        "fixture has long since kicked off",
        edge[1] == 0 and no_time[1] == 0
        and fl.shadow_run(f, reports, roster, rec, [str(d / "nozone.json")], str(d / "in.json"),
                          now=NOW, dates=DATES)[0] == text
        and fl.shadow_run(f, reports, roster, rec, [str(d / "nozone.json")], str(d / "in.json"),
                          now=pd.Timestamp("2024-09-29 17:00", tz="UTC"))[0].startswith(
            "STOPPED. ARI at ATL kicked off 2024-09-29 17:00 UTC")
        and "NOTE. ARI at ATL: no kickoff time in the odds file, so it was not checked" in no_time[0]
        and "no kickoff time" not in text
        and fl.shadow_run(f, reports, roster, rec, [str(d / "game.json")], str(d / "in.json"))[0]
        .startswith("STOPPED. ARI at ATL kicked off"))
    oops = fl.shadow_run(None, reports, roster, rec, [str(d / "game.json")], str(d / "in.json"),
                         now=NOW, out=str(d / "no.csv"))
    chk("a fault it did not foresee still stops with words, not a "
        "traceback, under its own code",
        oops[1] == 3 and oops[0].startswith("STOPPED. Something it did not foresee: TypeError")
        and "Nothing was priced" in oops[0] and not (d / "no.csv").exists())


# This section is the one place the file names players and a week. It
# replays one saved response (the book's own names, ids and lines for one
# game) against the data on file cut off before that game, so what it
# expects cannot move as later weeks arrive.
@section("37. live run — real data")
def _():
    import ff_data
    try:
        from sim_record import RECORD
    except ImportError:
        RECORD = None
    chk("the committed record was built from the model code that is here",
        RECORD is not None and RECORD.get("code") == fl.code_stamp()
        and RECORD.get("layout") == fl.LAYOUT, None if RECORD is None else RECORD.get("code"))
    if RECORD is None:
        return
    fl.check_record(RECORD)
    a = RECORD["s21"]["all"]
    chk("...over 46 weeks or more, with thousands of main-line legs behind "
        "the S21 figures and a table for every stat",
        RECORD["weeks"] >= 46 and RECORD["first"] == 202401 and RECORD["through"] >= 202610
        and a["OVER"][0] > 1000 and a["UNDER"][0] > 5000
        and 0.65 < a["OVER"][1] < 0.85 and 0.5 < a["OVER"][2] < 0.9
        and set(RECORD["bands"]) == set(ft.ALL_STATS)
        and all(set(RECORD["bands"][s_]) == set(fl.RUNG_LABELS)
                for s_ in ft.ALL_STATS if s_ != TD_STAT))
    frame = REAL.get("frame")
    if frame is None:
        frame = fs.load_frame()
    frame = frame[frame.t < 202611]
    reports = fp.load_reports([2023, 2024, 2025, 2026])
    roster = ff_data.load_roster(2026)
    inputs = fl.read_inputs({"season": 2026, "week": 11, "starters": {
        "Denver Broncos": "00-0039732", "LV": "00-0041562"}})
    B = fl.run_live(frame, reports, roster, [real_event()], inputs)
    S, L = B.slate, B.lines
    key = {(r.name, r.stat, r.line): r for r in L.itertuples(index=False)}
    chk("a real week: Las Vegas at Denver, 2026 Week 11, from the real "
        "response. Both teams' slates are built, with the named starters, "
        "and this week's injury report is read",
        set(S.team) == {"DEN", "LV"} and set(S.game_id) == {"2026_11_LV_DEN"}
        and sorted(S.name[S.starting_qb]) == ["Bo Nix", "Fernando Mendoza"]
        and S.groupby("team").size().between(12, 40).all()
        and (S.status != "none").sum() >= 3 and S.chance.between(0.0, 1.0).all()
        and not any("NO INJURY REPORT" in n for n in B.notes), S.groupby("team").size().to_dict())
    chk("...every player the book lists is found by his id, the one the "
        "book spells without his suffix included, and every line is priced",
        B.unmatched == [] and set(L.matched) == {"id"} and len(L) == 17
        and ("Marvin Mims Jr.", TD_STAT, 1.5) in key
        and ("Bo Nix", "passing_tds", 1.5) in key and key[("Bo Nix", "passing_tds", 1.5)].kind == "main"
        and key[("Fernando Mendoza", "passing_tds", 0.5)].kind == "main"
        and key[("Bo Nix", "passing_tds", 1.5)].rung == "main" and B.off_slate == {}
        and not any("TOO HIGH" in n or "alias" in n for n in B.notes), (len(L), B.unmatched))
    own = fs.standin_lines(History(frame, 202611), fs.line_window(History(frame, 202611), "00-0039732"),
                           "passing_tds")
    chk("...a passing-touchdown line is read on the quarterback's own rung, "
        "and a line off his ladder has no record rather than another "
        "quarterback's",
        own == [("x0.8", 0.5), ("main", 1.5)]
        and key[("Bo Nix", "passing_tds", 0.5)].rung == "x0.8"
        and all(key[("Bo Nix", "passing_tds", x)].rung == ""
                and key[("Bo Nix", "passing_tds", x)].no_record == fl.OFF_LADDER
                for x in (2.5, 3.5, 4.5)))
    chk("...a starter with fewer than four games behind him has no record "
        "beside his lines, and says why; nor has two or more touchdowns",
        key[("Fernando Mendoza", "passing_tds", 0.5)].rung == ""
        and key[("Fernando Mendoza", "passing_tds", 0.5)].no_record == fl.NO_ROLE
        and len(fs.line_window(History(frame, 202611), "00-0041562")) < 4
        and all(r.no_record == fl.TWO_PLUS for r in L.itertuples() if r.stat == TD_STAT))
    nix = key[("Bo Nix", "passing_tds", 1.5)]
    tgt = {tm: sum(B.P.point(i, "targets") for i in S.index[S.team == tm]
                   if not math.isnan(B.P.point(i, "targets"))) for tm in ("DEN", "LV")}
    chk("...and the numbers are football: a starter is expected one to two "
        "and a half touchdown passes, two or more touchdowns is rare for "
        "everyone, and chances fall as the line rises",
        0.8 < nix.expected < 2.6 and 0.15 < nix.over < 0.75
        and all(0.0 <= r.over <= 1.0 and near(r.over + r.push + r.under, 1.0, 1e-9)
                for r in L.itertuples())
        and max(r.over for r in L.itertuples() if r.stat == TD_STAT) < 0.2
        and key[("Bo Nix", "passing_tds", 0.5)].over > nix.over
        > key[("Bo Nix", "passing_tds", 2.5)].over > key[("Bo Nix", "passing_tds", 4.5)].over
        and all(20 < v < 60 for v in tgt.values()), (nix.expected, nix.over, tgt))
    text = fl.render(B, RECORD)
    chk("...and it prints: the game, both starters first on their teams, a "
        "record beside every passing-touchdown line and the warning under it",
        "=== LV at DEN ===" in text and "Bo Nix (QB, starting QB)  plays " in text
        and text.index("--- LV ---") < text.index("Fernando Mendoza (QB, starting QB)")
        < text.index("--- DEN ---") < text.index("Bo Nix (QB, starting QB)")
        and text.count("        ! " + fl.PASS_TD_UNDER) == 8
        and text.count("on his main line: happened ") == 1
        and text.count("on his x0.8 rung: happened ") == 1
        and text.count("no record: " + fl.OFF_LADDER) == 3
        and text.count("no record: " + fl.NO_ROLE) == 3
        and "POSTED BUT NOT PRICED" not in text)


_summary()
sys.exit(1 if fails else 0)
