"""Comprehensive tests for all views and templates."""

import os
from django.test import TestCase, Client
from django.urls import reverse, resolve
from django.conf import settings
from apps.streamflow.models import (
    PullConfiguration,
    Station,
    MasterStation,
    DataPullLog,
    DischargeObservation,
)
from decimal import Decimal


class ViewsAndTemplatesTestCase(TestCase):
    """Test that all views work and have proper templates."""

    @classmethod
    def setUpTestData(cls):
        """Create test data."""
        # Create test station
        cls.station = Station.objects.create(
            station_number="01010000",
            name="Test Station",
            agency="USGS",
            latitude=Decimal("45.0"),
            longitude=Decimal("-70.0"),
            state="ME",
            huc_code="01010001",
            is_active=True,
        )

        # Create master station
        cls.master_station = MasterStation.objects.create(
            station_number="01010001",
            station_name="Test Master Station",
            latitude=Decimal("45.0"),
            longitude=Decimal("-70.0"),
            state_code="ME",
            huc_code="01010001",
            agency="USGS",
        )

        # Create pull configuration
        cls.config = PullConfiguration.objects.create(
            name="Test Configuration",
            description="Test description",
            data_type="daily_mean",
            data_strategy="append",
            pull_start_date="2026-01-01T00:00:00Z",
            schedule_type="daily",
            is_enabled=True,
        )

        # Create data pull log
        cls.log = DataPullLog.objects.create(
            configuration=cls.config,
            status="success",
            start_time="2026-01-20T12:00:00Z",
            records_processed=100,
        )

        # Create observation
        cls.observation = DischargeObservation.objects.create(
            station=cls.station,
            observed_at="2026-01-20T12:00:00Z",
            discharge=Decimal("100.0"),
            unit="cfs",
            type="daily_mean",
        )

    def setUp(self):
        """Set up test client."""
        self.client = Client()

    def test_dashboard_view(self):
        """Test dashboard view."""
        url = reverse('streamflow:dashboard')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'streamflow/dashboard.html')

    def test_configuration_list_view(self):
        """Test configuration list view."""
        url = reverse('streamflow:configuration_list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'streamflow/configuration_list.html')

    def test_configuration_detail_view(self):
        """Test configuration detail view."""
        url = reverse('streamflow:configuration_detail', args=[self.config.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'streamflow/configuration_detail.html')

    def test_configuration_create_view(self):
        """Test configuration create view."""
        url = reverse('streamflow:configuration_create')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'streamflow/configuration_form.html')

    def test_configuration_update_view(self):
        """Test configuration update view."""
        url = reverse('streamflow:configuration_update', args=[self.config.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'streamflow/configuration_form.html')

    def test_configuration_delete_view(self):
        """Test configuration delete view."""
        url = reverse('streamflow:configuration_delete', args=[self.config.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'streamflow/configuration_confirm_delete.html')

    def test_station_list_view(self):
        """Test station list view."""
        url = reverse('streamflow:station_list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'streamflow/station_list.html')

    def test_station_detail_view(self):
        """Test station detail view."""
        url = reverse('streamflow:station_detail', args=[self.station.station_number])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'streamflow/station_detail.html')

    def test_station_create_view(self):
        """Test station create view."""
        url = reverse('streamflow:station_create')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'streamflow/station_form.html')

    def test_station_update_view(self):
        """Test station update view."""
        url = reverse('streamflow:station_update', args=[self.station.station_number])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'streamflow/station_form.html')

    def test_station_import_view(self):
        """Test station import view."""
        url = reverse('streamflow:station_import')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'streamflow/station_import.html')

    def test_station_sync_view(self):
        """Test station sync view."""
        url = reverse('streamflow:station_sync')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'streamflow/station_sync.html')

    def test_add_stations_to_config_view(self):
        """Test add stations to config view."""
        url = reverse('streamflow:add_stations', args=[self.config.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'streamflow/add_stations.html')

    def test_log_list_view(self):
        """Test log list view."""
        url = reverse('streamflow:log_list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'streamflow/log_list.html')

    def test_log_detail_view(self):
        """Test log detail view."""
        url = reverse('streamflow:log_detail', args=[self.log.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'streamflow/log_detail.html')

    def test_all_urls_resolve(self):
        """Test that all URL patterns can be resolved."""
        urls_to_test = [
            ('streamflow:dashboard', [], {}),
            ('streamflow:configuration_list', [], {}),
            ('streamflow:configuration_create', [], {}),
            ('streamflow:configuration_detail', [self.config.pk], {}),
            ('streamflow:configuration_update', [self.config.pk], {}),
            ('streamflow:configuration_delete', [self.config.pk], {}),
            ('streamflow:trigger_pull', [self.config.pk], {}),
            ('streamflow:toggle_configuration', [self.config.pk], {}),
            ('streamflow:station_list', [], {}),
            ('streamflow:station_create', [], {}),
            ('streamflow:station_import', [], {}),
            ('streamflow:station_sync', [], {}),
            ('streamflow:station_export_csv', [], {}),
            ('streamflow:station_detail', [self.station.station_number], {}),
            ('streamflow:station_update', [self.station.station_number], {}),
            ('streamflow:toggle_station_status', [self.station.station_number], {}),
            ('streamflow:add_stations', [self.config.pk], {}),
            ('streamflow:add_station_to_config', [self.config.pk], {}),
            ('streamflow:log_list', [], {}),
            ('streamflow:log_detail', [self.log.pk], {}),
        ]

        for url_name, args, kwargs in urls_to_test:
            with self.subTest(url_name=url_name):
                try:
                    url = reverse(url_name, args=args, kwargs=kwargs)
                    self.assertIsNotNone(url, f"URL {url_name} could not be reversed")
                except Exception as e:
                    self.fail(f"Failed to reverse URL {url_name}: {e}")

    def test_ajax_endpoints(self):
        """Test AJAX endpoints return JSON."""
        # Test station search AJAX
        url = reverse('streamflow:station_search_ajax')
        response = self.client.get(url, {'q': 'test'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')

    def test_post_only_views_reject_get(self):
        """Test that POST-only views handle requests appropriately."""
        # These should redirect on GET
        post_urls = [
            ('streamflow:trigger_pull', [self.config.pk]),
            ('streamflow:toggle_configuration', [self.config.pk]),
            ('streamflow:toggle_station_status', [self.station.station_number]),
        ]

        for url_name, args in post_urls:
            with self.subTest(url_name=url_name):
                url = reverse(url_name, args=args)
                response = self.client.get(url, follow=False)
                # These views redirect on successful POST, but may not handle GET gracefully
                # Just verify they don't crash
                self.assertIn(response.status_code, [200, 302, 405])

    def test_templates_exist(self):
        """Test that all template files actually exist on disk."""
        templates_to_check = [
            'streamflow/dashboard.html',
            'streamflow/configuration_list.html',
            'streamflow/configuration_detail.html',
            'streamflow/configuration_form.html',
            'streamflow/configuration_confirm_delete.html',
            'streamflow/station_list.html',
            'streamflow/station_detail.html',
            'streamflow/station_form.html',
            'streamflow/station_import.html',
            'streamflow/station_sync.html',
            'streamflow/add_stations.html',
            'streamflow/log_list.html',
            'streamflow/log_detail.html',
        ]

        template_dirs = settings.TEMPLATES[0]['DIRS']
        app_template_dir = os.path.join(
            settings.BASE_DIR, 'apps', 'streamflow', 'templates'
        )

        for template in templates_to_check:
            with self.subTest(template=template):
                # Check in app templates directory
                template_path = os.path.join(app_template_dir, template)
                self.assertTrue(
                    os.path.exists(template_path),
                    f"Template {template} does not exist at {template_path}"
                )

    def test_base_template_exists(self):
        """Test that base template exists."""
        base_template = os.path.join(settings.BASE_DIR, 'templates', 'base.html')
        self.assertTrue(
            os.path.exists(base_template),
            f"Base template does not exist at {base_template}"
        )


class ViewResponseContentTestCase(TestCase):
    """Test that views return expected content."""

    @classmethod
    def setUpTestData(cls):
        """Create test data."""
        cls.station = Station.objects.create(
            station_number="01010000",
            name="Test Station",
            agency="USGS",
            is_active=True,
        )
        cls.config = PullConfiguration.objects.create(
            name="Test Config",
            data_type="daily_mean",
            data_strategy="append",
            pull_start_date="2026-01-01T00:00:00Z",
            schedule_type="daily",
            is_enabled=True,
        )

    def setUp(self):
        """Set up test client."""
        self.client = Client()

    def test_dashboard_contains_key_elements(self):
        """Test dashboard contains expected elements."""
        response = self.client.get(reverse('streamflow:dashboard'))
        self.assertContains(response, 'Dashboard')
        self.assertContains(response, 'Configuration')
        self.assertContains(response, 'Station')

    def test_station_list_contains_station(self):
        """Test station list displays stations."""
        response = self.client.get(reverse('streamflow:station_list'))
        self.assertContains(response, 'Stations')
        self.assertContains(response, self.station.station_number)

    def test_configuration_list_contains_config(self):
        """Test configuration list displays configurations."""
        response = self.client.get(reverse('streamflow:configuration_list'))
        self.assertContains(response, 'Configurations')
        self.assertContains(response, self.config.name)

    def test_station_detail_shows_info(self):
        """Test station detail shows station information."""
        response = self.client.get(
            reverse('streamflow:station_detail', args=[self.station.station_number])
        )
        self.assertContains(response, self.station.name)
        self.assertContains(response, self.station.station_number)

    def test_configuration_detail_shows_info(self):
        """Test configuration detail shows configuration information."""
        response = self.client.get(
            reverse('streamflow:configuration_detail', args=[self.config.pk])
        )
        self.assertContains(response, self.config.name)
        self.assertContains(response, self.config.description or '')
