"""
ff_scoring.py — league-correct fantasy scoring for Dustin's four 2026 leagues.

WHY THIS EXISTS
---------------
FantasyPros does not ingest custom bonus scoring. Its projections for three of the
four leagues are computed on the wrong rules. This module replaces that guesswork
with arithmetic: it scores real nflverse game logs under each league's ACTUAL rules.

Every scoring value here comes from Dustin's own stated league settings, not from
the connector. Where a rule is unconfirmed it is marked UNVERIFIED and defaults to
off, so an unconfirmed rule can never silently inflate a number.

Usage
-----
    from ff_data import load_weekly
    from ff_scoring import LEAGUES, score

    wk = load_weekly([2025, 2026])
    wk["pts"] = score(wk, LEAGUES["holmdels"])

    # or every league at once
    from ff_scoring import score_all
    scored = score_all(wk)
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class League:
    name: str
    key: str
    teams: int
    my_team: str

    # --- per-unit scoring ---
    pass_yd: float = 0.04
    pass_td: float = 4.0
    pass_int: float = -2.0
    rush_yd: float = 0.1
    rush_td: float = 6.0
    rec: float = 0.0
    rec_yd: float = 0.1
    rec_td: float = 6.0
    st_td: float = 6.0          # kick/punt return + defensive TDs credited to the player
    fumble_lost: float = -2.0
    two_pt: float = 2.0

    # Which lost fumbles are penalized.
    #   "offense" — rushing + receiving + sack fumbles only. Matches nflverse's
    #               reference calc and most platforms' default.
    #   "all"     — also charges special-teams fumbles (muffed punts, return
    #               fumbles). Affects ~0.2% of player-weeks, almost all returners.
    # Yahoo's exact treatment of muffed punts is unconfirmed for these leagues,
    # so the narrower definition is the default.
    fumble_scope: str = "offense"

    # --- the rules FantasyPros misses ---
    rec_first_down: float = 0.0           # Holmdel's: 0.5 per receiving 1st down
    return_yds_per_point: float = 0.0     # Holmdel's: 1 pt per 50 return yards

    # milestone bonuses: (stat column, threshold, points) — fires once at >= threshold
    milestones: list[tuple[str, float, float]] = field(default_factory=list)

    # explosive-play bonuses: (count column, points per play)
    explosive: list[tuple[str, float]] = field(default_factory=list)

    # --- kicker scoring ---
    pat: float = 1.0
    fg_yards_per_point: float = 0.0        # e.g. 10 => total made-FG yards / 10
    fg_tiers: list[tuple[int, int, float]] = field(default_factory=list)
    fg_miss: float = 0.0                   # penalty per miss; 0 = none

    # --- team DST scoring ---
    # Recorded for reference and for reasoning about streaming decisions.
    # NOT yet computed — see score_dst() for why.
    dst: dict = field(default_factory=dict)

    # roster
    starters: dict[str, int] = field(default_factory=dict)
    bench: int = 0
    ir: int = 0
    uses_k_dst: bool = True

    # operational constraints that change waiver advice
    acquisitions_per_season: int | None = None
    acquisitions_per_week: int | None = None
    playoff_weeks: str = ""

    notes: str = ""


# ---------------------------------------------------------------------------
# League definitions. Sources are Dustin's stated settings, cross-checked
# against the FantasyPros connector on 2026-10-29.
# ---------------------------------------------------------------------------

LEAGUES: dict[str, League] = {

    "guillotine": League(
        name="Mid Season Guillotine",
        key="nfl~db5caac1-6d74-4e86-adde-549164c71811",
        teams=10,
        my_team="Ballin On A Budget",
        pass_td=4.0, pass_int=-2.0, rec=1.0,
        starters={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 2},
        bench=4, ir=0, uses_k_dst=False,
        playoff_weeks="runs Weeks 9-17, weekly elimination",
        notes=("ELIMINATION FORMAT. Lowest weekly score is out. The objective is "
               "minimizing P(lowest score), NOT maximizing expected points. "
               "No K, no DST. Connector syncs this league correctly."),
    ),

    "cameron_wood": League(
        name="Life's Good in Cameron Wood",
        key="nfl~6e661db6-5379-4508-9637-d51048ad2226",
        teams=10,
        my_team="The Dude McBrides",
        pass_td=6.0, pass_int=-1.0, rec=0.5,
        explosive=[
            ("passing_40", 1.0),     # 40+ yard completions
            ("rushing_40", 1.0),     # 40+ yard runs
            ("receiving_40", 1.0),   # 40+ yard receptions
            # 40+ yard TDs pay a further +1 each and STACK with the above.
            # These are NOT in the weekly box score — prepare() derives them
            # from play-by-play. score() refuses to run without them rather
            # than silently undercounting every big-play player.
            ("td40_pass", 1.0),
            ("td40_rush", 1.0),
            ("td40_rec", 1.0),
        ],
        pat=1.0, fg_miss=0.0,
        fg_tiers=[(0, 19, 1), (20, 29, 2), (30, 39, 3), (40, 49, 4), (50, 99, 5)],
        starters={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "K": 1, "DST": 1},
        bench=6, ir=2,
        playoff_weeks="4-team playoffs, Weeks 15-16",
        notes=("Dustin is commissioner. 1-pt bonuses on all 40+ yard completions, "
               "runs and receptions, PLUS 40+ yard TDs, and they stack. "
               "Connector reports every bonus as 0 — that is false."),
    ),

    "gridiron_grail": League(
        name="TheQuestForTheGridironGrail (keeper)",
        key="nfl~dea821ad-a185-441c-ad65-4edc094e9f3b",
        teams=12,
        my_team="Dirty D",
        pass_td=6.0, pass_int=-1.0, rec=1.0,
        milestones=[
            ("passing_yards", 250, 5.0),
            ("rushing_yards", 100, 5.0),
            ("receiving_yards", 100, 5.0),
        ],
        pat=1.0, fg_yards_per_point=10.0, fg_miss=0.0,
        starters={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "K": 1, "DST": 1},
        bench=6, ir=0,
        playoff_weeks="6-team playoffs, Weeks 14-16",
        notes=("Keeper league. NO IR SLOT — an injured stash costs a real bench spot. "
               "5-pt milestone bonuses reward ceiling over consistency. "
               "Kicker FGs scored at 10 yards per point. "
               "Current keepers: James Cook, Ashton Jeanty."),
    ),

    "holmdels": League(
        name="Holmdel's Finest",
        key="nfl~11c96180-84d8-4c9f-a243-8106a937109f",
        teams=12,
        my_team="It's Bo Time",
        pass_td=4.0, pass_int=-1.0, rec=0.5,
        rec_first_down=0.5,
        return_yds_per_point=50.0,
        milestones=[
            ("passing_yards", 300, 3.0),
            ("rushing_yards", 100, 3.0),
            ("receiving_yards", 100, 3.0),
        ],
        # CONFIRMED from Dustin's Yahoo settings screen, 2026-10-29.
        pat=1.0, fg_yards_per_point=10.0, fg_miss=0.0,
        dst={"sack": 1, "int": 2, "fum_rec": 2, "td": 6, "safety": 2,
             "block_kick": 2, "return_td": 6, "fourth_down_stop": 0.5,
             "xp_returned": 2,
             "pts_allowed": [(0, 0, 10), (1, 6, 7), (7, 13, 5), (14, 20, 3),
                             (21, 27, 1), (28, 34, -1), (35, 99, -4)]},
        starters={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "K": 1, "DST": 1},
        bench=7, ir=1,
        acquisitions_per_season=50, acquisitions_per_week=4,
        playoff_weeks="6-team playoffs, Weeks 15-17",
        notes=("WORST SYNC. Connector reports scoring_is_custom=false and serves "
               "generic half-PPR with no warning. The 0.5-per-receiving-first-down "
               "rule pushes possession receivers toward full-PPR value. "
               "ACQUISITION CAP: 50/season, 4/week — waiver claims are a scarce "
               "resource here, unlike the other leagues. "
               "KICKER: 10 yards per point on TOTAL made-FG yardage, no miss "
               "penalty and no flat credit for making a kick — a 25-yarder is "
               "2.5, a 55-yarder 5.5. Tested against tiered scoring: the "
               "reordering is modest (1-4 rank spots), because volume still "
               "dominates under both schemes. Do not oversell this as an edge. "
               "DST: sack is 1 (connector says 2) and the points-allowed ladder "
               "is 5/3/1 at 7-13/14-20/21-27 (connector says 4/1/0), so the "
               "connector systematically undervalues mid-range defensive games."),
    ),
}


# ---------------------------------------------------------------------------
# Scoring engine
# ---------------------------------------------------------------------------

def _col(df: pd.DataFrame, name: str) -> pd.Series:
    """Fetch a stat column, or zeros if this dataset doesn't carry it."""
    if name in df.columns:
        return pd.to_numeric(df[name], errors="coerce").fillna(0)
    return pd.Series(0.0, index=df.index)


def score(df: pd.DataFrame, lg: League) -> pd.Series:
    """Score a weekly-stats frame under one league's real rules.

    Returns a float Series aligned to df.index. Offensive skill scoring only —
    kicker and DST scoring are not modeled (they vary most and matter least).
    """
    # A declared bonus whose column is absent would score as zero, which is
    # silently wrong rather than loudly broken. Refuse instead.
    required = [c for c, _ in lg.explosive] + [s for s, _, _ in lg.milestones]
    absent = [c for c in required if c not in df.columns]
    if absent:
        raise KeyError(
            f"{lg.name} scores bonuses on {absent}, which this frame does not "
            f"have. Run prepare(weekly, pbp) before scoring this league — "
            f"otherwise every big-play player comes in low and nothing warns you."
        )

    if lg.fumble_scope == "all":
        fum = _col(df, "fumbles_lost_total")
    else:
        fum = (_col(df, "rushing_fumbles_lost")
               + _col(df, "receiving_fumbles_lost")
               + _col(df, "sack_fumbles_lost"))

    p = (
        _col(df, "passing_yards") * lg.pass_yd
        + _col(df, "passing_tds") * lg.pass_td
        + _col(df, "passing_interceptions") * lg.pass_int
        + _col(df, "rushing_yards") * lg.rush_yd
        + _col(df, "rushing_tds") * lg.rush_td
        + _col(df, "receptions") * lg.rec
        + _col(df, "receiving_yards") * lg.rec_yd
        + _col(df, "receiving_tds") * lg.rec_td
        + _col(df, "special_teams_tds") * lg.st_td
        + fum * lg.fumble_lost
        + (
            _col(df, "passing_2pt_conversions")
            + _col(df, "rushing_2pt_conversions")
            + _col(df, "receiving_2pt_conversions")
        ) * lg.two_pt
    )

    if lg.rec_first_down:
        p = p + _col(df, "receiving_first_downs") * lg.rec_first_down

    if lg.return_yds_per_point:
        ret = _col(df, "punt_return_yards") + _col(df, "kickoff_return_yards")
        p = p + ret / lg.return_yds_per_point

    for stat, thresh, pts in lg.milestones:
        p = p + (_col(df, stat) >= thresh).astype(float) * pts

    for stat, pts in lg.explosive:
        p = p + _col(df, stat) * pts

    return p.astype(float)


def score_kicker(df: pd.DataFrame, lg: League) -> pd.Series:
    """Score kickers under a league's real FG rules.

    Two schemes, and they behave very differently:

      fg_yards_per_point — total MADE field-goal yardage divided by the rate.
          Holmdel's and the keeper league both use 10 yards per point. A
          25-yarder is 2.5 points; a 55-yarder is 5.5, with no flat credit for
          simply making a kick. Measured against tiered scoring on 2026 data,
          this reorders kickers by only 1-4 rank spots — volume dominates under
          either scheme. Real, but a small effect; don't oversell it.

      fg_tiers — flat points by distance band (Cameron Wood: 1/2/3/4/5).
    """
    if not lg.uses_k_dst:
        return pd.Series(0.0, index=df.index)

    p = _col(df, "pat_made") * lg.pat

    if lg.fg_yards_per_point:
        p = p + _col(df, "fg_made_distance") / lg.fg_yards_per_point
    elif lg.fg_tiers:
        for col, lo in [("fg_made_0_19", 0), ("fg_made_20_29", 20),
                        ("fg_made_30_39", 30), ("fg_made_40_49", 40),
                        ("fg_made_50_59", 50), ("fg_made_60_", 60)]:
            pts = next((v for a, b, v in lg.fg_tiers if a <= lo <= b), 0)
            p = p + _col(df, col) * pts

    if lg.fg_miss:
        p = p + _col(df, "fg_missed") * lg.fg_miss

    return p.astype(float)


def score_dst(df: pd.DataFrame, lg: League):
    """NOT IMPLEMENTED — raises rather than returning zeros.

    Team DST scoring needs two things the weekly PLAYER file does not contain:
    points allowed (which lives in game/schedule data) and team-level
    aggregation of individual defensive lines. Holmdel's also scores 4th-down
    stops, which needs play-by-play.

    The rules are recorded in League.dst so streaming decisions can reason
    about them. Returning zeros here would be silently wrong — the exact
    failure mode this module exists to prevent.
    """
    raise NotImplementedError(
        f"DST scoring is not built. {lg.name}'s real rules are in its .dst "
        f"dict. If you fall back to a connector DST projection, SAY SO — its "
        f"sack value and points-allowed tiers are wrong for this league."
    )


def score_all(df: pd.DataFrame) -> pd.DataFrame:
    """Add one points column per league. Column names are the LEAGUES keys."""
    out = df.copy()
    for k, lg in LEAGUES.items():
        out[k] = score(df, lg)
    return out


def add_explosive_tds(weekly: pd.DataFrame, pbp: pd.DataFrame) -> pd.DataFrame:
    """Cameron Wood only: 40+ yard TDs pay a further +1 and stack with the
    40+ yard play bonus. The weekly box score has no such column, so derive the
    counts from play-by-play and merge them on.

    Adds columns: td40_pass, td40_rush, td40_rec.

    JOIN WARNING
    ------------
    This joins on GSIS player_id, NOT on player_name. nflverse's `player_name`
    is abbreviated to first-initial-plus-surname ("J.Allen", "J.Love") and is
    NOT unique: an earlier version of this function joined on it and credited
    Julian Love (safety) and Jeremiyah Love (RB) with Jordan Love's 40+ yard
    passing touchdowns, and Jonathan Allen (DT) with Josh Allen's. Never join
    nflverse tables on an abbreviated name.
    """
    need = {"season", "week", "touchdown", "yards_gained",
            "passer_player_id", "rusher_player_id", "receiver_player_id"}
    missing = need - set(pbp.columns)
    if missing:
        raise KeyError(f"play-by-play is missing {sorted(missing)}")
    if "player_id" not in weekly.columns:
        raise KeyError("weekly frame has no player_id — cannot join safely")

    big = pbp[(pbp.touchdown == 1) & (pbp.yards_gained >= 40)]

    out = weekly.copy()
    for col, label in [("passer_player_id", "td40_pass"),
                       ("rusher_player_id", "td40_rush"),
                       ("receiver_player_id", "td40_rec")]:
        t = (big[big[col].notna()]
             .groupby(["season", "week", col])
             .size().reset_index(name=label)
             .rename(columns={col: "player_id"}))
        out = out.merge(t, on=["season", "week", "player_id"], how="left")
        out[label] = out[label].fillna(0)

    return out


def prepare(weekly: pd.DataFrame, pbp: pd.DataFrame) -> pd.DataFrame:
    """Enrich a weekly frame with everything the leagues need beyond the box
    score. Run this ONCE after loading, then score off the result.

    Scoring a league with explosive-TD bonuses off a frame that hasn't been
    through here raises rather than quietly undercounting — see score().
    """
    return add_explosive_tds(weekly, pbp)


def describe(lg: League) -> str:
    """Human-readable summary of what this league actually scores."""
    lines = [f"{lg.name}  ({lg.teams} teams, '{lg.my_team}')",
             f"  key: {lg.key}"]
    rec_label = {1.0: "full PPR", 0.5: "half PPR", 0.0: "no PPR"}.get(lg.rec, f"{lg.rec}/rec")
    lines.append(f"  {rec_label} | pass TD {lg.pass_td:g} | INT {lg.pass_int:g}")
    if lg.rec_first_down:
        lines.append(f"  +{lg.rec_first_down:g} per RECEIVING FIRST DOWN  <- FantasyPros misses this")
    for stat, th, pts in lg.milestones:
        lines.append(f"  +{pts:g} at {th:g} {stat.replace('_', ' ')}  <- FantasyPros misses this")
    for stat, pts in lg.explosive:
        lines.append(f"  +{pts:g} per {stat.replace('_', ' ')}  <- FantasyPros misses this")
    if lg.return_yds_per_point:
        lines.append(f"  1 pt per {lg.return_yds_per_point:g} return yards  <- FantasyPros misses this")
    st = " / ".join(f"{v}{k}" for k, v in lg.starters.items())
    lines.append(f"  lineup: {st} | bench {lg.bench} | IR {lg.ir}")
    if lg.acquisitions_per_season:
        lines.append(f"  acquisition cap: {lg.acquisitions_per_season}/season, "
                     f"{lg.acquisitions_per_week}/week")
    if lg.playoff_weeks:
        lines.append(f"  {lg.playoff_weeks}")
    if lg.notes:
        lines.append(f"  NOTE: {lg.notes}")
    return "\n".join(lines)


if __name__ == "__main__":
    for lg in LEAGUES.values():
        print(describe(lg))
        print()
