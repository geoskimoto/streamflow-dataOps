"""Celery configuration for Django."""

import os
from celery import Celery
from celery.schedules import crontab

# Set the default Django settings module
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("streamflow_dataops")

# Load task modules from all registered Django apps
app.config_from_object("django.conf:settings", namespace="CELERY")

# Auto-discover tasks in installed apps
app.autodiscover_tasks()

# Celery Beat schedule for periodic tasks
app.conf.beat_schedule = {
    # Run active raster pull configurations every 8 hours
    'pull-raster-data-scheduled': {
        'task': 'src.acquisition.raster_tasks.scheduled_raster_pulls',
        'schedule': crontab(minute=0, hour='*/8'),  # Every 8 hours at the top of the hour
    },
    # Clean up old rasters weekly
    'cleanup-old-rasters': {
        'task': 'src.acquisition.raster_tasks.cleanup_old_rasters',
        'schedule': crontab(minute=0, hour=2, day_of_week=0),  # Sunday at 2 AM
        'kwargs': {'days': 365, 'dry_run': False},
    },
}


@app.task(bind=True)
def debug_task(self):
    """Debug task for testing Celery."""
    print(f"Request: {self.request!r}")
