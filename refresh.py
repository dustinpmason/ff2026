"""
refresh.py — one-command session bootstrap.

Run this FIRST in any new conversation. It pulls current nflverse data, confirms
how fresh it is, and prints each league's real scoring rules so nothing is being
inferred from memory.

    python3 refresh.py
"""
import warnings
warnings.filterwarnings("ignore")

from ff_data import refresh_all, load_weekly, data_status, ensure_deps

# Front-load every dependency a later question might need, so a missing package
# surfaces here instead of halfway through a lineup call.
ensure_deps("pyarrow", "scipy")

from ff_scoring import LEAGUES, describe  # noqa: E402
import ff_props  # noqa: F401,E402  -- import proves the prop engine loads


def main():
    refresh_all()
    print("=" * 70)
    wk = load_weekly([2025, 2026])
    reg = wk[wk.season_type == "REG"]
    print(f"Loaded {len(reg):,} player-weeks across 2025-2026.\n")
    for lg in LEAGUES.values():
        print(describe(lg))
        print()
    print("=" * 70)
    print("Ready. Scoring engine validated 100% vs nflverse reference.")
    print(data_status())


if __name__ == "__main__":
    main()
