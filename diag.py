import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

print("=" * 70)
print("1. PERIODIC TASK (Celery Beat DB Schedule)")
print("=" * 70)
from django_celery_beat.models import PeriodicTask
try:
    t = PeriodicTask.objects.get(name='compute-daily-flow-percentiles')
    print("EXISTS  enabled=%s  last_run_at=%s" % (t.enabled, t.last_run_at))
except PeriodicTask.DoesNotExist:
    print("MISSING — task was never seeded into the DB")

print("\n--- All PeriodicTasks ---")
for pt in PeriodicTask.objects.all().order_by('name'):
    print("  %-55s  enabled=%-5s  last_run=%s" % (pt.name, pt.enabled, pt.last_run_at))

print()
print("=" * 70)
print("2. COMPUTATION LOG (analytics task run history)")
print("=" * 70)
from apps.analytics.models import ComputationLog, ScheduledComputation
print("ScheduledComputation records:")
for sc in ScheduledComputation.objects.all():
    print("  name=%-30s  task_path=%-60s  enabled=%s  last_run=%s  status=%s" % (
        sc.name, sc.task_path, sc.is_enabled, sc.last_run_at, sc.last_run_status))

print("\nComputationLog (last 10 runs):")
logs = ComputationLog.objects.order_by('-started_at')[:10]
for l in logs:
    err = l.error_message[:60] if l.error_message else ''
    print("  %s  %-8s  records=%s  err=%s" % (l.started_at, l.status, l.records_computed, err))
print("  Total log entries:", ComputationLog.objects.count())

print()
print("=" * 70)
print("3. DAILY_FLOW_PERCENTILES table range")
print("=" * 70)
from apps.streamflow.models import DailyFlowPercentile
from django.db.models import Min, Max, Count
agg = DailyFlowPercentile.objects.aggregate(
    min_date=Min('date'), max_date=Max('date'), total=Count('id')
)
print("  min_date=%s  max_date=%s  total_rows=%s" % (agg['min_date'], agg['max_date'], agg['total']))
if agg['max_date']:
    from datetime import date, timedelta
    recent_dates = DailyFlowPercentile.objects.filter(
        date__gte=agg['max_date'] - timedelta(days=7)
    ).values('date').annotate(stations=Count('id')).order_by('-date')
    print("  Recent dates (stations with percentile rows):")
    for row in recent_dates:
        print("    %s  ->  %d stations" % (row['date'], row['stations']))

print()
print("=" * 70)
print("4. DISCHARGE_OBSERVATIONS latest daily_mean per agency")
print("=" * 70)
from apps.streamflow.models import DischargeObservation, Station
from django.db.models import Max
for agency in ['USGS', 'EC', 'NOAA_RFC']:
    latest = DischargeObservation.objects.filter(
        type='daily_mean', station__agency=agency
    ).aggregate(latest=Max('observed_at'))['latest']
    count = DischargeObservation.objects.filter(
        type='daily_mean', station__agency=agency
    ).count()
    print("  %-10s  latest_daily_mean=%-30s  total_records=%d" % (agency, str(latest), count))
