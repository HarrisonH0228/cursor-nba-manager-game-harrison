import json
import os
import shutil
import tempfile

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

    fd, temp_path = tempfile.mkstemp(
        dir=os.path.dirname(CACHE_PATH), suffix=".tmp", prefix="cache-"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)

        with open(temp_path, encoding="utf-8") as handle:
            json.loads(handle.read())

        if os.path.exists(CACHE_PATH):
            try:
                shutil.copy2(CACHE_PATH, CACHE_PATH + ".bak")
            except OSError:
                pass

        os.replace(temp_path, CACHE_PATH)
        temp_path = None
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


def get_players():
    return load_cache().get("players", [])
