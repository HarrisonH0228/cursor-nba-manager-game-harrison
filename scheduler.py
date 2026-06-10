import atexit

from apscheduler.schedulers.background import BackgroundScheduler

from fetcher import refresh_cache

_scheduler = None


def start_scheduler(app):
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    _scheduler = BackgroundScheduler()
    _scheduler.add_job(refresh_cache, "interval", days=1)
    _scheduler.start()

    atexit.register(lambda: _scheduler.shutdown(wait=False))

    return _scheduler
