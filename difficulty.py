"""Difficulty presets for CPU behavior, trades, and simulation."""

DIFFICULTY_LEVELS = ("easy", "normal", "hard", "legend")

DIFFICULTY_LABELS = {
    "easy": "Easy",
    "normal": "Normal",
    "hard": "Hard",
    "legend": "Legend",
}

DIFFICULTY_DESCRIPTIONS = {
    "easy": "Forgiving trades and light CPU free agency.",
    "normal": "Balanced challenge for most players.",
    "hard": "Smart CPU GMs and tougher trade partners.",
    "legend": "Aggressive CPU GMs, tough trades, minimal sim favors.",
}

PRESETS = {
    "easy": {
        "max_cpu_fa_signings": 6,
        "cpu_fa_retry_stars": False,
        "cpu_star_offer_floor": 0.94,
        "trade_tolerance": 18,
        "outcome_nudge_blend": 0.14,
        "outcome_nudge_min_gap": 6,
        "gm_personalities_from_start": False,
        "weak_team_fa_boost": 0,
    },
    "normal": {
        "max_cpu_fa_signings": 12,
        "cpu_fa_retry_stars": True,
        "cpu_star_offer_floor": 1.0,
        "trade_tolerance": 15,
        "outcome_nudge_blend": 0.12,
        "outcome_nudge_min_gap": 8,
        "gm_personalities_from_start": False,
        "weak_team_fa_boost": 4,
    },
    "hard": {
        "max_cpu_fa_signings": 24,
        "cpu_fa_retry_stars": True,
        "cpu_star_offer_floor": 1.05,
        "trade_tolerance": 11,
        "outcome_nudge_blend": 0.08,
        "outcome_nudge_min_gap": 10,
        "gm_personalities_from_start": True,
        "weak_team_fa_boost": 8,
    },
    "legend": {
        "max_cpu_fa_signings": 32,
        "cpu_fa_retry_stars": True,
        "cpu_star_offer_floor": 1.10,
        "trade_tolerance": 8,
        "outcome_nudge_blend": 0.05,
        "outcome_nudge_min_gap": 12,
        "gm_personalities_from_start": True,
        "weak_team_fa_boost": 12,
    },
}


def normalize_difficulty(value):
    """Return a valid difficulty slug, defaulting to normal."""
    if value in PRESETS:
        return value
    return "normal"


def difficulty_label(value):
    slug = normalize_difficulty(value)
    return DIFFICULTY_LABELS[slug]


def get_difficulty_settings(season):
    """Return preset tunables for the season's difficulty."""
    slug = normalize_difficulty((season or {}).get("difficulty"))
    return dict(PRESETS[slug])
