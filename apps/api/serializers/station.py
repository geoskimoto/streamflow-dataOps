"""Serializers for Station model."""

from rest_framework import serializers
from apps.streamflow.models import Station, MasterStation


class LastObservationDateMixin:
    """Mixin providing safe last_observation_date access via related metadata."""

    def get_last_observation_date(self, obj):
        metadata = getattr(obj, 'metadata', None)
        if metadata is None or metadata.last_observation_date is None:
            return None
        return metadata.last_observation_date.isoformat()


class StationSerializer(LastObservationDateMixin, serializers.ModelSerializer):
    """Serializer for Station model."""

    last_observation_date = serializers.SerializerMethodField()

    class Meta:
        model = Station
        fields = [
            'id',
            'station_number',
            'name',
            'agency',
            'latitude',
            'longitude',
            'timezone',
            'huc_code',
            'basin',
            'state',
            'catchment_area',
            'years_of_record',
            'record_start_date',
            'record_end_date',
            'is_active',
            'last_updated',
            'last_observation_date',
        ]
        read_only_fields = ['id', 'last_updated']


class StationListSerializer(LastObservationDateMixin, serializers.ModelSerializer):
    """Lightweight serializer for station lists."""

    last_observation_date = serializers.SerializerMethodField()

    class Meta:
        model = Station
        fields = [
            'id',
            'station_number',
            'name',
            'agency',
            'latitude',
            'longitude',
            'is_active',
            'last_observation_date',
        ]
        read_only_fields = ['id']


class StationCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating stations."""

    class Meta:
        model = Station
        fields = [
            'station_number',
            'name',
            'agency',
            'latitude',
            'longitude',
            'timezone',
            'huc_code',
            'basin',
            'state',
            'catchment_area',
            'years_of_record',
            'record_start_date',
            'record_end_date',
            'is_active',
        ]

    def validate_station_number(self, value):
        """Validate station number uniqueness."""
        if Station.objects.filter(station_number=value).exists():
            raise serializers.ValidationError(
                f"Station {value} already exists."
            )
        return value

    def validate_latitude(self, value):
        """Validate latitude range."""
        if value and (value < -90 or value > 90):
            raise serializers.ValidationError(
                "Latitude must be between -90 and 90."
            )
        return value

    def validate_longitude(self, value):
        """Validate longitude range."""
        if value and (value < -180 or value > 180):
            raise serializers.ValidationError(
                "Longitude must be between -180 and 180."
            )
        return value


class MasterStationSerializer(serializers.ModelSerializer):
    """Serializer for MasterStation cross-reference lookups."""

    class Meta:
        model = MasterStation
        fields = [
            'station_number',
            'noaa_lid',
            'rfc_code',
            'station_name',
            'agency',
            'state_code',
            'huc_code',
            'latitude',
            'longitude',
            'altitude_ft',
            'drainage_area_sqmi',
        ]
