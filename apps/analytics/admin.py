"""Django admin configuration for the analytics app."""

from django.contrib import admin

from apps.analytics.models import ComputationLog, ScheduledComputation


@admin.register(ScheduledComputation)
class ScheduledComputationAdmin(admin.ModelAdmin):
    list_display    = ["name", "schedule", "is_enabled", "last_run_status", "last_run_at"]
    list_filter     = ["is_enabled", "schedule", "last_run_status"]
    search_fields   = ["name", "task_path"]
    ordering        = ["name"]
    readonly_fields = ["task_path", "last_run_at", "last_run_status", "created_at", "updated_at"]


@admin.register(ComputationLog)
class ComputationLogAdmin(admin.ModelAdmin):
    list_display    = ["computation", "status", "records_computed", "duration_seconds", "started_at"]
    list_filter     = ["status", "computation"]
    search_fields   = ["computation__name", "celery_task_id"]
    ordering        = ["-started_at"]
    readonly_fields = [
        "computation", "status", "celery_task_id", "started_at",
        "completed_at", "duration_seconds", "records_computed", "error_message",
    ]
