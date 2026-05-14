from django.db import migrations

TASK_PATH = "src.analytics.tasks.compute_forecast_percentile_bands"


def seed(apps, schema_editor):
    ScheduledComputation = apps.get_model("analytics", "ScheduledComputation")
    ScheduledComputation.objects.get_or_create(
        task_path=TASK_PATH,
        defaults={
            "name":        "NWRFC Forecast Percentile Bands",
            "description": (
                "Computes exceedance percentile bands for the latest NWRFC ForecastRun "
                "per station, covering the next 8 calendar days. Compares each forecasted "
                "discharge against the station's full period-of-record daily_mean observations. "
                "Results are stored in forecast_percentiles (one row per station per date per "
                "source) and served via GET /api/v1/forecasts/discharge/percentile-bands/."
            ),
            "schedule":   "every_6h",
            "is_enabled": True,
        },
    )


def unseed(apps, schema_editor):
    ScheduledComputation = apps.get_model("analytics", "ScheduledComputation")
    ScheduledComputation.objects.filter(task_path=TASK_PATH).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("analytics", "0003_replace_percentile_computation"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
