"""Django models for the streamflow application."""

from django.db import models
from django.utils import timezone


class Station(models.Model):
    """Stores station metadata."""

    AGENCY_CHOICES = [
        ("USGS", "USGS"),
        ("EC", "Environment Canada"),
    ]

    station_number = models.CharField(max_length=50, unique=True, db_index=True)
    name = models.TextField()
    agency = models.CharField(max_length=50, choices=AGENCY_CHOICES)

    # Geographic Information
    latitude = models.DecimalField(max_digits=10, decimal_places=8, null=True, blank=True)
    longitude = models.DecimalField(max_digits=11, decimal_places=8, null=True, blank=True)
    timezone = models.CharField(max_length=50, default="UTC")

    # Hydrological Attributes
    huc_code = models.CharField(max_length=20, blank=True, db_index=True)
    basin = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=50, blank=True, db_index=True)
    catchment_area = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True, help_text="sq km")

    # Record Statistics
    years_of_record = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    record_start_date = models.DateTimeField(null=True, blank=True)
    record_end_date = models.DateTimeField(null=True, blank=True)

    # Status
    is_active = models.BooleanField(default=True)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "stations"
        ordering = ["station_number"]

    def __str__(self):
        return f"{self.station_number} - {self.name}"


class DischargeObservation(models.Model):
    """Stores time series discharge observations."""

    TYPE_CHOICES = [
        ("realtime_15min", "Real-time 15 min"),
        ("daily_mean", "Daily Mean"),
    ]

    UNIT_CHOICES = [
        ("cfs", "Cubic Feet per Second"),
        ("cms", "Cubic Meters per Second"),
    ]

    QUALITY_CHOICES = [
        ("P", "Provisional"),
        ("A", "Approved"),
    ]

    station = models.ForeignKey(
        Station,
        on_delete=models.CASCADE,
        related_name="discharge_observations",
        db_index=True,
    )
    observed_at = models.DateTimeField(db_index=True)
    discharge = models.DecimalField(max_digits=20, decimal_places=4)
    unit = models.CharField(max_length=10, choices=UNIT_CHOICES)
    type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    quality_code = models.CharField(max_length=10, choices=QUALITY_CHOICES, blank=True)

    class Meta:
        db_table = "discharge_observations"
        constraints = [
            models.UniqueConstraint(
                fields=["station", "observed_at", "type"],
                name="unique_observation_idx",
            )
        ]
        indexes = [
            models.Index(fields=["station", "observed_at", "type"], name="idx_station_observed_type"),
        ]
        ordering = ["-observed_at"]

    def __str__(self):
        return f"{self.station.station_number} - {self.observed_at}"


class ForecastRun(models.Model):
    """Stores forecast data."""

    SOURCE_CHOICES = [
        ("NOAA_RFC", "NOAA River Forecast Center"),
    ]

    station = models.ForeignKey(
        Station,
        on_delete=models.CASCADE,
        related_name="forecast_runs",
        db_index=True,
    )
    source = models.CharField(max_length=50, choices=SOURCE_CHOICES)
    run_date = models.DateTimeField(db_index=True)
    data = models.JSONField(help_text="Array of { date: string, value: number }")
    rmse = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True, help_text="Accuracy metric")

    class Meta:
        db_table = "forecast_runs"
        indexes = [
            models.Index(fields=["station", "run_date"], name="idx_station_run_date"),
        ]
        ordering = ["-run_date"]

    def __str__(self):
        return f"{self.station.station_number} - {self.source} - {self.run_date}"


class PullConfiguration(models.Model):
    """Stores data pull job configurations."""

    DATA_TYPE_CHOICES = [
        ("realtime_15min", "Real-time 15 min"),
        ("daily_mean", "Daily Mean"),
    ]

    STRATEGY_CHOICES = [
        ("append", "Append"),
        ("overwrite", "Overwrite"),
    ]

    SCHEDULE_TYPE_CHOICES = [
        ("hourly", "Hourly"),
        ("daily", "Daily"),
        ("weekly", "Weekly"),
        ("custom", "Custom Cron"),
    ]

    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    data_type = models.CharField(max_length=20, choices=DATA_TYPE_CHOICES)
    data_strategy = models.CharField(max_length=20, choices=STRATEGY_CHOICES)
    pull_start_date = models.DateTimeField()
    is_enabled = models.BooleanField(default=True)

    # Schedule (cron-like)
    schedule_type = models.CharField(max_length=20, choices=SCHEDULE_TYPE_CHOICES)
    schedule_value = models.CharField(max_length=50, blank=True, help_text="e.g., '0 */6 * * *' for cron")

    last_run_at = models.DateTimeField(null=True, blank=True)
    next_run_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "pull_configurations"
        ordering = ["-created_at"]

    def __str__(self):
        return self.name


class PullConfigurationStation(models.Model):
    """Junction table linking configurations to stations."""

    configuration = models.ForeignKey(
        PullConfiguration,
        on_delete=models.CASCADE,
        related_name="configuration_stations",
        db_index=True,
    )
    station_number = models.CharField(max_length=50)
    station_name = models.TextField(blank=True)
    huc_code = models.CharField(max_length=20, blank=True)
    state = models.CharField(max_length=50, blank=True)

    class Meta:
        db_table = "pull_configuration_stations"

    def __str__(self):
        return f"{self.configuration.name} - {self.station_number}"


class DataPullLog(models.Model):
    """Tracks data pull job execution history."""

    STATUS_CHOICES = [
        ("running", "Running"),
        ("success", "Success"),
        ("failed", "Failed"),
    ]

    configuration = models.ForeignKey(
        PullConfiguration,
        on_delete=models.CASCADE,
        related_name="logs",
        db_index=True,
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    records_processed = models.IntegerField(null=True, blank=True)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)

    class Meta:
        db_table = "data_pull_logs"
        indexes = [
            models.Index(fields=["configuration", "start_time"], name="idx_config_start_time"),
        ]
        ordering = ["-start_time"]

    def __str__(self):
        return f"{self.configuration.name} - {self.status} - {self.start_time}"


class PullStationProgress(models.Model):
    """Tracks the progress of each station within a configuration (Smart Append Logic)."""

    configuration = models.ForeignKey(
        PullConfiguration,
        on_delete=models.CASCADE,
        related_name="progress_records",
        db_index=True,
    )
    station_number = models.CharField(max_length=50)

    # CRUCIAL FIELD FOR SMART LOGIC
    last_successful_pull_date = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "pull_station_progress"
        constraints = [
            models.UniqueConstraint(
                fields=["configuration", "station_number"],
                name="unique_progress_idx",
            )
        ]

    def __str__(self):
        return f"{self.configuration.name} - {self.station_number}"


class MasterStation(models.Model):
    """Master station list (from CSV import)."""

    AGENCY_CHOICES = [
        ("USGS", "USGS"),
        ("EC", "Environment Canada"),
    ]

    station_number = models.CharField(max_length=50, unique=True, db_index=True)
    station_name = models.TextField()
    latitude = models.DecimalField(max_digits=10, decimal_places=8, null=True, blank=True)
    longitude = models.DecimalField(max_digits=11, decimal_places=8, null=True, blank=True)
    state_code = models.CharField(max_length=10, blank=True, db_index=True)
    huc_code = models.CharField(max_length=20, blank=True, db_index=True)
    altitude_ft = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    drainage_area_sqmi = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    agency = models.CharField(max_length=20, choices=AGENCY_CHOICES, default="USGS")

    class Meta:
        db_table = "master_stations"
        ordering = ["station_number"]

    def __str__(self):
        return f"{self.station_number} - {self.station_name}"


class StationMapping(models.Model):
    """Stores mappings between different network IDs."""

    source_agency = models.CharField(max_length=50)
    source_id = models.CharField(max_length=50, db_index=True)
    target_agency = models.CharField(max_length=50)
    target_id = models.CharField(max_length=50)

    class Meta:
        db_table = "station_mappings"
        constraints = [
            models.UniqueConstraint(
                fields=["source_agency", "source_id", "target_agency"],
                name="unique_mapping_idx",
            )
        ]
        indexes = [
            models.Index(fields=["source_agency", "source_id"], name="idx_source_lookup"),
        ]

    def __str__(self):
        return f"{self.source_agency}:{self.source_id} -> {self.target_agency}:{self.target_id}"
