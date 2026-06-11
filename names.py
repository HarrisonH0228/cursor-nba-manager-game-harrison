"""Diverse fake player name generation for draft prospects."""

import json
import random
from pathlib import Path

_NAMES_DATA = None
_SUFFIXES = ("Jr.", "II", "III")


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
