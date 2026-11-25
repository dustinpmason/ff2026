# Wednesday night — Packers @ Rams, two items

Two blocks, pasted into the SAME new project thread:

| When (ET) | Paste | Why then |
|---|---|---|
| **Wed 11/25, 2:15pm to 4:30pm** | MAIN, with the Bet365 boost's terms screenshot attached | Inside six hours of the 8:00pm kickoff, so Pinnacle fairs can count as verified |
| **Wed 11/25, 6:35pm to 7:30pm** | RE-CHECK | Inactives post about 6:30pm |

Thursday's and Friday's games get their own prompt. The two BetMGM items
(100% token, $10 bonus bet) and FanDuel's 50% are held for Thursday.

---

# MAIN — paste Wednesday between 2:15pm and 4:30pm ET

Packers @ Rams, kickoff Wed 11/25 8:00pm ET, PropLine event 32694. Bottom
line first, then the reasoning. Soft anchors do not stop the run; they
decide the tier.

## What Dustin holds for tonight (read from his screenshots, Tue 10:18pm ET)

| # | Book | Item | Max stake | Min odds | Legs / bet type | Window |
|---|---|---|---|---|---|---|
| F30 | FanDuel | 30% Profit Boost | $10 | +100 (max +200000) | 3+ leg SGP / SGP+; Packers @ Rams ("See more" not opened); pre-game or live | dated 11/26 |
| G1 | **Bet365** | "Gravy Train" Super Profit Boost, **Boost 1 of 6: 50%** | on the attached screenshot | on the attached screenshot | on the attached screenshot | must be USED today |

**G1 is a chain.** Bet365 gives one boost a day from Wed 11/25 to Mon
11/30: 50%, 60%, 70%, 80%, 100%, then 200% on Monday. Each is unlocked
only by claiming AND using the one before it. So G1 is placed tonight
whatever its tier: if nothing is positive, give the least-negative bet
that meets the terms at the smallest stake the terms allow, and say what
it costs. Skip is not an answer for G1.

**Read G1's terms from the attached screenshot and print them first**
(stake limit, minimum odds, bet types and number of selections, eligible
sports and events, when it expires, any cap on winnings). If no screenshot
is attached, ask for it in your first reply and keep working: build G1
both ways in step 4 (a straight bet, and a 3+ leg same-game parlay).

**Bet365 is not on PropLine.** For G1 the deliverable is the price each
bet needs, which Dustin reads against the Bet365 slip.

Held for Thursday, not for tonight: FanDuel 50% (any bet type, -200
minimum, $10, Bears @ Lions "+2 more"); BetMGM 100% Odds Boost Token
(straight, parlay or SGP, -300 total minimum, $10, NFL, expires Fri 6:04pm);
BetMGM $10 Bonus Bet (expires Thu 11:13pm). Do not build for them.

**In your first reply ask Dustin, in one message, and keep working:**

1. Has he received any other boost since Tuesday 10:18pm (DraftKings had
   sent nothing)?
2. Has he already placed anything on this game?

## Dustin's rule: no UNDER on any starter

Dustin does not bet the under on a starter. Apply this to every pool
before anything is built. A player is a starter if ANY of these holds:

- he is a quarterback with a posted line;
- he is QB1, RB1, TE1 or WR1 to WR3 on FantasyPros' depth chart (codes GB
  and LAR);
- he averaged 50% or more of offensive snaps over his last three games
  with a snap (`st[player].games`);
- he played 50% or more in his last game.

Report per book how many legs the rule removed, and name every under that
still reaches a slip with the reason it is allowed. This is Dustin's
preference, not a finding, and it is settled: apply it and show the cost.

**Nothing is a bet recommendation until Dustin says he placed it.** Do not
call `log_bet` unless he does. Do log every slip you show with
`log_slip_rec`.

## Step 0 — setup

1. Re-clone. Print the commit hash and `DATA AS OF`, passing the
   connector's `current_week`.
2. `python3 test_regression.py`, last three lines. Expected: `1966 checks
   run, 1966 passed, 0 failed`, `ALL PASS`. A lower count means a file is
   missing from the commit: say so and stop.
3. Pull the bet log with `bl.load_drive_search(...)`, print
   `bl.drive_pull_report(r)`, then `record_pull` and `status()`.
4. Do not patch anything; paste every traceback in full and move on.
   Build `aliases` and `meta` first. A pull has a 15-minute working life:
   re-pull before each step that builds verdicts or prices. Pass the SAME
   `quotes` list object to every call made from one pull.

## Step 1 — the board, the clock, injuries

```python
h = ff_boost.hours_to_kickoff(event["commence_time"])
print(round(h, 1), ff_boost.anchor_drift(h).describe())
```

Read that line out. If `h` is over 6, say nothing is verified yet and when
to re-pull, and finish the run anyway.

`anchor_coverage`: if the EV feed anchors nothing on Pinnacle while
Pinnacle has two-sided lines, say so at the top and de-vig Pinnacle's own
prices from the same pull (Shin). Start every `fair_source` with the
anchor's name and name no other book in it.

Injuries and context, from PropLine's feed AND the web, each with its
source and date. By name: **Josh Jacobs** (finger; his coach said Monday he
was unlikely to play, the Packers listed him questionable Tuesday),
**Kyren Williams** (toe soreness, expected to play), **Puka Nacua** and
**Davante Adams** (both on injured reserve), **Luke Musgrave**, and every
player you shortlist. Both teams were on a bye in Week 11. Inactives are
due about 6:30pm; say they are not out yet. Roof status at the stadium.
Each shortlisted player's CURRENT team.

## Step 1b — the news sweep for this game (new this week)

This sets role news beside each book's line. It gives no probability and
it does not change any verdict the engine makes. It adds two tags to the
leg tables in step 2b.

1. ONE call, saved to a file by the harness:
   `propline_get_injuries(sport_key="football_nfl")`.
2. ONE call, saved to a file by the harness:
   `propline_get_event_movement(sport_key="americanfootball_nfl",
   event_id=32694, markets="player_pass_yds,player_pass_attempts,player_pass_completions,player_pass_tds,player_rush_yds,player_rush_attempts,player_reception_yds,player_receptions",
   bookmakers="draftkings,fanduel,betmgm")`. Do not pass "since".
3. Copy `flags_wk12.json` from the repo to `flags_tonight.json`. In the
   copy, add an entry for anything step 1 found that the injury report
   does not carry, in the shape of the entries already there, with the
   time it was published and its time zone. Never retype the two saved
   responses.
4. Run:
   `python3 ff_news.py --week 12 --no-save --injuries <injuries file> --flags flags_tonight.json <movement file>`
   If it prints STOPPED naming an entry as more than 72 hours old: if you
   re-read a current source that still says so, add `"confirmed": "<the
   time you read it, with zone>"` to that entry and keep its `"at"`;
   otherwise delete the entry from the copy. Run again. On Tuesday night
   the Kyren Williams entry was the one it named.
5. Paste section 0 ("NEWS THE LINE MAY NOT HAVE CAUGHT UP WITH"), every
   "! FLAGGED OUT, YET" line, section 1b and the player names in section 2
   (lines on a hot run), as printed.

What the two tags mean, and the only way they are used:

- **NEWS.** A player named in section 0 gets the line from section 0 in
  his row. It is a lead, not a verdict. In the 41 games tested, an over on
  a line a book had not yet moved for a teammate's absence came in 54.5%
  (101 lines from 14 games: too few to act on alone).
- **HOT.** A player whose line is in section 2 gets "HOT" on his OVER
  rows. In the same 41 games, overs on lines like that came in 43.6%
  against 50.8% priced (287 lines). Use it as a tie-break only: when two
  legs are within 2 points of win %, take the one that is not a HOT over,
  and say whenever a recommended slip contains a HOT over. It is not a
  reason to bet the under.

## Step 2 — the pools, the snap check, the census

One pool for **FanDuel**, from its own prices: main lines both sides,
rungs (`ladder_margin` → `ladder_cross_check` → `ladder_fair` →
`rung_legs(..., market=<that market's key>, meta=meta, aliases=ALIASES,
tiers=...)`, once per market, no `odds=`), and anytime-TD YES legs where
an anchor has a two-sided price. A second pool from **DraftKings** prices,
used only as the stand-in for Bet365 in step 4.

- **Anytime TD.** The books post it with no point; Pinnacle posts it as
  Over/Under 0.5. Join them on the player.
- **A TD leg inherits the player's veto.**
- **Rungs.** Mark every rung above 1.25 times the player's main line
  "LONG RUNG". Measured blind on 41 games at the best of three books,
  rungs under 0.8 times the main line gave up 5% to 7%, rungs from 1.25 to
  1.6 times gave up about 20%, and rungs above 2.2 times about 42%. Prefer
  the low rungs when two legs are otherwise close, and say when a
  recommended slip carries a LONG RUNG.

Before the verdicts, once:

```python
st = ff_props.snap_trends(snaps, roster, wk, {x["player"] for x in quotes},
                          aliases=ALIASES)
print(ff_props.snap_summary(st))      # every FLAGGED, ABSENT, NOT CHECKED
```

Both teams were idle in Week 11, so "last game" is Week 10: say so once.
Pass `snap=st.get(player)` into every `boost_verdict`. A leg on an ABSENT
player rests on the market's number alone: say so wherever he appears.

Then the census:

```python
rows_fd = ff_boost.usable_legs(fd_pool, boost_pct=0.30, hours=h, snaps=st)
rows_dk = ff_boost.usable_legs(dk_pool, boost_pct=0.50, hours=h, snaps=st)
print(ff_boost.usable_report(rows_fd, top=8, boost_label="FanDuel legs, 30%"))
print(ff_boost.usable_report(rows_dk, top=8, boost_label="DraftKings legs as a Bet365 stand-in, 50%"))
fd_verified = [r.leg for r in rows_fd if r.read in ("CLEARS", "THIN")]
dk_verified = [r.leg for r in rows_dk if r.read in ("CLEARS", "THIN")]
```

Report per book: legs built, verdict counts, refusals with reasons
counted, and the counts line.

## Step 2b — the leg tables

Paste all three tables **in the reply**, straight after the bottom line.
"Win %" is the leg's fair chance of cashing: the de-vigged anchor price,
never the game-log model's number. Sort every table by win %, highest
first.

Columns for every table: player and team; the leg in plain words; main
line or rung (with LONG RUNG where it applies); the price at FanDuel and
at DraftKings; **win %** with "1 in N"; what the fair rests on; VERIFIED
yes or no; the verdict (CLEAR / CAUTION, and why in a few words); any snap
flag; **the NEWS and HOT tags from step 1b**; and how often he has cleared
that line this season, "X of N games", with his last four results. That
last column is a fact from the game log, not a lean; say so once.

1. **Player overs.** Every non-VETO OVER, main lines and rungs. Up to 25
   rows. A rung's win % is an estimate, and no rung is VERIFIED; mark it.
2. **Player unders, under Dustin's rule.** Every non-VETO UNDER on a
   player who is NOT a starter. Under it, one line naming the starters
   whose unders the rule removed.
3. **Anytime TD scorer.** Every player with a YES price and a fair from an
   anchor's two-sided price. Players with a price but no two-sided fair go
   in one line under the table, with no win %.

Above the tables, one line each: the pull time, hours to kickoff with the
drift line, and how many legs are VERIFIED.

## From the tables to the slips

Every slip below is assembled from legs in those tables, and shows it. For
each item give two slips:

- **Best value:** the highest EV at the book's real quote.
- **Most likely:** the highest chance to cash among slips that clear the
  item's minimum and are not negative at the quote. If no such slip is
  positive, say so and show the least-negative one with its EV.

Write each leg with **its win % beside it**, then the slip's own chance to
cash. For a same-game slip the legs' win % do not simply multiply: give
the engine's figure and say whether it is a floor or an estimate.

## Step 3 — F30, FanDuel 30%, 3+ legs, +100

```python
f30 = ff_boost.enumerate_candidates(fd_pool, meta, boost_pct=0.30,
        mode="single-game", event_id=ev, floor=100, ceiling=600,
        legs_per_slip=3, limit=12, stake=10, aliases=ALIASES, quotes=q)
```

Build it a second time from `fd_verified` if that pool has legs on at
least three players. For both: `build_notes`, `immature_slips`,
`too_good_slips`, the price target printed, the build time. Re-pull, then
price every shortlisted slip with `propline_price_sgp` at FanDuel (on a
503 `book_unavailable`, retry once). Table: quote, quote/product, clears
+100, verdict, chance to cash with "1 in N", cushion, EV, confidence.
FanDuel's real slip has run 5 to 7% under PropLine's quote: give the EV at
the quote and at 6% under it. A 30% boost on a same-game parlay is close
to what the markup takes; if nothing is positive, Skip is a complete
answer for F30.

## Step 4 — G1, the Bet365 50% boost

Build to the terms on the screenshot. Share no player with the F30 slip.

```python
need = ff_boost.needed_odds(p, 0.50, minimum=<the boost's minimum odds, if any>)
ev_dollars = stake * (p * (d - 1) * 1.50 - (1 - p))     # d = decimal price
```

`p` is the chance the bet cashes; `d` is DraftKings' price, as the
stand-in. The deliverable is `need`: **the price it needs at Bet365**.

- **If a straight bet qualifies:** rank `dk_verified` and the anytime-TD
  YES legs whose fair is Pinnacle's two-sided price by `ev_dollars`, after
  Dustin's rule, non-VETO, not `too_good`. Give the best six: the bet in
  plain words, win % with "1 in N", what the fair rests on, VERIFIED,
  NEWS and HOT tags, DraftKings' stand-in price, the price it needs, and
  EV in dollars at the stand-in. Best value and most likely.
- **If it needs 2 or more selections:** build from `dk_pool` with
  `enumerate_candidates(..., boost_pct=0.50, mode="single-game",
  floor=<the minimum>, legs_per_slip=<the minimum number>, ...)`. The
  chance to cash is the engine's same-game figure; say whether it is a
  floor or an estimate, and give the price it needs for that chance.

If Bet365 posts a different line from DraftKings, the `p` does not apply
and Dustin should send the slip back. Say what stake you would use and
why, within the terms.

## Step 5 — no player on more than one slip

The better slip keeps its legs; the other takes its best slip that shares
no PLAYER with it. Say what the rule cost. Then name the one game script
that sinks both.

## Step 6 — check each chosen slip

```python
print(ff_boost.score_slip(legs, meta, boost_pct=<boost>, book_odds=<quote>,
                          aliases=ALIASES, quotes=q,
                          floor=<the item's minimum>).report())
```

A correlated slip reads NOT PRICED AS A PARLAY with a `[STOP]`; that
finding ends with the estimate and its EV. Read the number out and do not
present it as a refusal. DO NOT PLACE means a vetoed leg.

## Step 7 — log, then the closing table

Log every slip shown with `log_slip_rec` (G1 under book `"bet365"`, with
the DraftKings stand-in as `odds` and a note saying so). Upload. Print
`recommended_summary()`.

End with **Top slip per item**: one row each for F30 and G1, best value
and most likely where they differ, Use / Marginal / Skip (G1 is never
Skip), no player repeated across rows. In the slip cell, put each leg's
win % in brackets after it, and HOT or LONG RUNG where it applies.
Confidence A only when every leg is VERIFIED. For G1 the quote cell reads
"needs +N or better at Bet365".

Under the table: the pull time, what Dustin must confirm on each bet slip,
what sinks each slip, and what to re-check after inactives.

## Send back

The three leg tables; step 1's drift line and injury state; step 1b's
pasted sections; both census reports; the F30 pricing table with build
times; the G1 table and its terms as you read them; each `score_slip`
first line; the closing table; every traceback; anything that looked
plausible but was wrong.

---

# RE-CHECK — paste Wednesday between 6:35pm and 7:30pm ET

Kickoff is 8:00pm ET. Re-clone. Do not rebuild pools.

1. Official inactives for both teams, with the time checked. Every player
   on a slip from MAIN by name, plus Josh Jacobs and Kyren Williams. A
   scratch that moves a role counts even when the scratched player is on
   no slip.
2. `propline_get_lineups(sport_key="football_nfl", event_id=32694)`. Paste
   the first three player entries of the response word for word (its
   shape is needed to build a reader for it). Add each INACTIVE
   quarterback, back, receiver and tight end to `flags_tonight.json` as
   kind OUT, source "PropLine lineups", "at" = his "since". If Jacobs is
   ACTIVE, add him as kind BACK with the time that was reported.
3. Pull the movement response again and rerun the step 1b command with
   the new flags file. Paste section 0 and any "! FLAGGED OUT, YET" line.
   A line in section 0 now is news from the last hour that a book has not
   moved for: name the player, the stat, the book and its line, and say
   whether any slip from MAIN is on the other side of it.
4. Re-pull prices. `h` and `anchor_drift(h).describe()`. For every leg on
   a chosen slip: its price now at Dustin's book, its fair now from the
   SAME pull, and `leg_verified`.
5. Re-price each chosen slip. New quote, quote/product, chance to cash,
   EV, beside MAIN's figures. For G1 recompute `p` and the needed price;
   if Dustin has sent Bet365's real price, give the EV at it.
6. Say which slips fell out and why, and whether any call changed.
   Reissue the leg tables on the fresh pull, dropping every inactive
   player and marking any win % that moved by more than 2 points.
7. Log anything new with `log_slip_rec`. If Dustin placed something,
   `log_bet` it and mark its slip record `placed=True`. Upload.
8. End with the Top slip per item table, then give Dustin
   `flags_tonight.json` as a file to download.
