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
| **B51** | Anchor scarcity is a standing constraint on cross-game MODE, filed separately so it stops being confused with the hold gate | **OPEN** | `get_market_coverage(days=7)`, 15 events in window: Pinnacle carried pass/rush/reception yards on **1** event; confirmed not a filter artifact. Cross-game leg selection needs 3 anchored events, so for most of the week the module cannot be used as designed — and rungs, now that B49 makes them parseable, would anchor off Kalshi contracts carrying a dollar or two, the input B46 exists to reject. **This does NOT gate the hold re-measurement**, which de-vigs a book's own two-sided legs and needs no external anchor (the first measurement ran on DK + FD over 2 events while Pinnacle covered almost nothing). A 2026-11-03 edit of HANDOFF merged the two and wrongly reported the re-measurement as blocked; corrected same day. No route to better anchors is known. Do not record a coverage figure here as standing — D16. |

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

`get_market_coverage(days=7)`, 15 events in window: **Pinnacle carries
pass/rush/reception yards on ONE event.** Confirmed not to be a filter
artifact — dropping the `bookmakers` filter showed 17 books on an event
Pinnacle simply is not on. BetMGM carries **none** of the three markets.

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
| **F4** | Goal-line modeling (inside-5 carries) | 90m | Best available predictor of anytime-TD; shrink rates toward the 38% baseline |
| F5 | Weather / wind / roof | 60m | Books move game totals faster than props |
| F6 | Line movement as a news detector | 60m | Information before the reporting |
| F7 | DFS pick'em vs sportsbook divergence | 60m | Different pricing mechanism = mispricing |
| F8 | Championship odds, opponent modeling, trade value | varies | Fantasy depth |

## Tier 5 — when there is time

| # | Item | Effort | Note |
|---|---|---|---|
| E4 | DST team scoring | 60m | `score_dst()` already refuses to lie; no deadline |
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

## E3. The correlation table is not reproducible

**Value: MEDIUM. Effort: ~30 min.** The 43,228-pair correlation map lives only
as constants in `ff_guillotine.SAME_TEAM_CORR` and in the instructions. The
script that produced it was ad-hoc and is gone, so it cannot be refreshed as
the season adds data — and these estimates will tighten considerably by Week 14.

**Fix:** a `ff_correlation.py` that recomputes the table from the pool and
prints it, so the constants can be updated with one command.

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
