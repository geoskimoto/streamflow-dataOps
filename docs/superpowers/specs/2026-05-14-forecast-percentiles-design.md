# Forecast Percentile Bands — Design Spec

**Date:** 2026-05-14  
**Status:** Approved  
**Scope:** StreamflowOps backend + downstream dashboard (usgs-streamflow-dashboard)

---

## Overview

Extend the existing observed-percentile system to pre-compute and serve percentile bands for NWRFC forecast data out to day 8. The dashboard date picker will span both the historical observed period and the 8-day forecast window, with a source label indicating which data type is being shown.

---

## 1. Data Model

**New model:** `ForecastPercentile` in `apps/streamflow/models.py` (alongside `DailyFlowPercentile`).

| Field | Type | Notes |
|---|---|---|
| `station` | FK → Station | CASCADE |
| `target_date` | DateField | The forecasted calendar date |
| `source` | CharField(20) | `'NWRFC'`; extensible for `'MUTHRE'`, etc. |
| `forecast_run_date` | DateTimeField | Issuance datetime of the ForecastRun used |
| `forecast_discharge` | DecimalField(12, 4) | Forecasted flow in cfs |
| `percentile_rank` | DecimalField(5, 2) | 0–100 exceedance rank |
| `band` | CharField(10) | Same `p0_4`…`p99_100` classification |
| `historical_record_count` | IntegerField | Number of historical records used |
| `computed_at` | DateTimeField | When this row was computed |

**Unique constraint:** `(station, target_date, source)` — one active row per station/date/source. Upsert replaces when a newer forecast run arrives.

**Indexes:** `(station, target_date)`, `(source, target_date)`

**Table name:** `forecast_percentiles`

---

## 2. Computation Logic

**New function:** `compute_forecast_percentiles(source='NWRFC', max_days=8)` in `src/analytics/percentiles.py`.

### Steps

1. Query the latest `ForecastRun` per station where `source='NOAA_RFC'` — one row per station, most recent `run_date`.
2. Parse each run's JSON `data` array (`[{date, value}]`), keeping only entries whose date falls within `[today, today + max_days)`.
3. Build a flat list of `(station_id, target_date, forecast_discharge_cfs, run_date)` tuples across all stations.
4. Run a single SQL query using a `VALUES` CTE to compare each forecasted value against the station's full historical `daily_mean` record:

```sql
WITH forecast_vals (station_id, target_date, discharge) AS (
    VALUES %s  -- injected as parameterized rows
)
SELECT
    fv.station_id,
    fv.target_date,
    fv.discharge,
    COUNT(h.id)                                             AS historical_record_count,
    ROUND(
        COUNT(h.id) FILTER (WHERE h.discharge <= fv.discharge) * 100.0
        / NULLIF(COUNT(h.id), 0),
    2)                                                      AS percentile_rank
FROM forecast_vals fv
JOIN discharge_observations h
    ON h.station_id = fv.station_id
   AND h.type = 'daily_mean'
GROUP BY fv.station_id, fv.target_date, fv.discharge
HAVING COUNT(h.id) >= 30
ORDER BY fv.station_id, fv.target_date
```

5. Apply `classify_band()` (unchanged) to each `percentile_rank`.
6. Upsert into `ForecastPercentile` via `update_or_create` on `(station, target_date, source)`.

### Key decisions

- **Same historical baseline as observed percentiles**: forecast value compared against the station's full period-of-record daily_mean observations (not same-DOY subset), matching the existing observed methodology.
- **Latest run wins**: if NWRFC issues multiple runs in a day, the task always uses the most recent `run_date` per station and overwrites the prior result.
- **Stations without NOAA_RFC ForecastRuns are silently skipped** — no error, just no rows in `forecast_percentiles` for that station.
- **Minimum 30 historical records** required (same threshold as `MIN_HISTORICAL_RECORDS` in `percentiles.py`).

---

## 3. Celery Task & Schedule

**New task:** `compute_forecast_percentile_bands` in `src/analytics/tasks.py`.

- Same structure as existing `compute_daily_flow_percentiles` task.
- Calls `compute_forecast_percentiles(source='NWRFC', max_days=8)`.
- Logs start/end/record count via `ComputationLog`.
- Updates `ScheduledComputation` last-run status.
- Registered in `ScheduledComputation` data migration with name `"NWRFC Forecast Percentile Bands"`.

**Schedule:** Every 6 hours — 00:00, 06:00, 12:00, 18:00 UTC. NWRFC issues forecasts twice daily; 6-hour polling ensures fresh bands within half a cycle.

---

## 4. API

### New viewset action — percentile bands

```
GET /api/v1/forecasts/discharge/percentile-bands/
```

**Query params:**

| Param | Required | Description |
|---|---|---|
| `date` | No | `YYYY-MM-DD`. Defaults to the earliest available forecast date. |
| `source` | No | Forecast source. Defaults to `NWRFC`. |
| `station` | No | Filter to a single station number. |

**Response:**

```json
{
  "date": "2026-05-18",
  "source": "NWRFC",
  "forecast_run_date": "2026-05-14T12:00:00Z",
  "computed_at": "2026-05-14T13:01:22Z",
  "count": 238,
  "results": [
    {
      "station_number": "12114500",
      "forecast_discharge": 4820.0,
      "percentile_rank": 72.4,
      "band": "p51_75",
      "historical_record_count": 8431
    }
  ]
}
```

**Caching:** None — forecasts update intraday.

### New viewset action — date range

```
GET /api/v1/forecasts/discharge/percentile-date-range/
```

**Query params:** `source` (optional, default `NWRFC`)

**Response:**

```json
{
  "source": "NWRFC",
  "min_date": "2026-05-15",
  "max_date": "2026-05-22",
  "forecast_run_date": "2026-05-14T12:00:00Z"
}
```

**Caching:** 1 hour (same pattern as observed date-range endpoint).

### Placement

Both actions added to `ForecastRunViewSet` in `apps/api/views/forecast.py` (currently 174 lines — well within a manageable size). Registered under the existing `/api/v1/forecasts/` router prefix.

---

## 5. Dashboard Integration

**App:** `/home/geoskimoto/usgs-streamflow-dashboard`

### Date picker bounds

- **Min:** existing observed `min_date` (unchanged)
- **Max:** `max_date` from forecast percentile-date-range endpoint (today + ~8 days)
- Bootstrap the bounds by calling both date-range endpoints on load and taking the union.

### Routing logic

```
date <= today  →  GET /api/v1/observations/discharge/percentile-bands/?date=...
date > today   →  GET /api/v1/forecasts/discharge/percentile-bands/?date=...&source=NWRFC
```

Today's date shows observed data when available, forecast as fallback (observed endpoint returns data for today if the daily task has run).

### Source label

Small text element near the date picker:

- Observed period: *"Observed conditions"*
- Forecast period: *"Forecast: NWRFC — issued [forecast_run_date formatted as local date/time]"*

Label updates whenever the selected date changes.

---

## 6. Testing

| Layer | What to test |
|---|---|
| Unit | `compute_forecast_percentiles()` with fixture ForecastRuns; verify upsert replaces stale rows; verify stations with no NOAA_RFC runs are skipped; verify `max_days` cutoff |
| Model | `ForecastPercentile` unique constraint enforced; `forecast_run_date` updated on upsert |
| API | `/percentile-bands/` returns correct band for known discharge; date param validation; `source` param filters correctly; missing date defaults correctly |
| Integration | Celery task runs end-to-end against test DB with seeded ForecastRuns and historical observations |
| Dashboard | Date picker max extends to today+8; label switches correctly at the observed/forecast boundary; NWRFC run date displayed correctly |

---

## 7. Migration Path

1. Add `ForecastPercentile` model → generate and apply migration
2. Register `ScheduledComputation` row via data migration
3. Add `compute_forecast_percentiles()` to `src/analytics/percentiles.py`
4. Add Celery task and beat schedule entry
5. Add API actions and register routes
6. Run task manually once to populate initial data
7. Deploy dashboard changes — date picker and label

No changes to existing observed-percentile pipeline, `DailyFlowPercentile` model, or existing API endpoints.
