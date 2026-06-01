"""Management command to map NWRFC Q2 (Canadian) LIDs to EC gauge IDs via
coordinate proximity, and optionally export an EC→NWRFC JSON crosswalk.

Usage:
    python manage.py map_nwrfc_to_ec_stations
    python manage.py map_nwrfc_to_ec_stations --dry-run
    python manage.py map_nwrfc_to_ec_stations --export-json
    python manage.py map_nwrfc_to_ec_stations --clear
"""

import json
import math
import os

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.streamflow.models import Station, StationMapping
from src.acquisition.canada_client import CanadaClient


def _dist(lat1, lon1, lat2, lon2):
    """Euclidean distance in degrees."""
    return math.sqrt((lat1 - lat2) ** 2 + (lon1 - lon2) ** 2)


class Command(BaseCommand):
    help = (
        "Match NWRFC Q2 (Canadian BC) LIDs to EC gauge IDs by coordinate proximity "
        "and write StationMapping rows. Optionally export ec_nwrfc_crosswalk.json."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report matches without writing to DB or disk",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Delete existing NOAA_RFC→EC mappings first",
        )
        parser.add_argument(
            "--threshold",
            type=float,
            default=0.05,
            help="Max distance in degrees to accept a match (default: 0.05 ≈ 5 km)",
        )
        parser.add_argument(
            "--export-json",
            action="store_true",
            help="Write data/ec_nwrfc_crosswalk.json after matching",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        threshold = options["threshold"]

        self.stdout.write("=" * 60)
        self.stdout.write("MAP NWRFC Q2 STATIONS → EC GAUGE IDs")
        if dry_run:
            self.stdout.write(self.style.WARNING("(DRY RUN — no changes written)"))
        self.stdout.write("=" * 60)

        if options["clear"] and not dry_run:
            deleted, _ = StationMapping.objects.filter(
                source_agency="NOAA_RFC", target_agency="EC"
            ).delete()
            self.stdout.write(
                self.style.WARNING(f"Cleared {deleted} existing NOAA_RFC→EC mappings.")
            )

        # ── 1. Load NWRFC Q2 stations ─────────────────────────────────────
        q2_stations = list(
            Station.objects.filter(
                agency="NOAA_RFC",
                station_number__endswith="Q2",
                latitude__isnull=False,
                longitude__isnull=False,
            ).values("station_number", "latitude", "longitude")
        )
        self.stdout.write(
            f"Found {len(q2_stations)} NOAA_RFC Q2 stations with coordinates."
        )

        if not q2_stations:
            self.stdout.write(
                self.style.WARNING(
                    "No Q2 stations found. Run import_bc_stations first, "
                    "or ensure Station records exist with agency='NOAA_RFC' and "
                    "station_number ending in 'Q2'."
                )
            )
            return

        # ── 2. Load BC EC stations via CanadaClient ───────────────────────
        self.stdout.write("Fetching BC stations from Environment Canada API...")
        client = CanadaClient()
        ec_stations = client.get_stations_by_province("BC", limit=5000)
        ec_candidates = [
            s for s in ec_stations
            if s.get("latitude") is not None and s.get("longitude") is not None
        ]
        self.stdout.write(
            f"Loaded {len(ec_candidates)} EC BC stations with coordinates."
        )

        for s in ec_candidates:
            s["latitude"] = float(s["latitude"])
            s["longitude"] = float(s["longitude"])

        # ── 3. Coordinate matching ────────────────────────────────────────
        matched = []
        unresolved = []

        for q2 in q2_stations:
            q2_lat = float(q2["latitude"])
            q2_lon = float(q2["longitude"])

            best_ec = None
            best_dist = float("inf")
            for ec in ec_candidates:
                d = _dist(q2_lat, q2_lon, ec["latitude"], ec["longitude"])
                if d < best_dist:
                    best_dist = d
                    best_ec = ec

            if best_ec is None or best_dist > threshold:
                unresolved.append(q2["station_number"])
                self.stdout.write(
                    self.style.WARNING(
                        f"  UNRESOLVED: {q2['station_number']} "
                        f"(nearest EC {best_dist:.4f}° away)"
                    )
                )
            else:
                matched.append((q2["station_number"], best_ec["station_number"]))
                self.stdout.write(
                    f"  MATCH: {q2['station_number']} → {best_ec['station_number']} "
                    f"({best_ec.get('name', '')}, dist={best_dist:.4f}°)"
                )

        # ── 4. Write StationMapping rows ──────────────────────────────────
        if not dry_run:
            with transaction.atomic():
                for nwrfc_lid, ec_id in matched:
                    StationMapping.objects.update_or_create(
                        source_agency="NOAA_RFC",
                        source_id=nwrfc_lid,
                        target_agency="EC",
                        defaults={"target_id": ec_id},
                    )

        # ── 5. Export JSON crosswalk ──────────────────────────────────────
        if options["export_json"] and not dry_run:
            crosswalk = {ec_id: nwrfc_lid for nwrfc_lid, ec_id in matched}
            out_path = os.path.join(
                os.path.dirname(
                    os.path.dirname(
                        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                    )
                ),
                "data",
                "ec_nwrfc_crosswalk.json",
            )
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, "w") as f:
                json.dump(crosswalk, f, indent=2, sort_keys=True)
            self.stdout.write(self.style.SUCCESS(f"Exported crosswalk to {out_path}"))

        # ── 6. Summary ────────────────────────────────────────────────────
        self.stdout.write("")
        self.stdout.write("=" * 60)
        self.stdout.write(self.style.SUCCESS(f"  Matched   : {len(matched)}"))
        self.stdout.write(self.style.WARNING(f"  Unresolved: {len(unresolved)}"))
        if unresolved:
            self.stdout.write(f"  Unresolved LIDs: {', '.join(unresolved)}")
        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run — no DB changes made."))
