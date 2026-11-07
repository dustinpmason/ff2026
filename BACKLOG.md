# Fantasy Football + NFL Props Copilot — Backlog

Open work. Items move out of here when built and verified.

---

# MASTER BUILD ORDER  *(supersedes the per-section tables below)*

## Tier 0 — before Sunday · COMPLETE (2026-10-30)

All shipped and covered by `test_regression.py` (37 checks, all passing).

| # | Item | Status | Verified by |
|---|---|---|---|
| **B1** | Name normalization + stop silent substitution | DONE | 6 of 7 mismatches resolve; `De'Zhaun Stribling` surfaces as unresolved; "Show me those TD's" corrected 113.8 → 125.4; P(elim) 2.59% → 3.94% |
| **B2** | `best_lineup` must validate every slot | DONE | Raises naming the short position; `rank()` sorts NaN last |
| **E1** | Byes & injuries in the guillotine sim | DONE | Wk9 byes (PIT/TEN) → P(elim) 3.70% → 2.71%; excluded list reports 6 rostered names, not 100; Ilhan's Brother flagged short at RB |
| **P2** | `suspended_at` / `pregame_only` / `max_age` | DONE | `screen_quotes()` — 3-book suspension raises scratch flag; `pregame_only` dropped in-play; stale quotes dropped at 120s live / 900s pregame |
| **P3** | `shin` de-vig for longshots | DONE | `devig(..., "auto")` switches below 25% implied; +450 leg 17.50% → 16.23%; `Edge.devig_method` echoes which model ran |
| **B4** | Reject invalid `fair_over` | DONE | Rejects 0.0, 1.0, 1.5, −0.1 |
| **B5** | `enumerate_lineups` fails silently | DONE | Raises naming the slot counts |
| **B6** | *Found during Tier 0:* `add_shares()` not idempotent | DONE | Second call hit `KeyError('_team_carries')` via pandas `_x`/`_y` suffixing — broke any caller who pre-computed shares before `role_trend`. Now drops its own derived columns first. |

**Next: P1** (relabel model output), then Tier 2 (F2 backtest → P0 boost optimizer → F1 market-implied projections).

## Tier 1 — before the first bet is placed

| # | Item | Status | Notes |
|---|---|---|---|
| **E2** | Bet log (price taken, book, stake, ref) | DONE 2026-10-30 | `ff_betlog.py`. Durable copy in Drive folder `ff-betlog` — the sandbox is destroyed between conversations, so `~/ff-data` would not have survived either. One file per session, append-only by construction (Drive's `update_file` changes metadata only, so there is no content append). |
| **P6** | Log engine recommendations incl. PASS | DONE 2026-10-30 | `log_edge()` / `rec_summary()`. Reports per-tier hit rate, calibration buckets, and PASS hit rate separately from bets placed. |
| **B7** | *Found during E2:* `grade_rec` double-counted | DONE 2026-10-30 | Wrote both a `rec_grade` audit copy and a superseding `rec`, so `rec_summary` reported 10 verdicts for 5 recommendations and doubled every tier count. Now one record; all readers go through `live_recs()`. |
| **P1** | Relabel model output in betting context | DONE 2026-10-30 | `boost_verdict()` / `boost_leg_report()` — CLEAR/CAUTION/VETO, no stake sizing, reports the number as a **gap** not an "edge". |

### Found by the first deployment test (2026-10-30)

| # | Item | Status | Notes |
|---|---|---|---|
| **B8** | `DATA AS OF` used `week.max()` with no completeness guard | DONE | Claimed the season was complete through Week 8 when Week 8 held 73 rows from 2 teams (the Thursday game). Mislabeled every number built on data that actually ran through Week 7. `bye_weeks()` and `team_byes()` already guarded on this; the header line — the one claim that travels with every other number — did not. Guard is now `ff_data.MIN_TEAMS_COMPLETE_WEEK`, shared by all three, and the partial week is named explicitly. |
| **B9** | `screen_quotes()` passed price-less quotes as usable | DONE | Bovada's one-sided anytime-TD market arrived with `over=None, under=None`, passed the screen, and killed `prop_edge` with a `TypeError` inside `american_to_prob` — the exact failure the screen exists to prevent. Now drops price-less quotes, flags one-sided books in `QuoteScreen.one_sided`, and `prop_edge` raises a ValueError naming the cause. |
| **B10** | The 0.25 longshot gate on Shin de-vig | DONE | Removed, not raised. Shin is identical to multiplicative at even money and strictly better-founded away from it, so no price favours multiplicative. The gate also discarded most of the correction where it mattered (−1.02 pts at +245, −1.04 at +270 vs −1.19 at +400, all short-priced TD legs that fill a 3-leg boost) and was discontinuous: 24.9% and 25.1% implied got answers 1.3 pts apart. Shin is now the default everywhere. |
| **B11** | `Edge.devig_method` lied on the recommended path | DONE | Passing `fair_over` set it to `"n/a (external fair line)"`, so it could never report shin on the path the instructions mandate. Now reports `"upstream (…)"` or echoes a caller-supplied label. |
| **B12** | Regression check for usage trends was near-unfalsifiable | DONE | `len(seen) >= 1` passed if any one of five players returned any verdict, `UNKNOWN` included — one run had Rashee Rice come back UNKNOWN and it still passed. Replaced with synthetic players whose STABLE / COLLAPSED / EXPANDED / GAME_SCRIPT / UNKNOWN answers are known by construction. |
| **D1** | Doc: Drive pull query returned the folder | DONE | `title contains 'ff-betlog-'` matches token prefixes, not substrings, so it returned the `ff-betlog` folder. Use `parentId = '<folder id>'`. Also documented that Drive's trash is eventually consistent — one post-delete search is not proof of cleanup. |
| **D2** | Doc: `Edge.report()` does not exist | DONE | It is `ff_props.edge_report(edge, label)`. |
| **D3** | Doc: check count was wrong | DONE | I reported 61 from a `grep -c PASS` that matched the `ALL PASS` summary line. The real count was 60, nothing was missing, and the test session spent a `git fetch --deepen` chasing a check that never existed. Now 89, reconciled against `grep -c 'chk('`. |
| **P7** | ~~`get_event_ev` anchor chain fails on `player_anytime_td`~~ — **WRONG DIAGNOSIS, corrected** | DONE 2026-10-30 | The chain is fine. The second deployment test isolated the variable: default chain with no book filter returns **24 lines**, all `fair_source: "kalshi"`. The `bookmakers` filter silently empties the response. I had written the first test's unverified conclusion into the instructions as fact. `lines: []` now documented as three-way ambiguous (no anchor / nothing cleared `min_ev_pct` / your books don't quote it) with a diagnosis order. |
| **P8** | anytime-TD is available at his books but **YES-only** | **CORRECTED 2026-10-30, does NOT block P0** | I escalated this to "blocks P0" on two test reports without checking — the same failure as P7. Measured directly: `get_market_coverage` shows `player_anytime_td` at **13/13 events for draftkings, fanduel AND betmgm**, and a direct `get_odds` pull on DEN@KC (event 53172) returns 30 DraftKings outcomes, `line_type: "main"`, `suspended_at: null`. "None of your books" was wrong. What IS right: every outcome carries `side: null` with no "No" counterpart, so the market cannot be de-vigged from the book's own price and **requires an external fair anchor** (`get_event_ev`). That is a real constraint on how TD legs are priced, not a reason they can't be used. Caveat: books post props at different times, so availability depends on when you look — the earlier session may have checked before DK posted. Treat availability as a query-time check, not a fixed fact. |

### Found by the seventh deployment test (2026-11-02)

| # | Item | Status | Notes |
|---|---|---|---|
| **B28** | An unrecognised outcome label was silently priced as the OVER | DONE | `flatten_odds` branched `if label in UNDER_NAMES … else over`, so any label that was neither a known Over nor Under name became the Over with no error. **The B24 signature inside the adapter written to fix B24** — "a plausible number rather than an error". Verified synthetically: `{"name": "Mystery Label", "price": -250}` returned `over: -250`. Now an odd label on a market that carries a LINE is recorded in `unknown_labels`, raises a `label_warning`, and `screen_quotes` drops the quote. Odd labels on one-sided boards (a player name, an N+ rung, both `point: None`) remain legitimate. Two outcomes claiming the same side now raise. |
| **B29** | `player_id` was dropped | DONE | After three name-matching bugs this project's rule is never to join player data on a name — and the adapter discarded the id that makes that possible. Carried now, `None` where PropLine has none (DK's anytime-TD board for some entries and D/ST). |
| **B30** | `payout_multiplier` was dropped | DONE | A DFS leg at 1.5x boost or 0.75x discount was indistinguishable from a standard pick. Carried. |
| **B31** | `rung` held a player name on anytime-TD | DONE | "Ameer Abdullah" was written into a field meaning a threshold. Player names now go to `outcome_label`; `rung` only holds an actual N+ rung. |
| **B32** | The threshold model claimed edges on binary low-event stats | DONE | Live: Rome Odunze at 1.0% against a 25.2% Pinnacle fair line on **0-for-7** — a 24-point "gap" from a stat that is 0 or 1 per week with almost no events. `boost_verdict` now returns CAUTION with "MODEL ABSTAINS" naming the hit count. **Deliberately not VETO**: the model being unable to assess a leg is not the leg being broken, and vetoing would remove TD legs — a market actively in use — for the wrong reason. |
| **D10** | Doc: "the `bookmakers` filter silently empties the response" was overstated | DONE | On `player_pass_yds`, filtering to his three books at `min_ev_pct=-100` returned 4 lines; an earlier `[]` there was simply nothing clearing the bar. The claim holds for `player_anytime_td` (verified twice at `min_ev_pct=-100`) and was wrongly generalised — **the third unverified causal claim to reach the instructions**, after P7 and P8. |
| **D11** | Doc: coverage figures stated without the `days` window | DONE | `days=5` on a Monday covers 2 events; the same call on a Friday covered 13. "13/13" is meaningless without the window; reaching Sunday early in the week needs `days=7`. |
| **D12** | Doc: `log_bet()` returns `id`, not `bet_id` | DONE | The instructions' idiom read `None`. |

### Found by proceeding mid-week (2026-11-02)

| # | Item | Status | Notes |
|---|---|---|---|
| **B27** | The newest week was called complete, and its unplayed teams were called byes | DONE | Monday morning of Week 8: 26 teams had rows, clearing the threshold of 20, so `data_status` reported "complete through Week 8" while Chicago and Seattle had not played Monday night. Both had played every other week, so Week 8 was their only gap and **`team_byes()` assigned them a bye in Week 8** — a wrong value, not a silent omission, on a week they were playing. Jaxon Smith-Njigba (SEA) and Luther Burden III (CHI) were both in the live best lineup, so a derived-bye lookup would have excluded two starters. A team count cannot distinguish 26-of-28-with-MNF-pending from 26-complete-with-six-byes. New rule in `ff_data.complete_weeks()`: **the highest week present is in progress** unless a connector `current_week` says otherwise, since data arrives incrementally and the newest week is always the likeliest to be partial. `data_status` now also names the teams with no rows and says they may be byes *or* unplayed. Conservative cost: a genuinely finished week reads as in-progress until the next week's first game lands, or until `current_week` is passed. |
| **D9** | A regression check re-implemented the logic it tested | DONE | Section 15 recomputed "last complete week" as "every week clearing MIN_TEAMS", which is exactly the assumption B27 corrected — so it failed the moment the fix landed. It now calls `complete_weeks()`. A check that re-implements its subject will always drift away from it. |

### Found by the sixth deployment test (2026-10-31)

| # | Item | Status | Notes |
|---|---|---|---|
| **B24** | `screen_quotes` read an Under price as an Over price | DONE | `"price"` was in `PRICE_KEYS_OVER` with no name check, so a native `get_odds` outcome row `{"name":"Under","price":-113}` returned `(-113, None)` — **the Under's price reported as the Over's** — and a plainly two-sided market came back `one_sided`. Same swap as B13, one layer upstream, in the screen that exists to stop bad prices reaching `prop_edge`, arriving as a plausible number rather than an error. `_prices` now reads `name` first. **All 135 existing checks were blind to it** because every fixture used the pre-flattened shape; section 23 now tests the native one. |
| **B25** | No adapter existed between `get_odds` and the screen | DONE | `get_odds` returns one row per outcome; the screen wants both sides on one dict; nothing bridged them, and the instructions just said to run the quotes through the screen. Added `flatten_odds(resp, line_type=)` — pairs Over/Under per (book, player, line) and carries `suspended_at`, `pregame_only` and `last_update`. Milestone rungs and anytime-TD come back one-sided, as they genuinely are. |
| **B26** | `one_sided` only checked the missing *under* | DONE | An Over-only row was flagged; an Under-only row passed unflagged. Either side missing now counts. |
| **P10** | `get_event_ev`'s default de-vig silently becomes `fair_over` | DONE (reporting) | Its default is multiplicative, and the engine cannot see upstream. Harmless at even money — where shin and multiplicative agree, which is exactly why the trap is invisible in testing — and live on every other line. `Edge.devig_method` now reads `UNKNOWN — get_event_ev defaults to MULTIPLICATIVE unless you passed devig='shin'` rather than the passive "upstream". Instructions now require passing `devig="shin"` and the matching label. |
| **D8** | Doc: the fair anchor is per-LINE, not per-book | DONE | DraftKings' Mahomes 222.5 anchored on Bovada while Pinnacle sat at 223.5. Read `fair_source` off the line being priced; calling it "Pinnacle's fair line" would have been false. |
| **U1** | Project instructions field | RESOLVED | The sixth test reported the bootstrap came from the project instructions, section "FIRST ACTION OF EVERY CONVERSATION", with nothing recovered from elsewhere. |

### Found by the fifth deployment test (2026-10-31)

| # | Item | Status | Notes |
|---|---|---|---|
| **B21** | `test_regression.py` could not complete from a clean clone | DONE | Section 22 loaded `guillotine_rosters.json`, which was never committed and is not gitignored — so the suite died with `FileNotFoundError` on every clean bootstrap, and had been broken that way since the B19 check landed. Replaced with a **synthetic league built from pool names**, including one roster deliberately short at RB. A regression test must not depend on live roster data: it changes weekly, and this check needs a short roster to exist at all. |
| **B22** | The suite died *before* printing its count | DONE | The crash aborted the run and never reached the summary, so the one number sessions are told to quote did not exist — and "no count this run" is useless for deciding whether anything regressed. A `sys.excepthook` + `atexit` summary now always prints: partial count, the section that died, and "anything later is UNVERIFIED", exiting non-zero. Verified by injecting the original failure: output is `121 checks run … CRASHED in section '22. …'`. |
| **B23** | The B19 A/B was unexercisable on live data | DONE (same fix as B21) | On the live Week 9 slate no roster was short, so `fill_replacement` True and False were the same computation and all four runs agreed within noise — the check could neither confirm the fix nor catch its regression. The synthetic fixture guarantees a short roster, and the modes now separate by ~38 points (131.4 vs 93.6) rather than sitting inside Monte Carlo noise. |
| **D7** | Test session asserted player teams from recall, not data | DOCUMENTED | Reported Dowdle as Carolina (so not a Week 9 bye) and Okonkwo as the TEN bye player. nflverse has Dowdle with four 2026 games for PIT; `get_nfl_depth_charts` confirms Dowdle PIT and Okonkwo WAS as of 2026-10-31. Both backwards, and finding 4 was built on it. Instructions now require sourcing a player's team from `build_meta()` or the connector and saying which. Note the "no short roster" observation may still be true for an unrelated reason — rosters move, and waiver adds since the cached pull would legitimately change it. |
| **U1** | **Project instructions field contains a session report, not instructions** | **NEEDS DUSTIN** | The project's custom-instructions field currently holds a previous session's output — the "Bootstrap succeeded… 121 checks run… Failure list" narrative. There is no bootstrap command or repo URL in it, so a fresh session cannot start from the project at all; this one recovered the bootstrap from elsewhere. Worse, that text reads as a completed run with specific figures, which invites a session to report those figures instead of measuring. Re-paste the contents of PROJECT-INSTRUCTIONS.md into the instructions field. |

### Found by the fourth deployment test (2026-10-30)

| # | Item | Status | Notes |
|---|---|---|---|
| **B19** | `fill_replacement=False` silently kept filling | DONE | `add_replacement_level()` mutates the pool in place, and the padding was gated on whether the pool *contained* replacement keys rather than on the flag. So once any `True` run had touched a pool, a later `False` run kept padding — order-dependent, invisible in the report, and it broke precisely the A/B comparison the flag exists for. The flag is now passed down to `best_lineup(fill=...)` and is authoritative regardless of pool state. Verified by alternating True/False four times on one shared pool. |
| **B20** | Simulation noise was not reported, and I quoted inside it | DONE | `Result.se()` gives the binomial standard error on P(elim), `sims_needed(resolve)` says what sim count a given resolution requires, and the report prints the error bar plus a warning when the sim count cannot resolve small differences. **This corrects a number of mine:** I reported the replacement-fill correction as "2.71% → 3.21%, +18% relative" from a single pair of 20,000-sim runs. At that count 1 se is ~0.12 pts, so a 0.28 pt effect resolves to barely 2 se. The 80,000-sim figure is **2.871% → 3.155%, +0.28 pts, +9.9% relative** — I overstated the effect by roughly double, from noise, while criticizing exactly this kind of claim. |

### Found by the third deployment test (2026-10-30)

| # | Item | Status | Notes |
|---|---|---|---|
| **B17** | Drive text upload corrupted the first real payload | DONE — **prevented**, not just detected | B16 caught it live: a note containing an em dash stored locally as `\u2014` (6 chars) arrived in Drive as the raw 3-byte character, 727 → 722 chars, checksums differing, records parsing identically *by luck*. Now `upload_payload_b64()` + `base64Content`: pure `[A-Za-z0-9+/=]`, no escape sequences, so the failure mode cannot occur. **Verified against live Drive** with an em dash, accented Latin and CJK in one payload — `fileSize` 719 matched local exactly and the round trip is byte-identical. |
| **B18** | Short rosters understated opponents, biasing risk DOWNWARD | DONE | An unfillable slot scored as nothing, which in a survival sim makes that opponent likelier to post the low score — so own elimination risk read *lower* than it is. `add_replacement_level()` derives a per-position replacement **distribution** (not a mean) from the tier just past the startable boundary, sized to the actual league. Measured: Ilhan's Brother 114.5 → 124.6 proj, P(elim) **2.71% → 3.21%** (+18% relative), all of it previously hidden in the flattering direction. `run(fill_replacement=False)` restores the old behaviour. |
| **P9** | `get_event_ev` prices none of DK/FD/BetMGM on `player_anytime_td` | DOCUMENTED · workaround in place | Confirmed with `min_ev_pct=-100`: any `bookmakers` filter to his three books returns `[]`, unfiltered returns 32 lines priced only at betrivers/kalshi/hardrock/novig/prophetx/pinnacle — while `get_odds` returns 30 live DraftKings outcomes for the same event. TD legs cannot be EV-screened at his books. Workaround is the already-documented path: his price from `get_odds`, fair prob from an unfiltered `get_event_ev` anchor, passed as `fair_over`. Never read a filtered `[]` as "no edge". |
| **D5** | Doc: "Pinnacle carries no anytime-TD market" — wrong | DONE | Pinnacle has it at 13/13 events, 100 markets, and anchors 8 of 32 lines on DEN@KC. **Third unverified claim I wrote into the instructions as fact** (after P7 and P8) — and this one I introduced in the very edit that corrected P8, by verifying the clause I was changing and leaving the adjacent clause standing. |
| **D6** | A regression check was always-true | DONE | Left an `... if False else True` artifact in the new section — the same unfalsifiable-check failure as B12, two rounds after criticizing it. Removed; count went 122 → 121. |

### Found by the second deployment test (2026-10-30)

| # | Item | Status | Notes |
|---|---|---|---|
| **B13** | `prop_edge` priced the UNDER at the OVER's price | DONE | When the model preferred UNDER and `under_odds` was omitted, it fell back to `over_odds`: on +275/−350 it reported **EV +217%/$ and Kelly 0.79** where the real figures were +8.7% and 0.31 — inflated ~25x, with a stake recommendation attached, for a bet nobody can place. Flattering, and reachable from the documented workflow: `screen_quotes` flags a one-sided market and says to pass `fair_over`, which lands exactly here. Now raises. |
| **B14** | A player returning from a full-season absence was permanently unresolvable | DONE | `build_pool` read 2026 only, so Zach Charbonnet (0 rows 2026, 17 in 2025) was reported alongside De'Zhaun Stribling (0 in both) — two different problems with different answers. Excluding him was not the safe default: understating an **opponent** makes them likelier to post the low score, so own elimination risk reads *smaller* than it is. `build_pool(wk, lg, season=)` now falls back to prior-season form, marks it in `Pool.stale`, widens the spread 1.35x, and reports it in `Result.stale_projections`. |
| **B15** | `players_on_bye` returned an empty set for an upcoming week | DONE | A derived byes map knows only completed weeks, so asking it about an upcoming week returned nothing and read as "nobody is on bye" — the exact failure the function's docstring warned about but did not prevent. Now raises, naming the connector call to use. `run()` also takes `week=` and the report warns when it is omitted. |
| **B16** | Drive upload was not byte-safe and corruption was undetectable | DONE | The procedure has the payload travel through a tool call as text, so it is retyped; observed case was a local `\u2014` escape arriving as the raw 3-byte character (JSON-equivalent by luck). Transcription cannot be made safe — corruption is now **detectable**: `upload_payload()` prints a checksum and `verify_uploaded(downloaded)` diffs the round trip, reporting whether the records happen to parse identically. |
| **D4** | Check counts were quoted from unreliable greps, twice | DONE | 61 came from `grep -c PASS` matching the `ALL PASS` line; 109 from `grep -c 'chk('` which counts `def chk(` and both branches of try/except pairs. The suite now reports its own count (**107**) and the instructions say to quote only that. |

## F2 — backtest · IN PROGRESS (2026-11-02)

| Part | Status | Notes |
|---|---|---|
| Falsification criteria | DONE | Written before the logic, on purpose. `audit()` fails on inflated hit rate (leakage), post-kickoff prices, >5% ungraded legs, implausible ROI, and an empty sample. Verified against four deliberately broken backtests. |
| Grading | DONE | Local, against nflverse, joined ESPN id → GSIS id via the roster crosswalk. PropLine's results endpoint is Pro tier and is not needed. UNGRADED counts as a LOSS. |
| Boost economics | DONE | `breakeven_p`, `expected_roi`, `roi_band`. **A 20% boost is break-even at best after SGP hold; 30% is thin but positive; 50% is where the money is.** |
| **Scope change** | — | **The available history cannot measure profitability.** 84 event-clusters → ±23% ROI error bar against a +2–13% effect; resolving 2 points needs ~11,000 independent slips, ~40 weeks of NFL. Reframed to measuring the SGP **hold** from prices, which needs ~30 calls and has no outcome variance. |
| **B33** — the audit's own error bar assumed independence | DONE | Slips from one game share legs and game script, so 100 slips from 5 events are not 100 observations — treating them as such understated the se by ~4.5x, which is the "noise looks significant" error the audit exists to catch, committed by the audit. Now computed on distinct events and reported. Found by doing the call-count arithmetic, not by a test session. |
| Hold measurement | **DONE 2026-11-02** | 12 priced combinations, 2 events, DK + FD. **The guessed (8%, 20%) band was badly wrong** — 8% was not attained by any slip and the floor is 17.7%. And it is not one number: **cross-game 18.6%** (17.7–20.9%, exact because cross-game legs are independent), **same-game independent legs 30.2%** (23.1–37.2%, the book haircutting legs that are not correlated), **same-game correlated not measurable** (the price implies a joint 1.8–1.95x the independent product, which needs a model this project lacks). Replaced with `SGP_HOLD_CROSS_GAME` / `SGP_HOLD_SAME_GAME` and `hold_band(cross_game=)`. |
| **Policy change** | — | **A 20% boost is negative everywhere measured. 30% works cross-game only (+1.3% at +300) and is −10.7% same-game. Structure is worth ~22 points of boost**, making "prefer SGPx" the primary lever. The old table assumed ~14% hold and every figure in it was optimistic. |
| **B34** — audit noise floor collapsed at 0%/100% | DONE | Two slips, both losses → binomial se exactly 0, so it printed "2 se is 0.0%" and "resolving 1 point needs ~0 slips": perfect resolution claimed from the least informative sample possible. That is the B33 error inside the audit's own noise reporting. Now Agresti-Coull on the full sample, inflated by sqrt(n/n_eff) for clustering — an earlier attempt divided a win count by a cluster count and threw a math domain error. |
| **B35** — a wrong-but-valid player id graded as a normal win | DONE | A fabricated id resolved to a different real player who played and cleared the line, so the leg graded WIN with no trace — the B24/B28 signature. `Leg.event_teams` now cross-checks the resolved player's team against the event, and `audit()` fails when >10% of legs omit it. |
| **D13** — the historical endpoints carry no `player_id` | DOCUMENTED | `get_odds_history` and `get_odds_closing` return a name and `outcome_id` only; just live `get_odds` has the id. So a backtest's entry point must start from a name via `search_players` — a name-shaped hole in the never-join-on-name rule at precisely the point the backtest needs it. Mitigated by using PropLine's own mapping rather than local matching, plus the `event_teams` guard. |
| Pipeline validation | **DONE 2026-11-02** | 8 events, Weeks 5–6, 950 graded legs. **Name resolution was NOT the blocker: 99.2% end-to-end** (121/122 names → espn id → GSIS), 2.1% ungraded (3 real scratches). The `event_teams` guard fired on **0 of 950 real legs with 0 false positives**, and a probe confirmed it is live rather than silent. Independent corroboration of the hold: mean per-leg Shin hold 6.30% compounds to **17.74%** over 3 legs, landing on the bottom edge of the measured cross-game band — from historical Weeks 5–6 lines, a completely different data path from the live `price_sgp` pulls. |
| **F2 VERDICT** | **Do not build a scaled outcome backtest** | Not because of data quality — that hypothesis is dead. Because the sample arithmetic cannot be fixed: 8 events gave 2se = 23 points on the hit rate; scaling to all 84 event-clusters tightens ROI to roughly ±13% against an effect of +1.3% to +4.1%. An order of magnitude short, and the NFL does not produce enough independent games. **What the history CAN measure, it measures from prices, and that is already pinned.** |
| **P10** — Pinnacle IS available historically | RESOLVED 2026-11-02 | The validation de-vigged recreational books against themselves because its historical pull excluded Pinnacle and `get_event_ev` is live-only — the circularity the instructions forbid. One call settled it: `get_odds_history` with `bookmakers="pinnacle"` on event 53166 returns two-sided main lines, `redacted: false`, with liquidity and pre-kickoff snapshots. **Always include pinnacle in a historical pull.** Historical EV screening is possible. |
| **B36** — `audit()` quoted the wrong ROI band | DONE | It used the pessimistic same-game band even when the caller knew the slips were cross-game. On 250 cross-game slips it reported −8.5% to +2.0% where the correct band was +1.3% to +4.1% — the wrong SIGN, from a default meant to be cautious. `audit(slips, cross_game=)` now takes structure, and names which band it used when structure is unknown. |
| **D14** — `search_players` traps | DOCUMENTED | `team_abbr` is as-of-TODAY, not as-of-game (Kaleb Johnson reads GB but was propped in a Week 5 PIT game) — using it to validate a historical event rejects real legs. And duplicate player records exist: `DeVonta Smith` returns two espn ids with identical names and identical `known_names`, both `team: null`. The crosswalk broke the tie only because one has no GSIS id — luck, not logic. |

### Next, now that F2 is settled

HANDOFF.md and this table disagreed on the order of items 1 and 2 — a real
contradiction between the two docs, now resolved in favour of P0 first.
**P0 depends on the hold's interface, not its value.** `ff_boost` imports
`SGP_HOLD_*` from `ff_backtest` rather than restating them, so Sunday's
re-measurement updates one place and P0 follows it with no rework. Meanwhile
the re-measurement is gated on a full Sunday slate, and running it on a
Monday reproduces the exact constraint that caused the original caveat.

| # | Item | Status | Why |
|---|---|---|---|
| **1** | **P0 — the boost-slip optimiser** | **DONE 2026-11-02** | `ff_boost.py`, 65 checks. See the P0 section below. |
| **2** | Widen the hold measurement | NEXT | `SGP_HOLD_*` is what every ROI figure depends on, it converges fast because prices carry no outcome variance, and the same-game-correlated case is still unmeasurable. Re-run on a full Sunday slate with 3+ events and BetMGM live. **Re-scoped:** Dustin uses single-game mode roughly half the time (TNF/SNF/MNF boosts), so the same-game band matters at least as much as the cross-game one — and it is the weaker number, 23.1–37.2% off 12 slips on one slate. Measure both structures deliberately, not just the cross-game case the original caveat named. |
| **3** | Grade forward via the bet log | | CLV across 30+ legs is the measurement that actually works at a $10 stake. A retrospective backtest of a strategy claiming no leg-selection edge was never going to produce a trustworthy number. |

## P0 — boost-slip optimiser · COMPLETE (2026-11-02)

`ff_boost.py`. Falsification criteria written first, as `test_boost.py`, then
folded into `test_regression.py` as sections 29–39 once green. Suite went
223 → **288 checks**.

### Usage, as stated by Dustin 2026-11-02

**Single-game mode is roughly half the use**, not an edge case — TNF/SNF/MNF
boosts are usually offered for that game alone. Cross-game is the Sunday
1pm/4pm window. Both are first-class; mode is an explicit input because the
module cannot read a boost's terms.

Consequence worth stating plainly: **under the measured numbers P0 will
refuse most standalone-game boosts.** Same-game at +300 is −16.2% at a 20%
boost and −10.7% at 30%; the measured minimum is ~50%. Stretching to +500
does not rescue it (−8.9% at 30%). If the typical TNF offer is 20–30%, the
honest answer on most of them is "don't play this."

### Step 4 of the original spec was replaced

The 2026-10-29 spec said to **prefer** positively correlated combinations
because they raise the true joint. That is wrong on its own terms, before
the hold measurement is even considered: it counts the lift and not its
price. Books charge 0.61–0.65 on QB stacks, and this project's own note
records that their factors track the measured correlation table closely.
Buying a real lift at its real price is not an edge, and it costs you the
ability to state an EV.

Two further reasons it was replaced:

- **The haircut fights the +300 floor, which is the binding constraint.**
  Three legs at −150 price at +363 independent and +225 at a 0.62 factor. To
  clear +300 same-game-correlated you must reach for materially longer legs
  — lower per-leg hit probability — against an unquantifiable correlation
  offset. Cross-game at ~1.0 clears the floor with the shortest legs.
- **The table's actionable content is a veto, not a selector.** The
  detectable bad deal is a book haircutting legs the table puts at ~0.00
  (receiver-only slips came back 0.87–0.96). That is a charge for
  correlation that does not exist, and it needs no joint model.

**Replacement:** default to cross-game. Construct same-game candidates too,
tagged by structure. Penalise a `correlation_factor` lower than the table
justifies. Correlated slips carry a price, a payout and the factor
comparison but **never an EV or a P(cash)**. When the boost restricts the
slip to one game, prefer correlated over same-game-independent and say why.

### Decisions made during the build

| | |
|---|---|
| **A `mixed` structure kind** | Two legs in one event and a third elsewhere is neither cross-game nor same-game. It takes the pessimistic band. Without it, the likeliest real mistake — accidentally doubling up on one game while building a Sunday slip — reads as cross-game and gets scored against a band ~12 points too favourable. That is B36's signature in the one direction this module is most exposed to. |
| **Structure is derived, never declared** | `classify()` reads it off the legs. A caller passing `mode="cross-game"` does not make a slip cross-game. |
| **Refusal, with the losers still visible** | `Shortlist.playable` is the headline verdict and goes False when the boost does not cover the measured hold. Every enumerated slip is still returned carrying its own `PLAY` / `NEGATIVE` / `UNPRICEABLE` tag and its numbers. A returned slip reads as a recommendation, so the verdict has to be separate from the data — but hiding the data is the other failure. |
| **UNPRICEABLE counts as playable, NEGATIVE does not** | The 30.2% same-game figure was measured on *independent* legs. Letting it reject a stack would be using a number outside what it measured. |
| **P0 can detect opposing RBs; the guillotine cannot** | `correlation_matrix()` treats every different-team pair as independent because it does not model the schedule. P0 knows the event, so two backs inside one event are genuinely facing each other and the measured −0.14 applies. |
| **`fair_prob` validated at construction** | Same rule as B4, one layer earlier: a 0.0 or 1.0 cannot reach a slip. |
| **`price_candidate` returns a copy** | B19 shipped because a function mutated a shared pool in place and a later run inherited the earlier one's state. |

### B37 — two EV computations that could contradict each other

Found by reading the suite's own output on the first green run, not by a
check. The 20%-boost refusal printed *"a 20% boost returns nothing playable
— Best candidate is **+15.7%** at the pessimistic end"*: a positive EV
beside a NEGATIVE verdict.

Cause: `verdict` derived the true probability from the offered price and the
measured hold, while `ev_pct` used the de-vigged joint directly against the
*independent product* — which is not a price anyone will lay. The book's SGP
quote is routinely far shorter, so a direct EV computed against the product
is an EV for a bet that does not exist.

Fix: `ev_pct` is **None until the slip is priced**. Before pricing the only
honest number is `ev_band`, the anticipated ROI across the measured hold
band. Once a real `price_sgp` quote is attached, `ev_pct` is computed
against *that*, and `slip_hold` reports the hold actually observed on that
slip rather than the population band — which for a cross-game slip is the
better number, since the band is a population figure and this is the slip in
front of you.

This is the project's recurring signature again: a plausible number rather
than an error, in the flattering direction.

### Falsification probes

Each of the four documented failure modes was confirmed catchable by
deliberately breaking the module and checking the right checks went red:

| Break | Result |
|---|---|
| mixed slips tagged `cross-game` | 3 failures, including the hold-band check |
| EV/P(cash)/breakeven ungated on correlated slips | 3 failures |
| `correlation_factor` divided into the joint | 1 failure — EV moved when the factor moved |
| floor read off the product, not the book price | 1 failure |

Breaking `ev_pct`'s gate *alone* raises a `TypeError` rather than failing a
check, because `p_cash` is gated by the same flag. The harness names the
section and exits non-zero, so nothing is silent, but the assertion itself
is only exercised when both gates are removed together.

### Found by the ninth deployment test (2026-11-02/03) — P0's first contact with live payloads

The module's own logic held: all four adversarial probes passed, `classify()`
was correct on the cases it could see, the no-EV gate held, and the
circularity screen fired for the right reason and only that reason. **Every
defect was in the intake path around it** — which is what the synthetic
fixtures could not reach, exactly as HANDOFF's standing lesson 3 predicts.

| # | Item | Status | Notes |
|---|---|---|---|
| **B38** | `classify()` was position-blind AND market-blind | DONE | `build_meta()` returns Travis Hunter as **CB** — his nflverse primary position — while he carried a receiving-yards prop on Trevor Lawrence's team. A genuine QB×receiver pair scored **independent**, which hands it the cheaper hold band *and* an `ev_pct` and `p_cash` it must never receive. Two failure modes at once, arriving through the data rather than the code, and he was in the shortlisted candidate that got priced. The side now comes from the **market** (`MARKET_SIDE`), which is what the correlation table was actually measured on. Same fix closed a second hole the live test could not reach because cross-game was unbuildable: the table was measured on **yards**, so two same-event `player_anytime_td` legs were being asserted independent at +0.00 when nobody has measured TD correlation at all. A same-event pair involving a market outside the table is now `unmeasured` and makes the slip unpriceable. Different-event pairs stay independent regardless of market — that one IS measured, and it is what makes cross-game exact. |
| **B39** | Two flattering defaults, both meaning "nothing found against it" when nothing was checked | DONE | `BoostLeg.verdict` defaulted to `CLEAR`: a live run built **32 legs that all read CLEAR** without `boost_verdict()` ever being called. Default is now `UNSCREENED` and intake drops it naming the screen. Separately, `team=None`/`pos=None` were accepted silently and every such leg classified independent — the same live run built all 32 that way. An unknown team on legs **sharing an event** is now unmeasurable rather than independent. Both are the shape of the 6.0 phantom-player mean (B1), which outranked 1,058 real players by being the fallback. |
| **B40** | The refusal reason hardcoded its direction | DONE | `'legs are too short' if combos else 'not enough legs'` — the direction was never checked. Live, **all 4,144 combinations priced ABOVE the ceiling and none below the floor**, and the message sent the reader hunting the wrong way. Confirmed hardcoded by feeding synthetic −400 legs (genuinely too short) and getting the same sentence verbatim. Now counts both directions per combination and reports what it measured. |
| **B41** | A regression check depended on live data, for the third time | DONE | Section 17 named **Zach Charbonnet** as the returning player with 0 rows in 2026. On 2026-11-03 he played Week 8, picked up a row, and all three checks failed — the data moved out from under the fixture. B21 and B23 are the same lesson. The fixture is now synthetic: a constructed player with prior-season rows only, and an absent name deliberately never added to the frame. |

### Verified by isolation, NOT a bug — the Pinnacle 0.5000 question

A live run found Pinnacle quoting −114/−114 on essentially every yardage
main line on event 87238, so 15 of 16 anchored lines de-vigged to exactly
0.5000, and reported this as "the anchor carries almost no information."
A dedicated isolation run settled it: **PropLine is not normalizing or
degrading Pinnacle prices on this tier.**

The decisive evidence needs no breadth: in the **same response, same book,
same tier**, Pinnacle's `player_receptions` lines vary richly (−205/152,
158/−215, 182/−250) while its yardage lines sit flat. No tier-level
normalizer flattens one market and leaves another untouched in one payload.

Mechanism: a continuous stat on a half-yard grid lets the **point** absorb
the information, so the price stays flat and only tilts when the grid cannot
absorb the value (2 of 20 lines did exactly that). Discrete stats —
receptions at 1.5/2.5/3.5, pass TDs at 0.5/1.5 — have no grid, so price must
carry everything.

**But the finding underneath it is real and actionable.** `liquidity: 250`
on every one of those lines is Pinnacle's opening tier, ~68 hours out. By
the final pre-kickoff snapshot only 2 of 22 lines are exactly 0.5000, and on
a second event inside the last six hours it is **0 of 16**. So an exact
0.5000 at minimum limits is the book saying *"I set the point at my estimate
and have taken no money yet"* — a prior, not a posterior. An EV built on it
is an EV against an opening number.

`liquidity` is present in the live `get_odds` payload and `ff_boost` ignores
it. That is P2's shape exactly: a field carrying real information, discarded.
**Batch two.**

Caveat kept from the isolation run: the by-liquidity bucket table is small-
sample and non-monotonic. The directional claim rests on the final-snapshot
and second-event figures, which are clean; treat the buckets as
consistent-with rather than proof.

**Do not switch the anchor to Kalshi on the strength of its 98.9%
"informative" rate.** That is an artifact of being an order-driven exchange
where most alternate contracts carry under $5 — Derrick Henry rec 9.5 at
113/−223 with `liquidity: 0.94` is noise wearing a precise-looking number,
and it is the worst possible input to `fair_over`. Pinnacle stays default.
The rule is a **timing** rule, not a book rule.

### Batch two — intake hardening (2026-11-03)

| # | Item | Status | Notes |
|---|---|---|---|
| **B42** | `liquidity` was discarded, so an opening anchor read as a settled price | DONE | `BoostLeg.anchor_liquidity`, `anchor_immature`, `anchor_note`; the report prints `** OPENING ANCHOR **` and `Shortlist.immature_anchors` names them. An exact 0.5000 is the signal on its own — by kickoff only ~9% of lines sit there — and liquidity at or below Pinnacle's 250 minimum confirms it. Bovada reports null liquidity, so the 0.5000 has to stand alone there. **This is P2's shape exactly:** a field carrying real information, present in the payload, silently discarded. |
| **B43** | The pre-pricing read was a hard gate and produced a false negative | DONE | `playable` went False whenever the boost failed to cover the PESSIMISTIC end of the hold band. Live: the band said 23.1–37.2%, the slip it refused actually held **19.2%**, and it priced at **+1.4%**. A false negative on the one thing the tool exists to find, from a 14-point-wide band used as a gate. `playable` is now structural (is there anything to price), `outlook` is advisory, and `Candidate.verdict` after `price_candidate()` is the verdict — where the hold is observed rather than assumed. The shortlist caps at 8, so pricing everything costs 8 calls. Also dissolves the live finding that `sl.playable=False` sat next to a candidate reading PLAY: only one of them is a verdict now. |
| **B44** | The odds → anchor join was raw-name keyed | DONE | `get_event_ev` carries `description` and **no `player_id`**, so the live intake path joins on a name — D13 recorded this for the historical endpoints and said "just live `get_odds` has the id", which is wrong about the EV endpoint. Event 87238 carried `Brian Thomas Jr.` (9.5, kalshi) and `Brian Thomas` (10.5, pinnacle) in the SAME payload while DK/FD both priced 10.5, so a raw join lost his entire board. `ff_boost.norm_player()` wraps `normalize_name` (built for B1) and strips a trailing team parenthetical for Bovada's `Garrett Wilson (NYJ)`. Deliberately does NOT merge Josh/Joshua Palmer — those go through `search_players` on exact `known_names`. |
| **B45** | A circular leg constructed cleanly and was only caught downstream | DONE | Now refused in `__post_init__`. Intake still checks, because `fair_source` is reassignable afterwards. |
| **D15** | Four instruction corrections from live contact | DONE | (a) `lines: []` has a **fourth** meaning — an anchor book carries the market one-sidedly so no fair line can be derived, measured on 53173 with Bovada at prices identical to DK. (b) `redacted` is **absent** from live `get_odds` at every level, not false; it is outcome-level on `get_odds_history` only, so it is not a usable live guard. (c) One market across four books is **~280KB**, not the ~68KB claimed — disk is the normal path for prop pulls. (d) Anchor scarcity recorded as a binding constraint, not a detail. |

**Deliberately NOT built:** an adapter that joins `get_odds` rows to
`get_event_ev` lines end to end. Writing one now means guessing the EV
response's exact shape, and B24 shipped because 135 checks were blind to a
price swap behind fixtures in a shape PropLine never returns. `norm_player()`
is shape-independent and fixes the part that actually failed. Build the
adapter from a saved live payload, not from a guess.

### Found by the tenth deployment test (2026-11-03) — batches one and two on live payloads

Every structural guarantee held on live data: B38 confirmed with the real
Travis Hunter leg (`build_meta` returns him CB, the pair still took +0.31
from the market and the note surfaced `(CB)` so the disagreement is visible),
B39 confirmed both halves, B40's direction matched an independent count of
every combination, B44 recovered exactly the two Brian Thomas Jr. quotes and
upgraded him from a Kalshi anchor to a Pinnacle one, B45 held at construction
and at intake, and `ev_pct` was byte-identical across `correlation_factor`
0.60 vs 1.40.

| # | Item | Status | Notes |
|---|---|---|---|
| **B46** | `anchor_immature` could not see a thin anchor — a scope bug in B42 itself | DONE | It tested `fair_prob == 0.5` FIRST and returned early, so the liquidity check was unreachable for any line not exactly at 0.5000. Live: Rashod Bateman, Kalshi anchor, `fair_prob 0.5052`, **`anchor_liquidity 0.98`** → read as a SETTLED price. That is precisely the input these instructions single out as "noise wearing a precise-looking number" (Derrick Henry at liquidity 0.94), and **the flag written to catch it was structurally blind to it.** Three legs were in that state. Split into `anchor_opening` (exact 0.5000 at ≤250) and `anchor_thin` (liquidity ≤25, whatever fair_prob says); `anchor_immature` is either. The 25 threshold is crude and documented as such — Pinnacle's 250 is a bet limit, Kalshi's 0.98 is resting money, and the two are not the same unit. |
| **B47** | `ff_data.CACHE` hardcoded another session's scratchpad UUID | DONE | `/tmp/claude-0/-home-claude/a8825ed4-…/scratchpad/nflverse` — a literal path from a session that no longer exists. It survived only because that path happened to be writable wherever it ran. Now derived at runtime from `FF_CACHE` or the system temp dir. Found incidentally; nobody was looking for it. |
| **B48** | `ensure_deps()` swallowed an install timeout and produced a confusing downstream error | DONE | The bootstrap failed on first run: `pip install pyarrow` exceeded the hardcoded `timeout=300`, the generic `except Exception` swallowed the `TimeoutExpired`, and the process limped on with a half-registered pyarrow until `pd.read_parquet` died with `ArrowKeyError: extension pandas.period already defined` — nothing like the cause. Timeout raised to 900s and `TimeoutExpired` named separately with what to do about it. |
| **D16** | Two coverage figures I wrote into the instructions went stale within days | DONE | "BetMGM carried **none** of the three yardage markets" → measured 1 event each three days later. "Pinnacle DOES carry anytime-TD, 13/13 events" → measured **0 of 15**, with every TD line on the test event anchoring on Kalshi. Both were point-in-time measurements generalised into standing claims, which is the P7/P8/D5/D10 failure for the fifth and sixth time. The fix is not newer numbers — they go stale too. The instructions now say **never record a coverage figure as a standing fact**; measure at query time and state the window. |
| **D17** | The instructions said to pass `anchor_liquidity` without saying where it comes from | DONE | `get_event_ev` carries **no `liquidity` field at any level** — its line keys are exactly `description, fair_books, fair_probs, fair_source, market_key, outcomes, point`. Liquidity has to be joined back out of `get_odds` for whichever book `fair_source` names, which usually costs a second pull. Also recorded: **only Pinnacle and Kalshi report liquidity at all**; DK (0/276), FD (0/204) and Bovada all return null, not just Bovada as previously written. |
| **D18** | A second, distinct way a leg loses its anchor: LINE-GRID mismatch | DONE | `Nate Boerkircher` is spelled identically in both payloads, but the EV response carries 7.5/9.5/14.5/… and **not 6.5**, which is DraftKings' main line; FanDuel's 7.5 anchors fine. Same consequence as a name split, completely different cause, and `norm_player()` cannot help. Documented with an explicit warning **not** to snap to the nearest point — a fair probability for 7.5 is not one for 6.5, and substituting it invents the number. |
| **B49** | `flatten_odds(line_type="milestone")` raises instead of returning one-sided rows | **DONE** | Fixed 2026-11-03 against a live bovada/DK/FanDuel payload for event 87238. The grouping key `(player, point)` collapsed every rung for one player into one group, and the second rung tripped B28's same-side guard. **The guard was right; the key was wrong.** Key is now `(player, point, threshold)`, widened ONLY where `point is None` — the two-sided path is byte-identical, because this is the code B24 lived in. Two rungs at the same threshold still raise; that is a real duplicate. Three things the live board showed that the writeup had wrong or missing: (1) the `ValueError` escapes `flatten_odds` entirely rather than being caught per market, and bovada is iterated first, so ONE collision aborted the whole call and took DK's 28 rungs and FD's 10 with it — not one book's board, all of them; (2) cardinality is 28 rungs for a starting QB at DK, 11 at bovada, 10 at FD, not the "six" assumed; (3) **DK posts `238+` alongside its own main line of `Over 237.5`** at -113 vs -111 — the identical wager, two rows, two cents apart. Rejected keying on `player_id` despite it being stable across all three books here: `flatten_odds`'s own note says DK's anytime-TD board leaves it null for some entries and for D/ST, so it would collapse every null-id player into one group — the same bug in a new place. It stays the cross-book joiner, not the grouping key. |
| **B50** | `canonical_bet()` has no caller — the rung/main-line duplicate is detectable but not yet detected | **OPEN** | B49 shipped `canonical_bet(q)`, which maps any quote to `(player, market, "over", threshold)` so that DK's `238+` and DK's `Over 237.5` come out identical. Nothing calls it. **This is deliberate, not an oversight: there is no merge point yet.** `ff_boost.py:80` pulls `line_type="main"` only, so main and milestone rows never meet today and wiring a dedupe in now would be speculative. The moment anything merges the two lists, it must canonicalize first — two rows that are one bet, parlayed with each other, price as independent legs and the P(cash) that comes out is fiction. Note the mapping must never snap: a rung at N is `over N-0.5` exactly, because these stats are integer-valued, and a whole-number main line at 237 pushes at 237 and is a DIFFERENT bet from `238+`. That is D18's rule on the rung grid, and section 25b checks it. |
| **B51** | Anchor scarcity is a standing constraint on cross-game MODE, filed separately so it stops being confused with the hold gate | **OPEN** | `get_market_coverage(days=7)`, 15 events in window: Pinnacle carried pass/rush/reception yards on **1** event; confirmed not a filter artifact. Cross-game leg selection needs 3 anchored events, so for most of the week the module cannot be used as designed — and rungs, now that B49 makes them parseable, would anchor off Kalshi contracts carrying a dollar or two, the input B46 exists to reject. **This does NOT gate the hold re-measurement**, which de-vigs a book's own two-sided legs and needs no external anchor (the first measurement ran on DK + FD over 2 events while Pinnacle covered almost nothing). A 2026-11-03 edit of HANDOFF merged the two and wrongly reported the re-measurement as blocked; corrected same day. Coverage is VOLATILE, not uniformly poor: re-measured 2026-11-03, event 87238 had full Pinnacle coverage on all three yardage markets and BetMGM live, three days after a 15-event sweep found Pinnacle on one event and BetMGM on none. So the constraint is unpredictability per event, not a standing absence — measure the specific event before concluding it cannot be anchored. Do not record a coverage figure here as standing — D16. |
| **B52** | Two leagues' DST points-allowed ladders were never written down | **OPEN — needs Dustin, not code** | E4 scores Holmdel's DST under its real rules. Cameron Wood and Gridiron Grail cannot be scored because nobody ever recorded their points-allowed TIER VALUES — LEAGUE-CONFIG has Cameron Wood's band EDGES (0 / 1-6 / 7-13 / 14-20 / [gap at 21-27] / 28-34 / 35+) but no points, and Gridiron Grail has no ladder at all. Their event values (sack, INT, TD, safety, blocked kick, return TD) are now encoded. **Do not copy Holmdel's ladder across** — Holmdel's pays 5/3/1 at 7-13/14-20/21-27 where the connector's generic preset pays 4/1/0, which is the whole reason the correction layer exists. Five minutes on each Yahoo settings screen closes this and makes DST computable in three of four leagues. Also unconfirmed: whether Yahoo charges a DST for points the opponent's defence or special teams scored against your offence. `pts_allowed_scope` defaults to "opponent_total" and names the assumption rather than burying it. |
| **B53** | ~~`_pair_r` asserts INDEPENDENCE for pairs the table never measured~~ | **WITHDRAWN 2026-11-05 — the claim was wrong** | I filed this after reading `_pair_r` and seeing a 4-entry correlation dict with a bare `return 0.0, ""` fall-through, and concluded every other same-event pair was unmeasured. **It is not.** The map in PROJECT-INSTRUCTIONS was pooled over 43,228 same-game pairs, and it measures the fall-through directly: same-team WR x WR is **+0.00 over 2,970 pairs**, TE x WR same team +0.02, WR x WR opposing +0.02, and every RB/WR/TE cross-team combination ~0.00. Same-team receivers genuinely do not stack — target competition cancels team volume. So the 0.0 encodes a measurement, not an omission, and `test_regression` asserts it by name ("same-team WR x WR is NOT correlated (measured +0.00)"). The `(None, why)` path the docstring describes is for the cases that ARE unmeasured and already return it: an unknown team, and a market outside passing/rushing/receiving yards. **A 2026-11-04 session's flag on same-team RB x RB was the same error**, and the slip it worried about (Henry + Flowers + Bateman) is correctly same-game-independent. Lesson, and it is the D16/P7 shape pointed at code rather than data: a constant's SIZE is not its COVERAGE — a 4-entry table can encode a finding about everything outside it, and the place that says so was the docs, not the dict. Read the measurement before calling a default a bug. |
| **B54** | `anchor_opening` could not fire — its liquidity threshold was pinned to a tier that moved | **DONE 2026-11-05** | OPENING_LIQUIDITY was 250 because that was Pinnacle's minimum tier the day it was written. Measured on event 87238: liquidity **250 on every outcome 2026-11-03**, **500 on every outcome 2026-11-05**, about a day out — Pinnacle raises the limit as an event approaches, so the flag tested a line the board had already walked past. On the 2026-11-05 pull, 7 of 14 receiving lines were priced -112/-112 (exactly 0.5000) at liquidity 500 and none flagged; a 2026-11-04 run carried 31 of 60 Pinnacle anchors at exactly 0.5000 in silence. **Raised to 500, gate kept.** My first attempt deleted the liquidity condition entirely on the strength of the docstring's "the 0.5000 is the signal on its own" — the suite caught it: section 35b asserts an exact 0.5000 at liquidity 10,000 is NOT flagged, because an even price behind genuinely deep money is a real coin flip, not a prior. The gate was right; the constant was stale. Three checks added at the 500 boundary. **Note why the suite was blind before: a flag that never fires breaks no test** — every existing check used a liquidity value the old threshold still covered. |
| **B55** | FLOOR/CEILING are applied to the product; a boost token's minimum odds apply to the real SGP price | **DONE 2026-11-05** | `Candidate.token_min_odds` carries the promo's stated minimum, `token_minimum` checks it against `book_odds` and `token_note` says what happened. **`None` means UNKNOWN and is the dangerous state, not a neutral one** — an unpriced slip returns None and the note says UNPRICED, gives the 0.81-0.86 estimate range, and labels it an estimate. Kept separate from FLOOR on purpose: FLOOR asks whether a slip is worth betting, the token minimum asks whether the book will let the token attach, and a slip can clear one while voiding the other — that case is checked by name. 9 checks. |
| **B56** | No model for stake-back tokens (bet reset / safety net) | **DONE 2026-11-05** | `stake_back_ev()` and `stake_back_band()` in `ff_boost`, 7 checks. `EV = p*(d-1)*S - (1-p)*S*(1-v)`. Returns COMPONENTS rather than one number, because the refund is almost the entire figure and burying it hides where the edge comes from — at +900 the raw bet is -$2.81 and the refund +$6.03 (**corrected 2026-11-05** — this row carried -$1.80/+$6.43 from the pre-measurement defaults of hold 0.22 / v 0.70 after the docstring and instructions had both been regrounded, so the backlog disagreed with the code it describes; a re-test caught it). `bonus_value` is an argument with no safe default behaviour, so `stake_back_band` quotes 0.60/0.70/0.80 and the spread is ~$1.85 on a $10 stake. Checked that EV rises monotonically as odds lengthen, which is the property that makes these the opposite of a boost and sends them to First TD Scorer. The raw bet stays negative at every price tested — the token IS the edge. |
| **B57** | The +600 ceiling fixed the zero-candidate failure and now selects nothing | **OPEN — observation, not yet a decision** | First live run at CEILING=600, 2026-11-04, event 87238: **616 of 616** BetMGM 3-leg combinations landed inside the band (0 of 616 under the old +300/+450). The zero-candidate failure is fixed. But the band then filtered nothing at all, so ranking fell entirely to P(cash) differences of ~1.5 points, and roughly half of those rested on fair probabilities of exactly 0.5000 (see B54). **The ordering of candidates 1 through 40 was close to noise.** Products clustered +541 to +564 because every main line on the board sits near -112, which is the mechanism behind the "three near-coin-flips multiply to ~+560" prediction. Not obviously wrong — a band that admits everything is only a problem if something else does the selecting, and right now nothing does. Decide whether selection belongs in the band or in leg quality. |
| **B58** | The Drive bet-log folder returned zero files; cause not established | **DIAGNOSED AND FIXED 2026-11-05 — no data was lost** | Queried the folder directly. **The query shape was correct and the folder genuinely had no LIVE files**, so the 2026-11-04 session's conclusion was right. But it held **eight trashed logs** the query could not see, because Drive's search defaults to `trashed = false` — an all-trashed folder and an empty folder return byte-identical results. Downloaded the earliest and latest: both throwaway test records ("VERIFICATION TEST", "THROWAWAY verification bet - delete", "ROUND-TRIP TEST", player "Throwaway Tester"), 698-769 bytes each, artifacts of the session that debugged the unicode round-trip. **No real betting history exists or was lost; E2 is intact.** The actual defect was that the session could not have known either way: `sync_state()` says "N log file(s) pulled from Drive" and at N=0 cannot distinguish NOBODY PULLED from THE PULL FOUND NOTHING — opposite situations, since the first means history is UNKNOWN and must not be written over. B39's UNSCREENED shape one module over. Added `record_pull(live, trashed)` and `pull_state()`: no marker reads UNKNOWN rather than empty, an unchecked trash says so, and zero live beside trashed files refuses to be read as a fresh start. `status()` now prints it. The PULL procedure in PROJECT-INSTRUCTIONS is now two queries. 7 checks. **Independently verified 2026-11-05**: a separate session downloaded all nine files rather than trusting filenames and confirmed the live log holds 6 `rec` records (engine verdicts, BetMGM, all tier PASS, 0 acted on, per-LINE anchors pinnacle x3 / bovada x2 / kalshi x1) and **zero `bet` records**, with all eight trashed files self-identifying as throwaway. Decoded sizes matched Drive's `fileSize` byte for byte on all nine. Drive was unchanged afterwards — same etag, same modifiedTime. Six defects in the FIX were found in the same run: B65. |
| **B59** | `OPENING_LIQUIDITY` was a hardcoded tier and would go stale again | **DONE 2026-11-05, with one limitation now guarded** | `modal_liquidity()`, `book_liquidity_tiers()`, `BoostLeg.opening_liquidity_tier`, keyed by the ANCHOR book. 20 checks. Verified on a live six-book pull: pinnacle 28/28 at exactly 500 resolves; **kalshi refuses, 252 distinct values across 272 readings, mode share 0.015**; the four null-liquidity books are absent rather than present with None. Judgement calls, all documented in the function: ties break HIGH (over-flagging is noise, missing an opening anchor is the failure that has happened); <3 readings returns None; the mode must cover >=50%. **Limitation found by a live re-test and now guarded:** `modal_liquidity` derives the most COMMON limit and asserts it is the MINIMUM tier. Those agree on an opening board, uniform at the floor, and diverge on a MATURE board, uniform at depth — Pinnacle rises to 5,000-10,000 by kickoff, which would have yielded a tier of 10,000 and flagged EVERY exact-0.5000 line as opening regardless of depth, on the very pull you bet from. `TIER_MAX_TRUSTED = 2000` rejects a derived tier above it, falling back to the constant. That is a BOUND, not a threshold: it only has to sit in the wide gap between an opening floor (250-1,000 observed) and a mature board (5,000-10,000), so it does not reintroduce B54. **The remaining gap, now visible rather than remembered:** nothing sets `opening_liquidity_tier` at intake, and on a live run that was **48 of 48 legs** falling back silently, because every anchor was Bovada or Kalshi and neither quotes a tier. `Shortlist.tier_fallbacks` counts it and `describe()` prints it — B39's UNSCREENED lesson aimed at this field. Threading recommendation accepted from the re-test: build ONE resolver from the `get_odds` payload and set `anchor_liquidity` and `opening_liquidity_tier` together at BoostLeg construction, never inside `_intake` — they are the same D17 join, setting one without the other is a latent bug, and redoing the name/point join on built legs re-runs the fragile part (B44, D18; 17 of 41 quotes dropped at that join on one live run). |
| **B60** | `get_event_ev` silently DROPS an anchor book while its odds feed stays healthy | **DETECTION VALIDATED 2026-11-05; upstream fault remains** | `ff_props.anchor_coverage()`. **Validated in both directions on a live dropout, which is the strongest evidence available:** at 05:48Z it flagged Pinnacle on four markets (reception_yds 0 of 14, receptions 0 of 14, rush_yds 0 of 5, pass_yds 0 of 2) while a paired control showed Pinnacle live, unsuspended, liquidity 500, prices varied; the fall-through was observed directly, with six of Pinnacle's exact (player, point) lines present in the EV anchored on bovada or kalshi instead, and the other eight **absent from the response entirely** — so a dropout can remove lines, not merely re-anchor them. At 05:59Z the same call on the same market reported healthy and Pinnacle anchored 14 of 14. Same code, opposite verdict, both correct. The dropout lasted 10-30 minutes and ended on its own. **Partial dropouts measured and did not occur:** seven market-level observations across the cycle were every one 0% or 100% — Pinnacle's anchoring is binary, so the documented limitation matters LESS than assumed, not more (one event, one night, one book). Also recorded: **only the TOP available chain book's count is interpretable** — bovada anchoring 21 of 30 is kalshi taking the rest, not a partial. **Untested live: polymarket carries no NFL props and smarkets is not in the NFL book list at all**, so two of five chain entries have synthetic coverage only. |
| **B61** | The SGP correlation factor is `quote / product` against a COARSE QUOTE GRID — not a property of the slip | **OPEN — explanation replaced 2026-11-05** | First filed as composition-dependence: yardage slips haircut hard (0.81-0.86), receptions and mixes barely (0.87-0.99). **A controlled run disproved that.** Same three Baltimore players, same event, same side, varying only the market: yards 0.8355 (product +528), receptions **0.7933** (+562), mixed **0.7705** (+614) — the opposite ordering, with receptions BELOW yards on identical players. Factor vs log(product) across those slips is **r = -0.989**; the spread between two receptions slips (0.189) is **4.5x** the between-market spread at matched product (0.042). Mechanism: quotes snap to a grid (+210, +230, +400, +425, +450, +475, ~0.25 apart in decimal), so lengthening the product against a near-static quote drops the ratio mechanically. Composition looked causal because **main-line yards cannot produce a short product** — the book moves the POINT until yards sit near -110/-120, so three yards legs are always ~+520 or longer, while receptions carry real price spread and can be either; the two were perfectly confounded. 0.7705 also fell BELOW the recorded floor of 0.81, so `OBSERVED_SGP_FACTORS` is now (0.77, 0.99) and is DERIVED from `SGP_FACTORS_OBSERVED` with a check that it covers every measurement — the previous check only asserted the range was >=0.15 wide, which would not have caught this. Real fix: predict the quote from the product against the grid. Thirteen points at one book on one event is not enough to fit it. |
| **B62/B63/B64** | Three defects in `anchor_coverage`, all found by a live test, all fixed | **DONE 2026-11-05** | **B62, the worst: the detector was blind when NOTHING anchored.** The "a book below it anchored" condition — added to kill the lower-priority false positive — opened a hole underneath itself: with no anchors at all, no book has anything below it, so nothing flagged and `healthy` returned True. That is this fault at its loudest, and it is **reason 6 of the `lines: []` ambiguity** — the case the instructions say only a paired `get_odds` control can diagnose. The control reported it healthy. Observed live 2026-11-05 03:00-03:03. Now handled first and separately as `AnchorCoverage.blank`, with its own message. **B63: `min_markets=3` hid a confirmed dropout on a real market.** `player_pass_yds` has two QBs, so Pinnacle carries exactly 2 two-sided lines; it anchored 0 of 30 and the detector said "no silent dropouts" in the same minute it correctly flagged three other markets. Root cause: `_two_sided_markets` counted market ENTRIES, which are not comparable across books — Pinnacle 14 (one per player), Bovada 30 (alternates separate), Kalshi's entire 44-outcome TD board **1**. Now counts distinct two-sided (player, point) LINES, and the threshold is 1: a market can be legitimately small, so size is the wrong gate, and the "anchored zero while a lower book anchored" condition does the real filtering. **B64: anytime-TD was largely invisible** — Kalshi scored 1 and could never clear a threshold, on the market where TD lines most often anchor. Line-counting fixes it. Bovada's one-sided TD board still contributes nothing, which is correct rather than a gap: a book quoting only "Yes" cannot be de-vigged and cannot anchor — reason 4 of the same ambiguity. 5 new checks, 12 in the section. |
| **B65** | Six defects in B58's own `record_pull`/`pull_state`, found hours after writing them | **DONE 2026-11-05** | A live test of code written the same night. **(a) A plausible number instead of an error** — `record_pull("name.jsonl")` reported **32 live file(s)**, because `sorted()` iterates a string into characters; a dict reported its key count; only an int raised. Inflating the apparent history is the flattering direction. This is B24/B28/B37 one module over, committed by the author of the note warning about it. Now `_namelist()` raises TypeError. **(b) `pull_state()` crashed on valid JSON of the wrong shape** — a marker of `[]` raised AttributeError out of `rec.get`, taking down all of `status()`; the guard caught only (ValueError, OSError). **(c) A marker of `{}` printed "Drive pull at None: 0 live file(s)" — a half-written file presenting as a successfully recorded empty pull**, with `at: None` the only tell and nothing reading it. (b) and (c) now both read UNKNOWN. **(d) THE ONE THAT MATTERS: a FAILED Drive query had no representation.** A session whose query errored and recorded `record_pull([], [])` got output byte-identical to a genuinely empty checked folder — and that was the ONLY state printing no warning at all, so **the most reassuring output the function can produce was reachable from a broken query.** B58 closed "nobody pulled" vs "the pull found nothing" and left "the pull FAILED" sitting in the same hole, one notch along. Added `record_pull(error=...)`, and the clean case now states its claim out loud instead of being silent — silence is what an unasked question looks like. **(e) `DRIVE_PREFIX` was defined and never enforced on the read path**: `_read_all` globbed `*.jsonl`, so a stray file was ingested AS HISTORY while a real log under any other extension was **silently skipped** — a `.txt` log holding a $500 bet read as no history, no warning, which is precisely the shape B58 exists to prevent. Now globs the prefix and NAMES anything in the directory it will not read. (f) An unparseable download still counts toward "N log file(s) pulled" — left open, see B66. **Found while fixing (e): the new stray-file warning fired TWICE per `status()`**, because `status()` reads the log twice, which is the same noise the test had flagged on the JSON-decode warning (three copies). Adding a warning to that path made it worse. Both now go through `_warn_once()` — a warning repeated is a warning skimmed, and the repetition made the log look more broken than it was. 15 checks. |
| **B66** | Test records are structurally indistinguishable from real ones | **OPEN** | Verified 2026-11-05: all eight trashed logs are test data, and the claim holds — but it holds **because a human wrote "delete me" in prose**, not because the record says so. Two of the eight use real players at plausible prices: Tyreek Hill reception yards 54.5 OVER at -115, $10; and Travis Kelce anytime TD at +270 with `fair_p: 0.248` and a 30% boost — which is the worked example straight out of PROJECT-INSTRUCTIONS, reused as a fixture. On player, market, price, stake and boost alone both are indistinguishable from a bet Dustin would actually place. **Only the free-text `note` marks them, and nothing validates, greps or reasons about `note`.** A future fixture that omits it pollutes the history silently, and CLV grading would run on it. Fix: a first-class `test: true` field set by the logging call, excluded from `_bets()`/`live_recs()` by default and reported separately — so the distinction lives in the schema rather than in prose. Also open from B65: an unparseable download still counts toward "N log file(s) pulled", so "pulled and empty" and "pulled and unreadable" read alike, and the per-line JSON warning re-prints on every `_read_all()` call (three times per `status()`). |
| **F9** | Touchdown-scorer workflow — first TD and anytime TD off short prompts | **DONE 2026-11-05** | `ff_props.devig_field()` plus a named workflow section in PROJECT-INSTRUCTIONS, so "who do you like for the first TD" and "top 8 anytime TD and probability" have one path instead of being assembled from four sections. 8 checks. **The two markets are structurally different and must not share a method:** `player_1st_td` has exactly one winner so the field de-vigs to 1; `player_anytime_td` does NOT — several players score, so its prices sum to the expected NUMBER of scorers, and normalising them to 1 would divide every probability by roughly three while looking entirely plausible. That is refused. **Second refusal, found on live data:** a first-TD field with no no-scorer outcome is INCOMPLETE. Event 87238: DraftKings 32 outcomes including "No Touchdown Scorer" (+6000) and both D/STs, booksum **1.5535**; BetMGM 23 with neither, booksum **1.4109**; the nine DK had and BetMGM lacked sum to **0.1788**, almost the whole gap. So BetMGM's leaner market is a SHORTER FIELD, and de-vigging it inflates every player ~10% in the flattering direction — **never compare two books' overround without checking the outcome count.** Also measured: on that 55%-overround field Shin puts the longest shot (+11000) at **0.22% against 0.58% proportional**, a factor of 2.6, while the favourite rises 12.87% -> 15.17%. This is a MARKET workflow only — the threshold model abstains on low-event binary stats (B32) and F4, the best TD predictor, is unbuilt, so the section says to report de-vigged market probability and best price, never a model opinion. |
| **F10** | TD edge from ROLE CHANGE, not from a better level estimate | **OPEN — the version of F4 worth building** | F4's measurement says we cannot out-predict a book on a player's TD LEVEL: the best feature reaches AUC 0.66 and the market prices team totals and game script better than this project can. But the project's one demonstrated signal is CHANGE, not level — `role_trend` caught Jeanty COLLAPSED (touch share 0.364 -> 0.185) and Juwan Johnson COLLAPSED (0.104 -> 0.042) while season averages still looked fine, and a sim built on those averages still liked Jeanty. **The edge hypothesis is that a book reprices a role change more slowly than the play-by-play reveals it** — a backup who has taken over goal-line work for two weeks, priced off a season of being the backup. That is a DIFFERENT claim from "our number beats their number" and it is testable: join `role_trend` output to the market's de-vigged anytime-TD probability and measure whether flagged players outperform their implied rate. **Needs historical TD odds** (propline_get_odds_closing / get_odds_history) and real outcomes, so it is a measurement task before it is a build task. Do not build the suggester until the join is measured — that is exactly the F2 mistake, which was reframed from "build the backtest" to "measure the hold" once the data could not support the original question. |
| **F13** | The correlation table covers only three markets, so most slips are UNPRICEABLE | **OPEN — BLOCKED BY E3, established 2026-11-05** | `MARKET_SIDE` maps exactly `player_pass_yds`, `player_rush_yds`, `player_reception_yds`. Every other market in a same-event slip returns `(None, why)` from `_pair_r` and the slip classifies UNPRICEABLE with no EV — correctly, since independence there would be an assumption. But that means **receptions, anytime TD, pass TDs, longest reception, rush attempts and everything else cannot appear in a priced same-game slip at all.** Dustin named receptions explicitly ("JSN over 5 receptions"), and a 2026-11-05 run confirmed a receptions slip classifies same-game-correlated/unpriceable for this reason. The existing table came from a pooled measurement over 43,228 same-game pairs, z-scored per player; extending it is the same job on more markets — **but the existing table cannot be reproduced, so there is no baseline to extend consistently.** A filter sweep on 2026-11-05 put every documented value inside its plausible range without landing on any of them, and showed the estimates swing up to 2.4x on an undocumented filter choice. New entries measured on MY filter would sit on a different scale from the existing four, making the table internally inconsistent. **Do E3 first.** Early reading from that sweep, for when it is unblocked: receptions behaves as a RECV-side market as expected — QB passing x WR receptions same team +0.199 against +0.243 for receiving yards — so the likely outcome is extra MARKET_SIDE entries rather than a new table shape. **Measure before building anything that depends on it** — and note the existing finding that "everything else is ~0.00" was itself a measurement, so the honest default for a NEW market is unmeasured, not zero. Cross-game pairs are unaffected: different events are independent whatever the markets. |
| **F11** | Enumeration is not token-aware: it builds to the PROJECT band, not to the promo. **Design settled 2026-11-05.** | **OPEN — build after F13** | `enumerate_candidates(floor=300, ceiling=600, legs_per_slip=3)` filters on this project's band and builds 3-leg slips only. A token has its own **minimum total odds, minimum legs, maximum stake and eligible bet type**, and those decide whether it attaches. B55 added `token_min_odds` but it is checked AFTER pricing a candidate the enumerator chose for unrelated reasons — nothing builds TOWARD the token, and a 4-leg token cannot be served at all because `legs_per_slip` is a fixed int. **DESIGN:** take a token spec (pct, max_stake, min_odds, min_legs, eligible type, event restriction); enumerate leg counts `min_legs` to `min_legs + 1` ONLY, because vig compounds per leg and there is no reason to go further; **deliberately OVERSHOOT the product and then price**, targeting roughly `min_odds / 0.80`, because B61 showed the correlation factor runs 0.77-0.99 and depends on product length and composition, so the product needed to clear a minimum CANNOT be computed — only the real `price_sgp` quote is what the book checks; rank locally before spending pricing calls by fewest legs, then worst leg quality, then true joint; price the top 8; report which cleared, each EV against the token, and `token_note` for any that voided. **"Push the odds higher" is dropped from scope** at Dustin's call — target the minimum, do not reach past it. Thin pool until F13 lands: with `MARKET_SIDE` covering three yards markets, any slip containing receptions or a TD leg is unpriceable, so the enumerator would be choosing from a fraction of the board. |
| **F14** | No single-leg Q&A path — "do you like CMC over 50 rushing yards?" | **OPEN — cheapest item on this list** | Every part exists and nothing joins them: `get_odds` for the price at his book, an unfiltered `get_event_ev(devig="shin")` for the fair line, `prop_edge()` for the gap, `boost_verdict()`/`role_trend()`/`decline_onset()` for the veto pass, `anchor_coverage()` for whether the anchor is real. A session assembles that from five sections each time, so the answer shape varies run to run. Same gap the TD workflow (F9) just closed, and the same fix: one named section naming the tool order and the output shape. **The output must be allowed to be "the market says X, the model abstains"** — B32 means the threshold model has nothing to say on low-event binaries, and F4's falsification means it should not claim to beat a price on level either. |
| **F15** | No path for "what do you think about THIS parlay?" | **OPEN** | Dustin assembles slips himself from watching games and wants a sanity check. Needs free text ("JSN over 5 receptions, CMC over 50 rush") resolved to real lines at a real book, then `classify()` + `price_sgp` + the veto pass. **The resolution step is the fragile part and should be built defensively:** it is the B44 name join (Brian Thomas Jr. vs Brian Thomas) and D18 line-grid mismatch (his book at 46.5 where the anchor is at 47.5) in one step, and a 2026-11-05 run dropped 17 of 41 quotes at that join. A leg that cannot be resolved must be refused by name, never snapped to the nearest line. Blocked in practice by F13 for most interesting slips. |
| **F12** | The leg pool is main lines only, so odds cannot be tuned | **OPEN — blocked on B51** | The production path pulls `flatten_odds(line_type="main")`. Alternates and milestone rungs are what let you PICK a price rather than take the one on offer, which is exactly what "push the odds to +400" needs. B49 made rungs parseable and `canonical_bet()` (B50) stops a rung being parlayed with its own main line. **The wall is anchor quality, not parsing:** Pinnacle carries no alternates on props at all, so alternates and rungs would anchor off Kalshi contracts carrying a dollar or two — the exact input B46 exists to reject — and a rung is one-sided so it cannot be de-vigged pairwise at all. Do not build this before B51 has a route. |
| **F16** | No allocator across multiple tokens on one slate | **OPEN** | Dustin typically holds 4-6 tokens of different shapes (percentage, max stake, SGP-only vs parlay, different minimums) and the question "which token on which slip" has no answer in the code. It is not independent per token: slips on one game share legs and game script, so three $10 slips with 2-of-3 overlap behave closer to one $30 bet on a game going over than to three independent bets. **P4 (slate-level exposure) is the prerequisite and is unbuilt** — flat staking across correlated slips is the thing it exists to prevent. Also wants the stake-back tokens (B56) in the same comparison, since on the 2026-11-05 inventory they were worth $2-4 each while every boost token priced negative; an allocator that only ranks boosts would recommend the worse instrument. |

### Leg count at a fixed target price — settled 2026-11-05, do not re-derive

Asked whether 4 safer legs reaching a token's minimum beats 3 riskier ones.
**At the same offered price it cannot, because the implied probability IS
the price.** Three legs at -141 and four at -202 both multiply to +400; the
longer slip does not buy a better chance, it buries more vig in the same
one. Using the measured 6.30% per-leg Shin hold:

| legs to reach +400 | each leg | compounded hold | true P(cash) |
|---|---|---|---|
| 2 | +124 | 12.2% | 17.82% |
| **3** | **-141** | **17.7%** | **16.99%** |
| 4 | -202 | 22.9% | 16.27% |
| 5 | -263 | 27.8% | 15.65% |

The measured SGP holds point the same way — 3-leg 23.1/28.0/28.5/35.1%
against a single 4-leg observation at 41.4% — **but that comparison is
confounded and must not be quoted as evidence**: the 4-leg slip sat at a
longer product, and B61 established the factor tracks product length, so
leg count and length cannot be separated there. n=1 besides.

**Where more legs DOES win, and it is the only case:** when reaching the
minimum in fewer legs forces a leg the model would veto. A collapsed role
has a stated probability that is overstated, so the whole slip's number is
wrong — four clean legs at a worse structural hold beat three legs where
one is broken. The decision is **leg quality, not leg count**, and
`boost_verdict` / `role_trend` are what assess it.

**Rule: use the fewest legs that reach the minimum, unless dropping to that
many forces a leg you would veto.**
| **B67** | An RB with a RECEIVING prop was scored at the WR correlation | **DONE 2026-11-05** | `_pair_r` resolved a same-team `{PASS, RECV}` pair by asking only whether the receiving player was a TE, so every other position — including a running back catching passes — took `SAME_TEAM_CORR[("QB","WR")] = +0.31`. The `("QB","RB")` entry is QB passing x RB RUSHING and never applied. Measured on nflverse 2025-26: QB passing x RB receiving is **+0.157 (n=2,154)** against +0.243 for WR receiving on the same filter — a ratio of 0.65, so the live value was roughly **2x** too high. Fixed with three branches on the receiving side. **The value shipped is the RATIO applied to the documented +0.31, giving +0.20, not the raw +0.157**, because the documented table's filter is unrecoverable (E3) and a raw level from a different filter would sit on a different scale from its neighbours, while a ratio measured within one filter transfers. Marked `SAME_TEAM_CORR_PROVISIONAL` and E3 should overwrite it with a direct measurement. **Low operational stakes, stated so nobody over-reads the fix:** magnitude does not decide priceability — `classify()` refuses an EV on any non-zero pair — so this reaches the explanation text and the comparison against the book's own `correlation_factor`, not what is bettable. 6 checks. |
### Found by an INDEPENDENT REVIEW of a diff that had already passed 464 checks (2026-11-05)

Dustin asked why every follow-up surfaces a new self-caught error. The answer
turned out to be demonstrable: an adversarial reviewer was given the diff and
the failure-pattern list as questions, and **not** the author's reasoning. It
returned ten findings, four of them on the betting path. See the SHIP GATE in
HANDOFF.md — this section is the evidence that step 6 of it is not optional.
**Every finding below was in code that 464 passing checks had blessed.**

| # | Item | Status | Notes |
|---|---|---|---|
| **B70** | `devig_field`'s mutual-exclusivity refusal was OPT-IN, reachable by omitting an argument | **DONE 2026-11-05** | The docstring spends a paragraph on it: anytime TD must be refused because several players score, so the field sums to the expected NUMBER of scorers and normalising it "would divide every probability by roughly three and look entirely plausible doing it". The guard was `if market and market not in MUTUALLY_EXCLUSIVE_MARKETS`, and `market` defaulted to `None`. **`devig_field(anytime_td_board)` with no market argument ran the full Shin normalisation and returned a 58.3% implied scorer at 26.6% fair, tagged `method: shin, complete: True`, no warning** — the exact failure the docstring describes, reachable by leaving out a keyword. **Why 464 checks were blind: every caller in the repo passed `market=` explicitly, so the default was never once exercised. A parameter's DEFAULT is a code path.** `market` is now required; an explicit `market=None` is also refused and the message lists the fields that do qualify. 3 checks. |
| **B71** | The completeness guard checked a NAME and never the arithmetic | **DONE 2026-11-05** | `complete` was `any(name in NO_SCORER_NAMES)`, so a field carrying "No Touchdown Scorer" reported `complete: True` however short it was — which is the BetMGM short-field case the docstring itself warns about, with the guard asserting the field is fine. **A booksum below 1.0 is arithmetic PROOF of incompleteness on a mutually exclusive field** (true outcomes sum to 1 before any margin) and was unchecked: three prices summing to 0.65 returned `overround: -0.35` and scaled a 20% outcome **UP to 30.8%** — manufactured edge, the direction that costs money. Now refused, with the message saying the name check is what let it through. **B71b:** Shin's bisection collapses to z=0 on such a field and `fair_at` falls back to proportional scaling, while the result still reported `"method": "shin"` — a method that did not run. The label now states what was actually computed. 4 checks. |
| **B72** | `anchor_coverage` reported a clean bill of health when its OWN control came back empty | **DONE 2026-11-05** | `eligible` derives entirely from `odds_response`, so when the control was the thing that failed, `eligible == []`, which made `blank` False and left the per-book loop nothing to iterate — and `healthy` returned **True**, printing *"no silent dropouts: every book live to anchor did"* about books that were never observed. Confirmed against `{}`, `{"bookmakers": []}` and `{"error": "HTTP 503"}` beside a populated EV response carrying the known B60 signature; `anchor_coverage({}, {})` printed the same reassuring line. **This is the function whose entire purpose is to be the paired control, and the one failure it could not survive was its own control failing.** B46's shape — a guard asserting something it never measured — in the detector itself. Third state added: `control_usable`, measured before `eligible`, forces `healthy` False and prints NO USABLE CONTROL with instructions to re-pull. **B72b:** the blank branch set `silent_dropouts = [eligible[0]]`, naming the top chain book as a specific dropout when the measured finding is only "nothing anchored at all" — and the guarding check's own NAME said it should name itself rather than list a per-book dropout, while its assertion required `== ["pinnacle"]`. The name won; nothing outside the dataclass reads the field and `healthy` still catches it via `blank`. 9 checks. |
| **B73** | `team` and `pos` guards both tested truthiness, and NaN is truthy | **DONE 2026-11-05** | `build_meta` aggregates with `agg("last")` over a pandas frame, so an absent field arrives as `float('nan')`, not `None`. `if not a.team` therefore **passed** a NaN team; `a.team == b.team` then evaluated False, and two **same-team** rushing legs were routed to the OPPOSING branch and returned **−0.14, "opposing rushing in one event"**. Not a missed refusal — a confident wrong SIGN on a pair whose team is simply unknown. And the B69 fix shipped hours earlier was defeated the same way: `(recv.pos or "")` let a whitespace-only position through to `elif pos:`, returning **+0.31** labelled `"(   with a receiving prop, scored as WR)"` — a blank where the category should be, on the largest of the three coefficients, **arguably worse than the "(receiver)" label B69 removed**. A NaN position raised `AttributeError` out of `classify()`. New `_clean()` normalises both fields, since both answer the same "is this known" question and the B69 comment explicitly cited the team guard as its model. 5 checks. **Verifying this one also exposed a flaw in how I verify:** reverting the fix made the suite CRASH rather than FAIL, and a harness counting `^  FAIL` lines reported zero — a crash stops every later section, so the run prints "0 failed" over a partial count. The suite's own crash banner said so and my grep ignored it. The checks now catch and fail instead of exploding, and the revert produces 5 clean failures at the full count. |
| **B74** | Two checks that could not fail, and a band carried as inline literals | **DONE 2026-11-05** | Lesson 4 again, for the third time. (a) `chk("the same players at a longer product get a LOWER factor", 0.7705 < 0.7933 < 0.8355)` compared three **literals** — no code touched, cannot fail. Now reads the controlled triple out of `SGP_FACTORS_OBSERVED` and asserts it is still present there, so an edit to the measurements fires it. (b) `chk("the band's top is reachable in a real First TD market", stake_back_band(900)[...] <= 0.71)` asserted `0.71 <= 0.71` against a retyped literal; it would have caught a regression to the unreachable v=0.80, but its NAME claimed reachability, which it never measured. The band's three v values were inline literals in `stake_back_band`, so they are now `STAKE_BACK_V_OBSERVED` with provenance — same treatment `OBSERVED_SGP_FACTORS` got — and the checks pin the band to that constant. 5 checks. |
| **B75** | `tier_fallbacks`' `describe()` states a cause it never measured | **OPEN — found 2026-11-05 by review** | The property counts `opening_liquidity_tier is None`, which conflates "the anchor book quotes no tier" with "**nobody ever called `book_liquidity_tiers`**" — and `describe()` prints the first as fact: *"3 of 3 leg-slots fell back to the hardcoded 500 because their anchor book quotes no tier"*. `book_liquidity_tiers` **has no caller anywhere in the repo**, so that wrong explanation is the output on every run today, and it names Pinnacle — the one book the project's own notes say *does* quote a uniform tier. The leg already carries `fair_source`, so the data to tell the two cases apart is in hand and unused. Same shape as the bug this property was written to expose. Fix: distinguish never-measured from measured-and-absent, and say which. |
| **B76** | A derived liquidity tier can NARROW the net, against the asymmetry argued 300 lines above it | **OPEN — found 2026-11-05 by review** | `modal_liquidity`'s docstring is explicit that ties break high because "a tier that is too low misses an opening anchor... the exact failure this flag exists to prevent", and `TIER_MAX_TRUSTED` rests on the same reasoning — but the leg takes the derived tier unconditionally, with no `max(derived, OPENING_LIQUIDITY)` floor. On a maturing board with 20 lines still at the 250 floor and 8 raised to 400, `modal_liquidity` returns 250, and a leg at `fair_prob=0.5000, anchor_liquidity=400` comes back `anchor_opening=False` where the hardcoded 500 would have flagged it. **The suite currently blesses this** ("a derived tier below the constant narrows it"), so fixing it means changing that check deliberately. Compounding: `TIER_MIN_SAMPLE` counts non-null READINGS, not board coverage — a book reporting liquidity on 3 of 276 outcomes at 20 each yields a tier of 20.0, which would silence `anchor_opening` on every 0.5000 line above liquidity 20. The `book_liquidity_tiers` docstring claims books reporting no liquidity are simply absent; a book reporting ~1% of its board is present with a tier derived from it. |
| **B77** | `stake_back_ev`'s docstring says the caller must state the assumptions; the signature makes them optional | **OPEN — found 2026-11-05 by review** | "it is an argument rather than a constant and the caller must state it" is contradicted by `bonus_value: float = 0.65`, and `market_hold: float = 0.39` has the same shape. Both are, by the docstring's own admission, "one book, one market, one night" — and the default hold is a **First-TD-board overround applied to whatever odds you pass**. `stake_back_ev(-150)` returns `p_true 0.4317, EV +$0.888`; at a realistic two-way overround of 0.045 the same call gives `p_true 0.5742, EV +$2.337`, a 2.6x error on a market the docstring itself discusses. No range validation either: `bonus_value=3.0` returns `EV +$25.04` and `market_hold=-0.5` returns `p_true 0.2`. Fix: drop the defaults, or refuse any `odds` outside the First-TD range they were measured on, and bound both inputs. |
| **B78** | `bk.get("key") or bk.get("title")` manufactures a key that can never match the chain | **OPEN — found 2026-11-05 by review** | In `ff_props.anchor_coverage` and `ff_boost` intake. `title` is by construction the DISPLAY name, so the fallback yields e.g. `"Pinnacle"` against a lowercase `ANCHOR_CHAIN` — and on the B60 signature (Pinnacle carrying `title` and no `key`) the result is `live={'Pinnacle': 14}, eligible=[], silent_dropouts=[], healthy=True`, with the `blank` path silenced too. **The fallback manufactures an unusable entry instead of refusing**, and it does so in the dropout detector. The join is unnormalised on the EV side as well: a payload spelling `fair_source: "Pinnacle"` registers under a key nothing reads. In `book_liquidity_tiers` the same expression yields `{None: 500.0}` when a payload has neither field. Fix: normalise both sides (lower/strip) and treat a book with no usable key as unidentified rather than inventing one. |
| **B79** | Minor, from the same review | **OPEN — found 2026-11-05 by review** | (a) `token_note` with a decimal factor below 1.0 prints `"+2667 to -421"` — a positive number reading as long odds. Unreachable from `enumerate_candidates` (FLOOR=300) but reachable via `replace`, which is the only way to set `token_min_odds` at all. (b) `if mk.get("suspended_at") is not None: continue` treats an ABSENT key as live, while the docstring says "unsuspended" — benign direction for a dropout detector, but a `.get` default standing in for a measurement. (c) A test comment still carries the superseded composition explanation ("the factor depends on what the legs ARE, not how long they are") which `ff_boost.py:212-224` and its own neighbouring check both contradict. (d) **B55 is unreachable in normal use:** `enumerate_candidates` has no `token_min_odds` parameter and `token_note`/`token_minimum` appear in no `report()` or `describe()` path, so the "unknown is the dangerous state" signal is, in practice, total silence — compare `tier_fallbacks`, which the same diff did surface. |
| **E6** | Two correlation fall-throughs whose provenance cannot be established | **CLOSED 2026-11-06 — all twelve cells measured, see B114** | `_pair_r` returns `(0.0, "")` — priceable — for two **same-team** backs sharing one carry pool, while two *opposing* backs get −0.14 and refuse the slip. It also returns 0.0 for a cross-team PASS×RECV pair. The table comment says everything absent measured ~0.00 over 43,228 pairs, but nothing records whether same-team RB pairs or cross-team passing×receiving pairs were in that sweep at all. **This is E3's unreproducibility showing up as an operational question rather than a documentation one**: the honest default for a pair nobody can confirm was measured is unmeasured, not zero. Settle it when E3 rebuilds the table. **The RECEIVING half went live on a PLACED BET and is now measured** (`measurements/e6_same_team_receivers.py`). Two JAX receivers sat in one DraftKings SGP on 2026-11-05 and the engine priced them as independent off this fall-through. Measured over 30,681 same-team receiver pairs, 2023-26, min 6 games: **WR x WR receiving yards r = +0.0090 (n=12,622)**, WR x TE +0.0144, TE x TE +0.0201 — so the 0.0 is a genuine approximation, not an unexamined guess. And on the quantity a parlay actually needs, joint threshold crossing: independent product 0.1501 against an **observed joint of 0.1474, a lift of 0.9817x** (phi -0.0116). **So the fall-through is very slightly OPTIMISTIC** — two same-team receivers cross together a touch less often than independence implies, because competing for targets just outweighs sharing a good passing day. Applied to that bet it moved the quoted EV from **+1.83% to -0.04%**, i.e. from a small edge to break-even, which is the scale that matters: a 2% lift error is worth about 2 points of EV on a three-leg slip. The same-team RB x RB carry-pool pair and the cross-team PASS x RECV pair are still unmeasured and still return 0.0. |
| **B68b** | The guillotine's matrix guards team but not position — the defect the same diff fixed next door | **DONE 2026-11-06 — see B116; the filed defect was the smaller half of it** | `correlation_matrix` has `if ti is None or tj is None: continue` with no `pi`/`pj` equivalent, and `SAME_TEAM_CORR.get(key, 0.0)` below it. A player whose meta is `("KC", None)` — team joined, position did not, which is exactly what a partial `build_meta` join produces — yields a silent **0.0** for what may be a QB/WR pair at +0.31. **The same diff added a 27-line comment block immediately above these tables in this file and left the hole in the function underneath it.** And `is None` does not catch the pandas miss either: `agg("last")` yields NaN, which is not None, so a NaN team slips past line 220 and is caught only accidentally by `ti != tj`. Same `_clean()` treatment as B73, applied here when E3 gives this module its own table. |

### Found by the eleventh deployment test (2026-11-05, TNF JAX@BAL) — the five fixes on live payloads

All five shipped fixes behaved correctly on real boards. B67 took **+0.20** on
the RB-receiving pair and labelled itself PROVISIONAL; B69 printed
`CB with a receiving prop, scored as WR` for Travis Hunter instead of hiding
behind "(receiver)"; B71's refusal fired on BetMGM's 23-outcome and Kalshi's
28-outcome First TD fields and was quoted verbatim; B72's new
`control_usable` field reported True on both pulls with a real control. **No
leg came back with an empty or NaN team/position**, so B73's refusal path was
not exercised live — it remains fixture-only.

| # | Item | Status | Notes |
|---|---|---|---|
### Found by an INDEPENDENT REVIEW of the B84/B85 diff, 526 checks green (2026-11-05)

Dustin asked whether a retest was needed. Measured answer: no — a project-thread
test had a **28% chance of hitting B84's new path** on a board with 4 flagged
legs, and B85's new branch only fires on a deliberately polluted dict. So the
likely outcome was a clean-looking test confirming nothing. The reviewer was
run instead, and returned eight findings, **four of them defects in the two
fixes shipped hours earlier.** This is the second consecutive round where the
reviewer found real defects in code the suite had just blessed.

| # | Item | Status | Notes |
|---|---|---|---|
### Found by the B82 deployment test (2026-11-06) — and the biggest finding was not B82

| # | Item | Status | Notes |
|---|---|---|---|
### Found by the B98 re-test (2026-11-06) — a torn repo, and what it cost

| # | Item | Status | Notes |
|---|---|---|---|
### Found grading the first real placed bet (2026-11-06) — JAX@BAL, lost all three legs, -$5.13

| # | Item | Status | Notes |
|---|---|---|---|
| **B119** | The factor note cited a QB-stack range on every correlated slip, and the live slip disproved its own claim | **DONE 2026-11-07** | `factor_note` printed *"the books' factors have tracked this table closely (0.61-0.65 on QB stacks)"* for **any** correlated structure. Two faults, both visible in one round's output. The range is a QB-stack observation and means nothing beside a backfield pair: printed against a **0.921** factor on two same-team backs it invites reading 0.921 as generous when the comparison is to a different kind of slip. And the general claim was contradicted by the slip beside it — **DraftKings charged 0.686 on an opposing-QB pair measured at +7.22%, against 0.672 on a true QB stack measured at +31%**: the same haircut for four times the correlation, which is the opposite of tracking the table. The range is now cited only where it was observed, a mixed slip is told the range covers only PART of what it is charged for, and the general claim is gone. **The 0.686-vs-0.672 observation is one event and is NOT a finding** — logged here to re-check, not acted on. |
| **B118** | The B93 hold note's stated reason was false in 100% of the cases it could reach | **DONE 2026-11-07** | The loud note read *"p_cash here is the PRODUCT of the de-vigged legs and that is not the joint for CORRELATED legs"*. But `slip_hold` returns None unless `structure.priceable`, and priceable means **every pair is MEASURED INDEPENDENT** — so the note could only ever fire on slips where its own stated reason was false. It fired, on `***`, on the **one slip of four that got an EV** in a live round. **B93b's firing-rate check missed it because it compared cross-game against same-game and never independent against correlated** — the axis the reasoning actually turned on. A correlated slip has no hold at all, which is now pinned by a check. What really drives a below-band hold is the **anchor**: the band is a population figure, and a priceable slip under it is either a better price or resting on soft fair numbers. In the live case all three legs were exactly 0.5000 opening priors with no liquidity, so `p_cash` and the hold were nearly meaningless. The note now branches on `anchor_immature` — loud and actionable when the anchors are soft (naming which leg, and saying to re-pull before quoting the EV), and a plain statement that the price beats the population band when they are not. Lesson 66. |
| **B117** | A verdict the engine logged for the OTHER side was reported as absent | **DONE 2026-11-07** | `log_edge` records `edge.side` — **the side the MODEL prefers** — while `log_bet` records the side the slip actually took, and in one live round **5 of 12 legs differed**. B110 had just added `side` to the gap detector's match key, correctly, so those legs came back `state: missing` with `!! NOT in this log` and a printed remedy of "call log_edge for slip legs too" — which **would have created a duplicate rec for a verdict that was already there**. B39 again, inside code written the same day, and the regression the match-key fix introduced. Worse, it buried the most actionable thing on the slip: the engine's own lean was AGAINST two of the three legs in the slip that priced. Now a third state, reported first and loud: *"N bet legs take the side the ENGINE DID NOT PREFER"*, with the standing clarification that a CLEAR verdict means the veto found nothing wrong with the leg, **not** that the model likes the side you bet. Same-side legs still link silently and a genuinely absent verdict is still MISSING. 7 checks. Lesson 67. |
| **B116** | B68b's filed defect was redundant; the real one was the join beside it | **DONE 2026-11-06** | B68b was filed as "no `pi`/`pj` guard beside the `ti`/`tj` one, so `("KC", None)` yields a silent 0.0". Measured first, as B68 did for its own sign error. **(1) The filed premise does not fire from the named source**: `build_meta` over 2026 weekly returns 1,732 players with **zero** missing fields, so no `("KC", None)` arrives that way. **(2) The real hole is one line up.** `meta.get(name, (None, None))` is a **RAW NAME** lookup — in the module whose own `normalize_name` docstring reads *"THIRD occurrence of a name-join bug in this project. Never match player data on a raw name"* — while `_correlated_draws`, two lines away in the same call path, resolves the same player through `resolve()`, which normalises. One function, two join policies. **96 of those 1,732 names carry a suffix whose plain spelling is not a meta key**, so a roster source spelling "Brian Thomas" for "Brian Thomas Jr." missed, and a miss dropped QB x WR from **+0.3100 to +0.0000**, confirmed on a real PIT stack. **(3) The guard as filed is INERT**: `_meta_field` maps NaN, blank and None alike to None, no table key contains None, so the keyed lookup already misses — removing an explicit `if pi is None` changed no behaviour and no check could fail on it, which in this project is worse than no guard because it reads as coverage. It was deleted and the mechanism documented instead. **The actual defect was the SILENCE**, not the 0.0: once a position is genuinely unknown, 0.0 is the right number; what was wrong is that nothing said so. `correlation_coverage()` now names unresolved players, `Result.correlation_unresolved` carries them out and `report()` prints them. **Effect measured before prioritising** (`measurements/b68b_position_join_effect.py`, 10 deliberately QB-stacked teams, 60,000 sims): dropping the correlation signal entirely moves the best lineup's P(elim) by **-2.05pp with a 4.15pp max shift** across 260 lineups against a **0.10pp** noise se — so the sim is genuinely sensitive — while at the measured 5.5% miss rate the shift is **+0.21pp**, about 2 se, and **the recommended lineup was identical in all three fixtures.** Same verdict as B68 and reached the same way: real silent bug, low operational stakes today. Also NaN handling: a NaN team passed the `is None` guard and was read as a DIFFERENT team, which is B73 in `ff_boost` one module over. 18 checks; **three of the first five reverts did not bite** and had to be rewritten — the inert guard, a collision check that hit the exact-match fast path and never reached the canon map, and a report path nothing exercised. |
| **B115** | I truncated `ff_boost.py` to half its length with a patch script, and the suite is the only reason it was caught | **RECOVERED 2026-11-06** | A patch script did `old = s[s.index(marker):]` and replaced it — a slice running to **END OF FILE**. That silently deleted 537 lines: `classify`, `price_candidate`, `enumerate_candidates`, `report`, `stake_back_ev`, `stake_back_band` and every `Candidate` property below `hold_band_reason`. `python3 -c "import ff_boost"` **succeeded**, because what was left was syntactically valid, so the usual smoke test said nothing. The suite caught it: `AttributeError: 'Shortlist' object has no attribute 'tier_fallbacks'` with a crash marker naming the section. Recovery was not clean either — grafting the tail back from `git show HEAD:` restored a **STALE** tail, because HEAD predated today's work, so B95/B99b (`stake_back_ev(fair_prob=)`) and B93/B93b (`hold_vs_band`, `hold_band_note`, and `report()` printing it) came back missing and had to be rebuilt **from the suite sections that specify them** — which is the second reason the suite earned its keep today. Final state verified by exact parity: 734 checks, the same count as before the truncation, every DONE item intact. Lessons 62 and 63. |
| **B114** | Eight of twelve market-side pairs were priced as independent without anyone having measured them | **DONE 2026-11-06** | `_pair_r` gated four canonical pairs and returned a bare `(0.0, "")` for everything else, so a MEASURED zero and an unexamined fall-through were **the same value with the same empty label** — B53's family, B81's specific complaint, and E6's open question. Closing the gate on the unmeasured ones first produced a worse bug: same-team **rushing x receiving**, the commonest same-game shape there is, went to "never measured" and refused an EV. So all twelve cells were measured in one sweep instead (`measurements/e6_full_pair_sweep.py`, nflverse 2023-2026 REG, z-scored per player-season, min 6 games, min 200 pairs), with a **CONTROL that voids its own run**: same-team PASS x RECV must recover near the table's +0.31 or nothing is admissible — it recovered **+0.2462**. Two results contradict the mechanism stories told about them. **(a) Same-team RB x RB is POSITIVE**, lift **1.0992x** over 3,815 pairs. The carry-pool argument — two backs splitting fixed carries should be negative, more so than the -0.14 given OPPOSING backs — is **wrong**: game script dominates, a team that runs 35 times feeds both and one that runs 18 feeds neither. **(b) Same-team RUSH x RECV is -1.22%** over 28,499 pairs, effectively independent, so the intuition that "same team means correlated" would have refused a large share of real slips for no measured reason. Also newly gated: **opposing QB x QB at +7.22%**, the shootout stack, never measured before. The gate threshold is 3% because that is where the **empirical gap** is — five pairs between 4.60% and 19.93%, six at or below 1.75%, nothing between — and a suite check fails if a future measurement lands in that gap, so the number must be re-argued rather than inherited. Firing rate measured before shipping: 3-leg same-event slips priced as independent went from **50% to 27%**, every removal driven by a measured deviation, **zero refused as unmeasured**, and receiver-heavy slips — the shape that actually gets bet — still price. The canonical `SAME_TEAM_CORR`/`OPPOSING_CORR` values are **deliberately unchanged**: B68 is explicit that pasting one filter's levels over them is how that table became unreproducible, and E3 owns re-deriving it. Opposing RB x RB recovered -0.0804 against the table's -0.14 — right sign, ~1.7x overstated, agreeing with B68's independent fantasy-score sweep. **A lookup-order bug nearly hid all of it**: `pair_lift` sorts the two sides, and two table keys were written unsorted (RECV sorts before RUSH), so the commonest shape was unreachable and refused — a key-order bug reads exactly like an honest refusal, so an import-time assertion now rejects an unsorted key. 32 checks, 6 reverts failing by name. |
| **B113** | The B107 guard was on the read side only, so it closed nothing | **DONE 2026-11-06** | The project-thread test ran clean — no raise, none of the three sentinel lines — and then said the thing that mattered: **"the guard fired for the weaker reason (no id) rather than the stronger one (measured clustering), and it would have fired identically had those four been four genuinely independent games."** Correct. **0 of 101 `rec` records in the live log carried an `event_id`**, so all three calibration rows printed CANNOT BE READ and the scorecard said nothing — and `event_id` defaulted to `None`, so nothing ever made the caller decide. An omission and a deliberate `None` were the same keystroke-free outcome, which is **D16 verbatim: unchecked state must not look like checked state.** Both loggers now **raise** on an omitted `event_id`, keyword-only so it cannot be passed by position, with the consequence in the error text, not just the rule. An explicit `event_id=None` is accepted — that is a decision on record. The same test also found `log_recommendation` was **the least-signposted function in the module**: `log_edge` needs an `Edge`, the only documented route to one is `prop_edge`, which needs a model estimate and a screened quote, so a backfill or hand-entered verdict had **no documented path at all** and the session resorted to reading the dataclass and hand-constructing one. My own text mentioned `log_recommendation` only as "a hand-built call" the probability guard "bites" — discouragement where signposting was needed. Now documented as the no-pricing entry point, with `model_p=None` as the honest value for a verdict whose probability was never recorded. **And writing that sentence broke it**: `_check_prob` raised on `None`, so the instruction I had just written was a worked example that does not work — B106 for the second time, caught this round only because I ran the call I had documented. `None` now returns `None`, a percentage is still refused, and the backfill was run end to end before shipping. 13 checks, 3 reverts failing by name. Lesson 60. |
| **B112** | My own B110 fix crashed the entire report on one malformed historical record | **DONE 2026-11-06** | Found by asking the right question before answering "should we test": **every synthetic log the 714 checks run against was written by me this afternoon, and the real log is 69 records deep across six schema generations.** Fed plausible historical shapes, `_key`'s `float(leg["line"])` hit a hand-written `"n/a"` and raised `ValueError` out of `unlogged_bet_verdicts` — which `rec_summary` calls first, so **the whole engine scorecard died on one bad leg in one old bet.** Two of the three crashes were introduced by me today; the third, `bet_summary` iterating `b["legs"]` with a non-dict leg in it, was pre-existing and had simply never been hit. A report that cannot survive the data it is reporting on **fails at exactly the moment it is needed** — Monday, after a slate, with no second chance before the next one. Now: `_num()` returns None rather than raising, `_legs()` skips non-records, and the calibration block separates USABLE verdicts from those with a missing or out-of-range `model_p` and **names the count** instead of either crashing or silently showing fewer. `_check_prob` guards the write path only, so records that predate it are a read-path problem by construction. 9 checks against a deliberately filthy six-generation log. **Lesson 14 violated for the fifth time in the same session**: three of these reverts crashed the suite instead of failing it, because the checks asserted on report text evaluated at module level — a `_out()` helper now makes a broken report a FAILURE, not a dead run. |
| **B111** | My own firing-rate measurement was wrong, in the permissive direction | **DONE 2026-11-06** | Lesson 51 says measure a new flag's firing rate before shipping it. I did, and then **described the wrong input.** I wrote *"it still fires at n=46 from a single slate"* into both `PROJECT-INSTRUCTIONS.md` and this backlog as evidence the gate catches clustering rather than small samples. The test behind it gave all 46 verdicts **one event id — one GAME.** A real 13-game Sunday slate gives 13 events and reads fine. The companion claim, *"clears at roughly 20 graded verdicts spread across games"*, was also wrong: the threshold is **per bucket**, so it clears at 5 distinct games IN A BUCKET. Re-measured, full coverage: 9 verdicts over 1 game refuses everything, 15 over 5 games still refuses one bucket, **24 over 8 games reads**, 46 over 1 game never reads at any volume. The number was real and the label was wrong, and the error argued the gate was stricter than it is — which is the direction that gets a weak guard trusted. Lesson 57: measure the thing the claim is about, and state the input in the words the claim uses. |
| **B110** | Eleven defects in the B107/B108 fix, found by the independent reviewer after 684 checks passed | **DONE 2026-11-06** | **Third reviewer pass in a row to find betting-path defects inside the same morning's work** — four here, two of them inside the B107 gate itself. Worst first. **(1) The gate was non-monotone in the worst direction.** With partial event coverage it fell back to the player count: five verdicts from ONE game printed `TOO CLUSTERED` with all five ids present and **`overconfident by 77%` once three ids were deleted.** Strictly less information, strictly more confident — and partial coverage is the NORMAL state for weeks, because pre-B107 records have no id and are not to be backfilled, so the gate would have been inert for exactly the transition it was built for. `_independence` is now three-valued: a count, or `None` with a reason, printed as **CANNOT BE READ** and never as a weaker TOO CLUSTERED. **(2) Zero coverage printed a clean confident line with no annotation at all** — less measured than partial, yet it read better, because silence about events reads as "no clustering". **(3)** A leg carrying `engine_model_p` but no `engine_tier` was invisible to the gap detector, a false negative in the direction that flatters the model. **(4)** The detector keyed on `(bet_id, player, market)`, so one rec suppressed **every** leg for that player and market — and a ladder is exactly where two legs share both and differ in tier, which the live log has (Flowers 47.5/48.5, Bateman 15.5/14.5). Now keyed on line and side too. **(5) B39, in my own new message:** `if r.get("bet_id")` meant a verdict logged at verdict time — the documented flow, before the bet exists — was reported as `NOT in this log`, and the remedy printed was to log it again, **the double count the function exists to prevent.** Split into MISSING and UNLINKED with different remedies. **(6)** "every number above" was printed above nothing but the header. **(7)** The detector compared raw player names, the one join this project forbids; a local normaliser rather than `ff_props.norm_player`, since importing it would put `ff_props` in `ff_betlog`'s shipset (lesson 41, B99/B100), with a check asserting the two still agree so a drift fails by name. **(8)** The clustering rule covered one of the four rates the report prints; the PASS line — the number B108 is *about* — printed `Well above it means the guard is too tight` ungated, advice to loosen a working guard. **(9)** The top bucket excluded 1.0 and nothing reconciled bucket totals against the graded count, so a `model_p` of 77.0 instead of 0.77 **dropped all six verdicts and printed an empty calibration header**; now refused at the door. **(10)** `event_id` stored raw: `{"53166", 53166}` is two events to a set and integer `0` is falsy, so three games reported as "5+ events" and the verdict flipped. **(11)** `bet_summary`'s "record is not the signal" caution lived inside the CLV branch, so with no closing lines — the log's actual state — a 33% hit rate and **+108% ROI printed with no caution of any kind**; and a slip's game lives on its legs, so the rec-level counter read the wrong shape and said "0 players". 30 new checks, each of the eleven failing by name on revert. **Three of section 51's own checks had pinned the broken behaviour as correct** — lesson 58. |
| **B109** | A missing nflverse weekly row was about to be read as a scratch | **DONE 2026-11-06** | Caught live by the grading session, before it wrote the grade — the one place in this loop where the two readings diverge materially. nflverse's weekly table carries only players with a recorded stat, so **an active receiver who drew zero targets and an inactive player are the same row: none.** Brian Thomas Jr. had no Week 9 row; his roster status said ACT, which means dressed, not played. **Snap counts settled it: 19 offensive snaps, 34%.** He played and caught nothing, so the number is 0 and the Over is a LOSS, not a VOID — and a VOID would have dropped the verdict from `rec_summary()` entirely, which counts only WIN/LOSS, **costing the model credit for a PASS it got right.** One row away sat Bryan Thomas Jr., a Jacksonville DE with 0 offensive snaps: the same name, separated only by distinct PropLine ids, which is the standing reason the join never runs on names. Written into the grading-discipline section rather than left as a one-time save. Lesson 55: "not present in the data" is a state, not an answer. |
| **B108** | Every number on the engine scorecard was computed on a silent subset | **DONE 2026-11-06** | `log_bet` stores `engine_tier` as a field on the leg; `rec_summary` reads `live_recs()`, which filters `kind == "rec"`. **A leg bet on the engine's own say-so therefore never reached the engine's own scorecard.** The three legs of slip `7a5f4b8e` all carried `engine_tier: PASS` and all three lost, so the PASS column read **2/7 (29%) when the honest figure was 2/10 (20%)** — the omission *flattered* the model by hiding three correct PASSes, which is the direction that does real damage, since it argues for loosening a guard that was working. Fixed by making the reader name what it cannot see: `unlogged_bet_verdicts()` finds bet legs with an `engine_tier` and no linking rec, and `rec_summary()` prints the gap and the legs at the top rather than quietly computing on a subset. **Deliberately not merged** — a session calling both `log_bet` and `log_edge` would then be double-counted, so the match is on `(bet_id, player, market)` and the instruction now says to call both with `acted_on=True` and `bet_id` set. 7 checks. Lesson 54. |
| **B107** | `n=4` was one football game, printed as four independent failures | **DONE 2026-11-06** | The eye-catching line in the Week 9 grading output was `70%-85%  n=4  said 77%  went 0%  overconfident by 77%`. **Three of those four verdicts were Baltimore pass-catchers — Flowers twice, Bateman once — on the night Lamar Jackson and Huntley both went to IR.** One injury, three correlated legs, and a calibration row that read as three separate indictments of the model. Across the whole graded set, 9 verdicts covered **6 distinct players**, with Henry, Bateman and Flowers each appearing at two lines. The reading session caught this itself and said so, which is the only reason the number was not believed — the code could not see it at all, because **recs carried no `event_id`**. Now: `log_recommendation` and `log_edge` take an optional `event_id` (optional because older records do not have one and **backfilling the game from a date would be inventing data**), and the calibration row prints distinct players and distinct events beside `n`, printing **TOO CLUSTERED TO READ** in place of a verdict below 5 independent units. The unit is the EVENT where every verdict in the bucket carries one and the player otherwise — five pass-catchers in one game is one game, and a player-only gate would have waved that through. Partial coverage reads `2+ events (2 of 5 verdicts carry one)` rather than `2 events`, which would assert what nothing measured (B39). **Firing rate measured before shipping** (lesson 51): every bucket at today's 9 verdicts, clear by ~20 spread across games, and still firing at n=46 from a single slate — so it gates clustering, not sample size. 17 checks; 5 separate reverts each fail by name. Lesson 53: a count of observations is not a count of independent observations. |
| **B106** | The documented `grade_leg` call bypassed the guard that had just been added to it | **DONE 2026-11-06** | Found by checking the instructions against the new code rather than against themselves — the fourth time that check has turned something up. The weekly-rhythm line showed `bl.grade_leg(rec["id"], i, result, closing_odds=...)`, **without the two arguments B102 added**, so the circular-CLV guard would never have fired on a session following the documented call. **Exactly the B82/B98 shape: a worked example that quietly disables a protection**, and the second time in two days that the instruction a session actually reads was the one steering it wrong. Also fixed in the same pass: the `propline_grade_clv` section told a session to report `ev_vs_close_pct` and said nothing about checking `fair_source` first, so it actively directed the circular number; B104's point-vs-name diagnosis and B103's untrustworthy `resolution` had no entry at all; and B105's two-pass grading was nowhere, while the weekly rhythm implied one pass. All five now sit at the line where the work happens, verified by walking back to the nearest heading. **Standing check from here: after changing a function's signature, grep the instructions for every call of it.** |

| **B102** | "A book is not its own reference" was never applied to the GRADING path | **DONE 2026-11-06** | The project's oldest rule — *"RIGHT: fair line from a sharp anchor, price from the book you'd bet. WRONG: de-vigs DraftKings against itself"* — and grading had no guard for it, because there the number arrives **pre-computed from an external grader** and the circularity is invisible. Measured on the real slip: PropLine's `grade_clv` returned `ev_vs_close_pct` of **-4.86% and -3.70% with `fair_source: draftkings` on both matched legs — the book the bet was placed at.** So the figure was largely measuring DraftKings' own 5.6% two-sided hold rather than whether the price taken was good. Re-graded against the best **same-point** non-DK close the picture was worse: Strange -4.13% (BetMGM 33.5), Hunter -6.52% (FanDuel 8.5), Washington **≤-4.96% and truly worse** — no non-DK book quoted 63.5 at all, and the session correctly did NOT snap to Pinnacle's 61.5 (D18). Three-leg average at best **-5.20%**, so the reported -4.28% was the most flattering reading available. New `check_clv_source(book, fair_source)`: refuses a fair line from the bet's own book, flags a MISSING source as its own problem (unknowable is not clean), and `grade_leg` now records both and REFUSES the write rather than putting a number in the log that reads as measured value to every later reader. Book names are normalised, since `"DraftKings"`, `"draft kings"` and `"DRAFTKINGS"` all arrive across endpoints. 11 checks, 6 failing on revert. |
| **B103** | PropLine's `resolution` field contradicts itself inside one response | **OPEN — upstream, 2026-11-06** | In one `grade_clv` payload, Strange **Over 33.5** came back `resolution: "won"` with `actual_value: 22`, while **Over 34.5** came back `"lost"` with the **same** `actual_value: 22`. **22 is plainly under 33.5, so "won" is wrong** — and the two gradings are mutually inconsistent inside a single response. The session settled from the box score instead and was right to. This extends the project's existing never-trust-their-grader posture from names to **resolution output**: settle locally from the box score, and use `resolution` for nothing. Not fixable here; record it so no future session treats that field as authoritative. |
| **B104** | A grading reason string blamed the name when the cause was the point | **OPEN — upstream, 2026-11-06** | Strange's leg returned `no_outcome_for_selection`, which reads as a player-matching failure. The real cause: **DraftKings closed at 34.5 while the bet was at 33.5.** The session proved it by re-running the same selection at 34.5, which matched immediately. Same family as B90 and B80 — a message asserting a cause nobody measured — but upstream, so the fix is on our side: when a grade returns `no_outcome_for_selection`, re-query the player's closing lines and report whether the POINT moved before reporting a name problem. Worth a helper, since a wrong diagnosis here sends the next session chasing a name-join bug that does not exist. |
| **B105** | Settlement is impossible the same night, and nothing said so | **OPEN — 2026-11-06** | The grading instruction says to settle against nflverse by player id. **nflverse had ZERO Week 9 rows** the night of the Week 9 opener, so that was impossible, and the session fell back to PropLine's box score — a different source than asked for, correctly flagged. The closing-line window and the nflverse window do not overlap: closing lines must be pulled within hours (the event delists — `price_sgp` returned `404 event_not_at_book`, so **no closing SGP price exists for a same-game slip once the game ends**), while nflverse lands days later. So grading is inherently TWO passes: closing lines now, box-score settlement now, nflverse confirmation later. The instructions should say that rather than implying one pass, and a re-settle against nflverse by GSIS id should be scheduled rather than assumed. |

| **B101** | The fallback instruction I wrote last round steered toward the weaker join | **DONE 2026-11-06** | Three gaps in the Touchdown-scorer section, found by checking the instructions against what the session actually did rather than against what they say. **(1) I told it to join on the name.** The B99 fallback paragraph ended "key it with `norm_player`" — in a project whose standing rule is never to join on a name, and in a section that had just explained `flatten_odds` carries `player_id`. The session ignored my advice and used the id, correctly: **Bovada appends a team parenthetical to all 27/29 of its names, so the cross-check column came back silently EMPTY on a name join**, and the id matched 23/23 and 24/24 with no DraftKings id missing from Bovada. Now: id first, `norm_player` only where the id is absent, which is D/ST rows and is the sole reason the name join had marginally higher recall. **(2) The fallback said "about fifteen lines" and never said what they must do.** The session's own audit: its loop lacked every refusal `field_from_odds` applies, and of its three copies **only one had a duplicate-key guard.** The minimum set is now enumerated at that line. **(3) Nothing said to write it once** — three scripts, three copies, divergent. **(4) `screen_quotes` was never mentioned in the TD section at all**; the generic "screen every quote" instruction sits in two-sided-pricing context, so a First TD session never reached for it. It hand-eyeballed `suspended_at`, published, ran the real function in diagnostics and said *"I had no right to that confidence when I gave you the boards."* Now required before publishing, with a note that a near-universal `one_sided` list is expected on a YES-only market and is not a finding — the signal to read is `scratch_risk`. |

| **B100** | I named a file coupling in a caption and then shipped half of it | **DONE 2026-11-06** | **Mine, and it cost three test rounds.** `ff_boost.py` went out with the caption *"IMPORTANT: ff_props.py and ff_boost.py must be committed together — that's the bug this round fixed"* and **`ff_props.py` was not attached.** The repo is updated by uploading files one at a time, so a partial commit is the normal failure, and commit `0c3ad82` duly shipped the B82 `ff_boost.py` without its `ff_props.py` — leaving `ff_boost` unimportable for the third session running. B99 solved DETECTION: the session got the actionable error, did not shim, and used the documented `flatten_odds` fallback. What was still hand-written was **the list of files**, by me, from memory, in a caption. `shipset.py` now computes it from the import graph: `python3 shipset.py ff_boost.py` answers `MUST ALSO SHIP: ff_backtest, ff_props`. **Both directions are reported** — ship a module without what it imports and it fails loudly, ship it without its importers and they run against a stale copy, which is the quieter and worse case. One hop by default, since the transitive closure over seven modules is "all of them" and that is not advice. 7 checks, including the exact ff_boost→ff_props coupling that caused this. **Standing rule from here: when any `.py` changes, send the shipset, not the file.** |

| **B99** | The B82 refactor made `ff_boost` unimportable on a half-updated repo, and the error said nothing useful | **DONE 2026-11-06** | **I caused this.** Moving `norm_player` from `ff_boost` to `ff_props` (B82, for lesson 7 — one home) made `ff_boost` depend on a NEW `ff_props`. The repo is updated by uploading files one at a time through the GitHub web UI, so **a half-updated clone is the normal case, not an edge case.** The test session's clone had the new `ff_boost` and the old `ff_props` and got a bare `ImportError: cannot import name 'norm_player' from 'ff_props'`. From that it concluded three functions were missing, built a shim, and **two of those three claims were wrong** — it later found `flatten_odds` present and `book_liquidity_tiers` present at `ff_boost.py:330`, having tested only `hasattr(ff_props, ...)` and reported absence from one module as absence. The import now raises with the diagnosis: half-updated repo, these two files ship together, do not shim. **The refactor was still right** — duplicating `norm_player` is B68's shape — but a cryptic failure at module load cost more than the refactor saved, and the fix is the message, not a retreat. |
| **B99b** | `market_hold` is inert once `fair_prob` is passed, and was silently so | **DONE 2026-11-06** | Caught by the session's own audit. It headlined *"measured `market_hold`=0.3195, not the 0.39 default"* and then measured the figure identical at every hold from **0.10 to 0.542** — because it had also passed `fair_prob`, which replaces the derivation the hold feeds. The argument did nothing and nothing said so. `p_source` now reads `measured (fair_prob given, so market_hold 31.9% was NOT used)`. Worth more than it looks: measuring the hold matters a great deal with no per-leg fair probability and not at all with one, and the write-up credited a conclusion to the wrong input. 3 checks. |

| **B98** | The B82 helpers existed, were documented, and the session still hand-rolled — because the guidance was in the wrong section | **FIXED, STILL UNTESTED after THREE rounds — see B99/B100** | **A clean negative result, and the fault is mine twice over.** The helpers shipped, the instructions were pasted, and the session still wrote its own `field()` walking `bookmakers[].markets[].outcomes[]`. The damning evidence is its own self-audit: it listed *"not called, and should have been: flatten_odds, screen_quotes, american_to_prob"* **while auditing the exact code `field_from_odds` was built to replace** — it did not know the function existed. **Cause 1, placement.** The "NEVER build a field by hand" block sat at line 1316, inside *"Stake-back tokens are NOT boosts"* (1233-1412). A session working a First TD question reads *"Touchdown-scorer questions"*, which begins at 1412 — **after it. Cause 2, and the worse one: the section it DID read told it to hand-roll.** It said *"**First TD** — `devig_field(...)`. Pass `{name: american}` from ONE book"* and stopped. That is an instruction to construct a dict with no word on where one comes from, so it constructed one. **Systemic, not a one-off: FOUR of that day's instruction edits — field extraction (B82), liquidity (B92), Drive verification (B91) and the hold/band verdict (B93) — all landed inside the stake-back section**, because each was inserted by `replace()` anchored on whatever string I had last been reading rather than by what the section is about. All four moved to the section that owns them, verified by walking back to the nearest heading; the field guidance now sits at the exact line that used to say "pass a dict". **Nothing was wrong with the code, and a second test round would have found nothing** — the instruction was correct, correctly worded, and filed where the reader never went. **The re-test could not settle it either: the clone did not have `field_from_odds` at all** (B99), so whether the moved guidance gets followed is still an open question. What the re-test DID show is that the split created a new gap — the Touchdown-scorer section named `field_from_odds` and nothing else, so a session that could not find it fell back to a hand loop rather than to `flatten_odds`, which was present and sufficient. The fallback is now named at that same line. **Round 3 (2026-11-06, commit `0c3ad82`): torn again, for the reason in B100 — I never attached `ff_props.py`. So `field_from_odds` has never once existed in a clone a session ran against, and its adoption is still unmeasured.** What round 3 DID show is that the B99 work landed: the session hit the new import error, **did not shim it** ("per the error's own instruction"), used `flatten_odds` as the documented fallback, and joined across books on **`player_id` rather than name** — which is better than `norm_player` and is the project's own never-join-on-a-name rule. The remaining failure has changed shape and is now precisely what `field_from_odds` fixes: **it wrote the same `flatten_odds`→dict loop three times in three scripts, and only one of the three carried a duplicate-key guard.** Not a bypass any more — a duplication that diverged. |

| **B95** | `stake_back_ev` derives `p` from a UNIFORM hold, which punishes the leg you shopped hardest | **DONE 2026-11-06** | Surfaced by the test session, unprompted, and it is the most valuable thing to come out of a deployment test so far. `p = implied(odds)/(1+market_hold)` assumes the leg carries the FIELD'S AVERAGE margin. **Measured on a live First TD board, per-leg margins ran +0.01pp to -3.52pp inside ONE game.** Chase Brown's BetMGM +525 carried almost none, so the derivation put him at p=0.1213 against a measured fair of **0.1601 — 24% low — and his $10 token at $3.29 instead of $5.47.** The error has a direction, which is what makes it bad: **shopping a price is exactly what makes its margin unrepresentative, so the better you shop, the more the function understates you.** Fixed with a `fair_prob` override on both `stake_back_ev` and `stake_back_band`, used verbatim, validated to (0,1), and the result now carries `p_source` so a derived p and a measured one are no longer indistinguishable. **Second half, and it corrects a documented project result:** the docstring stated flatly that "the raw bet's EV does not depend on the odds at all", proved by substituting `p = 1/(d*(1+h))`. **That substitution IS the uniform-hold assumption.** With measured per-leg probabilities the base EV is not constant — on that board it ran -$1.41 at +300, **+$0.01 at +525** and -$0.37 at +1450 — so **price QUALITY beats price LENGTH once margins vary**: Chase Brown at +525 paying ~0pp returns $5.47 where Tee Higgins at +800 paying 2.05pp returns $4.07. Shorter odds, better EV, against the standing advice. Both halves pinned: a check asserts the base EV IS constant under a uniform hold, and another that it is NOT with measured probabilities. 10 checks, 9 failing when `fair_prob` is ignored. |
| **B96** | Measured First TD overrounds are materially tighter than the recorded ones | **OPEN — found 2026-11-06** | Three Sunday boards measured **+29.8% to +34.5%** (DraftKings 1.2980 / 1.3195 / 1.3223, Bovada 1.3095 / 1.3448 / 1.3389), against **39.4% and 54.2%** in the project notes. So `stake_back_ev`'s 0.39 default is not merely unprovenanced (B77) but is now high by roughly a quarter against three fresh boards, and `MAX_OBSERVED_OVERROUND`'s refusal message still says "real boards measured 1.35 to 1.57" when the observed range is now **1.30 to 1.57**. Neither is urgent — the diagnostic ceiling is an upper bound and still clears everything — but the message is stale and the default is worse than it looks. Re-measure across more boards and replace the default with a measured central value, or drop it and require the argument, which B77 already proposes. |
| **B97** | Kalshi was reported unusable for the wrong reason, by a hand-roll | **OPEN — minor, 2026-11-06** | The session told Dustin Kalshi's First TD board was "the classic polluted-field case, booksum 21.38". **That number was an artifact of its own dict, not a property of Kalshi's market.** Read through `flatten_odds`, Kalshi's board is 23 clean two-sided rows with a **+34.0% overround on CIN@ATL — in line with DraftKings' +32.0% and Bovada's +34.5%.** Three different Kalshi numbers were quoted from three constructions (21.38 raw, 20.08 collapsed, 1.3401 correct). Kalshi IS unusable here, but for the same reason BetMGM is — no no-scorer row — plus 0.94 on LV@SF and thin liquidity. Worth recording because it is the exact failure mode B82 exists to prevent, caught only because the number was absurd: **a hand-roll produced a market characterisation that was really a self-portrait.** No engine change; the instructions now forbid the hand-roll outright. |

| **B93** | The engine PRINTS a slip's hold beside its band and says nothing when they disagree | **DONE 2026-11-05** | Not a missing computation. `report()` already emits `this slip's hold: 18.8% (observed, not assumed — reference band 23.1%-37.2%)` — **both numbers, adjacent, with no verdict** — and `slip_hold` and `hold_band` are properties on the same object. The reader is left to notice that 18.8% is outside 23.1-37.2% while scanning dozens of lines, and it slid past. A placed DraftKings SGP (three JAX@BAL receiving legs, +550, 30% boost) was quoted at a **slip hold of 18.79%** — which is BELOW the measured same-game band of **23.1-37.2%** and sits inside the **cross-game** band of 17.7-20.9% instead. Every number in the write-up was arithmetically correct; the anomaly is that a same-game structure priced like a cross-game one, which is independent evidence that the fair product (0.12494, and note 0.5³ = 0.125 with one anchor at *exactly* 0.5000) is generous. **If the true hold were merely at the BEST end of its own band, that bet is -3.6% rather than +1.83%.** This needs no re-examination of any anchor and no new measurement — it is two existing measurements disagreeing, already printed one line apart. **And the same-game band was unambiguously the right one: Dustin explicitly asked for a TNF-only slip**, so this was not a structure mix-up, it was a plausible number next to the band that contradicts it, with nothing drawing the line between them. B39's family in its softest form — the information is present, unflagged, and therefore indistinguishable from information that was checked. **FIXED.** New `hold_vs_band` ("below"/"within"/"above"/None) and `hold_band_note`, printed by `report()`. The mechanism turned out to be sharper than "two measurements disagree": `p_cash` is `fair_joint`, a PRODUCT, and `slip_hold`'s own docstring already said the product is the joint only for a cross-game slip. So for same-game the hold is computed from a number that omits whatever correlation the table does not carry, and the band is what real same-game slips actually hold — a product-based hold beneath it is evidence the product is OVERSTATING P(cash). The three cases are therefore worded differently and only one is marked loud: same-game-below flatters the EV and gets `***`; cross-game-below is exact and merely beats the population; above-band understates and is self-correcting. **B93b, same day, before any test round: the cross-game branch was cut.** The first cut printed a soft "this beats the population" line for a cross-game slip below its band, and a firing-rate check showed that is noise by construction — three legs at -110/-110 hold **13.03%** against a **17.7%** band floor (the band implies ~-115/-115 legs), and all three cross-game slips measured this session (15.1%, 14.5%, 4.9%) sat below it. **A note that fires on good shopping is a note that gets ignored** — B91's lesson, shipped hours after writing it. The deeper reason is cleaner: for a cross-game slip `slip_hold` is EXACT, and its own docstring already said it is "a better number than the measured band", so remarking that it differs from a population reference adds nothing. The band earns its keep only where the slip's own number is incomplete, which is same-game. Firing rate across the five slips measured this session is now **1 of 5 — and it is the one that got placed.** Checks are built by reconstructing the REAL placed slip — p_cash 12.4942%, hold 18.79%, EV +1.83% all reproduced to four decimals — so the fixture is the bet that exposed it. 14 checks, 8 failing on revert. Original proposal kept below for the record: `report()` states the comparison rather than leaving it adjacent — one line naming the direction and what it implies. **A hold BELOW the band is the dangerous direction, because it flatters the EV**, so it warrants the louder wording; above the band is merely a worse price than expected. Cheap, because nothing needs computing. Note the legitimate alternative reading, which the flag should state rather than resolve: DraftKings' `correlation_factor` was **0.9498**, only a 5% correlation haircut, against 0.602 on a genuinely-correlated stack and 0.787 on an independent receiver slip earlier the same day — so the book may simply have priced it tight. The flag's job is to surface the disagreement, not to pick a winner. |
| **B94** | A grid mismatch is usable as a one-sided sanity check, and that is not written down anywhere | **OPEN — found 2026-11-05, invented by the project thread** | D18 forbids snapping a fair probability from one line to a neighbouring one, correctly — a fair number for 32.5 is not one for 33.5. So when Pinnacle came back mid-session on a different grid (Strange 32.5, Hunter 9.5, Washington 61.5 against DraftKings' 33.5, 8.5, 63.5) the sharp anchor was unusable for pricing. **The thread then used it anyway, as an inequality.** DK's point is HIGHER than Pinnacle's on Strange and Washington and LOWER on Hunter, so a correct Bovada number must be below 0.5159, below 0.5192 and above 0.4642 respectively. Measured: 0.4892, 0.5000, 0.5108 — all three consistent. **A sharp line on an adjacent point cannot give you a probability but it does give you a BOUND**, and monotonicity in the threshold is free. That is a genuinely new technique, not in any instruction, and it turns the most common anchor failure (grid mismatch, 75 of 179 lines on one board) from a dead loss into a one-sided check. Worth building into `anchor_coverage` or a helper: given a soft anchor and a sharp line at a nearby point, report whether the soft number violates the bound. The thread was also right about what it buys — "it rules out a gross anchor error, not a two-point one" — and a 2pp miss still swings that slip from -13% to +11%, so the bound must be reported as a bound and never as a validation. |

| **B90** | One refusal message asserted the conflict narrative for BOTH reasons `supports()` returns None | **DONE 2026-11-05** | Introduced hours earlier in the B88b fix, and it cost a wrong report. `supports()` returns None for a share/count CONFLICT and, separately, for a COUNT THAT DID NOT MOVE (`count_flat`) — and both took one veto message reading *"the COUNT moved the other way, and a threshold prop is priced on count. He is a bigger part of a smaller pie, or the reverse."* Live: **CeeDee Lamb's targets were exactly flat at 11.5 → 11.5** (share 151%, team volume 68%), `direction_conflict=False`, `count_flat=True` — and he was told the count moved the other way. **The reading session believed the message, reported him as "the B84 case", and had to correct itself by inspecting the flags**, which is the measurable cost of a message asserting what the code never determined. Same class as B80 and B88/A4, committed inside the fix for them. Each state now has its own sentence in both `boost_verdict` and `prop_edge`. **And the first revert check showed ZERO failures** — I had separated the messages and written no check for it, so gate item 5 is what caught it; 6 checks now, 2 failing on revert. |
| **B91** | A verification that could never pass, so it got ignored | **DONE 2026-11-05** | `verify_uploaded` required BYTE identity, which is **unreachable for any log containing a non-ASCII character**: `json.dumps` is ASCII-only by design, so an em dash is stored locally as `\u2014` and comes back from Drive as the raw character. Measured: **`ff_props.py` holds 178 em dashes, 35 of them inside verdict-reason f-strings** — largely ones I wrote today — so every role-change verdict guaranteed a False. The docstring's advice, *"a mismatch means re-upload, not shrug"*, cannot help, because the transcoding is in the transport rather than the attempt: a live session re-uploaded, got False again, and declined to call `mark_uploaded` — **leaving 69 verdicts in Drive unmarked and due to be re-uploaded by every future session.** The old code already computed record equality and still returned False, calling it *"equivalent by luck"*. That is the wrong reading of this cause: escape-versus-raw for the same codepoint is a deterministic lossless JSON transcoding, while truncation or reordering is what luck would look like — and both show up at the record level. Verification is now canonical-record equality (sorted keys, ASCII-forced), and the byte difference is still REPORTED so the original canary's information survives as a message rather than a verdict. **A check that cannot pass is not caution; it is noise that trains the reader to ignore the one signal meant to be load-bearing** — B39's lesson arriving from the opposite side. Verified still failing on: an altered field, a dropped record, a reordered record, unparseable content. 8 checks, 3 failing on revert. The existing check that pinned the old behaviour was reconciled rather than flipped — it now asserts both the pass and the byte-difference report. |
| **B92** | `flatten_odds` does not carry liquidity, which forces the hand-roll B82 is about | **DONE 2026-11-05** | The test session hand-rolled a `liquidity_index()` that walks `bookmakers[].markets[].outcomes[]` directly, and owned it — but its reason is the actionable part: **there is no sanctioned path from a `get_odds` payload to per-line anchor depth, because `flatten_odds` drops `liquidity`.** So anyone needing anchor liquidity must bypass the one function that does the outcome pairing, the `line_type` filter, the Over/Under label matching and the price-key fallbacks. That session's version happened to be keyed safely — `line_type == "main"`, keyed on `(book, norm_player, market, point)` — but B82 exists because the next one will not be. **FIXED:** `over_liquidity` / `under_liquidity`, carried per SIDE because Kalshi quotes resting money per contract and one line's two sides can differ by orders of magnitude — Justice Hill's main 14.5 had $5,977 behind the over against $112 on the under, so a single per-line number would have been a fiction. `None` means the book never reported liquidity (DraftKings 0/276, FanDuel 0/204, Bovada), kept distinct from 0.0 because `anchor_thin` treats "never reported" and "nothing resting" differently — a check pins that specifically, and collapsing None to 0.0 fails it. 5 checks, 2 failing on revert. **This removes the last reason to hand-roll the payload walk**, so B82 is now about replacing hand-rolls that have no excuse rather than ones that did. |

| **B88** | Four defects in the B84/B85 fixes themselves | **DONE 2026-11-05** | **(A1) The dangerous one.** `devig_field`'s lower bound (B71) and its diagnosis (B85) were BOTH gated on whether a no-scorer row was present, so **a polluted field carrying one had no upper bound at all** — and the real DraftKings First TD board carries "No Touchdown Scorer", making this the likely path rather than an edge case. Measured: that board plus rung pollution gives **booksum 3.0326 over 14 outcomes, RETURNED**, tagged `method: shin, complete: True`, turning a 55.6% implied scorer into **24.4% "fair"**. Every player divided by about three — verbatim the failure this module's own docstring warns about, reached through a door I had just reinforced on the other side. Fixed with `BOOKSUM_REFUSE_ABOVE = 2.00`, applied outside the name check and outside `require_complete` (which governs inspecting an *incomplete* field; a booksum this high is extra outcomes, not incompleteness). **(A2)** The B85 diagnosis compared `booksum > 1.0 + MAX_PLAUSIBLE_OVERROUND` = 2.0, while its own comment claimed the threshold was 1.0 — so the whole 1.0–2.0 band, where a *lightly* polluted field lands, still read "too low by whatever is missing" at 71% overround against a 57% measured maximum. **Root cause of both halves: one constant serving as a refusal line and a diagnostic ceiling at once.** Split into `BOOKSUM_REFUSE_ABOVE` and `MAX_OBSERVED_OVERROUND = 0.57`. **(A3)** `boost_verdict` used `side is None` as a proxy for "no edge supplied", but `Edge.side` is an unvalidated `str` and this file uses lowercase `"over"`/`"under"` in several places. So `Edge(side="over")` was not None, `supports()` returned None because the string is not canonical, and the call fell through to the CONFLICT branch — printing *"the COUNT moved the other way"* on a trend whose count moved 3.2 → 8.0, the **same** way. A fabricated divergence that **re-vetoed exactly the Justice Hill expansion B80 exists to un-veto, reached by letter case.** Side is now normalised, and "no edge" / "unrecognised side" are separate states, the latter named as a caller bug rather than a finding about the player. **(A4)** Both conflict messages printed `team volume {ratio:.0%}` while `direction_conflict` never reads that field — and it is 0.0 when unmeasured and **hardcoded to 1.0 by `role_trend`**, so a reader saw "team volume 0%" (a team that ran no plays) or "team volume 100%" directly before "he is a bigger part of a smaller pie", which 100% contradicts. New `has_team_volume` flag; the messages omit it when unmeasured. 40 checks; each fix verified to fail on revert. |
| **B88b** | Three prose/edge defects from the same review | **DONE 2026-11-05** | **(A5)** `direction_conflict` used strict inequalities, so a count ratio of **exactly 1.0** was neither above nor below, reported no conflict, and `supports()` answered confidently off the share verdict — while `expected_now` equalled the sample mean exactly, meaning no staleness in either direction. At ratio 1.0001 the same state already returned None, and this module retired `LONGSHOT_P` for precisely that discontinuity. New `count_flat` property. **(A6)** `share_ratio` is forced to 1.0 both when `has_share` is False and when the share baseline is zero, and `describe()` printed it regardless — giving `"COLLAPSED, share 100%"`, self-contradictory against `SHARE_COLLAPSE = 0.65` and reading as exactly the GAME_SCRIPT diagnosis the mechanism exists to distinguish. New `share_measured` property. **(A8)** `UsageTrend.describe()` narrated *every* flagged trend as "the sample describes a role this player no longer has", including the states `supports()` refuses to answer, so `report()` printed a confident role-change story over an undetermined one. **A first cut of that patch used `L.append()` in a function that builds with `s +=`** and would have raised `NameError` on exactly the state it was written for — 560 checks stayed green because nothing ran a conflicting trend through `describe()`. Found by reading the function, which is gate item 2. |
| **B88c** | My own figures were unreproducible prose, and two checks could not discriminate | **DONE 2026-11-05** | The reviewer noted B84's numbers (264 flagged, 21 conflicts, wrong on all 21, `team_volume_ratio` 0.42–1.98) sat in a docstring as a **prose assertion with nothing in the repo able to reproduce them** — D16's shape exactly, committed in a fix for a different instance of D16. Now `measurements/b84_direction_conflict.py`, which re-derives all of them and writes the per-player rows to CSV; the docstring points at it and says the script wins if they ever diverge. Two test-quality defects from the same review, both lesson 4 **inside checks written to enforce lesson 4**: the `MAX_PLAUSIBLE_OVERROUND` bracket passed for any value across a 3.5x range (now tight to the measurements, with the refusal line and the diagnostic ceiling pinned separately), and a check named *"reports count, share AND team volume"* never asserted the count. Also corrected: **four comments and three test references named a function `price_edge` that does not exist** — it is `prop_edge` — and I repeated that wrong name to Dustin several times; plus a comment reading "these two cases are exhaustive" over what is now a five-branch conditional. |
| **B89** | A near-flat count still earns a confident direction | **OPEN — found 2026-11-05** | B88b/A5 fixed the discontinuity at exactly 1.0, but a count ratio of 0.9999 against a falling share still returns a confident UNDER, and at that ratio `expected_now` sits within a whisker of the sample mean — so "the model overstates him" is technically true and practically empty. The fuller fix is a tolerance band around 1.0 instead of an equality test. **Not guessed, because picking a tolerance by eye is the error this project keeps repeating** (B49's snapping, LONGSHOT_P's retirement, `token_note`'s single-sitting range). Measure what count ratio is needed before `expected_now` separates from the sample mean by enough to matter, then set the band from that. `measurements/b84_direction_conflict.py` already emits the per-player rows needed to do it. |

| **B84** | `supports()` read the direction off SHARE, but a threshold prop is priced on COUNT — and they diverge | **DONE 2026-11-05** | Found by the twelfth deployment test, hours after B80 shipped, in the method B80 created. `verdict` is decided on share_ratio — **deliberately and correctly**, with the Corum case documented: a count drop that leaves share intact is the team running fewer plays, not a lost role. That is the right test for *did his role change?* But `supports()` then mapped that verdict to a betting direction, and **production follows OPPORTUNITY COUNT, not share.** When team volume moves the two diverge: a player can take a bigger slice of a smaller pie (share up, count down), and the model built on his old count then OVERSTATES him — supporting an UNDER — while the verdict says EXPANDED and the mapping claimed the opposite. **Measured across 264 flagged role changes in the 2025-26 pool: 21 have share and count pointing opposite ways, and the verdict-derived direction was wrong on ALL 21. Of the 243 where they agree, 2 disagreed, both where `expected_now` sits within a point of the sample mean. So refusing a direction on conflict fixes 21 of 23 known disagreements and costs ZERO correct calls** — about as clean a fix boundary as this project has had. `team_volume_ratio` on the conflicting set runs 0.42 to 1.98, confirming the divergence is team-driven rather than noise. **Worse than B80 in one respect:** B80 was over-conservative and dropped good legs, whereas this was sometimes over-PERMISSIVE — it admitted a leg as CAUTION with the note *"the model UNDERSTATES the OVER, the true edge is likely larger than shown"* when production said the model overstates it. Encouraging text pointing the wrong way is worse than a wrongly-dropped leg. Fix: new `direction_conflict` property, and `supports()` returns None on it. **The None had to be plumbed carefully, because `elif supported:` treats None as False** and would have vetoed "AGAINST THE {side}" — re-entering B80's exact mistake through a new third state. Both call sites now separate the three None reasons (no side / not flagged / conflict) and name which one applies. 18 checks; removing the conflict test produces 6 clean failures. |
| **B85** | The incomplete-field refusal printed "too low" over whatever booksum arrived | **DONE 2026-11-05** | **This one is mine twice over.** The reviewer flagged the directional wording this morning and I concluded B70's required-`market` fix resolved it — it does not: a polluted dict for a genuinely exclusive market still reaches this branch with a booksum far ABOVE 1.0. Then I added the B71 booksum guard immediately above this message and did not re-read the message below it, which is gate item 2 verbatim. Observed live: a dict keyed on player name alone pulled milestone rungs into a First TD field, giving 13 outcomes at booksum **2.9756**, and the refusal called 2.98 *"too low by whatever is missing"*. The caller is already confused at that point and the message added to it. Now branches on `MAX_PLAUSIBLE_OVERROUND = 1.00` — a **diagnostic** threshold that chooses which sentence prints and never whether the field is refused — and the high branch names the actual cause (`keyed on name alone`, rebuild from `flatten_odds` with the line in the key). Threshold provenance: measured complete First TD boards ran DraftKings 1.5421 and bovada 1.5655; short fields ran BetMGM 1.4124 and Kalshi 1.3501. So a real field topped out near 57% and the polluted dict hit 198%. 7 checks, including that every measured real board clears the threshold. |
| **B86** | A slip leg can sit at the opening liquidity tier with no flag raised | **DONE 2026-11-06** | `anchor_thin` fires at liquidity ≤ 25 and `anchor_opening` requires `abs(fair_prob - 0.5) <= 1e-9` **and** liquidity ≤ tier. All three legs of the Sunday slip sat at **liquidity 250, equal to the derived tier**, with fair probs 0.5152 / 0.5354 / 0.5217 — so the liquidity condition was met on all three and **neither flag fired, purely because the prices were not exactly 0.5000.** Nothing in the engine's output said the anchors were shallow; the thread only surfaced it by querying the fields by hand. The gap matters because the thread's own sensitivity table shows the whole edge lives there: treating the anchors as fully accurate gives EV +15.3%, and treating them as carrying no information gives **+0.2% at a 17.4% hold — on the measured cross-game band.** And 54 of Pinnacle's 62 two-sided lines that run sat at exactly 0.5000, so picking the 8 that moved is selection on 250 of resting money. **CONFIRMED LIVE 2026-11-05 PM with a concrete case, and the session initially mis-reported it.** On a three-leg Sunday slip: Gibbs at liquidity 250 against a *derived* tier of 250 — at the gate, not through it — but `anchor_opening` also requires `fair_prob == 0.5000` and his is 0.5427, so no flag. Likely ($176) and Allen ($106) get **no derived tier at all**, because `book_liquidity_tiers` deliberately refuses Kalshi (resting dollars with no dominant mode, so a mode would be invented) — those are the 2 of 3 in `tier_fallbacks`. And `anchor_thin` is liquidity <= 25, which $106 and $176 clear comfortably. **So every automated anchor guard was silent on all three legs**, and the session had written prose leaning on "shallow Kalshi anchors" as though the tooling had flagged them, then corrected itself: that was its own judgment about $106 and $176, not a module finding. Also worth recording: **zero CLEAR legs in the entire 98-leg pool** — all three slip legs were CAUTION, two on sample width. **FIXED: `anchor_untested`.** All three legs of the real slip now flag, and a mature anchor (liquidity 3,000 against a 1,000 tier) stays silent. **RESIDUAL by construction, and the firing-rate check decided that** — the broad version (liquidity <= tier, full stop) fires on **100%** of a three-days-out board and is the noise B93b cut; excluding what `anchor_opening` and `anchor_thin` already catch brings it to **8 of 62 (13%)**, which is exactly the set that had no flag. Both go to **0% near kickoff**. Unreported liquidity returns False — never reported is not the same as low — and `anchor_note` is defensive about it anyway, because a note that can raise turns a flag into an outage. **It overturned a documented position, deliberately.** Two checks asserted a moved price at the opening limit was NOT flagged, reasoning *"the 0.5000 does the work; liquidity only sets how far the net reaches."* The measurement contradicts that: **all 62 lines sat at liquidity 250** and only 54 were at 0.5000, so 250 of resting money cannot make 0.5065 meaningful when it does not make 0.5000 meaningful. The old checks' DISTINCTION survives — moved and unmoved are different states and now get different flags — and only the verdict changed, from "no flag" to "a quieter one". `anchor_immature` was safe to widen because it feeds `immature_anchors`, a report that gates nothing, and at slip level names three players rather than sixty-two. 16 checks; 9 fail when the flag is disabled, 3 when it is made broad, 2 when unreported is treated as low. Original proposal kept for the record: a third flag on liquidity alone (`anchor_untested`, liquidity ≤ tier regardless of price) so a shallow anchor is visible without being confused with the exactly-0.5000 signature, which is a different state and correctly narrow. |
| **B87** | A fabricated price produced a steep-hold "finding" | **OPEN — found 2026-11-05** | The thread passed a dummy `-10000` for an unused side and `boost_verdict` computed a hold from it and reported **"hold 52.3% is steep"** as a reason against the leg — a finding derived entirely from a number nobody quoted. It was caught and corrected to 6.5% before upload, but only because 52.3% is obviously absurd; a dummy of -400 would have produced a plausible-looking steep hold and stood. B24's family: a fabricated input yielding a confident finding. Fix: refuse a two-sided hold computation when either side is outside a plausible range (roughly -2000..+2000) rather than returning a number, and say which side was implausible. Note this is the same shape as B77's unbounded `bonus_value` and `market_hold`, so fix them together. |
| **B80** | The role-change VETO asserts a direction it never computes, and it rejected a good leg | **DONE 2026-11-05** | `boost_verdict`'s docstring promises "a role change running against **the side being bet**". The code is `if est.role_changed: veto(f"... and it runs against {side}.")` where `side = edge.side` — so it vetoes on ANY role change and then **asserts the direction in prose without ever checking it.** B46's exact shape, in the screen that decides what reaches a slip. Measured live: Justice Hill was the best-priced leg on the board (ev_pct −0.23%) and was VETOED because his targets went **2.2 → 6.0 — an expansion, which runs FOR the Over being bet** — while the message claimed it ran against it. The leg was swapped out for a worse one. `u.baseline` and `u.recent` are both in hand, so the direction is computable from data already present and simply unused — same as B75. **This is a live behaviour change needing Dustin's sign-off, because the fix UN-vetoes legs:** an expansion against an Over (or a contraction against an Under) should be at most CAUTION — the sample still describes a role the player no longer has, so the estimate is unreliable, but unreliable in the leg's favour. Only a role change opposing the side should veto. **FIXED, Dustin signed off 12:21.** Six states enumerated rather than branches counted: COLLAPSED/EXPANDED x OVER/UNDER, plus no-side, plus the soft GAME_SCRIPT flag. A supportive change is now CAUTION — not CLEAR, because the direction helps while the magnitude stays unreliable, matching `price_edge` costing a supportive change one tier. An absent edge VETOes **for the missing side**, not for a direction nobody measured. **The duplicate is gone, which is the part that mattered:** the two-line expression existed in both `price_edge` and `boost_verdict` and now lives once, as `UsageTrend.supports(side)`, returning None when the side is unknown so no caller can guess. A check asserts it is not re-inlined. Also confirmed the fix is operationally real rather than cosmetic: `enumerate_candidates` drops VETO (ff_boost:1187) and only annotates CAUTION (ff_boost:1090), so Hill would now be admitted with a note — pinned by a check, since a fix that only changed wording would have been worthless. 20 checks; reverting to the blanket veto produces 5 clean failures at the full count. |
| **B81** | A measured zero and a never-measured zero share the empty-string label | **DONE 2026-11-06 — see B114; every return now names itself and `Structure.zeros` carries the provenance to the report** | Every non-zero branch of `_pair_r` names itself; the `(0.0, "")` returns do not. B53 established that the 0.0 encodes a real measurement (same-team WR×WR at +0.00 over 2,970 pairs), but **from the label alone a reader cannot tell "measured ~0.00" from "fell through with nothing to say."** Observed live on `Derrick Henry x Zay Flowers` and `Travis Hunter x Parker Washington`, both printing `r = 0.0, reason: ''`. Same shape as B75's `tier_fallbacks` and E6's provenance gap, and it is one line: give the established-independent return a reason string naming the measurement. Note E6 is the reason this matters more than cosmetics — two of the fall-throughs may never have been measured at all. |
| **B82** | The engine is hardened; the ad-hoc extraction code in the project thread is not — and it reproduced two fixed bugs | **DONE 2026-11-05** | The test thread self-caught two errors, and **both were the project's own documented failure modes, committed in its one-off diagnostic scripts rather than by the engine.** (a) It queried `"Chris Rodriguez"` where the board name is `"Chris Rodriguez Jr."`, got `meta=None`, and reported the player as UNKNOWN — **B44's exact name-join shape**, which `norm_player()` exists to prevent but which a hand-written dict lookup bypasses. (b) Extracting Kalshi's First TD field with a dict comprehension kept the **last** price per player, which on a two-sided board (28 Yes / 22 No) is the **No** side at prices like −4900, producing a booksum of **20.99** — **B24/B28's Over/Under side-mixing**, which `screen_quotes` exists to prevent. Both were caught, but only because the numbers were absurd enough to notice: a name-join miss that returns a plausible position, or a side-mix on a board where both sides are near −110, would not be. **Controlled follow-up 2026-11-05 PM — the side-mix did NOT reproduce, and that narrowing belongs on the record.** Across all 19 (book, player) combos on a live payload serving more than two rows, every hand-rolled Over/Under matched the main line, because milestone rungs carry distinct names (`"100+ Rushing Yards"`) and so never overwrite the `Over`/`Under` keys. The Kalshi incident fired because that board is **Yes/No**, where every player genuinely has two rows under one name. So the mechanism is real but **board-shaped**: last-write-wins SWAPS sides on a Yes/No board and merely POLLUTES on an Over/Under board. The pollution is still serious — keyed on name alone the point is discarded and rungs join the field, giving 13 outcomes at booksum 2.9756 where a real two-sided line is ~1.07 — and it was `devig_field`'s guards that caught it, not the extraction. **A third instance of the same class appeared in the same session:** `getattr(candidate, "anchor_opening", None)` returned `None` for an attribute that lives on **BoostLeg, not Candidate**, and `opening=None thin=None` was printed as though it were a measurement. A `getattr` default standing in for a reading, on the wrong object — B39's shape reached through a typo rather than a missing value. So session-facing accessors must RAISE on an unknown field rather than default. **A working starting point now exists**, written in the thread and worth lifting nearly as-is: build on `flatten_odds` with the LINE in the key, require exactly one main row, and raise on a one-sided or suspended market rather than returning a dict. **The engine's guards only protect calls that go through the engine, and the numbers Dustin reads come from whatever the thread writes in the moment.** Fix: export the extraction primitives the thread keeps hand-rolling — a field-builder that takes a `get_odds` payload plus a market and returns `{name: american}` Yes-side-only with names normalised through `norm_player()`, so `devig_field` is never fed a hand-built dict. This is the engine-vs-session boundary, and it is where the remaining defects live. **B92 (DONE) removed the one legitimate excuse** — anchor depth is now reachable from `flatten_odds` alone. **FIXED with two helpers, both deliberately thin, because the value is that they exist and are the obvious thing to reach for.** `field_from_odds(response, market=, book=)` returns `{normalised name: american}` for one book's mutually exclusive field, ready for `devig_field`. The Kalshi failure turns out to have been entirely avoidable: **`OVER_NAMES` already contains `"yes"` and `UNDER_NAMES` `"no"`**, so `flatten_odds` routes a Yes/No board correctly and the hand-roll bypassed the one function that fixes it. `two_sided_field(...)` returns one line's `{"Over", "Under"}` plus its point. What they REFUSE is the substance: a non-exclusive market (named early, and pointing at the other helper); **two names that NORMALISE to one key**, showing both prices, since taking either is exactly how 20.99 happened; a row with no affirmative price; an empty result, naming the books actually present because a silent `{}` reads as "this book does not carry it"; more than one main line for a player, since choosing silently is how `"29+ Receiving Yards"` at -116 gets mistaken for `Over 28.5` at -116 (the same wager) or `"30+"` at -108 for the main Under (a different one); a one-sided market; a suspended market. **`norm_player` moved from `ff_boost` to `ff_props`** — where the intake that needs it lives — and is re-exported, so it has one home per lesson 7 rather than being reimplemented. 17 checks; each of the four guards verified to fail on revert. |
| **B83** | Reporting drifted off the measured band, and one range mixed two different bets | **OPEN — found 2026-11-05 by review of the output** | Two separate reporting faults in an otherwise sound write-up, both of the "a plausible number instead of the measured one" family. (a) The stake-back comparison table was computed at **v = 0.62, which is not a point in `STAKE_BACK_V_OBSERVED` (0.58/0.65/0.71)** — an invented midpoint presented beside correctly-banded figures elsewhere in the same answer. (b) The headline "each $10 stake-back is worth **$1.75–$3.17**" is not one bet's band: $1.75 is **Henry +600 at v=0.58** and $3.17 is **Strange +1000 at v=0.71** — two different bets at two different assumptions, printed as a single range. Verified: Henry's own band is $1.75/$2.38/$2.93 and Strange's is $1.94/$2.60/$3.17. Fix belongs in PROJECT-INSTRUCTIONS: quote `stake_back_band()` output per leg and never interpolate `v`. |
| **D19** | The Pinnacle dropout window is longer than documented, and drops are per-market-per-event | **OPEN — found 2026-11-05** | The instructions describe 10–30 minute dropouts. Measured 2026-11-05 afternoon: first seen **15:42Z, still absent at 16:49Z — 67+ minutes**. Measured again that evening on the Sunday slate: first observed **17:37Z, still present at ~19:40Z — PAST TWO HOURS**, so 67 minutes is not a ceiling either. Say a dropout IS RUNNING, never that it should clear shortly. **And it has a measurable price.** On DAL@IND the EV endpoint anchored Dak Prescott 5.5 on bovada at fair 0.5108 while a local Shin de-vig of Pinnacle gave **0.5217** — 1.1 points on a live slip leg, in the direction that makes the bet look worse. Bovada's own main line de-vigs to exactly 0.5108, so the endpoint reports bovada faithfully; it has simply substituted a softer book for the sharp one **without saying so**. And the scope is finer than recorded: in the same window Pinnacle was dropped on `player_reception_yds`, `player_rush_yds` **and** `player_pass_yds` across **two different events**, while anchoring 10 of 32 lines on `player_anytime_td` and reading healthy. So different markets on the same event drop **independently**. **Operational consequence, and it is not small: the yardage markets are exactly what a main-line boost slip is built from**, so the only positive-EV slip available tonight had all three of its fair lines sourced from bovada/kalshi at opening liquidity rather than from Pinnacle. Update the dropout note with the measured duration and the per-market scope, and add the rule: check `fair_source` per leg before quoting a yardage EV, not just `anchor_coverage`. |

| **B69** | A missing position took the LARGEST receiving coefficient and printed it as a category | **DONE 2026-11-05** | Found by tracing where `pos` comes from before writing a test prompt for B67. `_pair_r`'s receiving branch ended `else: r = SAME_TEAM_CORR[("QB","WR")], pos or "receiver"` — so a leg whose position was **missing** got **+0.31**, the largest of the three receiving values, labelled `same team passing x receiving (receiver)`. That label reads like a deliberate generic category, not like a miss: B39's shape exactly. **The same function already refuses on a missing TEAM, eight lines earlier, for identical reasoning** — I applied it to one field and not the other. `pos` comes from `build_meta()`'s name join, which **B44** established is the fragile link (one live payload carried both `Brian Thomas Jr.` and `Brian Thomas`), so an unmatched name was the likely route in, and B67 had just made the branch three-way without revisiting its fall-through. **The first fix was too broad and the suite caught it.** I refused every position outside WR/TE/RB, which failed section 30b's `the pair is scored off the market, not the roster label` — a check written 2026-11-02 to pin that a CB carrying a receiving prop (Travis Hunter, whose nflverse PRIMARY position is CB) still pairs with his QB at +0.31, because a receiving prop is evidence of a receiving role whatever the roster label says. **"Missing" and "present but outside the table" are different states and only the first is a miss.** Narrowed to refuse only an empty position; an odd-but-present one still resolves off the market and now names itself in the label (`CB with a receiving prop, scored as WR`) instead of hiding behind "receiver". The refusal text points at the name join and `search_players` rather than blaming the market. 5 checks, all three new ones verified to fail against the old behaviour. **Operational effect is on the explanation, not what is bettable** — `classify()` already refused an EV on the pair either way. |
| **B68** | `ff_guillotine` keeps its OWN copy of the correlation table, and its QB×RB entry has the WRONG SIGN for a fantasy score | **OPEN — found 2026-11-05 while fixing B67, effect measured and small** | Two separate problems, found by checking whether B67's bug existed anywhere else. **(a) Duplicate table.** `ff_guillotine.py:102-103` redefines `SAME_TEAM_CORR` and `OPPOSING_CORR` as its own literals rather than importing `ff_boost`'s. B67 was fixed in one copy only. Any future correction to either table has to be made twice or it silently diverges — exactly the state that let B67 live. **(b) The borrowed numbers do not describe what the sim correlates.** `ff_boost`'s table is a MARKET-level table: `("QB","RB") = -0.10` is QB *passing yards* × RB *rushing yards*, where the negative is a game-script effect (team ahead ⇒ run more ⇒ QB throws less). `ff_guillotine.correlation_matrix()` applies it to **fantasy scores**, which include receptions, receiving yards and TDs. Measured QB × RB same-team fantasy-score correlation, nflverse, guillotine scoring, z-scored per player-season, six filter variants: **+0.037, +0.033, +0.064, +0.089, +0.054, +0.079 — positive under every one, never negative.** The sign in the code is wrong, and unlike E3's levels the *sign* is not filter-sensitive. Mechanism: the game-script drag on yards does not survive into points, because TDs are shared upside. Other three entries on the same sweep: QB×WR measured +0.202…+0.326 against +0.31 in code (inside range, high end); QB×TE +0.189…+0.345 against +0.27 (inside range); opposing RB×RB −0.034…−0.089 against −0.14 (right sign, magnitude roughly 2× overstated). **Effect measured before prioritising, not assumed:** flipping QB×RB from −0.10 to +0.06 over 200,000 sims moved best P(elim) by **0.007pp on a typical synthetic league and 0.003pp with every team deliberately QB-RB stacked; max shift across all lineups 0.089pp; the recommended lineup was identical in both fixtures.** One pair among nine starters at a 0.16 difference barely moves a lineup total's variance. **That is two fixtures, not a proof** — it says the sign error did not change the answer where it was measured, not that it never will. So: real correctness bug, low operational stakes, behind F14. **Fix (i) as originally stated is WRONG and was not done — corrected 2026-11-06.** The tables cannot be merged: the chain runs `ff_guillotine <- ff_props <- ff_boost`, so the guillotine is the LEAF and importing from `ff_boost` would be circular, which is why the copy exists. They also should not share values, for the reason (b) gives — they are different quantities wearing the same keys, so merging would make the wrong sign permanent and invisible rather than fixing it. The divergence (a) actually feared, a pair added to one table and not the other, is now pinned by a suite check on the KEY SETS only; values are expected to diverge once E3 lands. So the real fix is (ii) alone: give the guillotine its own fantasy-score table measured on a documented filter — E3's job. Do NOT paste the six numbers above in as a fix: they are one filter's levels and E3 exists because that is how the current table became unreproducible. |

### BetMGM SGP hold — first reading, 2026-11-04/05. NOT a replacement for SGP_HOLD_*

Measured on event 87238 (JAX@BAL). **`price_sgp` reaches BetMGM** even
though the tool documents only fanduel / draftkings / betonlineag / lowvig —
`bookmaker: "betmgm"` returns `quoted: true` with a real price, verified
independently three times on 2026-11-05. That is what made this possible,
and it matters because BetMGM is where the boost tokens are.

**3-leg same-game hold: median 28.2%, range 23.1-35.1% (n=4).** On the same
event DraftKings measured 26.8% and FanDuel 28.5% on an identical trio. All
three books land inside the existing DK/FD band of 23.1-37.2%. BetMGM is not
cheaper.

**Three caveats, and the third is the one that matters.**

1. n=4, one event, one book.
2. Two of the four joints rest on fair probabilities of exactly 0.5000 —
   opening anchors that `anchor_opening` failed to flag (B54).
3. **The joint assumes the legs are independent, and nothing measured that.**
   Every slip was same-team receiving and rushing, which B53 shows falls
   through `_pair_r` to an asserted 0.0. Hold is `1 - quote * true_joint`, so
   an unmeasured correlation moves this figure in whichever direction the
   correlation actually runs. The number inherits B53 and cannot be cleaned
   up without fixing it first.

**A rung claim from that session does not survive re-measurement.** It
reported four slips all quoting +450 and concluded the payout was pinned to
a rung, so maximising true joint probability was worth "a free 12 points of
hold". Re-measured 2026-11-05 across a wider product range, BetMGM quoted
**+400, +450 and +475** on three structurally different slips. The payout is
not pinned; it tracks the product on a coarse grid of about 0.25 in decimal.
Those four original products spanned only 6.408-6.673 — a single grid step.
Within one step a higher true joint is genuinely free; across steps it is a
trade-off, because a higher true joint means a shorter product and a smaller
payout. **Do not generalise a rung from slips that all sit inside one.**

Fold this into the Sunday re-measurement rather than substituting it.

### The default band returned nothing on a real board — RESOLVED 2026-11-03, ceiling raised to +600

Two live events now, both yielding **zero candidates at the documented
+300/+450 band**. On 87238 every one of 1,248 distinct combinations priced
ABOVE the ceiling (min +558.8, median +569.8, max +592.8), because every
surviving main line sits at −110 to −115 and three near-coin-flips multiply
to roughly +560–590.

The documented target shape — "three legs near −150 each" — **does not exist
on main-line prop boards.** A −150 prop main line is rare; the book moves the
point until the price is near even money.

The band is not obviously wrong, though. Computed against the measured hold:

| price | 30% boost (cross) | 50% boost (cross) | 50% boost (same-game) |
|---|---|---|---|
| +575 | +3.9% to +6.7% | +17.9% to +21.1% | +3.9% to +15.8% |
| +450 | +3.0% to +5.8% | +16.6% to +19.7% | +2.7% to +14.5% |

Minimum boost for +EV barely moves with price: **25% cross-game at +575 vs
26% at +450.** So the ceiling is not protecting EV — it is protecting hit
rate, which is what Dustin actually asked for ("regular hits beat occasional
big ones"). A +575 slip at ~12% true probability cashes about half as often
as a +363 one at ~21%.

**Dustin's call, taken 2026-11-03: raise `CEILING` to 600.** The reasoning
that decided it: the real comparison is not +575 against +363, because the
+363 slip does not exist on a main-line board — it is +575 against no bet.
The ceiling buys hit rate, not EV, and 600 rather than 700+ keeps as much
hit rate as the boards allow while still returning candidates.

The two rejected options, and why:

- **2-leg slips** land near +300 and preserve the hit rate, but most boosts
  require 3+ legs, so it only applies sometimes. Worth revisiting per offer.
- **Alternate lines and milestone rungs** are the genuinely better fix —
  they let you PICK a 60% leg instead of taking whatever the main line
  offers, which is exactly what the original band assumed. Was blocked twice
  over; **B49 is now fixed, so rungs are PARSEABLE. They are still not
  PLAYABLE.** A rung is one-sided by construction, so it needs an external
  fair anchor, and **Pinnacle offers no alternates on props at all** — rungs
  would anchor off Kalshi contracts carrying a dollar or two, the exact
  input B46 exists to reject. The remaining block is anchor quality, and
  there is no route to it yet. Do not read B49 being closed as this being
  unblocked.

### The same-game hold band may be biased pessimistic — a hypothesis, NOT a finding

Two live same-game slips have now held **below** the band's pessimistic end:
19.2% and 21.9% against a floor of 23.1%. The band rests on 12 slips from one
slate, so two more observations is not a measurement, and the test session
that found the second one said so explicitly rather than claiming it.

**Record it as the thing to test on the Sunday re-measurement**, which is
already scoped to cover same-game deliberately. If the band is biased
pessimistic, it matters: it is the number that will be rejecting most of the
standalone-game boosts, which are half of Dustin's use.

### Structural constraint, bigger than any code bug

**Measured 2026-10-31, and both figures below went stale within three days.
Treat them as a dated reading, never as standing — D16.**
`get_market_coverage(days=7)`, 15 events in window: Pinnacle carried
pass/rush/reception yards on ONE event. Confirmed not to be a filter
artifact — dropping the `bookmakers` filter showed 17 books on an event
Pinnacle simply is not on. BetMGM carried none of the three markets.

**Re-measured 2026-11-03 on event 87238 (JAX@BAL, TNF Week 9) — one event,
not a slate:** Pinnacle carries ALL THREE yardage markets (4 pass / 26
reception / 10 rush outcomes, ~20 players two-sided, liquidity a flat 250,
which is its bet limit and not depth). **BetMGM is live on all three**,
main and milestone. Kalshi carries 388 priced outcomes with median
liquidity $38.52 and a max of $2,195, far above the "a dollar or two" this
file records elsewhere — but a $0.20 floor means roughly half still fail
B46's thin-anchor test. **Check coverage on the day, every time. Do not
copy any number in this section forward.**

Cross-game mode needs three anchored events. So for most of the week the
module cannot be used as designed, regardless of what gets fixed. Legs come
anchored from one game until Sunday props post.

### Not built, deliberately

- **No fetching.** The sandbox has no network to PropLine and the MCP tools
  belong to the session. Every function takes already-pulled payloads, the
  same shape as `flatten_odds`.
- **No full-slate pricing.** `price_sgp` is one call per slip per book, and a
  Sunday slate enumerates hundreds of combinations. Enumeration and ranking
  are local and free; the shortlist caps at 8 and only those get priced. The
  local ranking is a heuristic, the book price is the answer.

## Tier 2 — core builds · ~5 hours

**Order matters here. F2 before P0.**

| # | Item | Effort | Payoff |
|---|---|---|---|
| ~~**F2**~~ | Backtest harness + method comparison | — | **SETTLED 2026-11-02.** Verdict: do not build a scaled outcome backtest. See the F2 section above. |
| ~~**P0**~~ | Boost-slip optimizer | — | **DONE 2026-11-02.** `ff_boost.py`. See the P0 section above. |
| **F1** | Market-implied fantasy projections | 60-90m | Independent of the other two — build whenever. `get_event_ev` already returns fair probs, so a ~50/50 line IS the market's median projection for that stat. Improves every lineup call across 4 leagues |

**Why F2 first, reversing the original order:** P0 has to commit to a
construction method — correlated stack vs independent legs, odds target, how to
pick legs. Building it first means choosing that method on theory and finding
out later. F2 answers it empirically, and its harness (historical closing lines
+ graded prop results) is infrastructure P0 reuses anyway.

F2 does not need P0 to exist. It compares simple, definable strategies:
random legs at the odds floor, highest-probability legs, correlated QB stacks,
best-priced legs, SGP vs SGPx. The winner becomes P0's default.

**If only one gets built:** P0, since it is the usable tool — but treat its
method as provisional and flag it as unvalidated until F2 runs.

## Tier 3 — measurement · ~2 hours

| # | Item | Effort | Payoff |
|---|---|---|---|
| F3 | Unified CLV ledger across all copilots | 60m | Which copilots produce edge vs entertainment |
| P4 | Slate-level exposure tracking | 30m | Flat stakes wrongly assume independence |
| E3 | Make the correlation table reproducible | 30m | Estimates tighten a lot by Week 14 |

## Tier 4 — edge expansion · ~5 hours

| # | Item | Effort | Payoff |
|---|---|---|---|
| **F4** | Goal-line modeling (inside-5 carries) | **PREMISE MEASURED AND FALSIFIED 2026-11-05 — do not build as written** | Tested out of sample on 2025-26 play-by-play, 5,747 player-games, strictly-prior features only. The 38% baseline is real: inside-5 rushes convert at **0.378** (inside-10 at 0.280). **But inside-5 share is NOT the best available predictor — it loses to simpler features.** Across all players, AUC: prior TD rate **0.640**, inside-5 share **0.577**. Among players with a real rushing role (3+ carries/game, n=1,698), plain CARRY share **0.662** > inside-10 share 0.651 > prior TD rate 0.639 > inside-5 share **0.639**. Blending td_rate with inside-5 share peaks at +0.007 AUC, which is inside the noise. **The cause is sample size:** inside-5 rushes run 2.32 per team-game, so the median share estimate rests on **4 prior inside-5 carries** and the 25th percentile on **1**. Carry share measures the same underlying role with 20-30x the data. In hit-rate terms against a 30.8% base: top quintile by carry share scores **48.5%** vs 43.5% by inside-5 share, and the bottom quintile separates far better (11.2% vs 19.1%). A plain ">=50% of team carries" heuristic gets 46.2% on 435 player-games and needs no model at all. **Honest ceiling:** every feature tested sits at AUC 0.58-0.66 on a binary event. That is weak, and none of it was compared against the market's own de-vigged probability, which is the only benchmark that matters for betting. Do not report a model TD probability as if it beats a price. See F10 for the version worth building. |
| F5 | Weather / wind / roof | 60m | Books move game totals faster than props |
| F6 | Line movement as a news detector | 60m | Information before the reporting |
| F7 | DFS pick'em vs sportsbook divergence | 60m | Different pricing mechanism = mispricing |
| F8 | Championship odds, opponent modeling, trade value | varies | Fantasy depth |

## Tier 5 — when there is time

| # | Item | Effort | Note |
|---|---|---|---|
| ~~E4~~ | DST team scoring | — | **DONE 2026-11-03.** `team_defense_weeks(pbp)` + `score_dst(df, lg)`, 14 checks. The stated blocker — points allowed "lives in game data rather than the player file" — was true of the WEEKLY file and false of the play-by-play `refresh.py` already loads, which carries scores, `fourth_down_failed`, sacks, INTs, fumble recoveries, blocks and `defensive_extra_point_conv`. Nothing new is fetched. Validated by reconciliation rather than a reference calc: credited points allowed equals every point scored in every game (5,579 = 5,579), and sacks and INTs each tie out to the play count exactly. A pick-six pays ONCE — nflverse's `return_touchdown` covers interception and fumble returns too, so `td` and `return_td` split on play_type. **Only Holmdel's can actually be scored**, which is the league where it mattered most; Cameron Wood and Gridiron Grail raise, because their points-allowed ladders were never recorded. "No deadline" was wrong — this was a caveat paid every week in two of four leagues. |
| B3 | `data_status` staleness detection | 20m | Currently manual via connector `current_week` |
| P5 | Calibrate edge threshold / remove dead Kelly | 15m | Cosmetic, but removes false precision |

## Not doing

**E5 — opponent lineups assume optimal play.** High effort, and the bias is
conservative (it makes the user look *less* safe). Wrong in the right direction.
Revisit only if F8's opponent modeling gets built anyway.

## Sequencing notes

- **B1 and B2 share a root cause** — fix together, they are one change.
- **F2 before P0** (reordered 2026-10-30). The backtest decides the method; the
  optimizer implements it. Building in the other order means committing to a
  construction method on theory and discovering later whether it cashes.
- **E2 gates F3.** No ledger without a log.
- **E2 also feeds F2's realism** — once real bets exist, the backtest can be
  checked against actual results rather than only simulated ones.
- **F1 is the single best value-per-hour item on this list** and has no
  deadline, which is the only reason it sits below Tier 1. It is independent of
  F2/P0, so it can be slotted in whenever there is a spare 90 minutes.

---

# END-TO-END REVIEW — 2026-10-29

Full audit of all five modules after a day of rapid change. Findings below,
ranked by value against effort. **Bugs B1 and B3 are currently corrupting
output and both are small fixes.**

## Priority order for this weekend

| # | Item | Value | Effort | Why now |
|---|---|---|---|---|
| **P0** | Boost-slip optimizer | **HIGHEST** | ~90 min | Nothing solves the actual use case |
| **P1** | Model is not an edge source for betting | **HIGH** | ~30 min | Mis-signals every week it runs |
| **B1** | Phantom players in guillotine | **HIGH** | ~20 min | Actively wrong right now |
| **P2** | `suspended_at` / `pregame_only` / `max_age` ignored | **HIGH** | ~20 min | Prevents real Sunday errors |
| **E1** | Byes/injuries in guillotine | **HIGH** | ~45 min | Week 9 byes hit Sunday |
| **E2** | Bet log for CLV | **HIGH** | ~30 min | Can't backfill; starts with first bet |
| **B2** | `best_lineup` position validation | MED | ~15 min | Same root as B1 |
| P3 | `shin` de-vig unused for longshots | MED | ~10 min | Wrong math on TD props |
| P4 | No slate-level exposure tracking | MED | ~30 min | Flat stakes assume independence |
| B3 | `data_status` can't detect staleness | MED | ~20 min | Currently manual |
| P5 | Edge threshold uncalibrated; Kelly dead | LOW | ~15 min | Cosmetic but misleading |
| B4 | `prop_edge` accepts invalid `fair_over` | LOW | ~5 min | Cheap |
| B5 | `enumerate_lineups` fails silently | LOW | ~5 min | Cheap |
| E3 | Correlation table not reproducible | MED | ~30 min | Refresh mid-season |
| E4 | DST scoring | MED | ~1 hr | No deadline |
| E5 | Opponent lineups assume optimal play | LOW | HIGH | Not worth it |

*Superseded by the MASTER BUILD ORDER above. Tier 0 (B1, B2, E1, P2, P3, B4,
B5, B6) shipped 2026-10-30. P1 moved to Tier 1 after the scope conversation:
under boost-chasing the model's job is vetoing legs, not selecting them, so
relabeling matters but is not Sunday-blocking.*

---

# FUTURE IDEAS — brainstormed 2026-10-30

Not scheduled. Ranked by what they would actually change. The data inventory
behind these: **nflverse play-by-play carries 372 columns and 18,738 plays in
2026 alone** — weather, temp, wind, roof, full situational and drive context,
55 win-probability/EPA columns. We currently use about 15 of them.

## F1. Market-implied fantasy projections  *(highest value)*

De-vig every prop market for a player — pass yards, TDs, INTs, receptions,
rush yards — and you have **the market's complete projected stat line**. Run it
through `ff_scoring` and you get the market's projection IN each league's real
scoring, first-down rule included.

That is a projection weighted by actual money from books that lose when they
are wrong. It does not exist as a product. It is strictly better than consensus
rankings for start/sit, and it **sidesteps our model's sample-size problem
entirely** — the thing that defeated us repeatedly today.

This is the genuine synergy between the two use cases: **the betting data makes
the fantasy side better**, not the reverse.

## F2. Backtest harness + method comparison  *(build BEFORE P0)*

PropLine has closing lines and graded prop results, so the season can be
replayed: "build a 3-leg slip at the odds floor every week by method X — how
often did it cash?"

**Methods worth comparing** (all definable without P0 existing):

1. Random legs that clear +300
2. Highest-probability legs that still clear the floor
3. Correlated QB stack (QB + his pass-catchers)
4. Deliberately uncorrelated / cross-game (SGPx)
5. Best-priced legs by `ev_pct`
6. Goal-line-weighted legs for anytime-TD slips (once F4 exists)

**What it answers:** whether 20-25% boosts actually clear in practice, whether
correlated or independent slips cash more often at the same price, the real hit
rate versus the theoretical one, and how much leg-shopping is worth.

**Why it comes first:** P0 must commit to one construction method. Deciding
that empirically costs 2 hours; deciding it on theory and being wrong costs a
season. The harness — pulling historical closing lines and graded results — is
also infrastructure P0 reuses.

## F3. Unified CLV ledger across the whole copilot suite

CLV is sport-agnostic — it needs only the price taken and the closing line. One
ledger spanning the PGA, NCAAB, World Cup and Triple Crown copilots answers the
question none of them can answer alone: **which copilots produce edge and which
are entertainment?** After a season, that tells you where to invest and what to
retire.

## F4. Goal-line modeling — NOT "red zone share"

**Measured 2025-26, TD conversion by zone:**

| Zone | Rush TD rate | Pass TD rate | n (rush/pass) |
|---|---|---|---|
| Inside the 2 | **48.1%** | 34.7% | 622 / 426 |
| Inside the 5 | **38.2%** | 37.8% | 1,155 / 900 |
| Inside the 10 | 28.1% | **31.7%** | 1,912 / 1,747 |
| Red zone 1-20 | 16.4% | **21.7%** | 3,693 / 3,816 |
| 21-50 | 1.2% | **3.3%** | 6,663 / 8,456 |

**The crossover is the 5-yard line.** Inside the 20 the pass converts better;
only inside the 5 does rushing win, and inside the 2 it dominates. So
"red-zone share" is the wrong granularity — **goal-line (inside 5) carries must
be a separate input** from red-zone targets.

**Why this matters for the boost use case:** anytime-TD is a longshot market
(and the one where `shin` de-vig is required). Goal-line carry share is the best
available predictor of it, and it is not in any public ranking.

**Two findings already visible:**
- **Josh Allen: 24 goal-line carries, 18 TDs, 75% conversion.** Anytime-TD
  markets price QBs as passers; rushing QBs near the goal line are
  systematically underpriced.
- **Ashton Jeanty: 20 goal-line carries, 4 TDs, 20%** against a 38% baseline.
  Getting the volume, not converting. Either negative variance due to regress —
  which would make him a buy — or something real about Vegas's goal-line usage.
  **Directly relevant to the keeper decision.** Worth separating before next
  summer.

Conversion rates range 20% to 75% across players, so some is skill and scheme
and much is noise. **Shrink player rates toward the 38% baseline the same way
the QB/RB correlation work did** — do not trust a 20-carry sample raw.

## F5. Weather, wind and roof

`weather`, `temp`, `wind` and `roof` (dome / outdoors / closed / open) are all
in the play-by-play and completely unused. Wind wrecks passing and kicking
props, and books adjust game totals faster than they adjust individual props.

## F6. Line movement as a news detector

Opening-to-current movement reveals what the market learned. Combined with
`suspended_at` firing across several books, that is injury information arriving
**before the reporting does** — see P2.

## F7. DFS pick'em versus sportsbook divergence

PrizePicks, Underdog and Sleeper set lines differently from sportsbooks.
Systematic divergence against a sharp anchor is mispricing. Mind the
`payout_multiplier` trap on Underdog.

## F8. Fantasy extensions

- **Championship probability** for the three non-guillotine leagues — the
  guillotine simulation generalizes directly.
- **Opponent behavior modeling** via FantasyPros start/sit consensus: managers
  play the consensus, not the optimum. Would replace the pessimistic
  "everyone plays optimally" assumption (E5).
- **Trade valuation from market-implied rest-of-season value** rather than
  consensus rankings.

---

# THE BETTING OBJECTIVE — restated 2026-10-29

**This supersedes the "find the sharpest edge" framing that shaped the engine.**

The real goal is **exploiting profit boosts**. Those require, typically:
3+ legs, **+300 or better** on an SGP/SGPx, **$10 max wager**. Dustin wants to
maximize **P(cash)** subject to that odds floor, grinding $30-45 wins across a
season. He is comfortable up to ~+500 when supported, but regular hits beat
occasional big ones.

## Why this changes everything

**A profit boost on a FAIRLY priced parlay has EV = boost x (d-1)/d.** At a 30%
boost that is **+22.5% at +300, +25% at +500** — nearly independent of odds, and
an order of magnitude larger than the 1-3 point leg edges the engine was built
to hunt. **The boost IS the edge.** Finding mispriced legs is a rounding error
next to it.

| Odds | Breakeven | w/ 30% boost | EV at fair | $10 pays | hits/17wk |
|---|---|---|---|---|---|
| +300 | 25.0% | 20.4% | +22.5% | $39 | 4.2 |
| +400 | 20.0% | 16.1% | +24.0% | $52 | 3.4 |
| +500 | 16.7% | 13.3% | +25.0% | $65 | 2.8 |
| +700 | 12.5% | 9.9% | +26.2% | $91 | 2.1 |

**Target +300 to +450.** EV above that range improves by ~2.5 points while the
hit rate nearly halves. Given the stated goal of grinding regular wins, the
extra EV is not worth the variance.

**Target shape: three legs near -150 each (60%).** Three such legs price at
+363, clear the floor, and carry 21.6% true probability against a 20.4% boosted
breakeven. Shorter legs cash more but fail the +300 requirement — the floor is
the binding constraint, not leg quality.

## Boost policy — which offers are worth playing

Boosts seen in the wild: 10%, 20%, 25%, 30%, 50%, rarely 100%. **A 3-leg parlay
carries roughly 14% compounded hold** (three legs at ~5% each), so the boost has
to clear that before any of it is profit.

**EV = boost x (d-1)/d  -  parlay hold**

| Boost | +300 | +400 | +500 | +700 |
|---|---|---|---|---|
| 10% | -6.5% | -6.0% | -5.7% | -5.3% |
| 20% | +1.0% | +2.0% | +2.7% | +3.5% |
| 25% | +4.7% | +6.0% | +6.8% | +7.9% |
| 30% | +8.5% | +10.0% | +11.0% | +12.2% |
| 50% | +23.5% | +26.0% | +27.7% | +29.8% |
| 100% | +61.0% | +66.0% | +69.3% | +73.5% |

**Break-even boost is 17-19%.** Rules:

- **10% boost: do not play.** Negative at every price.
- **20-25%: stretch to +500-700.** EV is marginal and longer odds are what make
  it positive.
- **30%+: sit at +300-400 and cash more often.** EV is comfortable either way,
  so optimize hit rate instead of squeezing EV.
- **50%/100%: play them every time one appears.** These dwarf everything else
  the engine could find.

**Leg shopping moves this materially.** Legs at 4.5% hold compound to 12.9%; at
6% to 16.9%. That swing is roughly the difference between a 20% boost working
and not. Shopping every leg across FanDuel/DraftKings/BetMGM is worth as much
as finding a better leg.

**Prefer SGPx when the boost allows it.** Cross-game legs are uncorrelated per
the measured table, so fair joint = product of de-vigged leg probabilities and
hold is EXACTLY computable. Same-game slips require a true joint we cannot
estimate, so their EV is an informed guess. Verifiability is worth more than a
slightly better headline price.

## What this means for the engine

- **The model does NOT pick legs.** De-vigged market probability is the better
  estimate of P(leg hits), always. Use `get_event_ev` fair probs.
- **The model VETOES legs.** `usage_trend` / `role_trend` / `decline_onset`
  exist to say "not this player — his role collapsed and the sample lies."
  Screening, not selection. This is the model's real job and it is a good one.
- **The only edge beyond the boost** is a `correlation_factor` more lenient
  than the measured correlation table justifies. A lightly-haircut QB+WR stack
  means true joint probability exceeds the price. That screening criterion is
  now the core method.
- **SGPx (cross-game) legs are uncorrelated** per the measured table, so books
  should price them at the independent product. A haircut on an SGPx is
  unjustified and should be refused.

## P0. Build the boost-slip optimizer  *(NEW — now the top betting item)*

**Value: HIGHEST. Effort: ~90 min.** Nothing in the engine currently solves the
actual problem. Needed:

1. Pull `get_event_ev` across the slate; keep legs whose price is not badly
   worse than fair (ev_pct >= about -2%).
2. Veto any leg whose player carries a role-change flag against that side.
3. Enumerate 3-leg combinations landing in +300 to +450.
4. Prefer combinations with real positive correlation (QB + his pass-catchers,
   per the measured table) since those raise true joint probability.
5. Price the survivors with `price_sgp` across books; compare each book's
   `correlation_factor` against the measured table and flag slips where the
   book is charging LESS than the correlation warrants.
6. Report P(cash), the boosted payout on $10, and the boosted breakeven.

**Until this exists, the betting workflow does not serve the actual use case.**

---

# BETTING-SIDE FINDINGS

## P1. The model is not an edge source for betting — stop presenting it as one

**Severity: HIGH. This mis-signals every week it runs.**

Track record of `ff_props` against sharp de-vigged lines, every case where they
disagreed by more than noise:

| Player | Model | Sharp line | Gap | Who was right |
|---|---|---|---|---|
| Darren Waller 21.5 rec yds | 80% | 50% | +30 | **market** |
| MarShawn Lloyd 4.5 rec yds | 71% | 42% | +29 | **market** |
| Josh Allen 250 pass yds | 51% | 49% | +2 | agreed, no action |

**Zero for two on disagreements**, both caused by role changes the model could
not see. This is not bad luck — it is what theory predicts. A threshold
estimate built on 6-7 games, carrying a 95% interval 40+ points wide, cannot
out-estimate a de-vigged Pinnacle line that aggregates far more information.

**The problem is that `prop_edge` emits a number called "edge."** A +30-point
edge reads like a finding. It is an artifact of a stale sample.

**Fix — and it is a simplification, not a loss:**
- **`propline_get_event_ev` is the edge source for betting.** It compares a real
  book price to a real sharp line. No model involved, no sample-size problem.
- **`ff_props` becomes context, not signal.** Its genuine contributions to a
  betting decision are `usage_trend`, `role_trend` and `decline_onset` —
  explaining WHY a line might be mispriced. That is real value the market data
  does not provide.
- Relabel or suppress the model-vs-market "edge" in a betting context, or gate
  it behind an explicit opt-in. The threshold engine stays useful for FANTASY
  (projecting a player for a lineup) where there is no market to beat.

## P2. Live PropLine signals are ignored — `suspended_at`, `pregame_only`, `max_age`

**Severity: HIGH. Effort: ~20 min.** Three fields carrying real information,
none mentioned in the instructions:

- **`suspended_at`** — the book pulled that market pregame. The tool's own
  guidance: treat as unbettable, and **if several books suspend the same
  player, treat it as a probable scratch.** That is injury information arriving
  BEFORE the news does, and we are discarding it.
- **`pregame_only`** — once a game is live, books without an in-play feed return
  their last pregame quote forever. Nothing goes stale-flagged because the book
  is simply never polled again. Quoting those as live prices is a real error.
- **`max_age`** — drops quotes a book has not refreshed within N seconds. Not
  used, so a 20-minute-old price can be presented as current.

**Fix:** document all three; filter suspended markets out; pass `max_age` on
in-play pulls; refuse to quote `pregame_only` books once a game has started.

## P3. `shin` de-vig is never used, and multiplicative is wrong for longshots

**Severity: MEDIUM. Effort: ~10 min.** `get_event_ev` accepts
`devig="shin"`, which corrects the favourite-longshot bias by loading the
overround onto the longshot. The tool explicitly says to use it for anytime-TD
and first-scorer markets. We always use the default multiplicative, which
**systematically overstates the fair probability of longshots** — exactly the
markets a $10 entertainment bettor is most drawn to.

**Fix:** use `devig="shin"` for any TD-scorer or long-odds market, and echo
`devig_method` when reporting.

## P4. No slate-level exposure tracking

**Severity: MEDIUM. Effort: ~30 min.** Flat stakes ($13/$10/$5) implicitly
assume bets are independent. Five props on the same game are not — the measured
correlation table shows QB/WR pairs at +0.31, and a game that goes under drags
every total-based leg with it. Betting five "independent" $10 props on one game
is closer to one $50 bet than to five $10 bets.

**Fix:** track exposure per game and per correlated cluster; warn when a slate
concentrates. Pairs with the bet log (E2).

## P5. The edge threshold is uncalibrated and Kelly is dead code

**Severity: LOW, but it creates false precision.** The 3-percentage-point gate
that decides PASS vs COIN-FLIP was chosen by me with no derivation. A typical
estimate carries a **43-point** confidence interval — the gate is 14x narrower
than the uncertainty it sits inside. Meanwhile `prop_edge` computes a Kelly
fraction, returns it, and nothing ever reads it; stakes come from a flat dict.

**Fix:** either calibrate the threshold against CLV once there is a bet history,
or state plainly that it is a convention rather than a derived number. Remove
Kelly or actually use it — returning an unused number invites someone quoting it.

## P6. No record of engine recommendations, only of bets placed

**Severity: MEDIUM.** E2 logs what was bet. Nothing logs what the engine
*said* — including its PASS calls. Without that, there is no way to ask "would
we have done better following or ignoring it," which is the question that
decides whether any of this is worth running.

**Fix:** append every recommendation (including PASS) to the same log with a
`recommended` flag, so engine calls can be graded separately from bets placed.

---

## B1. Phantom players corrupt opponent projections — ACTIVE BUG

**Severity: HIGH. Wrong output today.**

`_draw()` and `_mean_of()` fall back to a mean of **6.0** for any name not in
the nflverse pool. The pool's real-player mean is 2.4, so **6.0 outranks 1,058
of 1,687 real players** — a phantom gets STARTED over most genuine ones.

Roster names come from FantasyPros, pool names from nflverse, and they differ on
name suffixes. **7 of 10 guillotine rosters contain an unmatched name**, and one
is being started right now:

```
Patrick Mahomes II  James Cook III     Travis Etienne Jr.
Aaron Jones Sr.     Kyle Pitts Sr.     KC Concepcion Jr.
De'Zhaun Stribling  (genuinely absent — no 2026 data)
```

**Measured impact:** "Show me those TD's" projects 113.8 with Mahomes as a
phantom, **124.5** with him resolved (+10.7). The lowest opponent projection
rises 113.8 -> 119.8, so **P(eliminated) is understated** — the error flatters
the user, which is the kind that never prompts a second look.

**Fix:** normalize names (strip Jr./Sr./II/III/IV, punctuation, case) and build
a canonical lookup in `build_pool`. Resolves 6 of 7 above. **Critically, the
real fix is to STOP SILENTLY SUBSTITUTING** — an unresolved name must surface
in the `Result` and in `report()`, not vanish into a 6.0.

**This is the THIRD name-matching bug in this project** — the draft playbooks
hit it on SOS lookups, `add_explosive_tds` hit it on abbreviated names this
afternoon. Standing rule: never join player data on a name without
normalization, and never let an unmatched name take a default value silently.

## B2. `best_lineup` does not validate positions

**Severity: MEDIUM.** `best_lineup({"RB": ["Blake Corum"]}, pool)` returns a
one-player "lineup" with no error. `enumerate_lineups` correctly raises on a
missing QB; `best_lineup` — which builds every OPPONENT's lineup — does not.
A malformed or short roster silently produces a low total, making that opponent
look weak and the user look safe. Same failure direction as B1.

**Fix:** verify the lineup fills every slot; raise or report explicitly.

## B3. `data_status()` cannot actually detect staleness

**Severity: MEDIUM.** It reports the latest week IN THE FILE and has no idea
what the current NFL week is — the sandbox cannot reach a schedule source. So
"DATA AS OF Week 7" reads identically whether that is current or three weeks
behind. Today it is correct only because a human cross-checked the connector.

**Fix:** accept an optional `current_week` and say plainly when the file is
behind. The session already pulls `current_week` from FantasyPros; pass it in.

## B4. `prop_edge` accepts a nonsensical `fair_over`

**Severity: LOW.** `fair_over=0.0` or `1.0` returns a tier instead of being
rejected, producing a meaningless infinite edge. Validate to (0, 1) exclusive.

## B5. `enumerate_lineups` returns an empty list silently

**Severity: LOW.** A roster too small to fill the lineup returns `[]` rather
than raising, so `run()` fails later with an opaque error. Raise at the source.

---

## E1. Byes and injuries are not modeled in the guillotine

**Value: HIGH. Effort: ~45 min.** The simulation will happily project a player
on bye at his season average. A session caught Germie Bernard's Week 9 PIT bye
manually and zeroed five opponent bye players by hand — that should not depend
on someone remembering.

**Fix:** accept `unavailable: list[str]` in `run()`, exclude those players from
lineup construction entirely (not zero them — a zeroed player can still be
"started," which is worse), and list them in `report()`. Bye weeks are
derivable from the data — `ff_props.bye_weeks()` already does it.

**Week 9 byes land this Sunday, so this one has a date on it.**

## E2. No bet log, so CLV cannot be graded

**Value: HIGH. Effort: ~30 min.** `propline_grade_clv` is the honest scorecard
for whether this project has edge, and it needs the price actually taken on
each bet. **Nothing records that today**, and it cannot be reconstructed later.

**Fix:** a simple append-only CSV (`bets.csv`) plus a helper that formats rows
for `grade_clv`. Columns: date, event_id, sport, market, selection, side,
point, price_taken, bookmaker, stake, ref. Must be written the moment a bet is
placed.

## E3. The correlation table is not reproducible — AND IT IS FILTER-SENSITIVE

**Value: HIGH, raised 2026-11-05. Effort: ~45 min. Blocks F13.** The
43,228-pair correlation map lives only as constants in
`ff_guillotine.SAME_TEAM_CORR` and in the instructions. The script that
produced it was ad-hoc and is gone, so it cannot be refreshed as the season
adds data.

**Measured 2026-11-05 while scoping F13: the documented values cannot be
reproduced, and the reason matters more than the fact.** Rebuilding the pool
from nflverse 2025-26 and sweeping the two obvious filters — minimum games
for a player's z-score baseline, and a minimum per-game volume to count a
game at all — gives:

| filter | pairs | QBxWR | QBxTE | RBxRB opp | QBxRB |
|---|---|---|---|---|---|
| **documented** | **43,228** | **+0.31** (2217) | **+0.27** (1203) | **-0.14** (1395) | **-0.10** (1353) |
| games>=4, no vol | 78,040 | +0.24 (3643) | +0.23 (1896) | -0.07 (2802) | -0.08 (2308) |
| games>=6, no vol | 65,569 | +0.26 (2945) | +0.26 (1500) | -0.09 (2298) | -0.09 (1798) |
| games>=4, vol>=5 | 12,997 | +0.37 (1047) | +0.46 (392) | -0.17 (778) | -0.10 (1083) |
| games>=6, vol>=5 | 9,575 | +0.37 (791) | +0.50 (250) | -0.18 (639) | -0.10 (904) |
| games>=8, vol>=5 | 6,806 | +0.36 (551) | +0.50 (185) | -0.19 (491) | -0.10 (720) |

**The documented numbers are PLAUSIBLE — every one sits inside the range the
sweep produces — but none of these filters lands on them**, and the
documented pair count (43,228) sits between two of them. So the table is not
wrong; its method is simply unrecoverable.

**The real finding is the sensitivity.** QB x TE runs from **+0.21 to +0.50**
across reasonable filter choices, a 2.4x swing on an undocumented decision.
RB x RB opposing runs -0.07 to -0.19. These are not small differences: the
instructions tell a session to compare the book's `correlation_factor`
against this table, and a factor that looks fair against +0.27 looks like a
steal against +0.50.

**Fix, revised:** a `ff_correlation.py` that (a) recomputes the WHOLE table
on one explicitly documented filter, existing four entries included, so the
table is internally consistent; (b) prints the filter alongside the values;
(c) reports a pair count and an interval per entry, not a bare point
estimate. **Expect the shipped constants to change** — that is the point,
and it is a live behaviour change that needs Dustin's sign-off, because
`_pair_r` feeds `classify()` and therefore whether a slip gets an EV at all.

**Also found, independent of the above and live today:** `_pair_r` maps a
`{PASS, RECV}` same-team pair to `SAME_TEAM_CORR[("QB","WR")] = +0.31`
unless the receiving player's position is literally TE. **An RB with a
receiving prop therefore gets +0.31.** Measured: QB passing yards x RB
receiving yards, same team, is **+0.157** (n=2,154) — overstated roughly 2x.
The table has three position pairs on the receiving side and the code
distinguishes only TE from not-TE. **FIXED as B67 2026-11-05**, with the
ratio rather than the raw level, pending this item.

**E3 now serves TWO callers, and they need DIFFERENT tables — added
2026-11-05 with B68.** `ff_guillotine.py:102-103` has its own duplicate
literal copy of both tables, so the four values are doing two unrelated jobs:

- **`ff_boost` needs a MARKET table** — QB *passing yards* × RB *rushing
  yards*, one market against another. That is what the documented numbers
  measure, and what the sweep above reproduces.
- **`ff_guillotine` needs a FANTASY-SCORE table** — total points against
  total points, receptions and TDs included. The market numbers are simply
  the wrong quantity there, and for QB×RB they are the wrong **sign**: six
  filter variants on fantasy scores give **+0.033 to +0.089, never negative**,
  against −0.10 in the code. The game-script drag that makes passing yards
  trade off against rushing yards does not survive into points, because TDs
  are upside both players share.

So E3's deliverable is **two tables from one documented filter**, not one —
plus a single home for them, since the duplicate is why B67 needed fixing
twice. **The betting side is the one that needs sign-off** (it gates whether
a slip gets an EV at all); the fantasy side's effect was measured at under
0.1pp of P(elim) with no change to the recommended lineup, so it can move
without ceremony. Full numbers in B68.

## E5. Opponent lineups assume optimal play

**Value: LOW. Effort: HIGH.** Every opponent is assumed to start their best
eight by mean. Real managers misplay lineups, leave injured players in, and miss
byes. The model is therefore pessimistic about the user's survival odds —
a conservative bias, which is the right direction to be wrong in. Not worth
modeling without data on how these specific managers behave.

---

## E4. DST team scoring  *(requested 2026-10-29)*

**What:** Compute team defense/special-teams fantasy points under each league's
real rules. Currently `score_dst()` raises `NotImplementedError` rather than
returning zeros, so nothing is silently wrong — but DST advice falls back to
connector projections that are known-wrong for Holmdel's.

**Why it matters:** Holmdel's points-allowed ladder pays **5/3/1** at 7–13 /
14–20 / 21–27 where the connector assumes **4/1/0**. Most defensive games land in
those middle bands, so the connector systematically undervalues them. Sacks are
worth 1, not 2.

**What it needs:**
- Points allowed — NOT in the weekly player file. Lives in game/schedule data.
  nflverse's `schedules`/`games` release paths 404'd on 2026-10-29; the working
  source still needs to be found. Deriving from play-by-play is a fallback.
- Team-level aggregation of the `def_*` player columns (sacks, INTs, fumbles
  recovered, TDs, safeties, blocked kicks) — these exist per-player and need
  summing by team and week.
- 4th-down stops at +0.5 (Holmdel's only) — needs play-by-play: 4th-down plays
  where the defense prevented a conversion.
- Return TDs and extra-point returns.

**Definitional care needed:** fantasy "points allowed" usually excludes points
the opposing *defense* scored against your offense. Confirm Yahoo's treatment
before trusting the number.

**Estimate:** ~1 hour, most of it finding a reliable points-allowed source.

**Rules are already recorded** in `LEAGUES['holmdels'].dst` — this is a compute
task, not a research task.

---

## 2. Guillotine survival simulation  *(not yet requested — flagged as high value)*

**What:** Monte Carlo over all ten teams' lineups to estimate P(lowest score
this week), rather than maximizing expected points.

**Why it matters:** In an elimination league the objective is genuinely
different. If projected comfortably above the cut, the correct play is the
*lowest-variance* lineup. If projected near the bottom, it's the highest-variance
one. Expected-points optimization gives the wrong answer in both cases, and no
projection site computes this because the question doesn't exist in redraft.

**Timing:** Mid Season Guillotine runs Weeks 9–17. First cut is Week 9.

**What it needs:** per-player scoring distributions (the `ff_props` engine
already produces these), opponent lineup estimates via the connector, and a
simulation loop.

---

## ~~3. Usage-trend guard for the prop engine~~ — BUILT 2026-10-29

Shipped in `ff_props.py`: `opportunity_column()`, `usage_trend()`, `UsageTrend`,
wired into `Estimate.usage` and enforced in `prop_edge()`.

**How it works:** compares opportunity over the last N games against the prior
games only (not the whole sample, which includes the recent games and dilutes the
signal). Window scales with sample size — 2 games on a short sample, up to 4 on a
long one. A fixed window of 3 was tested first and missed Waller.
COLLAPSED below 60%, EXPANDED above 160%.

**Enforcement:** a flagged role change forces `tier = PASS` regardless of edge.
Verified on Waller — a +30.8 point edge at +54% EV returns PASS, $0.

**Calibration:** 17.3% flag rate among players with a baseline of 7+ targets or
carries (the ones with real prop markets); every flag inspected was a genuine
role change. Higher rates below that threshold are harmless — no prop market
exists there.

**Known limitation:** a 2-game window on a 5-7 game sample is noisy. Some flags
will be one-off game scripts rather than permanent changes. The guard asserts
"the model is unreliable here," not "this player is finished" — which is the
correct and more modest claim.

*Original problem statement kept below for context.*

### (original)

**The problem:** `ff_props.threshold_prob()` weights OUTCOMES, not OPPORTUNITY. A
player whose role has collapsed but who broke one long play still scores well on
every estimator, including the recency-weighted one.

**The live case:** Darren Waller, receiving yards 21.5. Model said 80%, Pinnacle
said 50%. His targets went 2, 3, 8, 6 in Weeks 1–4 then 2, 2 in Weeks 6–7 — role
gone. At current usage his expected output is 17.2 yards, well under the line.
The recency weighting returned 81%, HIGHER than the normal fit, because Week 7
was 50 yards on one catch. Every estimator agreed and every estimator was wrong.

**The fix:** before returning an Estimate, compare recent opportunity (targets /
carries / pass attempts over the last 2–3 games) against the sample mean. When
recent usage is materially below the sample — say below 60% of it — either widen
the interval sharply or refuse to return a point estimate, and say why. The same
guard should fire in reverse for a player whose role just expanded.

**Why it matters beyond this one bet:** mid-season role changes are common, and
this is precisely when a prop looks most mispriced and is not. Sportsbooks price
current usage; a backward-looking sample does not.

---

## 4. Live prop odds ingestion  *(in progress 2026-10-29)*

See the odds research. Blocked on a decision about which route to take —
the sandbox cannot reach any odds provider directly.
