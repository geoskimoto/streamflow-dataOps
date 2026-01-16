"""Celery application configuration."""

from celery import Celery
from celery.schedules import crontab
from src.config import settings

app = Celery("streamflow_acquisition")

# Configure Celery
app.conf.update(
    broker_url=settings.REDIS_URL,
    result_backend=settings.REDIS_URL,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 1 hour max per task
    task_soft_time_limit=3000,  # 50 minutes soft limit
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)

# Auto-discover tasks
app.autodiscover_tasks(["src.acquisition"])

# Beat schedule - will be dynamically updated by Django interface in Component 3
# This is just a placeholder for testing
app.conf.beat_schedule = {
    "test-task-every-hour": {
        "task": "src.acquisition.tasks.test_task",
        "schedule": crontab(minute=0),  # Every hour
    },
}


@app.task(bind=True)
def debug_task(self):
    """Debug task to test Celery setup."""
    print(f"Request: {self.request!r}")
