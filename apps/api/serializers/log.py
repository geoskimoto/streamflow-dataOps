"""Serializers for DataPullLog model."""

from rest_framework import serializers
from apps.streamflow.models import DataPullLog


class DataPullLogSerializer(serializers.ModelSerializer):
    """Serializer for data pull logs."""
    
    configuration_name = serializers.CharField(source='configuration.name', read_only=True)
    duration_seconds = serializers.SerializerMethodField()
    
    class Meta:
        model = DataPullLog
        fields = [
            'id',
            'configuration',
            'configuration_name',
            'status',
            'records_processed',
            'start_time',
            'end_time',
            'duration_seconds',
            'error_message',
        ]
        read_only_fields = ['id', 'configuration_name', 'duration_seconds']
    
    def get_duration_seconds(self, obj):
        """Calculate duration in seconds."""
        if obj.end_time and obj.start_time:
            delta = obj.end_time - obj.start_time
            return delta.total_seconds()
        return None


class DataPullLogListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for log lists."""
    
    configuration_name = serializers.CharField(source='configuration.name', read_only=True)
    
    class Meta:
        model = DataPullLog
        fields = [
            'id',
            'configuration',
            'configuration_name',
            'status',
            'records_processed',
            'start_time',
            'end_time',
        ]
        read_only_fields = ['id', 'configuration_name']
