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

## SHIP GATE — run this before saying "done", every time

**Why this section exists, stated plainly because it is the whole point.**
Dustin observed on 2026-11-05 that almost every follow-up he asks produces a
new self-caught error, and asked how to trust the first output instead. The
diagnosis is not that the lessons below were missing. **Lesson 6 — "when a
code path can guess, make it refuse instead" — was already written in this
file when B69 shipped that morning, and B69 is exactly a code path guessing
instead of refusing.** A retrospective list of failures, read at the START of
a session, does not fire at the moment of shipping. It has to be a gate.

The deeper reason self-testing does not catch these: **the fix and its tests
get written in one pass, so the tests inherit the fix's blind spot.** B67's
checks covered all three branches of the conditional and passed; they were
blind to the fourth STATE (position missing) because the author was thinking
in branches. The same model produced both. That is why item 6 below is not
optional — an independent reader is the only step that does not share the
blind spot.

Counted over this session: roughly **8 defects were catchable before
shipping with information already in hand**, against **6 that genuinely
required live payloads** (Pinnacle dropout, SGP factor confound, real
`token_note` range, `stake_back_ev` ceiling, F4's falsification, B43's false
negative). The second group is the cost of building against an API whose
behaviour cannot be fully observed. The first group is what this gate exists
to drive to near-zero. **Do not use this gate to claim the second group
away.**

Before shipping ANY code change:

1. **Grep every constant, table and function name you touched across the
   whole repo** — not just the file you edited. B68: `SAME_TEAM_CORR` had a
   second literal copy in `ff_guillotine.py` and B67 was fixed in one of
   them.
2. **Re-read the ENTIRE function you edited, especially the `else` and any
   `.get(k, default)` / `or ""` / bare `return 0.0`.** B69: a new third
   branch was added to a conditional and its fall-through — which handed out
   the largest of three values for a MISSING input — was never re-read.
3. **Enumerate input STATES, not code branches.** Write them down. For
   `_pair_r`'s receiving pair the states are TE / RB / WR / present-but-odd /
   **missing** — five, where the code had three branches and an `else`. The
   missing state is the one that gets skipped, every time.
4. **For every new number: where did it come from, and is it one
   observation?** `token_note`'s 0.81–0.86 and `stake_back_ev`'s defaults
   both shipped from a single sitting and were materially wrong.
5. **Try to make each new check FAIL.** Break the code deliberately, confirm
   the check fires by name, restore. A check that cannot fail is worse than
   no check (lesson 4) and two have shipped.
6. **Send the diff to an independent reviewer before shipping the files.**
   Give it the code and the failure-pattern list below as QUESTIONS. Do NOT
   give it your reasoning or your conclusions — a reviewer handed the
   author's hypothesis returns it confirmed. This is the only step that does
   not share the author's blind spot, and it is cheaper than a wasted test
   round, which costs Dustin a paste into another thread, a run, and a trip
   back.

**"The suite passes" is not the stopping signal.** The suite only covers what
was already understood, so a pass mostly confirms nothing previously
understood got broken. The stopping signal is: suite passes AND items 1–5 ran
AND the reviewer came back.

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
12. **A parameter's DEFAULT is a code path, and an argument every caller
    passes is an argument no test omits.** `devig_field`'s
    mutual-exclusivity refusal — the one its docstring spends a paragraph
    on — was `if market and market not in ...` with `market=None` by
    default. 464 checks never exercised it because all six callers passed
    `market=` explicitly. Omitting one keyword returned an anytime-TD board
    normalised to 1, a 58% scorer quoted at 27%. **Grep the callers of
    anything you add a default to; if none omit it, write the test that
    does.**
13. **A detector must be able to report that it could not measure.** Three
    states, not two: healthy / fault found / **I had nothing to look at.**
    `anchor_coverage` derived `eligible` from the control payload, so a
    failed control gave it nothing to iterate and `healthy` returned True,
    printing "every book live to anchor did" about books never observed.
    The function whose entire job is to be the paired control could not
    survive its own control failing.
14. **Counting FAIL lines misses a CRASH, and a crash is worse.** Verifying
    B73 by reverting it and counting `^  FAIL` reported zero — because the
    revert made the suite raise, which stops every later section and prints
    "0 failed" over a partial count. The suite's own crash banner said so
    and the harness ignored it. **When probing whether a check bites, read
    the crash line and the check count, not just the failure count** — and
    write the check to fail rather than explode.
15. **The reviewer found four betting-path defects in code that had just
    passed 464 checks.** That is the measurement that settles whether step 6
    of the ship gate earns its cost. Two of the four were in the guard
    clauses of fixes shipped the same morning, which is the part
    self-review structurally cannot catch: the same model wrote the fix,
    the comment explaining the fix, and the test blessing it.
16. **The engine's guards only protect calls that go through the engine.**
    The eleventh deployment test self-caught two errors and BOTH were the
    project's own fixed bugs, re-committed in the thread's own ad-hoc
    extraction scripts: a raw name lookup that `norm_player()` exists to
    prevent (B44), and a dict comprehension that kept the "No" side of a
    two-sided board, which `screen_quotes` exists to prevent (B24/B28).
    Both were caught only because the resulting numbers were absurd — a
    booksum of 20.99, a position of None. **A side-mix on a board where
    both sides sit near -110, or a name miss that returns a plausible
    position, would have passed silently.** Hardening a module does not
    harden the session that calls it. Export the primitives the thread
    keeps hand-rolling (B82).
17. **A veto must measure the thing its message claims.** The role-change
    veto fires on ANY role change and then asserts "it runs against
    <side>" without computing the direction. It rejected the best-priced
    leg on the board for a role EXPANSION that argued FOR the side being
    bet. Same shape as lesson 6, but inverted: not a plausible number
    instead of an error — a plausible REASON instead of a measurement.
18. **Two copies of a rule, and the newer one was written without the
    rule.** B80's direction test existed in `price_edge` — with a comment
    saying blanket-blocking "was wrong" — while `boost_verdict`, written
    later, restated the same reasoning minus the test and vetoed
    everything. Lesson 7 said a constant copied into two files is one bug
    with two homes; this is the same thing for LOGIC, and it is harder to
    grep for because the copy does not look like the original. **When
    adding a guard, grep for the concept, not the identifier** — and when
    two call sites need the same decision, give it one home rather than a
    comment promising they match.
19. **A correct detection rule is not a correct DIRECTION rule.**
    `usage_trend`'s verdict is decided on SHARE, deliberately and rightly:
    a count drop that leaves share intact is the team running fewer plays.
    But B80's `supports()` then read a BETTING direction off that verdict,
    and a threshold prop is priced on opportunity COUNT. They diverge
    whenever team volume moves — 21 of 264 flagged role changes, and the
    direction was wrong on all 21. **When reusing a classifier's output for
    a new decision, check that the quantity it was built on is the quantity
    the new decision turns on.** It usually isn't.
20. **Adding a third state to a two-state return re-opens the bug the
    second state fixed.** `supports()` returned True/False/None, and B84
    added a second reason for None. `elif supported:` treats None as False,
    so the conflict case would have vetoed "AGAINST THE <side>" — exactly
    B80's assert-a-direction-you-never-measured, re-entered through the new
    value. **After widening a return type, grep every caller for truthiness
    tests on it**, not just for the old values.
21. **An over-permissive bug is worse than an over-conservative one, and
    it reads better.** B80 dropped good legs, which is visible and
    annoying. B84 admitted bad legs with the note "the model UNDERSTATES
    this side, the true edge is likely larger than shown" pointing the
    wrong way. Encouraging prose in the wrong direction is the more
    expensive failure and the harder one to notice, because nothing looks
    broken.
22. **Reinforcing one side of a door is not closing it.** B71 added a LOWER
    bound to `devig_field` and B85 corrected the diagnosis — both inside the
    `not has_no_scorer` branch. A polluted field that DOES carry a no-scorer
    row therefore had no upper bound at all, and the real DraftKings board
    carries one. Booksum 3.0326 was returned as `method: shin,
    complete: True`. **When adding a guard inside a branch, ask what the
    other branch now lacks.**
23. **One constant doing two jobs will be wrong at both.**
    `MAX_PLAUSIBLE_OVERROUND` was documented as purely diagnostic and was
    also the only ceiling — so it was too loose to refuse pollution and
    mis-placed for the diagnosis, and its own comment described a threshold
    the code did not apply. Split a refusal line from a diagnostic ceiling
    the moment one value is asked to answer "is this allowed?" and "what do
    I say about it?".
24. **An unvalidated string is a branch you did not write.** `Edge.side` is
    a bare `str` and this codebase uses both "OVER" and "over".
    `Edge(side="over")` slipped past a `side is None` check, returned None
    from `supports()`, and landed in the conflict branch — asserting a
    divergence that had not happened and re-vetoing the leg B80 exists to
    un-veto. Normalise at the boundary, and keep "absent" distinct from
    "unusable".
25. **Do not print a field your decision never read.** The conflict message
    quoted `team_volume_ratio` while `direction_conflict` ignores it — and
    that field is 0.0 when unmeasured and hardcoded to 1.0 by
    `role_trend`, so the message asserted "team volume 0%" and "100%" as
    measurements. Carry a `has_*` flag for any value that has a fabricated
    default, and omit rather than assert.
26. **My own measurements need an artefact, not a docstring.** B84's
    264/21/243 figures were prose with nothing in the repo able to
    re-derive them — D16's shape, committed inside a fix for D16. They now
    live in `measurements/b84_direction_conflict.py`. **If a number is
    worth putting in a docstring, it is worth a script that reproduces
    it.**
27. **One message for two states is a message that asserts.** `supports()`
    returns None for a share/count conflict AND for a count that did not
    move, and one veto sentence covered both — telling a reader whose
    targets were flat at 11.5 that "the COUNT moved the other way". The
    session believed the message, reported the wrong predicate, and had to
    correct itself from the flags. **When you add a second reason for an
    existing return value, add a second sentence.** This was committed
    inside the fix for the same class of bug, which is now the pattern:
    the fix is where the next one lives.
28. **A check that can never pass is worse than no check.**
    `verify_uploaded` demanded byte identity from a transport that cannot
    deliver it for non-ASCII content — 178 em dashes in ff_props.py, 35 in
    verdict reasons, so every realistic log failed. A live session got
    False, reasoned past it by hand, and left 69 records unmarked. The old
    code even computed record equality, printed "equivalent by luck", and
    failed anyway. **Check the property that matters, not a proxy that is
    permanently violated** — and if the proxy carried real information,
    keep it as a message rather than as the verdict.
29. **Gate item 5 is not optional and it earns its keep every time.** The
    B90 fix shipped with the suite green and ZERO checks pinning it;
    reverting the fix produced no failures at all. Separating two messages
    felt too obvious to test. Every fix gets the revert check, including
    the ones that are "just wording" — especially those, because wording
    is what the reader acts on.
30. **A fall-through can be right and still be worth measuring.** E6 flagged
    that `_pair_r` returns 0.0 for same-team receiver pairs without anyone
    being able to establish it had been measured. It turned out to be a good
    approximation — WR x WR receiving yards r = +0.009 over 12,622 pairs —
    but the number that matters for a parlay is the JOINT CROSSING lift,
    which is 0.9817x, not 1.0. On the slip it ran live in, that 2% took the
    EV from +1.83% to -0.04%. **"Approximately independent" and "priceable
    as independent" are not the same claim at three legs.**
31. **Printing two numbers next to each other is not comparing them.**
    `report()` emits `this slip's hold: 18.8% (observed — reference band
    23.1%-37.2%)`: the contradiction was on the page, one line apart, and
    still slid past a careful reader working through dozens of lines. If the
    hold were merely at the best end of its own band that bet is -3.6%
    rather than +1.83%. **A fact presented without a verdict is
    indistinguishable from a fact that was checked** — B39's family in its
    softest and most reachable form. When the engine holds both sides of a
    comparison, it should state the comparison.
32. **Fix the reason, not just the symptom.** B82 is "the session keeps
    hand-rolling payload walks". The most useful thing done about it was not
    a warning but B92: `flatten_odds` dropped `liquidity`, so there was NO
    sanctioned path to per-line anchor depth and the hand-roll was the only
    option. Carrying one field removed the excuse. **When something keeps
    getting bypassed, check whether it is missing the thing people bypass it
    for.**
33. **"Never reported" is not zero, and one number is not two.** B92 carries
    liquidity per SIDE because Kalshi's two sides of one line differed
    $5,977 against $112 — a per-line average would have been a fiction — and
    returns None rather than 0.0 for books that report none, because
    anchor_thin treats those differently. Both distinctions have their own
    check; collapsing either one fails it.
34. **Check a new flag's FIRING RATE before shipping it.** B93's first cut
    noted when a cross-game slip held below its band — which is nearly every
    well-shopped slip, since three legs at -110/-110 hold 13.03% against a
    17.7% floor. It would have fired on all three cross-game slips measured
    that day. A signal that fires on good execution is noise, and B91's
    lesson about unsatisfiable checks is the same lesson from the other
    side: one never passes, the other never shuts up, and both get ignored.
    **Count how often a new flag fires against real cases before you ship
    it** — it took one script, and the answer went from 3-of-5 to 1-of-5,
    the one that mattered.
