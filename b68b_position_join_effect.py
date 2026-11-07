#!/usr/bin/env python3
"""B68b: what does a dropped position cost the guillotine simulation?

`correlation_matrix` guards TEAM (`if ti is None or tj is None: continue`) and
has no `pi`/`pj` equivalent, then does `SAME_TEAM_CORR.get(key, 0.0)`. So a
player whose meta is `("KC", None)` — team joined, position did not — yields a
silent **0.0** for what may be a QB/WR pair at +0.31. The same hole swallows a
player missing from `meta` entirely, and `meta.get(name, ...)` is a RAW NAME
lookup in a module whose own `normalize_name` docstring reads "THIRD
occurrence of a name-join bug in this project. Never match player data on a
raw name."

Measured exposure, nflverse 2026 weekly (1,732 players):
  * `build_meta` itself yields 0 bad rows — team and position are always
    present, so the bug does not fire from that source today.
  * 96 players carry a name suffix whose plain spelling is NOT a meta key, so
    any roster source that spells "Brian Thomas" for "Brian Thomas Jr."
    misses, and a miss drops the pair to 0.0.
  * Confirmed directly on a real PIT stack: QB x WR goes +0.3100 -> +0.0000
    when the receiver's position is NaN or his name is absent.

What is NOT established by any of that is whether it changes an ANSWER. B68
measured its own sign error at 0.007pp on P(elim) with the recommended
lineup identical, and recorded "real correctness bug, low operational
stakes". This does the same arithmetic for this one, because a 0.31 drop is
about twice the 0.16 B68 flipped and can hit several pairs at once.

    python3 measurements/b68b_position_join_effect.py
"""
import sys, pathlib
_here = pathlib.Path(__file__).resolve().parent
for _cand in (_here, _here.parent):
    if (_cand / "ff_props.py").exists():
        sys.path.insert(0, str(_cand))
        break
else:
    sys.exit(f"cannot find ff_props.py next to or above {_here}")
import numpy as np
import ff_guillotine as g
from ff_data import load_weekly
from ff_scoring import LEAGUES

SEASON = 2026
N_SIMS = 60_000
MISS_RATE = 96 / 1732          # the measured suffix-miss rate, not a guess


def _drop_positions(meta, names):
    """Same meta with those players' POSITION gone — team still joined."""
    out = dict(meta)
    for n in names:
        if n in out:
            out[n] = (out[n][0], None)
    return out


def _stacked_league(pool, meta):
    """A league where every team starts its own QB with his own receivers.

    The effect has to be measurable before it can be called small, and a
    randomly-built roster rarely stacks. B68 used the same device.
    """
    by_team = {}
    for n, (t, p) in meta.items():
        if p in ("QB", "RB", "WR", "TE") and g.resolve(n, pool):
            by_team.setdefault(t, {}).setdefault(p, []).append(n)
    teams, tid = [], 0
    for t, pos in by_team.items():
        # The lineup needs QB1 RB2 WR2 TE1 FLEX2, so the roster has to carry
        # enough beyond the fixed slots to fill both flexes AND leave a
        # choice — otherwise there is one legal lineup and nothing to compare.
        if (len(pos.get("QB", [])) < 1 or len(pos.get("WR", [])) < 5
                or len(pos.get("RB", [])) < 4 or len(pos.get("TE", [])) < 2):
            continue
        teams.append({"team_id": str(tid), "team_name": f"stack {t}",
                      "roster": {"QB": pos["QB"][:1], "RB": pos["RB"][:4],
                                 "WR": pos["WR"][:5], "TE": pos["TE"][:2]}})
        tid += 1
        if tid >= 10:
            break
    return teams


def _compare(label, teams, pool, meta, dropped):
    a = g.run(teams, pool, my_team_id="0", n_sims=N_SIMS, meta=meta, week=9)
    b = g.run(teams, pool, my_team_id="0", n_sims=N_SIMS, meta=dropped,
              week=9)
    ra = {tuple(sorted(L)): float(p) for L, p in zip(a.lineups, a.p_last)}
    rb = {tuple(sorted(L)): float(p) for L, p in zip(b.lineups, b.p_last)}
    shared = set(ra) & set(rb)
    if not shared:
        print(f"{label}: no comparable lineups")
        return
    best_a = min(ra, key=lambda k: ra[k])
    best_b = min(rb, key=lambda k: rb[k])
    shifts = [abs(ra[k] - rb[k]) for k in shared]
    # Monte Carlo noise floor. A shift inside its own error bar is not a
    # measurement, and this project has quoted one as if it were.
    pm = ra[best_a]
    se = (pm * (1 - pm) / N_SIMS) ** 0.5
    print(f"{label}")
    print(f"  P(elim) of the best lineup : {ra[best_a]:.4%} -> "
          f"{rb[best_b]:.4%}   ({(rb[best_b]-ra[best_a])*100:+.4f}pp)")
    print(f"  max shift over {len(shared)} lineups : "
          f"{max(shifts)*100:.4f}pp")
    print(f"  1 se of simulation noise   : {se*100:.4f}pp, so a shift "
          f"under {2*se*100:.4f}pp is inside the error bar")
    print(f"  recommended lineup identical: {best_a == best_b}")
    if best_a != best_b:
        print(f"    with meta   : {sorted(best_a)}")
        print(f"    without pos : {sorted(best_b)}")
    print()


def main() -> None:
    wk = load_weekly([SEASON])
    pool = g.build_pool(wk, LEAGUES["guillotine"])
    meta = g.build_meta(wk)

    teams = _stacked_league(pool, meta)
    if len(teams) < 4:
        sys.exit(f"only {len(teams)} stackable teams — fixture too thin to "
                 f"measure, reporting nothing")
    print(f"{len(teams)} deliberately QB-stacked teams, {N_SIMS:,} sims, "
          f"season {SEASON}\n")

    # 1. The whole correlation signal removed: the upper bound on what any
    #    join failure can cost, and the number that says whether the sim is
    #    sensitive to this at all.
    allp = sorted({p for t in teams for v in t["roster"].values() for p in v})
    _compare("EVERY position dropped (upper bound)", teams, pool, meta,
             _drop_positions(meta, allp))

    # 2. The measured miss rate, applied to the players most likely to miss.
    rng = np.random.default_rng(7)
    k = max(1, round(len(allp) * MISS_RATE))
    sampled = list(rng.choice(allp, size=k, replace=False))
    _compare(f"the measured {MISS_RATE:.1%} miss rate ({k} of {len(allp)} "
             f"players)", teams, pool, meta, _drop_positions(meta, sampled))

    # 3. The worst realistic single case: one team's own QB-WR stack broken,
    #    which is what one suffixed receiver actually does.
    me = teams[0]["roster"]
    one = [me["WR"][0]]
    _compare(f"one receiver's position dropped ({one[0]})", teams, pool,
             meta, _drop_positions(meta, one))


if __name__ == "__main__":
    main()
