import atexit

from apscheduler.schedulers.background import BackgroundScheduler

from errors import get_logger
from fetcher import refresh_cache

logger = get_logger(__name__)
_scheduler = None


def _safe_refresh():
    try:
        result = refresh_cache()
        if result["ok"]:
            logger.info("Scheduled cache refresh succeeded")
        elif result["used_cache"]:
            logger.warning(
                "Scheduled cache refresh failed; using cached data from %s",
                result.get("last_updated") or "unknown time",
            )
        else:
            logger.error(
                "Scheduled cache refresh failed with no cached data: %s",
                result.get("error") or "unknown error",
            )
    except Exception:
        logger.exception("Scheduled cache refresh raised unexpectedly")


def start_scheduler(app):
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    _scheduler = BackgroundScheduler()
    _scheduler.add_job(_safe_refresh, "interval", days=1)
    _scheduler.start()

    atexit.register(lambda: _scheduler.shutdown(wait=False))

    return _scheduler
