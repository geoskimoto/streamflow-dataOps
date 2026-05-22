# Analytics & Statistics Section Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a user-managed Analytics section to the GUI for configuring scheduled station metadata computations and NOAA flood threshold pulls, with a REST API bulk endpoint for last-observation dates.

**Architecture:** New models in `apps/analytics/` extend the existing `ScheduledComputation` pattern with user-configurable `StatisticsConfiguration` records (one per agency/computation-type combination). A new Celery dispatcher runs hourly and fires due configs — matching the `PullConfiguration` dispatcher pattern in `src/acquisition/tasks.py`. Computed results land in `StationMetadata` (OneToOne per station) and `FloodThreshold` (OneToOne per station), both exposed through the existing DRF API.

**Tech Stack:** Django 4.2, Celery, croniter, PostgreSQL `PERCENTILE_CONT`, DRF, Bootstrap 5, Font Awesome, requests

---

## File Map

| Status | File | Purpose |
|--------|------|---------|
| **Modify** | `apps/analytics/models.py` | Add 5 new models |
| **Create** | `apps/analytics/migrations/0005_analytics_station_statistics.py` | Auto-generated migration |
| **Modify** | `apps/analytics/admin.py` | Register new models |
| **Create** | `src/analytics/station_metadata.py` | PostgreSQL computation logic |
| **Create** | `src/analytics/flood_thresholds.py` | NOAA NWPS API fetcher |
| **Modify** | `src/analytics/tasks.py` | Add dispatcher + two execution tasks |
| **Modify** | `config/celery.py` | Register dispatcher in beat schedule |
| **Modify** | `apps/api/serializers/station.py` | Add `last_observation_date` field |
| **Modify** | `apps/api/views/station.py` | Add `last_observation` bulk action |
| **Create** | `apps/analytics/forms.py` | `StatisticsConfigurationForm` |
| **Replace** | `apps/analytics/views.py` | Full CRUD + dashboard views |
| **Replace** | `apps/analytics/urls.py` | Full URL patterns |
| **Modify** | `config/urls.py` | Add `analytics/` include |
| **Modify** | `templates/base.html` | Add Analytics nav dropdown |
| **Create** | `apps/analytics/templates/analytics/dashboard.html` | Analytics overview |
| **Create** | `apps/analytics/templates/analytics/configuration_list.html` | Config list |
| **Create** | `apps/analytics/templates/analytics/configuration_form.html` | Create/edit form |
| **Create** | `apps/analytics/templates/analytics/configuration_detail.html` | Detail + logs |
| **Create** | `apps/analytics/templates/analytics/configuration_confirm_delete.html` | Delete confirm |
| **Create** | `apps/analytics/templates/analytics/station_metadata_list.html` | Station stats browser |
| **Create** | `tests/test_analytics_models.py` | Model + admin tests |
| **Create** | `tests/test_analytics_tasks.py` | Task logic tests |
| **Create** | `tests/test_analytics_api.py` | API endpoint tests |
| **Create** | `tests/test_analytics_views.py` | View + form tests |

---

## Task 1: Core Analytics Models

**Files:**
- Modify: `apps/analytics/models.py`
- Create: migration via `python manage.py makemigrations analytics`
- Test: `tests/test_analytics_models.py`

### Background

The existing `apps/analytics/models.py` has `ScheduledComputation` (seeded system tasks) and `ComputationLog`. We are adding five new user-managed models. Do not modify the existing models.

- **`StationMetadata`** — OneToOne to Station; caches computed flow statistics + last observation date
- **`FloodThreshold`** — OneToOne to Station; stores NOAA NWPS flood stage/flow thresholds
- **`StatisticsConfiguration`** — User-created config defining what to compute, for which agency, on what schedule
- **`StatisticsConfigurationStation`** — Junction table allowing explicit station selection per config
- **`StatisticsComputationLog`** — Execution audit trail per config run

- [ ] **Step 1.1: Write failing model tests**

Create `tests/test_analytics_models.py`:

```python
"""Tests for analytics models: StationMetadata, FloodThreshold, StatisticsConfiguration."""

from django.test import TestCase
from django.utils import timezone

from apps.analytics.models import (
    FloodThreshold,
    StatisticsComputationLog,
    StatisticsConfiguration,
    StatisticsConfigurationStation,
    StationMetadata,
)
from apps.streamflow.models import Station


def make_station(number='01010000', agency='USGS'):
    return Station.objects.create(station_number=number, name=f'Station {number}', agency=agency)


class StationMetadataTest(TestCase):
    def test_create_and_str(self):
        station = make_station()
        meta = StationMetadata.objects.create(
            station=station,
            last_observation_date='2025-05-01',
            years_on_record=35.5,
            record_completeness_pct=98.2,
            daily_observation_count=12960,
            mean_annual_flow_cfs=4500.00,
            q50_cfs=3200.00,
        )
        self.assertEqual(meta.station, station)
        self.assertIn('01010000', str(meta))

    def test_onetoone_enforced(self):
        station = make_station()
        StationMetadata.objects.create(station=station)
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            StationMetadata.objects.create(station=station)


class FloodThresholdTest(TestCase):
    def test_create_with_thresholds(self):
        station = make_station('02020000')
        ft = FloodThreshold.objects.create(
            station=station,
            noaa_lid='AABC2',
            action_stage_ft=12.5,
            action_flow_cfs=8000,
            minor_stage_ft=15.0,
            minor_flow_cfs=12000,
            moderate_stage_ft=18.0,
            moderate_flow_cfs=20000,
            major_stage_ft=22.0,
            major_flow_cfs=35000,
            source='noaa_api',
        )
        self.assertEqual(ft.source, 'noaa_api')
        self.assertIn('AABC2', str(ft))

    def test_partial_thresholds_allowed(self):
        station = make_station('03030000')
        ft = FloodThreshold.objects.create(station=station, noaa_lid='XYZW1')
        self.assertIsNone(ft.action_stage_ft)
        self.assertIsNone(ft.major_flow_cfs)


class StatisticsConfigurationTest(TestCase):
    def test_create_annual_config(self):
        config = StatisticsConfiguration.objects.create(
            name='USGS Annual Metadata',
            computation_type='station_metadata',
            agency_filter='USGS',
            schedule_type='annual',
            annual_run_month=10,
            annual_run_day=1,
        )
        self.assertTrue(config.is_enabled)
        self.assertIsNone(config.last_run_at)
        self.assertIsNone(config.next_run_at)

    def test_unique_name(self):
        StatisticsConfiguration.objects.create(name='Dupe', computation_type='station_metadata')
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            StatisticsConfiguration.objects.create(name='Dupe', computation_type='station_metadata')

    def test_get_station_queryset_all_agency(self):
        s1 = make_station('AAA', 'USGS')
        s2 = make_station('BBB', 'EC')
        config = StatisticsConfiguration.objects.create(
            name='All Metadata', computation_type='station_metadata', agency_filter='ALL',
        )
        qs = config.get_station_queryset()
        self.assertIn(s1, qs)
        self.assertIn(s2, qs)

    def test_get_station_queryset_agency_filter(self):
        usgs = make_station('USG1', 'USGS')
        ec = make_station('EC01', 'EC')
        config = StatisticsConfiguration.objects.create(
            name='USGS Only', computation_type='station_metadata', agency_filter='USGS',
        )
        qs = config.get_station_queryset()
        self.assertIn(usgs, qs)
        self.assertNotIn(ec, qs)

    def test_get_station_queryset_explicit_stations(self):
        s1 = make_station('STA1', 'USGS')
        s2 = make_station('STA2', 'USGS')
        s3 = make_station('STA3', 'USGS')
        config = StatisticsConfiguration.objects.create(
            name='Explicit', computation_type='station_metadata', agency_filter='USGS',
        )
        StatisticsConfigurationStation.objects.create(configuration=config, station=s1)
        StatisticsConfigurationStation.objects.create(configuration=config, station=s2)
        qs = config.get_station_queryset()
        self.assertIn(s1, qs)
        self.assertIn(s2, qs)
        self.assertNotIn(s3, qs)


class StatisticsComputationLogTest(TestCase):
    def setUp(self):
        self.config = StatisticsConfiguration.objects.create(
            name='Test Config', computation_type='station_metadata',
        )

    def test_log_lifecycle(self):
        log = StatisticsComputationLog.objects.create(
            configuration=self.config,
            status='running',
            started_at=timezone.now(),
        )
        self.assertEqual(log.status, 'running')
        log.status = 'success'
        log.stations_processed = 309
        log.save()
        self.assertEqual(log.status, 'success')

    def test_ordered_by_started_at_desc(self):
        t1 = timezone.now()
        t2 = timezone.now()
        log1 = StatisticsComputationLog.objects.create(
            configuration=self.config, status='success', started_at=t1,
        )
        log2 = StatisticsComputationLog.objects.create(
            configuration=self.config, status='failed', started_at=t2,
        )
        logs = list(StatisticsComputationLog.objects.all())
        self.assertEqual(logs[0], log2)
```

- [ ] **Step 1.2: Run tests to confirm they fail**

```bash
cd /home/streamflow/streamflow-dataOps/streamflow-dataOps && source venv/bin/activate
python manage.py test tests.test_analytics_models -v 2 2>&1 | head -30
```
Expected: `ImportError` — models don't exist yet.

- [ ] **Step 1.3: Add new models to `apps/analytics/models.py`**

Append to the end of the existing file (after `ComputationLog`):

```python
from apps.streamflow.models import Station as _Station  # noqa: E402  (avoid circular at class body level)


class StationMetadata(models.Model):
    """Cached computed statistics per station. Refreshed on schedule."""

    station = models.OneToOneField(
        'streamflow.Station',
        on_delete=models.CASCADE,
        related_name='metadata',
        db_index=True,
    )

    # Record bounds
    last_observation_date = models.DateField(null=True, blank=True, db_index=True)
    record_start_date = models.DateField(null=True, blank=True)
    record_end_date = models.DateField(null=True, blank=True)
    years_on_record = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)

    # Data quality
    daily_observation_count = models.IntegerField(null=True, blank=True)
    record_completeness_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    # Flow statistics (cfs, daily_mean observations)
    mean_annual_flow_cfs = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    q10_cfs = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    q25_cfs = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    q50_cfs = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    q75_cfs = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    q90_cfs = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    computed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'station_metadata'

    def __str__(self):
        return f"Metadata: {self.station.station_number}"


class FloodThreshold(models.Model):
    """NWS flood stage and flow thresholds per station, sourced from NOAA NWPS API."""

    SOURCE_CHOICES = [
        ('noaa_api', 'NOAA API'),
        ('manual', 'Manual'),
    ]

    station = models.OneToOneField(
        'streamflow.Station',
        on_delete=models.CASCADE,
        related_name='flood_threshold',
        db_index=True,
    )
    noaa_lid = models.CharField(max_length=50, blank=True, help_text='NOAA HADS Location ID used for lookup')

    action_stage_ft = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    action_flow_cfs = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    minor_stage_ft = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    minor_flow_cfs = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    moderate_stage_ft = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    moderate_flow_cfs = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    major_stage_ft = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    major_flow_cfs = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    record_stage_ft = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    record_flow_cfs = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='noaa_api')
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'flood_thresholds'

    def __str__(self):
        return f"FloodThreshold: {self.station.station_number} ({self.noaa_lid})"


class StatisticsConfiguration(models.Model):
    """User-managed scheduled analytics configuration. One per agency/computation-type."""

    COMPUTATION_TYPE_CHOICES = [
        ('station_metadata', 'Station Metadata & Statistics'),
        ('flood_thresholds', 'Flood Thresholds (NOAA NWPS)'),
        ('percentile_backfill', 'Percentile Band Backfill'),
    ]

    AGENCY_CHOICES = [
        ('ALL', 'All Agencies'),
        ('USGS', 'USGS'),
        ('EC', 'Environment Canada'),
        ('NOAA_RFC', 'NOAA RFC'),
    ]

    SCHEDULE_TYPE_CHOICES = [
        ('annual', 'Annual'),
        ('monthly', 'Monthly'),
        ('weekly', 'Weekly'),
        ('daily', 'Daily'),
        ('custom', 'Custom Cron'),
    ]

    name = models.CharField(max_length=200, unique=True)
    description = models.TextField(blank=True)
    computation_type = models.CharField(max_length=30, choices=COMPUTATION_TYPE_CHOICES)
    agency_filter = models.CharField(max_length=20, choices=AGENCY_CHOICES, default='ALL')

    # Schedule fields
    schedule_type = models.CharField(max_length=20, choices=SCHEDULE_TYPE_CHOICES, default='annual')
    annual_run_month = models.IntegerField(
        default=10,
        help_text='Month for annual runs (1–12). Default: 10 (October, water year start).',
    )
    annual_run_day = models.IntegerField(
        default=1,
        help_text='Day of month for annual runs (1–31). Default: 1.',
    )
    schedule_value = models.CharField(
        max_length=100,
        blank=True,
        help_text='Cron expression for custom schedule (5 fields: min hr dom mon dow)',
    )

    # Status
    is_enabled = models.BooleanField(default=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    next_run_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'statistics_configurations'
        ordering = ['name']

    def __str__(self):
        return self.name

    def get_station_queryset(self):
        """Returns stations to process: explicit M2M selection or all matching agency_filter."""
        from apps.streamflow.models import Station
        explicit_ids = self.stations.values_list('station_id', flat=True)
        if explicit_ids.exists():
            return Station.objects.filter(id__in=explicit_ids)
        if self.agency_filter == 'ALL':
            return Station.objects.all()
        return Station.objects.filter(agency=self.agency_filter)


class StatisticsConfigurationStation(models.Model):
    """Explicit station selection for a StatisticsConfiguration (optional override)."""

    configuration = models.ForeignKey(
        StatisticsConfiguration,
        on_delete=models.CASCADE,
        related_name='stations',
    )
    station = models.ForeignKey(
        'streamflow.Station',
        on_delete=models.CASCADE,
    )

    class Meta:
        db_table = 'statistics_configuration_stations'
        unique_together = [('configuration', 'station')]

    def __str__(self):
        return f"{self.configuration.name} – {self.station.station_number}"


class StatisticsComputationLog(models.Model):
    """Execution history for statistics configuration runs."""

    STATUS_CHOICES = [
        ('running', 'Running'),
        ('success', 'Success'),
        ('failed', 'Failed'),
        ('partial', 'Partial Success'),
    ]

    configuration = models.ForeignKey(
        StatisticsConfiguration,
        on_delete=models.CASCADE,
        related_name='logs',
        db_index=True,
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    celery_task_id = models.CharField(max_length=255, blank=True, db_index=True)
    started_at = models.DateTimeField(db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    stations_processed = models.IntegerField(null=True, blank=True)
    records_computed = models.IntegerField(null=True, blank=True)
    error_message = models.TextField(blank=True)

    class Meta:
        db_table = 'statistics_computation_logs'
        indexes = [
            models.Index(fields=['configuration', 'started_at'], name='idx_stat_log_config_started'),
            models.Index(fields=['status'], name='idx_stat_log_status'),
        ]
        ordering = ['-started_at']

    def __str__(self):
        return f"{self.configuration.name} – {self.status} – {self.started_at}"
```

Note: Remove the stray import at the top of the appended block — the `_Station` import is not needed since we reference `'streamflow.Station'` as a string. The models block only needs `from django.db import models` which is already imported.

- [ ] **Step 1.4: Generate and apply migration**

```bash
cd /home/streamflow/streamflow-dataOps/streamflow-dataOps && source venv/bin/activate
python manage.py makemigrations analytics --name analytics_station_statistics
python manage.py migrate analytics
```

Expected: Migration created and applied with no errors.

- [ ] **Step 1.5: Run tests to confirm they pass**

```bash
python manage.py test tests.test_analytics_models -v 2
```

Expected: All tests pass.

- [ ] **Step 1.6: Commit**

```bash
cd /home/streamflow/streamflow-dataOps/streamflow-dataOps
git add apps/analytics/models.py apps/analytics/migrations/0005_analytics_station_statistics.py tests/test_analytics_models.py
git commit -m "feat: add StationMetadata, FloodThreshold, StatisticsConfiguration models"
```

---

## Task 2: Admin Registration

**Files:**
- Modify: `apps/analytics/admin.py`

- [ ] **Step 2.1: Add new model registrations to `apps/analytics/admin.py`**

Append after the existing `ComputationLogAdmin`:

```python
from apps.analytics.models import (
    ComputationLog,
    FloodThreshold,
    ScheduledComputation,
    StatisticsComputationLog,
    StatisticsConfiguration,
    StatisticsConfigurationStation,
    StationMetadata,
)


@admin.register(StationMetadata)
class StationMetadataAdmin(admin.ModelAdmin):
    list_display = ['station', 'last_observation_date', 'years_on_record', 'mean_annual_flow_cfs', 'computed_at']
    search_fields = ['station__station_number', 'station__name']
    ordering = ['station__station_number']
    readonly_fields = [
        'station', 'last_observation_date', 'record_start_date', 'record_end_date',
        'years_on_record', 'daily_observation_count', 'record_completeness_pct',
        'mean_annual_flow_cfs', 'q10_cfs', 'q25_cfs', 'q50_cfs', 'q75_cfs', 'q90_cfs',
        'computed_at',
    ]


@admin.register(FloodThreshold)
class FloodThresholdAdmin(admin.ModelAdmin):
    list_display = ['station', 'noaa_lid', 'action_stage_ft', 'minor_stage_ft', 'major_stage_ft', 'source', 'last_updated']
    search_fields = ['station__station_number', 'noaa_lid']
    list_filter = ['source']
    readonly_fields = ['last_updated']


@admin.register(StatisticsConfiguration)
class StatisticsConfigurationAdmin(admin.ModelAdmin):
    list_display = ['name', 'computation_type', 'agency_filter', 'schedule_type', 'is_enabled', 'last_run_at', 'next_run_at']
    list_filter = ['computation_type', 'agency_filter', 'schedule_type', 'is_enabled']
    search_fields = ['name']
    readonly_fields = ['last_run_at', 'next_run_at', 'created_at', 'updated_at']


@admin.register(StatisticsConfigurationStation)
class StatisticsConfigurationStationAdmin(admin.ModelAdmin):
    list_display = ['configuration', 'station']
    search_fields = ['configuration__name', 'station__station_number']


@admin.register(StatisticsComputationLog)
class StatisticsComputationLogAdmin(admin.ModelAdmin):
    list_display = ['configuration', 'status', 'stations_processed', 'duration_seconds', 'started_at']
    list_filter = ['status', 'configuration']
    search_fields = ['configuration__name', 'celery_task_id']
    ordering = ['-started_at']
    readonly_fields = [
        'configuration', 'status', 'celery_task_id', 'started_at',
        'completed_at', 'duration_seconds', 'stations_processed', 'records_computed', 'error_message',
    ]
```

Update the import at the top of the file to consolidate (replace existing imports):

```python
from django.contrib import admin

from apps.analytics.models import (
    ComputationLog,
    FloodThreshold,
    ScheduledComputation,
    StatisticsComputationLog,
    StatisticsConfiguration,
    StatisticsConfigurationStation,
    StationMetadata,
)
```

- [ ] **Step 2.2: Verify admin loads**

```bash
cd /home/streamflow/streamflow-dataOps/streamflow-dataOps && source venv/bin/activate
python manage.py check
```

Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 2.3: Commit**

```bash
git add apps/analytics/admin.py
git commit -m "feat: register StationMetadata, FloodThreshold, StatisticsConfiguration in admin"
```

---

## Task 3: Station Metadata Computation Logic

**Files:**
- Create: `src/analytics/station_metadata.py`
- Test: `tests/test_analytics_tasks.py` (partial — metadata section)

### Background

Computes `StationMetadata` for a set of stations using a single PostgreSQL query per batch. Uses `PERCENTILE_CONT` for flow duration statistics and window math for completeness. Operates only on `daily_mean` type observations with `discharge >= 0`. Upsert semantics (safe to re-run).

The function signature is `compute_station_metadata(station_ids=None)` where `station_ids` is a list of integer PKs. If `None`, runs for all stations.

- [ ] **Step 3.1: Write failing tests for station metadata computation**

Add to `tests/test_analytics_tasks.py`:

```python
"""Tests for analytics computation tasks."""

from datetime import date, timedelta
from unittest.mock import patch, MagicMock

from django.test import TestCase
from django.utils import timezone

from apps.analytics.models import StationMetadata, StatisticsConfiguration, StatisticsComputationLog
from apps.streamflow.models import Station, DischargeObservation


def make_station(number='01010000', agency='USGS'):
    return Station.objects.create(station_number=number, name=f'Station {number}', agency=agency)


def add_daily_obs(station, start_date, days, base_discharge=1000.0):
    obs = []
    for i in range(days):
        obs.append(DischargeObservation(
            station=station,
            observed_at=timezone.make_aware(
                timezone.datetime.combine(start_date + timedelta(days=i), timezone.datetime.min.time())
            ),
            discharge=base_discharge + i,
            unit='cfs',
            type='daily_mean',
            quality_code='P',
        ))
    DischargeObservation.objects.bulk_create(obs, ignore_conflicts=True)


class StationMetadataComputationTest(TestCase):
    def setUp(self):
        self.station = make_station('META001')
        self.start = date(2020, 1, 1)
        add_daily_obs(self.station, self.start, 365 * 3)  # 3 years of data

    def test_compute_creates_metadata(self):
        from src.analytics.station_metadata import compute_station_metadata
        count = compute_station_metadata(station_ids=[self.station.id])
        self.assertEqual(count, 1)
        meta = StationMetadata.objects.get(station=self.station)
        self.assertIsNotNone(meta.last_observation_date)
        self.assertIsNotNone(meta.mean_annual_flow_cfs)
        self.assertIsNotNone(meta.q50_cfs)
        self.assertGreater(meta.years_on_record, 2)

    def test_compute_upserts_on_rerun(self):
        from src.analytics.station_metadata import compute_station_metadata
        compute_station_metadata(station_ids=[self.station.id])
        compute_station_metadata(station_ids=[self.station.id])
        self.assertEqual(StationMetadata.objects.filter(station=self.station).count(), 1)

    def test_compute_all_stations(self):
        s2 = make_station('META002')
        add_daily_obs(s2, self.start, 365)
        from src.analytics.station_metadata import compute_station_metadata
        count = compute_station_metadata()
        self.assertGreaterEqual(count, 2)

    def test_station_with_no_obs_skipped(self):
        empty = make_station('EMPTY001')
        from src.analytics.station_metadata import compute_station_metadata
        count = compute_station_metadata(station_ids=[empty.id])
        self.assertEqual(count, 0)
        self.assertFalse(StationMetadata.objects.filter(station=empty).exists())

    def test_last_observation_date_correct(self):
        from src.analytics.station_metadata import compute_station_metadata
        compute_station_metadata(station_ids=[self.station.id])
        meta = StationMetadata.objects.get(station=self.station)
        expected = self.start + timedelta(days=365 * 3 - 1)
        self.assertEqual(meta.last_observation_date, expected)

    def test_completeness_pct_range(self):
        from src.analytics.station_metadata import compute_station_metadata
        compute_station_metadata(station_ids=[self.station.id])
        meta = StationMetadata.objects.get(station=self.station)
        self.assertGreater(float(meta.record_completeness_pct), 0)
        self.assertLessEqual(float(meta.record_completeness_pct), 100)
```

- [ ] **Step 3.2: Run tests to confirm they fail**

```bash
python manage.py test tests.test_analytics_tasks.StationMetadataComputationTest -v 2 2>&1 | head -20
```

Expected: `ImportError: cannot import name 'compute_station_metadata'`

- [ ] **Step 3.3: Create `src/analytics/station_metadata.py`**

```python
"""Station metadata computation: flow statistics and record bounds via PostgreSQL."""

import logging
from decimal import Decimal

from django.db import connection
from django.utils import timezone

logger = logging.getLogger(__name__)


def compute_station_metadata(station_ids=None):
    """Compute and upsert StationMetadata for stations with daily_mean observations.

    Args:
        station_ids: List of Station PKs to process. None means all stations.

    Returns:
        Number of StationMetadata rows upserted.
    """
    from apps.analytics.models import StationMetadata

    station_filter_sql = ''
    params = []
    if station_ids:
        station_filter_sql = 'AND o.station_id = ANY(%s)'
        params.append(list(station_ids))

    sql = f"""
        WITH obs_stats AS (
            SELECT
                o.station_id,
                MAX(o.observed_at AT TIME ZONE 'UTC')::date          AS last_obs_date,
                MIN(o.observed_at AT TIME ZONE 'UTC')::date          AS rec_start,
                MAX(o.observed_at AT TIME ZONE 'UTC')::date          AS rec_end,
                COUNT(*)                                              AS obs_count,
                AVG(o.discharge)                                      AS mean_flow,
                PERCENTILE_CONT(0.10) WITHIN GROUP (ORDER BY o.discharge) AS q10,
                PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY o.discharge) AS q25,
                PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY o.discharge) AS q50,
                PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY o.discharge) AS q75,
                PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY o.discharge) AS q90
            FROM streamflow_dischargeobservation o
            WHERE o.type = 'daily_mean'
              AND o.discharge IS NOT NULL
              AND o.discharge >= 0
              {station_filter_sql}
            GROUP BY o.station_id
        )
        SELECT
            station_id,
            last_obs_date,
            rec_start,
            rec_end,
            obs_count,
            CASE
                WHEN rec_end > rec_start THEN
                    ROUND(
                        obs_count::numeric /
                        (rec_end - rec_start + 1) * 100,
                        2
                    )
                ELSE 100.0
            END                                            AS completeness_pct,
            ROUND(
                (rec_end - rec_start)::numeric / 365.25,
                2
            )                                              AS years_on_record,
            ROUND(mean_flow::numeric, 2)                   AS mean_flow,
            ROUND(q10::numeric, 2)                         AS q10,
            ROUND(q25::numeric, 2)                         AS q25,
            ROUND(q50::numeric, 2)                         AS q50,
            ROUND(q75::numeric, 2)                         AS q75,
            ROUND(q90::numeric, 2)                         AS q90
        FROM obs_stats
    """

    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        rows = cursor.fetchall()

    if not rows:
        logger.info('compute_station_metadata: no rows returned (no qualifying observations)')
        return 0

    now = timezone.now()
    upsert_count = 0

    for row in rows:
        (station_id, last_obs_date, rec_start, rec_end,
         obs_count, completeness_pct, years_on_record,
         mean_flow, q10, q25, q50, q75, q90) = row

        StationMetadata.objects.update_or_create(
            station_id=station_id,
            defaults={
                'last_observation_date': last_obs_date,
                'record_start_date': rec_start,
                'record_end_date': rec_end,
                'daily_observation_count': obs_count,
                'record_completeness_pct': completeness_pct,
                'years_on_record': years_on_record,
                'mean_annual_flow_cfs': mean_flow,
                'q10_cfs': q10,
                'q25_cfs': q25,
                'q50_cfs': q50,
                'q75_cfs': q75,
                'q90_cfs': q90,
                'computed_at': now,
            },
        )
        upsert_count += 1

    logger.info('compute_station_metadata: upserted %d rows', upsert_count)
    return upsert_count
```

- [ ] **Step 3.4: Run tests to confirm they pass**

```bash
python manage.py test tests.test_analytics_tasks.StationMetadataComputationTest -v 2
```

Expected: All 6 tests pass.

- [ ] **Step 3.5: Commit**

```bash
git add src/analytics/station_metadata.py tests/test_analytics_tasks.py
git commit -m "feat: add station metadata computation logic with PostgreSQL percentile queries"
```

---

## Task 4: NOAA NWPS Flood Threshold Fetcher

**Files:**
- Create: `src/analytics/flood_thresholds.py`
- Test: `tests/test_analytics_tasks.py` (add FloodThreshold section)

### Background

The NOAA NWPS API base URL `https://api.water.noaa.gov/nwps/v1` is already used by `NOAAClient` in `src/acquisition/noaa_client.py`. This new module calls `GET /gauges/{lid}` to retrieve gauge metadata including flood stage thresholds.

**HADS LID resolution priority:**
1. NOAA_RFC stations: `station.station_number` is already the HADS LID
2. USGS stations: look up `MasterStation.noaa_lid` where `station_number` matches
3. Any agency: check `StationMapping` for a mapping to `NOAA_RFC`

**API response structure (verify at runtime):** The `/gauges/{lid}` endpoint returns JSON. The flood thresholds are under `flood.stageflow` or `flood.categories`. Each category has `stage` (ft) and optionally `flow` (cfs). Null/missing values are stored as NULL in the database. Not all gauges have all threshold levels.

- [ ] **Step 4.1: Add flood threshold tests to `tests/test_analytics_tasks.py`**

Add after the `StationMetadataComputationTest` class:

```python
class FloodThresholdFetcherTest(TestCase):
    def setUp(self):
        self.noaa_station = make_station('PNCO3', 'NOAA_RFC')
        self.usgs_station = make_station('14211010', 'USGS')

    @patch('src.analytics.flood_thresholds.requests.get')
    def test_fetch_noaa_rfc_station(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                'gaugeId': 'PNCO3',
                'flood': {
                    'stageflow': {
                        'action': {'stage': 12.5, 'flow': 8000},
                        'flood': {'stage': 15.0, 'flow': 12000},
                        'moderate': {'stage': 18.0, 'flow': 20000},
                        'major': {'stage': 22.0, 'flow': 35000},
                    }
                }
            }
        )
        mock_get.return_value.raise_for_status = lambda: None

        from src.analytics.flood_thresholds import fetch_flood_thresholds_for_stations
        result = fetch_flood_thresholds_for_stations([self.noaa_station.id])

        self.assertEqual(result['updated'], 1)
        self.assertEqual(result['errors'], 0)

        from apps.analytics.models import FloodThreshold
        ft = FloodThreshold.objects.get(station=self.noaa_station)
        self.assertEqual(ft.noaa_lid, 'PNCO3')
        self.assertEqual(float(ft.action_stage_ft), 12.5)
        self.assertEqual(float(ft.minor_stage_ft), 15.0)
        self.assertEqual(float(ft.moderate_stage_ft), 18.0)
        self.assertEqual(float(ft.major_stage_ft), 22.0)
        self.assertIsNone(ft.record_stage_ft)

    @patch('src.analytics.flood_thresholds.requests.get')
    def test_api_error_counted_not_raised(self, mock_get):
        mock_get.return_value = MagicMock(raise_for_status=MagicMock(side_effect=Exception('timeout')))

        from src.analytics.flood_thresholds import fetch_flood_thresholds_for_stations
        result = fetch_flood_thresholds_for_stations([self.noaa_station.id])

        self.assertEqual(result['errors'], 1)
        self.assertEqual(result['updated'], 0)

    def test_station_without_hads_lid_skipped(self):
        from src.analytics.flood_thresholds import fetch_flood_thresholds_for_stations
        result = fetch_flood_thresholds_for_stations([self.usgs_station.id])
        self.assertEqual(result['skipped'], 1)
        self.assertEqual(result['updated'], 0)

    @patch('src.analytics.flood_thresholds.requests.get')
    def test_upsert_on_rerun(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {'flood': {'stageflow': {'action': {'stage': 10.0, 'flow': None}}}}
        )
        mock_get.return_value.raise_for_status = lambda: None

        from src.analytics.flood_thresholds import fetch_flood_thresholds_for_stations
        fetch_flood_thresholds_for_stations([self.noaa_station.id])
        fetch_flood_thresholds_for_stations([self.noaa_station.id])

        from apps.analytics.models import FloodThreshold
        self.assertEqual(FloodThreshold.objects.filter(station=self.noaa_station).count(), 1)
```

- [ ] **Step 4.2: Run tests to confirm they fail**

```bash
python manage.py test tests.test_analytics_tasks.FloodThresholdFetcherTest -v 2 2>&1 | head -10
```

Expected: `ImportError: cannot import name 'fetch_flood_thresholds_for_stations'`

- [ ] **Step 4.3: Create `src/analytics/flood_thresholds.py`**

```python
"""NOAA NWPS flood threshold fetcher. Calls /gauges/{lid} and upserts FloodThreshold rows."""

import logging

import requests

logger = logging.getLogger(__name__)

NWPS_BASE_URL = 'https://api.water.noaa.gov/nwps/v1'
REQUEST_TIMEOUT = 15


def _resolve_hads_lid(station):
    """Return the NOAA HADS LID for a station, or None if unavailable."""
    from apps.streamflow.models import MasterStation, StationMapping

    if station.agency == 'NOAA_RFC':
        return station.station_number

    # USGS: try MasterStation.noaa_lid
    try:
        master = MasterStation.objects.get(station_number=station.station_number, agency='USGS')
        if master.noaa_lid:
            return master.noaa_lid
    except MasterStation.DoesNotExist:
        pass

    # Any agency: try StationMapping for a NOAA_RFC target
    mapping = StationMapping.objects.filter(
        source_agency=station.agency,
        source_id=station.station_number,
        target_agency='NOAA_RFC',
    ).first()
    if mapping:
        return mapping.target_id

    return None


def _extract_threshold(stageflow, category, field):
    """Safely extract a numeric threshold value from the stageflow dict."""
    value = stageflow.get(category, {}).get(field)
    if value is None or value == '':
        return None
    try:
        return float(value) if value else None
    except (TypeError, ValueError):
        return None


def fetch_flood_thresholds_for_stations(station_ids):
    """Fetch NOAA NWPS flood thresholds and upsert FloodThreshold for given station PKs.

    NWPS API: GET /gauges/{lid}
    Response path: flood.stageflow.{action|flood|moderate|major|record}.{stage|flow}
    Note: NWPS uses 'flood' for what NWS calls minor flood stage. Stored as minor_* here.

    Returns:
        dict with keys: updated, skipped, errors
    """
    from apps.analytics.models import FloodThreshold
    from apps.streamflow.models import Station

    stations = Station.objects.filter(id__in=station_ids)
    updated = skipped = errors = 0

    for station in stations:
        lid = _resolve_hads_lid(station)
        if not lid:
            logger.debug('No HADS LID for %s, skipping', station.station_number)
            skipped += 1
            continue

        try:
            response = requests.get(
                f'{NWPS_BASE_URL}/gauges/{lid}',
                timeout=REQUEST_TIMEOUT,
                headers={'Accept': 'application/json'},
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            logger.error('NWPS API error for %s (lid=%s): %s', station.station_number, lid, exc)
            errors += 1
            continue

        flood = data.get('flood') or {}
        stageflow = flood.get('stageflow') or flood.get('categories') or {}

        FloodThreshold.objects.update_or_create(
            station=station,
            defaults={
                'noaa_lid': lid,
                'action_stage_ft': _extract_threshold(stageflow, 'action', 'stage'),
                'action_flow_cfs': _extract_threshold(stageflow, 'action', 'flow'),
                # NWPS 'flood' category = NWS minor flood stage
                'minor_stage_ft': _extract_threshold(stageflow, 'flood', 'stage'),
                'minor_flow_cfs': _extract_threshold(stageflow, 'flood', 'flow'),
                'moderate_stage_ft': _extract_threshold(stageflow, 'moderate', 'stage'),
                'moderate_flow_cfs': _extract_threshold(stageflow, 'moderate', 'flow'),
                'major_stage_ft': _extract_threshold(stageflow, 'major', 'stage'),
                'major_flow_cfs': _extract_threshold(stageflow, 'major', 'flow'),
                'record_stage_ft': _extract_threshold(stageflow, 'record', 'stage'),
                'record_flow_cfs': _extract_threshold(stageflow, 'record', 'flow'),
                'source': 'noaa_api',
            },
        )
        updated += 1
        logger.debug('Updated flood thresholds for %s (lid=%s)', station.station_number, lid)

    logger.info(
        'fetch_flood_thresholds: updated=%d, skipped=%d, errors=%d', updated, skipped, errors
    )
    return {'updated': updated, 'skipped': skipped, 'errors': errors}
```

- [ ] **Step 4.4: Run tests to confirm they pass**

```bash
python manage.py test tests.test_analytics_tasks.FloodThresholdFetcherTest -v 2
```

Expected: All 4 tests pass.

- [ ] **Step 4.5: Commit**

```bash
git add src/analytics/flood_thresholds.py tests/test_analytics_tasks.py
git commit -m "feat: add NOAA NWPS flood threshold fetcher with HADS LID resolution"
```

---

## Task 5: Celery Tasks + Dispatcher + Beat Schedule

**Files:**
- Modify: `src/analytics/tasks.py`
- Modify: `config/celery.py`
- Test: `tests/test_analytics_tasks.py` (add dispatcher section)

### Background

Add three tasks to `src/analytics/tasks.py`:

1. `dispatch_statistics_computations` — hourly dispatcher (mirrors `scheduled_streamflow_pulls` in `src/acquisition/tasks.py`)
2. `run_station_metadata_task(config_id)` — executes metadata computation for one config
3. `run_flood_thresholds_task(config_id)` — executes flood threshold fetch for one config

The dispatcher uses `_compute_stats_next_run()` which supports `annual`, `monthly`, `weekly`, `daily`, `custom` schedule types via croniter.

- [ ] **Step 5.1: Add dispatcher tests to `tests/test_analytics_tasks.py`**

Add after the `FloodThresholdFetcherTest` class:

```python
class StatisticsDispatcherTest(TestCase):
    def setUp(self):
        self.config = StatisticsConfiguration.objects.create(
            name='Test Dispatch',
            computation_type='station_metadata',
            agency_filter='ALL',
            schedule_type='monthly',
            is_enabled=True,
            next_run_at=None,  # overdue — should dispatch
        )

    @patch('src.analytics.tasks.run_station_metadata_task')
    def test_dispatcher_fires_overdue_config(self, mock_task):
        from src.analytics.tasks import dispatch_statistics_computations
        result = dispatch_statistics_computations()
        mock_task.delay.assert_called_once_with(self.config.id)
        self.assertEqual(result['dispatched'], 1)

    @patch('src.analytics.tasks.run_station_metadata_task')
    def test_dispatcher_skips_future_config(self, mock_task):
        from django.utils import timezone
        from datetime import timedelta
        self.config.next_run_at = timezone.now() + timedelta(days=10)
        self.config.save()
        from src.analytics.tasks import dispatch_statistics_computations
        result = dispatch_statistics_computations()
        mock_task.delay.assert_not_called()
        self.assertEqual(result['dispatched'], 0)

    @patch('src.analytics.tasks.run_station_metadata_task')
    def test_dispatcher_skips_disabled_config(self, mock_task):
        self.config.is_enabled = False
        self.config.save()
        from src.analytics.tasks import dispatch_statistics_computations
        result = dispatch_statistics_computations()
        mock_task.delay.assert_not_called()

    @patch('src.analytics.tasks.run_station_metadata_task')
    def test_dispatcher_skips_already_running(self, mock_task):
        from django.utils import timezone
        StatisticsComputationLog.objects.create(
            configuration=self.config,
            status='running',
            started_at=timezone.now(),
        )
        from src.analytics.tasks import dispatch_statistics_computations
        result = dispatch_statistics_computations()
        mock_task.delay.assert_not_called()

    def test_compute_stats_next_run_monthly(self):
        from src.analytics.tasks import _compute_stats_next_run
        from django.utils import timezone as tz
        now = tz.now()
        next_run = _compute_stats_next_run(now, self.config)
        self.assertGreater(next_run, now)

    def test_compute_stats_next_run_annual(self):
        from src.analytics.tasks import _compute_stats_next_run
        from django.utils import timezone as tz
        self.config.schedule_type = 'annual'
        self.config.annual_run_month = 10
        self.config.annual_run_day = 1
        now = tz.now()
        next_run = _compute_stats_next_run(now, self.config)
        self.assertGreater(next_run, now)
        self.assertEqual(next_run.month, 10)
        self.assertEqual(next_run.day, 1)
```

- [ ] **Step 5.2: Run tests to confirm they fail**

```bash
python manage.py test tests.test_analytics_tasks.StatisticsDispatcherTest -v 2 2>&1 | head -10
```

Expected: `ImportError: cannot import name 'dispatch_statistics_computations'`

- [ ] **Step 5.3: Add tasks to `src/analytics/tasks.py`**

Append the following to the end of the existing `src/analytics/tasks.py` file (after the existing tasks):

```python
# ---------------------------------------------------------------------------
# Statistics Configuration dispatcher and execution tasks
# ---------------------------------------------------------------------------

def _compute_stats_next_run(from_time, config):
    """Compute next run datetime for a StatisticsConfiguration using croniter."""
    from croniter import croniter
    from datetime import datetime

    schedule_type = config.schedule_type

    if schedule_type == 'daily':
        cron_expr = '0 0 * * *'
    elif schedule_type == 'weekly':
        cron_expr = '0 0 * * 0'
    elif schedule_type == 'monthly':
        cron_expr = '0 0 1 * *'
    elif schedule_type == 'annual':
        day = max(1, min(31, config.annual_run_day))
        month = max(1, min(12, config.annual_run_month))
        cron_expr = f'0 0 {day} {month} *'
    elif schedule_type == 'custom':
        if not config.schedule_value:
            raise ValueError(f'StatisticsConfiguration {config.id} has custom schedule but no schedule_value')
        cron_expr = config.schedule_value
    else:
        raise ValueError(f'Unknown schedule_type: {schedule_type!r}')

    it = croniter(cron_expr, from_time)
    return it.get_next(datetime)


@shared_task
def dispatch_statistics_computations():
    """Hourly dispatcher: fires StatisticsConfiguration tasks that are due."""
    from apps.analytics.models import StatisticsConfiguration, StatisticsComputationLog
    from django.utils import timezone

    now = timezone.now()
    configs = StatisticsConfiguration.objects.filter(is_enabled=True)
    dispatched = skipped = 0

    for config in configs:
        # Skip if not yet due
        if config.next_run_at is not None and config.next_run_at > now:
            skipped += 1
            continue

        # Skip if a run is already in progress
        if config.logs.filter(status='running').exists():
            logger.debug('Skipping config %s: already running', config.id)
            skipped += 1
            continue

        if config.computation_type == 'station_metadata':
            run_station_metadata_task.delay(config.id)
        elif config.computation_type == 'flood_thresholds':
            run_flood_thresholds_task.delay(config.id)
        else:
            logger.warning('Unknown computation_type %r for config %s', config.computation_type, config.id)
            skipped += 1
            continue

        dispatched += 1
        next_run = _compute_stats_next_run(now, config)
        StatisticsConfiguration.objects.filter(id=config.id).update(next_run_at=next_run)
        logger.info('Dispatched statistics config %s (%s), next_run_at=%s', config.id, config.name, next_run)

    logger.info('dispatch_statistics_computations: dispatched=%d, skipped=%d', dispatched, skipped)
    return {'dispatched': dispatched, 'skipped': skipped}


@shared_task
def run_station_metadata_task(config_id):
    """Compute and store StationMetadata for all stations in a StatisticsConfiguration."""
    from apps.analytics.models import StatisticsConfiguration, StatisticsComputationLog
    from src.analytics.station_metadata import compute_station_metadata
    from django.utils import timezone
    import time

    config = StatisticsConfiguration.objects.get(id=config_id)
    station_ids = list(config.get_station_queryset().values_list('id', flat=True))

    log = StatisticsComputationLog.objects.create(
        configuration=config,
        status='running',
        started_at=timezone.now(),
        celery_task_id=run_station_metadata_task.request.id or '',
    )

    start_time = time.monotonic()
    try:
        count = compute_station_metadata(station_ids=station_ids)
        duration = time.monotonic() - start_time
        log.status = 'success'
        log.stations_processed = len(station_ids)
        log.records_computed = count
        log.duration_seconds = round(duration, 2)
        log.completed_at = timezone.now()
        log.save()
        StatisticsConfiguration.objects.filter(id=config_id).update(last_run_at=timezone.now())
        logger.info('run_station_metadata_task: config=%s upserted=%d in %.1fs', config_id, count, duration)
        return {'status': 'success', 'upserted': count}
    except Exception as exc:
        duration = time.monotonic() - start_time
        log.status = 'failed'
        log.error_message = str(exc)
        log.duration_seconds = round(duration, 2)
        log.completed_at = timezone.now()
        log.save()
        logger.error('run_station_metadata_task failed for config %s: %s', config_id, exc)
        raise


@shared_task
def run_flood_thresholds_task(config_id):
    """Fetch NOAA NWPS flood thresholds for all stations in a StatisticsConfiguration."""
    from apps.analytics.models import StatisticsConfiguration, StatisticsComputationLog
    from src.analytics.flood_thresholds import fetch_flood_thresholds_for_stations
    from django.utils import timezone
    import time

    config = StatisticsConfiguration.objects.get(id=config_id)
    station_ids = list(config.get_station_queryset().values_list('id', flat=True))

    log = StatisticsComputationLog.objects.create(
        configuration=config,
        status='running',
        started_at=timezone.now(),
        celery_task_id=run_flood_thresholds_task.request.id or '',
    )

    start_time = time.monotonic()
    try:
        result = fetch_flood_thresholds_for_stations(station_ids)
        duration = time.monotonic() - start_time
        log.status = 'success' if result['errors'] == 0 else 'partial'
        log.stations_processed = len(station_ids)
        log.records_computed = result['updated']
        log.duration_seconds = round(duration, 2)
        log.completed_at = timezone.now()
        if result['errors']:
            log.error_message = f"{result['errors']} API errors; {result['skipped']} skipped (no HADS LID)"
        log.save()
        StatisticsConfiguration.objects.filter(id=config_id).update(last_run_at=timezone.now())
        return {'status': log.status, **result}
    except Exception as exc:
        duration = time.monotonic() - start_time
        log.status = 'failed'
        log.error_message = str(exc)
        log.duration_seconds = round(duration, 2)
        log.completed_at = timezone.now()
        log.save()
        logger.error('run_flood_thresholds_task failed for config %s: %s', config_id, exc)
        raise
```

Also ensure the existing `@shared_task` decorator and `logger` are imported at the top of the file. The existing file already imports these.

- [ ] **Step 5.4: Register dispatcher in `config/celery.py`**

Add to the `beat_schedule` dict in `config/celery.py` after the existing entries:

```python
    'dispatch-statistics-computations': {
        'task': 'src.analytics.tasks.dispatch_statistics_computations',
        'schedule': crontab(minute=0),  # every hour on the hour
    },
```

- [ ] **Step 5.5: Run all analytics task tests**

```bash
python manage.py test tests.test_analytics_tasks -v 2
```

Expected: All tests pass.

- [ ] **Step 5.6: Commit**

```bash
git add src/analytics/tasks.py config/celery.py tests/test_analytics_tasks.py
git commit -m "feat: add statistics computation dispatcher, metadata task, flood threshold task"
```

---

## Task 6: REST API — Bulk Last-Observation Endpoint + Serializer

**Files:**
- Modify: `apps/api/serializers/station.py`
- Modify: `apps/api/views/station.py`
- Test: `tests/test_analytics_api.py`

### Background

Two changes to the existing API:

1. Add `last_observation_date` to `StationSerializer` and `StationListSerializer`. Sourced from `station.metadata.last_observation_date` (a OneToOne relation — `None` if StationMetadata doesn't exist yet for that station).

2. Add a `last_observation` action to `StationViewSet`:
   `GET /api/v1/stations/last-observation/`
   Returns all stations (no pagination) as a lightweight list: `station_number`, `name`, `agency`, `is_active`, `last_observation_date`.

- [ ] **Step 6.1: Write failing API tests**

Create `tests/test_analytics_api.py`:

```python
"""Tests for analytics-related REST API endpoints."""

from datetime import date

from django.test import TestCase
from django.urls import reverse
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from rest_framework import status

from apps.analytics.models import StationMetadata
from apps.streamflow.models import Station


def make_station(number, agency='USGS', is_active=True):
    return Station.objects.create(
        station_number=number, name=f'Station {number}', agency=agency, is_active=is_active,
    )


class LastObservationEndpointTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        User.objects.create_user('tester', password='pass')
        self.client.login(username='tester', password='pass')

        self.s1 = make_station('01010001', 'USGS')
        self.s2 = make_station('01010002', 'EC')
        self.s3 = make_station('01010003', 'USGS', is_active=False)

        StationMetadata.objects.create(
            station=self.s1, last_observation_date=date(2025, 5, 1),
        )
        StationMetadata.objects.create(
            station=self.s2, last_observation_date=date(2024, 11, 15),
        )
        # s3 has no StationMetadata

    def test_endpoint_returns_all_stations(self):
        url = '/api/v1/stations/last-observation/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        numbers = [r['station_number'] for r in response.data]
        self.assertIn('01010001', numbers)
        self.assertIn('01010002', numbers)
        self.assertIn('01010003', numbers)

    def test_response_includes_last_observation_date(self):
        url = '/api/v1/stations/last-observation/'
        response = self.client.get(url)
        by_number = {r['station_number']: r for r in response.data}
        self.assertEqual(by_number['01010001']['last_observation_date'], '2025-05-01')
        self.assertEqual(by_number['01010002']['last_observation_date'], '2024-11-15')
        self.assertIsNone(by_number['01010003']['last_observation_date'])

    def test_response_includes_agency_and_is_active(self):
        url = '/api/v1/stations/last-observation/'
        response = self.client.get(url)
        by_number = {r['station_number']: r for r in response.data}
        self.assertEqual(by_number['01010001']['agency'], 'USGS')
        self.assertFalse(by_number['01010003']['is_active'])

    def test_station_serializer_includes_last_observation_date(self):
        url = f'/api/v1/stations/01010001/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('last_observation_date', response.data)
        self.assertEqual(response.data['last_observation_date'], '2025-05-01')

    def test_station_without_metadata_returns_null(self):
        url = f'/api/v1/stations/01010003/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data['last_observation_date'])
```

- [ ] **Step 6.2: Run tests to confirm they fail**

```bash
python manage.py test tests.test_analytics_api -v 2 2>&1 | head -20
```

Expected: Failures — endpoint doesn't exist yet, serializer missing field.

- [ ] **Step 6.3: Update `apps/api/serializers/station.py`**

Read the file first to find the exact field lists. Add `last_observation_date` as a `SerializerMethodField` to both `StationSerializer` and `StationListSerializer`.

In `StationSerializer`:

```python
last_observation_date = serializers.SerializerMethodField()

def get_last_observation_date(self, obj):
    try:
        return obj.metadata.last_observation_date
    except Exception:
        return None
```

Add `'last_observation_date'` to the `fields` list in `StationSerializer.Meta` and `StationListSerializer.Meta` (after `'is_active'`).

- [ ] **Step 6.4: Add `last_observation` action to `apps/api/views/station.py`**

Read the file first. Add the following import at the top if not already present:

```python
from rest_framework.decorators import action
from rest_framework.response import Response
```

Add this method to the `StationViewSet` class:

```python
@action(detail=False, methods=['get'], url_path='last-observation')
def last_observation(self, request):
    """Return all stations with their last observation date in one response.

    Intended for downstream apps that need to determine active gages
    without querying each station individually.
    """
    stations = (
        Station.objects.select_related('metadata')
        .only('station_number', 'name', 'agency', 'is_active')
        .order_by('station_number')
    )
    data = [
        {
            'station_number': s.station_number,
            'name': s.name,
            'agency': s.agency,
            'is_active': s.is_active,
            'last_observation_date': (
                s.metadata.last_observation_date.isoformat()
                if hasattr(s, 'metadata') and s.metadata and s.metadata.last_observation_date
                else None
            ),
        }
        for s in stations
    ]
    return Response(data)
```

- [ ] **Step 6.5: Run API tests**

```bash
python manage.py test tests.test_analytics_api -v 2
```

Expected: All 5 tests pass.

- [ ] **Step 6.6: Commit**

```bash
git add apps/api/serializers/station.py apps/api/views/station.py tests/test_analytics_api.py
git commit -m "feat: add last_observation_date to station API and bulk /stations/last-observation/ endpoint"
```

---

## Task 7: Analytics Forms

**Files:**
- Create: `apps/analytics/forms.py`
- Test: `tests/test_analytics_views.py` (form validation section)

### Background

`StatisticsConfigurationForm` must validate:
- `schedule_value` is a valid 5-field cron expression when `schedule_type == 'custom'`
- `annual_run_month` is 1–12
- `annual_run_day` is 1–31
- Show/hide annual fields based on schedule_type (handled in template JS; form still validates)

- [ ] **Step 7.1: Write failing form tests**

Create `tests/test_analytics_views.py`:

```python
"""Tests for analytics views and forms."""

from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User

from apps.analytics.models import StatisticsConfiguration
from apps.streamflow.models import Station


class StatisticsConfigurationFormTest(TestCase):
    def test_valid_annual_form(self):
        from apps.analytics.forms import StatisticsConfigurationForm
        form = StatisticsConfigurationForm(data={
            'name': 'USGS Annual',
            'description': '',
            'computation_type': 'station_metadata',
            'agency_filter': 'USGS',
            'schedule_type': 'annual',
            'annual_run_month': 10,
            'annual_run_day': 1,
            'schedule_value': '',
            'is_enabled': True,
        })
        self.assertTrue(form.is_valid(), form.errors)

    def test_valid_monthly_form(self):
        from apps.analytics.forms import StatisticsConfigurationForm
        form = StatisticsConfigurationForm(data={
            'name': 'EC Monthly',
            'computation_type': 'flood_thresholds',
            'agency_filter': 'EC',
            'schedule_type': 'monthly',
            'annual_run_month': 10,
            'annual_run_day': 1,
            'schedule_value': '',
            'is_enabled': True,
        })
        self.assertTrue(form.is_valid(), form.errors)

    def test_custom_schedule_requires_cron_value(self):
        from apps.analytics.forms import StatisticsConfigurationForm
        form = StatisticsConfigurationForm(data={
            'name': 'Custom',
            'computation_type': 'station_metadata',
            'agency_filter': 'ALL',
            'schedule_type': 'custom',
            'annual_run_month': 10,
            'annual_run_day': 1,
            'schedule_value': '',
            'is_enabled': True,
        })
        self.assertFalse(form.is_valid())
        self.assertIn('schedule_value', form.errors)

    def test_invalid_cron_rejected(self):
        from apps.analytics.forms import StatisticsConfigurationForm
        form = StatisticsConfigurationForm(data={
            'name': 'BadCron',
            'computation_type': 'station_metadata',
            'agency_filter': 'ALL',
            'schedule_type': 'custom',
            'annual_run_month': 10,
            'annual_run_day': 1,
            'schedule_value': 'not a cron',
            'is_enabled': True,
        })
        self.assertFalse(form.is_valid())
        self.assertIn('schedule_value', form.errors)

    def test_valid_cron_accepted(self):
        from apps.analytics.forms import StatisticsConfigurationForm
        form = StatisticsConfigurationForm(data={
            'name': 'GoodCron',
            'computation_type': 'station_metadata',
            'agency_filter': 'ALL',
            'schedule_type': 'custom',
            'annual_run_month': 10,
            'annual_run_day': 1,
            'schedule_value': '0 2 1 * *',
            'is_enabled': True,
        })
        self.assertTrue(form.is_valid(), form.errors)

    def test_annual_month_out_of_range(self):
        from apps.analytics.forms import StatisticsConfigurationForm
        form = StatisticsConfigurationForm(data={
            'name': 'BadMonth',
            'computation_type': 'station_metadata',
            'agency_filter': 'ALL',
            'schedule_type': 'annual',
            'annual_run_month': 13,
            'annual_run_day': 1,
            'schedule_value': '',
            'is_enabled': True,
        })
        self.assertFalse(form.is_valid())
        self.assertIn('annual_run_month', form.errors)
```

- [ ] **Step 7.2: Run tests to confirm they fail**

```bash
python manage.py test tests.test_analytics_views.StatisticsConfigurationFormTest -v 2 2>&1 | head -10
```

Expected: `ImportError: cannot import name 'StatisticsConfigurationForm'`

- [ ] **Step 7.3: Create `apps/analytics/forms.py`**

```python
"""Forms for the analytics section."""

from django import forms
from croniter import croniter

from apps.analytics.models import StatisticsConfiguration


class StatisticsConfigurationForm(forms.ModelForm):
    class Meta:
        model = StatisticsConfiguration
        fields = [
            'name', 'description', 'computation_type', 'agency_filter',
            'schedule_type', 'annual_run_month', 'annual_run_day', 'schedule_value',
            'is_enabled',
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
            'schedule_value': forms.TextInput(attrs={'placeholder': '0 0 1 10 *'}),
        }
        help_texts = {
            'schedule_value': 'Required for Custom schedule. 5-field cron (min hr dom mon dow).',
            'annual_run_month': '1–12. Default 10 (October = water year start).',
            'annual_run_day': '1–31. Default 1.',
        }

    def clean_annual_run_month(self):
        value = self.cleaned_data.get('annual_run_month')
        if value is not None and not (1 <= value <= 12):
            raise forms.ValidationError('Month must be between 1 and 12.')
        return value

    def clean_annual_run_day(self):
        value = self.cleaned_data.get('annual_run_day')
        if value is not None and not (1 <= value <= 31):
            raise forms.ValidationError('Day must be between 1 and 31.')
        return value

    def clean(self):
        cleaned_data = super().clean()
        schedule_type = cleaned_data.get('schedule_type')
        schedule_value = cleaned_data.get('schedule_value', '').strip()

        if schedule_type == 'custom':
            if not schedule_value:
                self.add_error('schedule_value', 'A cron expression is required for Custom schedule.')
            else:
                try:
                    croniter(schedule_value)
                except (ValueError, KeyError):
                    self.add_error('schedule_value', f'Invalid cron expression: "{schedule_value}". Use 5 fields: min hr dom mon dow.')

        return cleaned_data
```

- [ ] **Step 7.4: Run form tests**

```bash
python manage.py test tests.test_analytics_views.StatisticsConfigurationFormTest -v 2
```

Expected: All 6 tests pass.

- [ ] **Step 7.5: Commit**

```bash
git add apps/analytics/forms.py tests/test_analytics_views.py
git commit -m "feat: add StatisticsConfigurationForm with cron and range validation"
```

---

## Task 8: Analytics Views, URLs, and config/urls.py

**Files:**
- Replace: `apps/analytics/views.py`
- Replace: `apps/analytics/urls.py`
- Modify: `config/urls.py`
- Test: `tests/test_analytics_views.py` (add view tests)

### Background

Implement these views in `apps/analytics/views.py`:

| View | URL | Method |
|------|-----|--------|
| `analytics_dashboard` | `analytics/` | GET |
| `StatisticsConfigurationListView` | `analytics/configurations/` | GET |
| `StatisticsConfigurationCreateView` | `analytics/configurations/new/` | GET, POST |
| `StatisticsConfigurationDetailView` | `analytics/configurations/<int:pk>/` | GET |
| `StatisticsConfigurationUpdateView` | `analytics/configurations/<int:pk>/edit/` | GET, POST |
| `StatisticsConfigurationDeleteView` | `analytics/configurations/<int:pk>/delete/` | GET, POST |
| `trigger_statistics_config` | `analytics/configurations/<int:pk>/trigger/` | POST |
| `toggle_statistics_config` | `analytics/configurations/<int:pk>/toggle/` | POST |
| `station_metadata_list` | `analytics/station-metadata/` | GET |

All views require `@login_required`.

- [ ] **Step 8.1: Add view tests to `tests/test_analytics_views.py`**

Add after the form tests:

```python
class AnalyticsViewsTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('analyst', password='pass')
        self.client = Client()
        self.client.login(username='analyst', password='pass')
        self.config = StatisticsConfiguration.objects.create(
            name='Test Config',
            computation_type='station_metadata',
            agency_filter='USGS',
            schedule_type='annual',
        )

    def test_dashboard_loads(self):
        response = self.client.get('/analytics/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Analytics')

    def test_config_list_loads(self):
        response = self.client.get('/analytics/configurations/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test Config')

    def test_config_detail_loads(self):
        response = self.client.get(f'/analytics/configurations/{self.config.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test Config')

    def test_config_create_get(self):
        response = self.client.get('/analytics/configurations/new/')
        self.assertEqual(response.status_code, 200)

    def test_config_create_post(self):
        response = self.client.post('/analytics/configurations/new/', {
            'name': 'New Config',
            'computation_type': 'flood_thresholds',
            'agency_filter': 'NOAA_RFC',
            'schedule_type': 'annual',
            'annual_run_month': 10,
            'annual_run_day': 1,
            'schedule_value': '',
            'is_enabled': True,
        })
        self.assertRedirects(response, f'/analytics/configurations/{StatisticsConfiguration.objects.get(name="New Config").id}/')

    def test_toggle_enables_disables(self):
        self.config.is_enabled = True
        self.config.save()
        response = self.client.post(f'/analytics/configurations/{self.config.id}/toggle/')
        self.assertEqual(response.status_code, 302)
        self.config.refresh_from_db()
        self.assertFalse(self.config.is_enabled)

    def test_unauthenticated_redirects(self):
        self.client.logout()
        response = self.client.get('/analytics/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login', response.url)

    def test_station_metadata_list_loads(self):
        station = Station.objects.create(station_number='META999', name='Test', agency='USGS')
        from apps.analytics.models import StationMetadata
        from datetime import date
        StationMetadata.objects.create(station=station, last_observation_date=date(2025, 1, 1))
        response = self.client.get('/analytics/station-metadata/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'META999')
```

- [ ] **Step 8.2: Run view tests to confirm they fail**

```bash
python manage.py test tests.test_analytics_views.AnalyticsViewsTest -v 2 2>&1 | head -20
```

Expected: 404 errors — URLs not registered yet.

- [ ] **Step 8.3: Write `apps/analytics/views.py`**

Replace the placeholder file entirely:

```python
"""Analytics section views: StatisticsConfiguration CRUD, dashboard, station metadata browser."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView
from django.utils import timezone

from apps.analytics.forms import StatisticsConfigurationForm
from apps.analytics.models import (
    FloodThreshold,
    StatisticsComputationLog,
    StatisticsConfiguration,
    StationMetadata,
)


@login_required
def analytics_dashboard(request):
    configs = StatisticsConfiguration.objects.annotate(
        log_count=Count('logs'),
    ).order_by('name')

    recent_logs = StatisticsComputationLog.objects.select_related('configuration').order_by('-started_at')[:20]

    total_metadata = StationMetadata.objects.count()
    total_thresholds = FloodThreshold.objects.count()

    return render(request, 'analytics/dashboard.html', {
        'configs': configs,
        'recent_logs': recent_logs,
        'total_metadata': total_metadata,
        'total_thresholds': total_thresholds,
        'enabled_count': configs.filter(is_enabled=True).count(),
    })


class StatisticsConfigurationListView(LoginRequiredMixin, ListView):
    model = StatisticsConfiguration
    template_name = 'analytics/configuration_list.html'
    context_object_name = 'configs'
    ordering = ['name']

    def get_queryset(self):
        qs = super().get_queryset().annotate(log_count=Count('logs'))
        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(name__icontains=q)
        ct = self.request.GET.get('type', '')
        if ct:
            qs = qs.filter(computation_type=ct)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['computation_types'] = StatisticsConfiguration.COMPUTATION_TYPE_CHOICES
        return ctx


class StatisticsConfigurationCreateView(LoginRequiredMixin, CreateView):
    model = StatisticsConfiguration
    form_class = StatisticsConfigurationForm
    template_name = 'analytics/configuration_form.html'

    def get_success_url(self):
        return reverse_lazy('analytics:configuration_detail', kwargs={'pk': self.object.pk})

    def form_valid(self, form):
        messages.success(self.request, f'Configuration "{form.instance.name}" created.')
        return super().form_valid(form)


class StatisticsConfigurationDetailView(LoginRequiredMixin, DetailView):
    model = StatisticsConfiguration
    template_name = 'analytics/configuration_detail.html'
    context_object_name = 'config'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['logs'] = self.object.logs.order_by('-started_at')[:25]
        ctx['station_count'] = self.object.get_station_queryset().count()
        ctx['explicit_stations'] = self.object.stations.select_related('station').order_by('station__station_number')[:50]
        return ctx


class StatisticsConfigurationUpdateView(LoginRequiredMixin, UpdateView):
    model = StatisticsConfiguration
    form_class = StatisticsConfigurationForm
    template_name = 'analytics/configuration_form.html'

    def get_success_url(self):
        return reverse_lazy('analytics:configuration_detail', kwargs={'pk': self.object.pk})

    def form_valid(self, form):
        messages.success(self.request, f'Configuration "{form.instance.name}" updated.')
        return super().form_valid(form)


class StatisticsConfigurationDeleteView(LoginRequiredMixin, DeleteView):
    model = StatisticsConfiguration
    template_name = 'analytics/configuration_confirm_delete.html'
    success_url = reverse_lazy('analytics:configuration_list')
    context_object_name = 'config'

    def form_valid(self, form):
        messages.success(self.request, f'Configuration "{self.object.name}" deleted.')
        return super().form_valid(form)


@login_required
def trigger_statistics_config(request, pk):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    config = get_object_or_404(StatisticsConfiguration, pk=pk)
    if config.computation_type == 'station_metadata':
        from src.analytics.tasks import run_station_metadata_task
        run_station_metadata_task.delay(config.id)
    elif config.computation_type == 'flood_thresholds':
        from src.analytics.tasks import run_flood_thresholds_task
        run_flood_thresholds_task.delay(config.id)
    messages.success(request, f'Triggered "{config.name}" — check logs for status.')
    return redirect('analytics:configuration_detail', pk=pk)


@login_required
def toggle_statistics_config(request, pk):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    config = get_object_or_404(StatisticsConfiguration, pk=pk)
    config.is_enabled = not config.is_enabled
    config.save(update_fields=['is_enabled'])
    state = 'enabled' if config.is_enabled else 'disabled'
    messages.success(request, f'Configuration "{config.name}" {state}.')
    return redirect('analytics:configuration_detail', pk=pk)


@login_required
def station_metadata_list(request):
    qs = StationMetadata.objects.select_related('station').order_by('station__station_number')

    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(station__station_number__icontains=q) | qs.filter(station__name__icontains=q)

    agency = request.GET.get('agency', '')
    if agency:
        qs = qs.filter(station__agency=agency)

    return render(request, 'analytics/station_metadata_list.html', {
        'metadata_list': qs[:500],
        'total': StationMetadata.objects.count(),
        'query': q,
        'agency': agency,
    })
```

- [ ] **Step 8.4: Write `apps/analytics/urls.py`**

Replace the placeholder file entirely:

```python
"""URL configuration for the analytics section."""

from django.urls import path
from apps.analytics import views

app_name = 'analytics'

urlpatterns = [
    path('', views.analytics_dashboard, name='dashboard'),
    path('configurations/', views.StatisticsConfigurationListView.as_view(), name='configuration_list'),
    path('configurations/new/', views.StatisticsConfigurationCreateView.as_view(), name='configuration_create'),
    path('configurations/<int:pk>/', views.StatisticsConfigurationDetailView.as_view(), name='configuration_detail'),
    path('configurations/<int:pk>/edit/', views.StatisticsConfigurationUpdateView.as_view(), name='configuration_update'),
    path('configurations/<int:pk>/delete/', views.StatisticsConfigurationDeleteView.as_view(), name='configuration_delete'),
    path('configurations/<int:pk>/trigger/', views.trigger_statistics_config, name='trigger'),
    path('configurations/<int:pk>/toggle/', views.toggle_statistics_config, name='toggle'),
    path('station-metadata/', views.station_metadata_list, name='station_metadata_list'),
]
```

- [ ] **Step 8.5: Register analytics URLs in `config/urls.py`**

Add `path("analytics/", include("apps.analytics.urls")),` to the `urlpatterns` list:

```python
urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("apps.api.urls")),
    path("accounts/", include("django.contrib.auth.urls")),
    path("analytics/", include("apps.analytics.urls")),
    path("", include("apps.streamflow.urls")),
]
```

- [ ] **Step 8.6: Run view tests**

```bash
python manage.py test tests.test_analytics_views -v 2
```

Expected: All view and form tests pass.

- [ ] **Step 8.7: Commit**

```bash
git add apps/analytics/views.py apps/analytics/urls.py config/urls.py tests/test_analytics_views.py
git commit -m "feat: add analytics views, URL routing for statistics configuration CRUD"
```

---

## Task 9: Analytics Templates

**Files:**
- Create: `apps/analytics/templates/analytics/dashboard.html`
- Create: `apps/analytics/templates/analytics/configuration_list.html`
- Create: `apps/analytics/templates/analytics/configuration_form.html`
- Create: `apps/analytics/templates/analytics/configuration_detail.html`
- Create: `apps/analytics/templates/analytics/configuration_confirm_delete.html`
- Create: `apps/analytics/templates/analytics/station_metadata_list.html`

### Background

All templates extend `base.html`. Follow the same Bootstrap 5 + Font Awesome patterns used in `apps/streamflow/templates/streamflow/`. Reference `configuration_list.html`, `configuration_detail.html`, and `configuration_form.html` in streamflow for exact card structure, badge styles, log tables, and form layout.

Django's `APP_DIRS=True` will discover these automatically under `apps/analytics/templates/`.

- [ ] **Step 9.1: Create template directory**

```bash
mkdir -p /home/streamflow/streamflow-dataOps/streamflow-dataOps/apps/analytics/templates/analytics
```

- [ ] **Step 9.2: Create `dashboard.html`**

```html
{% extends "base.html" %}
{% load humanize %}

{% block title %}Analytics Dashboard{% endblock %}

{% block content %}
<div class="container-fluid mt-4">
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h2><i class="fas fa-chart-bar"></i> Analytics Dashboard</h2>
        <a href="{% url 'analytics:configuration_create' %}" class="btn btn-primary">
            <i class="fas fa-plus-circle"></i> New Configuration
        </a>
    </div>

    <!-- Key Metrics -->
    <div class="row mb-4">
        <div class="col-lg-3 col-md-6 mb-3">
            <div class="card border-primary">
                <div class="card-body">
                    <h6 class="text-muted mb-2">Configurations</h6>
                    <h2 class="mb-0">{{ configs.count }}</h2>
                    <small class="text-success">{{ enabled_count }} enabled</small>
                </div>
                <div class="card-footer bg-transparent">
                    <a href="{% url 'analytics:configuration_list' %}" class="text-primary text-decoration-none">View all <i class="fas fa-arrow-right"></i></a>
                </div>
            </div>
        </div>
        <div class="col-lg-3 col-md-6 mb-3">
            <div class="card border-info">
                <div class="card-body">
                    <h6 class="text-muted mb-2">Stations with Metadata</h6>
                    <h2 class="mb-0">{{ total_metadata|intcomma }}</h2>
                    <small class="text-muted">last_observation_date cached</small>
                </div>
                <div class="card-footer bg-transparent">
                    <a href="{% url 'analytics:station_metadata_list' %}" class="text-info text-decoration-none">Browse <i class="fas fa-arrow-right"></i></a>
                </div>
            </div>
        </div>
        <div class="col-lg-3 col-md-6 mb-3">
            <div class="card border-warning">
                <div class="card-body">
                    <h6 class="text-muted mb-2">Flood Thresholds</h6>
                    <h2 class="mb-0">{{ total_thresholds|intcomma }}</h2>
                    <small class="text-muted">stations with NWS thresholds</small>
                </div>
            </div>
        </div>
    </div>

    <div class="row">
        <!-- Configuration Status -->
        <div class="col-lg-6 mb-4">
            <div class="card">
                <div class="card-header bg-light"><h6 class="mb-0"><i class="fas fa-cog"></i> Configurations</h6></div>
                <div class="list-group list-group-flush">
                    {% for config in configs %}
                    <a href="{% url 'analytics:configuration_detail' config.pk %}" class="list-group-item list-group-item-action">
                        <div class="d-flex justify-content-between align-items-center">
                            <div>
                                <strong>{{ config.name }}</strong>
                                <small class="text-muted d-block">{{ config.get_computation_type_display }} · {{ config.get_agency_filter_display }} · {{ config.get_schedule_type_display }}</small>
                            </div>
                            <div>
                                {% if config.is_enabled %}
                                    <span class="badge bg-success">Enabled</span>
                                {% else %}
                                    <span class="badge bg-secondary">Disabled</span>
                                {% endif %}
                            </div>
                        </div>
                        {% if config.last_run_at %}
                        <small class="text-muted">Last run: {{ config.last_run_at|naturaltime }}</small>
                        {% endif %}
                        {% if config.next_run_at %}
                        <small class="text-muted ms-2">Next: {{ config.next_run_at|naturaltime }}</small>
                        {% endif %}
                    </a>
                    {% empty %}
                    <div class="list-group-item text-muted">No configurations yet. <a href="{% url 'analytics:configuration_create' %}">Create one.</a></div>
                    {% endfor %}
                </div>
            </div>
        </div>

        <!-- Recent Logs -->
        <div class="col-lg-6 mb-4">
            <div class="card">
                <div class="card-header bg-light"><h6 class="mb-0"><i class="fas fa-list"></i> Recent Computation Logs</h6></div>
                <div class="list-group list-group-flush">
                    {% for log in recent_logs %}
                    <div class="list-group-item">
                        <div class="d-flex justify-content-between">
                            <span><strong>{{ log.configuration.name }}</strong></span>
                            {% if log.status == 'success' %}
                                <span class="badge bg-success">Success</span>
                            {% elif log.status == 'running' %}
                                <span class="badge bg-primary">Running</span>
                            {% elif log.status == 'partial' %}
                                <span class="badge bg-warning text-dark">Partial</span>
                            {% else %}
                                <span class="badge bg-danger">Failed</span>
                            {% endif %}
                        </div>
                        <small class="text-muted">
                            {{ log.started_at|naturaltime }}
                            {% if log.stations_processed %} · {{ log.stations_processed|intcomma }} stations{% endif %}
                        </small>
                    </div>
                    {% empty %}
                    <div class="list-group-item text-muted">No runs yet.</div>
                    {% endfor %}
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}
```

- [ ] **Step 9.3: Create `configuration_list.html`**

```html
{% extends "base.html" %}
{% load humanize %}

{% block title %}Analytics Configurations{% endblock %}

{% block content %}
<div class="container-fluid mt-4">
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h2><i class="fas fa-chart-bar"></i> Analytics Configurations</h2>
        <a href="{% url 'analytics:configuration_create' %}" class="btn btn-primary">
            <i class="fas fa-plus-circle"></i> New Configuration
        </a>
    </div>

    <!-- Filters -->
    <div class="card mb-3">
        <div class="card-body">
            <form method="get" class="row g-2 align-items-end">
                <div class="col-md-6">
                    <input type="text" name="q" value="{{ request.GET.q }}" class="form-control" placeholder="Search by name…">
                </div>
                <div class="col-md-4">
                    <select name="type" class="form-select">
                        <option value="">All types</option>
                        {% for val, label in computation_types %}
                        <option value="{{ val }}" {% if request.GET.type == val %}selected{% endif %}>{{ label }}</option>
                        {% endfor %}
                    </select>
                </div>
                <div class="col-md-2">
                    <button type="submit" class="btn btn-outline-primary w-100">Filter</button>
                </div>
            </form>
        </div>
    </div>

    <div class="card">
        <div class="card-body p-0">
            <table class="table table-hover mb-0">
                <thead class="table-light">
                    <tr>
                        <th>Name</th>
                        <th>Type</th>
                        <th>Agency</th>
                        <th>Schedule</th>
                        <th>Last Run</th>
                        <th>Next Run</th>
                        <th>Status</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    {% for config in configs %}
                    <tr>
                        <td><a href="{% url 'analytics:configuration_detail' config.pk %}">{{ config.name }}</a></td>
                        <td><small>{{ config.get_computation_type_display }}</small></td>
                        <td><span class="badge bg-secondary">{{ config.agency_filter }}</span></td>
                        <td>
                            {{ config.get_schedule_type_display }}
                            {% if config.schedule_type == 'annual' %}
                            <small class="text-muted">({{ config.annual_run_month }}/{{ config.annual_run_day }})</small>
                            {% endif %}
                        </td>
                        <td><small class="text-muted">{{ config.last_run_at|naturaltime|default:"Never" }}</small></td>
                        <td><small class="text-muted">{{ config.next_run_at|naturaltime|default:"—" }}</small></td>
                        <td>
                            {% if config.is_enabled %}
                                <span class="badge bg-success">Enabled</span>
                            {% else %}
                                <span class="badge bg-secondary">Disabled</span>
                            {% endif %}
                        </td>
                        <td>
                            <a href="{% url 'analytics:configuration_detail' config.pk %}" class="btn btn-sm btn-outline-primary"><i class="fas fa-eye"></i></a>
                            <a href="{% url 'analytics:configuration_update' config.pk %}" class="btn btn-sm btn-outline-secondary"><i class="fas fa-edit"></i></a>
                        </td>
                    </tr>
                    {% empty %}
                    <tr><td colspan="8" class="text-center text-muted py-4">No configurations found. <a href="{% url 'analytics:configuration_create' %}">Create one.</a></td></tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</div>
{% endblock %}
```

- [ ] **Step 9.4: Create `configuration_form.html`**

```html
{% extends "base.html" %}
{% load crispy_forms_tags %}

{% block title %}{% if form.instance.pk %}Edit{% else %}New{% endif %} Analytics Configuration{% endblock %}

{% block content %}
<div class="container mt-4" style="max-width: 760px;">
    <h2><i class="fas fa-chart-bar"></i> {% if form.instance.pk %}Edit{% else %}New{% endif %} Analytics Configuration</h2>

    <form method="post" class="mt-4">
        {% csrf_token %}
        <div class="card mb-3">
            <div class="card-header bg-light"><strong>Basic Information</strong></div>
            <div class="card-body">
                {% crispy form.name %}
                {% crispy form.description %}
                {% crispy form.computation_type %}
                {% crispy form.agency_filter %}
            </div>
        </div>

        <div class="card mb-3">
            <div class="card-header bg-light"><strong>Schedule</strong></div>
            <div class="card-body">
                {% crispy form.schedule_type %}
                <div id="annual-fields">
                    <div class="row">
                        <div class="col-md-6">{% crispy form.annual_run_month %}</div>
                        <div class="col-md-6">{% crispy form.annual_run_day %}</div>
                    </div>
                </div>
                <div id="custom-field" style="display:none;">
                    {% crispy form.schedule_value %}
                </div>
            </div>
        </div>

        <div class="card mb-4">
            <div class="card-header bg-light"><strong>Status</strong></div>
            <div class="card-body">
                {% crispy form.is_enabled %}
            </div>
        </div>

        <div class="d-flex gap-2">
            <button type="submit" class="btn btn-primary"><i class="fas fa-save"></i> Save Configuration</button>
            <a href="{% url 'analytics:configuration_list' %}" class="btn btn-outline-secondary">Cancel</a>
        </div>
    </form>
</div>

{% block extra_js %}
<script>
document.addEventListener('DOMContentLoaded', function() {
    const scheduleType = document.querySelector('[name=schedule_type]');
    const annualFields = document.getElementById('annual-fields');
    const customField = document.getElementById('custom-field');

    function updateVisibility() {
        const val = scheduleType.value;
        annualFields.style.display = val === 'annual' ? '' : 'none';
        customField.style.display = val === 'custom' ? '' : 'none';
    }

    scheduleType.addEventListener('change', updateVisibility);
    updateVisibility();
});
</script>
{% endblock %}
{% endblock %}
```

Note: If `crispy_forms_tags` isn't available for individual field rendering, replace `{% crispy form.field_name %}` with `{{ form.field_name.label_tag }} {{ form.field_name }} {{ form.field_name.errors }}` wrapped in `<div class="mb-3">`.

- [ ] **Step 9.5: Create `configuration_detail.html`**

```html
{% extends "base.html" %}
{% load humanize %}

{% block title %}{{ config.name }}{% endblock %}

{% block content %}
<div class="container-fluid mt-4">
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h2><i class="fas fa-chart-bar"></i> {{ config.name }}</h2>
        <div class="d-flex gap-2">
            <form method="post" action="{% url 'analytics:trigger' config.pk %}">
                {% csrf_token %}
                <button type="submit" class="btn btn-success"><i class="fas fa-play"></i> Run Now</button>
            </form>
            <form method="post" action="{% url 'analytics:toggle' config.pk %}">
                {% csrf_token %}
                <button type="submit" class="btn {% if config.is_enabled %}btn-warning{% else %}btn-outline-success{% endif %}">
                    {% if config.is_enabled %}<i class="fas fa-pause"></i> Disable{% else %}<i class="fas fa-play"></i> Enable{% endif %}
                </button>
            </form>
            <a href="{% url 'analytics:configuration_update' config.pk %}" class="btn btn-outline-secondary"><i class="fas fa-edit"></i> Edit</a>
            <a href="{% url 'analytics:configuration_delete' config.pk %}" class="btn btn-outline-danger"><i class="fas fa-trash"></i> Delete</a>
        </div>
    </div>

    <div class="row">
        <div class="col-lg-4 mb-4">
            <div class="card">
                <div class="card-header bg-light"><h6 class="mb-0">Configuration Details</h6></div>
                <div class="card-body">
                    <dl class="row mb-0">
                        <dt class="col-sm-5">Type</dt>
                        <dd class="col-sm-7">{{ config.get_computation_type_display }}</dd>
                        <dt class="col-sm-5">Agency</dt>
                        <dd class="col-sm-7">{{ config.get_agency_filter_display }}</dd>
                        <dt class="col-sm-5">Schedule</dt>
                        <dd class="col-sm-7">
                            {{ config.get_schedule_type_display }}
                            {% if config.schedule_type == 'annual' %}({{ config.annual_run_month }}/{{ config.annual_run_day }}){% endif %}
                            {% if config.schedule_type == 'custom' %}<br><code>{{ config.schedule_value }}</code>{% endif %}
                        </dd>
                        <dt class="col-sm-5">Status</dt>
                        <dd class="col-sm-7">
                            {% if config.is_enabled %}<span class="badge bg-success">Enabled</span>{% else %}<span class="badge bg-secondary">Disabled</span>{% endif %}
                        </dd>
                        <dt class="col-sm-5">Stations</dt>
                        <dd class="col-sm-7">{{ station_count|intcomma }} {% if explicit_stations %}<small class="text-muted">(explicit)</small>{% else %}<small class="text-muted">(agency filter)</small>{% endif %}</dd>
                        <dt class="col-sm-5">Last Run</dt>
                        <dd class="col-sm-7">{{ config.last_run_at|naturaltime|default:"Never" }}</dd>
                        <dt class="col-sm-5">Next Run</dt>
                        <dd class="col-sm-7">{{ config.next_run_at|naturaltime|default:"Not scheduled" }}</dd>
                    </dl>
                </div>
            </div>
        </div>

        <div class="col-lg-8 mb-4">
            <div class="card">
                <div class="card-header bg-light"><h6 class="mb-0"><i class="fas fa-list"></i> Recent Runs</h6></div>
                <div class="list-group list-group-flush">
                    {% for log in logs %}
                    <div class="list-group-item">
                        <div class="d-flex justify-content-between align-items-center">
                            <div>
                                {% if log.status == 'success' %}<span class="badge bg-success">Success</span>
                                {% elif log.status == 'running' %}<span class="badge bg-primary">Running</span>
                                {% elif log.status == 'partial' %}<span class="badge bg-warning text-dark">Partial</span>
                                {% else %}<span class="badge bg-danger">Failed</span>{% endif %}
                                <small class="text-muted ms-2">{{ log.started_at|date:"Y-m-d H:i" }}</small>
                            </div>
                            <small class="text-muted">
                                {% if log.stations_processed %}{{ log.stations_processed|intcomma }} stations · {% endif %}
                                {% if log.duration_seconds %}{{ log.duration_seconds }}s{% endif %}
                            </small>
                        </div>
                        {% if log.error_message %}
                        <small class="text-danger d-block mt-1">{{ log.error_message|truncatechars:120 }}</small>
                        {% endif %}
                    </div>
                    {% empty %}
                    <div class="list-group-item text-muted">No runs yet. Click "Run Now" to trigger.</div>
                    {% endfor %}
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}
```

- [ ] **Step 9.6: Create `configuration_confirm_delete.html`**

```html
{% extends "base.html" %}

{% block title %}Delete {{ config.name }}{% endblock %}

{% block content %}
<div class="container mt-5" style="max-width: 540px;">
    <div class="card border-danger">
        <div class="card-header bg-danger text-white">
            <h5 class="mb-0"><i class="fas fa-exclamation-triangle"></i> Confirm Deletion</h5>
        </div>
        <div class="card-body">
            <p>Delete configuration <strong>{{ config.name }}</strong> and all its computation logs?</p>
            <p class="text-danger"><small>This cannot be undone.</small></p>
            <form method="post">
                {% csrf_token %}
                <div class="d-flex gap-2">
                    <button type="submit" class="btn btn-danger"><i class="fas fa-trash"></i> Delete</button>
                    <a href="{% url 'analytics:configuration_detail' config.pk %}" class="btn btn-outline-secondary">Cancel</a>
                </div>
            </form>
        </div>
    </div>
</div>
{% endblock %}
```

- [ ] **Step 9.7: Create `station_metadata_list.html`**

```html
{% extends "base.html" %}
{% load humanize %}

{% block title %}Station Metadata{% endblock %}

{% block content %}
<div class="container-fluid mt-4">
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h2><i class="fas fa-database"></i> Station Metadata <small class="text-muted fs-6">({{ total|intcomma }} stations)</small></h2>
        <a href="{% url 'analytics:configuration_list' %}" class="btn btn-outline-secondary">
            <i class="fas fa-cog"></i> Manage Schedules
        </a>
    </div>

    <div class="card mb-3">
        <div class="card-body">
            <form method="get" class="row g-2 align-items-end">
                <div class="col-md-5">
                    <input type="text" name="q" value="{{ query }}" class="form-control" placeholder="Station number or name…">
                </div>
                <div class="col-md-4">
                    <select name="agency" class="form-select">
                        <option value="">All agencies</option>
                        <option value="USGS" {% if agency == 'USGS' %}selected{% endif %}>USGS</option>
                        <option value="EC" {% if agency == 'EC' %}selected{% endif %}>Environment Canada</option>
                        <option value="NOAA_RFC" {% if agency == 'NOAA_RFC' %}selected{% endif %}>NOAA RFC</option>
                    </select>
                </div>
                <div class="col-md-3">
                    <button type="submit" class="btn btn-outline-primary w-100">Filter</button>
                </div>
            </form>
        </div>
    </div>

    <div class="card">
        <div class="card-body p-0">
            <div class="table-responsive">
                <table class="table table-sm table-hover mb-0">
                    <thead class="table-light">
                        <tr>
                            <th>Station</th>
                            <th>Agency</th>
                            <th>Last Observation</th>
                            <th>Record Start</th>
                            <th>Years</th>
                            <th>Completeness</th>
                            <th>Mean Flow (cfs)</th>
                            <th>Q50 (cfs)</th>
                            <th>Computed</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for meta in metadata_list %}
                        <tr>
                            <td>
                                <a href="{% url 'streamflow:station_detail' meta.station.station_number %}">
                                    {{ meta.station.station_number }}
                                </a>
                                <small class="text-muted d-block">{{ meta.station.name|truncatechars:35 }}</small>
                            </td>
                            <td><span class="badge bg-secondary">{{ meta.station.agency }}</span></td>
                            <td>
                                {% if meta.last_observation_date %}
                                    <span class="{% if meta.last_observation_date|timesince > '180 days' %}text-danger{% endif %}">
                                        {{ meta.last_observation_date|date:"Y-m-d" }}
                                    </span>
                                {% else %}—{% endif %}
                            </td>
                            <td>{{ meta.record_start_date|date:"Y-m-d"|default:"—" }}</td>
                            <td>{{ meta.years_on_record|default:"—" }}</td>
                            <td>
                                {% if meta.record_completeness_pct %}
                                    <span class="{% if meta.record_completeness_pct < 80 %}text-warning{% endif %}">
                                        {{ meta.record_completeness_pct }}%
                                    </span>
                                {% else %}—{% endif %}
                            </td>
                            <td>{{ meta.mean_annual_flow_cfs|intcomma|default:"—" }}</td>
                            <td>{{ meta.q50_cfs|intcomma|default:"—" }}</td>
                            <td><small class="text-muted">{{ meta.computed_at|naturaltime|default:"—" }}</small></td>
                        </tr>
                        {% empty %}
                        <tr><td colspan="9" class="text-center text-muted py-4">
                            No station metadata yet. <a href="{% url 'analytics:configuration_create' %}">Create a station metadata configuration</a> and run it.
                        </td></tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
</div>
{% endblock %}
```

- [ ] **Step 9.8: Run full test suite to confirm no regressions**

```bash
python manage.py test tests.test_analytics_models tests.test_analytics_tasks tests.test_analytics_api tests.test_analytics_views -v 2
```

Expected: All pass.

- [ ] **Step 9.9: Commit**

```bash
git add apps/analytics/templates/
git commit -m "feat: add analytics templates for dashboard, configuration CRUD, station metadata"
```

---

## Task 10: Navbar Update

**Files:**
- Modify: `templates/base.html`

- [ ] **Step 10.1: Add Analytics dropdown to navbar in `templates/base.html`**

Insert the following nav item after the `<!-- Gridded Data Dropdown -->` block and before `<!-- System Diagnostics -->`:

```html
                    <!-- Analytics Dropdown -->
                    <li class="nav-item dropdown">
                        <a class="nav-link dropdown-toggle {% if 'analytics' in request.resolver_match.app_name %}active{% endif %}"
                           href="#" id="analyticsDropdown" role="button"
                           data-bs-toggle="dropdown" aria-expanded="false">
                            <i class="fas fa-chart-bar"></i> Analytics
                        </a>
                        <ul class="dropdown-menu" aria-labelledby="analyticsDropdown">
                            <li>
                                <a class="dropdown-item" href="{% url 'analytics:dashboard' %}">
                                    <i class="fas fa-tachometer-alt"></i> Dashboard
                                </a>
                            </li>
                            <li>
                                <a class="dropdown-item" href="{% url 'analytics:configuration_list' %}">
                                    <i class="fas fa-cog"></i> Configurations
                                </a>
                            </li>
                            <li>
                                <a class="dropdown-item" href="{% url 'analytics:station_metadata_list' %}">
                                    <i class="fas fa-database"></i> Station Metadata
                                </a>
                            </li>
                        </ul>
                    </li>
```

- [ ] **Step 10.2: Fix file ownership**

```bash
sudo chown -R streamflow:streamflow /home/streamflow/streamflow-dataOps/streamflow-dataOps/apps/analytics/
sudo chown -R streamflow:streamflow /home/streamflow/streamflow-dataOps/streamflow-dataOps/src/analytics/
sudo chown -R streamflow:streamflow /home/streamflow/streamflow-dataOps/streamflow-dataOps/tests/test_analytics_*.py
sudo chown streamflow:streamflow /home/streamflow/streamflow-dataOps/streamflow-dataOps/templates/base.html
sudo chown streamflow:streamflow /home/streamflow/streamflow-dataOps/streamflow-dataOps/config/urls.py
sudo chown streamflow:streamflow /home/streamflow/streamflow-dataOps/streamflow-dataOps/config/celery.py
```

- [ ] **Step 10.3: Run full system check**

```bash
cd /home/streamflow/streamflow-dataOps/streamflow-dataOps && source venv/bin/activate
python manage.py check
python manage.py test tests.test_analytics_models tests.test_analytics_tasks tests.test_analytics_api tests.test_analytics_views -v 1
```

Expected: 0 system check issues, all tests pass.

- [ ] **Step 10.4: Final commit**

```bash
git add templates/base.html
git commit -m "feat: add Analytics nav dropdown linking to dashboard, configurations, station metadata"
```

---

## Self-Review Checklist

**Spec coverage:**
- [x] User-manageable StatisticsConfiguration model with GUI CRUD
- [x] Separate configs per agency (agency_filter field)
- [x] Schedule types: annual (default Oct 1), monthly, weekly, daily, custom cron
- [x] Custom cron field with validation
- [x] Optional explicit station selection via M2M (default = agency filter)
- [x] Station metadata: last_observation_date, years_on_record, record bounds, completeness, flow stats
- [x] Flood thresholds from NOAA NWPS API (action, minor, moderate, major, record)
- [x] REST API: `GET /api/v1/stations/last-observation/` returning all stations + last_observation_date
- [x] `last_observation_date` added to station serializer
- [x] Monthly refresh for station metadata (via annual/monthly schedule config, dispatcher honors next_run_at)
- [x] Separate "Analytics" nav section
- [x] Computation logs with status, duration, records_processed
- [x] Manual trigger via GUI
- [x] TDD throughout
- [x] File ownership preservation

**Type consistency check:**
- `get_station_queryset()` on `StatisticsConfiguration` is called in views and tasks — consistent
- `run_station_metadata_task(config_id)` — consistent between dispatcher and direct import in trigger view
- Template URLs use `analytics:` namespace — consistent with `app_name = 'analytics'` in urls.py
- `StationMetadata.last_observation_date` is a `DateField` — serializer returns `.isoformat()` — consistent with test assertion `'2025-05-01'`
