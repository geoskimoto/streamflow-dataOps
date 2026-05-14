import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from apps.streamflow.models import DailyFlowPercentile
from django.db.models import Count
from datetime import date, timedelta

print("Stations with percentile rows by date (last 14 days):")
print("-" * 50)
today = date(2026, 3, 3)
for i in range(14):
    d = today - timedelta(days=i)
    n = DailyFlowPercentile.objects.filter(date=d).count()
    bar = "#" * (n // 20)
    print("  %s  %4d stations  %s" % (d, n, bar))
