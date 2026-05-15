import math

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count, Q

from apps.streamflow.models import (
    DischargeObservation,  # noqa: F401 — confirms model name at import time
    ForecastRun,
    MasterStation,
    Station,
    StationMapping,
)


def _dist(lat1, lon1, lat2, lon2):
    """Euclidean distance in degrees between two coordinate pairs."""
    return math.sqrt((lat1 - lat2) ** 2 + (lon1 - lon2) ** 2)


class Command(BaseCommand):
    help = (
        "Populate station_mappings with NOAA_RFC → USGS pairings by matching "
        "NOAA HADS station coordinates (from master_stations) to the nearest "
        "USGS station that has >= 30 daily_mean DischargeObservations."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--clear",
            action="store_true",
            default=False,
            help="Delete existing NOAA_RFC → USGS mappings before running.",
        )
        parser.add_argument(
            "--threshold",
            type=float,
            default=0.1,
            help="Maximum distance in degrees to consider a USGS station a match (default: 0.1).",
        )

    def handle(self, *args, **options):
        threshold = options["threshold"]

        if options["clear"]:
            deleted, _ = StationMapping.objects.filter(
                source_agency="NOAA_RFC", target_agency="USGS"
            ).delete()
            self.stdout.write(
                self.style.WARNING(f"Cleared {deleted} existing NOAA_RFC → USGS mapping(s).")
            )

        # ── 1. Build USGS candidate list ──────────────────────────────────────
        self.stdout.write("Loading USGS candidates with >= 30 daily_mean observations…")
        usgs_candidates = list(
            Station.objects.filter(
                agency="USGS",
                latitude__isnull=False,
                longitude__isnull=False,
            )
            .annotate(
                obs_count=Count(
                    "discharge_observations",
                    filter=Q(discharge_observations__type="daily_mean"),
                )
            )
            .filter(obs_count__gte=30)
            .values("id", "station_number", "latitude", "longitude")
        )
        self.stdout.write(f"  {len(usgs_candidates)} USGS candidates found.")

        # ── 2. Collect NOAA_RFC stations that have at least one ForecastRun ───
        self.stdout.write("Loading NOAA_RFC stations with forecast data…")
        noaa_station_ids = (
            ForecastRun.objects.filter(source="NOAA_RFC")
            .values_list("station_id", flat=True)
            .distinct()
        )
        noaa_stations = list(
            Station.objects.filter(id__in=noaa_station_ids, agency="NOAA_RFC")
        )
        total = len(noaa_stations)
        self.stdout.write(f"  {total} NOAA_RFC stations to process.")

        # ── 3. Build a lookup dict from master_stations for quick coord access ─
        # Key: station_number (HADS ID like "ABOM8"), value: (lat, lon)
        master_lookup: dict[str, tuple[float, float]] = {}
        for ms in MasterStation.objects.filter(
            station_number__in=[s.station_number for s in noaa_stations],
            latitude__isnull=False,
            longitude__isnull=False,
        ).values("station_number", "latitude", "longitude"):
            master_lookup[ms["station_number"]] = (
                float(ms["latitude"]),
                float(ms["longitude"]),
            )

        # Pre-cast USGS coords to float once for performance
        for c in usgs_candidates:
            c["latitude"] = float(c["latitude"])
            c["longitude"] = float(c["longitude"])

        # ── 4. Match each NOAA_RFC station to the nearest USGS candidate ──────
        mapped = 0
        unresolved_no_coords = 0
        unresolved_no_match = 0

        with transaction.atomic():
            for idx, noaa_station in enumerate(noaa_stations, start=1):
                if idx % 50 == 0 or idx == total:
                    self.stdout.write(f"  Processing {idx}/{total}…")

                coords = master_lookup.get(noaa_station.station_number)
                if coords is None:
                    unresolved_no_coords += 1
                    continue

                noaa_lat, noaa_lon = coords

                best_usgs = None
                best_dist = float("inf")
                for candidate in usgs_candidates:
                    d = _dist(noaa_lat, noaa_lon, candidate["latitude"], candidate["longitude"])
                    if d < best_dist:
                        best_dist = d
                        best_usgs = candidate

                if best_usgs is None or best_dist > threshold:
                    unresolved_no_match += 1
                    continue

                StationMapping.objects.update_or_create(
                    source_agency="NOAA_RFC",
                    source_id=noaa_station.station_number,
                    target_agency="USGS",
                    defaults={"target_id": best_usgs["station_number"]},
                )
                mapped += 1

        # ── 5. Summary ────────────────────────────────────────────────────────
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=" * 55))
        self.stdout.write(self.style.SUCCESS("NWRFC → USGS mapping complete"))
        self.stdout.write(self.style.SUCCESS("=" * 55))
        self.stdout.write(f"  Total NOAA_RFC stations processed : {total}")
        self.stdout.write(self.style.SUCCESS(f"  Mapped (upserted)                 : {mapped}"))
        self.stdout.write(
            self.style.WARNING(
                f"  Unresolved (no master coords)     : {unresolved_no_coords}"
            )
        )
        self.stdout.write(
            self.style.WARNING(
                f"  Unresolved (no USGS within {threshold}°) : {unresolved_no_match}"
            )
        )
