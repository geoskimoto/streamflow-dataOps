"""Scheduled analytics computation tasks."""

import logging
from datetime import datetime, timezone

from celery import shared_task

from apps.analytics.models import ComputationLog, ScheduledComputation
from apps.streamflow.models import FlowPercentileBand
from src.analytics.percentiles import compute_percentile_bands

logger = logging.getLogger(__name__)

TASK_PATH_PERCENTILE_BANDS = "src.analytics.tasks.compute_flow_percentile_bands"


@shared_task(bind=True, max_retries=3)
def compute_flow_percentile_bands(self):
    """
    Precompute exceedance percentile bands for all stations with a daily_mean
    observation in the past 2 days. Compares current value against the full
    period of record (no seasonal filter). Results are upserted into the
    flow_percentile_bands table.

    Runs every 6 hours via Celery beat. Checks the ScheduledComputation
    registry for the is_enabled flag before doing any work.
    """
    try:
        computation = ScheduledComputation.objects.get(task_path=TASK_PATH_PERCENTILE_BANDS)
    except ScheduledComputation.DoesNotExist:
        logger.error(
            f"ScheduledComputation record not found for {TASK_PATH_PERCENTILE_BANDS}. "
            "Run the seed migration or management command."
        )
        return {"status": "error", "detail": "ScheduledComputation record missing"}

    if not computation.is_enabled:
        logger.info(f"'{computation.name}' is disabled — skipping")
        return {"status": "skipped"}

    started_at = datetime.now(timezone.utc)
    log = ComputationLog.objects.create(
        computation=computation,
        status="running",
        started_at=started_at,
        celery_task_id=self.request.id or "",
    )

    try:
        rows = compute_percentile_bands()
        computed_at = datetime.now(timezone.utc)

        # Bulk upsert — one row per station, updated in place
        records = [
            FlowPercentileBand(
                station_id=row["station_id"],
                current_discharge=row["current_discharge"],
                observation_date=row["observation_date"],
                percentile_rank=row["percentile_rank"],
                band=row["band"],
                historical_record_count=row["historical_record_count"],
                computed_at=computed_at,
            )
            for row in rows
        ]

        FlowPercentileBand.objects.bulk_create(
            records,
            update_conflicts=True,
            unique_fields=["station"],
            update_fields=[
                "current_discharge",
                "observation_date",
                "percentile_rank",
                "band",
                "historical_record_count",
                "computed_at",
            ],
        )

        completed_at = datetime.now(timezone.utc)
        duration = (completed_at - started_at).total_seconds()

        log.status = "success"
        log.records_computed = len(records)
        log.completed_at = completed_at
        log.duration_seconds = duration
        log.save()

        computation.last_run_at = completed_at
        computation.last_run_status = "success"
        computation.save(update_fields=["last_run_at", "last_run_status"])

        logger.info(
            f"'{computation.name}' complete: {len(records)} stations "
            f"in {duration:.1f}s"
        )
        return {"status": "success", "stations_computed": len(records), "duration_seconds": duration}

    except Exception as exc:
        completed_at = datetime.now(timezone.utc)
        log.status = "failed"
        log.error_message = str(exc)
        log.completed_at = completed_at
        log.duration_seconds = (completed_at - started_at).total_seconds()
        log.save()

        computation.last_run_status = "failed"
        computation.save(update_fields=["last_run_status"])

        logger.error(f"'{computation.name}' failed: {exc}")
        raise
