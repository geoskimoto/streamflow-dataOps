"""Forms for the analytics section."""

from django import forms
from croniter import croniter

from apps.analytics.models import StatisticsConfiguration


class StatisticsConfigurationForm(forms.ModelForm):
    class Meta:
        model = StatisticsConfiguration
        fields = [
            'name', 'description', 'computation_type', 'agency_filter',
            'schedule_type', 'annual_run_month', 'annual_run_day', 'schedule_value',
            'is_enabled',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
            'computation_type': forms.Select(attrs={'class': 'form-select'}),
            'agency_filter': forms.Select(attrs={'class': 'form-select'}),
            'schedule_type': forms.Select(attrs={'class': 'form-select'}),
            'annual_run_month': forms.NumberInput(attrs={'class': 'form-control'}),
            'annual_run_day': forms.NumberInput(attrs={'class': 'form-control'}),
            'schedule_value': forms.TextInput(attrs={
                'placeholder': '0 0 1 10 *',
                'class': 'form-control',
            }),
        }
        help_texts = {
            'schedule_value': 'Required for Custom schedule. 5-field cron (min hr dom mon dow).',
            'annual_run_month': '1–12. Default 10 (October = water year start).',
            'annual_run_day': '1–31. Default 1.',
        }

    def clean(self):
        cleaned_data = super().clean()
        schedule_type = cleaned_data.get('schedule_type')
        schedule_value = cleaned_data.get('schedule_value', '').strip()

        if schedule_type == 'custom':
            if not schedule_value:
                self.add_error('schedule_value', 'A cron expression is required for Custom schedule.')
            else:
                try:
                    croniter(schedule_value)
                except (ValueError, KeyError):
                    self.add_error(
                        'schedule_value',
                        f'Invalid cron expression: "{schedule_value}". Use 5 fields: min hr dom mon dow.',
                    )

        return cleaned_data
