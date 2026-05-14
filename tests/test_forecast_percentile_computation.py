"""Tests for ForecastPercentile model and compute_forecast_percentiles()."""

from datetime import date, datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch
from django.test import TestCase
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.streamflow.models import Station, ForecastPercentile, DischargeObservation, ForecastRun
from apps.analytics.models import ScheduledComputation, ComputationLog
from src.analytics.percentiles import compute_forecast_percentiles
from src.analytics.tasks import compute_forecast_percentile_bands


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
                observed_at=datetime(2020, 1, 1, tzinfo=dt_timezone.utc) + timedelta(days=i),
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
        ForecastRun.objects.filter(station=self.station).update(
            data=[
                {'date': (today + timedelta(days=1)).isoformat() + 'T00:00:00Z', 'value': 50.0},
                {'date': (today + timedelta(days=3)).isoformat() + 'T00:00:00Z', 'value': 50.0},
                {'date': (today + timedelta(days=9)).isoformat() + 'T00:00:00Z', 'value': 50.0},
            ]
        )
        results = compute_forecast_percentiles(source='NWRFC', max_days=3)
        dates = {r['target_date'] for r in results}
        self.assertIn(today + timedelta(days=1), dates)
        self.assertIn(today + timedelta(days=3), dates)   # boundary — must be included
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
                observed_at=datetime(2020, 1, 1, tzinfo=dt_timezone.utc) + timedelta(days=i),
                discharge=float(i + 1),
                unit='cfs',
                type='daily_mean',
                quality_code='A',
            )
            for i in range(100)
        ])
        results = compute_forecast_percentiles(source='NWRFC', max_days=8)
        station_ids = {r['station_id'] for r in results}
        self.assertNotIn(station_no_run.id, station_ids)

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
                observed_at=datetime(2020, 1, 1, tzinfo=dt_timezone.utc) + timedelta(days=i),
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

    def test_invalid_source_raises_value_error(self):
        with self.assertRaises(ValueError):
            compute_forecast_percentiles(source='BOGUS')


FORECAST_TASK_PATH = 'src.analytics.tasks.compute_forecast_percentile_bands'


class ComputeForecastPercentileBandsTaskTest(TestCase):

    def setUp(self):
        self.computation, _ = ScheduledComputation.objects.get_or_create(
            task_path=FORECAST_TASK_PATH,
            defaults={
                'name': 'NWRFC Forecast Percentile Bands',
                'description': 'Computes forecast percentile bands.',
                'schedule': 'every_6h',
                'is_enabled': True,
            },
        )
        # Ensure enabled state for tests that depend on it
        self.computation.is_enabled = True
        self.computation.save(update_fields=['is_enabled'])

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
