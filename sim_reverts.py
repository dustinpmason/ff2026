#!/usr/bin/env python3
"""S1. Break every behaviour in `ff_sim.py` and see that `test_sim.py` notices.

    python3 sim_reverts.py            # all of them; about 30 minutes on 2 cores
    python3 sim_reverts.py --check    # only confirm each revert still applies
    python3 sim_reverts.py 0 1 17     # just these, by number

SIM-HANDOFF.md, "Before saying done", item 1: "Break every new check. Remove
the behaviour and confirm a check fails. A crash counts; a pass does not."
This is that, kept as a script so it can be run again after any change
instead of being claimed once.

How it works. Each entry below is one small edit to `ff_sim.py` that removes
or reverses one behaviour. For each, a temporary directory gets the edited
`ff_sim.py`, a COPY of `test_sim.py`, and links to every other module; the
suite is run there and its own last line is read. "ALL PASS" means the
revert was NOT CAUGHT. Anything else is caught.

The suite is copied, not linked, on purpose: Python puts a script's REAL
directory on its path, so a linked `test_sim.py` imports the real, unbroken
`ff_sim.py` and every revert reads ALL PASS. The first run of this did
exactly that and reported 0 of 148 caught.

Two controls run with EVERY pass, including a pass of a few numbered
reverts, and a pass that fails either proves nothing: an edit that changes
no behaviour must read NOT CAUGHT (so the unbroken suite passes here), and
an edit that breaks the week key must be caught.

An entry whose text no longer matches `ff_sim.py` exactly once is reported
as BAD REVERT. That is a failure of this file, to be fixed here; it is
never to be read as "caught".

LAST FULL RUN — 2026-11-20, 2 cores: 257 reverts, 257 caught, 0 not;
runner controls OK. It was run in four blocks of numbered reverts (each
block runs the controls). After the third block one fixture in
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
SRC = (REPO / "ff_sim.py").read_text()
TEST = (REPO / "test_sim.py").read_text()

NULL = "CONTROL: nothing changed (must read NOT CAUGHT)"
BROKEN = "CONTROL: week key broken (must be caught)"

M: list = []


def mut(name: str, *pairs) -> None:
    M.append((name, pairs))


# ---- controls on this runner itself
mut(NULL, ("def tkey(season: int, week: int) -> int:",
           "def tkey(season: int,  week: int) -> int:"))
mut(BROKEN, ("    return int(season) * 100 + int(week)",
             "    return int(season) * 100 + int(week) + 1"))

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


def run_one(i: int):
    name, pairs = M[i]
    s = SRC
    for old, new in pairs:
        if s.count(old) != 1:
            return i, name, "BAD REVERT", f"{s.count(old)} matches for {old[:50]!r}"
        s = s.replace(old, new)
    if CHECK_ONLY:
        return i, name, "applies", ""
    d = pathlib.Path(tempfile.mkdtemp(prefix="sim_revert_"))
    try:
        for f in REPO.glob("*.py"):
            if f.name not in ("ff_sim.py", "test_sim.py"):
                os.symlink(f, d / f.name)
        (d / "ff_sim.py").write_text(s)
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


def main() -> int:
    global CHECK_ONLY
    args = [a for a in sys.argv[1:]]
    CHECK_ONLY = "--check" in args
    only = [int(a) for a in args if a.isdigit()] or list(range(len(M)))
    # The two controls run with EVERY pass, however few reverts were asked
    # for. Without them a broken environment, where the unbroken suite
    # fails too, reads as "caught".
    only = sorted(set(only) | {0, 1})
    res = []
    with cf.ThreadPoolExecutor(max_workers=os.cpu_count() or 2) as ex:
        for r in ex.map(run_one, only):
            res.append(r)
            if r[2] not in ("caught", "applies") and r[1] != NULL:
                print(f"[{r[0]:3d}] {r[2]:11s} {r[1]}  {r[3]}", flush=True)
    # The unbroken suite once more, AFTER everything else: if the machine
    # went wrong part-way (a full disk, a dead cache), every revert after
    # that point "failed" for that reason and not because it was caught.
    last = None if CHECK_ONLY else run_one(0)
    bad = [r for r in res if r[2] == "BAD REVERT"]
    if CHECK_ONLY:
        print(f"{len(res)} reverts, {len(res) - len(bad)} apply cleanly, "
              f"{len(bad)} do not")
        return 1 if bad else 0
    real = [r for r in res if not r[1].startswith("CONTROL")]
    caught = sum(1 for r in real if r[2] == "caught")
    missed = [r for r in real if r[2] != "caught"]
    ctl = {r[1]: r[2] for r in res if r[1].startswith("CONTROL")}
    print(f"\n{len(real)} reverts: {caught} caught, {len(missed)} not")
    ok = (ctl.get(NULL) == "NOT CAUGHT" and ctl.get(BROKEN) == "caught"
          and last is not None and last[2] == "NOT CAUGHT")
    ctl["the unbroken suite again, at the end"] = last[2] if last else None
    print("runner controls:", "OK" if ok
          else f"FAILED {ctl} — the unbroken suite does not pass here, or a "
               f"broken one does. NOTHING ABOVE MEANS ANYTHING.")
    return 0 if ok and not missed else 1


if __name__ == "__main__":
    sys.exit(main())
