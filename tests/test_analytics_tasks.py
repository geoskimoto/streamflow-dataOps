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
