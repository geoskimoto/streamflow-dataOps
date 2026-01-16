"""
Tests for streamflow app forms.
"""
from django.test import TestCase
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import timedelta
from apps.streamflow.forms import (
    PullConfigurationForm, StationForm, StationSelectionForm
)
from apps.streamflow.models import PullConfiguration, Station


class PullConfigurationFormTests(TestCase):
    """Tests for PullConfigurationForm."""
    
    def test_valid_form(self):
        """Test form with valid data."""
        form_data = {
            'name': 'Test Config',
            'description': 'Test description',
            'data_type': 'daily_mean',
            'data_strategy': 'append',
            'schedule_type': 'hourly',
            'is_enabled': True,
            'pull_start_date': timezone.now()
        }
        form = PullConfigurationForm(data=form_data)
        if not form.is_valid():
            print(f"Form errors: {form.errors}")
        self.assertTrue(form.is_valid())
    
    def test_name_too_short(self):
        """Test validation for short names."""
        form_data = {
            'name': 'AB',  # Only 2 characters
            'data_type': 'daily_mean',
            'data_strategy': 'append',
            'schedule_type': 'hourly'
        }
        form = PullConfigurationForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('name', form.errors)
    
    def test_duplicate_name(self):
        """Test validation for duplicate names."""
        # Create existing config
        PullConfiguration.objects.create(
            name='Existing Config',
            data_type='daily_mean',
            data_strategy='append',
            pull_start_date=timezone.now()
        )
        
        # Try to create another with same name
        form_data = {
            'name': 'Existing Config',
            'data_type': 'daily_mean',
            'data_strategy': 'append',
            'schedule_type': 'hourly'
        }
        form = PullConfigurationForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('name', form.errors)
    
    def test_custom_schedule_requires_cron(self):
        """Test that custom schedule requires cron expression."""
        form_data = {
            'name': 'Test Config',
            'data_type': 'daily_mean',
            'data_strategy': 'append',
            'schedule_type': 'custom',
            'schedule_value': ''  # Missing cron
        }
        form = PullConfigurationForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('schedule_value', form.errors)
    
    def test_valid_cron_schedule(self):
        """Test valid cron expression."""
        form_data = {
            'name': 'Test Config',
            'data_type': 'daily_mean',
            'data_strategy': 'append',
            'schedule_type': 'custom',
            'schedule_value': '0 */6 * * *',  # Valid cron
            'is_enabled': True,
            'pull_start_date': timezone.now()
        }
        form = PullConfigurationForm(data=form_data)
        self.assertTrue(form.is_valid())
    
    def test_invalid_cron_schedule(self):
        """Test invalid cron expression."""
        form_data = {
            'name': 'Test Config',
            'data_type': 'daily_mean',
            'data_strategy': 'append',
            'schedule_type': 'custom',
            'schedule_value': '0 */6 * *',  # Invalid: only 4 fields
            'is_enabled': True
        }
        form = PullConfigurationForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('schedule_value', form.errors)
    
    def test_future_start_date_rejected(self):
        """Test that future start dates are rejected."""
        future_date = timezone.now() + timedelta(days=1)
        form_data = {
            'name': 'Test Config',
            'data_type': 'daily_mean',
            'data_strategy': 'append',
            'schedule_type': 'hourly',
            'pull_start_date': future_date.isoformat(),
            'is_enabled': True
        }
        form = PullConfigurationForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('pull_start_date', form.errors)
    
    def test_past_start_date_accepted(self):
        """Test that past start dates are accepted."""
        past_date = timezone.now() - timedelta(days=30)
        form_data = {
            'name': 'Test Config',
            'data_type': 'daily_mean',
            'data_strategy': 'append',
            'schedule_type': 'hourly',
            'pull_start_date': past_date,
            'is_enabled': True
        }
        form = PullConfigurationForm(data=form_data)
        self.assertTrue(form.is_valid())


class StationFormTests(TestCase):
    """Tests for StationForm."""
    
    def test_valid_station_form(self):
        """Test form with valid station data."""
        form_data = {
            'station_number': '01013500',
            'name': 'Test River',
            'agency': 'USGS',
            'latitude': 47.068333,
            'longitude': -69.061111,
            'timezone': 'UTC',
            'is_active': True
        }
        form = StationForm(data=form_data)
        if not form.is_valid():
            print(f"Station form errors: {form.errors}")
        self.assertTrue(form.is_valid())
    
    def test_invalid_latitude(self):
        """Test validation for out-of-range latitude."""
        form_data = {
            'station_number': '01013500',
            'name': 'Test River',
            'agency': 'USGS',
            'latitude': 95.0,  # Out of range
            'longitude': -69.0,
            'is_active': True
        }
        form = StationForm(data=form_data)
        self.assertFalse(form.is_valid())
    
    def test_invalid_longitude(self):
        """Test validation for out-of-range longitude."""
        form_data = {
            'station_number': '01013500',
            'name': 'Test River',
            'agency': 'USGS',
            'latitude': 47.0,
            'longitude': -200.0,  # Out of range
            'is_active': True
        }
        form = StationForm(data=form_data)
        self.assertFalse(form.is_valid())
    
    def test_negative_catchment_area(self):
        """Test validation for negative catchment area."""
        form_data = {
            'station_number': '01013500',
            'name': 'Test River',
            'agency': 'USGS',
            'latitude': 47.0,
            'longitude': -69.0,
            'catchment_area': -100.0,  # Negative
            'is_active': True
        }
        form = StationForm(data=form_data)
        self.assertFalse(form.is_valid())
    
    def test_end_date_before_start_date(self):
        """Test validation for end date before start date."""
        form_data = {
            'station_number': '01013500',
            'name': 'Test River',
            'agency': 'USGS',
            'latitude': 47.0,
            'longitude': -69.0,
            'record_start_date': timezone.now().date(),
            'record_end_date': (timezone.now() - timedelta(days=365)).date(),
            'is_active': True
        }
        form = StationForm(data=form_data)
        self.assertFalse(form.is_valid())


class FormHelpTextTests(TestCase):
    """Tests for form help text and labels."""
    
    def test_configuration_form_has_help_text(self):
        """Test that configuration form has help text."""
        form = PullConfigurationForm()
        self.assertIsNotNone(form.fields['name'].help_text)
        self.assertIsNotNone(form.fields['data_type'].help_text)
        self.assertIsNotNone(form.fields['data_strategy'].help_text)
    
    def test_configuration_form_has_labels(self):
        """Test that configuration form has proper labels."""
        form = PullConfigurationForm()
        self.assertEqual(form.fields['name'].label, 'Configuration Name')
        self.assertEqual(form.fields['data_type'].label, 'Data Type')
        self.assertEqual(form.fields['data_strategy'].label, 'Data Strategy')
    
    def test_station_form_has_widgets(self):
        """Test that station form has proper widgets."""
        form = StationForm()
        self.assertIn('form-control', form.fields['station_number'].widget.attrs.get('class', ''))
        self.assertIn('placeholder', form.fields['station_number'].widget.attrs)
