import json
import os

CACHE_PATH = os.path.join(os.path.dirname(__file__), "data", "cache.json")

DEFAULT_CACHE = {"last_updated": None, "season": None, "players": []}


def load_cache():
    if not os.path.exists(CACHE_PATH):
        return dict(DEFAULT_CACHE)

    with open(CACHE_PATH, encoding="utf-8") as f:
        data = json.load(f)

    if not data:
        return dict(DEFAULT_CACHE)

    data.setdefault("players", [])
    return data


def save_cache(data):
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    temp_path = CACHE_PATH + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(temp_path, CACHE_PATH)


def get_players():
    return load_cache().get("players", [])
