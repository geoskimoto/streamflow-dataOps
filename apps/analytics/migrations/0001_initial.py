from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="ScheduledComputation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=100, unique=True)),
                ("description", models.TextField(blank=True)),
                ("task_path", models.CharField(
                    max_length=255,
                    unique=True,
                    help_text="Dotted Celery task path",
                )),
                ("schedule", models.CharField(
                    max_length=20,
                    choices=[
                        ("hourly",   "Hourly"),
                        ("every_6h", "Every 6 Hours"),
                        ("daily",    "Daily"),
                        ("weekly",   "Weekly"),
                    ],
                )),
                ("is_enabled", models.BooleanField(default=True)),
                ("last_run_at",     models.DateTimeField(null=True, blank=True)),
                ("last_run_status", models.CharField(
                    max_length=20,
                    choices=[
                        ("success", "Success"),
                        ("failed",  "Failed"),
                        ("running", "Running"),
                        ("never",   "Never Run"),
                    ],
                    default="never",
                )),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "scheduled_computations", "ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="ComputationLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("computation", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="logs",
                    to="analytics.scheduledcomputation",
                    db_index=True,
                )),
                ("status", models.CharField(
                    max_length=20,
                    choices=[
                        ("running", "Running"),
                        ("success", "Success"),
                        ("failed",  "Failed"),
                    ],
                )),
                ("celery_task_id",   models.CharField(max_length=255, blank=True, db_index=True)),
                ("started_at",       models.DateTimeField(db_index=True)),
                ("completed_at",     models.DateTimeField(null=True, blank=True)),
                ("duration_seconds", models.DecimalField(decimal_places=2, max_digits=10, null=True, blank=True)),
                ("records_computed", models.IntegerField(null=True, blank=True)),
                ("error_message",    models.TextField(blank=True)),
            ],
            options={
                "db_table": "computation_logs",
                "ordering": ["-started_at"],
            },
        ),
        migrations.AddIndex(
            model_name="computationlog",
            index=models.Index(
                fields=["computation", "started_at"],
                name="idx_comp_log_comp_started",
            ),
        ),
        migrations.AddIndex(
            model_name="computationlog",
            index=models.Index(fields=["status"], name="idx_comp_log_status"),
        ),
    ]
