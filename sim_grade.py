"""S29. Grade saved shadow runs.

    python3 sim_grade.py                         # every shadow_*_wk*.csv here
    python3 sim_grade.py shadow_2026_wk11.csv    # or the files named
    python3 sim_grade.py --out graded.csv        # ...and save every line with its result

A shadow run is saved by `sim_live.py --out shadow_<season>_wk<N>.csv`.
Run `refresh.py` first: a game is graded once both its stats and its snap
counts are on file, and until then its lines are named and left out. Read `ff_sim_grade.py`'s first
page for what counts as what.

It stops, and says why, on a file that is not a saved run, a line saved
twice, or two files holding the same game.
"""
from __future__ import annotations

import argparse
import glob
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import pandas as pd                # noqa: E402

import ff_data                     # noqa: E402
import ff_sim as fs                # noqa: E402
import ff_sim_grade as fg          # noqa: E402

YEARS = (2023, 2024, 2025, 2026)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("files", nargs="*", help="saved shadow runs; default: shadow_*_wk*.csv "
                                             "beside this script")
    ap.add_argument("--out", help="save every line with its result as CSV")
    args = ap.parse_args(argv)
    files = args.files or sorted(glob.glob(str(Path(__file__).resolve().parent / "shadow_*_wk*.csv")))
    if not files:
        print("STOPPED. No shadow file was named and there is no shadow_*_wk*.csv "
              "beside this script.")
        return 2
    try:
        frame = fs.load_frame(YEARS)
        weekly = ff_data.load_weekly(list(YEARS))
        snaps = fg.unplaced_snaps(
            ff_data.load_snaps(list(YEARS)),
            pd.concat([ff_data.load_roster(y) for y in YEARS], ignore_index=True))
    except Exception as e:      # noqa: BLE001 - stop and say what
        print(f"STOPPED. Could not load the data ({type(e).__name__}: {e}). Run refresh.py.")
        return 3
    text, code = fg.grade_files(frame, files, out=args.out, weekly=weekly, snaps=snaps)
    print(text)
    return code


if __name__ == "__main__":
    sys.exit(main())
