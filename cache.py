import os

from errors import CacheWriteError, read_json, write_json

CACHE_PATH = os.path.join(os.path.dirname(__file__), "data", "cache.json")

DEFAULT_CACHE = {"last_updated": None, "season": None, "players": []}

_players_cache = {"mtime": None, "payload": None}


def invalidate_players_cache():
    _players_cache["mtime"] = None
    _players_cache["payload"] = None


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
    invalidate_players_cache()


def get_players():
    return load_cache().get("players", [])


def get_cached_players_payload():
    """Return (cache_data, players_list) with in-process cache keyed by file mtime."""
    mtime = os.path.getmtime(CACHE_PATH) if os.path.exists(CACHE_PATH) else None
    if _players_cache["mtime"] == mtime and _players_cache["payload"] is not None:
        cache_data, players = _players_cache["payload"]
        return cache_data, list(players)

    cache_data = load_cache()
    players = list(cache_data.get("players", []))
    _players_cache["mtime"] = mtime
    _players_cache["payload"] = (cache_data, players)
    return cache_data, players
