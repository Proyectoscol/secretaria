"""
Celery application factory.

Import this in tasks.py and in the Celery worker entrypoint.
"""

from __future__ import annotations

import os
from celery import Celery

REDIS_URL: str = os.getenv("KOS_REDIS_URL", "redis://redis:6379/0")

app = Celery(
    "kos",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["services.queue.tasks"],
)

app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # Retry delays (exponential back-off via Celery's countdown)
    task_acks_late=True,
    worker_prefetch_multiplier=1,       # 1 task at a time per worker slot
    # Max 2 concurrent document jobs to stay inside 8 GB RAM budget
    worker_concurrency=int(os.getenv("KOS_CELERY_CONCURRENCY", "2")),
    # Soft/hard time limits (seconds)
    task_soft_time_limit=600,           # 10 min — warn
    task_time_limit=900,                # 15 min — kill
)
