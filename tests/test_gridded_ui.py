"""
Comprehensive UI tests for Gridded Data (Raster) frontend.

Tests all pages, forms, navigation, and user interactions.
"""

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
import json

from apps.streamflow.models import (
    RasterDataset,
    RasterVariable,
    SpatialExtent,
    RasterLayer,
    RasterPullConfiguration,
    RasterPullLog
)


class GriddedDataUITestCase(TestCase):
    """Base test case with common setup for gridded data UI tests."""
    
    def setUp(self):
        """Set up test data."""
        self.client = Client()
        
        # Create dataset
        self.dataset = RasterDataset.objects.create(
            name='RTMA',
            description='Real-Time Mesoscale Analysis',
            gee_collection_id='NOAA/NWS/RTMA',
            resolution_m=2500,
            temporal_resolution='hourly',
            update_frequency='hourly',
            is_active=True
        )
        
        # Create variables
        self.temp_var = RasterVariable.objects.create(
            dataset=self.dataset,
            name='temperature',
            gee_band_name='TMP',
            unit='K',
            description='Air temperature at 2m'
        )
        
        self.precip_var = RasterVariable.objects.create(
            dataset=self.dataset,
            name='precipitation',
            gee_band_name='APCP',
            unit='kg/m^2',
            description='Accumulated precipitation'
        )
        
        # Create extent
        self.extent = SpatialExtent.objects.create(
            name='HUC_17',
            description='Columbia River Basin',
            min_lon=-125,
            min_lat=32,
            max_lon=-110,
            max_lat=42
        )
        
        # Create raster layer
        self.layer = RasterLayer.objects.create(
            variable=self.temp_var,
            extent=self.extent,
            timestamp=timezone.now(),
            date=timezone.now().date(),
            file_path='/fake/path/test.tif',
            resolution_m=2500.0,
            width_pixels=100,
            height_pixels=100,
            min_value=273.15,  # 0°C
            max_value=303.15,  # 30°C
            mean_value=288.15,  # 15°C
            std_dev=5.0,
            is_valid=True
        )
        
        # Create configuration
        self.config = RasterPullConfiguration.objects.create(
            name='Test RTMA Config',
            description='Test configuration',
            dataset=self.dataset,
            schedule_enabled=True,
            pull_frequency_hours=6,
            lookback_days=7
        )
        self.config.variables.add(self.temp_var)
        self.config.extents.add(self.extent)
        
        # Create pull log
        self.log = RasterPullLog.objects.create(
            configuration=self.config,
            status='success',
            started_at=timezone.now() - timedelta(hours=1),
            completed_at=timezone.now(),
            layers_successful=5
        )


class GriddedDataListViewTests(GriddedDataUITestCase):
    """Test gridded data list page."""
    
    def test_list_view_loads(self):
        """Test that list view loads successfully."""
        response = self.client.get(reverse('streamflow:gridded_data_list'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'streamflow/gridded_data_list.html')
    
    def test_list_view_shows_layers(self):
        """Test that layers appear in list."""
        response = self.client.get(reverse('streamflow:gridded_data_list'))
        self.assertContains(response, 'temperature')
        self.assertContains(response, 'HUC_17')
        self.assertContains(response, 'RTMA')
    
    def test_list_view_filters_by_dataset(self):
        """Test filtering by dataset."""
        response = self.client.get(
            reverse('streamflow:gridded_data_list'),
            {'dataset': 'RTMA'}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'temperature')
    
    def test_list_view_filters_by_variable(self):
        """Test filtering by variable."""
        response = self.client.get(
            reverse('streamflow:gridded_data_list'),
            {'variable': 'temperature'}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['layers']), 1)
    
    def test_list_view_filters_by_extent(self):
        """Test filtering by extent."""
        response = self.client.get(
            reverse('streamflow:gridded_data_list'),
            {'extent': 'HUC_17'}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['layers']), 1)
    
    def test_list_view_filters_by_date_range(self):
        """Test filtering by date range."""
        today = timezone.now().date()
        response = self.client.get(
            reverse('streamflow:gridded_data_list'),
            {
                'start_date': today.isoformat(),
                'end_date': today.isoformat()
            }
        )
        self.assertEqual(response.status_code, 200)
    
    def test_list_view_empty_state(self):
        """Test empty state when no layers match filters."""
        RasterLayer.objects.all().delete()
        response = self.client.get(reverse('streamflow:gridded_data_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No gridded data layers found')
    
    def test_list_view_pagination(self):
        """Test pagination works."""
        # Create 60 layers (more than page size of 50)
        for i in range(60):
            RasterLayer.objects.create(
                variable=self.temp_var,
                extent=self.extent,
                timestamp=timezone.now(),
                date=timezone.now().date(),
                file_path=f'/fake/path/test{i}.tif',
                resolution_m=2500.0,
                width_pixels=100,
                height_pixels=100,
                is_valid=True
            )
        
        response = self.client.get(reverse('streamflow:gridded_data_list'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['layers']), 50)
        
        # Test page 2
        response = self.client.get(
            reverse('streamflow:gridded_data_list'),
            {'page': 2}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['layers']), 11)


class GriddedDataDetailViewTests(GriddedDataUITestCase):
    """Test gridded data detail page."""
    
    def test_detail_view_loads(self):
        """Test that detail view loads successfully."""
        response = self.client.get(
            reverse('streamflow:gridded_data_detail', args=[self.layer.id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'streamflow/gridded_data_detail.html')
    
    def test_detail_view_shows_layer_info(self):
        """Test that layer information is displayed."""
        response = self.client.get(
            reverse('streamflow:gridded_data_detail', args=[self.layer.id])
        )
        self.assertContains(response, 'temperature')
        self.assertContains(response, 'RTMA')
        self.assertContains(response, 'HUC_17')
        self.assertContains(response, '2500')  # Resolution
    
    def test_detail_view_shows_statistics(self):
        """Test that statistics are displayed."""
        response = self.client.get(
            reverse('streamflow:gridded_data_detail', args=[self.layer.id])
        )
        self.assertContains(response, '273.15')  # Min value
        self.assertContains(response, '303.15')  # Max value
        self.assertContains(response, '288.15')  # Mean value
    
    def test_detail_view_shows_map(self):
        """Test that map elements are present."""
        response = self.client.get(
            reverse('streamflow:gridded_data_detail', args=[self.layer.id])
        )
        self.assertContains(response, 'leaflet')
        self.assertContains(response, 'id="map"')
    
    def test_detail_view_temperature_conversion(self):
        """Test temperature conversion filter appears."""
        response = self.client.get(
            reverse('streamflow:gridded_data_detail', args=[self.layer.id])
        )
        # Should show Fahrenheit conversion for Kelvin temps
        self.assertContains(response, '°F')
    
    def test_detail_view_404_invalid_id(self):
        """Test 404 for non-existent layer."""
        response = self.client.get(
            reverse('streamflow:gridded_data_detail', args=[99999])
        )
        self.assertEqual(response.status_code, 404)


class RasterConfigListViewTests(GriddedDataUITestCase):
    """Test raster configuration list page."""
    
    def test_config_list_loads(self):
        """Test that config list loads successfully."""
        response = self.client.get(reverse('streamflow:raster_config_list'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'streamflow/raster_config_list.html')
    
    def test_config_list_shows_configs(self):
        """Test that configurations appear in list."""
        response = self.client.get(reverse('streamflow:raster_config_list'))
        self.assertContains(response, 'Test RTMA Config')
        self.assertContains(response, 'RTMA')
    
    def test_config_list_shows_statistics(self):
        """Test that statistics are displayed."""
        response = self.client.get(reverse('streamflow:raster_config_list'))
        # Should show total runs and success rate
        self.assertContains(response, '1')  # 1 run
    
    def test_config_list_empty_state(self):
        """Test empty state when no configs."""
        RasterPullConfiguration.objects.all().delete()
        response = self.client.get(reverse('streamflow:raster_config_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No configurations found')


class RasterConfigCreateViewTests(GriddedDataUITestCase):
    """Test raster configuration create page."""
    
    def test_create_form_loads(self):
        """Test that create form loads successfully."""
        response = self.client.get(reverse('streamflow:raster_config_create'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'streamflow/raster_config_form.html')
    
    def test_create_form_shows_fields(self):
        """Test that form fields are present."""
        response = self.client.get(reverse('streamflow:raster_config_create'))
        self.assertContains(response, 'name')
        self.assertContains(response, 'dataset')
        self.assertContains(response, 'description')
        self.assertContains(response, 'variables')
        self.assertContains(response, 'extents')
    
    def test_create_config_success(self):
        """Test successful configuration creation."""
        data = {
            'name': 'New Test Config',
            'description': 'Test description',
            'dataset': self.dataset.id,
            'variables': [self.temp_var.id],
            'extents': [self.extent.id],
            'schedule_enabled': True,
            'pull_frequency_hours': 12,
            'lookback_days': 14,
            'resampling_method': 'bilinear',
            'apply_compression': True,
            'generate_thumbnails': False,
            'validate_on_pull': True
        }
        
        response = self.client.post(
            reverse('streamflow:raster_config_create'),
            data
        )
        
        self.assertEqual(response.status_code, 302)  # Redirect on success
        self.assertTrue(
            RasterPullConfiguration.objects.filter(name='New Test Config').exists()
        )
    
    def test_create_config_validation_no_variables(self):
        """Test validation error when no variables selected."""
        data = {
            'name': 'Bad Config',
            'dataset': self.dataset.id,
            'extents': [self.extent.id],
            'schedule_enabled': False,
            'pull_frequency_hours': 6,
            'lookback_days': 7
        }
        
        response = self.client.post(
            reverse('streamflow:raster_config_create'),
            data
        )
        
        self.assertEqual(response.status_code, 200)  # Stays on form
        self.assertContains(response, 'at least one variable')
    
    def test_create_config_validation_no_extents(self):
        """Test validation error when no extents selected."""
        data = {
            'name': 'Bad Config',
            'dataset': self.dataset.id,
            'variables': [self.temp_var.id],
            'schedule_enabled': False,
            'pull_frequency_hours': 6,
            'lookback_days': 7
        }
        
        response = self.client.post(
            reverse('streamflow:raster_config_create'),
            data
        )
        
        self.assertEqual(response.status_code, 200)  # Stays on form
        self.assertContains(response, 'at least one extent')


class RasterConfigDetailViewTests(GriddedDataUITestCase):
    """Test raster configuration detail page."""
    
    def test_detail_view_loads(self):
        """Test that detail view loads successfully."""
        response = self.client.get(
            reverse('streamflow:raster_config_detail', args=[self.config.id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'streamflow/raster_config_detail.html')
    
    def test_detail_view_shows_config_info(self):
        """Test that configuration information is displayed."""
        response = self.client.get(
            reverse('streamflow:raster_config_detail', args=[self.config.id])
        )
        self.assertContains(response, 'Test RTMA Config')
        self.assertContains(response, 'RTMA')
        self.assertContains(response, 'temperature')
        self.assertContains(response, 'HUC_17')
    
    def test_detail_view_shows_logs(self):
        """Test that execution logs are displayed."""
        response = self.client.get(
            reverse('streamflow:raster_config_detail', args=[self.config.id])
        )
        self.assertContains(response, 'Recent Execution Logs')
        self.assertContains(response, 'success')
    
    def test_detail_view_404_invalid_id(self):
        """Test 404 for non-existent config."""
        response = self.client.get(
            reverse('streamflow:raster_config_detail', args=[99999])
        )
        self.assertEqual(response.status_code, 404)


class RasterConfigEditViewTests(GriddedDataUITestCase):
    """Test raster configuration edit page."""
    
    def test_edit_form_loads(self):
        """Test that edit form loads successfully."""
        response = self.client.get(
            reverse('streamflow:raster_config_edit', args=[self.config.id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'streamflow/raster_config_form.html')
    
    def test_edit_form_shows_existing_data(self):
        """Test that form is pre-filled with existing data."""
        response = self.client.get(
            reverse('streamflow:raster_config_edit', args=[self.config.id])
        )
        self.assertContains(response, 'Test RTMA Config')
        self.assertContains(response, 'Test configuration')
    
    def test_edit_config_success(self):
        """Test successful configuration update."""
        data = {
            'name': 'Updated Config Name',
            'description': 'Updated description',
            'dataset': self.dataset.id,
            'variables': [self.temp_var.id, self.precip_var.id],
            'extents': [self.extent.id],
            'schedule_enabled': False,
            'pull_frequency_hours': 24,
            'lookback_days': 30,
            'resampling_method': 'nearest',
            'apply_compression': True,
            'generate_thumbnails': True,
            'validate_on_pull': False
        }
        
        response = self.client.post(
            reverse('streamflow:raster_config_edit', args=[self.config.id]),
            data
        )
        
        self.assertEqual(response.status_code, 302)  # Redirect on success
        
        self.config.refresh_from_db()
        self.assertEqual(self.config.name, 'Updated Config Name')
        self.assertEqual(self.config.pull_frequency_hours, 24)


class RasterConfigDeleteViewTests(GriddedDataUITestCase):
    """Test raster configuration delete page."""
    
    def test_delete_confirmation_loads(self):
        """Test that delete confirmation page loads."""
        response = self.client.get(
            reverse('streamflow:raster_config_delete', args=[self.config.id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'streamflow/raster_config_confirm_delete.html')
    
    def test_delete_shows_config_name(self):
        """Test that config name is shown in confirmation."""
        response = self.client.get(
            reverse('streamflow:raster_config_delete', args=[self.config.id])
        )
        self.assertContains(response, 'Test RTMA Config')
    
    def test_delete_config_success(self):
        """Test successful configuration deletion."""
        response = self.client.post(
            reverse('streamflow:raster_config_delete', args=[self.config.id])
        )
        
        self.assertEqual(response.status_code, 302)  # Redirect after delete
        self.assertFalse(
            RasterPullConfiguration.objects.filter(id=self.config.id).exists()
        )


class TriggerRasterPullViewTests(GriddedDataUITestCase):
    """Test manual raster pull trigger."""
    
    def test_trigger_requires_post(self):
        """Test that GET request doesn't trigger pull."""
        response = self.client.get(
            reverse('streamflow:trigger_raster_pull', args=[self.config.id])
        )
        # Should redirect or return error, not trigger
        self.assertNotEqual(response.status_code, 200)
    
    def test_trigger_404_invalid_id(self):
        """Test 404 for non-existent config."""
        response = self.client.post(
            reverse('streamflow:trigger_raster_pull', args=[99999])
        )
        self.assertEqual(response.status_code, 404)


class NavigationTests(GriddedDataUITestCase):
    """Test navigation and links."""
    
    def test_navbar_has_gridded_data_link(self):
        """Test that navbar contains gridded data link."""
        response = self.client.get(reverse('streamflow:dashboard'))
        self.assertContains(response, 'Gridded Data')
        self.assertContains(response, reverse('streamflow:gridded_data_list'))
    
    def test_navbar_has_gridded_config_link(self):
        """Test that navbar contains gridded config link."""
        response = self.client.get(reverse('streamflow:dashboard'))
        self.assertContains(response, 'Gridded Configurations')
        self.assertContains(response, reverse('streamflow:raster_config_list'))
    
    def test_dashboard_has_gridded_data_cards(self):
        """Test that dashboard shows gridded data statistics."""
        response = self.client.get(reverse('streamflow:dashboard'))
        self.assertContains(response, 'Gridded Data Layers')
        self.assertContains(response, 'Gridded Configurations')


class TemplateFilterTests(GriddedDataUITestCase):
    """Test custom template filters."""
    
    def test_kelvin_to_fahrenheit_filter(self):
        """Test temperature conversion filter."""
        from apps.streamflow.templatetags.raster_filters import kelvin_to_fahrenheit
        
        # 273.15 K = 32°F (freezing)
        result = kelvin_to_fahrenheit(273.15)
        self.assertAlmostEqual(result, 32.0, places=1)
        
        # 373.15 K = 212°F (boiling)
        result = kelvin_to_fahrenheit(373.15)
        self.assertAlmostEqual(result, 212.0, places=1)
        
        # None input
        result = kelvin_to_fahrenheit(None)
        self.assertIsNone(result)
    
    def test_kelvin_to_celsius_filter(self):
        """Test celsius conversion filter."""
        from apps.streamflow.templatetags.raster_filters import kelvin_to_celsius
        
        # 273.15 K = 0°C
        result = kelvin_to_celsius(273.15)
        self.assertAlmostEqual(result, 0.0, places=1)
        
        # 373.15 K = 100°C
        result = kelvin_to_celsius(373.15)
        self.assertAlmostEqual(result, 100.0, places=1)
    
    def test_format_file_size_filter(self):
        """Test file size formatting filter."""
        from apps.streamflow.templatetags.raster_filters import format_file_size
        
        # Test various sizes
        self.assertEqual(format_file_size(500), '500.0 B')
        self.assertEqual(format_file_size(1024), '1.0 KB')
        self.assertEqual(format_file_size(1024 * 1024), '1.0 MB')
        self.assertEqual(format_file_size(1024 * 1024 * 1024), '1.0 GB')


class ErrorHandlingTests(GriddedDataUITestCase):
    """Test error handling and edge cases."""
    
    def test_invalid_filter_values(self):
        """Test that invalid filter values don't break the page."""
        response = self.client.get(
            reverse('streamflow:gridded_data_list'),
            {'dataset': 'INVALID_DATASET'}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['layers']), 0)
    
    def test_invalid_date_format(self):
        """Test that invalid date format is handled gracefully."""
        response = self.client.get(
            reverse('streamflow:gridded_data_list'),
            {'start_date': 'not-a-date'}
        )
        # Should still load, just ignore invalid date
        self.assertEqual(response.status_code, 200)
    
    def test_layer_without_statistics(self):
        """Test displaying layer without statistics."""
        layer = RasterLayer.objects.create(
            variable=self.temp_var,
            extent=self.extent,
            timestamp=timezone.now(),
            date=timezone.now().date(),
            file_path='/fake/path/test.tif',
            resolution_m=2500.0,
            width_pixels=100,
            height_pixels=100,
            is_valid=True
            # No min/max/mean values
        )
        
        response = self.client.get(
            reverse('streamflow:gridded_data_detail', args=[layer.id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No statistics available')


class UIConsistencyTests(GriddedDataUITestCase):
    """Test UI consistency and styling."""
    
    def test_purple_theme_present(self):
        """Test that purple theme styling is present."""
        response = self.client.get(reverse('streamflow:gridded_data_list'))
        self.assertContains(response, '#6f42c1')  # Purple color
        self.assertContains(response, 'raster-card')
        self.assertContains(response, 'btn-raster')
    
    def test_all_pages_extend_base_template(self):
        """Test that all pages use base template."""
        urls = [
            reverse('streamflow:gridded_data_list'),
            reverse('streamflow:gridded_data_detail', args=[self.layer.id]),
            reverse('streamflow:raster_config_list'),
            reverse('streamflow:raster_config_create'),
        ]
        
        for url in urls:
            response = self.client.get(url)
            self.assertContains(response, 'Streamflow DataOps')  # Base template title
    
    def test_all_pages_have_back_buttons(self):
        """Test that detail pages have back navigation."""
        detail_urls = [
            reverse('streamflow:gridded_data_detail', args=[self.layer.id]),
            reverse('streamflow:raster_config_detail', args=[self.config.id]),
        ]
        
        for url in detail_urls:
            response = self.client.get(url)
            self.assertContains(response, 'Back')
