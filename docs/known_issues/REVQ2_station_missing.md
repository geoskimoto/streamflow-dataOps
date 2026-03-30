# REVQ2 — Station Not Resolvable via NOAA API

**Date identified:** 2026-03-30
**Status:** Unresolved — station skipped during parquet import

## Problem

`REVQ2` appears in the `nwrfc_forecast_runs.parquet` file (6,496 forecast runs spanning
2003–2026) but cannot be resolved to a `Station` record via the NOAA Water API.

Two resolution attempts are made by `import_parquet_forecasts` / `parquet_forecast_importer.py`:

1. **Direct gauge lookup** — `GET /nwps/v1/gauges/REVQ2` → **404 Not Found**
2. **NWRFC gauge list fallback** — `GET /nwps/v1/gauges?rfc=NWRFC&limit=10000` →
   **504 Gateway Timeout** (endpoint slow; REVQ2 may not appear even when it responds)

There is no corresponding record in `MasterStation` or `Station` tables.

## Likely Cause

The `Q2` suffix in the LID suggests a British Columbia / Canadian station operated under
the NWRFC umbrella. Canadian gauges are sometimes excluded from or inconsistently listed
in the NOAA Water API.

## Impact

All 6,496 forecast runs for REVQ2 are skipped during parquet import. The data remains
in the parquet file and is not lost.

## Resolution Options

1. **Re-attempt API resolution** — Run `import_noaa_rfc_stations --rfc NWRFC` when the
   NOAA API is stable and check if REVQ2 appears. If it does, run the parquet import again
   and REVQ2 will be picked up automatically.

2. **Manual station creation** — Add `MasterStation` and `Station` records directly via
   the Django admin using coordinates sourced from NWRFC or Environment Canada records,
   then re-run the parquet import.

3. **BC station crosswalk** — Check the BC Hydat database or Environment Canada for a
   matching station and add a `StationMapping` linking the REVQ2 LID to the EC station.

## Related Files

- `nwrfc_forecast_runs.parquet` — source data (REVQ2 has 6,496 rows)
- `src/acquisition/parquet_forecast_importer.py` — import service with API resolution logic
- `apps/streamflow/management/commands/import_parquet_forecasts.py` — management command
- `apps/streamflow/management/commands/import_noaa_rfc_stations.py` — RFC station import
