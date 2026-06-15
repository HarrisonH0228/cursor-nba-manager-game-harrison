# [App Name]

Simulates in an arcade-feel what it's like to be an NBA GM and to manage a team.

## Demo
https://cursor-nba-manager-game-harrison-1.onrender.com/

## Features
- Player-driven simulated games
- Players attributes change with age over time
- Player stats depend on attribute

## Tech Stack
- Python 3 / Flask
- Bootstrap 5
- nba_api API
- APScheduler
- Deployed on Render

## Setup
Establish a Python virtual environment, then run the command run flask OR you can run Python Debugger

### Prerequisites
- Python 3.x

### Installation
\`\`\`bash
git clone https://github.com/HarrisonH0228/cursor-nba-manager-game-harrison
cd ~Document/GitHub/cursor-nba-manager-game-harrison
pip install -r requirements.txt
\`\`\`

### Run Locally
\`\`\`bash
flask run
\`\`\`
Open http://localhost:5000

### Admin and security notes
- Admin routes require login. Default password is `1234`; override with the `ADMIN_PASSWORD` environment variable.
- Player cache refresh uses `POST /refresh` only (Search page button).
- HTML forms include CSRF tokens; JSON trade preview sends `X-CSRFToken` from the page meta tag.

## How It Works
The app combines real NBA data with a locally simulated GM career. It fetches from stats.nba.com via nba_api, which is then processed into overall ratings and attributes for each player, then stored in data/cache.json. A scheduler in the background keeps that cache updated, and if the API is unavailable, the app falls back to the last cached snapshot.
When you start a game, Flask assigns you a random NBA team and tracks your session inside the browser. Starting a season copies the cached player pool into a new save file under data/seasons/, then simulates a full league year using that copied file so the original cache isn't affected: schedule, standings, trades, free agency, playoffs, and draft. All GM actions read and write that season file while the cache remains the shared source of real world player identities and base stats.
The UI is a Flask server that renders Bootstrap templates. Each page load pulls from the cache and/or your active season save, runs the relevant simulation or trade logic in Python, and returns HTML. There isn't a separate client app, the browser talks to Flask routes, and persistence is plain JSON on disk plus Flask session cookies for "who you are" and "which season you're in."

## What I'd Build Next
- I'd add salary caps and player contract negotiations
- Make the other teams trade for and sign players
- Make it more like a game, adding difficulties and modes