"""Shared, agency-agnostic per-gage backfill runner.

Extracted from ``backfill_usgs_observations`` so a second agency's command
(Environment Canada) can reuse the same machinery without duplicating ~250
lines that survived several review rounds:

- per-gage fault isolation, with the DB connection explicitly reset after a
  failure so the *next* gage reconnects instead of also failing
- pacing (``time.sleep``) on every path - success, not-in-db, and failure
  alike - so a run of failures doesn't hammer a struggling upstream
  back-to-back
- a crash-safe ``<report>.done.txt`` resume sidecar, appended and flushed
  per gage (not just at the end) so a killed multi-hour run can resume
- the report CSV is written inside ``try/finally`` so even an exception or
  Ctrl-C still produces it, reflecting whatever rows completed so far
- a dry run that fetches and reports but makes no database writes, and
  never creates the resume sidecar

``fetch(station_number, start_date, end_date)`` is the one agency-specific
seam; everything else here is verbatim from the USGS command's ``handle()``.
"""

import csv
import time
from pathlib import Path

from django.db import connection
from django.db.models import Max

from apps.streamflow.management.gage_lists import load_skip_file
from apps.streamflow.models import DischargeObservation, Station
from src.acquisition.data_processor import DataProcessor

_REPORT_FIELDS = [
    "station_number",
    "status",
    "fetched",
    "written",
    "db_max_before",
    "db_max_after",
]


def run_backfill(*, command, gages, fetch, agency, options) -> list:
    """Run a per-gage backfill loop and return the collected report rows.

    ``command`` is used only for ``command.stdout.write(...)`` and
    ``command.style``, so callers keep their existing CLI output.
    ``fetch(station_number, start_date, end_date)`` is the agency-specific
    data source call. ``agency`` scopes the ``Station`` lookup so e.g. an EC
    run cannot accidentally process a USGS station sharing the same id.

    ``options`` is the command's parsed options dict, read with ``.get()``.
    The keys this function reads, and the contract each one has:

    - ``start``, ``end``: must already be ``None`` or a timezone-aware
      ``datetime`` by the time they reach this function - **never** the raw
      ``--start``/``--end`` strings argparse hands the command. This
      function does no parsing or validation of its own (that stays in the
      calling command, which raises ``CommandError`` on a bad format or an
      invalid range before calling here); it passes ``start``/``end``
      straight through to ``fetch(gage, start, end)`` unexamined. A command
      that forgets to parse and re-stash them into ``options`` before
      calling ``run_backfill`` will silently pass raw strings to ``fetch``
      instead of failing loudly - see the guard below, which catches this
      specific mistake.
    - ``dry_run``: truthy means fetch-and-report only, no database writes,
      and no ``.done.txt`` sidecar is created.
    - ``sleep``: seconds to pace between gages. **A missing key or an
      explicit ``None`` silently disables pacing** rather than raising -
      acceptable in tests, but a caller's command should always supply a
      real default (see ``backfill_usgs_observations``'s ``--sleep``
      default of ``1.0``), since pacing exists specifically because at
      least one upstream (USGS) degrades silently under bursts instead of
      returning a 429.
    - ``report``: path for the per-gage CSV report; also the base path for
      the ``<report>.done.txt`` resume sidecar. ``None``/falsy means no
      report and no sidecar are written.
    - ``skip_gages_file``: path to a file of already-completed gage ids
      (one per line) to exclude from this run before it starts.
    """
    if isinstance(options.get("start"), str) or isinstance(options.get("end"), str):
        raise TypeError(
            "run_backfill() received a raw string for options['start'] or "
            "options['end']. Both must be pre-parsed into a timezone-aware "
            "datetime (or None) by the calling command before it calls "
            "run_backfill - see backfill_usgs_observations.handle(), which "
            "parses --start/--end with _parse_date() and stashes the "
            "parsed datetimes back into options before delegating here."
        )

    skip = load_skip_file(options.get("skip_gages_file"))
    if skip:
        gages = [g for g in gages if g not in skip]
        command.stdout.write(f"Skipping {len(skip)} already-completed gages")

    start = options.get("start")
    end = options.get("end")
    dry_run = options.get("dry_run")
    sleep_seconds = options.get("sleep")
    report_path = options.get("report")

    processor = DataProcessor()
    rows = []

    command.stdout.write(
        f"Backfilling {len(gages)} gages "
        f"({'dry run' if dry_run else 'writing'})"
    )

    done_handle = None
    if report_path and not dry_run:
        done_path = Path(f"{report_path}.done.txt")
        done_path.parent.mkdir(parents=True, exist_ok=True)
        done_handle = done_path.open("a")

    try:
        for index, gage in enumerate(gages, start=1):
            try:
                station = Station.objects.filter(
                    station_number=gage, agency=agency
                ).first()
                if station is None:
                    command.stdout.write(
                        command.style.WARNING(
                            f"[{index}/{len(gages)}] {gage}: not in "
                            f"stations table, skipped"
                        )
                    )
                    rows.append({"station_number": gage, "status": "not_in_db"})
                    continue

                # Both the "before" and "after" reads, and the upsert
                # itself, sit inside this try: a dropped DB connection
                # (OperationalError/InterfaceError) mid-run is caught
                # below, where the connection is explicitly reset so the
                # *next* gage reconnects instead of also failing.
                before = _max_discharge(station)
                observations = fetch(gage, start, end)

                written = 0
                if observations and not dry_run:
                    written = processor.process_observations(
                        station_number=gage, observations=observations
                    )

                after = _max_discharge(station)

                if dry_run:
                    status = "dry_run"
                elif not observations:
                    status = "no_data"
                else:
                    status = "ok"

                rows.append(
                    {
                        "station_number": gage,
                        "status": status,
                        "fetched": len(observations),
                        "written": written,
                        "db_max_before": before,
                        "db_max_after": after,
                    }
                )
                command.stdout.write(
                    f"[{index}/{len(gages)}] {gage}: fetched "
                    f"{len(observations)}, wrote {written}, max "
                    f"{before} -> {after}"
                )

                if status == "ok" and done_handle:
                    done_handle.write(f"{gage}\n")
                    done_handle.flush()

            except Exception as exc:  # noqa: BLE001 - one bad gage must never abort the run
                # Reset a possibly-dead connection so the next gage can
                # reconnect. Django only reconnects when connection is
                # None, so without this one dropped connection would
                # fail every remaining gage with InterfaceError. Safe
                # unconditionally: for a non-DB failure this just costs
                # one lazy reconnect, and process_observations' own
                # transaction.atomic() has already unwound by the time
                # we get here, so no atomic block is active.
                connection.close()
                command.stdout.write(
                    command.style.ERROR(
                        f"[{index}/{len(gages)}] {gage}: failed: {exc}"
                    )
                )
                rows.append({"station_number": gage, "status": f"failed: {exc}"})
            finally:
                # Pacing applies on every path - success, not-in-db, and
                # failure alike - so a run of failures doesn't hammer a
                # struggling upstream back-to-back.
                if sleep_seconds and index < len(gages):
                    time.sleep(sleep_seconds)
    finally:
        # Always write what we have, even on exception or Ctrl-C, so a
        # multi-hour run against production never loses its resume state.
        if report_path:
            _write_report(command, report_path, rows)
        if done_handle:
            done_handle.close()

    failed = [r for r in rows if str(r.get("status", "")).startswith("failed")]
    command.stdout.write(
        command.style.SUCCESS(
            f"Done. {len(rows)} gages processed, {len(failed)} failed."
        )
    )

    return rows


def _max_discharge(station):
    return DischargeObservation.objects.filter(
        station=station, type="daily_mean"
    ).aggregate(m=Max("discharge"))["m"]


def _write_report(command, path, rows):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_REPORT_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in _REPORT_FIELDS})
    command.stdout.write(f"Report written to {target}")
