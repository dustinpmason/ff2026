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

from dataclasses import dataclass

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
    if played_only and opp and opp in df.columns:
        df = df[pd.to_numeric(df[opp], errors="coerce").fillna(0) > 0]

    cols = []
    for c in ["season", "week", "opponent_team", stat, opp]:
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
    verdict: str              # COLLAPSED | EXPANDED | STABLE | UNKNOWN
    per_opportunity: float    # production per unit of opportunity, full sample
    expected_now: float       # per_opportunity * recent usage

    @property
    def flagged(self) -> bool:
        return self.verdict in ("COLLAPSED", "EXPANDED")

    def describe(self) -> str:
        if self.verdict == "UNKNOWN":
            return "  usage      : not enough games to judge role change"
        arrow = {"COLLAPSED": "DOWN", "EXPANDED": "UP", "STABLE": "stable"}[self.verdict]
        s = (f"  usage      : {self.column} {self.baseline:.1f} -> {self.recent:.1f} "
             f"over last {self.window} ({self.ratio:.0%}, {arrow})")
        if self.flagged:
            s += (f"\n  ! ROLE CHANGE. At current usage, expected output is "
                  f"~{self.expected_now:.1f} — the sample describes a role this "
                  f"player no longer has.")
        return s


# Role-change thresholds. Deliberately wide: a 20-30% swing in targets is
# ordinary game-to-game noise, a 50% one is a different job.
COLLAPSE_RATIO = 0.60
EXPAND_RATIO = 1.60


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
    verdict = ("COLLAPSED" if ratio < COLLAPSE_RATIO
               else "EXPANDED" if ratio > EXPAND_RATIO
               else "STABLE")

    per_opp = float(y.sum() / o.sum()) if o.sum() > 0 else 0.0
    return UsageTrend(column=opp, window=window, recent=recent, baseline=baseline,
                      ratio=ratio, verdict=verdict, per_opportunity=per_opp,
                      expected_now=per_opp * recent)


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


def prop_edge(est: Estimate,
              over_odds: float,
              under_odds: float | None = None) -> Edge:
    """Compare the model against a market price and tier the result.

    Tiers follow the convention from Dustin's other copilots — strong /
    moderate / coin-flip / pass — rather than quoting a false-precision number.
    """
    if under_odds is None:
        # No two-way price available: fall back to the raw vigged number and
        # say so. The edge will read better than it is.
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
                               f"looks like. Check the market's number instead."))

    if edge < 0.03 or est.ci_width > 0.50:
        tier = "PASS"
        reasons.insert(0, "edge inside the noise")
    elif edge >= 0.08 and est.sample_verdict == "ADEQUATE" and est.ci_width <= 0.35:
        tier = "STRONG"
    elif edge >= 0.05 and est.sample_verdict != "THIN":
        tier = "MODERATE"
    else:
        tier = "COIN-FLIP"

    return Edge(side=side, model_p=model_p, fair_p=fair_p, edge=edge,
                ev_per_dollar=ev, hold=hold, kelly=kelly, tier=tier,
                reasoning="; ".join(reasons) if reasons else "clean read")


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
        f"  model       : {e.model_p*100:.0f}%   market (de-vigged): {e.fair_p*100:.0f}%",
        f"  edge        : {e.edge*100:+.1f} pts    EV {e.ev_per_dollar*100:+.1f}%/$",
    ]
    if not np.isnan(e.hold):
        lines.append(f"  book hold   : {e.hold*100:.1f}%")
    lines.append(f"  VERDICT     : {e.tier}  ->  ${stake}")
    lines.append(f"  why         : {e.reasoning}")
    return "\n".join(lines)
