"""Funny news ticker headline generation."""

import random

from attributes import ROTATION_SIZE, team_rating_pool
from news_templates import TEMPLATES

MAX_NEWS_ITEMS = 30
OFFCOURT_NEWS_CHANCE = 0.35


def _format_headline(season, category, context):
    templates = TEMPLATES.get(category, ["{team} did something."])
    indices = season.setdefault("news_template_index", {})
    start = indices.get(category, 0)
    safe = {k: str(v) for k, v in context.items() if v is not None}
    feed = season.get("news_feed", [])
    existing = set(feed)

    for offset in range(len(templates)):
        idx = (start + offset) % len(templates)
        template = templates[idx]
        try:
            headline = template.format(**safe)
        except KeyError:
            headline = template
        if headline not in existing:
            indices[category] = (idx + 1) % len(templates)
            return headline

    return None


def append_news(season, category, **context):
    """Push a headline onto season news_feed (newest first)."""
    feed = season.setdefault("news_feed", [])
    headline = _format_headline(season, category, context)
    if not headline or headline in feed:
        return headline or ""
    feed.insert(0, headline)
    season["news_feed"] = feed[:MAX_NEWS_ITEMS]
    return headline


def _random_player_context(season, lookup, rng):
    from season import roster_players, team_name

    team_ids = [int(tid) for tid in season.get("rosters", {}).keys()]
    if not team_ids:
        return None
    team_id = rng.choice(team_ids)
    roster = roster_players(season, team_id, lookup)
    if not roster:
        return None
    pool = team_rating_pool(roster)
    if not pool:
        pool = sorted(roster, key=lambda player: player.get("overall") or 0, reverse=True)
    player = rng.choice(pool[:ROTATION_SIZE] or pool)
    return {
        "player": player.get("name", "Unknown"),
        "team": team_name(season, team_id),
        "team_id": team_id,
    }


def _ambient_headline(season, lookup, rng, existing):
    ctx = _random_player_context(season, lookup, rng)
    if not ctx:
        return None
    category = rng.choice(["offcourt", "ambient"])
    templates = TEMPLATES.get(category, [])
    if not templates:
        return None
    for _ in range(len(templates)):
        template = rng.choice(templates)
        try:
            headline = template.format(**{k: str(v) for k, v in ctx.items() if v is not None})
        except KeyError:
            headline = template
        if headline not in existing:
            return headline
    return None


def news_headlines(season, limit=12, lookup=None, rng=None):
    seen = set()
    unique = []
    for headline in season.get("news_feed", []):
        if headline in seen:
            continue
        seen.add(headline)
        unique.append(headline)
        if len(unique) >= limit:
            break

    if len(unique) >= limit or not lookup:
        return unique

    rng = rng or random.Random()
    attempts = 0
    while len(unique) < limit and attempts < limit * 4:
        attempts += 1
        headline = _ambient_headline(season, lookup, rng, seen)
        if headline:
            seen.add(headline)
            unique.append(headline)

    return unique


def maybe_roll_offcourt_news(season, lookup, day, rng=None):
    """Maybe add a fake off-court player headline once per simulated day."""
    rng = rng or random.Random()
    if rng.random() >= OFFCOURT_NEWS_CHANCE:
        return ""
    ctx = _random_player_context(season, lookup, rng)
    if not ctx:
        return ""
    return append_news(
        season,
        "offcourt",
        player=ctx["player"],
        team=ctx["team"],
    )
