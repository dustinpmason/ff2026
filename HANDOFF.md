# Handoff — fantasy football + NFL props copilot

Paste this into a **new general thread** (not a project thread) to continue the
build. The previous build thread got long enough that re-reading it dominated
the cost; everything durable is written down here and in the two docs.

---

## First thing: get the state

```bash
rm -rf ~/ff && git clone --depth 1 https://github.com/dustinpmason/ff2026.git ~/ff && cd ~/ff && python3 refresh.py
python3 test_regression.py        # expect: "306 checks run, 306 passed, 0 failed"
```

Then read **BACKLOG.md** and **PROJECT-INSTRUCTIONS.md** from the repo. They are
the authoritative record — every decision, every bug, every measured number.
Do not re-derive anything they already state.

**The suite prints its own check count. Quote that number and nothing else.**
Do not count checks by grepping the source or the output; two sessions were
sent hunting for checks that never existed that way.

## How the two thread types divide

| | |
|---|---|
| **Build thread** (general, like this one) | Writing code, testing in the container, producing files. Maintains the two markdown docs as files. |
| **Project thread** (inside the Claude project) | Fresh sessions that bootstrap from GitHub and run verification or measurement prompts. Gets the instructions automatically. |

Keep them separate. The build thread does not need the project instructions in
context.

## Current state

- **306 regression checks, all passing.** Seven engine modules: `ff_data`,
  `ff_scoring`, `ff_props`, `ff_guillotine`, `ff_betlog`, `ff_backtest`,
  `ff_boost`.
- Tier 0 and Tier 1 complete. P1 complete. F2 settled. **P0 complete.**
- Eight deployment-test rounds done. Six of eight found real bugs.

## F2 is settled — nothing is waiting on an answer

The pipeline validation ran on 8 events, Weeks 5–6, 950 graded legs.

- **Name resolution was not the blocker: 99.2% end-to-end.** That hypothesis
  is dead. The `event_teams` guard fired on **0 of 950 real legs with 0 false
  positives**, and a probe confirmed it is live rather than silent.
- **The verdict is still: do not build a scaled outcome backtest** — for the
  sample arithmetic, which cannot be fixed. 8 events gave 2se = 23 points on
  the hit rate; all 84 event-clusters would tighten ROI to roughly ±13%
  against an effect of +1.3% to +4.1%. The NFL does not produce enough
  independent games.
- **Pinnacle IS available historically** (confirmed on event 53166: two-sided
  main lines, `redacted: false`, liquidity, pre-kickoff snapshots). The
  validation had de-vigged recreational books against themselves because its
  pull excluded Pinnacle — always include it.
- The hold got independent corroboration from a different data path: per-leg
  Shin hold 6.30% compounds to **17.74%** over three legs, on the bottom edge
  of the measured cross-game band.

**P0 is now built.** `ff_boost.py` — see the P0 section in BACKLOG.md for what
it does, what it refuses to do, and why step 4 of the original spec was
replaced.

## The measured facts that drive decisions

**SGP hold — measured 2026-11-02, replaced a guess that was badly wrong.** The
guess was (8%, 20%); 8% was never attained and the floor is 17.7%.

| structure | hold | min boost for +EV at +300 |
|---|---|---|
| Cross-game (SGPx) | 18.6% (17.7–20.9%) | ~28% |
| Same-game, independent legs | 30.2% (23.1–37.2%) | ~50% |
| Same-game, correlated (QB stack) | not measurable | — |

- **A 20% boost is negative everywhere measured. Skip them.**
- 30% works **cross-game only** (+1.3% at +300); same-game at 30% is −10.7%.
- **Structure is worth ~22 points of boost** — "prefer SGPx" is the primary
  lever, not a tidiness preference.
- Caveat: 12 slips, 2 events, 2 books, one slate. **Worth re-measuring on a
  full Sunday slate** — that run was constrained to two events, no true
  3-event cross-game SGPx was constructible, and BetMGM was not live.

**A backtest cannot measure profitability with the available history.** 84
event-clusters gives a ±23% ROI error bar against a +2–13% effect. Resolving 2
points needs ~11,000 independent slips, about 40 weeks of NFL. Slips from one
game are correlated, so the independent unit is the event, not the slip.

**The model abstains on binary low-event stats.** A TD prop on 0-for-7 produced
a 24-point "gap" that is not evidence. `boost_verdict` returns CAUTION with
MODEL ABSTAINS — deliberately not VETO, because the model being unable to
assess a leg is not the leg being broken.

## Next, in order

1. **Widen the hold measurement** on a full Sunday slate — 3+ events for a
   true cross-game SGPx, BetMGM live, and an attempt at the
   same-game-correlated case that is currently unmeasurable. **Measure both
   structures deliberately.** Dustin uses single-game mode about half the
   time (TNF/SNF/MNF boosts are usually offered for that game alone), so the
   same-game band is not secondary — and at 23.1–37.2% off 12 slips on one
   slate it is the weaker of the two numbers. It is also the number that
   will be rejecting most of his standalone-game boosts, so it had better be
   right.
2. **Deployment-test P0** on a live slate. Eight of eight prior rounds that
   touched new code found something; this module has never seen a real
   payload. The intake path (`get_event_ev` + `flatten_odds` +
   `screen_quotes` → `BoostLeg`) is the part most likely to be wrong,
   because every fixture behind it is synthetic by design.
3. **Grade forward via the bet log.** CLV across 30+ legs is the measurement
   that works at a $10 stake.
4. Tiers 3–5 as listed in BACKLOG.md.

## Workflow improvement not yet done

The engine files are hand-uploaded to GitHub each round, which is the biggest
friction in the project. A local clone on the Mac plus device access would let
files be written and pushed directly. Two caveats: git needs **delete
permission** on the folder or its lock files break every subsequent command,
and pushing needs git credentials configured over HTTPS (SSH will not work
through the proxy).

**If this is set up, add a rule:** the manual upload is currently an accidental
review gate — a broken file cannot reach the repo without passing through
Dustin. Pushing directly removes that, so the suite must pass before any push,
and anything beyond a small fix should be described before it goes.

## Standing lessons — these are the failure patterns, not trivia

Eight rounds of testing produced a consistent signal: **not one defect was
arithmetic.** Every one was an unverified claim or a fixture that did not match
reality.

1. **Verify before writing a causal claim into the docs.** Three separate false
   claims reached PROJECT-INSTRUCTIONS.md this way (P7, P8, D5/D10). The worst
   pattern: correcting one clause in an edit while leaving the adjacent clause
   unverified.
2. **Never assert a player's team, or any id, from memory.** Look it up in
   `build_meta()`, the roster, or the connector, and say which. A fabricated
   espn id resolved to a *different real player* who had no row that week,
   producing a plausible "did not play" instead of an error.
3. **A test fixture that does not match the live shape proves nothing.** 135
   passing checks were blind to `screen_quotes` reading an Under price as an
   Over price, because every fixture used a pre-flattened shape that PropLine
   never returns.
4. **A check that cannot fail is worse than no check.** Two shipped: one passed
   if any player returned any verdict including UNKNOWN; one was literally
   `... if False else True`.
5. **Do not quote a number inside its own error bar.** A replacement-fill
   effect was reported as +18% from a single pair of 20k-sim runs; at 80k it
   was +9.9%.
6. **The dangerous bug returns a plausible number, not an error.** That is the
   signature shared by B13, B24, B28 and B35. When a code path can guess, make
   it refuse instead.
