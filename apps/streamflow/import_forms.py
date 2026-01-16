"""Station import form for bulk CSV uploads."""

from django import forms
from django.core.exceptions import ValidationError
import csv
import io


class StationImportForm(forms.Form):
    """Form for importing stations from CSV file."""
    
    csv_file = forms.FileField(
        label='CSV File',
        help_text='Upload a CSV file with station data. Required columns: station_number, name, agency, latitude, longitude',
        widget=forms.FileInput(attrs={
            'class': 'form-control',
            'accept': '.csv'
        })
    )
    
    skip_duplicates = forms.BooleanField(
        label='Skip duplicate stations',
        required=False,
        initial=True,
        help_text='Skip stations that already exist in the database',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )
    
    update_existing = forms.BooleanField(
        label='Update existing stations',
        required=False,
        initial=False,
        help_text='Update metadata for stations that already exist',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )
    
    def clean_csv_file(self):
        """Validate CSV file format and required columns."""
        csv_file = self.cleaned_data.get('csv_file')
        
        if not csv_file:
            return csv_file
        
        # Check file size (limit to 10MB)
        if csv_file.size > 10 * 1024 * 1024:
            raise ValidationError('File size exceeds 10MB limit.')
        
        # Check file extension
        if not csv_file.name.endswith('.csv'):
            raise ValidationError('File must be a CSV file.')
        
        # Try to parse CSV and validate headers
        try:
            # Read file content
            csv_file.seek(0)
            content = csv_file.read().decode('utf-8')
            csv_file.seek(0)  # Reset file pointer
            
            # Parse CSV
            reader = csv.DictReader(io.StringIO(content))
            headers = reader.fieldnames
            
            if not headers:
                raise ValidationError('CSV file is empty or has no headers.')
            
            # Check required columns
            required_columns = {'station_number', 'name', 'agency', 'latitude', 'longitude'}
            missing_columns = required_columns - set(headers)
            
            if missing_columns:
                raise ValidationError(
                    f'CSV file is missing required columns: {", ".join(missing_columns)}. '
                    f'Found columns: {", ".join(headers)}'
                )
            
            # Validate that there's at least one data row
            rows = list(reader)
            if not rows:
                raise ValidationError('CSV file contains no data rows.')
            
            # Store parsed data for later use
            self.parsed_rows = rows
            self.csv_headers = headers
            
        except UnicodeDecodeError:
            raise ValidationError('File must be UTF-8 encoded.')
        except csv.Error as e:
            raise ValidationError(f'Invalid CSV format: {str(e)}')
        except Exception as e:
            raise ValidationError(f'Error reading CSV file: {str(e)}')
        
        return csv_file
