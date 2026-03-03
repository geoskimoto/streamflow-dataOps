"""Scheduled analytics computation tasks."""

import logging
from datetime import date, datetime, timedelta, timezone

from celery import shared_task

from apps.analytics.models import ComputationLog, ScheduledComputation
from apps.streamflow.models import DailyFlowPercentile
from src.analytics.percentiles import compute_percentile_for_date

logger = logging.getLogger(__name__)

TASK_PATH = "src.analytics.tasks.compute_daily_flow_percentiles"

# How many rows to pass to bulk_create at once
_INSERT_BATCH = 5_000


@shared_task(bind=True, max_retries=3)
def compute_daily_flow_percentiles(self, target_date_iso: str | None = None):
    """
    Compute and upsert exceedance percentile bands for all stations that have
    a daily_mean observation on ``target_date`` (defaults to yesterday UTC).

    Runs daily via Celery beat. Checks the ScheduledComputation registry for
    the is_enabled flag before doing any work.

    Args:
        target_date_iso: ISO date string (YYYY-MM-DD). Defaults to yesterday.
    """
    if target_date_iso is None:
        target_date = date.today() - timedelta(days=1)
    else:
        target_date = date.fromisoformat(target_date_iso)

    try:
        computation = ScheduledComputation.objects.get(task_path=TASK_PATH)
    except ScheduledComputation.DoesNotExist:
        logger.error(
            "ScheduledComputation record not found for %s. "
            "Run migrations to seed it.",
            TASK_PATH,
        )
        return {"status": "error", "detail": "ScheduledComputation record missing"}

    if not computation.is_enabled:
        logger.info("'%s' is disabled — skipping", computation.name)
        return {"status": "skipped"}

    started_at = datetime.now(timezone.utc)
    log = ComputationLog.objects.create(
        computation=computation,
        status="running",
        started_at=started_at,
        celery_task_id=self.request.id or "",
    )

    try:
        rows = compute_percentile_for_date(target_date)
        computed_at = datetime.now(timezone.utc)

        records = [
            DailyFlowPercentile(
                station_id=row["station_id"],
                date=row["observation_date"],
                discharge=row["discharge"],
                percentile_rank=row["percentile_rank"],
                band=row["band"],
                historical_record_count=row["historical_record_count"],
                computed_at=computed_at,
            )
            for row in rows
        ]

        # Upsert — safe to re-run for the same date
        for i in range(0, len(records), _INSERT_BATCH):
            DailyFlowPercentile.objects.bulk_create(
                records[i: i + _INSERT_BATCH],
                update_conflicts=True,
                unique_fields=["station", "date"],
                update_fields=[
                    "discharge",
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
            "'%s' complete: %d stations for %s in %.1fs",
            computation.name, len(records), target_date, duration,
        )
        return {
            "status": "success",
            "target_date": target_date.isoformat(),
            "stations_computed": len(records),
            "duration_seconds": duration,
        }

    except Exception as exc:
        completed_at = datetime.now(timezone.utc)
        log.status = "failed"
        log.error_message = str(exc)
        log.completed_at = completed_at
        log.duration_seconds = (completed_at - started_at).total_seconds()
        log.save()

        computation.last_run_status = "failed"
        computation.save(update_fields=["last_run_status"])

        logger.error("'%s' failed: %s", computation.name, exc)
        raise
