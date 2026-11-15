"""Retention for the realtime_15min rolling window.

realtime_15min is a rolling ~15-day reference window, not an archive. The
single most important property here is that pruning NEVER touches
daily_mean: those rows are decades old by definition, so an unscoped
age-based delete would wipe the entire 37.8M-row archive.
"""

from datetime import timedelta

import pytest
from django.conf import settings
from django.utils import timezone

from apps.streamflow.models import DischargeObservation, Station
from src.acquisition.monitoring_tasks import prune_realtime_observations


@pytest.fixture
def station(db):
    return Station.objects.create(
        station_number="12200500", name="Skagit", agency="USGS", is_active=True
    )


def _obs(station, days_ago, obs_type, value=100.0, unit="cfs"):
    return DischargeObservation.objects.create(
        station=station,
        observed_at=timezone.now() - timedelta(days=days_ago),
        discharge=value,
        unit=unit,
        type=obs_type,
        quality_code="A",
    )


def test_daily_mean_is_never_deleted_however_old(station):
    # THE critical invariant. These are decades old and must survive.
    _obs(station, 40 * 365, "daily_mean")
    _obs(station, 10 * 365, "daily_mean")
    _obs(station, 30, "daily_mean")

    prune_realtime_observations(retention_days=15)

    assert DischargeObservation.objects.filter(type="daily_mean").count() == 3


def test_old_realtime_rows_are_deleted(station):
    _obs(station, 20, "realtime_15min")
    _obs(station, 16, "realtime_15min")

    result = prune_realtime_observations(retention_days=15)

    assert DischargeObservation.objects.filter(type="realtime_15min").count() == 0
    assert result["deleted"] == 2


def test_recent_realtime_rows_are_kept(station):
    _obs(station, 14, "realtime_15min")
    _obs(station, 1, "realtime_15min")

    result = prune_realtime_observations(retention_days=15)

    assert DischargeObservation.objects.filter(type="realtime_15min").count() == 2
    assert result["deleted"] == 0


def test_mixed_table_only_loses_old_realtime(station):
    _obs(station, 40 * 365, "daily_mean")      # ancient archive
    _obs(station, 20, "realtime_15min")        # past the window
    _obs(station, 2, "realtime_15min")         # inside the window

    prune_realtime_observations(retention_days=15)

    assert DischargeObservation.objects.filter(type="daily_mean").count() == 1
    kept = DischargeObservation.objects.filter(type="realtime_15min")
    assert kept.count() == 1


def test_dry_run_deletes_nothing_but_reports_the_count(station):
    _obs(station, 20, "realtime_15min")
    _obs(station, 18, "realtime_15min")

    result = prune_realtime_observations(retention_days=15, dry_run=True)

    assert DischargeObservation.objects.filter(type="realtime_15min").count() == 2
    assert result["deleted"] == 2
    assert result["dry_run"] is True


def test_retention_days_defaults_to_the_setting(station):
    _obs(station, settings.REALTIME_RETENTION_DAYS + 5, "realtime_15min")
    _obs(station, 1, "realtime_15min")

    prune_realtime_observations()

    assert DischargeObservation.objects.filter(type="realtime_15min").count() == 1


def test_setting_default_is_15_days():
    assert settings.REALTIME_RETENTION_DAYS == 15


def test_absurd_retention_is_refused_rather_than_deleting_everything(station):
    # A zero or negative window would delete the whole rolling series, and a
    # bad config should fail loudly rather than quietly emptying a table.
    _obs(station, 1, "realtime_15min")

    with pytest.raises(ValueError):
        prune_realtime_observations(retention_days=0)
    with pytest.raises(ValueError):
        prune_realtime_observations(retention_days=-5)

    assert DischargeObservation.objects.filter(type="realtime_15min").count() == 1


def test_other_observation_types_are_untouched(station):
    _obs(station, 400, "ec_realtime_daily", unit="cms")

    prune_realtime_observations(retention_days=15)

    assert DischargeObservation.objects.filter(type="ec_realtime_daily").count() == 1


def test_returns_the_cutoff_and_window_for_the_log(station):
    result = prune_realtime_observations(retention_days=15)
    assert result["retention_days"] == 15
    assert result["cutoff"] is not None


def test_beat_entry_resolves_to_a_registered_task():
    """
    The beat schedule's 'task' string must match a name actually registered
    with the Celery app, or the job silently never fires (NotRegistered on
    the worker). Celery names a task after its defining __module__, not
    whatever module re-exports it, so pointing this entry at the
    src.acquisition.raster_tasks re-export (instead of
    src.acquisition.monitoring_tasks, where prune_realtime_observations is
    actually defined) would reproduce the same silent-breakage bug already
    found in three other beat entries. Forces app.loader.import_default_modules()
    because app.conf.include is lazy and a bare django.setup() never triggers it.
    """
    from config.celery import app

    app.loader.import_default_modules()
    task_name = app.conf.beat_schedule["prune-realtime-observations"]["task"]
    assert task_name in app.tasks

