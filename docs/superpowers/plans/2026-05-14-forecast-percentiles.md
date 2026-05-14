# Forecast Percentile Bands Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pre-compute and serve 8-day NWRFC exceedance percentile bands in a new `forecast_percentiles` table, extending the StreamflowOps API and downstream dashboard date picker into the forecast period.

**Architecture:** New `ForecastPercentile` model (one row per station/date/source) populated by a new Celery task `compute_forecast_percentile_bands` running every 6 hours. Two new actions on `ForecastRunViewSet` serve the bands and date-range via `GET /api/v1/forecasts/discharge/percentile-bands/` and `GET /api/v1/forecasts/discharge/percentile-date-range/`. The dashboard routes observed dates to the existing endpoint and forecast dates to the new one, displaying a source label near the date picker.

**Tech Stack:** Django 4.2, PostgreSQL, Celery, Django REST Framework, drf-spectacular, psycopg2, Python 3.12.

---

## File Map

| Action | Path | Responsibility |
|--------|------|---------------|
| Modify | `apps/streamflow/models.py` | Add `ForecastPercentile` model after `DailyFlowPercentile` |
| Create | `apps/streamflow/migrations/0017_forecast_percentile.py` | Schema migration (auto-generated via makemigrations) |
| Modify | `src/analytics/percentiles.py` | Add `compute_forecast_percentiles()` |
| Modify | `src/analytics/tasks.py` | Add `compute_forecast_percentile_bands` Celery task |
| Create | `apps/analytics/migrations/0004_seed_forecast_percentile_computation.py` | Register task in ScheduledComputation |
| Modify | `config/celery.py` | Add beat schedule entry |
| Create | `apps/api/serializers/forecast_percentile.py` | Three serializer classes for forecast percentile endpoints |
| Modify | `apps/api/serializers/__init__.py` | Export new serializers |
| Modify | `apps/api/views/forecast.py` | Add `percentile_bands` and `percentile_date_range` actions |
| Create | `tests/test_forecast_percentile_computation.py` | Unit + task tests |
| Create | `tests/test_api_forecast_percentiles.py` | API endpoint tests |

---

## Task 1: ForecastPercentile Model + Migration

**Files:**
- Modify: `apps/streamflow/models.py` (after line 739, end of file)
- Create: `apps/streamflow/migrations/0017_forecast_percentile.py` (auto-generated)
- Create: `tests/test_forecast_percentile_computation.py`

- [ ] **Step 1: Write the failing model test**

Create `tests/test_forecast_percentile_computation.py`:

```python
"""Tests for ForecastPercentile model and compute_forecast_percentiles()."""

from datetime import date, timedelta
from django.test import TestCase
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.streamflow.models import Station, ForecastPercentile


class ForecastPercentileModelTest(TestCase):

    def setUp(self):
        self.station = Station.objects.create(
            station_number='TEST001',
            name='Test Station',
            agency='NOAA_RFC',
        )
        self.target_date = date.today() + timedelta(days=1)

    def _make(self, **kwargs):
        defaults = dict(
            station=self.station,
            target_date=self.target_date,
            source='NWRFC',
            forecast_run_date=timezone.now(),
            forecast_discharge=4820.0,
            percentile_rank=72.4,
            band='p51_75',
            historical_record_count=8431,
            computed_at=timezone.now(),
        )
        defaults.update(kwargs)
        return ForecastPercentile.objects.create(**defaults)

    def test_create_and_str(self):
        fp = self._make()
        self.assertEqual(fp.band, 'p51_75')
        self.assertIn('TEST001', str(fp))
        self.assertIn('NWRFC', str(fp))

    def test_unique_constraint_station_date_source(self):
        self._make()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._make(forecast_discharge=9999.0)

    def test_different_source_same_station_date_allowed(self):
        self._make(source='NWRFC')
        fp2 = self._make(source='MUTHRE')   # different source — must not raise
        self.assertEqual(fp2.source, 'MUTHRE')

    def test_different_date_same_station_source_allowed(self):
        self._make(target_date=self.target_date)
        fp2 = self._make(target_date=self.target_date + timedelta(days=1))
        self.assertNotEqual(fp2.target_date, self.target_date)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/streamflow/streamflow-dataOps/streamflow-dataOps
source venv/bin/activate
python manage.py test tests.test_forecast_percentile_computation.ForecastPercentileModelTest -v 2
```

Expected: ImportError — `cannot import name 'ForecastPercentile' from 'apps.streamflow.models'`

- [ ] **Step 3: Add ForecastPercentile model**

In `apps/streamflow/models.py`, append after the closing `__str__` of `DailyFlowPercentile` (after line 739):

```python


class ForecastPercentile(models.Model):
    """
    Precomputed exceedance percentile band for a forecast value at a station on a future date.

    One row per (station, target_date, source). Upserted each time the
    compute_forecast_percentile_bands task runs — always reflects the most
    recent ForecastRun for that source.
    """

    station = models.ForeignKey(
        Station,
        on_delete=models.CASCADE,
        related_name="forecast_percentiles",
        db_index=True,
    )
    target_date        = models.DateField(db_index=True, help_text="Forecasted date")
    source             = models.CharField(max_length=20, help_text="Forecast source label, e.g. NWRFC")
    forecast_run_date  = models.DateTimeField(help_text="Issuance datetime of the ForecastRun used")
    forecast_discharge = models.DecimalField(max_digits=12, decimal_places=4)
    percentile_rank    = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        help_text="0–100; compared against station's full period-of-record daily_mean observations",
    )
    band                    = models.CharField(max_length=10, choices=BAND_CHOICES)
    historical_record_count = models.IntegerField(
        help_text="Total daily_mean records used in the percentile computation"
    )
    computed_at = models.DateTimeField(help_text="When this row was computed")

    class Meta:
        db_table = "forecast_percentiles"
        constraints = [
            models.UniqueConstraint(
                fields=["station", "target_date", "source"],
                name="unique_forecast_percentile",
            )
        ]
        indexes = [
            models.Index(fields=["station", "target_date"], name="idx_fcst_pct_station_date"),
            models.Index(fields=["source", "target_date"],  name="idx_fcst_pct_source_date"),
        ]
        ordering = ["target_date"]

    def __str__(self):
        return f"{self.station.station_number} – {self.target_date} – {self.source} – {self.band}"
```

- [ ] **Step 4: Generate and apply migration**

```bash
python manage.py makemigrations streamflow --name forecast_percentile
python manage.py migrate
```

Expected: `Applying streamflow.0017_forecast_percentile... OK`

- [ ] **Step 5: Run model tests to verify they pass**

```bash
python manage.py test tests.test_forecast_percentile_computation.ForecastPercentileModelTest -v 2
```

Expected: 4 tests pass.

- [ ] **Step 6: Commit**

```bash
git add apps/streamflow/models.py \
        apps/streamflow/migrations/0017_forecast_percentile.py \
        tests/test_forecast_percentile_computation.py
git commit -m "feat: add ForecastPercentile model and migration"
```

---

## Task 2: compute_forecast_percentiles() Function

**Files:**
- Modify: `src/analytics/percentiles.py`
- Modify: `tests/test_forecast_percentile_computation.py` (add class)

- [ ] **Step 1: Write the failing computation tests**

Append to `tests/test_forecast_percentile_computation.py`:

```python
from datetime import datetime
from django.utils import timezone
from apps.streamflow.models import DischargeObservation, ForecastRun
from src.analytics.percentiles import compute_forecast_percentiles


class ComputeForecastPercentilesTest(TestCase):

    def setUp(self):
        self.station = Station.objects.create(
            station_number='COMP001',
            name='Computation Test Station',
            agency='NOAA_RFC',
        )

        # 100 historical daily_mean observations with discharge 1.0–100.0
        today = date.today()
        observations = [
            DischargeObservation(
                station=self.station,
                observed_at=datetime(2020, 1, 1, tzinfo=timezone.utc) + timedelta(days=i),
                discharge=float(i + 1),
                unit='cfs',
                type='daily_mean',
                quality_code='A',
            )
            for i in range(100)
        ]
        DischargeObservation.objects.bulk_create(observations)

        # ForecastRun with values for tomorrow and day+2
        self.run_date = timezone.now()
        self.tomorrow = today + timedelta(days=1)
        self.day2 = today + timedelta(days=2)
        ForecastRun.objects.create(
            station=self.station,
            source='NOAA_RFC',
            run_date=self.run_date,
            forecast_type='short',
            data=[
                {'date': self.tomorrow.isoformat() + 'T00:00:00Z', 'value': 50.0},
                {'date': self.day2.isoformat() + 'T00:00:00Z', 'value': 75.0},
            ],
        )

    def test_returns_correct_percentile_ranks(self):
        results = compute_forecast_percentiles(source='NWRFC', max_days=8)
        by_date = {r['target_date']: r for r in results}

        self.assertIn(self.tomorrow, by_date)
        self.assertIn(self.day2, by_date)
        self.assertAlmostEqual(by_date[self.tomorrow]['percentile_rank'], 50.0, places=1)
        self.assertAlmostEqual(by_date[self.day2]['percentile_rank'], 75.0, places=1)

    def test_returns_correct_bands(self):
        results = compute_forecast_percentiles(source='NWRFC', max_days=8)
        by_date = {r['target_date']: r for r in results}
        self.assertEqual(by_date[self.tomorrow]['band'], 'p26_50')
        self.assertEqual(by_date[self.day2]['band'], 'p51_75')

    def test_source_label_set_correctly(self):
        results = compute_forecast_percentiles(source='NWRFC', max_days=8)
        self.assertTrue(all(r['source'] == 'NWRFC' for r in results))

    def test_forecast_run_date_attached(self):
        results = compute_forecast_percentiles(source='NWRFC', max_days=8)
        for r in results:
            self.assertIsNotNone(r['forecast_run_date'])

    def test_excludes_dates_beyond_max_days(self):
        today = date.today()
        cutoff = today + timedelta(days=3)
        # day2 is today+2, which is within max_days=3; day3 would be outside
        ForecastRun.objects.filter(station=self.station).update(
            data=[
                {'date': (today + timedelta(days=1)).isoformat() + 'T00:00:00Z', 'value': 50.0},
                {'date': (today + timedelta(days=9)).isoformat() + 'T00:00:00Z', 'value': 50.0},
            ]
        )
        results = compute_forecast_percentiles(source='NWRFC', max_days=3)
        dates = {r['target_date'] for r in results}
        self.assertNotIn(today + timedelta(days=9), dates)

    def test_station_with_no_nwrfc_run_skipped(self):
        station_no_run = Station.objects.create(
            station_number='NORFC001',
            name='No RFC Run',
            agency='USGS',
        )
        # Create 100 observations so it has history, but no ForecastRun
        DischargeObservation.objects.bulk_create([
            DischargeObservation(
                station=station_no_run,
                observed_at=datetime(2020, 1, 1, tzinfo=timezone.utc) + timedelta(days=i),
                discharge=float(i + 1),
                unit='cfs',
                type='daily_mean',
                quality_code='A',
            )
            for i in range(100)
        ])
        results = compute_forecast_percentiles(source='NWRFC', max_days=8)
        station_numbers = {r['station_id'] for r in results}
        self.assertNotIn(station_no_run.id, station_numbers)

    def test_station_with_fewer_than_30_historical_records_skipped(self):
        sparse_station = Station.objects.create(
            station_number='SPARSE001',
            name='Sparse Station',
            agency='NOAA_RFC',
        )
        # Only 10 historical observations — below MIN_HISTORICAL_RECORDS
        DischargeObservation.objects.bulk_create([
            DischargeObservation(
                station=sparse_station,
                observed_at=datetime(2020, 1, 1, tzinfo=timezone.utc) + timedelta(days=i),
                discharge=float(i + 1),
                unit='cfs',
                type='daily_mean',
                quality_code='A',
            )
            for i in range(10)
        ])
        ForecastRun.objects.create(
            station=sparse_station,
            source='NOAA_RFC',
            run_date=timezone.now(),
            forecast_type='short',
            data=[{'date': (date.today() + timedelta(days=1)).isoformat() + 'T00:00:00Z', 'value': 50.0}],
        )
        results = compute_forecast_percentiles(source='NWRFC', max_days=8)
        station_ids = {r['station_id'] for r in results}
        self.assertNotIn(sparse_station.id, station_ids)

    def test_returns_empty_when_no_forecast_runs(self):
        ForecastRun.objects.all().delete()
        results = compute_forecast_percentiles(source='NWRFC', max_days=8)
        self.assertEqual(results, [])

    def test_uses_latest_run_when_multiple_exist(self):
        today = date.today()
        # Add an older run with a different value for tomorrow
        ForecastRun.objects.create(
            station=self.station,
            source='NOAA_RFC',
            run_date=self.run_date - timedelta(days=1),
            forecast_type='medium',
            data=[{'date': (today + timedelta(days=1)).isoformat() + 'T00:00:00Z', 'value': 10.0}],
        )
        results = compute_forecast_percentiles(source='NWRFC', max_days=8)
        by_date = {r['target_date']: r for r in results}
        # Should use the newer run's value (50.0), not the older (10.0)
        self.assertAlmostEqual(by_date[self.tomorrow]['forecast_discharge'], 50.0, places=1)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python manage.py test tests.test_forecast_percentile_computation.ComputeForecastPercentilesTest -v 2
```

Expected: ImportError — `cannot import name 'compute_forecast_percentiles' from 'src.analytics.percentiles'`

- [ ] **Step 3: Implement compute_forecast_percentiles()**

In `src/analytics/percentiles.py`, add these imports at the top (after existing imports):

```python
from datetime import timedelta
```

Then append after the last function in the file (after line 229):

```python

# ---------------------------------------------------------------------------
# Forecast percentile computation
# ---------------------------------------------------------------------------

# Maps ForecastPercentile.source label -> ForecastRun.source value
_FORECAST_RUN_SOURCE_MAP = {
    'NWRFC': 'NOAA_RFC',
}


def compute_forecast_percentiles(
    source: str = 'NWRFC',
    max_days: int = 8,
) -> list[dict]:
    """
    Compute exceedance percentile bands for the most recent NOAA_RFC ForecastRun
    per station, covering the next max_days calendar days from today.

    Compares each forecasted discharge against the station's full period-of-record
    daily_mean observations — the same methodology as compute_percentile_for_date().

    Args:
        source: ForecastPercentile.source label (e.g. 'NWRFC'). Determines which
                ForecastRun.source to query via _FORECAST_RUN_SOURCE_MAP.
        max_days: Number of calendar days ahead to include (today is day 0,
                  so max_days=8 covers today+1 through today+8).

    Returns:
        List of dicts with keys:
            station_id, target_date, forecast_discharge, source,
            forecast_run_date, historical_record_count, percentile_rank, band
    """
    from apps.streamflow.models import ForecastRun  # avoid circular import at module load

    run_source = _FORECAST_RUN_SOURCE_MAP.get(source)
    if run_source is None:
        raise ValueError(f"Unknown forecast source: {source!r}. Add it to _FORECAST_RUN_SOURCE_MAP.")

    today = date.today()
    cutoff = today + timedelta(days=max_days)

    # Latest ForecastRun per station (DISTINCT ON station_id ORDER BY run_date DESC)
    latest_runs = (
        ForecastRun.objects
        .filter(source=run_source)
        .order_by('station_id', '-run_date')
        .distinct('station_id')
        .values('station_id', 'run_date', 'data')
    )

    # Build flat list of forecast points within [today+1, cutoff)
    forecast_rows: list[dict] = []
    for run in latest_runs:
        for point in (run['data'] or []):
            try:
                pt_date = date.fromisoformat(str(point['date'])[:10])
            except (KeyError, ValueError, TypeError):
                continue
            if today < pt_date < cutoff:
                forecast_rows.append({
                    'station_id':    run['station_id'],
                    'target_date':   pt_date,
                    'discharge':     float(point['value']),
                    'forecast_run_date': run['run_date'],
                })

    if not forecast_rows:
        logger.info("compute_forecast_percentiles(%s): no forecast data found", source)
        return []

    # Build VALUES clause with type hints on first row so PostgreSQL infers column types
    value_parts = []
    flat_params: list = []
    for i, row in enumerate(forecast_rows):
        if i == 0:
            value_parts.append('(%s::bigint, %s::date, %s::numeric)')
        else:
            value_parts.append('(%s, %s, %s)')
        flat_params.extend([row['station_id'], row['target_date'].isoformat(), row['discharge']])

    values_clause = ', '.join(value_parts)

    sql = f"""
        WITH forecast_vals (station_id, target_date, discharge) AS (
            VALUES {values_clause}
        )
        SELECT
            fv.station_id,
            fv.target_date,
            fv.discharge,
            COUNT(h.id)                                              AS historical_record_count,
            ROUND(
                COUNT(h.id) FILTER (WHERE h.discharge <= fv.discharge) * 100.0
                / NULLIF(COUNT(h.id), 0),
            2)                                                       AS percentile_rank
        FROM forecast_vals fv
        JOIN discharge_observations h
            ON h.station_id = fv.station_id
           AND h.type = 'daily_mean'
        GROUP BY fv.station_id, fv.target_date, fv.discharge
        HAVING COUNT(h.id) >= %s
        ORDER BY fv.station_id, fv.target_date
    """

    flat_params.append(MIN_HISTORICAL_RECORDS)

    # Build lookup: (station_id, target_date) -> forecast_run_date
    run_date_lookup = {
        (r['station_id'], r['target_date']): r['forecast_run_date']
        for r in forecast_rows
    }

    with connection.cursor() as cursor:
        cursor.execute(sql, flat_params)
        columns = [col[0] for col in cursor.description]
        rows = cursor.fetchall()

    results = []
    for row in rows:
        d = dict(zip(columns, row))
        station_id  = d['station_id']
        target_date = d['target_date']
        rank = float(d['percentile_rank'])
        results.append({
            'station_id':            station_id,
            'target_date':           target_date,
            'forecast_discharge':    float(d['discharge']),
            'source':                source,
            'forecast_run_date':     run_date_lookup[(station_id, target_date)],
            'historical_record_count': int(d['historical_record_count']),
            'percentile_rank':       rank,
            'band':                  classify_band(rank),
        })

    logger.info(
        "compute_forecast_percentiles(%s, max_days=%d): %d rows", source, max_days, len(results)
    )
    return results
```

- [ ] **Step 4: Run computation tests**

```bash
python manage.py test tests.test_forecast_percentile_computation.ComputeForecastPercentilesTest -v 2
```

Expected: All 9 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/analytics/percentiles.py tests/test_forecast_percentile_computation.py
git commit -m "feat: add compute_forecast_percentiles() to percentiles.py"
```

---

## Task 3: Celery Task + Schedule Registration

**Files:**
- Modify: `src/analytics/tasks.py`
- Create: `apps/analytics/migrations/0004_seed_forecast_percentile_computation.py`
- Modify: `config/celery.py`
- Modify: `tests/test_forecast_percentile_computation.py` (add class)

- [ ] **Step 1: Write the failing task test**

Append to `tests/test_forecast_percentile_computation.py`:

```python
from unittest.mock import patch, MagicMock
from apps.analytics.models import ScheduledComputation, ComputationLog
from src.analytics.tasks import compute_forecast_percentile_bands

FORECAST_TASK_PATH = 'src.analytics.tasks.compute_forecast_percentile_bands'


class ComputeForecastPercentileBandsTaskTest(TestCase):

    def setUp(self):
        self.computation = ScheduledComputation.objects.create(
            name='NWRFC Forecast Percentile Bands',
            description='Computes forecast percentile bands.',
            task_path=FORECAST_TASK_PATH,
            schedule='every_6h',
            is_enabled=True,
        )

    @patch('src.analytics.tasks.compute_forecast_percentiles')
    def test_task_creates_computation_log(self, mock_compute):
        mock_compute.return_value = []
        compute_forecast_percentile_bands.apply()
        self.assertEqual(
            ComputationLog.objects.filter(computation=self.computation, status='success').count(),
            1,
        )

    @patch('src.analytics.tasks.compute_forecast_percentiles')
    def test_task_upserts_forecast_percentile_rows(self, mock_compute):
        station = Station.objects.create(
            station_number='TASK001', name='Task Test', agency='NOAA_RFC'
        )
        today = date.today()
        mock_compute.return_value = [
            {
                'station_id': station.id,
                'target_date': today + timedelta(days=1),
                'forecast_discharge': 500.0,
                'source': 'NWRFC',
                'forecast_run_date': timezone.now(),
                'historical_record_count': 100,
                'percentile_rank': 50.0,
                'band': 'p26_50',
            }
        ]
        compute_forecast_percentile_bands.apply()
        self.assertEqual(ForecastPercentile.objects.filter(station=station).count(), 1)

    @patch('src.analytics.tasks.compute_forecast_percentiles')
    def test_task_skipped_when_disabled(self, mock_compute):
        self.computation.is_enabled = False
        self.computation.save()
        result = compute_forecast_percentile_bands.apply().get()
        self.assertEqual(result['status'], 'skipped')
        mock_compute.assert_not_called()

    @patch('src.analytics.tasks.compute_forecast_percentiles')
    def test_task_updates_scheduled_computation_status(self, mock_compute):
        mock_compute.return_value = []
        compute_forecast_percentile_bands.apply()
        self.computation.refresh_from_db()
        self.assertEqual(self.computation.last_run_status, 'success')
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python manage.py test tests.test_forecast_percentile_computation.ComputeForecastPercentileBandsTaskTest -v 2
```

Expected: ImportError — `cannot import name 'compute_forecast_percentile_bands'`

- [ ] **Step 3: Add the Celery task**

In `src/analytics/tasks.py`, add `FORECAST_TASK_PATH` constant and the new task. After line 14 (`TASK_PATH = ...`), add:

```python
FORECAST_TASK_PATH = "src.analytics.tasks.compute_forecast_percentile_bands"
```

After line 127 (end of file), add:

```python

@shared_task(bind=True, max_retries=3)
def compute_forecast_percentile_bands(self):
    """
    Compute and upsert exceedance percentile bands for the latest NWRFC forecast
    per station, covering the next 8 calendar days.

    Runs every 6 hours via Celery beat. Uses upsert semantics on
    (station, target_date, source) so re-running is safe.
    """
    from apps.streamflow.models import ForecastPercentile
    from src.analytics.percentiles import compute_forecast_percentiles

    try:
        computation = ScheduledComputation.objects.get(task_path=FORECAST_TASK_PATH)
    except ScheduledComputation.DoesNotExist:
        logger.error(
            "ScheduledComputation record not found for %s. Run migrations to seed it.",
            FORECAST_TASK_PATH,
        )
        return {"status": "error", "detail": "ScheduledComputation record missing"}

    if not computation.is_enabled:
        logger.info("'%s' is disabled — skipping", computation.name)
        return {"status": "skipped"}

    started_at = datetime.now(timezone.utc)
    log = ComputationLog.objects.create(
        computation=computation,
        status="running",
        started_at=started_at,
        celery_task_id=self.request.id or "",
    )

    try:
        rows = compute_forecast_percentiles(source='NWRFC', max_days=8)
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
                    'forecast_run_date',
                    'forecast_discharge',
                    'percentile_rank',
                    'band',
                    'historical_record_count',
                    'computed_at',
                ],
            )

        completed_at = datetime.now(timezone.utc)
        duration = (completed_at - started_at).total_seconds()

        log.status = "success"
        log.records_computed = len(records)
        log.completed_at = completed_at
        log.duration_seconds = duration
        log.save()

        computation.last_run_at = completed_at
        computation.last_run_status = "success"
        computation.save(update_fields=["last_run_at", "last_run_status"])

        logger.info(
            "'%s' complete: %d rows in %.1fs", computation.name, len(records), duration
        )
        return {
            "status": "success",
            "rows_computed": len(records),
            "duration_seconds": duration,
        }

    except Exception as exc:
        completed_at = datetime.now(timezone.utc)
        log.status = "failed"
        log.error_message = str(exc)
        log.completed_at = completed_at
        log.duration_seconds = (completed_at - started_at).total_seconds()
        log.save()

        computation.last_run_status = "failed"
        computation.save(update_fields=["last_run_status"])

        logger.error("'%s' failed: %s", computation.name, exc)
        raise
```

- [ ] **Step 4: Run task tests**

```bash
python manage.py test tests.test_forecast_percentile_computation.ComputeForecastPercentileBandsTaskTest -v 2
```

Expected: All 4 tests pass.

- [ ] **Step 5: Create the ScheduledComputation data migration**

Create `apps/analytics/migrations/0004_seed_forecast_percentile_computation.py`:

```python
from django.db import migrations

TASK_PATH = "src.analytics.tasks.compute_forecast_percentile_bands"


def seed(apps, schema_editor):
    ScheduledComputation = apps.get_model("analytics", "ScheduledComputation")
    ScheduledComputation.objects.get_or_create(
        task_path=TASK_PATH,
        defaults={
            "name":        "NWRFC Forecast Percentile Bands",
            "description": (
                "Computes exceedance percentile bands for the latest NWRFC ForecastRun "
                "per station, covering the next 8 calendar days. Compares each forecasted "
                "discharge against the station's full period-of-record daily_mean observations. "
                "Results are stored in forecast_percentiles (one row per station per date per "
                "source) and served via GET /api/v1/forecasts/discharge/percentile-bands/."
            ),
            "schedule":   "every_6h",
            "is_enabled": True,
        },
    )


def unseed(apps, schema_editor):
    ScheduledComputation = apps.get_model("analytics", "ScheduledComputation")
    ScheduledComputation.objects.filter(task_path=TASK_PATH).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("analytics", "0003_replace_percentile_computation"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
```

- [ ] **Step 6: Apply the data migration**

```bash
python manage.py migrate analytics
```

Expected: `Applying analytics.0004_seed_forecast_percentile_computation... OK`

- [ ] **Step 7: Add beat schedule entry**

In `config/celery.py`, add after the `'compute-daily-flow-percentiles'` entry (after line 122):

```python

    # Analytics: Compute NWRFC forecast percentile bands.
    # Runs every 6 hours to stay current with NWRFC's twice-daily issuance.
    # Upsert semantics make re-runs safe.
    'compute-forecast-percentile-bands': {
        'task': 'src.analytics.tasks.compute_forecast_percentile_bands',
        'schedule': crontab(minute=0, hour='0,6,12,18'),
    },
```

- [ ] **Step 8: Commit**

```bash
git add src/analytics/tasks.py \
        apps/analytics/migrations/0004_seed_forecast_percentile_computation.py \
        config/celery.py \
        tests/test_forecast_percentile_computation.py
git commit -m "feat: add compute_forecast_percentile_bands Celery task and beat schedule"
```

---

## Task 4: API Serializers

**Files:**
- Create: `apps/api/serializers/forecast_percentile.py`
- Modify: `apps/api/serializers/__init__.py`

- [ ] **Step 1: Create serializer file**

Create `apps/api/serializers/forecast_percentile.py`:

```python
"""Serializers for forecast percentile endpoints."""

from rest_framework import serializers


class ForecastPercentileResultSerializer(serializers.Serializer):
    """Single station result within a forecast percentile-bands response."""

    station_number          = serializers.CharField()
    forecast_discharge      = serializers.FloatField()
    percentile_rank         = serializers.FloatField()
    band                    = serializers.CharField()
    historical_record_count = serializers.IntegerField()


class ForecastPercentileBandsResponseSerializer(serializers.Serializer):
    """Top-level envelope for GET /forecasts/discharge/percentile-bands/."""

    date              = serializers.DateField()
    source            = serializers.CharField()
    forecast_run_date = serializers.DateTimeField(allow_null=True)
    computed_at       = serializers.DateTimeField(allow_null=True)
    count             = serializers.IntegerField()
    results           = ForecastPercentileResultSerializer(many=True)


class ForecastPercentileDateRangeSerializer(serializers.Serializer):
    """Date range of available forecast percentile bands, for dashboard rangeslider."""

    source            = serializers.CharField()
    min_date          = serializers.DateField(allow_null=True)
    max_date          = serializers.DateField(allow_null=True)
    forecast_run_date = serializers.DateTimeField(allow_null=True)
```

- [ ] **Step 2: Export from __init__.py**

In `apps/api/serializers/__init__.py`, add after the `from .forecast import (...)` block:

```python
from .forecast_percentile import (
    ForecastPercentileResultSerializer,
    ForecastPercentileBandsResponseSerializer,
    ForecastPercentileDateRangeSerializer,
)
```

And add to `__all__`:

```python
    'ForecastPercentileResultSerializer',
    'ForecastPercentileBandsResponseSerializer',
    'ForecastPercentileDateRangeSerializer',
```

- [ ] **Step 3: Verify import works**

```bash
python manage.py shell -c "from apps.api.serializers import ForecastPercentileBandsResponseSerializer; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add apps/api/serializers/forecast_percentile.py apps/api/serializers/__init__.py
git commit -m "feat: add forecast percentile serializers"
```

---

## Task 5: API Endpoint Actions

**Files:**
- Modify: `apps/api/views/forecast.py`
- Create: `tests/test_api_forecast_percentiles.py`

- [ ] **Step 1: Write the failing API tests**

Create `tests/test_api_forecast_percentiles.py`:

```python
"""Tests for forecast percentile API endpoints."""

from datetime import date, timedelta
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status

from apps.streamflow.models import Station, ForecastPercentile


class ForecastPercentileBandsEndpointTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.station = Station.objects.create(
            station_number='API001',
            name='API Test Station',
            agency='NOAA_RFC',
        )
        self.tomorrow = date.today() + timedelta(days=1)
        self.day2     = date.today() + timedelta(days=2)
        now = timezone.now()

        ForecastPercentile.objects.create(
            station=self.station,
            target_date=self.tomorrow,
            source='NWRFC',
            forecast_run_date=now,
            forecast_discharge=4820.0,
            percentile_rank=72.4,
            band='p51_75',
            historical_record_count=8431,
            computed_at=now,
        )
        ForecastPercentile.objects.create(
            station=self.station,
            target_date=self.day2,
            source='NWRFC',
            forecast_run_date=now,
            forecast_discharge=3200.0,
            percentile_rank=40.0,
            band='p26_50',
            historical_record_count=8431,
            computed_at=now,
        )

    def _url(self):
        return '/api/v1/forecasts/discharge/percentile-bands/'

    def test_returns_200_with_date_param(self):
        response = self.client.get(self._url(), {'date': self.tomorrow.isoformat()})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_response_structure(self):
        response = self.client.get(self._url(), {'date': self.tomorrow.isoformat()})
        data = response.json()
        self.assertIn('date', data)
        self.assertIn('source', data)
        self.assertIn('forecast_run_date', data)
        self.assertIn('computed_at', data)
        self.assertIn('count', data)
        self.assertIn('results', data)

    def test_returns_correct_station_data(self):
        response = self.client.get(self._url(), {'date': self.tomorrow.isoformat()})
        data = response.json()
        self.assertEqual(data['count'], 1)
        result = data['results'][0]
        self.assertEqual(result['station_number'], 'API001')
        self.assertAlmostEqual(result['forecast_discharge'], 4820.0, places=1)
        self.assertEqual(result['band'], 'p51_75')

    def test_date_param_filters_correctly(self):
        response = self.client.get(self._url(), {'date': self.day2.isoformat()})
        data = response.json()
        self.assertEqual(data['count'], 1)
        self.assertAlmostEqual(data['results'][0]['forecast_discharge'], 3200.0, places=1)

    def test_invalid_date_returns_400(self):
        response = self.client.get(self._url(), {'date': 'not-a-date'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_station_filter(self):
        other = Station.objects.create(
            station_number='API002', name='Other', agency='NOAA_RFC'
        )
        ForecastPercentile.objects.create(
            station=other,
            target_date=self.tomorrow,
            source='NWRFC',
            forecast_run_date=timezone.now(),
            forecast_discharge=100.0,
            percentile_rank=10.0,
            band='p5_10',
            historical_record_count=500,
            computed_at=timezone.now(),
        )
        response = self.client.get(self._url(), {
            'date': self.tomorrow.isoformat(),
            'station': 'API001',
        })
        data = response.json()
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['results'][0]['station_number'], 'API001')

    def test_source_param_defaults_to_nwrfc(self):
        response = self.client.get(self._url(), {'date': self.tomorrow.isoformat()})
        self.assertEqual(response.json()['source'], 'NWRFC')

    def test_no_data_for_date_returns_zero_count(self):
        far_future = date.today() + timedelta(days=100)
        response = self.client.get(self._url(), {'date': far_future.isoformat()})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['count'], 0)

    def test_no_caching_headers(self):
        response = self.client.get(self._url(), {'date': self.tomorrow.isoformat()})
        self.assertNotIn('Cache-Control', response)


class ForecastPercentileDateRangeEndpointTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.station = Station.objects.create(
            station_number='RNG001',
            name='Range Test',
            agency='NOAA_RFC',
        )
        now = timezone.now()
        for days in [1, 2, 3, 4, 5]:
            ForecastPercentile.objects.create(
                station=self.station,
                target_date=date.today() + timedelta(days=days),
                source='NWRFC',
                forecast_run_date=now,
                forecast_discharge=1000.0,
                percentile_rank=50.0,
                band='p26_50',
                historical_record_count=500,
                computed_at=now,
            )

    def _url(self):
        return '/api/v1/forecasts/discharge/percentile-date-range/'

    def test_returns_200(self):
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_response_structure(self):
        data = self.client.get(self._url()).json()
        self.assertIn('source', data)
        self.assertIn('min_date', data)
        self.assertIn('max_date', data)
        self.assertIn('forecast_run_date', data)

    def test_correct_date_range(self):
        data = self.client.get(self._url()).json()
        self.assertEqual(data['min_date'], (date.today() + timedelta(days=1)).isoformat())
        self.assertEqual(data['max_date'], (date.today() + timedelta(days=5)).isoformat())

    def test_cache_control_header_set(self):
        response = self.client.get(self._url())
        self.assertIn('Cache-Control', response)
        self.assertIn('max-age=3600', response['Cache-Control'])

    def test_empty_when_no_data(self):
        ForecastPercentile.objects.all().delete()
        data = self.client.get(self._url()).json()
        self.assertIsNone(data['min_date'])
        self.assertIsNone(data['max_date'])
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python manage.py test tests.test_api_forecast_percentiles -v 2
```

Expected: Multiple failures — URLs resolve but endpoints don't exist yet.

- [ ] **Step 3: Add imports to forecast.py**

In `apps/api/views/forecast.py`, make three targeted additions:

**a)** Add `from datetime import date, timedelta` as the first line of the file (before the `rest_framework` import).

**b)** Change line 11 from:
```python
from apps.streamflow.models import ForecastRun
```
to:
```python
from apps.streamflow.models import ForecastRun, ForecastPercentile
```

**c)** Add after the existing `from apps.api.serializers.forecast import (...)` block:
```python
from apps.api.serializers.forecast_percentile import (
    ForecastPercentileBandsResponseSerializer,
    ForecastPercentileDateRangeSerializer,
)
```

- [ ] **Step 4: Add percentile_bands action**

In `apps/api/views/forecast.py`, append inside `ForecastRunViewSet` after the `latest` action (after line 174):

```python

    @extend_schema(
        parameters=[
            OpenApiParameter('date', OpenApiTypes.DATE,
                             description='Forecast date (YYYY-MM-DD). Defaults to earliest available.'),
            OpenApiParameter('source', OpenApiTypes.STR,
                             description='Forecast source label (default: NWRFC).'),
            OpenApiParameter('station', OpenApiTypes.STR,
                             description='Filter to a single station number.'),
        ],
        responses={200: ForecastPercentileBandsResponseSerializer},
    )
    @action(detail=False, methods=['get'], url_path='discharge/percentile-bands')
    def percentile_bands(self, request):
        """
        Return precomputed exceedance percentile bands for all stations with
        NWRFC forecast data on a given date.

        Use ``?date=YYYY-MM-DD`` to drive the dashboard date picker in the
        forecast period. Omit the parameter to get the earliest available date.
        No caching — forecasts update intraday.
        """
        source         = request.query_params.get('source', 'NWRFC')
        station_filter = request.query_params.get('station')

        date_param = request.query_params.get('date')
        if date_param:
            try:
                target_date = date.fromisoformat(date_param)
            except ValueError:
                return Response(
                    {'detail': 'Invalid date format. Use YYYY-MM-DD.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            earliest = ForecastPercentile.objects.filter(
                source=source
            ).aggregate(d=Min('target_date'))['d']
            target_date = earliest or (date.today() + timedelta(days=1))

        queryset = ForecastPercentile.objects.filter(
            target_date=target_date,
            source=source,
        ).select_related('station')

        if station_filter:
            queryset = queryset.filter(station__station_number=station_filter)

        agg = queryset.aggregate(
            computed_at=Max('computed_at'),
            forecast_run_date=Max('forecast_run_date'),
        )

        results = [
            {
                'station_number':          obj.station.station_number,
                'forecast_discharge':      float(obj.forecast_discharge),
                'percentile_rank':         float(obj.percentile_rank),
                'band':                    obj.band,
                'historical_record_count': obj.historical_record_count,
            }
            for obj in queryset
        ]

        return Response({
            'date':              target_date.isoformat(),
            'source':            source,
            'forecast_run_date': agg['forecast_run_date'].isoformat() if agg['forecast_run_date'] else None,
            'computed_at':       agg['computed_at'].isoformat() if agg['computed_at'] else None,
            'count':             len(results),
            'results':           results,
        })

    @extend_schema(
        parameters=[
            OpenApiParameter('source', OpenApiTypes.STR,
                             description='Forecast source label (default: NWRFC).'),
        ],
        responses={200: ForecastPercentileDateRangeSerializer},
    )
    @action(detail=False, methods=['get'], url_path='discharge/percentile-date-range')
    def percentile_date_range(self, request):
        """
        Return the min and max forecast dates available in forecast_percentiles.

        Use this to extend the dashboard rangeslider into the forecast period.
        Response is cached for 1 hour.
        """
        source = request.query_params.get('source', 'NWRFC')

        agg = ForecastPercentile.objects.filter(source=source).aggregate(
            min_date=Min('target_date'),
            max_date=Max('target_date'),
            forecast_run_date=Max('forecast_run_date'),
        )

        response = Response({
            'source':            source,
            'min_date':          agg['min_date'].isoformat() if agg['min_date'] else None,
            'max_date':          agg['max_date'].isoformat() if agg['max_date'] else None,
            'forecast_run_date': agg['forecast_run_date'].isoformat() if agg['forecast_run_date'] else None,
        })
        response['Cache-Control'] = 'public, max-age=3600'
        return response
```

- [ ] **Step 5: Run API tests**

```bash
python manage.py test tests.test_api_forecast_percentiles -v 2
```

Expected: All 14 tests pass.

- [ ] **Step 6: Run full test suite to check for regressions**

```bash
python manage.py test tests -v 1 -k "not selenium and not live and not gee and not earthdata and not nomads and not huc17"
```

Expected: No regressions in existing tests.

- [ ] **Step 7: Commit**

```bash
git add apps/api/views/forecast.py \
        tests/test_api_forecast_percentiles.py
git commit -m "feat: add forecast percentile-bands and percentile-date-range API endpoints"
```

---

## Task 6: Seed Initial Data and Verify End-to-End

- [ ] **Step 1: Run the Celery task manually to populate forecast_percentiles**

```bash
source venv/bin/activate
python manage.py shell -c "
from src.analytics.tasks import compute_forecast_percentile_bands
result = compute_forecast_percentile_bands.apply()
print(result.get())
"
```

Expected output (approximate):
```
{'status': 'success', 'rows_computed': <N>, 'duration_seconds': <T>}
```

If `rows_computed` is 0, check that NOAA_RFC ForecastRuns exist:
```bash
python manage.py shell -c "
from apps.streamflow.models import ForecastRun
print('NOAA_RFC runs:', ForecastRun.objects.filter(source='NOAA_RFC').count())
"
```

- [ ] **Step 2: Verify rows in the database**

```bash
python manage.py shell -c "
from apps.streamflow.models import ForecastPercentile
from django.db.models import Min, Max, Count
agg = ForecastPercentile.objects.filter(source='NWRFC').aggregate(
    rows=Count('id'),
    stations=Count('station', distinct=True),
    min_date=Min('target_date'),
    max_date=Max('target_date'),
)
print(agg)
"
```

Expected: `rows` > 0, `stations` ~240, `min_date` = tomorrow, `max_date` = today+8.

- [ ] **Step 3: Smoke-test the API endpoints**

```bash
curl -s "http://localhost:8000/api/v1/forecasts/discharge/percentile-date-range/" | python -m json.tool
```

Expected: JSON with `min_date`, `max_date`, `source: "NWRFC"`.

```bash
# Replace YYYY-MM-DD with tomorrow's date
curl -s "http://localhost:8000/api/v1/forecasts/discharge/percentile-bands/?date=YYYY-MM-DD" | python -m json.tool | head -20
```

Expected: JSON with `count` > 0 and `results` array containing station band data.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore: verify forecast percentile pipeline end-to-end"
```

---

## Spec Coverage Check

| Spec section | Implemented in |
|---|---|
| `ForecastPercentile` model with all 9 fields | Task 1 |
| Unique constraint `(station, target_date, source)` | Task 1 |
| Indexes on `(station, target_date)` and `(source, target_date)` | Task 1 |
| `compute_forecast_percentiles()` using latest run per station | Task 2 |
| Same COUNT FILTER SQL methodology as observed percentiles | Task 2 |
| Same `classify_band()` function | Task 2 (reused, no change) |
| `MIN_HISTORICAL_RECORDS=30` threshold | Task 2 |
| Stations with no NOAA_RFC runs skipped | Task 2 |
| Celery task with upsert semantics | Task 3 |
| `ScheduledComputation` registration via data migration | Task 3 |
| Beat schedule every 6 hours | Task 3 |
| `GET /api/v1/forecasts/discharge/percentile-bands/` | Task 5 |
| `GET /api/v1/forecasts/discharge/percentile-date-range/` | Task 5 |
| `source` param defaults to `NWRFC` | Task 5 |
| No caching on bands endpoint | Task 5 |
| 1-hour cache on date-range endpoint | Task 5 |
| `forecast_run_date` in both response envelopes | Task 5 |
| Initial data seeded | Task 6 |
