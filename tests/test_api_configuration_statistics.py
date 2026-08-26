"""Tests for the configuration statistics and execution-history endpoints.

Both were returning 500s: statistics averaged raw timestamps (Postgres has no
avg(timestamptz)) and execution_history read a DataPullLog.stations_processed
field that does not exist. Statistics also reported a COUNT of the
records_processed column under a "total_records_processed" label, which is off
by roughly three orders of magnitude on a real config.
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.streamflow.models import DataPullLog
from tests.factories import make_pull_config


def _log(config, status, records=700, minutes=4, hours_ago=1):
    start = timezone.now() - timedelta(hours=hours_ago)
    return DataPullLog.objects.create(
        configuration=config,
        status=status,
        start_time=start,
        end_time=start + timedelta(minutes=minutes),
        records_processed=records,
    )


class ConfigurationStatisticsTest(APITestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(
            username="apiuser", password="pw-for-test-only"
        )
        self.client.force_authenticate(user=user)
        self.config = make_pull_config("USGS", station_count=2, name="Paced pull")

    def _get(self):
        return self.client.get(
            reverse("api:configuration-statistics", args=[self.config.id])
        )

    def test_the_endpoint_returns_a_response_instead_of_erroring(self):
        _log(self.config, "success")

        self.assertEqual(self._get().status_code, 200)

    def test_total_records_processed_sums_records_rather_than_counting_runs(self):
        _log(self.config, "success", records=700)
        _log(self.config, "success", records=800)
        _log(self.config, "partial", records=500)

        data = self._get().data

        self.assertEqual(data["data_stats"]["total_records_processed"], 2000)

    def test_average_duration_is_reported_in_seconds(self):
        _log(self.config, "success", minutes=2)
        _log(self.config, "success", minutes=6)

        data = self._get().data

        self.assertEqual(data["execution_stats"]["avg_duration_seconds"], 240.0)

    def test_average_duration_is_null_when_no_run_has_finished(self):
        DataPullLog.objects.create(
            configuration=self.config,
            status="running",
            start_time=timezone.now(),
            end_time=None,
        )

        data = self._get().data

        self.assertIsNone(data["execution_stats"]["avg_duration_seconds"])

    def test_partial_runs_are_reported_separately(self):
        _log(self.config, "success")
        _log(self.config, "partial")
        _log(self.config, "partial")

        self.assertEqual(self._get().data["execution_stats"]["partial"], 2)

    def test_partial_runs_count_toward_the_success_rate(self):
        _log(self.config, "success")
        _log(self.config, "partial")
        _log(self.config, "partial")
        _log(self.config, "failed")

        self.assertEqual(self._get().data["execution_stats"]["success_rate"], 75.0)

    def test_a_configuration_with_no_runs_does_not_error(self):
        data = self._get().data

        self.assertEqual(data["execution_stats"]["total_executions"], 0)
        self.assertEqual(data["execution_stats"]["success_rate"], 0)
        self.assertIsNone(data["latest_execution"])


class ConfigurationExecutionHistoryTest(APITestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(
            username="apiuser2", password="pw-for-test-only"
        )
        self.client.force_authenticate(user=user)
        self.config = make_pull_config("USGS", station_count=2, name="Paced pull")

    def _get(self, **params):
        return self.client.get(
            reverse("api:configuration-execution-history", args=[self.config.id]),
            params,
        )

    def test_the_endpoint_returns_a_response_instead_of_erroring(self):
        _log(self.config, "success")

        self.assertEqual(self._get().status_code, 200)

    def test_each_entry_reports_its_duration_in_seconds(self):
        _log(self.config, "success", minutes=4)

        entry = self._get().data[0]

        self.assertEqual(entry["duration_seconds"], 240.0)

    def test_a_run_still_in_progress_has_no_duration(self):
        DataPullLog.objects.create(
            configuration=self.config,
            status="running",
            start_time=timezone.now(),
            end_time=None,
        )

        self.assertIsNone(self._get().data[0]["duration_seconds"])

    def test_history_can_be_filtered_to_partial_runs(self):
        _log(self.config, "success")
        _log(self.config, "partial")

        data = self._get(status="partial").data

        self.assertEqual([e["status"] for e in data], ["partial"])
