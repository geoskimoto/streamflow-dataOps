"""Serializers for observation models."""

from rest_framework import serializers
from apps.streamflow.models import DischargeObservation


class DischargeObservationSerializer(serializers.ModelSerializer):
    """Serializer for discharge observations."""

    station_number = serializers.CharField(source='station.station_number', read_only=True)

    class Meta:
        model = DischargeObservation
        fields = [
            'id',
            'station',
            'station_number',
            'observed_at',
            'discharge',
            'unit',
            'type',
            'quality_code',
        ]
        read_only_fields = ['id', 'station_number']


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


class DailyFlowPercentileSerializer(serializers.Serializer):
    """Single station result within a percentile-bands response."""

    station_number          = serializers.CharField()
    discharge               = serializers.FloatField()
    percentile_rank         = serializers.FloatField()
    band                    = serializers.CharField()
    historical_record_count = serializers.IntegerField()


class PercentileBandsResponseSerializer(serializers.Serializer):
    """Top-level envelope for GET /observations/discharge/percentile-bands/."""

    date        = serializers.DateField()
    computed_at = serializers.DateTimeField(allow_null=True)
    count       = serializers.IntegerField()
    results     = DailyFlowPercentileSerializer(many=True)


class PercentileDateRangeSerializer(serializers.Serializer):
    """Date range available in daily_flow_percentiles, for rangeslider bounds."""

    min_date = serializers.DateField(allow_null=True)
    max_date = serializers.DateField(allow_null=True)
