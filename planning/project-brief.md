## What I'm Building
I'm building a unique game where you act as the General Manager (GM) of an NBA team. There can be different objectives to this game, the player may want to trade all their talent away in favor of draft picks and younger players, or they may want to throw away their draft picks in favor of already proven stars! I want there to be API access for modern player statistics/ratings, draft picks, trade engine, season simulation, and more!

## Who It's For
This is for people who want to be able to act like an NBA GM in an arcade-like game, where there isn't any risk for your job and you can explore numerous possibilities. I'm anticipating my target audience will be teenagers and adults who are invested in sports and the NBA.

## The API
- Name: BallDontLie
- Base URL: balldontlie.io
- Authentication method: API Key
- Rate limits: 5 requests per minute
- What data I'll be pulling: Player stats, player teams, teams
- Link to docs: balldontlie.io/docs

## Data I'm Storing
- What gets cached: Player Point per game, Rebounds per game, Assists per game, Steals per game, Blocks per game
- How often it refreshes: Once every day
- File format (JSON/CSV): JSON
- What a single record looks like (paste an example API response): i don't know yet

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