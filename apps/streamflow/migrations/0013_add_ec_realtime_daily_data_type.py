from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('streamflow', '0012_fix_usgs_fips_state_codes'),
    ]

    operations = [
        migrations.AlterField(
            model_name='pullconfiguration',
            name='data_type',
            field=models.CharField(
                choices=[
                    ('realtime_15min', 'Real-time 15 min'),
                    ('daily_mean', 'Daily Mean'),
                    ('forecast', 'Forecast'),
                    ('ec_realtime_daily', 'EC Wateroffice Daily Mean'),
                ],
                max_length=20,
            ),
        ),
    ]
