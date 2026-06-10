## What I'm Building
I'm building a unique game where you act as the General Manager (GM) of an NBA team. There can be different objectives to this game, the player may want to trade all their talent away in favor of draft picks and younger players, or they may want to throw away their draft picks in favor of already proven stars! I want there to be API access for modern player statistics/ratings, draft picks, trade engine, season simulation, and more!

## Who It's For
This is for people who want to be able to act like an NBA GM in an arcade-like game, where there isn't any risk for your job and you can explore numerous possibilities. I'm anticipating my target audience will be teenagers and adults who are invested in sports and the NBA.

## The API
- Name: nba_api
- Base URL: https://stats.nba.com
- Authentication method: None (public NBA.com stats endpoints)
- Rate limits: Unofficial; NBA throttles aggressive traffic (~0.6s between calls recommended). Cloud provider IPs (Render, AWS, GCP) are often blocked.
- What data I'll be pulling: Player stats, player teams, teams
- Link to docs: https://github.com/swar/nba_api

## Data I'm Storing
- What gets cached: Player Point per game, Rebounds per game, Assists per game, Steals per game, Blocks per game
- How often it refreshes: Once every day (locally; Render serves committed cache only)
- File format (JSON/CSV): JSON
- What a single record looks like (paste an example API response):
```json
{
  "last_updated": "2026-06-10T12:00:00Z",
  "season": 2026,
  "source": "nba_api",
  "players": [
    {
      "id": 203999,
      "name": "Nikola Jokic",
      "team": "Denver Nuggets",
      "team_id": 1610612743,
      "ppg": 29.6,
      "rpg": 12.7,
      "apg": 10.2,
      "spg": 1.8,
      "bpg": 0.6,
      "gp": 72,
      "overall": 98.4,
      "age": 30
    }
  ]
}
```

## User Interactions
- View their team (Player Names, Rating, Age, Contract)
- Trade Engine
    - Owned Draft Picks
    - Owned Players (with trade value)
    - Able to select other team's players or picks to trade for

## Pages / Routes
I don't know yet

## Error States
[What could go wrong? How will the app handle each case?]
- API is down → default to the most recent cached data with a disclaimer that it may be outdated
- API returns no results → default to most recent cached data with a disclaimer that it may be outdated
- Cache file is missing → Make a new one

## Stretch Goals
- No Salary cap mode
- Other GM personalities (Rebuilder, Contender, Cheap)
- AI trade negotiation with GMs
- Challenge mode
- Current player & rookie scouting reports
- News feed and media reactions
- Dynamic league (other teams trading with each other)
