"""Tests that the dashboard treats partial runs as healthy-but-noteworthy.

A config losing a few stations per run to transient upstream errors must not
be listed under "Failed Configurations" — that alert is for configs that are
actually broken.
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.streamflow.models import DataPullLog
from tests.factories import make_pull_config


def _log(config, status, hours_ago=1):
    start = timezone.now() - timedelta(hours=hours_ago)
    return DataPullLog.objects.create(
        configuration=config,
        status=status,
        start_time=start,
        end_time=start + timedelta(minutes=4),
        records_processed=700,
    )


class DashboardPartialStatusTest(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(
            username="dash", password="pw-for-test-only"
        )
        self.client.force_login(user)

    def test_a_config_with_only_partial_runs_is_not_flagged_as_failed(self):
        config = make_pull_config("USGS", station_count=2, name="Mostly healthy")
        for _ in range(4):
            _log(config, "partial")

        response = self.client.get(reverse("streamflow:dashboard"))

        flagged = [c.name for c in response.context["failed_configs"]]
        self.assertNotIn("Mostly healthy", flagged)

    def test_a_config_with_real_failures_is_still_flagged(self):
        config = make_pull_config("USGS", station_count=2, name="Actually broken")
        for _ in range(4):
            _log(config, "failed")

        response = self.client.get(reverse("streamflow:dashboard"))

        flagged = [c.name for c in response.context["failed_configs"]]
        self.assertIn("Actually broken", flagged)

    def test_partial_runs_count_toward_the_success_rate(self):
        """A run that delivered >95% of its stations did its job."""
        config = make_pull_config("USGS", station_count=2, name="Paced")
        _log(config, "success")
        _log(config, "partial")
        _log(config, "partial")
        _log(config, "partial")

        response = self.client.get(reverse("streamflow:dashboard"))

        self.assertEqual(response.context["success_rate"], 100)

    def test_dashboard_reports_partial_runs_separately(self):
        config = make_pull_config("USGS", station_count=2, name="Paced")
        _log(config, "success")
        _log(config, "partial")
        _log(config, "partial")

        response = self.client.get(reverse("streamflow:dashboard"))

        self.assertEqual(response.context["recent_partial"], 2)
