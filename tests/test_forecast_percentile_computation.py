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
