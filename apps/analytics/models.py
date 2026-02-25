"""Django models for the analytics application."""

from django.db import models


class ScheduledComputation(models.Model):
    """
    Registry of analytics computations run on a schedule.
    One row per computation type — seeded via data migration.
    The beat schedule is defined in config/celery.py; this model controls
    enable/disable and provides monitoring visibility.
    """

    SCHEDULE_CHOICES = [
        ("hourly",   "Hourly"),
        ("every_6h", "Every 6 Hours"),
        ("daily",    "Daily"),
        ("weekly",   "Weekly"),
    ]

    STATUS_CHOICES = [
        ("success", "Success"),
        ("failed",  "Failed"),
        ("running", "Running"),
        ("never",   "Never Run"),
    ]

    name        = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    task_path   = models.CharField(
        max_length=255,
        unique=True,
        help_text="Dotted Celery task path, e.g. src.analytics.tasks.compute_flow_percentile_bands",
    )
    schedule    = models.CharField(max_length=20, choices=SCHEDULE_CHOICES)
    is_enabled  = models.BooleanField(default=True)

    # Denormalized for quick dashboard/admin display — updated by each task run
    last_run_at     = models.DateTimeField(null=True, blank=True)
    last_run_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="never")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "scheduled_computations"
        ordering = ["name"]

    def __str__(self):
        return self.name


class ComputationLog(models.Model):
    """Execution history for scheduled analytics computations."""

    STATUS_CHOICES = [
        ("running", "Running"),
        ("success", "Success"),
        ("failed",  "Failed"),
    ]

    computation = models.ForeignKey(
        ScheduledComputation,
        on_delete=models.CASCADE,
        related_name="logs",
        db_index=True,
    )

    # Execution
    status           = models.CharField(max_length=20, choices=STATUS_CHOICES)
    celery_task_id   = models.CharField(max_length=255, blank=True, db_index=True)
    started_at       = models.DateTimeField(db_index=True)
    completed_at     = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    # Results
    records_computed = models.IntegerField(null=True, blank=True)
    error_message    = models.TextField(blank=True)

    class Meta:
        db_table = "computation_logs"
        indexes = [
            models.Index(fields=["computation", "started_at"], name="idx_comp_log_comp_started"),
            models.Index(fields=["status"],                    name="idx_comp_log_status"),
        ]
        ordering = ["-started_at"]

    def __str__(self):
        return f"{self.computation.name} – {self.status} – {self.started_at}"
