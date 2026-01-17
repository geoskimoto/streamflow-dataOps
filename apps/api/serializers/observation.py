"""Serializers for observation models."""

from rest_framework import serializers
from apps.streamflow.models import DischargeObservation


class DischargeObservationSerializer(serializers.ModelSerializer):
    """Serializer for discharge observations."""
    
    class Meta:
        model = DischargeObservation
        fields = [
            'id',
            'station_number',
            'timestamp',
            'value',
            'unit',
            'data_type',
            'quality_code',
            'is_provisional',
            'data_source',
        ]
        read_only_fields = ['id']


class ObservationStatisticsSerializer(serializers.Serializer):
    """Serializer for observation statistics."""
    
    start_date = serializers.DateTimeField()
    end_date = serializers.DateTimeField()
    count = serializers.IntegerField()
    min_value = serializers.FloatField(allow_null=True)
    max_value = serializers.FloatField(allow_null=True)
    mean_value = serializers.FloatField(allow_null=True)
    latest_value = serializers.FloatField(allow_null=True)
    latest_timestamp = serializers.DateTimeField(allow_null=True)
