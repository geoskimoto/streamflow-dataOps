"""
Back up and delete the NOAA_RFC rows superseded by the NWRFC archive.

Phases are separate commands so the backup is always taken before anything is
destroyed, and so --verify can be re-run afterwards.

  PYTHONPATH=$PWD venv/bin/python scripts/swap_nwrfc_archive.py --verify
  PYTHONPATH=$PWD venv/bin/python scripts/swap_nwrfc_archive.py --backup
  PYTHONPATH=$PWD venv/bin/python scripts/swap_nwrfc_archive.py --delete

Scope: everything inside the archive's coverage window EXCEPT three LIDs that
NWRFC does not carry in the archive. The NWPS API serves only the current
forecast, so those rows cannot be re-fetched and are preserved instead.
Rows predating the window (2003-07-18 → 2005-09-30) are outside the filter
and are never touched.
"""
import argparse
import gzip
import json
import os
import sys

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from apps.streamflow.models import ForecastRun  # noqa: E402

WINDOW_START = "2005-10-01 00:13:00+00"
WINDOW_END = "2026-09-22 16:24:00+00"
# Present in forecast_runs but absent from the archive; the NWPS API serves
# only the current forecast, so these 708 runs cannot be re-fetched.
EXCLUDED_LIDS = ["COQO3", "SKMW1", "WDHN2"]
BACKUP_PATH = "data/backups/nwrfc_superseded_runs.jsonl.gz"


def target_queryset():
    return (
        ForecastRun.objects.filter(
            source="NOAA_RFC",
            run_date__gte=WINDOW_START,
            run_date__lte=WINDOW_END,
        )
        .exclude(station__station_number__in=EXCLUDED_LIDS)
    )


def backup():
    os.makedirs(os.path.dirname(BACKUP_PATH), exist_ok=True)
    qs = target_queryset().select_related("station")
    n = 0
    with gzip.open(BACKUP_PATH, "wt") as fh:
        for r in qs.iterator(chunk_size=2000):
            fh.write(json.dumps({
                "station_number": r.station.station_number,
                "source": r.source,
                "run_date": r.run_date.isoformat(),
                "forecast_type": r.forecast_type,
                "is_forecast": r.is_forecast,
                "rmse": str(r.rmse) if r.rmse is not None else None,
                "data": r.data,
            }) + "\n")
            n += 1
    print(f"backed up {n:,} rows -> {BACKUP_PATH}")
    return n


def delete():
    if not os.path.exists(BACKUP_PATH):
        sys.exit(f"refusing to delete: no backup at {BACKUP_PATH}. Run --backup first.")
    n, _ = target_queryset().delete()
    print(f"deleted {n:,} rows")


def verify():
    from django.db.models import Count
    print("by source:", list(
        ForecastRun.objects.values("source").annotate(n=Count("id")).order_by()
    ))
    print("remaining in window:", target_queryset().count())
    print("preserved pre-window:", ForecastRun.objects.filter(
        source="NOAA_RFC", run_date__lt=WINDOW_START).count())
    print("preserved orphan-station:", ForecastRun.objects.filter(
        source="NOAA_RFC", station__station_number__in=EXCLUDED_LIDS).count())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--backup", action="store_true")
    ap.add_argument("--delete", action="store_true")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()
    if a.backup:
        backup()
    if a.delete:
        delete()
    if a.verify:
        verify()
    if not (a.backup or a.delete or a.verify):
        ap.error("pick at least one of --backup / --delete / --verify")
