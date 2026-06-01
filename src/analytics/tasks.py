"""Scheduled analytics computation tasks."""

import logging
from datetime import date, datetime, timedelta, timezone

from celery import shared_task

from apps.streamflow.models import DailyFlowPercentile, ForecastPercentile
from src.analytics.percentiles import (
    compute_percentile_for_date,
    compute_forecast_percentiles,
    backfill_station_chunk,
    iter_station_id_chunks,
)

logger = logging.getLogger(__name__)

# How many rows to pass to bulk_create at once
_INSERT_BATCH = 5_000


# ---------------------------------------------------------------------------
# Statistics Configuration dispatcher and execution tasks
# ---------------------------------------------------------------------------

def _compute_stats_next_run(from_time, config):
    """Compute next run datetime for a StatisticsConfiguration using croniter."""
    from croniter import croniter
    from datetime import datetime

    schedule_type = config.schedule_type

    if schedule_type == 'daily':
        cron_expr = '0 0 * * *'
    elif schedule_type == 'weekly':
        cron_expr = '0 0 * * 0'
    elif schedule_type == 'monthly':
        cron_expr = '0 0 1 * *'
    elif schedule_type == 'annual':
        day = max(1, min(31, config.annual_run_day))
        month = max(1, min(12, config.annual_run_month))
        cron_expr = f'0 0 {day} {month} *'
    elif schedule_type == 'custom':
        if not config.schedule_value:
            raise ValueError(f'StatisticsConfiguration {config.id} has custom schedule but no schedule_value')
        cron_expr = config.schedule_value
    else:
        raise ValueError(f'Unknown schedule_type: {schedule_type!r}')

    # Strip tzinfo so croniter always returns a naive datetime for consistent comparison
    naive_from = from_time.replace(tzinfo=None) if hasattr(from_time, "tzinfo") and from_time.tzinfo is not None else from_time
    it = croniter(cron_expr, naive_from)
    return it.get_next(datetime)


@shared_task
def dispatch_statistics_computations():
    """Hourly dispatcher: fires StatisticsConfiguration tasks that are due."""
    from apps.analytics.models import StatisticsConfiguration, StatisticsComputationLog
    from django.utils import timezone

    now = timezone.now()
    configs = StatisticsConfiguration.objects.filter(is_enabled=True)
    dispatched = skipped = 0

    for config in configs:
        # Skip if not yet due
        if config.next_run_at is not None and config.next_run_at > now:
            skipped += 1
            continue

        # Skip if a run is already in progress
        if config.logs.filter(status='running').exists():
            logger.debug('Skipping config %s: already running', config.id)
            skipped += 1
            continue

        if config.computation_type == 'station_metadata':
            run_station_metadata_task.delay(config.id)
        elif config.computation_type == 'flood_thresholds':
            run_flood_thresholds_task.delay(config.id)
        elif config.computation_type == 'daily_flow_percentiles':
            run_daily_flow_percentiles_task.delay(config.id)
        elif config.computation_type == 'forecast_percentiles':
            run_forecast_percentiles_task.delay(config.id)
        elif config.computation_type == 'percentile_backfill':
            run_percentile_backfill_task.delay(config.id)
        else:
            logger.warning('Unknown computation_type %r for config %s', config.computation_type, config.id)
            skipped += 1
            continue

        dispatched += 1
        next_run = _compute_stats_next_run(now, config)
        StatisticsConfiguration.objects.filter(id=config.id).update(next_run_at=next_run)
        logger.info('Dispatched statistics config %s (%s), next_run_at=%s', config.id, config.name, next_run)

    logger.info('dispatch_statistics_computations: dispatched=%d, skipped=%d', dispatched, skipped)
    return {'dispatched': dispatched, 'skipped': skipped}


@shared_task
def run_station_metadata_task(config_id):
    """Compute and store StationMetadata for all stations in a StatisticsConfiguration."""
    from apps.analytics.models import StatisticsConfiguration, StatisticsComputationLog
    from src.analytics.station_metadata import compute_station_metadata
    from django.utils import timezone
    import time

    config = StatisticsConfiguration.objects.get(id=config_id)
    station_ids = list(config.get_station_queryset().values_list('id', flat=True))

    log = StatisticsComputationLog.objects.create(
        configuration=config,
        status='running',
        started_at=timezone.now(),
        celery_task_id=run_station_metadata_task.request.id or '',
    )

    start_time = time.monotonic()
    try:
        count = compute_station_metadata(station_ids=station_ids)
        duration = time.monotonic() - start_time
        log.status = 'success'
        log.stations_processed = len(station_ids)
        log.records_computed = count
        log.duration_seconds = round(duration, 2)
        log.completed_at = timezone.now()
        log.save()
        StatisticsConfiguration.objects.filter(id=config_id).update(last_run_at=timezone.now())
        logger.info('run_station_metadata_task: config=%s upserted=%d in %.1fs', config_id, count, duration)
        return {'status': 'success', 'upserted': count}
    except Exception as exc:
        duration = time.monotonic() - start_time
        log.status = 'failed'
        log.error_message = str(exc)
        log.duration_seconds = round(duration, 2)
        log.completed_at = timezone.now()
        log.save()
        logger.error('run_station_metadata_task failed for config %s: %s', config_id, exc)
        raise


@shared_task
def run_flood_thresholds_task(config_id):
    """Fetch NOAA NWPS flood thresholds for all stations in a StatisticsConfiguration."""
    from apps.analytics.models import StatisticsConfiguration, StatisticsComputationLog
    from src.analytics.flood_thresholds import fetch_flood_thresholds_for_stations
    from django.utils import timezone
    import time

    config = StatisticsConfiguration.objects.get(id=config_id)
    station_ids = list(config.get_station_queryset().values_list('id', flat=True))

    log = StatisticsComputationLog.objects.create(
        configuration=config,
        status='running',
        started_at=timezone.now(),
        celery_task_id=run_flood_thresholds_task.request.id or '',
    )

    start_time = time.monotonic()
    try:
        result = fetch_flood_thresholds_for_stations(station_ids)
        duration = time.monotonic() - start_time
        log.status = 'success' if result['errors'] == 0 else 'partial'
        log.stations_processed = len(station_ids)
        log.records_computed = result['updated']
        log.duration_seconds = round(duration, 2)
        log.completed_at = timezone.now()
        if result['errors']:
            log.error_message = f"{result['errors']} API errors; {result['skipped']} skipped (no HADS LID)"
        log.save()
        StatisticsConfiguration.objects.filter(id=config_id).update(last_run_at=timezone.now())
        return {'status': log.status, **result}
    except Exception as exc:
        duration = time.monotonic() - start_time
        log.status = 'failed'
        log.error_message = str(exc)
        log.duration_seconds = round(duration, 2)
        log.completed_at = timezone.now()
        log.save()
        logger.error('run_flood_thresholds_task failed for config %s: %s', config_id, exc)
        raise


@shared_task
def run_daily_flow_percentiles_task(config_id):
    """Compute and upsert DailyFlowPercentile for the past two days for all stations in a StatisticsConfiguration.

    Computes both today-1 and today-2 on every run. USGS daily_mean values arrive
    with variable latency (often 12-36 hours), so recomputing today-2 catches stations
    whose observations weren't yet available on the previous day's run.
    """
    from apps.analytics.models import StatisticsConfiguration, StatisticsComputationLog
    from django.utils import timezone as dj_timezone
    import time

    config = StatisticsConfiguration.objects.get(id=config_id)
    station_ids = list(config.get_station_queryset().values_list('id', flat=True))
    today = date.today()
    target_dates = [today - timedelta(days=1), today - timedelta(days=2)]

    log = StatisticsComputationLog.objects.create(
        configuration=config,
        status='running',
        started_at=dj_timezone.now(),
        celery_task_id=run_daily_flow_percentiles_task.request.id or '',
    )

    start_time = time.monotonic()
    total_records = 0
    total_stations: set = set()
    try:
        computed_at = datetime.now(timezone.utc)
        for target_date in target_dates:
            rows = compute_percentile_for_date(target_date, station_ids=station_ids)
            records = [
                DailyFlowPercentile(
                    station_id=row['station_id'],
                    date=row['observation_date'],
                    discharge=row['discharge'],
                    percentile_rank=row['percentile_rank'],
                    band=row['band'],
                    historical_record_count=row['historical_record_count'],
                    computed_at=computed_at,
                )
                for row in rows
            ]
            for i in range(0, len(records), _INSERT_BATCH):
                DailyFlowPercentile.objects.bulk_create(
                    records[i: i + _INSERT_BATCH],
                    update_conflicts=True,
                    unique_fields=['station', 'date'],
                    update_fields=['discharge', 'percentile_rank', 'band', 'historical_record_count', 'computed_at'],
                )
            total_records += len(records)
            total_stations.update(r['station_id'] for r in rows)
            logger.info(
                'run_daily_flow_percentiles_task: config=%s date=%s stations=%d',
                config_id, target_date, len(records),
            )

        duration = time.monotonic() - start_time
        log.status = 'success'
        log.stations_processed = len(total_stations)
        log.records_computed = total_records
        log.duration_seconds = round(duration, 2)
        log.completed_at = dj_timezone.now()
        log.save()
        StatisticsConfiguration.objects.filter(id=config_id).update(last_run_at=dj_timezone.now())
        logger.info(
            'run_daily_flow_percentiles_task: config=%s COMPLETE dates=%s total_stations=%d total_records=%d in %.1fs',
            config_id, [d.isoformat() for d in target_dates], len(total_stations), total_records, duration,
        )
        return {'status': 'success', 'target_dates': [d.isoformat() for d in target_dates], 'stations': len(total_stations)}

    except Exception as exc:
        duration = time.monotonic() - start_time
        log.status = 'failed'
        log.error_message = str(exc)
        log.duration_seconds = round(duration, 2)
        log.completed_at = dj_timezone.now()
        log.save()
        logger.error('run_daily_flow_percentiles_task failed for config %s: %s', config_id, exc)
        raise


@shared_task
def run_forecast_percentiles_task(config_id):
    """Compute and upsert ForecastPercentile for NWRFC forecasts for all stations in a StatisticsConfiguration."""
    from apps.analytics.models import StatisticsConfiguration, StatisticsComputationLog
    from django.utils import timezone as dj_timezone
    import time

    config = StatisticsConfiguration.objects.get(id=config_id)
    station_ids = list(config.get_station_queryset().values_list('id', flat=True))

    log = StatisticsComputationLog.objects.create(
        configuration=config,
        status='running',
        started_at=dj_timezone.now(),
        celery_task_id=run_forecast_percentiles_task.request.id or '',
    )

    start_time = time.monotonic()
    try:
        rows = compute_forecast_percentiles(source='NWRFC', max_days=8, station_ids=station_ids)
        computed_at = datetime.now(timezone.utc)

        records = [
            ForecastPercentile(
                station_id=row['station_id'],
                target_date=row['target_date'],
                source=row['source'],
                forecast_run_date=row['forecast_run_date'],
                forecast_discharge=row['forecast_discharge'],
                percentile_rank=row['percentile_rank'],
                band=row['band'],
                historical_record_count=row['historical_record_count'],
                computed_at=computed_at,
            )
            for row in rows
        ]

        for i in range(0, len(records), _INSERT_BATCH):
            ForecastPercentile.objects.bulk_create(
                records[i: i + _INSERT_BATCH],
                update_conflicts=True,
                unique_fields=['station', 'target_date', 'source'],
                update_fields=[
                    'forecast_run_date', 'forecast_discharge', 'percentile_rank',
                    'band', 'historical_record_count', 'computed_at',
                ],
            )

        duration = time.monotonic() - start_time
        unique_stations = len({r['station_id'] for r in rows})
        log.status = 'success'
        log.stations_processed = unique_stations
        log.records_computed = len(records)
        log.duration_seconds = round(duration, 2)
        log.completed_at = dj_timezone.now()
        log.save()
        StatisticsConfiguration.objects.filter(id=config_id).update(last_run_at=dj_timezone.now())
        logger.info(
            'run_forecast_percentiles_task: config=%s rows=%d stations=%d in %.1fs',
            config_id, len(records), unique_stations, duration,
        )
        return {'status': 'success', 'rows': len(records), 'stations': unique_stations}

    except Exception as exc:
        duration = time.monotonic() - start_time
        log.status = 'failed'
        log.error_message = str(exc)
        log.duration_seconds = round(duration, 2)
        log.completed_at = dj_timezone.now()
        log.save()
        logger.error('run_forecast_percentiles_task failed for config %s: %s', config_id, exc)
        raise


@shared_task
def run_percentile_backfill_task(config_id):
    """
    Backfill DailyFlowPercentile for ALL historical daily_mean observations
    for all stations in a StatisticsConfiguration.

    Long-running (30-90 min for full station set). Uses chunked SQL.
    Safe to re-run — uses upsert semantics.
    """
    from apps.analytics.models import StatisticsConfiguration, StatisticsComputationLog
    from django.utils import timezone as dj_timezone
    import time

    config = StatisticsConfiguration.objects.get(id=config_id)
    station_ids = list(config.get_station_queryset().values_list('id', flat=True))

    log = StatisticsComputationLog.objects.create(
        configuration=config,
        status='running',
        started_at=dj_timezone.now(),
        celery_task_id=run_percentile_backfill_task.request.id or '',
    )

    start_time = time.monotonic()
    total_records = 0
    total_stations = 0

    try:
        computed_at = datetime.now(timezone.utc)
        for chunk in iter_station_id_chunks(chunk_size=100, station_ids=station_ids):
            rows = backfill_station_chunk(chunk, computed_at)
            records = [
                DailyFlowPercentile(
                    station_id=row['station_id'],
                    date=row['obs_date'],
                    discharge=row['discharge'],
                    percentile_rank=row['percentile_rank'],
                    band=row['band'],
                    historical_record_count=row['historical_record_count'],
                    computed_at=row['computed_at'],
                )
                for row in rows
            ]
            for i in range(0, len(records), _INSERT_BATCH):
                DailyFlowPercentile.objects.bulk_create(
                    records[i: i + _INSERT_BATCH],
                    update_conflicts=True,
                    unique_fields=['station', 'date'],
                    update_fields=['discharge', 'percentile_rank', 'band', 'historical_record_count', 'computed_at'],
                )
            total_records += len(records)
            total_stations += len(chunk)
            logger.info(
                'run_percentile_backfill_task: config=%s chunk=%d stations upserted=%d total_so_far=%d',
                config_id, len(chunk), len(records), total_records,
            )

        duration = time.monotonic() - start_time
        log.status = 'success'
        log.stations_processed = total_stations
        log.records_computed = total_records
        log.duration_seconds = round(duration, 2)
        log.completed_at = dj_timezone.now()
        log.save()
        StatisticsConfiguration.objects.filter(id=config_id).update(last_run_at=dj_timezone.now())
        logger.info(
            'run_percentile_backfill_task: config=%s COMPLETE stations=%d records=%d in %.1fs',
            config_id, total_stations, total_records, duration,
        )
        return {'status': 'success', 'stations': total_stations, 'records': total_records}

    except Exception as exc:
        duration = time.monotonic() - start_time
        log.status = 'failed'
        log.error_message = str(exc)
        log.duration_seconds = round(duration, 2)
        log.completed_at = dj_timezone.now()
        log.save()
        logger.error('run_percentile_backfill_task failed for config %s: %s', config_id, exc)
        raise


# ---------------------------------------------------------------------------
# Station activity sync (runs daily via Celery beat)
# ---------------------------------------------------------------------------

@shared_task
def sync_station_activity_task(months_back: int = 6):
    """
    Update Station.is_active for every station based on whether it has a
    discharge observation within the last ``months_back`` months.

    Uses the (station_id, observed_at, type) composite index — typically
    completes in a few seconds regardless of total station count.
    """
    from django.db import connection
    import time

    start = time.monotonic()
    with connection.cursor() as cursor:
        cursor.execute("""
            UPDATE stations s
            SET is_active = EXISTS (
                SELECT 1 FROM discharge_observations o
                WHERE o.station_id = s.id
                  AND o.observed_at >= NOW() - INTERVAL %(months)s
            )
        """, {"months": f"{months_back} months"})
        updated = cursor.rowcount

    duration = time.monotonic() - start
    logger.info(
        "sync_station_activity_task: updated %d stations in %.1fs (months_back=%d)",
        updated, duration, months_back,
    )
    return {"updated": updated, "duration_seconds": round(duration, 2)}
