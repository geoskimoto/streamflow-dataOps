"""Flow percentile computation logic."""

import logging
from datetime import datetime, timezone

from django.db import connection

logger = logging.getLogger(__name__)


BAND_THRESHOLDS = [
    (4,   "p0_4"),
    (10,  "p5_10"),
    (25,  "p11_25"),
    (50,  "p26_50"),
    (75,  "p51_75"),
    (101, "p76_100"),  # catch-all upper bound
]

MIN_HISTORICAL_RECORDS = 30


def classify_band(percentile_rank: float) -> str:
    """Map a percentile rank (0–100) to its band key."""
    for threshold, band in BAND_THRESHOLDS:
        if percentile_rank <= threshold:
            return band
    return "p76_100"


def compute_percentile_bands() -> list[dict]:
    """
    Compute exceedance percentile bands for all stations with a daily_mean
    observation within the past 2 days, using the full period of record as
    the historical baseline.

    Uses a single raw SQL query with DISTINCT ON and COUNT FILTER to avoid
    per-station round-trips. All computation stays in PostgreSQL.

    Returns:
        List of dicts with keys: station_id, station_number, current_discharge,
        observation_date, historical_record_count, percentile_rank, band
    """
    sql = """
        WITH latest_obs AS (
            -- Most recent daily_mean per station within the past 2 days
            SELECT DISTINCT ON (station_id)
                station_id,
                discharge,
                observed_at::date AS observation_date
            FROM discharge_observations
            WHERE type = 'daily_mean'
              AND observed_at >= NOW() - INTERVAL '2 days'
            ORDER BY station_id, observed_at DESC
        )
        SELECT
            s.id                AS station_id,
            s.station_number,
            l.discharge         AS current_discharge,
            l.observation_date,
            COUNT(h.id)         AS historical_record_count,
            ROUND(
                COUNT(h.id) FILTER (WHERE h.discharge <= l.discharge) * 100.0
                / NULLIF(COUNT(h.id), 0),
            2)                  AS percentile_rank
        FROM latest_obs l
        JOIN stations s
            ON s.id = l.station_id
        JOIN discharge_observations h
            ON h.station_id = l.station_id
           AND h.type = 'daily_mean'
        GROUP BY
            s.id,
            s.station_number,
            l.discharge,
            l.observation_date
        HAVING COUNT(h.id) >= %(min_records)s
        ORDER BY s.station_number
    """

    with connection.cursor() as cursor:
        cursor.execute(sql, {"min_records": MIN_HISTORICAL_RECORDS})
        columns = [col[0] for col in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]

    results = []
    for row in rows:
        rank = float(row["percentile_rank"])
        results.append({
            "station_id":              row["station_id"],
            "station_number":          row["station_number"],
            "current_discharge":       row["current_discharge"],
            "observation_date":        row["observation_date"],
            "historical_record_count": int(row["historical_record_count"]),
            "percentile_rank":         rank,
            "band":                    classify_band(rank),
        })

    logger.info(f"Computed percentile bands for {len(results)} stations")
    return results
