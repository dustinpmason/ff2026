# Replay of Weeks 9 to 11 on the books' closing lines (engine thread, 2026-11-22)

This is S3: the simulator graded against real book lines and scored against the books' prices.
Made by the engine thread, which can reach PropLine. Nothing here was made before kickoff; it
is a walk-forward replay, like the 46-week record, with real lines in place of stand-in lines.

## How it was made

- 30 finished games: all 15 of Week 9, all 14 of Week 10, and Thursday of Week 11.
- Lines and prices: `propline_get_odds_closing`, 12 prop markets, DraftKings, FanDuel, BetMGM.
  The closing files carry no player id and no team, so every player is matched by name.
- The model is `ff_sim_live.run_live` on the history before each week (commit 6add0e4, the
  committed `sim_record.py`). Nothing in it was changed.
- Handed in, all from what the books posted before kickoff and nothing else:
  - the starter is the quarterback with a priced passing-yards main line;
  - a player whose prices stopped moving more than an hour before kickoff is off the board
    (of 21 such players with yardage lines, none played); his lines are dropped, and if he is
    on the slate he gets chance 0;
  - a slate player posted in another team's game gets chance 0 for the old team;
  - a posted player with a yardage, catches or carries line who is not on the slate is added;
  - a book name the data lacks is aliased when one player on those teams has the same last
    name and a first name starting the same way (Cameron/Cam).
- Graded with `sim_grade.py` as committed. Scored with `replay_score.py`.

## Result

21,945 lines priced, 21,887 graded, 58 void.

Book main lines, one per player and stat, with a two-sided closing price: 1,323 lines, 30 games.

| | Brier |
|---|---|
| calling every line 50/50 | 0.2500 |
| the market's de-vigged closing price | 0.2484 |
| the simulator | 0.2664 |

- Simulator minus market: +0.0181 (se 0.0050, clustered by game). Simulator minus a coin flip:
  +0.0164 (se 0.0053). Worse in Week 9 (0.2544 against 0.2480) and Week 10 (0.2793 against 0.2492).
- On the side it favoured it said 59.7% and 49.2% happened. Where it favoured the over: said
  58.8%, happened 41.8% (505 lines). Under: said 60.3%, happened 53.8% (820 lines).
- Logistic fit of the result on the market's chance and the simulator's chance together:
  weight on the market +0.95 (se 0.24), weight on the simulator -0.25 (se 0.12).
- Betting the side it favoured at 60% or better, best price of the three books: 531 bets,
  market said 52.6%, 51.2% won, return -7.5% (se 5.7). Overs it put at 60%+: 184 bets, 41.3% won.
- Stat lines: the book's line misses by less than the simulator's expected number on every
  stat (receiving yards 19.8 against 21.2, rushing yards 16.8 against 19.3).

Ladder overs with a closing price: 18,406 rungs. Weight on the price's implied chance +0.99
(se 0.07), on the simulator -0.02 (se 0.07). Rungs it put at 70%+ with its own edge of 5%+:
136 bets, it said 76.0%, the price said 64.6%, 55.9% won.

Anytime touchdown: 734 players. It said 16.8%, 16.5% scored. Weight on the price +1.21
(se 0.27), on the simulator -0.28 (se 0.27).

Across every line, ladders included, its chances read as stated in every band from 60% up.
That is the easy rungs; it is not information the price lacks.

Sensitivity: handing every player with live yardage lines a 97% chance of playing (what the
close knows) moves the main-line Brier from 0.2664 to 0.2652. The reading does not change.

## Limits

- Closing lines are the hardest test, and they are made after inactives. A run 3 to 6 hours
  out faces softer lines and knows less.
- 30 games. The Brier gaps are 3 standard errors; the returns are not measured tightly.
- Names only. corr(expected, book line) is 0.989 over the main lines, so mismatches are few.
- Three lines were checked by hand against the raw closing file and the raw weekly table.

## To reproduce

    python3 sim_grade.py replay_shadow_2026_wk09.csv replay_shadow_2026_wk10.csv \
        replay_shadow_2026_wk11.csv --out graded.csv
    python3 replay_score.py .

`replay_closing.py <week> <odds folder> <out folder>` is the script that made the shadow
files; it needs the saved closing responses, which are not in the repo (47 MB).
The files are named `replay_*` so that `sim_grade.py` does not pick them up by itself.
