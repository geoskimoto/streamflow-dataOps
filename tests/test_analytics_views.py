"""Tests for analytics views and forms."""

from django.test import TestCase, Client
from django.contrib.auth.models import User

from apps.analytics.models import StatisticsConfiguration
from apps.analytics.forms import StatisticsConfigurationForm


class StatisticsConfigurationFormTest(TestCase):
    def test_valid_annual_form(self):
        form = StatisticsConfigurationForm(data={
            'name': 'USGS Annual',
            'description': '',
            'computation_type': 'station_metadata',
            'agency_filter': 'USGS',
            'schedule_type': 'annual',
            'annual_run_month': 10,
            'annual_run_day': 1,
            'schedule_value': '',
            'is_enabled': True,
        })
        self.assertTrue(form.is_valid(), form.errors)

    def test_valid_monthly_form(self):
        form = StatisticsConfigurationForm(data={
            'name': 'EC Monthly',
            'computation_type': 'flood_thresholds',
            'agency_filter': 'EC',
            'schedule_type': 'monthly',
            'annual_run_month': 10,
            'annual_run_day': 1,
            'schedule_value': '',
            'is_enabled': True,
        })
        self.assertTrue(form.is_valid(), form.errors)

    def test_custom_schedule_requires_cron_value(self):
        form = StatisticsConfigurationForm(data={
            'name': 'Custom',
            'computation_type': 'station_metadata',
            'agency_filter': 'ALL',
            'schedule_type': 'custom',
            'annual_run_month': 10,
            'annual_run_day': 1,
            'schedule_value': '',
            'is_enabled': True,
        })
        self.assertFalse(form.is_valid())
        self.assertIn('schedule_value', form.errors)

    def test_invalid_cron_rejected(self):
        form = StatisticsConfigurationForm(data={
            'name': 'BadCron',
            'computation_type': 'station_metadata',
            'agency_filter': 'ALL',
            'schedule_type': 'custom',
            'annual_run_month': 10,
            'annual_run_day': 1,
            'schedule_value': 'not a cron',
            'is_enabled': True,
        })
        self.assertFalse(form.is_valid())
        self.assertIn('schedule_value', form.errors)

    def test_valid_cron_accepted(self):
        form = StatisticsConfigurationForm(data={
            'name': 'GoodCron',
            'computation_type': 'station_metadata',
            'agency_filter': 'ALL',
            'schedule_type': 'custom',
            'annual_run_month': 10,
            'annual_run_day': 1,
            'schedule_value': '0 2 1 * *',
            'is_enabled': True,
        })
        self.assertTrue(form.is_valid(), form.errors)

    def test_annual_month_out_of_range(self):
        form = StatisticsConfigurationForm(data={
            'name': 'BadMonth',
            'computation_type': 'station_metadata',
            'agency_filter': 'ALL',
            'schedule_type': 'annual',
            'annual_run_month': 13,
            'annual_run_day': 1,
            'schedule_value': '',
            'is_enabled': True,
        })
        self.assertFalse(form.is_valid())
        self.assertIn('annual_run_month', form.errors)

    def test_annual_day_out_of_range(self):
        form = StatisticsConfigurationForm(data={
            'name': 'BadDay',
            'computation_type': 'station_metadata',
            'agency_filter': 'ALL',
            'schedule_type': 'annual',
            'annual_run_month': 10,
            'annual_run_day': 32,
            'schedule_value': '',
            'is_enabled': True,
        })
        self.assertFalse(form.is_valid())
        self.assertIn('annual_run_day', form.errors)

    def test_whitespace_only_cron_rejected(self):
        form = StatisticsConfigurationForm(data={
            'name': 'WhitespaceCron',
            'computation_type': 'station_metadata',
            'agency_filter': 'ALL',
            'schedule_type': 'custom',
            'annual_run_month': 10,
            'annual_run_day': 1,
            'schedule_value': '   ',
            'is_enabled': True,
        })
        self.assertFalse(form.is_valid())
        self.assertIn('schedule_value', form.errors)
