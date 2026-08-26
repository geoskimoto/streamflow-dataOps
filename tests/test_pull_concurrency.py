"""Tests that execute_pull_configuration honors per-source pacing.

Guards the fix for USGS NWIS throttling: the dispatch loop must cap concurrency
and space out submissions according to get_pull_pacing(), not fan out at the
default worker count for every source.
"""

import threading
import time
from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.streamflow.models import PullConfiguration, PullConfigurationStation
from src.acquisition import tasks


class ConcurrencyRecorder:
    """Records the peak number of simultaneous in-flight station calls."""

    def __init__(self):
        self._lock = threading.Lock()
        self.in_flight = 0
        self.peak = 0
        self.call_times = []

    def __call__(self, config_station, config_id, config):
        with self._lock:
            self.in_flight += 1
            self.peak = max(self.peak, self.in_flight)
            self.call_times.append(time.monotonic())
        try:
            time.sleep(0.05)
            return {"records": 1, "success": True, "error": None}
        finally:
            with self._lock:
                self.in_flight -= 1


def _make_config(data_source, station_count):
    config = PullConfiguration.objects.create(
        name=f"{data_source} pacing test",
        data_source=data_source,
        data_type="daily_mean",
        is_enabled=True,
        pull_start_date=timezone.now() - timedelta(days=2),
    )
    for i in range(station_count):
        PullConfigurationStation.objects.create(
            configuration=config, station_number=f"1200{i:04d}"
        )
    return config


class PullPacingIsEnforcedTest(TestCase):
    def test_usgs_pull_never_exceeds_its_paced_worker_count(self):
        config = _make_config("USGS", station_count=12)
        recorder = ConcurrencyRecorder()
        expected_workers = tasks.get_pull_pacing("USGS").workers

        with mock.patch.object(tasks, "_process_single_station", recorder):
            with mock.patch.object(tasks, "get_pull_pacing") as paced:
                # Keep the real worker cap, drop the delay so the test is quick.
                paced.return_value = tasks.PullPacing(
                    workers=expected_workers, delay_seconds=0
                )
                tasks.execute_pull_configuration(config.id)

        self.assertEqual(recorder.peak, expected_workers)

    def test_default_source_still_fans_out_at_the_full_worker_count(self):
        config = _make_config("EC", station_count=12)
        recorder = ConcurrencyRecorder()

        with mock.patch.object(tasks, "_process_single_station", recorder):
            tasks.execute_pull_configuration(config.id)

        self.assertEqual(recorder.peak, tasks.STATION_WORKERS)

    def test_pull_spaces_submissions_by_the_configured_delay(self):
        config = _make_config("USGS", station_count=4)
        recorder = ConcurrencyRecorder()

        with mock.patch.object(tasks, "_process_single_station", recorder):
            with mock.patch.object(tasks, "get_pull_pacing") as paced:
                paced.return_value = tasks.PullPacing(workers=3, delay_seconds=0.1)
                tasks.execute_pull_configuration(config.id)

        gaps = [
            b - a for a, b in zip(recorder.call_times, recorder.call_times[1:])
        ]
        self.assertTrue(
            all(gap >= 0.09 for gap in gaps),
            f"submissions were not spaced by the delay: {gaps}",
        )
