from django.db import migrations


def seed_computations(apps, schema_editor):
    ScheduledComputation = apps.get_model("analytics", "ScheduledComputation")
    ScheduledComputation.objects.get_or_create(
        task_path="src.analytics.tasks.compute_flow_percentile_bands",
        defaults={
            "name":        "Flow Percentile Bands",
            "description": (
                "Computes exceedance percentile bands for all stations with a "
                "daily_mean observation in the past 2 days. Compares current "
                "value against the full period of record. Results are stored in "
                "flow_percentile_bands and exposed via "
                "GET /api/v1/observations/discharge/percentile-bands/."
            ),
            "schedule":   "every_6h",
            "is_enabled": True,
        },
    )


def unseed_computations(apps, schema_editor):
    ScheduledComputation = apps.get_model("analytics", "ScheduledComputation")
    ScheduledComputation.objects.filter(
        task_path="src.analytics.tasks.compute_flow_percentile_bands"
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("analytics", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_computations, unseed_computations),
    ]
