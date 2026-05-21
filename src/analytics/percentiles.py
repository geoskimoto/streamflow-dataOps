"""Flow percentile computation logic."""

import logging
from datetime import date, datetime, timezone, timedelta
from typing import Generator

from django.db import connection

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Band classification
# ---------------------------------------------------------------------------

BAND_THRESHOLDS = [
    (4,   "p0_4"),
    (10,  "p5_10"),
    (25,  "p11_25"),
    (50,  "p26_50"),
    (75,  "p51_75"),
    (85,  "p76_85"),
    (90,  "p86_90"),
    (95,  "p91_95"),
    (98,  "p96_98"),
    (101, "p99_100"),
]

MIN_HISTORICAL_RECORDS = 30


def classify_band(percentile_rank: float) -> str:
    """Map a percentile rank (0–100) to its band key."""
    for threshold, band in BAND_THRESHOLDS:
        if percentile_rank <= threshold:
            return band
    return "p99_100"


# ---------------------------------------------------------------------------
# Single-date computation (used by the daily Celery task)
# ---------------------------------------------------------------------------

def compute_percentile_for_date(
    target_date: date,
    station_ids: list[int] | None = None,
) -> list[dict]:
    """
    Compute exceedance percentile bands for stations with a daily_mean observation
    on ``target_date``, comparing each value against the station's full period of record.

    Uses one SQL query (no per-station round-trips).

    Args:
        target_date: Date to compute percentiles for.
        station_ids: Optional list of Station PKs to restrict computation to.
                     Pass None to compute all qualifying stations.
                     Pass [] to compute none.

    Returns:
        List of dicts with keys:
            station_id, station_number, discharge, observation_date,
            historical_record_count, percentile_rank, band
    """
    if station_ids is not None:
        station_filter = "AND station_id = ANY(%(station_ids)s)"
    else:
        station_filter = ""

    sql = f"""
        WITH obs_on_date AS (
            -- One row per station for the target date (take latest if multiple)
            SELECT DISTINCT ON (station_id)
                station_id,
                discharge,
                observed_at::date AS observation_date
            FROM discharge_observations
            WHERE type = 'daily_mean'
              AND observed_at::date = %(target_date)s
              {station_filter}
            ORDER BY station_id, observed_at DESC
        )
        SELECT
            s.id                AS station_id,
            s.station_number,
            o.discharge,
            o.observation_date,
            COUNT(h.id)         AS historical_record_count,
            ROUND(
                COUNT(h.id) FILTER (WHERE h.discharge <= o.discharge) * 100.0
                / NULLIF(COUNT(h.id), 0),
            2)                  AS percentile_rank
        FROM obs_on_date o
        JOIN stations s
            ON s.id = o.station_id
        JOIN discharge_observations h
            ON h.station_id = o.station_id
           AND h.type = 'daily_mean'
        GROUP BY
            s.id,
            s.station_number,
            o.discharge,
            o.observation_date
        HAVING COUNT(h.id) >= %(min_records)s
        ORDER BY s.station_number
    """

    params: dict = {"target_date": target_date, "min_records": MIN_HISTORICAL_RECORDS}
    if station_ids is not None:
        params["station_ids"] = station_ids

    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        columns = [col[0] for col in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]

    results = []
    for row in rows:
        rank = float(row["percentile_rank"])
        results.append({
            "station_id":              row["station_id"],
            "station_number":          row["station_number"],
            "discharge":               row["discharge"],
            "observation_date":        row["observation_date"],
            "historical_record_count": int(row["historical_record_count"]),
            "percentile_rank":         rank,
            "band":                    classify_band(rank),
        })

    logger.info(
        "compute_percentile_for_date(%s, station_ids=%s): %d stations",
        target_date,
        "all" if station_ids is None else len(station_ids),
        len(results),
    )
    return results


# ---------------------------------------------------------------------------
# Historical backfill (used by the management command)
# ---------------------------------------------------------------------------

def backfill_station_chunk(
    station_ids: list[int],
    computed_at: datetime,
) -> list[dict]:
    """
    Compute exceedance percentile bands for *all* daily_mean observations
    for the given station IDs using a single window-function SQL pass.

    The window function (RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
    handles ties the same way as the COUNT FILTER approach in
    compute_percentile_for_date: every observation with the same discharge
    receives the same percentile rank (count of records ≤ that value ÷ total).

    Args:
        station_ids: List of Station PKs to process in this chunk.
        computed_at: Timestamp to stamp on every result row.

    Returns:
        List of dicts ready to be passed to DailyFlowPercentile bulk_create.
    """
    sql = """
        WITH base AS (
            SELECT
                station_id,
                observed_at::date AS obs_date,
                discharge,
                COUNT(*) OVER (PARTITION BY station_id)
                    AS total_count,
                -- COUNT with RANGE gives all tied rows the same rank
                COUNT(*) OVER (
                    PARTITION BY station_id
                    ORDER BY discharge
                    RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                ) AS count_le
            FROM discharge_observations
            WHERE type = 'daily_mean'
              AND station_id = ANY(%(station_ids)s)
        )
        SELECT
            station_id,
            obs_date,
            discharge,
            total_count  AS historical_record_count,
            ROUND(count_le * 100.0 / total_count, 2) AS percentile_rank
        FROM base
        WHERE total_count >= %(min_records)s
        ORDER BY station_id, obs_date
    """

    with connection.cursor() as cursor:
        cursor.execute(sql, {
            "station_ids": station_ids,
            "min_records": MIN_HISTORICAL_RECORDS,
        })
        columns = [col[0] for col in cursor.description]
        rows = cursor.fetchall()

    results = []
    for row in rows:
        d = dict(zip(columns, row))
        rank = float(d["percentile_rank"])
        results.append({
            "station_id":              d["station_id"],
            "obs_date":                d["obs_date"],
            "discharge":               d["discharge"],
            "historical_record_count": int(d["historical_record_count"]),
            "percentile_rank":         rank,
            "band":                    classify_band(rank),
            "computed_at":             computed_at,
        })

    return results


def iter_station_id_chunks(
    chunk_size: int = 100,
    station_ids: list[int] | None = None,
) -> Generator[list[int], None, None]:
    """
    Yield successive chunks of station IDs that have at least
    MIN_HISTORICAL_RECORDS daily_mean observations.

    Args:
        chunk_size: Number of station IDs per chunk.
        station_ids: Optional explicit list; if None, queries all qualifying
                     stations ordered by ID.
    """
    sql_all = """
        SELECT station_id
        FROM discharge_observations
        WHERE type = 'daily_mean'
        GROUP BY station_id
        HAVING COUNT(*) >= %(min_records)s
        ORDER BY station_id
    """

    with connection.cursor() as cursor:
        if station_ids is not None:
            ids = sorted(station_ids)
        else:
            cursor.execute(sql_all, {"min_records": MIN_HISTORICAL_RECORDS})
            ids = [row[0] for row in cursor.fetchall()]

    for i in range(0, len(ids), chunk_size):
        yield ids[i: i + chunk_size]


# ---------------------------------------------------------------------------
# Forecast percentile computation
# ---------------------------------------------------------------------------

# Maps ForecastPercentile.source label -> ForecastRun.source value
_FORECAST_RUN_SOURCE_MAP = {
    'NWRFC': 'NOAA_RFC',
}


def compute_forecast_percentiles(
    source: str = 'NWRFC',
    max_days: int = 8,
) -> list[dict]:
    """
    Compute exceedance percentile bands for the most recent NOAA_RFC ForecastRun
    per station, covering the next max_days calendar days from today.

    Compares each forecasted discharge against the station's full period-of-record
    daily_mean observations — the same methodology as compute_percentile_for_date().

    Args:
        source: ForecastPercentile.source label (e.g. 'NWRFC'). Determines which
                ForecastRun.source to query via _FORECAST_RUN_SOURCE_MAP.
        max_days: Number of calendar days ahead to include. today+1 through
                  today+max_days are included (today itself is excluded).

    Returns:
        List of dicts with keys:
            station_id, target_date, forecast_discharge, source,
            forecast_run_date, historical_record_count, percentile_rank, band
    """
    from apps.streamflow.models import ForecastRun  # avoid circular import at module load

    run_source = _FORECAST_RUN_SOURCE_MAP.get(source)
    if run_source is None:
        raise ValueError(f"Unknown forecast source: {source!r}. Add it to _FORECAST_RUN_SOURCE_MAP.")

    today = date.today()
    cutoff = today + timedelta(days=max_days)

    # Latest ForecastRun per station (DISTINCT ON station_id ORDER BY run_date DESC).
    # When multiple forecast_types share the same run_date (e.g., short + medium from
    # the parquet importer), PostgreSQL picks one non-deterministically. This is
    # acceptable for the current 8-day window since both types cover it, but if
    # max_days is extended beyond the short-range horizon, revisit to union all types.
    latest_runs = (
        ForecastRun.objects
        .filter(source=run_source)
        .order_by('station_id', '-run_date')
        .distinct('station_id')
        .values('station_id', 'run_date', 'data')
    )

    # Load NOAA_RFC → USGS station PK mapping via station_mappings table
    from apps.streamflow.models import StationMapping, Station as _Station

    _sm_rows = StationMapping.objects.filter(
        source_agency='NOAA_RFC', target_agency='USGS'
    ).values('source_id', 'target_id')

    _usgs_pk = {
        s['station_number']: s['id']
        for s in _Station.objects.filter(agency='USGS').values('id', 'station_number')
    }
    _noaa_pk = {
        s['station_number']: s['id']
        for s in _Station.objects.filter(agency='NOAA_RFC').values('id', 'station_number')
    }

    # {noaa_station_id (pk): usgs_station_id (pk)}
    _noaa_to_usgs: dict[int, int] = {}
    for sm in _sm_rows:
        noaa_pk = _noaa_pk.get(sm['source_id'])
        usgs_pk = _usgs_pk.get(sm['target_id'])
        if noaa_pk and usgs_pk:
            _noaa_to_usgs[noaa_pk] = usgs_pk

    logger.info(
        "compute_forecast_percentiles: loaded %d NOAA_RFC→USGS station mappings",
        len(_noaa_to_usgs),
    )

    # Build flat list of forecast points within (today, cutoff)
    forecast_rows: list[dict] = []
    for run in latest_runs:
        usgs_station_id = _noaa_to_usgs.get(run['station_id'])
        if usgs_station_id is None:
            logger.debug(
                "compute_forecast_percentiles: no USGS mapping for NOAA_RFC station_id=%s, skipping",
                run['station_id'],
            )
            continue
        for point in (run['data'] or []):
            try:
                pt_date = date.fromisoformat(str(point['date'])[:10])
                discharge = float(point['value'])
            except (KeyError, ValueError, TypeError):
                logger.warning(
                    "Skipping malformed forecast point for station_id=%s: %r",
                    run['station_id'], point,
                )
                continue
            if today < pt_date <= cutoff:
                forecast_rows.append({
                    'station_id':        usgs_station_id,   # USGS PK — used for discharge join and ForecastPercentile FK
                    'target_date':       pt_date,
                    'discharge':         discharge,
                    'forecast_run_date': run['run_date'],
                })

    # Deduplicate by (station_id, target_date) — multiple NOAA stations may map to the same
    # USGS station, producing duplicate keys that violate the unique constraint on upsert.
    # Keep the row with the latest forecast_run_date.
    _seen: dict[tuple, dict] = {}
    for row in forecast_rows:
        key = (row['station_id'], row['target_date'])
        if key not in _seen or row['forecast_run_date'] > _seen[key]['forecast_run_date']:
            _seen[key] = row
    forecast_rows = list(_seen.values())

    if not forecast_rows:
        logger.info("compute_forecast_percentiles(%s): no forecast data found", source)
        return []

    # Build VALUES clause with type hints on first row so PostgreSQL infers column types
    value_parts = []
    flat_params: list = []
    for i, row in enumerate(forecast_rows):
        if i == 0:
            value_parts.append('(%s::bigint, %s::date, %s::numeric)')
        else:
            value_parts.append('(%s, %s, %s)')
        flat_params.extend([row['station_id'], row['target_date'].isoformat(), row['discharge']])

    values_clause = ', '.join(value_parts)

    sql = f"""
        WITH forecast_vals (station_id, target_date, discharge) AS (
            VALUES {values_clause}
        )
        SELECT
            fv.station_id,
            fv.target_date,
            fv.discharge,
            COUNT(h.id)                                              AS historical_record_count,
            ROUND(
                COUNT(h.id) FILTER (WHERE h.discharge <= fv.discharge) * 100.0
                / NULLIF(COUNT(h.id), 0),
            2)                                                       AS percentile_rank
        FROM forecast_vals fv
        JOIN discharge_observations h
            ON h.station_id = fv.station_id
           AND h.type = 'daily_mean'
        GROUP BY fv.station_id, fv.target_date, fv.discharge
        HAVING COUNT(h.id) >= %s
        ORDER BY fv.station_id, fv.target_date
    """

    flat_params.append(MIN_HISTORICAL_RECORDS)

    # Build lookup: (station_id, target_date) -> forecast_run_date
    run_date_lookup = {
        (r['station_id'], r['target_date']): r['forecast_run_date']
        for r in forecast_rows
    }

    with connection.cursor() as cursor:
        cursor.execute(sql, flat_params)
        columns = [col[0] for col in cursor.description]
        rows = cursor.fetchall()

    results = []
    for row in rows:
        d = dict(zip(columns, row))
        station_id  = d['station_id']
        target_date = d['target_date']
        rank = float(d['percentile_rank'])
        results.append({
            'station_id':              station_id,
            'target_date':             target_date,
            'forecast_discharge':      float(d['discharge']),
            'source':                  source,
            'forecast_run_date':       run_date_lookup[(station_id, target_date)],
            'historical_record_count': int(d['historical_record_count']),
            'percentile_rank':         rank,
            'band':                    classify_band(rank),
        })

    logger.info(
        "compute_forecast_percentiles(%s, max_days=%d): %d rows", source, max_days, len(results)
    )
    return results
