[ ] Web interface — a real browser UI, not a command-line output
[ ] External API connection — pulls live data from a real API (not mocked or hardcoded)
[ ] File-based data storage — reads and writes JSON or CSV; data persists between sessions
[ ] Scheduled data refresh — data updates automatically on a timer, not just when a user loads the page
[ ] User interaction — at least one search, filter, or form input that changes what the user sees
[ ] Error handling — the app degrades gracefully; no unhandled crashes, no naked stack traces shown to the user
[ ] Environment variables — all API keys and secrets live in .env, never in committed code
[ ] Clean commit history — meaningful commit messages, committed at logical checkpoints
[ ] README.md — explains what the app does, how to run it locally, and what API keys are required
[ ] Deployed on Render — accessible via a public URL you can share
[ ] Auto-deploy from GitHub — every push to main triggers a redeploy