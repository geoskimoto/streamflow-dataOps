from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("streamflow", "0013_add_ec_realtime_daily_data_type"),
    ]

    operations = [
        migrations.CreateModel(
            name="FlowPercentileBand",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("station", models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="percentile_band",
                    to="streamflow.station",
                )),
                ("current_discharge", models.DecimalField(decimal_places=4, max_digits=20)),
                ("observation_date", models.DateField(
                    help_text="Date of current_discharge observation"
                )),
                ("percentile_rank", models.DecimalField(
                    decimal_places=2,
                    max_digits=5,
                    help_text="0–100; computed against full period of record",
                )),
                ("band", models.CharField(
                    choices=[
                        ("p0_4",    "Very Low (0–4th percentile)"),
                        ("p5_10",   "Low (5th–10th percentile)"),
                        ("p11_25",  "Below Normal (11th–25th percentile)"),
                        ("p26_50",  "Normal (26th–50th percentile)"),
                        ("p51_75",  "Above Normal (51st–75th percentile)"),
                        ("p76_100", "High (76th–100th percentile)"),
                    ],
                    max_length=10,
                )),
                ("historical_record_count", models.IntegerField(
                    help_text="Number of daily_mean records used in the percentile computation"
                )),
                ("computed_at", models.DateTimeField(
                    help_text="When this row was last computed"
                )),
            ],
            options={"db_table": "flow_percentile_bands", "ordering": []},
        ),
        migrations.AddIndex(
            model_name="flowpercentileband",
            index=models.Index(fields=["band"], name="idx_percentile_band"),
        ),
        migrations.AddIndex(
            model_name="flowpercentileband",
            index=models.Index(fields=["computed_at"], name="idx_percentile_computed_at"),
        ),
    ]
