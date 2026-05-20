"""Django models for the analytics application."""

from django.db import models


class ScheduledComputation(models.Model):
    """
    Registry of analytics computations run on a schedule.
    One row per computation type — seeded via data migration.
    The beat schedule is defined in config/celery.py; this model controls
    enable/disable and provides monitoring visibility.
    """

    SCHEDULE_CHOICES = [
        ("hourly",   "Hourly"),
        ("every_6h", "Every 6 Hours"),
        ("daily",    "Daily"),
        ("weekly",   "Weekly"),
    ]

    STATUS_CHOICES = [
        ("success", "Success"),
        ("failed",  "Failed"),
        ("running", "Running"),
        ("never",   "Never Run"),
    ]

    name        = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    task_path   = models.CharField(
        max_length=255,
        unique=True,
        help_text="Dotted Celery task path, e.g. src.analytics.tasks.compute_flow_percentile_bands",
    )
    schedule    = models.CharField(max_length=20, choices=SCHEDULE_CHOICES)
    is_enabled  = models.BooleanField(default=True)

    # Denormalized for quick dashboard/admin display — updated by each task run
    last_run_at     = models.DateTimeField(null=True, blank=True)
    last_run_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="never")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "scheduled_computations"
        ordering = ["name"]

    def __str__(self):
        return self.name


class ComputationLog(models.Model):
    """Execution history for scheduled analytics computations."""

    STATUS_CHOICES = [
        ("running", "Running"),
        ("success", "Success"),
        ("failed",  "Failed"),
    ]

    computation = models.ForeignKey(
        ScheduledComputation,
        on_delete=models.CASCADE,
        related_name="logs",
        db_index=True,
    )

    # Execution
    status           = models.CharField(max_length=20, choices=STATUS_CHOICES)
    celery_task_id   = models.CharField(max_length=255, blank=True, db_index=True)
    started_at       = models.DateTimeField(db_index=True)
    completed_at     = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    # Results
    records_computed = models.IntegerField(null=True, blank=True)
    error_message    = models.TextField(blank=True)

    class Meta:
        db_table = "computation_logs"
        indexes = [
            models.Index(fields=["computation", "started_at"], name="idx_comp_log_comp_started"),
            models.Index(fields=["status"],                    name="idx_comp_log_status"),
        ]
        ordering = ["-started_at"]

    def __str__(self):
        return f"{self.computation.name} – {self.status} – {self.started_at}"


class StationMetadata(models.Model):
    """
    Precomputed summary statistics for a monitoring station.
    Covers record length, completeness, and flow percentile bands.
    """

    station = models.OneToOneField(
        'streamflow.Station',
        on_delete=models.CASCADE,
        related_name='metadata',
    )

    # Record extent
    last_observation_date  = models.DateField(null=True, blank=True, db_index=True)
    record_start_date      = models.DateField(null=True, blank=True)
    record_end_date        = models.DateField(null=True, blank=True)
    years_on_record        = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    daily_observation_count = models.IntegerField(null=True, blank=True)
    record_completeness_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    # Flow statistics (cfs)
    mean_annual_flow_cfs = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    q10_cfs              = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    q25_cfs              = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    q50_cfs              = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    q75_cfs              = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    q90_cfs              = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    computed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'station_metadata'

    def __str__(self):
        return f"Metadata: {self.station.station_number}"


class FloodThreshold(models.Model):
    """
    NOAA NWPS flood stage and flow thresholds for a monitoring station.
    Populated from the NOAA API or entered manually.
    """

    SOURCE_CHOICES = [
        ('noaa_api', 'NOAA API'),
        ('manual',   'Manual'),
    ]

    station = models.OneToOneField(
        'streamflow.Station',
        on_delete=models.CASCADE,
        related_name='flood_threshold',
    )

    noaa_lid = models.CharField(max_length=50, blank=True)

    # Stage (ft) and flow (cfs) thresholds — all nullable; not every station has all levels
    action_stage_ft   = models.DecimalField(max_digits=8,  decimal_places=2, null=True, blank=True)
    action_flow_cfs   = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    minor_stage_ft    = models.DecimalField(max_digits=8,  decimal_places=2, null=True, blank=True)
    minor_flow_cfs    = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    moderate_stage_ft = models.DecimalField(max_digits=8,  decimal_places=2, null=True, blank=True)
    moderate_flow_cfs = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    major_stage_ft    = models.DecimalField(max_digits=8,  decimal_places=2, null=True, blank=True)
    major_flow_cfs    = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    record_stage_ft   = models.DecimalField(max_digits=8,  decimal_places=2, null=True, blank=True)
    record_flow_cfs   = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    source       = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='noaa_api')
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'flood_thresholds'

    def __str__(self):
        return f"FloodThreshold: {self.station.station_number} ({self.noaa_lid})"


class StatisticsConfiguration(models.Model):
    """
    Configures a scheduled statistics computation run — what to compute,
    which stations, and on what schedule.
    """

    COMPUTATION_TYPE_CHOICES = [
        ('station_metadata',  'Station Metadata & Statistics'),
        ('flood_thresholds',  'Flood Thresholds (NOAA NWPS)'),
        ('percentile_backfill', 'Percentile Band Backfill'),
    ]

    AGENCY_FILTER_CHOICES = [
        ('ALL',      'All Agencies'),
        ('USGS',     'USGS'),
        ('EC',       'Environment Canada'),
        ('NOAA_RFC', 'NOAA RFC'),
    ]

    SCHEDULE_TYPE_CHOICES = [
        ('annual',  'Annual'),
        ('monthly', 'Monthly'),
        ('weekly',  'Weekly'),
        ('daily',   'Daily'),
        ('custom',  'Custom Cron'),
    ]

    name             = models.CharField(max_length=200, unique=True)
    description      = models.TextField(blank=True)
    computation_type = models.CharField(max_length=30, choices=COMPUTATION_TYPE_CHOICES)
    agency_filter    = models.CharField(max_length=20, choices=AGENCY_FILTER_CHOICES, default='ALL')

    # Schedule
    schedule_type    = models.CharField(max_length=20, choices=SCHEDULE_TYPE_CHOICES, default='annual')
    annual_run_month = models.IntegerField(default=10)
    annual_run_day   = models.IntegerField(default=1)
    schedule_value   = models.CharField(max_length=100, blank=True)

    is_enabled  = models.BooleanField(default=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    next_run_at = models.DateTimeField(null=True, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'statistics_configurations'
        ordering = ['name']

    def get_station_queryset(self):
        """
        Return the Station queryset this configuration applies to.
        Explicit station overrides take precedence; otherwise agency_filter is used.
        """
        from apps.streamflow.models import Station
        explicit_ids = self.stations.values_list('station_id', flat=True)
        if explicit_ids.exists():
            return Station.objects.filter(id__in=explicit_ids)
        if self.agency_filter == 'ALL':
            return Station.objects.all()
        return Station.objects.filter(agency=self.agency_filter)

    def __str__(self):
        return self.name


class StatisticsConfigurationStation(models.Model):
    """
    Explicit station override for a StatisticsConfiguration.
    When any rows exist for a configuration, only those stations are processed.
    """

    configuration = models.ForeignKey(
        StatisticsConfiguration,
        on_delete=models.CASCADE,
        related_name='stations',
    )
    station = models.ForeignKey(
        'streamflow.Station',
        on_delete=models.CASCADE,
    )

    class Meta:
        db_table = 'statistics_configuration_stations'
        unique_together = [('configuration', 'station')]

    def __str__(self):
        return f"{self.configuration.name} – {self.station.station_number}"


class StatisticsComputationLog(models.Model):
    """Execution history for statistics computation runs."""

    STATUS_CHOICES = [
        ('running', 'Running'),
        ('success', 'Success'),
        ('failed',  'Failed'),
        ('partial', 'Partial Success'),
    ]

    configuration = models.ForeignKey(
        StatisticsConfiguration,
        on_delete=models.CASCADE,
        related_name='logs',
        db_index=True,
    )

    status         = models.CharField(max_length=20, choices=STATUS_CHOICES)
    celery_task_id = models.CharField(max_length=255, blank=True, db_index=True)
    started_at     = models.DateTimeField(db_index=True)
    completed_at   = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    stations_processed = models.IntegerField(null=True, blank=True)
    records_computed   = models.IntegerField(null=True, blank=True)
    error_message      = models.TextField(blank=True)

    class Meta:
        db_table = 'statistics_computation_logs'
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['configuration', 'started_at'], name='idx_stat_log_config_started'),
            models.Index(fields=['status'],                      name='idx_stat_log_status'),
        ]

    def __str__(self):
        return f"{self.configuration.name} – {self.status} – {self.started_at}"
