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
    # NOAA NOMADS RTMA - Hourly at 5 minutes past the hour
    'fetch-rtma-hourly': {
        'task': 'src.acquisition.raster_tasks.scheduled_raster_pulls',
        'schedule': crontab(minute=5),  # Every hour at :05
        'kwargs': {
            'data_source': 'nomads',
            'dataset_name': 'NOAA_RTMA'
        }
    },
    
    # NASA SMAP Soil Moisture - Daily at 3 AM UTC
    'fetch-smap-daily': {
        'task': 'src.acquisition.raster_tasks.scheduled_raster_pulls',
        'schedule': crontab(hour=3, minute=0),
        'kwargs': {
            'data_source': 'earthdata',
            'dataset_name': 'NASA_SMAP_L4'
        }
    },
    
    # MODIS LST Terra - Daily at 4 AM UTC
    'fetch-modis-terra-daily': {
        'task': 'src.acquisition.raster_tasks.scheduled_raster_pulls',
        'schedule': crontab(hour=4, minute=0),
        'kwargs': {
            'data_source': 'earthdata',
            'dataset_name': 'MODIS_LST_Terra'
        }
    },
    
    # MODIS LST Aqua - Daily at 4:30 AM UTC
    'fetch-modis-aqua-daily': {
        'task': 'src.acquisition.raster_tasks.scheduled_raster_pulls',
        'schedule': crontab(hour=4, minute=30),
        'kwargs': {
            'data_source': 'earthdata',
            'dataset_name': 'MODIS_LST_Aqua'
        }
    },
    
    # GPM Precipitation - Daily at 5 AM UTC
    'fetch-gpm-daily': {
        'task': 'src.acquisition.raster_tasks.scheduled_raster_pulls',
        'schedule': crontab(hour=5, minute=0),
        'kwargs': {
            'data_source': 'earthdata',
            'dataset_name': 'NASA_GPM_IMERG'
        }
    },
    
    # Data retention cleanup - Remove old RTMA data (>7 days)
    'cleanup-rtma-weekly': {
        'task': 'src.acquisition.raster_tasks.cleanup_old_layers',
        'schedule': crontab(minute=0, hour=2, day_of_week=0),  # Sunday 2 AM
        'kwargs': {
            'dataset_name': 'NOAA_RTMA',
            'retention_days': 7,
            'dry_run': False
        }
    },
    
    # Cleanup old raster data (>30 days for NASA datasets)
    'cleanup-earthdata-monthly': {
        'task': 'src.acquisition.raster_tasks.cleanup_old_layers',
        'schedule': crontab(minute=0, hour=3, day_of_month=1),  # 1st of month at 3 AM
        'kwargs': {
            'data_source': 'earthdata',
            'retention_days': 30,
            'dry_run': False
        }
    },
    
    # Health check - Monitor pull status and send alerts
    'monitor-pull-health': {
        'task': 'src.acquisition.raster_tasks.monitor_pull_health',
        'schedule': crontab(minute=0, hour='*/6'),  # Every 6 hours
    },
    
    # Database cleanup - Remove old pull logs (>90 days)
    'cleanup-pull-logs': {
        'task': 'src.acquisition.raster_tasks.cleanup_old_pull_logs',
        'schedule': crontab(minute=0, hour=1, day_of_week=0),  # Sunday 1 AM
        'kwargs': {'retention_days': 90}
    },
}


@app.task(bind=True)
def debug_task(self):
    """Debug task for testing Celery."""
    print(f"Request: {self.request!r}")
