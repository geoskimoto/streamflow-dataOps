"""Flow percentile computation logic."""

import logging
from datetime import date, datetime, timezone
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

def compute_percentile_for_date(target_date: date) -> list[dict]:
    """
    Compute exceedance percentile bands for all stations that have a
    daily_mean observation on ``target_date``, comparing each value
    against the station's full period of record.

    Uses one SQL query (no per-station round-trips).

    Returns:
        List of dicts with keys:
            station_id, station_number, discharge, observation_date,
            historical_record_count, percentile_rank, band
    """
    sql = """
        WITH obs_on_date AS (
            -- One row per station for the target date (take latest if multiple)
            SELECT DISTINCT ON (station_id)
                station_id,
                discharge,
                observed_at::date AS observation_date
            FROM discharge_observations
            WHERE type = 'daily_mean'
              AND observed_at::date = %(target_date)s
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

    with connection.cursor() as cursor:
        cursor.execute(sql, {
            "target_date": target_date,
            "min_records": MIN_HISTORICAL_RECORDS,
        })
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
        "compute_percentile_for_date(%s): %d stations", target_date, len(results)
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
