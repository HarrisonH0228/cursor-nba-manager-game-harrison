## Security Issues Flagged by Cursor

### app.py

* Default FLASK_SECRET_KEY = "dev" (line 111). Anyone who knows this can forge session cookies. On a public deploy, that enables session hijacking and (with a crafted season_id) path issues below.
- I decided to keep this because I'm keeping this project local

* Admin panel has no authentication — only ADMIN_ENABLED (defaults to true). /admin and all roster/custom-player mutation routes are open to anyone who can reach the site. _admin_guard() only checks the env flag, not identity.
- I fixed this by adding a password so I can still access the admin panel myself

* No CSRF protection on any POST route (trades, season sim, draft picks, admin actions, new game). A malicious page could trigger actions while you’re logged in.
- Fixed this because it seemed like a major vulnerability

* GET /refresh mutates server state (calls NBA API, rewrites cache.json) with no auth or rate limit. Easy to abuse for DoS or unwanted API hammering; also classic CSRF trigger via <img src="/refresh">.
- Fixed this to prevent issues in the future

* app.run(debug=True) in __main__ (line 1607). Fine locally; ensure production never uses this entrypoint with debug on.
- Will fix this (if I ever made this site publicly available)

### season_store.py + game.py

* season_id is not validated before os.path.join(SEASONS_DIR, f"{season_id}.json"). IDs are UUIDs in normal flow, but session values are trusted. With a weak/forged session cookie, a value like ../../something could write/read outside data/seasons/. Fix: accept only UUID format (or basename-safe slug).
- Fixed this to prevent bugs if anything goes wrong

### trade.py

* validate_trade() never checks that partner_team_id exists in the season (standings/rosters). A crafted partner_id can pass validation for pick-only trades and execute_trade() will setdefault new roster/pick buckets for arbitrary team IDs, corrupting save data.
- Fixed this to prevent possible save data corruption