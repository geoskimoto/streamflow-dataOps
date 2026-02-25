"""Serializers for the analytics app."""

from rest_framework import serializers

from apps.analytics.models import ComputationLog, ScheduledComputation


class ComputationLogSerializer(serializers.ModelSerializer):
    """Full detail serializer for computation run logs."""

    class Meta:
        model = ComputationLog
        fields = [
            "id",
            "computation",
            "status",
            "celery_task_id",
            "started_at",
            "completed_at",
            "duration_seconds",
            "records_computed",
            "error_message",
        ]
        read_only_fields = fields


class ScheduledComputationListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list view."""

    class Meta:
        model = ScheduledComputation
        fields = [
            "id",
            "name",
            "schedule",
            "is_enabled",
            "last_run_at",
            "last_run_status",
        ]
        read_only_fields = fields


class ScheduledComputationSerializer(serializers.ModelSerializer):
    """Full detail serializer including recent logs."""

    recent_logs = serializers.SerializerMethodField()

    class Meta:
        model = ScheduledComputation
        fields = [
            "id",
            "name",
            "description",
            "task_path",
            "schedule",
            "is_enabled",
            "last_run_at",
            "last_run_status",
            "created_at",
            "updated_at",
            "recent_logs",
        ]
        read_only_fields = [
            "id", "task_path", "last_run_at", "last_run_status",
            "created_at", "updated_at", "recent_logs",
        ]

    def get_recent_logs(self, obj):
        logs = obj.logs.order_by("-started_at")[:10]
        return ComputationLogSerializer(logs, many=True).data
