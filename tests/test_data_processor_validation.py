"""Validation must keep real flood peaks.

Streamflow is heavy-tailed: the largest days of any long record sit far beyond
mean + 5 sigma and are real, approved USGS values. A batch z-score filter
removed them at 271 of 285 audited gages, including the whole November 2021
Skagit crest. These tests pin that high-z values survive while genuinely
invalid records are still rejected.

**Fixture sizing matters, and it is subtle.** With a batch of n values where
one is an outlier and the rest are equal, the largest attainable |z| using the
population standard deviation is exactly sqrt(n - 1). So a 26-value batch caps
at |z| = 5.0, which a strict `> 5` test never trips — a 26-value fixture
CANNOT distinguish the fixed code from the broken code. The fixtures below use
a 300-day baseflow record so the crest days reach |z| of 5.0 to 9.6, which is
what the real 31,453-day Skagit record looks like: its true mean + 5 sigma is
63,441 cfs, and this fixture's is ~65,410 cfs.
"""

from datetime import datetime, timedelta, timezone

from src.acquisition.data_processor import DataProcessor

START = datetime(2021, 1, 1, tzinfo=timezone.utc)

# The real USGS daily means for 12200500 that are missing from production.
SKAGIT_CREST = [65200.0, 94100.0, 119000.0, 96200.0, 77900.0, 65500.0]

# 300 days of plausible baseflow, 3,000-8,850 cfs.
BASEFLOW = [3000.0 + (i % 40) * 150 for i in range(300)]


def _obs(value, day_offset):
    return {
        "observed_at": START + timedelta(days=day_offset),
        "discharge": value,
        "unit": "cfs",
        "type": "daily_mean",
        "quality_code": "A",
    }


def _batch(values):
    return [_obs(v, i) for i, v in enumerate(values)]


def _z_scores(values):
    mean = sum(values) / len(values)
    std_dev = (sum((x - mean) ** 2 for x in values) / len(values)) ** 0.5
    return [abs((v - mean) / std_dev) for v in values]


def test_fixture_is_actually_discriminating():
    # Guard the guard: if someone shrinks these fixtures, the peak tests below
    # would silently pass against the broken code too. This asserts the crest
    # really does exceed the old |z| > 5 cutoff.
    values = BASEFLOW + SKAGIT_CREST
    crest_z = _z_scores(values)[len(BASEFLOW):]

    assert max(crest_z) > 5.0
    assert sum(1 for z in crest_z if z > 5.0) >= 4, (
        f"expected several crest days above the old cutoff, got {crest_z}"
    )


def test_extreme_flood_peak_is_retained():
    # One 119,000 cfs crest against a long baseflow record: z is far above 5.
    values = BASEFLOW + [119000.0]

    valid = DataProcessor().validate_observations(_batch(values))

    assert len(valid) == len(values)
    assert 119000.0 in [float(o["discharge"]) for o in valid]


def test_skagit_november_2021_crest_survives_validation():
    # The exact days the 5-sigma filter removed from 12200500. The old code
    # dropped five of these six.
    values = BASEFLOW + SKAGIT_CREST

    valid = DataProcessor().validate_observations(_batch(values))

    kept = [float(o["discharge"]) for o in valid]
    assert len(valid) == len(values)
    for value in SKAGIT_CREST:
        assert value in kept, f"{value} cfs was dropped"


def test_high_z_value_is_logged_not_dropped(caplog):
    values = BASEFLOW + SKAGIT_CREST

    with caplog.at_level("INFO"):
        valid = DataProcessor().validate_observations(_batch(values))

    assert len(valid) == len(values)
    assert any("High-z discharge retained" in r.message for r in caplog.records)


def test_negative_discharge_still_rejected():
    valid = DataProcessor().validate_observations([_obs(-5.0, 0)])
    assert valid == []


def test_absurdly_high_discharge_still_rejected():
    valid = DataProcessor().validate_observations([_obs(2_000_000.0, 0)])
    assert valid == []


def test_none_discharge_still_rejected():
    valid = DataProcessor().validate_observations([_obs(None, 0)])
    assert valid == []


def test_missing_required_field_still_rejected():
    valid = DataProcessor().validate_observations([{"discharge": 100.0}])
    assert valid == []


def test_mixed_batch_keeps_peaks_and_rejects_invalid():
    # A realistic pull: valid baseflow, a real crest, and two bad records.
    observations = _batch(BASEFLOW + SKAGIT_CREST)
    observations.append(_obs(-1.0, 999))
    observations.append(_obs(5_000_000.0, 1000))

    valid = DataProcessor().validate_observations(observations)

    kept = [float(o["discharge"]) for o in valid]
    assert len(valid) == len(BASEFLOW) + len(SKAGIT_CREST)
    assert 119000.0 in kept
    assert -1.0 not in kept
    assert 5_000_000.0 not in kept
