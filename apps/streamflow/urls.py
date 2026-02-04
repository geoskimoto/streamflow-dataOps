"""URL configuration for streamflow app."""

from django.urls import path
from . import views

app_name = 'streamflow'

urlpatterns = [
    # Dashboard
    path('', views.dashboard, name='dashboard'),
    
    # Pull Configurations
    path('configurations/', views.PullConfigurationListView.as_view(), name='configuration_list'),
    path('configurations/new/', views.PullConfigurationCreateView.as_view(), name='configuration_create'),
    path('configurations/<int:pk>/', views.PullConfigurationDetailView.as_view(), name='configuration_detail'),
    path('configurations/<int:pk>/edit/', views.PullConfigurationUpdateView.as_view(), name='configuration_update'),
    path('configurations/<int:pk>/delete/', views.PullConfigurationDeleteView.as_view(), name='configuration_delete'),
    path('configurations/<int:pk>/trigger/', views.trigger_pull, name='trigger_pull'),
    path('configurations/<int:pk>/toggle/', views.toggle_configuration, name='toggle_configuration'),
    
    # Stations
    path('stations/', views.StationListView.as_view(), name='station_list'),
    path('stations/all/', views.MasterStationListView.as_view(), name='master_station_list'),
    path('stations/new/', views.StationCreateView.as_view(), name='station_create'),
    path('stations/import/', views.station_import, name='station_import'),
    path('stations/sync/', views.sync_master_stations, name='station_sync'),
    path('stations/export/', views.station_export_csv, name='station_export_csv'),
    path('stations/<str:station_number>/', views.StationDetailView.as_view(), name='station_detail'),
    path('stations/<str:station_number>/edit/', views.StationUpdateView.as_view(), name='station_update'),
    path('stations/<str:station_number>/toggle/', views.toggle_station_status, name='toggle_station_status'),
    path('stations/search/', views.station_search, name='station_search'),
    path('stations/search/ajax/', views.station_search_ajax, name='station_search_ajax'),
    path('configurations/<int:pk>/stations/add/', views.add_stations_to_config, name='add_stations'),
    path('configurations/<int:pk>/stations/<int:station_id>/remove/', views.remove_station_from_config, name='remove_station'),
    path('configurations/<int:pk>/station/add/', views.add_station_to_config, name='add_station_to_config'),
    
    # Logs
    path('logs/', views.DataPullLogListView.as_view(), name='log_list'),
    path('logs/<int:pk>/', views.log_detail, name='log_detail'),
    
    # Gridded Data (Raster/GEE)
    path('gridded-data/', views.gridded_data_list, name='gridded_data_list'),
    path('gridded-data/<int:layer_id>/', views.gridded_data_detail, name='gridded_data_detail'),
    
    # Gridded Configurations
    path('gridded-configurations/', views.raster_config_list, name='raster_config_list'),
    path('gridded-configurations/new/', views.raster_config_create, name='raster_config_create'),
    path('gridded-configurations/<int:config_id>/', views.raster_config_detail, name='raster_config_detail'),
    path('gridded-configurations/<int:config_id>/edit/', views.raster_config_edit, name='raster_config_edit'),
    path('gridded-configurations/<int:config_id>/delete/', views.raster_config_delete, name='raster_config_delete'),
    path('gridded-configurations/<int:config_id>/toggle/', views.toggle_raster_configuration, name='toggle_raster_configuration'),
    path('gridded-configurations/<int:config_id>/trigger/', views.trigger_raster_pull, name='trigger_raster_pull'),
    
    # System Diagnostics
    path('diagnostics/', views.system_diagnostics, name='system_diagnostics'),
    
    # Gridded Data Logs
    path('gridded-logs/', views.RasterPullLogListView.as_view(), name='raster_log_list'),
]
