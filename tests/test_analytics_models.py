"""Tests for analytics models: StationMetadata, FloodThreshold, StatisticsConfiguration."""

from datetime import timedelta

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
        t2 = t1 + timedelta(seconds=1)
        log1 = StatisticsComputationLog.objects.create(
            configuration=self.config, status='success', started_at=t1,
        )
        log2 = StatisticsComputationLog.objects.create(
            configuration=self.config, status='failed', started_at=t2,
        )
        logs = list(StatisticsComputationLog.objects.all())
        self.assertEqual(logs[0], log2)
