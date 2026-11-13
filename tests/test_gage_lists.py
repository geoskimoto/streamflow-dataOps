"""Tests for shared gage-list resolution used by the backfill and audit commands."""

import pytest
from django.core.management.base import CommandError

from apps.streamflow.management.gage_lists import load_skip_file, resolve_gages
from apps.streamflow.models import Station


def test_comma_separated_gages():
    assert resolve_gages({"gages": "12200500,13317000"}) == ["12200500", "13317000"]


def test_whitespace_and_blanks_are_stripped():
    assert resolve_gages({"gages": " 12200500 , ,13317000 "}) == [
        "12200500",
        "13317000",
    ]


def test_csv_with_usgs_id_column(tmp_path):
    csv_path = tmp_path / "gages.csv"
    csv_path.write_text("usgs_id,nwsli\n12200500,MVEW1\n13317000,WHBI1\n")

    assert resolve_gages({"gage_list_csv": str(csv_path)}) == [
        "12200500",
        "13317000",
    ]


def test_csv_duplicates_are_collapsed_preserving_order(tmp_path):
    csv_path = tmp_path / "gages.csv"
    csv_path.write_text("usgs_id\n12200500\n13317000\n12200500\n")

    assert resolve_gages({"gage_list_csv": str(csv_path)}) == [
        "12200500",
        "13317000",
    ]


def test_csv_missing_usgs_id_column_raises(tmp_path):
    csv_path = tmp_path / "bad.csv"
    csv_path.write_text("site_no\n12200500\n")

    with pytest.raises(CommandError, match="usgs_id"):
        resolve_gages({"gage_list_csv": str(csv_path)})


def test_missing_csv_raises():
    with pytest.raises(CommandError, match="No such CSV"):
        resolve_gages({"gage_list_csv": "/nonexistent/path.csv"})


def test_all_usgs_reads_stations(db):
    Station.objects.create(station_number="13317000", name="B", agency="USGS")
    Station.objects.create(station_number="12200500", name="A", agency="USGS")
    Station.objects.create(station_number="08NL071", name="C", agency="EC")

    assert resolve_gages({"all_usgs": True}) == ["12200500", "13317000"]


def test_no_selection_raises():
    with pytest.raises(CommandError, match="--gages"):
        resolve_gages({})


def test_load_skip_file_returns_set(tmp_path):
    skip = tmp_path / "done.txt"
    skip.write_text("12200500\n13317000\n\n")

    assert load_skip_file(str(skip)) == {"12200500", "13317000"}


def test_load_skip_file_none_returns_empty_set():
    assert load_skip_file(None) == set()


def test_load_skip_file_missing_raises():
    with pytest.raises(CommandError, match="No such skip file"):
        load_skip_file("/nonexistent/skip.txt")


def test_csv_with_station_number_column_only(tmp_path):
    csv_path = tmp_path / "gages.csv"
    csv_path.write_text("station_number,name\n08LE031,A\n08LD001,B\n")

    assert resolve_gages({"gage_list_csv": str(csv_path)}) == [
        "08LE031",
        "08LD001",
    ]


def test_csv_with_usgs_id_column_only(tmp_path):
    csv_path = tmp_path / "gages.csv"
    csv_path.write_text("usgs_id,nwsli\n12200500,MVEW1\n13317000,WHBI1\n")

    assert resolve_gages({"gage_list_csv": str(csv_path)}) == [
        "12200500",
        "13317000",
    ]


def test_csv_with_both_columns_prefers_station_number(tmp_path):
    csv_path = tmp_path / "gages.csv"
    csv_path.write_text(
        "station_number,usgs_id\n08LE031,12200500\n08LD001,13317000\n"
    )

    assert resolve_gages({"gage_list_csv": str(csv_path)}) == [
        "08LE031",
        "08LD001",
    ]


def test_csv_with_neither_column_raises(tmp_path):
    csv_path = tmp_path / "bad.csv"
    csv_path.write_text("site_no\n12200500\n")

    with pytest.raises(CommandError, match="usgs_id.*station_number"):
        resolve_gages({"gage_list_csv": str(csv_path)})


def test_all_stations_respects_agency(db):
    Station.objects.create(station_number="13317000", name="U", agency="USGS")
    Station.objects.create(station_number="08LE031", name="E", agency="EC")

    assert resolve_gages({"all_usgs": True}) == ["13317000"]
    assert resolve_gages({"all_ec": True}) == ["08LE031"]
