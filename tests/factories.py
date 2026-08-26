"""Shared object factories for tests."""

from datetime import timedelta

from django.utils import timezone

from apps.streamflow.models import PullConfiguration, PullConfigurationStation


def make_pull_config(data_source, station_count, data_type="daily_mean", name=None):
    """Create an enabled PullConfiguration with `station_count` stations."""
    config = PullConfiguration.objects.create(
        name=name or f"{data_source} test config",
        data_source=data_source,
        data_type=data_type,
        is_enabled=True,
        pull_start_date=timezone.now() - timedelta(days=2),
    )
    for i in range(station_count):
        PullConfigurationStation.objects.create(
            configuration=config, station_number=f"1200{i:04d}"
        )
    return config
