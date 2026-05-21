"""Serializers for the analytics app."""

from rest_framework import serializers

from apps.analytics.models import StatisticsComputationLog, StatisticsConfiguration


class StatisticsComputationLogSerializer(serializers.ModelSerializer):
    """Full detail serializer for statistics computation run logs."""

    class Meta:
        model = StatisticsComputationLog
        fields = [
            "id",
            "configuration",
            "status",
            "celery_task_id",
            "started_at",
            "completed_at",
            "duration_seconds",
            "stations_processed",
            "records_computed",
            "error_message",
        ]
        read_only_fields = fields


class StatisticsConfigurationSerializer(serializers.ModelSerializer):
    """Full detail serializer for statistics configurations including recent logs."""

    recent_logs = serializers.SerializerMethodField()

    class Meta:
        model = StatisticsConfiguration
        fields = [
            "id",
            "name",
            "description",
            "computation_type",
            "agency_filter",
            "schedule_type",
            "is_enabled",
            "last_run_at",
            "next_run_at",
            "created_at",
            "updated_at",
            "recent_logs",
        ]
        read_only_fields = [
            "id", "last_run_at", "next_run_at", "created_at", "updated_at", "recent_logs",
        ]

    def get_recent_logs(self, obj):
        logs = obj.logs.order_by("-started_at")[:10]
        return StatisticsComputationLogSerializer(logs, many=True).data
