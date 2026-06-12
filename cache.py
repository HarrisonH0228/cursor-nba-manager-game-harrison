import os

from errors import CacheWriteError, read_json, write_json

CACHE_PATH = os.path.join(os.path.dirname(__file__), "data", "cache.json")

DEFAULT_CACHE = {"last_updated": None, "season": None, "players": []}


def ensure_cache_file():
    if os.path.exists(CACHE_PATH):
        return
    save_cache(dict(DEFAULT_CACHE))


def load_cache():
    data = read_json(CACHE_PATH, DEFAULT_CACHE, "player cache")
    if not isinstance(data, dict):
        return dict(DEFAULT_CACHE)
    if not data:
        return dict(DEFAULT_CACHE)
    data.setdefault("players", [])
    data.setdefault("last_updated", None)
    data.setdefault("season", None)
    return data


def save_cache(data):
    if not write_json(CACHE_PATH, data, "player cache"):
        raise CacheWriteError("Could not save player cache.")


def get_players():
    return load_cache().get("players", [])
