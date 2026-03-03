"""
Replace the 'Flow Percentile Bands' scheduled computation (every-6h, single
current-day cache) with 'Daily Flow Percentiles' (daily, time-series append).
"""

from django.db import migrations


def upgrade(apps, schema_editor):
    ScheduledComputation = apps.get_model("analytics", "ScheduledComputation")

    # Remove old 6-hourly cache task
    ScheduledComputation.objects.filter(
        task_path="src.analytics.tasks.compute_flow_percentile_bands"
    ).delete()

    # Register new daily append task
    ScheduledComputation.objects.get_or_create(
        task_path="src.analytics.tasks.compute_daily_flow_percentiles",
        defaults={
            "name":        "Daily Flow Percentiles",
            "description": (
                "Appends yesterday's exceedance percentile bands for all stations "
                "with a daily_mean observation on that date. Compares each value "
                "against the station's full period of record. Results are stored "
                "in daily_flow_percentiles (one row per station per date) and "
                "served via GET /api/v1/observations/discharge/percentile-bands/"
                "?date=YYYY-MM-DD."
            ),
            "schedule":   "daily",
            "is_enabled": True,
        },
    )


def downgrade(apps, schema_editor):
    ScheduledComputation = apps.get_model("analytics", "ScheduledComputation")

    ScheduledComputation.objects.filter(
        task_path="src.analytics.tasks.compute_daily_flow_percentiles"
    ).delete()

    ScheduledComputation.objects.get_or_create(
        task_path="src.analytics.tasks.compute_flow_percentile_bands",
        defaults={
            "name":        "Flow Percentile Bands",
            "description": "Legacy 6-hourly current-day cache (archived).",
            "schedule":    "every_6h",
            "is_enabled":  False,
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ("analytics", "0002_seed_scheduled_computations"),
    ]

    operations = [
        migrations.RunPython(upgrade, downgrade),
    ]
