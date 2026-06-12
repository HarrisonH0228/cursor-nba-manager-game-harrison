"""Shared logging and JSON I/O helpers."""

import json
import logging
import os
from datetime import datetime

_LOG_CONFIGURED = False


class CacheWriteError(RuntimeError):
    """Raised when the player cache cannot be written."""


class SeasonSaveError(RuntimeError):
    """Raised when a season file cannot be saved."""


class CustomPlayersWriteError(RuntimeError):
    """Raised when custom_players.json cannot be written."""


def configure_logging(level=logging.INFO):
    global _LOG_CONFIGURED
    if _LOG_CONFIGURED:
        return
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    _LOG_CONFIGURED = True


def get_logger(name):
    configure_logging()
    return logging.getLogger(name)


def read_json(path, default, label):
    logger = get_logger(__name__)
    if not os.path.exists(path):
        return dict(default) if isinstance(default, dict) else default

    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError:
        logger.exception("%s JSON decode failed: %s", label, path)
        return dict(default) if isinstance(default, dict) else default
    except OSError:
        logger.exception("%s read failed: %s", label, path)
        return dict(default) if isinstance(default, dict) else default

    if data is None:
        return dict(default) if isinstance(default, dict) else default
    return data


def write_json(path, data, label):
    logger = get_logger(__name__)
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    temp_path = path + ".tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
        os.replace(temp_path, path)
        return True
    except OSError:
        logger.exception("%s write failed: %s", label, path)
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except OSError:
            pass
        return False


def format_cache_timestamp(iso_str):
    if not iso_str:
        return None
    try:
        normalized = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        return dt.strftime("%b %d, %Y %I:%M %p UTC")
    except (TypeError, ValueError):
        return str(iso_str)
