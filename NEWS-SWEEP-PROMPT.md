# News sweep, NFL Week 12 (Wed 11/25 to Fri 11/27)

One block, pasted into a NEW project thread each time. It can be run more
than once: every run saves its own log, and the later runs are the ones that
catch news the lines have not moved for yet.

| Run | When (Eastern) | Why then |
|---|---|---|
| A | Tuesday 11/24 | DONE 3:23pm. Zero lines to look at: on a short week the lines opened Monday night, after Monday's news |
| B | Wednesday 11/25, 4:30pm to 7:00pm | Final injury reports for Thursday's games come out Wednesday afternoon. Packers at Rams kicks 8:00pm and its inactives come at 6:30pm: run after 6:30pm if betting that game |
| C | Thursday 11/26, 10:00am to 12:15pm | Bears at Lions kicks 1:00pm (inactives 11:30am); the two later games the same day |
| D | Friday 11/27, 11:30am to 2:00pm | Broncos at Steelers kicks 3:00pm (inactives 1:30pm) |

Before each run, the last run's `flags_wk12.json` must be in the repo: Step 5
starts from it.

Delete from GAMES any game Dustin is not betting. Nothing else needs editing.

---

# SWEEP — paste everything below this line

NEWS SWEEP, NFL Week 12. This finds role and usage news (injuries, returns,
depth-chart and quarterback changes) and sets it beside each book's line:
where the line opened, where it is now, and whether it has moved since the
news. It is advisory. It is not a betting run.

GAMES (Eastern time; PropLine event ids):
  1. Green Bay Packers at Los Angeles Rams, Wed 11/25 8:00pm, id 32694
  2. Chicago Bears at Detroit Lions, Thu 11/26 1:00pm, id 32695
  3. Philadelphia Eagles at Dallas Cowboys, Thu 11/26 4:30pm, id 32688
  4. Kansas City Chiefs at Buffalo Bills, Thu 11/26 8:15pm, id 32696
  5. Denver Broncos at Pittsburgh Steelers, Fri 11/27 3:00pm, id 32701
Leave out any game that has already kicked off.

RULES FOR THIS THREAD
- Do not recommend a bet, build a slip, or give a probability or an EV. The
  script gives none and neither do you.
- Report what the script prints. Do not adjust its verdicts or add a
  projection of your own beside them.
- If the script prints STOPPED, fix what it names and run it again. If you
  cannot, quote the message word for word and stop.
- Never retype a movement or injury response. Work from the file the harness
  saved. The only things typed by hand are the findings in Step 5.
- A finding with no publish time, the wrong year, or older than 72 hours does
  not go in the flags file. List it in the report under "found but not
  entered" and say why. Never guess a time to get one in.
- Paraphrase what a page says. Do not quote more than a few words from it.

STEP 1. Set up
    git clone https://github.com/dustinpmason/ff2026.git && cd ff2026
    python3 refresh.py
    python3 -c "import ff_news; print('ff_news loaded')"

STEP 2. Pull the injury report and the lines
  a. ONE call: propline_get_injuries(sport_key="football_nfl"), no team and
     no status filter. It is about 100 KB, so the harness saves it to a file
     and gives you the path. Keep the path.
     If it comes back in the chat instead of as a file, do not retype it:
     leave --injuries off the commands below, and in Step 5 enter each
     quarterback, back, receiver and tight end of the GAMES' teams that it
     lists as out, injured reserve, doubtful or questionable, with source
     "PropLine injuries (ESPN)" and "at" = his status_since.
  b. For each game in GAMES, ONE call:
       propline_get_event_movement(
         sport_key="americanfootball_nfl", event_id=<id>,
         markets="player_pass_yds,player_pass_attempts,player_pass_completions,player_pass_tds,player_rush_yds,player_rush_attempts,player_reception_yds,player_receptions",
         bookmakers="draftkings,fanduel,betmgm")
     Do not pass "since". Each response is 500 to 900 KB and is saved to a
     file. Keep the paths. If one comes back in the chat instead, say so and
     leave that game out.
  Note the two sport keys differ: football_nfl for injuries,
  americanfootball_nfl for movement.

STEP 3. First pass
    python3 ff_news.py --week 12 --no-save --injuries <injuries file> <the movement files>
  Read, for every game:
    - the lines under ACROSS n GAMES at the top
    - 1. FLAGS, and every line marked "! FLAGGED OUT, YET ..."
    - 1b. RETURNS TO CHECK
    - any "Posted, and not placed on either team" line
    - 3. ROLES: the players marked * are the ones with a real role

STEP 4. Look for what the injury report does not have
  Work through the teams in kickoff order. If you run short of room, stop
  and say which teams were not searched. Never present an unsearched team as
  clean.
  For EACH team:
  a. FantasyPros injury_status, ONE CALL AT A TIME (two at once fail with
     "Session operation in progress"). Name: every * player in that team's
     ROLES, every name of that team under RETURNS TO CHECK, FLAGGED OUT YET,
     and "not placed on either team". Full first and last names.
     Read practice_details (status, practice_1 to practice_3,
     probability_of_playing) and player_news (each item has "published" in
     UTC and a url). A player missing from practice_details is not thereby
     healthy: it only means he is not on the injury feed.
     If resolved_players shows him on another team, or as "FA", he has left.
  b. get_nfl_depth_charts(team_code=<code>, position="ALL"). FantasyPros
     writes two codes its own way: JAC and LAR. Compare depth 1 and 2 at QB,
     RB, WR and TE with ROLES:
       - a depth-1 or depth-2 player who is not in ROLES at all (new to the
         team, or back from a long absence)
       - a * player who is missing from the chart, or listed below a player
         with a smaller role
       - a depth-1 quarterback who is not the * quarterback in ROLES
     Each of these is something to look up in (c).
  c. Web search. At least two searches a team, more where (a) or (b) raised
     something. A plain "<team> injury report" search returned 2021 to 2025
     pages in Run A, and naming the site fixed it. So put 2026 and a site in
     every search:
       "<team> practice report 2026" on the team's own site
         (packers.com, detroitlions.com, dallascowboys.com ...)
       "<player> 2026" on cbssports.com/fantasy/football/news (it carries
         each practice estimate with a time and zone)
       "<player> 2026" on nbcsports.com/fantasy/football/player-news
       the team's page at espn.com/nfl/team/transactions for call-ups,
         signings, releases and activations
     Search results still mix seasons: an article from 2023 or 2025 about the
     same two teams reads like this week's. So for every result you mean to
     use:
       1. OPEN the page.
       2. Find its publish date WITH THE YEAR. No year, or not 2026: do not
          use it.
       3. Find its publish time and time zone.
            time and zone shown           use them
            time shown, no zone           use the START of that day, Eastern:
            or date only                  2026-11-24 00:00-05:00, and put
                                          "time not given, start of day used"
                                          in "detail"
          The start of the day is the earliest it could have been, which is
          the safe direction: a line posted that day is then read as posted
          after the news, not as a line that failed to move.
     What counts: ruled out, doubtful, questionable, did not practice,
     upgraded or downgraded in practice, activated from injured reserve,
     designated to return, named the starter, benched, a coach describing a
     changed role, signed, released, elevated from the practice squad.
     What does not: opinion, projections, start/sit advice, a recap of last
     week's box score.
  d. Only if a game in GAMES kicks off within 6 hours:
     propline_get_lineups(sport_key="football_nfl", event_id=<id>). Each
     player has a role (starter, bench, active, inactive), a status (expected
     or confirmed) and "since". An INACTIVE quarterback, back, receiver or
     tight end is a finding: kind OUT, source "PropLine lineups", "at" = his
     "since". A STARTER at quarterback who is not the * quarterback in ROLES
     is a NEW_QB finding. Paste the first three player entries of the
     response word for word at the end of your report: the script does not
     read this response yet and its shape is needed to build that.

STEP 5. Write flags_wk12.json
  START FROM THE LAST RUN'S FILE: flags_wk12.json in the repo folder. For each
  entry in it:
    - still true (you saw it again in Step 4, or a current listing says so):
      KEEP its "at" exactly as it is and set "confirmed" to the time you read
      the current source. Never replace an old "at" with a newer article's
      time: the first report is when the books could act, and moving it later
      makes every line posted in between look like a line that failed to move.
    - superseded (a questionable player now ruled out, or cleared): replace it
      with the new finding at the NEW finding's own time.
    - cannot be confirmed today: delete it and name it in the report.
  An entry older than 72 hours with no "confirmed" stops the script, and the
  message names it.
  Then add what is new. One entry a finding, timed at the EARLIEST report of
  that fact you found. Skip a finding the injury report already carries,
  unless your source is EARLIER than the time printed beside it in FLAGS or
  gives a different status.

    {"flags": [
      {"player": "Josh Jacobs", "team": "GB", "position": "RB", "kind": "DOUBTFUL",
       "source": "FantasyPros news (head coach)", "at": "2026-11-23 16:58:34 UTC",
       "detail": "coach: unlikely to play; limited Monday",
       "url": "https://..."}
    ]}

  player    as ROLES spells him when he is there
  team      the team's code or full name
  position  QB, RB, FB, WR or TE
  kind      OUT           ruled out, injured reserve, suspended, released
            DOUBTFUL      doubtful, or the coach says unlikely
            QUESTIONABLE  questionable, or did not practice with no ruling
            BACK          returning after missing at least one game: activated,
                          or practising in full with the coach saying he plays
            NEW_QB        a different quarterback starts than in the team's
                          last game. "player" is the new starter
            NOTE          anything else about a role: depth-chart order, a
                          coach quote, a signing. Shown, no direction drawn
  source    who reported it
  at        when it was published, WITH a zone: "2026-11-25 14:10-05:00"
            (Eastern in November is -05:00) or "2026-11-25 19:10 UTC".
            For a depth-chart observation with no date, use the time you
            pulled it, kind NOTE, and say "when it changed is not known".
  confirmed only for an entry whose "at" is more than 72 hours old: when you
            read a current source that still says so. Same format as "at".
  detail    a few words. Optional.
  url       the page. Optional.

  One special case. A player under RETURNS TO CHECK who turns out to be on
  injured reserve for weeks, or off the team, is an absence older than 72
  hours. Enter him as OUT with "at" = when it began (the news item that
  placed him there; failing that, the Monday of his first week out at
  00:00 Eastern, saying so in "detail") AND "confirmed" = the time you read
  the current listing that still has him out:
      {"player": "...", "team": "DEN", "position": "RB", "kind": "OUT",
       "source": "FantasyPros listing", "at": "2026-10-26 00:00-04:00",
       "confirmed": "2026-11-24 09:30-05:00", "detail": "injured reserve since Week 8"}

STEP 6. Second pass
    python3 ff_news.py --week 12 --injuries <injuries file> --flags flags_wk12.json <the movement files>
  If a "! FLAGGED OUT, YET ..." line or a RETURNS TO CHECK name is still
  there and you have not settled it, go back to Step 4 for that player once.
  What cannot be settled stays in the report as unsettled.
  The last line printed names the log it saved (news_2026_wk12_<time>.csv).

STEP 7. Report, in this order, in plain words
  1. BOTTOM LINE. Three sentences at most: how many lines the news points at
     that a book has not moved for, what must be settled first, and anything
     where two sources disagree.
  2. LINES TO LOOK AT. Every line under "0. NEWS THE LINE MAY NOT HAVE CAUGHT
     UP WITH", as a table: game, player, stat, the news (who, what, source,
     when in Eastern time), each book's opener and line now, the verdict, and
     whether he is also on a hot run. If there are none, say "none" and
     nothing more. Do not promote anything else into this table.
  3. SETTLE FIRST. Every "FLAGGED OUT, YET", every RETURNS TO CHECK name and
     every "not placed on either team" player: what you found, the source and
     its time, and whether it is settled.
  4. OVERS TO BE CAREFUL WITH. Section 2 of each game (lines on a hot run),
     as one table, with the line the script prints about what a hot run has
     been worth, once. List only players marked * in section 3 (a real
     role); give the count of the others and do not list them.
  5. FLAGS. Every flag by game: player, kind, detail, source, time (Eastern),
     link. Mark the ones you entered by hand.
  6. WHAT WAS SEARCHED. By team: the FantasyPros and depth-chart calls made,
     the searches run, the pages opened. Then "found but not entered": each
     item, and whether it had no date, the wrong year, or was too old. Then
     "carried from the last run": how many entries were kept with a new
     "confirmed", replaced, and deleted, naming the replaced and deleted.
  7. The time (Eastern) the second pass ran.

STEP 8. Give me flags_wk12.json and the news_2026_wk12_<time>.csv log as
  files I can download.
