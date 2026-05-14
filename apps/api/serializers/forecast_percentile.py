"""Serializers for forecast percentile endpoints."""

from rest_framework import serializers


class ForecastPercentileResultSerializer(serializers.Serializer):
    """Single station result within a forecast percentile-bands response."""

    station_number          = serializers.CharField()
    forecast_discharge      = serializers.FloatField()
    percentile_rank         = serializers.FloatField()
    band                    = serializers.CharField()
    historical_record_count = serializers.IntegerField()


class ForecastPercentileBandsResponseSerializer(serializers.Serializer):
    """Top-level envelope for GET /forecasts/discharge/percentile-bands/."""

    date              = serializers.DateField()
    source            = serializers.CharField()
    forecast_run_date = serializers.DateTimeField(allow_null=True)
    computed_at       = serializers.DateTimeField(allow_null=True)
    count             = serializers.IntegerField()
    results           = ForecastPercentileResultSerializer(many=True)


class ForecastPercentileDateRangeSerializer(serializers.Serializer):
    """Date range of available forecast percentile bands, for dashboard rangeslider."""

    source            = serializers.CharField()
    min_date          = serializers.DateField(allow_null=True)
    max_date          = serializers.DateField(allow_null=True)
    forecast_run_date = serializers.DateTimeField(allow_null=True)
