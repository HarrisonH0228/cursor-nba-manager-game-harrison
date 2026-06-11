"""Funny news ticker headline generation."""

import random

MAX_NEWS_ITEMS = 30

_TEMPLATES = {
    "trade": [
        "Sources say {team} traded {player} for 'culture' and a bag of picks",
        "BREAKING: {team} ships {player} out — league insiders cite 'vibes'",
        "{team} and {partner} completed a trade involving {player}. Nobody clapped.",
        "Trade alert: {player} is headed to {team}. Fantasy managers in shambles.",
    ],
    "signing": [
        "{player} signs with {team} for ${salary}M/yr, reportedly for the cafeteria fries",
        "{team} lands {player} on a ${salary}M deal — agent calls it 'market rate, emotionally'",
        "Free agency: {player} chooses {team} over literally sleeping on it",
        "{player} inks with {team}. Contract: ${salary}M. Happiness: pending.",
    ],
    "rejection": [
        "{player} declined {team}'s ${salary}M offer, calling it 'a participation trophy contract'",
        "{player} told {team} to try again — with more zeros",
        "Sources: {player} rejected {team}'s offer and went to touch grass",
        "{player} passed on {team}. 'I know my worth,' said someone who definitely does.",
    ],
    "injury": [
        "{player} listed as OUT ({detail})",
        "{player} is day-to-day with a classic case of being too good",
        "Injury report: {player} — {detail}. Rival fans nod solemnly.",
        "{team}: {player} unavailable. Reason: {detail}",
    ],
    "game": [
        "{player} dropped {pts} on {opp}; defenders filed a complaint",
        "{player} went for {pts} vs {opp}. The box score needs a nap.",
        "Hot take: {player}'s {pts}-point night against {opp} was 'pretty good'",
        "{opp} couldn't stop {player} ({pts} PTS). Film study cancelled.",
    ],
    "upset": [
        "UPSET: {winner} ({w_score}) stuns {loser} ({l_score}). Brackets weep.",
        "{loser} lost to {winner}. Somewhere, a fan yelled at their TV.",
        "Shocker: {winner} beats {loser} {w_score}-{l_score}. Math is broken.",
    ],
    "draft": [
        "{team} selects {player}; scout notes: 'he looks fast in 2K'",
        "With the pick, {team} takes {player}. Twitter is undefeated.",
        "{team} drafts {player}. Ceiling: sky. Floor: also sky, allegedly.",
        "Draft pick: {team} grabs {player}. Analysts say 'sure, why not'",
    ],
    "retirement": [
        "{player} hangs it up at {age}; league mourns, fantasy GMs rejoice",
        "{player} announces retirement. Highlights reel loading…",
        "End of an era: {player} retires. Someone please tell their agent.",
    ],
    "pick_trade": [
        "{team} traded a pick for a {year} R{round} future pick. Time travel confirmed.",
        "Draft trade: {team} swaps picks for {year} R{round}. GM playing 4D chess (probably).",
    ],
    "championship": [
        "CHAMPIONS: {team} win the NBA Finals — Larry O'Brien trophy secured",
        "{team} capture the title. Parade planning already underway.",
        "NBA Finals: {team} hoist the trophy. Confetti budget: unlimited.",
    ],
}


def _format_headline(season, category, context):
    templates = _TEMPLATES.get(category, ["{team} did something."])
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


def news_headlines(season, limit=12):
    seen = set()
    unique = []
    for headline in season.get("news_feed", []):
        if headline in seen:
            continue
        seen.add(headline)
        unique.append(headline)
        if len(unique) >= limit:
            break
    return unique
