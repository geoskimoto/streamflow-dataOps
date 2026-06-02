"""Tests for NWMIngestionLog model."""
import pytest
from datetime import date


@pytest.mark.django_db
def test_nwm_ingestion_log_create(db):
    from apps.nwm_forcings.models import NWMIngestionLog

    log = NWMIngestionLog.objects.create(
        ingest_date=date(2026, 1, 15),
        stations_updated=37,
        status="success",
    )
    assert log.id is not None
    assert log.status == "success"
    assert log.stations_updated == 37
    assert log.error_message == ""


@pytest.mark.django_db
def test_nwm_ingestion_log_failed_status(db):
    from apps.nwm_forcings.models import NWMIngestionLog

    log = NWMIngestionLog.objects.create(
        ingest_date=date(2026, 1, 15),
        stations_updated=0,
        status="failed",
        error_message="NOMADS returned 503",
    )
    assert log.status == "failed"
    assert "503" in log.error_message


@pytest.mark.django_db
def test_nwm_ingestion_log_unique_date(db):
    from apps.nwm_forcings.models import NWMIngestionLog
    from django.db import IntegrityError

    NWMIngestionLog.objects.create(ingest_date=date(2026, 1, 15), status="success")
    with pytest.raises(IntegrityError):
        NWMIngestionLog.objects.create(ingest_date=date(2026, 1, 15), status="success")
