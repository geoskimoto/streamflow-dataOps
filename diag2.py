import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from apps.streamflow.models import DischargeObservation, Station, PullConfiguration
from django.db.models import Max, Count
from datetime import date, timedelta

print("=" * 70)
print("A. Stations with daily_mean obs ON Feb 26 vs Feb 27")
print("=" * 70)
feb26 = DischargeObservation.objects.filter(
    type='daily_mean', observed_at__date=date(2026, 2, 26)
).values('station__agency').annotate(n=Count('station_id', distinct=True))
feb27 = DischargeObservation.objects.filter(
    type='daily_mean', observed_at__date=date(2026, 2, 27)
).values('station__agency').annotate(n=Count('station_id', distinct=True))
mar02 = DischargeObservation.objects.filter(
    type='daily_mean', observed_at__date=date(2026, 3, 2)
).values('station__agency').annotate(n=Count('station_id', distinct=True))

print("Agency      Feb-26   Feb-27   Mar-02")
agencies = set()
f26 = {r['station__agency']: r['n'] for r in feb26}
f27 = {r['station__agency']: r['n'] for r in feb27}
m02 = {r['station__agency']: r['n'] for r in mar02}
agencies = set(list(f26.keys()) + list(f27.keys()) + list(m02.keys()))
for a in sorted(agencies):
    print("  %-10s %6d   %6d   %6d" % (a or 'None', f26.get(a,0), f27.get(a,0), m02.get(a,0)))

print()
print("=" * 70)
print("B. Total distinct stations with any daily_mean observation")
print("   split by: has obs BEFORE Feb 27 only vs has obs ON/AFTER Feb 27")
print("=" * 70)
# Stations with obs before Feb 27
before = set(DischargeObservation.objects.filter(
    type='daily_mean', observed_at__date__lt=date(2026, 2, 27)
).values_list('station_id', flat=True).distinct())
# Stations with obs on/after Feb 27
after = set(DischargeObservation.objects.filter(
    type='daily_mean', observed_at__date__gte=date(2026, 2, 27)
).values_list('station_id', flat=True).distinct())
only_historical = before - after
active_recent = after
print("  Stations with daily_mean ONLY before Feb-27 (historical, no recent pull): %d" % len(only_historical))
print("  Stations with daily_mean ON or AFTER Feb-27 (active pulls):               %d" % len(active_recent))
print("  Stations in both:                                                          %d" % len(before & after))

print()
print("  Agency breakdown of 'only historical' stations:")
hist_agencies = DischargeObservation.objects.filter(
    station_id__in=list(only_historical),
    type='daily_mean'
).values('station__agency').annotate(n=Count('station_id', distinct=True))
for r in hist_agencies:
    print("    %-10s  %d stations" % (r['station__agency'], r['n']))

print()
print("=" * 70)
print("C. Active PullConfiguration summary (daily_mean type)")
print("=" * 70)
daily_configs = PullConfiguration.objects.filter(
    data_type='daily_mean', is_enabled=True
)
print("  Enabled daily_mean PullConfigurations: %d" % daily_configs.count())
for cfg in daily_configs:
    stations = cfg.configuration_stations.count()
    print("    [%d] %-40s  agency=%-6s  stations=%d  last_run=%s" % (
        cfg.id, cfg.name[:40], cfg.data_source, stations,
        cfg.last_run_at.strftime('%Y-%m-%d %H:%M') if cfg.last_run_at else 'Never'))

print()
all_configs = PullConfiguration.objects.filter(is_enabled=True)
print("  All enabled configs by data_type:")
from django.db.models import Count as DCount
for row in PullConfiguration.objects.filter(is_enabled=True).values('data_type', 'data_source').annotate(n=DCount('id')):
    print("    data_type=%-20s  source=%-8s  configs=%d" % (row['data_type'], row['data_source'], row['n']))
