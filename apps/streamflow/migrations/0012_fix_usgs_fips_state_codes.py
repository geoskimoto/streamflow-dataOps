"""Data migration to convert USGS FIPS numeric state codes to 2-letter abbreviations."""

from django.db import migrations

# FIPS numeric code -> 2-letter state abbreviation (all 50 states + DC + territories)
FIPS_TO_STATE = {
    '1': 'AL', '2': 'AK', '4': 'AZ', '5': 'AR', '6': 'CA',
    '8': 'CO', '9': 'CT', '10': 'DE', '11': 'DC', '12': 'FL',
    '13': 'GA', '15': 'HI', '16': 'ID', '17': 'IL', '18': 'IN',
    '19': 'IA', '20': 'KS', '21': 'KY', '22': 'LA', '23': 'ME',
    '24': 'MD', '25': 'MA', '26': 'MI', '27': 'MN', '28': 'MS',
    '29': 'MO', '30': 'MT', '31': 'NE', '32': 'NV', '33': 'NH',
    '34': 'NJ', '35': 'NM', '36': 'NY', '37': 'NC', '38': 'ND',
    '39': 'OH', '40': 'OK', '41': 'OR', '42': 'PA', '44': 'RI',
    '45': 'SC', '46': 'SD', '47': 'TN', '48': 'TX', '49': 'UT',
    '50': 'VT', '51': 'VA', '53': 'WA', '54': 'WV', '55': 'WI',
    '56': 'WY',
    # Territories
    '60': 'AS', '66': 'GU', '69': 'MP', '72': 'PR', '78': 'VI',
}

STATE_TO_FIPS = {v: k for k, v in FIPS_TO_STATE.items()}


def fix_fips_forward(apps, schema_editor):
    MasterStation = apps.get_model('streamflow', 'MasterStation')
    Station = apps.get_model('streamflow', 'Station')
    PullConfigurationStation = apps.get_model('streamflow', 'PullConfigurationStation')

    for fips, abbr in FIPS_TO_STATE.items():
        MasterStation.objects.filter(
            agency='USGS', state_code=fips
        ).update(state_code=abbr)

        Station.objects.filter(
            agency='USGS', state=fips
        ).update(state=abbr)

        PullConfigurationStation.objects.filter(
            state=fips
        ).update(state=abbr)


def fix_fips_reverse(apps, schema_editor):
    MasterStation = apps.get_model('streamflow', 'MasterStation')
    Station = apps.get_model('streamflow', 'Station')
    PullConfigurationStation = apps.get_model('streamflow', 'PullConfigurationStation')

    for fips, abbr in FIPS_TO_STATE.items():
        MasterStation.objects.filter(
            agency='USGS', state_code=abbr
        ).update(state_code=fips)

        Station.objects.filter(
            agency='USGS', state=abbr
        ).update(state=fips)

        PullConfigurationStation.objects.filter(
            state=abbr,
            configuration__data_source='USGS',
        ).update(state=fips)


class Migration(migrations.Migration):

    dependencies = [
        ('streamflow', '0011_alter_forecastrun_run_date'),
    ]

    operations = [
        migrations.RunPython(fix_fips_forward, fix_fips_reverse),
    ]
