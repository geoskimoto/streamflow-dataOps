"""The skip_inactive_stations flag must be settable from the GUI.

Pull behavior that is only changeable from a shell is invisible to whoever
is looking at the configuration page wondering why 2100 stations vanished.
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.streamflow.forms import PullConfigurationForm


def _valid_data(**overrides):
    data = {
        "name": "USGS pull",
        "description": "",
        "data_source": "USGS",
        "data_type": "daily_mean",
        "forecast_type": "short",
        "data_strategy": "append",
        "pull_start_date": (timezone.now() - timedelta(days=2)).strftime(
            "%Y-%m-%dT%H:%M"
        ),
        "is_enabled": True,
        "schedule_type": "custom",
        "schedule_value": "0 */6 * * *",
    }
    data.update(overrides)
    return data


class SkipInactiveStationsFormTest(TestCase):
    def test_the_flag_is_exposed_as_a_form_field(self):
        self.assertIn("skip_inactive_stations", PullConfigurationForm().fields)

    def test_the_flag_can_be_turned_on_through_the_form(self):
        form = PullConfigurationForm(_valid_data(skip_inactive_stations=True))

        self.assertTrue(form.is_valid(), form.errors)
        self.assertTrue(form.save().skip_inactive_stations)

    def test_the_flag_stays_off_when_not_submitted(self):
        form = PullConfigurationForm(_valid_data())

        self.assertTrue(form.is_valid(), form.errors)
        self.assertFalse(form.save().skip_inactive_stations)


class SkipInactiveStationsRendersInGuiTest(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(
            username="editor", password="pw-for-test-only"
        )
        self.client.force_login(user)

    def test_the_configuration_form_page_renders_the_checkbox(self):
        response = self.client.get(reverse("streamflow:configuration_create"))
        html = response.content.decode()

        self.assertIn('name="skip_inactive_stations"', html)
        self.assertIn("Skip Inactive Stations", html)
