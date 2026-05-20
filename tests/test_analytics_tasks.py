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


class FloodThresholdFetcherTest(TestCase):
    def setUp(self):
        self.noaa_station = make_station('PNCO3', 'NOAA_RFC')
        self.usgs_station = make_station('14211010', 'USGS')

    @patch('src.analytics.flood_thresholds.requests.get')
    def test_fetch_noaa_rfc_station(self, mock_get):
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
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
        mock_get.return_value = mock_response

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
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception('timeout')
        mock_get.return_value = mock_response

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
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            'flood': {'stageflow': {'action': {'stage': 10.0, 'flow': None}}}
        }
        mock_get.return_value = mock_response

        from src.analytics.flood_thresholds import fetch_flood_thresholds_for_stations
        fetch_flood_thresholds_for_stations([self.noaa_station.id])
        fetch_flood_thresholds_for_stations([self.noaa_station.id])

        from apps.analytics.models import FloodThreshold
        self.assertEqual(FloodThreshold.objects.filter(station=self.noaa_station).count(), 1)
