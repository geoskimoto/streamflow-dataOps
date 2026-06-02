"""NWMIngestionLog — tracks daily NWM forcing ingestion runs."""
from django.db import models


class NWMIngestionLog(models.Model):
    STATUS_CHOICES = [
        ("success", "Success"),
        ("partial", "Partial"),
        ("failed", "Failed"),
    ]

    ingest_date = models.DateField(unique=True)
    stations_updated = models.IntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    error_message = models.TextField(default="", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "nwm_ingestion_log"
        ordering = ["-ingest_date"]

    def __str__(self) -> str:
        return f"NWM ingest {self.ingest_date} — {self.status} ({self.stations_updated} stations)"
