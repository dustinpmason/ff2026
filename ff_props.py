"""
ff_props.py — threshold probability engine.

THE CORE IDEA
-------------
"Will Josh Allen throw for 250+ yards?" is the SAME computation whether you're
valuing a fantasy milestone bonus or pricing a sportsbook passing-yards prop.
One engine serves both:

  fantasy : expected bonus value = P(clear threshold) x bonus points
  betting : edge = P(model) - P(implied by the de-vigged market price)

WHAT THIS MODULE REFUSES TO DO
------------------------------
Return a bare percentage. NFL player samples are small — a full season is 17
games, and a mid-season read is 6-8. A point estimate off that sample carries a
confidence interval wide enough to swallow most apparent edges. Every estimate
here ships with a bootstrap interval and a sample-size verdict, and the headline
output is a CONFIDENCE TIER, not a false-precision number.

Usage
-----
    from ff_data import load_weekly
    from ff_props import player_series, threshold_prob, prop_edge, report

    wk  = load_weekly([2025, 2026])
    s   = player_series(wk, "Josh Allen", "passing_yards")
    est = threshold_prob(s, 250)
    print(report(est, "Josh Allen 250+ pass yds"))

    # with a market price
    print(prop_edge(est, over_odds=-115, under_odds=-105))
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import re

import numpy as np
import pandas as pd

from ff_data import ensure_deps, MIN_TEAMS_COMPLETE_WEEK, complete_weeks

# scipy is used for the normal-fit estimate. A fresh sandbox does not have it,
# and without this the failure lands on the first prop question rather than at
# bootstrap, which is a much worse place to discover it.
ensure_deps("scipy", quiet=True)

RNG = np.random.default_rng(20261029)

# Below this many games, treat any estimate as directional only.
MIN_GAMES_MEANINGFUL = 8
MIN_GAMES_CONFIDENT = 14


# ---------------------------------------------------------------------------
# Data shaping
# ---------------------------------------------------------------------------

def opportunity_column(stat: str) -> str | None:
    """The volume stat that DRIVES a production stat.

    Production is opportunity times efficiency. Threshold estimates built on
    production alone cannot see a role change — see usage_trend().
    """
    if stat.startswith("passing") or stat in ("completions",):
        return "attempts"
    if stat.startswith("rushing") or stat in ("carries",):
        return "carries"
    if stat.startswith("receiving") or stat in ("receptions",):
        return "targets"
    return None


def share_column(stat: str) -> str | None:
    """The SHARE counterpart of an opportunity column."""
    opp = opportunity_column(stat)
    return {"targets": "_tgt_share", "carries": "_carry_share",
            "attempts": "_att_share"}.get(opp) if opp else None


DERIVED_SHARE_COLS = (
    "_team_carries", "_team_targets", "_team_attempts", "_team_touches",
    "_carry_share", "_tgt_share", "_att_share", "_touches", "_touch_share",
)


def add_shares(weekly: pd.DataFrame) -> pd.DataFrame:
    """Attach each player's SHARE of his team's weekly opportunity.

    Raw counts conflate two different things: a shrinking role, and a team
    running fewer plays. A back whose carries fall from 18 to 9 because his
    team trailed all day has not lost his job — and treating that as a role
    change produces false alarms on exactly the players worth betting.

    Measured on 2026: three of seven count-based flags were team volume, not
    role. Jeanty's carries fell to 51% of baseline while his SHARE only fell to
    76%; Puka Nacua's targets fell to 57% while his share held at 83%.
    """
    df = weekly.copy()
    if "team" not in df.columns or "week" not in df.columns:
        return df

    # Idempotent: drop any columns a previous call added before recomputing.
    # Without this, a second call merges _team_carries into a frame that
    # already has it, pandas suffixes both to _x/_y, and the very next line
    # raises KeyError('_team_carries'). role_trend() and usage_trend() both
    # call add_shares() internally, so a caller who pre-computed shares — the
    # natural thing to do when looping over players — hit this every time.
    df = df.drop(columns=[c for c in DERIVED_SHARE_COLS if c in df.columns])

    tot = (df.groupby(["team", "week"])
             .agg(_team_carries=("carries", "sum"),
                  _team_targets=("targets", "sum"),
                  _team_attempts=("attempts", "sum"))
             .reset_index())
    df = df.merge(tot, on=["team", "week"], how="left")
    for num, den, out in [("carries", "_team_carries", "_carry_share"),
                          ("targets", "_team_targets", "_tgt_share"),
                          ("attempts", "_team_attempts", "_att_share")]:
        if num in df.columns:
            d = pd.to_numeric(df[den], errors="coerce").replace(0, np.nan)
            df[out] = pd.to_numeric(df[num], errors="coerce") / d

    # Combined touches, for OVERALL role rather than one stat's role. A back on
    # a trailing team loses carries and gains targets: his carry share falls
    # while his job is untouched. Touch share sees through that composition
    # shift; carry share alone does not.
    if "carries" in df.columns and "targets" in df.columns:
        df["_touches"] = (pd.to_numeric(df["carries"], errors="coerce").fillna(0)
                          + pd.to_numeric(df["targets"], errors="coerce").fillna(0))
        tt = (df.groupby(["team", "week"])["_touches"].sum()
                .rename("_team_touches").reset_index())
        df = df.merge(tt, on=["team", "week"], how="left")
        df["_touch_share"] = df["_touches"] / df["_team_touches"].replace(0, np.nan)
    return df


def role_trend(weekly: pd.DataFrame, player: str, window: int | None = None) -> UsageTrend:
    """OVERALL role trend, for questions about a player's total value rather
    than one stat — lineup decisions, the guillotine simulation, keeper calls.

    Uses combined touch share (carries + targets) for skill players, which is
    immune to the composition shift that breaks per-stat checks. Use
    usage_trend() instead for a specific prop: a receiving prop should care
    that a back's targets vanished even when his rushing job is untouched.
    """
    full = add_shares(weekly[weekly.season_type == "REG"]
                      if "season_type" in weekly.columns else weekly)
    d = full[full.player_display_name == player].sort_values(["season", "week"])
    if d.empty:
        return UsageTrend("_touch_share", 0, 0, 0, 1.0, "UNKNOWN", 0, 0)

    pos = d["position"].iloc[-1] if "position" in d.columns else "WR"
    col = "_att_share" if pos == "QB" else "_touch_share"
    raw = "attempts" if pos == "QB" else "_touches"
    d = d[pd.to_numeric(d[raw], errors="coerce").fillna(0) > 0]

    n = len(d)
    w = window or max(2, min(4, n // 3))
    if n < w + 2:
        return UsageTrend(col, 0, 0, 0, 1.0, "UNKNOWN", 0, 0)

    sv = pd.to_numeric(d[col], errors="coerce").fillna(0).values
    cv = pd.to_numeric(d[raw], errors="coerce").fillna(0).values
    s_rec, s_base = float(sv[-w:].mean()), float(sv[:-w].mean())
    c_rec, c_base = float(cv[-w:].mean()), float(cv[:-w].mean())
    s_ratio = s_rec / s_base if s_base > 0 else 1.0
    c_ratio = c_rec / c_base if c_base > 0 else 1.0

    if s_ratio < SHARE_COLLAPSE:
        verdict = "COLLAPSED"
    elif s_ratio > SHARE_EXPAND:
        verdict = "EXPANDED"
    elif c_ratio < COLLAPSE_RATIO:
        verdict = "GAME_SCRIPT"
    else:
        verdict = "STABLE"

    return UsageTrend(column=col.lstrip("_"), window=w, recent=c_rec, baseline=c_base,
                      ratio=c_ratio, verdict=verdict, per_opportunity=0.0,
                      expected_now=0.0, share_baseline=s_base, share_recent=s_rec,
                      share_ratio=s_ratio, team_volume_ratio=1.0, has_share=True)


@dataclass
class Decline:
    """WHEN a player's role changed, and what the data can say about why."""
    player: str
    onset_week: int | None
    before: float          # mean share before onset
    after: float           # mean share from onset on
    drop: float            # after / before
    missed_weeks: list[int] = field(default_factory=list)
    missed_before_onset: bool = False
    verdict: str = "UNKNOWN"
    search_hint: str = ""

    def describe(self) -> str:
        if self.onset_week is None:
            return f"{self.player}: no clear decline onset in the sample"
        L = [f"{self.player}: role changed at WEEK {self.onset_week} — "
             f"share {self.before:.1%} -> {self.after:.1%} ({self.drop:.0%})"]
        if self.missed_weeks:
            L.append(f"  missed weeks (not byes): {self.missed_weeks}")
        L.append(f"  {self.verdict}")
        if self.search_hint:
            L.append(f"  -> {self.search_hint}")
        return "\n".join(L)


def bye_weeks(weekly: pd.DataFrame,
              current_week: int | None = None) -> dict[str, int]:
    """Each team's bye, derived from the data: the week in which no player on
    that team recorded a game. Avoids needing a schedule feed to tell a bye
    apart from an absence."""
    df = weekly[weekly.season_type == "REG"] if "season_type" in weekly.columns else weekly

    # Only COMPLETE weeks can reveal a bye. A partially-played week (the data
    # refreshed mid-week, so only Thursday's game is in) makes every team that
    # has not played yet look like it is on bye — this produced "21 teams on
    # bye in Week 8" when only the TNF game had been recorded.
    complete = complete_weeks(df, current_week)
    if not complete:
        return {}
    df = df[df.week.isin(complete)]
    allw = set(complete)
    out: dict[str, int] = {}
    for team, g in df.groupby("team"):
        miss = sorted(allw - set(g.week.unique()))
        if len(miss) == 1:
            out[team] = miss[0]
    return out


def decline_onset(weekly: pd.DataFrame, player: str) -> Decline:
    """Locate WHEN a player's role changed, and say what the data can and
    cannot establish about the cause.

    WHY THIS IS NOT AN INJURY DETECTOR
    ----------------------------------
    PropLine's injury history begins 2026-10-18 and returns nothing at all for
    a decline that started earlier — verified empirically on Jeanty, whose
    carries began falling in Week 5 and whose injury-history query comes back
    with zero rows. ESPN's `status_since` is no better: it marks when the
    CURRENT designation began, refreshed weekly, not when the injury happened.

    So the data can establish WHEN. It cannot establish WHY. What it CAN do is
    turn an open-ended question into a targeted one: this returns the onset
    week so a news search has a date to aim at, and flags whether the player
    missed games just before — the one injury signal that IS in the data.
    """
    full = add_shares(weekly[weekly.season_type == "REG"]
                      if "season_type" in weekly.columns else weekly)
    d = full[full.player_display_name == player].sort_values("week")
    if len(d) < 4:
        return Decline(player, None, 0, 0, 1.0, verdict="too few games")

    pos = d["position"].iloc[-1] if "position" in d.columns else "WR"
    col = "_att_share" if pos == "QB" else "_touch_share"
    sv = pd.to_numeric(d[col], errors="coerce").fillna(0).values
    weeks = d.week.astype(int).tolist()

    # Change point: the split maximizing the fall in mean share.
    best_k, best_gap = None, 0.0
    for k in range(2, len(sv) - 1):
        gap = sv[:k].mean() - sv[k:].mean()
        if gap > best_gap:
            best_k, best_gap = k, gap
    if best_k is None or best_gap <= 0:
        return Decline(player, None, 0, 0, 1.0, verdict="no decline detected")

    before, after = float(sv[:best_k].mean()), float(sv[best_k:].mean())
    onset = weeks[best_k]

    team = d["team"].iloc[-1]
    bye = bye_weeks(full).get(team)
    played = set(weeks)
    missed = [w for w in range(1, max(weeks) + 1)
              if w not in played and w != bye]
    # Missed games ANYWHERE from just before the onset onward implicate an
    # injury — not only games missed strictly before it. Barkley's decline was
    # detected at Week 4 and he then missed Weeks 5 and 6; a strict
    # before-onset window skipped the obvious explanation.
    missed_before = any(w >= onset - 2 for w in missed)

    # Is this a STEP (a single week where things changed) or a GRADUAL slide?
    # They mean different things: a step points at a discrete event — a
    # benching, an injury, a personnel change. A steady slide points at
    # something progressive, and pinning it to one week is false precision.
    gradual = False
    if len(sv) >= 5:
        r = np.corrcoef(np.arange(len(sv)), sv)[0, 1]
        step_size = abs(sv[best_k] - sv[best_k - 1])
        gradual = r < -0.6 and step_size < (before - after)

    drop = after / before if before > 0 else 1.0
    if gradual:
        verdict = ("GRADUAL slide, not a single-week step — usage has eroded "
                   "steadily rather than changing at one point. That pattern "
                   "fits a progressive injury or a slow role erosion, not a "
                   "benching. Do not treat the onset week as a real event")
        hint = (f"look at {player}'s full-season trend and any recurring injury "
                f"designation rather than one week's news")
    elif drop >= SHARE_COLLAPSE:
        verdict = "decline is mild — not a role change by the share test"
        hint = ""
    elif missed_before:
        verdict = (f"MISSED WEEKS {missed} around the drop — an injury is the "
                   f"leading explanation")
        hint = (f"confirm with news for {player} around Week {onset}; if he is "
                f"healthy now, the sample understates him")
    else:
        verdict = ("played through it — no missed games before the drop, so "
                   "this is EITHER a demotion OR playing hurt. The data cannot "
                   "tell these apart")
        hint = (f"search news for '{player} injury' and '{player} snap share' "
                f"around Week {onset}, and check who absorbed the work")
    return Decline(player, onset, before, after, drop, missed, missed_before,
                   verdict, hint)


def attach_injury(trend: UsageTrend, player: str,
                  injuries: list[dict] | None) -> tuple[UsageTrend, str]:
    """Annotate a usage flag with the player's CURRENT injury status.

    This module cannot fetch injuries — the sandbox has no network access to
    PropLine, and the MCP tools belong to the session, not to Python. The
    caller must pass the list from `propline_get_injuries(sport_key=...)`.

    An injury does NOT cancel a usage flag. It explains it, and the
    implication differs sharply:
      - flagged AND still Out/Doubtful  -> the drop persists; do not expect
        the old baseline back this week.
      - flagged AND now cleared/absent from the report -> the drop may be
        behind him and the sample understates him. This is the case where a
        market that has not caught up is genuinely exploitable.
      - flagged and never injured -> a real depth-chart change.
    """
    if not injuries:
        return trend, "no injury data supplied — pull propline_get_injuries and pass it in"
    rec = next((r for r in injuries
                if str(r.get("player_name", "")).lower() == player.lower()), None)
    if rec is None:
        return trend, ("not on the current injury report — a usage change here is "
                       "more likely a real role change than an injury effect")
    status = rec.get("status", "?")
    note = f"{status} ({rec.get('injury_type', '?')}), since {rec.get('status_since', '?')}"
    if str(rec.get("status_code", "")).lower() in ("out", "doubtful", "injured_list"):
        return trend, f"{note} — usage drop likely persists while he is unavailable"
    return trend, f"{note} — may be limiting snaps; the drop could reverse on full health"


def player_series(weekly: pd.DataFrame,
                  player: str,
                  stat: str,
                  seasons: list[int] | None = None,
                  played_only: bool = True) -> pd.DataFrame:
    """Game log for one player and one stat, oldest first.

    Carries the opportunity column alongside the stat so usage_trend() can run.

    played_only drops games the player didn't appear in. For yardage stats a
    zero is almost always an absence, not a performance, and leaving them in
    biases every threshold estimate downward.
    """
    df = weekly[weekly.player_display_name == player]
    if df.empty:
        raise LookupError(f"no rows for player {player!r}")
    if "season_type" in df.columns:
        df = df[df.season_type == "REG"]
    if seasons:
        df = df[df.season.isin(seasons)]

    opp = opportunity_column(stat)
    shr = share_column(stat)

    # Shares need team totals, so compute them before filtering to one player.
    if shr and shr not in df.columns:
        full = add_shares(weekly[weekly.season_type == "REG"]
                          if "season_type" in weekly.columns else weekly)
        keep = ["player_display_name", "season", "week", shr,
                "_team_carries", "_team_targets", "_team_attempts"]
        df = df.merge(full[[c for c in keep if c in full.columns]],
                      on=["player_display_name", "season", "week"], how="left")

    if played_only and opp and opp in df.columns:
        df = df[pd.to_numeric(df[opp], errors="coerce").fillna(0) > 0]

    team_col = {"targets": "_team_targets", "carries": "_team_carries",
                "attempts": "_team_attempts"}.get(opp)
    cols = []
    for c in ["season", "week", "opponent_team", stat, opp, shr, team_col]:
        if c and c in df.columns and c not in cols:
            cols.append(c)
    out = df[cols].sort_values(["season", "week"]).reset_index(drop=True)
    # Record which column is the STAT. Without this, a caller that omits the
    # stat name has to guess from column order — and guessing broke the moment
    # the opportunity column was appended, silently scoring targets as yards.
    out.attrs["stat"] = stat
    out.attrs["opportunity"] = opp
    return out


# ---------------------------------------------------------------------------
# Estimation
# ---------------------------------------------------------------------------

@dataclass
class UsageTrend:
    """Whether a player's OPPORTUNITY has changed inside the sample window."""
    column: str
    window: int
    recent: float
    baseline: float
    ratio: float
    verdict: str              # COLLAPSED | EXPANDED | GAME_SCRIPT | STABLE | UNKNOWN
    per_opportunity: float    # production per unit of opportunity, full sample
    expected_now: float       # per_opportunity * recent usage
    share_baseline: float = 0.0
    share_recent: float = 0.0
    share_ratio: float = 1.0
    team_volume_ratio: float = 1.0
    has_share: bool = False
    # B88/A4. `team_volume_ratio` is 0.0 when the share column is present but
    # the team-total column is not, and `role_trend` HARDCODES it to 1.0 and
    # never measures it at all. The B84 conflict message printed it as a
    # measurement either way, so a reader saw "team volume 0%" (a team that
    # ran no plays) or "team volume 100%" directly before "he is a bigger
    # part of a smaller pie" — which 100% contradicts. This flag says whether
    # the number was measured, so the messages can leave it out when it
    # wasn't rather than asserting it.
    has_team_volume: bool = False

    @property
    def flagged(self) -> bool:
        """Only a genuine ROLE change blocks a bet. GAME_SCRIPT is a softer
        signal — the player's share of his offense is intact and team volume
        reverts more readily than a depth-chart position does."""
        return self.verdict in ("COLLAPSED", "EXPANDED")

    @property
    def direction_conflict(self) -> bool:
        """SHARE and COUNT point opposite ways, so the production direction
        is not determined by the verdict.

        B84. `verdict` is decided on SHARE — deliberately, because a count
        drop that leaves share intact is the team running fewer plays, and
        using count as primary misclassified Corum's real promotion. That is
        right for "did his role change?". But a THRESHOLD PROP is priced on
        production, and production follows OPPORTUNITY COUNT. When team
        volume moves, the two diverge: a player can take a bigger slice of a
        smaller pie (share up, count down) and the model built on his old
        count then OVERSTATES him, supporting an under — while the verdict
        says EXPANDED and the old mapping claimed the opposite.

        Measured over 264 flagged role changes in the 2025-26 pool: **21
        have share and count pointing opposite ways, and the verdict-derived
        direction was wrong on all 21.** Of the 243 where they agree, only 2
        disagreed, both at the boundary where `expected_now` sits within a
        point of the sample mean. So this test fixes 21 of 23 known
        disagreements and costs nothing correct. `team_volume_ratio` on the
        conflicting set runs 0.42 to 1.98, confirming the divergence is
        team-volume driven rather than noise.

        **Re-derive these numbers with
        `measurements/b84_direction_conflict.py`.** They were originally
        written here as prose with nothing in the repo able to reproduce
        them, which is D16's shape — a measurement recorded as a standing
        claim. The script is the artefact; if it stops reproducing these
        figures, this docstring is what is wrong.
        """
        if not self.flagged or not self.has_share:
            return False
        return ((self.share_ratio > 1.0 and self.ratio < 1.0)
                or (self.share_ratio < 1.0 and self.ratio > 1.0))

    @property
    def share_measured(self) -> bool:
        """Was `share_ratio` measured, or forced to 1.0?

        B88/A6. `usage_trend` sets `share_ratio = 1.0` both when `has_share`
        is False and when `has_share` is True but `share_baseline` is 0 —
        reachable when the share merge leaves NaN baseline weeks that
        `fillna(0)` turns into zeros. The role-change messages printed it
        regardless, so a reader saw `"COLLAPSED, share 100%"`, which is
        self-contradictory against SHARE_COLLAPSE = 0.65 and reads as
        exactly the GAME_SCRIPT diagnosis ("count fell, share held") this
        mechanism exists to distinguish from a real collapse.
        """
        return bool(self.has_share and self.share_baseline > 0)

    @property
    def count_flat(self) -> bool:
        """Opportunity COUNT did not move, so there is no staleness in it.

        B88/A5. `direction_conflict` used strict inequalities, so a count
        ratio of EXACTLY 1.0 was neither above nor below and reported no
        conflict — and `supports()` then answered confidently off the share
        verdict. Measured on an integer log (baseline targets [8,4,6,5,7]
        mean 6.0, recent [5,7] mean 6.0, team targets doubling): ratio 1.0,
        share_ratio 0.496, verdict COLLAPSED, `supports("UNDER")` -> True,
        while `expected_now` equals the sample mean EXACTLY. By B84's own
        principle — production follows opportunity count — there is no
        staleness in either direction, so a confident answer is wrong. At
        ratio 1.0001 the same state already returned None, and this module
        retired LONGSHOT_P for precisely that kind of discontinuity.
        """
        if not self.flagged or not self.has_share:
            return False
        return self.ratio == 1.0

    def supports(self, side: str | None) -> bool | None:
        """Does this role change run WITH the side being bet, or against it?

        The model is built on the old role, so a COLLAPSE means it overstates
        the player — which makes the true UNDER probability higher than the
        model says, supporting an under and refusing an over. An EXPANSION is
        the same logic reversed.

        Returns None when the direction cannot be established, and a caller
        must not guess from it. THREE separate reasons it can be None, and a
        caller that needs to explain itself must tell them apart:
          * `side` is not OVER/UNDER — nothing to compare against
          * not `flagged` — no role change, so no direction to have
          * `direction_conflict` — share and count disagree (B84)

        **B80: this lived as a duplicated two-line expression in
        `prop_edge` and `boost_verdict`, and the second copy had been
        written WITHOUT the direction test at all** — it vetoed every role
        change and asserted the direction in prose. It cost the best-priced
        leg on a live board, a Justice Hill over whose targets had gone
        2.2 -> 6.0, an EXPANSION that supported the bet. One home, so the two
        readings cannot drift again.
        """
        if side not in ("OVER", "UNDER") or not self.flagged:
            return None
        if self.direction_conflict or self.count_flat:
            return None
        return ((self.verdict == "COLLAPSED" and side == "UNDER")
                or (self.verdict == "EXPANDED" and side == "OVER"))

    @property
    def soft_flagged(self) -> bool:
        return self.verdict == "GAME_SCRIPT"

    def describe(self) -> str:
        if self.verdict == "UNKNOWN":
            return "  usage      : not enough games to judge role change"
        arrow = {"COLLAPSED": "DOWN", "EXPANDED": "UP",
                 "GAME_SCRIPT": "DOWN", "STABLE": "stable"}[self.verdict]
        s = (f"  usage      : {self.column} {self.baseline:.1f} -> {self.recent:.1f} "
             f"over last {self.window} ({self.ratio:.0%}, {arrow})")
        # B88/A6+A4. Print share only when it was MEASURED, and team volume
        # only when it was measured — both are forced to 1.0 in states this
        # class cannot distinguish from a real reading, and printing them
        # regardless produced "COLLAPSED, share 100%" and "team volume 0%".
        if self.share_measured:
            s += (f"\n  share      : {self.share_baseline:.1%} -> {self.share_recent:.1%} "
                  f"({self.share_ratio:.0%} of baseline)")
            s += (f"; team volume at {self.team_volume_ratio:.0%}"
                  if self.has_team_volume else
                  "; team volume not measured")
        elif self.has_share:
            s += ("\n  share      : baseline is zero, so no share ratio could "
                  "be computed — the verdict below is count-derived")
        if self.flagged and (self.direction_conflict or self.count_flat):
            # B88/A8. describe() asserted "the sample describes a role this
            # player no longer has" for every flagged trend, including the
            # states supports() refuses to answer — so report() printed a
            # confident role-change narrative over an undetermined one.
            # NOTE this function builds with `s +=`, not a list; a first cut
            # of this patch used L.append() and would have raised NameError
            # on exactly the state it was added for, which no test covered.
            s += ("\n  ! which SIDE this helps is NOT established: "
                  + ("the opportunity count did not move"
                     if self.count_flat else
                     "share and count point opposite ways"))
        if self.verdict == "GAME_SCRIPT":
            s += ("\n  ~ GAME SCRIPT, not a role change. The raw count fell but his "
                  "SHARE of the offense held up — the team ran fewer plays. Team "
                  "volume reverts more readily than a depth-chart spot, so treat "
                  "this as added uncertainty rather than a changed role.")
        elif self.flagged:
            s += (f"\n  ! ROLE CHANGE. At current usage, expected output is "
                  f"~{self.expected_now:.1f} — the sample describes a role this "
                  f"player no longer has.")
        return s


# Role-change thresholds. Deliberately wide: a 20-30% swing in targets is
# ordinary game-to-game noise, a 50% one is a different job.
COLLAPSE_RATIO = 0.60

# RETIRED as a switch, kept as a label. There used to be a threshold here:
# below 0.25 implied, de-vig with Shin; above it, multiplicative. Measured
# across the full price range, that was wrong twice over.
#
# First, Shin is a strict GENERALIZATION of multiplicative — the two are
# identical at even money (-110/-110 -> 50.00% both ways) and diverge smoothly
# from there. There is no region where multiplicative is the better model, so
# there is nothing for a threshold to protect.
#
# Second, the cliff discarded most of the correction where it mattered. The
# shin-minus-multiplicative gap is already -1.02 pts at +245 and -1.04 at
# +270, against -1.19 at +400 — nearly full size. Both of those sat on the
# multiplicative side of a 0.25 gate, and short-priced TD legs are exactly
# what fills a 3-leg boost at +300. Worse, the gate was discontinuous: 24.9%
# implied and 25.1% implied got answers 1.3 pts apart.
#
# Shin is now the default for every market. `LONGSHOT_P` only labels a price
# as a longshot in reporting.
LONGSHOT_P = 0.25
EXPAND_RATIO = 1.60

# Share is a cleaner signal than raw count — it already divides out team
# volume — so it earns tighter thresholds. These are judgment calls, validated
# against 2026 cases: they must keep Waller (share 51%), Barkley (35%) and
# McLaurin (43%) as role changes; reclassify Jeanty (76%), Nacua (83%) and
# Harvey (72%) as game script; and keep Corum (155%) as a real expansion.
SHARE_COLLAPSE = 0.65
SHARE_EXPAND = 1.45


def usage_trend(log: pd.DataFrame, stat: str) -> UsageTrend:
    """Detect a role change by comparing recent opportunity against the prior
    baseline — NOT against the whole sample, which includes the recent games
    and dilutes the very signal we're looking for.

    This exists because threshold_prob() weights OUTCOMES. A player whose
    targets collapsed but who broke one long play scores well on every
    estimator, recency-weighted included, because recency weighting rewards the
    fluke. Opportunity is the thing that actually carries forward.
    """
    opp = opportunity_column(stat)
    nil = UsageTrend(opp or "?", 0, 0, 0, 1.0, "UNKNOWN", 0, 0)
    if not opp or opp not in log.columns:
        return nil

    o = pd.to_numeric(log[opp], errors="coerce").fillna(0).values.astype(float)
    y = pd.to_numeric(log[stat], errors="coerce").fillna(0).values.astype(float)
    n = len(o)

    # Window scales with sample: 2 games on a short sample, up to 4 on a long
    # one. A fixed 3 was tested and missed a real collapse on a 6-game sample.
    window = max(2, min(4, n // 3))
    if n < window + 2:
        return nil

    recent = float(o[-window:].mean())
    baseline = float(o[:-window].mean())
    if baseline <= 0:
        return nil

    ratio = recent / baseline

    # Share-based check. A count drop that leaves SHARE intact is the team
    # running fewer plays, not the player losing his role.
    shr = share_column(stat)
    has_share = bool(shr) and shr in log.columns and log[shr].notna().any()
    has_tv = False
    s_base = s_rec = s_ratio = tv_ratio = 0.0
    if has_share:
        sv = pd.to_numeric(log[shr], errors="coerce").fillna(0).values.astype(float)
        s_rec, s_base = float(sv[-window:].mean()), float(sv[:-window].mean())
        s_ratio = s_rec / s_base if s_base > 0 else 1.0
        tcol = {"targets": "_team_targets", "carries": "_team_carries",
                "attempts": "_team_attempts"}.get(opp)
        if tcol and tcol in log.columns:
            tvv = pd.to_numeric(log[tcol], errors="coerce").fillna(0).values.astype(float)
            tb = float(tvv[:-window].mean())
            # B88/A4. tb <= 0 also means unmeasured, not "volume held at
            # 100%" — a fabricated 1.0 is what let the conflict message
            # assert a team-volume figure nobody read.
            has_tv = tb > 0
            tv_ratio = float(tvv[-window:].mean()) / tb if tb > 0 else 1.0

    # SHARE is the primary signal when available; the count only decides
    # whether a game-script note is warranted. Using the count as primary and
    # share as a veto misclassified Corum, whose carry share rose 29% -> 45%
    # (a real promotion) but sat just under the count threshold.
    if has_share and s_base > 0:
        if s_ratio < SHARE_COLLAPSE:
            verdict = "COLLAPSED"
        elif s_ratio > SHARE_EXPAND:
            verdict = "EXPANDED"
        elif ratio < COLLAPSE_RATIO:
            verdict = "GAME_SCRIPT"      # count fell, share held
        else:
            verdict = "STABLE"
    else:
        verdict = ("COLLAPSED" if ratio < COLLAPSE_RATIO
                   else "EXPANDED" if ratio > EXPAND_RATIO
                   else "STABLE")

    per_opp = float(y.sum() / o.sum()) if o.sum() > 0 else 0.0
    return UsageTrend(column=opp, window=window, recent=recent, baseline=baseline,
                      ratio=ratio, verdict=verdict, per_opportunity=per_opp,
                      expected_now=per_opp * recent,
                      share_baseline=s_base, share_recent=s_rec,
                      share_ratio=s_ratio if has_share else 1.0,
                      team_volume_ratio=tv_ratio if has_share else 1.0,
                      has_team_volume=bool(has_share and has_tv),
                      has_share=has_share)


@dataclass
class Estimate:
    stat: str
    line: float
    n: int
    empirical: float          # share of games clearing the line
    parametric: float         # normal fit P(X >= line)
    recency: float            # exponentially recency-weighted share
    blended: float            # the number to actually use
    ci_low: float
    ci_high: float
    mean: float
    sd: float
    hits: int
    usage: UsageTrend | None = None

    @property
    def role_changed(self) -> bool:
        return self.usage is not None and self.usage.flagged

    @property
    def ci_width(self) -> float:
        return self.ci_high - self.ci_low

    @property
    def sample_verdict(self) -> str:
        if self.n < MIN_GAMES_MEANINGFUL:
            return "THIN"
        if self.n < MIN_GAMES_CONFIDENT:
            return "MODERATE"
        return "ADEQUATE"


def threshold_prob(log: pd.DataFrame,
                   line: float,
                   stat: str | None = None,
                   half_life: float = 6.0,
                   n_boot: int = 10_000) -> Estimate:
    """P(stat >= line) from a game log, three ways, with a bootstrap interval.

    half_life — games. Controls the recency weighting. 6 means a game six weeks
    back counts half as much as the most recent one.
    """
    # Resolve the stat column. Prefer what player_series recorded; otherwise
    # take the last column that is neither metadata nor an opportunity column.
    # Never just take columns[-1] — that is the opportunity column now.
    if stat is None:
        stat = log.attrs.get("stat")
    if stat is None:
        meta = {"season", "week", "opponent_team"}
        opps = {"attempts", "carries", "targets"}
        cands = [c for c in log.columns if c not in meta and c not in opps]
        stat = cands[-1] if cands else log.columns[-1]
    if stat not in log.columns:
        raise KeyError(f"stat {stat!r} not in log columns {list(log.columns)}")

    x = pd.to_numeric(log[stat], errors="coerce").dropna().values.astype(float)
    n = len(x)
    if n < 3:
        raise ValueError(f"only {n} games — not enough to estimate anything")

    hits = int((x >= line).sum())
    emp = hits / n

    mu, sd = float(x.mean()), float(x.std(ddof=1)) if n > 1 else 0.0
    if sd > 0:
        from scipy import stats as st
        para = float(1 - st.norm.cdf(line, mu, sd))
    else:
        para = float(x[0] >= line)

    # recency weighting: most recent game has weight 1, decaying backwards
    age = np.arange(n - 1, -1, -1, dtype=float)
    w = 0.5 ** (age / half_life)
    rec = float(((x >= line) * w).sum() / w.sum())

    # Blend. Empirical is unbiased but coarse on small n; the normal fit
    # borrows strength from the shape; recency catches genuine role change.
    blended = float(np.clip(0.45 * emp + 0.25 * para + 0.30 * rec, 0.01, 0.99))

    boot = np.array([(RNG.choice(x, n, replace=True) >= line).mean()
                     for _ in range(n_boot)])
    lo, hi = np.percentile(boot, [2.5, 97.5])

    return Estimate(stat=stat, line=line, n=n, empirical=emp, parametric=para,
                    recency=rec, blended=blended, ci_low=float(lo),
                    ci_high=float(hi), mean=mu, sd=sd, hits=hits,
                    usage=usage_trend(log, stat))


# ---------------------------------------------------------------------------
# Fantasy side — what is a bonus actually worth?
# ---------------------------------------------------------------------------

def bonus_value(est: Estimate, bonus_points: float) -> float:
    """Expected points per game from a threshold bonus FantasyPros ignores."""
    return est.blended * bonus_points


# ---------------------------------------------------------------------------
# Betting side — odds, de-vig, edge
# ---------------------------------------------------------------------------

def american_to_prob(odds: float) -> float:
    """Implied probability from American odds, vig included."""
    return 100.0 / (odds + 100.0) if odds > 0 else -odds / (-odds + 100.0)


def american_to_decimal(odds: float) -> float:
    return 1 + (odds / 100.0 if odds > 0 else 100.0 / -odds)


MUTUALLY_EXCLUSIVE_MARKETS = {"player_1st_td", "player_last_td",
                              "team_first_td_scorer", "first_team_to_score"}

NO_SCORER_NAMES = {"no touchdown scorer", "no td scorer", "no scorer",
                   "none", "no touchdown"}

# Overround bounds for a mutually exclusive field. Measured on live First TD
# boards, 2026-11-05: complete fields ran DraftKings 1.5421 (54.2%) and
# bovada 1.5655 (56.6%); short fields ran BetMGM 1.4124 (41.2%, 23 outcomes)
# and Kalshi 1.3501 (35.0%, 28). So a real field — complete or short —
# topped out near 57%. A dict keyed on player name alone, which pulls
# milestone rungs into the field, produced 2.9756 (198%).
#
# B88. These were ONE constant doing TWO jobs, and that is why both halves
# were wrong. `MAX_PLAUSIBLE_OVERROUND = 1.00` was documented as "a
# DIAGNOSTIC threshold: it decides which sentence the refusal prints, never
# whether the field is refused" — and it was only ever consulted INSIDE the
# `not has_no_scorer` branch. So:
#   * A polluted field that DOES carry a no-scorer row had no upper bound at
#     all. Measured: the real DraftKings First TD board plus rung pollution
#     gives booksum 3.0326 over 14 outcomes, and devig_field RETURNED it,
#     tagged `method: shin, complete: True`, turning a 55.6% implied scorer
#     into 24.4% "fair". Every player divided by about three, which is
#     verbatim the failure this module's own docstring warns about. The real
#     board carries "No Touchdown Scorer", so this is the LIKELY path, not an
#     edge case.
#   * The diagnosis fired at booksum > 2.0 while its own comment claimed the
#     threshold was 1.0, leaving the 1.0-2.0 band — where a lightly polluted
#     field actually lands — telling the caller a booksum of 1.7151 was "too
#     low by whatever is missing" when 71% overround is well above anything
#     measured.
# Split into a refusal line and a diagnostic ceiling, which is what the two
# jobs needed all along.
MAX_OBSERVED_OVERROUND = 0.57     # diagnosis only: above this, suspect extra
                                  # outcomes rather than a fat margin
BOOKSUM_REFUSE_ABOVE = 2.00       # refusal: no book charges 100% margin on a
                                  # mutually exclusive field, so this can only
                                  # be crossed by pollution
MAX_PLAUSIBLE_OVERROUND = MAX_OBSERVED_OVERROUND   # back-compat alias


def devig_field(prices: dict, *, market: str, method: str = "shin",
                require_complete: bool = True) -> dict:
    """De-vig a whole MUTUALLY EXCLUSIVE field at once (first TD scorer).

    `prices` is {outcome name: American odds}. Returns a dict with `fair`
    ({name: probability}), `booksum`, `overround`, `n`, `z` and `method`.

    **This is only valid where exactly one outcome can win.** First TD
    scorer qualifies; anytime TD does NOT, and passing it is refused —
    several players score in a game, so those prices sum to the expected
    number of scorers, not to 1. Normalising them to 1 would divide every
    probability by roughly three and look entirely plausible doing it. Use
    the two-sided path for anytime TD: price from your book, fair
    probability from an unfiltered `get_event_ev(devig="shin")`.

    **An incomplete field is refused too, and this is the subtle one.**
    Measured on event 87238, 2026-11-05: DraftKings listed 32 outcomes
    including "No Touchdown Scorer" (+6000) and both D/STs, booksum
    **1.5535**. BetMGM listed 23, with no No-Scorer and no defences,
    booksum **1.4109**. The nine outcomes DK carried and BetMGM did not
    sum to **0.1788** — almost the entire gap. So BetMGM's apparently
    leaner market is a SHORTER FIELD, not a better one, and dividing its
    23 prices by 1.4109 instead of the true ~1.55 inflates every player by
    about 10%, in the direction that makes a bet look good.

    So a field without a no-scorer outcome is refused by default. Pass
    `require_complete=False` only to inspect one deliberately, and never
    quote the result as a probability.
    """
    # B70. `market` was keyword-OPTIONAL and defaulted to None, so this
    # refusal — the one the docstring above spends a paragraph on — was
    # opt-in. `devig_field(anytime_td_board)` with no market argument ran
    # the full Shin normalisation and returned a 58% implied scorer at 27%
    # fair, tagged `method: shin, complete: True`, no warning. Exactly the
    # "divide every probability by roughly three and look entirely
    # plausible doing it" failure described above, reachable by OMITTING an
    # argument. Every caller in the repo passed `market` explicitly, which
    # is precisely why 464 checks never exercised the default: a
    # parameter's default is a code path, and no test omitted it.
    # `market` is now required.
    if market not in MUTUALLY_EXCLUSIVE_MARKETS:
        raise ValueError(
            f"{market!r} is not a mutually exclusive field, so its prices do "
            f"not sum to 1 and cannot be de-vigged as one. Anytime TD is "
            f"the usual mistake: several players score, so the field sums "
            f"to the expected NUMBER of scorers. Use a two-sided fair "
            f"line per player instead (get_event_ev, unfiltered, shin). "
            f"Mutually exclusive fields: {sorted(MUTUALLY_EXCLUSIVE_MARKETS)}")
    clean = {k: _num(v) for k, v in (prices or {}).items()}
    clean = {k: v for k, v in clean.items() if v is not None}
    if len(clean) < 2:
        raise ValueError(f"a field needs at least 2 priced outcomes, got "
                         f"{len(clean)}")
    r = {k: american_to_prob(v) for k, v in clean.items()}
    booksum = sum(r.values())
    has_no_scorer = any(str(k).strip().lower() in NO_SCORER_NAMES
                        for k in clean)
    # B71. The completeness guard below checks a NAME and never the
    # arithmetic, so a field carrying "No Touchdown Scorer" was reported
    # `complete: True` however short it was. A booksum BELOW 1.0 is
    # arithmetic proof of incompleteness on a mutually exclusive field — the
    # true outcomes sum to 1 before any margin, so a book quoting less than
    # 1.0 is missing outcomes no matter what it is named. Unchecked, Shin's
    # bisection collapses to z=0 and the field is scaled UP: three prices
    # summing to 0.65 returned a 20% outcome at 30.8%, i.e. manufactured
    # edge, while reporting `method: shin, complete: True`. That is the
    # flattering direction, which is the one that costs money.
    if booksum < 1.0:
        raise ValueError(
            f"this field's prices sum to {booksum:.4f}, BELOW 1.0. A "
            f"mutually exclusive field sums to 1 before any margin, so a "
            f"booksum under 1 is proof that outcomes are missing — "
            f"de-vigging it would scale every price UP and manufacture "
            f"edge. Got {len(clean)} outcomes"
            + (" including a no-scorer entry, which is why the name check "
               "alone passed it" if has_no_scorer else "")
            + ". Pull the complete field before quoting anything from it.")
    # B88. The UPPER bound, and it is deliberately outside the name check.
    # The lower bound above and the diagnosis below were both gated on
    # whether a no-scorer row was PRESENT, so a polluted field carrying one
    # — which the real DraftKings board does — had no ceiling at all and was
    # returned as fair probabilities. `require_complete` does not gate this
    # either: it governs whether an INCOMPLETE field may be inspected, and a
    # booksum this high is not incompleteness, it is extra outcomes. There is
    # no inspecting your way out of that.
    if booksum > BOOKSUM_REFUSE_ABOVE:
        raise ValueError(
            f"this field's prices sum to {booksum:.4f} over {len(clean)} "
            f"outcomes, above the {BOOKSUM_REFUSE_ABOVE:.2f} ceiling. No book "
            f"charges {BOOKSUM_REFUSE_ABOVE - 1:.0%} margin on a mutually "
            f"exclusive field — real boards measured 1.35 to 1.57 — so this "
            f"is EXTRA OUTCOMES, not a wide market, and de-vigging it would "
            f"divide every probability by roughly {booksum:.1f}. The usual "
            f"cause is a dict keyed on player name alone, so alternate lines "
            f"and milestone rungs ('100+ Rushing Yards') joined the main "
            f"field; rebuild it from flatten_odds with the LINE in the key."
            + (" Note a no-scorer row is present, so neither the name check "
               "nor require_complete would have caught this."
               if has_no_scorer else ""))
    if require_complete and not has_no_scorer:
        # B85. This used to assert the booksum "is too low by whatever is
        # missing" unconditionally. That is the right diagnosis for the case
        # it was written for — a short First TD field, booksum ~1.4 against a
        # complete ~1.55 — but the no-scorer check fires BEFORE anything
        # reasons about direction, so the prose was printed over whatever
        # number arrived. Observed live: a hand-built dict keyed on name
        # alone pulled milestone rungs into the field, giving 13 outcomes at
        # booksum 2.9756, and the refusal called 2.98 "too low". The caller
        # is already confused at that point; the message must not add to it.
        # B88/A2. This compared against `1.0 + MAX_PLAUSIBLE_OVERROUND`,
        # i.e. a booksum of 2.0, while this very comment claimed the
        # threshold was 1.0. So the whole 1.0-2.0 band — where a LIGHTLY
        # polluted field actually lands — still got the "too low" sentence:
        # a booksum of 1.7151 is 71% overround against the 57% maximum ever
        # measured, and the refusal called it too low. One constant was
        # serving as both a refusal line and a diagnostic ceiling, and that
        # conflation produced both halves of the bug. The ceiling is the
        # measured one; the refusal line lives above, outside the name check.
        if booksum > 1.0 + MAX_OBSERVED_OVERROUND:
            diag = (f"and its booksum ({booksum:.4f}) is TOO HIGH for a "
                    f"field of {len(clean)} outcomes — above the "
                    f"{MAX_OBSERVED_OVERROUND:.0%} margin ever measured on a "
                    f"real board, which means extra outcomes are in here, not "
                    f"that outcomes are missing. The usual cause is a dict "
                    f"keyed on name alone, so alternate lines and milestone "
                    f"rungs ('100+ Rushing Yards') joined the main field. "
                    f"Rebuild it from flatten_odds with the line in the key")
        else:
            diag = (f"so it is INCOMPLETE and its booksum ({booksum:.4f}) is "
                    f"too low by whatever is missing. De-vigging it would "
                    f"inflate every outcome. Pull the book that carries the "
                    f"full field (DraftKings listed 'No Touchdown Scorer' "
                    f"where BetMGM listed nothing)")
        raise ValueError(
            f"this field has {len(clean)} outcomes and no no-scorer entry, "
            f"{diag}, or pass require_complete=False to inspect it without "
            f"quoting it.")

    if method == "auto":
        method = "shin"
    if method == "multiplicative":
        fair = {k: v / booksum for k, v in r.items()}
        return {"fair": fair, "booksum": booksum, "overround": booksum - 1.0,
                "n": len(clean), "z": 0.0, "method": "multiplicative",
                "complete": has_no_scorer}
    if method != "shin":
        raise ValueError(f"unknown devig method {method!r}")

    # Same Shin inversion as the two-way `devig`, over N outcomes:
    # p_i = (sqrt(z^2 + 4(1-z) r_i^2 / B) - z) / (2(1-z)), z set so sum == 1.
    def fair_at(z: float) -> dict:
        if z <= 1e-12:
            return {k: v / booksum for k, v in r.items()}
        return {k: (math.sqrt(z * z + 4.0 * (1.0 - z) * v * v / booksum) - z)
                   / (2.0 * (1.0 - z)) for k, v in r.items()}

    lo, hi = 0.0, 0.95
    for _ in range(100):
        mid = (lo + hi) / 2.0
        if sum(fair_at(mid).values()) > 1.0:
            lo = mid
        else:
            hi = mid
    z = (lo + hi) / 2.0
    fair = fair_at(z)
    s = sum(fair.values())
    # B71b. `fair_at` falls back to plain proportional scaling when z
    # collapses, so reporting "shin" there names a method that did not run.
    # The booksum guard above now catches the case that drove z to 0, but
    # the label should state what was actually computed either way — a
    # downstream reader comparing methods must not be told shin when the
    # numbers are multiplicative.
    return {"fair": {k: v / s for k, v in fair.items()}, "booksum": booksum,
            "overround": booksum - 1.0, "n": len(clean), "z": z,
            "method": "shin" if z > 1e-12 else "multiplicative (shin z "
                                               "collapsed to 0)",
            "complete": has_no_scorer}


def devig(over_odds: float, under_odds: float,
          method: str = "auto") -> tuple[float, float, float]:
    """Remove the book's margin from a two-way market.

    Returns (fair P(over), fair P(under), hold). Hold is the book's take —
    anything much above ~5% on a player prop is an expensive market to beat.

    `method`:
      "multiplicative" — scale both sides proportionally. Correct when the
          margin is spread evenly, which it roughly is on a 50/50 line.
      "shin"          — Shin's model, which loads the overround onto the
          longshot. Books price longshots with a fatter margin (the
          favourite-longshot bias), so proportional scaling SYSTEMATICALLY
          OVERSTATES a longshot's fair probability. On an anytime-TD leg
          priced +450 that error runs several points in the direction that
          makes a bad bet look good — and TD legs are boost-parlay staples.
      "auto"          — accepted for compatibility; resolves to shin.

    Shin is the DEFAULT for every market, not just longshots. It is identical
    to multiplicative at even money and strictly better-founded away from it,
    so there is no price at which multiplicative is preferable. Pass
    "multiplicative" explicitly only to compare the two.

    Shin assumes a fraction z of volume comes from insiders and solves for the
    true probabilities that would produce the observed prices. It needs both
    sides: a one-sided quote carries no information about how the margin is
    distributed.
    """
    po, pu = american_to_prob(over_odds), american_to_prob(under_odds)
    total = po + pu
    hold = total - 1.0

    if method == "auto":
        method = "shin"
    if method == "multiplicative":
        return po / total, pu / total, hold
    if method != "shin":
        raise ValueError(f"unknown devig method {method!r}; "
                         f"expected 'multiplicative', 'shin' or 'auto'")

    # Shin: p_i = (sqrt(z^2 + 4(1-z) r_i^2 / B) - z) / (2(1-z)), with z chosen
    # so the fair probabilities sum to 1. Solved numerically — a closed form
    # exists for two outcomes but is easy to get subtly wrong, and this is
    # microseconds either way.
    r = (po, pu)

    def fair(z: float) -> tuple[float, float]:
        if z <= 1e-12:
            return po / total, pu / total
        return tuple((math.sqrt(z * z + 4.0 * (1.0 - z) * ri * ri / total) - z)
                     / (2.0 * (1.0 - z)) for ri in r)

    lo, hi = 0.0, min(0.9, max(0.0, hold * 4.0) + 0.5)
    for _ in range(80):
        mid = (lo + hi) / 2.0
        if sum(fair(mid)) > 1.0:
            lo = mid
        else:
            hi = mid
    fo, fu = fair((lo + hi) / 2.0)
    s = fo + fu
    return fo / s, fu / s, hold


@dataclass
class Edge:
    side: str
    model_p: float
    fair_p: float
    edge: float
    ev_per_dollar: float
    hold: float
    kelly: float
    tier: str
    reasoning: str
    fair_source: str = "unspecified"
    devig_method: str = "unspecified"


# B87. The widest and narrowest a single side of a TWO-SIDED prop quote can
# be before a hold computed from it stops meaning anything. Not a measurement
# of any market — a plausibility bound on a QUOTE, which is why it is this
# loose. A live thread passed a dummy `-10000` for a side it did not have;
# `prop_edge` computed a hold from it and `boost_verdict` reported
# **"hold 52.3% is steep"** as a reason against the leg — a finding derived
# entirely from a number nobody quoted. It was caught only because 52.3% is
# absurd on its face; a dummy of -400 would have produced a plausible steep
# hold and stood (B24's family).
#
# This refuses the HOLD, not the edge: a genuinely long two-sided quote still
# gets priced, it just gets no steep-hold claim attached to a price that
# cannot support one.
TWO_SIDED_QUOTE_RANGE = (-2000.0, 2000.0)


def two_sided_hold(over_odds: float, under_odds: float | None,
                   *, method: str = "multiplicative") -> tuple[float, str]:
    """(hold, why) for a two-sided prop, or (nan, why) when it is refused."""
    if under_odds is None:
        return float("nan"), "one-sided price, no hold to compute"
    lo, hi = TWO_SIDED_QUOTE_RANGE
    for label, o in (("OVER", over_odds), ("UNDER", under_odds)):
        if o is None or not lo <= float(o) <= hi:
            return float("nan"), (
                f"hold NOT computed: the {label} price {o} is outside "
                f"{lo:+.0f}..{hi:+.0f}, the range where a two-sided hold is "
                f"meaningful. A dummy or placeholder on one side produces a "
                f"confident steep-hold 'finding' from a number nobody "
                f"quoted — pass the real price for both sides or neither.")
    h = devig(over_odds, under_odds, method)[2]
    # A NEGATIVE hold means the two prices imply a booksum below 1 — an arb
    # inside a single book, which does not happen. The backlog worried that a
    # dummy of -400 "would have produced a plausible-looking steep hold";
    # measured, it produces -4.0%, implausible in the other direction. Either
    # way one of the two prices is not from this book. -0.005 tolerates
    # rounding rather than treating it as a signal.
    if h < -0.005:
        return float("nan"), (
            f"hold NOT computed: {over_odds:+.0f}/{under_odds:+.0f} implies "
            f"a hold of {h*100:.1f}%, an arb inside one book, which does not "
            f"happen — one of these two prices is not this book's. Check "
            f"which side you actually have a quote for.")
    return h, "two-sided, measured"


def prop_edge(est: Estimate,
              over_odds: float,
              under_odds: float | None = None,
              fair_over: float | None = None,
              fair_source: str | None = None,
              devig_method: str = "auto",
              market: str | None = None,
              side: str | None = None) -> Edge:
    """Compare the model against a market price and tier the result.

    Raises ValueError on a missing `over_odds`. That used to fall through to
    `american_to_prob` and die with "'>' not supported between instances of
    'NoneType' and 'int'" — an error that says nothing about what went wrong,
    thrown three frames from the cause. Run quotes through `screen_quotes()`
    first and this never comes up.

    Tiers follow the convention from Dustin's other copilots — strong /
    moderate / coin-flip / pass — rather than quoting a false-precision number.
    """
    if over_odds is None:
        raise ValueError(
            "over_odds is None — there is no price to compare against. This "
            "is usually a one-sided or empty market (Bovada's anytime-TD "
            "lists one outcome per player with no 'No' side). Run the quotes "
            "through screen_quotes() first: it drops price-less quotes and "
            "flags one-sided books that need an external fair line.")

    # PREFERRED: a fair probability from a SHARP source, passed in.
    # propline_get_event_ev returns exactly this, anchored per line on
    # Pinnacle / Bovada / Kalshi — pass its value and its `fair_source`.
    #
    # Without it, this de-vigs the price you were quoted, which means using a
    # book as its own reference. That is circular: a recreational book's no-vig
    # line is not the truth, it is that book's opinion plus its shading. Only
    # pass over_odds/under_odds alone when they come from a sharp book.
    if fair_over is not None:
        if not 0.0 < fair_over < 1.0:
            raise ValueError(
                f"fair_over must be strictly between 0 and 1, got {fair_over}. "
                f"A fair probability of exactly 0 or 1 implies a certainty and "
                f"produces an infinite edge.")
        # Hold is the raw booksum minus 1 and does not depend on the de-vig
        # model, so the method passed here is irrelevant to the result. It is
        # pinned rather than forwarded because on this path devig_method is a
        # free-text LABEL describing the upstream choice ("shin
        # (get_event_ev)"), which devig() would rightly reject.
        hold, hold_note = two_sided_hold(over_odds, under_odds)
        # On this path the de-vig happened UPSTREAM, in whatever produced
        # `fair_over` — get_event_ev(devig="shin"), say. prop_edge did not
        # choose it and must not claim to have. Pass the upstream choice as
        # devig_method so the report says something true.
        used_devig = (devig_method if devig_method not in ("auto", "")
                      else "UNKNOWN — get_event_ev defaults to MULTIPLICATIVE "
                           "unless you passed devig='shin'")
    elif under_odds is None:
        # No two-way price and no external fair line: fall back to the raw
        # vigged number. The edge will read better than it is.
        fair_over = american_to_prob(over_odds)
        hold, hold_note = float("nan"), "one-sided price, no hold to compute"
        used_devig = "none (one-sided price, still vigged)"
    else:
        m = "shin" if devig_method == "auto" else devig_method
        hold, hold_note = two_sided_hold(over_odds, under_odds, method=m)
        if hold != hold:                                     # refused
            # The de-vig itself is still needed for fair_over, but the hold
            # it would yield is the fabricated one, so it is dropped.
            fair_over = devig(over_odds, under_odds, m)[0]
        else:
            fair_over, _, hold = devig(over_odds, under_odds, m)
        used_devig = m

    p = est.blended
    edge_over = p - fair_over
    # B126. The side was DERIVED from which way the edge pointed, with no
    # way for a caller to ask about the side it actually wants to bet. That
    # is the root of the Cade Otton near-miss: a live session wanted
    # verdicts for specific sides to build slips, `prop_edge` could only
    # answer for the side the model liked, so the session computed one
    # verdict per LINE and attached it to whichever side it was betting.
    # `boost_verdict` vetoes "a role change running against THE SIDE BEING
    # BET" (B80), so that discarded exactly the thing the veto turns on —
    # and nearly shipped Otton OVER with his targets collapsed 5.4 -> 1.5.
    #
    # Forcing a side is not a worse answer, it is a different question:
    # "what does the model think of the bet I want to make" rather than
    # "what does the model like here". A forced side the model dislikes
    # yields a NEGATIVE edge, which is the honest answer and is what makes
    # the disagreement computable instead of a note in prose.
    if side is not None:
        side = str(side).upper()
        if side not in ("OVER", "UNDER"):
            raise ValueError(
                f"side must be 'OVER' or 'UNDER', got {side!r}")
    else:
        side = "OVER" if edge_over >= 0 else "UNDER"
    model_p = p if side == "OVER" else 1 - p
    fair_p = fair_over if side == "OVER" else 1 - fair_over
    # Signed to the side being evaluated: +ve means the model likes this
    # side, -ve means it does not. Only the derived side can assume +ve.
    edge = edge_over if side == "OVER" else -edge_over

    # The UNDER must be priced at the UNDER's price. Falling back to
    # `over_odds` here produced a number for a bet nobody can place, and it
    # flattered: on a +275/-350 market, pricing the UNDER at +275 reported
    # EV +217%/$ and Kelly 0.79 where the real figures were +8.7% and 0.31 —
    # inflated ~25x, with a stake recommendation attached.
    #
    # This is reachable from the documented workflow, which is what makes it
    # dangerous: screen_quotes() flags a one-sided market and says to price it
    # against an external fair line, and doing exactly that landed here. A
    # one-sided market means only ONE side is purchasable, so if the model
    # prefers the side nobody is quoting, the answer is that there is no bet —
    # not a number computed against the wrong price.
    if side == "UNDER" and under_odds is None:
        raise ValueError(
            f"the model prefers the UNDER ({1 - fair_over:.1%} fair, model "
            f"{1 - est.blended:.1%}) but no under_odds was supplied, so the "
            f"UNDER has no price to compute against. This is usually a "
            f"one-sided market (anytime-TD at DraftKings/FanDuel is YES-only) "
            f"where the UNDER is not purchasable at all — there is no bet "
            f"here. Evaluate only the side the book actually quotes, or pass "
            f"under_odds if you have it. Refusing rather than pricing the "
            f"UNDER at the OVER's price, which overstated EV ~25x.")

    odds = over_odds if side == "OVER" else under_odds
    dec = american_to_decimal(odds)
    ev = model_p * (dec - 1) - (1 - model_p)
    kelly = max(0.0, (model_p * (dec - 1) - (1 - model_p)) / (dec - 1))

    # Tiering. The confidence interval does most of the work here: a 6-point
    # edge means nothing if the interval spans 40 points.
    reasons = []
    if est.sample_verdict == "THIN":
        reasons.append(f"only {est.n} games")
    if est.ci_width > 0.40:
        reasons.append(f"CI spans {est.ci_width*100:.0f} pts")
    if not np.isnan(hold) and hold > 0.06:
        reasons.append(f"hold {hold*100:.1f}% is steep")
    # B121. A UNITS mismatch between the estimate and the market, which this
    # engine could not see at all. Found live: a First TD Scorer leg was
    # priced against a model probability built from a rushing+receiving TD
    # series — that is P(scores A touchdown), while the market is P(scores
    # the FIRST one), roughly three times smaller. The engine reported a
    # +19.2 point "edge" that was almost entirely the units error, and
    # nothing in the output hinted at it; the reading session caught it by
    # hand. `Estimate` carries `stat`, never the market being priced, so the
    # two quantities had no way to be compared.
    _stat = str(getattr(est, "stat", "") or "").lower()
    _td_shaped = "td" in _stat or "touchdown" in _stat
    _mkt = (market or "").lower()
    if _td_shaped and "first" in _mkt:
        raise ValueError(
            f"the estimate is built on {est.stat!r} at line {est.line}, "
            f"which is P(scores A touchdown), and you are pricing {market!r}, "
            f"which is P(scores the FIRST touchdown). Those are different "
            f"events and the first is roughly 3x the second, so the edge "
            f"would be almost entirely a units error. Refusing rather than "
            f"returning it. Price the first-TD market off the market's own "
            f"de-vigged field and report no model number — F4 measured that "
            f"this project cannot out-predict a book on TD level anyway "
            f"(best feature AUC 0.66).")
    _units_unchecked = _td_shaped and not _mkt
    if _units_unchecked:
        reasons.append(
            "TD-shaped estimate priced against an unnamed market — pass "
            "market= so a first-TD line cannot be scored with an "
            "anytime-TD probability (they differ by about 3x)")
    if np.isnan(hold):
        # B120. A nan hold was SILENT here, so a leg whose hold could not be
        # computed came back `tier=MODERATE`, `reasoning="clean read"` and
        # `boost_verdict=CLEAR` — a leg with no measurable vig reading as
        # VETTED. Found live on a First TD leg the same night B87 introduced
        # the refusal: B87 stopped the fabricated number and stopped there,
        # leaving the refusal invisible to everything downstream, which is
        # B39's shape inside B87's own fix. The reason now carries WHY,
        # which also puts it in front of `boost_verdict`.
        reasons.append(f"no hold measured — {hold_note}")

    # A role change OVERRIDES the edge. This is the Waller case: the model read
    # 80% against a market at 50% because his targets had halved. A big edge on
    # a player whose role just changed is evidence the sample is stale, not
    # evidence of value — and the bigger the edge, the stronger that evidence.
    if est.role_changed:
        u = est.usage
        # A role change is DIRECTIONAL evidence, not a blanket disqualifier.
        # The model is built on the old role, so:
        #   COLLAPSED + UNDER  -> the model OVERSTATES his output, which means
        #                         the true under probability is HIGHER than it
        #                         says. The flag supports the bet.
        #   COLLAPSED + OVER   -> the model is inflated on the side you'd bet.
        #                         Refuse.
        #   EXPANDED  + OVER   -> supported, same logic reversed.
        #   EXPANDED  + UNDER  -> refuse.
        # Blanket-blocking both sides was wrong and would have refused a
        # genuinely attractive under on a player whose targets had halved.
        supported = u.supports(side)
        if supported is not True:
            # B84. `not supported` folded False and None together, so a
            # conflicting role change — share up while count fell, or the
            # reverse — was reported as "AGAINST YOU", naming a direction
            # the data does not establish. The outcome is the same PASS
            # either way; the REASON must not claim more than was measured.
            if supported is None:
                _tv = (f" and team volume {u.team_volume_ratio:.0%}"
                       if u.has_team_volume
                       else " (team volume not measured for this series)")
                # B90. Two different reasons reach here — a share/count
                # conflict, and a count that did not move — and one message
                # asserted the conflict narrative for both.
                if u.count_flat:
                    _tail = (f"{u.column} did not move at all "
                             f"({u.baseline:.1f} -> {u.recent:.1f}), so the "
                             f"sample is not stale in either direction and "
                             f"there is no side for the change to help")
                else:
                    _tail = (f"share and count point opposite ways, so the "
                             f"verdict ({u.verdict}) does not fix which side "
                             f"the staleness helps: he is a bigger part of a "
                             f"smaller pie, or the reverse")
                why = (f"ROLE CHANGE, DIRECTION NOT ESTABLISHED — {u.column} "
                       f"{u.baseline:.1f} -> {u.recent:.1f} ({u.ratio:.0%}) "
                       f"while share went {u.share_ratio:.0%}{_tv}. {_tail}. "
                       f"PASS because it is undetermined, not because it runs "
                       f"against you.")
            else:
                why = (f"ROLE CHANGE AGAINST YOU — {u.column} "
                       f"{u.baseline:.1f} -> {u.recent:.1f} "
                       f"({u.ratio:.0%}, share {u.share_ratio:.0%}). "
                       f"The sample describes a role this player no "
                       f"longer has, and the staleness runs in the "
                       f"direction of the {side}. Refuse whatever "
                       f"the edge looks like.")
            return Edge(side=side, model_p=model_p, fair_p=fair_p, edge=edge,
                        ev_per_dollar=ev, hold=hold, kelly=0.0, tier="PASS",
                        reasoning=why,
                        fair_source=fair_source or ("de-vigged from the quoted "
                                                    "price — NOT a sharp reference"),
                        devig_method=used_devig)
        reasons.append(f"role change SUPPORTS this side — {u.column} "
                       f"{u.baseline:.1f} -> {u.recent:.1f} (share "
                       f"{u.share_ratio:.0%}); the model understates the {side}, "
                       f"so the true edge is likely larger than shown, but the "
                       f"magnitude is unreliable")

    # A game-script flag is softer than a role change: the player's share of
    # his offense held up, and team volume reverts more readily than a
    # depth-chart spot. Add uncertainty, do not auto-PASS.
    if est.usage is not None and est.usage.soft_flagged:
        u = est.usage
        reasons.append(f"team volume at {u.team_volume_ratio:.0%}, share held "
                       f"at {u.share_ratio:.0%} — game script, not role loss")

    if edge < 0.03 or est.ci_width > 0.50:
        tier = "PASS"
        # B126. "inside the noise" is true of a SMALL edge and false of a
        # negative one. With a side forced, the model can be actively
        # against the bet — a -8% edge is not noise, it is a disagreement,
        # and reporting it as noise hides the one thing the caller asked.
        if edge < -0.005:
            reasons.insert(0, (
                f"the model is AGAINST this side by {abs(edge)*100:.1f} "
                f"points — it prefers "
                f"{'UNDER' if side == 'OVER' else 'OVER'} here. This is not "
                f"a thin edge, it is a disagreement."))
        else:
            reasons.insert(0, "edge inside the noise")
    elif edge >= 0.08 and est.sample_verdict == "ADEQUATE" and est.ci_width <= 0.35:
        tier = "STRONG"
    elif edge >= 0.05 and est.sample_verdict != "THIN":
        tier = "MODERATE"
    else:
        tier = "COIN-FLIP"

    # B121. An unchecked units question costs a tier, for the same reason a
    # role change does: the edge may be real but it may be three times the
    # quantity the market is about, and nothing here can tell. STRONG on a
    # leg whose units were never checked is the "reads as vetted" fault the
    # live round named.
    if _units_unchecked:
        tier = {"STRONG": "MODERATE", "MODERATE": "COIN-FLIP"}.get(tier, tier)

    # A supportive role change still costs a tier: the DIRECTION is informative
    # but the MAGNITUDE is not, so do not let it license a big stake.
    if est.role_changed:
        tier = {"STRONG": "MODERATE", "MODERATE": "COIN-FLIP"}.get(tier, tier)

    # Soft flag costs one tier — real uncertainty, but not disqualifying.
    if est.usage is not None and est.usage.soft_flagged:
        tier = {"STRONG": "MODERATE", "MODERATE": "COIN-FLIP",
                "COIN-FLIP": "PASS"}.get(tier, tier)

    return Edge(side=side, model_p=model_p, fair_p=fair_p, edge=edge,
                ev_per_dollar=ev, hold=hold, kelly=kelly, tier=tier,
                reasoning="; ".join(reasons) if reasons else "clean read",
                devig_method=used_devig,
                fair_source=fair_source or ("de-vigged from the quoted price "
                                            "— NOT a sharp reference"))


# Flat stake sizing, mirroring the convention from the other copilots. Applies
# to STANDALONE props only — a boost slip is a fixed $10 by rule, so stake
# sizing is not a decision there. See boost_verdict() below.
STAKES = {"STRONG": 13, "MODERATE": 10, "COIN-FLIP": 5, "PASS": 0}


# ---------------------------------------------------------------------------
# P1 — what the model is FOR, in a boost slip
#
# The tiers above read like bet selection with stake sizing, and the number
# they are built on is called "edge". In the boost use case both framings are
# wrong, in a way that mis-signals every week:
#
#   1. The model is NOT a sharp reference. "Edge" means a gap against a price
#      believed to be fair. This model's gap is against a de-vigged book line
#      or a Kalshi anchor, computed from a handful of games with confidence
#      intervals routinely 40-70 points wide. Calling that an edge invites
#      betting ON it. Measured: the model is 0-for-2 when it disagreed with a
#      sharp line (Waller, Lloyd) — and both were role changes, which is the
#      one thing it genuinely sees.
#
#   2. The boost objective is not edge, it is CASHING. A boost needs >= 3 legs
#      at >= +300 for a fixed $10. The legs are largely chosen by what the
#      boost covers and what the books offer. The model's job is to VETO the
#      legs that are quietly broken — the player whose role collapsed, the
#      market three books just suspended — not to rank the rest.
#
# So in a boost context the output is an inclusion verdict, not a bet rating,
# and the gap is reported as a gap, never as an edge.
# ---------------------------------------------------------------------------

BOOST_VERDICTS = {
    "VETO":    "Do not include. Something is wrong with this leg.",
    "CAUTION": "Include only if you need the leg count. Known weakness.",
    "CLEAR":   "Nothing against it. Not an endorsement — just no veto.",
}


def boost_verdict(est: Estimate, edge: Edge | None = None,
                  screen: QuoteScreen | None = None) -> tuple[str, list[str]]:
    """Should this leg go on a boost slip? Returns (verdict, reasons).

    This is a VETO function. A CLEAR verdict means nothing was found against
    the leg, which is not the same as a recommendation — with intervals this
    wide the model cannot endorse a leg, only reject one.

    Vetoes, in order of how much they are trusted:
      - a multi-book suspension (probable scratch) — the strongest signal here
      - a role change running against the side being bet
      - no usable price, or a sample too thin to say anything
    """
    reasons: list[str] = []
    verdict = "CLEAR"

    def veto(why: str):
        nonlocal verdict
        verdict = "VETO"
        reasons.append(why)

    def caution(why: str):
        nonlocal verdict
        if verdict != "VETO":
            verdict = "CAUTION"
        reasons.append(why)

    if screen is not None:
        if screen.scratch_risk:
            veto(f"PROBABLE SCRATCH — suspended at "
                 f"{len(screen.suspended_books)} books "
                 f"({', '.join(screen.suspended_books)}). The books know "
                 f"something the wire has not printed.")
        if not screen.usable:
            veto("no usable price at any book")
        if screen.one_sided:
            caution(f"one-sided market at {', '.join(screen.one_sided)} — "
                    f"cannot be de-vigged, needs an external fair line")

    if est.role_changed:
        u = est.usage
        # B88/A3. `side = edge.side if edge is not None else None` then
        # tested `side is None` as a proxy for "no edge supplied". But
        # `Edge.side` is an unvalidated str and this file uses lowercase
        # "over"/"under" in several places, so `Edge(side="over")` was not
        # None, `supports()` returned None because the string is not
        # canonical, and the call fell through to the CONFLICT branch —
        # printing "the COUNT moved the other way" on a trend whose count
        # moved 3.2 -> 8.0, the SAME way. A fabricated divergence, and it
        # re-vetoed exactly the Justice Hill expansion B80 exists to
        # un-veto, reached by letter case. Normalise, and keep "no edge" and
        # "unusable side" as separate states.
        raw_side = edge.side if edge is not None else None
        side = (raw_side.strip().upper()
                if isinstance(raw_side, str) and raw_side.strip() else None)
        if side not in ("OVER", "UNDER"):
            side = None
        tv = (f" and team volume {u.team_volume_ratio:.0%}"
              if u.has_team_volume else
              " (team volume not measured for this series)")
        # B80. This used to veto on ANY role change and then assert "it runs
        # against {side}" in the message WITHOUT EVER CHECKING THE
        # DIRECTION. Measured live 2026-11-05: Justice Hill was the
        # best-priced leg on the TNF board (ev_pct -0.23%) and was vetoed
        # because his targets went 2.2 -> 6.0 — an EXPANSION, which supports
        # the Over being bet — while the message claimed the opposite. He
        # was swapped out for a worse leg.
        #
        # `prop_edge` already had this right, 150 lines up, with a comment
        # saying blanket-blocking both sides "was wrong and would have
        # refused a genuinely attractive under on a player whose targets had
        # halved". So the same file held the fix and an un-fixed restatement
        # of the same reasoning — B68's shape applied to logic instead of a
        # constant. The expression below is deliberately IDENTICAL to
        # prop_edge's, so the two cannot drift.
        #
        # `flagged` is exactly verdict in (COLLAPSED, EXPANDED), so these
        # cases below are exhaustive for anything reaching here. NOTE this
        # conditional has grown to five branches (unrecognised side, no
        # side, conflict/flat, supported, opposed) — re-read all of them
        # before adding a sixth.
        supported = u.supports(side)
        if side is None and edge is not None and raw_side is not None:
            veto(f"ROLE CHANGE, SIDE NOT RECOGNISED — {u.column} "
                 f"{u.baseline:.1f} -> {u.recent:.1f} ({u.verdict}). The "
                 f"Edge carries side={raw_side!r}, which is not OVER or "
                 f"UNDER, so the direction cannot be compared against it. "
                 f"This is a caller bug, not a finding about the player.")
        elif side is None:
            # No edge means no side, so the direction cannot be determined.
            # Refusing is right, but the REASON has to be the missing side
            # rather than a direction nobody measured.
            veto(f"ROLE CHANGE, DIRECTION UNKNOWN — {u.column} "
                 f"{u.baseline:.1f} -> {u.recent:.1f} ({u.verdict}, share "
                 f"{u.share_ratio:.0%}). No edge was supplied, so there is "
                 f"no side to compare the change against. Pass the Edge to "
                 f"get a directional read.")
        elif supported is None:
            # B84. Share and count point opposite ways, so the verdict does
            # not fix the production direction. This branch has to come
            # before the truthiness test below: `elif supported:` treats
            # None as False and would VETO "AGAINST THE {side}", asserting
            # a direction again — the same mistake B80 fixed, re-entered
            # through a new None.
            # B90. `supports()` returns None for TWO different reasons here
            # — share and count conflicting, and the count not moving at all
            # — and this message asserted the conflict narrative for both.
            # Live result: CeeDee Lamb's targets were exactly flat at
            # 11.5 -> 11.5 and the refusal told the reader "the COUNT moved
            # the other way". The reading session then reported him as the
            # conflict case and had to correct itself by inspecting the
            # flags. A message asserting what the code did not determine —
            # the same class as B80 and B88/A4, introduced in the fix for
            # them, which is why each state now gets its own sentence.
            if u.count_flat:
                veto(f"ROLE CHANGE, DIRECTION NOT ESTABLISHED — {u.column} "
                     f"did NOT move ({u.baseline:.1f} -> {u.recent:.1f}) "
                     f"while share went {u.share_ratio:.0%}{tv}. The verdict "
                     f"is {u.verdict} off SHARE, but a threshold prop is "
                     f"priced on opportunity COUNT, and his count is flat — "
                     f"so the sample is not stale in either direction and "
                     f"there is no side for the change to help. Refused as "
                     f"UNDETERMINED, not as against the {side}.")
            else:
                veto(f"ROLE CHANGE, DIRECTION NOT ESTABLISHED — {u.column} "
                     f"{u.baseline:.1f} -> {u.recent:.1f} ({u.ratio:.0%}) "
                     f"while share went {u.share_ratio:.0%}{tv}. The verdict "
                     f"is {u.verdict} off SHARE, but the COUNT moved the "
                     f"OTHER WAY, and a threshold prop is priced on count. "
                     f"He is a bigger part of a smaller pie, or the reverse "
                     f"— which side the staleness helps is undetermined, so "
                     f"this is refused as UNKNOWN rather than as against the "
                     f"{side}.")
        elif supported:
            # Still not CLEAR: the direction helps, the magnitude is not
            # trustworthy. Matches prop_edge, which costs a supportive
            # role change one tier rather than rewarding it.
            caution(f"ROLE CHANGE SUPPORTS THIS SIDE — {u.column} "
                    f"{u.baseline:.1f} -> {u.recent:.1f} ({u.verdict}, share "
                    f"{u.share_ratio:.0%}). The model is built on the old "
                    f"role, so it UNDERSTATES the {side} — the leg is "
                    f"playable and the true edge is likely larger than "
                    f"shown, but the magnitude is unreliable, so do not size "
                    f"up on it.")
        else:
            veto(f"ROLE CHANGE AGAINST THE {side} — {u.column} "
                 f"{u.baseline:.1f} -> {u.recent:.1f} ({u.verdict}, share "
                 f"{u.share_ratio:.0%}). The sample describes a role this "
                 f"player no longer has, and the staleness runs in the "
                 f"direction of the {side}.")
    elif est.usage is not None and est.usage.soft_flagged:
        u = est.usage
        caution(f"team volume at {u.team_volume_ratio:.0%} but share held at "
                f"{u.share_ratio:.0%} — game script, not role loss")

    # A binary, low-event stat breaks the threshold model. Measured live:
    # Rome Odunze came back at 1.0% against a 25.2% Pinnacle fair line on 7
    # games — a 24-point gap produced by a stat that is 0 or 1 each week with
    # almost no events in the sample. The right outcome happened there only
    # because the one-sided guard refused the unpriced side. A gap that large
    # invites exactly the misreading this whole framing exists to prevent.
    if est.stat.endswith("_tds") and est.line <= 1.5:
        gap = abs(est.blended - (edge.fair_p if edge is not None
                                 and edge.side == "OVER" else est.blended))
        if est.hits <= 1 or est.n < 10:
            # CAUTION, not VETO. The model abstaining is not the same as the
            # leg being broken — a veto is for a collapsed role or a probable
            # scratch. A TD leg the model cannot assess may be perfectly fine
            # at the market price, and TD legs are a market Dustin actively
            # wants. Vetoing them would remove a whole leg type for the wrong
            # reason.
            caution(f"MODEL ABSTAINS — binary stat, {est.hits} event(s) in "
                    f"{est.n} games. Its {est.blended:.0%} is not evidence "
                    f"either way; a {est.hits}/{est.n} sample cannot pin a TD "
                    f"rate. Judge this leg on the market price alone and "
                    f"ignore the gap shown.")
        elif gap > 0.15:
            caution(f"binary stat and the model disagrees with the market by "
                    f"{gap*100:.0f} pts — on TD markets that is usually the "
                    f"model being wrong, not an edge")

    if est.sample_verdict == "THIN":
        caution(f"only {est.n} games")
    if est.ci_width > 0.50:
        caution(f"interval spans {est.ci_width*100:.0f} points — the model "
                f"has no real opinion here")

    return verdict, reasons


def boost_leg_report(est: Estimate, edge: Edge, label: str = "",
                     screen: QuoteScreen | None = None) -> str:
    """Report a leg for a boost slip: inclusion verdict, no stake, no "edge"."""
    verdict, reasons = boost_verdict(est, edge, screen)
    gap = (edge.model_p - edge.fair_p) * 100.0   # in points, not a fraction
    L = [label or f"{est.stat} {edge.side} {est.line:g}"]
    L.append(f"  VERDICT     : {verdict} — {BOOST_VERDICTS[verdict]}")
    L.append(f"  market fair : {edge.fair_p:.1%}  ({edge.fair_source})")
    # Deliberately "gap", not "edge": see the comment block above.
    L.append(f"  model says  : {edge.model_p:.1%}  "
             f"(gap {gap:+.1f} pts — NOT an edge; this model is not a sharp "
             f"reference)")
    L.append(f"  sample      : {est.n} games, interval "
             f"{est.ci_low*100:.0f}-{est.ci_high*100:.0f}%")
    L.append(f"  de-vig      : {edge.devig_method}")
    if reasons:
        for r in reasons:
            L.append(f"  - {r}")
    else:
        L.append("  - nothing found against this leg")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def report(est: Estimate, label: str = "") -> str:
    head = label or f"P({est.stat} >= {est.line:g})"
    band = f"{est.ci_low*100:.0f}-{est.ci_high*100:.0f}%"
    lines = [
        f"{head}",
        f"  sample      : {est.n} games, {est.hits} cleared  "
        f"[{est.sample_verdict}]",
        f"  distribution: mean {est.mean:.1f}, sd {est.sd:.1f}",
        f"  empirical   : {est.empirical*100:.0f}%",
        f"  normal fit  : {est.parametric*100:.0f}%",
        f"  recency-wtd : {est.recency*100:.0f}%",
        f"  USE         : {est.blended*100:.0f}%   (95% CI {band})",
    ]
    if est.usage is not None:
        lines.append(est.usage.describe())
    if est.ci_width > 0.40:
        lines.append(f"  ! interval spans {est.ci_width*100:.0f} points — "
                     f"treat as directional, not precise")
    if est.role_changed:
        lines.append("  ! DO NOT BET THIS off the model. Role change detected.")
    return "\n".join(lines)


def edge_report(e: Edge, label: str = "") -> str:
    stake = STAKES[e.tier]
    lines = [
        f"{label}",
        f"  side        : {e.side}",
        f"  model       : {e.model_p*100:.0f}%   market (fair): {e.fair_p*100:.0f}%",
        f"  fair from   : {e.fair_source}",
        f"  edge        : {e.edge*100:+.1f} pts    EV {e.ev_per_dollar*100:+.1f}%/$",
    ]
    if not np.isnan(e.hold):
        lines.append(f"  book hold   : {e.hold*100:.1f}%")
    lines.append(f"  de-vig      : {e.devig_method}")
    lines.append(f"  VERDICT     : {e.tier}  ->  ${stake}")
    lines.append(f"  why         : {e.reasoning}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Live-quote hygiene (P2)
#
# PropLine returns three fields that carry real information and were being
# discarded. Each one, left unread, produces a specific Sunday error:
#
#   suspended_at   The book pulled that market pregame. Unbettable — and when
#                  SEVERAL books suspend the same player at once, that is a
#                  probable scratch. This is injury news arriving before the
#                  news does, which is the single most valuable signal in the
#                  feed and we were throwing it away.
#   pregame_only   Once a game kicks off, a book with no in-play feed keeps
#                  returning its last pregame quote forever. Nothing is
#                  stale-flagged, because the book is simply never polled
#                  again. Presenting that as a live price is just wrong.
#   max_age        Request parameter that drops quotes a book has not
#                  refreshed within N seconds. Unset, a 20-minute-old price
#                  reads as current.
# ---------------------------------------------------------------------------

SCRATCH_BOOKS = 3          # suspensions across this many books = probable scratch
LIVE_MAX_AGE_S = 120       # pass as max_age on in-play pulls
PREGAME_MAX_AGE_S = 900    # pregame prices move slower; 15 min is tolerable


# Names PropLine uses for each side of a two-way market. Checked BEFORE any
# generic price key, because a generic key cannot tell you which side it is.
OVER_NAMES = {"over", "yes", "o"}
UNDER_NAMES = {"under", "no", "u"}

PRICE_KEYS_OVER = ("over", "over_odds", "price_over", "odds_over",
                   "over_price", "yes", "yes_odds")
PRICE_KEYS_UNDER = ("under", "under_odds", "price_under", "odds_under",
                    "under_price", "no", "no_odds")
PRICE_KEYS_BARE = ("price", "odds", "american", "american_odds")


def _num(v):
    if isinstance(v, dict):
        v = v.get("odds", v.get("price", v.get("american")))
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.replace("+", "").strip())
        except ValueError:
            return None
    return None


def _prices(q: dict) -> tuple[float | None, float | None]:
    """Pull (over, under) American prices out of a quote.

    Handles two shapes. A FLATTENED quote carries both sides on one dict
    (`{"over": -111, "under": -113}`). A SINGLE OUTCOME row carries one price
    plus a `name` saying which side it is (`{"name": "Under", "price": -113}`)
    — that is what `propline_get_odds` actually returns, one row per outcome.

    The `name` is read FIRST, and a bare `price`/`odds` key is only treated as
    the over when nothing says otherwise. An earlier version listed "price" in
    PRICE_KEYS_OVER with no name check, so a native Under row returned
    (-113, None): **the Under's price came back as the Over's price**, and a
    plainly two-sided market was then reported as one-sided. That is the same
    swap as the prop_edge UNDER bug, one layer upstream, in the screen whose
    whole job is to stop bad prices reaching prop_edge — and it arrives as a
    plausible number rather than an error.

    A single outcome cannot be de-vigged on its own. Use `flatten_odds()` to
    pair the sides before screening.
    """
    over = under = None
    for k in PRICE_KEYS_OVER:
        v = _num(q.get(k))
        if v is not None:
            over = v
            break
    for k in PRICE_KEYS_UNDER:
        v = _num(q.get(k))
        if v is not None:
            under = v
            break
    if over is not None or under is not None:
        return over, under

    # Single-outcome row: the name decides the side.
    bare = None
    for k in PRICE_KEYS_BARE:
        bare = _num(q.get(k))
        if bare is not None:
            break
    if bare is None:
        return None, None

    label = str(q.get("name") or q.get("side") or q.get("outcome") or "").strip().lower()
    if label in UNDER_NAMES:
        return None, bare
    # "Over", "Yes", a player name, or an N+ milestone rung all price the
    # side you can actually back, which is the over/yes side.
    return bare, None


_RUNG_RE = re.compile(r"\s*(\d+(?:\.\d+)?)\s*\+")


def rung_threshold(name) -> float | None:
    """Parse the N out of a milestone rung label like "175+ Passing Yards".

    Returns None for anything that is not a leading `N+`, which includes every
    anytime-TD outcome (those are player names) and any rung grammar a book
    invents that we have not seen. None is a refusal to guess, not a zero:
    callers must treat it as "this row has no threshold", never as a number.
    """
    m = _RUNG_RE.match(str(name or ""))
    return float(m.group(1)) if m else None


def canonical_bet(q: dict) -> tuple | None:
    """The identity of the wager a quote represents, for collision detection.

    A rung and a main line can be THE SAME BET under different labels.
    DraftKings posts `238+ Passing Yards` at -113 alongside a main line of
    `Over 237.5` at -111: identical wagers, two cents apart, arriving as two
    rows because `flatten_odds` filters by `line_type` and so never sees both
    in one call. Treated as two legs they would be parlayed with each other,
    priced as independent, and the resulting P(cash) would be fiction.

    So the equivalence is computed here rather than left for a caller to
    notice. A rung at N is exactly "over N - 0.5", because these stats are
    integer-valued: 238+ yards and >237.5 yards are the same event, and
    neither can push.

    NOTHING IS SNAPPED. If a book ever posts a whole-number main line at 237,
    `Over 237` pushes at exactly 237 and is NOT the same bet as `238+`; the
    subtraction leaves them unequal on its own, and that must stay true. This
    is D18's rule — a fair probability for one point is not a fair
    probability for a neighbouring one — applied to the rung grid.

    Returns None when the row has no threshold at all (anytime-TD), meaning
    "not comparable this way", never a default number.
    """
    if not isinstance(q, dict):
        return None
    if q.get("line") is not None:
        threshold = float(q["line"])
    elif q.get("rung_threshold") is not None:
        threshold = float(q["rung_threshold"]) - 0.5
    else:
        return None
    # KEYED ON THE NORMALISED NAME, always — not `player_id or player`, which
    # is what sat here and which fails in the one direction that matters: it
    # MISSES a duplicate. A rung row carrying `espn:3915416` and a main row
    # carrying null for the same player produce two different keys, so the two
    # rows that are one bet compare as different bets and get parlayed. The
    # raw-name fallback missed a second way: DraftKings spells "D.J. Moore"
    # where Pinnacle spells "DJ Moore", and the ladder's anchor join lost all
    # 18 of his rungs to exactly that before `norm_player` was applied there.
    #
    # The name is the only key present on every row, so it is the grouping
    # key. It can OVER-group — two different players really can share a
    # spelling — so this key alone is not proof that two quotes are one bet.
    # `same_bet()` confirms with the id. That split is B127's established
    # pattern: normalised name to group, `player_id` to refuse.
    return (norm_player(str(q.get("player") or "")),
            q.get("market"), "over", threshold)


def same_bet(a: dict, b: dict) -> bool:
    """True when two quotes are the SAME wager under different labels.

    `canonical_bet` groups; this confirms. Equal canonical keys and no
    conflicting `player_id`: two ids that differ mean two players who happen
    to share a spelling, and a missing id on either side cannot distinguish
    them, so it defers to the key rather than inventing a distinction.

    Use this, not `==` on the keys, wherever a rung list and a main-line list
    are merged. A rung at N and that player's own `Over N-0.5` are one bet;
    parlayed with each other they price as independent legs and the P(cash)
    that comes out is fiction.
    """
    ka, kb = canonical_bet(a), canonical_bet(b)
    if ka is None or kb is None or ka != kb:
        return False
    ia, ib = a.get("player_id"), b.get("player_id")
    if ia is not None and ib is not None and str(ia) != str(ib):
        return False
    return True


# `get_event_ev` picks an anchor PER LINE, in this order, and no other book
# can ever anchor. A live DraftKings carrying three two-sided markets is not
# a missing anchor, it is a book that was never eligible — the first version
# of `anchor_coverage` flagged exactly that and a live pull caught it.
ANCHOR_CHAIN = ("pinnacle", "polymarket", "kalshi", "bovada", "smarkets")


@dataclass
class AnchorCoverage:
    """Which books ANCHORED, against which were live enough to anchor."""
    anchored: dict                      # {book: lines it anchored}
    live: dict                          # {book: two-sided LINES it carries}
    silent_dropouts: list               # live to anchor, anchored nothing
    total_lines: int = 0
    blank: bool = False                 # nothing anchored at all (B62)
    eligible: list = field(default_factory=list)   # chain books live enough
    # B72. The one failure this detector could not survive was its OWN
    # control coming back empty. `eligible` derives entirely from the
    # odds_response, so a failed or empty control gave `eligible == []`,
    # which made `blank` False and left the per-book loop with nothing to
    # iterate — and `healthy` then returned True, printing "every book live
    # to anchor did" about books that were never observed. A positive claim
    # from a measurement that did not happen: B46's shape, in the function
    # whose entire purpose is to be the paired control.
    control_usable: bool = True
    # B78. Live books whose identity could not be established — no `key`,
    # and a `title` that resolves to no chain book. Previously each was
    # given its display name as a manufactured key, which could never match
    # the lowercase chain, so it sat in `live` looking accounted for while
    # contributing nothing to `eligible`. An unidentifiable book may BE the
    # anchor, so it is named here and it costs `healthy`.
    unidentified: list = field(default_factory=list)

    @property
    def healthy(self) -> bool:
        if not self.control_usable:
            return False
        # B78. An unidentifiable live book may BE the anchor, so health
        # cannot be claimed over it. On the measured B60 payload — Pinnacle
        # carrying `title` and no `key` — this was the difference between
        # `healthy=True` and the dropout being seen at all.
        if self.unidentified:
            return False
        return not self.silent_dropouts and not self.blank

    def describe(self) -> str:
        a = ", ".join(f"{b} {n}" for b, n in
                      sorted(self.anchored.items(), key=lambda kv: -kv[1])) or "none"
        L = [f"anchored {self.total_lines} line(s): {a}"]
        if self.unidentified:
            L.append(
                "  *** LIVE BOOK(S) NOT IDENTIFIABLE: "
                + ", ".join(self.unidentified)
                + ". Each carries two-sided lines but no `key`, and its "
                "`title` matches no book in the anchor chain — so nothing "
                "here can tell whether one of them is the anchor that "
                "dropped out. This is NOT a clean bill of health: the "
                "measured B60 signature is exactly this (Pinnacle with a "
                "title and no key), and an earlier version gave each a "
                "manufactured key that could never match the chain, which "
                "made this case read as healthy.")
        if not self.control_usable:
            L.append(
                "  *** NO USABLE CONTROL. The get_odds pull carried no "
                "bookmaker with any two-sided line, so NOTHING was "
                "measured about which books were live. This is not a "
                "clean bill of health and it is not 'no market' — it is "
                "most likely a failed or empty control pull. Re-pull "
                "get_odds for this event and this market before quoting "
                "any EV; until then a dropout can neither be confirmed "
                "nor ruled out.")
        if self.blank:
            L.append(
                f"  *** NOTHING ANCHORED AT ALL, while "
                f"{', '.join(f'{b} carries {self.live[b]}' for b in self.eligible)} "
                f"two-sided line(s) in the SAME pull — B60 at its loudest. "
                f"An empty or anchorless EV response next to a live anchor "
                f"feed is the one case the EV payload cannot diagnose on its "
                f"own. There is no fair line here: do not quote an EV, and "
                f"do not read this as 'no market'.")
        for b in (self.silent_dropouts if not self.blank else []):
            L.append(
                f"  *** {b} ANCHORED NOTHING while carrying "
                f"{self.live[b]} two-sided line(s) in the SAME pull — "
                f"B60. This is not an empty response and nothing in the "
                f"EV payload says it happened. Every line that would "
                f"have anchored on {b} fell through to a softer source. "
                f"Do not quote an EV from this pull without saying so.")
        if self.healthy:
            L.append("  no silent dropouts: every book live to anchor did")
        return "\n".join(L)


def _two_sided_lines(bookmaker: dict) -> int:
    """Distinct two-sided, unsuspended LINES a book carries — anchorable.

    B63. This counted market ENTRIES and that is not comparable across
    books. On one reception-yards pull Pinnacle showed 14 entries (one per
    player, main only) while Bovada showed 30 (alternates are separate
    entries), and Kalshi's entire anytime-TD Yes/No board — 44 outcomes —
    arrived as a SINGLE entry. A threshold applied to that number means a
    different thing at every book.

    A (player, point) pair carrying both sides is the same unit everywhere,
    so that is what gets counted. This also fixes most of B64: Kalshi's
    collapsed TD board resolves to its real line count instead of 1.

    A one-sided board contributes nothing, which is correct rather than a
    gap — a book quoting only "Yes" cannot be de-vigged and so cannot
    anchor. That is reason 4 of the `lines: []` ambiguity, not a dropout.
    """
    lines = set()
    for mk in bookmaker.get("markets") or []:
        if mk.get("suspended_at") is not None:
            continue
        sides: dict = {}
        for oc in mk.get("outcomes") or []:
            key = (oc.get("description"), oc.get("point"))
            sides.setdefault(key, set()).add(
                str(oc.get("name") or "").strip().lower())
        for key, s in sides.items():
            if s & OVER_NAMES and s & UNDER_NAMES:
                lines.add((mk.get("key"), key))
    return len(lines)


def book_key(bk: dict) -> str | None:
    """A book's CHAIN-COMPARABLE key, or None when it cannot be identified.

    B78. Every site did `bk.get("key") or bk.get("title")`. `title` is by
    construction the DISPLAY name, so on the B60 signature — Pinnacle
    carrying `title` and no `key` — the fallback manufactured `"Pinnacle"`
    against a lowercase `ANCHOR_CHAIN`, an entry that can never match
    anything. Measured on that exact payload: `live={'Pinnacle': 14}`,
    `eligible=[]`, `silent_dropouts=[]`, **`healthy=True`** — the detector
    written to catch B60 reporting health on a textbook B60 dropout, which
    is the worst possible place for this fault to live.

    So: take `key` when it is there; otherwise normalise `title` and accept
    it ONLY if it resolves to a chain book. Anything else returns None,
    because a manufactured key that cannot match is worse than an admitted
    unknown — it looks like coverage.
    """
    k = (bk.get("key") or "").strip().lower()
    if k:
        return k
    t = "".join(ch for ch in (bk.get("title") or "").lower()
                if ch.isalnum())
    if not t:
        return None
    for chain in ANCHOR_CHAIN:
        if t == "".join(ch for ch in chain if ch.isalnum()):
            return chain
    return None


def norm_fair_source(src) -> str | None:
    """`fair_source` as a chain-comparable key. B78.

    The anchored side keyed on the raw string, so a payload spelling
    `fair_source: "Pinnacle"` counted separately from `pinnacle` and the
    book read as having anchored nothing.
    """
    if not src:
        return None
    t = str(src).strip().lower()
    # Live payloads carry trailing provenance, e.g.
    # "bovada (via get_event_ev, unfiltered)".
    t = t.split("(")[0].strip()
    flat = "".join(ch for ch in t if ch.isalnum())
    for chain in ANCHOR_CHAIN:
        if flat == "".join(ch for ch in chain if ch.isalnum()):
            return chain
    return t or None


def anchor_coverage(ev_response: dict, odds_response: dict,
                    *, min_lines: int = 1) -> AnchorCoverage:
    """Catch B60: an anchor book silently missing from a populated EV response.

    `get_event_ev` drops an anchor book while that book's odds feed stays
    perfectly healthy, and **it does not return `[]` when it does** — it
    returns a populated, plausible response with the sharp anchor quietly
    replaced by a softer one. Observed three times on event 87238; on the
    worst, Pinnacle anchored 0 of 154 lines across three calls over 90
    seconds while a paired `get_odds` control showed it live with 14
    two-sided markets, `suspended_at: null`, liquidity 500 and varied
    prices. One dropout cleared in minutes, another outlasted the window,
    so **re-polling is not a fix.**

    `anchor_opening` and `anchor_thin` cannot catch this: they key on
    liquidity, and `get_event_ev` carries no liquidity field at any level
    (D17). Nothing downstream of the EV response can see it either, because
    the response looks complete. The only way to know is to hold the two
    payloads side by side, which is what this does.

    Pass the EV response and a `get_odds` pull **from the same moment**, on
    the same market. A book flags when it is in `ANCHOR_CHAIN`, carries at
    least `min_lines` two-sided unsuspended lines, and anchored zero while
    a book BELOW it in the chain anchored some — or when NOTHING anchored
    at all, which is handled separately as `blank` (B62).

    `min_lines` defaults to 1, not 3. A threshold of 3 hid a confirmed
    dropout on `player_pass_yds`, where Pinnacle carries exactly two
    two-sided lines because a game has two quarterbacks: it anchored 0 of
    30 and the detector said "no silent dropouts" in the same minute it
    correctly flagged three other markets. A market can be legitimately
    small, so size is the wrong gate; the "anchored zero while a lower book
    anchored" condition does the real filtering. The residual risk of a
    threshold of 1 is flagging a D18 grid mismatch as a dropout, and that
    trade is deliberate — a false flag costs a check, a missed dropout
    costs a silently wrong EV.

    All three conditions came from a live pull disproving a simpler rule.
    The first version flagged any live book that anchored nothing, and
    immediately reported DraftKings — which can never anchor, so its absence
    means nothing. And because the chain is tried in order, a lower-priority
    book anchoring zero is correct rather than suspicious: it means the
    books above it covered every line.

    **Partial dropouts are still not detected, and measurement says that
    matters less than it sounds.** Seven market-level observations across a
    live dropout-and-recovery cycle were every one 0% or 100%: Pinnacle
    anchored 0 of 14, 0 of 14, 0 of 5, 0 of 2 while dropped, then 14 of 14,
    14 of 14, 5 of 5 once recovered. Its anchoring is binary. The partial
    case would need a per-line join on (player, point), which is where B44
    and D18 live, and a fragile join inside a detector is a detector you
    cannot trust. One event, one night, one book — it does not rule partials
    out in general.

    **Only the TOP available chain book's count is interpretable.** Bovada
    anchoring 21 of 30 anchorable lines is not a partial dropout; Kalshi
    sits above it and took the rest. Reading a lower book's count as a
    dropout is an easy mistake and this function does not make it.

    This reports rather than raises. The dropout is upstream and the right
    response is usually to say so and re-pull, not to abort — but an EV
    quoted from a pull with a dropout must carry that fact.
    """
    anchored: dict = {}
    for ln in ev_response.get("lines") or []:
        src = norm_fair_source(ln.get("fair_source"))
        if src:
            anchored[src] = anchored.get(src, 0) + 1

    live: dict = {}
    unidentified: list[str] = []
    for bk in odds_response.get("bookmakers") or []:
        n = _two_sided_lines(bk)
        if not n:
            continue
        key = book_key(bk)
        if key is None:
            # B78. Not silently given an invented key. An unidentifiable
            # book could BE the anchor, so it is named and it costs health.
            unidentified.append(str(bk.get("title") or bk.get("key")
                                    or "<no name>"))
            continue
        live[key] = n

    # Only chain books can anchor, and the chain is tried IN ORDER per line.
    # So a LOWER-priority book anchoring nothing is correct behaviour — the
    # books above it covered everything. The dropout signature is the
    # reverse: a book anchored zero while live, and books BELOW it in the
    # chain picked up the work that should have been its.
    #
    # B62. That "books below anchored" condition — added to kill a false
    # positive — opened a hole underneath it: when NOTHING anchors at all,
    # no book has anything below it, so nothing flags and `healthy` comes
    # back True. That is the loudest possible version of this fault, and it
    # is exactly reason 6 of the `lines: []` ambiguity, the case the
    # instructions say only a paired `get_odds` control can diagnose. The
    # control reported it healthy. So a total blank is handled first and
    # separately, rather than falling through the per-book loop.
    # B72. An empty control cannot clear anybody — see the note on
    # `control_usable`. Measured BEFORE `eligible`, because `eligible` is
    # derived from this same payload and so goes quiet in exactly the case
    # that needs flagging.
    control_usable = bool(live)

    eligible = [b for b in ANCHOR_CHAIN if live.get(b, 0) >= min_lines]
    blank = bool(eligible) and not anchored
    dropouts = []
    if blank:
        # B72b. This used to be `[eligible[0]]`, which names the top chain
        # book as a specific dropout when the measured finding is only
        # "nothing anchored at all". `describe()` suppressed it, but
        # `silent_dropouts` is a documented field and a caller reading it
        # got an accusation the data does not support. `blank` already
        # carries the finding; the per-book list stays empty.
        dropouts = []
    else:
        for i, book in enumerate(ANCHOR_CHAIN):
            if anchored.get(book) or live.get(book, 0) < min_lines:
                continue
            if any(anchored.get(b) for b in ANCHOR_CHAIN[i + 1:]):
                dropouts.append(book)
    return AnchorCoverage(anchored=anchored, live=live,
                          silent_dropouts=dropouts, blank=blank,
                          eligible=eligible, control_usable=control_usable,
                          unidentified=unidentified,
                          total_lines=len(ev_response.get("lines") or []))


from ff_guillotine import normalize_name

_PAREN = re.compile(r"\s*\([^)]*\)\s*$")

def norm_player(name: str) -> str:
    """Canonical key for joining a book's quote to its anchor line.

    USE THIS FOR THE ODDS -> ANCHOR JOIN. It is the one join in the live
    intake path that has to happen on a name, and it has already cost a
    player his whole board.

    D13 recorded that the HISTORICAL endpoints carry no player_id and said
    "just live get_odds has the id". Measured 2026-11-02: live
    get_event_ev has no player_id either — only `description` — while
    get_odds does. So the anchor join is name-keyed on the live path too,
    and the never-join-on-a-name rule has a second and larger hole than
    D13 describes, at exactly the point boost intake needs it.

    It bites inside one response. On event 87238 the EV payload carried
    BOTH spellings at once:

        Brian Thomas Jr.  reception_yds  9.5   anchor kalshi
        Brian Thomas      reception_yds  10.5  anchor pinnacle

    DraftKings and FanDuel both priced him at 10.5, so a raw-name join
    found only the kalshi 9.5 rows and his entire DK/FD board went
    unanchored. normalize_name() — built for B1, the phantom-player bug —
    already collapses both to "brian thomas". The intake path simply was
    not using it.

    Also strips a trailing parenthetical: Bovada writes
    "Garrett Wilson (NYJ)" where DraftKings writes "Garrett Wilson".

    What it does NOT fix, and must not be trusted to: first-name variants
    such as Josh/Joshua Palmer, which are different strings all the way
    down. Resolve those through propline_search_players on an exact
    known_names match, as the instructions require.
    """
    return normalize_name(_PAREN.sub("", str(name).strip()))

def flatten_odds(response: dict,
                 line_type: str = "main",
                 market: str | None = None,
                 player: str | None = None) -> list[dict]:
    """Turn a `propline_get_odds` event response into screenable quotes.

    THE MISSING ADAPTER. `get_odds` returns bookmakers[].markets[].outcomes[],
    one row per outcome; `screen_quotes` and `prop_edge` want one dict per
    book carrying both sides. Nothing bridged them, and feeding the native
    shape straight in silently misread an Under price as an Over price.

    Returns one dict per (book, market, player, line) with `over`/`under`
    paired, plus the fields the screen needs: `suspended_at` from the market,
    `pregame_only` from the bookmaker, and `last_update`.

    **`over_liquidity` / `under_liquidity` are carried per SIDE (B92).**
    Kalshi quotes resting money per contract and the two sides of one line
    can differ by orders of magnitude, so a single per-line number would be
    a fiction. `None` means the book never reported liquidity — DraftKings
    0/276, FanDuel 0/204, Bovada — which is a different state from zero and
    must not be collapsed into it. This field exists because dropping it was
    the one reason left to hand-roll a walk of
    bookmakers[].markets[].outcomes[], which bypasses everything below.

    `line_type` defaults to "main" — a book's primary two-sided line.
    "milestone" rungs are one-sided by construction (one N+ outcome each) and
    come back with `under=None`, which `screen_quotes` flags rather than
    pricing. One row per rung: a real board posts 28 for a starting QB at
    DraftKings, not the one the first fixture here carried. Each rung carries
    its label in `rung`, its parsed threshold in `rung_threshold`, and
    `line=None`.

    This stays a TRANSLATION. It does not decide that a rung and a main line
    are the same bet, because filtering by `line_type` means it never sees
    both in one call — use `canonical_bet()` wherever the two lists are
    merged.
    """
    out: list[dict] = []
    for bk in response.get("bookmakers") or []:
        # B78. `book_key` first so a chain book carrying only a `title`
        # is named the way the chain names it; the raw title is kept as a
        # last resort because this one is for the reader, not for a match.
        book = book_key(bk) or bk.get("title") or bk.get("key") or "?"
        for mk in bk.get("markets") or []:
            if line_type and mk.get("line_type") != line_type:
                continue
            if market and mk.get("key") != market:
                continue
            groups: dict[tuple, dict] = {}
            for oc in mk.get("outcomes") or []:
                who = oc.get("description") or oc.get("name") or "?"
                if player and player.lower() not in str(who).lower():
                    continue
                label = str(oc.get("name") or "").strip().lower()
                # B49. The key was (player, point). Every milestone rung
                # carries point=None, so all of one player's rungs at one book
                # collapsed into a single group, each took the `else` branch
                # below as an "over", and the second one tripped the same-side
                # guard. The guard was right; the key was wrong.
                #
                # The widening applies ONLY to the one-sided path. Whenever
                # `point` is not None the key is exactly what it always was,
                # because this is the code the B24 Under/Over swap lived in
                # and the two-sided guard must not weaken by a hair.
                #
                # The third component is the parsed THRESHOLD, not the label:
                # a book posting both "238+ Passing Yards" and an equivalent
                # label for the same rung is a genuine duplicate and must
                # still raise. The raw label is the fallback only when the
                # grammar does not parse, so unparseable rungs still separate
                # instead of colliding.
                rung_label = None
                rung_t = None
                if oc.get("point") is None and "+" in str(oc.get("name") or ""):
                    rung_label = oc.get("name")
                    rung_t = rung_threshold(rung_label)
                key = (who, oc.get("point"),
                       rung_t if rung_t is not None else rung_label)
                g = groups.setdefault(key, {
                    "book": book,
                    "market": mk.get("key"),
                    "player": who,
                    # Carried, not dropped. After three separate name-matching
                    # bugs this project's standing rule is never to join
                    # player data on a name — and an adapter that discards the
                    # id forces exactly that. Not universally present:
                    # DraftKings' anytime-TD board has player_id null for some
                    # entries and for D/ST, so expect None and fall back.
                    "player_id": oc.get("player_id"),
                    "line": oc.get("point"),
                    "over": None,
                    "under": None,
                    # B92. Carried per SIDE, because Kalshi quotes resting
                    # money per contract and the two sides of one line can
                    # differ by orders of magnitude. Dropping it was the
                    # reason a session hand-rolled its own walk of
                    # bookmakers[].markets[].outcomes[] to get anchor depth —
                    # bypassing the outcome pairing, the line_type filter,
                    # the Over/Under label matching and the price-key
                    # fallbacks that live in this function. B82 is about
                    # those hand-rolls; this removes one reason to write
                    # them rather than warning against it. None means the
                    # book never reported liquidity (DraftKings 0/276,
                    # FanDuel 0/204, Bovada), which is a different state
                    # from zero and must not become it.
                    "over_liquidity": None,
                    "under_liquidity": None,
                    "line_type": mk.get("line_type"),
                    "suspended_at": mk.get("suspended_at"),
                    "pregame_only": bk.get("pregame_only"),
                    "last_update": oc.get("last_seen_at") or mk.get("last_update")
                                   or bk.get("last_update"),
                    "outcome_names": [],
                    "unknown_labels": [],
                    # DFS books price a leg at a multiplier; 1.0 is a standard
                    # pick, 1.5 a boost, 0.75 a discount. Dropping it made a
                    # boosted DFS leg indistinguishable from a standard one.
                    "payout_multiplier": oc.get("payout_multiplier"),
                })
                price = _num(oc.get("price"))
                g["outcome_names"].append(oc.get("name"))
                if oc.get("payout_multiplier") is not None:
                    g["payout_multiplier"] = oc.get("payout_multiplier")

                if label in UNDER_NAMES:
                    side = "under"
                elif label in OVER_NAMES:
                    side = "over"
                else:
                    # NOT silently the over. An unrecognised label on a market
                    # that should pair two sides is the B24 signature all over
                    # again — a plausible number instead of an error. A
                    # synthetic `{"name": "Mystery Label", "price": -250}`
                    # came back as over=-250 with nothing to show for it.
                    #
                    # Unrecognised labels ARE legitimate on one-sided boards:
                    # anytime-TD names the player, a milestone names its rung
                    # ("280+ Passing Yards"). Those carry point=None. A market
                    # WITH a point is an Over/Under, so a strange label there
                    # is recorded and surfaced.
                    side = "over"
                    if oc.get("point") is not None:
                        g["unknown_labels"].append(oc.get("name"))
                    elif rung_label is not None:
                        # Both keys are set ONLY on a rung. Absence is the
                        # signal that a row is not one — B31 asserts a player
                        # name on a one-sided board leaves `rung` absent, not
                        # None — so neither is pre-seeded in the group above.
                        #
                        # The threshold is DERIVED from the label, and `line`
                        # is a point a book posted. Writing 238.0 into `line`
                        # would make the two indistinguishable, and the next
                        # thing that happens to `line` is a join against the
                        # EV grid — D18 with a new way in. `line` stays None
                        # on a rung; the number lives here.
                        g["rung"] = rung_label
                        g["rung_threshold"] = rung_t
                    else:
                        # A player name on a one-sided board. Previously
                        # written into `rung`, which made "Ameer Abdullah"
                        # look like a threshold.
                        g["outcome_label"] = oc.get("name")

                if g[side] is not None:
                    raise ValueError(
                        f"two outcomes claim the same side of "
                        f"{mk.get('key')} / {who} / {oc.get('point')} at "
                        f"{book}: {g['outcome_names']}. One of them was "
                        f"misclassified, so neither price can be trusted.")
                g[side] = price
                g[f"{side}_liquidity"] = _num(oc.get("liquidity"))

            for g in groups.values():
                if g["unknown_labels"]:
                    g["label_warning"] = (
                        f"unrecognised outcome label(s) "
                        f"{g['unknown_labels']} on a market with a line "
                        f"({g['line']}) — priced as the OVER, which may be "
                        f"wrong. Check the raw response before betting it.")
            out += list(groups.values())
    return out


@dataclass
class QuoteScreen:
    """What survived the screen, and why the rest did not."""
    usable: list[dict] = field(default_factory=list)
    dropped: list[tuple[str, str]] = field(default_factory=list)   # (book, reason)
    scratch_risk: bool = False
    suspended_books: list[str] = field(default_factory=list)
    one_sided: list[str] = field(default_factory=list)

    def describe(self) -> str:
        L = [f"{len(self.usable)} usable quote(s)"]
        if self.scratch_risk:
            L.append(f"  ** PROBABLE SCRATCH ** suspended at "
                     f"{len(self.suspended_books)} books: "
                     f"{', '.join(self.suspended_books)}")
            L.append("     Do not bet this leg. Check the injury report — the "
                     "books know something the wire has not printed yet.")
        if self.one_sided:
            L.append(f"  one-sided (cannot be de-vigged): "
                     f"{', '.join(self.one_sided)}")
            L.append("     Price these only against an external fair line — "
                     "pass fair_over from get_event_ev.")
        for book, why in self.dropped:
            L.append(f"  dropped {book}: {why}")
        return "\n".join(L)


def screen_quotes(quotes: list[dict],
                  game_started: bool = False,
                  max_age_s: float | None = None,
                  now: float | None = None) -> QuoteScreen:
    """Drop quotes that are not safe to price off, and surface scratch risk.

    `quotes` are the per-book entries from propline_get_odds — each a dict
    that may carry `book`/`sportsbook`, `suspended_at`, `pregame_only`,
    `last_update`/`updated_at`/`timestamp`, and the prices.

    Call this BEFORE prop_edge. An edge computed against a suspended or
    stale quote is a number about a price nobody will take.
    """
    import datetime as _dt

    def _ts(v) -> float | None:
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return float(v)
        try:
            return _dt.datetime.fromisoformat(
                str(v).replace("Z", "+00:00")).timestamp()
        except (ValueError, TypeError):
            return None

    now = now if now is not None else _dt.datetime.now(_dt.timezone.utc).timestamp()
    if max_age_s is None:
        max_age_s = LIVE_MAX_AGE_S if game_started else PREGAME_MAX_AGE_S

    out = QuoteScreen()
    for q in quotes:
        book = str(q.get("book") or q.get("sportsbook") or q.get("name") or "?")

        if q.get("suspended_at"):
            out.suspended_books.append(book)
            out.dropped.append((book, "market suspended by the book"))
            continue

        if game_started and q.get("pregame_only"):
            out.dropped.append((book, "pregame_only book, game is live — this "
                                      "is its last pregame quote, not a price"))
            continue

        age = None
        for k in ("last_update", "updated_at", "timestamp", "last_updated"):
            t = _ts(q.get(k))
            if t is not None:
                age = now - t
                break
        if age is not None and age > max_age_s:
            out.dropped.append((book, f"stale: {age/60:.1f} min old "
                                      f"(limit {max_age_s/60:.1f} min)"))
            continue

        # A quote with no price is the deadest quote there is, and letting one
        # through defeated the entire point of this screen. Bovada's anytime-TD
        # market is one-sided — 31 outcomes, one per player, no "No" side — so
        # it arrived with over=None, under=None, passed as usable, and then
        # killed prop_edge with a TypeError inside american_to_prob.
        over, under = _prices(q)
        if over is None and under is None:
            out.dropped.append((book, "no price in the quote — nothing to "
                                      "price off"))
            continue
        if over is None or under is None:
            # EITHER side missing means the market cannot be de-vigged, so
            # anything priced off it needs an external fair line. Checking
            # only `under` missed the Under-only case, which arrives whenever
            # a native outcome row is screened without being paired first.
            # B122. This appended only the BOOK, so on a 32-row anytime-TD
            # board `describe()` printed "draftkings" thirty-two times and
            # could not say WHICH leg was one-sided — the only thing you
            # want from it on a mixed board. The player and market come
            # along now, deduped, and the book is kept because a leg
            # one-sided at one book may be two-sided at another.
            _who = " ".join(str(x) for x in
                            (q.get("player"), q.get("market"),
                             q.get("point"))
                            if x not in (None, ""))
            _entry = f"{_who} @{book}" if _who else book
            if _entry not in out.one_sided:
                out.one_sided.append(_entry)

        if q.get("label_warning"):
            # A strange outcome label on a market that carries a line means
            # the side assignment is a guess. Priced as the over, flagged
            # here, and NOT quietly usable.
            out.dropped.append((book, q["label_warning"]))
            continue

        out.usable.append(q)

    out.scratch_risk = len(out.suspended_books) >= SCRATCH_BOOKS
    return out


def field_from_odds(response: dict, *, market: str, book: str,
                    line_type: str | None = None) -> dict:
    """`{normalised name: american}` for ONE book's mutually exclusive field.

    B82. THE HAND-ROLL THIS EXISTS TO REPLACE. A session needing a First TD
    field to pass to `devig_field` wrote its own walk of
    `bookmakers[].markets[].outcomes[]`, keyed a dict on the outcome name,
    and got **booksum 20.99** — because Kalshi posts that board two-sided
    (28 Yes / 22 No) and last-write-wins kept the **No** price, at numbers
    like -4900, for every player quoted both ways. On an Over/Under board
    the same code merely POLLUTES: keying on name alone discards the point,
    so thirteen milestone rungs joined one player's main line and produced
    13 outcomes at booksum 2.9756 where a real two-sided line is ~1.07.

    Neither failure was necessary. `flatten_odds` already pairs the
    outcomes, filters `line_type`, matches Over/Under labels through
    OVER_NAMES/UNDER_NAMES — **which include "yes" and "no"** — and falls
    back across the price keys. The hand-roll bypassed the one function that
    solves all of it. So this is deliberately thin: its value is that it
    exists and is the obvious thing to reach for.

    What it refuses, rather than guessing:

    * a market that is not mutually exclusive, named early and with a
      better message than `devig_field` can give after the fact
    * two outcomes whose names NORMALISE to the same key — that is the
      ambiguity the 20.99 came from, and taking either one is the bug
    * a row with no affirmative price
    * an empty field, naming the book and market asked for, because a
      silent `{}` becomes "this book doesn't carry it" when the real cause
      is a misspelled book key

    Names come back through `norm_player`, so the result joins to anchors
    and to `build_meta` without a second name bug — "Chris Rodriguez Jr."
    and "Chris Rodriguez" land on one key, which is B44. The no-scorer row
    survives it (`"No Touchdown Scorer"` -> `"no touchdown scorer"`, which
    is in NO_SCORER_NAMES), so `devig_field`'s completeness check still
    works on the output.

    `line_type` defaults to None — no filter — because a mutually exclusive
    field is not a main/milestone distinction and real boards label it
    inconsistently. Rungs cannot leak in regardless: they only exist on
    yardage markets, which the exclusivity guard rejects first.
    """
    if market not in MUTUALLY_EXCLUSIVE_MARKETS:
        raise ValueError(
            f"{market!r} is not a mutually exclusive field, so there is no "
            f"field to build. Mutually exclusive markets: "
            f"{sorted(MUTUALLY_EXCLUSIVE_MARKETS)}. For a two-sided market "
            f"use two_sided_field(), which returns one line's Over/Under.")

    rows = [r for r in flatten_odds(response, line_type=line_type,
                                    market=market)
            if r["book"] == book]
    if not rows:
        books = sorted({(book_key(bk) or bk.get("title")
                         or bk.get("key") or "?")
                        for bk in response.get("bookmakers") or []})
        raise LookupError(
            f"no {market} outcomes for book {book!r} in this payload. Books "
            f"present: {books}. An empty field reads as 'this book does not "
            f"carry the market' when the usual cause is a misspelled key.")

    field: dict[str, float] = {}
    source: dict[str, str] = {}
    for r in rows:
        raw = r.get("outcome_label") or r["player"]
        key = norm_player(raw)
        price = r["over"]
        if price is None:
            raise ValueError(
                f"{raw!r} has no affirmative price in {book}'s {market} "
                f"(row: over={r['over']}, under={r['under']}). On a Yes/No "
                f"board the Yes side is the one a field needs; a row "
                f"carrying only the No side is not something to invert.")
        if key in field:
            raise ValueError(
                f"two outcomes in {book}'s {market} normalise to {key!r}: "
                f"{source[key]!r} at {field[key]:+.0f} and {raw!r} at "
                f"{price:+.0f}. Taking either one is how a hand-rolled "
                f"version of this produced a booksum of 20.99 — the field "
                f"is ambiguous and cannot be de-vigged until it is "
                f"resolved.")
        field[key] = float(price)
        source[key] = raw
    return field


def two_sided_field(response: dict, *, market: str, book: str,
                    player: str) -> tuple[dict, float | None]:
    """One book's single two-sided line: `({"Over": am, "Under": am}, line)`.

    B82, the other half. Built on `flatten_odds` for the same reason as
    `field_from_odds` — it already does the outcome pairing, the
    `line_type` filter, the Over/Under label matching and the price-key
    fallbacks, and every hand-rolled version has reproduced a bug it
    already fixes.

    Deliberately refuses rather than returning something usable-looking:

    * more than one main line for that player at that book, because
      choosing one silently is how a rung gets mistaken for the main line
      (`"29+ Receiving Yards"` at -116 IS `Over 28.5` at -116, the same
      wager, while `"30+"` at -108 happens to match the main UNDER's price
      and is a different bet entirely)
    * a one-sided market, which cannot be de-vigged two-way
    * a suspended market, which is not bettable

    `player` matches as a case-insensitive substring, the same contract
    `flatten_odds` uses, so pass enough of the name to be unambiguous.
    """
    rows = [r for r in flatten_odds(response, line_type="main", market=market,
                                    player=player)
            if r["book"] == book]
    if len(rows) != 1:
        detail = ", ".join(f"{r['player']} @ {r['line']}" for r in rows) or "none"
        raise LookupError(
            f"expected exactly one main {market} line for {player!r} at "
            f"{book}, got {len(rows)}: {detail}. More than one means the "
            f"player match is ambiguous; zero means the book, market or "
            f"spelling is wrong.")
    r = rows[0]
    if r["over"] is None or r["under"] is None:
        raise ValueError(
            f"{player!r} at {book} is one-sided on {market} "
            f"(over={r['over']}, under={r['under']}), so it has no two-way "
            f"price to de-vig. A milestone rung looks like this.")
    if r["suspended_at"] is not None:
        raise ValueError(
            f"{player!r} at {book} was suspended at {r['suspended_at']} — "
            f"not bettable, so its price is not a price.")
    return {"Over": float(r["over"]), "Under": float(r["under"])}, r["line"]


# ---------------------------------------------------------------------------
# Milestone ladders
# ---------------------------------------------------------------------------
#
# A milestone ladder ("10+ Receiving Yards", "20+", "30+" ...) is ONE-SIDED by
# construction, so `devig` cannot touch it: there is no Under price to carry
# information about how the margin is distributed. That is why this project
# could read rungs (`flatten_odds(line_type="milestone")`) long before it
# could price one.
#
# The way in is that a ladder is MONOTONE and it crosses the same book's own
# two-sided main line. Where it crosses, the book has quoted the same event
# twice — once with vig visible (the main pair de-vigs) and once with the vig
# baked in (the rung) — and the ratio measures that book's ladder margin
# directly. Measured on a Vikings/Bills board: DraftKings +5.58% (sd 0.74%,
# n=15), FanDuel +6.54% (sd 0.26%, n=12).
#
# NOTHING HERE IS A HARD-CODED MARGIN. Those two numbers came from fourteen
# players in one game, and B53's lesson is that a constant's SIZE is not its
# COVERAGE — a margin frozen in source would be re-verified against every
# future board by hand, or more likely not at all. So the margin is MEASURED
# AT RUNTIME off whatever board is in front of it: every player carrying both
# a ladder and that book's own main line is one observation, and the median
# across the board is the estimate. A board too thin to measure returns None.
#
# THE ANCHOR CHAIN IS ABSENT FROM LADDERS. On that same board DraftKings
# posted 182 milestone outcomes and FanDuel 132; Pinnacle posted 22 main-line
# outcomes and ZERO milestone, and Polymarket, Kalshi, Bovada and Smarkets
# were not on the board at all. So a rung can never be anchored the way this
# project anchors everything else, and pretending otherwise would make
# `anchor_untested` mean two different things.
#
# What resolves it is that the anchor and the ladder answer DIFFERENT
# questions. The anchor sets the LEVEL (where the player's distribution sits)
# and the ladder supplies the SHAPE (how it falls away). So the ladder is
# de-vigged with its own measured margin and then PINNED so it agrees with
# the anchor at the anchor's point. The fair probability of a rung is read off
# that pinned curve, and `fair_source` records both halves, because a curve
# whose level came from Pinnacle and whose shape came from DraftKings is
# neither one of them.
#
# The pin is a shift in the THRESHOLD domain, not in probability. An additive
# shift in probability leaves the bounds (a rung can come out above 1), and a
# multiplicative one distorts a survival curve by a constant ratio it has no
# reason to obey. A level disagreement IS a yards disagreement: "DraftKings'
# ladder sits 1.8 yards above Pinnacle's level" is the statement being made,
# it keeps the curve a valid survival function for free, and the shift is
# reportable in the units the bet is denominated in.
#
# Interpolation between rungs is LINEAR IN LOG-ODDS, not in probability.
# Measured by hold-one-out on real ladders — drop an interior rung, rebuild it
# from its neighbours, compare against the price the book actually posted,
# 253 rungs: probability-linear missed by a median 0.572% in the tail
# (q < 15%) and 0.739% in the core; logit-linear missed by 0.137% and 0.521%.
# Logit is 4.2x better where the recommendation value is. The earlier
# probability-linear reading of the ladder margin's dispersion was therefore
# measuring its own interpolation error as much as the book's.
#
# NO RUNG IS EXTRAPOLATED. Outside the span the book actually posted there is
# no curve, and inventing one is D18 with a new way in — a fair probability
# for a point nobody quoted. `ladder_fair` refuses instead.

# An observation count below this is not a median, it is an anecdote. Four is
# the floor at which the dispersion gate below can fail for the right reason;
# the real boards measured 15 and 12.
LADDER_MARGIN_MIN_N = 4

# Dispersion above which the median is not a measurement of one thing. The
# two measured books came in at 0.74% and 0.26% AFTER the logit correction,
# so this sits well clear of them and still catches a board where the
# crossings disagree about what the margin even is.
LADDER_MARGIN_MAX_SD = 0.025

# A per-rung margin outside this range is not a margin. Negative is an arb
# inside one book, which does not happen (`two_sided_hold` refuses the same
# thing for the same reason); above 30% and the "ladder" is a different kind
# of product, or the main line being crossed belongs to another market.
LADDER_MARGIN_PLAUSIBLE = (0.0, 0.30)

# A rung whose own uncertainty is this large a FRACTION of its probability is
# not priceable. This is the one judgment call in the block and it is here as
# a named constant so it can be reverted and re-measured rather than argued
# about: cross-book agreement on de-vigged rungs ran ~1.1pp absolute in the
# deep tail, which at a 4% rung is a quarter of the whole number. Absolute
# accuracy holding up into the tail (1.14% vs 0.88% in the core, only 1.30x)
# does NOT mean relative accuracy does, and it is the relative figure that
# decides whether an edge survives.
LADDER_MAX_REL_UNCERTAINTY = 0.25

# A level disagreement this large in probability points gets flagged. The pin
# ABSORBS the gap by construction — that is what it is for — so without a flag
# a book whose ladder disagrees with the anchor about the player would price
# exactly like one that agrees, and the disagreement would be invisible in the
# output. 3pp is roughly three times the measured cross-book agreement on
# de-vigged rungs (median 0.94%, mean 1.43% over 119 shared rungs), which is
# the level at which a gap stops looking like two books rounding differently.
LADDER_LEVEL_GAP_FLAG = 0.03

# Below this much variation in the book's OWN de-vigged main lines, the
# margin's denominator is effectively a constant and its dispersion stops
# being a measure of how well the margin is known.
#
# Measured on one board: DraftKings' own-main fair ran 0.3366..0.5122 (sd
# 0.0485) while FanDuel's was EXACTLY 0.5000 on all twelve crossings (sd
# 0.0000) — FanDuel posts symmetric pairs on this market. FanDuel's margin
# then came back with an sd of 0.34% against DraftKings' 1.06%, which reads as
# the better-measured number and is the opposite: the only thing varying in it
# is the ladder, because the denominator never moves. The gate sits two orders
# of magnitude clear of both.
#
# This is a second instance of something already settled in this project
# rather than a new discovery: Pinnacle quoting -114/-114 across a yardage
# board was isolated and confirmed as genuine book behaviour, not a data
# artifact. What is new is that it also costs the ladder margin's error bar,
# because that sd is propagated into every rung's uncertainty.
LADDER_FLAT_DENOMINATOR_SD = 0.005

# The anchor's resting money, below which its level is an opinion rather than
# a price. DELIBERATELY DUPLICATED from `ff_boost.THIN_ANCHOR_LIQUIDITY`, the
# same way `ff_guillotine` duplicates the correlation table: `ff_boost`
# imports from `ff_props`, so importing back is circular. Keep the two in
# step by hand.
#
# This exists because the first live test of the ladder found the gap it
# fills. On a Week 10 board (WAS@NYG) Pinnacle was absent entirely, every fair
# pinned to Kalshi, and of 158 rungs whose anchor could be joined back,
# **every single one** had a resting side at or under $25 — min $1.30, median
# $5.25, max $19.50. The ladder printed `fair 80.01% +/- 1.02%` off $1.30 with
# nothing warning anyone. The +/- is a real measurement of the MARGIN and
# says nothing about the LEVEL, and on that board the level was noise.
#
# F12's original entry predicted exactly this — "alternates and rungs would
# anchor off Kalshi contracts carrying a dollar or two, the exact input B46
# exists to reject" — and the ladder work answered the de-vig and the
# level-SOURCE questions while carrying none of the anchor-maturity machinery
# across. `anchor_thin`, `anchor_opening` and `anchor_untested` all live on
# `BoostLeg`, which this path never touches.
LADDER_THIN_ANCHOR_LIQUIDITY = 25


def _logit(p: float) -> float:
    p = min(max(float(p), 1e-9), 1.0 - 1e-9)
    return math.log(p / (1.0 - p))


def _expit(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


@dataclass
class LadderMargin:
    """What one book charges on its milestone ladder, measured on this board.

    `margin is None` means NOT MEASURED, which is a different state from zero
    and must not become it — B39/D16's rule, that an unchecked state must not
    look like a checked one, applied to the one number the rest of this block
    divides by.
    """
    book: str
    margin: float | None
    n: int
    sd: float
    why: str
    observations: list[tuple] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    # Spread of the book's OWN de-vigged main lines across the crossings. When
    # this is ~0 the book posts symmetric pairs, `sd` above is measuring the
    # ladder against a constant, and it understates how well the margin is
    # known. Carried rather than folded into `sd` so the two stay separable.
    denominator_sd: float = float("nan")

    @property
    def measured(self) -> bool:
        return self.margin is not None

    @property
    def flat_denominator(self) -> bool:
        """True when the book's own main lines carry no level variation."""
        return (self.denominator_sd == self.denominator_sd
                and self.denominator_sd < LADDER_FLAT_DENOMINATOR_SD)

    def describe(self) -> str:
        if not self.measured:
            return f"{self.book}: ladder margin NOT measured — {self.why}"
        s = (f"{self.book}: ladder margin {self.margin:+.2%} "
             f"(median of {self.n} own-main crossings, sd {self.sd:.2%})")
        if self.flat_denominator:
            s += (f"\n  ! {self.book} posts symmetric main lines here "
                  f"(own-fair sd {self.denominator_sd:.4f}), so that "
                  f"{self.sd:.2%} is the ladder varying against a constant "
                  f"0.5 and UNDERSTATES the margin's error")
        return s


@dataclass
class LadderFair:
    """The fair probability of one rung, with every input that produced it."""
    book: str
    player: str
    threshold: float          # the N of "N+", as posted
    canonical_line: float     # the equivalent main line: N - 0.5
    price: float | None
    q_raw: float | None       # implied by the price, vig included
    fair: float | None        # de-vigged AND level-pinned; None when refused
    uncertainty: float | None  # 1 sd on `fair`, propagated
    margin: float | None
    level_shift: float | None  # the pin, in log-odds
    anchor: str | None
    anchor_point: float | None
    anchor_fair: float | None
    # Book minus anchor at the anchor's own point, in probability points. The
    # pin removes this from the fair; the flag reports it, because a level
    # disagreement that got silently absorbed is the one thing the pinning
    # design is most likely to hide.
    level_gap: float | None = None
    # The anchor's SHALLOW-side liquidity at the point the level was pinned
    # to; None when the anchor reported none. Carried so a rung leg can say
    # whether its level is a price or an opening prior — the second live run
    # found 121 of 306 rungs pinned to an exact 0.5000 on opening-limit
    # money with no flag able to fire, because this was computed here for
    # the `anchor THIN` flag and then thrown away.
    anchor_liquidity: float | None = None
    player_id: object = None
    fair_source: str = ""
    flags: list[str] = field(default_factory=list)
    why: str = ""

    @property
    def priceable(self) -> bool:
        return self.fair is not None

    def describe(self) -> str:
        head = f"{self.player} {self.threshold:g}+ @{self.book}"
        if not self.priceable:
            return f"{head}: NOT PRICEABLE — {self.why}"
        s = (f"{head}: fair {self.fair:.1%} +/- {self.uncertainty:.1%} "
             f"(price implies {self.q_raw:.1%})")
        if self.flags:
            s += "  [" + ", ".join(self.flags) + "]"
        return s


def _anchor_index(quotes: list[dict]) -> tuple[dict, dict]:
    """Index anchor-side quotes by player_id AND by normalised name."""
    by_id: dict[str, list[dict]] = {}
    by_name: dict[str, list[dict]] = {}
    for q in quotes:
        pid = q.get("player_id")
        if pid is not None:
            by_id.setdefault(str(pid), []).append(q)
        by_name.setdefault(norm_player(str(q.get("player") or "")),
                           []).append(q)
    return by_id, by_name


def _anchor_for(pid, name: str, by_id: dict,
                by_name: dict) -> tuple[list[dict], str]:
    """The anchor rows for one player, preferring the player_id join.

    B44/B101's rule is never to join player data on a raw name. The first
    version of this joined on the TUPLE `(player_id, player)`, which obeys
    the letter of that rule and fails in a new way: `player_id` is routinely
    absent — `flatten_odds`' own docstring notes DraftKings' anytime-TD board
    carries null ids — so when the ladder's book reports an id and the
    anchor's book does not, the tuples differ and the join silently MISSES.
    A miss is refused rather than mispriced, so it is not dangerous, but it
    costs anchor coverage invisibly, which is the one thing B60 exists to
    stop. The real board hid it: DraftKings and Pinnacle both carried ids.

    So: UNION the id index and the name index rather than trying them in
    order. Short-circuiting on the id was the first attempt and it found the
    ladder's OWN book's main line — same payload, same id — and returned
    before the name index could offer the anchor's title-only row, which
    carries no id at all. Rows whose id actively conflicts are excluded — two players really can share a name, and `norm_player` exists
    because one of them already lost his whole board to this join.
    """
    cand = by_name.get(name, [])
    ids = {str(c["player_id"]) for c in cand
           if c.get("player_id") is not None}
    # Two DIFFERENT players sharing one normalised spelling. An anchor row
    # with no id is then unattributable — it could be either of them — so it
    # is dropped rather than guessed.
    ambiguous = len(ids) > 1
    out, seen, dropped = [], set(), 0
    for c in cand:
        cid = c.get("player_id")
        cid = None if cid is None else str(cid)
        if pid is not None and cid is not None and cid != str(pid):
            dropped += 1
            continue
        if cid is None and ambiguous:
            dropped += 1
            continue
        if id(c) not in seen:
            seen.add(id(c))
            out.append(c)
    # A row the id index knows but the name index does not: the two books
    # spell him differently enough that `norm_player` did not collapse them.
    # The id is the stronger key, so it wins.
    if pid is not None:
        for c in by_id.get(str(pid), []):
            if id(c) not in seen:
                seen.add(id(c))
                out.append(c)
    if not out:
        if dropped:
            return [], (f"{dropped} anchor row(s) match the name but belong "
                        f"to a different player_id than {pid} — two players "
                        f"share this spelling, so the join is refused rather "
                        f"than guessed")
        return [], "no anchor row for this player under id or name"
    by = "player_id" if (pid is not None and str(pid) in by_id) else "name"
    note = f"joined on {by}"
    if dropped:
        note += f", {dropped} same-name row(s) excluded on a conflicting id"
    return out, note


def ladder_margin(quotes: list[dict], *, book: str,
                  method: str = "auto") -> LadderMargin:
    """Measure `book`'s milestone margin from its OWN main-line crossings.

    `quotes` must carry BOTH line types for the book, which means two
    `flatten_odds` calls concatenated — it filters by `line_type`, so one call
    can never see both. Passing only one type is the likely mistake and it is
    reported as such rather than returning a confident None.

    The margin is measured against the SAME book's main line, never against
    the anchor's. Measuring it against Pinnacle multiplies the book's margin
    by the two books' disagreement about the player, and the result is not a
    margin at all: on a real board that produced James Cook at -1.55%, a
    negative margin, which is an arb inside one book and does not happen. The
    sign was the tell that two quantities had been multiplied together.
    """
    rows = [q for q in quotes if q.get("book") == book]
    if not rows:
        return LadderMargin(book, None, 0, float("nan"),
                            f"no quotes at all for {book!r} in the {len(quotes)} "
                            f"rows passed — check the book key spelling")
    ladders: dict[tuple, dict[float, float]] = {}
    main_rows: list[dict] = []
    for q in rows:
        who = q.get("player")
        key = (q.get("player_id"), norm_player(str(who or "")), who)
        if q.get("line_type") == "milestone":
            t = q.get("rung_threshold")
            p = _num(q.get("over"))
            if t is not None and p is not None:
                # canonical_bet's equivalence, not a new one: a rung at N is
                # exactly "over N - 0.5" because these stats are integers.
                ladders.setdefault(key, {})[float(t) - 0.5] = p
        elif q.get("line_type") == "main" and q.get("line") is not None:
            if _num(q.get("over")) is not None and _num(q.get("under")) is not None:
                main_rows.append(q)

    mains = main_rows
    if not ladders and not mains:
        return LadderMargin(book, None, 0, float("nan"),
                            f"{book} has neither ladders nor two-sided main "
                            f"lines in these rows")
    if not ladders:
        return LadderMargin(book, None, 0, float("nan"),
                            f"{book} has {len(mains)} two-sided main lines but "
                            f"no milestone rungs — pass the output of "
                            f"flatten_odds(line_type='milestone') too")
    if not mains:
        return LadderMargin(book, None, 0, float("nan"),
                            f"{book} has {len(ladders)} ladders but no "
                            f"two-sided main line to cross them against — "
                            f"pass flatten_odds(line_type='main') too")

    obs, rejected = [], []
    by_id, by_name = _anchor_index(main_rows)
    for key, curve in sorted(ladders.items(), key=lambda kv: str(kv[0])):
        pid, nkey, who = key
        found, jwhy = _anchor_for(pid, nkey, by_id, by_name)
        if not found:
            rejected.append(f"{who}: ladder but no own main line — {jwhy}")
            continue
        mn = found[0]
        pt = float(mn["line"])
        own = devig(float(mn["over"]), float(mn["under"]), method)[0]
        q = _ladder_interp(curve, pt)
        if q is None:
            lo, hi = min(curve), max(curve)
            rejected.append(f"{who}: own main {pt:g} is outside the ladder's "
                            f"span {lo:g}..{hi:g} — not extrapolated")
            continue
        # No `own <= 0` guard. `devig` returns a fair probability strictly
        # inside (0, 1) for every one of 192 extreme price pairs across all
        # three methods, so the guard that was here could not fire, and a
        # guard no input can trip is dead code — deleted twice already in
        # this project (B126, B127) for reading as a check that passed.
        m = q / own - 1.0
        lo, hi = LADDER_MARGIN_PLAUSIBLE
        if not lo <= m <= hi:
            rejected.append(f"{who}: implied margin {m:+.2%} outside "
                            f"{lo:.0%}..{hi:.0%}")
            continue
        obs.append((who, pt, own, q, m))

    if len(obs) < LADDER_MARGIN_MIN_N:
        return LadderMargin(
            book, None, len(obs), float("nan"),
            f"only {len(obs)} usable crossing(s), need "
            f"{LADDER_MARGIN_MIN_N}: a median off fewer is an anecdote",
            obs, rejected)

    ms = sorted(o[4] for o in obs)
    med = _median(ms)
    sd = _pstdev(ms)
    den_sd = _pstdev(o[2] for o in obs)
    if sd > LADDER_MARGIN_MAX_SD:
        return LadderMargin(
            book, None, len(obs), sd,
            f"crossings disagree too much to be one margin: sd {sd:.2%} "
            f"above the {LADDER_MARGIN_MAX_SD:.1%} gate, range "
            f"{ms[0]:+.2%}..{ms[-1]:+.2%}. Something other than vig is "
            f"moving these — stale rungs, or a main line from another market.",
            obs, rejected, den_sd)
    return LadderMargin(book, med, len(obs), sd, "measured from own-main "
                        "crossings", obs, rejected, den_sd)


def _median(xs) -> float:
    s = sorted(float(x) for x in xs)
    n = len(s)
    if not n:
        return float("nan")
    h = n // 2
    return s[h] if n % 2 else (s[h - 1] + s[h]) / 2.0


def _pstdev(xs) -> float:
    s = [float(x) for x in xs]
    if len(s) < 2:
        return 0.0
    m = sum(s) / len(s)
    return (sum((x - m) ** 2 for x in s) / len(s)) ** 0.5


def _ladder_interp(curve: dict[float, float], t: float) -> float | None:
    """Implied probability at `t` on a ladder of American prices.

    Linear in LOG-ODDS between the two bracketing rungs — measured 4.2x more
    accurate than probability-linear in the tail by hold-one-out on real
    ladders. Returns None outside the posted span: there is no curve there and
    extrapolating one is D18.
    """
    if not curve:
        return None
    ts = sorted(curve)
    t = float(t)
    if t < ts[0] or t > ts[-1]:
        return None
    qs = {k: american_to_prob(v) for k, v in curve.items()}
    for a, b in zip(ts, ts[1:]):
        if a <= t <= b:
            if t == a:
                return qs[a]
            if t == b:
                return qs[b]
            w = (t - a) / (b - a)
            return _expit(_logit(qs[a]) + w * (_logit(qs[b]) - _logit(qs[a])))
    return qs[ts[-1]]


def _ladder_pin(curve: dict[float, float], margin: float,
                pt: float, target: float) -> tuple[float | None, float, str]:
    """The log-odds shift `c` that makes the de-vigged ladder hit `target`.

    Returns (c, gap, why), `gap` in probability points at the anchor's own
    point. `c` is None when the pin is impossible.

    THE PIN IS A PROPORTIONAL-ODDS SHIFT applied to the whole curve:

        S*(t) = expit(logit(S(t)) + c)

    Closed-form, keeps the curve inside (0, 1) and monotone for free, and —
    the property that decides it — evaluates the ladder ONLY at points the
    book actually posted, plus the anchor's own point.

    A shift in the THRESHOLD domain was the first attempt, because "DraftKings
    sits 1.8 yards above Pinnacle" is the more natural sentence. It fails on
    real boards, and not rarely. Pinnacle's main line frequently coincides
    with a ladder's BOTTOM rung — Aaron Jones at 9.5 against a ladder starting
    at 9.5 — and when the book sits a shade below the anchor there, the
    required shift is NEGATIVE and lands off the end of the posted ladder. The
    solve then fails and takes every rung on that ladder down with it: eight
    good rungs discarded over a 2pp level nudge, and the same for every
    low-volume player whose first rung IS his main line. Refusing was correct
    given the transform; the transform was what needed replacing.

    The equivalent in threshold units is computed separately by
    `_ladder_shift_yards` as a READABLE DIAGNOSTIC ONLY, and is allowed to be
    unavailable without costing the pin. A number that exists for the report
    must never become a number the pricing depends on.
    """
    q = _ladder_interp(curve, pt)
    if q is None:
        lo, hi = min(curve), max(curve)
        return None, float("nan"), (
            f"the anchor's point {pt:g} is outside the ladder's posted span "
            f"{lo:g}..{hi:g}, so there is nothing there to pin to — not "
            f"extrapolated")
    # No range guards on `s` or `target`. `american_to_prob` and `devig` both
    # stay strictly inside (0, 1) at every extreme either can be handed, so
    # the two guards that were here could not fire. Dead code reads as a check
    # that passed, which is the B126/B127 mistake.
    s = q / (1.0 + margin)
    return _logit(target) - _logit(s), target - s, "proportional-odds pin"


def _ladder_shift_yards(curve: dict[float, float], margin: float,
                        pt: float, target: float) -> float | None:
    """The level gap in THRESHOLD units, for the report only.

    Solves S(pt + δ) = target by bisection inside the posted span. Monotone by
    construction, so bisection cannot land on a second root. Returns None when
    the target is not reachable inside the span — common, and harmless here
    because nothing prices off this number.
    """
    ts = sorted(curve)
    lo, hi = ts[0] - pt, ts[-1] - pt
    if lo > hi:
        return None

    def s(d: float) -> float | None:
        qq = _ladder_interp(curve, pt + d)
        return None if qq is None else qq / (1.0 + margin)

    slo, shi = s(lo), s(hi)
    if slo is None or shi is None:
        return None
    if not (min(slo, shi) - 1e-12 <= target <= max(slo, shi) + 1e-12):
        return None
    for _ in range(60):
        mid = (lo + hi) / 2.0
        v = s(mid)
        if v is None:
            return None
        if v > target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def _ladder_interp_error(curve: dict[float, float]) -> float | None:
    """This ladder's OWN interpolation error, by hold-one-out on its rungs.

    Measured rather than assumed, for the same reason the margin is: a figure
    from another board is a figure whose coverage nobody rechecked. Needs at
    least two interior rungs to drop; returns None below that, and the caller
    must then report the fair as uncertainty-unknown rather than exact.
    """
    ts = sorted(curve)
    if len(ts) < 4:
        return None
    errs = []
    for i in range(1, len(ts) - 1):
        t = ts[i]
        sub = {k: v for k, v in curve.items() if k != t}
        pred = _ladder_interp(sub, t)
        if pred is not None:
            errs.append(abs(pred - american_to_prob(curve[t])))
    return _median(errs) if len(errs) >= 2 else None


def ladder_fair(quotes: list[dict], *, book: str,
                anchor: str | None = None,
                method: str = "auto",
                margin: LadderMargin | None = None,
                cross: LadderCross | None = None) -> list[LadderFair]:
    """Fair probability for every rung `book` posts, level-pinned to an anchor.

    `quotes` is the concatenation of `flatten_odds(line_type="main")` and
    `flatten_odds(line_type="milestone")` for one event and market — the
    ladder needs its own book's main line to measure the margin, and the
    anchor's main line to set the level.

    `anchor` defaults to the first `ANCHOR_CHAIN` book that posts a two-sided
    main line for the player. Per-player, not per-board: Pinnacle covering
    nine of twelve players is not Pinnacle covering the board, and B60 is
    about exactly the gap between those two statements.

    Every returned rung is either priceable with its inputs recorded, or
    refused with a reason. None is never a price.
    """
    rows = [q for q in quotes if q.get("line_type") in ("main", "milestone")]
    mg = margin if margin is not None else ladder_margin(
        rows, book=book, method=method)

    ladders: dict[tuple, dict[float, float]] = {}
    prices: dict[tuple, dict[float, dict]] = {}
    anchor_rows: list[dict] = []
    for q in rows:
        who = q.get("player")
        key = (q.get("player_id"), norm_player(str(who or "")), who)
        if q.get("book") == book and q.get("line_type") == "milestone":
            t = q.get("rung_threshold")
            p = _num(q.get("over"))
            if t is not None and p is not None:
                ladders.setdefault(key, {})[float(t) - 0.5] = p
                prices.setdefault(key, {})[float(t) - 0.5] = q
        elif q.get("line_type") == "main" and q.get("line") is not None:
            if _num(q.get("over")) is not None and _num(q.get("under")) is not None:
                anchor_rows.append(q)

    out: list[LadderFair] = []
    by_id, by_name = _anchor_index(anchor_rows)
    for key, curve in sorted(ladders.items(), key=lambda kv: str(kv[0])):
        pid, nkey, who = key
        ierr = _ladder_interp_error(curve)
        cands, join_why = _anchor_for(pid, nkey, by_id, by_name)
        chain = (anchor,) if anchor else ANCHOR_CHAIN
        pick = None
        for name in chain:
            for c in cands:
                # Matched on the quote's own `book`, which `flatten_odds` has
                # ALREADY normalised through `book_key`. A `book_key(c)` call
                # sat here too and was dead: a flattened quote carries neither
                # `key` nor `title`, so it returned None every time while
                # implying a normalisation that happens upstream. Dead code
                # that reads as a safeguard is the B126/B127 fault.
                #
                # That upstream normalisation is what lets a title-only
                # Pinnacle payload — the B60 signature, `key` absent and
                # `title` "Pinnacle" against a lowercase chain — still anchor
                # a ladder here.
                if c.get("book") == name:
                    pick = (name, c)
                    break
            if pick:
                break

        shift = gap = a_pt = a_fair = None
        base_flags: list[str] = []
        refuse = ""
        if not mg.measured:
            refuse = f"ladder margin not measured — {mg.why}"
        elif pick is None:
            have = sorted({str(c.get("book")) for c in cands}) or ["none"]
            refuse = (f"no anchor-chain book posts a two-sided main line for "
                      f"{who} — present: {', '.join(have)} ({join_why}). The "
                      f"ladder gives a shape with no level to pin it to.")
        else:
            a_name, a_row = pick
            a_pt = float(a_row["line"])
            a_fair = devig(float(a_row["over"]), float(a_row["under"]),
                           method)[0]
            shift, gap, pin_why = _ladder_pin(curve, mg.margin, a_pt, a_fair)
            if shift is None:
                refuse = (f"{a_name} puts {who}'s fair at {a_fair:.1%} on "
                          f"{a_pt:g}, but {pin_why}")
            elif abs(gap) >= LADDER_LEVEL_GAP_FLAG:
                yd = _ladder_shift_yards(curve, mg.margin, a_pt, a_fair)
                # The yards figure is a diagnostic and is allowed to be
                # missing. When it is, the gap is still reported in the
                # probability points the pin actually used, rather than the
                # flag going quiet because the prettier number was unavailable.
                where = f", about {yd:+.1f} in {mg.book} line units" if yd is not None else ""
                base_flags.append(
                    f"level gap: {book}'s ladder implies "
                    f"{a_fair - gap:.1%} at {a_pt:g} where {a_name} is fair "
                    f"at {a_fair:.1%} ({gap:+.1%}{where})")

        for t in sorted(curve):
            q_row = prices[key][t]
            price = _num(q_row.get("over"))
            q_raw = american_to_prob(price) if price is not None else None
            rec = LadderFair(
                book=book, player=who, threshold=t + 0.5, canonical_line=t,
                price=price, q_raw=q_raw, fair=None, uncertainty=None,
                margin=mg.margin, level_shift=shift, level_gap=gap,
                anchor=pick[0] if pick else None,
                anchor_point=a_pt, anchor_fair=a_fair, player_id=pid,
                flags=list(base_flags), why=refuse)
            if refuse:
                out.append(rec)
                continue
            # `t` is a rung the book posted, so `q_raw` is the price's own
            # implied probability and cannot be None here: `curve` is built
            # only from rungs whose price parsed. No guard — a guard no input
            # can trip is dead code, which this project has now deleted twice.
            fair = _expit(_logit(q_raw / (1.0 + mg.margin)) + shift)
            # Uncertainty: the margin's own dispersion and the ladder's
            # measured interpolation error, added in quadrature. A rung with
            # too few neighbours to hold one out reports the margin term only
            # and says so, rather than reporting a tighter number than it has.
            mterm = fair * mg.sd / (1.0 + mg.margin)
            terms = [mterm]
            if ierr is None:
                rec.flags.append("interp error unmeasured (ladder too short "
                                 "to hold one out)")
            else:
                terms.append(ierr)
            # The cross-book term is the only one that sees model risk in the
            # pin itself. Without it the propagated figure is about three
            # times too tight in the tail, which makes the deep-tail gate
            # below silently unreachable — a gate that cannot fire is worse
            # than no gate, because it reads as a check that passed.
            # The anchor's depth. B92 carries liquidity PER SIDE because the
            # two sides of one line can differ by orders of magnitude, so the
            # MIN side is what the level rests on — an $18 over against a
            # $0.28 under is a $0.28 anchor. None is "never reported"
            # (DraftKings, FanDuel and Bovada all return null), which is a
            # different state from zero and is flagged as its own thing
            # rather than being read as deep or as thin.
            a_lo = a_hi = None
            if pick is not None:
                sides = [_num(pick[1].get("over_liquidity")),
                         _num(pick[1].get("under_liquidity"))]
                named = [v for v in sides if v is not None]
                if named:
                    a_lo, a_hi = min(named), max(named)
            rec.anchor_liquidity = a_lo
            if a_lo is None:
                rec.flags.append(
                    f"anchor depth UNKNOWN: {rec.anchor} reported no "
                    f"liquidity, so nothing here says whether this level is "
                    f"a price or an opinion")
            elif a_lo <= LADDER_THIN_ANCHOR_LIQUIDITY:
                rec.flags.append(
                    f"anchor THIN: {rec.anchor} rests ${a_lo:g} on its "
                    f"shallow side"
                    + (f" (${a_hi:g} on the other)" if a_hi != a_lo else "")
                    + f", at or under ${LADDER_THIN_ANCHOR_LIQUIDITY}. The "
                    f"+/- below measures the MARGIN and says nothing about "
                    f"the LEVEL, which is what this money is backing")
            if mg.flat_denominator:
                rec.flags.append(
                    f"{book} posts symmetric main lines here, so the margin's "
                    f"{mg.sd:.2%} sd understates its own error")
            if cross is not None and cross.measured:
                terms.append(cross.median)
            else:
                rec.flags.append(
                    "uncertainty is a LOWER BOUND: no cross-book check, so "
                    "it carries no term for the pin's own model risk")
            unc = sum(t ** 2 for t in terms) ** 0.5
            if q_row.get("suspended_at") is not None:
                rec.flags.append(f"suspended at {q_row['suspended_at']}")
            rec.fair = fair
            rec.uncertainty = unc
            rec.fair_source = (f"level {rec.anchor}, shape {book} ladder "
                               f"(margin {mg.margin:+.2%})")
            if fair > 0 and unc / fair > LADDER_MAX_REL_UNCERTAINTY:
                rec.flags.append(
                    f"deep tail: +/-{unc:.1%} is "
                    f"{unc / fair:.0%} of a {fair:.1%} rung, over the "
                    f"{LADDER_MAX_REL_UNCERTAINTY:.0%} gate — the "
                    f"uncertainty swamps any edge")
            out.append(rec)
    return out


@dataclass
class LadderCross:
    """Independently-pinned ladders at two books, compared rung by rung.

    This is the only runtime estimate of how wrong a pinned ladder can be for
    reasons the propagated uncertainty cannot see. `ladder_fair` propagates
    the margin's dispersion and the ladder's own interpolation error, and both
    are small — on a real board they come to about 0.4pp on a 3% rung. The
    offline validation put the actual disagreement between two books' pinned
    ladders at 1.14pp in the deep tail, roughly three times that. The
    difference is model risk in the proportional-odds pin itself plus the books
    genuinely disagreeing, neither of which is in the error propagation and
    neither of which can be reasoned about from one ladder.

    Measured rather than taken from that offline run, for the reason nothing
    else here is hard-coded either: a figure from one board is a figure whose
    coverage nobody rechecked.

    The disagreement is treated as CONSTANT IN ABSOLUTE TERMS rather than
    split into bands. Measured, it barely varies — 1.14% in the deep tail
    against 0.88% in the core, a ratio of 1.30 — so one scalar is what the
    data supports, and a band structure would be reading shape into noise.
    What does NOT follow is that the relative error is constant: 1.1pp is a
    third of a 3% rung and a fiftieth of a 50% one, which is exactly why
    `LADDER_MAX_REL_UNCERTAINTY` gates on the ratio.
    """
    books: tuple[str, ...]
    n: int
    median: float | None
    mean: float
    p90: float
    why: str
    players: int = 0

    @property
    def measured(self) -> bool:
        return self.median is not None

    def describe(self) -> str:
        if not self.measured:
            return f"cross-book check NOT measured — {self.why}"
        return (f"cross-book check: {'/'.join(self.books)} disagree by a "
                f"median {self.median:.2%} over {self.n} shared rungs across "
                f"{self.players} player(s) (mean {self.mean:.2%}, "
                f"p90 {self.p90:.2%})")


def ladder_cross_check(quotes: list[dict], *, books: tuple[str, str],
                       anchor: str | None = None,
                       method: str = "auto") -> LadderCross:
    """Price both books' ladders independently and compare the shared rungs.

    Each book is de-vigged by its OWN measured margin and pinned to the SAME
    anchor, so a disagreement that survives is not a margin difference and not
    a level difference. It is the two books disagreeing about the shape, which
    is the quantity the pin cannot check on its own.
    """
    a, b = books
    # A book against ITSELF agrees perfectly by construction, which comes back
    # as a measured disagreement of 0.0 — and that is worse than no check at
    # all: `ladder_fair` would drop its "uncertainty is a LOWER BOUND" flag
    # and add a zero model-risk term, so the output would claim to have been
    # cross-validated by the very ladder it was derived from.
    if a == b:
        return LadderCross(
            (a, b), 0, None, float("nan"), float("nan"),
            f"both books are {a!r}: a ladder agrees with itself by "
            f"construction, so this measures nothing. Pass two different "
            f"books, or no cross-check at all.")
    fa = {(f.player, f.canonical_line): f
          for f in ladder_fair(quotes, book=a, anchor=anchor, method=method)
          if f.priceable}
    fb = {(f.player, f.canonical_line): f
          for f in ladder_fair(quotes, book=b, anchor=anchor, method=method)
          if f.priceable}
    shared = sorted(set(fa) & set(fb))
    if len(shared) < LADDER_MARGIN_MIN_N:
        return LadderCross(
            (a, b), len(shared), None, float("nan"), float("nan"),
            f"only {len(shared)} rung(s) priceable at both {a} and {b}, need "
            f"{LADDER_MARGIN_MIN_N} — one scalar off fewer is an anecdote")
    diffs = sorted(abs(fa[k].fair - fb[k].fair) for k in shared)
    return LadderCross(
        (a, b), len(diffs), _median(diffs),
        sum(diffs) / len(diffs), diffs[int(0.9 * (len(diffs) - 1))],
        "measured from independently-pinned ladders",
        len({k[0] for k in shared}))


def ladder_report(fairs: list[LadderFair], margin: LadderMargin | None = None,
                  *, limit: int | None = None) -> str:
    """Human-readable ladder pricing, refusals included rather than dropped."""
    lines: list[str] = []
    if margin is not None:
        lines.append(margin.describe())
        if margin.rejected:
            lines.append(f"  {len(margin.rejected)} crossing(s) not used:")
            for r in margin.rejected[:6]:
                lines.append(f"    - {r}")
            if len(margin.rejected) > 6:
                lines.append(f"    ... and {len(margin.rejected) - 6} more")
        lines.append("")
    ok = [f for f in fairs if f.priceable]
    no = [f for f in fairs if not f.priceable]
    lines.append(f"{len(ok)} rung(s) priced, {len(no)} refused")
    shown = ok if limit is None else ok[:limit]
    for f in shown:
        lines.append("  " + f.describe())
    if limit is not None and len(ok) > limit:
        lines.append(f"  ... and {len(ok) - limit} more priced")
    if no:
        lines.append("  ! NOT PRICEABLE")
        seen: set[str] = set()
        for f in no:
            if f.why in seen:
                continue
            seen.add(f.why)
            n = sum(1 for g in no if g.why == f.why)
            lines.append(f"    {n} rung(s): {f.why}")
    return "\n".join(lines)
