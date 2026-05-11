# Daily Flow Percentile Bands — API Implementation Spec

This document is a complete specification for implementing a date-driven flow
conditions map with rangeslider. It describes every API endpoint needed, exact
request/response shapes, caching rules, band semantics, and integration notes.
No prior knowledge of this codebase is assumed.

---

## 1. Context

The Streamflow Dashboard displays a map of active monitoring stations coloured
by their current flow condition (how today's discharge compares to the station's
full period of record). The new feature adds a **date rangeslider** so the user
can scrub backward through time and see historical flow conditions for any past
date.

The backend pre-computes and stores one row per station per date in the
`daily_flow_percentiles` table. A Celery task appends yesterday's data each
morning at 06:00 UTC. A separate backfill command populates all historical dates.

---

## 2. Base URL

All endpoints are under:

```
/api/v1/
```

The API uses Django REST Framework with JSON responses. No authentication is
required (read-only public data).

---

## 3. Endpoints

### 3.1 `GET /api/v1/observations/discharge/percentile-bands/`

Returns precomputed exceedance percentile bands for **all stations** on a given
date (or the latest available date if none is specified).

#### Query Parameters

| Parameter | Type   | Required | Description |
|-----------|--------|----------|-------------|
| `date`    | string | No       | Target date in `YYYY-MM-DD` format. Omit to get the latest date that has data. |
| `station` | string | No       | Filter to a single station number (e.g. `12345678`). |

#### Response — 200 OK

```json
{
  "date": "2024-07-15",
  "computed_at": "2024-07-16T06:03:22.481Z",
  "count": 847,
  "results": [
    {
      "station_number": "12114500",
      "discharge": 1842.3,
      "percentile_rank": 72.14,
      "band": "p51_75",
      "historical_record_count": 18623
    },
    ...
  ]
}
```

#### Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `date` | string (YYYY-MM-DD) | The date the values represent. |
| `computed_at` | string (ISO 8601) or `null` | When the row was computed. `null` if no data exists for this date yet. |
| `count` | integer | Number of station records in `results`. |
| `results` | array | One object per station (see below). |

**Each result object:**

| Field | Type | Description |
|-------|------|-------------|
| `station_number` | string | Station identifier (matches `station_number` in `/api/v1/stations/`). |
| `discharge` | number | Daily mean discharge in cfs for this date. |
| `percentile_rank` | number | 0–100. The percentage of all historical daily_mean observations for this station that were ≤ this discharge value. |
| `band` | string | Discrete condition category (see Section 4). |
| `historical_record_count` | integer | Total daily_mean observations used as the comparison baseline for this station. |

#### Error Responses

| Status | Condition |
|--------|-----------|
| 400    | `date` parameter is not a valid YYYY-MM-DD string. Body: `{"detail": "Invalid date format. Use YYYY-MM-DD."}` |

#### HTTP Caching

- **Past dates** (any date before today): Response includes `Cache-Control: public, max-age=86400`, `ETag`, and `Last-Modified` headers. Data never changes once computed — safe to cache aggressively.
- **Today's date or no-data dates**: No cache headers. Re-fetch as needed.

Implement conditional GET (`If-None-Match` / `If-Modified-Since`) to avoid
redundant data transfer when the user scrubs back to a previously loaded date.

---

### 3.2 `GET /api/v1/observations/discharge/percentile-date-range/`

Returns the minimum and maximum dates for which percentile band data exists.
Use this to set the bounds of the rangeslider on page load.

#### Query Parameters

None.

#### Response — 200 OK

```json
{
  "min_date": "1900-10-01",
  "max_date": "2026-02-27"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `min_date` | string (YYYY-MM-DD) or `null` | Earliest date with any data. `null` if the table is empty. |
| `max_date` | string (YYYY-MM-DD) or `null` | Latest date with any data. `null` if the table is empty. |

#### HTTP Caching

Response includes `Cache-Control: public, max-age=3600`. Refresh at most once
per hour; `max_date` advances by one day each morning after the Celery task runs.

---

### 3.3 `GET /api/v1/stations/` (existing — used for map layer)

Returns station metadata needed to place markers on the map. This endpoint
already exists. Use it to build the base station layer separately from the
percentile layer, so station positions only load once.

#### Relevant Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `is_active` | boolean | Pass `true` to limit to active stations. |
| `limit`    | integer | Page size (max 1000). Pass `limit=1000` to load all at once. |

#### Response Shape (list action)

```json
{
  "count": 923,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 1,
      "station_number": "12114500",
      "name": "GREEN RIVER NEAR AUBURN, WA",
      "agency": "USGS",
      "latitude": "47.32401389",
      "longitude": "-122.2317361",
      "is_active": true
    },
    ...
  ]
}
```

Join on `station_number` to combine station position with percentile band data.

---

## 4. Band Classification

`percentile_rank` is mapped to a discrete `band` label using these thresholds.
Apply the colour mapping to map markers / legend.

| Band key    | Percentile range | Suggested colour | Label |
|-------------|------------------|------------------|-------|
| `p0_4`      | ≤ 4              | `#B22222` (dark red) | Much below normal |
| `p5_10`     | 5 – 10           | `#FF4500` (orange-red) | Below normal |
| `p11_25`    | 11 – 25          | `#FFA500` (orange) | Below normal |
| `p26_50`    | 26 – 50          | `#90EE90` (light green) | Normal |
| `p51_75`    | 51 – 75          | `#228B22` (forest green) | Above normal |
| `p76_85`    | 76 – 85          | `#0D47A1` (navy)        | High |
| `p86_90`    | 86 – 90          | `#283593` (indigo)      | Very high |
| `p91_95`    | 91 – 95          | `#4527A0` (deep purple) | Extreme |
| `p96_98`    | 96 – 98          | `#7B1FA2` (purple)      | Severe |
| `p99_100`   | > 98             | `#AD1457` (magenta)     | Exceptional |

The classification uses inclusive upper bounds:

```python
if   percentile_rank <=  4: band = 'p0_4'
elif percentile_rank <= 10: band = 'p5_10'
elif percentile_rank <= 25: band = 'p11_25'
elif percentile_rank <= 50: band = 'p26_50'
elif percentile_rank <= 75: band = 'p51_75'
elif percentile_rank <= 85: band = 'p76_85'
elif percentile_rank <= 90: band = 'p86_90'
elif percentile_rank <= 95: band = 'p91_95'
elif percentile_rank <= 98: band = 'p96_98'
else:                        band = 'p99_100'
```

Stations with fewer than 30 historical daily_mean observations are excluded from
the results entirely (insufficient data for a meaningful percentile).

---

## 5. Recommended Integration Sequence

### 5.1 On page load

1. `GET /api/v1/observations/discharge/percentile-date-range/`
   — Store `min_date` and `max_date` to configure rangeslider bounds.
   — Cache response for 1 hour (honour the `Cache-Control` header).

2. `GET /api/v1/stations/?is_active=true&limit=1000`
   — Build the base map layer (lat/lng + station_number → marker).
   — Keep this layer separate; it doesn't need to reload on date change.

3. `GET /api/v1/observations/discharge/percentile-bands/`  (no date param)
   — Loads the latest available date.
   — Colour each marker using `band`. Show `percentile_rank` and `discharge`
     in the marker tooltip.

### 5.2 On rangeslider date change

```
GET /api/v1/observations/discharge/percentile-bands/?date=YYYY-MM-DD
```

- Build a lookup map: `station_number → { band, percentile_rank, discharge }`.
- Re-colour all existing map markers. Stations absent from the response
  (no data for that date) should be rendered in a neutral / greyed-out style.
- Display the selected date prominently in the UI.

### 5.3 Debouncing

Debounce rangeslider input by ~300 ms to avoid firing a request on every pixel
of drag. Requests for past dates will hit CDN/browser cache on repeat access.

---

## 6. Data Notes

- **Units**: All `discharge` values are in **cubic feet per second (cfs)**.
- **Coverage**: Not every station has data for every date. Sparse coverage is
  normal for dates before 1950 or for stations with short records.
- **Empty results**: A valid date request may return `"count": 0` if no stations
  had a `daily_mean` observation on that date. This is normal — handle gracefully.
- **Percentile semantics**: `percentile_rank = 72` means this discharge is higher
  than 72% of all historical daily observations for that station. It is an
  *exceedance* rank, not a flow frequency.
- **Ties**: Tied discharge values receive the same percentile rank (count of
  records ≤ the value ÷ total records × 100).

---

## 7. Example Fetch Sequence (JavaScript)

```js
const BASE = '/api/v1';

// Step 1: get slider bounds
const { min_date, max_date } = await fetch(`${BASE}/observations/discharge/percentile-date-range/`)
  .then(r => r.json());

// Step 2: load stations once
const stationsResp = await fetch(`${BASE}/stations/?is_active=true&limit=1000`).then(r => r.json());
const stationMap = Object.fromEntries(
  stationsResp.results.map(s => [s.station_number, s])
);

// Step 3: load bands for a date (or latest)
async function loadBands(date = null) {
  const url = date
    ? `${BASE}/observations/discharge/percentile-bands/?date=${date}`
    : `${BASE}/observations/discharge/percentile-bands/`;
  const data = await fetch(url).then(r => r.json());
  return Object.fromEntries(
    data.results.map(r => [r.station_number, r])
  );
}

// Step 4: on date change (debounced)
const bands = await loadBands('2023-07-15');
for (const [stNum, marker] of Object.entries(mapMarkers)) {
  const b = bands[stNum];
  marker.setStyle({ color: b ? BAND_COLOURS[b.band] : '#cccccc' });
  if (b) marker.setTooltipContent(`${b.discharge} cfs — ${b.percentile_rank}th pct`);
}
```

---

## 8. OpenAPI / Swagger

Interactive docs are available at:

```
/api/v1/docs/
```

The two new endpoints appear under the `observations` tag as:
- `GET /observations/discharge/percentile-bands/`
- `GET /observations/discharge/percentile-date-range/`

---

## 9. Development / Testing

Verify the endpoints are live and returning data:

```bash
# Date range bounds
curl -s http://localhost/api/v1/observations/discharge/percentile-date-range/ | python3 -m json.tool

# Latest date (all stations)
curl -s http://localhost/api/v1/observations/discharge/percentile-bands/ | python3 -m json.tool | head -30

# Specific historical date
curl -s "http://localhost/api/v1/observations/discharge/percentile-bands/?date=2023-07-15" | python3 -m json.tool | head -30

# Single station on a date
curl -s "http://localhost/api/v1/observations/discharge/percentile-bands/?date=2023-07-15&station=12114500" | python3 -m json.tool

# Confirm cache headers are present on past dates
curl -sI "http://localhost/api/v1/observations/discharge/percentile-bands/?date=2023-07-15" | grep -E 'Cache-Control|ETag|Last-Modified'
```

Expected `cache-control` output on a past date:
```
Cache-Control: public, max-age=86400
```
