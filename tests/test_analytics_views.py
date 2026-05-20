"""Tests for analytics views and forms."""

from django.test import TestCase, Client
from django.contrib.auth.models import User

from apps.analytics.models import StatisticsConfiguration
from apps.analytics.forms import StatisticsConfigurationForm
from apps.streamflow.models import Station


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


class AnalyticsViewsTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('analyst', password='pass')
        self.client = Client()
        self.client.login(username='analyst', password='pass')
        self.config = StatisticsConfiguration.objects.create(
            name='Test Config',
            computation_type='station_metadata',
            agency_filter='USGS',
            schedule_type='annual',
        )

    def test_dashboard_loads(self):
        response = self.client.get('/analytics/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Analytics')

    def test_config_list_loads(self):
        response = self.client.get('/analytics/configurations/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test Config')

    def test_config_detail_loads(self):
        response = self.client.get(f'/analytics/configurations/{self.config.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test Config')

    def test_config_create_get(self):
        response = self.client.get('/analytics/configurations/new/')
        self.assertEqual(response.status_code, 200)

    def test_config_create_post(self):
        response = self.client.post('/analytics/configurations/new/', {
            'name': 'New Config',
            'computation_type': 'flood_thresholds',
            'agency_filter': 'NOAA_RFC',
            'schedule_type': 'annual',
            'annual_run_month': 10,
            'annual_run_day': 1,
            'schedule_value': '',
            'is_enabled': True,
        })
        self.assertRedirects(response, f'/analytics/configurations/{StatisticsConfiguration.objects.get(name="New Config").id}/')

    def test_toggle_enables_disables(self):
        self.config.is_enabled = True
        self.config.save()
        response = self.client.post(f'/analytics/configurations/{self.config.id}/toggle/')
        self.assertEqual(response.status_code, 302)
        self.config.refresh_from_db()
        self.assertFalse(self.config.is_enabled)

    def test_unauthenticated_redirects(self):
        self.client.logout()
        response = self.client.get('/analytics/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login', response.url)

    def test_station_metadata_list_loads(self):
        from apps.analytics.models import StationMetadata
        from datetime import date
        station = Station.objects.create(station_number='META999', name='Test', agency='USGS')
        StationMetadata.objects.create(station=station, last_observation_date=date(2025, 1, 1))
        response = self.client.get('/analytics/station-metadata/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'META999')
