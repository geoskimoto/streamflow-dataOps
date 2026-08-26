"""Tests that partial runs are counted as healthy across the log views.

Partial means the run delivered nearly all its stations, so it belongs in the
success-rate numerator — but it stays visible as its own count so a config
that is quietly degrading is still noticeable.
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


class PartialCountsAsHealthyTest(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(
            username="viewer", password="pw-for-test-only"
        )
        self.client.force_login(user)
        self.config = make_pull_config("USGS", station_count=2, name="Paced pull")

    def test_healthy_statuses_are_defined_on_the_model(self):
        self.assertEqual(
            set(DataPullLog.HEALTHY_STATUSES), {"success", "partial"}
        )

    def test_configuration_detail_counts_partial_toward_success_rate(self):
        _log(self.config, "success")
        _log(self.config, "partial")
        _log(self.config, "partial")
        _log(self.config, "failed")

        response = self.client.get(
            reverse("streamflow:configuration_detail", args=[self.config.id])
        )

        self.assertEqual(response.context["stats"]["success_rate"], 75)

    def test_configuration_detail_reports_partial_runs_separately(self):
        _log(self.config, "success")
        _log(self.config, "partial")
        _log(self.config, "partial")

        response = self.client.get(
            reverse("streamflow:configuration_detail", args=[self.config.id])
        )

        self.assertEqual(response.context["stats"]["partial_runs"], 2)

    def test_log_list_exposes_a_partial_count(self):
        _log(self.config, "success")
        _log(self.config, "partial")
        _log(self.config, "partial")

        response = self.client.get(reverse("streamflow:log_list"))

        self.assertEqual(response.context["partial_count"], 2)

    def test_log_list_renders_a_partial_badge_not_a_failed_one(self):
        _log(self.config, "partial")

        response = self.client.get(reverse("streamflow:log_list"))
        html = response.content.decode()

        self.assertIn("bg-warning text-dark", html)
        self.assertIn("Partial", html)
        self.assertNotIn('<span class="badge bg-danger">', html)

    def test_dashboard_renders_a_partial_badge_not_a_failed_one(self):
        _log(self.config, "partial")

        response = self.client.get(reverse("streamflow:dashboard"))
        html = response.content.decode()

        self.assertIn("Partial", html)

    def test_log_detail_renders_a_partial_badge_not_a_failed_one(self):
        log = _log(self.config, "partial")

        response = self.client.get(reverse("streamflow:log_detail", args=[log.pk]))
        html = response.content.decode()

        self.assertIn("Partial", html)
        self.assertNotIn("Execution Failed", html)

    def test_log_list_can_filter_to_partial_runs_only(self):
        _log(self.config, "success")
        _log(self.config, "partial")

        response = self.client.get(reverse("streamflow:log_list"), {"status": "partial"})

        statuses = {log.status for log in response.context["logs"]}
        self.assertEqual(statuses, {"partial"})
