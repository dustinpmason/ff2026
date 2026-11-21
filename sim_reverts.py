#!/usr/bin/env python3
"""S1. Break every behaviour in `ff_sim.py`, `ff_sim_opp.py`,
`ff_sim_eff.py`, `ff_sim_play.py`, `ff_sim_td.py` and `ff_sim_live.py` and
see that `test_sim.py` notices.

    python3 sim_reverts.py            # all of them; about 9 hours on 2 cores
    python3 sim_reverts.py --check    # only confirm each revert still applies
    python3 sim_reverts.py 8 9 17     # just these, by number (plus the controls)
    python3 sim_reverts.py --show 300 # ...and print which checks failed for each
    python3 sim_reverts.py --fast 613 614   # `ff_sim_live.py` reverts, about 12 s each

SIM-HANDOFF.md, "Before saying done", item 1: "Break every new check. Remove
the behaviour and confirm a check fails. A crash counts; a pass does not."
This is that, kept as a script so it can be run again after any change
instead of being claimed once.

How it works. Each entry below is one small edit to `ff_sim.py` (or, for
the entries made with `mut_opp`, `mut_eff`, `mut_play`, `mut_td` and
`mut_live`, to `ff_sim_opp.py`, `ff_sim_eff.py`, `ff_sim_play.py`,
`ff_sim_td.py` and `ff_sim_live.py`)
that removes or reverses one behaviour. For each, a temporary directory gets the edited
file, a COPY of `test_sim.py`, and links to every other module; the
suite is run there and its own last line is read. "ALL PASS" means the
revert was NOT CAUGHT. Anything else is caught.

The suite is copied, not linked, on purpose: Python puts a script's REAL
directory on its path, so a linked `test_sim.py` imports the real, unbroken
`ff_sim.py` and every revert reads ALL PASS. The first run of this did
exactly that and reported 0 of 148 caught.

Twelve controls run with EVERY pass, including a pass of a few numbered
reverts, and a pass that fails any of them proves nothing. Two for each
file: an edit that changes no behaviour must read NOT CAUGHT (so the
unbroken suite passes here, and the edited copy is the one imported), and
an edit that breaks something plain must be caught. They are numbers 0 to
11; the reverts start at 12.

`--fast` is for the newest file only (`FAST_TARGET`). Its sections are the
last in the suite and nothing before them imports it, so the earlier part
of the suite is run once, unbroken, in this process, and each revert runs
only the rest, in a child forked from that point with the edited file
first on its path. It refuses to start if a check before the cut fails or
the file has already been imported, which is what makes a child's verdict
the same as a full run's. The file's own two controls go the same way; the
other ten, and the unbroken suite at the end, are run in full as always.
Before it was first used, twelve entries (the two controls and ten
reverts) were run both ways: the same verdict and the same failing checks
for all twelve, in 214 s against 488 s.

An entry whose text no longer matches its file exactly once is reported
as BAD REVERT. That is a failure of this file, to be fixed here; it is
never to be read as "caught".

LAST RUNS — 2026-11-20 and 21, 2 cores. 981 reverts and 12 controls.

  `ff_sim.py` and `ff_sim_opp.py`, 355 reverts: 355 caught, 0 not, on a
  fresh clone in seven blocks, run before the later files existed.

  `ff_sim_eff.py`, 89 reverts: 89 caught, 0 not, on a fresh clone in
  three blocks; twelve of the 355 were run again alongside and caught.

  `ff_sim_play.py`, 62 reverts: 62 caught, 0 not, in the working copy,
  each run once. The first pass was 61 reverts, 58 caught; the three not
  caught were edits that changed nothing and were dropped (see
  SIM-BACKLOG, S13); the rest were added or rewritten after the review.

  `ff_sim_td.py`, 95 reverts, in the working copy. One pass of all 95
  after the first review's fixes: 93 caught, 2 not. One of the two was an
  edit that changed nothing (a guard the rewritten chance made redundant;
  the guard and the entry were dropped). The other was real: the check
  that a player with no number is left out of the table could not fail,
  and was replaced. Then the 18 entries those two edits touch (every
  entry in the chance of a line, and the table one) were run once more:
  18 caught, 0 not. The other 77 were not rerun after those edits, which
  removed two lines from the chance of a line and replaced one check in
  section 31.

  `ff_sim_live.py`, 380 reverts, in the working copy, with `--fast`. One
  pass of 378 (2026-11-21): 365 caught, 13 not. Three of the 13 were edits
  that change nothing and were dropped: a player added who is already on
  the slate is listed once either way, a status of "none" filed as a row
  reads the same as no row, and a touchdown line has no push to be put
  down to. Nine showed a check that could not fail, and each was added or
  tightened in sections 33 to 36 (an ESPN number of "nan"; the slate's
  four games exactly; a starter named for a team not playing; what a
  status handed in leaves alone, twice; the chance of scoring at 0.5; the
  starter printed before a busier quarterback; the chance of playing on
  a priced line; an added player's name looked for on his team first).
  The thirteenth was a name with no id being tied to a namesake's id,
  which the review found the same hour; that code was changed, its two
  reverts rewritten and five added. Then the 37 entries concerned (the 28
  whose text lies in the block that changed, the five new among them, and
  the nine above) were run once on the final file: 37 caught, 0 not. The
  other 343 were NOT rerun after that last edit, which changed only how a
  posted player is matched to a slate row; the suite has only been added
  to since they ran. Controls and the unbroken suite passed at the end of
  both runs.

  From 2026-11-20 the rule, set by Dustin, is: reverts for new code only,
  run once; earlier ones are not rerun while their file and their
  sections of the suite are byte for byte unchanged (checked against the
  commit each time). Each block runs the controls and the unbroken suite
  again at its end; all passed. The whole list has NOT been run in one go
  since the second file was added. Entry numbers shift when controls are
  added: find an entry by `--show` and its name, not by an old number.

The first full run of the `ff_sim.py` reverts alone (2026-11-20, 257 of
257) was run in four blocks. After its third block one fixture in
`test_sim.py` section 14 was made stricter, because revert "avail: share B
DID list" had not been caught, and the six availability reverts were run
again against it: all caught.
"""
from __future__ import annotations

import concurrent.futures as cf
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent
TARGETS = ("ff_sim.py", "ff_sim_opp.py", "ff_sim_eff.py", "ff_sim_play.py",
           "ff_sim_td.py", "ff_sim_live.py")
SRC = {f: (REPO / f).read_text() for f in TARGETS}
TEST = (REPO / "test_sim.py").read_text()

NULL = "CONTROL: nothing changed (must read NOT CAUGHT)"
BROKEN = "CONTROL: week key broken (must be caught)"
NULL_OPP = "CONTROL: nothing changed in ff_sim_opp.py (must read NOT CAUGHT)"
BROKEN_OPP = "CONTROL: ff_sim_opp.py's shared stats swapped (must be caught)"
NULL_EFF = "CONTROL: nothing changed in ff_sim_eff.py (must read NOT CAUGHT)"
BROKEN_EFF = "CONTROL: ff_sim_eff.py's stats reordered (must be caught)"
NULL_PLAY = "CONTROL: nothing changed in ff_sim_play.py (must read NOT CAUGHT)"
BROKEN_PLAY = "CONTROL: ff_sim_play.py's statuses reordered (must be caught)"
NULL_TD = "CONTROL: nothing changed in ff_sim_td.py (must read NOT CAUGHT)"
BROKEN_TD = "CONTROL: ff_sim_td.py's stats reordered (must be caught)"
NULL_LIVE = "CONTROL: nothing changed in ff_sim_live.py (must read NOT CAUGHT)"
BROKEN_LIVE = "CONTROL: ff_sim_live.py's anytime line moved (must be caught)"
CONTROLS = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11)
NULLS = (NULL, NULL_OPP, NULL_EFF, NULL_PLAY, NULL_TD, NULL_LIVE)
BROKENS = (BROKEN, BROKEN_OPP, BROKEN_EFF, BROKEN_PLAY, BROKEN_TD, BROKEN_LIVE)

M: list = []


def mut(name: str, *pairs) -> None:
    M.append((name, pairs, "ff_sim.py"))


def mut_opp(name: str, *pairs) -> None:
    M.append((name, pairs, "ff_sim_opp.py"))


def mut_eff(name: str, *pairs) -> None:
    M.append((name, pairs, "ff_sim_eff.py"))


def mut_play(name: str, *pairs) -> None:
    M.append((name, pairs, "ff_sim_play.py"))


def mut_td(name: str, *pairs) -> None:
    M.append((name, pairs, "ff_sim_td.py"))


def mut_live(name: str, *pairs) -> None:
    M.append((name, pairs, "ff_sim_live.py"))


# ---- controls on this runner itself
mut(NULL, ("def tkey(season: int, week: int) -> int:",
           "def tkey(season: int,  week: int) -> int:"))
mut(BROKEN, ("    return int(season) * 100 + int(week)",
             "    return int(season) * 100 + int(week) + 1"))
mut_opp(NULL_OPP, ('OPP_STATS = ("targets", "carries", "attempts")',
                   'OPP_STATS = ("targets",  "carries", "attempts")'))
mut_opp(BROKEN_OPP, ('SHARED = ("targets", "carries")',
                     'SHARED = ("carries", "targets")'))
mut_eff(NULL_EFF, ("EFF_STATS = (*OPP_STATS, *COUNTS, *YARDS)",
                   "EFF_STATS = (*OPP_STATS,  *COUNTS, *YARDS)"))
mut_eff(BROKEN_EFF, ("EFF_STATS = (*OPP_STATS, *COUNTS, *YARDS)",
                     "EFF_STATS = (*COUNTS, *OPP_STATS, *YARDS)"))
mut_play(NULL_PLAY, ('STATUSES = ("none", "listed", "questionable", "doubtful", "out")',
                     'STATUSES = ("none",  "listed", "questionable", "doubtful", "out")'))
mut_play(BROKEN_PLAY, ('STATUSES = ("none", "listed", "questionable", "doubtful", "out")',
                       'STATUSES = ("listed", "none", "questionable", "doubtful", "out")'))
mut_td(NULL_TD, ('TD_STATS = ("passing_tds", TD_STAT)', 'TD_STATS = ("passing_tds",  TD_STAT)'))
mut_td(BROKEN_TD, ('TD_STATS = ("passing_tds", TD_STAT)', 'TD_STATS = (TD_STAT, "passing_tds")'))
mut_live(NULL_LIVE, ("S21_FROM = 0.65", "S21_FROM  = 0.65"))
mut_live(BROKEN_LIVE, ('    "player_anytime_td": (TD_STAT, 0.5),', '    "player_anytime_td": (TD_STAT, 3.5),'))

# ---- the frame
mut("frame: active zeros dropped (left join)", ('how="outer"', 'how="left"'))
mut("frame: unplaced count wrong",
    ("unplaced = skill_snaps[skill_snaps.player_id.isna()]",
     "unplaced = skill_snaps[skill_snaps.player_id.notna()]"))
mut("frame: ambiguous PFR id guessed",
    ("for p, g in zip(x.pfr_id, x.gsis_id) if p not in ambiguous}",
     "for p, g in zip(x.pfr_id, x.gsis_id)}"))
mut("frame: weekly postseason kept",
    ('wk = weekly[weekly.season_type == "REG"].copy()', "wk = weekly.copy()"))
mut("frame: snaps postseason kept",
    ('sn = snaps[snaps.game_type == "REG"].copy()', "sn = snaps.copy()"))
mut("frame: duplicate weekly rows accepted",
    ('if wk.duplicated(["game_id", "player_id"]).any():', "if False:"))
mut("frame: missing column not refused",
    ('        if missing:\n            raise ValueError(f"{label} is missing',
     '        if False:\n            raise ValueError(f"{label} is missing'))
mut("frame: passing TD counted as anytime",
    ("    out[TD_STAT] = out.rushing_tds + out.receiving_tds\n\n    # Position",
     "    out[TD_STAT] = out.rushing_tds + out.receiving_tds + out.passing_tds\n\n    # Position"))
mut("frame: earlier weekly label not carried",
    ('carried = out["_wpos"].groupby(out["player_id"]).ffill()',
     'carried = out["_wpos"]'))
mut("frame: snap label preferred",
    ('carried.where(carried.notna(), out["_spos"])',
     'out["_spos"].where(out["_spos"].notna(), carried)'))
mut("frame: not sorted by player",
    ('out = out.sort_values(["player_id", "t"], kind="stable").reset_index(drop=True)\n    carried',
     'out = out.sort_values(["t", "player_id"], kind="stable").reset_index(drop=True)\n    carried'))
mut("frame: report counted over everyone",
    ("sk = out[out.position.isin(SKILL)]", "sk = out"))
mut("frame: defender thrown to not carried",
    ('qualifies = out["position"].isin(SKILL) | opp_row',
     'qualifies = out["position"].isin(SKILL)'))
mut("frame: carried from his FIRST game because of a later one",
    ('since = qualifies.groupby(out["player_id"]).cummax()',
     'since = qualifies.groupby(out["player_id"]).transform("max")'))
mut("frame: by-position share over all rows",
    ('for pos, g in on_field.groupby("position")}',
     'for pos, g in out.groupby("position")}'))
mut("describe: frame text",
    ("have no stat row and are \"\n            f\"graded as zeros.",
     "have no stat row and are \"\n            f\"dropped."))

# ---- history
mut("history: guard off by one",
    ("if len(t) and int(t.max()) >= self.before:",
     "if len(t) and int(t.max()) > self.before:"))
mut("history: guard removed",
    ("if len(t) and int(t.max()) >= self.before:", "if False:"))
mut("history: filter includes the week itself",
    ('return frame[frame["t"] < before]', 'return frame[frame["t"] <= before]'))
mut("history: filter AND guard both let the week in",
    ('return frame[frame["t"] < before]', 'return frame[frame["t"] <= before]'),
    ("if len(t) and int(t.max()) >= self.before:", "if False:"))
mut("history: min_season ignored",
    ('a += int(np.searchsorted(self.season_of[a:b], min_season, "left"))',
     "a += 0"))
mut("history: team look-back not limited",
    ("weeks = np.unique(self.t[idx])[-games:]",
     "weeks = np.unique(self.t[idx])"))
mut("history: missed counts his own last game",
    ("return int((self.team_weeks(team) > last).sum())",
     "return int((self.team_weeks(team) >= last).sum())"))
mut("history: last_week reads his first game",
    ("return int(self.t[sp[1] - 1]) if sp else None",
     "return int(self.t[sp[0]]) if sp else None"))
mut("history: missed returns 0 for an unknown player",
    ("        if last is None:\n            return None\n        return int((self.team_weeks",
     "        if last is None:\n            return 0\n        return int((self.team_weeks"))
mut("history: the build report rides along",
    ("        self.frame.attrs = {}      # the build report counts ALL seasons\n",
     ""))
mut("history: last position is his first",
    ("return self.position[sp[1] - 1] if sp else None",
     "return self.position[sp[0]] if sp else None"))

# ---- slates
mut("slate: extra column not refused",
    ('    if extra:\n        raise LeakError(f"a slate may carry',
     '    if False:\n        raise LeakError(f"a slate may carry'))
mut("slate: attrs not refused",
    ("    if slate.attrs:\n        raise LeakError(",
     "    if False:\n        raise LeakError("))
mut("slate: not checked before a projector sees it",
    ("        check_slate(slate)\n        slates[version] = slate",
     "        slates[version] = slate"))
mut("run: the projector is handed the harness's own slate",
    ("        outs = [pr.project(hist, slate.copy()) for pr in projectors]",
     "        outs = [pr.project(hist, slate) for pr in projectors]"))

# ---- frame checks
mut("check_frame: missing column accepted",
    ('    if missing:\n        raise ValueError(f"the frame is missing',
     '    if False:\n        raise ValueError(f"the frame is missing'))
mut("check_frame: repeated row accepted",
    ('    if frame.duplicated(["game_id", "player_id"]).any():\n        n = int(',
     '    if False:\n        n = int('))
mut("check_frame: wrong week key accepted",
    ('    if not (frame["t"] == frame["season"] * 100 + frame["week"]).all():',
     "    if False:"))
mut("run: frame not checked",
    ("    check_frame(frame)\n    names = [p.name for p in projectors]",
     "    names = [p.name for p in projectors]"))

# ---- lines and roles
mut("rungs: ceil instead of floor",
    ("by_line.setdefault(math.floor(median * f) + 0.5, f)",
     "by_line.setdefault(math.ceil(median * f) + 0.5, f)"))
mut("rungs: main label on the wrong factor",
    ('return [(MAIN if f == 1.0 else f"x{f:g}", line)',
     'return [(MAIN if f == 0.8 else f"x{f:g}", line)'))
mut("rungs: merge keeps the lowest factor",
    ("for f in sorted(RUNG_FACTORS, key=lambda f: abs(math.log(f))):",
     "for f in sorted(RUNG_FACTORS):"))
mut("rungs: not sorted",
    ("            for line, f in sorted(by_line.items())]",
     "            for line, f in by_line.items()]"))
mut("rungs: a negative median gets a ladder",
    ("    if median < 0:\n        # Scaling", "    if False:\n        # Scaling"))
mut("rungs: factors changed",
    ("RUNG_FACTORS = (0.6, 0.8, 1.0, 1.25, 1.6)",
     "RUNG_FACTORS = (0.5, 0.8, 1.0, 1.25, 1.6)"))
mut("line window: not limited to eight",
    ("return hist.rows(player_id, min_season=hist.season - 1)[-LINE_WINDOW:]",
     "return hist.rows(player_id, min_season=hist.season - 1)"))
mut("line window: nine games",
    ("LINE_WINDOW = 8 ", "LINE_WINDOW = 9 "))
mut("line window: reaches past last season",
    ("return hist.rows(player_id, min_season=hist.season - 1)[-LINE_WINDOW:]",
     "return hist.rows(player_id)[-LINE_WINDOW:]"))
mut("roles: no minimum games",
    ('    if len(win) < LINE_MIN_GAMES:\n        return {"recv": False',
     '    if len(win) < 1:\n        return {"recv": False'))
mut("lines: minimum games is three", ("LINE_MIN_GAMES = 4 ", "LINE_MIN_GAMES = 3 "))
mut("lines: minimum games is five", ("LINE_MIN_GAMES = 4 ", "LINE_MIN_GAMES = 5 "))
mut("roles: floor is exclusive",
    ("np.median(hist.col[opp][win]) >= ROLE_FLOOR[fam]",
     "np.median(hist.col[opp][win]) > ROLE_FLOOR[fam]"))
mut("roles: receiving floor moved",
    ('ROLE_FLOOR = {"recv": 3.0,', 'ROLE_FLOOR = {"recv": 3.5,'))
mut("roles: rushing floor moved", ('"rush": 5.0,', '"rush": 5.5,'))
mut("roles: passing floor moved", ('"pass": 20.0}', '"pass": 20.5}'))
mut("roles: td role ignores rushing",
    ('r["td"] = r["recv"] or r["rush"]', 'r["td"] = r["recv"]'))
mut("lines: no minimum games",
    ("    if len(win) < LINE_MIN_GAMES:\n        return []",
     "    if len(win) < 1:\n        return []"))
mut("lines: touchdown gets a ladder",
    ("    if stat == TD_STAT:\n        return [(MAIN, 0.5)]",
     "    if False:\n        return [(MAIN, 0.5)]"))
mut("lines: every ladder built on targets",
    ("return rungs(float(np.median(hist.col[stat][win])))",
     'return rungs(float(np.median(hist.col["targets"][win])))'))
mut("eligibility: quarterbacks get no rushing projection",
    ('"rush": ("RB", "QB"),', '"rush": ("RB",),'))
mut("eligibility: quarterbacks get a touchdown projection",
    ('"pass": ("QB",), "td": ("RB", "WR", "TE")}',
     '"pass": ("QB",), "td": ("RB", "WR", "TE", "QB")}'))
mut("slate B: looks back five games",
    ("CANDIDATE_LOOKBACK = 4 ", "CANDIDATE_LOOKBACK = 5 "))

# ---- one lined quarterback
# ---- yardsticks
mut("hit_share: no half-game pull",
    ("    return float(((x > line).sum() + 0.5) / (len(x) + 1.0))",
     "    return float(((x > line).sum()) / max(len(x), 1))"))
mut("hit_share: on the line counts as over",
    ("    return float(((x > line).sum() + 0.5) / (len(x) + 1.0))",
     "    return float(((x >= line).sum() + 0.5) / (len(x) + 1.0))"))
mut("hit_share: no games is a coin flip",
    ('    if not len(x):\n        return float("nan")        # no games',
     '    if False:\n        return float("nan")        # no games'))
mut("season avg: includes last season",
    ("return hist.values(player_id, stat, min_season=hist.season)",
     "return hist.values(player_id, stat, min_season=hist.season - 1)"))
mut("last four: is last five",
    ("return hist.values(player_id, stat, min_season=hist.season - 1)[-4:]",
     "return hist.values(player_id, stat, min_season=hist.season - 1)[-5:]"))
mut("last four: this season only",
    ("return hist.values(player_id, stat, min_season=hist.season - 1)[-4:]",
     "return hist.values(player_id, stat, min_season=hist.season)[-4:]"))
mut("gamelog: keeps games with no stat row",
    ("        keep = hist.has_stats[r]\n",
     "        keep = np.ones(len(r), dtype=bool)\n"))
mut("gamelog: keeps games with no opportunity",
    ("        if opp:\n            keep = keep & (hist.col[opp][r] > 0)",
     "        if False:\n            keep = keep & (hist.col[opp][r] > 0)"))
mut("gamelog: two seasons becomes one",
    ("        r = hist.rows(player_id, min_season=hist.season - 1)\n        keep",
     "        r = hist.rows(player_id, min_season=hist.season)\n        keep"))
mut("gamelog: point is the mean",
    ("    def point_of(self, x):\n        return float(np.median(x))",
     "    def point_of(self, x):\n        return float(np.mean(x))"))
mut("gamelog: point given on two games",
    ('    name = "gamelog_model"\n    min_games = 3',
     '    name = "gamelog_model"\n    min_games = 1'))
mut("blend: weights changed",
    ("0.45 * emp + 0.25 * para + 0.30 * rec",
     "0.50 * emp + 0.25 * para + 0.25 * rec"))
mut("blend: half-life changed",
    ("def gamelog_blend(x: np.ndarray, line: float, half_life: float = 6.0)",
     "def gamelog_blend(x: np.ndarray, line: float, half_life: float = 5.0)"))
mut("blend: clip removed",
    ("0.45 * emp + 0.25 * para + 0.30 * rec, 0.01, 0.99))",
     "0.45 * emp + 0.25 * para + 0.30 * rec, 0.0, 1.0))"))
mut("blend: flat log branch",
    ("        para = float(x[0] >= line)", "        para = 0.5"))
mut("blend: population sd",
    ("float(x.std(ddof=1))", "float(x.std(ddof=0))"))
mut("blend: fewer than three games allowed",
    ('    n = len(x)\n    if n < 3:\n        return float("nan")\n    over = x >= line',
     '    n = len(x)\n    if n < 2:\n        return float("nan")\n    over = x >= line'))
mut("blend: a missing game is kept",
    ("    x = x[~np.isnan(x)]            # as the engine does\n", ""))
mut("yardstick: probability given with no games",
    ("        return self.owner.prob_of(x, line) if len(x) >= self.owner.min_games \\",
     "        return self.owner.prob_of(x, line) if len(x) >= 0 \\"),
    ('    if not len(x):\n        return float("nan")        # no games',
     '    if False:\n        return float("nan")        # no games'))
mut("yardstick: point given under its minimum",
    ("        return self.owner.point_of(x) if len(x) >= self.owner.min_games \\",
     "        return self.owner.point_of(x) if len(x) >= 1 \\"))
mut("yardstick: mean replaced by median",
    ("    def point_of(self, x: np.ndarray) -> float:\n        return float(x.mean())",
     "    def point_of(self, x: np.ndarray) -> float:\n        return float(np.median(x))"))

# ---- the walk-forward
mut("run: truth ignores the team",
    ("            k = truth.get((game_id, team, pid))",
     "            k = next((v for kk, v in truth.items() if kk[0] == game_id and kk[2] == pid), None)"))
mut("run: no-role players get no projection",
    ("                if not (role[fam] or pos in POSITIONS[fam]):\n                    continue",
     "                if not role[fam]:\n                    continue"))
mut("run: everyone eligible for every stat",
    ("                if not (role[fam] or pos in POSITIONS[fam]):\n                    continue",
     "                if False:\n                    continue"))
mut("run: no-role players get lines",
    ("                if not role[fam]:\n                    continue\n                ladder",
     "                if False:\n                    continue\n                ladder"))
mut("run: did-not-play scored as zero",
    ('                act = float(actual[stat][k]) if played else float("nan")',
     "                act = float(actual[stat][k]) if played else 0.0"))
mut("run: did-not-play given a result",
    ("                    over = (act > line) if played else None",
     "                    over = (act > line)"))
mut("run: over means under",
    ("                    over = (act > line) if played else None",
     "                    over = (act < line) if played else None"))
mut("run: bad probability accepted",
    ("                        if not (math.isnan(p) or 0.0 <= p <= 1.0):",
     "                        if False:"))
mut("run: infinite projection accepted",
    ("                    if not (math.isnan(v) or math.isfinite(v)):",
     "                    if False:"))
mut("run: duplicate names accepted",
    ("    if len(set(names)) != len(names):", "    if False:"))
mut("run: undeclared slate reader accepted",
    ("        if differ:\n            raise LeakError(",
     "        if False:\n            raise LeakError("))
mut("run: version gap always zero",
    ('        differ += int((~_same(m[f"{col}_a"], m[f"{col}_b"])).sum())',
     "        differ += 0"))
mut("run: version gap compares single numbers only",
    ('                           ["game_id", "team", "player_id", "stat", "line"])):',
     '                           ["game_id", "team", "player_id", "stat", "line"]))[:1]:'))
mut("run: an unchecked claim is not reported",
    ("        if not compared and len(points):", "        if False:"))
mut("run: NOT CHECKED left out of describe",
    ("        if self.unverified:\n            out +=", "        if False:\n            out +="))
mut("run: 2023 graded",
    ("                if t // 100 >= first_season)", "                if t // 100 >= 0)"))
mut("run: the newest week graded by default",
    ("        return [t for t in ts if t != newest]", "        return ts"))
mut("run: `through` ignored by test_weeks",
    ("    return [t for t in ts if t <= through]", "    return ts"))
mut("run: `through` not passed on",
    ("    weeks = list(weeks) if weeks is not None else test_weeks(frame,\n                                                             through=through)",
     "    weeks = list(weeks) if weeks is not None else test_weeks(frame)"))
mut("run: a week with no game run empty",
    ("    if absent:\n        raise ValueError(f\"no game on file",
     "    if False:\n        raise ValueError(f\"no game on file"))
mut("run: slates never kept",
    ("        if keep_slates:\n            slates[t] = s",
     "        if False:\n            slates[t] = s"))
mut("run: main line not recorded",
    ('                main_line = dict(ladder).get(MAIN, float("nan"))',
     '                main_line = float("nan")'))
# ---- a projector's own joint
mut("joint: bad value accepted",
    ("                if not (math.isnan(j) or 0.0 <= j <= 1.0):",
     "                if False:"))
mut("joint: a player paired with himself",
    ("                if ls[x][1] != ls[y][1]:", "                if True:"))
mut("joint: asked of version B too",
    ('        if version == "A":\n            joints.extend(',
     "        if True:\n            joints.extend("))
mut("joint: position ignored",
    ("            if st == stat and ident[i][7] in positions:",
     "            if st == stat:"))
mut("joint: not merged into the pairs",
    ("    if joints is not None and len(joints):", "    if False:"))
mut("joint: sides not the correlation table's",
    ("    return [(side, tuple(pos), TD_STAT if col == \"_anytime_td\" else col,\n             bool(binary))",
     "    return [(side, tuple(pos), TD_STAT if col == \"_anytime_td\" else col,\n             False)"))

# ---- the leak probe
mut("probe: scramble spares the week itself",
    ('    late = (out["t"] >= before).to_numpy()',
     '    late = (out["t"] > before).to_numpy()'))
mut("probe: scramble changes nothing",
    ("        out.loc[late, c] = 900.0 + 37.0 * j + out.loc[late, c].fillna(0.0) * 3.0",
     "        pass"))
mut("probe: scramble leaves a missing snap count missing",
    ("        out.loc[late, c] = 900.0 + 37.0 * j + out.loc[late, c].fillna(0.0) * 3.0",
     "        out.loc[late, c] = 900.0 + 37.0 * j + out.loc[late, c] * 3.0"))
mut("probe: scramble leaves snap share alone",
    ('    out.loc[late, "offense_pct"] = 0.99\n', ""))
mut("probe: scramble leaves has_stats alone",
    ('    out.loc[late, "has_stats"] = True\n', ""))
mut("probe: scramble leaves the TD column alone",
    ("    out.loc[late, \"has_stats\"] = True\n    out[TD_STAT] = out.rushing_tds + out.receiving_tds\n",
     "    out.loc[late, \"has_stats\"] = True\n"))
mut("probe: never counts a change",
    ("            if not _eq(x, y):\n                probe.changed += 1",
     "            if False:\n                probe.changed += 1"))
mut("probe: a different row count ignored",
    ("    if len(real) != len(fake):\n        probe.changed += 1",
     "    if False:\n        probe.changed += 1"))
mut("probe: clean without measuring",
    ("        return self.measured and self.changed == 0",
     "        return self.changed == 0"))
mut("probe: results compared too",
    ("_LEG_RESULT = frozenset({len(_BASE_COLS) + 4, len(_BASE_COLS) + 5})",
     "_LEG_RESULT = frozenset()"))
mut("probe: point results compared too",
    ("_PT_RESULT = frozenset({len(_BASE_COLS) + 2})", "_PT_RESULT = frozenset()"))
mut("probe: runs the real frame twice",
    ("        fake = run_week(scramble_from(frame, t), t, projectors)",
     "        fake = run_week(frame, t, projectors)"))
mut("probe: NOT MEASURED reads as no leak",
    ('            return (f"LEAK PROBE: NOT MEASURED',
     '            return (f"LEAK PROBE: no leak'))
mut("probe: does not say what it cannot see",
    ('f"everything after it, was overwritten. It cannot see a "\n                f"projector that carries its own data.")',
     'f"everything after it, was overwritten.")'))
# ---- error bars, ranges, verdicts
mut("cluster: no small-sample factor",
    ("    se = math.sqrt(g / (g - 1.0) * float((sums ** 2).sum())) / n",
     "    se = math.sqrt(float((sums ** 2).sum())) / n"))
mut("cluster: not clustered",
    ("    sums = np.bincount(codes, weights=x - m, minlength=g)",
     "    sums = x - m"))
mut("cluster: one game gets an error bar",
    ('    if g < 2:\n        return m, float("nan"), n, g',
     '    if g < 1:\n        return m, float("nan"), n, g'))
mut("cluster: empty returns zero",
    ('    if n == 0:\n        return float("nan"), float("nan"), 0, 0',
     "    if n == 0:\n        return 0.0, 0.0, 0, 0"))
mut("range: multiplier is 2", ("Z95 = 1.96", "Z95 = 2.0"))
mut("range: empty is 0%",
    ('        return {"rate": float("nan"), "se": float("nan"), "n": 0, "games": 0,',
     '        return {"rate": 0.0, "se": float("nan"), "n": 0, "games": 0,'))
mut("read: verdict under 30 games",
    ('    if r["games"] < MIN_GAMES_FOR_VERDICT:\n        return "too few games to say"',
     '    if False:\n        return "too few games to say"'))
mut("read: the minimum is 31 games",
    ("MIN_GAMES_FOR_VERDICT = 30", "MIN_GAMES_FOR_VERDICT = 31"))
mut("read: the minimum is 29 games",
    ("MIN_GAMES_FOR_VERDICT = 30", "MIN_GAMES_FOR_VERDICT = 29"))
mut("read: nothing is ever as stated",
    ('    if r["lo"] <= stated <= r["hi"]:', "    if False:"))
mut("read: LESS and MORE swapped",
    ('    return ("happens LESS than stated" if r["rate"] < stated\n            else "happens MORE than stated")',
     '    return ("happens MORE than stated" if r["rate"] < stated\n            else "happens LESS than stated")'))
mut("verdict: no game minimum",
    ('    if games < MIN_GAMES_FOR_VERDICT or not math.isfinite(se):\n        return "too few games to say"',
     '    if not math.isfinite(se):\n        return "too few games to say"'))
mut("verdict: noise never called noise",
    ('    if abs(diff) <= Z95 * se:\n        return "no difference',
     '    if False:\n        return "no difference'))
mut("verdict: one standard error",
    ("    if abs(diff) <= Z95 * se:", "    if abs(diff) <= 1.0 * se:"))
mut("verdict: four standard errors",
    ("    if abs(diff) <= Z95 * se:", "    if abs(diff) <= 4.0 * se:"))
mut("verdict: direction swapped",
    ('    return "lower" if diff < 0 else "higher"',
     '    return "higher" if diff < 0 else "lower"'))

# ---- the stat-line miss
mut("error: typical miss is the mean",
    ("                        float(np.median(np.abs(err))), mean_abs, se,",
     "                        float(np.mean(np.abs(err))), mean_abs, se,"))
mut("error: bias sign",
    ("            err = (u[c] - u.actual).to_numpy(dtype=float)",
     "            err = (u.actual - u[c]).to_numpy(dtype=float)"))
mut("error: not clustered by game",
    ("            mean_abs, se, _, g = cluster_mean(np.abs(err), u.game_id)",
     "            mean_abs, se, _, g = cluster_mean(np.abs(err), np.arange(len(u)))"))
mut("error: role filter ignored",
    ("    if role_only:\n        d = d[d.role.astype(bool)]\n    if dnp_as_zero:",
     "    if False:\n        d = d[d.role.astype(bool)]\n    if dnp_as_zero:"))
mut("error: did-not-play kept",
    ("    else:\n        d = d[d.played.astype(bool)]\n    cols",
     "    else:\n        d = d\n    cols"))
mut("error: dnp_as_zero does nothing",
    ("        d = d.assign(actual=d.actual.where(d.played.astype(bool), 0.0))",
     "        d = d[d.played.astype(bool)]"))
mut("error: common ignored",
    ("        use = s[has.all(axis=1)] if common else s", "        use = s"))
mut("error: coverage always 1",
    ("            rec.append((stat, n, len(u), g, float(has[c].mean()),",
     "            rec.append((stat, n, len(u), g, 1.0,"))
mut("error: version not checked",
    ('    if version not in ("A", "B"):', "    if False:"))
mut("error: version filter ignored",
    ("    return df[df.version == version]", "    return df"))
mut("compare_error: a and b swapped",
    ('        diff = (np.abs(s[f"pt_{a}"] - s.actual)\n                - np.abs(s[f"pt_{b}"] - s.actual))',
     '        diff = (np.abs(s[f"pt_{b}"] - s.actual)\n                - np.abs(s[f"pt_{a}"] - s.actual))'))
mut("compare_error: did-not-play kept",
    ("    d = _select(run.points, version)\n    d = d[d.played.astype(bool)]\n    if role_only:\n        d = d[d.role.astype(bool)]\n    rec = []",
     "    d = _select(run.points, version)\n    if role_only:\n        d = d[d.role.astype(bool)]\n    rec = []"))
mut("compare_error: role filter ignored",
    ("    d = d[d.played.astype(bool)]\n    if role_only:\n        d = d[d.role.astype(bool)]\n    rec = []",
     "    d = d[d.played.astype(bool)]\n    rec = []"))

# ---- calibration of single lines
mut("legs: did-not-play kept",
    ("    d = _select(run.legs, version)\n    d = d[d.played.astype(bool)]\n    if stats is not None:",
     "    d = _select(run.legs, version)\n    if stats is not None:"))
mut("legs: stats filter ignored",
    ("    if stats is not None:\n        d = d[d.stat.isin(list(stats))]\n    if rung is not None:\n        d = d[d.rung == rung]\n    return d",
     "    if rung is not None:\n        d = d[d.rung == rung]\n    return d"))
mut("legs: rung filter ignored",
    ("    if rung is not None:\n        d = d[d.rung == rung]\n    return d",
     "    return d"))
mut("cal: a leg with no probability graded",
    ('    d = d[d[f"p_{name}"].notna()].copy()', "    d = d.copy()"))
mut("cal: exactly 50% put on UNDER",
    ("    fav_over = d.p >= 0.5", "    fav_over = d.p > 0.5"))
mut("cal: not folded",
    ('    d["p_side"] = np.where(fav_over, d.p, 1.0 - d.p)', '    d["p_side"] = d.p'))
mut("cal: hit ignores the side",
    ('    d["hit"] = np.where(fav_over, over, ~over)', '    d["hit"] = over'))
mut("cal: no edge tolerance", ("_EDGE = 1e-9 ", "_EDGE = 0.0 "))
mut("cal: top band excludes 100%",
    ("    return (q >= lo) & ((p <= hi + _EDGE) if last else (q < hi))",
     "    return (q >= lo) & (q < hi)"))
mut("cal: ladder not deduped",
    ('            b = b.sort_values("_near", kind="stable").drop_duplicates(dedupe)',
     '            b = b.sort_values("_near", kind="stable")'))
mut("cal: dedupe merges the two sides",
    ('                       ["game_id", "team", "player_id", "stat", "side"])',
     '                       ["game_id", "team", "player_id", "stat"])'))
mut("cal: dedupe merges two stats",
    ('                       ["game_id", "team", "player_id", "stat", "side"])',
     '                       ["game_id", "team", "player_id", "side"])'))
mut("cal: dedupe keeps the first rung, not the nearest",
    ("    d = legs.assign(_near=(legs.line - legs.main_line).abs())",
     "    d = legs.assign(_near=0)"))
mut("cal: not clustered by game",
    ('        r = rate_range(b[hit_col].astype(float), b.game_id)',
     '        r = rate_range(b[hit_col].astype(float), np.arange(len(b)))'))
mut("cal: stated is the band's middle",
    ("        stated = float(b[p_col].mean())", "        stated = (lo + hi) / 2"))
mut("cal: unfolded still folds",
    ('    p_col, hit_col = ("p_side", "hit") if folded else ("p", "over")',
     '    p_col, hit_col = ("p_side", "hit")'))
mut("cal: empty band silently dropped",
    ('            rec.append((label, 0, 0, 0, *(float("nan"),) * 5, "no legs"))\n            continue',
     "            continue"))

# ---- scores
mut("score: not on common legs",
    ('    cols = [f"p_{n}" for n in run.names]\n    d = d[d[cols].notna().all(axis=1)]\n    y = d["over"].astype(float).to_numpy()',
     '    cols = [f"p_{n}" for n in run.names]\n    y = d["over"].astype(float).to_numpy()'))
mut("score: Brier is absolute error",
    ("        b, se, k, g = cluster_mean((p - y) ** 2, d.game_id)",
     "        b, se, k, g = cluster_mean(np.abs(p - y), d.game_id)"))
mut("score: log loss sign",
    ("        ll = float(-(y * np.log(q) + (1 - y) * np.log(1 - q)).mean())",
     "        ll = float((y * np.log(q) + (1 - y) * np.log(1 - q)).mean())"))
mut("score: compare_brier swapped",
    ('    diff = (d[f"p_{a}"] - y) ** 2 - (d[f"p_{b}"] - y) ** 2',
     '    diff = (d[f"p_{b}"] - y) ** 2 - (d[f"p_{a}"] - y) ** 2'))
mut("score: compare_brier keeps a leg one did not price",
    ('    d = d[d[f"p_{a}"].notna() & d[f"p_{b}"].notna()]\n    y = d["over"].astype(float)',
     '    d = d[d[f"p_{a}"].notna()]\n    y = d["over"].astype(float)'))
# ---- what the active list is worth
mut("avail: difference swapped",
    ('    diff = (np.abs(m[f"{col}_a"] - m.actual) - np.abs(m[f"{col}_b"] - m.actual))',
     '    diff = (np.abs(m[f"{col}_b"] - m.actual) - np.abs(m[f"{col}_a"] - m.actual))'))
mut("avail: no-role players compared",
    ('    m = m[m.role.astype(bool) & m[f"{col}_a"].notna() & m[f"{col}_b"].notna()]',
     '    m = m[m[f"{col}_a"].notna() & m[f"{col}_b"].notna()]'))
mut("avail: A share over all players",
    ("    ar = a[a.role.astype(bool)].drop_duplicates(keys)",
     "    ar = a.drop_duplicates(keys)"))
mut("avail: share who DID play",
    ('"b_did_not_play": (float((~br.played.astype(bool)).mean())',
     '"b_did_not_play": (float((br.played.astype(bool)).mean())'))
mut("avail: share B DID list",
    ('"a_not_on_b": float(1.0 - seen / len(ar))', '"a_not_on_b": float(seen / len(ar))'))

# ---- pairs
mut("pairs: every rung is a side leg",
    ("    d = _legs(run, version, None, MAIN)\n    d = d[d[f\"p_{name}\"].notna()]\n    out = []",
     "    d = _legs(run, version, None, None)\n    d = d[d[f\"p_{name}\"].notna()]\n    out = []"))
mut("pairs: a leg with no probability is a side leg",
    ("    d = _legs(run, version, None, MAIN)\n    d = d[d[f\"p_{name}\"].notna()]\n    out = []",
     "    d = _legs(run, version, None, MAIN)\n    out = []"))
mut("pairs: position ignored",
    ("        s = d[(d.stat == stat) & d.position.isin(list(positions))]",
     "        s = d[(d.stat == stat)]"))
mut("pairs: a player paired with himself",
    ("    m = m[m.player_id_a != m.player_id_b]\n    first", "    first"))
mut("pairs: each pair twice", ("    m = m[first].copy()", "    m = m.copy()"))
mut("pairs: relation swapped",
    ('    m["relation"] = np.where(m.team_a == m.team_b, "same", "opp")',
     '    m["relation"] = np.where(m.team_a == m.team_b, "opp", "same")'))
mut("pairs: both means either",
    ('    m["both"] = m.hit_a & m.hit_b', '    m["both"] = m.hit_a | m.hit_b'))
mut("pairs: across games",
    ('    m = sl.merge(sl, on=["season", "game_id"], suffixes=("_a", "_b"))',
     '    m = sl.merge(sl, on=["season"], suffixes=("_a", "_b"))'))
mut("pairs: joint not held in bounds",
    ("    return float(min(max(j, max(0.0, pa + pb - 1.0)), min(pa, pb)))",
     "    return float(j)"))
mut("pairs: yes/no flags ignored",
    ("    j = pa * pb * (1.0 + r * _engine_pair_weight()(pa, pb, za, zb,\n                                                    bin_a, bin_b))",
     "    j = pa * pb * (1.0 + r * _engine_pair_weight()(pa, pb, za, zb,\n                                                    False, False))"))
mut("pairs: correlation ignored",
    ("    j = pa * pb * (1.0 + r * _engine_pair_weight()(pa, pb, za, zb,",
     "    j = pa * pb * (1.0 + 0 * r * _engine_pair_weight()(pa, pb, za, zb,"))
mut("pairs: a leg at exactly 1 not handled by corr_joint",
    ("    if not (0.0 < pa < 1.0 and 0.0 < pb < 1.0):\n        return float(pa * pb)\n",
     ""))
mut("pairs: sides not sorted for the lookup",
    ("        r = t.get((rel, *sorted((sa, sb))))", "        r = t.get((rel, sa, sb))"))
mut("pairs: per-season table ignored",
    ("        t = table.get(int(season), {}) if by_season else table",
     "        t = table"))
mut("pairs: unmeasured flagged measured",
    ("            vals.append(pa * pb)\n            had.append(False)",
     "            vals.append(pa * pb)\n            had.append(True)"))
mut("pairs: a 100% leg flagged as adjusted",
    ("        if r is None or not 0.0 < pa < 1.0 or not 0.0 < pb < 1.0:",
     "        if r is None:"))
mut("pairs: singles product is the stated one",
    ("        sp = ma * mb\n", '        sp = float(g["product"].mean())\n'))
mut("pairs: lift inverted",
    ('        lift = rate / sp if sp > 0 else float("nan")',
     '        lift = sp / rate if sp > 0 else float("nan")'))
mut("pairs: cell error not clustered",
    ("        rate, se, n, k = cluster_mean(both, g.game_id)",
     "        rate, se, n, k = cluster_mean(both, np.arange(len(g)))"))
mut("pairs: score difference swapped",
    ("        diff, se, _, _ = cluster_mean(loss - base, d.game_id)",
     "        diff, se, _, _ = cluster_mean(base - loss, d.game_id)"))
mut("pairs: score error not clustered",
    ("        diff, se, _, _ = cluster_mean(loss - base, d.game_id)",
     "        diff, se, _, _ = cluster_mean(loss - base, np.arange(len(d)))"))
mut("pairs: scored on pairs a method has no number for",
    ("    d = pairs[pairs[cols].notna().all(axis=1)]\n    y = d.both.astype(float)",
     "    d = pairs\n    y = d.both.astype(float)"))
mut("pairs: relation filter ignored",
    ("    d = pairs if relation is None else pairs[pairs.relation == relation]",
     "    d = pairs"))
mut("pairs: calibration keeps empty bands",
    ('    return (t[t.n > 0].drop(columns=["legs_before_dedupe"])',
     '    return (t.drop(columns=["legs_before_dedupe"])'))
mut("pairs: calibration happened is the stated",
    ('    t = _band_table(d, col, "both", bands, None)',
     "    t = _band_table(d, col, col, bands, None)"))

# ---- added 2026-11-19, after the second review
mut("frame: the LAST passer is called the starter",
    ('             .drop_duplicates(["game_id", "team"]))\n    started',
     '             .drop_duplicates(["game_id", "team"], keep="last"))\n    started'))
mut("frame: a non-quarterback who threw first is the starter",
    ('    pb = pb.merge(out.loc[out.position == "QB", ["game_id", "team", "player_id"]],',
     '    pb = pb.merge(out.loc[:, ["game_id", "team", "player_id"]],'))
mut("frame: starter by row order, not play order",
    ('    first = (pb.sort_values(["game_id", "team", "order_sequence"], kind="stable")',
     '    first = (pb.sort_values(["game_id", "team"], kind="stable")'))
mut("frame: starters counted wrong in the report",
    ('        "team_games_with_a_starting_qb": int(out.qb_start.sum()),',
     '        "team_games_with_a_starting_qb": int(len(team_games)),'))
mut("history: the starter of the team's OLDEST game",
    ("        newest = idx[self.t[idx] == self.t[idx].max()]",
     "        newest = idx[self.t[idx] == self.t[idx].min()]"))
mut("history: any quarterback is the last starter",
    ("        who = self.player[newest[self.qb_start[newest]]]",
     '        who = self.player[newest[self.position[newest] == "QB"]]'))
mut("slate A: today's label instead of the one he had going in",
    ("        label = (prior if prior is not None\n                 else snap if isinstance(snap, str) and snap else own)",
     "        label = own"))
mut("slate A: the build report rides along",
    ("    out = out[np.array(keep, dtype=bool)].reset_index(drop=True)\n    out.attrs = {}\n",
     "    out = out[np.array(keep, dtype=bool)].reset_index(drop=True)\n"))
mut("slate A: a lineman's first touch puts him on the slate",
    ("        keep.append(prior is not None or label in SKILL)",
     "        keep.append(True)"))
mut("slate A: only skill labels, whatever his history",
    ("        keep.append(prior is not None or label in SKILL)",
     "        keep.append(label in SKILL)"))
mut("slate A: nobody is marked as starting",
    ('    out["starting_qb"] = cur["qb_start"].to_numpy(dtype=bool)',
     '    out["starting_qb"] = False'))
mut("slate B: built from who is active today",
    ("        for pid in hist.team_recent_players(g.team, lookback):",
     '        for pid in sorted(set(frame.loc[(frame["t"] == hist.before) & (frame["team"] == g.team), "player_id"])):'))
mut("slate B: nobody is marked as the last starter",
    ("                        pid == qb))", "                        False))"))
mut("slate B: today's starter is read from the frame",
    ("        qb = hist.last_starting_qb(g.team)",
     '        qb = next(iter(frame.loc[(frame["t"] == hist.before) & (frame["team"] == g.team) & frame["qb_start"], "player_id"]), None)'))
mut("quarterbacks: every one with a starter's median is lined",
    ('        if role["pass"] and not starts:', "        if False:"))
mut("quarterbacks: a backup keeps his rushing line",
    ("            role = dict.fromkeys(role, False)",
     '            role = dict(role, **{"pass": False})'))
mut("quarterbacks: the starter loses his line",
    ('        if role["pass"] and not starts:', '        if role["pass"] and starts:'))
mut("run: newest input not recorded",
    ("        out.append((win, role, hist.last_week(pid),",
     "        out.append((win, role, None,"))
mut("check_frame: a missing stat accepted",
    ('    if blank:\n        raise ValueError(f"the frame has a missing value',
     '    if False:\n        raise ValueError(f"the frame has a missing value'))
mut("run: a blank beside a blank counts as compared",
    ('        compared += int((m[f"{col}_a"].notna() | m[f"{col}_b"].notna()).sum())',
     "        compared += len(m)"))
mut("joint: rows written when nobody states one",
    ("    if not pairs or not any(able):\n        return []",
     "    if not pairs:\n        return []"))
mut("joint: a None answer ends up a zero",
    ('                j = float("nan") if got is None else float(got)',
     "                j = 0.0 if got is None else float(got)"))
mut("joint: asked about the first leg twice",
    ("                got = o.p_both(a[2], a[3], a[4], b[2], b[3], b[4])",
     "                got = o.p_both(a[2], a[3], a[4], a[2], a[3], a[4])"))
mut("joint: the two legs' lines swapped",
    ("                got = o.p_both(a[2], a[3], a[4], b[2], b[3], b[4])",
     "                got = o.p_both(a[2], a[3], b[4], b[2], b[3], a[4])"))
mut("joint: written against the pair the other way round",
    ("        rows.append((game_id, a[1], a[0], b[1], b[0], *js))",
     "        rows.append((game_id, b[1], b[0], a[1], a[0], *js))"))
mut("probe: one talking projector covers a silent one",
    ("        return bool(self.outputs) and not self.silent",
     "        return sum(self.outputs.values()) > 0"))
mut("probe: a blank output counted as measured",
    ("                if not (isinstance(x, float) and math.isnan(x)):\n                    probe.outputs[names[j - first_output]] += 1",
     "                if True:\n                    probe.outputs[names[j - first_output]] += 1"))
mut("probe: the silent projector is not named",
    ('            who = ", ".join(self.silent) or "any projector"',
     '            who = "any projector"'))
mut("probe: joints not compared",
    ("        _diff_rows(real[3], fake[3], frozenset(), _JOINT_OUT, names, probe, t)\n", ""))
mut("probe: legs not compared",
    ("        _diff_rows(real[1], fake[1], _LEG_RESULT, _LEG_OUT, names, probe, t)\n", ""))
mut("probe: points not compared",
    ("        _diff_rows(real[0], fake[0], _PT_RESULT, _PT_OUT, names, probe, t)\n", ""))
mut("range: rate plus or minus two errors",
    ("    lo = 0.0 if rate == 0.0 else max(0.0, mid - half)\n    hi = 1.0 if rate == 1.0 else min(1.0, mid + half)",
     "    lo = rate - Z95 * se\n    hi = rate + Z95 * se"))
mut("range: 100% left a rounding hair short",
    ("    hi = 1.0 if rate == 1.0 else min(1.0, mid + half)",
     "    hi = min(1.0, mid + half)"))
mut("range: 0% left a rounding hair above",
    ("    lo = 0.0 if rate == 0.0 else max(0.0, mid - half)",
     "    lo = max(0.0, mid - half)"))
mut("reference: one rate for all rungs",
    ('    base = (y.groupby([d.stat, d.rung]).transform("mean") if len(d)',
     '    base = (y.groupby([d.stat]).transform("mean") if len(d)'))
mut("reference: one rate for all stats",
    ('    base = (y.groupby([d.stat, d.rung]).transform("mean") if len(d)',
     '    base = (y.groupby([d.rung]).transform("mean") if len(d)'))
mut("reference: not on the legs every projector priced",
    ('    d = d[d[[f"p_{n}" for n in run.names]].notna().all(axis=1)]\n    y = d["over"].astype(float)\n    base',
     '    y = d["over"].astype(float)\n    base'))
mut("reference: the gap to it is the wrong way round",
    ('    diff = (d[f"p_{name}"] - y) ** 2 - (base - y) ** 2',
     '    diff = (base - y) ** 2 - (d[f"p_{name}"] - y) ** 2'))
mut("reference: the gap's error not clustered",
    ("    m, se, n, g = cluster_mean(diff, d.game_id)\n    return {\"projector\": name,",
     "    m, se, n, g = cluster_mean(diff, np.arange(len(d)))\n    return {\"projector\": name,"))
mut("score: log loss not clipped",
    ("        q = np.clip(p, 1e-6, 1 - 1e-6)", "        q = p"))
mut("avail: B share over all players",
    ("    br = b[b.role.astype(bool)].drop_duplicates(keys)",
     "    br = b.drop_duplicates(keys)"))
mut("avail: 'not on B' means 'no role on B'",
    ("    on_b = set(zip(b.game_id, b.team, b.player_id))",
     "    on_b = set(zip(br.game_id, br.team, br.player_id))"))
mut("pairs: the lift's error is the numerator's alone",
    ("            lift_se = cluster_mean(lin, g.game_id)[1]",
     "            lift_se = se / sp"))
mut("pairs: the lift's error not clustered",
    ("            lift_se = cluster_mean(lin, g.game_id)[1]",
     "            lift_se = cluster_mean(lin, np.arange(len(g)))[1]"))
mut("pairs: a moved engine weight is not named",
    ('            raise ImportError(\n                "ff_sim.corr_joint reads ff_boost._pair_weight, which this "',
     '            raise ImportError(\n                "ff_sim.corr_joint reads ff_boost.pair_weight, which this "'),
    ('                "moved; tell the engine thread rather than copying it."',
     '                "moved."'))

# ---- added after the third review
mut("slate A: a first-game player takes the weekly label",
    ("                 else snap if isinstance(snap, str) and snap else own)",
     "                 else own)"))
mut("slate A: an empty snap label is taken as a label",
    ("                 else snap if isinstance(snap, str) and snap else own)",
     "                 else snap if isinstance(snap, str) else own)"))
mut("slate A: 'HB' is not read as a running back",
    ('SNAP_ALIAS = {"HB": "RB"}', "SNAP_ALIAS = {}"))
mut("joint: asked of a projector that never said it states one",
    ("    return m is not None and getattr(m, \"__func__\", m) is not Projection.p_both",
     "    return m is not None"))
mut("joint: a method set on the object is not asked",
    ("    m = getattr(o, \"p_both\", None)\n    return",
     "    m = getattr(type(o), \"p_both\", None)\n    return"))
mut("range: clustering ignored",
    ("        n_eff = n / max((se / naive) ** 2, 1.0)", "        n_eff = float(n)"))
mut("range: effective sample may exceed n",
    ("        n_eff = n / max((se / naive) ** 2, 1.0)",
     "        n_eff = n / (se / naive) ** 2"))
mut("range: all-hit legs counted one by one",
    ("        n_eff = float(g)\n    z2", "        n_eff = float(n)\n    z2"))
mut("range: one miss is enough to measure clustering",
    ("RARE_FOR_CLUSTERING = 5", "RARE_FOR_CLUSTERING = 1"))
mut("range: five misses are not enough",
    ("RARE_FOR_CLUSTERING = 5", "RARE_FOR_CLUSTERING = 6"))

mut("History: rows are left in the order they came",
    ('        rows = rows.sort_values(["player_id", "t"], kind="stable")\n        t = rows',
     '        t = rows'))

# ---- S4: the opportunity model (ff_sim_opp.py)
# -- the parts
mut_opp("opp: a game's own number is in its own 'before'",
        ("    return incl.groupby(groups).shift(1), incl.groupby(groups).last()",
         "    return incl, incl.groupby(groups).last()"))
mut_opp("opp: 'now' is the group's FIRST average",
        ("    return incl.groupby(groups).shift(1), incl.groupby(groups).last()",
         "    return incl.groupby(groups).shift(1), incl.groupby(groups).first()"))
mut_opp("opp: a plain average, not a leaning one",
        ("    incl = (values.groupby(groups).ewm(halflife=half_life).mean()",
         "    incl = (values.groupby(groups).expanding().mean()"))
mut_opp("opp: team half-life changed", ("HALF_LIFE_TEAM = 4.0 ", "HALF_LIFE_TEAM = 5.0 "))
mut_opp("opp: short half-life changed", ("HALF_LIFE_SHORT = 3.0 ", "HALF_LIFE_SHORT = 4.0 "))
mut_opp("opp: long half-life changed", ("HALF_LIFE_LONG = 10.0 ", "HALF_LIFE_LONG = 12.0 "))
mut_opp("opp: spread formula drops the Poisson part",
        ("    excess = float(((x - m) ** 2 - m).sum())",
         "    excess = float(((x - m) ** 2).sum())"))
mut_opp("opp: spread not held to its range",
        ("    return float(np.clip(float((m ** 2).sum()) / excess, *SIZE_RANGE))",
         "    return float((m ** 2).sum()) / excess"))
mut_opp("opp: no spread measurable gives the wide end",
        ("    if len(x) == 0 or excess <= 0:\n        return SIZE_RANGE[1]",
         "    if len(x) == 0 or excess <= 0:\n        return SIZE_RANGE[0]"))
mut_opp("opp: predicting for nobody is an error",
        ("    return beta[0] + X.reshape(len(X), len(beta) - 1) @ beta[1:]",
         "    return beta[0] + X.reshape(len(X), -1) @ beta[1:]"))
mut_opp("opp: any word is taken for the single number",
        ("        if single not in SINGLE:", "        if False:"))
mut_opp("opp: does not say it reads the slate",
        ("    uses_actives = True", "    uses_actives = False"))
# -- learning from the history
mut_opp("opp: a stale fit is reused for another history",
        ("        if self._last[0] is hist:", "        if self._last[0] is not None:"))
mut_opp("opp: the fit is kept by week, not by history",
        ("        if self._last[0] is hist:",
         "        if self._last[0] is not None and self._last[0].before == hist.before:"))
mut_opp("opp: team-games left in the order of their names",
        ('              [list(OPP_STATS)].sum().sort_values("t", kind="stable")\n',
         '              [list(OPP_STATS)].sum()\n'))
mut_opp("opp: too few team-games fitted anyway",
        ("        if len(tg) < MIN_FIT_ROWS:", "        if False:"))
mut_opp("opp: too few player-games fitted anyway",
        ("            if int(seen.sum()) < MIN_FIT_ROWS:", "            if False:"))
mut_opp("opp: a fit may have as few as 5 rows", ("MIN_FIT_ROWS = 16", "MIN_FIT_ROWS = 5"))
mut_opp("opp: a fit needs 30 rows", ("MIN_FIT_ROWS = 16", "MIN_FIT_ROWS = 30"))
mut_opp("opp: a team's first game is filled with zero",
        ("            X = np.column_stack([off_before.fillna(league),\n                                 def_before.fillna(league), market])",
         "            X = np.column_stack([off_before.fillna(0.0),\n                                 def_before.fillna(0.0), market])"))
mut_opp("opp: 'allowed' is the team's own, not the opponent's",
        ("            def_before, def_now = leaning_average(tg[stat], tg.opponent,",
         "            def_before, def_now = leaning_average(tg[stat], tg.team,"))
mut_opp("opp: share of a zero-volume team is not zero",
        ("            share = (P[stat] / team_total.where(team_total > 0)).fillna(0.0)",
         "            share = (P[stat] / team_total.where(team_total > 0)).fillna(1.0)"))
mut_opp("opp: the long-run share is fitted with the short half-life",
        ("            long_before, long_now = leaning_average(share, P.player_id,\n                                                    HALF_LIFE_LONG)",
         "            long_before, long_now = leaning_average(share, P.player_id,\n                                                    HALF_LIFE_SHORT)"))
mut_opp("opp: the short share is kept where the long one belongs",
        ("            fit.share[stat] = (beta, short_now.to_dict(), long_now.to_dict(),",
         "            fit.share[stat] = (beta, short_now.to_dict(), short_now.to_dict(),"))
mut_opp("opp: the all-player share is the largest, not the average",
        ("            overall = float(share.mean())", "            overall = float(share.max())"))
mut_opp("opp: position norm is one number for everyone",
        ("            norm = P.position.map(by_pos).fillna(overall)",
         "            norm = P.position.map({}).fillna(overall)"))
mut_opp("opp: a player with no position breaks the share fit",
        ("            norm = P.position.map(by_pos).fillna(overall)",
         "            norm = P.position.map(by_pos)"))
mut_opp("opp: spread measured on the team's volume as it turned out",
        ('                 * P[f"pred_{stat}"].to_numpy()[seen])',
         '                 * P[f"team_{stat}"].to_numpy()[seen])'))
mut_opp("opp: spread measured on every tiny expected count",
        ("            use = m > SIZE_MIN_MEAN\n", "            use = m > -1.0\n"))
mut_opp("opp: spread measured only above 3", ("SIZE_MIN_MEAN = 1.0", "SIZE_MIN_MEAN = 3.0"))
mut_opp("opp: starter's share measured on every quarterback",
        ("        starts = P[P.qb_start]", '        starts = P[P.position == "QB"]'))
mut_opp("opp: no starter on record gives half",
        ("                             if len(starts) else 1.0)",
         "                             if len(starts) else 0.5)"))
mut_opp("opp: pass-attempt spread measured on team totals",
        ("            starts.attempts.to_numpy(dtype=float),\n            fit.starter_share * starts.pred_attempts.to_numpy(dtype=float))",
         '            tg["attempts"].to_numpy(dtype=float), team_pred["attempts"])'))
mut_opp("opp: pass-attempt spread measured round the targets prediction",
        ("            fit.starter_share * starts.pred_attempts.to_numpy(dtype=float))",
         "            fit.starter_share * starts.pred_targets.to_numpy(dtype=float))"))
mut_opp("opp: pass-attempt spread measured round the whole team's attempts",
        ("            fit.starter_share * starts.pred_attempts.to_numpy(dtype=float))",
         "            starts.pred_attempts.to_numpy(dtype=float))"))
# -- projecting a slate
mut_opp("opp: a slate missing a column is not refused",
        ('        if missing:\n            raise ValueError(f"the slate is missing',
         '        if False:\n            raise ValueError(f"the slate is missing'))
mut_opp("opp: a starter flag that is neither yes nor no is read anyway",
        ("        if not flag.isin([True, False]).all():", "        if False:"))
mut_opp("opp: two starters on a team are each given the starter's share",
        ("        if (named > 1).any():", "        if False:"))
mut_opp("opp: a thin history is projected from anyway",
        ("        if not fit.ok:\n            return blank", "        if False:\n            return blank"))
mut_opp("opp: a new team is given no volume of its own",
        ("                [off_now.get(t, league) for _, t in teams],",
         "                [off_now.get(t, 0.0) for _, t in teams],"))
mut_opp("opp: a new opponent is taken to allow nothing",
        ("                [def_now.get(opponent[k], league) for k in teams], market])",
         "                [def_now.get(opponent[k], 0.0) for k in teams], market])"))
mut_opp("opp: projection uses the team's own 'allowed'",
        ("                [def_now.get(opponent[k], league) for k in teams], market])",
         "                [def_now.get(k[1], league) for k in teams], market])"))
mut_opp("opp: the two team inputs go in the other way round when projecting",
        ("                [off_now.get(t, league) for _, t in teams],\n                [def_now.get(opponent[k], league) for k in teams], market])",
         "                [def_now.get(opponent[k], league) for k in teams],\n                [off_now.get(t, league) for _, t in teams], market])"))
mut_opp("opp: a team's volume may fall below one play",
        ("            volume[stat] = dict(zip(teams, np.clip(predict(beta, X),\n                                                   VOLUME_FLOOR, None)))",
         "            volume[stat] = dict(zip(teams, predict(beta, X)))"))
mut_opp("opp: the floor under a team's volume is 5", ("VOLUME_FLOOR = 1.0", "VOLUME_FLOOR = 5.0"))
mut_opp("opp: a position never seen gets nothing",
        ("            norm = np.array([by_pos.get(p, overall) for p in pos], dtype=float)",
         "            norm = np.array([by_pos.get(p, 0.0) for p in pos], dtype=float)"))
mut_opp("opp: a player with no earlier game gets nothing",
        ("            raw = norm.copy()               # no earlier game: his position's",
         "            raw = np.zeros(n)"))
mut_opp("opp: the short share stands in for the long one when projecting",
        ("                [short[known], long_[known], norm[known]]))",
         "                [short[known], short[known], norm[known]]))"))
mut_opp("opp: a negative share is kept",
        ("            raw = np.clip(raw, 0.0, None)\n            total",
         "            total"))
mut_opp("opp: shares not scaled to one",
        ("            share = np.divide(raw, total, out=np.full(n, np.nan), where=total > 0)",
         "            share = raw"))
mut_opp("opp: a team given no share at all is priced at zero",
        ("out=np.full(n, np.nan), where=total > 0)", "out=np.zeros(n), where=total > 0)"))
mut_opp("opp: carries are shared out with the targets fit",
        ("            beta, short_now, long_now, by_pos, overall = fit.share[stat]",
         '            beta, short_now, long_now, by_pos, overall = fit.share["targets"]'))
mut_opp("opp: carries are scaled to the team's targets",
        ("            out[stat] = share * np.array([volume[stat][k] for k in key])",
         '            out[stat] = share * np.array([volume["targets"][k] for k in key])'))
mut_opp("opp: who starts is ignored",
        ("        starts = flag.to_numpy(dtype=bool)", "        starts = np.zeros(n, dtype=bool)"))
mut_opp("opp: the starter gets every pass attempt",
        ('        out["attempts"] = np.where(starts, fit.starter_share * team_att, np.nan)',
         '        out["attempts"] = np.where(starts, team_att, np.nan)'))
mut_opp("opp: everyone on the slate is given the starter's attempts",
        ('        out["attempts"] = np.where(starts, fit.starter_share * team_att, np.nan)',
         '        out["attempts"] = fit.starter_share * team_att'))
mut_opp("opp: a named starter not listed at quarterback gets none",
        ('        out["attempts"] = np.where(starts, fit.starter_share * team_att, np.nan)',
         '        out["attempts"] = np.where(starts & (pos == "QB"), fit.starter_share * team_att, np.nan)'))
mut_opp("opp: a player on the slate twice is given two shares",
        ('        if slate.duplicated(["game_id", "team", "player_id"]).any():',
         '        if False:'))
mut_opp("opp: a team-game with one carry is treated as having none",
        ("            share = (P[stat] / team_total.where(team_total > 0)).fillna(0.0)",
         "            share = (P[stat] / team_total.where(team_total > 1)).fillna(0.0)"))
# -- the count round the mean
mut_opp("opp: the single number is always the median",
        ('        if self.single == "mean":', "        if False:"))
mut_opp("opp: the single number is always the mean",
        ('        if self.single == "mean":', "        if True:"))
mut_opp("opp: the median is some other point",
        ("        return float(nbinom.ppf(0.5, *d))", "        return float(nbinom.ppf(0.6, *d))"))
mut_opp("opp: 'over' needs one more than the line",
        ("            nbinom.sf(math.floor(line), *d))",
         "            nbinom.sf(math.floor(line) + 1, *d))"))
mut_opp("opp: landing on a whole-number line counts as over",
        ("            nbinom.sf(math.floor(line), *d))",
         "            nbinom.sf(math.ceil(line) - 1, *d))"))
mut_opp("opp: a stat it does not project gets a number",
        ("        if stat not in self.mean:\n            return None",
         '        if stat not in self.mean:\n            stat = "targets"'))
mut_opp("opp: every stat is priced with the targets spread",
        ("        r = self.size[stat]", '        r = self.size["targets"]'))
# -- the closing spread and total
mut_opp("opp market: a game outside the history and slate is looked up",
        ("            if g not in allowed:", "            if False:"))
mut_opp("opp market: fitting is allowed every game there is",
        ("        market = self._market(tg.game_id, tg.team, fit.games)",
         "        market = self._market(tg.game_id, tg.team, set(self.lines or ()) | fit.games)"))
mut_opp("opp market: projecting is allowed every game there is",
        ("                              fit.games | {g for g, _ in teams})",
         "                              set(self.lines or ()) | fit.games)"))
mut_opp("opp market: the visitor gets the home team's spread",
        ("            out.append((spread if tm == home else -spread, total))",
         "            out.append((spread, total))"))
mut_opp("opp market: the spread is turned round when fitting only",
        ("        market = self._market(tg.game_id, tg.team, fit.games)",
         "        market = self._market(tg.game_id, tg.team, fit.games) * np.array([-1.0, 1.0])[:(2 if self.lines else 0)]"))
mut_opp("opp market: the spread is turned round when projecting only",
        ("                              fit.games | {g for g, _ in teams})",
         "                              fit.games | {g for g, _ in teams}) * np.array([-1.0, 1.0])[:(2 if self.lines else 0)]"))
mut_opp("opp market: a team that was not in the game is signed as the visitor",
        ("            if tm not in (home, away):", "            if False:"))
mut_opp("opp market: a game with no line is a zero",
        ("            if g not in self.lines:\n                raise KeyError(f\"no closing line on file for {g}\")\n            home, away, spread, total = self.lines[g]",
         "            home, away, spread, total = self.lines.get(g, (tm, tm, 0.0, 0.0))"))
mut_opp("opp market: an empty table of lines is read as no lines",
        ("        if self.lines is None:", "        if not self.lines:"))
mut_opp("opp market: a line that is not a number is used",
        ("            if not (math.isfinite(spread) and math.isfinite(total)):",
         "            if False:"))
mut_opp("opp market: only the spread is checked for being a number",
        ("            if not (math.isfinite(spread) and math.isfinite(total)):",
         "            if not math.isfinite(spread):"))
mut_opp("opp market: a missing total is accepted by the loader",
        ('    if g[["spread_line", "total_line"]].isna().any().any():',
         '    if g[["spread_line"]].isna().any().any():'))
mut_opp("opp market: postseason lines included",
        ('    g = p[p.season_type == "REG"].drop_duplicates("game_id")',
         '    g = p.drop_duplicates("game_id")'))
mut_opp("opp market: a missing line is accepted",
        ('    if g[["spread_line", "total_line"]].isna().any().any():', "    if False:"))
mut_opp("opp market: home and visitor the wrong way round",
        ("            zip(g.game_id, g.home_team, g.away_team, g.spread_line,",
         "            zip(g.game_id, g.away_team, g.home_team, g.spread_line,"))
# -- the expected counts beside what happened
mut_opp("opp sizes: the expected count sees the week it is checked on",
        ("        hist = History(frame[frame.t < t], t)\n        slate = slate_active(frame, hist)\n        mean = model.means(hist, slate)",
         "        hist = History(frame[frame.t < t], t)\n        slate = slate_active(frame, hist)\n        mean = model.means(History(frame[frame.t <= t], t + 1), slate)"))
mut_opp("opp sizes: graded on everyone who had been playing, not who was active",
        ("        slate = slate_active(frame, hist)\n        mean = model.means(hist, slate)\n        size",
         "        slate = __import__('ff_sim').slate_candidates(frame, hist)\n        mean = model.means(hist, slate)\n        size"))
mut_opp("opp sizes: the actual is taken from the first week asked for",
        ('        played = frame[frame.t == t].set_index(["game_id", "player_id"])',
         '        played = frame[frame.t == weeks[0]].set_index(["game_id", "player_id"])'))
mut_opp("opp sizes: rows it says nothing about are kept",
        ("    return rows[rows.expected.notna()].reset_index(drop=True)",
         "    return rows"))
mut_opp("opp sizes: one stat's actual under another's name",
        ('                "actual": played[stat].reindex(at).to_numpy(dtype=float)}))',
         '                "actual": played["targets"].reindex(at).to_numpy(dtype=float)}))'))
mut_opp("opp sizes: the game beside a player is another player's",
        ('                "game_id": slate["game_id"].to_numpy(),',
         '                "game_id": slate["game_id"].to_numpy()[::-1],'))
mut_opp("opp sizes: the variance is a Poisson's",
        ('                "variance": m + m ** 2 / size.get(stat, np.nan),',
         '                "variance": m,'))
mut_opp("opp sizes: every stat's variance uses the targets spread",
        ('                "variance": m + m ** 2 / size.get(stat, np.nan),',
         '                "variance": m + m ** 2 / size.get("targets", np.nan),'))
mut_opp("opp sizes: a week too thin to fit is an error",
        ('                "variance": m + m ** 2 / size.get(stat, np.nan),',
         '                "variance": m + m ** 2 / size[stat],'))
mut_opp("opp lined: every rung, not the main line",
        ("    L = L[(L.version == \"A\") & (L.rung == MAIN) & L.stat.isin(OPP_STATS)",
         "    L = L[(L.version == \"A\") & L.stat.isin(OPP_STATS)"))
mut_opp("opp lined: both versions",
        ("    L = L[(L.version == \"A\") & (L.rung == MAIN) & L.stat.isin(OPP_STATS)",
         "    L = L[(L.rung == MAIN) & L.stat.isin(OPP_STATS)"))
mut_opp("opp lined: every stat the projector priced",
        ("    L = L[(L.version == \"A\") & (L.rung == MAIN) & L.stat.isin(OPP_STATS)",
         "    L = L[(L.version == \"A\") & (L.rung == MAIN)"))
mut_opp("opp lined: the same player twice is counted twice",
        ('                validate="one_to_one")', "                )"))
mut_opp("opp lined: legs the projector did not price are kept",
        ('          & L[f"p_{name}"].notna()]', "          ]"))
mut_opp("opp lined: a result that disagrees, or is missing, is let through",
        ("    if not (j.actual == j.actual_again).all():", "    if False:"))
mut_opp("opp lined: 'said' is the chance of the under",
        ('        "said": j[f"p_{name}"].to_numpy(dtype=float),',
         '        "said": 1.0 - j[f"p_{name}"].to_numpy(dtype=float),'))

# ---- S17: efficiency (ff_sim_eff.py)
# -- the parts
mut_eff("eff: a game's own number is in its own 'before'",
        ("    return incl.groupby(groups).shift(1).fillna(0.0), incl.groupby(groups).last()",
         "    return incl, incl.groupby(groups).last()"))
mut_eff("eff: 'now' is the group's FIRST total",
        ("    return incl.groupby(groups).shift(1).fillna(0.0), incl.groupby(groups).last()",
         "    return incl.groupby(groups).shift(1).fillna(0.0), incl.groupby(groups).first()"))
mut_eff("eff: a plain total, not a leaning one",
        ("    incl = (values.groupby(groups).ewm(halflife=half_life).sum()",
         "    incl = (values.groupby(groups).expanding().sum()"))
mut_eff("eff: a leaning average where a total belongs",
        ("    incl = (values.groupby(groups).ewm(halflife=half_life).sum()",
         "    incl = (values.groupby(groups).ewm(halflife=half_life).mean()"))
mut_eff("eff: a first game has no 'before' at all",
        ("    return incl.groupby(groups).shift(1).fillna(0.0), incl.groupby(groups).last()",
         "    return incl.groupby(groups).shift(1), incl.groupby(groups).last()"))
mut_eff("eff: the pull adds the position's rate once, however hard it pulls",
        ("    return (own_num + k * norm) / (own_den + k)",
         "    return (own_num + norm) / (own_den + k)"))
mut_eff("eff: the pull counts double below the line",
        ("    return (own_num + k * norm) / (own_den + k)",
         "    return (own_num + k * norm) / (own_den + 2 * k)"))
mut_eff("eff: half-life changed", ("HALF_LIFE_RATE = 16.0 ", "HALF_LIFE_RATE = 8.0 "))
mut_eff("eff: the list of pulls loses its top",
        ("160.0, 320.0, 640.0, 1280.0)", "160.0, 320.0, 640.0)"))
mut_eff("eff: the list of pulls loses a middle value",
        ("SHRINK_GRID = (2.0, 5.0, 10.0, 20.0, 40.0, 80.0, 160.0,",
         "SHRINK_GRID = (2.0, 5.0, 10.0, 20.0, 40.0, 160.0,"))
mut_eff("eff: a rate may be learned from 5 games", ("MIN_RATE_ROWS = 16", "MIN_RATE_ROWS = 5"))
mut_eff("eff: a rate needs 30 games", ("MIN_RATE_ROWS = 16", "MIN_RATE_ROWS = 30"))
mut_eff("eff: a position gets its own spread from 20 catches",
        ("MIN_SPREAD_UNITS = 200.0", "MIN_SPREAD_UNITS = 20.0"))
mut_eff("eff: a position needs 2000 catches for its own spread",
        ("MIN_SPREAD_UNITS = 200.0", "MIN_SPREAD_UNITS = 2000.0"))
mut_eff("eff: the floor under yards each is a whole yard",
        ("RATE_FLOOR = 0.1", "RATE_FLOOR = 1.0"))
mut_eff("eff: a hundredth of the count's tail is dropped",
        ("TAIL = 1e-10", "TAIL = 1e-2"))
mut_eff("eff: does not say it reads the slate",
        ("    uses_actives = True", "    uses_actives = False"))
mut_eff("eff: an opportunity model reporting its median is accepted",
        ('        if self.opp.single != "mean":', "        if False:"))
mut_eff("eff: the opportunity model it is given is ignored",
        ("        self.opp = opportunity if opportunity is not None else OpportunityModel(",
         "        self.opp = OpportunityModel("))
mut_eff("eff: its own opportunity model takes the plain name",
        ('            f"{name}_opportunity")', '            "opportunity")'))
# -- learning from the history
mut_eff("eff: a stale fit is reused for another history",
        ("        if self._last[0] is hist:", "        if self._last[0] is not None:"))
mut_eff("eff: the fit is kept by week, not by history",
        ("        if self._last[0] is hist:",
         "        if self._last[0] is not None and self._last[0].before == hist.before:"))
mut_eff("eff: too few games fitted anyway",
        ("            if int(had.sum()) < MIN_RATE_ROWS:", "            if False:"))
mut_eff("eff: games with no opportunity are counted as games",
        ("            had = (den > 0).to_numpy()", "            had = (den >= 0).to_numpy()"))
mut_eff("eff: the all-player rate is the average of game rates",
        ("            overall = float(num.sum() / den.sum())",
         "            overall = float((num[den > 0] / den[den > 0]).mean())"))
mut_eff("eff: a position with no opportunities is given a rate",
        ("            by_pos = (pos_num[pos_den > 0] / pos_den[pos_den > 0]).to_dict()",
         "            by_pos = (pos_num / pos_den).to_dict()"))
mut_eff("eff: position rate is one number for everyone",
        ("            norm = F.position.map(by_pos).fillna(overall).to_numpy(dtype=float)",
         "            norm = F.position.map({}).fillna(overall).to_numpy(dtype=float)"))
mut_eff("eff: a player with no position breaks the fit",
        ("            norm = F.position.map(by_pos).fillna(overall).to_numpy(dtype=float)",
         "            norm = F.position.map(by_pos).to_numpy(dtype=float)"))
mut_eff("eff: what he has caught is leaned, what he was thrown is not",
        ("            den_before, den_now = leaning_sum(den, F.player_id, HALF_LIFE_RATE)",
         "            den_before, den_now = leaning_sum(den, F.player_id, 1e9)"))
mut_eff("eff: the pull is scored by the size of the miss, not its square",
        ("            miss = {k: float(((x - d * pulled(nb, db, norm[had], k)) ** 2).sum())",
         "            miss = {k: float(np.abs(x - d * pulled(nb, db, norm[had], k)).sum())"))
mut_eff("eff: the WORST pull is picked",
        ("            k = min(SHRINK_GRID, key=lambda v: (miss[v], v))",
         "            k = max(SHRINK_GRID, key=lambda v: (miss[v], v))"))
mut_eff("eff: the lightest pull is always picked",
        ("            k = min(SHRINK_GRID, key=lambda v: (miss[v], v))",
         "            k = SHRINK_GRID[0]"))
mut_eff("eff: the spread is measured with the lightest pull",
        ("                sq = (x - d * pulled(nb, db, norm[had], k)) ** 2",
         "                sq = (x - d * pulled(nb, db, norm[had], SHRINK_GRID[0])) ** 2"))
mut_eff("eff: a position's spread is per game, not per catch",
        ("                per = pd.Series(sq).groupby(pos).sum() / units",
         "                per = pd.Series(sq).groupby(pos).mean()"))
mut_eff("eff: the all-position spread is per game, not per catch",
        ('                out["spread_all"] = float(sq.sum() / d.sum())',
         '                out["spread_all"] = float(sq.mean())'))
mut_eff("eff: a thin position keeps its own spread",
        ('                out["spread"] = per[units >= MIN_SPREAD_UNITS].to_dict()',
         '                out["spread"] = per.to_dict()'))
mut_eff("eff: a rate that is not yards is given a spread",
        ("            if rate in {r for _, r in YARDS.values()}:\n                # How much",
         "            if True:\n                # How much"))
# -- projecting a slate
mut_eff("eff: a position never seen gets a rate of zero",
        ('            norm = np.array([r["by_pos"].get(p, r["overall"]) for p in pos],',
         '            norm = np.array([r["by_pos"].get(p, 0.0) for p in pos],'))
mut_eff("eff: a player's own games are ignored",
        ('            out[rate] = pulled(own_num, own_den, norm, r["k"])',
         '            out[rate] = norm'))
mut_eff("eff: the pull picked on the history is not the one used",
        ('            out[rate] = pulled(own_num, own_den, norm, r["k"])',
         '            out[rate] = pulled(own_num, own_den, norm, SHRINK_GRID[0])'))
mut_eff("eff: every rate is floored, not only yards",
        ('            out[rate] = pulled(own_num, own_den, norm, r["k"])',
         '            out[rate] = np.clip(pulled(own_num, own_den, norm, r["k"]), RATE_FLOOR, None)'))
mut_eff("eff: yards each may go below the floor",
        ("                out[rate] = np.clip(out[rate], RATE_FLOOR, None)\n", ""))
mut_eff("eff: a position never seen gets no spread",
        ('                    [r["spread"].get(p, r["spread_all"]) for p in pos], dtype=float)',
         '                    [r["spread"].get(p, 0.0) for p in pos], dtype=float)'))
mut_eff("eff: every position takes the all-position spread",
        ('                    [r["spread"].get(p, r["spread_all"]) for p in pos], dtype=float)',
         '                    [r["spread_all"] for p in pos], dtype=float)'))
mut_eff("eff: catches come from carries",
        ('COUNTS = {"receptions": ("targets", "catch"),',
         'COUNTS = {"receptions": ("carries", "catch"),'))
mut_eff("eff: completions use the catch rate",
        ('          "completions": ("attempts", "completion")}',
         '          "completions": ("attempts", "catch")}'))
mut_eff("eff: receiving yards are summed over targets, not catches",
        ('YARDS = {"receiving_yards": ("receptions", "yards_per_catch"),',
         'YARDS = {"receiving_yards": ("targets", "yards_per_catch"),'))
mut_eff("eff: rushing yards use yards per catch",
        ('         "rushing_yards": ("carries", "yards_per_carry"),',
         '         "rushing_yards": ("carries", "yards_per_catch"),'))
mut_eff("eff: passing yards use the completion rate as yards each",
        ('         "passing_yards": ("attempts", "yards_per_attempt")}',
         '         "passing_yards": ("attempts", "completion")}'))
mut_eff("eff: catches are not thinned by the catch rate",
        ("            mean[stat] = mean[frm] * rt[rate]", "            mean[stat] = mean[frm] * 1.0"))
mut_eff("eff: every count is spread as targets are",
        ("            size[stat] = size[frm]", '            size[stat] = size["targets"]'))
mut_eff("eff: yards are a count, not a count times yards each",
        ("            mean[stat] = mean[count] * rt[rate]", "            mean[stat] = mean[count] * 1.0"))
mut_eff("eff: every yardage is spread as carries are",
        ("            size[stat] = size[count]", '            size[stat] = size["carries"]'))
mut_eff("eff: a thin history still passes the opportunities through",
        ("        if not self.fit(hist).ok:\n            mean = {s: nan for s in EFF_STATS}",
         "        if False:\n            mean = {s: nan for s in EFF_STATS}"))
mut_eff("eff: yardage variance leaves out how the count varies",
        ('                             + each ** 2 * (c + c ** 2 / p["size"][stat]))',
         '                             + each ** 2 * c)'))
mut_eff("eff: yardage variance leaves out how one catch varies",
        ("                out[stat] = (c * var_each\n", "                out[stat] = (0.0 * var_each\n"))
mut_eff("eff: a count's variance is a Poisson's",
        ('                out[stat] = m + m ** 2 / p["size"][stat]', '                out[stat] = m'))
# -- the chance of a line
mut_eff("eff: a stat it does not project gets a number",
        ('        if stat not in self.p["mean"]:\n            return float("nan")',
         '        if stat not in self.p["mean"]:\n            stat = "targets"'))
mut_eff("eff: 'over' a count needs one more than the line",
        ("            return float(nbinom.sf(math.floor(line), r, r / (r + m)))",
         "            return float(nbinom.sf(math.floor(line) + 1, r, r / (r + m)))"))
mut_eff("eff: landing on a whole-number count line is over",
        ("            return float(nbinom.sf(math.floor(line), r, r / (r + m)))",
         "            return float(nbinom.sf(math.ceil(line) - 1, r, r / (r + m)))"))
mut_eff("eff: yards are priced as if they were a count",
        ("        if stat not in YARDS:\n            return float(nbinom.sf(",
         "        if True:\n            return float(nbinom.sf("))
mut_eff("eff: a line below zero is not certain",
        ("        if line < 0:\n            return 1.0\n", ""))
mut_eff("eff: the count under the yards has the yards' mean",
        ('        c = float(self.p["mean"][self.p["count"][stat]][i])', "        c = m"))
mut_eff("eff: a game with no catch is given yards",
        ("        k = np.arange(1, int(nbinom.ppf(1.0 - TAIL, r, p)) + 2)",
         "        k = np.arange(0, int(nbinom.ppf(1.0 - TAIL, r, p)) + 2)"))
mut_eff("eff: the yards do not grow with the catches",
        ("                      * gamma.sf(line, a=k * each ** 2 / var_each,",
         "                      * gamma.sf(line, a=each ** 2 / var_each,"))
mut_eff("eff: shape and scale the wrong way round",
        ("                      * gamma.sf(line, a=k * each ** 2 / var_each,\n                                 scale=var_each / each)).sum())",
         "                      * gamma.sf(line, a=k * var_each / each,\n                                 scale=each ** 2 / var_each)).sum())"))
mut_eff("eff: the yards of one catch are scaled to a quarter",
        ("                                 scale=var_each / each)).sum())",
         "                                 scale=var_each / each / 4)).sum())"))
# -- the expected numbers beside what happened
mut_eff("eff sizes: the expected number sees the week it is checked on",
        ("        hist = History(frame[frame.t < t], t)\n        slate = slate_active(frame, hist)\n        mean = model.parts(hist, slate)",
         "        hist = History(frame[frame.t < t], t)\n        slate = slate_active(frame, hist)\n        hist = History(frame[frame.t <= t], t + 1)\n        mean = model.parts(hist, slate)"))
mut_eff("eff sizes: graded on everyone who had been playing, not who was active",
        ("        slate = slate_active(frame, hist)\n        mean = model.parts(hist, slate)",
         "        slate = __import__('ff_sim').slate_candidates(frame, hist)\n        mean = model.parts(hist, slate)"))
mut_eff("eff sizes: the actual is taken from the first week asked for",
        ('        played = frame[frame.t == t].set_index(["game_id", "player_id"])',
         '        played = frame[frame.t == weeks[0]].set_index(["game_id", "player_id"])'))
mut_eff("eff sizes: rows it says nothing about are kept",
        ("    return rows[rows.expected.notna()].reset_index(drop=True)", "    return rows"))
mut_eff("eff sizes: one stat's actual under another's name",
        ('                "actual": played[stat].reindex(at).to_numpy(dtype=float)}))',
         '                "actual": played["targets"].reindex(at).to_numpy(dtype=float)}))'))
mut_eff("eff sizes: the game beside a player is another player's",
        ('                "game_id": slate["game_id"].to_numpy(),',
         '                "game_id": slate["game_id"].to_numpy()[::-1],'))
mut_eff("eff sizes: the chance of beating the expected number is the chance of beating zero",
        ('                "said_above": [P.p_over(i, stat, m) if m == m else np.nan',
         '                "said_above": [P.p_over(i, stat, 0.0) if m == m else np.nan'))
mut_eff("eff sizes: every stat's chance of beating its number is the targets one",
        ('                "said_above": [P.p_over(i, stat, m) if m == m else np.nan',
         '                "said_above": [P.p_over(i, "targets", m) if m == m else np.nan'))
mut_eff("eff lined: the chance of beating the expected number is the stated over",
        ('        "said_above": j.said_above.to_numpy(dtype=float),',
         '        "said_above": j[f"p_{name}"].to_numpy(dtype=float),'))
mut_eff("eff: a thin history gives rates of zero, not blanks",
        ("                out[rate] = np.full(n, np.nan)\n                continue",
         "                out[rate] = np.zeros(n)\n                continue"))
mut_eff("eff: a position needs MORE than the least for its own spread",
        ('                out["spread"] = per[units >= MIN_SPREAD_UNITS].to_dict()',
         '                out["spread"] = per[units > MIN_SPREAD_UNITS].to_dict()'))
mut_eff("eff: the all-player rate leaves out yards with no catch behind them",
        ("            overall = float(num.sum() / den.sum())",
         "            overall = float(num[den > 0].sum() / den.sum())"))
mut_eff("eff: every thin history is blamed on pass attempts",
        ('                           f"{ONE[den_col]} in the history; needs {MIN_RATE_ROWS}")',
         '                           f"pass attempt in the history; needs {MIN_RATE_ROWS}")'))
mut_eff("eff sizes: the variance column is the expected number",
        ('                "expected": mean[stat], "variance": var[stat],',
         '                "expected": mean[stat], "variance": mean[stat],'))
mut_eff("eff sizes: asked for some stats, it gives them all",
        ("        for stat in stats:\n            out.append(pd.DataFrame({",
         "        for stat in EFF_STATS:\n            out.append(pd.DataFrame({"))
mut_eff("eff lined: every rung, not the main line",
        ('    L = L[(L.version == "A") & (L.rung == MAIN) & L.stat.isin(list(stats))',
         '    L = L[(L.version == "A") & L.stat.isin(list(stats))'))
mut_eff("eff lined: both versions",
        ('    L = L[(L.version == "A") & (L.rung == MAIN) & L.stat.isin(list(stats))',
         '    L = L[(L.rung == MAIN) & L.stat.isin(list(stats))'))
mut_eff("eff lined: asked for some stats, it gives them all",
        ('    L = L[(L.version == "A") & (L.rung == MAIN) & L.stat.isin(list(stats))',
         '    L = L[(L.version == "A") & (L.rung == MAIN) & L.stat.isin(list(EFF_STATS))'))
mut_eff("eff lined: the same player twice is counted twice",
        ('                validate="one_to_one")', "                )"))
mut_eff("eff lined: legs the projector did not price are kept",
        ('          & L[f"p_{name}"].notna()]', "          ]"))
mut_eff("eff lined: a result that disagrees, or is missing, is let through",
        ("    if not (j.actual == j.actual_again).all():", "    if False:"))
mut_eff("eff lined: 'said' is the chance of the under",
        ('        "said": j[f"p_{name}"].to_numpy(dtype=float),',
         '        "said": 1.0 - j[f"p_{name}"].to_numpy(dtype=float),'))

# ---- S13: each player's chance of playing (ff_sim_play.py)
# -- the reports
mut_play("play: anything on the report with no game status is 'none'",
         ('        "status": kept.report_status.map(REPORT_WORD).fillna("listed")',
          '        "status": kept.report_status.map(REPORT_WORD).fillna("none")'))
mut_play("play: 'Doubtful' is read as out",
         ('REPORT_WORD = {"Questionable": "questionable", "Doubtful": "doubtful",',
          'REPORT_WORD = {"Questionable": "questionable", "Doubtful": "out",'))
mut_play("play: postseason reports are kept",
         ('    reg = raw[(raw.game_type == "REG") & raw.gsis_id.notna()]',
          '    reg = raw[raw.gsis_id.notna()]'))
mut_play("play: a report with no player id is kept",
         ('    reg = raw[(raw.game_type == "REG") & raw.gsis_id.notna()]',
          '    reg = raw[(raw.game_type == "REG")]'))
mut_play("play: a report for a game not on file yet is dropped",
         ("    kept = m[~late]\n", "    kept = m[~late & m.game_date.notna().to_numpy()]\n"))
mut_play("play: two reports in a week are taken in the order they came",
         ('            .sort_values("_stamp", kind="stable", na_position="first")\n', ""))
mut_play("play: a report changed on game day is used",
         ("    late = (stamp.dt.normalize() >= day).to_numpy()",
          "    late = (stamp.dt.normalize() > day).to_numpy()"))
mut_play("play: a report changed after the game is used",
         ("    late = (stamp.dt.normalize() >= day).to_numpy()",
          "    late = np.zeros(len(m), dtype=bool)"))
mut_play("play: a report with no time stamp is dropped",
         ("    late = (stamp.dt.normalize() >= day).to_numpy()",
          "    late = ((stamp.dt.normalize() >= day) | stamp.isna()).to_numpy()"))
mut_play("play: of two reports in a week the EARLIER stands",
         ('            .drop_duplicates(["season", "week", "gsis_id"], keep="last"))',
          '            .drop_duplicates(["season", "week", "gsis_id"], keep="first"))'))
mut_play("play: a reports table missing a column is not refused",
         ("    if need - set(raw.columns):", "    if False:"))
mut_play("play: the week is one out",
         ('        "t": (kept.season * 100 + kept.week).astype(int).to_numpy(),',
          '        "t": (kept.season * 100 + kept.week + 1).astype(int).to_numpy(),'))
mut_play("play: the count of rows kept is the count of rows read",
         ('        "kept": int(len(out))}', '        "kept": int(len(raw))}'))
mut_play("play: the count of rows with no time stamp is always zero",
         ('        "no_time_stamp": int(stamp.isna().sum()),', '        "no_time_stamp": 0,'))
mut_play("play: only the home teams' games are known",
         ('        for side in ("home_team", "away_team")], ignore_index=True)',
          '        for side in ("home_team",)], ignore_index=True)'))
mut_play("play: a fresh copy is fetched again",
         ("    if not force and not ff_data._is_stale(dest):", "    if False:"))
mut_play("play: a failed refresh stops even with a copy on hand",
         ("        if dest.exists():\n            print(f\"  ! injuries",
          "        if False:\n            print(f\"  ! injuries"))
mut_play("play: a half-finished download is left behind",
         ("        tmp.unlink(missing_ok=True)\n", ""))
mut_play("play: the cached file has another name",
         ('    dest = ff_data.CACHE / f"injuries_{year}.parquet"',
          '    dest = ff_data.CACHE / f"injury_{year}.parquet"'))
mut_play("play: fetched from another release",
         ('REPORT_URL = "{B}/injuries/injuries_{yr}.parquet"',
          'REPORT_URL = "{B}/injury/injuries_{yr}.parquet"'))
# -- who was listed, and whether he played
mut_play("play: listed from the last three games, not four",
         ("for d in range(1, lookback + 1)],", "for d in range(1, lookback)],"))
mut_play("play: games missed is one too many",
         ('        "missed": (C.back - 1).to_numpy(),', '        "missed": C.back.to_numpy(),'))
mut_play("play: games missed counts from his OLDEST of the four",
         ('         .groupby(["team", "seq", "player_id"], as_index=False).back.min())',
          '         .groupby(["team", "seq", "player_id"], as_index=False).back.max())'))
mut_play("play: listed for a game the team has not played",
         ('    C = C.merge(tw, on=["team", "seq"])      # a game the team has not played drops out',
          '    C = C.merge(tw, on=["team", "seq"], how="left")'))
mut_play("play: everyone listed is marked as having sat",
         ('        "played": C.played.notna().to_numpy()})',
          '        "played": C.played.isna().to_numpy()})'))
# -- counting
mut_play("play: an unknown status is accepted",
         ("            if bad:\n                raise ValueError(f\"unknown injury status",
          "            if False:\n                raise ValueError(f\"unknown injury status"))
mut_play("play: two reports for one player-week are accepted",
         ('            if reports.duplicated(["t", "player_id"]).any():', "            if False:"))
mut_play("play: a chance outside 0 to 1 may be handed in",
         ("            if not 0.0 <= float(p) <= 1.0:", "            if False:"))
mut_play("play: a game in the history is given the NEXT week's report",
         ('                           for k in zip(L.t, L.player_id)], dtype=object)',
          '                           for k in zip(L.t + 1, L.player_id)], dtype=object)'))
mut_play("play: a stale count is reused for another history",
         ("        if self._last[0] is hist:", "        if self._last[0] is not None:"))
mut_play("play: the count is kept by week, not by history",
         ("        if self._last[0] is hist:",
          "        if self._last[0] is not None and self._last[0].before == hist.before:"))
mut_play("play: too little history is counted on anyway",
         ("        if len(L) < MIN_CHANCE_ROWS:", "        if False:"))
mut_play("play: 50 listed player-games is enough", ("MIN_CHANCE_ROWS = 100", "MIN_CHANCE_ROWS = 50"))
mut_play("play: it takes 500 listed player-games", ("MIN_CHANCE_ROWS = 100", "MIN_CHANCE_ROWS = 500"))
mut_play("play: a player not on the report is counted as listed",
         ('        status = np.array([self._status.get(k, "none")',
          '        status = np.array([self._status.get(k, "listed")'))
mut_play("play: a status never seen is given no chance",
         ("            rate = float(played[is_s].mean()) if is_s.any() else everyone",
          "            rate = float(played[is_s].mean()) if is_s.any() else 0.0"))
mut_play("play: the pull is 5 rows, not 20", ("PRIOR_ROWS = 20.0", "PRIOR_ROWS = 5.0"))
mut_play("play: a cell is pulled toward everyone's rate, not its status's",
         ("                    (played[in_cell].sum() + PRIOR_ROWS * rate) / (n + PRIOR_ROWS))",
          "                    (played[in_cell].sum() + PRIOR_ROWS * everyone) / (n + PRIOR_ROWS))"))
mut_play("play: a cell is its own count with no pull",
         ("                    (played[in_cell].sum() + PRIOR_ROWS * rate) / (n + PRIOR_ROWS))",
          "                    played[in_cell].sum() / max(n, 1))"))
mut_play("play: a cell takes in every longer absence too",
         ("                in_cell = is_s & (L.missed.to_numpy() == miss)",
          "                in_cell = is_s & (L.missed.to_numpy() >= miss)"))
mut_play("play: the rows behind a cell are miscounted",
         ("                fit.count[(s, miss)] = n", "                fit.count[(s, miss)] = len(L)"))
# -- on a slate
mut_play("play: a slate player's status is last week's",
         ('            status = self._status.get((hist.before, pid), "none")',
          '            status = self._status.get((hist.before - 1, pid), "none")'))
mut_play("play: a slate player not on the report is 'listed'",
         ('            status = self._status.get((hist.before, pid), "none")',
          '            status = self._status.get((hist.before, pid), "listed")'))
mut_play("play: games missed looks back over every game the team has played",
         ("        weeks = {tm: np.sort(g.unique())[-CANDIDATE_LOOKBACK:]",
          "        weeks = {tm: np.sort(g.unique())"))
mut_play("play: a traded player's last game is his last for ANY team",
         ('            seen = last.get((tm, pid))',
          '            seen = max((v for (_, q), v in last.items() if q == pid), default=None)'))
mut_play("play: a chance handed in is ignored",
         ("            if handed is not None:", "            if False:"))
mut_play("play: a chance handed in for one team's listing is ignored",
         ("            handed = self.given.get((tm, pid), self.given.get(pid))",
          "            handed = self.given.get(pid)"))
mut_play("play: a slate for the wrong week is counted for anyway",
         ("        if week - {hist.before}:", "        if False:"))
mut_play("play: with too little history everyone is a coin flip",
         ('                rec.append((status, missed, 1.0, "taken to play"))',
          '                rec.append((status, missed, 0.5, "taken to play"))'))
mut_play("play: a player not seen lately takes the 'none' rate whatever his status",
         ('                rec.append((status, missed, fit.by_status[status], "counted"))',
          '                rec.append((status, missed, fit.by_status["none"], "counted"))'))
mut_play("play: the status is ignored when a chance is looked up",
         ('                rec.append((status, missed, fit.cell[(status, missed)], "counted"))',
          '                rec.append((status, missed, fit.cell[("none", missed)], "counted"))'))
# -- in the opportunity model
mut_play("play: the chances are not used",
         ("        p = self.chance.chances(hist, slate)", "        p = np.ones(len(slate))"))
mut_play("play: a player is weighed at his own chance too",
         ("            beside = m + (likely - p * m)       # him, and his teammates at their chances",
          "            beside = likely"))
mut_play("play: carries are left as they were",
         ("        for stat in SHARED:\n            m = out[stat]",
          "        for stat in SHARED[:1]:\n            m = out[stat]"))
mut_play("play: teammates across the whole slate, not his team's game",
         ('        team = pd.Series(list(zip(slate["game_id"], slate["team"])), dtype=object)',
          '        team = pd.Series(["all"] * len(slate), dtype=object)'))
mut_play("play: the closing lines handed in are dropped",
         ("        super().__init__(name, lines=lines, single=single)",
          "        super().__init__(name, lines=None, single=single)"))
mut_play("play: the choice of single number is dropped",
         ("        super().__init__(name, lines=lines, single=single)",
          "        super().__init__(name, lines=lines)"))
mut_play("play: left to itself it is handed nothing to count with",
         ("        self.chance = chance if chance is not None else PlayChance()",
          "        self.chance = chance"))
# -- chance beside played
mut_play("play check: graded on who was active, not who was listed",
         ("        slate = slate_candidates(frame, hist)\n        d = chance.describe(hist, slate)",
          "        slate = __import__('ff_sim').slate_active(frame, hist)\n        d = chance.describe(hist, slate)"))
mut_play("play check: 'played' means played for anyone",
         ('        was = set(zip(frame.team[frame.t == t], frame.player_id[frame.t == t]))',
          '        was = {(tm, q) for q in frame.player_id[frame.t == t] for tm in set(frame.team)}'))
mut_play("play check: 'played' is read from the first week asked for",
         ('        was = set(zip(frame.team[frame.t == t], frame.player_id[frame.t == t]))',
          '        was = set(zip(frame.team[frame.t == weeks[0]], frame.player_id[frame.t == weeks[0]]))'))
mut_play("play check: the chance sees the week it is checked on",
         ("        hist = History(frame[frame.t < t], t)\n        slate = slate_candidates(frame, hist)",
          "        hist = History(frame[frame.t <= t], t + 1)\n        slate = slate_candidates(frame, History(frame[frame.t < t], t))"))

# ---- S24: touchdowns (ff_sim_td.py)
mut_td("td: receiving touchdowns per target counts rushing ones",
       ('    "td_per_target": ("receiving_tds", "targets"),',
        '    "td_per_target": ("rushing_tds", "targets"),'))
mut_td("td: rushing touchdowns per carry counts receiving ones",
       ('    "td_per_carry": ("rushing_tds", "carries"),',
        '    "td_per_carry": ("receiving_tds", "carries"),'))
mut_td("td: touchdown passes are counted per completion",
       ('    "td_per_attempt": ("passing_tds", "attempts"),',
        '    "td_per_attempt": ("passing_tds", "completions"),'))
mut_td("td: targets use the carry rate and carries the target rate",
       ('ANYTIME_PARTS = (("targets", "td_per_target"), ("carries", "td_per_carry"))',
        'ANYTIME_PARTS = (("targets", "td_per_carry"), ("carries", "td_per_target"))'))
mut_td("td: an anytime touchdown leaves rushing out",
       ('ANYTIME_PARTS = (("targets", "td_per_target"), ("carries", "td_per_carry"))',
        'ANYTIME_PARTS = (("targets", "td_per_target"),)'))
mut_td("td: an anytime touchdown leaves receiving out",
       ('ANYTIME_PARTS = (("targets", "td_per_target"), ("carries", "td_per_carry"))',
        'ANYTIME_PARTS = (("carries", "td_per_carry"),)'))
mut_td("td: the two parts are reported rushing first",
       ('ANYTIME_PARTS = (("targets", "td_per_target"), ("carries", "td_per_carry"))',
        'ANYTIME_PARTS = (("carries", "td_per_carry"), ("targets", "td_per_target"))'))
mut_td("td: passing touchdowns use the rushing rate",
       ('PASSING = ("attempts", "td_per_attempt")', 'PASSING = ("attempts", "td_per_carry")'))
mut_td("td: passing touchdowns come from his carries",
       ('PASSING = ("attempts", "td_per_attempt")', 'PASSING = ("carries", "td_per_attempt")'))
mut_td("td: its list of stats leaves the touchdowns out",
       ("ALL_STATS = (*EFF_STATS, *TD_STATS)", "ALL_STATS = EFF_STATS"))
mut_td("td: the lightest pull on the list is lighter",
       ("TD_SHRINK_GRID = (20.0, 40.0,", "TD_SHRINK_GRID = (10.0, 40.0,"))
mut_td("td: the heaviest pull on the list is heavier",
       ("                  5120.0, 10240.0)", "                  5120.0, 20480.0)"))
mut_td("td: one pull in the middle of the list is moved",
       ("80.0, 160.0, 320.0,", "80.0, 200.0, 320.0,"))
# -- the fit
mut_td("td: a second history gets the first one's fit",
       ("        if self._last[0] is hist:", "        if self._last[0] is not None:"))
mut_td("td: nothing is remembered between calls",
       ("        fit.ok = True\n        self._last = (hist, fit)", "        fit.ok = True"))
mut_td("td: games without the opportunity count as games with it",
       ("            had = (den > 0).to_numpy()", "            had = (den >= 0).to_numpy()"))
mut_td("td: sixteen games are not enough",
       ("            if int(had.sum()) < MIN_RATE_ROWS:",
        "            if int(had.sum()) <= MIN_RATE_ROWS:"))
mut_td("td: eight games are enough",
       ("            if int(had.sum()) < MIN_RATE_ROWS:", "            if int(had.sum()) < 8:"))
mut_td("td: a thin history is named by its column, not in words",
       ('                           f"{ONE[den_col]} in the history; needs {MIN_RATE_ROWS}")',
        '                           f"{den_col} in the history; needs {MIN_RATE_ROWS}")'))
mut_td("td: a thin history is fitted anyway",
       ("                self._last = (hist, fit)\n                return fit\n", ""))
mut_td("td: the all-player rate is a mean of game rates",
       ("            overall = float(num.sum() / den.sum())",
        "            overall = float((num[den > 0] / den[den > 0]).mean())"))
mut_td("td: in the fit every position is pulled to the all-player rate",
       ("            norm = F.position.map(by_pos).fillna(overall).to_numpy(dtype=float)",
        "            norm = F.position.map({}).fillna(overall).to_numpy(dtype=float)"))
mut_td("td: a player with no position breaks the fit",
       ("            norm = F.position.map(by_pos).fillna(overall).to_numpy(dtype=float)",
        "            norm = F.position.map(by_pos).to_numpy(dtype=float)"))
mut_td("td: touchdowns lean on the newest twice as hard",
       ("leaning_sum(num, F.player_id, HALF_LIFE_RATE)",
        "leaning_sum(num, F.player_id, HALF_LIFE_RATE / 2)"))
mut_td("td: opportunities lean on the newest twice as hard",
       ("leaning_sum(den, F.player_id, HALF_LIFE_RATE)",
        "leaning_sum(den, F.player_id, HALF_LIFE_RATE / 2)"))
mut_td("td: totals do not lean at all",
       ("leaning_sum(num, F.player_id, HALF_LIFE_RATE)", "leaning_sum(num, F.player_id, 1e9)"),
       ("leaning_sum(den, F.player_id, HALF_LIFE_RATE)", "leaning_sum(den, F.player_id, 1e9)"))
mut_td("td: a player's totals run on into the next player's",
       ("leaning_sum(num, F.player_id, HALF_LIFE_RATE)", "leaning_sum(num, F.season * 0, HALF_LIFE_RATE)"),
       ("leaning_sum(den, F.player_id, HALF_LIFE_RATE)", "leaning_sum(den, F.season * 0, HALF_LIFE_RATE)"))
mut_td("td: the pull is scored by absolute miss",
       ("            miss = {k: float(((x - d * pulled(nb, db, norm[had], k)) ** 2).sum())",
        "            miss = {k: float(np.abs(x - d * pulled(nb, db, norm[had], k)).sum())"))
mut_td("td: the pull is scored on rates, a one-target game counting as much as a ten",
       ("            miss = {k: float(((x - d * pulled(nb, db, norm[had], k)) ** 2).sum())",
        "            miss = {k: float(((x / d - pulled(nb, db, norm[had], k)) ** 2).sum())"))
mut_td("td: the pull is scored with the game being scored already counted",
       ("            nb, db = num_before.to_numpy()[had], den_before.to_numpy()[had]",
        "            nb, db = num_before.to_numpy()[had] + x, den_before.to_numpy()[had] + d"))
mut_td("td: the worst pull is picked",
       ("                k=min(TD_SHRINK_GRID, key=miss.get), miss=miss,",
        "                k=max(TD_SHRINK_GRID, key=miss.get), miss=miss,"))
mut_td("td: the lightest pull is always picked",
       ("                k=min(TD_SHRINK_GRID, key=miss.get), miss=miss,",
        "                k=TD_SHRINK_GRID[0], miss=miss,"))
mut_td("td: a player's touchdowns and opportunities are stored swapped",
       ("                num_now=num_now.to_dict(), den_now=den_now.to_dict())",
        "                num_now=den_now.to_dict(), den_now=num_now.to_dict())"))
mut_td("td: a good fit is marked unusable",
       ("        fit.ok = True\n", "        fit.ok = False\n"))
# -- rates for a slate
mut_td("td: a thin history gives a rate of zero, not none",
       ("                out[rate] = np.full(n, np.nan)", "                out[rate] = np.zeros(n)"))
mut_td("td: an unseen position is pulled to zero",
       ('            norm = np.array([r["by_pos"].get(p, r["overall"]) for p in pos],',
        '            norm = np.array([r["by_pos"].get(p, 0.0) for p in pos],'))
mut_td("td: on the slate every position is pulled to the all-player rate",
       ('            norm = np.array([r["by_pos"].get(p, r["overall"]) for p in pos],',
        '            norm = np.array([r["overall"] for p in pos],'))
mut_td("td: his own touchdowns are ignored",
       ('            own_num = np.array([r["num_now"].get(p, 0.0) for p in pid], dtype=float)',
        '            own_num = np.array([0.0 for p in pid], dtype=float)'))
mut_td("td: his own opportunities are ignored",
       ('            own_den = np.array([r["den_now"].get(p, 0.0) for p in pid], dtype=float)',
        '            own_den = np.array([0.0 for p in pid], dtype=float)'))
mut_td("td: the pull used is not the one picked",
       ('            out[rate] = pulled(own_num, own_den, norm, r["k"])',
        '            out[rate] = pulled(own_num, own_den, norm, TD_SHRINK_GRID[0])'))
mut_td("td: every player is given his position's rate",
       ('            out[rate] = pulled(own_num, own_den, norm, r["k"])',
        '            out[rate] = norm'))
# -- parts and variances
mut_td("td: passing touchdowns are spread as targets are",
       ('        td = {"passing_tds": [(mean[opp] * rt[rate], size[opp])],',
        '        td = {"passing_tds": [(mean[opp] * rt[rate], size["targets"])],'))
mut_td("td: rushing touchdowns are spread as targets are",
       ("              TD_STAT: [(mean[o] * rt[r], size[o]) for o, r in ANYTIME_PARTS]}",
        '              TD_STAT: [(mean[o] * rt[r], size["targets"]) for o, r in ANYTIME_PARTS]}'))
mut_td("td: the expected count is the opportunities, not opportunities times rate",
       ("              TD_STAT: [(mean[o] * rt[r], size[o]) for o, r in ANYTIME_PARTS]}",
        "              TD_STAT: [(mean[o], size[o]) for o, r in ANYTIME_PARTS]}"))
mut_td("td: the expected count is the first part's alone",
       ("            mean[stat] = sum(m for m, _ in pieces)", "            mean[stat] = pieces[0][0]"))
mut_td("td: the efficiency model's parts are dropped",
       ('        return {**p, "mean": mean, "td": td}', '        return {"mean": mean, "td": td}'))
mut_td("td: what the touchdowns are built from is not reported",
       ('        return {**p, "mean": mean, "td": td}', '        return {**p, "mean": mean}'))
mut_td("td: the efficiency model's variances are dropped",
       ("        out = dict(self.eff.variances(hist, slate))", "        out = {}"))
mut_td("td: the variance is the count's alone, as if nothing varied game to game",
       ("            out[stat] = sum(m + m ** 2 / r for m, r in pieces)",
        "            out[stat] = sum(m for m, r in pieces)"))
mut_td("td: the variance is the first part's alone",
       ("            out[stat] = sum(m + m ** 2 / r for m, r in pieces)",
        "            out[stat] = [m + m ** 2 / r for m, r in pieces][0]"))
# -- chances
mut_td("td: a touchdown stat's single number is asked of the efficiency model",
       ('        return float(self.p["mean"][stat][i])', "        return self.under.point(i, stat)"))
mut_td("td: yards and catches are not passed through",
       ("        if stat not in TD_STATS:\n            return self.under.p_over(i, stat, line)\n",
        "        if stat not in self.p[\"mean\"]:\n            return self.under.p_over(i, stat, line)\n"))
mut_td("td: an efficiency model handed in is ignored",
       ("        self.eff = efficiency if efficiency is not None else EfficiencyModel(\n            f\"{name}_efficiency\")",
        "        self.eff = EfficiencyModel(\n            f\"{name}_efficiency\")"))
mut_td("td: its own efficiency model is not named after it",
       ('            f"{name}_efficiency")', '            "efficiency")'))
mut_td("td: the name given is dropped",
       ("        self.name = name\n        self.eff", "        self.name = \"touchdowns\"\n        self.eff"))
mut_td("td: it claims not to depend on who is active",
       ("    uses_actives = True\n\n    def __init__(self, name: str = \"touchdowns\",",
        "    uses_actives = False\n\n    def __init__(self, name: str = \"touchdowns\","))
mut_td("td: the chances are priced on another slate's parts",
       ("        return _TdLines(self.eff.project(hist, slate), self.parts(hist, slate))",
        "        return _TdLines(self.eff.project(hist, slate), self.parts(hist, slate.iloc[::-1]))"))
# -- after the review: thin positions, chances added from the top, the tables
mut_td("td: a position with one catch has a rate of its own",
       ("            own = pos_den >= MIN_POSITION_UNITS", "            own = pos_den > 0"))
mut_td("td: exactly 200 of the thing is not enough for a position",
       ("            own = pos_den >= MIN_POSITION_UNITS", "            own = pos_den > MIN_POSITION_UNITS"))
mut_td("td: a position has its own rate from 100",
       ("MIN_POSITION_UNITS = 200.0", "MIN_POSITION_UNITS = 100.0"))
mut_td("td: a position needs 2000 for its own rate",
       ("MIN_POSITION_UNITS = 200.0", "MIN_POSITION_UNITS = 2000.0"))
mut_td("td: a line that is not a number is priced, not refused",
       ('        if not math.isfinite(line):\n            raise ValueError(f"a {stat} line must be a number; got {line!r}")\n', ""))
mut_td("td: the refusal does not say which stat's line",
       ('            raise ValueError(f"a {stat} line must be a number; got {line!r}")',
        '            raise ValueError(f"a line must be a number; got {line!r}")'))
mut_td("td: landing on a whole-number line counts as over it",
       ("        n = math.floor(line) + 1        # the fewest", "        n = math.ceil(line)        # the fewest"))
mut_td("td: a half line is the chance of two more than it",
       ("        n = math.floor(line) + 1        # the fewest", "        n = math.floor(line) + 2        # the fewest"))
mut_td("td: the spread of the count ignores how his opportunities vary",
       ('        (m0, r0), *more = [(float(m[i]), r) for m, r in self.p["td"][stat]]',
        '        (m0, r0), *more = [(float(m[i]), 100 * r) for m, r in self.p["td"][stat]]'))
mut_td("td: the count is priced at twice its expected number",
       ('        (m0, r0), *more = [(float(m[i]), r) for m, r in self.p["td"][stat]]',
        '        (m0, r0), *more = [(2 * float(m[i]), r) for m, r in self.p["td"][stat]]'))
mut_td("td: only the first part is counted",
       ("        for m1, r1 in more:", "        for m1, r1 in []:"))
mut_td("td: the first part getting there alone is left out",
       ("        p = float(nbinom.sf(n - 1, r0, r0 / (r0 + m0)))", "        p = 0.0"))
mut_td("td: the first part alone has to beat the line by one more",
       ("        p = float(nbinom.sf(n - 1, r0, r0 / (r0 + m0)))",
        "        p = float(nbinom.sf(n, r0, r0 / (r0 + m0)))"))
mut_td("td: the second part has to make one more than the rest",
       ("                        * nbinom.sf(n - 1 - k, r1, r1 / (r1 + m1))).sum())",
        "                        * nbinom.sf(n - k, r1, r1 / (r1 + m1))).sum())"))
mut_td("td: the second part only has to get there by itself",
       ("                        * nbinom.sf(n - 1 - k, r1, r1 / (r1 + m1))).sum())",
        "                        * nbinom.sf(n - 1, r1, r1 / (r1 + m1))).sum())"))
mut_td("td: the first part's counts stop one short",
       ("            k = np.arange(n)\n            p += float(", "            k = np.arange(n - 1)\n            p += float("))
mut_td("td: the second part is spread as the first is",
       ("                        * nbinom.sf(n - 1 - k, r1, r1 / (r1 + m1))).sum())",
        "                        * nbinom.sf(n - 1 - k, r0, r0 / (r0 + m1))).sum())"))
mut_td("td: the chance returned is of NOT clearing the line",
       ("        return min(p, 1.0)      # can round", "        return 1.0 - min(p, 1.0)      # can round"))
mut_td("td: rounding can carry a chance over one",
       ("        return min(p, 1.0)      # can round", "        return p      # can round"))
mut_td("td: a player with no projection is certain to clear any line",
       ("        return min(p, 1.0)      # can round", "        return min(1.0, p)      # can round"))
# -- expected beside actual
mut_td("td table: the model sees the week it is set beside",
       ("        hist = History(frame[frame.t < t], t)\n        slate = slate_active(frame, hist)\n        p = model.parts(hist, slate)",
        "        hist = History(frame[frame.t <= t], t + 1)\n        slate = slate_active(frame, History(frame[frame.t < t], t))\n        p = model.parts(hist, slate)"))
mut_td("td table: it lists who had been playing, not who was active",
       ("        slate = slate_active(frame, hist)\n        p = model.parts(hist, slate)",
        "        slate = __import__('ff_sim').slate_candidates(frame, hist)\n        p = model.parts(hist, slate)"))
mut_td("td table: what he did is read from the first week asked for",
       ('        did = frame[frame.t == t].set_index(["game_id", "player_id"])',
        '        did = frame[frame.t == weeks[0]].set_index(["game_id", "player_id"])'))
mut_td("td table: a player with no number is kept",
       ('                "passing_tds", TD_STAT)}})[ok])', '                "passing_tds", TD_STAT)}}))'))
mut_td("td table: 'no number' is judged on passing touchdowns",
       ('        ok = ~np.isnan(p["mean"][TD_STAT])', '        ok = ~np.isnan(p["mean"]["passing_tds"])'))
mut_td("td table: expected targets and carries are swapped",
       ('            "e_targets": p["mean"]["targets"], "e_carries": p["mean"]["carries"],',
        '            "e_targets": p["mean"]["carries"], "e_carries": p["mean"]["targets"],'))
mut_td("td table: expected attempts are expected completions",
       ('            "e_attempts": p["mean"]["attempts"],', '            "e_attempts": p["mean"]["completions"],'))
mut_td("td table: receiving and rushing touchdowns are swapped",
       ('            "e_rec_td": p["td"][TD_STAT][0][0], "e_rush_td": p["td"][TD_STAT][1][0],',
        '            "e_rec_td": p["td"][TD_STAT][1][0], "e_rush_td": p["td"][TD_STAT][0][0],'))
mut_td("td table: expected passing touchdowns are the anytime number",
       ('            "e_pass_td": p["mean"]["passing_tds"],', '            "e_pass_td": p["mean"][TD_STAT],'))
mut_td("td table: the chance of one or more is of two or more",
       ('            "p1": [P.p_over(i, TD_STAT, 0.5) if ok[i] else np.nan',
        '            "p1": [P.p_over(i, TD_STAT, 1.5) if ok[i] else np.nan'))
mut_td("td table: the chance of two or more is of three or more",
       ('            "p2": [P.p_over(i, TD_STAT, 1.5) if ok[i] else np.nan',
        '            "p2": [P.p_over(i, TD_STAT, 2.5) if ok[i] else np.nan'))
mut_td("td table: nobody is marked as the starter",
       ('            "starter": slate["starting_qb"].to_numpy(),',
        '            "starter": np.zeros(len(slate), dtype=bool),'))
mut_td("td table: the team column is the opponent",
       ('            "team": slate["team"].to_numpy(),', '            "team": slate["opponent"].to_numpy(),'))
mut_td("td table: touchdowns scored are the rushing ones only",
       ('                "passing_tds", TD_STAT)}})[ok])',
        '                "passing_tds")}, TD_STAT: did["rushing_tds"].reindex(at).to_numpy(dtype=float)})[ok])'))
# -- the pulls picked
mut_td("td pulls: the pick for a week sees that week",
       ("        fit = model.fit(History(frame[frame.t < t], t))",
        "        fit = model.fit(History(frame[frame.t <= t], t + 1))"))
mut_td("td pulls: a week with too little history is kept",
       ("        if fit.ok:\n            out.append(", "        if True:\n            out.append("))
mut_td("td pulls: the week is not recorded",
       ('            out.append({"t": int(t), **{r: v["k"] for r, v in fit.rate.items()}})',
        '            out.append({"t": int(weeks[0]), **{r: v["k"] for r, v in fit.rate.items()}})'))
mut_td("td pulls: what is listed is the score, not the pull",
       ('            out.append({"t": int(t), **{r: v["k"] for r, v in fit.rate.items()}})',
        '            out.append({"t": int(t), **{r: v["overall"] for r, v in fit.rate.items()}})'))

# ---- S28: the live run (ff_sim_live.py)
mut_live("live: the Rams are given the Chargers' code",
         ('"Kansas City Chiefs": "KC", "Los Angeles Rams": "LA",',
          '"Kansas City Chiefs": "KC", "Los Angeles Rams": "LAC",'))
mut_live("live: an anytime touchdown is priced at one and a half",
         ('    "player_anytime_td": (TD_STAT, 0.5),', '    "player_anytime_td": (TD_STAT, 1.5),'))
mut_live("live: two or more touchdowns is priced as one or more",
         ('    "player_2plus_td": (TD_STAT, 1.5),', '    "player_2plus_td": (TD_STAT, 0.5),'))
mut_live("live: three or more touchdowns is priced as two or more",
         ('    "player_3plus_td": (TD_STAT, 2.5),', '    "player_3plus_td": (TD_STAT, 1.5),'))
mut_live("live: rushing attempts are read as rushing yards",
         ('    "player_rush_attempts": ("carries", None),',
          '    "player_rush_attempts": ("rushing_yards", None),'))
mut_live("live: targets are read as catches",
         ('    "player_reception_targets": ("targets", None),',
          '    "player_reception_targets": ("receptions", None),'))
mut_live("live: the fingerprint leaves the touchdown model out",
         ('MODEL_FILES = ("ff_sim.py", "ff_sim_opp.py", "ff_sim_eff.py", "ff_sim_play.py",\n               "ff_sim_td.py")',
          'MODEL_FILES = ("ff_sim.py", "ff_sim_opp.py", "ff_sim_eff.py", "ff_sim_play.py")'))
mut_live("live: the S21 caution starts at 70%",
         ("S21_FROM = 0.65", "S21_FROM = 0.70"))
mut_live("live: the D/ST is kept as a player",
         ('NOT_A_PLAYER = re.compile(r"d/st$|^no (touchdown|td) scorer$|^no scorer$", re.I)',
          'NOT_A_PLAYER = re.compile(r"^no (touchdown|td) scorer$|^no scorer$", re.I)'))
mut_live("live: the no-scorer row is kept as a player",
         ('NOT_A_PLAYER = re.compile(r"d/st$|^no (touchdown|td) scorer$|^no scorer$", re.I)',
          'NOT_A_PLAYER = re.compile(r"d/st$", re.I)'))
# -- reading files
mut_live('live: an unreadable odds file is not caught',
         ('            try:\n                s = Path(s).read_text()\n            except (OSError, UnicodeDecodeError) as e:\n                raise Missing(f"cannot read the odds file {where}: {e}") from e',
          '            s = Path(s).read_text()'))
mut_live("live: an odds file that is not JSON is not caught",
         ("        try:\n            source = json.loads(s)\n        except ValueError as e:\n            raise Missing(f\"{where} is not JSON: {e}\") from e",
          "        source = json.loads(s)"))
mut_live("live: the harness's wrapper is not opened",
         ('    if isinstance(source, list) and source and isinstance(source[0], dict) \\\n            and "text" in source[0]:',
          '    if False:'))
mut_live("live: a saved error text is not caught",
         ("        try:\n            source = json.loads(source[0][\"text\"])\n        except ValueError as e:\n            raise Missing(f\"{where} is a saved tool result whose text is not \"\n                          f\"JSON: {e}\") from e",
          "        source = json.loads(source[0][\"text\"])"))
mut_live("live: a response with no bookmakers is let through",
         ('    if not isinstance(source, dict) or not isinstance(source.get("bookmakers"), list):',
          '    if not isinstance(source, dict):'))
mut_live("live: only the home team's name is checked",
         ('    for side in ("home_team", "away_team"):', '    for side in ("home_team",):'))
mut_live("live: only the away team's name is checked",
         ('    for side in ("home_team", "away_team"):', '    for side in ("away_team",):'))
# -- posted lines
mut_live("live: the books asked for are ignored",
         ('        if books and q["book"] not in books:\n            continue\n', ''))
mut_live("live: a rung is priced at its number, not half a point under",
         ('            line = float(q["rung_threshold"]) - 0.5', '            line = float(q["rung_threshold"])'))
mut_live("live: a rung is priced half a point over its number",
         ('            line = float(q["rung_threshold"]) - 0.5', '            line = float(q["rung_threshold"]) + 0.5'))
mut_live("live: every line with a point counts as a main line",
         ('        main = (q["line_type"] == "main" and q["line"] is not None) \\',
          '        main = (q["line"] is not None) \\'))
mut_live("live: a rung in a main market counts as a main line",
         ('        main = (q["line_type"] == "main" and q["line"] is not None) \\',
          '        main = (q["line_type"] == "main") \\'))
mut_live("live: an anytime touchdown is a ladder line",
         ('        main = (q["line_type"] == "main" and q["line"] is not None) \\\n            or q["market"] == "player_anytime_td"',
          '        main = (q["line_type"] == "main" and q["line"] is not None)'))
mut_live("live: two or more touchdowns counts as a main line",
         ('            or q["market"] == "player_anytime_td"', '            or MARKETS[q["market"]][0] == TD_STAT'))
mut_live("live: a suspended market is not marked",
         ('                    q["suspended_at"] is not None))', '                    False))'))
mut_live("live: every market is marked suspended",
         ('                    q["suspended_at"] is not None))', '                    q["suspended_at"] is None))'))
mut_live("live: the book's id for the player is dropped",
         ('        rec.append((q["book"], q["market"], stat, q["player"], q["player_id"],',
          '        rec.append((q["book"], q["market"], stat, q["player"], None,'))
# -- inputs
mut_live("live: an unreadable inputs file is not caught",
         ("        except OSError as e:\n            raise Missing(f\"cannot read the inputs file {source}: {e}\") from e\n", ""))
mut_live("live: an inputs file that is not JSON is not caught",
         ("        except ValueError as e:\n            raise Missing(f\"the inputs file is not JSON: {e}\") from e\n",
          "        except ZeroDivisionError as e:\n            raise Missing(f\"the inputs file is not JSON: {e}\") from e\n"))
mut_live("live: inputs with no starters are let through",
         ('    if not isinstance(source, dict) or not isinstance(source.get("starters"), dict):',
          '    if not isinstance(source, dict) or source.get("starters") is None:'))
mut_live("live: a chance over 1 is let through",
         ("                or not 0.0 <= p <= 1.0:", "                or not 0.0 <= p:"))
mut_live("live: a chance under 0 is let through",
         ("                or not 0.0 <= p <= 1.0:", "                or not p <= 1.0:"))
mut_live("live: a chance of exactly 0 or 1 is refused",
         ("                or not 0.0 <= p <= 1.0:", "                or not 0.0 < p < 1.0:"))
mut_live("live: a chance given as true or false is let through",
         ("        if not isinstance(p, (int, float)) or isinstance(p, bool) \\",
          "        if not isinstance(p, (int, float)) \\"))
mut_live("live: a team's full name is not known",
         ("    if team in TEAM_CODE:\n        return TEAM_CODE[team]\n", ""))
mut_live("live: a team's code is not known",
         ("    if team in TEAM_CODE.values():\n        return team\n", ""))
# -- names
mut_live("live: a roster player with no ESPN number is given one",
         ('        has = r[r["espn_id"].notna()]', '        has = r'))
mut_live("live: an ESPN number is not matched as a whole number",
         ('        self.espn = {str(e).split(".")[0]: g for e, g in zip(has.espn_id, has.gsis_id)}',
          '        self.espn = {str(e): g for e, g in zip(has.espn_id, has.gsis_id)}'))
mut_live("live: a key that is not an ESPN number is looked up anyway",
         ('        if isinstance(key, str) and key.startswith("espn:"):\n            return self.espn.get(key[5:])',
          '        if isinstance(key, str):\n            return self.espn.get(key[5:] if key.startswith("espn:") else key)'))
mut_live("live: a name two players share picks one of them",
         ("        if len(found) != 1:", "        if len(found) < 1:"))
mut_live("live: the refusal does not list the players who share the name",
         ('                + (f" ({sorted(found)})" if found else "")\n', ''))
# -- the slate
mut_live("live: a slate for another week than the history's is built",
         ("    if t != hist.before:\n        raise ValueError(f\"the slate is for {t} and the history stops before \"\n                         f\"{hist.before}\")\n", ""))
mut_live("live: a team in two games is let through",
         ("    twice = sorted({tm for tm in teams if teams.count(tm) > 1})", "    twice = []"))
mut_live("live: a team with no starter named is let through",
         ("    unnamed = sorted(set(teams) - set(starters))", "    unnamed = []"))
mut_live("live: the slate reaches back five games",
         ("            recent = hist.team_recent_players(team, CANDIDATE_LOOKBACK)",
          "            recent = hist.team_recent_players(team, CANDIDATE_LOOKBACK + 1)"))
mut_live("live: the slate reaches back three games",
         ("            recent = hist.team_recent_players(team, CANDIDATE_LOOKBACK)",
          "            recent = hist.team_recent_players(team, CANDIDATE_LOOKBACK - 1)"))
mut_live("live: a team with no history is given an empty slate",
         ("            if not len(recent):\n                raise Missing(f\"{team} has no game in the history\")\n", ""))
mut_live("live: players added are left off the slate",
         ("            extra = [(pid, pos) for tm, pid, pos in add if tm == team] + [(qb, None)]",
          "            extra = [(qb, None)]"))
mut_live("live: a player added to one team is added to both",
         ("            extra = [(pid, pos) for tm, pid, pos in add if tm == team] + [(qb, None)]",
          "            extra = [(pid, pos) for tm, pid, pos in add] + [(qb, None)]"))
mut_live("live: a starter not on the slate is not put on it",
         ("            extra = [(pid, pos) for tm, pid, pos in add if tm == team] + [(qb, None)]",
          "            extra = [(pid, pos) for tm, pid, pos in add if tm == team]"))
mut_live("live: a player added twice is on the slate twice",
         ("            for pid in dict.fromkeys(order):", "            for pid in order:"))
mut_live("live: a position handed in is ignored",
         ("            pos_of = {pid: pos for pid, pos in extra if pos}", "            pos_of = {}"))
mut_live("live: a team is listed as its own opponent",
         ("        for team, opp in ((away, home), (home, away)):", "        for team, opp in ((away, away), (home, home)):"))
# -- the model
mut_live("live: the chances handed in do not reach the model",
         ("            f\"{name}_opp\", chance=PlayChance(reports, given=given))))",
          "            f\"{name}_opp\", chance=PlayChance(reports))))"))
mut_live("live: the injury report does not reach the model",
         ("            f\"{name}_opp\", chance=PlayChance(reports, given=given))))",
          "            f\"{name}_opp\", chance=PlayChance(None, given=given))))"))
mut_live("live: the model's name is not the one given",
         ("    return TouchdownModel(name, efficiency=EfficiencyModel(", "    return TouchdownModel(\"sim\", efficiency=EfficiencyModel("))
# -- sides
mut_live("live: a half-point line is treated as a whole number",
         ("    if float(line) != math.floor(line):", "    if False:"))
mut_live("live: a whole-number line cannot push",
         ("    if float(line) != math.floor(line):", "    if True:"))
mut_live("live: on a whole number, landing on it counts as over",
         ("    over, at_least = P.p_over(i, stat, line + 0.5), P.p_over(i, stat, line - 0.5)\n    return over, at_least - over, 1.0 - at_least",
          "    over, at_least = P.p_over(i, stat, line - 0.5), P.p_over(i, stat, line - 0.5)\n    return over, at_least - over, 1.0 - at_least"))
mut_live("live: on a whole number, landing on it counts as under",
         ("    return over, at_least - over, 1.0 - at_least", "    return over, at_least - over, 1.0 - over"))
mut_live("live: the under is the chance of the over",
         ("        return over, 0.0, 1.0 - over", "        return over, 0.0, over"))
# -- rungs
mut_live("live: the rung labels are in the wrong order",
         ('RUNG_LABELS = ("x0.6", "x0.8", MAIN, "x1.25", "x1.6")', 'RUNG_LABELS = ("x0.8", "x0.6", MAIN, "x1.25", "x1.6")'))
# -- one run
mut_live("live: a run with no week goes ahead on week 1",
         ("    if week is None:\n        raise Missing('no week: pass --week or put \"week\" in the inputs')\n",
          "    if week is None:\n        week = 1\n"))
mut_live("live: the week in the inputs wins over the one asked for",
         ("    week = week if week is not None else inputs.get(\"week\")", "    week = inputs.get(\"week\") or week"))
mut_live('live: a week that disagrees with the inputs is let through',
         ('    if inputs.get("week") is not None and inputs["week"] != week:',
          '    if False:'))
mut_live("live: a run with no odds files goes ahead",
         ("    if not len(events):\n        raise Missing(\"no odds files: nothing to price\")\n", ""))
mut_live("live: the model sees the week being run",
         ("    hist = History(frame[frame[\"t\"] < t], t)", "    hist = History(frame[frame[\"t\"] <= t], t + 1)"))
mut_live("live: a missing last week is let through",
         ("    if week > 1 and newest != tkey(season, week - 1):", "    if False:"))
mut_live("live: Week 1 is refused for having no last week",
         ("    if week > 1 and newest != tkey(season, week - 1):", "    if newest != tkey(season, week - 1):"))
mut_live("live: a last week with one team in four on file is let through",
         ("        if 2 * had < of:", "        if 8 * had < of:"))
mut_live("live: a last week with half the teams on file is refused",
         ("        if 2 * had < of:", "        if 2 * had <= of:"))
mut_live("live: last week's teams are counted over every season",
         ("        this_season = hist.frame[hist.frame[\"season\"] == season]", "        this_season = hist.frame"),
         ("        had = this_season.loc[this_season[\"t\"] == newest, \"team\"].nunique()",
          "        had = this_season[\"team\"].nunique()"))
mut_live("live: the home team is taken for the away team",
         ("    games = [(TEAM_CODE[e[\"away_team\"]], TEAM_CODE[e[\"home_team\"]]) for e in events]",
          "    games = [(TEAM_CODE[e[\"home_team\"]], TEAM_CODE[e[\"away_team\"]]) for e in events]"))
mut_live("live: a game already played is priced",
         ("    if played:\n        raise Missing(f\"{played} already have a game on file for week {week}: \"\n                      f\"that game has been played\")\n", ""))
mut_live("live: a run with no injury report goes ahead unasked",
         ("        if not allow_no_report:", "        if False:"))
mut_live('live: a starter named for a team not playing is looked up',
         ('    starters = {tm: placed(tm, who) for tm, who in inputs["starters"].items()\n                if tm in playing}',
          '    starters = {tm: placed(tm, who) for tm, who in inputs["starters"].items()}'))
mut_live('live: a chance or a status for a team not playing stops the run',
         ('        for tm, who, value in inputs[kind]:\n            if tm in playing:',
          '        for tm, who, value in inputs[kind]:\n            if True:'))
mut_live("live: the players added do not reach the slate",
         ("    slate = build_slate(hist, season, week, games, starters, names, add)",
          "    slate = build_slate(hist, season, week, games, starters, names)"))
mut_live("live: a chance for someone not on the slate is let pass",
         ("    if stray:\n        raise Missing(f\"a chance or a status was handed in for {stray}, who \"", "    if False:\n        raise Missing(f\"a chance or a status was handed in for {stray}, who \""))
mut_live("live: a status for someone not on the slate is let pass",
         ("for tm, pid in {*given, *said}", "for tm, pid in {*given}"))
mut_live("live: a chance for someone not on the slate is let pass, a status not",
         ("for tm, pid in {*given, *said}", "for tm, pid in {*said}"))
mut_live("live: a status that is not one of the five is let through",
         ("        if row.get(\"status\") not in STATUSES:", "        if row.get(\"status\") is None:"))
mut_live("live: a status handed in does not reach the report",
         ("    if said:\n        # A status", "    if False:\n        # A status"))
mut_live("live: the file's status is kept beside the one handed in",
         ("            old[~((old[\"t\"] == t) & old[\"player_id\"].isin(ids))],", "            old[~((old[\"t\"] == t + 1) & old[\"player_id\"].isin(ids))],"))
mut_live("live: a status handed in wipes that player's past reports",
         ("            old[~((old[\"t\"] == t) & old[\"player_id\"].isin(ids))],", "            old[~(old[\"player_id\"].isin(ids))],"))
mut_live("live: a status handed in wipes everyone's report for the week",
         ("            old[~((old[\"t\"] == t) & old[\"player_id\"].isin(ids))],", "            old[~((old[\"t\"] == t))],"))
mut_live("live: a status handed in is filed under last week",
         ("            pd.DataFrame([(t, pid, st) for (_, pid), st in said.items()", "            pd.DataFrame([(t - 1, pid, st) for (_, pid), st in said.items()"))
mut_live("live: a status handed in with no file breaks the run",
         ("        old = reports if reports is not None else pd.DataFrame(\n            columns=[\"t\", \"player_id\", \"status\"])", "        old = reports"))
mut_live("live: a chance from a status handed in does not say so",
         ("    slate.loc[told, \"source\"] = \"counted from the status handed in\"\n", ""))
mut_live("live: a chance given outright is relabelled as from a status",
         ("    told = [(tm, pid) in said and src != \"given\"", "    told = [(tm, pid) in said"))
mut_live("live: the chances handed in do not reach the run's model",
         ("    model = live_model(reports, given)", "    model = live_model(reports)"))
mut_live("live: a history too thin to fit is run anyway",
         ("    if all(math.isnan(P.point(i, s_)) for i in range(len(slate)) for s_ in ALL_STATS):", "    if False:"))
mut_live("live: the chance beside a player is not the one the model used",
         ("    slate = slate.assign(chance=ch[\"chance\"].to_numpy(), status=ch[\"status\"].to_numpy(),",
          "    slate = slate.assign(chance=1.0, status=ch[\"status\"].to_numpy(),"))
mut_live("live: the report's word beside a player is dropped",
         ("status=ch[\"status\"].to_numpy(),\n                         source=ch[\"source\"].to_numpy())",
          "status=\"none\",\n                         source=ch[\"source\"].to_numpy())"))
mut_live("live: where a chance came from is always 'counted'",
         ("                         source=ch[\"source\"].to_numpy())", "                         source=\"counted\")"))
mut_live("live: a team whose newest game is old is not noted",
         ("        if week > 1 and last != tkey(season, week - 1):", "        if False:"))
mut_live("live: in Week 1 every team is noted as stale",
         ("        if week > 1 and last != tkey(season, week - 1):", "        if last != tkey(season, week - 1):"))
mut_live("live: the books asked for do not reach the reader",
         ("        L = posted_lines(e, books)", "        L = posted_lines(e)"))
mut_live("live: names on the slate are matched as spelled",
         ("        by_name.setdefault((tm, norm_player(nm)), []).append(i)", "        by_name.setdefault((tm, nm), []).append(i)"))
mut_live("live: a line with no projection is priced as nothing",
         ("                if math.isnan(expected):", "                if False:"))
mut_live("live: the expected number on a line is the chance of the over",
         ("                             expected, over, push, under))", "                             over, over, push, under))"))
mut_live("live: over and under are swapped on a line",
         ("                             expected, over, push, under))", "                             expected, under, push, over))"))
# -- the record
mut_live('live: the record grades the list-known slate',
         ('        rec["bands"][stat] = {\n            r: table(fs.graded_legs(run, "live", version="B", stats=[stat],',
          '        rec["bands"][stat] = {\n            r: table(fs.graded_legs(run, "live", version="A", stats=[stat],'))
mut_live("live: every rung's table is the pooled one",
         ('                                    rung=r), True)',
          '                                    rung=None), True)'))
mut_live('live: the bands are read on the over, not the side favoured',
         ('                                    rung=r), True)',
          '                                    rung=r), False)'))
mut_live("live: the anytime touchdown is kept on the side favoured",
         ("        fs.graded_legs(run, \"live\", version=\"B\", stats=[TD_STAT]), False)}",
          "        fs.graded_legs(run, \"live\", version=\"B\", stats=[TD_STAT]), True)}"))
mut_live("live: the S21 figures take every rung",
         ("        rec[\"s21\"][stat] = s21(fs.graded_legs(run, \"live\", version=\"B\",\n                                              stats=[stat], rung=MAIN))",
          "        rec[\"s21\"][stat] = s21(fs.graded_legs(run, \"live\", version=\"B\",\n                                              stats=[stat]))"))
mut_live("live: the pooled S21 figures take every rung",
         ("    rec[\"s21\"][\"all\"] = s21(fs.graded_legs(run, \"live\", version=\"B\",\n                                           stats=laddered, rung=MAIN))",
          "    rec[\"s21\"][\"all\"] = s21(fs.graded_legs(run, \"live\", version=\"B\",\n                                           stats=laddered))"))
mut_live("live: the pooled S21 figures grade the list-known slate",
         ("    rec[\"s21\"][\"all\"] = s21(fs.graded_legs(run, \"live\", version=\"B\",", "    rec[\"s21\"][\"all\"] = s21(fs.graded_legs(run, \"live\", version=\"A\","))
mut_live("live: the S21 figures count every leg, not those at 65% or better",
         ("            d = g[(g.side == side) & (g.p_side >= S21_FROM)]", "            d = g[(g.side == side)]"))
mut_live("live: the S21 figures leave out a leg at exactly 65%",
         ("            d = g[(g.side == side) & (g.p_side >= S21_FROM)]", "            d = g[(g.side == side) & (g.p_side > S21_FROM + 0.02)]"))
mut_live("live: overs and unders are pooled in the S21 figures",
         ("            d = g[(g.side == side) & (g.p_side >= S21_FROM)]", "            d = g[(g.p_side >= S21_FROM)]"))
mut_live("live: the S21 'happened' is the stated chance",
         ("                         None if not len(d) else round(float(d.hit.mean()), 4)]",
          "                         None if not len(d) else round(float(d.p_side.mean()), 4)]"))
mut_live("live: a band's 'happened' is its stated chance",
         ("                 None if not r.n else round(float(r.happened), 4), r.read]", "                 None if not r.n else round(float(r.stated), 4), r.read]"))
mut_live("live: a band's count of legs is its count of games",
         ("        return [[float(lo), float(hi), int(r.n), int(r.games),", "        return [[float(lo), float(hi), int(r.games), int(r.games),"))
mut_live("live: a record is made though the leak probe failed",
         ("    if not probe.clean or run.unverified:", "    if False:"))
# -- reading the record
mut_live("live: the top of a band belongs to it, not the next",
         ("        if b[0] <= p < b[1] or (p == 1.0 and b[1] >= 1.0):", "        if b[0] < p <= b[1] or (p == 1.0 and b[1] >= 1.0):"))
mut_live("live: a chance of exactly 100% has no band",
         ("        if b[0] <= p < b[1] or (p == 1.0 and b[1] >= 1.0):", "        if b[0] <= p < b[1]:"))
mut_live("live: a line with no rung is read on the first table there is",
         ("    if not rung or not 0.0 <= p <= 1.0:\n        return None\n", "    if not 0.0 <= p <= 1.0:\n        return None\n    rung = rung or MAIN\n"))
# -- cautions
mut_live("live: passing-touchdown lines carry no warning",
         ("    if row.stat == \"passing_tds\":\n        out.append(PASS_TD_UNDER)\n", ""))
mut_live("live: passing yards carry the passing-touchdown warning",
         ("    if row.stat == \"passing_tds\":\n        out.append(PASS_TD_UNDER)", "    if row.stat.startswith(\"passing\"):\n        out.append(PASS_TD_UNDER)"))
mut_live("live: the S21 caution misses a line at exactly 65%",
         ("max(row.over, row.under) >= S21_FROM:\n        n, stated", "max(row.over, row.under) > S21_FROM:\n        n, stated"))
mut_live("live: the S21 caution quotes the other side's record",
         ("    side = \"OVER\" if row.over >= row.under else \"UNDER\"", "    side = \"UNDER\" if row.over >= row.under else \"OVER\""))
mut_live("live: the S21 caution quotes every stat's record, not this one's",
         ("        n, stated, happened = record[\"s21\"].get(row.stat, {}).get(side, (0, None, None))",
          "        n, stated, happened = record[\"s21\"].get(\"all\", {}).get(side, (0, None, None))"))
mut_live("live: a match by name is not flagged",
         ("    if row.matched == \"name\":\n        out.append(\"matched by NAME, not by id: check it is the right player\")\n", ""))
mut_live("live: a suspended market is not flagged",
         ("    if row.suspended:\n        out.append(f\"SUSPENDED at {row.suspended}\")\n", ""))
mut_live("live: a push is not flagged",
         ("    if row.push > 0:\n        out.append(f\"whole-number line: pushes {row.push:.1%}\")\n", ""))
# -- what is printed
mut_live("live: a touchdown is read on the side favoured",
         ("        b, what = band_of(record, TD_STAT, MAIN, row.over), \"scored\"",
          "        b, what = band_of(record, TD_STAT, MAIN, max(row.over, row.under)), \"scored\""))
mut_live("live: a line is read on the chance of the over, not the side favoured",
         ("        b = band_of(record, row.stat, row.rung, max(row.over, row.under))",
          "        b = band_of(record, row.stat, row.rung, row.over)"))
mut_live("live: an empty band is printed as a record of nothing",
         ("    if not n:\n        return f\"said {lo:.0%}-{hi:.0%}{where}: never, in the record\"\n", "    happened = happened or 0.0\n"))
mut_live("live: the record does not say where it was read",
         ("    return (f\"said {lo:.0%}-{hi:.0%}{where}: {what} {happened:.1%} of \"", "    return (f\"said {lo:.0%}-{hi:.0%}: {what} {happened:.1%} of \""))
mut_live("live: the record leaves out how it reads",
         ("            f\"{n:,} ({read})\")", "            f\"{n:,}\")"))
mut_live("live: a stat line keeps numbers under a half",
         ("        if not math.isnan(v) and v >= 0.5:", "        if not math.isnan(v):"))
mut_live("live: a stat line leaves out the chance of scoring",
         ("    if not math.isnan(td):\n        bits.append(f\"scores {td:.0%}\")\n", ""))
mut_live("live: the chance of scoring is the chance of two or more",
         ("    td = P.p_over(i, TD_STAT, 0.5)", "    td = P.p_over(i, TD_STAT, 1.5)"))
mut_live("live: the printout says nothing about being a shadow run",
         ("        \"SHADOW RUN: the simulator's own numbers. Not a lean, no prices; a \"\n        \"posted line is only a benchmark.\",\n", ""))
mut_live("live: the printout leaves out 'if he plays'",
         ("        \"Every number is IF HE PLAYS.\",\n", ""))
mut_live("live: the S21 banner quotes unders as overs",
         ("        f\"({s21['OVER'][0]:,} legs); unders stated {s21['UNDER'][1]:.1%}, \"", "        f\"({s21['OVER'][0]:,} legs); unders stated {s21['OVER'][1]:.1%}, \""))
mut_live("live: the passing-touchdown and scoring cautions are left off the top",
         ("        \"S24. Passing-touchdown UNDERS are unreliable: overstated by about 5 \"\n        \"points. S25. A regular's chance of scoring runs about 2 points low.\",\n", ""))
mut_live("live: the run's notes are not printed",
         ("    ] + [\"NOTE. \" + n for n in board.notes] + [\"\"]", "    ] + [\"\"]"))
mut_live("live: a player with no posted line is printed anyway",
         ("                if not (everyone or r.player_id in priced or r.starting_qb):", "                if False:"))
mut_live("live: asking for everyone changes nothing",
         ("                if not (everyone or r.player_id in priced or r.starting_qb):", "                if not (r.player_id in priced or r.starting_qb):"))
mut_live("live: a starter with no posted line is left out",
         ("                if not (everyone or r.player_id in priced or r.starting_qb):", "                if not (everyone or r.player_id in priced):"))
mut_live("live: players are printed in slate order",
         ("            for i in sorted(T.index, key=lambda i: (\n                    not S.starting_qb[i], POSITION_ORDER.get(S.position[i], 9), -busy(i))):",
          "            for i in T.index:"))
mut_live("live: the starter is not printed first",
         ("                    not S.starting_qb[i], POSITION_ORDER.get(S.position[i], 9), -busy(i))):",
          "                    POSITION_ORDER.get(S.position[i], 9), -busy(i))):"))
mut_live("live: the starter is not marked in print",
         ("{', starting QB' if r.starting_qb else ''})\"", "{''})\""))
mut_live("live: the report's word is not printed",
         ("                    f\"{'' if r.status == 'none' else ', report: ' + r.status})\"", "                    f\"{''})\""))
mut_live("live: a touchdown is printed as an over and an under",
         ("                    odds = (f\"yes {row.over:.1%}\" if row.stat == TD_STAT else", "                    odds = (f\"yes {row.over:.1%}\" if False else"))
mut_live("live: two or more touchdowns is printed as 'to score'",
         ("                    what = (\"to score\" if row.line == 0.5 else", "                    what = (\"to score\" if True else"))
mut_live("live: the cautions are not printed under a line",
         ("                    out += [f\"        ! {f}\" for f in flags_for(record, row)]\n", ""))
mut_live("live: the record is not printed beside a line",
         ("                               f\"{record_text(record, row)}\")", "                               f\"\")"))
mut_live("live: what was not priced is not printed",
         ("    if board.unmatched:\n        out.append(\"POSTED BUT NOT PRICED\")", "    if False:\n        out.append(\"POSTED BUT NOT PRICED\")"))
mut_live("live: a player's lines are another player's",
         ("                mine = L[(L.game_id == gid) & (L.team == team) & (L.player_id == r.player_id)]",
          "                mine = L[(L.game_id == gid) & (L.team == team)]"))
mut_live("live: the saved table has no record column",
         ("    d[\"record\"] = [record_text(record, r) for r in board.lines.itertuples(index=False)]\n", ""))
mut_live("live: the saved table's cautions are run together",
         ("    d[\"cautions\"] = [\" | \".join(flags_for(record, r))", "    d[\"cautions\"] = [\"\".join(flags_for(record, r))"))
mut_live("live: the saved table has the week in the season's place",
         ("    d.insert(0, \"week\", week)\n    d.insert(0, \"season\", season)", "    d.insert(0, \"week\", season)\n    d.insert(0, \"season\", week)"))
# -- the whole run
mut_live("live run: the record is not checked before a run",
         ("    try:\n        check_record(record)\n        if not inputs:", "    try:\n        if not inputs:"))
mut_live("live run: a run with no inputs file is not stopped by name",
         ("        if not inputs:\n            raise Missing(\"no --inputs file: it names the week and each \"\n                          \"team's starting quarterback\")\n", ""))
mut_live("live run: a stop ends with code 0",
         ("        return f\"STOPPED. {e}\", 2", "        return f\"STOPPED. {e}\", 0"))
mut_live("live run: a stop does not say STOPPED",
         ("        return f\"STOPPED. {e}\", 2", "        return f\"{e}\", 2"))
mut_live("live run: asking for everyone does not reach the printout",
         ("    text = render(board, record, everyone=everyone)", "    text = render(board, record)"))
mut_live("live run: the saved table does not say how many lines",
         ("        text += f\"\\n\\nsaved {len(board.lines):,} priced lines to {out}\"\n", ""))
mut_live("live run: the saved table carries the wrong week",
         ("               int(board.slate.week.iloc[0])).to_csv(out, index=False)", "               int(board.slate.week.iloc[0]) + 1).to_csv(out, index=False)"))
mut_live("live run: a good run ends with code 2",
         ("    return text, 0", "    return text, 2"))
# -- after the review: reading, kickoffs, inputs
mut_live("live2: only main lines are read from the file",
         ('        quotes = flatten_odds(event, line_type="")', '        quotes = flatten_odds(event, line_type="main")'))
mut_live("live2: a file that does not pair up is not caught",
         ("    try:\n        quotes = flatten_odds(event, line_type=\"\")\n    except ValueError as e:\n        raise Missing(f\"{game_of(event)}: the odds file does not pair up: {e}\") from e",
          "    quotes = flatten_odds(event, line_type=\"\")"))
mut_live("live2: a market with no stat is not counted",
         ("            passed[f\"no stat for {q['market']}\"] += 1\n            continue", "            continue"))
mut_live("live2: a posted point is ignored for the market's own line",
         ('        if q["line"] is not None:\n            try:', '        if q["line"] is not None and own is None:\n            try:'))
mut_live("live2: a point that is not a number is not caught",
         ("            try:\n                line = float(q[\"line\"])\n            except (TypeError, ValueError):\n                line = float(\"nan\")",
          "            line = float(q[\"line\"])"))
mut_live("live2: a label it cannot read is priced at zero",
         ('            line = float("nan")     # a label', '            line = 0.0     # a label'))
mut_live("live2: a label it cannot read is not counted",
         ("            passed[f\"label not read in {q['market']}\"] += 1\n            continue", "            continue"))
mut_live("live2: what was passed over is not handed on",
         ('    out.attrs["passed_over"] = dict(passed)', '    out.attrs["passed_over"] = {}'))
mut_live('live2: every player is said to be on the home team',
         ('                team = oc.get("player_team")\n',
          '                team = event.get("home_team")\n'))
mut_live("live2: a player is listed under the outcome's label, not his name",
         ('                who = oc.get("description") or oc.get("name")',
          '                who = oc.get("name")'))
mut_live("live2: a game is called home at away",
         ('''    return f"{TEAM_CODE[event['away_team']]} at {TEAM_CODE[event['home_team']]}"''',
          '''    return f"{TEAM_CODE[event['home_team']]} at {TEAM_CODE[event['away_team']]}"'''))
mut_live("live2: a game in progress is priced",
         ('        if e.get("live"):', '        if False:'))
mut_live("live2: a game that has started is priced",
         ("        elif kick <= now:", "        elif False:"))
mut_live("live2: a game kicking off this minute is priced",
         ("        elif kick <= now:", "        elif kick < now:"))
mut_live('live2: with no window, a game weeks off is priced',
         ('        elif window is None and kick > now + pd.Timedelta(days=MAX_DAYS_AHEAD):',
          '        elif False:'))
mut_live('live2: a game exactly eight days off is refused',
         ('        elif window is None and kick > now + pd.Timedelta(days=MAX_DAYS_AHEAD):',
          '        elif window is None and kick >= now + pd.Timedelta(days=MAX_DAYS_AHEAD):'))
mut_live("live2: a game nine days off is taken",
         ("MAX_DAYS_AHEAD = 8", "MAX_DAYS_AHEAD = 9"))
mut_live("live2: a game eight days off is refused",
         ("MAX_DAYS_AHEAD = 8", "MAX_DAYS_AHEAD = 7"))
mut_live("live2: a file with no kickoff time is run without a word",
         ('            notes.append(f"{game_of(e)}: no kickoff time in the odds file, "',
          '            (lambda *_: None)(f"{game_of(e)}: no kickoff time in the odds file, "'))
mut_live("live2: a kickoff time with no zone is not read as UTC",
         ('            kick = kick.tz_localize("UTC") if kick.tzinfo is None else kick.tz_convert("UTC")',
          '            kick = kick if kick.tzinfo is None else kick.tz_convert("UTC")'))
mut_live("live2: a key it does not know is let through",
         ("    if odd:\n        raise Missing(f\"the inputs have {odd}, which is not one of \"", "    if False:\n        raise Missing(f\"the inputs have {odd}, which is not one of \""))
mut_live("live2: a week that is not a whole number is let through",
         ("        if v is not None and (isinstance(v, bool) or not isinstance(v, int)):", "        if False:"))
mut_live("live2: a season given as true is let through",
         ("        if v is not None and (isinstance(v, bool) or not isinstance(v, int)):", "        if v is not None and not isinstance(v, int):"))
mut_live("live2: the week in the inputs is dropped",
         ("        out[k] = v", "        out[k] = None"))
mut_live("live2: a team with two starters named is let through",
         ('        if team_code(team) in out["starters"]:', '        if False:'))
mut_live("live2: a starter's team is not turned into its code",
         ('        out["starters"][team_code(team)] = who', '        out["starters"][team] = who'))
mut_live("live2: rows that are not rows are let through",
         ("        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):", "        if False:"))
mut_live("live2: a row with a key it does not know is let through",
         ('            if set(row) - keys or not {"team", "player"} <= set(row):', '            if not {"team", "player"} <= set(row):'))
mut_live("live2: a row with no team or no player is let through",
         ('            if set(row) - keys or not {"team", "player"} <= set(row):', '            if set(row) - keys:'))
mut_live("live2: a chance given as text is let through",
         ("                if not isinstance(p, (int, float)) or isinstance(p, bool) \\\n                        or not 0.0 <= p <= 1.0:",
          "                if p is None or isinstance(p, bool) \\\n                        or not 0.0 <= float(p) <= 1.0:"))
mut_live("live2: the statuses handed in are dropped on reading",
         ('                out[kind].append((team, who, row["status"]))', '                pass'))
mut_live("live2: the chances handed in are dropped on reading",
         ("                out[kind].append((team, who, float(p)))", "                pass"))
mut_live("live2: the players added are dropped on reading",
         ('                out[kind].append((team, who, row.get("position")))', '                pass'))
mut_live("live2: an added player's position is dropped on reading",
         ('                out[kind].append((team, who, row.get("position")))', '                out[kind].append((team, who, None))'))
# -- names and the slate
mut_live("live2: names are matched as spelled, suffix and all",
         ("                self.by_name.setdefault((team, norm_player(name)), set()).add(g)",
          "                self.by_name.setdefault((team, str(name).lower()), set()).add(g)"))
mut_live("live2: names from the history are not looked in",
         ("        for ids, names, teams in ((r.gsis_id, r.full_name, r.team),\n                                  (F.player_id, F.name, F.team)):",
          "        for ids, names, teams in ((r.gsis_id, r.full_name, r.team),):"))
mut_live("live2: names from the roster are not looked in",
         ("        for ids, names, teams in ((r.gsis_id, r.full_name, r.team),\n                                  (F.player_id, F.name, F.team)):",
          "        for ids, names, teams in ((F.player_id, F.name, F.team),):"))
mut_live("live2: a name is looked for on every team",
         ("        found = self.by_name.get((team, norm_player(who)), set())",
          "        found = {g for (tm, nm), gs in self.by_name.items() if nm == norm_player(who) for g in gs}"))
mut_live('live2: an id is taken for a team he is not on',
         ('            if (team, got) not in self.on and not (anywhere and got in self.known):',
          '            if False:'))
mut_live("live2: an nflverse id is looked up as a name",
         ("        got = who if GSIS.match(who) else self.from_key(who)", "        got = self.from_key(who)"))
mut_live("live2: a book's id in the inputs is looked up as a name",
         ("        got = who if GSIS.match(who) else self.from_key(who)", "        got = who if GSIS.match(who) else None"))
mut_live("live2: a player with no history has no name",
         ("                name = hist.last_name(pid) if seen else names.full.get(pid, pid)", "                name = hist.last_name(pid) if seen else pid"))
mut_live("live2: a player with no history has no position",
         ("                pos = pos_of.get(pid) or (hist.last_position(pid) if seen\n                                          else names.position.get(pid))",
          "                pos = pos_of.get(pid) or (hist.last_position(pid) if seen\n                                          else None)"))
mut_live("live2: a starter who is not a quarterback is let through",
         ('                if pid == qb and pos != "QB":', '                if False:'))
mut_live("live2: last week's starter is marked, not the one named",
         ("                            team, opp, pid, name, pos, pid == qb))", "                            team, opp, pid, name, pos, pid == hist.last_starting_qb(team)))"))
mut_live("live2: a game is named home at away in the slate",
         ('                rec.append((season, week, f"{season}_{week:02d}_{away}_{home}",', '                rec.append((season, week, f"{season}_{week:02d}_{home}_{away}",'))
# -- which record a line is read on
mut_live("live2: a player with no ladder is read on the main record",
         ('    if not ladder:\n        return ""', '    if not ladder:\n        return MAIN'))
mut_live("live2: a line far below his ladder is read on its lowest rung",
         ("    if not ladder[0][1] - below <= line <= ladder[-1][1] + above:", "    if not line <= ladder[-1][1] + above:"))
mut_live("live2: a line far above his ladder is read on its highest rung",
         ("    if not ladder[0][1] - below <= line <= ladder[-1][1] + above:", "    if not ladder[0][1] - below <= line:"))
mut_live("live2: the room below his ladder is a whole gap",
         ("    below = (ladder[1][1] - ladder[0][1]) / 2 if len(ladder) > 1 else 0.5", "    below = (ladder[1][1] - ladder[0][1]) if len(ladder) > 1 else 0.5"))
mut_live("live2: the room above his ladder is a whole gap",
         ("    above = (ladder[-1][1] - ladder[-2][1]) / 2 if len(ladder) > 1 else 0.5", "    above = (ladder[-1][1] - ladder[-2][1]) if len(ladder) > 1 else 0.5"))
mut_live("live2: there is no room at all off the ends of his ladder",
         ("    if not ladder[0][1] - below <= line <= ladder[-1][1] + above:", "    if not ladder[0][1] <= line <= ladder[-1][1]:"))
mut_live("live2: a one-rung ladder has room of five points",
         ("    above = (ladder[-1][1] - ladder[-2][1]) / 2 if len(ladder) > 1 else 0.5", "    above = (ladder[-1][1] - ladder[-2][1]) / 2 if len(ladder) > 1 else 5.0"))
mut_live("live2: of two rungs equally near, the one further from his main line",
         ("    return min(ladder, key=lambda r: (abs(r[1] - line), far[r[0]]))[0]", "    return min(ladder, key=lambda r: (abs(r[1] - line), -far[r[0]]))[0]"))
mut_live("live2: every line is read on his main line",
         ("    return min(ladder, key=lambda r: (abs(r[1] - line), far[r[0]]))[0]", "    return min(ladder, key=lambda r: (far[r[0]], abs(r[1] - line)))[0]"))
mut_live("live2: two or more touchdowns is read on the anytime record",
         ('    if stat == TD_STAT and line != 0.5:\n        return "", TWO_PLUS\n', ''))
mut_live("live2: a player with no stand-in line is read anyway",
         ('    if not role[FAMILY[stat]]:\n        return "", NO_ROLE\n', ''))
mut_live("live2: every stat is judged on his touchdown role",
         ("    if not role[FAMILY[stat]]:", '    if not role["td"]:'))
mut_live("live2: an anytime touchdown is read on a ladder rung",
         ('    if stat == TD_STAT:\n        return MAIN, ""\n', ''))
mut_live("live2: a line off his ladder gives no reason",
         ('    return rung, "" if rung else OFF_LADDER', '    return rung, ""'))
# -- the run
mut_live("live2: any week's report counts as this week's",
         ('    filed = (reports[(reports["t"] == t) & reports["player_id"].isin(set(slate.player_id))]',
          '    filed = (reports[reports["player_id"].isin(set(slate.player_id))]'))
mut_live("live2: a report for other teams counts as these teams'",
         ('    filed = (reports[(reports["t"] == t) & reports["player_id"].isin(set(slate.player_id))]',
          '    filed = (reports[(reports["t"] == t)]'))
mut_live("live2: a run with no report does not say so",
         ('        notes.append(f"NO INJURY REPORT ON FILE for week {week} for anyone in "',
          '        (lambda *_: None)(f"NO INJURY REPORT ON FILE for week {week} for anyone in "'))
mut_live("live2: what the injury file has is not said",
         ('        notes.append(\n            f"Injury file for these teams: {len(filed)} listed, "',
          '        (lambda *_: None)(\n            f"Injury file for these teams: {len(filed)} listed, "'))
mut_live("live2: the injury note counts questionable players as out",
         ("""            f"{int(n.get('out', 0))} out, {int(n.get('doubtful', 0))} doubtful, \"""",
          """            f"{int(n.get('questionable', 0))} out, {int(n.get('doubtful', 0))} doubtful, \""""))
mut_live("live2: the injury note counts chances as statuses",
         ('''            f"behind the league's report; {len(said)} status"''', '''            f"behind the league's report; {len(given)} status"'''))
mut_live("live2: teams with nobody on the injury file are not named",
         ("        if bare:\n            notes.append(", "        if False:\n            notes.append("))
mut_live("live2: every team is named as having nobody on the injury file",
         ("        bare = sorted(tm for tm in playing if not (\n            set(slate.player_id[slate.team == tm]) & set(filed.player_id)))",
          "        bare = sorted(tm for tm in playing)"))
mut_live("live2: what a file had that was passed over is not noted",
         ('        for why, n in sorted(L.attrs["passed_over"].items()):', '        for why, n in []:'))
mut_live('live2: a file with no usable line is passed over in silence',
         ('            if not books:\n                notes.append(f"{game}: the odds file has no line the "\n                             f"simulator has a stat for")\n            continue',
          '            continue'))
mut_live('live2: a book asked for that the file lacks is not named',
         ('        if absent:\n',
          '        if False:\n'))
mut_live('live2: a player on both slates is priced for the home team when the book does not say',
         ('for tm in ((told,) if told else on) if tm in on]',
          'for tm in ((told,) if told else on[-1:]) if tm in on]'))
mut_live('live2: a player on both slates is priced for the away team when the book does not say',
         ('for tm in ((told,) if told else on) if tm in on]',
          'for tm in ((told,) if told else on[:1]) if tm in on]'))
mut_live('live2: a player is looked for on the away team only',
         ('                on = [tm for tm in (away, home) if (tm, pid) in at]',
          '                on = [tm for tm in (away,) if (tm, pid) in at]'))
mut_live('live2: a player with an id not on the slate is matched by name',
         ('            where.append(hits[0] if len(hits) == 1 else why)',
          '            hits = hits or [j for tm in (away, home) for j in by_name.get((tm, norm_player(player)), [])]\n            where.append(hits[0] if len(hits) == 1 else why)'))
mut_live('live2: a player is never matched by name',
         ('                hits = [j for tm in ((told,) if told else (away, home))\n',
          '                hits = [j for tm in ()\n'))
mut_live("live2: a name two slate players share picks the first",
         ("            where.append(hits[0] if len(hits) == 1 else why)", "            where.append(hits[0] if len(hits) >= 1 else why)"))
mut_live('live2: a match by name is reported as a match by id',
         ('            how.append("id" if names.from_key(key) is not None else "name")',
          '            how.append("id")'))
mut_live("live2: a player it cannot place is dropped without a word",
         ('            unmatched.append((game, player, len(g.drop_duplicates(["stat", "line"])), why))',
          '            (lambda *_: None)((game, player, len(g.drop_duplicates(["stat", "line"])), why))'))
mut_live("live2: a line posted at two books is counted twice among the unpriced",
         ('            unmatched.append((game, player, len(g.drop_duplicates(["stat", "line"])), why))',
          '            unmatched.append((game, player, len(g), why))'))
mut_live("live2: every player is given the first slate row's role",
         ("            win, role = meta[i][0], meta[i][1]", "            win, role = meta[i][0], meta[0][1]"))
mut_live("live2: every player is read on the first slate row's ladder",
         ("            win, role = meta[i][0], meta[i][1]", "            win, role = meta[0][0], meta[i][1]"))
mut_live("live2: every stat is read on his targets ladder",
         ("                                          fs.standin_lines(hist, win, stat))", '                                          fs.standin_lines(hist, win, "targets"))'))
mut_live("live2: a line with no projection is priced as nothing",
         ("                if math.isnan(expected):\n                    blank.append(stat)\n                    continue", "                if False:\n                    continue"))
mut_live("live2: a line with no projection is dropped without a word",
         ("            for stat, n in sorted(Counter(blank).items()):", "            for stat, n in []:"))
mut_live("live2: a passer who is not the starter is not told why",
         ('                    ": he is not the named starter" if FAMILY[stat] == "pass" else "")))', '                    "" if FAMILY[stat] == "pass" else "")))'))
mut_live("live2: a line counts as main only if every book has it as main",
         ('                             "main" if (h.kind == "main").any() else "ladder",', '                             "main" if (h.kind == "main").all() else "ladder",'))
mut_live("live2: the books on a line are not put together",
         ('                             rung, no_record, " ".join(sorted(set(h.book))),', '                             rung, no_record, sorted(set(h.book))[0],'))
mut_live("live2: a line is marked suspended at every book that posts it",
         ('                             " ".join(sorted(set(h.book[h.suspended]))),', '                             " ".join(sorted(set(h.book))),'))
mut_live("live2: a line is found by id only if every book gave one",
         ('                             "id" if (h.how == "id").any() else "name",', '                             "id" if (h.how == "id").all() else "name",'))
mut_live("live2: the chance beside a line is not the player's",
         ("                             s.position, s.chance, s.source, stat, float(line),", "                             s.position, 1.0, s.source, stat, float(line),"))
mut_live("live2: the reason for no record is not kept on the line",
         ("                             rung, no_record, \" \".join(sorted(set(h.book))),", "                             rung, \"\", \" \".join(sorted(set(h.book))),"))
# -- the record, and reading it
mut_live("live2: the record does not say which weeks it covers",
         ('           "first": int(run.weeks[0]), "through": int(run.weeks[-1]),', '           "first": int(run.weeks[0]), "through": int(run.weeks[0]),'))
mut_live("live2: the record carries another S21 threshold than it used",
         ('"s21_from": S21_FROM,', '"s21_from": 0.5,'))
mut_live("live2: a missing record is let through",
         ("    if not record:\n        raise Missing(f\"there is no record (sim_record.py). {rebuild}\")", "    if not record:\n        return"))
mut_live("live2: a record from other model code is let through",
         ('    if record["code"] != code_stamp() or record["s21_from"] != S21_FROM:', '    if record["s21_from"] != S21_FROM:'))
mut_live("live2: a record with another S21 threshold is let through",
         ('    if record["code"] != code_stamp() or record["s21_from"] != S21_FROM:', '    if record["code"] != code_stamp():'))
mut_live("live2: a record in another layout is let through",
         ('    if set(RECORD_KEYS) - set(record) or record["layout"] != LAYOUT:', '    if set(RECORD_KEYS) - set(record):'))
mut_live("live2: a record with a part missing is let through",
         ('    if set(RECORD_KEYS) - set(record) or record["layout"] != LAYOUT:', '    if record.get("layout") != LAYOUT:'))
mut_live("live2: the S21 caution goes by the book's main line",
         ("    return row.rung == MAIN and row.stat != TD_STAT", '    return row.kind == "main" and row.stat != TD_STAT'))
mut_live("live2: the S21 caution is given on touchdowns",
         ("    return row.rung == MAIN and row.stat != TD_STAT", "    return row.rung == MAIN"))
mut_live('live2: the S21 caution is never given on a passing touchdown',
         ('    return row.rung == MAIN and row.stat != TD_STAT',
          '    return row.rung == MAIN and row.stat not in (TD_STAT, "passing_tds")'))
mut_live("live2: the S21 caution is given only when the over is favoured",
         ("    if on_main(row) and max(row.over, row.under) >= S21_FROM:", "    if on_main(row) and row.over >= S21_FROM:"))
mut_live("live2: the reason for no record is not printed",
         ('        return f"no record: {row.no_record}"', '        return "no record"'))
mut_live("live2: a line with no record is looked up anyway",
         ('    if not row.rung:\n        return f"no record: {row.no_record}"\n', ''))
mut_live("live2: a table the record lacks is not said to be missing",
         ('        return "no record: the record has no table for this"', '        return "no record"'))
mut_live('live2: his main line and his other rungs are named the wrong way round',
         ('" on his main line" if row.rung == MAIN\n',
          '" on his main line" if row.rung != MAIN\n'))
mut_live('live2: the printout does not say what the record covers',
         ('        "The record covers players with four recent games and a role in "\n        "them, graded with last game\'s starter and nothing handed in. A "\n        "line is read on HIS OWN stand-in rung nearest it: \\"his main "\n        "line\\" is the half point above his eight-game median, not the book\'s.",\n',
          ''))
# -- the whole run
mut_live("live2 run: the week asked for does not reach the run",
         ("                         week=week, books=books, allow_no_report=allow_no_report)", "                         week=None, books=books, allow_no_report=allow_no_report)"))
mut_live("live2 run: the books asked for do not reach the run",
         ("                         week=week, books=books, allow_no_report=allow_no_report)", "                         week=week, books=None, allow_no_report=allow_no_report)"))
mut_live("live2 run: leave to run without a report does not reach the run",
         ("                         week=week, books=books, allow_no_report=allow_no_report)", "                         week=week, books=books, allow_no_report=False)"))
mut_live("live2 run: a book's name has to be typed exactly",
         ("        books = {str(b).strip().lower() for b in books} if books else None", "        books = set(books) if books else None"))
mut_live('live2 run: kickoff times are not checked',
         ('        late = check_kickoffs(\n            events, pd.Timestamp.now(tz="UTC") if now is None else now,\n            week_window(dates, wk) if isinstance(wk, int) else None,\n            asked["season"] or int(frame["season"].max()))',
          '        late = []'))
mut_live('live2 run: the time handed in is ignored for the clock',
         ('            events, pd.Timestamp.now(tz="UTC") if now is None else now,\n',
          '            events, pd.Timestamp.now(tz="UTC"),\n'))
mut_live('live2 run: with no time handed in there is no clock',
         ('            events, pd.Timestamp.now(tz="UTC") if now is None else now,\n',
          '            events, now,\n'))
mut_live("live2 run: the note about a missing kickoff time is dropped",
         ("        board.notes += late\n", ""))
mut_live("live2 run: ladders are shown unasked",
         ("        if not ladders:\n            board.lines = ", "        if False:\n            board.lines = "))
mut_live("live2 run: asking for ladders shows main lines only",
         ("        if not ladders:\n            board.lines = ", "        if True:\n            board.lines = "))
mut_live("live2 run: it does not say how many lines it priced and did not show",
         ("            if hidden:\n                board.notes.append(", "            if False:\n                board.notes.append("))
mut_live("live2 run: the count of lines not shown counts main lines",
         ('        hidden = int((board.lines.kind != "main").sum())', '        hidden = int(len(board.lines))'))
mut_live("live2 run: nothing is saved when asked",
         ("        if out:\n            try:", "        if False:\n            try:"))
mut_live("live2 run: a failure to save is not caught by name",
         ("            except OSError as e:\n                raise Missing(f\"cannot save to {out}: {e}\") from e", "            except ZeroDivisionError as e:\n                raise Missing(f\"cannot save to {out}: {e}\") from e"))
mut_live("live2 run: a fault it did not foresee is a traceback",
         ("    except Exception as e:      # noqa", "    except ZeroDivisionError as e:      # noqa"))
mut_live("live2 run: a fault it did not foresee ends with code 2",
         ('                f"a file in a shape it does not know."), 3', '                f"a file in a shape it does not know."), 2'))
# -- after the second review (2026-11-21)
mut_live('live3: an odds file that is not text is a traceback',
         ('            except (OSError, UnicodeDecodeError) as e:\n                raise Missing(f"cannot read the odds file',
          '            except OSError as e:\n                raise Missing(f"cannot read the odds file'))
mut_live('live3: a response in the wrong shape is a traceback',
         ('    except (AttributeError, TypeError) as e:\n',
          '    except ZeroDivisionError as e:\n'))
mut_live('live3: a response whose books are not books is a traceback',
         ('    except (AttributeError, TypeError) as e:\n',
          '    except TypeError as e:\n'))
mut_live('live3: a response whose markets are not a list is a traceback',
         ('    except (AttributeError, TypeError) as e:\n',
          '    except AttributeError as e:\n'))
mut_live("live3: the week is counted from last week's last game, not its Sunday",
         ('    sundays = prev[prev.dt.dayofweek == 6]',
          '    sundays = prev'))
mut_live("live3: the week is counted from last week's Monday",
         ('    sundays = prev[prev.dt.dayofweek == 6]',
          '    sundays = prev[prev.dt.dayofweek == 0]'))
mut_live('live3: the week starts a day early',
         ('WEEK_STARTS = pd.Timedelta(days=3, hours=9)',
          'WEEK_STARTS = pd.Timedelta(days=2, hours=9)'))
mut_live("live3: the week starts at midnight UTC, inside Tuesday night's game",
         ('WEEK_STARTS = pd.Timedelta(days=3, hours=9)',
          'WEEK_STARTS = pd.Timedelta(days=3, hours=0)'))
mut_live('live3: the week lasts eight days',
         ('    return start, start + pd.Timedelta(days=7)',
          '    return start, start + pd.Timedelta(days=8)'))
mut_live("live3: the window is for the week named, not the one after last week's",
         ('    prev = pd.to_datetime(dates.loc[dates["week"] == week - 1, "game_date"])',
          '    prev = pd.to_datetime(dates.loc[dates["week"] == week, "game_date"])'))
mut_live('live3: with no dates the window is a fault',
         ('    if dates is None or week <= 1:\n        return None\n    prev',
          '    if week <= 1:\n        return None\n    prev'))
mut_live('live3: with no Sunday on file last week there is still a window',
         ('    if not len(sundays):\n        return None\n',
          ''))
mut_live("live3: the week's window is not used",
         ('        elif window is not None and not window[0] <= kick < window[1]:',
          '        elif False:'))
mut_live('live3: the eight-day rule is used with a window too',
         ('        elif window is None and kick > now + pd.Timedelta(days=MAX_DAYS_AHEAD):',
          '        elif kick > now + pd.Timedelta(days=MAX_DAYS_AHEAD):'))
mut_live("live3: a game at the week's first minute is refused",
         ('not window[0] <= kick < window[1]:',
          'not window[0] < kick < window[1]:'))
mut_live("live3: a game at the next week's first minute is taken",
         ('not window[0] <= kick < window[1]:',
          'not window[0] <= kick <= window[1]:'))
mut_live("live3: the refusal names the day after the week's last",
         ('                          f"{window[1] - pd.Timedelta(days=1):%Y-%m-%d}, going "',
          '                          f"{window[1]:%Y-%m-%d}, going "'))
mut_live("live3 run: the week's dates are not used",
         ('            week_window(dates, wk) if isinstance(wk, int) else None,\n',
          '            None,\n'))
mut_live("live3 run: the window goes by the inputs' week only",
         ('        wk = week if week is not None else asked["week"]',
          '        wk = asked["week"]'))
mut_live('live3 run: the window is for the week before',
         ('            week_window(dates, wk) if isinstance(wk, int) else None,\n',
          '            week_window(dates, wk - 1) if isinstance(wk, int) else None,\n'))
mut_live('live3: when the file puts a player on two teams the first is taken',
         ('            told = next(iter(teams)) if len(teams) == 1 else None\n            if len(teams) > 1 or (told and told not in (away, home)):',
          '            told = sorted(teams)[0] if teams else None\n            if told and told not in (away, home):'))
mut_live('live3: an outcome with no id is not taken to be the player another gives an id',
         ('            if (pid is None and len(same.get(n, ())) == 1\n',
          '            if (False and len(same.get(n, ())) == 1\n'))
mut_live('live3: an outcome with no id is tied to an id though the file gives the name two ids',
         ('            if (pid is None and len(same.get(n, ())) == 1\n',
          '            if (pid is None and len(same.get(n, ())) >= 1\n'))
mut_live('live3: the team the book names is not read',
         ('            teams = puts.get(pid or norm_player(player), set())',
          '            teams = set()'))
mut_live('live3: a team outside the game is taken as nothing said',
         ('            if len(teams) > 1 or (told and told not in (away, home)):',
          '            told = told if told in (away, home) else None\n            if len(teams) > 1:'))
mut_live('live3: a player the book puts on another team is priced for the slate he is on',
         ('for tm in ((told,) if told else on) if tm in on]',
          'for tm in ((told,) if told in on else on)]'))
mut_live('live3: a player with no id is looked for on both teams though the book names one',
         ('                hits = [j for tm in ((told,) if told else (away, home))\n',
          '                hits = [j for tm in (away, home)\n'))
mut_live('live3: a player off both slates is said to be on both',
         ('which team he is on" if len(on) == 2 else',
          'which team he is on" if len(on) != 2 else'))
mut_live('live3: a player the book puts elsewhere is given the wrong reason',
         ('inputs if he is playing." if told else',
          'inputs if he is playing." if not told else'))
mut_live('live3: a slate player the roster has elsewhere is not named',
         ('        self.team = dict(zip(r.gsis_id, r.team))',
          '        self.team = {}'))
mut_live('live3: ...he is named though his chance was handed in',
         ('            and (tm, pid) not in given and (tm, pid) not in said)',
          '            and (tm, pid) not in said)'))
mut_live('live3: ...he is named though his status was handed in',
         ('            and (tm, pid) not in given and (tm, pid) not in said)',
          '            and (tm, pid) not in given)'))
mut_live('live3: a slate player the roster does not have is taken to have left',
         ('            if names.team.get(pid) not in (None, tm)',
          '            if names.team.get(pid, "?") not in (None, tm)'))
mut_live('live3: a book asked for is named as absent though the file has it',
         ('        absent = sorted(set(books or ()) - set(L.book))',
          '        absent = sorted(set(books or ()))'))
mut_live('live3: with books asked for, the no-line note is given as well',
         ('            if not books:\n                notes.append(f"{game}: the odds file has no line the "',
          '            if True:\n                notes.append(f"{game}: the odds file has no line the "'))
mut_live('live3: a passing-touchdown line is read line by line, not on his rung',
         ('    rung = nearest_rung(line, ladder)',
          '    rung = f"line {line:g}" if stat == "passing_tds" else nearest_rung(line, ladder)'))
mut_live('live3: the record keeps no table for passing touchdowns',
         ('    laddered = [s for s in ALL_STATS if s != TD_STAT]',
          '    laddered = [s for s in ALL_STATS if s not in (TD_STAT, "passing_tds")]'))
mut_live("live3: the record's layout is the old one",
         ('LAYOUT = 3\n',
          'LAYOUT = 2\n'))
mut_live('live3: a push line where neither side reaches half says there is no table',
         ('    if b is None and row.stat != TD_STAT and max(row.over, row.under) < 0.5:',
          '    if False:'))
mut_live('live3: any line with no table is put down to a push',
         ('    if b is None and row.stat != TD_STAT and max(row.over, row.under) < 0.5:',
          '    if b is None and row.stat != TD_STAT:'))
mut_live('live3: any week is taken from the inputs',
         ('    if out["week"] is not None and not 1 <= out["week"] <= 22:',
          '    if False:'))
mut_live('live3: week 0 is taken from the inputs',
         ('not 1 <= out["week"] <= 22:',
          'not 0 <= out["week"] <= 22:'))
mut_live('live3: Week 1 is refused in the inputs',
         ('not 1 <= out["week"] <= 22:',
          'not 2 <= out["week"] <= 22:'))
mut_live('live3: week 23 is taken from the inputs',
         ('not 1 <= out["week"] <= 22:',
          'not 1 <= out["week"] <= 23:'))
mut_live('live3: week 22 is refused in the inputs',
         ('not 1 <= out["week"] <= 22:',
          'not 1 <= out["week"] <= 21:'))
mut_live('live3: any position is taken for an added player',
         ('                if row.get("position") is not None and row["position"] not in ADD_AT:',
          '                if False:'))
mut_live('live3: a fullback cannot be added',
         ('ADD_AT = ("QB", "RB", "FB", "WR", "TE")',
          'ADD_AT = ("QB", "RB", "WR", "TE")'))
mut_live('live3: a kicker can be added',
         ('ADD_AT = ("QB", "RB", "FB", "WR", "TE")',
          'ADD_AT = ("QB", "RB", "FB", "WR", "TE", "K")'))
mut_live('live3: a player listed twice is taken, the last standing',
         ('                if key in into:',
          '                if False:'))
mut_live('live3: a week that is not a whole number in range is run',
         ('    if isinstance(week, bool) or not isinstance(week, int) or not 1 <= week <= 22:',
          '    if False:'))
mut_live('live3: a week of True is run as Week 1',
         ('    if isinstance(week, bool) or not isinstance(week, int) or not 1 <= week <= 22:',
          '    if not isinstance(week, int) or not 1 <= week <= 22:'))
mut_live('live3: a week and a half is run',
         ('    if isinstance(week, bool) or not isinstance(week, int) or not 1 <= week <= 22:',
          '    if isinstance(week, bool) or not 1 <= week <= 22:'))
mut_live('live3: week 0 is run',
         ('    if isinstance(week, bool) or not isinstance(week, int) or not 1 <= week <= 22:',
          '    if isinstance(week, bool) or not isinstance(week, int) or not 0 <= week <= 22:'))
mut_live('live3: any season is run',
         ('    if season != newest_season and not (season == newest_season + 1 and week == 1):',
          '    if False:'))
mut_live('live3: next season is run for any week',
         ('    if season != newest_season and not (season == newest_season + 1 and week == 1):',
          '    if season != newest_season and not (season == newest_season + 1):'))
mut_live("live3: next season's Week 1 is refused",
         ('    if season != newest_season and not (season == newest_season + 1 and week == 1):',
          '    if season != newest_season:'))
mut_live('live3: a man who left in an earlier season is still found on his old team',
         ('        F = hist.frame[hist.frame["season"] == season]',
          '        F = hist.frame'))
mut_live("live3: this season's games are not used to place a player",
         ('        for ids, names, teams in ((r.gsis_id, r.full_name, r.team),\n                                  (F.player_id, F.name, F.team)):',
          '        for ids, names, teams in ((r.gsis_id, r.full_name, r.team),):'))
mut_live('live3: the roster is not used to place a player',
         ('        for ids, names, teams in ((r.gsis_id, r.full_name, r.team),\n                                  (F.player_id, F.name, F.team)):',
          '        for ids, names, teams in ((F.player_id, F.name, F.team),):'))
mut_live('live3: the roster is not asked when the book is silent',
         ('            if len(hits) == 1 and not told:',
          '            if False:'))
mut_live('live3: the roster overrules the book',
         ('            if len(hits) == 1 and not told:',
          '            if len(hits) == 1:'))
mut_live('live3: a roster team outside this game stops him being priced',
         ('                if there in (away, home) and there != his:',
          '                if there is not None and there != his:'))
mut_live("live3: he is refused though the roster has him on the slate's team",
         ('                if there in (away, home) and there != his:',
          '                if there in (away, home):'))
# -- after the third review (2026-11-21)
mut_live('live4: a team the book names that is no team it knows is dropped',
         ('                team = TEAM_CODE.get(team, team) if isinstance(team, str) and team else None',
          '                team = TEAM_CODE.get(team) if isinstance(team, str) and team else None'))
mut_live('live4: a defence is listed as a player',
         ('                if not isinstance(who, str) or NOT_A_PLAYER.search(who.strip()):\n                    continue\n                key = oc.get',
          '                if not isinstance(who, str):\n                    continue\n                key = oc.get'))
mut_live('live4: an empty id is kept as an id',
         ('                seen[(who, key if isinstance(key, str) and key else None, team)] = None',
          '                seen[(who, key, team)] = None'))
mut_live('live4: a player on two teams in the file is said to be on a team outside the game',
         ('            if len(teams) > 1 or (told and told not in (away, home)):',
          '            if told and told not in (away, home):'))
mut_live('live4: the team a player with no id is on is looked for under his id',
         ('                puts.setdefault(person(player, key) or norm_player(player), set()).add(team)',
          '                puts.setdefault(names.from_key(key) or norm_player(player), set()).add(team)'))
mut_live('live4: a player with no id is looked for on either slate though the file names his team',
         ('                       + (f"{told}\'s slate, where the odds file has him"\n                          if told else "either slate"))',
          '                       + "either slate")'))
mut_live('live4: a game outside the season is taken',
         ('        elif season is not None and not (',
          '        elif False and not ('))
mut_live('live4: the season starts in September',
         ('pd.Timestamp(f"{season}-08-01", tz="UTC") <= kick',
          'pd.Timestamp(f"{season}-09-01", tz="UTC") <= kick'))
mut_live('live4: the season runs into March',
         ('< pd.Timestamp(f"{season + 1}-03-01", tz="UTC")):',
          '<= pd.Timestamp(f"{season + 1}-03-01", tz="UTC")):'))
mut_live('live4: the season ends with its own year',
         ('< pd.Timestamp(f"{season + 1}-03-01", tz="UTC")):',
          '< pd.Timestamp(f"{season}-12-31", tz="UTC")):'))
mut_live('live4: the season is asked after the eight-day rule',
         ('        elif season is not None and not (',
          '        elif window is not None and season is not None and not ('))
mut_live('live4: it does not say the eight-day rule was all it had',
         ('    notes = [] if window is not None else [NO_WINDOW]',
          '    notes = []'))
mut_live('live4: it says the eight-day rule was used though there was a window',
         ('    notes = [] if window is not None else [NO_WINDOW]',
          '    notes = [NO_WINDOW]'))
mut_live('live4 run: the season is not handed to the kickoff check',
         ('            asked["season"] or int(frame["season"].max()))',
          '            None)'))
mut_live('live4: a player can be added only to a team he is already on',
         ('    add = [(tm, names.find(tm, who, anywhere=True), pos)',
          '    add = [(tm, names.find(tm, who), pos)'))
mut_live('live4: a player added twice is taken',
         ('    if len(added) != len(add):',
          '    if False:'))
mut_live('live4: a starter may be anyone in the league',
         ('            if (tm, names.find(tm, who, anywhere=True)) in added:',
          '            if True:'))
mut_live('live4: a starter just added to the team is refused',
         ('            if (tm, names.find(tm, who, anywhere=True)) in added:',
          '            if False:'))
mut_live('live4: an id from another team is taken though he is not being added',
         ('            if (team, got) not in self.on and not (anywhere and got in self.known):',
          '            if (team, got) not in self.on and not (got in self.known):'))
mut_live('live4: an id is taken for an added player nobody has heard of',
         ('            if (team, got) not in self.on and not (anywhere and got in self.known):',
          '            if (team, got) not in self.on and not anywhere:'))
mut_live('live4: a name from another team is taken though he is not being added',
         ('        if anywhere and not found:',
          '        if not found:'))
mut_live("live4: an added player's name is looked for in the league before his team",
         ('        if anywhere and not found:',
          '        if anywhere:'))
mut_live('live4: a status for a player on two slates is taken for both',
         ('        if also:\n            raise Missing(\n                f"a status was handed in for',
          '        if False:\n            raise Missing(\n                f"a status was handed in for'))
mut_live('live4: a status is refused for a player on one slate',
         ('        also = sorted(set(slate.team[slate.player_id == pid]) - {tm})',
          '        also = sorted(set(slate.team[slate.player_id == pid]))'))
# -- after the re-check of the third review (2026-11-21)
mut_live('live5: a bare name is tied to an id though a namesake is in the league',
         ('                    and names.any_name.get(n, set()) <= same[n]):',
          '                    and True):'))
mut_live('live5: a bare name is priced though a namesake is on these teams',
         ('                if len(hits) == 1 and {g for tm in ((told,) if told else (away, home))',
          '                if False and {g for tm in ((told,) if told else (away, home))'))
mut_live("live5: a namesake is looked for on the player's own team only",
         ('                if len(hits) == 1 and {g for tm in ((told,) if told else (away, home))',
          '                if len(hits) == 1 and {g for tm in (slate.team.iloc[hits[0]],)'))
mut_live('live5: a namesake on the other team stands in the way though the file names the team',
         ('                if len(hits) == 1 and {g for tm in ((told,) if told else (away, home))',
          '                if len(hits) == 1 and {g for tm in (away, home)'))
mut_live('live5: a player is his own namesake',
         ('                                       } - {slate.player_id.iloc[hits[0]]}:',
          '                                       }:'))


def run_one(i: int):
    name, pairs, target = M[i]
    s = SRC[target]
    for old, new in pairs:
        if s.count(old) != 1:
            return i, name, "BAD REVERT", f"{s.count(old)} matches for {old[:50]!r}"
        s = s.replace(old, new)
    if CHECK_ONLY:
        return i, name, "applies", ""
    d = pathlib.Path(tempfile.mkdtemp(prefix="sim_revert_"))
    try:
        for f in REPO.glob("*.py"):
            if f.name not in (target, "test_sim.py"):
                os.symlink(f, d / f.name)
        (d / target).write_text(s)
        (d / "test_sim.py").write_text(TEST)      # a COPY: see the docstring
        r = subprocess.run([sys.executable, "test_sim.py"], cwd=d,
                           capture_output=True, text=True, timeout=900)
        lines = r.stdout.strip().splitlines()
        if "checks run" not in r.stdout:
            return i, name, "NO SUMMARY", (r.stderr.strip().splitlines()
                                           or ["?"])[-1][:150]
        if lines[-1].strip() == "ALL PASS":
            return i, name, "NOT CAUGHT", ""
        fails = [ln.strip()[6:70] for ln in lines if ln.startswith("  FAIL")]
        return i, name, "caught", f"{len(fails)} failed: " + " | ".join(fails[:2])
    finally:
        shutil.rmtree(d, ignore_errors=True)


CHECK_ONLY = False
SHOW = False

#: `--fast`. The newest file's sections are the last in the suite, and
#: nothing before them imports it. So the suite's earlier part is run ONCE,
#: unbroken, and each revert of that file runs only the rest, in a child
#: process forked from that point with the edited file first on its path.
FAST_TARGET = "ff_sim_live.py"
FAST_CUT = "# S28 — the live run (ff_sim_live.py)"


def _verdict(i, name, text, err=""):
    lines = text.strip().splitlines()
    if "checks run" not in text:
        return i, name, "NO SUMMARY", (err or (lines or ["?"])[-1])[:150]
    if lines[-1].strip() == "ALL PASS":
        return i, name, "NOT CAUGHT", ""
    fails = [ln.strip()[6:70] for ln in lines if ln.startswith("  FAIL")]
    return i, name, "caught", f"{len(fails)} failed: " + " | ".join(fails[:2])


def fast_run(ids, report):
    """Run the reverts `ids` (all of `FAST_TARGET`) the fast way; `report`
    is called with each result as it comes. Refuses, by raising, unless the
    earlier part of the suite passes whole and has not imported the file:
    that is what makes a child's verdict the same as a full run's."""
    import atexit
    import contextlib
    import io
    import time
    import traceback
    cut = TEST.index(FAST_CUT)
    head = TEST[:cut]
    tail = "\n" * head.count("\n") + TEST[cut:]       # keep the line numbers
    g = {"__name__": "__main__", "__file__": str(REPO / "test_sim.py")}
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        exec(compile(head, "test_sim.py", "exec"), g)
    atexit.unregister(g["_summary"])
    module = FAST_TARGET[:-3]
    if g["fails"] or module in sys.modules or not g["ran"]:
        raise RuntimeError(
            f"--fast cannot be used: before the cut {len(g['fails'])} checks "
            f"failed of {len(g['ran'])}, and {module} "
            f"{'WAS' if module in sys.modules else 'was not'} imported")
    code = compile(tail, "test_sim.py", "exec")
    queue, running, res = list(ids), {}, []

    def start(i):
        name, pairs, target = M[i]
        s = SRC[target]
        for old, new in pairs:
            if s.count(old) != 1:
                return (i, name, "BAD REVERT", f"{s.count(old)} matches for {old[:50]!r}")
            s = s.replace(old, new)
        d = pathlib.Path(tempfile.mkdtemp(prefix="sim_revert_"))
        for f in REPO.glob("*.py"):
            if f.name not in (target, "test_sim.py"):
                os.symlink(f, d / f.name)
        (d / target).write_text(s)
        sys.stdout.flush()
        pid = os.fork()
        if pid == 0:
            try:
                out = open(d / "_out.txt", "w")
                os.dup2(out.fileno(), 1)
                os.dup2(out.fileno(), 2)
                sys.stdout = sys.stderr = out
                sys.path.insert(0, str(d))
                os.chdir(d)
                try:
                    exec(code, g)
                except SystemExit:
                    pass
                except BaseException:               # noqa: BLE001
                    traceback.print_exc()
                    g["_summary"]()
                out.flush()
            finally:
                os._exit(0)
        running[pid] = (i, name, d, time.time())
        return None

    while queue or running:
        while queue and len(running) < (os.cpu_count() or 2):
            bad = start(queue.pop(0))
            if bad:
                res.append(bad)
                report(bad)
        for pid, (i, name, d, t0) in list(running.items()):
            done, _ = os.waitpid(pid, os.WNOHANG)
            if not done and time.time() - t0 > 900:
                os.kill(pid, 9)
                os.waitpid(pid, 0)
                r = (i, name, "NO SUMMARY", "timed out after 900 s")
            elif not done:
                continue
            else:
                r = _verdict(i, name, (d / "_out.txt").read_text())
            del running[pid]
            shutil.rmtree(d, ignore_errors=True)
            res.append(r)
            report(r)
        time.sleep(0.1)
    return res


def main() -> int:
    global CHECK_ONLY, SHOW
    args = [a for a in sys.argv[1:]]
    CHECK_ONLY = "--check" in args
    SHOW = "--show" in args
    fast = "--fast" in args and not CHECK_ONLY
    only = [int(a) for a in args if a.isdigit()] or list(range(len(M)))
    # The controls run with EVERY pass, however few reverts were asked for.
    # Without them a broken environment, where the unbroken suite fails
    # too, reads as "caught".
    only = sorted(set(only) | set(CONTROLS))
    res = []

    def report(r):
        if SHOW or (r[2] not in ("caught", "applies") and r[1] not in NULLS):
            print(f"[{r[0]:3d}] {r[2]:11s} {r[1]}  {r[3]}", flush=True)

    quick = [i for i in only if fast and M[i][2] == FAST_TARGET]
    with cf.ThreadPoolExecutor(max_workers=os.cpu_count() or 2) as ex:
        for r in ex.map(run_one, [i for i in only if i not in quick]):
            res.append(r)
            report(r)
    if quick:
        res += fast_run(quick, report)
    # The unbroken suite once more, AFTER everything else: if the machine
    # went wrong part-way (a full disk, a dead cache), every revert after
    # that point "failed" for that reason and not because it was caught.
    last = None if CHECK_ONLY else run_one(0)
    bad = [r for r in res if r[2] == "BAD REVERT"]
    if CHECK_ONLY:
        print(f"{len(res)} entries ({len(CONTROLS)} of them controls), "
              f"{len(res) - len(bad)} apply cleanly, {len(bad)} do not")
        return 1 if bad else 0
    real = [r for r in res if not r[1].startswith("CONTROL")]
    caught = sum(1 for r in real if r[2] == "caught")
    missed = [r for r in real if r[2] != "caught"]
    ctl = {r[1]: r[2] for r in res if r[1].startswith("CONTROL")}
    print(f"\n{len(real)} reverts: {caught} caught, {len(missed)} not")
    ok = (all(ctl.get(n) == "NOT CAUGHT" for n in NULLS)
          and all(ctl.get(n) == "caught" for n in BROKENS)
          and last is not None and last[2] == "NOT CAUGHT")
    ctl["the unbroken suite again, at the end"] = last[2] if last else None
    print("runner controls:", "OK" if ok
          else f"FAILED {ctl} — the unbroken suite does not pass here, or a "
               f"broken one does. NOTHING ABOVE MEANS ANYTHING.")
    return 0 if ok and not missed else 1


if __name__ == "__main__":
    sys.exit(main())
