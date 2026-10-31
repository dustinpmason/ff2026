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

import numpy as np
import pandas as pd

from ff_data import ensure_deps, MIN_TEAMS_COMPLETE_WEEK

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


def bye_weeks(weekly: pd.DataFrame) -> dict[str, int]:
    """Each team's bye, derived from the data: the week in which no player on
    that team recorded a game. Avoids needing a schedule feed to tell a bye
    apart from an absence."""
    df = weekly[weekly.season_type == "REG"] if "season_type" in weekly.columns else weekly

    # Only COMPLETE weeks can reveal a bye. A partially-played week (the data
    # refreshed mid-week, so only Thursday's game is in) makes every team that
    # has not played yet look like it is on bye — this produced "21 teams on
    # bye in Week 8" when only the TNF game had been recorded.
    per_week = df.groupby("week").team.nunique()
    complete = set(per_week[per_week >= MIN_TEAMS_COMPLETE_WEEK].index)
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

    @property
    def flagged(self) -> bool:
        """Only a genuine ROLE change blocks a bet. GAME_SCRIPT is a softer
        signal — the player's share of his offense is intact and team volume
        reverts more readily than a depth-chart position does."""
        return self.verdict in ("COLLAPSED", "EXPANDED")

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
        if self.has_share:
            s += (f"\n  share      : {self.share_baseline:.1%} -> {self.share_recent:.1%} "
                  f"({self.share_ratio:.0%} of baseline); team volume at "
                  f"{self.team_volume_ratio:.0%}")
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


def prop_edge(est: Estimate,
              over_odds: float,
              under_odds: float | None = None,
              fair_over: float | None = None,
              fair_source: str | None = None,
              devig_method: str = "auto") -> Edge:
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
        hold = (devig(over_odds, under_odds, "multiplicative")[2]
                if under_odds is not None else float("nan"))
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
        hold = float("nan")
        used_devig = "none (one-sided price, still vigged)"
    else:
        m = "shin" if devig_method == "auto" else devig_method
        fair_over, _, hold = devig(over_odds, under_odds, m)
        used_devig = m

    p = est.blended
    edge_over = p - fair_over
    side = "OVER" if edge_over >= 0 else "UNDER"
    model_p = p if side == "OVER" else 1 - p
    fair_p = fair_over if side == "OVER" else 1 - fair_over
    edge = abs(edge_over)

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
        supported = ((u.verdict == "COLLAPSED" and side == "UNDER")
                     or (u.verdict == "EXPANDED" and side == "OVER"))
        if not supported:
            return Edge(side=side, model_p=model_p, fair_p=fair_p, edge=edge,
                        ev_per_dollar=ev, hold=hold, kelly=0.0, tier="PASS",
                        reasoning=(f"ROLE CHANGE AGAINST YOU — {u.column} "
                                   f"{u.baseline:.1f} -> {u.recent:.1f} "
                                   f"({u.ratio:.0%}, share {u.share_ratio:.0%}). "
                                   f"The sample describes a role this player no "
                                   f"longer has, and the staleness runs in the "
                                   f"direction of the {side}. Refuse whatever "
                                   f"the edge looks like."),
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
        reasons.insert(0, "edge inside the noise")
    elif edge >= 0.08 and est.sample_verdict == "ADEQUATE" and est.ci_width <= 0.35:
        tier = "STRONG"
    elif edge >= 0.05 and est.sample_verdict != "THIN":
        tier = "MODERATE"
    else:
        tier = "COIN-FLIP"

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
        side = edge.side if edge is not None else "this side"
        veto(f"ROLE CHANGE — {u.column} {u.baseline:.1f} -> {u.recent:.1f} "
             f"(share {u.share_ratio:.0%}). The sample describes a role this "
             f"player no longer has, and it runs against {side}.")
    elif est.usage is not None and est.usage.soft_flagged:
        u = est.usage
        caution(f"team volume at {u.team_volume_ratio:.0%} but share held at "
                f"{u.share_ratio:.0%} — game script, not role loss")

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

    `line_type` defaults to "main" — a book's primary two-sided line.
    "milestone" rungs are one-sided by construction (one N+ outcome each) and
    come back with `under=None`, which `screen_quotes` flags rather than
    pricing.
    """
    out: list[dict] = []
    for bk in response.get("bookmakers") or []:
        book = bk.get("key") or bk.get("title") or "?"
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
                key = (who, oc.get("point"))
                g = groups.setdefault(key, {
                    "book": book,
                    "market": mk.get("key"),
                    "player": who,
                    "line": oc.get("point"),
                    "over": None,
                    "under": None,
                    "line_type": mk.get("line_type"),
                    "suspended_at": mk.get("suspended_at"),
                    "pregame_only": bk.get("pregame_only"),
                    "last_update": oc.get("last_seen_at") or mk.get("last_update")
                                   or bk.get("last_update"),
                    "outcome_names": [],
                })
                price = _num(oc.get("price"))
                g["outcome_names"].append(oc.get("name"))
                if label in UNDER_NAMES:
                    g["under"] = price
                else:
                    g["over"] = price
                    # A milestone rung names its own threshold ("280+ Passing
                    # Yards"); carry it so the caller knows what was priced.
                    if label not in OVER_NAMES:
                        g["rung"] = oc.get("name")
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
            out.one_sided.append(book)

        out.usable.append(q)

    out.scratch_risk = len(out.suspended_books) >= SCRATCH_BOOKS
    return out
