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

import numpy as np
import pandas as pd

from ff_data import ensure_deps

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
    out: dict[str, int] = {}
    allw = set(range(1, int(df.week.max()) + 1))
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


def devig(over_odds: float, under_odds: float) -> tuple[float, float, float]:
    """Remove the book's margin from a two-way market by proportional scaling.

    Returns (fair P(over), fair P(under), hold). Hold is the book's take —
    anything much above ~5% on a player prop is an expensive market to beat.
    """
    po, pu = american_to_prob(over_odds), american_to_prob(under_odds)
    total = po + pu
    return po / total, pu / total, total - 1.0


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


def prop_edge(est: Estimate,
              over_odds: float,
              under_odds: float | None = None,
              fair_over: float | None = None,
              fair_source: str | None = None) -> Edge:
    """Compare the model against a market price and tier the result.

    Tiers follow the convention from Dustin's other copilots — strong /
    moderate / coin-flip / pass — rather than quoting a false-precision number.
    """
    # PREFERRED: a fair probability from a SHARP source, passed in.
    # propline_get_event_ev returns exactly this, anchored per line on
    # Pinnacle / Bovada / Kalshi — pass its value and its `fair_source`.
    #
    # Without it, this de-vigs the price you were quoted, which means using a
    # book as its own reference. That is circular: a recreational book's no-vig
    # line is not the truth, it is that book's opinion plus its shading. Only
    # pass over_odds/under_odds alone when they come from a sharp book.
    if fair_over is not None:
        hold = (devig(over_odds, under_odds)[2]
                if under_odds is not None else float("nan"))
    elif under_odds is None:
        # No two-way price and no external fair line: fall back to the raw
        # vigged number. The edge will read better than it is.
        fair_over = american_to_prob(over_odds)
        hold = float("nan")
    else:
        fair_over, _, hold = devig(over_odds, under_odds)

    p = est.blended
    edge_over = p - fair_over
    side = "OVER" if edge_over >= 0 else "UNDER"
    model_p = p if side == "OVER" else 1 - p
    fair_p = fair_over if side == "OVER" else 1 - fair_over
    edge = abs(edge_over)

    odds = over_odds if side == "OVER" else (under_odds if under_odds is not None else over_odds)
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
        return Edge(side=side, model_p=model_p, fair_p=fair_p, edge=edge,
                    ev_per_dollar=ev, hold=hold, kelly=0.0, tier="PASS",
                    reasoning=(f"ROLE CHANGE — {u.column} {u.baseline:.1f} -> "
                               f"{u.recent:.1f} ({u.ratio:.0%}). The sample "
                               f"describes a role this player no longer has, so "
                               f"the model is unreliable here whatever the edge "
                               f"looks like. Check the market's number instead."),
                    fair_source=fair_source or ("de-vigged from the quoted "
                                                "price — NOT a sharp reference"))

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

    # Soft flag costs one tier — real uncertainty, but not disqualifying.
    if est.usage is not None and est.usage.soft_flagged:
        tier = {"STRONG": "MODERATE", "MODERATE": "COIN-FLIP",
                "COIN-FLIP": "PASS"}.get(tier, tier)

    return Edge(side=side, model_p=model_p, fair_p=fair_p, edge=edge,
                ev_per_dollar=ev, hold=hold, kelly=kelly, tier=tier,
                reasoning="; ".join(reasons) if reasons else "clean read",
                fair_source=fair_source or ("de-vigged from the quoted price "
                                            "— NOT a sharp reference"))


# Flat stake sizing, mirroring the convention from the other copilots.
STAKES = {"STRONG": 13, "MODERATE": 10, "COIN-FLIP": 5, "PASS": 0}


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
    lines.append(f"  VERDICT     : {e.tier}  ->  ${stake}")
    lines.append(f"  why         : {e.reasoning}")
    return "\n".join(lines)
