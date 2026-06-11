"""Diverse fake player name generation for draft prospects."""

import json
import random
from pathlib import Path

_NAMES_DATA = None
_SUFFIXES = ("Jr.", "Sr.", "II", "III")
_SUFFIX_ORDER = ("Jr.", "Sr.", "II", "III", "IV")

_KNOWN_SUFFIXES = set(_SUFFIX_ORDER)


def _load_names_data():
    global _NAMES_DATA
    if _NAMES_DATA is None:
        path = Path(__file__).resolve().parent / "data" / "names.json"
        with path.open(encoding="utf-8") as handle:
            _NAMES_DATA = json.load(handle)
    return _NAMES_DATA


def generate_player_name(rng=None) -> str:
    rng = rng or random.Random()
    data = _load_names_data()
    first = rng.choice(data["first_names"])
    last = rng.choice(data["last_names"])
    if rng.random() < 0.08:
        return f"{first} {last} {rng.choice(_SUFFIXES)}"
    return f"{first} {last}"


def _normalize_name(name):
    return " ".join((name or "").split()).lower()


def _split_base_and_suffix(name):
    parts = (name or "").split()
    if len(parts) >= 2 and parts[-1] in _KNOWN_SUFFIXES:
        return " ".join(parts[:-1]), parts[-1]
    return name, None


def ensure_unique_name(name, existing_names):
    """If name collides, append Jr./Sr./II/III/IV until unique."""
    if not name:
        return name
    normalized_existing = {_normalize_name(n) for n in existing_names if n}
    candidate = " ".join(name.split())
    if _normalize_name(candidate) not in normalized_existing:
        return candidate

    base, _existing_suffix = _split_base_and_suffix(candidate)
    for suffix in _SUFFIX_ORDER:
        attempt = f"{base} {suffix}"
        if _normalize_name(attempt) not in normalized_existing:
            return attempt

    counter = 2
    while True:
        attempt = f"{base} {counter}"
        if _normalize_name(attempt) not in normalized_existing:
            return attempt
        counter += 1


def dedupe_all_player_names(players):
    """Ensure no duplicate names across a player iterable."""
    seen = set()
    for player in players:
        name = player.get("name") or ""
        unique = ensure_unique_name(name, seen)
        player["name"] = unique
        seen.add(_normalize_name(unique))
