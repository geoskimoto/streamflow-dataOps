"""Django admin configuration for the analytics app."""

from django.contrib import admin

from apps.analytics.models import (
    ComputationLog,
    FloodThreshold,
    ScheduledComputation,
    StatisticsComputationLog,
    StatisticsConfiguration,
    StatisticsConfigurationStation,
    StationMetadata,
)


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


@admin.register(StationMetadata)
class StationMetadataAdmin(admin.ModelAdmin):
    list_display    = ["station", "last_observation_date", "years_on_record", "mean_annual_flow_cfs", "computed_at"]
    search_fields   = ["station__station_number", "station__name"]
    ordering        = ["station__station_number"]
    readonly_fields = [
        "station", "last_observation_date", "record_start_date", "record_end_date",
        "years_on_record", "daily_observation_count", "record_completeness_pct",
        "mean_annual_flow_cfs", "q10_cfs", "q25_cfs", "q50_cfs", "q75_cfs", "q90_cfs",
        "computed_at",
    ]


@admin.register(FloodThreshold)
class FloodThresholdAdmin(admin.ModelAdmin):
    list_display    = ["station", "noaa_lid", "action_stage_ft", "minor_stage_ft", "major_stage_ft", "source", "last_updated"]
    search_fields   = ["station__station_number", "noaa_lid"]
    list_filter     = ["source"]
    readonly_fields = ["last_updated"]


@admin.register(StatisticsConfiguration)
class StatisticsConfigurationAdmin(admin.ModelAdmin):
    list_display    = ["name", "computation_type", "agency_filter", "schedule_type", "is_enabled", "last_run_at", "next_run_at"]
    list_filter     = ["computation_type", "agency_filter", "schedule_type", "is_enabled"]
    search_fields   = ["name"]
    readonly_fields = ["last_run_at", "next_run_at", "created_at", "updated_at"]


@admin.register(StatisticsConfigurationStation)
class StatisticsConfigurationStationAdmin(admin.ModelAdmin):
    list_display    = ["configuration", "station"]
    search_fields   = ["configuration__name", "station__station_number"]


@admin.register(StatisticsComputationLog)
class StatisticsComputationLogAdmin(admin.ModelAdmin):
    list_display    = ["configuration", "status", "stations_processed", "duration_seconds", "started_at"]
    list_filter     = ["status", "configuration"]
    search_fields   = ["configuration__name", "celery_task_id"]
    ordering        = ["-started_at"]
    readonly_fields = [
        "configuration", "status", "celery_task_id", "started_at",
        "completed_at", "duration_seconds", "stations_processed", "records_computed", "error_message",
    ]
