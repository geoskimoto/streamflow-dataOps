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
    """Return the station ids selected by a command's options.

    Recognises, in priority order, ``gages`` (comma-separated), then
    ``gage_list_csv`` (a CSV with a ``station_number`` or ``usgs_id``
    column - ``station_number`` wins if both are present), then
    ``all_usgs`` / ``all_ec`` (every ``Station`` with that agency).
    Duplicates are collapsed with first-seen order preserved.

    Which of ``--all-usgs``/``--all-ec`` a caller mentions in its error
    message is inferred from which of those keys are present in
    ``options`` at all (regardless of value) - i.e. whether the calling
    command's argparse defines that flag - so the USGS command's error
    doesn't advertise a flag it doesn't have, and vice versa.

    Raises:
        CommandError: if nothing is selected, or a CSV is missing or lacks
            a ``usgs_id``/``station_number`` column.
    """
    if options.get("gages"):
        return _dedupe(g.strip() for g in options["gages"].split(","))

    if options.get("gage_list_csv"):
        path = Path(options["gage_list_csv"])
        if not path.exists():
            raise CommandError(f"No such CSV: {path}")
        with path.open(newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = reader.fieldnames or []
            if "station_number" in fieldnames:
                column = "station_number"
            elif "usgs_id" in fieldnames:
                column = "usgs_id"
            else:
                raise CommandError(
                    f"{path} has no 'usgs_id' or 'station_number' column "
                    f"(found: {fieldnames})"
                )
            return _dedupe(
                (record.get(column) or "").strip() for record in reader
            )

    if options.get("all_usgs"):
        return _stations_for_agency("USGS")

    if options.get("all_ec"):
        return _stations_for_agency("EC")

    selectors = ["--gages", "--gage-list-csv"]
    if "all_usgs" in options:
        selectors.append("--all-usgs")
    if "all_ec" in options:
        selectors.append("--all-ec")
    raise CommandError(
        "Choose gages with " + ", ".join(selectors[:-1])
        + (" or " + selectors[-1] if len(selectors) > 1 else selectors[0])
    )


def _stations_for_agency(agency: str) -> List[str]:
    return list(
        Station.objects.filter(agency=agency)
        .order_by("station_number")
        .values_list("station_number", flat=True)
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
