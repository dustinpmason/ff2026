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

RNG = np.random.default_rng(20261029)

# Below this many games, treat any estimate as directional only.
MIN_GAMES_MEANINGFUL = 8
MIN_GAMES_CONFIDENT = 14


# ---------------------------------------------------------------------------
# Data shaping
# ---------------------------------------------------------------------------

def player_series(weekly: pd.DataFrame,
                  player: str,
                  stat: str,
                  seasons: list[int] | None = None,
                  played_only: bool = True) -> pd.DataFrame:
    """Game log for one player and one stat, oldest first.

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
    if played_only:
        snap = ("attempts" if stat.startswith("passing")
                else "carries" if stat.startswith("rushing")
                else "targets" if stat.startswith("receiving") else None)
        if snap and snap in df.columns:
            df = df[pd.to_numeric(df[snap], errors="coerce").fillna(0) > 0]
    cols = [c for c in ["season", "week", "opponent_team", stat] if c in df.columns]
    return df[cols].sort_values(["season", "week"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Estimation
# ---------------------------------------------------------------------------

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
    stat = stat or log.columns[-1]
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
                    ci_high=float(hi), mean=mu, sd=sd, hits=hits)


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
    if est.ci_width > 0.40:
        lines.append(f"  ! interval spans {est.ci_width*100:.0f} points — "
                     f"treat as directional, not precise")
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
