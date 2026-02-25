# EC BC Gap Fill — Performance Issue & Solutions

## Date: 2026-02-25

## Summary

The "EC Gap Fill 2025+ (BC)" pull configuration is running extremely slowly. Its purpose is to
backfill ~14 months of daily discharge data (2025-01-01 → present) for 307 British Columbia
Environment Canada stations sourced from the WaterOffice CSV API. In the current implementation
the job is fully sequential and is expected to take hours to complete.

---

## Background

After the HYDAT dataset ended at 2024-12-31, a gap-fill configuration was created to bridge
historical HYDAT data with the ongoing WaterOffice real-time feed. Two configurations exist:

| Configuration | Schedule | Date Range | Stations |
|---|---|---|---|
| EC Gap Fill 2025+ (BC) | One-time (immediate) | 2025-01-01 → today | 307 BC |
| EC Daily Current (BC) | Daily @ 06:00 UTC | Last 2 days | 307 BC |

The gap-fill config fires once and is expected to complete before handing off to the daily job.

---

## Architecture

```
Celery Beat (every 5 min)
  └─ scheduled_streamflow_pulls
       └─ execute_pull_configuration.delay(config_id)
            └─ FOR EACH station (307):          ← sequential loop
                 └─ get_wateroffice_daily_mean()
                      └─ WHILE monthly chunks:   ← sequential loop
                           └─ get_wateroffice_realtime_data()  ← HTTP request
                      └─ pandas groupby → daily means
                 └─ bulk_create DischargeObservations
```

**Key files:**
- `src/acquisition/canada_client.py` — WaterOffice HTTP client, monthly chunking, CSV parsing
- `src/acquisition/tasks.py` — Celery task, station loop, data processor dispatch
- `apps/streamflow/management/commands/create_ec_gap_fill_configs.py` — Creates the configurations
- `config/celery.py` — Celery Beat schedule

---

## Performance Bottlenecks

### Bottleneck 1 — Sequential Monthly HTTP Requests (Critical)

**File:** `src/acquisition/canada_client.py`

`get_wateroffice_daily_mean()` fetches data in monthly chunks using a `while` loop. Each iteration
is a blocking HTTP request with a 120-second timeout. Chunks are not parallelized.

For the gap-fill date range (Jan 2025 → Feb 2026):
- 13–14 monthly requests per station
- Each request: up to 120s timeout + up to 3 retries with 4–60s backoff

**Impact:** Station 1 must complete all 13-14 sequential HTTP calls before Station 2 starts.

---

### Bottleneck 2 — Sequential Station Loop (Critical)

**File:** `src/acquisition/tasks.py`

All 307 stations are processed in a `for` loop inside a single Celery task. There is no
per-station sub-task dispatch, no Celery group, and no parallelism. Station N waits for
all preceding stations to fully complete.

---

### Combined Impact

| Factor | Value |
|---|---|
| Stations | 307 |
| Monthly chunks per station | ~14 |
| Total HTTP requests | ~4,300 |
| Per-request timeout | 120 seconds |
| Retry backoff (per failure) | 4–60 seconds × up to 3 retries |
| Processing model | **Fully sequential** |

**Estimated worst-case runtime: 1–4+ hours** depending on WaterOffice API responsiveness.

---

### Bottleneck 3 — Overfetching (Moderate)

Each monthly chunk fetches the full month of 5-minute records even if only 1 day of data is
missing. For a partial current month this may not matter much, but for retries or partial
failures earlier months get re-fetched in full.

---

### Bottleneck 4 — No Progress Visibility (Moderate)

There is no per-station or per-chunk logging during execution. The `DataPullLog` only updates
at the end of the full run. This makes it impossible to distinguish a slow-but-working job
from a hung or failed one without digging into Celery internals.

---

## Proposed Solutions

### Solution A — Parallelize Stations via Celery Groups (Highest Impact)

Refactor `execute_pull_configuration()` to dispatch one sub-task per station using a Celery
`group()` or `chord()`. A parent task manages coordination; each station task handles its own
fetch-and-insert lifecycle independently.

**Estimated speedup:** 5–50x depending on Celery worker concurrency.

**Tradeoffs:**
- Requires refactoring task structure
- Need to handle partial failures (some stations succeed, some fail)
- `DataPullLog` aggregation becomes async — needs a completion callback or polling
- Should confirm WaterOffice does not rate-limit concurrent requests from a single IP

**Sketch:**
```python
# In execute_pull_configuration():
station_tasks = group(
    fetch_station_data.s(config_id, station_id, start_date, end_date)
    for station_id in station_ids
)
result = station_tasks.apply_async()
```

---

### Solution B — Concurrent Monthly Chunks per Station (High Impact)

Within `get_wateroffice_daily_mean()`, replace the sequential `while` loop with concurrent
async HTTP requests using `asyncio` + `aiohttp`, or with a `ThreadPoolExecutor` to stay
synchronous-compatible.

Fetch all 13-14 monthly chunks simultaneously, then merge and aggregate.

**Estimated speedup:** 5–10x per station (reduces 13 sequential waits to ~1 parallel wait).

**Tradeoffs:**
- Increases burst request load to WaterOffice — need to verify rate limits
- `aiohttp` adds a dependency; `ThreadPoolExecutor` is stdlib but less clean
- Pandas aggregation step is unchanged

**Sketch:**
```python
from concurrent.futures import ThreadPoolExecutor

chunks = list(generate_monthly_chunks(start_date, end_date))
with ThreadPoolExecutor(max_workers=4) as pool:
    results = list(pool.map(lambda c: fetch_chunk(station, c), chunks))
all_raw = [r for chunk in results for r in chunk]
```

---

### Solution C — Add Progress Logging (Low Effort, High Value)

Add station-level and chunk-level log entries during execution so the job's progress is
visible without tailing Celery logs.

This does not fix the performance but makes it possible to monitor the job and confirm it
is progressing rather than stalled.

**Implementation:** Add `logger.info()` calls inside the station loop in `tasks.py` and inside
the monthly chunk loop in `canada_client.py`.

---

### Solution D — Limit Gap-Fill to Missing Data Only (Moderate Impact)

Before fetching a monthly chunk, query the `DischargeObservation` table for existing records
in that month for that station. If the month is already fully populated, skip the fetch
entirely.

This makes re-runs and retries much faster, and avoids re-fetching months that were already
successfully backfilled.

**Implementation:** Add a pre-check in `get_wateroffice_daily_mean()` or the station loop in
`tasks.py`.

---

## Recommended Fix Order

1. **Solution C — Progress logging** — Quick win; adds observability immediately with minimal risk.
2. **Solution D — Skip already-populated months** — Protects against slow re-runs and partial failure recovery.
3. **Solution A — Celery station parallelism** — Biggest overall speedup; tackle after C and D are in place so failures are easier to debug.
4. **Solution B — Concurrent chunk fetching** — Layer on top of A for additional speedup if WaterOffice rate limits allow.

---

## Open Questions Before Implementing

- Does WaterOffice rate-limit requests by IP? Need to test concurrent requests before implementing A or B.
- What is the acceptable runtime for the gap-fill job? This determines how aggressively to parallelize.
- Is the job currently still running, or did it stall/timeout? Check `DataPullLog` and Celery worker logs.
- What Celery worker concurrency is configured? If concurrency=1, Solution A requires a config change too.
