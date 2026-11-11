# Test prompt — live run 3A, Wednesday (plumbing check before game day)

Paste everything below this line into the project thread.

---

Live run on **event 53178 (WAS @ NYG, TNF)**, the day before kickoff. Six
things shipped on 2026-11-11 after your second run and **none has touched a
real board**. This run checks that plumbing and collects more real quotes.
It is **not** the run to act on: Pinnacle is probably still at opening
limits, and a separate game-day prompt covers bettable slips tomorrow.

Rules as before: re-clone first and print the commit hash and `DATA AS OF`
(pass `current_week`). Do not patch or work around anything; paste
tracebacks and move on. Build the `aliases` map first. Put the anchor books
in the odds pull. Do not log to `ff_betlog`.

**For every step: if the board cannot produce the condition the step needs,
say so and build the condition by hand, as you did for the 18-player pool
last time. A clean run that never reached its target is not a pass.**

## Step 1 — rung legs now carry anchor depth and their own uncertainty

```python
tiers = ff_boost.book_liquidity_tiers(odds)
legs, refused = ff_boost.rung_legs(f, book="draftkings", market=mkt,
                                   event_id=ev, verdicts=V, meta=meta,
                                   aliases=aliases, tiers=tiers)
```

Across all rung legs (all markets you can price), report:

- `anchor_liquidity`: how many are set, and the distinct values. Last run
  it was 0 of 306; that was the bug.
- `anchor_level_fair`: how many equal exactly 0.5.
- counts of `l.anchor_opening`, `l.anchor_untested`, `l.anchor_thin`.
- distinct `tier_source` values.
- `fair_sd`: how many are set, and min / median / max. Then the same three
  numbers for only the rungs priced longer than +300, to see whether the
  tail really carries more uncertainty than the middle.

**Expected:** every rung pinned to Pinnacle has a number in
`anchor_liquidity`; if Pinnacle is still at its opening tier, a large share
come back `anchor_opening` or `anchor_untested`. Tell me the share. If
`anchor_opening` is 0 while many levels sit at exactly 0.5000 on tier-level
liquidity, that is a failure — paste three such legs in full.

## Step 2 — the shortlist: target, preference, balance, flags

Rungs + main lines in one pool, single-game, 50% boost:

```python
sl = ff_boost.enumerate_candidates(pool, meta, boost_pct=0.50,
                                   mode="single-game", event_id=ev)
for n in sl.build_notes: print("NOTE:", n)
print(ff_boost.report(sl.candidates))
```

Then the same with rungs only at `floor=300, ceiling=900`.

Check and report each of these:

1. **Price target.** The note should say **lower quartile**, a factor near
   **0.85**, a target near **+371**, and "roughly one quote in four". Paste
   the note. Report min and max product.
2. **Priceable preference.** Does any note say a group "took the PRICEABLE
   ... over the cheapest"? Paste every such note. If none fires, build one
   by hand: a pool where a QB has both a passing-yards rung and a
   rushing-yards rung, plus two of his receivers, so the cheapest
   combination is correlated and a priceable one is close by. Report
   whether the swap happened, and the two products.
3. **Price balance.** Every candidate should print a `price balance` line.
   Count how many say a leg "supplies N% of this slip's price — more than
   the other legs combined", and paste two examples of each kind.
4. **Anchor flags.** How many shortlisted slips carry
   `** OPENING ANCHOR **` or appear in `sl.immature_anchors`, and how many
   are clean? Last run the answer was structurally zero.
5. Does the anchor-depth line now show a number on rung slips?

## Step 3 — price them, and keep every quote

Price **every** shortlisted slip from step 2 (both shortlists) with
`propline_price_sgp` at all books. Re-pull odds right before pricing and
note both timestamps.

One row per quote, nothing dropped:

```
slip | lopsided? (price balance over 50%) | priceable? | engine product | book | quote | quote/engine product | quote/book's own independent | >= +300?
```

Then, **sportsbooks only** (drop novig and other exchanges):

- quotes at +300 or better, out of how many. The engine now predicts about
  one in four comes in under; tell me the actual share.
- min / lower quartile / median of quote/engine-product.
- the same split by lopsided vs balanced slips. One lopsided slip got the
  best quote last run; I want to know if that holds.

Apply each DraftKings quote with `price_candidate` and print verdict,
`clears_floor`, `slip_hold`, and `ev_pct` or `ev_floor_pct`.

## Step 4 — accumulation across cleared pairs

Same-team slip, all OVER, real DraftKings main lines and fairs:

1. one RB rushing yards + **two** receivers' receiving yards;
2. one RB rushing yards + **three** receivers' receiving yards;
3. slip 2 with the RB flipped to UNDER.

For each print `st.kind`, `st.priceable`, `len(st.pairs)`, `len(st.zeros)`
and `st.reason`.

**Expected:** 1 priceable; 2 not priceable with "cleared pairs sum to" in
the reason; 3 priceable. Slip 2 depends on the legs' real probabilities, so
if it comes back priceable, print the summed drift and the noise
(`ff_boost._zero_drift(legs, st.zeros)` and `ff_boost.product_noise(legs)`)
so I can see how close it was. That would be a real answer, not a failure.

## Step 5 — two quick ones

1. `ff_props.player_series(wk, "Cameron Skattebo", "rushing_yards",
   aliases=aliases)` returns rows; without `aliases` it raises and the
   message tells you to pass them. Paste the message.
2. Hand-build an independent 3-leg slip from the three longest rungs that
   `classify` calls independent. The report should show P(cash) and
   breakeven with a "1 in N" figure and a `LONGSHOT` line. Paste those
   three lines.

## What to send back

- Step 1's counts, with the opening/untested share stated plainly.
- The step 3 table in full, the miss share, and the lopsided/balanced split.
- Each numbered check in step 2 answered in one line, then the evidence.
- Every traceback, and anything that looked plausible but wrong.
- One line on whether Pinnacle is anchoring the yardage markets in
  `get_event_ev` yet (the dropout from last run), from `anchor_coverage`.
