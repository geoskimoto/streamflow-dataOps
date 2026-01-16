"""Django forms for streamflow application."""

from django import forms
from django.forms import ModelForm, inlineformset_factory
from django.core.exceptions import ValidationError
from .models import PullConfiguration, PullConfigurationStation, MasterStation, Station


class PullConfigurationForm(ModelForm):
    """Form for creating/editing pull configurations."""
    
    class Meta:
        model = PullConfiguration
        fields = [
            'name', 'description', 'data_type', 'data_strategy',
            'pull_start_date', 'is_enabled', 'schedule_type', 'schedule_value'
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
            'pull_start_date': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'schedule_value': forms.TextInput(attrs={
                'placeholder': 'e.g., 0 */6 * * * for every 6 hours'
            }),
        }


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
