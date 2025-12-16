from django.contrib import admin
from .models import (
    Station,
    DischargeObservation,
    ForecastRun,
    PullConfiguration,
    PullConfigurationStation,
    DataPullLog,
    PullStationProgress,
    MasterStation,
    StationMapping,
)


@admin.register(Station)
class StationAdmin(admin.ModelAdmin):
    list_display = ["station_number", "name", "agency", "state", "is_active"]
    list_filter = ["agency", "state", "is_active"]
    search_fields = ["station_number", "name"]


@admin.register(DischargeObservation)
class DischargeObservationAdmin(admin.ModelAdmin):
    list_display = ["station", "observed_at", "discharge", "unit", "type", "quality_code"]
    list_filter = ["type", "unit", "quality_code"]
    search_fields = ["station__station_number", "station__name"]
    date_hierarchy = "observed_at"


@admin.register(ForecastRun)
class ForecastRunAdmin(admin.ModelAdmin):
    list_display = ["station", "source", "run_date", "rmse"]
    list_filter = ["source"]
    search_fields = ["station__station_number", "station__name"]
    date_hierarchy = "run_date"


@admin.register(PullConfiguration)
class PullConfigurationAdmin(admin.ModelAdmin):
    list_display = ["name", "data_type", "data_strategy", "is_enabled", "last_run_at", "next_run_at"]
    list_filter = ["data_type", "data_strategy", "is_enabled", "schedule_type"]
    search_fields = ["name", "description"]


@admin.register(PullConfigurationStation)
class PullConfigurationStationAdmin(admin.ModelAdmin):
    list_display = ["configuration", "station_number", "station_name", "state"]
    list_filter = ["state"]
    search_fields = ["station_number", "station_name", "configuration__name"]


@admin.register(DataPullLog)
class DataPullLogAdmin(admin.ModelAdmin):
    list_display = ["configuration", "status", "records_processed", "start_time", "end_time"]
    list_filter = ["status"]
    search_fields = ["configuration__name"]
    date_hierarchy = "start_time"


@admin.register(PullStationProgress)
class PullStationProgressAdmin(admin.ModelAdmin):
    list_display = ["configuration", "station_number", "last_successful_pull_date", "updated_at"]
    search_fields = ["station_number", "configuration__name"]


@admin.register(MasterStation)
class MasterStationAdmin(admin.ModelAdmin):
    list_display = ["station_number", "station_name", "agency", "state_code", "huc_code"]
    list_filter = ["agency", "state_code"]
    search_fields = ["station_number", "station_name"]


@admin.register(StationMapping)
class StationMappingAdmin(admin.ModelAdmin):
    list_display = ["source_agency", "source_id", "target_agency", "target_id"]
    list_filter = ["source_agency", "target_agency"]
    search_fields = ["source_id", "target_id"]
