"""Station metadata computation: flow statistics and record bounds via PostgreSQL."""

import logging

from django.db import connection
from django.utils import timezone

logger = logging.getLogger(__name__)


def compute_station_metadata(station_ids=None):
    """Compute and upsert StationMetadata for stations with daily_mean observations.

    Args:
        station_ids: List of Station PKs to process. None means all stations.

    Returns:
        Number of StationMetadata rows upserted.
    """
    from apps.analytics.models import StationMetadata

    station_filter_sql = ''
    params = []
    if station_ids:
        station_filter_sql = 'AND o.station_id = ANY(%s)'
        params.append(list(station_ids))

    sql = f"""
        WITH obs_stats AS (
            SELECT
                o.station_id,
                MAX(o.observed_at AT TIME ZONE 'UTC')::date          AS last_obs_date,
                MIN(o.observed_at AT TIME ZONE 'UTC')::date          AS rec_start,
                MAX(o.observed_at AT TIME ZONE 'UTC')::date          AS rec_end,
                COUNT(*)                                              AS obs_count,
                AVG(o.discharge)                                      AS mean_flow,
                PERCENTILE_CONT(0.10) WITHIN GROUP (ORDER BY o.discharge) AS q10,
                PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY o.discharge) AS q25,
                PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY o.discharge) AS q50,
                PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY o.discharge) AS q75,
                PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY o.discharge) AS q90
            FROM discharge_observations o
            WHERE o.type = 'daily_mean'
              AND o.discharge IS NOT NULL
              AND o.discharge >= 0
              {station_filter_sql}
            GROUP BY o.station_id
        )
        SELECT
            station_id,
            last_obs_date,
            rec_start,
            rec_end,
            obs_count,
            CASE
                WHEN rec_end > rec_start THEN
                    LEAST(
                        ROUND(obs_count::numeric / (rec_end - rec_start + 1) * 100, 2),
                        100.0
                    )
                ELSE 100.0
            END                                            AS completeness_pct,
            ROUND(
                (rec_end - rec_start)::numeric / 365.25,
                2
            )                                              AS years_on_record,
            ROUND(mean_flow::numeric, 2)                   AS mean_flow,
            ROUND(q10::numeric, 2)                         AS q10,
            ROUND(q25::numeric, 2)                         AS q25,
            ROUND(q50::numeric, 2)                         AS q50,
            ROUND(q75::numeric, 2)                         AS q75,
            ROUND(q90::numeric, 2)                         AS q90
        FROM obs_stats
    """

    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        rows = cursor.fetchall()

    if not rows:
        logger.info('compute_station_metadata: no rows returned (no qualifying observations)')
        return 0

    now = timezone.now()
    upsert_count = 0

    for row in rows:
        (station_id, last_obs_date, rec_start, rec_end,
         obs_count, completeness_pct, years_on_record,
         mean_flow, q10, q25, q50, q75, q90) = row

        StationMetadata.objects.update_or_create(
            station_id=station_id,
            defaults={
                'last_observation_date': last_obs_date,
                'record_start_date': rec_start,
                'record_end_date': rec_end,
                'daily_observation_count': obs_count,
                'record_completeness_pct': completeness_pct,
                'years_on_record': years_on_record,
                'mean_annual_flow_cfs': mean_flow,
                'q10_cfs': q10,
                'q25_cfs': q25,
                'q50_cfs': q50,
                'q75_cfs': q75,
                'q90_cfs': q90,
                'computed_at': now,
            },
        )
        upsert_count += 1

    logger.info('compute_station_metadata: upserted %d rows', upsert_count)
    return upsert_count
