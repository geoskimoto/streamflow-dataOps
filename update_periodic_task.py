"""
Update the 'compute-daily-flow-percentiles' PeriodicTask in the database
to run at 06:00, 12:00, and 18:00 UTC instead of 06:00 UTC only.

DatabaseScheduler uses the DB as source of truth; code changes to
app.conf.beat_schedule do NOT automatically propagate to existing rows.
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django_celery_beat.models import PeriodicTask, CrontabSchedule

TASK_NAME = 'compute-daily-flow-percentiles'

# Get or create the new crontab: minute=0, hour='6,12,18', everything else *
new_cron, created = CrontabSchedule.objects.get_or_create(
    minute='0',
    hour='6,12,18',
    day_of_week='*',
    day_of_month='*',
    month_of_year='*',
    timezone='UTC',
)
if created:
    print("Created new CrontabSchedule: minute=0 hour=6,12,18 UTC")
else:
    print("Reusing existing CrontabSchedule: minute=0 hour=6,12,18 UTC")

try:
    pt = PeriodicTask.objects.get(name=TASK_NAME)
    old_cron = pt.crontab
    pt.crontab = new_cron
    pt.save(update_fields=['crontab'])
    print("Updated PeriodicTask '%s'" % TASK_NAME)
    print("  Old schedule: minute=%s hour=%s" % (old_cron.minute, old_cron.hour))
    print("  New schedule: minute=%s hour=%s" % (new_cron.minute, new_cron.hour))
except PeriodicTask.DoesNotExist:
    print("ERROR: PeriodicTask '%s' not found in database." % TASK_NAME)
    raise

# Verify
pt.refresh_from_db()
print("\nVerified — PeriodicTask state:")
print("  name:     %s" % pt.name)
print("  enabled:  %s" % pt.enabled)
print("  schedule: %s" % pt.crontab)
print("  last_run: %s" % pt.last_run_at)
