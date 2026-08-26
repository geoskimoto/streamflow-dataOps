"""Django models for the streamflow application."""

from django.db import models
from django.utils import timezone
from django.contrib.gis.db import models as gis_models


class Station(models.Model):
    """Stores station metadata."""

    AGENCY_CHOICES = [
        ("USGS", "USGS"),
        ("EC", "Environment Canada"),
        ("NOAA_RFC", "NOAA River Forecast Center"),
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

    # Historical Data Population Tracking
    historical_data_populated_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Timestamp when complete historical data was populated'
    )
    historical_record_count = models.IntegerField(
        default=0,
        help_text='Count of historical records populated'
    )

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
        ("nwrfc_web", "NWRFC Website"),
    ]

    FORECAST_TYPE_CHOICES = [
        ("short", "Short-range (3-7 days)"),
        ("medium", "Medium-range (up to 10 days)"),
        ("long", "Long-range (up to 30 days)"),
    ]

    station = models.ForeignKey(
        Station,
        on_delete=models.CASCADE,
        related_name="forecast_runs",
        db_index=True,
    )
    source = models.CharField(max_length=50, choices=SOURCE_CHOICES)
    run_date = models.DateTimeField(db_index=True, help_text="When forecast was issued")
    forecast_type = models.CharField(
        max_length=20,
        choices=FORECAST_TYPE_CHOICES,
        default="short",
        help_text="Forecast duration type"
    )
    is_forecast = models.BooleanField(
        default=True,
        help_text="True = forecast rows; False = observed rows scraped from same page",
    )
    data = models.JSONField(help_text="Array of { date: string, value: number }")
    rmse = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True, help_text="Accuracy metric")

    class Meta:
        db_table = "forecast_runs"
        constraints = [
            models.UniqueConstraint(
                fields=["station", "source", "run_date", "forecast_type", "is_forecast"],
                name="unique_forecast_run",
            )
        ]
        indexes = [
            models.Index(fields=["station", "run_date"], name="idx_station_run_date"),
            models.Index(fields=["station", "run_date", "forecast_type"], name="idx_station_run_date_type"),
        ]
        ordering = ["-run_date"]

    def __str__(self):
        return f"{self.station.station_number} - {self.source} - {self.forecast_type} - {self.run_date}"


class PullConfiguration(models.Model):
    """Stores data pull job configurations."""

    DATA_SOURCE_CHOICES = [
        ("USGS", "USGS NWIS"),
        ("EC", "Environment Canada"),
        ("NOAA", "NOAA National Water Model"),
        ("NOAA_RFC", "NOAA River Forecast Center"),
        ("nwrfc_web", "NWRFC Website (scraper)"),
    ]

    DATA_TYPE_CHOICES = [
        ("realtime_15min", "Real-time 15 min"),
        ("daily_mean", "Daily Mean"),
        ("forecast", "Forecast"),
        ("ec_realtime_daily", "EC Wateroffice Daily Mean"),
    ]

    FORECAST_TYPE_CHOICES = [
        ("short", "Short-range (3-7 days)"),
        ("medium", "Medium-range (up to 10 days)"),
        ("long", "Long-range (up to 30 days)"),
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
    data_source = models.CharField(max_length=20, choices=DATA_SOURCE_CHOICES, default="USGS")
    data_type = models.CharField(max_length=20, choices=DATA_TYPE_CHOICES)
    forecast_type = models.CharField(
        max_length=20,
        choices=FORECAST_TYPE_CHOICES,
        default="short",
        blank=True,
        help_text="Forecast duration (only applies to forecast data type)"
    )
    data_strategy = models.CharField(max_length=20, choices=STRATEGY_CHOICES)
    pull_start_date = models.DateTimeField()
    is_enabled = models.BooleanField(default=True)
    skip_inactive_stations = models.BooleanField(
        default=False,
        help_text=(
            "Only pull stations whose Station record is marked active. Skips "
            "discontinued gauges instead of requesting them every run. Leave "
            "off unless is_active is actually maintained for this data "
            "source — NOAA_RFC stations are all flagged inactive despite "
            "reporting, so enabling this would empty a forecast pull."
        ),
    )

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
        # Some stations failed, but few enough that the run is still healthy —
        # large configs routinely lose a handful to transient upstream errors
        # that self-heal on the next run. See tasks.classify_pull_status.
        ("partial", "Partial"),
        ("failed", "Failed"),
    ]

    # Statuses that mean the run did its job. Success-rate math should use
    # this rather than hardcoding "success" in each view.
    HEALTHY_STATUSES = ("success", "partial")

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
        ("NOAA_RFC", "NOAA River Forecast Center"),
    ]

    station_number = models.CharField(max_length=50, unique=True, db_index=True)
    station_name = models.TextField()
    latitude = models.DecimalField(max_digits=10, decimal_places=8, null=True, blank=True)
    longitude = models.DecimalField(max_digits=11, decimal_places=8, null=True, blank=True)
    state_code = models.CharField(max_length=10, blank=True, db_index=True)
    huc_code = models.CharField(max_length=20, blank=True, db_index=True)
    rfc_code = models.CharField(max_length=20, blank=True, db_index=True, help_text="River Forecast Center code (e.g., NWRFC, CNRFC)")
    noaa_lid = models.CharField(max_length=50, unique=True, null=True, blank=True, db_index=True, help_text="NOAA Location ID")
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


# ==========================================
# RASTER DATA MODELS
# ==========================================


class RasterDataset(models.Model):
    """Stores metadata about available raster datasets from various sources."""

    DATA_SOURCE_CHOICES = [
        ('earthdata', 'NASA EarthData'),
        ('nomads', 'NOAA NOMADS'),
        ('nwm_s3', 'NOAA NWM S3'),
        ('gee', 'Google Earth Engine (deprecated)'),
    ]

    name = models.CharField(
        max_length=100,
        unique=True,
        db_index=True,
        help_text="Human-readable dataset name (e.g., 'RTMA', 'SMAP SPL4')"
    )
    data_source = models.CharField(
        max_length=20,
        choices=DATA_SOURCE_CHOICES,
        default='earthdata',
        help_text="Data source provider"
    )
    collection_id = models.CharField(
        max_length=255,
        help_text="Collection/dataset ID (GEE: 'NOAA/NWS/RTMA', EarthData: 'SPL4SMGP_008', NOMADS: 'rtma2p5')"
    )
    daac = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="NASA DAAC archive (e.g., NSIDC_CPRD, GES_DISC, LPDAAC_ECS) - EarthData only"
    )
    file_format = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        help_text="Native file format (HDF5, NetCDF4, GRIB2, GeoTIFF)"
    )
    access_url_pattern = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        help_text="URL pattern for direct access (NOMADS) or base URL"
    )
    description = models.TextField(blank=True)
    resolution_m = models.IntegerField(help_text="Native resolution in meters")
    temporal_resolution = models.CharField(
        max_length=50,
        help_text="e.g., 'hourly', 'daily', '3-hourly'"
    )
    update_frequency = models.CharField(
        max_length=50,
        help_text="How often new data is available"
    )
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "raster_datasets"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.data_source}: {self.collection_id})"


class RasterVariable(models.Model):
    """Stores metadata about variables available in raster datasets."""

    dataset = models.ForeignKey(
        RasterDataset,
        on_delete=models.CASCADE,
        related_name="variables"
    )
    name = models.CharField(max_length=100, help_text="Variable name (e.g., 'temperature', 'precipitation')")
    gee_band_name = models.CharField(max_length=100, help_text="Band name in GEE (e.g., 'TMP', 'APCP')")
    unit = models.CharField(max_length=50, help_text="Measurement unit (e.g., 'Kelvin', 'mm', 'm/s')")
    description = models.TextField(blank=True)
    
    # Value ranges for validation
    min_valid_value = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    max_valid_value = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "raster_variables"
        constraints = [
            models.UniqueConstraint(
                fields=["dataset", "name"],
                name="unique_dataset_variable"
            )
        ]
        ordering = ["dataset", "name"]

    def __str__(self):
        return f"{self.dataset.name} - {self.name}"


class SpatialExtent(models.Model):
    """Stores spatial extents for raster data pulls."""

    name = models.CharField(max_length=100, unique=True, help_text="e.g., 'HUC_17', 'Western_US'")
    description = models.TextField(blank=True)
    
    # Bounding box
    min_lon = models.DecimalField(max_digits=10, decimal_places=6)
    min_lat = models.DecimalField(max_digits=10, decimal_places=6)
    max_lon = models.DecimalField(max_digits=10, decimal_places=6)
    max_lat = models.DecimalField(max_digits=10, decimal_places=6)
    
    # Polygon geometry (optional, for precise boundaries)
    geometry = gis_models.PolygonField(srid=4326, null=True, blank=True, help_text="Precise boundary polygon")
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "spatial_extents"
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def bbox(self):
        """Returns bounding box as [min_lon, min_lat, max_lon, max_lat]."""
        return [float(self.min_lon), float(self.min_lat), float(self.max_lon), float(self.max_lat)]


class RasterLayer(models.Model):
    """Stores metadata for individual raster files."""

    variable = models.ForeignKey(
        RasterVariable,
        on_delete=models.CASCADE,
        related_name="layers"
    )
    extent = models.ForeignKey(
        SpatialExtent,
        on_delete=models.CASCADE,
        related_name="layers"
    )
    
    # Temporal information
    timestamp = models.DateTimeField(db_index=True, help_text="Data timestamp (UTC)")
    date = models.DateField(db_index=True, help_text="Date component for easier querying")
    
    # File storage
    file_path = models.CharField(max_length=500, help_text="Relative path to raster file")
    file_size_bytes = models.BigIntegerField(null=True, blank=True)
    format = models.CharField(max_length=20, default="GeoTIFF")
    compression = models.CharField(max_length=20, default="LZW")
    
    # Raster properties
    resolution_m = models.IntegerField(help_text="Actual resolution in meters")
    width_pixels = models.IntegerField()
    height_pixels = models.IntegerField()
    crs = models.CharField(max_length=50, default="EPSG:4326")
    
    # Data statistics
    min_value = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    max_value = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    mean_value = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    std_dev = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    no_data_value = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    
    # Metadata
    thumbnail_path = models.CharField(max_length=500, blank=True, null=True, help_text="Path to thumbnail image")
    checksum_md5 = models.CharField(max_length=32, blank=True, help_text="File integrity checksum")
    
    # Status tracking
    is_valid = models.BooleanField(default=True, help_text="Passed validation checks")
    validation_errors = models.JSONField(null=True, blank=True, help_text="Validation error messages")
    processing_time_seconds = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "raster_layers"
        constraints = [
            models.UniqueConstraint(
                fields=["variable", "extent", "timestamp"],
                name="unique_raster_layer"
            )
        ]
        indexes = [
            models.Index(fields=["variable", "extent", "date"], name="idx_raster_var_ext_date"),
            models.Index(fields=["variable", "timestamp"], name="idx_raster_var_time"),
            models.Index(fields=["is_valid"], name="idx_raster_valid"),
        ]
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.variable.name} - {self.extent.name} - {self.timestamp}"


class RasterPullConfiguration(models.Model):
    """Stores configuration for automated raster data pulls."""

    name = models.CharField(max_length=200, unique=True)
    description = models.TextField(blank=True)
    
    # What to pull
    dataset = models.ForeignKey(
        RasterDataset,
        on_delete=models.CASCADE,
        related_name="pull_configs"
    )
    variables = models.ManyToManyField(
        RasterVariable,
        related_name="pull_configs"
    )
    extents = models.ManyToManyField(
        SpatialExtent,
        related_name="pull_configs"
    )
    
    # Pull schedule
    schedule_enabled = models.BooleanField(default=True)
    schedule_cron = models.CharField(max_length=100, blank=True, help_text="Celery cron expression")
    pull_frequency_hours = models.IntegerField(default=8, help_text="Hours between pulls")
    
    # Time window
    lookback_days = models.IntegerField(default=7, help_text="Days of historical data to check")
    max_age_hours = models.IntegerField(default=24, help_text="Maximum age of data to consider 'current'")
    
    # Processing options
    resampling_method = models.CharField(max_length=50, default="bilinear", help_text="e.g., 'nearest', 'bilinear', 'cubic'")
    target_resolution_m = models.IntegerField(null=True, blank=True, help_text="Target resolution for resampling (null = native)")
    apply_compression = models.BooleanField(default=True)
    generate_thumbnails = models.BooleanField(default=True)
    
    # Validation
    validate_on_pull = models.BooleanField(default=True)
    calculate_statistics = models.BooleanField(default=True)
    
    # Status
    is_active = models.BooleanField(default=True)
    last_successful_pull = models.DateTimeField(null=True, blank=True)
    last_pull_attempt = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "raster_pull_configurations"
        ordering = ["name"]

    def __str__(self):
        return self.name


class RasterPullLog(models.Model):
    """Stores execution history for raster data pulls."""

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("running", "Running"),
        ("success", "Success"),
        ("partial", "Partial Success"),
        ("failed", "Failed"),
    ]

    configuration = models.ForeignKey(
        RasterPullConfiguration,
        on_delete=models.CASCADE,
        related_name="pull_logs",
        null=True,
        blank=True
    )
    
    # Execution details
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    started_at = models.DateTimeField(auto_now_add=True, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    
    # Results
    layers_attempted = models.IntegerField(default=0)
    layers_successful = models.IntegerField(default=0)
    layers_failed = models.IntegerField(default=0)
    layers_skipped = models.IntegerField(default=0, help_text="Already existed")
    
    total_size_bytes = models.BigIntegerField(default=0)
    
    # Error tracking
    error_message = models.TextField(blank=True)
    error_traceback = models.TextField(blank=True)
    warnings = models.JSONField(null=True, blank=True, help_text="List of warning messages")
    
    # Celery task info
    celery_task_id = models.CharField(max_length=255, blank=True, db_index=True)
    
    class Meta:
        db_table = "raster_pull_logs"
        indexes = [
            models.Index(fields=["-started_at"], name="idx_pull_log_started"),
            models.Index(fields=["status"], name="idx_pull_log_status"),
            models.Index(fields=["configuration", "-started_at"], name="idx_pull_log_config"),
        ]
        ordering = ["-started_at"]

    def __str__(self):
        config_name = self.configuration.name if self.configuration else "Manual"
        return f"{config_name} - {self.started_at} ({self.status})"

    def calculate_duration(self):
        """Calculate and update duration if completed."""
        if self.completed_at and self.started_at:
            delta = self.completed_at - self.started_at
            self.duration_seconds = delta.total_seconds()
            self.save(update_fields=["duration_seconds"])

BAND_CHOICES = [
    ("p0_4",    "Very Low (0–4th percentile)"),
    ("p5_10",   "Low (5th–10th percentile)"),
    ("p11_25",  "Below Normal (11th–25th percentile)"),
    ("p26_50",  "Normal (26th–50th percentile)"),
    ("p51_75",  "Above Normal (51st–75th percentile)"),
    ("p76_85",  "High (76th–85th percentile)"),
    ("p86_90",  "Very High (86th–90th percentile)"),
    ("p91_95",  "Extreme (91st–95th percentile)"),
    ("p96_98",  "Severe (96th–98th percentile)"),
    ("p99_100", "Exceptional (>98th percentile)"),
]


class DailyFlowPercentile(models.Model):
    """
    Precomputed exceedance percentile band for a station on a specific date.

    One row per (station, date). The percentile rank compares that day's
    discharge against the station's full period of record (all daily_mean
    observations regardless of year). Population: Historical backfill via
    `run_percentile_backfill_task` and daily updates via `run_daily_flow_percentiles_task`
    triggered by StatisticsConfiguration dispatcher.
    """

    station = models.ForeignKey(
        Station,
        on_delete=models.CASCADE,
        related_name="daily_percentiles",
        db_index=True,
    )
    date = models.DateField(db_index=True, help_text="Observation date")

    discharge               = models.DecimalField(max_digits=20, decimal_places=4)
    percentile_rank         = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        help_text="0–100; computed against full period of record",
    )
    band                    = models.CharField(max_length=10, choices=BAND_CHOICES)
    historical_record_count = models.IntegerField(
        help_text="Total daily_mean records used in the percentile computation"
    )
    computed_at             = models.DateTimeField(help_text="When this row was computed")

    class Meta:
        db_table = "daily_flow_percentiles"
        constraints = [
            models.UniqueConstraint(
                fields=["station", "date"],
                name="unique_daily_flow_percentile",
            )
        ]
        indexes = [
            models.Index(fields=["date"],        name="idx_daily_pct_date"),
            models.Index(fields=["band", "date"], name="idx_daily_pct_band_date"),
        ]
        ordering = ["-date"]

    def __str__(self):
        return f"{self.station.station_number} – {self.date} – {self.band} ({self.percentile_rank:.1f}th pct)"


class ForecastPercentile(models.Model):
    """
    Precomputed exceedance percentile band for a forecast value at a station on a future date.

    One row per (station, target_date, source). Upserted each time the
    `run_forecast_percentiles_task` is triggered by StatisticsConfiguration dispatcher —
    always reflects the most recent ForecastRun for that source.
    """

    station = models.ForeignKey(
        Station,
        on_delete=models.CASCADE,
        related_name="forecast_percentiles",
        db_index=True,
    )
    target_date        = models.DateField(db_index=True, help_text="Forecasted date")
    source             = models.CharField(max_length=50, help_text="Forecast source label, e.g. NWRFC")
    forecast_run_date  = models.DateTimeField(help_text="Issuance datetime of the ForecastRun used")
    forecast_discharge = models.DecimalField(max_digits=20, decimal_places=4)
    percentile_rank    = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        help_text="0–100; compared against station's full period-of-record daily_mean observations",
    )
    band                    = models.CharField(max_length=10, choices=BAND_CHOICES)
    historical_record_count = models.IntegerField(
        help_text="Total daily_mean records used in the percentile computation"
    )
    computed_at = models.DateTimeField(help_text="When this row was computed")

    class Meta:
        db_table = "forecast_percentiles"
        constraints = [
            models.UniqueConstraint(
                fields=["station", "target_date", "source"],
                name="unique_forecast_percentile",
            )
        ]
        indexes = [
            models.Index(fields=["station", "target_date"], name="idx_fcst_pct_station_date"),
            models.Index(fields=["source", "target_date"],  name="idx_fcst_pct_source_date"),
        ]
        ordering = ["target_date"]

    def __str__(self):
        return f"{self.station.station_number} – {self.target_date} – {self.source} – {self.band}"


class BasinForcing(models.Model):
    """Daily basin-averaged meteorological forcings for EA-LSTM inference."""
    SOURCE_CHOICES = [
        ("nwm", "NWM Medium-Range"),
        ("daymet", "Daymet CAMELS"),
    ]

    station = models.ForeignKey(
        Station,
        on_delete=models.CASCADE,
        related_name="basin_forcings",
        db_index=True,
    )
    date = models.DateField(db_index=True)

    prcp_mm_day  = models.FloatField(help_text="Precipitation mm/day")
    tmax_c       = models.FloatField(help_text="Maximum air temperature °C")
    tmin_c       = models.FloatField(help_text="Minimum air temperature °C")
    srad_w_m2    = models.FloatField(help_text="Downward shortwave radiation W/m²")
    vp_pa        = models.FloatField(help_text="Vapor pressure Pa")
    dayl_s       = models.FloatField(help_text="Day length seconds/day")

    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default="nwm")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "basin_forcings"
        constraints = [
            models.UniqueConstraint(
                fields=["station", "date", "source"],
                name="unique_basin_forcing",
            )
        ]
        ordering = ["station", "date"]

    def __str__(self) -> str:
        return f"{self.station.station_number} {self.date} ({self.source})"
