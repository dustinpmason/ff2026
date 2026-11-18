#!/usr/bin/env python3
"""B205. Does the model's probability add anything to the market's fair line?

    python3 model_vs_fair.py

Reads the bet log the session has pulled from Drive (`ff_betlog.live_recs()`)
and scores every graded engine verdict that carries BOTH a model probability
and a market fair probability for the same side. It prints:

  - accuracy of each (Brier score: lower is better, a coin flip is 0.250)
  - how often the verdict's side won, by how far the model sat from the fair
  - the same with one verdict per player / market / side, because one player
    quoted at three books is one observation, not three
  - the best-fit weight on (model - fair): +1 would mean the model's
    disagreement is fully informative, 0 that it carries nothing, a negative
    number that the market's side wins more often the more the model disagrees

Run it after the log is pulled and graded. With no pulled log it says so and
exits 2 rather than printing a table about nothing.

Limits, stated because the figures get quoted:
  - Verdicts from one game move together, and older verdicts carry no event
    id, so the standard error printed is too small. Read it as a floor.
  - It scores the side the verdict is ON. Since B126 that can be a forced
    side, so a negative gap means the model was against the leg.
  - It cannot say WHY the model misses. The usual suspects are a stale role
    and a small sample; this only measures the result.
"""
from __future__ import annotations

import math
import sys

import ff_betlog as bl

GAP_BINS = ((-1.0, 0.03), (0.03, 0.10), (0.10, 0.20), (0.20, 1.0))


def usable(recs: list[dict]) -> list[dict]:
    return [r for r in recs
            if r.get("result") in ("WIN", "LOSS")
            and isinstance(r.get("model_p"), (int, float))
            and isinstance(r.get("fair_p"), (int, float))]


def dedupe(recs: list[dict]) -> list[dict]:
    seen, out = set(), []
    for r in recs:
        k = (r.get("player"), r.get("market"), r.get("side"))
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


def won(rs: list[dict]) -> int:
    return sum(r["result"] == "WIN" for r in rs)


def brier(rs: list[dict], key: str) -> float:
    return sum((r[key] - (r["result"] == "WIN")) ** 2 for r in rs) / len(rs)


def weight(rs: list[dict]) -> tuple[float, float]:
    """Slope of (outcome - fair) on (model - fair), and its naive se."""
    x = [r["model_p"] - r["fair_p"] for r in rs]
    y = [(r["result"] == "WIN") - r["fair_p"] for r in rs]
    n = len(rs)
    mx, my = sum(x) / n, sum(y) / n
    sxx = sum((a - mx) ** 2 for a in x)
    if n < 3 or sxx == 0:
        return float("nan"), float("nan")
    lam = sum((a - mx) * (b - my) for a, b in zip(x, y)) / sxx
    res = [(b - my) - lam * (a - mx) for a, b in zip(x, y)]
    return lam, math.sqrt(sum(e * e for e in res) / (n - 2) / sxx)


def table(tag: str, rs: list[dict]) -> None:
    print(f"\n{tag}: {len(rs)} verdicts, {len({r.get('player') for r in rs})} "
          f"players, {len({str(r.get('event_id')) for r in rs if r.get('event_id') is not None})} "
          f"games with an event id "
          f"({sum(r.get('event_id') is None for r in rs)} verdicts carry none)")
    print(f"  accuracy (Brier): model {brier(rs, 'model_p'):.3f}   "
          f"market fair {brier(rs, 'fair_p'):.3f}   coin flip 0.250")
    print("  the verdict's side, by how far the model sat above the fair line")
    for lo, hi in GAP_BINS:
        g = [r for r in rs if lo <= r["model_p"] - r["fair_p"] < hi]
        if not g:
            continue
        name = (f"under {hi * 100:.0f} pts" if lo < 0
                else f"{lo * 100:.0f}+ pts" if hi >= 1
                else f"{lo * 100:.0f}-{hi * 100:.0f} pts")
        print(f"    {name:<13} n={len(g):3d}  won {won(g):3d} ({won(g) / len(g):5.1%})"
              f"   model said {sum(r['model_p'] for r in g) / len(g):5.1%}"
              f"   fair said {sum(r['fair_p'] for r in g) / len(g):5.1%}")
    lam, se = weight(rs)
    print(f"  best-fit weight on (model - fair): {lam:+.2f}  (se {se:.2f}, a "
          f"floor: games are clustered)")


def main() -> int:
    recs = usable(bl.live_recs())
    if not recs:
        print("No graded verdict with both a model and a fair probability in "
              "the pulled log. Pull the log from Drive and grade it first "
              "(see `ff_betlog.status()`).")
        return 2
    print(bl.pull_state())
    table("EVERY VERDICT", recs)
    table("ONE PER PLAYER / MARKET / SIDE", dedupe(recs))
    for side in ("OVER", "UNDER"):
        g = [r for r in recs if str(r.get("side")).upper() == side]
        if g:
            print(f"\n  {side}: n={len(g)}  won {won(g)} ({won(g) / len(g):.1%})"
                  f"   model said {sum(r['model_p'] for r in g) / len(g):.1%}"
                  f"   fair said {sum(r['fair_p'] for r in g) / len(g):.1%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
