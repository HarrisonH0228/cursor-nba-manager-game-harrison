# NBA Manager Game

A browser-based NBA General Manager game. Search and browse live player stats pulled from NBA.com via the [nba_api](https://github.com/swar/nba_api) Python package.

## Requirements

- Python **3.10+**
- pip

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file (optional):

```env
FLASK_SECRET_KEY=your-secret-key
ENABLE_SCHEDULER=true
```

No API key is required — `nba_api` uses public NBA.com stats endpoints.

## Running locally

```bash
python app.py
```

Open http://127.0.0.1:5000/search

## Refreshing player data

Stats are cached in `data/cache.json`. Refresh locally (NBA.com blocks most cloud IPs):

```bash
python fetcher.py
```

Or click **Refresh Data** on the Search page while the app is running locally.

The scheduler refreshes once per day when `ENABLE_SCHEDULER=true` (local dev only).

## Deploying on Render

1. Set `ENABLE_SCHEDULER=false` on Render — the app serves cached JSON only.
2. Refresh data locally with `python fetcher.py`.
3. Commit the updated `data/cache.json` and deploy.

Render cannot call stats.nba.com directly in most cases. See [nba_api issue #176](https://github.com/swar/nba_api/issues/176).

## Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `FLASK_SECRET_KEY` | No | `dev` | Flask session secret |
| `ENABLE_SCHEDULER` | No | `true` | Daily auto-refresh (disable on Render) |

## Project structure

```
app.py          Flask routes
fetcher.py      nba_api client + cache refresh
cache.py        JSON file cache
scheduler.py    Daily background refresh
data/cache.json Cached player stats
templates/      HTML views
```
