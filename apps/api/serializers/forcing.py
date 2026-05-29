"""Serializer for BasinForcing model."""
from rest_framework import serializers
from apps.streamflow.models import BasinForcing


class BasinForcingSerializer(serializers.ModelSerializer):
    class Meta:
        model = BasinForcing
        fields = [
            "date",
            "prcp_mm_day",
            "tmax_c",
            "tmin_c",
            "srad_w_m2",
            "vp_pa",
            "dayl_s",
            "source",
        ]
