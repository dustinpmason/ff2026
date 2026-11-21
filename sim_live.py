#!/usr/bin/env python3
"""S28. A shadow run of the simulator on this week's slate.

    python3 sim_live.py --week 11 --inputs week11.json odds/*.json
    python3 sim_live.py --week 11 --inputs week11.json --ladders \\
        --out shadow_2026_wk11.csv odds/*.json
    python3 sim_live.py --record --current-week 11      # rebuild sim_record.py

A RUN. Each odds file is one saved `propline_get_odds` response for ONE
game (pass `event_id`, `markets` and `bookmakers` when pulling, as the
project instructions say). The inputs file names the week and every
team's starting quarterback, and may hand in chances of playing, add
players who are back, and say who a book means by a name the data does
not have:

    {"season": 2026, "week": 11,
     "starters": {"DEN": "Bo Nix", "LV": "Fernando Mendoza"},
     "statuses": [{"team": "DEN", "player": "Courtland Sutton", "status": "questionable"}],
     "chances":  [{"team": "LV", "player": "Brock Bowers", "chance": 0.0}],
     "add":      [{"team": "LV", "player": "Somebody Back", "position": "WR"}],
     "aliases":  [{"team": "TB", "name": "Kenneth Gainwell", "player": "Kenny Gainwell"}]}

A status (out, doubtful, questionable, listed, none) replaces the injury
file's for that player, which can be days behind; a chance overrides both.
An alias is the name a book posts with no id, the team, and the player it
is (his name in the data, his nflverse id, or "espn:<id>").

A posted player who is not on his team's slate (he has been out for its
last four games, or is new to it) is listed under "posted but not priced".
Until he is added, or is ruled out, HIS TEAMMATES' NUMBERS ARE TOO HIGH,
and the printout says so at the top and under the team.

It prints, for every player with a posted line, his projected stat line
and the chance of clearing each posted line, with the record of the band
that chance falls in and the cautions that apply. By default only each
book's main line and the anytime touchdown, with a count of the rest;
`--ladders` shows every rung, alternate and 2+/3+ touchdown line too.
`--out` also saves the lines shown as a table to grade after the games.

IT STOPS, SAYING WHAT, when something it needs is missing: an odds file it
cannot read, a game that has started or is not this week's (going by last
week's game dates), a team with no starter named, a name it cannot place, anything in the
inputs it does not know, last week's games not on file, no injury report
for these teams, or a record built from other model code.
`ff_sim_live.py` says what each is.

THE RECORD (`--record`, about ten minutes) walks the same set-up forward
over every graded week and writes `sim_record.py`, which has to be
committed with the model files it was built from. `--current-week` is the
NFL week now in progress; every week before it is graded.

No prices are read, printed or saved. A posted line is a benchmark.
"""
from __future__ import annotations

import argparse
import pprint
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import pandas as pd

import ff_data
import ff_sim as fs
import ff_sim_live as live
from ff_sim_play import load_reports
from sim_baseline import YEARS, newest_complete


def write_record(current_week: int | None) -> int:
    through = newest_complete(current_week)
    frame = fs.load_frame(YEARS)
    record = live.build_record(frame, load_reports(YEARS), through)
    path = Path(__file__).resolve().parent / "sim_record.py"
    path.write_text(
        '"""The simulator\'s walk-forward record, as `sim_live.py` prints it.\n\n'
        "MADE BY `python3 sim_live.py --record`. Do not edit by hand. It is\n"
        "only good for the model code it was built from (`code` below is that\n"
        'code\'s fingerprint); `ff_sim_live.check_record` refuses any other.\n"""\n\n'
        "RECORD = " + pprint.pformat(record, width=100, sort_dicts=False) + "\n")
    print(f"wrote {path.name}: {record['weeks']} weeks, {record['first']} to "
          f"{record['through']}, model code {record['code'][:12]}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("odds", nargs="*", help="saved get_odds event responses")
    ap.add_argument("--week", type=int)
    ap.add_argument("--inputs", help="the inputs file (starters, statuses, chances, add, aliases)")
    ap.add_argument("--books", help="comma-separated book keys; default all in the files")
    ap.add_argument("--ladders", action="store_true", help="price every rung, not only main lines")
    ap.add_argument("--everyone", action="store_true", help="print players with no posted line too")
    ap.add_argument("--out", help="also save the priced lines to this CSV")
    ap.add_argument("--allow-no-report", action="store_true")
    ap.add_argument("--record", action="store_true", help="rebuild sim_record.py and stop")
    ap.add_argument("--current-week", type=int, default=None)
    args = ap.parse_args()
    pd.set_option("display.width", 200)

    if args.record:
        return write_record(args.current_week)
    try:
        try:
            from sim_record import RECORD
        except ImportError:
            RECORD = None
        frame = fs.load_frame(YEARS)
        season = int(frame["season"].max())
        dates = pd.read_parquet(ff_data.fetch("pbp", season),
                                columns=["week", "season_type", "game_date"])
        dates = dates[dates.season_type == "REG"]
        reports, roster = load_reports(YEARS), ff_data.load_roster(season)
    except Exception as e:      # noqa: BLE001 - stop and say what
        print(f"STOPPED. Could not load what a run needs ({type(e).__name__}: "
              f"{e}). Run refresh.py; if it is sim_record.py, rebuild it with "
              f"--record.")
        return 3
    text, code = live.shadow_run(
        frame, reports, roster, RECORD, args.odds, args.inputs, week=args.week,
        books=set(args.books.split(",")) if args.books else None,
        ladders=args.ladders, everyone=args.everyone, out=args.out,
        allow_no_report=args.allow_no_report, now=None, dates=dates)
    print(text)
    return code


if __name__ == "__main__":
    sys.exit(main())
