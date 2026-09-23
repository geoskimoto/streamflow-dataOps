# NWRFC Historical Forecast Archive Import — Design

**Date:** 2026-09-23
**Status:** Approved, ready for implementation planning
**Source file:** `/home/geoskimoto/projects/resid-cast/all_nwrfc_forecasts_WY2006_2026.parquet` (590 MB)

---

## Goal

Import the complete NWRFC historical deterministic streamflow forecast archive
(water years 2006–2026) into `forecast_runs`, and correct the `run_date` key
semantics that currently prevent the archive from superseding the rows the live
Celery pull has been writing.

---

## Reconnaissance findings

All figures below were measured directly, not estimated. The scan script is
read-only and streamed all 1,487 row groups.

### The parquet

| Property | Value |
|---|---|
| Value rows | 144,269,656 |
| Forecast runs (distinct `lid` + `issuance_time`) | **3,596,831** |
| Distinct LIDs | 441 |
| Issuance window | 2005-10-01 00:13Z → 2026-09-22 16:24Z |
| Schema | `lid`, `issuance_time`, `sim_time`, `simulation (cfs)` |

The schema matches what `ParquetForecastImporter` already expects. Horizons are
dominated by 10-day (3,193,151 runs) and 9-day (383,132 runs) forecasts, so the
documented inference rule labels 99.1% of the archive `medium`.

Data anomalies to log rather than silently drop: one run has a **negative
horizon** (−4 days), and 820 runs contain a **single data point**.

### The existing database

| Source | Rows | Notes |
|---|---|---|
| `NOAA_RFC` | 89,242 | 294 stations, 2003-07-18 → 2026-09-22 |
| `nwrfc_web` | 36,550 | all 2026; 15,227 are `is_forecast=False` observed rows |

### The overlap — why "overwrite" would not have happened

Only **20,162 of 3,596,831** parquet runs (0.6%) collide with an existing DB
key. **3,576,669 would be new inserts**, and **69,192 existing `NOAA_RFC` rows
have no parquet counterpart**.

The cause is a key-semantics split within `NOAA_RFC`:

- **Pre-2026 rows (21,185)** were populated from this same NWRFC archive. Their
  `run_date` is the true issuance time, at clean minute precision
  (e.g. `2010-01-01 18:07:00`). These collide correctly. Four were compared
  point-for-point against the parquet and are **byte-identical**, so
  overwriting them is a genuine no-op.
- **2026 rows (68,265)** come from the live Celery pull, whose `run_date`
  records **when we fetched**, not when NWRFC issued. 68,057 of them carry
  microsecond precision, and there are 68,161 *distinct* `run_date` values
  across 68,265 rows.

Because the parquet's issuance times can never match a pull timestamp, an
upsert import would leave every 2026 forecast stored twice — once keyed on
issuance, once on pull time — with no field distinguishing them. The archive
also runs *later* than the last pull (16:24Z vs 10:30Z on 2026-09-22), so it
fully covers the period.

**Conclusion: overwriting is safe, but an upsert alone cannot do it. The
superseded rows must be explicitly deleted.**

### Root cause of the `run_date` defect

`NOAAClient.get_rfc_forecast()` reads `forecast.get("issueTime")`. The NWPS API
field is **`issuedTime`**. The lookup always returns `None`, so every pull falls
through to `datetime.now(timezone.utc)`.

Verified against the live API:

```
WTLO3 issuedTime = '2026-09-22T15:26:00Z'   (issueTime → None)
CHDW1 issuedTime = '2026-09-22T15:27:00Z'   (issueTime → None)
```

`issuedTime` is clean minute precision — the same format as the parquet's
`issuance_time`. Fixing the field name aligns live pulls with the archive key
exactly.

The defect was masked by a bare `except:` that substitutes `now()` without
logging.

### Two blockers in the existing importer

1. **The upsert key does not match the schema.** `_flush_batch` calls
   `bulk_create(unique_fields=["station","source","run_date","forecast_type"])`,
   but the real index is
   `unique_forecast_run (station_id, source, run_date, forecast_type, is_forecast)`.
   Confirmed in a rolled-back transaction:
   `ProgrammingError: there is no unique or exclusion constraint matching the ON CONFLICT specification`.

2. **That failure is silent.** `_flush_batch` catches the exception and returns
   `(0, 0)`, so a completely failed run prints `upserted: 0, failed: 0` and
   reads as a successful no-op.

Separately, the importer does `pd.read_parquet()` across all 144M rows and then
`.iterrows()` per group. With 9 GB RAM free, the load alone will not fit, and
`iterrows` at this scale is not viable.

---

## Decisions

| Decision | Choice |
|---|---|
| 2026 pull-time-keyed rows | Delete; the parquet is authoritative |
| 150 unmapped LIDs | Create `Station` records with `is_active=False` |
| `run_date` defect | Fix as part of this work, before the import |
| `forecast_type` rule | Keep the documented horizon rule unchanged |

`is_active=False` matches how the existing 366 `NOAA_RFC` stations are already
flagged and keeps the new stations out of pull configurations and active-station
counts. Per `CLAUDE.md`, `skip_inactive_stations` must stay off for NWRFC
configs or those pulls would silently empty.

---

## Implementation

### 1. Fix `run_date` semantics

**`src/acquisition/noaa_client.py`**

- Read `issuedTime`, falling back to `issueTime` in case the field name varies
  by endpoint.
- Replace the bare `except:` with `except ValueError`, logging the unparseable
  value.
- When no issuance time can be determined, **skip the run** rather than invent a
  key from `now()`. Fabricating a key is what produced 68k mis-keyed rows.

**`src/acquisition/tasks.py`** (the `NOAA_RFC` branch, ~line 180)

- Replace `ForecastRun.objects.create(...)` with `update_or_create` keyed on the
  full unique tuple.
- Pass `forecast_type` explicitly. Today it defaults to `short` for every live
  row regardless of horizon, which is inconsistent with the archive's `medium`.

### 2. Rewrite `ParquetForecastImporter`

- **Correct `unique_fields`** to include `is_forecast`.
- **Let flush failures propagate.** No silent `(0, 0)`.
- **Stream** via `pyarrow.ParquetFile.read_row_groups()` with `group_by`
  aggregation instead of loading the frame. A single `(lid, issuance_time)`
  group can straddle a row-group boundary, so runs must be buffered across
  boundaries and only emitted once complete.
- **Create new stations as `is_active=False`.**
- Log the negative-horizon run and single-point runs rather than dropping them.

### 3. Back up, then delete

Scoped precisely to the archive's coverage window:

| Band | Rows | Action |
|---|---|---|
| `NOAA_RFC` before 2005-10-01 00:13Z | 411 | **keep** (2003-07-18 → 2005-09-30, predates archive) |
| `NOAA_RFC` inside window | **88,831** | **delete** |
| `NOAA_RFC` after window | 0 | — |
| `nwrfc_web` | 36,550 | **untouched** |

`nwrfc_web` is left alone: different source, different provenance (scraper,
carries `is_forecast=False` observed rows), and its configuration is disabled.

Dump the 88,831 rows to a compressed file before deleting so the operation is
reversible. Pause Celery Beat during the swap so no pull can write mid-delete.

### 4. Import

3,596,831 runs across 441 LIDs. Estimated growth ~6-7 GB (database 19 GB →
~26 GB, against 36 GB free). Run under `nohup`.

### 5. Verify

- Run count matches 3,596,831 plus the 411 preserved pre-window rows.
- No `NOAA_RFC` row retains microsecond-precision `run_date`.
- Spot-check restored runs against the parquet point-for-point.
- One live pull cycle produces issuance-keyed rows that upsert cleanly rather
  than inserting duplicates.

---

## Testing

Tests written before implementation:

- `issuedTime` parsing, including missing and malformed values, which must
  log and skip rather than substitute `now()`.
- Corrected `unique_fields` upsert exercised against the real constraint.
- Row-group-straddling group assembly.
- Horizon → `forecast_type` inference at the 7-day and 10-day boundaries.
- Negative-horizon and single-point runs are logged, not silently dropped.

Then `--dry-run`, then a single-station `--station CHDW1` import, before the
full load.

Per the recorded baseline, roughly 311 tests already fail on clean `main`.
Regressions are proven by diffing failure sets, not by expecting green.

---

## Deployment note

**This working tree is production.** Importer and client changes are developed
in a separate worktree and merged only after tests pass. The delete-and-load is
executed here afterwards, with Celery Beat paused for the swap.

## Risks

| Risk | Mitigation |
|---|---|
| Delete removes data the archive doesn't replace | Window boundaries measured exactly; 411 pre-window rows explicitly preserved; full dump taken first |
| Import fails partway, leaving a gap | Backup dump enables restore; importer is idempotent via corrected upsert |
| Disk exhaustion during load | ~7 GB needed against 36 GB free; monitor during run |
| A pull writes during the swap | Celery Beat paused |
| 150 new stations alter pull behaviour | Created `is_active=False`; NWRFC configs keep `skip_inactive_stations` off |
