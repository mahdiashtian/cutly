"""Celery application and Celery Beat schedule.

``python main.py`` starts the worker and beat processes itself (see
``worker/processes.py``); they can also be run on their own, e.g.::

    celery -A worker.app worker -Q default -n default@%h --loglevel=INFO
    celery -A worker.app worker -Q broadcasts -n broadcasts@%h --pool=solo --loglevel=INFO
    celery -A worker.app beat --loglevel=INFO
"""
from __future__ import annotations

from celery import Celery

from core.config import Settings, get_settings
from worker.queue import BROADCAST_QUEUE, DEFAULT_QUEUE, TaskName


def create_celery(settings: Settings) -> Celery:
    app = Celery("cutly", broker=settings.broker_url, include=["worker.tasks"])
    app.conf.update(
        task_default_queue=DEFAULT_QUEUE,
        # A broadcast can run for hours; its own queue keeps it from starving
        # the 30-second message deletions.
        task_routes={TaskName.RUN_BROADCAST: {"queue": BROADCAST_QUEUE}},
        task_ignore_result=True,
        # Only idempotent tasks opt in to late acks (see worker.tasks).
        task_acks_late=False,
        worker_prefetch_multiplier=1,
        broker_connection_retry_on_startup=True,
        timezone="UTC",
        enable_utc=True,
        beat_schedule={
            # Durable scheduling: due/orphaned broadcasts live in SQL, Beat only
            # polls for them, so nothing scheduled is lost on a restart.
            "dispatch-broadcasts": {"task": TaskName.DISPATCH_BROADCASTS, "schedule": 60.0},
            "cleanup-files": {"task": TaskName.CLEANUP_FILES, "schedule": 30 * 60.0},
            "refresh-channel-titles": {"task": TaskName.REFRESH_CHANNEL_TITLES, "schedule": 6 * 3600.0},
        },
    )
    return app


celery_app = create_celery(get_settings())
