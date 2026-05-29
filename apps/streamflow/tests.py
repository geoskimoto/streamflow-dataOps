from django.test import TestCase
from apps.streamflow.models import BasinForcing, Station


class BasinForcingModelTest(TestCase):
    def test_basin_forcing_has_required_fields(self):
        station = Station.objects.create(
            station_number="14178000", name="Test", agency="USGS"
        )
        forcing = BasinForcing.objects.create(
            station=station,
            date="2026-05-29",
            prcp_mm_day=3.2,
            tmax_c=22.5,
            tmin_c=8.1,
            srad_w_m2=280.0,
            vp_pa=1100.0,
            dayl_s=50000.0,
            source="nwm",
        )
        self.assertEqual(forcing.station_id, station.id)
        self.assertEqual(forcing.source, "nwm")

    def test_unique_constraint_station_date(self):
        from django.db import IntegrityError
        station = Station.objects.create(
            station_number="14178001", name="Test2", agency="USGS"
        )
        BasinForcing.objects.create(station=station, date="2026-05-29",
            prcp_mm_day=1.0, tmax_c=20.0, tmin_c=5.0,
            srad_w_m2=200.0, vp_pa=900.0, dayl_s=43200.0, source="nwm")
        with self.assertRaises(IntegrityError):
            BasinForcing.objects.create(station=station, date="2026-05-29",
                prcp_mm_day=2.0, tmax_c=21.0, tmin_c=6.0,
                srad_w_m2=210.0, vp_pa=950.0, dayl_s=43200.0, source="nwm")
