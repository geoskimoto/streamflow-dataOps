"""Serializers for forecast models."""

from rest_framework import serializers
from apps.streamflow.models import ForecastRun


class ForecastRunSerializer(serializers.ModelSerializer):
    """Serializer for forecast runs."""
    
    station_number = serializers.CharField(source='station.station_number', read_only=True)
    station_name = serializers.CharField(source='station.name', read_only=True)
    forecast_point_count = serializers.SerializerMethodField()
    
    class Meta:
        model = ForecastRun
        fields = [
            'id',
            'station',
            'station_number',
            'station_name',
            'source',
            'run_date',
            'data',
            'rmse',
            'forecast_point_count',
        ]
        read_only_fields = ['id', 'station_number', 'station_name', 'forecast_point_count']
    
    def get_forecast_point_count(self, obj):
        """Return number of forecast points in the data array."""
        return len(obj.data) if obj.data else 0


class ForecastRunListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for forecast run lists (excludes full data)."""
    
    station_number = serializers.CharField(source='station.station_number', read_only=True)
    station_name = serializers.CharField(source='station.name', read_only=True)
    forecast_point_count = serializers.SerializerMethodField()
    
    class Meta:
        model = ForecastRun
        fields = [
            'id',
            'station_number',
            'station_name',
            'source',
            'run_date',
            'rmse',
            'forecast_point_count',
        ]
        read_only_fields = ['id', 'station_number', 'station_name', 'forecast_point_count']
    
    def get_forecast_point_count(self, obj):
        """Return number of forecast points in the data array."""
        return len(obj.data) if obj.data else 0


class ForecastStatisticsSerializer(serializers.Serializer):
    """Serializer for forecast statistics."""
    
    start_date = serializers.DateTimeField()
    end_date = serializers.DateTimeField()
    count = serializers.IntegerField()
    stations = serializers.IntegerField()
    total_forecast_points = serializers.IntegerField()
    avg_rmse = serializers.FloatField(allow_null=True)
