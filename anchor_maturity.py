"""How far is an anchor's number from where it closes, by the limit behind it?

B224. `BoostLeg.anchor_untested` asks whether a line's limit is above the
board's most common limit. Pinnacle raises limits on a schedule, so by game
day nearly every line sits AT the raised limit and the test has nothing left
to say. This script measures the thing the test was standing in for: how
much a Pinnacle fair still moves before kickoff, as a function of the limit
resting behind it when it is read.

Input: a folder of `propline_get_odds_history` responses, one JSON file per
event, pulled with bookmakers=pinnacle, changes_only=true and the main
yardage / reception markets. Each snapshot carries price, point, liquidity
and recorded_at.

    python3 anchor_maturity.py <folder>

Every line is sampled at fixed hours before kickoff, so a line that reprices
often does not count more than one that sits still.
"""
from __future__ import annotations

import json
import sys
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median

SAMPLE_HOURS = (72, 48, 36, 24, 18, 12, 6, 3, 1)


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _implied(american: float) -> float:
    a = float(american)
    return 100.0 / (a + 100.0) if a > 0 else -a / (-a + 100.0)


def _state_at(snaps: list[dict], when: datetime) -> dict | None:
    """Latest snapshot at or before `when`."""
    times = [s["_t"] for s in snaps]
    i = bisect_right(times, when)
    return snaps[i - 1] if i else None


def line_states(event: dict) -> list[dict]:
    """One row per (line, sample hour): the two-way fair then and at close."""
    kick = _ts(event["commence_time"])
    rows = []
    for bk in event.get("bookmakers") or []:
        for mk in bk.get("markets") or []:
            if mk.get("line_type") not in (None, "main"):
                continue
            sides = {}
            for oc in mk.get("outcomes") or []:
                snaps = [dict(s, _t=_ts(s["recorded_at"]))
                         for s in oc.get("snapshots") or []]
                snaps = [s for s in snaps if s["_t"] <= kick]
                snaps.sort(key=lambda s: s["_t"])
                if snaps:
                    sides[oc["name"]] = snaps
            if set(sides) != {"Over", "Under"}:
                continue

            def fair(when):
                o, u = _state_at(sides["Over"], when), _state_at(sides["Under"], when)
                if o is None or u is None or o["point"] != u["point"]:
                    return None
                io, iu = _implied(o["price"]), _implied(u["price"])
                liq = [x for x in (o.get("liquidity"), u.get("liquidity"))
                       if x is not None]
                return dict(point=float(o["point"]), fair=io / (io + iu),
                            liquidity=min(liq) if liq else None)

            close = fair(kick)
            if close is None:
                continue
            for h in SAMPLE_HOURS:
                now = fair(kick - timedelta(hours=h))
                if now is None:
                    continue
                rows.append(dict(event=str(event["id"]), market=mk["key"],
                                 line=mk.get("description"), hours=h,
                                 liquidity=now["liquidity"],
                                 point=now["point"], fair=now["fair"],
                                 close_point=close["point"],
                                 close_fair=close["fair"],
                                 close_liquidity=close["liquidity"]))
    return rows


def summarise(rows: list[dict], key) -> list[dict]:
    groups = defaultdict(list)
    for r in rows:
        groups[key(r)].append(r)
    out = []
    for k in sorted(groups, key=lambda x: (x is None, x)):
        g = groups[k]
        same = [r for r in g if r["point"] == r["close_point"]]
        gaps = sorted(abs(r["fair"] - r["close_fair"]) * 100 for r in same)
        out.append(dict(
            key=k, n=len(g), events=len({r["event"] for r in g}),
            point_held=len(same) / len(g),
            at_half=sum(abs(r["fair"] - 0.5) < 1e-9 for r in g) / len(g),
            gap_mean=mean(gaps) if gaps else float("nan"),
            gap_median=median(gaps) if gaps else float("nan"),
            gap_p90=gaps[int(0.9 * (len(gaps) - 1))] if gaps else float("nan"),
            within_2=(sum(x <= 2.0 for x in gaps) / len(g)) if g else 0.0))
    return out


def _print(title: str, table: list[dict]) -> None:
    print(f"\n{title}")
    print(f"{'':>10} {'n':>5} {'ev':>3} {'line held':>10} {'at .5000':>9} "
          f"{'gap mean':>9} {'median':>7} {'p90':>6} {'held & <=2pt':>13}")
    for t in table:
        print(f"{str(t['key']):>10} {t['n']:>5} {t['events']:>3} "
              f"{t['point_held']:>10.0%} {t['at_half']:>9.0%} "
              f"{t['gap_mean']:>9.2f} {t['gap_median']:>7.2f} "
              f"{t['gap_p90']:>6.2f} {t['within_2']:>13.0%}")


def main(folder: str) -> None:
    rows = []
    for f in sorted(Path(folder).glob("*.json")):
        rows += line_states(json.loads(f.read_text()))
    if not rows:
        raise SystemExit(f"no usable history files in {folder}")
    print(f"{len(rows)} line-samples, {len({r['event'] for r in rows})} events, "
          f"{len({(r['event'], r['line']) for r in rows})} lines")
    print("gap = |fair when read - fair at close|, in points, lines whose "
          "number did not move; 'line held' = same yardage/reception line at close")
    _print("BY LIMIT BEHIND THE LINE WHEN READ", summarise(rows, lambda r: r["liquidity"]))
    _print("BY HOURS BEFORE KICKOFF", summarise(rows, lambda r: -r["hours"]))

    # Does 'above the board's most common limit' carry anything inside one board?
    by_board = defaultdict(list)
    for r in rows:
        by_board[(r["event"], r["hours"])].append(r)
    rel = []
    for g in by_board.values():
        liqs = [r["liquidity"] for r in g if r["liquidity"] is not None]
        if len(liqs) < 3:
            continue
        mode = max(set(liqs), key=liqs.count)
        for r in g:
            if r["liquidity"] is not None:
                rel.append(dict(r, _rel="above mode" if r["liquidity"] > mode
                                else "at mode" if r["liquidity"] == mode
                                else "below mode"))
    _print("SAME BOARD, SAME HOUR: LIMIT AGAINST THE BOARD'S MOST COMMON LIMIT",
           summarise(rel, lambda r: r["_rel"]))
    for h in (24, 6, 1):
        _print(f"AT {h}h BEFORE KICKOFF, BY LIMIT",
               summarise([r for r in rows if r["hours"] == h],
                         lambda r: r["liquidity"]))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "history")
