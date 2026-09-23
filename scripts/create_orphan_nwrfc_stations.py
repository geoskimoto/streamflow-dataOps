"""
Create minimal Station records for NWRFC archive LIDs that resolve nowhere.

53 LIDs in the WY2006-2026 NWRFC archive return HTTP 404 from the NWPS gauge
endpoint and are absent from Station, MasterStation and StationMapping. They
appear to be retired NWRFC forecast points (plus a few 'X'-suffixed auxiliary
points). Their 203,314 forecast runs exist only in this archive and cannot be
re-fetched from any API, so we create placeholder stations rather than drop
the data.

The records are deliberately minimal and honest about what is unknown:
  - latitude/longitude left NULL (the model allows it) rather than guessed
  - is_active=False, so they stay out of pull configurations and active counts
  - name marks them as placeholders needing metadata

Idempotent: uses get_or_create and never overwrites an existing station.

  PYTHONPATH=$PWD venv/bin/python scripts/create_orphan_nwrfc_stations.py --dry-run
  PYTHONPATH=$PWD venv/bin/python scripts/create_orphan_nwrfc_stations.py
"""
import argparse
import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from apps.streamflow.models import Station  # noqa: E402

# Measured from the dry-run of import_parquet_forecasts against
# all_nwrfc_forecasts_WY2006_2026.parquet on 2026-09-23.
ORPHAN_LIDS = [
    "AGSO3", "APPO3", "ARDI1", "AUBW1X", "BNKW1", "BUDW1", "CDRW1", "CLUW1",
    "CPCW1", "CRCI1", "CSCI1", "CXCI1", "DRUM8", "ESSM8", "ETNI1", "ETSI1",
    "FCEO3", "GLAO3", "IHDW1", "JDAO3", "KADW1", "KEDW1", "KTCW1", "LGRW1",
    "LMNW1", "MCBO3", "MCDW1", "MCLO3", "MCMW1", "MEWW1", "MSRW1", "MYDW1",
    "MYDW1X", "NOXM8", "OSWO3", "OWCO3", "POBM8", "PRWW1", "PUYW1X", "RILW1",
    "RIMW1", "SCDO3", "SHDW1", "SKBW1", "SLNW1", "STOW1", "STWM8", "VANW1",
    "WFRM8", "WKMW1", "WLSO3", "WOPW1", "WYNW1",
]

# NWRFC LID suffixes encode the state; used only for the `state` field.
SUFFIX_STATE = {"O3": "OR", "W1": "WA", "I1": "ID", "M8": "MT"}


def state_for(lid):
    """Derive the state from the LID suffix, ignoring any trailing 'X'."""
    core = lid[:-1] if lid.endswith("X") else lid
    return SUFFIX_STATE.get(core[-2:], "")


def main(dry_run):
    created = existing = 0
    for lid in ORPHAN_LIDS:
        if dry_run:
            if Station.objects.filter(station_number=lid).exists():
                existing += 1
            else:
                created += 1
                print(f"  [DRY RUN] would create {lid} (state={state_for(lid) or '?'})")
            continue

        _, was_created = Station.objects.get_or_create(
            station_number=lid,
            defaults={
                "name": f"NWRFC forecast point {lid} (archive-only, metadata pending)",
                "agency": "NOAA_RFC",
                "state": state_for(lid),
                "is_active": False,
            },
        )
        if was_created:
            created += 1
            print(f"  created {lid} (state={state_for(lid) or '?'})")
        else:
            existing += 1

    verb = "would create" if dry_run else "created"
    print(f"\n{verb}: {created}   already present: {existing}   total: {len(ORPHAN_LIDS)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    main(ap.parse_args().dry_run)
