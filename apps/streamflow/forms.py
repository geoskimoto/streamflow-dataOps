"""Django forms for streamflow application."""

from django import forms
from django.forms import ModelForm, inlineformset_factory
from .models import PullConfiguration, PullConfigurationStation, MasterStation


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


# Inline formset for adding stations to a configuration
PullConfigurationStationFormSet = inlineformset_factory(
    PullConfiguration,
    PullConfigurationStation,
    fields=['station_number', 'station_name', 'huc_code', 'state'],
    extra=1,
    can_delete=True,
)
