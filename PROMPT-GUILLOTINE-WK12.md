# Guillotine waivers, FAAB and lineup — Week 12

Paste everything below the line into a NEW project thread, and attach the
ESPN screenshots listed under "What only Dustin can see" to the same message.

Run it Tuesday 11/24, before claims process overnight. This week's lineup
locks early: the first game is Wednesday 8:00pm ET.

---

Mid Season Guillotine, waiver run and lineup for Week 12. Follow
"Guillotine waivers and FAAB bids — the weekly procedure" and "Guillotine
lineups" in the project instructions exactly. Re-clone first and print the
commit hash and `DATA AS OF`. Where the instructions and this prompt differ,
this prompt is newer.

The engine changed on 2026-11-24 (B267 to B270). Use the calls below as
written: they build `idle` and pass it to the boards. Quote the board's own
tags (`HOLE at`, `IDLE`, `THIN`, `UNAVAILABLE THIS WEEK`, `LINEUP CAP`); do
not turn any of them into "he does not help".

```python
from ff_data import load_weekly
from ff_scoring import LEAGUES
from ff_guillotine import (build_pool, build_meta, players_on_bye, idle_games,
                           wire_sweep, waiver_board, drop_board,
                           waiver_demand, faab_read, run)
ME, WEEK = "3", 12
wk    = load_weekly([2025, 2026])
pool  = build_pool(wk, LEAGUES["guillotine"], season=2026)
meta  = build_meta(wk[wk.season == 2026])
idle  = idle_games(wk, 2026)
# teams = get_roster(league_key=..., all_teams=True)["teams"], with the cut
#         team's roster emptied (step 1)
# OUT   = the Out, IR and Doubtful players from step 2, any spelling
out12 = set(OUT)                                    # no byes in Week 12
out13 = set(OUT) | players_on_bye(13, meta, {"BAL", "IND", "LV", "NYJ"})
alive = [t for t in teams if any(t["roster"].values())]
WEEKS_LEFT = len(alive) - 1

swept, left_off = wire_sweep(pool, meta, teams, idle=idle)
print(left_off)
# cands = the released roster + last week's drops still unrostered + swept, at most twenty
for week, out in ((12, out12), (13, out13)):
    print(waiver_board(teams, pool, my_team_id=ME, candidates=cands, n_sims=80_000,
                       meta=meta, week=week, unavailable=out, idle=idle))
    print(drop_board(teams, pool, my_team_id=ME, n_sims=80_000, meta=meta,
                     week=week, unavailable=out))
# for each player worth a real bid (step 6):
d = waiver_demand(teams, pool, candidate=name, meta=meta, week=WEEK,
                  unavailable=out12, idle=idle, budgets=BUDGETS)   # {team_id: dollars}
print(faab_read(d, my_team_id=ME, my_budget=MY_DOLLARS, weeks_left=WEEKS_LEFT).report())
# the lineup (step 9):
print(run(teams, pool, my_team_id=ME, n_sims=80_000, meta=meta,
          unavailable=out12, week=WEEK).report())
```

## What only Dustin can see

His ESPN screenshots are attached. Read these four things from them and
PRINT WHAT YOU READ, as tables, before doing anything else, so he can correct
a misread. If a screenshot is missing, say which and carry on with what there
is; do not guess a number.

1. FAAB remaining for every team still alive, his own included.
2. Last week's processed bids (Wed 11/18): player, winner, winning amount,
   and every losing bid shown.
3. When this week's claims process.
4. The team eliminated after Week 11 and the roster it released.

For reference, last week's balances BEFORE the 11/18 claims were: The
Dunnernator $1,000, Ilhan's Brother $990, Ballin On A Budget (Dustin) $987,
Show me those TD's $750, The Quadfather Part II $450, brandon's Best Team
$400, Big Blue Crew $65. Use the screenshot's figures, not these.

## What is already known

- Dustin's team is "Ballin On A Budget", team id 3, league key
  `nfl~db5caac1-6d74-4e86-adde-549164c71811`.
- NO NFL team is on a bye in Week 12 (checked on the connector 11/24: byes
  run Weeks 5 to 11, then 13 and 14). So for Week 12 nobody is off, and
  `out12` is the Out, IR and Doubtful players only.
- Week 13 byes: BAL, IND, LV, NYJ. Week 14: ARI, DAL. Confirm with
  `get_schedule_and_strength` before using them.
- Week 12 kickoffs (ET): Packers at Rams Wed 8:00pm; Bears at Lions Thu
  1:00pm; Eagles at Cowboys Thu 4:30pm; Chiefs at Bills Thu 8:15pm; Broncos
  at Steelers Fri 3:00pm; the rest Sunday and Monday.
- On the roster as the connector had it 11/24, these lock before Sunday:
  Blake Corum (Wed); Luther Burden III, D'Andre Swift, Colston Loveland,
  DeVonta Smith, Javonte Williams (Thu afternoon); Rashee Rice and Kenneth
  Walker III (Thu night). Walker: Questionable (groin), did not take part
  in Monday's walkthrough, and FantasyPros put him at 11% to play as of
  11/23. Nobody else on the roster was on the injury feed.

## What to do

1. **State of the league.** Current week from the connector. Pull every
   roster. On 11/24 the connector still showed seven teams with players, so
   it had not yet applied the Week 11 cut. If the team in screenshot 4 still
   has players in the connector's response, give it an empty roster before
   anything is simulated, and say you did:
   `teams = [dict(t, roster={}) if t["team_name"] == CUT else t for t in teams]`
   Then say how many are alive and how many cuts are left including this
   week's (`WEEKS_LEFT`). If the connector's roster for Dustin differs from
   the screenshot, say so and use the screenshot.
2. **Who is unavailable.** `injury_status` for every player on Dustin's
   roster, every released player, and every player on a rival roster who is
   that team's only quarterback or only tight end. One call at a time. Out,
   IR and Doubtful go in `out`, in whatever spelling the tool gives. After
   the first `run`, check its "excluded as unavailable" line against `out`
   and name anyone on your list it did not exclude.
3. **Who is on the wire.** The released roster from screenshot 4, plus last
   week's drops if still unrostered, plus `wire_sweep(pool, meta, teams,
   idle=idle)`: print its account of who it left off. Keep at most twenty
   candidates: all of the released roster, then the sweep's best by mean.
   A player is on the wire when he is on no roster in `get_roster`.
   `get_player_ownership` does not work for this league (on 11/24 it
   answered "No players currently synced in league"), so do not use it.
   Run `injury_status` on every candidate you keep: on 11/24 the sweep's top
   name was Brock Bowers, who was inactive in Week 11 (ankle/quad), and its
   second was Max Hurleman, a practice-squad call-up with one game.
4. **`waiver_board`** for team 3, Week 12, 80,000 sims, with `idle=idle`.
   Then again for Week 13 with that week's byes added to `out`. One table:
   player, position, team, this week's change in P(elim), next week's, and
   every tag the board printed for him.
5. **`drop_board`** for his roster, Week 12 and Week 13. Pair each add worth
   making with its cheapest cut and give the net.
6. **`waiver_demand` + `faab_read`** for every candidate who takes more than
   1 point off his P(elim) in either week (at most six), with `budgets` from
   screenshot 1 and `idle=idle`. Print each report in full. A rival marked
   `HOLE at` has to add somebody: say which rivals those are.
7. **What the simulation cannot see**, for every player in steps 4 to 6: a
   quarterback change, a teammate returning or out, a player on a new team
   (compare the connector's depth chart with `meta`), and anyone tagged
   `IDLE`.
8. **The bids**, under the committed-resource rule: the number first, then
   the evidence that would move it. Say where each sits between last week's
   winning prices and the lock price, and what he gives up one step lower.
   Give the total if every claim lands and the budget left per remaining
   week. ESPN fails a claim whose drop player has already been dropped, so
   two claims tied to the same drop cannot both land: use that when he wants
   only one of two players, and say so.
9. **The lineup**, on the roster as it stands now and again as it would
   stand if the claims land (the real twelve with those adds in and those
   drops out, never a roster carrying every candidate): `run(...)` for Week
   12 with `out12`, 80,000 sims.
   Read the top of the report first (`! EMPTY SLOT`, `! LINEUP CAP`, short
   rosters). Give the lowest-risk lineup, and then list the starters IN LOCK
   ORDER with the time each locks, so he knows which decisions cannot wait
   for Sunday. For any starter listed Questionable, name the swap to make if
   he is ruled out and the last moment it can be made.
10. **End with one table:** claim, drop, bid, P(elim) this week before and
    after, the lock price, and one line on what would change the call.

## Send back

Every board and every `faab_read` report as printed, the tables you read
from the screenshots, the bids table, the lineup in lock order, every
traceback, and anything that looked plausible but was wrong.
