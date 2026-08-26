"""Tests for per-source request pacing in station pulls.

USGS NWIS throttles bursts: 8 unpaced parallel workers against 2890 stations
produced empty response bodies (JSON decode errors) and truncated gzip payloads
on roughly 1% of stations per run. Pacing is per-source because each upstream
has a different tolerance.
"""

from src.acquisition.tasks import STATION_WORKERS, get_pull_pacing


def test_usgs_is_paced_below_the_default_worker_count():
    pacing = get_pull_pacing("USGS")

    assert pacing.workers < STATION_WORKERS
    assert pacing.delay_seconds > 0


def test_nwrfc_web_stays_sequential_with_its_existing_delay():
    """Preserves the rate-limit fix from 54db0bd."""
    pacing = get_pull_pacing("nwrfc_web")

    assert pacing.workers == 1
    assert pacing.delay_seconds == 1.5


def test_unknown_source_falls_back_to_the_default_unpaced_behavior():
    pacing = get_pull_pacing("EC")

    assert pacing.workers == STATION_WORKERS
    assert pacing.delay_seconds == 0


def test_usgs_request_rate_stays_under_four_per_second():
    """2890 stations must not be fired faster than USGS tolerates."""
    pacing = get_pull_pacing("USGS")

    requests_per_second = pacing.workers / pacing.delay_seconds

    assert requests_per_second <= 4
