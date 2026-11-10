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
35. **Before building a helper to prevent a bug, check whether the existing
    function already prevents it.** B82's headline failure was a Kalshi
    Yes/No board keyed on name, which kept the No price and gave booksum
    20.99. `OVER_NAMES` already contains "yes" and `UNDER_NAMES` "no", so
    `flatten_odds` routes that board correctly and always did — the
    hand-roll bypassed the one function that fixes it. The helper is
    therefore thin, and its value is existing and being obvious to reach
    for, not being clever. **A bug that recurs in bypass code is usually a
    discoverability problem, not a logic one.**
36. **A derived quantity inherits the assumption it was derived under, and
    the assumption is usually invisible at the call site.**
    `stake_back_ev` backed p out of a price using a uniform hold. Nothing
    in the signature said so, and on a leg whose margin was unrepresentative
    — which is what a WELL-SHOPPED leg is — it ran 24% low and cost $2.18
    on a $10 token. **When a function derives an input you might already
    have measured, let the caller pass the measured one, and make the
    result say which it used.**
37. **A proof is only as general as its substitution.** The documented
    result "the raw bet's EV does not depend on the odds" was proved by
    substituting p = 1/(d*(1+h)) — which IS the uniform-hold assumption,
    not a fact about the bet. With measured per-leg probabilities the base
    EV varies by more than a dollar across one board, and a SHORTER price
    with no margin beats a longer one with 2pp. The theorem was right; the
    advice drawn from it was too broad. **Re-read what a result assumed
    before quoting it as a rule.**
38. **Guidance in the wrong section is guidance that does not exist.** B82
    shipped working helpers AND an instruction never to hand-roll a field —
    and the next session hand-rolled one, because the instruction was filed
    under "Stake-back tokens" while the session was reading "Touchdown-
    scorer questions". Worse, the section it DID read said "pass
    `{name: american}` from ONE book" and stopped, which is an instruction
    to build a dict by hand. **Put the rule at the line where the work
    happens, not in the section you happened to be editing.**
39. **Check WHERE an instruction lands, not just that it is correct.** Four
    edits in one day all ended up in the same wrong section because each
    was inserted with `replace()` anchored on the text I had last been
    looking at. The anchor is a convenience for the editor and means
    nothing to the reader. After adding to a long document, walk back to
    the nearest heading and ask whether a person with that question would
    ever reach this line.
40. **A negative deployment result can be about the instructions rather
    than the code.** Nothing was wrong with `field_from_odds`, and a second
    test round would have found nothing, because the failure was entirely
    in where the rule was filed. Before re-testing a feature that was
    ignored, check whether the reader was ever pointed at it.
41. **A cross-module move is a deployment coupling, and this repo deploys
    file by file.** Moving `norm_player` into ff_props was right by lesson
    7, but it made ff_boost refuse to import against an older ff_props —
    and files are uploaded one at a time, so a torn clone is the NORMAL
    state. A live session got a bare ImportError, inferred three missing
    functions, built a shim, and was wrong about two of the three. **When a
    symbol moves between modules, make the failure name the coupling**:
    which files ship together, and not to shim around it.
42. **"Absent from the module I checked" is not "absent".** That session
    reported `book_liquidity_tiers` missing after testing only
    `hasattr(ff_props, ...)`; it is in ff_boost. And it blamed the Kalshi
    booksum-21 detour on a missing `field_from_odds` when `flatten_odds`
    was present and would have returned 1.3500 first try. **It reported its
    own error as the tool's** — which is the failure mode worth naming,
    because a wrong repo-gap report sends the next session building around
    an absence that is not there.
43. **Naming only the best tool strands the reader when it is missing.**
    The Touchdown-scorer section said to use `field_from_odds` and stopped.
    A session that could not find it wrote the payload walk three times
    rather than falling back to `flatten_odds`, which was present and is
    what `field_from_odds` wraps. **Name the floor as well as the
    preferred call**, because the preferred call is exactly what is absent
    on a half-updated clone.
44. **Naming a coupling in prose is not shipping it.** `ff_boost.py` went
    out with a caption saying ff_props.py must be committed alongside it,
    and ff_props.py was not attached — costing three test rounds against a
    torn clone. B99 had already made the failure loud; what stayed
    hand-written was the LIST OF FILES, in a caption, from memory.
    `shipset.py` computes it from the import graph now. **When a fact is
    important enough to put in a warning, it is important enough to
    compute.**
45. **A fix can move a failure up a level rather than removing it.** With
    the B99 fallback named, the session stopped walking raw payloads — and
    wrote the same `flatten_odds`→dict loop three times instead, with only
    one of the three carrying a duplicate-key guard. The bypass became a
    divergent duplication. Worth knowing before declaring a class of bug
    closed: check what the next-cheapest wrong thing is.
46. **Check instructions against what a session DID, not against what they
    say.** Reading the Touchdown-scorer section for correctness found
    nothing. Reading it beside the transcript found that I had told the
    session to join on a NAME — in a project whose standing rule forbids
    exactly that — and that the session had quietly ignored me and been
    right. The guidance was internally consistent and still wrong, and only
    the comparison exposed it.
47. **An instruction that describes a shortcut must enumerate what the
    shortcut owes.** "About fifteen lines" invited fifteen lines without
    the six refusals the real helper makes, and the session wrote three
    copies with only one duplicate-key guard between them. If a fallback is
    worth documenting, document its obligations, not just its existence.
48. **The obvious causal story is the one to measure, not the one to
    accept.** A three-leg receiving slip lost in heavy rain and the natural
    reading was weather. Measured over five seasons, rain moves receiving
    yards by about ONE yard (-0.85 se) and wind shows no monotonic pattern
    at all. The legs missed by 11.5, 9.5 and 2.5. **A story that explains
    the direction is not a story that explains the magnitude** — check the
    size before accepting the mechanism.
49. **A rule the project states in one place is not a rule the project
    enforces everywhere.** "A book is not its own reference" is the oldest
    line in the instructions, and the grading path had no guard for it —
    because there the circular number arrives pre-computed from an external
    grader, so nothing looks like a de-vig. When a principle matters, grep
    for every path that could violate it, not just the one it was written
    about.
50. **After changing a signature, grep the instructions for every call of
    it.** B102 added two arguments to `grade_leg` and the documented
    example still showed the old call — so a session following the
    instructions would have disabled the guard that had just been written.
    Same shape as B82 ("pass {name: american} from ONE book") and B101
    ("key it with norm_player"): **three times in two days, the worked
    example in the instructions was the thing steering the session
    wrong.** Code and its documentation are one change, not two.
51. **Measure a new flag's firing rate BEFORE choosing its definition, not
    after.** B86 had two candidate definitions. The obvious one — liquidity
    at or under the book's tier — fires on 100% of a three-days-out board
    and would have been pure noise. Excluding what the existing flags
    already catch brings it to 13%, and to 0% near kickoff. **The
    measurement picked the definition**, in one script, before any code was
    written. B93b had to learn this by shipping the noisy version first.
52. **Overturning a prior decision needs the measurement, not the
    intuition.** Two checks asserted that a price which had moved off
    0.5000 was clean, because "the 0.5000 does the work". The board that
    motivated B86 had ALL 62 lines at liquidity 250 — so the same money
    sits behind the moved and unmoved prices alike, and the old reasoning
    does not survive. Keep the distinction the old check was protecting
    (moved and unmoved ARE different) and change only the verdict.

53. **A count of observations is not a count of independent
    observations.** `rec_summary` printed `n=4 ... overconfident by 77%`
    and three of the four were Baltimore pass-catchers in one game, on the
    night both Baltimore quarterbacks went to IR. One injury, read as
    three model failures. Anywhere a rate is printed beside an `n`, ask
    what the unit of independence actually is and print THAT beside it —
    and refuse the verdict when the unit is too small, rather than
    printing a verdict and a caveat. A reader takes the number; the caveat
    is decoration.

54. **A field written by one path and read by another is a silent
    subset.** `log_bet` stored `engine_tier` on the leg; `rec_summary`
    read only `kind == "rec"` records. Every number in the engine
    scorecard was computed on an incomplete set, and it happened to
    flatter the model. When two writers feed one reader, make the reader
    name what it cannot see — do not merge them silently, because a
    session that calls both would then be double-counted.

55. **"Not present in the data" is a state, not an answer.** A missing
    nflverse weekly row makes an active receiver with zero targets
    indistinguishable from a scratch, and the two grade differently
    (LOSS vs VOID, and a VOID drops out of the scorecard entirely). When
    absence is ambiguous, go find the measurement that disambiguates it —
    snap counts, here — rather than picking the reading that looks
    safer.

56. **A report must survive the data it reports on.** `float(leg["line"])`
    met a hand-written `"n/a"` in a two-week-old bet and killed the entire
    engine scorecard — not the one leg, the whole report, at the one moment
    it gets read. The log is many schema generations deep and every
    synthetic test fixture was written today, by me, to the current shape.
    Read paths need `_num`-style tolerance and must NAME what they could
    not use; write-path validators do nothing for records already stored.

57. **A guard that reads "unmeasured" as "fine" is worse than no guard.**
    The B107 clustering gate returned the player count whenever event
    coverage was partial or absent. Five verdicts from ONE game printed
    "TOO CLUSTERED" with all five ids present and "overconfident by 77%"
    once three ids were deleted — strictly less information, strictly more
    confident. And partial coverage was the NORMAL state, because old
    records have no id. Any guard that can fail to measure needs a THIRD
    answer — yes, no, and could-not-tell — and the could-not-tell must
    refuse, not fall back to the weaker proxy it was built to distrust.

58. **Measure the thing the claim is about.** I wrote "it still fires at
    n=46 from a single slate" into two documents as a firing-rate
    measurement. The test behind it gave all 46 verdicts ONE event id,
    which is one GAME. A real 13-game slate reads fine. The number was
    real, the label was wrong, and it was wrong in the permissive
    direction — it argued the gate was stricter than it is. Before writing
    a measurement down, state what the input actually was in the words the
    claim uses.

59. **A test written in the same pass as the fix pins the fix's blind
    spot.** Three of the checks written alongside the B107 gate asserted
    the broken behaviour as correct, including one that said in so many
    words that falling back to the player count was right. The independent
    reviewer found eleven defects in code that had just passed 684 checks,
    four in the betting path and two inside that hour's fix. The checks
    were not weak — they were aimed by the same misunderstanding that
    wrote the code. This is why SHIP GATE item 6 is not optional.

60. **A guard on the read side alone closes nothing.** The clustering
    gate refused honestly and permanently, because the field it needed to
    measure anything was optional and nobody passed it — 0 of 101 records.
    A refusal that cannot ever become a verdict is not a guard, it is a
    disabled report. Where a guard needs a field, REQUIRE the field, and
    require it such that an omission and a deliberate blank are different
    keystrokes: `= None` makes them the same, which is D16 again.

61. **Run the call you just documented.** I wrote `model_p=None` into the
    instructions as the honest value for a backfilled verdict, in the same
    breath as the code that raised on it. That is B106 for the second time
    — a worked example that disables what it demonstrates. A sentence in
    the project doc containing a function call is a claim about behaviour;
    execute it before shipping it, in the same pass that writes it.

62. **Never replace a slice that runs to end of file.** A patch script
    did `old = s[s.index(marker):]` and deleted 537 lines of
    `ff_boost.py` — `classify`, `price_candidate`, `report`,
    `stake_back_ev` and most of `Candidate`. The module still IMPORTED
    cleanly, because what remained was valid Python, so the smoke test
    passed. Anchor a replacement on both ends, or use Edit with an exact
    old_string, and check the line count after any scripted edit:
    `wc -l` before and after costs nothing and would have caught this
    immediately.

63. **`git show HEAD:` is not a backup.** Recovering that truncation from
    HEAD restored a tail that predated the same day's work, so B95, B99b,
    B93 and B93b came back silently missing. The suite sections for each
    were what specified them well enough to rebuild — which is the real
    argument for writing the failure into the check text rather than just
    asserting a value. When restoring from any older copy, diff what you
    restored against what the suite expects, and treat equal check COUNTS
    as the parity signal.

64. **A guard whose removal changes nothing is not a guard.** B68b was
    filed as a missing `if pi is None` beside an existing `if ti is None`.
    Adding it changed no behaviour, because the absent cases already
    missed the keyed lookup — so no check could fail on it, and in this
    project a check that cannot fail is worse than none, because it reads
    as coverage. Before writing a guard, revert it and confirm a check
    fails; if none can, the defect is somewhere else.

65. **Measure the filed premise, not just the filed fix.** B68b named
    `build_meta` as the source of `("KC", None)`. Over 2026 weekly,
    `build_meta` produces zero missing fields — the premise did not hold.
    The real hole was the RAW-NAME lookup one line above it, which the
    module's own docstring forbids in so many words. A backlog entry is a
    hypothesis with a date on it; re-measure it before building on it.

66. **Check the firing rate on the axis the REASONING turns on.** The
    B93 hold note was gated on cross-game vs same-game, measured on that
    axis, and shipped. Its stated reason was about CORRELATED legs — and
    the property it depended on returns None unless the slip is priceable,
    which means measured-independent. So it could only fire where its
    reason was false: wrong in 100% of reachable cases, on a `***` line,
    found by a live round rather than by 784 checks. A firing-rate check
    on the wrong axis is a check that passes and proves nothing.

67. **Two writers of the same field may disagree on purpose.**
    `log_edge` records the side the MODEL prefers; `log_bet` records the
    side the slip took. Adding `side` to the match key was right, and it
    turned 5 of 12 legs into "NOT in this log" with a remedy that would
    have duplicated them. When a join key gains a field, ask what else
    writes that field and whether the two are even trying to agree —
    disagreement can be the most informative state there is, and here it
    was: the engine's lean was against the legs that got bet.

68. **A detector that cannot name its subject reports health.**
    `anchor_coverage` exists to catch a silent anchor dropout, and on the
    measured dropout signature it returned `healthy=True` — because
    `bk.get("key") or bk.get("title")` manufactured a display-name key
    that could never match the lowercase chain. The book sat in `live`
    looking accounted for and contributed nothing to `eligible`. When a
    lookup falls back, ask what the fallback VALUE can still match; a key
    that matches nothing is worse than None, because None can be
    reported.

69. **The fix for "nobody calls this" is not only a caller.** B75's wrong
    explanation survived because `book_liquidity_tiers` had no caller, and
    the instruction to call it existed but sat mid-paragraph. The code now
    distinguishes never-looked-up from book-quoted-none, so a session that
    skips the call cannot assert the wrong cause — the guard does not
    depend on the instruction being read. Where an instruction and a field
    default can disagree, make the field able to say which happened.

70. **A prompt handed over for pasting must contain no instruction
    addressed to the human.** I wrote a test prompt with
    `[paste them here, however you'd normally write them]` in the middle
    of instructions aimed at the session. Dustin pasted it verbatim — as
    he had every other prompt — and the session correctly refused,
    pointing out that running `parse_tokens` on a placeholder would look
    like a parser result and be a measurement of an empty input. Anything
    the person must supply goes ABOVE the prompt as a labelled block, or
    in a separate message, never inside it; and if a prompt genuinely
    cannot be pasted unedited, say so in the sentence that hands it over.

71. **A refusal nothing downstream can see is not a refusal.** B87 made
    `prop_edge` refuse a fabricated hold and return nan. The same night, a
    live round showed a leg with `hold=nan` coming back `tier=MODERATE`,
    `reasoning="clean read"`, `boost_verdict=CLEAR` — the refusal was
    invisible to every consumer, so a leg with no measurable vig read as
    vetted. When you add a refusal, trace it to each thing that reads the
    value and ask what that thing now says. B39, inside B87's own fix.

72. **Two numbers that share a name are not the same quantity.** A model
    probability of P(scores A touchdown) was priced against a market of
    P(scores the FIRST touchdown) — about 3x apart — and the engine
    reported the difference as a +19.2 point edge. Nothing was broken:
    `Estimate` carries the STAT and the pricing call carries the MARKET,
    and nothing compared them. Where two inputs describe quantities that
    must match, make the function take both and check, rather than
    trusting the caller to have lined them up.

73. **A substring match against a whole report is not a check.** A check
    named "the fee is counted in what was staked" asserted `"$7.53" in
    output` — and passed a revert that zeroed the staked figure, because
    the same number appeared on the boost line. Anchor an assertion to the
    LINE it is about (`_line(out, "staked")`), or it can be satisfied by
    any other line that happens to carry the same text.

74. **The log has to be able to represent what actually happened.** A
    cash-out was unrepresentable, so a real +$5.42 result would have gone
    into the book as a LOSS and every figure downstream would have
    inherited it. Before trusting a measurement system, check that its
    vocabulary covers the outcomes the world actually produces — the gap
    is not a wrong number, it is a number that cannot be written down.

75. **If a guard would only block people, it is half a fix.** A verdict
    computed for the wrong side needed refusing — but `prop_edge` had no
    way to produce one for a chosen side, so the refusal alone would have
    left the correct workflow impossible and the guard would have been
    worked around. Before adding a check that something was done wrong,
    confirm there is a supported way to do it right, and build that first.

76. **A blocker worth respecting is still worth re-measuring.** F12 was
    filed as blocked on anchor quality. Re-measuring found the blocker
    intact (Pinnacle: zero alternate props) AND that the neighbouring
    figure B51 rested on was badly stale (1 event of 15, against 14/14
    measured a day earlier). The right move was neither to build around
    the blocker nor to inherit it — it was to take the half-hour and find
    out, which also surfaced B127 as the piece that HAD become buildable.

77. **A transform that reads better can still be the wrong transform.** The
    ladder's level pin started as a shift in the THRESHOLD domain, because
    "DraftKings sits 1.8 yards above Pinnacle" is the sentence a person
    actually wants. It fails on real boards, and not rarely: the anchor's
    main line is frequently the ladder's BOTTOM rung (Aaron Jones at 9.5
    against a ladder starting at 9.5), and when the book sits a shade below
    the anchor there, the required shift is negative and lands off the end
    of the posted ladder. That refused all eight of his rungs over a 2pp
    nudge, and would have done the same for every low-volume player whose
    first rung is his main line. A proportional-odds shift is closed-form,
    stays inside (0, 1) and monotone for free, and evaluates the ladder only
    where the book actually quoted. The readable number survived as a
    diagnostic that is ALLOWED to be missing. When a transform's appeal is
    its interpretability, keep the interpretation as output and choose the
    transform on how it fails.

78. **A fixture's own offset reads as the code's error.** The synthetic
    ladder placed its main line at `round(median) - 0.5`, where the
    generated curve's true survival is not 0.5, so the crossing measured a
    0.88pp LEVEL offset as margin: recovery came back 7.05% against a built
    6.00% and looked like a 1pp error in the measurement code. Moving the
    main to `median + 0.5`, where the curve's survival is exactly 0.5,
    brought it to 5.51% — the residual being integer price rounding, which
    is real. Before trusting a recovery check, confirm the fixture's own
    invariants hold exactly at the point the measurement reads them.

79. **A harness that reads only the failure count calls a crash a pass.**
    Two reverts came back NOT CAUGHT. The suite had in fact printed
    `CRASHED in section 63` and explicitly refused to claim a pass; the
    revert harness's regex read only the "N failed" number and saw 0.
    Lesson 14 has been about checks that crash instead of failing — this is
    the same mistake one level up, in the thing that grades the checks. A
    tool that judges a test suite must read the suite's own verdict rather
    than reconstruct one from a number. Both underlying checks were then
    made to fail cleanly: one crashed in its body (dividing by an empty
    list once the gate it relied on was removed), the other in its DETAIL
    string, formatting `None` with `:+.3%`. A detail argument is evaluated
    eagerly and can take down a run whose check body was correctly guarded.

80. **Tight dispersion can mean a constant denominator, not precision.**
    FanDuel's ladder margin measured sd 0.34% against DraftKings' 1.06% and
    read as the better-measured of the two. It is the opposite: FanDuel's
    own de-vigged main lines were EXACTLY 0.5000 on all twelve crossings,
    so the only thing varying in the ratio was the ladder. DraftKings' ran
    0.3366..0.5122. A ratio's error bar is not evidence about the ratio when
    one side of it never moves — and that sd was being propagated into every
    rung's uncertainty, where it would have made the tail look three times
    better known than it is. This is the same half-yard-grid behaviour
    already documented for Pinnacle's yardage board, observed at a second
    book and costing something new.

81. **A self-comparison does not merely produce a circular number — it can
    strip a warning.** `ladder_cross_check` run with the same book twice
    returned a MEASURED disagreement of 0.0, which removed `ladder_fair`'s
    "uncertainty is a LOWER BOUND" label and added a zero model-risk term:
    output claiming to have been cross-validated against the very ladder it
    was derived from. The first check written for it passed on a clause that
    accepted `median == 0.0` as evidence of refusal, so it was too weak to
    notice. "Do not de-vig a book against itself" is already a rule here;
    this is its third instance and the first where the damage was a silenced
    caveat rather than a wrong figure.

82. **A tuple is not a safeguard if a name is in it.** The ladder's anchor
    join keyed on `(player_id, player)`. That satisfies the letter of "never
    join player data on a raw name" while smuggling the name in as half the
    key, and the live board held the exact case: DraftKings spells
    "D.J. Moore", Pinnacle spells "DJ Moore", one `player_id`
    espn:3915416 — the tuples differed, the join missed, and all 18 of his
    rungs were refused as unanchored while both books were quoting him under
    the same id. Fixing it took that board from 132 priced rungs to 150. The
    same audit found `canonical_bet` keyed on `player_id or player`, which
    fails the same way and in the dangerous direction: it MISSES a duplicate,
    so the two rows that are one bet get parlayed with each other and price
    as independent legs. An id is the right joiner; an id AND a name is a
    name. This is B44/B101's fourth instance and the first wearing a
    disguise.

83. **A join with two keys needs a union, not a preference order.** The first
    fix tried the id index and returned on a hit, which looks obviously
    right. It found the LADDER's own book's main line — same payload, same
    id — and returned before the name index could offer the anchor's
    title-only row, which carries no `player_id` at all. The indices have to
    be merged, with a conflicting id excluding that ROW rather than refusing
    the whole join, and an id-less row dropped only once a spelling is
    genuinely ambiguous. A short-circuit on the stronger key silently
    answers a different question: "is there any row with this id", not "which
    rows are this player".

84. **A predicate needs its false cases pinned as hard as its true ones.**
    `same_bet` had four checks and all of them passed when the key
    comparison was deleted entirely, because every pair they tested either
    IS the same bet or conflicts on an id. Nothing asserted that two
    different thresholds, two different players or two different markets
    are NOT one bet. The same shape appeared twice more the same evening: a
    `_raises(..., ValueError)` on a percentage `model_p` passed a revert
    that removed the percentage branch, because the range check below it
    raises too — so the check survived while the diagnosis it existed for
    was lost. Assert on the message when the message is the point.

85. **A check that reads a figure out of a sentence can read the wrong
    clause.** `"$0.28" in flag` was meant to prove the thin-anchor warning
    names the SHALLOW side. It passed a revert that swapped min for max,
    because the swapped sentence still contains $0.28 — in the other clause,
    describing the deep side. Asserting `startswith` on the exact prefix
    caught it. B124 was the same lesson about a whole report; this is it
    inside one line.

86. **Reproduce a finding before filing it, including a correct-sounding
    one.** A session reported `threshold_prob` as non-monotone and called it
    a shape failure in the estimator. Its own three figures were strictly
    decreasing: it had seen an uneven RATE of decline and misnamed it.
    Measured directly, 0 of 88 adjacent pairs violate monotonicity across
    eight players, and the reproduction matched the session's numbers to
    three decimals — same data, different conclusion. Filing it unchecked
    would have put a defect in the backlog that does not exist and sent the
    next session hunting it. Filed as NOT A DEFECT rather than dropped, so
    the next reader of that kink does not raise it again.

87. **Check what the backlog says an item IS before marking it done.** I
    built `score_slip`, which is the scoring half of F15, and marked F15
    DONE. The original entry defines it as free text — "JSN over 5
    receptions, CMC over 50 rush" — resolved to real lines at a real book
    FIRST, and calls that resolution step **the fragile part**, noting a live
    run that dropped 17 of 41 quotes at exactly that join. I had also filed a
    second F15 row instead of updating the existing one, so for twenty
    minutes the backlog carried the same item as both DONE and OPEN, with the
    DONE row describing half the work. An item is finished when it does what
    it was filed to do, not when the part I happened to think of works. Read
    the entry, not the title.

88. **Check whether an open item is still open before offering it again.**
    I carried B108 — a graded bet with no logged recommendation — across
    three reports, ending each with it as a decision for Dustin to make.
    Running it found the backfill had been written the day before, by an
    earlier session, exactly as specified. The log was the authority on its
    own state and it was one query away; I was quoting a summary of a
    summary. A standing item in a backlog is a claim about the world, and
    claims about the world go stale. Re-check before spending somebody's
    attention on one — and before writing, because the prompt I handed over
    would have double-counted had the session not refused it.

89. **An experiment that measures disagreement has not measured error.**
    B128's follow-up pinned the model's level to the anchor and compared the
    two SHAPES: median residual 2.50% against the ladder's 0.82% precision,
    3.1x, with no relationship to sample size. The tempting write-up is "the
    model's shape is wrong by 2.5pp". What was actually measured is that the
    model and the market DISAGREE by 2.5pp. Calling that error assumes the
    market's shape is right, which is the assumption F4 was filed against,
    and the whole reason to build a model is the possibility that it is not.
    The operational conclusion is the same either way — a rung edge is
    dominated by a quantity nobody can sign — but the reason matters, because
    one version closes the question and the other says what would settle it:
    outcomes, logged and graded. Say which one you have.

90. **Measure the blast radius before asking for a sign-off.** E3 was filed
    expecting the rebuilt market table to be a live behaviour change needing
    Dustin's approval, because `_pair_r` feeds `classify()`. Measured, it is
    not: a correlated pair makes a slip UNPRICEABLE whatever `r` is, so the
    same QB-stack slip classifies identically under both tables with
    identical odds. The value reaches the reported `r` and `factor_note` and
    stops there. The sign-off is still worth asking for, but for a much
    smaller thing than the entry predicted — and the difference between "this
    changes what you bet" and "this changes a line of a report" is exactly
    what a person needs to answer. Run the before/after before writing the
    question.

91. **A property nobody checked is a defect nobody can find.** The lineup
    enumerator hard-picked one quarterback and never enumerated the
    alternative, for as long as this project has existed, and 1,140 checks
    passed identically before and after the fix. Nothing had ever asked the
    one question that finds it without knowing it: can every rostered player
    be reached? A session found it by noticing a delta with the wrong SIGN —
    adding a player cannot raise the best lineup's P(elim) — and then reading
    the enumerator to explain it. Both of those are properties, not examples:
    they hold for every input and they fail loudly on the bug. Prefer one
    property over ten examples when the examples all share an assumption.

92. **The vacuous clause, twice in one evening.** `or True` at the end of a
    check makes it pass unconditionally, and `abs(x is not None and 0 or 0)
    == 0` does the same thing less obviously. Both got written here while
    testing something genuinely hard to reach — an alarm that fires only on
    an impossible input. The fix is not more care at the keyboard; it is to
    extract the branch so it CAN be reached. `render_waiver_board` exists
    separately from `waiver_board` for exactly that reason: `waiver_value`
    cannot produce a positive delta by construction, so no test routed
    through it will ever exercise the alarm, and a check that cannot fail
    will get written to paper over it.

93. **The dangerous wrong answer is the reassuring one.** An eliminated team
    with an empty roster scored 0.00, came last in every simulation, and
    returned P(elim) = 0.0000%. Every other bug in this project has produced
    a number that looked wrong or a refusal that looked annoying; this one
    produced "you are safe" in a format where being wrong means being out.
    The diagnostic information existed — `short_rosters` named the team — but
    it sat below a headline figure that contradicted it, and a caller reads
    the headline. When a check and a headline disagree, the headline wins in
    practice, so the fix belongs in the headline: exclude the team, change
    the number, and say what the number is now relative to.

94. **Test the label, not just the number behind it.** `waiver_board` printed
    "inside the 0.250pp floor — treat as zero" on a −12.23pp move, because
    the comparison put a fraction against a figure in percentage points.
    Fourteen checks shipped around that function hours earlier; every one of
    them asserted on the ranking or the delta, both of which were right the
    whole time, and the suite's own fixture printed `-23.150pp ... inside the
    0.250pp floor` and passed. A human reads the sentence, not the float. If
    a function's output includes a verdict in words, the words are part of
    the contract and need a check of their own — including one on each side
    of the boundary, because the extremes pass under almost any arithmetic.

95. **A flag set by the caller is not a flag read from the data.** The first
    checks for `stale` and `position_defaulted` constructed `WaiverValue`
    with those fields set directly. They proved the formatting worked and
    nothing else: a revert that stopped reading `pool.stale` altogether
    passed every one. A field that is supposed to be DERIVED needs at least
    one check that drives the real derivation, with the source data arranged
    to make it true.

96. **Build the mirror of a function when the mirror is the same read.**
    `waiver_value` paired the comparison for an ADD and shipped with a note
    explaining why running twice is wrong. Nothing covered a DROP, so the
    next session to need one rolled its own, ran four simulations, and
    reported a 0.21pp ordering that was pure between-run noise — the exact
    failure the add-side docstring warns about, two functions away. Dropping
    X restricts the lineup set to those without X, which is literally the
    `p_without` term already computed. When a function exists because a
    naive approach is wrong, its inverse exists for the same reason, and
    leaving the inverse unbuilt is an invitation to repeat the mistake.

97. **Prove the mechanism, not just the output.** `drop_board` exists to
    read every cut off ONE set of draws. The checks counted the rows, read
    the ordering, and verified the costs — and a revert that ran one
    simulation per candidate passed all of them, because the fixture's
    deltas were large enough to survive the noise. What catches it is a
    property of the MECHANISM: if the draws are shared, every priced row
    reports the same baseline. One line, and it fails the moment the
    pairing does.
