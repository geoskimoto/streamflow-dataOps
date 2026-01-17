"""Serializers for Station model."""

from rest_framework import serializers
from apps.streamflow.models import Station


class StationSerializer(serializers.ModelSerializer):
    """Serializer for Station model."""
    
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
        ]
        read_only_fields = ['id', 'last_updated']


class StationListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for station lists."""
    
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
