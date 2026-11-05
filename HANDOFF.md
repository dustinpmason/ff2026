# Handoff — fantasy football + NFL props copilot

Paste this into a **new general thread** (not a project thread) to continue the
build. The previous build thread got long enough that re-reading it dominated
the cost; everything durable is written down here and in the two docs.

---

## First thing: get the state

```bash
rm -rf ~/ff && git clone --depth 1 https://github.com/dustinpmason/ff2026.git ~/ff && cd ~/ff && python3 refresh.py
python3 test_regression.py        # expect: "454 checks run, 454 passed, 0 failed"
```

Then read **BACKLOG.md**, **PROJECT-INSTRUCTIONS.md** and **LEAGUE-CONFIG.md**
from the repo. They are
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

- **454 regression checks, all passing.** Seven engine modules: `ff_data`,
  `ff_scoring`, `ff_props`, `ff_guillotine`, `ff_betlog`, `ff_backtest`,
  `ff_boost`.
- Tier 0 and Tier 1 complete. P1 complete. F2 settled. **P0 complete.**
- **Band is +300 to +600** (ceiling raised 2026-11-03 — see BACKLOG). On a
  standalone-game boost, 30% is marginal and 20% is a pass; structure
  decides, not price.
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
2. **B59/B60 — the anchor layer is less stable than the code assumes.**
   B59: `OPENING_LIQUIDITY` is still a hardcoded tier, now sitting exactly
   on Pinnacle's 500 and silent again at the next bump; derive it from the
   board's modal liquidity instead. B60: Pinnacle's availability as an
   anchor flipped 0/22 to 21/24 inside SEVEN MINUTES on one event, so
   which anchor a leg gets is not reproducible run to run. Measure B60
   before theorising — two hypotheses with different fixes are in its row.
   (B53 WITHDRAWN, the claim was wrong. B54, B55, B56 DONE.)
3. **Grade forward via the bet log.** CLV across 30+ legs is the measurement
   that works at a $10 stake. B58 is resolved: the log is intact, there is
   simply no real history in it yet — every prior file was a throwaway
   test. The first graded bet starts the record.
4. **The Mode A / Mode B build, once prioritised.** Dustin's stated vision,
   2026-11-05: (A) hand the tool a boost token and get back the slip to
   build for it; (B) conversational sanity checks on single legs and on
   slips he assembled himself. Gaps filed as F11-F16. **F13 — the
   correlation table covering only three yards markets — blocks both**, and
   it is a measurement rather than a build. F14 (single-leg Q&A) is the
   cheapest and most immediately useful. F11's design is settled; F12 and
   F16 are blocked on B51 and P4. Nothing here is built. Prioritise before
   writing code.
5. Tiers 3–5 as listed in BACKLOG.md.

**Two separate scarcity problems live near each other — do not merge them.**
An earlier edit of this file did, and wrongly reported item 1 as blocked.

- **The hold re-measurement needs EVENTS, not anchors.** Hold is measured by
  de-vigging a book's OWN two-sided legs and comparing their product to that
  book's parlay quote. No Pinnacle, no Kalshi, no external anchor is
  involved — which is why the first measurement ran on DK + FD across 2
  events while Pinnacle covered almost nothing. A full Sunday slate has
  ~13 games, so "3+ events" is trivially met. **This gate is reachable; run
  it.** Check BetMGM's coverage on the day rather than assuming it is
  absent — that exact claim went stale once already (D16).
- **Cross-game MODE needs 3 anchored events**, and that is the hard one:
  Pinnacle carried the three yardage markets on 1 of 15 events in window.
  That constrains using the module for live leg selection. It does not
  constrain measuring the hold. See B51.

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
3. **A test fixture that does not match the live shape proves nothing — and
   SHAPE INCLUDES CARDINALITY.** 135 passing checks were blind to
   `screen_quotes` reading an Under price as an Over price, because every
   fixture used a pre-flattened shape that PropLine never returns. Then B49:
   335 passing checks were blind to `flatten_odds` raising on milestone
   rungs, because the fixture posted ONE rung and one rung never collides. A
   real DraftKings board posts 28. The fixture had the right shape and the
   wrong count, which is the same lesson one level down. **A fixture
   exercising a grouped code path must carry at least two members of a
   group, and should carry the count a live board actually posts.**
4. **A check that cannot fail is worse than no check.** Two shipped: one passed
   if any player returned any verdict including UNKNOWN; one was literally
   `... if False else True`.
5. **Do not quote a number inside its own error bar.** A replacement-fill
   effect was reported as +18% from a single pair of 20k-sim runs; at 80k it
   was +9.9%.
6. **The dangerous bug returns a plausible number, not an error.** That is the
   signature shared by B13, B24, B28 and B35. When a code path can guess, make
   it refuse instead.
7. **A constant copied into two files is one bug with two homes.** B67 fixed
   the receiving-RB correlation in `ff_boost`; `ff_guillotine` had its own
   literal copy of the same table, untouched, and nothing anywhere said so.
   Found only by asking "does this bug exist anywhere else?" after shipping
   the fix. **When fixing a shared constant, grep the repo for its value
   before calling it done** — and if a duplicate has to stay, add a check
   that the copies match, so the next one-sided edit fails by name.
8. **Borrowing a measured number for a different quantity changes what it
   means, sometimes including its sign.** The betting table measures one
   market against another; the guillotine applies it to fantasy scores.
   QB x RB is -0.10 on passing-vs-rushing yards (game script) and **positive**
   on fantasy points (shared TDs). Both are correct measurements of different
   things. The table was reused because the position pairs matched, which is
   not the same as the quantities matching.
9. **Measure the effect before ranking the fix.** B68 is a genuine wrong sign
   in a live simulation, which sounds urgent. 200,000 sims put it at under
   0.01pp of P(elim) with the same lineup chosen either way, so it sits
   behind a feature Dustin will use tonight. The reverse error — assuming an
   ugly-looking bug is harmless — is equally available; the point is that
   neither ranking is free, and both took one script.
10. **Fixing a branch is not fixing its fall-through.** B67 made `_pair_r`'s
    receiving branch three-way and left `else:` handing out the WR value to
    anything that did not match — including a MISSING position (B69). The
    same function already refused on a missing team eight lines earlier, so
    the right reasoning was present in the file and applied to one field
    only. **After changing a branch, read its else.**
11. **A broad fix can quietly reverse a deliberate decision.** B69's first
    cut refused every position outside WR/TE/RB, which also refused the
    Travis-Hunter case that a previous session had deliberately made work
    (a CB carrying a receiving prop is a receiver whatever the label says).
    A named check from 2026-11-02 caught it. "Missing" and "present but
    unmeasured" are different states. Second time the suite has caught me
    asserting something broader than the actual defect — see B53.
