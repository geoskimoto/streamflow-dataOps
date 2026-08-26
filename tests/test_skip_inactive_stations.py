"""Tests for the opt-in skip_inactive_stations flag on PullConfiguration.

The USGS Daily Mean Pull requests all 2890 configured stations every run, but
only 768 are still reporting -- the rest are discontinued gauges already
flagged is_active=False. Honoring that flag removes ~2100 pointless requests
per run, which is what was tripping USGS throttling in the first place.

The flag is opt-in because is_active is not maintained for every agency: all
366 NOAA_RFC stations are flagged inactive while actively producing forecasts,
so a blanket filter would silently empty the NWRFC forecast pull.
"""

from unittest import mock

from django.test import TestCase

from apps.streamflow.models import PullConfiguration, Station
from src.acquisition import tasks
from tests.factories import make_pull_config


class StationRecorder:
    """Records which station numbers actually got processed."""

    def __init__(self):
        self.seen = []

    def __call__(self, config_station, config_id, config):
        self.seen.append(config_station.station_number)
        return {"records": 1, "success": True, "error": None}


def _station(number, is_active):
    return Station.objects.create(
        station_number=number,
        name=f"Station {number}",
        agency="USGS",
        latitude=45.0,
        longitude=-122.0,
        is_active=is_active,
    )


class SkipInactiveStationsTest(TestCase):
    def setUp(self):
        self.recorder = StationRecorder()

    def _run(self, config):
        with mock.patch.object(tasks, "_process_single_station", self.recorder):
            with mock.patch.object(
                tasks, "get_pull_pacing", return_value=tasks.PullPacing(8, 0)
            ):
                tasks.execute_pull_configuration(config.id)

    def test_the_flag_defaults_to_off(self):
        config = make_pull_config("USGS", station_count=1)

        self.assertFalse(config.skip_inactive_stations)

    def test_inactive_stations_are_still_pulled_when_the_flag_is_off(self):
        """Existing configs must not change behavior."""
        config = make_pull_config("USGS", station_count=3)
        _station("12000000", is_active=True)
        _station("12000001", is_active=False)
        _station("12000002", is_active=False)

        self._run(config)

        self.assertEqual(len(self.recorder.seen), 3)

    def test_inactive_stations_are_skipped_when_the_flag_is_on(self):
        config = make_pull_config("USGS", station_count=3)
        config.skip_inactive_stations = True
        config.save()
        _station("12000000", is_active=True)
        _station("12000001", is_active=False)
        _station("12000002", is_active=False)

        self._run(config)

        self.assertEqual(self.recorder.seen, ["12000000"])

    def test_stations_with_no_station_record_are_skipped_when_the_flag_is_on(self):
        config = make_pull_config("USGS", station_count=2)
        _station("12000000", is_active=True)
        # 12000001 intentionally has no Station row
        config.skip_inactive_stations = True
        config.save()

        self._run(config)

        self.assertEqual(self.recorder.seen, ["12000000"])

    def test_skipping_every_station_is_not_reported_as_success(self):
        """An empty run means the config is misconfigured, not healthy."""
        config = make_pull_config("USGS", station_count=2)
        _station("12000000", is_active=False)
        _station("12000001", is_active=False)
        config.skip_inactive_stations = True
        config.save()

        self._run(config)

        log = config.logs.get()
        self.assertEqual(log.status, "failed")
        self.assertIn("no active stations", log.error_message.lower())
