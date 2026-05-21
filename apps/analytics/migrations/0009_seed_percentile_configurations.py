from django.db import migrations
from django.utils import timezone


STANDARD_CONFIGS = [
    {
        'name': 'Daily Observed Percentiles — USGS',
        'description': (
            'Computes exceedance percentile bands for all USGS stations that have a daily_mean '
            'observation for the previous day. Runs 3× daily to capture late-arriving provisional '
            'values. Upsert semantics make re-runs safe.'
        ),
        'computation_type': 'daily_flow_percentiles',
        'agency_filter': 'USGS',
        'schedule_type': 'custom',
        'schedule_value': '0 6,12,18 * * *',
        'is_enabled': True,
    },
    {
        'name': 'Daily Observed Percentiles — EC',
        'description': (
            'Computes exceedance percentile bands for all Environment Canada stations that have a '
            'daily_mean observation for the previous day. Runs 3× daily.'
        ),
        'computation_type': 'daily_flow_percentiles',
        'agency_filter': 'EC',
        'schedule_type': 'custom',
        'schedule_value': '0 6,12,18 * * *',
        'is_enabled': True,
    },
    {
        'name': 'Forecast Percentiles — NWRFC',
        'description': (
            'Computes exceedance percentile bands for NOAA NWRFC 8-day forecasts. Maps NOAA_RFC '
            'stations to USGS stations via StationMapping and compares forecast discharges against '
            'each station\'s full period-of-record daily_mean observations. Runs every 6 hours to '
            'stay current with NWRFC issuance cycles.'
        ),
        'computation_type': 'forecast_percentiles',
        'agency_filter': 'ALL',
        'schedule_type': 'custom',
        'schedule_value': '0 0,6,12,18 * * *',
        'is_enabled': True,
    },
    {
        'name': 'Historical Backfill — USGS',
        'description': (
            'One-time (or as-needed) backfill of DailyFlowPercentile for all USGS stations using '
            'all available daily_mean discharge observations. Chunked in groups of 100 stations to '
            'avoid memory exhaustion. Can take 30–90 minutes for the full station set. '
            'Disabled by default — enable and trigger manually when needed.'
        ),
        'computation_type': 'percentile_backfill',
        'agency_filter': 'USGS',
        'schedule_type': 'custom',
        'schedule_value': '0 0 1 1 *',
        'is_enabled': False,
    },
    {
        'name': 'Historical Backfill — EC',
        'description': (
            'One-time (or as-needed) backfill of DailyFlowPercentile for all Environment Canada '
            'stations using all available daily_mean discharge observations. Chunked in groups of '
            '100 stations. Disabled by default — enable and trigger manually when needed.'
        ),
        'computation_type': 'percentile_backfill',
        'agency_filter': 'EC',
        'schedule_type': 'custom',
        'schedule_value': '0 0 1 1 *',
        'is_enabled': False,
    },
]

OLD_BEAT_TASK_NAMES = [
    'compute-daily-flow-percentiles',
    'compute-forecast-percentile-bands',
]


def seed_configurations(apps, schema_editor):
    StatisticsConfiguration = apps.get_model('analytics', 'StatisticsConfiguration')
    for cfg in STANDARD_CONFIGS:
        StatisticsConfiguration.objects.get_or_create(
            name=cfg['name'],
            defaults={k: v for k, v in cfg.items() if k != 'name'},
        )


def remove_old_periodic_tasks(apps, schema_editor):
    try:
        PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')
        deleted, _ = PeriodicTask.objects.filter(name__in=OLD_BEAT_TASK_NAMES).delete()
        if deleted:
            print(f'\n  Removed {deleted} orphaned Celery Beat periodic task(s): {OLD_BEAT_TASK_NAMES}')
    except LookupError:
        # django_celery_beat not installed or tables not created — skip silently
        pass


def reverse_seed(apps, schema_editor):
    StatisticsConfiguration = apps.get_model('analytics', 'StatisticsConfiguration')
    StatisticsConfiguration.objects.filter(
        name__in=[cfg['name'] for cfg in STANDARD_CONFIGS]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('analytics', '0008_remove_scheduled_computation'),
    ]

    operations = [
        migrations.RunPython(seed_configurations, reverse_code=reverse_seed),
        migrations.RunPython(remove_old_periodic_tasks, reverse_code=migrations.RunPython.noop),
    ]
