"""Shared gage-list resolution for the observation backfill and audit commands.

Both commands accept the same three ways of naming gages, so the parsing lives
here rather than being duplicated per command.
"""

import csv
from pathlib import Path
from typing import Dict, List, Set

from django.core.management.base import CommandError

from apps.streamflow.models import Station


def resolve_gages(options: Dict) -> List[str]:
    """Return the USGS site ids selected by a command's options.

    Recognises, in priority order, ``gages`` (comma-separated), then
    ``gage_list_csv`` (a CSV with a ``usgs_id`` column), then ``all_usgs``.
    Duplicates are collapsed with first-seen order preserved.

    Raises:
        CommandError: if nothing is selected, or a CSV is missing or lacks
            a ``usgs_id`` column.
    """
    if options.get("gages"):
        return _dedupe(g.strip() for g in options["gages"].split(","))

    if options.get("gage_list_csv"):
        path = Path(options["gage_list_csv"])
        if not path.exists():
            raise CommandError(f"No such CSV: {path}")
        with path.open(newline="") as handle:
            reader = csv.DictReader(handle)
            if "usgs_id" not in (reader.fieldnames or []):
                raise CommandError(
                    f"{path} has no 'usgs_id' column "
                    f"(found: {reader.fieldnames})"
                )
            return _dedupe(
                (record.get("usgs_id") or "").strip() for record in reader
            )

    if options.get("all_usgs"):
        return list(
            Station.objects.filter(agency="USGS")
            .order_by("station_number")
            .values_list("station_number", flat=True)
        )

    raise CommandError(
        "Choose gages with --gages, --gage-list-csv or --all-usgs"
    )


def load_skip_file(path) -> Set[str]:
    """Return the gage ids listed one-per-line in ``path``, or an empty set."""
    if not path:
        return set()
    file_path = Path(path)
    if not file_path.exists():
        raise CommandError(f"No such skip file: {file_path}")
    return {
        line.strip()
        for line in file_path.read_text().splitlines()
        if line.strip()
    }


def _dedupe(values) -> List[str]:
    seen, out = set(), []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out
