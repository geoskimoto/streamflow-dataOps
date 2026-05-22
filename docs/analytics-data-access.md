# Analytics Data Access Guide

**Last updated:** 2026-05-22  
**Applies to:** StreamFlow DataOps — production at `streamflowops.3rdplaces.io`

This guide covers all analytics output tables and how to access them, whether you are connecting directly to PostgreSQL or consuming the REST API.

---

## Overview of Analytics Outputs

The analytics system produces four types of output, each in its own DB table:

| Table | What it contains | Rows (current) | Refreshed |
|---|---|---|---|
| `daily_flow_percentiles` | Exceedance percentile rank + band for each station × date | ~36.9M | 3×/day (06:00, 12:00, 18:00 UTC) |
| `forecast_percentiles` | Exceedance percentile rank + band for NWRFC 8-day forecasts | ~3,900 | Every 6h (00:00, 06:00, 12:00, 18:00 UTC) |
| `station_metadata` | Fixed flow quantiles (Q10–Q90), record stats per station | 4,880 | Annual (October) |
| `flood_thresholds` | NWS action/minor/moderate/major/record stage and flow per station | varies | Annual or on-demand |

All refresh schedules are controlled via **Analytics → Configurations** in the web GUI and can be adjusted without code changes.

---

## 1. Connecting Directly to the Database

### Connection

```
Host:     localhost (or VPS internal IP)
Port:     5432
Database: streamflowops   (or as set in DATABASE_URL)
User:     streamflow
```

Read the connection string from the running environment:

```bash
grep DATABASE_URL /home/streamflow/streamflow-dataOps/streamflow-dataOps/.env
```

### 1.1 `daily_flow_percentiles`

One row per station per date. The primary lookup for "what condition was flow at station X on date Y?"

**Schema:**

| Column | Type | Notes |
|---|---|---|
| `id` | bigint | PK |
| `station_id` | bigint | FK → `stations.id` |
| `date` | date | Observation date (UTC) |
| `discharge` | numeric | Daily mean discharge in **cfs** |
| `percentile_rank` | numeric(5,2) | 0–100; percentage of historical records ≤ this discharge |
| `band` | varchar | Condition category — see Band Classification below |
| `historical_record_count` | integer | Number of historical daily_mean records used as baseline |
| `computed_at` | timestamptz | When this row was last computed |

**Unique constraint:** `(station_id, date)` — one row per station per date, upserted each run.

**Indexes:** `(date)`, `(station_id)`, `(station_id, date)` unique, `(band, date)`

**Common queries:**

```sql
-- All stations for a specific date
SELECT s.station_number, s.name, d.discharge, d.percentile_rank, d.band
FROM daily_flow_percentiles d
JOIN stations s ON s.id = d.station_id
WHERE d.date = '2026-05-21'
ORDER BY d.percentile_rank DESC;

-- Latest date available
SELECT MAX(date) FROM daily_flow_percentiles;

-- All dates for a single station
SELECT date, discharge, percentile_rank, band
FROM daily_flow_percentiles
WHERE station_id = (SELECT id FROM stations WHERE station_number = '12114500')
ORDER BY date DESC
LIMIT 30;

-- Stations currently in "much below normal" or "below normal" bands
SELECT s.station_number, s.name, d.discharge, d.percentile_rank, d.band
FROM daily_flow_percentiles d
JOIN stations s ON s.id = d.station_id
WHERE d.date = (SELECT MAX(date) FROM daily_flow_percentiles)
  AND d.band IN ('p0_4', 'p5_10')
ORDER BY d.percentile_rank;

-- Date range with data coverage
SELECT MIN(date) AS earliest, MAX(date) AS latest, COUNT(DISTINCT date) AS dates_with_data
FROM daily_flow_percentiles;
```

**Notes:**
- Only stations with ≥ 30 historical daily_mean observations are included.
- Stations missing a daily_mean for the target date are absent from that date's rows (not NULL-padded).
- Historical backfill extends to 1900-01-01 for long-record USGS stations.

---

### 1.2 `forecast_percentiles`

One row per station × target date × source. The lookup for "how does the forecasted flow for Thursday compare to historical record?"

**Schema:**

| Column | Type | Notes |
|---|---|---|
| `id` | bigint | PK |
| `station_id` | bigint | FK → `stations.id` (USGS station — not NOAA_RFC) |
| `target_date` | date | The forecasted calendar date |
| `source` | varchar(20) | `'NWRFC'` — extensible for other RFC sources |
| `forecast_run_date` | timestamptz | Issuance datetime of the ForecastRun used |
| `forecast_discharge` | numeric(12,4) | Forecasted flow in **cfs** |
| `percentile_rank` | numeric(5,2) | 0–100 exceedance rank vs. full period-of-record |
| `band` | varchar | Same `p0_4`…`p99_100` classification as observed |
| `historical_record_count` | integer | Historical daily_mean records used as baseline |
| `computed_at` | timestamptz | When this row was last computed |

**Unique constraint:** `(station_id, target_date, source)` — one active row per station/date/source. Newer forecast runs overwrite.

**Indexes:** `(target_date)`, `(station_id, target_date)`, `(source, target_date)`

**Important:** `station_id` is the **USGS station** PK, resolved from the NOAA_RFC station via `StationMapping`. Not all NOAA_RFC stations have a USGS mapping — unmapped stations are silently skipped.

**Common queries:**

```sql
-- Forecast bands for all stations for the next 8 days
SELECT s.station_number, s.name, f.target_date, f.forecast_discharge, f.percentile_rank, f.band
FROM forecast_percentiles f
JOIN stations s ON s.id = f.station_id
WHERE f.source = 'NWRFC'
  AND f.target_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '8 days'
ORDER BY f.target_date, s.station_number;

-- Latest forecast run date available
SELECT MAX(forecast_run_date) FROM forecast_percentiles WHERE source = 'NWRFC';

-- Stations with extreme forecasts (p91_95 and above) in the next 3 days
SELECT s.station_number, s.name, f.target_date, f.percentile_rank, f.band
FROM forecast_percentiles f
JOIN stations s ON s.id = f.station_id
WHERE f.source = 'NWRFC'
  AND f.target_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '3 days'
  AND f.band IN ('p91_95', 'p96_98', 'p99_100')
ORDER BY f.target_date, f.percentile_rank DESC;

-- Date range currently in table
SELECT MIN(target_date), MAX(target_date), COUNT(DISTINCT target_date)
FROM forecast_percentiles WHERE source = 'NWRFC';
```

---

### 1.3 `station_metadata`

One row per station. Fixed reference statistics computed across the full period of record. These are the characteristic flow thresholds — not event classifications.

**Schema:**

| Column | Type | Notes |
|---|---|---|
| `id` | bigint | PK |
| `station_id` | bigint | FK → `stations.id` (unique — one row per station) |
| `last_observation_date` | date | Most recent date with a daily_mean observation |
| `record_start_date` | date | Earliest daily_mean observation date |
| `record_end_date` | date | Latest daily_mean observation date |
| `years_on_record` | numeric | Decimal years of record length |
| `daily_observation_count` | integer | Total daily_mean observation rows |
| `record_completeness_pct` | numeric | % of expected daily records present (capped at 100%) |
| `mean_annual_flow_cfs` | numeric | Mean of all daily_mean values in **cfs** |
| `q10_cfs` | numeric | 10th percentile flow threshold in **cfs** |
| `q25_cfs` | numeric | 25th percentile flow threshold in **cfs** |
| `q50_cfs` | numeric | Median flow in **cfs** |
| `q75_cfs` | numeric | 75th percentile flow threshold in **cfs** |
| `q90_cfs` | numeric | 90th percentile flow threshold in **cfs** |
| `computed_at` | timestamptz | When this row was last computed |

**Common queries:**

```sql
-- Station reference stats
SELECT s.station_number, s.name, m.years_on_record, m.record_completeness_pct,
       m.q10_cfs, m.q50_cfs, m.q90_cfs, m.last_observation_date
FROM station_metadata m
JOIN stations s ON s.id = m.station_id
ORDER BY s.station_number;

-- Stations with no observation in the last 30 days (potentially inactive)
SELECT s.station_number, s.name, m.last_observation_date
FROM station_metadata m
JOIN stations s ON s.id = m.station_id
WHERE m.last_observation_date < CURRENT_DATE - INTERVAL '30 days'
ORDER BY m.last_observation_date;

-- Compare today's discharge to quantile thresholds for a station
SELECT
    s.station_number,
    d.discharge AS todays_discharge_cfs,
    m.q10_cfs, m.q50_cfs, m.q90_cfs,
    CASE
        WHEN d.discharge < m.q10_cfs THEN 'Below Q10'
        WHEN d.discharge < m.q50_cfs THEN 'Below median'
        WHEN d.discharge < m.q90_cfs THEN 'Above median'
        ELSE 'Above Q90'
    END AS relative_condition
FROM daily_flow_percentiles d
JOIN stations s ON s.id = d.station_id
JOIN station_metadata m ON m.station_id = d.station_id
WHERE d.date = (SELECT MAX(date) FROM daily_flow_percentiles)
ORDER BY s.station_number;
```

---

## 2. REST API

Base URL: `https://streamflowops.3rdplaces.io/api/v1/`  
Interactive docs: `https://streamflowops.3rdplaces.io/api/v1/docs/`  
Authentication: none required (read-only public data)

---

### 2.1 Observed Percentile Bands

#### `GET /api/v1/observations/discharge/percentile-bands/`

Returns precomputed exceedance percentile bands for all stations on a given date.

**Query parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `date` | `YYYY-MM-DD` | No | Target date. Omit to get the latest available date. |
| `station` | string | No | Filter to a single station number (e.g. `12114500`) |

**Response:**

```json
{
  "date": "2026-05-21",
  "computed_at": "2026-05-21T12:03:14.000Z",
  "count": 702,
  "results": [
    {
      "station_number": "12114500",
      "discharge": 1842.3,
      "percentile_rank": 72.14,
      "band": "p51_75",
      "historical_record_count": 18623
    }
  ]
}
```

**Caching:** Past dates return `Cache-Control: public, max-age=86400` — safe to cache aggressively. Today's date is not cached.

#### `GET /api/v1/observations/discharge/percentile-date-range/`

Returns the min and max dates available in `daily_flow_percentiles`. Use to set rangeslider bounds.

**Response:**

```json
{
  "min_date": "1900-01-01",
  "max_date": "2026-05-21"
}
```

**Caching:** `Cache-Control: public, max-age=3600`

---

### 2.2 Forecast Percentile Bands

#### `GET /api/v1/forecasts/discharge/percentile-bands/`

Returns precomputed percentile bands for NWRFC 8-day forecast values. Covers today through today + 8 days.

**Query parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `source` | string | No | Forecast source. Default: `NWRFC`. Only `NWRFC` is currently populated. |
| `target_date` | `YYYY-MM-DD` | No | Filter to a single forecast date. Omit for all available dates. |

**Response:**

```json
{
  "source": "NWRFC",
  "count": 480,
  "results": [
    {
      "station_number": "12114500",
      "target_date": "2026-05-24",
      "forecast_run_date": "2026-05-21T18:00:00Z",
      "forecast_discharge": 2100.0,
      "percentile_rank": 81.3,
      "band": "p76_85",
      "historical_record_count": 18623
    }
  ]
}
```

#### `GET /api/v1/forecasts/discharge/percentile-date-range/`

Returns the min and max `target_date` values available in `forecast_percentiles`.

**Response:**

```json
{
  "min_date": "2026-05-22",
  "max_date": "2026-05-30"
}
```

---

### 2.3 Station Metadata

#### `GET /api/v1/stations/last-observation/`

Bulk endpoint — returns all stations with their `last_observation_date` in a single response (no pagination). Designed for downstream apps determining "active gage" status.

**Response:**

```json
[
  {
    "station_number": "12114500",
    "name": "GREEN RIVER NEAR AUBURN, WA",
    "agency": "USGS",
    "is_active": true,
    "last_observation_date": "2026-05-21"
  }
]
```

For full station metadata (Q10–Q90 quantiles, record stats) — query the DB directly via `station_metadata` (no REST endpoint currently exists for this table).

---

### 2.4 Analytics Configuration & Run Logs (operational)

These endpoints expose the configuration system itself — useful for monitoring or external automation.

#### `GET /api/v1/statistics-configurations/`

Lists all `StatisticsConfiguration` records with their recent run logs.

```json
{
  "count": 8,
  "results": [
    {
      "id": 1,
      "name": "Daily Observed Percentiles — USGS",
      "computation_type": "daily_flow_percentiles",
      "agency_filter": "USGS",
      "schedule_type": "custom",
      "is_enabled": true,
      "last_run_at": "2026-05-21T18:02:11Z",
      "next_run_at": "2026-05-22T06:00:00Z",
      "recent_logs": [...]
    }
  ]
}
```

#### `GET /api/v1/statistics-computation-logs/`

Lists computation run history — status, duration, stations processed, records computed, errors.

---

### 2.5 Python example — observed bands

```python
import requests

BASE = 'https://streamflowops.3rdplaces.io/api/v1'

# Date range for slider bounds
date_range = requests.get(f'{BASE}/observations/discharge/percentile-date-range/').json()
print(date_range)  # {'min_date': '1900-01-01', 'max_date': '2026-05-21'}

# Latest bands — all stations
resp = requests.get(f'{BASE}/observations/discharge/percentile-bands/').json()
# Build a lookup: station_number → band data
bands = {r['station_number']: r for r in resp['results']}

# Historical date
bands_2020 = requests.get(
    f'{BASE}/observations/discharge/percentile-bands/',
    params={'date': '2020-07-15'}
).json()

# Single station
station = requests.get(
    f'{BASE}/observations/discharge/percentile-bands/',
    params={'date': '2026-05-21', 'station': '12114500'}
).json()
print(station['results'])
```

### 2.6 Python example — forecast bands

```python
# All forecast dates (today → +8 days)
resp = requests.get(f'{BASE}/forecasts/discharge/percentile-bands/').json()

# Group by target_date
from collections import defaultdict
by_date = defaultdict(list)
for r in resp['results']:
    by_date[r['target_date']].append(r)

# Single forecast date
day3 = requests.get(
    f'{BASE}/forecasts/discharge/percentile-bands/',
    params={'target_date': '2026-05-24'}
).json()
```

---

## 3. Band Classification Reference

Both `daily_flow_percentiles` and `forecast_percentiles` use the same 10-band classification. `percentile_rank` is an *exceedance* rank — rank 72 means the discharge is higher than 72% of all historical daily observations for that station.

| Band | Percentile range | Condition | Suggested colour |
|---|---|---|---|
| `p0_4` | ≤ 4 | Much below normal | `#B22222` dark red |
| `p5_10` | 5–10 | Below normal | `#FF4500` orange-red |
| `p11_25` | 11–25 | Below normal | `#FFA500` orange |
| `p26_50` | 26–50 | Normal | `#90EE90` light green |
| `p51_75` | 51–75 | Above normal | `#228B22` forest green |
| `p76_85` | 76–85 | High | `#0D47A1` navy |
| `p86_90` | 86–90 | Very high | `#283593` indigo |
| `p91_95` | 91–95 | Extreme | `#4527A0` deep purple |
| `p96_98` | 96–98 | Severe | `#7B1FA2` purple |
| `p99_100` | > 98 | Exceptional | `#AD1457` magenta |

Stations with fewer than 30 historical daily_mean observations are excluded from results.

---

## 4. How the Analytics Configuration System Works

All computation schedules are managed via **Analytics → Configurations** in the web GUI (`/analytics/configurations/`). There are no hardcoded Celery tasks for percentile computation.

### Active configurations and their station coverage

| Configuration | Computation | Agency | Stations | Schedule | Enabled |
|---|---|---|---|---|---|
| Daily Observed Percentiles — USGS | `daily_flow_percentiles` | USGS | 7,972 | 3×/day (06:00, 12:00, 18:00 UTC) | Yes |
| Daily Observed Percentiles — EC | `daily_flow_percentiles` | EC | 2,047 | 3×/day (06:00, 12:00, 18:00 UTC) | Yes |
| Forecast Percentiles — NWRFC | `forecast_percentiles` | ALL | 10,312 resolved, ~480 with NOAA mapping | Every 6h | Yes |
| Station Metadata and Stats | `station_metadata` | ALL | 10,312 | Annual (October) | Yes |
| Flood thresholds | `flood_thresholds` | ALL | 10,312 | Annual or on-demand | Yes |
| Historical Backfill — USGS | `percentile_backfill` | USGS | 7,972 | Disabled — trigger manually | No |
| Historical Backfill — EC | `percentile_backfill` | EC | 2,047 | Disabled — trigger manually | No |

### Station selection

Analytics configurations use **agency-filter** rather than explicit station lists. All stations matching the agency are included automatically — no manual station selection is needed. This differs from the timeseries pull configurations (which require explicit station selection because acquisition has rate limits).

### Dispatcher

A single Celery Beat task (`dispatch_statistics_computations`) fires hourly and checks which configurations are due based on their cron schedule. It dispatches the appropriate executor task per config. Run history and status are visible at `/analytics/logs/`.

---

## 5. curl / Quick Reference

```bash
BASE=https://streamflowops.3rdplaces.io/api/v1

# Observed: latest date available
curl -s "$BASE/observations/discharge/percentile-date-range/" | python3 -m json.tool

# Observed: all stations today
curl -s "$BASE/observations/discharge/percentile-bands/" | python3 -m json.tool | head -40

# Observed: historical date
curl -s "$BASE/observations/discharge/percentile-bands/?date=2020-07-15" | python3 -m json.tool | head -40

# Observed: single station
curl -s "$BASE/observations/discharge/percentile-bands/?date=2026-05-21&station=12114500" | python3 -m json.tool

# Forecast: all dates
curl -s "$BASE/forecasts/discharge/percentile-bands/" | python3 -m json.tool | head -40

# Forecast: specific date
curl -s "$BASE/forecasts/discharge/percentile-bands/?target_date=2026-05-24" | python3 -m json.tool

# Forecast date range
curl -s "$BASE/forecasts/discharge/percentile-date-range/" | python3 -m json.tool

# Stations with last observation date
curl -s "$BASE/stations/last-observation/" | python3 -m json.tool | head -30

# Analytics configuration status
curl -s "$BASE/statistics-configurations/" | python3 -m json.tool

# Computation run log
curl -s "$BASE/statistics-computation-logs/" | python3 -m json.tool | head -50
```
