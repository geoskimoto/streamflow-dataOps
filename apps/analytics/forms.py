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
            'description': forms.Textarea(attrs={'rows': 3}),
            'schedule_value': forms.TextInput(attrs={'placeholder': '0 0 1 10 *'}),
        }
        help_texts = {
            'schedule_value': 'Required for Custom schedule. 5-field cron (min hr dom mon dow).',
            'annual_run_month': '1–12. Default 10 (October = water year start).',
            'annual_run_day': '1–31. Default 1.',
        }

    def clean_annual_run_month(self):
        value = self.cleaned_data.get('annual_run_month')
        if value is not None and not (1 <= value <= 12):
            raise forms.ValidationError('Month must be between 1 and 12.')
        return value

    def clean_annual_run_day(self):
        value = self.cleaned_data.get('annual_run_day')
        if value is not None and not (1 <= value <= 31):
            raise forms.ValidationError('Day must be between 1 and 31.')
        return value

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
