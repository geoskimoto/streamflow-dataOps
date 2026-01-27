"""Django forms for streamflow application."""

from django import forms
from django.forms import ModelForm, inlineformset_factory
from django.core.exceptions import ValidationError
from django.utils import timezone
from .models import (
    PullConfiguration, 
    PullConfigurationStation, 
    MasterStation, 
    Station,
    RasterPullConfiguration,
    RasterVariable,
    SpatialExtent
)
import re


class PullConfigurationForm(ModelForm):
    """Form for creating/editing pull configurations with enhanced validation."""
    
    class Meta:
        model = PullConfiguration
        fields = [
            'name', 'description', 'data_source', 'data_type', 'data_strategy',
            'pull_start_date', 'is_enabled', 'schedule_type', 'schedule_value'
        ]
        widgets = {
            'description': forms.Textarea(attrs={
                'rows': 3,
                'placeholder': 'Describe the purpose and scope of this configuration...',
                'class': 'form-control'
            }),
            'pull_start_date': forms.DateTimeInput(attrs={
                'type': 'datetime-local',
                'class': 'form-control'
            }),
            'schedule_value': forms.TextInput(attrs={
                'placeholder': 'e.g., 0 */6 * * * for every 6 hours',
                'class': 'form-control'
            }),
            'name': forms.TextInput(attrs={
                'placeholder': 'Configuration name',
                'class': 'form-control'
            }),
            'data_source': forms.Select(attrs={'class': 'form-select'}),
            'data_type': forms.Select(attrs={'class': 'form-select'}),
            'data_strategy': forms.Select(attrs={'class': 'form-select'}),
            'schedule_type': forms.Select(attrs={'class': 'form-select'}),
        }
        labels = {
            'name': 'Configuration Name',
            'description': 'Description',
            'data_source': 'Data Source',
            'data_type': 'Data Type',
            'data_strategy': 'Data Strategy',
            'pull_start_date': 'Start Date (Optional)',
            'is_enabled': 'Enable Configuration',
            'schedule_type': 'Schedule Type',
            'schedule_value': 'Cron Schedule (for custom)',
        }
        help_texts = {
            'name': 'A unique, descriptive name for this configuration',
            'data_source': 'Select the data source (USGS, Environment Canada, NOAA RFC)',
            'data_type': 'Choose discharge, stage, or forecast data type',
            'data_strategy': 'Full historical: pull all available data. Latest only: pull recent data only',
            'pull_start_date': 'Leave empty to start from earliest available data',
            'schedule_type': 'How frequently to run this configuration',
            'schedule_value': 'Required only for custom schedule type. Use standard cron format',
            'is_enabled': 'Disabled configurations will not run on schedule',
        }
    
    def clean_name(self):
        """Validate configuration name."""
        name = self.cleaned_data.get('name')
        
        if not name or len(name.strip()) < 3:
            raise ValidationError('Configuration name must be at least 3 characters long.')
        
        # Check for duplicate names (excluding current instance if editing)
        qs = PullConfiguration.objects.filter(name__iexact=name)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        
        if qs.exists():
            raise ValidationError('A configuration with this name already exists.')
        
        return name.strip()
    
    def clean_schedule_value(self):
        """Validate cron schedule format for custom schedules."""
        schedule_type = self.cleaned_data.get('schedule_type')
        schedule_value = self.cleaned_data.get('schedule_value', '').strip()
        
        if schedule_type == 'custom':
            if not schedule_value:
                raise ValidationError('Cron schedule is required for custom schedule type.')
            
            # Basic cron validation (5 fields)
            cron_parts = schedule_value.split()
            if len(cron_parts) != 5:
                raise ValidationError(
                    'Invalid cron format. Expected 5 fields: minute hour day month weekday. '
                    'Example: "0 */6 * * *" runs every 6 hours.'
                )
        
        return schedule_value
    
    def clean_pull_start_date(self):
        """Validate start date is not in the future."""
        start_date = self.cleaned_data.get('pull_start_date')
        
        if start_date and start_date > timezone.now():
            raise ValidationError('Start date cannot be in the future.')
        
        return start_date


class StationSelectionForm(forms.Form):
    """Form for selecting stations to add to a configuration."""
    
    state_filter = forms.ChoiceField(
        required=False,
        label='Filter by State',
        choices=[('', 'All States')],
    )
    
    huc_filter = forms.CharField(
        required=False,
        label='Filter by HUC Code',
        widget=forms.TextInput(attrs={'placeholder': 'e.g., 02070010'}),
    )
    
    search_query = forms.CharField(
        required=False,
        label='Search by Station ID or Name',
        widget=forms.TextInput(attrs={'placeholder': 'Search stations...'}),
    )
    
    selected_stations = forms.ModelMultipleChoiceField(
        queryset=MasterStation.objects.all(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Populate state choices from MasterStation
        states = MasterStation.objects.values_list(
            'state_code', flat=True
        ).distinct().order_by('state_code')
        
        self.fields['state_filter'].choices = [('', 'All States')] + [
            (state, state) for state in states if state
        ]


class StationForm(ModelForm):
    """Form for creating/editing station metadata."""
    
    class Meta:
        model = Station
        fields = [
            'station_number', 'name', 'agency', 
            'latitude', 'longitude', 'timezone', 'state', 'huc_code', 'basin',
            'catchment_area', 'years_of_record', 
            'record_start_date', 'record_end_date', 'is_active'
        ]
        widgets = {
            'station_number': forms.TextInput(attrs={
                'placeholder': 'e.g., 01013500 for USGS',
                'class': 'form-control'
            }),
            'name': forms.TextInput(attrs={
                'placeholder': 'Station name',
                'class': 'form-control'
            }),
            'agency': forms.Select(attrs={'class': 'form-control'}),
            'latitude': forms.NumberInput(attrs={
                'placeholder': 'Latitude (-90 to 90)',
                'step': '0.000001',
                'class': 'form-control'
            }),
            'longitude': forms.NumberInput(attrs={
                'placeholder': 'Longitude (-180 to 180)',
                'step': '0.000001',
                'class': 'form-control'
            }),
            'timezone': forms.TextInput(attrs={
                'placeholder': 'e.g., America/New_York',
                'class': 'form-control'
            }),
            'state': forms.TextInput(attrs={
                'placeholder': 'e.g., ME',
                'class': 'form-control'
            }),
            'huc_code': forms.TextInput(attrs={
                'placeholder': 'e.g., 02070010',
                'maxlength': '20',
                'class': 'form-control'
            }),
            'basin': forms.TextInput(attrs={
                'placeholder': 'Basin name',
                'class': 'form-control'
            }),
            'catchment_area': forms.NumberInput(attrs={
                'placeholder': 'Catchment area (sq km)',
                'step': '0.0001',
                'class': 'form-control'
            }),
            'years_of_record': forms.NumberInput(attrs={
                'placeholder': 'Years of record',
                'step': '0.01',
                'class': 'form-control'
            }),
            'record_start_date': forms.DateTimeInput(attrs={
                'type': 'datetime-local',
                'class': 'form-control'
            }),
            'record_end_date': forms.DateTimeInput(attrs={
                'type': 'datetime-local',
                'class': 'form-control'
            }),
        }
        help_texts = {
            'station_number': 'Unique identifier from the data agency (e.g., USGS site code)',
            'latitude': 'Decimal degrees, positive for North',
            'longitude': 'Decimal degrees, positive for East, negative for West',
            'huc_code': 'Hydrologic Unit Code',
            'catchment_area': 'Drainage area in square kilometers',
            'years_of_record': 'Total years of available data',
        }
    
    def clean_station_number(self):
        """Validate station_number uniqueness."""
        station_number = self.cleaned_data.get('station_number')
        
        # Check if station_number already exists (excluding current instance in edit mode)
        queryset = Station.objects.filter(station_number=station_number)
        if self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)
        
        if queryset.exists():
            raise ValidationError(
                f'Station with number "{station_number}" already exists.'
            )
        
        return station_number
    
    def clean_latitude(self):
        """Validate latitude is between -90 and 90."""
        latitude = self.cleaned_data.get('latitude')
        
        if latitude is not None:
            if latitude < -90 or latitude > 90:
                raise ValidationError(
                    'Latitude must be between -90 and 90 degrees.'
                )
        
        return latitude
    
    def clean_longitude(self):
        """Validate longitude is between -180 and 180."""
        longitude = self.cleaned_data.get('longitude')
        
        if longitude is not None:
            if longitude < -180 or longitude > 180:
                raise ValidationError(
                    'Longitude must be between -180 and 180 degrees.'
                )
        
        return longitude
    
    def clean_catchment_area(self):
        """Validate catchment_area is non-negative."""
        catchment_area = self.cleaned_data.get('catchment_area')
        
        if catchment_area is not None and catchment_area < 0:
            raise ValidationError(
                'Catchment area must be greater than or equal to 0.'
            )
        
        return catchment_area
    
    def clean(self):
        """Additional cross-field validation."""
        cleaned_data = super().clean()
        record_start_date = cleaned_data.get('record_start_date')
        record_end_date = cleaned_data.get('record_end_date')
        
        # Validate that record_end_date is after record_start_date
        if record_start_date and record_end_date:
            if record_end_date < record_start_date:
                raise ValidationError(
                    'End date must be after start date.'
                )
        
        return cleaned_data


# Inline formset for adding stations to a configuration
PullConfigurationStationFormSet = inlineformset_factory(
    PullConfiguration,
    PullConfigurationStation,
    fields=['station_number', 'station_name', 'huc_code', 'state'],
    extra=1,
    can_delete=True,
)


class RasterPullConfigurationForm(ModelForm):
    """Form for creating/editing raster pull configurations."""
    
    from .models import RasterPullConfiguration
    
    class Meta:
        model = RasterPullConfiguration
        fields = [
            'name', 'description', 'variables', 'extents',
            'schedule_enabled', 'pull_frequency_hours', 'lookback_days',
            'resampling_method', 'apply_compression', 'generate_thumbnails',
            'validate_on_pull'
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., HUC17 Daily RTMA'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Describe the purpose of this configuration...'
            }),
            'variables': forms.CheckboxSelectMultiple(),
            'extents': forms.CheckboxSelectMultiple(),
            'pull_frequency_hours': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': 1,
                'max': 168
            }),
            'lookback_days': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': 1,
                'max': 365
            }),
            'resampling_method': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'bilinear, nearest, cubic'
            }),
            'schedule_enabled': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'apply_compression': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'generate_thumbnails': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'validate_on_pull': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        labels = {
            'name': 'Configuration Name',
            'description': 'Description',
            'variables': 'Variables to Pull',
            'extents': 'Spatial Extents',
            'schedule_enabled': 'Enable Automatic Pulls',
            'pull_frequency_hours': 'Pull Frequency (hours)',
            'lookback_days': 'Lookback Period (days)',
            'resampling_method': 'Resampling Method',
            'apply_compression': 'Apply LZW Compression',
            'generate_thumbnails': 'Generate Thumbnails',
            'validate_on_pull': 'Validate After Pull',
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Add help text
        self.fields['pull_frequency_hours'].help_text = 'How often to pull data (in hours)'
        self.fields['lookback_days'].help_text = 'How many days back to check for data'
        self.fields['resampling_method'].help_text = 'Options: bilinear, nearest, cubic'
    
    def clean(self):
        cleaned_data = super().clean()
        variables = cleaned_data.get('variables')
        extents = cleaned_data.get('extents')
        
        # Validate that at least one variable and extent are selected
        if not variables:
            raise ValidationError('Select at least one variable.')
        if not extents:
            raise ValidationError('Select at least one spatial extent.')
        
        # Validate all variables are from the same dataset
        if variables:
            datasets = set(var.dataset for var in variables)
            if len(datasets) > 1:
                raise ValidationError('All variables must be from the same dataset.')
            # Auto-populate dataset from variables
            cleaned_data['dataset'] = list(datasets)[0]
        
        return cleaned_data
