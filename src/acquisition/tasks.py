"""Celery tasks for data acquisition."""

import os
import sys
import django

# Setup Django
if 'DJANGO_SETTINGS_MODULE' not in os.environ:
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    django.setup()

from celery import Task, shared_task
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import logging
import time
from typing import NamedTuple
from config.celery import app
from django.db import transaction
from apps.streamflow.models import (
    PullConfiguration,
    PullConfigurationStation,
    StationMapping,
    DataPullLog,
)
from src.acquisition.usgs_client import USGSClient
from src.acquisition.canada_client import CanadaClient
from src.acquisition.noaa_client import NOAAClient
from src.acquisition.nwrfc_web_client import NWRFCWebClient
from src.acquisition.smart_append import SmartAppendLogic
from src.acquisition.data_processor import DataProcessor

logger = logging.getLogger(__name__)


@app.task(bind=True)
def test_task(self):
    """Test task to verify Celery setup."""
    logger.info("Test task executed successfully!")
    return "Test task completed"


def _save_nwrfc_forecast_run(station_obj, rows: list[dict], run_date) -> int:
    """Create ForecastRun records from a single nwrfc_web scrape.

    Splits rows into observed (is_forecast=False) and forecast (is_forecast=True)
    and writes one ForecastRun record per category.
    Uses update_or_create keyed on (station, source, run_date, forecast_type, is_forecast).
    Returns total number of data points stored across both records.
    """
    from apps.streamflow.models import ForecastRun

    observed = [{'date': r['date'], 'value': r['value']} for r in rows if not r['is_forecast']]
    forecast = [{'date': r['date'], 'value': r['value']} for r in rows if r['is_forecast']]

    total = 0
    for is_fc, data in [(False, observed), (True, forecast)]:
        if not data:
            continue
        ForecastRun.objects.update_or_create(
            station=station_obj,
            source='nwrfc_web',
            run_date=run_date,
            forecast_type='medium',
            is_forecast=is_fc,
            defaults={'data': data},
        )
        total += len(data)

    return total


def _process_single_station(config_station, config_id, config):
    """Fetch, process, and store data for a single station.

    Designed to run inside a ThreadPoolExecutor — all objects are
    instantiated locally so there is no shared mutable state between threads.

    Returns:
        dict with keys:
            records (int): number of records inserted
            success (bool): True if the station completed without error
            error (str | None): error message if success is False
    """
    station_number = config_station.station_number
    logger.info(f"\n--- Processing station {station_number} ---")

    smart_append = SmartAppendLogic()
    processor = DataProcessor()

    try:
        start_date = smart_append.get_pull_start_date(
            config_id=config_id,
            station_number=station_number,
            config_start_date=config.pull_start_date,
        )
        end_date = datetime.now(timezone.utc)
        logger.info(f"Pulling data from {start_date} to {end_date}")

        observations = []
        agency = config.data_source

        if agency == "USGS":
            client = USGSClient()
            if config.data_type == "daily_mean":
                observations = client.get_daily_mean(
                    station_number=station_number,
                    start_date=start_date,
                    end_date=end_date,
                )
            elif config.data_type == "realtime_15min":
                observations = client.get_instantaneous(
                    station_number=station_number,
                    start_date=start_date,
                    end_date=end_date,
                )
            else:
                logger.error(f"Unknown data type: {config.data_type}")
                return {"records": 0, "success": False, "error": f"Unknown data type: {config.data_type}"}

        elif agency == "EC":
            client = CanadaClient()
            logger.info(f"EC branch: data_type={config.data_type!r}")  # DEBUG
            if config.data_type == "daily_mean":
                observations = client.get_daily_mean(
                    station_number=station_number,
                    start_date=start_date,
                    end_date=end_date,
                )
            elif config.data_type == "realtime_15min":
                observations = client.get_realtime_data(
                    station_number=station_number,
                    start_date=start_date,
                    end_date=end_date,
                )
            elif config.data_type == "ec_realtime_daily":
                observations = client.get_wateroffice_daily_mean(
                    station_number=station_number,
                    start_date=start_date,
                    end_date=end_date,
                )
            else:
                logger.error(f"Unknown data type: {config.data_type}")
                return {"records": 0, "success": False, "error": f"Unknown data type: {config.data_type}"}

        elif agency == "NOAA":
            logger.info(f"NOAA source - checking for HADS ID mapping")
            try:
                mapping = StationMapping.objects.get(usgs_site_no=station_number)
                hads_id = mapping.noaa_hads_id
                if not hads_id:
                    logger.warning(f"No NOAA HADS ID for USGS {station_number}")
                    return {"records": 0, "success": True, "error": None}
                client = NOAAClient()
                forecast_type = getattr(config, 'forecast_type', 'short')
                forecast_data = client.get_forecast(hads_id, forecast_type=forecast_type)
                if forecast_data:
                    logger.info(f"Retrieved NOAA forecast with {len(forecast_data.get('data', []))} points")
                else:
                    logger.warning(f"No forecast data available for HADS {hads_id}")
                return {"records": 0, "success": True, "error": None}
            except StationMapping.DoesNotExist:
                logger.warning(f"No StationMapping found for USGS {station_number}")
                return {"records": 0, "success": True, "error": None}

        elif agency == "NOAA_RFC":
            client = NOAAClient()
            if config.data_type == "forecast":
                logger.info(f"Fetching RFC forecast for {station_number}")
                forecast_data = client.get_rfc_forecast(station_number)
                if forecast_data:
                    from apps.streamflow.models import Station, ForecastRun
                    station_obj, _ = Station.objects.get_or_create(
                        station_number=station_number,
                        defaults={
                            'name': config_station.station_name or f"NOAA Station {station_number}",
                            'agency': 'NOAA_RFC',
                        }
                    )
                    ForecastRun.objects.create(
                        station=station_obj,
                        source='NOAA_RFC',
                        run_date=forecast_data['run_date'],
                        data=forecast_data['forecast_data'],
                        rmse=forecast_data.get('rmse')
                    )
                    records = len(forecast_data['forecast_data'])
                    logger.info(
                        f"✓ Stored forecast run with {records} data points for {station_number}"
                    )
                    return {"records": records, "success": True, "error": None}
                else:
                    logger.warning(f"No forecast data available for {station_number}")
                    return {"records": 0, "success": True, "error": None}
            else:
                logger.error(f"NOAA_RFC only supports 'forecast' data type, got: {config.data_type}")
                return {"records": 0, "success": False, "error": f"NOAA_RFC only supports 'forecast' data type, got: {config.data_type}"}

        elif agency == "nwrfc_web":
            client = NWRFCWebClient()
            rows = client.fetch_and_parse(station_number)
            if not rows:
                logger.warning(f"nwrfc_web: no data returned for {station_number}")
                return {"records": 0, "success": True, "error": None}

            from apps.streamflow.models import Station as StationModel
            station_obj, _ = StationModel.objects.get_or_create(
                station_number=station_number,
                agency='NOAA_RFC',
                defaults={
                    'name': getattr(config_station, 'station_name', None) or f"NWRFC Station {station_number}",
                }
            )
            run_date = datetime.now(timezone.utc)
            records = _save_nwrfc_forecast_run(station_obj, rows, run_date)
            logger.info(f"nwrfc_web: stored {records} data points for {station_number}")
            return {"records": records, "success": True, "error": None}

        else:
            logger.error(f"Unknown agency: {agency}")
            return {"records": 0, "success": False, "error": f"Unknown agency: {agency}"}

        logger.info(f"Fetched {len(observations)} observations")

        inserted_count = 0
        if observations:
            inserted_count = processor.process_observations(
                station_number=station_number, observations=observations
            )
            logger.info(f"Inserted {inserted_count} records")
            if inserted_count > 0:
                latest_date = max(obs["observed_at"] for obs in observations)
                smart_append.update_pull_progress(
                    config_id=config_id,
                    station_number=station_number,
                    successful_pull_date=latest_date,
                )

        logger.info(f"✓ Successfully processed station {station_number}")
        return {"records": inserted_count, "success": True, "error": None}

    except Exception as e:
        error_msg = f"Error processing station {station_number}: {str(e)}"
        logger.error(error_msg)
        return {"records": 0, "success": False, "error": error_msg}


STATION_WORKERS = 8


class PullPacing(NamedTuple):
    """How hard we are allowed to hit one upstream source."""

    workers: int
    delay_seconds: float


# Per-source pacing. Each upstream tolerates a different request rate:
#   - nwrfc_web 429s on any parallelism at all (see 54db0bd)
#   - USGS NWIS silently degrades under bursts rather than returning 429 —
#     it hands back empty bodies (surfacing as "Expecting value: line 1
#     column 1") and truncated gzip payloads. 8 unpaced workers over 2890
#     stations meant ~14 req/s and lost 7-40 stations per run.
# Anything not listed keeps the historical unpaced behavior.
SOURCE_PACING = {
    "nwrfc_web": PullPacing(workers=1, delay_seconds=1.5),
    "USGS": PullPacing(workers=3, delay_seconds=1.0),
}

DEFAULT_PACING = PullPacing(workers=STATION_WORKERS, delay_seconds=0)


def get_pull_pacing(data_source: str) -> PullPacing:
    """Return the concurrency and inter-request delay to use for a source."""
    return SOURCE_PACING.get(data_source, DEFAULT_PACING)


# Share of stations that may fail before a run stops counting as healthy.
# Large configs always lose a few stations to transient upstream errors; those
# self-heal on the next run. Treating that as an outright failure hid the runs
# that were genuinely broken.
PARTIAL_FAILURE_THRESHOLD = 0.05


def classify_pull_status(successful: int, failed: int) -> str:
    """Classify a completed run as success, partial, or failed.

    Clean run -> success. Failures within PARTIAL_FAILURE_THRESHOLD of the
    stations attempted -> partial. Anything worse -> failed.
    """
    if failed == 0:
        return "success"

    attempted = successful + failed
    if failed <= attempted * PARTIAL_FAILURE_THRESHOLD:
        return "partial"

    return "failed"


@shared_task(bind=True, max_retries=3)
def execute_pull_configuration(self, config_id: int):
    """
    Execute a data pull for a specific configuration.

    This is the main task that orchestrates the entire data pull process:
    1. Load configuration
    2. For each station in configuration:
       - Determine start date using Smart Append Logic
       - Fetch data from appropriate source (USGS/EC)
       - Validate and store data
       - Update progress
    3. Log execution results

    Args:
        config_id: Pull configuration ID
    """
    try:
        logger.info(f"=" * 60)
        logger.info(f"Starting pull for configuration {config_id}")
        logger.info(f"=" * 60)

        # Get configuration
        try:
            config = PullConfiguration.objects.prefetch_related(
                'configuration_stations'
            ).get(id=config_id)
        except PullConfiguration.DoesNotExist:
            logger.error(f"Configuration {config_id} not found")
            return {"status": "error", "message": "Configuration not found"}

        if not config.is_enabled:
            logger.warning(f"Configuration {config_id} is disabled")
            return {"status": "skipped", "message": "Configuration disabled"}

        # Create log entry
        log = DataPullLog.objects.create(
            configuration=config,
            status="running",
            start_time=datetime.now(timezone.utc)
        )

        # Initialize counters
        total_records = 0
        successful_stations = 0
        failed_stations = 0
        errors = []

        # Get stations in configuration
        config_stations = list(config.configuration_stations.all())

        # Rate-limited sources get reduced concurrency and spaced-out submissions
        # so we don't trip upstream throttling (see SOURCE_PACING).
        pacing = get_pull_pacing(config.data_source)

        def _record(result):
            nonlocal total_records, successful_stations, failed_stations
            total_records += result["records"]
            if result["success"]:
                successful_stations += 1
            else:
                failed_stations += 1
                if result["error"]:
                    errors.append(result["error"])

        if pacing.workers == 1:
            logger.info(
                f"Processing {len(config_stations)} stations sequentially "
                f"({config.data_source} rate-limit mode, {pacing.delay_seconds}s delay)"
            )
            for cs in config_stations:
                try:
                    _record(_process_single_station(cs, config_id, config))
                except Exception as e:
                    failed_stations += 1
                    errors.append(f"Error processing {cs.station_number}: {e}")
                time.sleep(pacing.delay_seconds)
        else:
            logger.info(
                f"Processing {len(config_stations)} stations with {pacing.workers} "
                f"workers ({pacing.delay_seconds}s between submissions)"
            )
            with ThreadPoolExecutor(max_workers=pacing.workers) as executor:
                futures = {}
                for cs in config_stations:
                    futures[executor.submit(_process_single_station, cs, config_id, config)] = cs
                    if pacing.delay_seconds:
                        time.sleep(pacing.delay_seconds)
                for future in as_completed(futures):
                    cs = futures[future]
                    try:
                        _record(future.result())
                    except Exception as e:
                        failed_stations += 1
                        errors.append(f"Error processing {cs.station_number}: {e}")

        # Update log entry
        log_status = classify_pull_status(successful_stations, failed_stations)

        log.status = log_status
        log.records_processed = total_records
        log.end_time = datetime.now(timezone.utc)
        log.error_message = "\n".join(errors) if errors else ""
        log.save()

        # Update configuration last_run_at
        config.last_run_at = datetime.now(timezone.utc)
        config.save(update_fields=['last_run_at'])

        logger.info(f"\n" + "=" * 60)
        logger.info(f"Pull configuration {config_id} completed:")
        logger.info(f"  - Total records: {total_records}")
        logger.info(f"  - Successful stations: {successful_stations}")
        logger.info(f"  - Failed stations: {failed_stations}")
        logger.info(f"  - Status: {log_status}")
        logger.info(f"=" * 60)

        return {
            "status": log_status,
            "records_processed": total_records,
            "successful_stations": successful_stations,
            "failed_stations": failed_stations,
            "errors": errors,
        }

    except Exception as e:
        logger.error(f"Critical error in pull configuration {config_id}: {e}")
        if 'log' in locals():
            log.status = "failed"
            log.end_time = datetime.now(timezone.utc)
            log.error_message = str(e)
            log.save()
        raise


@shared_task
def execute_forecast_pull(config_id: int):
    """
    Execute a forecast data pull for a specific configuration.

    Args:
        config_id: Pull configuration ID
    """
    try:
        logger.info(f"Starting forecast pull for configuration {config_id}")

        # Get configuration
        try:
            config = PullConfiguration.objects.prefetch_related(
                'configuration_stations'
            ).get(id=config_id, is_enabled=True)
        except PullConfiguration.DoesNotExist:
            logger.warning(f"Configuration {config_id} not found or disabled")
            return

        # Initialize components
        noaa_client = NOAAClient()
        processor = DataProcessor()

        successful_count = 0
        failed_count = 0

        # Get stations in configuration
        config_stations = config.configuration_stations.all()

        for config_station in config_stations:
            station_number = config_station.station_number

            try:
                # Translate USGS ID to NOAA HADS ID
                try:
                    mapping = StationMapping.objects.get(
                        source_agency="USGS",
                        source_id=station_number,
                        target_agency="NOAA-HADS"
                    )
                    hads_id = mapping.target_id
                except StationMapping.DoesNotExist:
                    logger.warning(
                        f"No HADS mapping found for station {station_number}"
                    )
                    continue

                # Fetch forecast data
                forecast_type = getattr(config, 'forecast_type', 'short')
                forecast_data = noaa_client.get_forecast(hads_id, forecast_type=forecast_type)

                if forecast_data:
                    # Store forecast
                    success = processor.process_forecast(station_number, forecast_data)
                    if success:
                        successful_count += 1
                    else:
                        failed_count += 1
                else:
                    logger.info(
                        f"No forecast data available for station {station_number}"
                    )

            except Exception as e:
                logger.error(
                    f"Error fetching forecast for station {station_number}: {e}"
                )
                failed_count += 1
                continue

        logger.info(
            f"Forecast pull completed: {successful_count} successful, {failed_count} failed"
        )

        return {"successful": successful_count, "failed": failed_count}

    except Exception as e:
        logger.error(f"Critical error in forecast pull {config_id}: {e}")
        raise


@shared_task
def cleanup_old_logs(days_to_keep: int = 30):
    """
    Clean up old data pull logs.

    Args:
        days_to_keep: Number of days of logs to retain
    """
    from datetime import timedelta

    try:
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_to_keep)

        # Delete logs older than cutoff_date
        deleted_count = DataPullLog.objects.filter(
            start_time__lt=cutoff_date
        ).delete()[0]

        logger.info(f"Cleaned up {deleted_count} logs older than {cutoff_date}")
        return {"deleted": deleted_count}

    except Exception as e:
        logger.error(f"Error cleaning up logs: {e}")
        raise


def _compute_next_run(from_time, schedule_type, schedule_value):
    """Compute the next run time based on schedule type.

    Uses croniter for all schedule types to ensure runs land on the correct
    wall-clock times (e.g., "daily at 10:30") instead of drifting.

    Args:
        from_time: datetime to compute from (typically ``now``)
        schedule_type: one of 'hourly', 'daily', 'weekly', 'custom'
        schedule_value: cron expression string.  For 'custom' this is
            required.  For other types it is optional — when provided it
            overrides the default cron pattern for that type.

    Returns:
        datetime for the next scheduled run
    """
    from croniter import croniter

    _DEFAULT_CRONS = {
        'hourly': '0 * * * *',
        'daily': '0 0 * * *',
        'weekly': '0 0 * * 0',
    }

    if schedule_type == 'custom':
        if not schedule_value:
            raise ValueError(
                "schedule_type 'custom' requires a non-empty schedule_value "
                "(cron expression)"
            )
        cron_expr = schedule_value
    else:
        # Use schedule_value if the user supplied a cron expression,
        # otherwise fall back to a sensible default for the type.
        cron_expr = schedule_value.strip() if schedule_value else ''
        if not cron_expr:
            cron_expr = _DEFAULT_CRONS.get(schedule_type, '0 0 * * *')

    try:
        return croniter(cron_expr, from_time).get_next(datetime)
    except (ValueError, KeyError) as exc:
        logger.error(
            "Invalid cron expression %r for schedule_type %r: %s. "
            "Falling back to 24 h offset.",
            cron_expr,
            schedule_type,
            exc,
        )
        from datetime import timedelta
        return from_time + timedelta(days=1)


RUNNING_LOG_STALE_AFTER = timedelta(minutes=30)


@shared_task
def scheduled_streamflow_pulls():
    """Dispatcher that checks enabled PullConfigurations and kicks off due pulls.

    Runs on Celery Beat (every 5 minutes). For each enabled config whose
    next_run_at is in the past (or NULL), it dispatches
    execute_pull_configuration and atomically sets the next next_run_at.
    Configs that already have a running DataPullLog are skipped to prevent
    double-dispatch — but any "running" log older than
    RUNNING_LOG_STALE_AFTER is reaped (marked failed) first so a crashed
    worker can't permanently jam this config.
    """
    now = datetime.now(timezone.utc)
    configs = PullConfiguration.objects.filter(is_enabled=True)

    stale_cutoff = now - RUNNING_LOG_STALE_AFTER
    reaped = DataPullLog.objects.filter(
        status='running',
        start_time__lt=stale_cutoff,
    ).update(
        status='failed',
        end_time=now,
        error_message='Reaped by dispatcher: log stuck in "running" past staleness window',
    )
    if reaped:
        logger.warning("Reaped %d stale 'running' DataPullLog row(s)", reaped)

    dispatched = 0
    skipped = 0

    for config in configs:
        # Skip if there is already a fresh running pull for this config
        if DataPullLog.objects.filter(
            configuration=config,
            status='running',
            start_time__gte=stale_cutoff,
        ).exists():
            logger.debug("Skipping config %s (%s): already running", config.id, config.name)
            skipped += 1
            continue

        # Skip if next_run_at is set and still in the future
        if config.next_run_at is not None and config.next_run_at > now:
            continue

        # Due for execution — dispatch
        execute_pull_configuration.delay(config.id)
        dispatched += 1

        # Compute and atomically set next_run_at
        next_run = _compute_next_run(now, config.schedule_type, config.schedule_value)
        PullConfiguration.objects.filter(id=config.id).update(next_run_at=next_run)

        logger.info(
            "Dispatched pull for config %s (%s), next_run_at=%s",
            config.id, config.name, next_run,
        )

    logger.info("scheduled_streamflow_pulls: dispatched=%d, skipped=%d", dispatched, skipped)
    return {"dispatched": dispatched, "skipped": skipped}


@shared_task
def run_nwrfc_web_pull():
    """Look up the nwrfc_web PullConfiguration and trigger a pull.

    Decouples the beat schedule from the config's DB primary key.
    """
    try:
        config = PullConfiguration.objects.get(data_source='nwrfc_web', is_enabled=True)
    except PullConfiguration.DoesNotExist:
        logger.warning("run_nwrfc_web_pull: no enabled nwrfc_web PullConfiguration found — skipping")
        return {"skipped": True}
    except PullConfiguration.MultipleObjectsReturned:
        config = PullConfiguration.objects.filter(data_source='nwrfc_web', is_enabled=True).first()

    execute_pull_configuration.delay(config.id)
    logger.info("run_nwrfc_web_pull: queued execute_pull_configuration(config_id=%d)", config.id)
    return {"config_id": config.id}
