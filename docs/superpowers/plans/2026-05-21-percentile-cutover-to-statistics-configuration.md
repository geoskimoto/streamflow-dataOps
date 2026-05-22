# Percentile Cutover to StatisticsConfiguration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the two hardcoded Celery beat percentile tasks with fully user-configurable `StatisticsConfiguration`-driven tasks (daily observed, forecast, and historical backfill), then surgically remove every piece of the old `ScheduledComputation`/`ComputationLog` system.

**Architecture:** Extend the existing `StatisticsConfiguration` dispatcher pattern (already used for `station_metadata` and `flood_thresholds`) with three new computation types: `daily_flow_percentiles`, `forecast_percentiles`, and implement the already-defined-but-unimplemented `percentile_backfill`. New Celery task executor functions mirror the existing `run_station_metadata_task` pattern: they receive a `config_id`, resolve stations via `config.get_station_queryset()`, call the existing computation functions in `src/analytics/percentiles.py` (extended with an optional station filter), and write `StatisticsComputationLog` entries. Five standard configurations are seeded via data migration. The old `ScheduledComputation`/`ComputationLog` models, their two tasks, and their hardcoded beat entries are removed entirely.

**Tech Stack:** Django 4.2, Celery, PostgreSQL, psycopg2, croniter; models in `apps/analytics/` and `apps/streamflow/`; computation logic in `src/analytics/percentiles.py`; tasks in `src/analytics/tasks.py`

---

## File Map

| File | Change |
|------|--------|
| `src/analytics/percentiles.py` | Add optional `station_ids` param to `compute_percentile_for_date` and `compute_forecast_percentiles` |
| `apps/analytics/models.py` | Add `daily_flow_percentiles` and `forecast_percentiles` to `COMPUTATION_TYPE_CHOICES`; remove `ScheduledComputation` and `ComputationLog` classes |
| `apps/analytics/admin.py` | Remove `ScheduledComputation` and `ComputationLog` registrations and imports |
| `src/analytics/tasks.py` | Add 3 new executor tasks; wire dispatcher; remove 2 old tasks, 2 constants, and old imports |
| `config/celery.py` | Remove 2 hardcoded beat entries (`compute-daily-flow-percentiles`, `compute-forecast-percentile-bands`) |
| `apps/analytics/migrations/0007_add_percentile_computation_types.py` | Schema migration: new `computation_type` choices |
| `apps/analytics/migrations/0008_remove_scheduled_computation.py` | Schema migration: drop `computation_logs` and `scheduled_computations` tables |
| `apps/analytics/migrations/0009_seed_percentile_configurations.py` | Data migration: seed 5 standard `StatisticsConfiguration` records + delete orphaned Celery Beat periodic tasks |
| `tests/test_analytics_tasks.py` | Remove tests for old tasks; add tests for new executor tasks, updated computation functions, and dispatcher routing |

---

## Context for Implementers

### Existing computation functions (in `src/analytics/percentiles.py`)

**`compute_percentile_for_date(target_date)`** — One SQL query. Gets all stations that have a `daily_mean` observation on `target_date`, compares each discharge to the full period-of-record, returns a list of dicts:
```
{station_id, station_number, discharge, observation_date, historical_record_count, percentile_rank, band}
```

**`compute_forecast_percentiles(source='NWRFC', max_days=8)`** — Gets latest NOAA_RFC ForecastRun per station, maps NOAA_RFC → USGS via `StationMapping`, compares forecast discharges to USGS historical daily_mean, returns list of dicts:
```
{station_id, target_date, forecast_discharge, source, forecast_run_date, historical_record_count, percentile_rank, band}
```

**`backfill_station_chunk(station_ids, computed_at)`** — Window-function SQL for ALL historical daily_mean observations for given station IDs. Returns list of dicts:
```
{station_id, obs_date, discharge, historical_record_count, percentile_rank, band, computed_at}
```

**`iter_station_id_chunks(chunk_size=100, station_ids=None)`** — Generator. Yields lists of station IDs chunked by `chunk_size`. If `station_ids=None`, queries all stations with ≥30 daily_mean records. If `station_ids` is provided, chunks that list directly (the `backfill_station_chunk` SQL has its own `HAVING COUNT(*) >= 30` guard).

### Existing pattern for executor tasks

All existing executor tasks follow this exact structure:
1. `config = StatisticsConfiguration.objects.get(id=config_id)`
2. `station_ids = list(config.get_station_queryset().values_list('id', flat=True))`
3. Create `StatisticsComputationLog` with `status='running'`
4. `start_time = time.monotonic()`
5. Call computation function
6. Bulk create/upsert model records
7. Update log with `status='success'`, `stations_processed`, `records_computed`, `duration_seconds`
8. `StatisticsConfiguration.objects.filter(id=config_id).update(last_run_at=timezone.now())`

See `run_station_metadata_task` in `src/analytics/tasks.py` lines 308–347 for the exact pattern to replicate.

### Key model facts
- `DailyFlowPercentile`: unique on `(station, date)` — in `apps/streamflow/models.py`
- `ForecastPercentile`: unique on `(station, target_date, source)` — in `apps/streamflow/models.py`
- `StatisticsConfiguration.get_station_queryset()` returns all stations when `agency_filter='ALL'` and no explicit station overrides exist
- `_INSERT_BATCH = 5_000` is already defined at module level in `src/analytics/tasks.py`

### What NOT to touch
- `compute_percentile_for_date`, `backfill_station_chunk`, `iter_station_id_chunks`, `compute_forecast_percentiles` — only add the optional parameter; do not change existing logic
- `DailyFlowPercentile`, `ForecastPercentile` — do not modify these models
- `StatisticsConfigurationForm` in `apps/analytics/forms.py` — no changes needed; ModelForm reads choices from model automatically
- Any analytics views or templates — no changes needed
- `ScheduledComputation` data migration files (`0002`, `0004`) — leave these as-is; the model removal migration handles the table drop

---

## Task 1: Add `station_ids` Filter to `compute_percentile_for_date`

**Files:**
- Modify: `src/analytics/percentiles.py`
- Test: `tests/test_analytics_tasks.py`

- [ ] **Step 1: Write the failing tests**

Add a new test class to `tests/test_analytics_tasks.py`. Place it after the existing `StatisticsDispatcherTest` class.

```python
class ComputePercentileForDateFilterTest(TestCase):
    """Tests for the optional station_ids filter on compute_percentile_for_date."""

    def setUp(self):
        self.station_a = make_station('FILTER_A', 'USGS')
        self.station_b = make_station('FILTER_B', 'EC')
        start = date(2020, 1, 1)
        # Both stations get 60 days of history (> 30 minimum threshold)
        add_daily_obs(self.station_a, start, 60)
        add_daily_obs(self.station_b, start, 60)

    def test_no_filter_returns_both_stations(self):
        from src.analytics.percentiles import compute_percentile_for_date
        results = compute_percentile_for_date(date(2020, 2, 29))
        ids = {r['station_id'] for r in results}
        self.assertIn(self.station_a.id, ids)
        self.assertIn(self.station_b.id, ids)

    def test_station_ids_restricts_to_specified_stations(self):
        from src.analytics.percentiles import compute_percentile_for_date
        results = compute_percentile_for_date(
            date(2020, 2, 29),
            station_ids=[self.station_a.id],
        )
        ids = {r['station_id'] for r in results}
        self.assertIn(self.station_a.id, ids)
        self.assertNotIn(self.station_b.id, ids)

    def test_empty_station_ids_returns_no_results(self):
        from src.analytics.percentiles import compute_percentile_for_date
        results = compute_percentile_for_date(date(2020, 2, 29), station_ids=[])
        self.assertEqual(results, [])

    def test_none_station_ids_computes_all(self):
        from src.analytics.percentiles import compute_percentile_for_date
        results_none = compute_percentile_for_date(date(2020, 2, 29), station_ids=None)
        results_default = compute_percentile_for_date(date(2020, 2, 29))
        # Both should return the same station count
        self.assertEqual(
            {r['station_id'] for r in results_none},
            {r['station_id'] for r in results_default},
        )
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/streamflow/streamflow-dataOps/streamflow-dataOps
sudo -u streamflow venv/bin/python manage.py test tests.test_analytics_tasks.ComputePercentileForDateFilterTest --keepdb 2>&1 | tail -20
```

Expected: `TypeError: compute_percentile_for_date() got an unexpected keyword argument 'station_ids'`

- [ ] **Step 3: Implement the `station_ids` parameter**

In `src/analytics/percentiles.py`, replace the entire `compute_percentile_for_date` function (lines 44–118) with:

```python
def compute_percentile_for_date(
    target_date: date,
    station_ids: list[int] | None = None,
) -> list[dict]:
    """
    Compute exceedance percentile bands for stations with a daily_mean observation
    on ``target_date``, comparing each value against the station's full period of record.

    Uses one SQL query (no per-station round-trips).

    Args:
        target_date: Date to compute percentiles for.
        station_ids: Optional list of Station PKs to restrict computation to.
                     Pass None to compute all qualifying stations.
                     Pass [] to compute none.

    Returns:
        List of dicts with keys:
            station_id, station_number, discharge, observation_date,
            historical_record_count, percentile_rank, band
    """
    if station_ids is not None:
        station_filter = "AND station_id = ANY(%(station_ids)s)"
    else:
        station_filter = ""

    sql = f"""
        WITH obs_on_date AS (
            -- One row per station for the target date (take latest if multiple)
            SELECT DISTINCT ON (station_id)
                station_id,
                discharge,
                observed_at::date AS observation_date
            FROM discharge_observations
            WHERE type = 'daily_mean'
              AND observed_at::date = %(target_date)s
              {station_filter}
            ORDER BY station_id, observed_at DESC
        )
        SELECT
            s.id                AS station_id,
            s.station_number,
            o.discharge,
            o.observation_date,
            COUNT(h.id)         AS historical_record_count,
            ROUND(
                COUNT(h.id) FILTER (WHERE h.discharge <= o.discharge) * 100.0
                / NULLIF(COUNT(h.id), 0),
            2)                  AS percentile_rank
        FROM obs_on_date o
        JOIN stations s
            ON s.id = o.station_id
        JOIN discharge_observations h
            ON h.station_id = o.station_id
           AND h.type = 'daily_mean'
        GROUP BY
            s.id,
            s.station_number,
            o.discharge,
            o.observation_date
        HAVING COUNT(h.id) >= %(min_records)s
        ORDER BY s.station_number
    """

    params: dict = {"target_date": target_date, "min_records": MIN_HISTORICAL_RECORDS}
    if station_ids is not None:
        params["station_ids"] = station_ids

    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        columns = [col[0] for col in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]

    results = []
    for row in rows:
        rank = float(row["percentile_rank"])
        results.append({
            "station_id":              row["station_id"],
            "station_number":          row["station_number"],
            "discharge":               row["discharge"],
            "observation_date":        row["observation_date"],
            "historical_record_count": int(row["historical_record_count"]),
            "percentile_rank":         rank,
            "band":                    classify_band(rank),
        })

    logger.info(
        "compute_percentile_for_date(%s, station_ids=%s): %d stations",
        target_date,
        "all" if station_ids is None else len(station_ids),
        len(results),
    )
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
sudo -u streamflow venv/bin/python manage.py test tests.test_analytics_tasks.ComputePercentileForDateFilterTest --keepdb 2>&1 | tail -10
```

Expected: `Ran 4 tests in X.XXXs` `OK`

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
sudo -u streamflow venv/bin/python manage.py test --keepdb 2>&1 | tail -10
```

Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
cd /home/streamflow/streamflow-dataOps/streamflow-dataOps
git add src/analytics/percentiles.py tests/test_analytics_tasks.py
git commit -m "feat: add optional station_ids filter to compute_percentile_for_date"
```

---

## Task 2: Add `station_ids` Filter to `compute_forecast_percentiles`

**Files:**
- Modify: `src/analytics/percentiles.py`
- Test: `tests/test_analytics_tasks.py`

- [ ] **Step 1: Write the failing tests**

Add this class after `ComputePercentileForDateFilterTest` in `tests/test_analytics_tasks.py`:

```python
class ComputeForecastPercentilesFilterTest(TestCase):
    """Tests for the optional station_ids filter on compute_forecast_percentiles."""

    def setUp(self):
        from apps.streamflow.models import ForecastRun, StationMapping, MasterStation
        self.noaa_station = make_station('NWRFC001', 'NOAA_RFC')
        self.usgs_station_a = make_station('14211010', 'USGS')
        self.usgs_station_b = make_station('14246900', 'USGS')

        # Give USGS stations historical discharge data
        start = date(2020, 1, 1)
        add_daily_obs(self.usgs_station_a, start, 60)
        add_daily_obs(self.usgs_station_b, start, 60)

        # Create NOAA_RFC → USGS station mappings
        StationMapping.objects.create(
            source_agency='NOAA_RFC',
            source_id=self.noaa_station.station_number,
            target_agency='USGS',
            target_id=self.usgs_station_a.station_number,
        )

        # Create a ForecastRun for the NOAA station with data for the next 3 days
        today = date.today()
        ForecastRun.objects.create(
            station=self.noaa_station,
            source='NOAA_RFC',
            run_date=today,
            forecast_type='short',
            data=[
                {'date': (today + timedelta(days=i)).isoformat(), 'value': 1000.0 + i * 10}
                for i in range(1, 4)
            ],
        )

    def test_station_ids_none_returns_all_mappable_stations(self):
        from src.analytics.percentiles import compute_forecast_percentiles
        results = compute_forecast_percentiles(source='NWRFC', max_days=4, station_ids=None)
        ids = {r['station_id'] for r in results}
        self.assertIn(self.usgs_station_a.id, ids)

    def test_station_ids_filter_excludes_unspecified_stations(self):
        from src.analytics.percentiles import compute_forecast_percentiles
        # Filter to only usgs_station_b — which has no NOAA mapping, so should be empty
        results = compute_forecast_percentiles(
            source='NWRFC',
            max_days=4,
            station_ids=[self.usgs_station_b.id],
        )
        ids = {r['station_id'] for r in results}
        self.assertNotIn(self.usgs_station_a.id, ids)

    def test_empty_station_ids_returns_no_results(self):
        from src.analytics.percentiles import compute_forecast_percentiles
        results = compute_forecast_percentiles(source='NWRFC', max_days=4, station_ids=[])
        self.assertEqual(results, [])
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
sudo -u streamflow venv/bin/python manage.py test tests.test_analytics_tasks.ComputeForecastPercentilesFilterTest --keepdb 2>&1 | tail -20
```

Expected: `TypeError: compute_forecast_percentiles() got an unexpected keyword argument 'station_ids'`

- [ ] **Step 3: Implement the `station_ids` parameter**

In `src/analytics/percentiles.py`, update the `compute_forecast_percentiles` function signature and add the filter. Change the function signature at line 243 from:

```python
def compute_forecast_percentiles(
    source: str = 'NWRFC',
    max_days: int = 8,
) -> list[dict]:
```

to:

```python
def compute_forecast_percentiles(
    source: str = 'NWRFC',
    max_days: int = 8,
    station_ids: list[int] | None = None,
) -> list[dict]:
```

Then, immediately after the existing deduplication block (the `_seen` logic), add the station filter before the `if not forecast_rows:` check. The existing code ends with:

```python
    _seen: dict[tuple, dict] = {}
    for row in forecast_rows:
        key = (row['station_id'], row['target_date'])
        if key not in _seen or row['forecast_run_date'] > _seen[key]['forecast_run_date']:
            _seen[key] = row
    forecast_rows = list(_seen.values())

    if not forecast_rows:
```

Replace `if not forecast_rows:` block and insert:

```python
    _seen: dict[tuple, dict] = {}
    for row in forecast_rows:
        key = (row['station_id'], row['target_date'])
        if key not in _seen or row['forecast_run_date'] > _seen[key]['forecast_run_date']:
            _seen[key] = row
    forecast_rows = list(_seen.values())

    # Apply station_ids filter after NOAA→USGS mapping (station_ids refers to USGS PKs)
    if station_ids is not None:
        station_id_set = set(station_ids)
        forecast_rows = [r for r in forecast_rows if r['station_id'] in station_id_set]

    if not forecast_rows:
        logger.info("compute_forecast_percentiles(%s): no forecast data found", source)
        return []
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
sudo -u streamflow venv/bin/python manage.py test tests.test_analytics_tasks.ComputeForecastPercentilesFilterTest --keepdb 2>&1 | tail -10
```

Expected: `Ran 3 tests in X.XXXs` `OK`

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
sudo -u streamflow venv/bin/python manage.py test --keepdb 2>&1 | tail -10
```

Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/analytics/percentiles.py tests/test_analytics_tasks.py
git commit -m "feat: add optional station_ids filter to compute_forecast_percentiles"
```

---

## Task 3: Add New `computation_type` Choices + Migration 0007

**Files:**
- Modify: `apps/analytics/models.py`
- Create: `apps/analytics/migrations/0007_add_percentile_computation_types.py`

- [ ] **Step 1: Update `COMPUTATION_TYPE_CHOICES` in `apps/analytics/models.py`**

In `apps/analytics/models.py`, replace the `COMPUTATION_TYPE_CHOICES` list inside `StatisticsConfiguration` (currently at lines 178–182) with:

```python
    COMPUTATION_TYPE_CHOICES = [
        ('station_metadata',      'Station Metadata & Statistics'),
        ('flood_thresholds',      'Flood Thresholds (NOAA NWPS)'),
        ('daily_flow_percentiles', 'Observed Flow Percentiles (Daily)'),
        ('forecast_percentiles',   'Forecast Flow Percentiles (NOAA NWRFC)'),
        ('percentile_backfill',    'Percentile Band Historical Backfill'),
    ]
```

- [ ] **Step 2: Generate the migration**

```bash
sudo -u streamflow venv/bin/python manage.py makemigrations analytics --name add_percentile_computation_types
```

Expected output: `Migrations for 'analytics': apps/analytics/migrations/0007_add_percentile_computation_types.py`

- [ ] **Step 3: Verify migration content**

```bash
cat apps/analytics/migrations/0007_add_percentile_computation_types.py
```

Expected: An `AlterField` operation on `statistics_configurations.computation_type` with the 5 choices.

- [ ] **Step 4: Apply the migration**

```bash
sudo -u streamflow venv/bin/python manage.py migrate analytics --keepdb 2>&1 | tail -5
```

Expected: `Applying analytics.0007_add_percentile_computation_types... OK`

- [ ] **Step 5: Verify no model check errors**

```bash
sudo -u streamflow venv/bin/python manage.py check
```

Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 6: Commit**

```bash
git add apps/analytics/models.py apps/analytics/migrations/0007_add_percentile_computation_types.py
git commit -m "feat: add daily_flow_percentiles and forecast_percentiles computation_type choices"
```

---

## Task 4: Implement Three New Executor Tasks + Wire Dispatcher

**Files:**
- Modify: `src/analytics/tasks.py`
- Test: `tests/test_analytics_tasks.py`

- [ ] **Step 1: Write failing tests for the new executor tasks**

Add these test classes to `tests/test_analytics_tasks.py`, after `ComputeForecastPercentilesFilterTest`:

```python
class RunDailyFlowPercentilesTaskTest(TestCase):
    def setUp(self):
        self.station = make_station('DAILY001', 'USGS')
        add_daily_obs(self.station, date(2020, 1, 1), 60)
        self.config = StatisticsConfiguration.objects.create(
            name='Daily USGS Test',
            computation_type='daily_flow_percentiles',
            agency_filter='USGS',
            schedule_type='custom',
            schedule_value='0 6,12,18 * * *',
            is_enabled=True,
        )

    def test_task_creates_computation_log(self):
        from src.analytics.tasks import run_daily_flow_percentiles_task
        run_daily_flow_percentiles_task(self.config.id)
        log = StatisticsComputationLog.objects.get(configuration=self.config)
        self.assertIn(log.status, ['success', 'partial'])
        self.assertIsNotNone(log.completed_at)
        self.assertIsNotNone(log.duration_seconds)

    def test_task_updates_last_run_at(self):
        from src.analytics.tasks import run_daily_flow_percentiles_task
        run_daily_flow_percentiles_task(self.config.id)
        self.config.refresh_from_db()
        self.assertIsNotNone(self.config.last_run_at)

    def test_task_upserts_daily_flow_percentile_records(self):
        from apps.streamflow.models import DailyFlowPercentile
        from src.analytics.tasks import run_daily_flow_percentiles_task
        # Add observation for yesterday so there is a row to compute
        yesterday = date.today() - timedelta(days=1)
        add_daily_obs(self.station, yesterday, 1, base_discharge=1234.0)
        run_daily_flow_percentiles_task(self.config.id)
        # The station has 60+ historical records so it should compute
        exists = DailyFlowPercentile.objects.filter(
            station=self.station, date=yesterday
        ).exists()
        self.assertTrue(exists)

    def test_task_is_idempotent(self):
        from apps.streamflow.models import DailyFlowPercentile
        from src.analytics.tasks import run_daily_flow_percentiles_task
        yesterday = date.today() - timedelta(days=1)
        add_daily_obs(self.station, yesterday, 1, base_discharge=1234.0)
        run_daily_flow_percentiles_task(self.config.id)
        run_daily_flow_percentiles_task(self.config.id)
        count = DailyFlowPercentile.objects.filter(
            station=self.station, date=yesterday
        ).count()
        self.assertEqual(count, 1)


class RunForecastPercentilesTaskTest(TestCase):
    def setUp(self):
        self.config = StatisticsConfiguration.objects.create(
            name='Forecast Test',
            computation_type='forecast_percentiles',
            agency_filter='ALL',
            schedule_type='custom',
            schedule_value='0 0,6,12,18 * * *',
            is_enabled=True,
        )

    @patch('src.analytics.tasks.compute_forecast_percentiles', return_value=[])
    def test_task_creates_log_and_calls_computation(self, mock_compute):
        from src.analytics.tasks import run_forecast_percentiles_task
        run_forecast_percentiles_task(self.config.id)
        mock_compute.assert_called_once()
        log = StatisticsComputationLog.objects.get(configuration=self.config)
        self.assertEqual(log.status, 'success')

    @patch('src.analytics.tasks.compute_forecast_percentiles', return_value=[])
    def test_task_passes_station_ids_when_agency_filtered(self, mock_compute):
        from src.analytics.tasks import run_forecast_percentiles_task
        usgs = make_station('14211010', 'USGS')
        self.config.agency_filter = 'USGS'
        self.config.save()
        run_forecast_percentiles_task(self.config.id)
        _, kwargs = mock_compute.call_args
        self.assertIn(usgs.id, kwargs['station_ids'])

    @patch('src.analytics.tasks.compute_forecast_percentiles', side_effect=RuntimeError('boom'))
    def test_task_logs_failure_on_exception(self, mock_compute):
        from src.analytics.tasks import run_forecast_percentiles_task
        with self.assertRaises(RuntimeError):
            run_forecast_percentiles_task(self.config.id)
        log = StatisticsComputationLog.objects.get(configuration=self.config)
        self.assertEqual(log.status, 'failed')
        self.assertIn('boom', log.error_message)


class RunPercentileBackfillTaskTest(TestCase):
    def setUp(self):
        self.station = make_station('BACK001', 'USGS')
        add_daily_obs(self.station, date(2020, 1, 1), 60)
        self.config = StatisticsConfiguration.objects.create(
            name='Backfill Test',
            computation_type='percentile_backfill',
            agency_filter='USGS',
            schedule_type='custom',
            schedule_value='0 0 1 10 *',
            is_enabled=False,  # manually triggered, not auto-scheduled
        )

    def test_backfill_creates_daily_flow_percentile_records(self):
        from apps.streamflow.models import DailyFlowPercentile
        from src.analytics.tasks import run_percentile_backfill_task
        run_percentile_backfill_task(self.config.id)
        count = DailyFlowPercentile.objects.filter(station=self.station).count()
        self.assertGreater(count, 0)

    def test_backfill_log_records_stations_and_records_counts(self):
        from src.analytics.tasks import run_percentile_backfill_task
        run_percentile_backfill_task(self.config.id)
        log = StatisticsComputationLog.objects.get(configuration=self.config)
        self.assertEqual(log.status, 'success')
        self.assertGreater(log.records_computed, 0)
        self.assertGreater(log.stations_processed, 0)

    def test_backfill_is_idempotent(self):
        from apps.streamflow.models import DailyFlowPercentile
        from src.analytics.tasks import run_percentile_backfill_task
        run_percentile_backfill_task(self.config.id)
        count_after_first = DailyFlowPercentile.objects.filter(station=self.station).count()
        run_percentile_backfill_task(self.config.id)
        count_after_second = DailyFlowPercentile.objects.filter(station=self.station).count()
        self.assertEqual(count_after_first, count_after_second)


class UpdatedDispatcherTest(TestCase):
    """Dispatcher routes all five computation types to the correct tasks."""

    def _make_config(self, computation_type):
        return StatisticsConfiguration.objects.create(
            name=f'Dispatch {computation_type}',
            computation_type=computation_type,
            agency_filter='ALL',
            schedule_type='monthly',
            is_enabled=True,
            next_run_at=None,
        )

    @patch('src.analytics.tasks.run_daily_flow_percentiles_task')
    def test_dispatcher_routes_daily_flow_percentiles(self, mock_task):
        config = self._make_config('daily_flow_percentiles')
        from src.analytics.tasks import dispatch_statistics_computations
        dispatch_statistics_computations()
        mock_task.delay.assert_called_once_with(config.id)

    @patch('src.analytics.tasks.run_forecast_percentiles_task')
    def test_dispatcher_routes_forecast_percentiles(self, mock_task):
        config = self._make_config('forecast_percentiles')
        from src.analytics.tasks import dispatch_statistics_computations
        dispatch_statistics_computations()
        mock_task.delay.assert_called_once_with(config.id)

    @patch('src.analytics.tasks.run_percentile_backfill_task')
    def test_dispatcher_routes_percentile_backfill(self, mock_task):
        config = self._make_config('percentile_backfill')
        from src.analytics.tasks import dispatch_statistics_computations
        dispatch_statistics_computations()
        mock_task.delay.assert_called_once_with(config.id)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
sudo -u streamflow venv/bin/python manage.py test \
  tests.test_analytics_tasks.RunDailyFlowPercentilesTaskTest \
  tests.test_analytics_tasks.RunForecastPercentilesTaskTest \
  tests.test_analytics_tasks.RunPercentileBackfillTaskTest \
  tests.test_analytics_tasks.UpdatedDispatcherTest \
  --keepdb 2>&1 | tail -20
```

Expected: `ImportError` or `AttributeError` — functions don't exist yet.

- [ ] **Step 3: Add three new executor tasks to `src/analytics/tasks.py`**

At the end of `src/analytics/tasks.py`, after `run_flood_thresholds_task`, add:

```python
@shared_task
def run_daily_flow_percentiles_task(config_id):
    """Compute and upsert DailyFlowPercentile for yesterday for all stations in a StatisticsConfiguration."""
    from apps.analytics.models import StatisticsConfiguration, StatisticsComputationLog
    from apps.streamflow.models import DailyFlowPercentile
    from src.analytics.percentiles import compute_percentile_for_date
    from django.utils import timezone
    import time

    config = StatisticsConfiguration.objects.get(id=config_id)
    station_ids = list(config.get_station_queryset().values_list('id', flat=True))
    target_date = date.today() - timedelta(days=1)

    log = StatisticsComputationLog.objects.create(
        configuration=config,
        status='running',
        started_at=timezone.now(),
        celery_task_id=run_daily_flow_percentiles_task.request.id or '',
    )

    start_time = time.monotonic()
    try:
        rows = compute_percentile_for_date(target_date, station_ids=station_ids)
        computed_at = datetime.now(timezone.utc)

        records = [
            DailyFlowPercentile(
                station_id=row['station_id'],
                date=row['observation_date'],
                discharge=row['discharge'],
                percentile_rank=row['percentile_rank'],
                band=row['band'],
                historical_record_count=row['historical_record_count'],
                computed_at=computed_at,
            )
            for row in rows
        ]

        for i in range(0, len(records), _INSERT_BATCH):
            DailyFlowPercentile.objects.bulk_create(
                records[i: i + _INSERT_BATCH],
                update_conflicts=True,
                unique_fields=['station', 'date'],
                update_fields=['discharge', 'percentile_rank', 'band', 'historical_record_count', 'computed_at'],
            )

        duration = time.monotonic() - start_time
        log.status = 'success'
        log.stations_processed = len(records)
        log.records_computed = len(records)
        log.duration_seconds = round(duration, 2)
        log.completed_at = timezone.now()
        log.save()
        StatisticsConfiguration.objects.filter(id=config_id).update(last_run_at=timezone.now())
        logger.info(
            'run_daily_flow_percentiles_task: config=%s date=%s stations=%d in %.1fs',
            config_id, target_date, len(records), duration,
        )
        return {'status': 'success', 'target_date': target_date.isoformat(), 'stations': len(records)}

    except Exception as exc:
        duration = time.monotonic() - start_time
        log.status = 'failed'
        log.error_message = str(exc)
        log.duration_seconds = round(duration, 2)
        log.completed_at = timezone.now()
        log.save()
        logger.error('run_daily_flow_percentiles_task failed for config %s: %s', config_id, exc)
        raise


@shared_task
def run_forecast_percentiles_task(config_id):
    """Compute and upsert ForecastPercentile for NWRFC forecasts for all stations in a StatisticsConfiguration."""
    from apps.analytics.models import StatisticsConfiguration, StatisticsComputationLog
    from apps.streamflow.models import ForecastPercentile
    from src.analytics.percentiles import compute_forecast_percentiles
    from django.utils import timezone
    import time

    config = StatisticsConfiguration.objects.get(id=config_id)
    station_ids = list(config.get_station_queryset().values_list('id', flat=True))

    log = StatisticsComputationLog.objects.create(
        configuration=config,
        status='running',
        started_at=timezone.now(),
        celery_task_id=run_forecast_percentiles_task.request.id or '',
    )

    start_time = time.monotonic()
    try:
        rows = compute_forecast_percentiles(source='NWRFC', max_days=8, station_ids=station_ids)
        computed_at = datetime.now(timezone.utc)

        records = [
            ForecastPercentile(
                station_id=row['station_id'],
                target_date=row['target_date'],
                source=row['source'],
                forecast_run_date=row['forecast_run_date'],
                forecast_discharge=row['forecast_discharge'],
                percentile_rank=row['percentile_rank'],
                band=row['band'],
                historical_record_count=row['historical_record_count'],
                computed_at=computed_at,
            )
            for row in rows
        ]

        for i in range(0, len(records), _INSERT_BATCH):
            ForecastPercentile.objects.bulk_create(
                records[i: i + _INSERT_BATCH],
                update_conflicts=True,
                unique_fields=['station', 'target_date', 'source'],
                update_fields=[
                    'forecast_run_date', 'forecast_discharge', 'percentile_rank',
                    'band', 'historical_record_count', 'computed_at',
                ],
            )

        duration = time.monotonic() - start_time
        unique_stations = len({r['station_id'] for r in rows})
        log.status = 'success'
        log.stations_processed = unique_stations
        log.records_computed = len(records)
        log.duration_seconds = round(duration, 2)
        log.completed_at = timezone.now()
        log.save()
        StatisticsConfiguration.objects.filter(id=config_id).update(last_run_at=timezone.now())
        logger.info(
            'run_forecast_percentiles_task: config=%s rows=%d stations=%d in %.1fs',
            config_id, len(records), unique_stations, duration,
        )
        return {'status': 'success', 'rows': len(records), 'stations': unique_stations}

    except Exception as exc:
        duration = time.monotonic() - start_time
        log.status = 'failed'
        log.error_message = str(exc)
        log.duration_seconds = round(duration, 2)
        log.completed_at = timezone.now()
        log.save()
        logger.error('run_forecast_percentiles_task failed for config %s: %s', config_id, exc)
        raise


@shared_task
def run_percentile_backfill_task(config_id):
    """
    Backfill DailyFlowPercentile for ALL historical daily_mean observations
    for all stations in a StatisticsConfiguration.

    Long-running (30–90 min for full station set). Uses chunked SQL to avoid
    memory exhaustion. Safe to re-run — uses upsert semantics.
    """
    from apps.analytics.models import StatisticsConfiguration, StatisticsComputationLog
    from apps.streamflow.models import DailyFlowPercentile
    from src.analytics.percentiles import backfill_station_chunk, iter_station_id_chunks
    from django.utils import timezone
    import time

    config = StatisticsConfiguration.objects.get(id=config_id)
    station_ids = list(config.get_station_queryset().values_list('id', flat=True))

    log = StatisticsComputationLog.objects.create(
        configuration=config,
        status='running',
        started_at=timezone.now(),
        celery_task_id=run_percentile_backfill_task.request.id or '',
    )

    start_time = time.monotonic()
    total_records = 0
    total_stations = 0

    try:
        computed_at = datetime.now(timezone.utc)
        for chunk in iter_station_id_chunks(chunk_size=100, station_ids=station_ids or None):
            rows = backfill_station_chunk(chunk, computed_at)
            records = [
                DailyFlowPercentile(
                    station_id=row['station_id'],
                    date=row['obs_date'],
                    discharge=row['discharge'],
                    percentile_rank=row['percentile_rank'],
                    band=row['band'],
                    historical_record_count=row['historical_record_count'],
                    computed_at=row['computed_at'],
                )
                for row in rows
            ]
            for i in range(0, len(records), _INSERT_BATCH):
                DailyFlowPercentile.objects.bulk_create(
                    records[i: i + _INSERT_BATCH],
                    update_conflicts=True,
                    unique_fields=['station', 'date'],
                    update_fields=['discharge', 'percentile_rank', 'band', 'historical_record_count', 'computed_at'],
                )
            total_records += len(records)
            total_stations += len(chunk)
            logger.info(
                'run_percentile_backfill_task: config=%s chunk=%d stations upserted=%d total_so_far=%d',
                config_id, len(chunk), len(records), total_records,
            )

        duration = time.monotonic() - start_time
        log.status = 'success'
        log.stations_processed = total_stations
        log.records_computed = total_records
        log.duration_seconds = round(duration, 2)
        log.completed_at = timezone.now()
        log.save()
        StatisticsConfiguration.objects.filter(id=config_id).update(last_run_at=timezone.now())
        logger.info(
            'run_percentile_backfill_task: config=%s COMPLETE stations=%d records=%d in %.1fs',
            config_id, total_stations, total_records, duration,
        )
        return {'status': 'success', 'stations': total_stations, 'records': total_records}

    except Exception as exc:
        duration = time.monotonic() - start_time
        log.status = 'failed'
        log.error_message = str(exc)
        log.duration_seconds = round(duration, 2)
        log.completed_at = timezone.now()
        log.save()
        logger.error('run_percentile_backfill_task failed for config %s: %s', config_id, exc)
        raise
```

Also add `date` and `timedelta` to the imports at the top of `src/analytics/tasks.py` — they are needed by `run_daily_flow_percentiles_task`. The current imports are:

```python
from datetime import date, datetime, timedelta, timezone
```

This is already correct. Confirm `date` and `timedelta` are already imported.

- [ ] **Step 4: Wire the dispatcher for three new computation types**

In `src/analytics/tasks.py`, find `dispatch_statistics_computations`. The current routing block (around lines 290–298) is:

```python
        if config.computation_type == 'station_metadata':
            run_station_metadata_task.delay(config.id)
        elif config.computation_type == 'flood_thresholds':
            run_flood_thresholds_task.delay(config.id)
        else:
            logger.warning('Unknown computation_type %r for config %s', config.computation_type, config.id)
            skipped += 1
            continue
```

Replace that block with:

```python
        if config.computation_type == 'station_metadata':
            run_station_metadata_task.delay(config.id)
        elif config.computation_type == 'flood_thresholds':
            run_flood_thresholds_task.delay(config.id)
        elif config.computation_type == 'daily_flow_percentiles':
            run_daily_flow_percentiles_task.delay(config.id)
        elif config.computation_type == 'forecast_percentiles':
            run_forecast_percentiles_task.delay(config.id)
        elif config.computation_type == 'percentile_backfill':
            run_percentile_backfill_task.delay(config.id)
        else:
            logger.warning('Unknown computation_type %r for config %s', config.computation_type, config.id)
            skipped += 1
            continue
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
sudo -u streamflow venv/bin/python manage.py test \
  tests.test_analytics_tasks.RunDailyFlowPercentilesTaskTest \
  tests.test_analytics_tasks.RunForecastPercentilesTaskTest \
  tests.test_analytics_tasks.RunPercentileBackfillTaskTest \
  tests.test_analytics_tasks.UpdatedDispatcherTest \
  --keepdb 2>&1 | tail -10
```

Expected: All pass.

- [ ] **Step 6: Run full test suite**

```bash
sudo -u streamflow venv/bin/python manage.py test --keepdb 2>&1 | tail -10
```

Expected: All pass.

- [ ] **Step 7: Commit**

```bash
git add src/analytics/tasks.py tests/test_analytics_tasks.py
git commit -m "feat: add run_daily_flow_percentiles_task, run_forecast_percentiles_task, run_percentile_backfill_task and wire dispatcher"
```

---

## Task 5: Remove Old Tasks, Beat Entries, Models, and Admin

This task completely eliminates the old `ScheduledComputation`/`ComputationLog` system. All changes in this task should be committed together.

**Files:**
- Modify: `src/analytics/tasks.py` — remove 2 old tasks, 2 constants, old imports
- Modify: `config/celery.py` — remove 2 beat entries
- Modify: `apps/analytics/models.py` — remove `ScheduledComputation` and `ComputationLog` classes
- Modify: `apps/analytics/admin.py` — remove old registrations and imports
- Create: `apps/analytics/migrations/0008_remove_scheduled_computation.py`
- Test: `tests/test_analytics_tasks.py` — remove tests for old tasks

- [ ] **Step 1: Remove old tasks and imports from `src/analytics/tasks.py`**

At the top of `src/analytics/tasks.py`, the current imports are:

```python
from apps.analytics.models import ComputationLog, ScheduledComputation
from apps.streamflow.models import DailyFlowPercentile
from src.analytics.percentiles import compute_percentile_for_date, compute_forecast_percentiles
```

Replace with:

```python
from apps.streamflow.models import DailyFlowPercentile, ForecastPercentile
from src.analytics.percentiles import (
    compute_percentile_for_date,
    compute_forecast_percentiles,
    backfill_station_chunk,
    iter_station_id_chunks,
)
```

Note: `ForecastPercentile` and the backfill imports are now needed at module level since the new tasks use them. The new executor tasks import these at the top (remove the local imports from inside the function bodies in the new tasks you just added — move them to module level instead).

Remove these constants entirely from the file:

```python
TASK_PATH = "src.analytics.tasks.compute_daily_flow_percentiles"
FORECAST_TASK_PATH = "src.analytics.tasks.compute_forecast_percentile_bands"

# How many rows to pass to bulk_create at once
_INSERT_BATCH = 5_000
```

Keep `_INSERT_BATCH = 5_000` — just remove `TASK_PATH` and `FORECAST_TASK_PATH`.

Delete the entire `compute_daily_flow_percentiles` function (lines 21–128) and the entire `compute_forecast_percentile_bands` function (lines 131–231).

After these removals, the file should begin with imports, then `_INSERT_BATCH`, then `_compute_stats_next_run`, then `dispatch_statistics_computations`, then the four existing executor tasks, then the three new executor tasks from Task 4.

Also update the local imports inside the new task functions (added in Task 4). In `run_daily_flow_percentiles_task`, `run_forecast_percentiles_task`, and `run_percentile_backfill_task`, remove the local imports of `DailyFlowPercentile`, `ForecastPercentile`, `compute_percentile_for_date`, `compute_forecast_percentiles`, `backfill_station_chunk`, and `iter_station_id_chunks` since these are now at module level. Keep only the local imports of `StatisticsConfiguration`, `StatisticsComputationLog`, and `timezone` (which are import-inside-function to avoid circular imports, following the existing pattern).

- [ ] **Step 2: Remove two beat entries from `config/celery.py`**

In `config/celery.py`, delete these two entries from `app.conf.beat_schedule`:

```python
    # Analytics: Compute yesterday's daily flow percentile bands.
    # Runs 3x/day so that late-arriving USGS provisional values (which can
    # trickle in throughout the day) are captured in the same date's row.
    # The task uses upsert semantics so re-running the same date is safe.
    'compute-daily-flow-percentiles': {
        'task': 'src.analytics.tasks.compute_daily_flow_percentiles',
        'schedule': crontab(minute=0, hour='6,12,18'),  # 06:00, 12:00, 18:00 UTC
    },

    # Analytics: Compute NWRFC forecast percentile bands.
    # Runs every 6 hours to stay current with NWRFC's twice-daily issuance.
    # Upsert semantics make re-runs safe.
    'compute-forecast-percentile-bands': {
        'task': 'src.analytics.tasks.compute_forecast_percentile_bands',
        'schedule': crontab(minute=0, hour='0,6,12,18'),
    },
```

Leave the `dispatch-statistics-computations` entry in place — the new configurations will be driven by the dispatcher.

- [ ] **Step 3: Remove `ScheduledComputation` and `ComputationLog` from `apps/analytics/models.py`**

Delete the entire `ScheduledComputation` class (lines 7–51) and the entire `ComputationLog` class (lines 54–90) from `apps/analytics/models.py`.

The file should now begin with the imports, then `StationMetadata`.

- [ ] **Step 4: Remove old registrations from `apps/analytics/admin.py`**

Replace the entire contents of `apps/analytics/admin.py` with:

```python
"""Django admin configuration for the analytics app."""

from django.contrib import admin

from apps.analytics.models import (
    FloodThreshold,
    StatisticsComputationLog,
    StatisticsConfiguration,
    StatisticsConfigurationStation,
    StationMetadata,
)


@admin.register(StationMetadata)
class StationMetadataAdmin(admin.ModelAdmin):
    list_display    = ["station", "last_observation_date", "years_on_record", "mean_annual_flow_cfs", "computed_at"]
    search_fields   = ["station__station_number", "station__name"]
    ordering        = ["station__station_number"]
    readonly_fields = [
        "station", "last_observation_date", "record_start_date", "record_end_date",
        "years_on_record", "daily_observation_count", "record_completeness_pct",
        "mean_annual_flow_cfs", "q10_cfs", "q25_cfs", "q50_cfs", "q75_cfs", "q90_cfs",
        "computed_at",
    ]


@admin.register(FloodThreshold)
class FloodThresholdAdmin(admin.ModelAdmin):
    list_display    = ["station", "noaa_lid", "action_stage_ft", "minor_stage_ft", "major_stage_ft", "source", "last_updated"]
    search_fields   = ["station__station_number", "noaa_lid"]
    list_filter     = ["source"]
    readonly_fields = ["last_updated"]


@admin.register(StatisticsConfiguration)
class StatisticsConfigurationAdmin(admin.ModelAdmin):
    list_display    = ["name", "computation_type", "agency_filter", "schedule_type", "is_enabled", "last_run_at", "next_run_at"]
    list_filter     = ["computation_type", "agency_filter", "schedule_type", "is_enabled"]
    search_fields   = ["name"]
    readonly_fields = ["last_run_at", "next_run_at", "created_at", "updated_at"]


@admin.register(StatisticsConfigurationStation)
class StatisticsConfigurationStationAdmin(admin.ModelAdmin):
    list_display    = ["configuration", "station"]
    search_fields   = ["configuration__name", "station__station_number"]


@admin.register(StatisticsComputationLog)
class StatisticsComputationLogAdmin(admin.ModelAdmin):
    list_display    = ["configuration", "status", "stations_processed", "duration_seconds", "started_at"]
    list_filter     = ["status", "configuration"]
    search_fields   = ["configuration__name", "celery_task_id"]
    ordering        = ["-started_at"]
    readonly_fields = [
        "configuration", "status", "celery_task_id", "started_at",
        "completed_at", "duration_seconds", "stations_processed", "records_computed", "error_message",
    ]
```

- [ ] **Step 5: Create migration 0008 to drop the old tables**

Create `apps/analytics/migrations/0008_remove_scheduled_computation.py` with this exact content:

```python
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('analytics', '0007_add_percentile_computation_types'),
    ]

    operations = [
        # ComputationLog has a FK to ScheduledComputation — must be deleted first
        migrations.DeleteModel(name='ComputationLog'),
        migrations.DeleteModel(name='ScheduledComputation'),
    ]
```

- [ ] **Step 6: Remove old task tests from `tests/test_analytics_tasks.py`**

The existing test file does NOT contain any test classes specifically for `compute_daily_flow_percentiles` or `compute_forecast_percentile_bands` — those tasks were never directly tested in this file. Verify this with:

```bash
grep -n "compute_daily_flow_percentiles\|compute_forecast_percentile_bands\|ComputationLog\|ScheduledComputation" tests/test_analytics_tasks.py
```

If any references appear, remove those lines. If no output, nothing to change.

- [ ] **Step 7: Apply migration 0008**

```bash
sudo -u streamflow venv/bin/python manage.py migrate analytics --keepdb 2>&1 | tail -5
```

Expected: `Applying analytics.0008_remove_scheduled_computation... OK`

- [ ] **Step 8: Run system check**

```bash
sudo -u streamflow venv/bin/python manage.py check
```

Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 9: Run full test suite**

```bash
sudo -u streamflow venv/bin/python manage.py test --keepdb 2>&1 | tail -10
```

Expected: All tests pass. If any test references `ScheduledComputation`, `ComputationLog`, `TASK_PATH`, `FORECAST_TASK_PATH`, or the old task function names, remove that test.

- [ ] **Step 10: Commit**

```bash
git add src/analytics/tasks.py config/celery.py apps/analytics/models.py \
        apps/analytics/admin.py apps/analytics/migrations/0008_remove_scheduled_computation.py \
        tests/test_analytics_tasks.py
git commit -m "feat: remove ScheduledComputation/ComputationLog system and old hardcoded beat tasks — complete cutover to StatisticsConfiguration"
```

---

## Task 6: Seed Standard Configurations + Clean Celery Beat DB

**Files:**
- Create: `apps/analytics/migrations/0009_seed_percentile_configurations.py`

This migration does two things:
1. Creates five standard `StatisticsConfiguration` records so the system is operational immediately after deploy
2. Deletes the orphaned `django_celery_beat.PeriodicTask` DB entries for the two removed beat tasks — these will otherwise continue firing against non-existent task functions

**Why the Celery Beat cleanup is here:** Django Celery Beat's `DatabaseScheduler` reads `beat_schedule` on startup and creates/updates DB records — but it does **not** delete entries that are no longer in `beat_schedule`. The two old entries (`compute-daily-flow-percentiles`, `compute-forecast-percentile-bands`) will remain in the `django_celery_beat_periodictask` table and will be dispatched on their old schedules until removed. This migration removes them atomically with the seeding.

- [ ] **Step 1: Create migration 0009**

Create `apps/analytics/migrations/0009_seed_percentile_configurations.py` with this exact content:

```python
from django.db import migrations
from django.utils import timezone


STANDARD_CONFIGS = [
    {
        'name': 'Daily Observed Percentiles — USGS',
        'description': (
            'Computes exceedance percentile bands for all USGS stations that have a daily_mean '
            'observation for the previous day. Runs 3× daily to capture late-arriving provisional '
            'values. Upsert semantics make re-runs safe.'
        ),
        'computation_type': 'daily_flow_percentiles',
        'agency_filter': 'USGS',
        'schedule_type': 'custom',
        'schedule_value': '0 6,12,18 * * *',
        'is_enabled': True,
    },
    {
        'name': 'Daily Observed Percentiles — EC',
        'description': (
            'Computes exceedance percentile bands for all Environment Canada stations that have a '
            'daily_mean observation for the previous day. Runs 3× daily.'
        ),
        'computation_type': 'daily_flow_percentiles',
        'agency_filter': 'EC',
        'schedule_type': 'custom',
        'schedule_value': '0 6,12,18 * * *',
        'is_enabled': True,
    },
    {
        'name': 'Forecast Percentiles — NWRFC',
        'description': (
            'Computes exceedance percentile bands for NOAA NWRFC 8-day forecasts. Maps NOAA_RFC '
            'stations to USGS stations via StationMapping and compares forecast discharges against '
            'each station\'s full period-of-record daily_mean observations. Runs every 6 hours to '
            'stay current with NWRFC issuance cycles.'
        ),
        'computation_type': 'forecast_percentiles',
        'agency_filter': 'ALL',
        'schedule_type': 'custom',
        'schedule_value': '0 0,6,12,18 * * *',
        'is_enabled': True,
    },
    {
        'name': 'Historical Backfill — USGS',
        'description': (
            'One-time (or as-needed) backfill of DailyFlowPercentile for all USGS stations using '
            'all available daily_mean discharge observations. Chunked in groups of 100 stations to '
            'avoid memory exhaustion. Can take 30–90 minutes for the full station set. '
            'Disabled by default — enable and trigger manually when needed.'
        ),
        'computation_type': 'percentile_backfill',
        'agency_filter': 'USGS',
        'schedule_type': 'custom',
        'schedule_value': '0 0 1 1 *',  # Placeholder — trigger manually via GUI
        'is_enabled': False,
    },
    {
        'name': 'Historical Backfill — EC',
        'description': (
            'One-time (or as-needed) backfill of DailyFlowPercentile for all Environment Canada '
            'stations using all available daily_mean discharge observations. Chunked in groups of '
            '100 stations. Disabled by default — enable and trigger manually when needed.'
        ),
        'computation_type': 'percentile_backfill',
        'agency_filter': 'EC',
        'schedule_type': 'custom',
        'schedule_value': '0 0 1 1 *',  # Placeholder — trigger manually via GUI
        'is_enabled': False,
    },
]

OLD_BEAT_TASK_NAMES = [
    'compute-daily-flow-percentiles',
    'compute-forecast-percentile-bands',
]


def seed_configurations(apps, schema_editor):
    StatisticsConfiguration = apps.get_model('analytics', 'StatisticsConfiguration')
    for cfg in STANDARD_CONFIGS:
        StatisticsConfiguration.objects.get_or_create(
            name=cfg['name'],
            defaults={k: v for k, v in cfg.items() if k != 'name'},
        )


def remove_old_periodic_tasks(apps, schema_editor):
    try:
        PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')
        deleted, _ = PeriodicTask.objects.filter(name__in=OLD_BEAT_TASK_NAMES).delete()
        if deleted:
            print(f'\n  Removed {deleted} orphaned Celery Beat periodic task(s): {OLD_BEAT_TASK_NAMES}')
    except LookupError:
        # django_celery_beat not installed or tables not created — skip silently
        pass


def reverse_seed(apps, schema_editor):
    StatisticsConfiguration = apps.get_model('analytics', 'StatisticsConfiguration')
    StatisticsConfiguration.objects.filter(
        name__in=[cfg['name'] for cfg in STANDARD_CONFIGS]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('analytics', '0008_remove_scheduled_computation'),
    ]

    operations = [
        migrations.RunPython(seed_configurations, reverse_code=reverse_seed),
        migrations.RunPython(remove_old_periodic_tasks, reverse_code=migrations.RunPython.noop),
    ]
```

- [ ] **Step 2: Apply migration 0009**

```bash
sudo -u streamflow venv/bin/python manage.py migrate analytics --keepdb 2>&1 | tail -10
```

Expected:
```
Applying analytics.0009_seed_percentile_configurations...
  Removed 2 orphaned Celery Beat periodic task(s): [...]
 OK
```

If `django_celery_beat` tables don't exist in the test DB, the `LookupError` is caught and the migration still succeeds.

- [ ] **Step 3: Verify seeded configurations**

```bash
sudo -u streamflow venv/bin/python manage.py shell -c "
from apps.analytics.models import StatisticsConfiguration
for c in StatisticsConfiguration.objects.order_by('name'):
    print(c.name, '|', c.computation_type, '|', c.agency_filter, '|', 'enabled' if c.is_enabled else 'disabled')
"
```

Expected output (5 lines):
```
Daily Observed Percentiles — EC | daily_flow_percentiles | EC | enabled
Daily Observed Percentiles — USGS | daily_flow_percentiles | USGS | enabled
Forecast Percentiles — NWRFC | forecast_percentiles | ALL | enabled
Historical Backfill — EC | percentile_backfill | EC | disabled
Historical Backfill — USGS | percentile_backfill | USGS | disabled
```

- [ ] **Step 4: Run full test suite**

```bash
sudo -u streamflow venv/bin/python manage.py test --keepdb 2>&1 | tail -10
```

Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/analytics/migrations/0009_seed_percentile_configurations.py
git commit -m "feat: seed standard percentile configurations and clean orphaned Celery Beat entries"
```

---

## Task 7: Deploy

- [ ] **Step 1: Fix file ownership**

```bash
sudo chown -R streamflow:streamflow /home/streamflow/streamflow-dataOps/streamflow-dataOps/
```

- [ ] **Step 2: Collect static files**

```bash
sudo -u streamflow venv/bin/python manage.py collectstatic --noinput 2>&1 | tail -5
```

- [ ] **Step 3: Run migrations on production DB**

```bash
sudo -u streamflow venv/bin/python manage.py migrate 2>&1 | tail -10
```

Expected: Migrations 0007, 0008, 0009 applied. Verify the Celery Beat cleanup message appears.

- [ ] **Step 4: Restart all services**

```bash
sudo systemctl restart gunicorn.service celery-worker.service celery-beat.service
```

- [ ] **Step 5: Verify services are running**

```bash
sudo systemctl status gunicorn.service celery-worker.service celery-beat.service --no-pager | grep -E "Active:|●"
```

Expected: All three show `active (running)`.

- [ ] **Step 6: Verify analytics GUI shows the 5 new configurations**

Navigate to `https://streamflowops.3rdplaces.io/analytics/configurations/` and confirm:
- 5 configurations appear
- 3 are enabled (both USGS/EC daily + NWRFC forecasts)
- 2 are disabled (USGS and EC backfills)
- The `computation_type` column shows the correct labels

- [ ] **Step 7: Trigger a manual test run**

On the detail page for "Daily Observed Percentiles — USGS", click "Run Now". Monitor the computation log entry — it should appear with `status=running` then transition to `status=success` within a minute.

- [ ] **Step 8: Verify no old beat tasks remain in Celery Beat DB**

```bash
sudo -u streamflow venv/bin/python manage.py shell -c "
from django_celery_beat.models import PeriodicTask
old = PeriodicTask.objects.filter(name__in=['compute-daily-flow-percentiles', 'compute-forecast-percentile-bands'])
print('Orphaned entries remaining:', old.count())
"
```

Expected: `Orphaned entries remaining: 0`

- [ ] **Step 9: Check Celery worker logs for errors**

```bash
sudo journalctl -u celery-worker.service -n 50 --no-pager | grep -E "ERROR|WARNING|CRITICAL"
```

Expected: No errors related to missing tasks or imports.

---

## Self-Review

### Spec Coverage Check

| Requirement | Task |
|---|---|
| Daily observed USGS station percentiles, configurable | Task 4 (executor task) + Task 6 (seeded config) |
| Daily observed EC station percentiles, configurable | Task 4 (executor task) + Task 6 (seeded config) |
| Forecast percentile configs for USGS via NOAA | Task 4 (executor task) + Task 6 (seeded config) |
| Historical backfill — USGS | Task 4 (executor task) + Task 6 (seeded config, disabled) |
| Historical backfill — EC | Task 4 (executor task) + Task 6 (seeded config, disabled) |
| Station filter by agency | Task 1 + Task 2 (station_ids param) |
| Remove old hardcoded tasks | Task 5 |
| Remove old beat entries | Task 5 |
| Remove `ScheduledComputation`/`ComputationLog` models | Task 5 |
| Dispatcher routes new types | Task 4 |
| Orphaned Celery Beat DB entries cleaned | Task 6 |
| Tests for new functions and tasks | Tasks 1, 2, 4 |

### Placeholder Scan
No placeholders. All code blocks contain complete implementations.

### Type/Name Consistency
- `run_daily_flow_percentiles_task` — used consistently in Task 4 (implementation) and Task 4 (tests) and Task 5 (dispatcher routing)
- `run_forecast_percentiles_task` — consistent
- `run_percentile_backfill_task` — consistent
- `compute_percentile_for_date(target_date, station_ids=None)` — new signature used in Task 1 tests, Task 1 implementation, and Task 4 task body
- `compute_forecast_percentiles(source, max_days, station_ids=None)` — new signature used in Task 2 tests, Task 2 implementation, and Task 4 task body
- `backfill_station_chunk(station_ids, computed_at)` — existing signature, used correctly in Task 4
- `iter_station_id_chunks(chunk_size, station_ids)` — existing signature, used correctly in Task 4
- Migration numbers: 0007 → 0008 → 0009 in dependency chain
