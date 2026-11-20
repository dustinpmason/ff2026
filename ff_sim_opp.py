#!/usr/bin/env python3
"""
ff_sim_opp.py — S4. The opportunity model: the first piece of the simulator.

It projects three things and nothing else: a player's TARGETS, his CARRIES,
and the starting quarterback's PASS ATTEMPTS. Catches, yards and touchdowns are what a
player does with an opportunity, and come later (efficiency). For those it
returns "no projection", which the harness reports as coverage.

HOW IT WORKS, IN ORDER

  1. How much will the TEAM throw and run? For each team in each game: its
     own recent volume, and what its opponent has recently allowed, each as
     an average that leans on the newest games. A straight-line fit on the
     games in the history turns those two into a number. Optionally the
     game's closing spread and total go into the same fit.

  2. What SHARE of it is his? His share of his team's targets (or carries)
     over his recent games, a longer-run version of the same, and what his
     position usually gets. A second straight-line fit on the history
     weighs the three.

  3. Who is actually here? The shares of everyone on the slate for that
     team are scaled to add up to 1. So when a teammate is not on the
     slate, his share is handed round. This is the first projector that
     reads who is on the slate (`uses_actives = True`). It hands a share to
     EVERYONE on the slate, so a slate that lists players who will not play
     (the harness's version B) costs it: see `sim_opportunity.py`.

  4. A range, not just a number. His count is spread around its mean the
     way counts in the history were spread around theirs (a negative
     binomial; one spread per stat, measured on the history: for pass
     attempts, on starting quarterbacks' own games). The chance of clearing
     a line is read off that.

  Pass attempts are simpler: the team's projected attempts times the share
  starters have thrown, given to whoever the slate names as the starter.
  It says nothing about any other quarterback's attempts.

THREE THINGS IN THE FITS A READER SHOULD KNOW. A position's usual share is
averaged over the whole history, so the share fit's rows for early games
use a norm that later games helped set (it is still only history, never
the week being projected). The spread is measured round the fit's own
in-sample numbers, on players with an earlier game and before shares are
scaled to the slate, and is then applied to the scaled numbers and to
first-game players too. And it is ONE spread per stat, which
`sim_opportunity.py` shows is too wide for the biggest roles and too
narrow for small ones.

WHAT THE BRIEF ASKED FOR THAT THIS IS NOT. SIM-HANDOFF.md describes "team
plays, pass rate, each player's share of snaps, targets and carries". This
first version fits team targets, team carries and team pass attempts
directly, three separate fits, rather than plays times pass rate; and it
never reads a snap count. Each player's count is also drawn on its own:
it says nothing about two teammates together, and a team's projected
targets and its quarterback's projected attempts are not tied to each
other.

EVERYTHING ELSE IS LEARNED FROM THE HISTORY IT IS HANDED. Both fits, the
position norms, the starter's share of pass attempts and the spreads are
worked out again every week from earlier weeks only. What is NOT learned:
the constants below (eight numbers: three half-lives, the fewest rows a
fit may have, the smallest expected count the spread is measured on, the
two ends of the range the spread is held to, and the floor under a team's
volume), and one convention: with no start on record in the history, a
starter is taken to throw every pass. They were CHOSEN before the first
run and have not been tuned against the test (S2).

THE SINGLE NUMBER it reports is the expected count (`single="mean"`), which
is what the next stage multiplies. `single="median"` reports the count's
median instead: a whole number, usually below the mean. Measured, the
median does not miss by less (`sim_opportunity.py`).

THE CLOSING SPREAD AND TOTAL are market numbers and are not on the harness's
slate. They are handed to the model at construction (`lines=`), which the
leak probe cannot see into (S8). The model looks a line up for exactly two
sets of games: those in the history it is fitting, and those on the slate
in front of it. `_market` refuses anything else (`LeakError`); as the code
stands nothing asks it for anything else, so that refusal is a tripwire
for a later edit and is tested directly. The table from `closing_lines`
holds only games already played: on a live week the model with lines stops
with a `KeyError` naming the game until that week's lines are supplied.
Whether to use them at all is Dustin's decision; `sim_opportunity.py`
reports the model with and without.

    python3 sim_opportunity.py --current-week 11

Owned by the simulator thread. It imports the engine and edits none of it.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

import ff_data

ff_data.ensure_deps("scipy")

from scipy.stats import nbinom  # noqa: E402

from ff_sim import (MAIN, History, LeakError, Projection,  # noqa: E402
                    Projector, SLATE_COLS, slate_active)

#: What this model projects.
OPP_STATS = ("targets", "carries", "attempts")
#: The two stats that are SHARED OUT among a team's players.
SHARED = ("targets", "carries")

# CHOSEN, NOT TUNED (S2). Every number in this model that is set by hand.
HALF_LIFE_TEAM = 4.0      # games: a team's volume, and what a defence allows
HALF_LIFE_SHORT = 3.0     # games: a player's recent share
HALF_LIFE_LONG = 10.0     # games: ...and his longer-run share
#: Either straight-line fit on fewer rows than this and nothing is said.
MIN_FIT_ROWS = 16
#: The spread of a shared count is measured on expected counts above this.
SIZE_MIN_MEAN = 1.0
#: The spread is held to this range of the negative binomial's size. Near 1
#: is very wide; 500 is all but a Poisson.
SIZE_RANGE = (1.0, 500.0)
#: A team is never projected for less than this many targets, carries or
#: pass attempts.
VOLUME_FLOOR = 1.0

SINGLE = ("mean", "median")


def ols(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Least squares with an intercept. Returns [intercept, slopes...]."""
    X1 = np.column_stack([np.ones(len(X)), X])
    return np.linalg.lstsq(X1, np.asarray(y, dtype=float), rcond=None)[0]


def predict(beta: np.ndarray, X: np.ndarray) -> np.ndarray:
    X = np.asarray(X, dtype=float)
    return beta[0] + X.reshape(len(X), len(beta) - 1) @ beta[1:]


def leaning_average(values: pd.Series, groups: pd.Series, half_life: float):
    """(before, now) for an average that leans on the newest games.

    `before` is, for each row, the average over that group's EARLIER rows:
    what was known going into that game. Blank for a group's first row.
    `now` is, per group, the average over all its rows: what is known going
    into the next one. Rows must already be in time order.
    """
    incl = (values.groupby(groups).ewm(halflife=half_life).mean()
            .reset_index(level=0, drop=True).reindex(values.index))
    return incl.groupby(groups).shift(1), incl.groupby(groups).last()


def size_from(x: np.ndarray, m: np.ndarray) -> float:
    """The negative binomial's size from counts and their means.

    Variance = m + m^2 / size, so size = sum(m^2) / sum((x - m)^2 - m).
    Counts no more spread than a Poisson give the top of `SIZE_RANGE`.
    """
    excess = float(((x - m) ** 2 - m).sum())
    if len(x) == 0 or excess <= 0:
        return SIZE_RANGE[1]
    return float(np.clip(float((m ** 2).sum()) / excess, *SIZE_RANGE))


class OppFit:
    """Everything learned from one History. See `OpportunityModel.fit`."""

    def __init__(self):
        self.ok = False
        self.why = ""
        self.team = {}      # stat -> (beta, off_now, def_now, league_mean)
        self.share = {}     # stat -> (beta, short_now, long_now, by_pos, overall)
        self.size = {}      # stat -> negative binomial size
        self.starter_share = float("nan")
        self.games = set()  # the history's game ids


class OpportunityModel(Projector):
    """Targets, carries and pass attempts. See the module docstring.

        OpportunityModel()                          no market numbers
        OpportunityModel("opp_market", lines=...)   with closing spread, total
        OpportunityModel("opp_median", single="median")

    `lines` is {game_id: (home_team, away_team, spread_line, total_line)}
    with the spread as nflverse gives it: positive when the HOME team is
    favoured. `single` is which one number it reports: the expected count,
    or the count's median.
    """
    uses_actives = True

    def __init__(self, name: str = "opportunity", lines: dict | None = None,
                 single: str = "mean"):
        if single not in SINGLE:
            raise ValueError(f"single must be one of {SINGLE}, not {single!r}")
        self.name = name
        self.lines = lines
        self.single = single
        self._last = (None, None)

    # -- the market numbers, guarded ---------------------------------------
    def _market(self, game_ids, teams, allowed: set) -> np.ndarray:
        """[[spread in this team's favour, total], ...], or no columns.

        Refuses a game that is not in `allowed`. The lines table holds
        every game there is, including ones not yet played when the week
        being projected was played. Both callers below pass the games they
        are entitled to, so this cannot fire as the code stands; it is
        there for the edit that asks for more.
        """
        if self.lines is None:
            return np.zeros((len(game_ids), 0))
        out = []
        for g, tm in zip(game_ids, teams):
            if g not in allowed:
                raise LeakError(
                    f"{self.name} asked for the line of {g}, which is "
                    f"neither in its history nor on its slate")
            if g not in self.lines:
                raise KeyError(f"no closing line on file for {g}")
            home, away, spread, total = self.lines[g]
            if tm not in (home, away):
                raise ValueError(f"{tm} did not play in {g} ({away} at {home})")
            spread, total = float(spread), float(total)
            if not (math.isfinite(spread) and math.isfinite(total)):
                raise ValueError(f"the closing line on file for {g} is not "
                                 f"a number")
            out.append((spread if tm == home else -spread, total))
        return np.array(out, dtype=float).reshape(len(out), 2)

    # -- learning from the history -----------------------------------------
    def fit(self, hist: History) -> OppFit:
        """Learn the two fits, the norms and the spreads from `hist` alone."""
        if self._last[0] is hist:
            return self._last[1]
        fit = OppFit()
        F = hist.frame          # a History keeps each player's games together, oldest first
        tg = (F.groupby(["game_id", "team", "opponent", "t"], as_index=False)
              [list(OPP_STATS)].sum().sort_values("t", kind="stable")
              .reset_index(drop=True))
        fit.games = set(tg.game_id)
        if len(tg) < MIN_FIT_ROWS:
            fit.why = (f"only {len(tg)} team-games in the history; needs "
                       f"{MIN_FIT_ROWS}")
            self._last = (hist, fit)
            return fit
        market = self._market(tg.game_id, tg.team, fit.games)

        team_pred = {}
        for stat in OPP_STATS:
            league = float(tg[stat].mean())
            off_before, off_now = leaning_average(tg[stat], tg.team,
                                                  HALF_LIFE_TEAM)
            def_before, def_now = leaning_average(tg[stat], tg.opponent,
                                                  HALF_LIFE_TEAM)
            X = np.column_stack([off_before.fillna(league),
                                 def_before.fillna(league), market])
            beta = ols(X, tg[stat].to_numpy())
            fit.team[stat] = (beta, off_now.to_dict(), def_now.to_dict(), league)
            team_pred[stat] = predict(beta, X)

        totals = tg[["game_id", "team"]].copy()
        for stat in OPP_STATS:
            totals[f"team_{stat}"] = tg[stat].to_numpy()
            totals[f"pred_{stat}"] = team_pred[stat]
        P = F.merge(totals, on=["game_id", "team"])    # keeps F's order
        for stat in SHARED:
            team_total = P[f"team_{stat}"]
            share = (P[stat] / team_total.where(team_total > 0)).fillna(0.0)
            short_before, short_now = leaning_average(share, P.player_id,
                                                      HALF_LIFE_SHORT)
            long_before, long_now = leaning_average(share, P.player_id,
                                                    HALF_LIFE_LONG)
            by_pos = share.groupby(P.position).mean().to_dict()
            overall = float(share.mean())
            norm = P.position.map(by_pos).fillna(overall)
            seen = short_before.notna().to_numpy()
            if int(seen.sum()) < MIN_FIT_ROWS:
                fit.why = (f"only {int(seen.sum())} player-games with an "
                           f"earlier game in the history; needs {MIN_FIT_ROWS}")
                self._last = (hist, fit)
                return fit
            X = np.column_stack([short_before[seen], long_before[seen],
                                 norm[seen]])
            beta = ols(X, share[seen].to_numpy())
            fit.share[stat] = (beta, short_now.to_dict(), long_now.to_dict(),
                               by_pos, overall)
            # The spread of a count round its mean, with the TEAM's volume as
            # the fit above puts it (in-sample), not as it turned out.
            m = (np.clip(predict(beta, X), 0.0, None)
                 * P[f"pred_{stat}"].to_numpy()[seen])
            x = P[stat].to_numpy()[seen]
            use = m > SIZE_MIN_MEAN
            fit.size[stat] = size_from(x[use], m[use])

        starts = P[P.qb_start]
        fit.starter_share = (float((starts.attempts / starts.team_attempts).mean())
                             if len(starts) else 1.0)
        # The spread of a STARTER's own attempts round what he would have
        # been given: wider than the team's, because starters leave games.
        fit.size["attempts"] = size_from(
            starts.attempts.to_numpy(dtype=float),
            fit.starter_share * starts.pred_attempts.to_numpy(dtype=float))
        fit.ok = True
        self._last = (hist, fit)
        return fit

    # -- projecting a slate --------------------------------------------------
    def means(self, hist: History, slate: pd.DataFrame) -> dict:
        """{stat: expected count for each slate row}. NaN where it says
        nothing: every stat when the history is too thin; targets or
        carries for a team none of whose slate players is given any share;
        pass attempts for everyone but the starter the slate names,
        whatever position he is listed at."""
        n = len(slate)
        missing = set(SLATE_COLS) - set(slate.columns)
        if missing:
            raise ValueError(f"the slate is missing {sorted(missing)}")
        flag = slate["starting_qb"]
        if not flag.isin([True, False]).all():
            raise ValueError("starting_qb must be True or False on every "
                             "slate row")
        starts = flag.to_numpy(dtype=bool)
        if slate.duplicated(["game_id", "team", "player_id"]).any():
            d = slate[slate.duplicated(["game_id", "team", "player_id"])].iloc[0]
            raise ValueError(f"{d['player_id']} is on the slate twice for "
                             f"{d['team']} in {d['game_id']}")
        key = list(zip(slate["game_id"], slate["team"]))
        team_key = pd.Series(key, dtype=object)
        named = pd.Series(starts.astype(float)).groupby(team_key).transform("sum")
        if (named > 1).any():
            two = sorted({k for k, v in zip(key, named) if v > 1})
            raise ValueError(f"more than one starting quarterback named for "
                             f"{two[0][1]} in {two[0][0]}")
        blank = {stat: np.full(n, np.nan) for stat in OPP_STATS}
        fit = self.fit(hist)
        if not fit.ok:
            return blank
        opponent = dict(zip(key, slate["opponent"]))
        teams = sorted(set(key))
        market = self._market([g for g, _ in teams], [t for _, t in teams],
                              fit.games | {g for g, _ in teams})
        volume = {}
        for stat in OPP_STATS:
            beta, off_now, def_now, league = fit.team[stat]
            X = np.column_stack([
                [off_now.get(t, league) for _, t in teams],
                [def_now.get(opponent[k], league) for k in teams], market])
            volume[stat] = dict(zip(teams, np.clip(predict(beta, X),
                                                   VOLUME_FLOOR, None)))

        pid = slate["player_id"].to_numpy(dtype=object)
        pos = slate["position"].to_numpy(dtype=object)
        out = dict(blank)
        for stat in SHARED:
            beta, short_now, long_now, by_pos, overall = fit.share[stat]
            norm = np.array([by_pos.get(p, overall) for p in pos], dtype=float)
            short = np.array([short_now.get(p, np.nan) for p in pid], dtype=float)
            long_ = np.array([long_now.get(p, np.nan) for p in pid], dtype=float)
            known = ~np.isnan(short)
            raw = norm.copy()               # no earlier game: his position's
            raw[known] = predict(beta, np.column_stack(
                [short[known], long_[known], norm[known]]))
            raw = np.clip(raw, 0.0, None)
            total = pd.Series(raw).groupby(team_key).transform("sum").to_numpy()
            share = np.divide(raw, total, out=np.full(n, np.nan), where=total > 0)
            out[stat] = share * np.array([volume[stat][k] for k in key])

        team_att = np.array([volume["attempts"][k] for k in key])
        out["attempts"] = np.where(starts, fit.starter_share * team_att, np.nan)
        return out

    def project(self, hist: History, slate: pd.DataFrame) -> Projection:
        mean = self.means(hist, slate)
        size = self.fit(hist).size
        return _Counts(mean, size, self.single)


class _Counts(Projection):
    """A negative-binomial count per slate row and stat."""

    def __init__(self, mean: dict, size: dict, single: str):
        self.mean, self.size, self.single = mean, size, single

    def _dist(self, i: int, stat: str):
        if stat not in self.mean:
            return None
        m = float(self.mean[stat][i])
        if math.isnan(m):
            return None
        r = self.size[stat]
        return r, r / (r + m)

    def point(self, i, stat):
        d = self._dist(i, stat)
        if d is None:
            return float("nan")
        if self.single == "mean":
            return float(self.mean[stat][i])
        return float(nbinom.ppf(0.5, *d))

    def p_over(self, i, stat, line):
        d = self._dist(i, stat)
        return float("nan") if d is None else float(
            nbinom.sf(math.floor(line), *d))


def expected_vs_actual(model: OpportunityModel, frame: pd.DataFrame,
                       weeks) -> pd.DataFrame:
    """One row per week, slate player and stat: the model's EXPECTED count
    and the VARIANCE it puts round it, beside what he did. Actives known.

    The harness grades a projection's single number and its chances. It
    does not see the spread the counts are given, so whether the expected
    counts are the right SIZE and the spread the right WIDTH is asked
    here. Rows where the model says nothing are left out.
    """
    out = []
    for t in weeks:
        hist = History(frame[frame.t < t], t)
        slate = slate_active(frame, hist)
        mean = model.means(hist, slate)
        size = model.fit(hist).size
        played = frame[frame.t == t].set_index(["game_id", "player_id"])
        at = pd.MultiIndex.from_arrays([slate["game_id"], slate["player_id"]])
        for stat in OPP_STATS:
            m = mean[stat]
            out.append(pd.DataFrame({
                "t": int(t), "stat": stat,
                "game_id": slate["game_id"].to_numpy(),
                "player_id": slate["player_id"].to_numpy(),
                "expected": m,
                "variance": m + m ** 2 / size.get(stat, np.nan),
                "actual": played[stat].reindex(at).to_numpy(dtype=float)}))
    rows = pd.concat(out, ignore_index=True)
    return rows[rows.expected.notna()].reset_index(drop=True)


def with_main_line(run, rows: pd.DataFrame, name: str) -> pd.DataFrame:
    """The players the calibration tables are about: each one with a MAIN
    stand-in line (actives known), his row of `expected_vs_actual` beside
    the harness's leg for him. `said` is `name`'s stated chance of the
    over and `over` whether it went over.

    Raises if the two do not line up player for player, result for result.
    """
    L = run.legs
    L = L[(L.version == "A") & (L.rung == MAIN) & L.stat.isin(OPP_STATS)
          & L[f"p_{name}"].notna()]
    j = L.merge(rows.rename(columns={"actual": "actual_again"}),
                on=["game_id", "player_id", "stat"], how="left",
                validate="one_to_one")
    if not (j.actual == j.actual_again).all():     # a missing row fails this too
        raise RuntimeError("the harness's legs and the model's expected "
                           "counts do not line up player for player")
    return pd.DataFrame({
        "stat": j.stat.to_numpy(), "game_id": j.game_id.to_numpy(),
        "player_id": j.player_id.to_numpy(),
        "line": j.line.to_numpy(dtype=float),
        "expected": j.expected.to_numpy(dtype=float),
        "actual": j.actual.to_numpy(dtype=float),
        "said": j[f"p_{name}"].to_numpy(dtype=float),
        "over": j["over"].astype(bool).to_numpy()})


def closing_lines(years) -> dict:
    """{game_id: (home_team, away_team, spread_line, total_line)} from the
    engine's play-by-play loader, regular season only, so only games that
    have been played. The spread is positive when the home team is
    favoured."""
    cols = ["game_id", "season_type", "home_team", "away_team", "spread_line",
            "total_line"]
    p = ff_data.load_pbp(list(years), columns=cols)
    g = p[p.season_type == "REG"].drop_duplicates("game_id")
    if g[["spread_line", "total_line"]].isna().any().any():
        raise ValueError("a regular-season game has no closing spread or total")
    return {a: (b, c, float(d), float(e)) for a, b, c, d, e in
            zip(g.game_id, g.home_team, g.away_team, g.spread_line,
                g.total_line)}
