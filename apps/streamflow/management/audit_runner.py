"""Shared, agency-agnostic per-gage observation audit runner.

Extracted from ``audit_usgs_observations`` so a second agency's command
(Environment Canada) can reuse the same comparison and reporting machinery
without duplicating ~230 lines that survived two review rounds. Mirrors
``backfill_runner.py``'s relationship to the two backfill commands.

Every property the USGS audit's review established is preserved exactly,
regardless of which agency calls in:

- Tolerance is ``max(ABS_TOLERANCE, REL_TOLERANCE * source_value)``, applied
  against the **source** (API) value, never the stored one.
- The comparison is bounded **below** by the station's first stored date and
  deliberately **not** bounded above. A two-sided bound would define
  "complete" as "everything up to whatever we already have", so a repair
  that wrote nothing recent would score zero missing - exactly the failure
  mode this command exists to catch. ``n_missing_in_db_span`` (gaps strictly
  between the first and last stored date) is kept separate from
  ``n_missing_after_db_last`` (tail staleness after the last stored date) so
  the two are never silently summed into a misleadingly large or small
  total; ``n_missing`` is their sum by construction.
- Five statuses, each with its own per-gage stdout line so an operator can
  triage from the log alone: ``ok``, ``failed``, ``no_db_data``,
  ``no_api_data``, ``not_in_db``.
- ``n_db_rows`` (raw row count) is reported alongside ``n_db`` (distinct-
  date count); when they differ a WARNING names the excess, since keying on
  date alone is blind to duplicate rows stored at a non-midnight timestamp.
- Success styling requires at least one row, every gage "ok", AND zero
  discrepancies - status "ok" only means the comparison ran, not that it
  found nothing wrong.
- A not-all-clear run raises ``CommandError`` **after** the report is
  written inside the ``finally``, so a wrapper script can gate on the exit
  code and still read the report.
- Per-gage fault isolation with a ``connection.close()`` reset so one dead
  connection doesn't poison every remaining gage, and inter-gage pacing that
  fires on every path - success, skip, and failure alike.

``fetch(station_number)`` is the one agency-specific seam - it must return
the full record (every observation the source has for that station); the
lower-bound-only comparison relies on seeing API dates before the DB's
earliest row so it can correctly exclude them. ``unit`` scopes the DB read
(``cfs`` for USGS, ``cms`` for EC) so a differently-unit'd row is never
compared against the API's native unit. ``id_field`` is the column name used
for the gage/station id in both the per-row dict and the CSV report (the
USGS command uses ``usgs_id`` for its pinned test file; a new caller is free
to choose its own). ``api_label`` is the human-readable source name used in
the "no data" stdout line (e.g. ``"USGS API"`` / ``"EC API"``).
"""

import csv
import time
from pathlib import Path

from django.core.management.base import CommandError
from django.db import connection

from apps.streamflow.models import DischargeObservation, Station

# A value counts as different if it is off by more than ABS_TOLERANCE *and*
# REL_TOLERANCE of the source value - this floor/ratio pair is unit-agnostic
# by design; it was established against USGS cfs values and is preserved
# verbatim rather than rescaled per unit.
ABS_TOLERANCE = 0.5
REL_TOLERANCE = 0.005

_REPORT_FIELDS_TAIL = [
    "status",
    "n_db",
    "n_db_rows",
    "n_api_in_span",
    "n_missing",
    "n_missing_in_db_span",
    "n_missing_after_db_last",
    "n_value_diff",
    "db_max",
    "api_max",
    "first_missing",
]


def run_audit(
    *, command, gages, fetch, agency, unit, id_field, api_label, options
) -> list:
    """Run a per-gage audit loop, write the report, and return the rows.

    ``command`` is used only for ``command.stdout.write(...)`` and
    ``command.style``, so callers keep their existing CLI output.
    ``fetch(station_number)`` is the agency-specific data source call and
    must return the agency's full record for that station (the calling
    command's closure supplies whatever start/end the client needs - e.g.
    EC's client requires a non-``None`` start, so the EC command's closure
    passes a fixed earliest-possible date).

    ``options`` is the command's parsed options dict, read with ``.get()``:

    - ``sleep``: seconds to pace between gages. A missing key or an
      explicit ``None`` silently disables pacing.
    - ``report``: path for the per-gage CSV report. ``None``/falsy means no
      report is written.

    Raises:
        CommandError: if the run is not all-clear (see module docstring).
            Raised after the report is written.
    """
    rows = []
    total_missing_in_span = total_missing_after_last = total_diff = 0
    sleep_seconds = options.get("sleep")
    report_path = options.get("report")

    try:
        for index, gage in enumerate(gages, start=1):
            try:
                station = Station.objects.filter(
                    station_number=gage, agency=agency
                ).first()
                if station is None:
                    command.stdout.write(
                        command.style.WARNING(
                            f"[{index}/{len(gages)}] {gage}: not in stations table"
                        )
                    )
                    rows.append({id_field: gage, "status": "not_in_db"})
                    continue

                api_rows = fetch(gage)

                api_by_date = {
                    o["observed_at"].date(): float(o["discharge"])
                    for o in api_rows
                }
                # Only rows in the agency's native unit are comparable to
                # the API; a differently-unit'd daily_mean row would
                # otherwise be flagged as a spurious value difference.
                db_rows = list(
                    DischargeObservation.objects.filter(
                        station=station, type="daily_mean", unit=unit
                    ).values_list("observed_at", "discharge")
                )
                db_by_date = {
                    observed_at.date(): float(discharge)
                    for observed_at, discharge in db_rows
                }
                # Keying on date collapses duplicates, so the distinct-date
                # count alone is blind to a duplicate row stored at a
                # non-midnight time - exactly the corruption the
                # midnight-UTC invariant exists to prevent. Report the raw
                # row count alongside it. This does not fail the gage; it
                # is a separate class of problem from missing/stale days.
                n_db_rows = len(db_rows)
                if n_db_rows > len(db_by_date):
                    command.stdout.write(
                        command.style.WARNING(
                            f"[{index}/{len(gages)}] {gage}: "
                            f"{n_db_rows - len(db_by_date)} duplicate "
                            f"daily_mean row(s) beyond "
                            f"{len(db_by_date)} distinct dates - "
                            f"non-midnight timestamps suspected"
                        )
                    )

                if not db_by_date:
                    command.stdout.write(
                        command.style.WARNING(
                            f"[{index}/{len(gages)}] {gage}: no stored "
                            f"{unit} daily-mean observations"
                        )
                    )
                    rows.append({id_field: gage, "status": "no_db_data"})
                    continue
                if not api_by_date:
                    command.stdout.write(
                        command.style.WARNING(
                            f"[{index}/{len(gages)}] {gage}: {api_label} "
                            f"returned no data"
                        )
                    )
                    rows.append({id_field: gage, "status": "no_api_data"})
                    continue

                # Only judge from the earliest date the DB actually covers -
                # otherwise every day before the first stored row reads as
                # "missing". Deliberately unbounded on the upper end for the
                # total: a two-sided bound would define "complete" as
                # "everything up to whatever we already have", hiding a
                # backfill that wrote nothing recent. The split below keeps
                # that tail staleness visible without conflating it with
                # the in-span gaps.
                lo, hi = min(db_by_date), max(db_by_date)
                in_span = {d: v for d, v in api_by_date.items() if d >= lo}

                missing_in_db_span = sorted(
                    d for d in in_span if d <= hi and d not in db_by_date
                )
                missing_after_db_last = sorted(d for d in in_span if d > hi)
                missing = missing_in_db_span + missing_after_db_last

                diffs = [
                    d
                    for d, api_value in in_span.items()
                    if d in db_by_date
                    and abs(api_value - db_by_date[d])
                    > max(ABS_TOLERANCE, REL_TOLERANCE * api_value)
                ]

                total_missing_in_span += len(missing_in_db_span)
                total_missing_after_last += len(missing_after_db_last)
                total_diff += len(diffs)

                record = {
                    id_field: gage,
                    "status": "ok",
                    "n_db": len(db_by_date),
                    "n_db_rows": n_db_rows,
                    "n_api_in_span": len(in_span),
                    "n_missing": len(missing),
                    "n_missing_in_db_span": len(missing_in_db_span),
                    "n_missing_after_db_last": len(missing_after_db_last),
                    "n_value_diff": len(diffs),
                    "db_max": max(db_by_date.values()),
                    "api_max": max(api_by_date.values()),
                    "first_missing": missing[0].isoformat() if missing else "",
                }
                rows.append(record)
                command.stdout.write(
                    f"[{index}/{len(gages)}] {gage}: missing={len(missing)} "
                    f"(in_span={len(missing_in_db_span)} "
                    f"after_last={len(missing_after_db_last)}) "
                    f"diff={len(diffs)} db_max={record['db_max']:.0f} "
                    f"api_max={record['api_max']:.0f}"
                )

            except Exception as exc:  # noqa: BLE001 - one bad gage must never abort the run
                # Reset a possibly-dead connection so the next gage can
                # reconnect. Django only reconnects when connection is None,
                # so without this one dropped connection would fail every
                # remaining gage with InterfaceError.
                connection.close()
                command.stdout.write(
                    command.style.ERROR(f"[{index}/{len(gages)}] {gage}: failed: {exc}")
                )
                rows.append({id_field: gage, "status": f"failed: {exc}"})
            finally:
                # Pacing applies on every path - success, not-in-db, and
                # failure alike - so a run of failures doesn't hammer a
                # struggling upstream back-to-back.
                if sleep_seconds and index < len(gages):
                    time.sleep(sleep_seconds)
    finally:
        # Always write what we have, even on exception or Ctrl-C, so a
        # long audit against production never loses its progress.
        if report_path:
            _write_report(command, report_path, rows, id_field)

    counts = status_counts(rows)
    # "All clear" means every gage compared cleanly AND nothing was actually
    # wrong. Status "ok" only means the comparison ran: a gage with 5,000
    # missing days and 3,000 value differences is still "ok", so counting
    # statuses alone would print a green SUCCESS summary over a completely
    # failed restoration.
    all_ok = (
        len(rows) > 0
        and counts["ok"] == len(rows)
        and total_missing_in_span == 0
        and total_diff == 0
    )
    summary = (
        f"Audited {len(rows)} gages: {counts['ok']} ok, "
        f"{counts['failed']} failed, {counts['no_db_data']} no_db_data, "
        f"{counts['no_api_data']} no_api_data, "
        f"{counts['not_in_db']} not_in_db ("
        f"{total_missing_in_span} missing_in_db_span, "
        f"{total_missing_after_last} missing_after_db_last, "
        f"{total_diff} value differences — totals cover 'ok' gages only)."
    )
    style = command.style.SUCCESS if all_ok else command.style.WARNING
    command.stdout.write(style(summary))

    if not all_ok:
        # Exit nonzero so a wrapper script can gate on the audit instead of
        # grepping stdout. The report (written in the finally above) is
        # already on disk by the time this raises.
        raise CommandError(f"Audit not all-clear. {summary}")

    return rows


def status_counts(rows):
    """Tally outcomes so the summary can never read as clean success when
    some gages failed, were skipped, or had no data - a dynamic
    "failed: {exc}" status string is matched by prefix, mirroring
    ``backfill_runner``'s own failed-count logic."""
    counts = {
        "ok": 0,
        "failed": 0,
        "no_db_data": 0,
        "no_api_data": 0,
        "not_in_db": 0,
    }
    for row in rows:
        status = str(row.get("status", ""))
        if status.startswith("failed"):
            counts["failed"] += 1
        elif status in counts:
            counts[status] += 1
    return counts


def _write_report(command, path, rows, id_field):
    fields = [id_field] + _REPORT_FIELDS_TAIL
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fields})
    command.stdout.write(f"Report written to {target}")
