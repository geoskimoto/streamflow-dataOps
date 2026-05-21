from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('analytics', '0007_add_percentile_computation_types'),
    ]

    operations = [
        # ComputationLog has a FK to ScheduledComputation — must be deleted first
        migrations.DeleteModel(name='ComputationLog'),
        migrations.DeleteModel(name='ScheduledComputation'),
    ]
