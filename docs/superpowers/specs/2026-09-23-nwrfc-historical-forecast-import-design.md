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
| Forecast runs (distinct `lid` + `issuance_time`) | **3,577,182** |
| Distinct LIDs | 441 |
| Issuance window | 2005-10-01 00:13Z → 2026-09-22 16:24Z |
| Schema | `lid`, `issuance_time`, `sim_time`, `simulation (cfs)` |

The schema matches what `ParquetForecastImporter` already expects. Horizons are
dominated by 9- and 10-day forecasts, so the documented inference rule labels
99.5% of the archive `medium`:

| `forecast_type` | Runs |
|---|---|
| `medium` | 3,559,239 |
| `long` | 15,922 |
| `short` | 2,021 |

Data anomalies to log rather than silently drop: **27 runs have a negative
horizon** (the last forecast point precedes issuance), and **12 runs contain a
single data point**.

> **Correction (measured after implementation).** The first pass of this
> reconnaissance reported 3,596,831 runs, 820 single-point runs, 16,380 `short`
> runs and 1 negative-horizon run. Those figures were wrong. The scan grouped
> rows *within* each parquet row group and summed the results, so every run
> straddling a row-group boundary was counted twice, and its truncated
> fragments were misread as single-point and `short` runs. (The negative-horizon
> undercount was separate: the scan bucketed horizons by rounded days, so
> horizons between −12 h and 0 fell into the `0` bucket.)
>
> The figures above come from streaming the whole file through the implemented
> `iter_forecast_runs`, which merges across boundaries. Verified against ground
> truth on a 60-row-group slice (5,912,700 rows): a single global
> `pandas.groupby` yields 147,267 runs and 0 single-point runs; the streaming
> iterator yields exactly the same; the old per-row-group method yields 147,790
> runs (+523) and 36 spurious single-point runs.
>
> Database-derived figures in this document are unaffected — they came from SQL,
> not the parquet scan.

### The existing database

| Source | Rows | Notes |
|---|---|---|
| `NOAA_RFC` | 89,242 | 294 stations, 2003-07-18 → 2026-09-22 |
| `nwrfc_web` | 36,550 | all 2026; 15,227 are `is_forecast=False` observed rows |

### The overlap — why "overwrite" would not have happened

Roughly **20,000 of 3,577,182** parquet runs (~0.6%) collide with an existing
DB key. The overwhelming majority would be new inserts, and **69,192 existing
`NOAA_RFC` rows have no parquet counterpart**.

(The collision count came from the same per-row-group scan corrected above, so
treat it as approximate — a straddling run matching a DB key was counted twice.
The 69,192 figure is set-based and exact. None of this changes the decision:
the superseded window is deleted outright rather than upserted over, so the
collision count drives nothing.)

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
| `COQO3`/`SKMW1`/`WDHN2` (absent from archive) | Exclude from the delete; preserve their 708 runs |

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
- Log the 27 negative-horizon runs and 12 single-point runs rather than dropping them.

### 3. Back up, then delete

Scoped precisely to the archive's coverage window:

| Band | Rows | Action |
|---|---|---|
| `NOAA_RFC` before 2005-10-01 00:13Z | 411 | **keep** (2003-07-18 → 2005-09-30, predates archive) |
| `NOAA_RFC` inside window | 88,831 | |
| — of which `COQO3`/`SKMW1`/`WDHN2` | 708 | **keep** (absent from archive, see below) |
| — remainder | **88,123** | **delete** |
| `NOAA_RFC` after window | 0 | — |
| `nwrfc_web` | 36,550 | **untouched** |

The delete covers the **whole archive window**, not just the 2026 pull-time
rows. The ~20.5k pre-2026 rows inside the window are deleted too, even though
they would have upserted correctly, because:

- they are byte-identical to the parquet and are immediately re-imported, so
  nothing is lost;
- it makes the load a clean insert with no mixed insert/update path;
- it resolves the 69 colliding runs whose horizon-inferred `forecast_type`
  disagrees with the stored label. Under an upsert those 69 would have created
  *duplicates* rather than overwriting, because `forecast_type` is part of the
  unique key.

`nwrfc_web` is left alone: different source, different provenance (scraper,
carries `is_forecast=False` observed rows), and its configuration is disabled.

Three stations with existing `NOAA_RFC` forecasts have no parquet presence —
`COQO3` (239 runs), `SKMW1` (236), `WDHN2` (233). All 708 are 2026 live pulls
collected since 2026-02-07, and NWRFC does not carry these gauges in the
archive, so a window delete would remove them with nothing to replace them.
The NWPS API only serves the *current* forecast, so they cannot be re-fetched.

**These three LIDs are excluded from the delete.** Their 708 runs retain
pull-time-keyed `run_date`s — inconsistent with the rest of the table, but the
data is real and otherwise unrecoverable. Once the `run_date` fix lands, new
pulls for these stations key on issuance time like everything else.

This makes the delete **88,123 rows** rather than 88,831.

Dump the 88,831 rows to a compressed file before deleting so the operation is
reversible. Pause Celery Beat during the swap so no pull can write mid-delete.

### 4. Import

3,577,182 runs across 441 LIDs. Estimated growth ~6-7 GB (database 19 GB →
~26 GB, against 36 GB free). Run under `nohup`.

### 5. Verify

- `NOAA_RFC` row count reconciles to 3,577,182 imported + 411 preserved
  pre-window + 708 preserved orphan-station rows, less any runs the importer
  reports as failed. Any shortfall must be explained, not rounded past.
- The only `NOAA_RFC` rows retaining microsecond-precision `run_date` are the
  708 belonging to `COQO3`, `SKMW1`, `WDHN2`.
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
