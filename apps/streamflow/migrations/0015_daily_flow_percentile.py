"""
Replace the single-row-per-station flow_percentile_bands table with a
time-series daily_flow_percentiles table (one row per station per date).
"""

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("streamflow", "0014_add_flow_percentile_band"),
    ]

    operations = [
        # 1. Create the new time-series table
        migrations.CreateModel(
            name="DailyFlowPercentile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("station", models.ForeignKey(
                    db_index=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="daily_percentiles",
                    to="streamflow.station",
                )),
                ("date", models.DateField(db_index=True, help_text="Observation date")),
                ("discharge", models.DecimalField(decimal_places=4, max_digits=20)),
                ("percentile_rank", models.DecimalField(
                    decimal_places=2,
                    max_digits=5,
                    help_text="0–100; computed against full period of record",
                )),
                ("band", models.CharField(
                    max_length=10,
                    choices=[
                        ("p0_4",    "Very Low (0–4th percentile)"),
                        ("p5_10",   "Low (5th–10th percentile)"),
                        ("p11_25",  "Below Normal (11th–25th percentile)"),
                        ("p26_50",  "Normal (26th–50th percentile)"),
                        ("p51_75",  "Above Normal (51st–75th percentile)"),
                        ("p76_100", "High (76th–100th percentile)"),
                    ],
                )),
                ("historical_record_count", models.IntegerField(
                    help_text="Total daily_mean records used in the percentile computation"
                )),
                ("computed_at", models.DateTimeField(help_text="When this row was computed")),
            ],
            options={"db_table": "daily_flow_percentiles", "ordering": ["-date"]},
        ),
        migrations.AddConstraint(
            model_name="dailyflowpercentile",
            constraint=models.UniqueConstraint(
                fields=["station", "date"],
                name="unique_daily_flow_percentile",
            ),
        ),
        migrations.AddIndex(
            model_name="dailyflowpercentile",
            index=models.Index(fields=["date"], name="idx_daily_pct_date"),
        ),
        migrations.AddIndex(
            model_name="dailyflowpercentile",
            index=models.Index(fields=["band", "date"], name="idx_daily_pct_band_date"),
        ),

        # 2. Drop the old single-row-per-station cache
        migrations.DeleteModel(name="FlowPercentileBand"),
    ]
