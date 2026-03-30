"""
Django management command to import NWRFC forecast runs from a parquet file.

Usage examples:
    # Import all stations from a parquet file
    python manage.py import_parquet_forecasts nwrfc_forecast_runs.parquet

    # Preview without writing to the database
    python manage.py import_parquet_forecasts nwrfc_forecast_runs.parquet --dry-run

    # Import only specific stations
    python manage.py import_parquet_forecasts nwrfc_forecast_runs.parquet --station PATW1 PESW1

    # Use a smaller batch size (useful for low-memory environments)
    python manage.py import_parquet_forecasts nwrfc_forecast_runs.parquet --batch-size 200

Parquet schema expected:
    lid              object          NOAA Location ID (e.g. PATW1)
    issuance_time    datetime64[us]  When the forecast was issued
    sim_time         datetime64[us]  Simulated value timestamp (6-hourly)
    simulation (cfs) float64         Forecast discharge in cfs

Behaviour:
    - Timestamps are treated as UTC if tz-naive.
    - forecast_type is inferred from each run's actual horizon:
        ≤ 7 days → short, ≤ 10 days → medium, > 10 days → long
    - If a ForecastRun already exists in the DB for the same
      (station, source, run_date, forecast_type), its data is overwritten —
      the parquet file is considered the authoritative source of truth.
    - Missing Station records are created automatically:
        1. From an existing MasterStation record if one is found.
        2. By fetching metadata from the NOAA Water API otherwise.
      Runs are skipped for any LID that cannot be resolved.
"""

from django.core.management.base import BaseCommand, CommandError

from src.acquisition.parquet_forecast_importer import ParquetForecastImporter


class Command(BaseCommand):
    help = "Import NWRFC 6-hourly forecast runs from a parquet file into the database"

    def add_arguments(self, parser):
        parser.add_argument(
            "parquet_file",
            type=str,
            help="Path to the parquet file (absolute or relative to manage.py)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate and preview the import without writing to the database",
        )
        parser.add_argument(
            "--station",
            nargs="+",
            metavar="LID",
            help="Limit import to one or more NOAA LIDs (e.g. --station PATW1 PESW1)",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=500,
            metavar="N",
            help="Number of ForecastRun objects to upsert per database transaction (default: 500)",
        )

    def handle(self, *args, **options):
        parquet_path = options["parquet_file"]
        dry_run = options["dry_run"]
        filter_lids = options.get("station")
        batch_size = options["batch_size"]

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no data will be written to the database\n"))

        importer = ParquetForecastImporter(
            stdout=self.stdout,
            stderr=self.stderr,
            style=self.style,
        )

        try:
            importer.run(
                parquet_path=parquet_path,
                dry_run=dry_run,
                filter_lids=filter_lids,
                batch_size=batch_size,
            )
        except FileNotFoundError:
            raise CommandError(f"Parquet file not found: {parquet_path}")
        except ValueError as exc:
            raise CommandError(str(exc))
