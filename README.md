# ff2026

A personal, local command-line tool for managing my own Yahoo Fantasy Football teams.

This is not a product. It is not distributed, hosted, sold, or made available to anyone
else. It runs on my machine, reads data for leagues my own Yahoo account belongs to, and
prints output for me.

## Why it exists

I play in three 2026 NFL fantasy football leagues, and all three use different scoring
rules and roster requirements. Generic rankings and generic ADP are built for a generic
league, so the same player is worth meaningfully different amounts in each of mine.

The tool reads each league's actual scoring settings and re-values players against those
settings, so a decision in one league isn't made using another league's math.

## What it does

**Working**
- Yahoo OAuth 2.0 authentication (authorization code flow, local token cache + refresh)
- League discovery for the authenticated account

**In progress**
- Snapshot each league's settings — scoring modifiers, roster slots, team count, draft
  format — into a local SQLite database
- Re-score player projections against each league's scoring profile
- Build a pre-draft board per league: tiers, value over replacement, ADP delta
- Offline draft-day pick tracker (no network dependency during a live draft)

**Planned**
- Weekly lineup and waiver context: roster, matchup, available players, usage trends

## Design constraints

These are deliberate, not incidental.

- **Read-only.** No write operations to any Yahoo resource.
- **Local only.** SQLite file on my machine. No server, no hosting, no public interface.
- **No redistribution.** Nothing retrieved from the API is republished, resold,
  displayed to other users, or shared outside this machine.
- **Low request volume.** A handful of calls per day, cached aggressively. No polling
  loops, no bursty traffic. The draft-day path is designed to require no network calls
  at all.
- **Single user, single account.** Me.

## Data sources

| Source | Auth | Use |
|---|---|---|
| Yahoo Fantasy Sports API | OAuth 2.0 | league settings, rosters, player pool, matchups (pending access) |
| Sleeper API | none | player master list, ID crosswalk, add/drop trends |
| nflverse / `nfl_data_py` | none | historical stats and usage rates |

Fantasy data provided by Yahoo Fantasy.

## Yahoo API access status

OAuth 2.0 authentication against a YDN application succeeds and returns a valid token,
but Yahoo Fantasy endpoints return `401 additional_authorization_required`. The app
creation form at `developer.yahoo.com/apps/create` no longer offers a Fantasy Sports
permission to select, so the application's grant does not include fantasy scope.

An access request has been submitted through the Yahoo Sports Developer Portal. Until
that is resolved, league settings are captured manually from each league's Yahoo
settings page, and player data comes from the no-auth sources above. The Yahoo client
code is in place and unchanged either way.

## Stack

Python 3.10, SQLite, `requests`, `yahoo_oauth`. No framework, no server, no ORM.

## Local setup

```
python3 -m venv .venv
source .venv/bin/activate
pip3 install -r requirements.txt
python3 test_auth.py
```

Credentials live in `oauth2.json`, which is gitignored and never committed.

## License / attribution

Personal project, not licensed for redistribution. Yahoo Fantasy data is subject to the
Yahoo Fantasy Sports API Terms of Use, and any display of it here includes the
attribution above.
