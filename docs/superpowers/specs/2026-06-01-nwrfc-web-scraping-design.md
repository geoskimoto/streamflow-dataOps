# NWRFC Website Scraping — Design Spec
**Date:** 2026-06-01  
**Status:** Approved  
**Project:** StreamflowOps + USGS Streamflow Dashboard

---

## Problem Statement

The NOAA Water API (`api.water.noaa.gov/nwps/v1`) does not serve Canadian NWRFC stations (Q2 suffix, ~30 BC stations). All return 404. Additionally, the API provides only a 6–8 day forecast horizon while the NWRFC website (`textPlot.cgi`) provides 10-day deterministic forecasts for all stations — US and Canadian alike. This feature adds a web scraping path to StreamflowOps to capture the full 10-day forecast from the NWRFC website and expose Canadian BC stations in the dashboard.

---

## Architecture Overview

```
NWRFC website (textPlot.cgi)
    ↓
src/acquisition/nwrfc_web_client.py   ← new scraper
    ↓
tasks.py  _process_single_station()   ← new dispatch branch (data_source='nwrfc_web')
    ↓
ForecastRun (existing model)          ← source='nwrfc_web', is_forecast=True/False
    ↓
REST API  /api/v1/stations/{lid}/forecasts/?source=nwrfc_web
    ↓
Dashboard  →  replaces NOAA API as primary NWRFC forecast source
```

**Scope:** All ~290 NWRFC stations (US + Canadian Q2). Canadian BC stations additionally require `Station` records and `StationMapping` entries connecting NWRFC LIDs to EC gauge IDs.

---

## Section 1: NWRFCWebClient Scraper

**File:** `src/acquisition/nwrfc_web_client.py`

**Endpoint:** `https://www.nwrfc.noaa.gov/station/flowplot/textPlot.cgi?id={LID}&pe=QR`

Returns an HTML table with rows at 6-hour intervals covering ~10 days of recent observed values followed by a 10-day deterministic forecast.

### Responsibilities

| Method | Purpose |
|---|---|
| `fetch(lid)` | GET the page; raise on HTTP error; return raw HTML |
| `parse(html, scrape_time)` | Extract rows via BeautifulSoup; tag each row as observed or forecast based on whether its timestamp is before/after `scrape_time` |
| `to_forecast_run_data(rows)` | Return `[{"date": "ISO-Z", "value": float_cfs, "is_forecast": bool}, ...]` |

### Key Decisions

- **Units:** Page returns CFS — no conversion needed.
- **Missing values:** Rows with `"---"` or unparseable values are skipped and logged (not silently dropped).
- **Observed/forecast split:** Each row's timestamp is compared to `scrape_time` (UTC). Rows before → `is_forecast=False`; rows at or after → `is_forecast=True`.
- **Rate limiting:** `asyncio.sleep(0.5)` between station requests.
- **Caching:** None at scraper level — `PullConfiguration` controls run frequency.
- **Error handling:** HTTP errors and parse failures raise with the LID in the message for traceability.

---

## Section 2: StreamflowOps Model & Task Changes

### ForecastRun model additions (new migration)

```python
source = CharField(
    max_length=20,
    choices=[('noaa_api', 'NOAA API'), ('nwrfc_web', 'NWRFC Website')],
    default='noaa_api',
)
is_forecast = BooleanField(default=True)
```

- `source` distinguishes the data origin for downstream consumers.
- `is_forecast=False` marks observed rows scraped from the same `textPlot.cgi` response.
- Existing `ForecastRun` rows default to `source='noaa_api'`, `is_forecast=True` — no backfill needed.

### PullConfiguration addition

Add `'nwrfc_web'` to `DATA_SOURCE_CHOICES`. No other model changes.

### tasks.py dispatch

New branch in `_process_single_station()`:

```python
elif config.data_source == 'nwrfc_web':
    rows = nwrfc_web_client.fetch_and_parse(station.noaa_lid)
    _save_forecast_run(station, rows, source='nwrfc_web')
```

### `_save_forecast_run()` helper (new or extend existing)

- Splits rows into observed list (`is_forecast=False`) and forecast list (`is_forecast=True`).
- Creates **two** `ForecastRun` records per scrape — one for each group — keyed on `(station, run_date, source, is_forecast)`.
- Each record stores its subset as JSON: `[{"date": "ISO-Z", "value": float_cfs}, ...]`.

### Celery beat

One new `PeriodicTask`: `nwrfc_web_pull`, every 6 hours, targeting a `PullConfiguration` with `data_source='nwrfc_web'` and `agency_filter='NOAA_RFC'`.

---

## Section 3: Canadian Station Records & Mappings

### What already exists

- `CanadaClient` (`src/acquisition/canada_client.py`) — full EC data fetcher, operational.
- `import_bc_stations.py` — imports EC stations into StreamflowOps.
- `StationMapping` model — supports flexible `source_agency → target_agency` mapping.
- Known gap documented in `docs/known_issues/REVQ2_station_missing.md`.

### What needs to be built

**New management command: `map_nwrfc_to_ec_stations`**

1. Pull all NWRFC Q2-suffix LIDs from `PullConfiguration` station list.
2. Pull BC EC stations via `CanadaClient.list_stations(province='BC')`.
3. Match by nearest coordinate within a 5 km tolerance threshold.
4. Write `StationMapping` rows:
   - `source_agency='NOAA_RFC'`, `source_id='REVQ2'`
   - `target_agency='EC'`, `target_id='08MF005'`
5. Print unmatched stations to stdout for manual review.

No new model fields needed — `StationMapping` handles this cleanly.

**One-time seeding:** Run `import_bc_stations` first to ensure EC `Station` records exist, then run `map_nwrfc_to_ec_stations` to create mappings.

---

## Section 4: Dashboard Integration

### `dataops_adapter`

New API client method `get_nwrfc_web_forecasts(site_id, num_runs=5)` calling the StreamflowOps REST endpoint with `source=nwrfc_web` filter.

### `data_manager.py`

New method `get_nwrfc_forecasts(site_id)`:
- Tries `nwrfc_web` source first.
- Falls back to `noaa_api` source if empty (ensures continuity during rollout and for any stations not yet scraped).

### `viz_manager.py`

No changes needed — existing `_add_resid_cast_overlay()` trace rendering works for any forecast data in the same schema. The 10-day horizon will automatically show more trace data.

### Canadian BC stations on map

Once `StationMapping` entries are populated and `Station` records exist with EC gauge IDs, the dashboard's existing map logic picks them up automatically — no map code changes needed.

### Feature flag

New env var `USE_NWRFC_WEB_FORECASTS=true` in dashboard `.env`. When `false`, existing NOAA API path remains active unchanged.

---

## Section 5: Testing

### Unit tests — `src/acquisition/tests/test_nwrfc_web_client.py`

- Parse valid HTML table → correct `[{"date", "value", "is_forecast"}]` output
- Rows with `"---"` values are skipped and logged, not silently dropped
- Observed/forecast split assigns correct `is_forecast` value at timestamp boundary
- HTTP error raises with LID in message

### Integration tests (marked, off by default)

- Live fetch for `REVQ2` (Canadian) returns non-empty data
- Live fetch for `DAID1` (US) returns non-empty data

### Management command tests

- `map_nwrfc_to_ec_stations --dry-run` produces expected match/no-match counts
- Coordinate matching respects 5 km distance threshold; stations beyond threshold are unmatched

### Dashboard tests

- `get_nwrfc_forecasts()` falls back to `noaa_api` source when `nwrfc_web` returns empty
- `USE_NWRFC_WEB_FORECASTS=false` keeps existing behavior unchanged

---

## Implementation Order

1. `ForecastRun` migration (`source`, `is_forecast` fields)
2. `NWRFCWebClient` scraper + unit tests
3. `PullConfiguration` new choice + `tasks.py` dispatch + `_save_forecast_run()`
4. Celery beat `PeriodicTask` registration
5. `map_nwrfc_to_ec_stations` management command
6. Seed BC stations (`import_bc_stations`) + run crosswalk command
7. Dashboard: `get_nwrfc_web_forecasts()` + `get_nwrfc_forecasts()` with fallback + feature flag

---

## Open Questions / Out of Scope

- **resid-cast integration:** Low priority; resid-cast will continue using NOAA API until explicitly updated.
- **Historical scraping:** `textPlot.cgi` only serves current forecast window; no backfill of historical forecasts is planned.
- **EC observation data for BC stations:** `CanadaClient` can fetch observations for BC EC gauges, but scheduling EC observation pulls is out of scope for this spec.
