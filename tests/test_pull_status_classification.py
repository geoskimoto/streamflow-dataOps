"""Tests for proportional pull-run status classification.

A run over 2890 stations that loses a handful to transient upstream errors is
not a failed run. The old all-or-nothing rule marked 27 of 29 USGS runs
"failed" while >99% of stations succeeded, which buried real failures.
"""

from unittest import mock

from django.test import TestCase

from apps.streamflow.models import DataPullLog
from src.acquisition import tasks
from src.acquisition.tasks import PARTIAL_FAILURE_THRESHOLD, classify_pull_status
from tests.factories import make_pull_config


def test_a_clean_run_is_success():
    assert classify_pull_status(successful=2890, failed=0) == "success"


def test_a_run_losing_a_few_stations_is_partial_not_failed():
    assert classify_pull_status(successful=2870, failed=20) == "partial"


def test_a_run_losing_most_stations_is_failed():
    assert classify_pull_status(successful=100, failed=2790) == "failed"


def test_a_run_losing_every_station_is_failed():
    assert classify_pull_status(successful=0, failed=2890) == "failed"


def test_failures_exactly_at_the_threshold_are_still_partial():
    total = 1000
    failed = int(total * PARTIAL_FAILURE_THRESHOLD)

    assert classify_pull_status(successful=total - failed, failed=failed) == "partial"


def test_failures_just_past_the_threshold_are_failed():
    total = 1000
    failed = int(total * PARTIAL_FAILURE_THRESHOLD) + 1

    assert classify_pull_status(successful=total - failed, failed=failed) == "failed"


def test_a_run_with_no_stations_is_success():
    assert classify_pull_status(successful=0, failed=0) == "success"


def _failing_stations(*station_numbers):
    """Stub for _process_single_station that fails the named stations."""
    failing = set(station_numbers)

    def stub(config_station, config_id, config):
        if config_station.station_number in failing:
            return {
                "records": 0,
                "success": False,
                "error": f"Error processing station {config_station.station_number}: boom",
            }
        return {"records": 1, "success": True, "error": None}

    return stub


class PullRunRecordsProportionalStatusTest(TestCase):
    def test_partial_is_a_valid_status_choice_on_the_log_model(self):
        choices = dict(DataPullLog._meta.get_field("status").choices)

        self.assertIn("partial", choices)

    def test_a_run_losing_one_station_of_forty_is_logged_as_partial(self):
        config = make_pull_config("USGS", station_count=40)

        with mock.patch.object(
            tasks, "_process_single_station", _failing_stations("12000000")
        ):
            with mock.patch.object(
                tasks, "get_pull_pacing", return_value=tasks.PullPacing(8, 0)
            ):
                tasks.execute_pull_configuration(config.id)

        log = DataPullLog.objects.get(configuration=config)
        self.assertEqual(log.status, "partial")
        self.assertIn("12000000", log.error_message)

    def test_a_run_losing_every_station_is_still_logged_as_failed(self):
        config = make_pull_config("USGS", station_count=4)
        all_stations = [f"1200{i:04d}" for i in range(4)]

        with mock.patch.object(
            tasks, "_process_single_station", _failing_stations(*all_stations)
        ):
            with mock.patch.object(
                tasks, "get_pull_pacing", return_value=tasks.PullPacing(8, 0)
            ):
                tasks.execute_pull_configuration(config.id)

        log = DataPullLog.objects.get(configuration=config)
        self.assertEqual(log.status, "failed")

    def test_a_clean_run_is_still_logged_as_success(self):
        config = make_pull_config("USGS", station_count=4)

        with mock.patch.object(
            tasks, "_process_single_station", _failing_stations()
        ):
            with mock.patch.object(
                tasks, "get_pull_pacing", return_value=tasks.PullPacing(8, 0)
            ):
                tasks.execute_pull_configuration(config.id)

        log = DataPullLog.objects.get(configuration=config)
        self.assertEqual(log.status, "success")
